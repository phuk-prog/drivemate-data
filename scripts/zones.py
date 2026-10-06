"""UK charge and emission zones (ULEZ, Clean Air Zones, Scottish Low Emission Zones…) from
OpenStreetMap boundaries, with what each means for an ordinary car, for the app's
"your route enters a charge zone" warning.

Usage: zones.py zones.geojsonseq charge-zones-uk.json
  (input from: osmium export -f geojsonseq --geometry-types=polygon of boundary=low_emission_zone)

Only zones mapped in OpenStreetMap are included. Charges are checked by hand (Oct 2026)
and kept in RULES below; a zone not listed there is still included with a general note.
"""
import json
import math
import sys

src, dst = sys.argv[1], sys.argv[2]

# Name fragment → (title shown in the app, what it means for a car, applies to private cars?)
RULES = [
    ("congestion", "London Congestion Charge", "£18 a day, 7am–6pm weekdays, 12–6pm weekends", True),
    ("london low emission", "London ULEZ", "£12.50 a day for older cars (petrol before 2006, diesel before Sept 2015)", True),
    ("ultra low emission", "London ULEZ", "£12.50 a day for older cars (petrol before 2006, diesel before Sept 2015)", True),
    ("birmingham", "Birmingham Clean Air Zone", "£8 a day for older cars", True),
    ("bristol", "Bristol Clean Air Zone", "£9 a day for older cars", True),
    ("glasgow", "Glasgow Low Emission Zone", "Older cars not allowed: £60 penalty", True),
    ("edinburgh", "Edinburgh Low Emission Zone", "Older cars not allowed: £60 penalty", True),
    ("aberdeen", "Aberdeen Low Emission Zone", "Older cars not allowed: £60 penalty", True),
    ("dundee", "Dundee Low Emission Zone", "Older cars not allowed: £60 penalty", True),
    ("oxford", "Oxford Zero Emission Zone", "Daily charge for cars that aren't fully electric, 7am–7pm", True),
    ("hackney", "Hackney and Islington Zero Emission Zone", "Streets closed to non-electric cars at peak times", True),
    # Class B/C Clean Air Zones don't charge private cars.
    ("sheffield", "Sheffield Clean Air Zone", "No charge for private cars", False),
    ("bradford", "Bradford Clean Air Zone", "No charge for private cars", False),
    ("bath", "Bath Clean Air Zone", "No charge for private cars", False),
    ("portsmouth", "Portsmouth Clean Air Zone", "No charge for private cars", False),
    ("newcastle", "Newcastle and Gateshead Clean Air Zone", "No charge for private cars", False),
]


def rule_for(name):
    low = name.lower()
    for frag, title, note, cars in RULES:
        if frag in low:
            return title, note, cars
    return name, "Low emission zone: check whether your car must pay", True


def simplify(ring, tol_m=15.0):
    """Douglas–Peucker in metres (rings are small enough for a flat approximation)."""
    if len(ring) < 5:
        return ring
    lat0 = math.radians(ring[0][1])
    kx, ky = 111320.0 * math.cos(lat0), 110540.0

    def dist(p, a, b):
        px, py = p[0] * kx, p[1] * ky
        ax, ay = a[0] * kx, a[1] * ky
        bx, by = b[0] * kx, b[1] * ky
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = dist(ring[k], ring[i], ring[j])
            if d > best:
                best, idx = d, k
        if best > tol_m and idx > 0:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [[round(p[0], 5), round(p[1], 5)] for p, k in zip(ring, keep) if k]


zones = {}
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        feat = json.loads(line)
        props = feat.get("properties") or {}
        name = props.get("name") or props.get("alt_name") or ""
        if not name:
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        title, note, cars = rule_for(name)
        z = zones.setdefault(title, {"name": title, "note": note, "cars": cars, "polygons": []})
        # Outer rings only: holes in these zones are tiny and don't matter for a warning.
        for poly in polys:
            if poly:
                z["polygons"].append(simplify(poly[0]))

out = {"source": "© OpenStreetMap contributors (ODbL); charges checked Oct 2026", "zones": list(zones.values())}
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))
print(json.dumps({"zones": len(zones), "names": sorted(zones)}))
