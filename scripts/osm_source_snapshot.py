"""Retain an exact OSM PBF snapshot; this does not render or interpret its tags.

The input must already have passed the real OSM parser/build checks. Chunk
hashes protect storage/transfer; they do not establish OSM accuracy. The
manifest records the complete file hash so nodes, ways, relations and tags
can be recovered without the losses of a selected-feature export.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

DEFAULT_CHUNK_BYTES = 200_000_000
MAX_SOURCE_BYTES = 50_000_000_000
MAX_CHUNKS = 1000
MAX_MANIFEST_BYTES = 1_000_000
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"


def check_url(url):
    if not isinstance(url, str) or not re.fullmatch(
            r"https://download\.geofabrik\.de/(?:[a-z0-9_-]+/)*[a-z0-9_-]+\.osm\.pbf", url):
        raise ValueError("A canonical HTTPS Geofabrik PBF source is required")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "download.geofabrik.de"
            or parts.query or parts.fragment or not parts.path.endswith(".osm.pbf")
            or ".." in parts.path.split("/")):
        raise ValueError("An HTTPS Geofabrik PBF source is required")


def safe_path(path):
    if any(part.is_symlink() for part in (path, *path.absolute().parents)):
        raise ValueError("Symlink in snapshot path")


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def retain(source, destination, source_url, chunk_bytes=DEFAULT_CHUNK_BYTES):
    check_url(source_url)
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= DEFAULT_CHUNK_BYTES:
        raise ValueError("Invalid chunk size")
    source, destination = Path(source), Path(destination)
    safe_path(source)
    safe_path(destination)
    if source.is_symlink() or not source.is_file() or not source.stat().st_size:
        raise ValueError("Missing or empty source snapshot")
    if destination.exists():
        raise ValueError("Snapshot destination must be new")
    original = source.stat()
    if original.st_size > MAX_SOURCE_BYTES or (original.st_size + chunk_bytes - 1) // chunk_bytes > MAX_CHUNKS:
        raise ValueError("Source exceeds snapshot bounds")
    destination.parent.mkdir(parents=True, exist_ok=True)
    whole = hashlib.sha256()
    total = 0
    chunks = []
    with tempfile.TemporaryDirectory(prefix=".osm-snapshot-", dir=destination.parent) as scratch:
        staging = Path(scratch) / "snapshot"
        staging.mkdir()
        with source.open("rb") as stream:
            if identity(os.fstat(stream.fileno())) != identity(original):
                raise ValueError("Source changed before snapshot capture")
            while True:
                first = stream.read(min(chunk_bytes, 1024 * 1024))
                if not first:
                    break
                digest = hashlib.sha256()
                size = 0
                number = len(chunks)
                name = f"osm-source.part{number:05d}"
                with (staging / name).open("wb") as out:
                    block = first
                    while block:
                        out.write(block)
                        whole.update(block)
                        digest.update(block)
                        size += len(block)
                        if size == chunk_bytes:
                            break
                        block = stream.read(min(chunk_bytes - size, 1024 * 1024))
                total += size
                chunks.append({"name": name, "bytes": size, "sha256": digest.hexdigest()})
                if total > original.st_size or len(chunks) > MAX_CHUNKS:
                    raise ValueError("Source grew during snapshot capture")
            if identity(os.fstat(stream.fileno())) != identity(original):
                raise ValueError("Source changed during snapshot capture")
        safe_path(source)
        if total != original.st_size or identity(source.stat()) != identity(original):
            raise ValueError("Source changed during snapshot capture")
        manifest = {"schema": 1, "format": "osm-pbf-byte-snapshot",
                    "source_url": source_url, "source_bytes": total,
                    "source_sha256": whole.hexdigest(), "chunks": chunks,
                    "attribution": ATTRIBUTION,
                    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                    "scope": "Current supplied extract; not edit history or proof of map completeness"}
        (staging / "osm-source-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify(staging)
        safe_path(source)
        if identity(source.stat()) != identity(original):
            raise ValueError("Source changed before snapshot commit")
        safe_path(destination)
        if destination.exists():
            raise ValueError("Snapshot destination appeared during capture")
        staging.rename(destination)
    return manifest


def verify(directory):
    directory = Path(directory)
    safe_path(directory)
    manifest_path = directory / "osm-source-manifest.json"
    if directory.is_symlink() or not directory.is_dir() or manifest_path.is_symlink():
        raise ValueError("Unsafe snapshot directory or manifest")
    if not manifest_path.is_file() or not 0 < manifest_path.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("Missing or oversized snapshot manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
            or manifest["schema"] != 1 or manifest.get("format") != "osm-pbf-byte-snapshot"
            or not isinstance(manifest.get("chunks"), list) or not 1 <= len(manifest["chunks"]) <= MAX_CHUNKS
            or type(manifest.get("source_bytes")) is not int
            or not 1 <= manifest["source_bytes"] <= MAX_SOURCE_BYTES
            or not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("source_sha256", "")))):
        raise ValueError("Invalid snapshot manifest")
    check_url(manifest.get("source_url"))
    whole = hashlib.sha256()
    total = 0
    expected = {"osm-source-manifest.json"}
    for index, chunk in enumerate(manifest["chunks"]):
        name = f"osm-source.part{index:05d}"
        if (not isinstance(chunk, dict) or chunk.get("name") != name or type(chunk.get("bytes")) is not int
                or not 1 <= chunk["bytes"] <= DEFAULT_CHUNK_BYTES
                or not re.fullmatch(r"[0-9a-f]{64}", str(chunk.get("sha256", "")))):
            raise ValueError("Invalid snapshot chunk")
        expected.add(name)
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != chunk["bytes"]:
            raise ValueError("Missing or resized snapshot chunk")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                whole.update(block)
        total += chunk["bytes"]
        if digest.hexdigest() != chunk["sha256"]:
            raise ValueError("Snapshot chunk checksum mismatch")
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError("Unexpected snapshot files")
    if total != manifest.get("source_bytes") or whole.hexdigest() != manifest.get("source_sha256"):
        raise ValueError("Whole snapshot checksum mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("retain")
    capture.add_argument("--source", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--source-url", required=True)
    capture.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    check = sub.add_parser("verify")
    check.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = (retain(args.source, args.output, args.source_url, args.chunk_bytes)
                if args.command == "retain" else verify(args.directory))
    print(json.dumps({"source_sha256": manifest["source_sha256"],
                      "bytes": manifest["source_bytes"], "chunks": len(manifest["chunks"])}))


if __name__ == "__main__":
    main()
