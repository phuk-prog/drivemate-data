"""Lossless app-readable packs of exported OSM features, without inferring facts.

Preserves complete GeoJSON features from osmium export. Raw PBF snapshots
remain authoritative for nodes/relations not represented by that export.
Bounding-box assignment is conservative: features may occur in several packs.
"""
import argparse
from collections import OrderedDict
from contextlib import nullcontext
import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import sys

MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_FEATURE_CELLS = 256
MAX_PACKS = 4096
MAX_RECORDS_PER_PACK = 5_000_000
OPEN_SPOOLS = 32
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"
MANIFEST = "feature-packs-manifest.json"


def pack_name(cell):
    return "feature-packs-global.jsonl.gz" if cell is None else f"feature-packs-{cell[0]}_{cell[1]}.jsonl.gz"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _positions(geometry):
    if not isinstance(geometry, dict):
        raise ValueError("Missing geometry")
    kind = geometry.get("type")
    if kind == "GeometryCollection":
        children = geometry.get("geometries")
        if not isinstance(children, list) or not children:
            raise ValueError("Empty geometry collection")
        for child in children:
            yield from _positions(child)
        return
    depths = {"Point": 0, "MultiPoint": 1, "LineString": 1,
              "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}
    if kind not in depths:
        raise ValueError("Unsupported geometry type")

    def walk(value, depth):
        if not isinstance(value, list) or not value:
            raise ValueError("Empty or malformed coordinates")
        if depth == 0:
            if (len(value) < 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
                    or not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90):
                raise ValueError("Nonfinite or out-of-range position")
            yield value
        else:
            for child in value:
                yield from walk(child, depth - 1)
    coordinates = geometry.get("coordinates")
    yield from walk(coordinates, depths[kind])
    lines = [coordinates] if kind == "LineString" else coordinates if kind == "MultiLineString" else []
    if any(len(line) < 2 for line in lines):
        raise ValueError("Line needs two positions")
    polygons = [coordinates] if kind == "Polygon" else coordinates if kind == "MultiPolygon" else []
    if any(len(ring) < 4 or ring[0] != ring[-1] for polygon in polygons for ring in polygon):
        raise ValueError("Polygon rings must be closed")


def feature_cells(feature):
    if (not isinstance(feature, dict) or feature.get("type") != "Feature"
            or not isinstance(feature.get("properties"), dict)):
        raise ValueError("Expected GeoJSON feature and property object")
    west = south = math.inf
    east = north = -math.inf
    for position in _positions(feature.get("geometry")):
        lon, lat = position[:2]
        west, east = min(west, lon), max(east, lon)
        south, north = min(south, lat), max(north, lat)

    def lower(value):
        scaled = float(value) * 2
        return math.floor(scaled) - (1 if scaled.is_integer() else 0)
    first_col, last_col = max(-360, lower(west)), min(359, math.floor(east * 2))
    first_row, last_row = max(-180, lower(south)), min(179, math.floor(north * 2))
    count = (last_col - first_col + 1) * (last_row - first_row + 1)
    if count > MAX_FEATURE_CELLS:
        return None
    return [(row, col) for row in range(first_row, last_row + 1)
            for col in range(first_col, last_col + 1)]


def build(source, output):
    stdin_source = str(source) == "-"
    source, output = Path(source), Path(output)
    if not stdin_source and (source.is_symlink() or not source.is_file()):
        raise ValueError("Missing or unsafe GeoJSONSeq source")
    if output.exists() or output.is_symlink():
        raise ValueError("Output directory must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    features = 0
    source_hash = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix=".feature-packs-", dir=output.parent) as temporary:
        root = Path(temporary)
        spool = root / "spool"
        spool.mkdir()
        handles = OrderedDict()
        def close_spool(handle):
            raw, compressed = handle
            try:
                compressed.close()
            finally:
                raw.close()
        try:
            with (nullcontext(sys.stdin.buffer) if stdin_source else source.open("rb")) as stream:
                while True:
                    record = stream.readline(MAX_RECORD_BYTES + 1)
                    if not record:
                        break
                    source_hash.update(record)
                    if len(record) > MAX_RECORD_BYTES:
                        raise ValueError("Feature record exceeds size limit")
                    record = record.strip().lstrip(b"\x1e")
                    if not record:
                        continue
                    def reject_constant(value):
                        raise ValueError("Nonfinite JSON number: " + value)
                    feature = json.loads(record, parse_constant=reject_constant)
                    cells = feature_cells(feature)
                    if cells is None:
                        cells = [None]
                    line = json.dumps(feature, ensure_ascii=False, separators=(",", ":"),
                                      allow_nan=False).encode("utf-8") + b"\n"
                    if len(line) > MAX_RECORD_BYTES:
                        raise ValueError("Encoded feature exceeds record size limit")
                    for cell in cells:
                        count = counts.get(cell, 0) + 1
                        if count > MAX_RECORDS_PER_PACK or cell not in counts and len(counts) >= MAX_PACKS:
                            raise ValueError("Feature pack inventory exceeds bounded limits")
                        counts[cell] = count
                        handle = handles.pop(cell, None)
                        if handle is None:
                            if len(handles) >= OPEN_SPOOLS:
                                _, oldest = handles.popitem(last=False)
                                close_spool(oldest)
                            raw = (spool / pack_name(cell)).open("ab")
                            handle = (raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0))
                        handles[cell] = handle
                        handle[1].write(line)
                    features += 1
        finally:
            for handle in handles.values():
                close_spool(handle)
        if not features:
            raise ValueError("No exported features")
        staged = root / "packs"
        staged.mkdir()
        inventory = {}
        for cell in sorted(counts, key=pack_name):
            filename = pack_name(cell)
            with (staged / filename).open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                    # LRU reopen creates gzip members. Recompress their joined
                    # stream once so final bytes never depend on eviction order.
                    with gzip.open(spool / filename, "rb") as records:
                        while block := records.read(1024 * 1024):
                            compressed.write(block)
            # Release each processed spool immediately; peak disk needs only
            # one additional finished pack, not a second complete UK set.
            (spool / filename).unlink()
            path = staged / filename
            inventory[filename] = {"bytes": path.stat().st_size, "sha256": digest(path),
                                   "records": counts[cell], "scope": "global" if cell is None else "region",
                                   "cell": list(cell) if cell is not None else None}
        manifest = {"schema": 1, "format": "osm-geojson-ndjson-gzip",
                    "source_sha256": source_hash.hexdigest(), "features": features,
                    "pack_records": sum(counts.values()), "files": inventory,
                    "attribution": ATTRIBUTION,
                    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                    "distribution": "Half-degree bbox overlap, including seams; read global pack alongside regional packs",
                    "global_fallback": "Features exceeding regional fanout retained once in global pack; no geometry altered",
                    "limitations": "Exported objects only; raw PBF retains objects not represented by osmium export"}
        (staged / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_directory(staged)
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared during export")
        staged.rename(output)
    return {"features": features, "packs": len(counts), "pack_records": sum(counts.values())}


def validate_directory(directory):
    directory = Path(directory)
    manifest_path = directory / MANIFEST
    if directory.is_symlink() or not directory.is_dir() or manifest_path.is_symlink():
        raise ValueError("Unsafe feature pack directory")
    if not manifest_path.is_file() or not 0 < manifest_path.stat().st_size <= 2_000_000:
        raise ValueError("Missing or oversized feature manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    def positive(value):
        return type(value) is int and value > 0
    def sha(value):
        return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1
            or manifest.get("format") != "osm-geojson-ndjson-gzip" or not sha(manifest.get("source_sha256"))
            or not positive(manifest.get("features")) or not positive(manifest.get("pack_records"))
            or manifest.get("attribution") != ATTRIBUTION or not isinstance(manifest.get("files"), dict)
            or not 1 <= len(manifest["files"]) <= MAX_PACKS):
        raise ValueError("Invalid feature manifest")
    total = 0
    for name, info in manifest["files"].items():
        if not isinstance(info, dict):
            raise ValueError("Invalid feature pack metadata")
        cell = info.get("cell")
        if info.get("scope") == "global":
            if cell is not None or name != pack_name(None):
                raise ValueError("Invalid global pack metadata")
        elif (info.get("scope") != "region" or not isinstance(cell, list) or len(cell) != 2
              or any(type(c) is not int for c in cell) or not -180 <= cell[0] <= 179
              or not -360 <= cell[1] <= 359 or name != pack_name(cell)):
            raise ValueError("Invalid region pack metadata")
        path = directory / name
        if (path.is_symlink() or not path.is_file() or not positive(info.get("bytes"))
                or not positive(info.get("records")) or info["records"] > MAX_RECORDS_PER_PACK
                or not sha(info.get("sha256")) or path.stat().st_size != info["bytes"]
                or digest(path) != info["sha256"]):
            raise ValueError("Feature pack does not match verified metadata")
        count = 0
        with gzip.open(path, "rb") as stream:
            while record := stream.readline(MAX_RECORD_BYTES + 1):
                if len(record) > MAX_RECORD_BYTES or not record.endswith(b"\n"):
                    raise ValueError("Invalid feature record length or terminator")
                def reject_constant(value):
                    raise ValueError("Nonfinite JSON number: " + value)
                feature = json.loads(record, parse_constant=reject_constant)
                cells = feature_cells(feature)
                if (cell is None and cells is not None) or (cell is not None and (cells is None or tuple(cell) not in cells)):
                    raise ValueError("Feature does not belong to its pack")
                count += 1
                if count > info["records"]:
                    raise ValueError("Feature count mismatch")
        if count != info["records"]:
            raise ValueError("Feature count mismatch")
        total += count
    if total != manifest["pack_records"] or manifest["features"] > total:
        raise ValueError("Feature inventory count mismatch")
    if {p.name for p in directory.iterdir()} != {*manifest["files"], MANIFEST}:
        raise ValueError("Unexpected feature pack files")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="GeoJSONSeq input file, or - for stdin")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output)))


if __name__ == "__main__":
    main()
