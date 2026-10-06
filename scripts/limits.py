"""UK speed limits from OpenStreetMap (maxspeed on roads), in half-degree squares like the lane
files, so the app has every limit on the phone (no live map-server lookups while driving).

Usage: limits.py roads-maxspeed.geojsonseq out_dir [motorways.geojsonseq] [checks.md]
  (input: osmium tags-filter w/maxspeed, then osmium export -f geojsonseq --geometry-types=linestring -u type_id)
Also writes a list of limits that look wrong (for a person to check on OpenStreetMap) to checks.md.
Writes out_dir/limits-<floor(lat*2)>_<floor(lon*2)>.json = {"ways": [[kmh, [[lon, lat], ...]], ...]}.
"""
import json
import math
import os
import re
import sys

src, out_dir = sys.argv[1], sys.argv[2]
motorways_src = sys.argv[3] if len(sys.argv) > 3 else None
checks_path = sys.argv[4] if len(sys.argv) > 4 else None
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
suspects = []  # (reason, way id, road name, limit text)
ends = {}  # rounded end point -> [(way index, mph)]
ways_info = []  # (id, name, highway, mph, length_m, first, last)


def mph_of(kmh):
    return round(kmh / MPH)


def length_m(pts):
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        kx = 111320.0 * math.cos(math.radians(a[1]))
        total += math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110540.0)
    return total
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
        # Checks: limits that don't fit the kind of road.
        hw, mph, name = props.get("highway", ""), mph_of(kmh), props.get("name") or props.get("ref") or ""
        wid = props.get("@id") or feat.get("id") or ""
        if hw in ("residential", "living_street", "service") and mph > 40:
            suspects.append((f"{mph} mph on a {hw.replace('_', ' ')} road", wid, name, props.get("maxspeed")))
        if hw == "motorway" and mph <= 30:
            suspects.append((f"only {mph} mph on a motorway", wid, name, props.get("maxspeed")))
        ways_info.append((wid, name, hw, mph, length_m(pts), tuple(pts[0]), tuple(pts[-1])))
        for end in (tuple(pts[0]), tuple(pts[-1])):
            ends.setdefault(end, []).append((len(ways_info) - 1, mph))
        # Filed under every half-degree square it touches.
        for key in {f"{math.floor(p[1] * 2)}_{math.floor(p[0] * 2)}" for p in pts}:
            squares.setdefault(key, []).append([round(kmh, 1), pts])
        count += 1

os.makedirs(out_dir, exist_ok=True)
for key, ways in squares.items():
    with open(os.path.join(out_dir, f"limits-{key}.json"), "w", encoding="utf-8") as f:
        json.dump({"ways": ways}, f, separators=(",", ":"))
# A short stretch with a much higher limit than the roads at both of its ends (a "60 between two
# 30s"): usually a mapping mistake.
for i, (wid, name, hw, mph, length, first, last) in enumerate(ways_info):
    if length > 400:
        continue
    before = [m for j, m in ends.get(first, []) if j != i]
    after = [m for j, m in ends.get(last, []) if j != i]
    if before and after and mph - max(before) >= 20 and mph - max(after) >= 20:
        suspects.append((f"{mph} mph for {length:.0f} m between {max(before)} and {max(after)} mph", wid, name, ""))

# Motorways with no limit mapped at all.
if motorways_src:
    with open(motorways_src, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            props = feat.get("properties") or {}
            if props.get("highway") == "motorway" and not props.get("maxspeed"):
                suspects.append(("motorway with no speed limit mapped", props.get("@id") or feat.get("id") or "", props.get("ref") or props.get("name") or "", ""))

if checks_path:
    with open(checks_path, "w", encoding="utf-8") as f:
        f.write(f"## Speed limits to check ({len(suspects)})\n\n")
        f.write("Each links to the road on OpenStreetMap; fixing it there fixes the app the next week.\n\n")
        for reason, wid, name, raw in suspects[:300]:
            ref = str(wid).lstrip("w")
            link = f"https://www.openstreetmap.org/way/{ref}" if ref.isdigit() else ""
            f.write(f"- {reason}" + (f" — {name}" if name else "") + (f" ({raw})" if raw else "") + (f" — {link}" if link else "") + "\n")
        if len(suspects) > 300:
            f.write(f"\n…and {len(suspects) - 300} more.\n")
print(json.dumps({"limit_ways": count, "limit_squares": len(squares), "limits_to_check": len(suspects)}))
