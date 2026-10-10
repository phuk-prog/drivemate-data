"""Cut a small real-data PMTiles test fixture from a verified UK archive.

Takes a (2r+1)x(2r+1) window of z14 tiles around a point plus every ancestor
tile (z0..z13) of that window, and writes them as two archives matching the
regional split: a base (z0-9) and one detail package (z10-14) named after the
point's z8 root. Tile payloads are copied byte-for-byte; nothing is edited.
Output is reproducible (fixed gzip timestamps) and listed in fixture.json with
SHA-256 values and the source archive identity, so device tests can render
genuine local map content without network access.

Fixtures are OpenStreetMap-derived (ODbL) OpenMapTiles data; keep the
attribution that fixture.json records wherever the files are committed.
"""
import argparse
import copy
import json
import math
import mmap
from pathlib import Path

from region_pmtiles import (BASE_MAX_ZOOM, deterministic_gzip, parent_key, region_bounds,
                            sha256, walk_index)

ATTRIBUTION = "© OpenMapTiles © OpenStreetMap contributors (ODbL)"


def z14_tile(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon) and -85 < lat < 85 and -180 <= lon < 180):
        raise ValueError("Invalid fixture centre")
    n = 1 << 14
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def wanted_tiles(lat, lon, radius):
    if type(radius) is not int or not 0 <= radius <= 3:
        raise ValueError("Fixture radius must be 0..3 z14 tiles")
    cx, cy = z14_tile(lat, lon)
    wanted = set()
    for x in range(cx - radius, cx + radius + 1):
        for y in range(cy - radius, cy + radius + 1):
            for z in range(0, 15):
                wanted.add((z, *parent_key(14, x, y, z)[1:]))
    return wanted, (cx, cy)


def build(source, output, lat, lon, radius=1):
    from pmtiles.reader import Reader
    from pmtiles.writer import write
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    wanted, centre = wanted_tiles(lat, lon, radius)
    root = parent_key(14, *centre, 8)
    detail_name = f"region-z8-x{root[1]}-y{root[2]}"
    with source.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        def fetch(offset, length):
            if offset < 0 or length < 0 or offset + length > len(mm):
                raise ValueError("Map data offset outside archive")
            return mm[offset:offset + length]
        reader = Reader(fetch)
        header = reader.header()
        meta = reader.metadata()
        rows = [r for r in walk_index(fetch, header) if (r[1], r[2], r[3]) in wanted]
        found = {(r[1], r[2], r[3]) for r in rows}
        missing = sorted(t for t in wanted if t[0] == 14 and t not in found)
        if missing:
            raise ValueError(f"Source archive lacks fixture tiles: {missing}")
        result = {"schema": 1, "status": "test_fixture", "attribution": ATTRIBUTION,
                  "source_sha256": sha256(source), "centre": [lat, lon],
                  "z14_centre_tile": list(centre), "radius": radius, "packages": {}}
        for name, keep in (("base", lambda z: z <= BASE_MAX_ZOOM),
                           (detail_name, lambda z: z > BASE_MAX_ZOOM)):
            selected = sorted((r for r in rows if keep(r[1])), key=lambda r: r[0])
            path = output / f"{name}.pmtiles"
            new_header = copy.copy(header)
            new_meta = dict(meta)
            if name != "base":
                w, s, e, n = region_bounds(root)
                new_header.update({"min_lon_e7": int(w * 1e7), "min_lat_e7": int(s * 1e7),
                                   "max_lon_e7": int(e * 1e7), "max_lat_e7": int(n * 1e7),
                                   "center_lon_e7": int(lon * 1e7), "center_lat_e7": int(lat * 1e7),
                                   "center_zoom": 14})
            with deterministic_gzip(), write(str(path)) as writer:
                for tileid, _z, _x, _y, offset, length in selected:
                    writer.write_tile(tileid, fetch(header["tile_data_offset"] + offset, length))
                writer.finalize(new_header, new_meta)
            result["packages"][name] = {"filename": path.name, "tiles": len(selected),
                                        "bytes": path.stat().st_size, "sha256": sha256(path)}
    (output / "fixture.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--lat", required=True, type=float)
    p.add_argument("--lon", required=True, type=float)
    p.add_argument("--radius", type=int, default=1)
    a = p.parse_args()
    print(json.dumps(build(a.source, a.output, a.lat, a.lon, a.radius), indent=2))


if __name__ == "__main__":
    main()
