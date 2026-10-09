"""Fills gaps in our lane data with the arrows painted on the road, as spotted in Mapillary's
street photos. Runs after lanes.py and adds `turn:lanes` to roads that have a lane count in
OpenStreetMap but no lane arrows.

Usage: arrows.py roads.geojsonseq lanes_dir cache_in.json.gz cache_out.json.gz
       arrows.py --selftest

Only real painted arrows are used, never a guess. A road gets arrows only when all of this holds:
  - the arrows sit in the last 60 m before the junction, in as many separate lines (lanes) as
    OpenStreetMap says the road has, each lane's arrows agreeing with each other;
  - left arrows are to the left of straight-on ones, and those to the left of right ones;
  - the junction really has a road going each way an arrow points.
Anything else is left alone.

Mapillary's answers are kept between weekly runs (cache file) so each week only the oldest or
missing junctions are fetched again. The key comes from the MAPILLARY_TOKEN environment variable
and is never printed. Mapillary data: CC BY-SA 4.0 (credited in the lane files' "source").
"""
import concurrent.futures
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
APPROACH_M = 60.0      # arrows this far before the junction
LANE_W = 3.5           # typical UK lane width
GAP_M = 1.8            # arrows further apart than this sideways are in different lanes
MAX_AGE_S = 6 * 365 * 86400   # ignore arrows not seen for six years
REFRESH_S = 28 * 86400        # fetch each junction again after four weeks
SOURCE_NOTE = "lane arrows partly from Mapillary (CC BY-SA 4.0)"

# Direction words: OpenStreetMap's, and the order they sit in across the road (left to right).
RANK = {"left": 0, "slight_left": 0, "through": 1, "slight_right": 2, "right": 2, "reverse": 3}


def parse_arrow(value):
    """Mapillary object value → set of OSM lane directions, or None if not a lane arrow."""
    if not value.startswith("marking--discrete--arrow--"):
        return None
    kind = value[len("marking--discrete--arrow--"):]
    if "u-turn" in kind or "uturn" in kind:
        return {"reverse"}
    out = set()
    if "left" in kind:
        out.add("left")
    if "right" in kind:
        out.add("right")
    if "straight" in kind:
        out.add("through")
    return out or None


def key(lon, lat):
    return (round(lon, 5), round(lat, 5))


def metres(lat):
    """Metres per degree of longitude and latitude here."""
    return 111320.0 * math.cos(math.radians(lat)), 110540.0


def bearing(a, b):
    kx, ky = metres(a[1])
    return math.degrees(math.atan2((b[0] - a[0]) * kx, (b[1] - a[1]) * ky)) % 360


def rel_angle(to, frm):
    """to − from, −180…180 (positive = to the right)."""
    return (to - frm + 540) % 360 - 180


def approach_lanes(t):
    """(lane count, tag to write, reverse geometry?) for the road's approach to its end, or None."""
    if t.get("junction") in ("roundabout", "circular"):
        return None
    oneway = t.get("oneway")
    if oneway in ("yes", "1", "-1") or t.get("highway") in ("motorway", "motorway_link"):
        if "turn:lanes" in t:
            return None
        n = t.get("lanes")
        tag = "turn:lanes"
    else:
        if "turn:lanes:forward" in t or "turn:lanes" in t:
            return None
        n = t.get("lanes:forward")
        tag = "turn:lanes:forward"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if not 2 <= n <= 5:
        return None
    return n, tag, oneway == "-1"


def tail(g, length=APPROACH_M + 10):
    """The last [length] metres of the line, as segments ending at the junction."""
    segs = []
    total = 0.0
    for i in range(len(g) - 1, 0, -1):
        a, b = g[i - 1], g[i]
        kx, ky = metres(b[1])
        d = math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * ky)
        segs.append((a, b, d, total))   # total = distance from b to the junction
        total += d
        if total >= length:
            break
    return segs


def place(p, segs):
    """(distance before the junction, sideways offset: + right of travel) of point p, or None."""
    best = None
    for a, b, d, to_end in segs:
        if d < 0.5:
            continue
        kx, ky = metres(b[1])
        ax, ay = (a[0] - b[0]) * kx, (a[1] - b[1]) * ky   # b at the origin
        px, py = (p[0] - b[0]) * kx, (p[1] - b[1]) * ky
        ux, uy = -ax / d, -ay / d                          # unit vector a → b
        t = -(px * ux + py * uy)                           # metres back from b
        if t < -2 or t > d + 2:
            continue
        side = px * uy - py * ux                           # + = right of travel
        dist = to_end + max(t, 0.0)
        if best is None or abs(side) < abs(best[1]):
            best = (dist, side)
    return best


def infer(g, n, two_way, features, exits, now):
    """turn:lanes for this approach from the arrows, or None. g ends at the junction."""
    segs = tail(g)
    if not segs:
        return None
    half = n * LANE_W / 2
    pts = []
    for lon, lat, value, seen in features:
        dirs = parse_arrow(value)
        if not dirs or (seen and now - seen / 1000 > MAX_AGE_S):
            continue
        pl = place((lon, lat), segs)
        if pl is None:
            continue
        dist, side = pl
        if not 3 <= dist <= APPROACH_M:
            continue
        # One-way: the road's line runs down the middle of its lanes. Two-way (UK, driving on the
        # left): our lanes are on the left of the line.
        if two_way:
            if not -(2 * half + 1.5) <= side <= 1.0:
                continue
        elif abs(side) > half + 1.5:
            continue
        pts.append((side, frozenset(dirs)))
    if len(pts) < n:
        return None
    pts.sort(key=lambda x: x[0])
    lanes = [[pts[0]]]
    for p in pts[1:]:
        if p[0] - lanes[-1][-1][0] > GAP_M:
            lanes.append([p])
        else:
            lanes[-1].append(p)
    if len(lanes) != n:
        return None
    sets = []
    for lane in lanes:
        kinds = {d for _, d in lane}
        if len(kinds) != 1:   # arrows in one lane disagree
            return None
        sets.append(next(iter(kinds)))
    # Left arrows on the left, right arrows on the right.
    for prev, cur in zip(sets, sets[1:]):
        if min(RANK[d] for d in cur) < min(RANK[d] for d in prev) or max(RANK[d] for d in cur) < max(RANK[d] for d in prev):
            return None
    # Every arrow must point at a real road leaving the junction.
    for d in set().union(*sets):
        if not any(fits(d, a) for a in exits):
            return None
    order = ["left", "slight_left", "through", "slight_right", "right", "reverse"]
    return "|".join(";".join(sorted(s, key=order.index)) for s in sets)


def fits(direction, angle):
    if direction == "left":
        return -160 <= angle <= -20
    if direction == "right":
        return 20 <= angle <= 160
    if direction == "through":
        return -45 <= angle <= 45
    if direction == "reverse":
        return True
    return False


def exits_at(roads_path, ends):
    """For each junction point: the compass bearings of the roads you can drive away along."""
    out = {k: [] for k in ends}
    with open(roads_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            props = feat.get("properties") or {}
            if props.get("highway") not in ROAD_CLASSES and props.get("highway") not in ("residential", "service", "living_street"):
                continue
            g = feat.get("geometry", {}).get("coordinates") or []
            oneway = props.get("oneway")
            fwd_only = oneway in ("yes", "1") or props.get("junction") == "roundabout" or props.get("highway") in ("motorway", "motorway_link")
            back_only = oneway == "-1"
            for i, c in enumerate(g):
                k = key(c[0], c[1])
                if k not in out:
                    continue
                if i + 1 < len(g) and not back_only:
                    out[k].append(bearing(c, g[i + 1]))
                if i > 0 and not fwd_only:
                    out[k].append(bearing(c, g[i - 1]))
    return out


def fetch(lon, lat, token, radius=APPROACH_M + 15):
    kx, ky = metres(lat)
    dx, dy = radius / kx, radius / ky
    bbox = f"{lon - dx:.6f},{lat - dy:.6f},{lon + dx:.6f},{lat + dy:.6f}"
    url = f"https://graph.mapillary.com/map_features?fields=object_value,geometry,last_seen_at&bbox={bbox}&limit=1000"
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r).get("data") or []
            return [[round(f["geometry"]["coordinates"][0], 6), round(f["geometry"]["coordinates"][1], 6),
                     f.get("object_value", ""), f.get("last_seen_at") or 0]
                    for f in data if str(f.get("object_value", "")).startswith("marking--discrete--arrow")]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Mapillary did not answer")


def main(roads, lanes_dir, cache_in, cache_out):
    token = os.environ.get("MAPILLARY_TOKEN")
    budget = int(os.environ.get("MAPILLARY_MAX_FETCH", "25000"))
    now = time.time()

    # Every lane square, and each road needing arrows (a road can sit in several squares).
    squares = {}
    for name in sorted(os.listdir(lanes_dir)):
        if name.startswith("lanes-") and name.endswith(".json"):
            with open(os.path.join(lanes_dir, name), encoding="utf-8") as f:
                squares[name] = json.load(f)
    cands = {}
    for data in squares.values():
        for w in data["ways"]:
            t = w["t"]
            if t.get("highway") not in ROAD_CLASSES or w["id"] in cands:
                continue
            a = approach_lanes(t)
            if a is None or len(w["g"]) < 2:
                continue
            n, tag, rev = a
            g = list(reversed(w["g"])) if rev else w["g"]
            cands[w["id"]] = (n, tag, g, tag.endswith(":forward"))
    ends = {key(*c[2][-1]) for c in cands.values()}
    print(f"roads with a lane count but no arrows: {len(cands):,}; junctions: {len(ends):,}", flush=True)

    cache = {}
    if cache_in and os.path.exists(cache_in):
        try:
            with gzip.open(cache_in, "rt", encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}

    # Fetch the missing junctions first, then the oldest.
    def ck(k):
        return f"{k[0]:.5f},{k[1]:.5f}"
    todo = sorted((k for k in ends if now - cache.get(ck(k), {}).get("t", 0) > REFRESH_S),
                  key=lambda k: cache.get(ck(k), {}).get("t", 0))[:budget]
    fetched = failed = 0
    if token and todo:
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            jobs = {pool.submit(fetch, k[0], k[1], token): k for k in todo}
            for job in concurrent.futures.as_completed(jobs):
                k = jobs[job]
                try:
                    cache[ck(k)] = {"t": int(now), "f": job.result()}
                    fetched += 1
                except Exception:
                    failed += 1
                if failed > 200 and failed > fetched:
                    print("::warning::Mapillary keeps failing; using what we have", flush=True)
                    for j in jobs:
                        j.cancel()
                    break
    elif not token:
        print("::warning::MAPILLARY_TOKEN not set: using last week's painted arrows only", flush=True)

    exits = exits_at(roads, ends)
    added = {}
    for wid, (n, tag, g, two_way) in cands.items():
        end = key(*g[-1])
        feats = cache.get(ck(end), {}).get("f") or []
        if not feats:
            continue
        here = exits.get(end) or []
        approach = bearing(g[-2], g[-1])
        # Leaving the way we came isn't a choice at the junction.
        angles = [rel_angle(b, approach) for b in here if abs(rel_angle(b, (approach + 180) % 360)) > 15]
        turn = infer(g, n, two_way, feats, angles, now)
        if turn:
            added[wid] = (tag, turn)

    for name, data in squares.items():
        hit = False
        for w in data["ways"]:
            if w["id"] in added:
                tag, turn = added[w["id"]]
                w["t"][tag] = turn
                w["t"]["turn:lanes:source"] = "mapillary"
                hit = True
        if hit:
            if SOURCE_NOTE not in data.get("source", ""):
                data["source"] = data.get("source", "") + "; " + SOURCE_NOTE
            with open(os.path.join(lanes_dir, name), "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))

    with gzip.open(cache_out, "wt", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
    stats = {"candidates": len(cands), "junctions": len(ends), "fetched": fetched, "failed": failed,
             "cached": len(cache), "roads_given_arrows": len(added)}
    print(json.dumps(stats))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as s:
            s.write(f"Painted arrows (Mapillary): {len(added):,} more roads with lane arrows "
                    f"(from {len(cands):,} with a lane count only; {fetched:,} junctions checked this week, "
                    f"{len(cache):,} known)\n\n")


def selftest():
    """Made-up junction: a one-way 2-lane road heading north into a T-junction (left and right)."""
    now = time.time()
    lat0, lon0 = 53.4, -2.15
    kx, ky = metres(lat0)

    def pt(east, north):
        return [lon0 + east / kx, lat0 + north / ky]
    g = [pt(0, -200), pt(0, 0)]
    left_right = [rel_angle(270, 0), rel_angle(90, 0)]
    arrows = [pt(-1.7, -20) + ["marking--discrete--arrow--left", 0], pt(-1.8, -35) + ["marking--discrete--arrow--left", 0],
              pt(1.8, -22) + ["marking--discrete--arrow--right", 0]]
    assert infer(g, 2, False, arrows, left_right, now) == "left|right", infer(g, 2, False, arrows, left_right, now)
    # Wrong way round (right arrow in the left lane): rejected.
    swapped = [pt(-1.7, -20) + ["marking--discrete--arrow--right", 0], pt(1.8, -22) + ["marking--discrete--arrow--left", 0]]
    assert infer(g, 2, False, swapped, left_right, now) is None
    # Only one lane's arrows seen: not enough.
    assert infer(g, 2, False, arrows[:2], left_right, now) is None
    # A straight-on arrow at a T-junction (no road ahead): rejected.
    straight = [pt(-1.7, -20) + ["marking--discrete--arrow--split-left-or-straight", 0], pt(1.8, -22) + ["marking--discrete--arrow--right", 0]]
    assert infer(g, 2, False, straight, left_right, now) is None
    with_ahead = left_right + [0.0]
    assert infer(g, 2, False, straight, with_ahead, now) == "left;through|right"
    # Two-way road, our two lanes on the left of the centre line.
    two = [pt(-1.8, -20) + ["marking--discrete--arrow--left", 0], pt(-5.3, -25) + ["marking--discrete--arrow--left", 0]]
    assert infer(g, 2, True, two, left_right, now) == "left|left"
    two = [pt(-5.3, -20) + ["marking--discrete--arrow--left", 0], pt(-1.8, -25) + ["marking--discrete--arrow--right", 0]]
    assert infer(g, 2, True, two, left_right, now) == "left|right"
    # Arrows past the junction or too far back don't count.
    far = [pt(-1.7, -90) + ["marking--discrete--arrow--left", 0], pt(1.8, 10) + ["marking--discrete--arrow--right", 0]]
    assert infer(g, 2, False, far, left_right, now) is None
    assert parse_arrow("marking--discrete--arrow--split-right-or-straight") == {"right", "through"}
    assert parse_arrow("marking--discrete--stop-line") is None
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        main(*sys.argv[1:5])
