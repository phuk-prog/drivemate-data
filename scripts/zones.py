"""UK charge and emission zones (ULEZ, Congestion Charge, Clean Air Zones, Scottish Low Emission
Zones…) with what each means for an ordinary car, for the app's "your route enters a charge zone"
warning.

Usage: zones.py zones.geojsonseq charge-zones-uk.json [--official "Title=file.geojson" ...]
                [--birmingham-roads roads.geojsonseq]
       zones.py --selftest

Sources, best first:
  - --official: boundaries published by the people who run the zone, as GeoJSON (WGS84 or
    British National Grid, EPSG:27700). Used now for the London Congestion Charge zone and the
    London-wide ULEZ (Transport for London, London Datastore, Open Government Licence v2).
    A zone given here replaces any OpenStreetMap zone with the same title.
  - OpenStreetMap boundary=low_emission_zone (osmium export -f geojsonseq --geometry-types=polygon).
  - --birmingham-roads: Birmingham's Clean Air Zone is "every road inside the A4540 Middleway
    ring road, but not the Middleway itself" (Birmingham City Council). The council's own
    boundary file is restricted (Ordnance Survey PSMA licence, derived from OS MasterMap), so it
    is NOT used: the ring is traced from the A4540 in OpenStreetMap instead (checked Oct 2026: it
    matches the council's boundary to within about 40 m, 99% overlap). Needs shapely.
A file that is missing or broken is skipped with a warning; the other zones are still written.

Output (what app/.../data/ChargeZones.kt reads):
  {"source": "...", "zones": [{"name", "note", "cars", "polygons": [[[lon, lat], ...], ...]}]}
Charges are checked by hand (Oct 2026) and kept in RULES below; a zone not listed there is still
included with a general note.
"""
import json
import math
import sys

# Name fragment → (title shown in the app, what it means for a car, applies to private cars?)
RULES = [
    ("congestion", "London Congestion Charge", "£18 a day, 7am–6pm weekdays, 12–6pm weekends", True),
    ("london low emission", "London ULEZ", "£12.50 a day for older cars (petrol before 2006, diesel before Sept 2015)", True),
    ("ultra low emission", "London ULEZ", "£12.50 a day for older cars (petrol before 2006, diesel before Sept 2015)", True),
    ("ulez", "London ULEZ", "£12.50 a day for older cars (petrol before 2006, diesel before Sept 2015)", True),
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
OSM_CREDIT = "© OpenStreetMap contributors (ODbL)"
TFL_CREDIT = "Contains Transport for London data (London Datastore, Open Government Licence v2)"
UK_BOX = (-8.7, 49.8, 1.8, 60.9)
# Middle of Birmingham city centre (New Street station): inside the A4540 ring.
BIRMINGHAM_CENTRE = (-1.8986, 52.4796)


def rule_for(name):
    low = name.lower()
    for frag, title, note, cars in RULES:
        if frag in low:
            return title, note, cars
    return name, "Low emission zone: check whether your car must pay", True


def simplify(ring, tol_m=15.0):
    """Douglas–Peucker in metres (rings are small enough for a flat approximation)."""
    if len(ring) < 5:
        return [[round(p[0], 5), round(p[1], 5)] for p in ring]
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


def ring_area_m2(ring):
    """Area of a lon/lat ring in square metres (flat approximation, fine for a city)."""
    if len(ring) < 3:
        return 0.0
    kx, ky = 111320.0 * math.cos(math.radians(ring[0][1])), 110540.0
    s = 0.0
    for a, b in zip(ring, ring[1:] + ring[:1]):
        s += a[0] * kx * b[1] * ky - b[0] * kx * a[1] * ky
    return abs(s) / 2


def outer_rings(geom):
    """Outer rings of a Polygon / MultiPolygon (holes in these zones don't matter for a warning)."""
    t = (geom or {}).get("type")
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return []
    return [[[float(p[0]), float(p[1])] for p in poly[0]] for poly in polys if poly and poly[0]]


def read_official(path):
    """Outer rings (WGS84 lon/lat) from a GeoJSON file, converting from British National Grid
    when the file says so (or its numbers are clearly metres)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    feats = data.get("features") if data.get("type") == "FeatureCollection" else [data]
    rings = [r for feat in feats or [] for r in outer_rings(feat.get("geometry"))]
    crs = json.dumps(data.get("crs") or "")
    if "27700" in crs or any(abs(p[0]) > 1000 for r in rings for p in r[:1]):
        from pyproj import Transformer

        to_wgs = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
        rings = [[list(to_wgs.transform(p[0], p[1])) for p in r] for r in rings]
    out = []
    for r in rings:
        if not all(UK_BOX[0] <= p[0] <= UK_BOX[2] and UK_BOX[1] <= p[1] <= UK_BOX[3] for p in r):
            raise ValueError("boundary is not in the UK")
        if ring_area_m2(r) >= 1000:  # leave out slivers
            out.append(simplify(r))
    if not out or sum(ring_area_m2(r) for r in out) < 100_000:
        raise ValueError("no usable boundary in the file")
    return out


def birmingham_ring(roads_path):
    """Birmingham Clean Air Zone traced from OpenStreetMap: the area enclosed by the A4540
    Middleway (and the roundabouts on it), inner edge, so the Middleway itself is outside.
    Input: geojsonseq of roads around Birmingham. Returns a ring or None."""
    from shapely.geometry import LineString, Point
    from shapely.ops import polygonize, unary_union

    ways = []
    with open(roads_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            g = feat.get("geometry") or {}
            if g.get("type") != "LineString" or len(g.get("coordinates") or []) < 2:
                continue
            ways.append((feat.get("properties") or {}, g["coordinates"]))

    def pts(c):
        return {(round(p[0], 7), round(p[1], 7)) for p in c}

    ring_ways = [c for t, c in ways if "A4540" in (t.get("ref") or "").replace(" ", "").split(";")]
    if not ring_ways:
        return None
    # Roundabouts the ring runs through often carry no road number: add those joined to it.
    joined = set().union(*(pts(c) for c in ring_ways))
    rest = [c for t, c in ways if t.get("junction") in ("roundabout", "circular") and c not in ring_ways]
    while True:
        add = [c for c in rest if pts(c) & joined]
        if not add:
            break
        ring_ways += add
        rest = [c for c in rest if c not in add]
        joined |= set().union(*(pts(c) for c in add))
    centre = Point(*BIRMINGHAM_CENTRE)
    faces = [p for p in polygonize(unary_union([LineString(c) for c in ring_ways])) if p.contains(centre)]
    if not faces:
        return None
    ring = [[x, y] for x, y in faces[0].exterior.coords]
    area = ring_area_m2(ring)
    # The real zone is about 7.7 km²: anything far off means the ring wasn't traced properly.
    if not 5e6 <= area <= 11e6:
        print(f"::warning::Birmingham ring traced from the A4540 is {area / 1e6:.1f} km², expected ~7.7: left out", flush=True)
        return None
    return simplify(ring)


def build(src, official=None, birmingham_roads=None):
    zones = {}
    sources = {OSM_CREDIT}
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
            rings = outer_rings(feat.get("geometry"))
            if not rings:
                continue
            title, note, cars = rule_for(name)
            z = zones.setdefault(title, {"name": title, "note": note, "cars": cars, "polygons": []})
            z["polygons"] += [simplify(r) for r in rings]

    for title, path in (official or []):
        try:
            rings = read_official(path)
        except Exception as e:  # missing download, broken file, wrong place: keep what OSM has
            print(f"::warning::{title}: official boundary not used ({e}); keeping OpenStreetMap's, if any", flush=True)
            continue
        t, note, cars = rule_for(title)
        zones[t] = {"name": t, "note": note, "cars": cars, "polygons": rings}
        if "London" in t:
            sources.add(TFL_CREDIT)

    if birmingham_roads and "Birmingham Clean Air Zone" not in zones:
        try:
            ring = birmingham_ring(birmingham_roads)
        except Exception as e:
            ring = None
            print(f"::warning::Birmingham Clean Air Zone not traced ({e})", flush=True)
        if ring:
            t, note, cars = rule_for("Birmingham")
            zones[t] = {"name": t, "note": note, "cars": cars, "polygons": [ring]}

    for must in ("London ULEZ", "London Congestion Charge", "Birmingham Clean Air Zone"):
        if must not in zones:
            print(f"::warning::{must} is missing from charge-zones-uk.json this week", flush=True)
    source = "; ".join(sorted(sources)) + "; charges checked Oct 2026"
    return {"source": source, "zones": list(zones.values())}


def selftest():
    import os
    import tempfile

    tmp = tempfile.mkdtemp()
    osm = os.path.join(tmp, "zones.geojsonseq")
    sq = lambda x, y, d: [[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]
    with open(osm, "w", encoding="utf-8") as f:
        f.write("\x1e" + json.dumps({"type": "Feature", "properties": {"name": "Glasgow LEZ"},
                                     "geometry": {"type": "Polygon", "coordinates": [sq(-4.26, 55.85, 0.02)]}}) + "\n")
        f.write(json.dumps({"type": "Feature", "properties": {"name": "London Ultra Low Emission Zone"},
                            "geometry": {"type": "Polygon", "coordinates": [sq(-0.2, 51.4, 0.3)]}}) + "\n")
    # Official Congestion Charge zone: a tiny made-up square in central London.
    ccz = os.path.join(tmp, "ccz.geojson")
    with open(ccz, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                   "geometry": {"type": "MultiPolygon", "coordinates": [[sq(-0.13, 51.50, 0.01)]]}}]}, f)
    # Official ULEZ that replaces OSM's.
    ulez = os.path.join(tmp, "ulez.geojson")
    with open(ulez, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                   "geometry": {"type": "Polygon", "coordinates": [sq(-0.4, 51.3, 0.5)]}}]}, f)
    broken = os.path.join(tmp, "broken.geojson")
    with open(broken, "w", encoding="utf-8") as f:
        f.write("<html>Service unavailable</html>")
    # Birmingham: a made-up ring road of two numbered halves joined by an unnumbered roundabout.
    cx, cy = BIRMINGHAM_CENTRE
    r = 0.015
    a = [[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r]]
    b = [[cx + r, cy + r + 0.0005], [cx - r, cy + r + 0.0005], [cx - r, cy - r]]
    rb = [[cx + r, cy + r], [cx + r + 0.0003, cy + r + 0.0003], [cx + r, cy + r + 0.0005], [cx + r - 0.0003, cy + r + 0.0002], [cx + r, cy + r]]
    roads = os.path.join(tmp, "bham.geojsonseq")
    with open(roads, "w", encoding="utf-8") as f:
        for t, c in (({"highway": "trunk", "ref": "A4540"}, a), ({"highway": "trunk", "ref": "A4540"}, b),
                     ({"highway": "trunk", "junction": "roundabout"}, rb),
                     ({"highway": "primary", "ref": "A38"}, [[cx, cy - 0.05], [cx, cy + 0.05]])):
            f.write(json.dumps({"type": "Feature", "properties": t, "geometry": {"type": "LineString", "coordinates": c}}) + "\n")

    out = build(osm, [("London Congestion Charge", ccz), ("London ULEZ", ulez), ("Birmingham Clean Air Zone", broken)], roads)
    byname = {z["name"]: z for z in out["zones"]}
    assert set(byname) == {"Glasgow Low Emission Zone", "London ULEZ", "London Congestion Charge", "Birmingham Clean Air Zone"}, sorted(byname)
    assert byname["London Congestion Charge"]["cars"] and byname["London Congestion Charge"]["note"].startswith("£18")
    assert byname["London ULEZ"]["polygons"][0][0] == [-0.4, 51.3], "official ULEZ should replace OpenStreetMap's"
    bham = byname["Birmingham Clean Air Zone"]["polygons"][0]
    assert 5e6 < ring_area_m2(bham) < 11e6, ring_area_m2(bham)
    assert "Transport for London" in out["source"] and "OpenStreetMap" in out["source"]
    # Same shape the app reads: [lon, lat] pairs.
    for z in out["zones"]:
        for ring in z["polygons"]:
            assert len(ring) >= 4 and all(len(p) == 2 and -9 < p[0] < 2 and 49 < p[1] < 61 for p in ring)
    # British National Grid input is converted (needs pyproj, installed in the workflow).
    try:
        import pyproj  # noqa: F401
        bng = os.path.join(tmp, "bng.geojson")
        with open(bng, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::27700"}},
                       "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [
                           [[529000, 180000], [531000, 180000], [531000, 182000], [529000, 182000], [529000, 180000]]]}}]}, f)
        ring = read_official(bng)[0]
        assert -0.2 < ring[0][0] < -0.05 and 51.49 < ring[0][1] < 51.53, ring[0]
    except ImportError:
        print("(pyproj not installed: British National Grid check skipped)")
    print("selftest ok")


def main(argv):
    if argv == ["--selftest"]:
        selftest()
        return
    src, dst = argv[0], argv[1]
    official, bham = [], None
    rest = argv[2:]
    while rest:
        flag = rest.pop(0)
        if flag == "--official":
            title, _, path = rest.pop(0).partition("=")
            official.append((title, path))
        elif flag == "--birmingham-roads":
            bham = rest.pop(0)
        else:
            raise SystemExit(f"unknown option {flag}")
    out = build(src, official, bham)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    names = sorted(z["name"] for z in out["zones"])
    print(json.dumps({"zones": len(names), "names": names}))
    if not names:
        raise SystemExit("::error::no charge zones at all - something is broken")


if __name__ == "__main__":
    main(sys.argv[1:])
