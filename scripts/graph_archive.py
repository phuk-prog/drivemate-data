"""Validate Valhalla extract container structure without extracting files.

This does not prove graph connectivity, legal routing or binary engine compatibility.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import tarfile

TILE = re.compile(r"([0-3])/(?:[0-9]{3}/)*[0-9]{3}\.gph")
MAX_GRAPH = 64 * 1024**3


class FingerprintedReader:
    def __init__(self, stream, limit):
        self.stream = stream
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        block = self.stream.read(size)
        self.size += len(block)
        if self.size > self.limit:
            raise ValueError("Graph exceeds declared size")
        self.digest.update(block)
        return block


def validate(path, compressed=False, expected_bytes=None, expected_sha256=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Graph archive missing or symlinked")
    opener = gzip.open if compressed else open
    names, levels = set(), {}
    index_size = None
    index = None
    expected_entries = set()
    with opener(path, "rb") as source:
        reader = FingerprintedReader(source, expected_bytes or MAX_GRAPH)
        try:
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for entry in archive:
                    if entry.name in names:
                        raise ValueError("Duplicate graph archive member")
                    names.add(entry.name)
                    match = TILE.fullmatch(entry.name)
                    if entry.name != "index.bin" and not match:
                        raise ValueError("Unexpected or unsafe graph archive path")
                    if not entry.isfile() or entry.size <= 0 or entry.sparse is not None:
                        raise ValueError("Graph member must be a nonempty regular file")
                    if entry.name == "index.bin":
                        index_size = entry.size
                        if index_size > 16_000_000 or index_size % 16:
                            raise ValueError("Invalid or oversized Valhalla extract index")
                    else:
                        level = match.group(1)
                        levels[level] = levels.get(level, 0) + 1
                        tile_id = int(''.join(entry.name[:-4].split('/')[1:]))
                        graph_id = tile_id * 8 + int(level)
                        expected_entries.add((entry.offset_data, graph_id, entry.size))
                    # Read through every member: seek/skip alone can conceal truncated final data.
                    member = archive.extractfile(entry)
                    if entry.name == "index.bin":
                        index = member.read()
                    total = 0
                    if index is not None and entry.name == "index.bin":
                        total = len(index)
                    while True:
                        block = member.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                    if total != entry.size:
                        raise ValueError("Truncated graph archive member")
        except tarfile.TarError as exc:
            raise ValueError("Invalid graph TAR container") from exc
        # Include padding/trailing bytes and force gzip footer/CRC verification.
        while reader.read(1024 * 1024):
            pass
    tiles = sum(levels.values())
    if not tiles or index_size != tiles * 16:
        raise ValueError("Missing or inconsistent Valhalla extract index")
    # Valhalla 3.6.3 extract index: little-endian offset:uint64, GraphId:uint32, size:uint32.
    entries = list(struct.iter_unpack('<QII', index))
    if len({entry[1] for entry in entries}) != len(entries) or set(entries) != expected_entries:
        raise ValueError("Valhalla extract index offsets/IDs/sizes do not match tile members")
    if expected_bytes is not None and reader.size != expected_bytes:
        raise ValueError("Graph byte count differs")
    sha = reader.digest.hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError("Graph integrity verification failed")
    return {"schema": 1, "bytes": reader.size, "sha256": sha,
            "tile_members": tiles, "by_level": levels, "index_bytes": index_size,
            "index_entries_verified": len(entries),
            "scope": "TAR/extract structure and fingerprint; runtime routes and legal correctness require separate tests"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--gzip", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = validate(args.file, args.gzip)
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
