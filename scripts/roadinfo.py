"""Road warnings and turn landmarks from OpenStreetMap, in half-degree squares, so the app has them
on the phone and they work with no signal (they used to come from a live map-server question
during the drive).

Usage: roadinfo.py roadinfo.geojsonseq out_dir [--min-elements N]
       roadinfo.py --selftest
  input: osmium tags-filter (see map-data.yml), then
         osmium export -f geojsonseq --geometry-types=point,linestring,polygon -a type,id

Writes out_dir/roadinfo-<floor(lat*2)>_<floor(lon*2)>.json shaped like a map-server (Overpass)
answer, so the app's existing reader (RoadAlerts.parseFile) reads it unchanged:
  {"source": "© OpenStreetMap contributors, ODbL 1.0 https://opendatacommons.org/licenses/odbl/1-0/", "elements": [
     {"type": "node", "id": 1, "lat": 53.4, "lon": -2.1, "tags": {...}},
     {"type": "way", "id": 2, "center": {"lat": 53.4, "lon": -2.1}, "tags": {...}}, ...]}
Same choice of things as the app's live question:
  speed bumps, hazard signs, speed cameras, level crossings, toll booths, traffic lights and stop
  signs (points); schools (outlines, as their middle); named fuel stations, pubs, places of
  worship, fast food and supermarkets (points or outlines).
A thing goes in the square it is in, and also in the next square when it is within EDGE degrees
of the edge, so a route running along an edge still finds it.
"""
import json
import math
import os
import re
import sys

SOURCE = "© OpenStreetMap contributors, ODbL 1.0 https://opendatacommons.org/licenses/odbl/1-0/"
EDGE = 0.002
KEEP = ("traffic_calming", "hazard", "highway", "railway", "barrier", "maxspeed",
        "amenity", "shop", "name", "brand", "direction")
CALMING = re.compile(r"^(bump|hump|table|cushion|yes)$")
PLACE_AMENITY = re.compile(r"^(fuel|pub|place_of_worship|fast_food)$")
KIND_ORDER = ("speed bump", "hazard sign", "speed camera", "level crossing", "toll booth",
              "traffic lights", "stop sign", "school", "named place")


def kind_of(otype, tags):
    """Which of the app's things this is (None = not wanted). Mirrors the app's live question."""
    if tags.get("name") and (PLACE_AMENITY.match(tags.get("amenity", "")) or tags.get("shop") == "supermarket"):
        return "named place"
    if otype == "node":
        if CALMING.match(tags.get("traffic_calming", "")):
            return "speed bump"
        if "hazard" in tags:
            return "hazard sign"
        hw = tags.get("highway")
        if hw == "speed_camera":
            return "speed camera"
        if tags.get("railway") == "level_crossing":
            return "level crossing"
        if tags.get("barrier") == "toll_booth":
            return "toll booth"
        if hw == "traffic_signals":
            return "traffic lights"
        if hw == "stop":
            return "stop sign"
        return None
    if otype == "way" and tags.get("amenity") == "school":
        return "school"
    return None


def type_and_id(props):
    t, i = props.get("@type"), props.get("@id")
    if t is None or i is None:
        return None, None
    i = int(i)
    if t == "area":  # osmium's area ids: way id * 2, or relation id * 2 + 1
        return ("relation" if i % 2 else "way"), i // 2
    return t, i


def all_coords(c):
    if isinstance(c[0], (int, float)):
        yield c
    else:
        for x in c:
            yield from all_coords(x)


def middle(geom):
    """Middle of the bounding box, the same as the map server's 'center'."""
    pts = list(all_coords(geom["coordinates"]))
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


def squares_for(lat, lon):
    keys = set()
    for dlat in (-EDGE, 0.0, EDGE):
        for dlon in (-EDGE, 0.0, EDGE):
            keys.add((math.floor((lat + dlat) * 2), math.floor((lon + dlon) * 2)))
    return keys


def build(lines):
    """Returns ({square: [element, ...]}, {kind: count})."""
    seen = set()
    squares = {}
    counts = {}
    for line in lines:
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        feat = json.loads(line)
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        otype, oid = type_and_id(props)
        if otype is None or (otype, oid) in seen:
            continue
        tags = {k: str(props[k]) for k in KEEP if props.get(k) not in (None, "")}
        kind = kind_of(otype, tags)
        if kind is None:
            continue
        if otype == "node":
            if geom.get("type") != "Point":
                continue
            lon, lat = geom["coordinates"][:2]
            el = {"type": "node", "id": oid, "lat": round(lat, 6), "lon": round(lon, 6), "tags": tags}
        else:
            if not geom.get("coordinates"):
                continue
            m = middle(geom)
            if m is None:
                continue
            lat, lon = m
            el = {"type": otype, "id": oid, "center": {"lat": round(lat, 6), "lon": round(lon, 6)}, "tags": tags}
        seen.add((otype, oid))
        counts[kind] = counts.get(kind, 0) + 1
        for key in squares_for(lat, lon):
            squares.setdefault(key, []).append(el)
    return squares, counts


def write(squares, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    total = 0
    for (row, col), els in squares.items():
        els.sort(key=lambda e: (e["type"], e["id"]))
        path = os.path.join(out_dir, f"roadinfo-{row}_{col}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source": SOURCE, "elements": els}, f, ensure_ascii=False, separators=(",", ":"))
        total += os.path.getsize(path)
    return total


def selftest():
    import tempfile

    def feat(t, i, geom, **tags):
        return "\x1e" + json.dumps({"type": "Feature", "geometry": geom, "properties": {"@type": t, "@id": i, **tags}})

    def pt(lat, lon):
        return {"type": "Point", "coordinates": [lon, lat]}

    sq = [[-2.20, 53.40], [-2.19, 53.40], [-2.19, 53.41], [-2.20, 53.41], [-2.20, 53.40]]
    lines = [
        feat("node", 1, pt(53.30, -2.30), traffic_calming="hump", surface="asphalt"),  # middle of square 106_-5
        feat("node", 2, pt(53.30, -2.30), traffic_calming="chicane"),                  # not wanted
        feat("node", 3, pt(53.4991, -2.30), highway="traffic_signals"),                 # near top edge -> 2 squares
        feat("node", 4, pt(53.30, -2.30), highway="crossing"),                         # not wanted
        feat("node", 5, pt(53.30, -2.30), amenity="pub", name="The Crown", brand=""),
        feat("node", 6, pt(53.30, -2.30), amenity="pub"),                              # no name: not wanted
        feat("way", 7, {"type": "Polygon", "coordinates": [sq]}, amenity="school", name="St Mary's"),
        feat("way", 7, {"type": "LineString", "coordinates": sq}, amenity="school"),   # same way twice
        feat("relation", 8, {"type": "MultiPolygon", "coordinates": [[sq]]}, shop="supermarket", name="Tesco", brand="Tesco"),
        feat("area", 19, {"type": "MultiPolygon", "coordinates": [[sq]]}, amenity="fuel", name="Esso"),  # relation 9
        feat("node", 10, pt(53.30, -2.30), hazard="animal_crossing"),
        feat("node", 11, pt(53.4999, -1.9999), highway="speed_camera", maxspeed="30 mph", direction="90"),  # corner -> 4
        feat("relation", 12, {"type": "MultiPolygon", "coordinates": [[sq]]}, amenity="school"),  # schools: ways only
    ]
    squares, counts = build(lines)
    assert counts == {"speed bump": 1, "traffic lights": 1, "named place": 3, "school": 1,
                      "hazard sign": 1, "speed camera": 1}, counts
    ids = lambda key: sorted((e["type"], e["id"]) for e in squares.get(key, []))
    assert ("node", 1) in ids((106, -5)) and ("node", 1) not in ids((107, -5))
    assert ("node", 3) in ids((106, -5)) and ("node", 3) in ids((107, -5))
    assert all(("node", 11) in ids(k) for k in ((106, -5), (107, -5), (106, -4), (107, -4)))
    assert ("relation", 9) in ids((106, -5))
    assert ("relation", 12) not in ids((106, -5))
    els = {(e["type"], e["id"]): e for e in squares[(106, -5)]}
    assert els[("node", 1)] == {"type": "node", "id": 1, "lat": 53.3, "lon": -2.3, "tags": {"traffic_calming": "hump"}}
    assert els[("node", 5)]["tags"] == {"amenity": "pub", "name": "The Crown"}
    school = els[("way", 7)]
    assert school["center"] == {"lat": 53.405, "lon": -2.195} and "lat" not in school, school
    assert school["tags"] == {"amenity": "school", "name": "St Mary's"}
    assert els[("node", 11)]["tags"] == {"highway": "speed_camera", "maxspeed": "30 mph", "direction": "90"}
    with tempfile.TemporaryDirectory() as d:
        write(squares, d)
        names = sorted(os.listdir(d))
        assert names == ["roadinfo-106_-4.json", "roadinfo-106_-5.json", "roadinfo-107_-4.json", "roadinfo-107_-5.json"], names
        data = json.load(open(os.path.join(d, "roadinfo-106_-5.json"), encoding="utf-8"))
        assert data["source"] == SOURCE and isinstance(data["elements"], list) and len(data["elements"]) == 8
        for e in data["elements"]:
            assert e["type"] in ("node", "way", "relation") and isinstance(e["id"], int) and isinstance(e["tags"], dict)
            assert ("lat" in e and "lon" in e) if e["type"] == "node" else ("center" in e)
    print("roadinfo selftest ok")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--min-elements", type=int, default=50000)
    a = ap.parse_args()
    src, out_dir, min_elements = a.src, a.out_dir, a.min_elements
    with open(src, encoding="utf-8") as f:
        squares, counts = build(f)
    total = sum(counts.values())
    by_kind = ", ".join(f"{k}: {counts.get(k, 0)}" for k in KIND_ORDER)
    if total < min_elements or not squares:
        print(f"::error::Road warnings: only {total} things found ({by_kind}) - build failed")
        sys.exit(1)
    size = write(squares, out_dir)
    biggest = max(os.path.getsize(os.path.join(out_dir, n)) for n in os.listdir(out_dir))
    if biggest > 1_900_000_000:
        print("::error::A road-warning square is too big for GitHub")
        sys.exit(1)
    line = f"Road warnings and landmarks: {total} ({by_kind}) in {len(squares)} squares, {size / 1048576:.1f} MB"
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(line + "\n\n")


if __name__ == "__main__":
    main()
