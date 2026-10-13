"""Preserves road tags and centreline geometry from the OSM road export.

Phone lane files keep the bounded selection of roads and tags. Optional
backend detail files retain all exported roads and tags without activating
them in the phone's lane database.
This does not preserve the raw OSM nodes/relations or supply lane boundaries.

Usage: lanes.py roads.geojsonseq lanes.json
"""
import argparse
import gzip
import json
import os
import sys

from grid_tiles import tiles_for_polyline

KEEP = [
    "lanes", "lanes:forward", "lanes:backward",
    "turn:lanes", "turn:lanes:forward", "turn:lanes:backward",
    "oneway", "junction", "maxspeed", "ref", "name", "highway",
    "destination", "destination:ref", "destination:lanes",
    "bus:lanes", "bus:lanes:forward", "bus:lanes:backward",
    "psv:lanes", "psv:lanes:forward", "psv:lanes:backward",
    "bridge", "tunnel", "layer", "width", "width:lanes",
    "change:lanes", "change:lanes:forward", "change:lanes:backward",
]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source")
parser.add_argument("destination")
parser.add_argument("--details-out", help="Optional backend road-detail directory; not phone lane data")
args = parser.parse_args()
src, dst = args.source, args.destination
ways = []
details = {}
stats = {"roads": 0, "with_lanes": 0, "with_turn_lanes": 0, "context_only": 0}
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        feat = json.loads(line)
        props = feat.get("properties", {})
        stats["roads"] += 1
        has_lanes = any(k in props for k in ("lanes", "lanes:forward", "lanes:backward"))
        has_turn = any(k.startswith("turn:lanes") for k in props)
        if has_lanes:
            stats["with_lanes"] += 1
        if has_turn:
            stats["with_turn_lanes"] += 1
        coords = feat["geometry"]["coordinates"]
        if args.details_out:
            detail = {
                "id": props.get("@id") or props.get("id"),
                "t": {k: v for k, v in props.items() if not k.startswith("@")},
                "g": coords,
            }
            if not (has_lanes or has_turn):
                detail["ctx"] = 1
            for key in tiles_for_polyline(coords, 2):
                details.setdefault(key, []).append(detail)
        if not (has_lanes or has_turn):
            stats["context_only"] += 1
            continue
        way = {
            "id": props.get("@id") or props.get("id"),
            # @-prefixed fields describe the export, not original OSM tags.
            "t": {k: props[k] for k in KEEP if k in props},
            "g": coords,
        }
        ways.append(way)

SOURCE = "© OpenStreetMap contributors, ODbL 1.0 https://opendatacommons.org/licenses/odbl/1-0/"

if dst.endswith(".json"):
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE, "ways": ways}, f, separators=(",", ":"))
else:
    # Split into squares of half a degree (about 55 x 35 km), so the app only fetches the
    # squares along your route: lanes-<row>_<col>.json, row = floor(lat*2), col = floor(lon*2).
    os.makedirs(dst, exist_ok=True)
    squares = {}
    for w in ways:
        keys = tiles_for_polyline(w["g"], 2)
        for k in keys:
            squares.setdefault(k, []).append(w)
    for (row, col), items in squares.items():
        with open(os.path.join(dst, f"lanes-{row}_{col}.json"), "w", encoding="utf-8") as f:
            json.dump({"source": SOURCE, "ways": items}, f, separators=(",", ":"))
    stats["squares"] = len(squares)

if args.details_out:
    os.makedirs(args.details_out, exist_ok=True)
    for (row, col), items in sorted(details.items()):
        path = os.path.join(args.details_out, f"road-details-{row}_{col}.json.gz")
        # No filename or wall-clock timestamp in the gzip header.
        with open(path, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
                compressed.write(json.dumps({"source": SOURCE, "ways": items},
                                            separators=(",", ":")).encode("utf-8"))
    stats["detail_squares"] = len(details)

print(json.dumps(stats))
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as s:
        s.write(f"Roads: {stats['roads']:,} · with lane counts: {stats['with_lanes']:,} · "
                f"with lane arrows: {stats['with_turn_lanes']:,}\n\n")
