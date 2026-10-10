"""Checks published lane squares against expected lane layouts at named checkpoints.

The matching is a port of the Android consumer (OwnMap.kt, ``LaneDb``): segments are
filed in a ~200 m grid (with neighbouring cells), the nearest segment closer than 20 m
whose bearing is within 40 degrees of the heading (forward) or more than 140 degrees
from it (backward) wins, and crossing roads (40-140 degrees) are skipped. The lane count
follows ``laneCountAt`` and the arrows follow ``lanesAt`` (before its manoeuvre filter).

The app does not check ``oneway`` while matching, so it can pick a one-way carriageway
driven against its direction. That match is kept (it is what the phone would use) and
flagged ``against_oneway``; a second, diagnostic match that skips such ways is reported
as ``strict_oneway_match`` whenever it differs.

Nothing here edits or "corrects" data: it only reports what the files say.

Usage:
  lane_acceptance.py --lanes lanes-106_-5.json [more squares] --checkpoints cps.json \
      --json-out result.json --md-out result.md
"""
import argparse
import json
import math
from pathlib import Path

MAX_DISTANCE_M = 20.0      # OwnMap.kt nearest(): bestD = 20.0
FORWARD_MAX_DEG = 40.0     # diff < 40 -> forward
BACKWARD_MIN_DEG = 140.0   # diff > 140 -> backward, otherwise a crossing road
MIN_SEGMENT_M = 1.0        # segments shorter than 1 m are ignored
CELL = 0.002               # grid cell, about 200 m
EARTH_RADIUS = 6_371_000.0
NEARBY_REPORT_M = 30.0

ONEWAY_COUNT = {"yes", "1", "-1"}  # laneCountAt
OSM_DIRECTION = {
    "left": "left", "slight_left": "slight left", "sharp_left": "sharp left",
    "right": "right", "slight_right": "slight right", "sharp_right": "sharp right",
    "reverse": "uturn",
}


# ---------- Geo (port of nav/Geo.kt) ----------

def distance(a, b):
    d_lat = math.radians(b[0] - a[0])
    d_lon = math.radians(b[1] - a[1])
    h = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def bearing(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    d_lon = math.radians(b[1] - a[1])
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff(a, b):
    d = abs(a - b) % 360.0
    return 360 - d if d > 180 else d


def project_distance(p, a, b):
    m_lon = 111_320.0 * math.cos(math.radians(p[0]))
    m_lat = 110_540.0
    ax, ay = (a[1] - p[1]) * m_lon, (a[0] - p[0]) * m_lat
    bx, by = (b[1] - p[1]) * m_lon, (b[0] - p[0]) * m_lat
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    t = 0.0 if len2 == 0.0 else min(1.0, max(0.0, (-ax * dx - ay * dy) / len2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.sqrt(cx * cx + cy * cy)


def osm_direction(value):
    """OSM arrow name -> the app's direction name (through, none, merge_*, blank -> straight)."""
    return OSM_DIRECTION.get(value.strip(), "straight")


def cell_key(lat, lon):
    return (math.floor(lat / CELL), math.floor(lon / CELL))


# ---------- Lane database ----------

class LaneIndex:
    def __init__(self, documents):
        self.grid = {}
        self.ways = 0
        self.way_ids = set()
        seen = set()
        for doc_no, doc in enumerate(documents):
            for i, w in enumerate(doc.get("ways", [])):
                raw_id = w.get("id")
                # The app de-duplicates by optString("id", "$i"): a way crossing squares is in both.
                dedup = str(raw_id) if raw_id is not None else str(i)
                if dedup in seen:
                    continue
                seen.add(dedup)
                self.ways += 1
                self.way_ids.add(str(raw_id))
                way = {"id": raw_id if raw_id is not None else f"{doc_no}:{i}",
                       "tags": {k: str(v) for k, v in (w.get("t") or {}).items()}}
                prev = None
                for lon, lat in ((c[0], c[1]) for c in w.get("g", [])):
                    pt = (lat, lon)
                    if prev is not None:
                        seg = (prev, pt, way)
                        mid = ((prev[0] + pt[0]) / 2, (prev[1] + pt[1]) / 2)
                        cells = set()
                        for q in (prev, pt, mid):
                            for dy in (-1, 0, 1):
                                for dx in (-1, 0, 1):
                                    cells.add(cell_key(q[0] + dy * CELL, q[1] + dx * CELL))
                        for c in cells:
                            self.grid.setdefault(c, []).append(seg)
                    prev = pt

    @classmethod
    def from_files(cls, paths):
        docs = []
        for p in paths:
            with open(p, encoding="utf-8") as f:
                docs.append(json.load(f))
        return cls(docs)

    def segments(self, p):
        return self.grid.get(cell_key(*p), [])

    def nearest(self, p, heading, strict_oneway=False):
        """Port of LaneDb.nearest(); returns (segment, forward, distance_m) or None."""
        best, best_d = None, MAX_DISTANCE_M
        for seg in self.segments(p):
            a, b, way = seg
            d = project_distance(p, a, b)
            if d >= best_d or distance(a, b) < MIN_SEGMENT_M:
                continue
            diff = angle_diff(heading, bearing(a, b))
            if diff < FORWARD_MAX_DEG:
                forward = True
            elif diff > BACKWARD_MIN_DEG:
                forward = False
            else:
                continue  # a road crossing yours
            if strict_oneway and against_oneway(way["tags"], forward):
                continue
            best_d = d
            best = (seg, forward, d)
        return best

    def nearby_ways(self, p, radius=NEARBY_REPORT_M):
        found = {}
        for a, b, way in self.segments(p):
            d = project_distance(p, a, b)
            if d <= radius:
                key = str(way["id"])
                if key not in found or d < found[key][0]:
                    found[key] = (d, way, bearing(a, b))
        out = []
        for d, way, brg in sorted(found.values(), key=lambda x: x[0]):
            out.append({"way_id": way["id"], "osm_url": osm_url(way["id"]), "distance_m": round(d, 1),
                        "segment_bearing": round(brg), "name": way["tags"].get("name"),
                        "ref": way["tags"].get("ref"), "tags": lane_tags(way["tags"])})
        return out


def against_oneway(tags, forward):
    oneway = tags.get("oneway")
    if oneway in ("yes", "1", "true") or (tags.get("junction") in ("roundabout", "circular") and oneway != "no"):
        return not forward
    if oneway == "-1":
        return forward
    return False


def lane_count_at(tags, forward):
    """Port of LaneDb.laneCountAt() after the match."""
    oneway = tags.get("oneway") in ONEWAY_COUNT
    total = _int(tags.get("lanes"))
    if oneway:
        n = total
    elif forward:
        n = _int(tags.get("lanes:forward"))
        if n is None and total is not None:
            n = total // 2
    else:
        n = _int(tags.get("lanes:backward"))
        if n is None and total is not None:
            n = total // 2
    return n if n is not None and 1 <= n <= 6 else None


def arrows_at(tags, forward):
    """Lane arrows the app's lanesAt() reads, before it filters by manoeuvre.

    Returns (tag_used, raw_value, lanes) where lanes is a list of direction lists.
    """
    oneway = tags.get("oneway") in ("yes", "1", "-1") or tags.get("junction") == "roundabout"
    if oneway:
        key = "turn:lanes"
    elif forward:
        key = "turn:lanes:forward" if "turn:lanes:forward" in tags else "turn:lanes"
    else:
        key = "turn:lanes:backward"
    raw = tags.get(key)
    if raw is None:
        return key, None, None
    lanes = []
    for lane in raw.split("|"):
        dirs = []
        for v in lane.split(";"):
            d = osm_direction(v)
            if d not in dirs:
                dirs.append(d)
        lanes.append(dirs)
    return key, raw, lanes


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def lane_tags(tags):
    keep = ("highway", "oneway", "junction", "lanes", "lanes:forward", "lanes:backward",
            "turn:lanes", "turn:lanes:forward", "turn:lanes:backward")
    return {k: tags[k] for k in keep if k in tags}


def osm_url(way_id):
    s = str(way_id)
    for prefix in ("way/", "w"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return f"https://www.openstreetmap.org/way/{s}" if s.isdigit() else None


def normalise_expected_arrows(pattern):
    """["straight", "left;straight"] -> [{"straight"}, {"left", "straight"}]; "*" matches any lane."""
    app_names = set(OSM_DIRECTION.values()) | {"straight"}
    out = []
    for lane in pattern:
        if lane.strip() == "*":
            out.append(None)
            continue
        dirs = set()
        for v in lane.split(";"):
            v = v.strip()
            dirs.add(v if v in app_names else osm_direction(v))
        out.append(dirs)
    return out


# ---------- Checkpoint evaluation ----------

def evaluate(index, cp):
    p = (float(cp["lat"]), float(cp["lon"]))
    heading = float(cp["heading"])
    expected_lanes = cp.get("expected_lanes")
    expected_arrows = cp.get("expected_arrows")
    expected_ways = [str(w) for w in cp.get("expected_way_ids") or []]
    result = {"name": cp["name"], "lat": p[0], "lon": p[1], "heading": heading,
              "expected_lanes": expected_lanes, "expected_arrows": expected_arrows,
              "expected_way_ids": cp.get("expected_way_ids")}
    if expected_ways:
        result["expected_ways_in_lane_data"] = {w: w in index.way_ids for w in expected_ways}
    match = index.nearest(p, heading)
    result["nearby_lane_ways"] = index.nearby_ways(p)
    if match is None:
        result.update({"verdict": "NO_DATA", "matched": None, "count_verdict": "NO_DATA",
                       "arrows_verdict": "NO_DATA" if expected_arrows else "NOT_CHECKED",
                       "way_verdict": "NO_DATA" if expected_ways else "NOT_CHECKED",
                       "reason": f"no lane-tagged way within {MAX_DISTANCE_M:.0f} m in a compatible direction"})
        return result
    (a, b, way), forward, d = match
    tags = way["tags"]
    count = lane_count_at(tags, forward)
    arrow_key, arrow_raw, arrows = arrows_at(tags, forward)
    # lanesAt() returns null for fewer than two arrow lanes; then nothing is shown from arrows.
    shown_arrows = arrows if arrows is not None and len(arrows) >= 2 else None
    shown_count = len(shown_arrows) if shown_arrows else count
    result["matched"] = {
        "way_id": way["id"], "osm_url": osm_url(way["id"]), "name": tags.get("name"), "ref": tags.get("ref"),
        "highway": tags.get("highway"), "distance_m": round(d, 1), "segment_bearing": round(bearing(a, b)),
        "forward": forward, "against_oneway": against_oneway(tags, forward), "tags": lane_tags(tags)}
    result["lane_count_app"] = count
    result["arrow_tag"] = arrow_key
    result["arrows_raw"] = arrow_raw
    result["arrows"] = arrows
    result["shown_lane_count"] = shown_count
    notes = []
    if arrows is not None and count is not None and len(arrows) != count:
        notes.append(f"turn lanes list {len(arrows)} lanes but lane count tags give {count}")
    if result["matched"]["against_oneway"]:
        notes.append("the app matched a one-way way against its direction (opposite carriageway?)")
    if tags.get("junction") in ("roundabout", "circular") and tags.get("oneway") not in ONEWAY_COUNT:
        notes.append("junction=%s without oneway tag: laneCountAt treats it as two-way and halves lanes"
                     % tags.get("junction"))
    strict = index.nearest(p, heading, strict_oneway=True)
    if strict is None or strict[0][2] is not way:
        result["strict_oneway_match"] = None if strict is None else {
            "way_id": strict[0][2]["id"], "osm_url": osm_url(strict[0][2]["id"]),
            "name": strict[0][2]["tags"].get("name"), "ref": strict[0][2]["tags"].get("ref"),
            "distance_m": round(strict[2], 1), "forward": strict[1],
            "lane_count_app": lane_count_at(strict[0][2]["tags"], strict[1]),
            "arrows_raw": arrows_at(strict[0][2]["tags"], strict[1])[1]}

    # Count
    if expected_lanes is None:
        count_verdict = "NOT_CHECKED"
    elif shown_count is None:
        count_verdict = "NO_DATA"
    else:
        count_verdict = "MATCH" if shown_count == int(expected_lanes) else "MISMATCH"
    # Arrows
    if not expected_arrows:
        arrows_verdict = "NOT_CHECKED"
    elif shown_arrows is None:
        arrows_verdict = "NO_DATA"
    else:
        want = normalise_expected_arrows(expected_arrows)
        if len(want) != len(shown_arrows):
            arrows_verdict = "MISMATCH"
        else:
            arrows_verdict = "MATCH" if all(w is None or w == set(got)
                                            for w, got in zip(want, shown_arrows)) else "MISMATCH"
    # Way: the checkpoint names the OSM way(s) it lies on; matching another way means the app
    # would show some other road's lanes here, whatever their count.
    if not expected_ways:
        way_verdict = "NOT_CHECKED"
    elif str(way["id"]) in expected_ways:
        way_verdict = "MATCH"
    else:
        way_verdict = "MISMATCH"
        notes.append("matched way %s is not the checkpoint road (%s)%s" % (
            way["id"], ", ".join(expected_ways),
            "" if any(result["expected_ways_in_lane_data"].values())
            else "; the checkpoint road has no lane data, so the app falls back to a nearby road"))
    result["way_verdict"] = way_verdict
    result["count_verdict"] = count_verdict
    result["arrows_verdict"] = arrows_verdict
    parts = [v for v in (way_verdict, count_verdict, arrows_verdict) if v != "NOT_CHECKED"]
    if "MISMATCH" in parts:
        verdict = "MISMATCH"
    elif not parts or "NO_DATA" in parts:
        verdict = "NO_DATA"
    else:
        verdict = "MATCH"
    result["verdict"] = verdict
    result["notes"] = notes
    return result


def run(lane_paths, checkpoints):
    index = LaneIndex.from_files(lane_paths)
    results = [evaluate(index, cp) for cp in checkpoints]
    summary = {}
    for r in results:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    return {"tool": "scripts/lane_acceptance.py", "matching": {
        "max_distance_m": MAX_DISTANCE_M, "forward_max_deg": FORWARD_MAX_DEG,
        "backward_min_deg": BACKWARD_MIN_DEG, "grid_cell_deg": CELL,
        "source": "port of OwnMap.kt LaneDb.nearest / laneCountAt / lanesAt"},
        "lane_files": [Path(p).name for p in lane_paths], "ways_indexed": index.ways,
        "summary": summary, "results": results}


def _fmt_arrows(arrows):
    if not arrows:
        return "none"
    return "[" + " | ".join(";".join(lane) for lane in arrows) + "]"


def markdown(report):
    lines = ["| Checkpoint | Verdict | Matched way | Lanes (data / expected) | Arrows (data / expected) |",
             "|---|---|---|---|---|"]
    for r in report["results"]:
        m = r.get("matched")
        if m:
            label = " ".join(x for x in (m.get("ref"), m.get("name")) if x) or m.get("highway") or ""
            way = f"[{m['way_id']}]({m['osm_url']}) {label}" if m.get("osm_url") else f"{m['way_id']} {label}"
        else:
            way = "none within 20 m"
        exp_arrows = _fmt_arrows([a.split(";") for a in r["expected_arrows"]]) if r.get("expected_arrows") else "-"
        exp_lanes = r["expected_lanes"] if r.get("expected_lanes") is not None else "-"
        lines.append(f"| {r['name']} | **{r['verdict']}** | {way} | {r.get('shown_lane_count')} / {exp_lanes} "
                     f"| {_fmt_arrows(r.get('arrows'))} / {exp_arrows} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lanes", nargs="+", required=True, help="lane square JSON files")
    ap.add_argument("--checkpoints", required=True, help="JSON list, or object with a 'checkpoints' list")
    ap.add_argument("--json-out")
    ap.add_argument("--md-out")
    args = ap.parse_args(argv)
    with open(args.checkpoints, encoding="utf-8") as f:
        cps = json.load(f)
    if isinstance(cps, dict):
        cps = cps["checkpoints"]
    report = run(args.lanes, cps)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    else:
        print(text)
    md = markdown(report)
    if args.md_out:
        Path(args.md_out).write_text(md, encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
