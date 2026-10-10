"""Make *unpublished* PMTiles base/detail packages from one verified UK archive.

Source is unchanged. Detail tiles z>=10 belong to their single z8 ancestor,
with automatic subdivision to z9/z10 when estimated compressed tile bytes
exceed 200 MB. Low zoom 0..9 lives in one base package.

This is experimental data packaging, NOT an Android package switch or
authorization to distribute archives under unreviewed source licences.
"""
import argparse
from collections import defaultdict
import contextlib
import copy
import gzip
import hashlib
import json
import math
import mmap
from pathlib import Path

BASE_MAX_ZOOM = 9
DETAIL_MIN_ZOOM = 10
REGION_ZOOM = 8
MAX_SUBDIVISION = 10
DEFAULT_MAX_BYTES = 200_000_000


def parent_key(zoom, x, y, ancestor):
    if zoom < ancestor:
        raise ValueError("Cannot place a smaller-zoom tile inside a larger-zoom region")
    shift = zoom - ancestor
    return ancestor, x >> shift, y >> shift


def region_bounds(key):
    z, x, y = key
    if not (0 <= z <= 22 and 0 <= x < 1 << z and 0 <= y < 1 << z):
        raise ValueError("Invalid map region")
    scale = 1 << z
    lon_w = x / scale * 360 - 180
    lon_e = (x + 1) / scale * 360 - 180
    def latitude(ty):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / scale))))
    return [lon_w, latitude(y + 1), lon_e, latitude(y)]


def walk_index(fetch, header):
    from pmtiles.tile import deserialize_directory, tileid_to_zxy
    length = header["tile_data_length"]
    previous = -1
    seen = set()

    def traverse(offset, size, depth=0):
        nonlocal previous
        if (offset, size) in seen:
            raise ValueError("Repeated or cyclic PMTiles directory reference")
        seen.add((offset, size))
        if depth > 4:
            raise ValueError("Too many PMTiles directory levels")
        rows = deserialize_directory(fetch(offset, size))
        for row in rows:
            if row.run_length == 0:
                if row.offset < 0 or row.offset + row.length > header["leaf_directory_length"]:
                    raise ValueError("Leaf directory outside archive")
                yield from traverse(header["leaf_directory_offset"] + row.offset, row.length, depth + 1)
            else:
                if (row.length <= 0 or row.offset < 0
                    or row.offset + row.length > length or row.tile_id <= previous):
                    raise ValueError("Invalid or unordered PMTiles tile index")
                for tileid in range(row.tile_id, row.tile_id + row.run_length):
                    z, x, y = tileid_to_zxy(tileid)
                    if z > 14:
                        raise ValueError("Map exceeds supported detail zoom")
                    yield tileid, z, x, y, row.offset, row.length
                previous = row.tile_id + row.run_length - 1
    yield from traverse(header["root_offset"], header["root_length"])


def plan_tile_sets(index, max_bytes=DEFAULT_MAX_BYTES):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Package size limit must be a positive integer")
    base = []
    roots = defaultdict(list)
    for tileid, z, x, y, offset, length in index:
        row = (tileid, z, x, y, offset, length)
        if z <= BASE_MAX_ZOOM:
            base.append(row)
        else:
            roots[parent_key(z, x, y, REGION_ZOOM)].append(row)
    if not base or not roots:
        raise ValueError("Archive is missing base or detail tiles")

    groups = {"base": base}
    def add_region(key, rows):
        estimated = sum(row[5] for row in rows)
        if estimated > max_bytes and key[0] < MAX_SUBDIVISION:
            children = defaultdict(list)
            for row in rows:
                children[parent_key(row[1], row[2], row[3], key[0] + 1)].append(row)
            for child, members in sorted(children.items()):
                add_region(child, members)
            return
        if estimated > max_bytes:
            raise ValueError(f"Even the smallest permitted region {key} exceeds package limit")
        z, x, y = key
        groups[f"region-z{z}-x{x}-y{y}"] = rows
    for key, rows in sorted(roots.items()):
        add_region(key, rows)
    if sum(len(v) for v in groups.values()) != len(base) + sum(map(len, roots.values())):
        raise ValueError("Tiles were lost or duplicated during region partition")
    # Region sections may never contain a low zoom tile, and base may never
    # contain a high zoom tile. This is what permits a single-source renderer.
    for name, items in groups.items():
        if name == "base":
            if any(row[1] > BASE_MAX_ZOOM for row in items):
                raise ValueError("Detailed tile leaked into the nationwide base")
        elif any(row[1] < DETAIL_MIN_ZOOM for row in items):
            raise ValueError("Low zoom tile leaked into a detail region")
    return groups


def describe_groups(groups):
    return {
        name: {
            "tiles": len(rows),
            "estimated_tile_bytes": sum(row[5] for row in rows),
            "bounds": region_bounds(tuple(map(int, name.replace("region-z", "").replace("-x", ",").replace("-y", ",").split(",")))) if name != "base" else None,
        }
        for name, rows in sorted(groups.items())
    }


@contextlib.contextmanager
def deterministic_gzip():
    """Make archive bytes reproducible: identical input gives identical SHA-256.

    pmtiles 3.4.1 gzips the root directory and metadata with the current time
    in the gzip header, so re-exporting an unchanged region changed its
    checksum. Tile payloads are copied raw and are unaffected.
    """
    original = gzip.compress

    def compress(data, compresslevel=9, *, mtime=None):
        return original(data, compresslevel, mtime=0)
    gzip.compress = compress
    try:
        yield
    finally:
        gzip.compress = original


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(source, destination, max_bytes=DEFAULT_MAX_BYTES, pilot=None, dry_run=False,
          available=None):
    """Write a standalone base and selected region or all regions, never publish.

    ``available`` optionally names the release's assets so that each detail
    package's companion lane/limit/places squares list only real files.
    """
    from region_companions import annotate
    from pmtiles.reader import Reader
    from pmtiles.tile import TileType, Compression
    from pmtiles.writer import write
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Missing or unsafe source archive")
    if pilot is not None:
        parts = pilot.split("/")
        if len(parts) != 3 or any(not t.isdigit() for t in parts):
            raise ValueError("Pilot must be '8/x/y'")
        key = tuple(map(int, parts))
        if key[0] != REGION_ZOOM:
            raise ValueError("Pilot must use a z8 root")
        region_bounds(key)
    with source.open("rb") as src, mmap.mmap(src.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        def fetch(offset, length):
            if offset < 0 or length < 0 or offset + length > len(mm):
                raise ValueError("Map data offset outside archive")
            return mm[offset:offset+length]
        reader = Reader(fetch)
        header = reader.header()
        if (header["tile_type"] != TileType.MVT or
            header["tile_compression"] != Compression.GZIP or header["max_zoom"] < DETAIL_MIN_ZOOM):
            raise ValueError("Only detailed gzip MVT PMTiles archives are supported")
        meta = reader.metadata()
        groups = plan_tile_sets(walk_index(fetch, header), max_bytes)
        region_names = list(groups)
        total_addressed_tiles = sum(map(len, groups.values()))
        if pilot is not None:
            def matches(name):
                if name == "base":
                    return True
                a = name.replace("region-z", "").replace("-x", ",").replace("-y", ",")
                key = tuple(map(int, a.split(",")))
                return parent_key(key[0], key[1], key[2], REGION_ZOOM) == tuple(map(int,pilot.split("/")))
            groups = {name: rows for name, rows in groups.items() if matches(name)}
            if len(groups) <= 1:
                raise ValueError("Selected pilot has no detailed map data")
        if not groups:
            raise ValueError("No map regions selected")
        # Validate input tile ownership before packaging. The source archive's
        # expanded run lengths are already checked by walk_index().
        all_rows = list(groups.values())
        seen_tiles = set()
        for rows in all_rows:
            for row in rows:
                if row[0] in seen_tiles:
                    raise ValueError("Overlapping tile assignments")
                seen_tiles.add(row[0])
        if not seen_tiles:
            raise ValueError("Selected regions have no tiles")
        inventory = {
            "schema": 1, "status": "pilot_unpublished" if pilot else "unpublished",
            "source_sha256": sha256(source), "source_bytes": source.stat().st_size,
            "base_zoom_max": BASE_MAX_ZOOM, "detail_zoom_min": DETAIL_MIN_ZOOM,
            "max_package_bytes": max_bytes, "pilot_root": pilot,
            "tile_partition": "Each z10+ tile belongs to exactly one z8 parent or subdivided descendant.",
            "licensing": "Unreviewed sources must not be publicly redistributed from this pilot.",
            "candidate_regions": len(region_names) - 1,
            "source_addressed_tiles": total_addressed_tiles,
            "selected_addressed_tiles": sum(map(len, groups.values())),
            "packages": {},
        }
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise ValueError("Output directory must be empty; never overwrite a verified region")
        for name, rows in sorted(groups.items()):
            rows = sorted(rows, key=lambda r: r[0])
            region = None if name == "base" else tuple(map(int, name.replace("region-z","").replace("-x",",").replace("-y",",").split(",")))
            info = {
                "tiles": len(rows), "estimated_tile_bytes": sum(r[5] for r in rows),
                "bounds": region_bounds(region) if region else None,
            }
            if not dry_run:
                path = destination / f"{name}.pmtiles"
                new_header = copy.copy(header)
                new_metadata = dict(meta)
                if region:
                    west, south, east, north = info["bounds"]
                    new_header.update({
                        "min_lon_e7": int(west * 10**7), "min_lat_e7": int(south * 10**7),
                        "max_lon_e7": int(east * 10**7), "max_lat_e7": int(north * 10**7),
                        "center_lon_e7": int((west + east) / 2 * 10**7),
                        "center_lat_e7": int((south + north) / 2 * 10**7),
                        "center_zoom": region[0],
                    })
                    new_metadata["bounds"] = ",".join(f"{v:.7f}" for v in info["bounds"])
                    new_metadata["center"] = f"{(west + east)/2:.7f},{(south+north)/2:.7f},{region[0]}"
                with deterministic_gzip(), write(str(path)) as writer:
                    for tileid, z, x, y, offset, length in rows:
                        writer.write_tile(tileid, fetch(header["tile_data_offset"]+offset, length))
                    writer.finalize(new_header, new_metadata)
                if path.stat().st_size > max_bytes and name != "base":
                    path.unlink()
                    raise ValueError(f"Region {name} exceeds {max_bytes} byte cap after writing")
                # Compare EVERY expanded source tile ID and compressed payload
                # with the output. This also catches invalid writer deduplication,
                # missing intermediate tiles, or cross-package geometry drift.
                # Source tile bytes are unchanged: no geometry or metadata edits.
                with path.open("rb") as verify_file, mmap.mmap(verify_file.fileno(),0,access=mmap.ACCESS_READ) as result_map:
                    def read_region(off, count):
                        if off < 0 or count < 0 or off + count > len(result_map):
                            raise ValueError("Regional PMTiles points outside output")
                        return result_map[off:off+count]
                    readback = Reader(read_region)
                    region_header = readback.header()
                    if region_header["addressed_tiles_count"] != len(rows):
                        raise ValueError(f"Tile count mismatch in {name}")
                    emitted = walk_index(read_region, region_header)
                    verified = 0
                    for source_row in rows:
                        output_row = next(emitted, None)
                        if output_row is None or output_row[0] != source_row[0]:
                            raise ValueError(f"Missing/changed tile IDs in {name}")
                        origin_bytes = fetch(header["tile_data_offset"]+source_row[4],source_row[5])
                        emitted_bytes = read_region(
                            region_header["tile_data_offset"]+output_row[4], output_row[5])
                        if origin_bytes != emitted_bytes:
                            raise ValueError(f"Tile payload mismatch in {name}: {source_row[0]}")
                        verified += 1
                    if next(emitted, None) is not None:
                        raise ValueError(f"Unexpected additional tiles in {name}")
                info["verified_tile_payloads"] = verified
                info.update({"filename":path.name,"bytes":path.stat().st_size,"sha256":sha256(path)})
            inventory["packages"][name] = info
        inventory = annotate(inventory, available)
        (destination / ("regional-plan.json" if dry_run else "regional-manifest.json")).write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return inventory


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    p.add_argument("--pilot", help="Build only one z8 area, e.g. 8/126/82 for Manchester")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--release-manifest", type=Path,
                   help="Release manifest.json; limits companion squares to published files")
    p.add_argument("--available-dir", type=Path,
                   help="Build output folder; limits companion squares to files it contains")
    a = p.parse_args()
    available = None
    if a.release_manifest is not None and a.available_dir is not None:
        raise SystemExit("Use either --release-manifest or --available-dir")
    if a.available_dir is not None:
        available = {f.name for f in a.available_dir.rglob("*") if f.is_file()}
        if not available:
            raise SystemExit("Build output folder is empty")
    if a.release_manifest is not None:
        files = json.loads(a.release_manifest.read_text(encoding="utf-8")).get("files")
        if not isinstance(files, dict) or not files:
            raise SystemExit("Release manifest has no files inventory")
        available = set(files)
    result = build(a.source, a.output, a.max_bytes, a.pilot, a.plan_only, available)
    print(f"{len(result['packages'])} candidate packages, pilot={a.pilot}, published=no")


if __name__ == "__main__":
    main()
