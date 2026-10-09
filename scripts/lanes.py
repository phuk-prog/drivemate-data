"""Pulls the lane details out of the road data: lane counts, lane arrows (turn:lanes),
one-way, speed limits, road names/numbers — everything the app needs for lane guidance.

Usage: lanes.py roads.geojsonseq lanes.json
"""
import json
import os
import sys

from grid_tiles import tiles_for_polyline

KEEP = [
    "lanes", "lanes:forward", "lanes:backward",
    "turn:lanes", "turn:lanes:forward", "turn:lanes:backward",
    "oneway", "junction", "maxspeed", "ref", "name", "highway",
    "destination", "destination:ref", "destination:lanes",
    # Bus lanes, so the app can mark them and never advise them.
    "bus:lanes", "bus:lanes:forward", "bus:lanes:backward",
    "psv:lanes", "psv:lanes:forward", "psv:lanes:backward",
]

src, dst = sys.argv[1], sys.argv[2]
ways = []
stats = {"roads": 0, "with_lanes": 0, "with_turn_lanes": 0}
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
        if not (has_lanes or has_turn):
            continue
        stats["with_lanes"] += 1
        if has_turn:
            stats["with_turn_lanes"] += 1
        coords = feat["geometry"]["coordinates"]
        ways.append({
            "id": props.get("@id") or props.get("id"),
            "t": {k: props[k] for k in KEEP if k in props},
            "g": [[round(c[0], 5), round(c[1], 5)] for c in coords],
        })

SOURCE = "© OpenStreetMap contributors (ODbL)"

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

print(json.dumps(stats))
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as s:
        s.write(f"Roads: {stats['roads']:,} · with lane counts: {stats['with_lanes']:,} · "
                f"with lane arrows: {stats['with_turn_lanes']:,}\n\n")
