"""UK speed limits from OpenStreetMap (maxspeed on roads), in half-degree squares like the lane
files, so the app has every limit on the phone (no live map-server lookups while driving).

Usage: limits.py roads-maxspeed.geojsonseq out_dir
  (input: osmium tags-filter w/maxspeed, then osmium export -f geojsonseq --geometry-types=linestring)
Writes out_dir/limits-<floor(lat*2)>_<floor(lon*2)>.json = {"ways": [[kmh, [[lon, lat], ...]], ...]}.
"""
import json
import math
import os
import re
import sys

src, out_dir = sys.argv[1], sys.argv[2]
MPH = 1.609344


def parse_speed(raw):
    """Same rules as the app (RoadAlerts.parseSpeed): '30 mph', '50', UK national limit codes."""
    s = (raw or "").strip().lower()
    if not s:
        return None
    if s.endswith("nsl_single"):
        return 60 * MPH
    if s.endswith("nsl_dual") or s in ("gb:motorway", "uk:motorway"):
        return 70 * MPH
    if s.endswith(":urban") and (s.startswith("gb") or s.startswith("uk")):
        return 30 * MPH
    m = re.search(r"\d+", s)
    if not m:
        return None
    n = float(m.group())
    return n * MPH if "mph" in s else n


def simplify(line, tol_m=5.0):
    """Douglas–Peucker in metres; keeps the road's shape to within ~5 m."""
    if len(line) < 3:
        return line
    lat0 = math.radians(line[0][1])
    kx, ky = 111320.0 * math.cos(lat0), 110540.0

    def dist(p, a, b):
        px, py, ax, ay, bx, by = p[0] * kx, p[1] * ky, a[0] * kx, a[1] * ky, b[0] * kx, b[1] * ky
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = dist(line[k], line[i], line[j])
            if d > best:
                best, idx = d, k
        if best > tol_m and idx > 0:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(line, keep) if k]


squares = {}
count = 0
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        feat = json.loads(line)
        props = feat.get("properties") or {}
        if "highway" not in props:
            continue
        kmh = parse_speed(props.get("maxspeed"))
        geom = feat.get("geometry") or {}
        if kmh is None or geom.get("type") != "LineString":
            continue
        pts = [[round(p[0], 5), round(p[1], 5)] for p in simplify(geom["coordinates"])]
        if len(pts) < 2:
            continue
        # Filed under every half-degree square it touches.
        for key in {f"{math.floor(p[1] * 2)}_{math.floor(p[0] * 2)}" for p in pts}:
            squares.setdefault(key, []).append([round(kmh, 1), pts])
        count += 1

os.makedirs(out_dir, exist_ok=True)
for key, ways in squares.items():
    with open(os.path.join(out_dir, f"limits-{key}.json"), "w", encoding="utf-8") as f:
        json.dump({"ways": ways}, f, separators=(",", ":"))
print(json.dumps({"limit_ways": count, "limit_squares": len(squares)}))
