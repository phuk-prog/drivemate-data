"""UK speed limits in half-degree squares like the lane files, so the app has every limit on the
phone (no live map-server lookups while driving).

Usage: limits.py maxspeed.geojsonseq out_dir [motorways.geojsonseq] [checks.md]
                 [--roads roads.geojsonseq --signs-cache-in in.json.gz --signs-cache-out out.json.gz]
       limits.py --selftest

Sources:
  1. OpenStreetMap maxspeed on roads (osmium tags-filter w/maxspeed, then osmium export
     -f geojsonseq --geometry-types=linestring -u type_id).
  2. Where OpenStreetMap has no limit: UK speed-limit signs spotted in Mapillary street photos
     (map features "regulatory--maximum-speed-limit-<mph>--g<n>", CC BY-SA 4.0), only with
     --roads (the lane step's roads file: osmium export -a type,id). Rules — never a guess:
       - a sign counts only for the road it stands beside (within 20 m, nearest road going the
         way the sign faces; skipped if another road is about as close) and only for traffic
         it faces (Mapillary's aligned_direction = the way the sign's face points, so it is read
         by traffic heading the opposite way); on a two-way road a sign facing an unknown
         direction is not used;
       - a sign's limit runs from the sign, in its direction of travel, to the next sign, the
         end of that stretch of road, or at most 1 km, whichever comes first;
       - variable (LED) signs, national-limit signs (whose meaning depends on the road type),
         odd values and signs not seen for five years are ignored;
       - on two-way roads the limit is published only where both directions are known and agree;
         a limit known for one direction only is written to "dir" (not used by the app yet).
     OpenStreetMap's own limits are never overwritten, with one exception: Welsh roads still
     mapped at 30 mph where 20 mph signs confirm the change (both directions, or the one way of
     a one-way road). Every Welsh 30-vs-20 case is listed in checks.md for fixing on OSM.
  3. National Highways (checked Oct 2026): no free download of permanent speed limits. Its open
     Network Model has no speed limits, the keyed "Road Limits and Features" API has none yet,
     and "Speed Managed Areas" are temporary roadworks limits. So nothing is used from it.
  Where nothing is known the road is left out (the app then shows no limit).

Mapillary answers are cached between weekly runs (cache file, refreshed after eight weeks,
at most MAPILLARY_SIGNS_MAX_FETCH requests a week). The key comes from MAPILLARY_TOKEN and is
never printed. Without a key last week's cached signs are used.

Writes out_dir/limits-<floor(lat*2)>_<floor(lon*2)>.json =
  {"ways": [[kmh, [[lon, lat], ...]], ...],   <- what the app reads (OwnMap.kt), unchanged shape
   "src": ["o" | "m", ...],                    <- one per "ways" entry: o = OpenStreetMap, m = signs
   "dir": [[kmh, [[lon, lat], ...]], ...],     <- one-direction limits, points in travel order
   "source": "..."}                            <- credits
Also writes a list of limits that look wrong (for a person to check on OpenStreetMap) to checks.md.
"""
import argparse
import concurrent.futures
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

MPH = 1.609344
UK_MPH = {10, 15, 20, 30, 40, 50, 60, 70}   # values a UK speed-limit sign can show
NEAR_M = 20.0          # a sign this close to the road's line stands beside it
SPAN_M = 1000.0        # furthest a sign's limit is carried along the road
MAX_AGE_S = 5 * 365 * 86400
REFRESH_S = 56 * 86400
TILE_LAT, TILE_LON = 0.09, 0.1       # Mapillary search boxes must be under 0.01 square degrees
SIGN_RE = re.compile(r"^regulatory--maximum-speed-limit-(\d+)--g\d+$")
OSM_CREDIT = "© OpenStreetMap contributors (ODbL)"
SIGN_CREDIT = "speed-limit signs from Mapillary (CC BY-SA 4.0)"
# Wales, roughly (the England border to within a few km; the coast pushed out to sea). Only used
# to pick which 30 mph roads to check against 20 mph signs and to head the report.
WALES = [(-3.32, 53.40), (-3.10, 53.27), (-2.93, 53.19), (-2.92, 53.10), (-2.76, 53.01), (-2.70, 52.96),
         (-2.82, 52.93), (-3.04, 52.87), (-3.03, 52.80), (-3.05, 52.70), (-3.12, 52.62), (-3.08, 52.52),
         (-3.03, 52.45), (-3.03, 52.34), (-2.99, 52.26), (-3.12, 52.17), (-3.10, 52.06), (-2.97, 51.93),
         (-2.66, 51.84), (-2.65, 51.62), (-2.68, 51.55), (-3.17, 51.42), (-3.56, 51.35), (-4.40, 51.50),
         (-4.95, 51.55), (-5.40, 51.70), (-5.40, 51.90), (-5.10, 52.08), (-4.55, 52.18), (-4.15, 52.40),
         (-4.15, 52.72), (-4.85, 52.75), (-4.70, 53.00), (-4.75, 53.33), (-4.45, 53.48), (-3.85, 53.38)]


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


def sign_mph(value):
    """Mapillary object value → mph shown on a fixed UK speed-limit sign, or None."""
    m = SIGN_RE.match(value or "")
    if not m:
        return None
    mph = int(m.group(1))
    return mph if mph in UK_MPH else None


def in_wales(lon, lat):
    inside = False
    j = len(WALES) - 1
    for i in range(len(WALES)):
        xi, yi = WALES[i]
        xj, yj = WALES[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


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


def mph_of(kmh):
    return round(kmh / MPH)


def length_m(pts):
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        kx = 111320.0 * math.cos(math.radians(a[1]))
        total += math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110540.0)
    return total


def bearing(a, b):
    kx = 111320.0 * math.cos(math.radians(a[1]))
    return math.degrees(math.atan2((b[0] - a[0]) * kx, (b[1] - a[1]) * 110540.0)) % 360


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def oneway_of(t):
    """+1 = only along the line, -1 = only against it, 0 = both ways."""
    ow = str(t.get("oneway") or "")
    if ow == "-1":
        return -1
    if ow in ("yes", "1", "true") or t.get("junction") in ("roundabout", "circular") or t.get("highway") in ("motorway", "motorway_link"):
        return 1
    return 0


# ---------------------------------------------------------------- Mapillary signs (cache + fetch)

def tile_of(lon, lat):
    return f"{math.floor(lat / TILE_LAT)}_{math.floor(lon / TILE_LON)}"


def tile_box(key):
    r, c = (int(x) for x in key.split("_"))
    return (c * TILE_LON, r * TILE_LAT, (c + 1) * TILE_LON, (r + 1) * TILE_LAT)


def fetch_box(box, token, depth=0, opener=None):
    """Speed-limit signs in a box (minlon, minlat, maxlon, maxlat) → (rows, requests used).
    Mapillary returns at most 2000 per request: a full answer is split into four smaller boxes."""
    url = ("https://graph.mapillary.com/map_features?fields=id,object_value,geometry,last_seen_at,aligned_direction"
           f"&bbox={box[0]:.6f},{box[1]:.6f},{box[2]:.6f},{box[3]:.6f}"
           "&object_values=regulatory--maximum-speed-limit-*&limit=2000")
    data = (opener or _get)(url, token)
    used = 1
    if len(data) >= 2000 and depth < 3:
        mx, my = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        rows = []
        for sub in ((box[0], box[1], mx, my), (mx, box[1], box[2], my), (box[0], my, mx, box[3]), (mx, my, box[2], box[3])):
            r, u = fetch_box(sub, token, depth + 1, opener)
            rows += r
            used += u
        return rows, used
    rows = []
    for f in data:
        mph = sign_mph(str(f.get("object_value", "")))
        c = (f.get("geometry") or {}).get("coordinates")
        if mph is None or not c:
            continue
        ad = f.get("aligned_direction")
        rows.append([round(c[0], 6), round(c[1], 6), mph, f.get("last_seen_at") or 0,
                     None if ad is None else round(float(ad), 1)])
    return rows, used


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("data") or []
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Mapillary did not answer")


def update_cache(tiles, cache, token, budget, now, opener=None):
    """Fetch tiles never seen, then the oldest, within the request budget. Returns stats."""
    todo = sorted((k for k in tiles if now - cache.get(k, {}).get("t", 0) > REFRESH_S),
                  key=lambda k: cache.get(k, {}).get("t", 0))
    fetched = failed = used = 0
    if not token:
        if todo:
            print("::warning::MAPILLARY_TOKEN not set: using last week's speed-limit signs only", flush=True)
        return {"tiles_wanted": len(tiles), "tiles_fetched": 0, "requests": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        it = iter(todo)
        running = {}
        while True:
            while len(running) < 8 and used + len(running) < budget:
                k = next(it, None)
                if k is None:
                    break
                running[pool.submit(fetch_box, tile_box(k), token, 0, opener)] = k
            if not running:
                break
            done, _ = concurrent.futures.wait(running, return_when=concurrent.futures.FIRST_COMPLETED)
            for job in done:
                k = running.pop(job)
                try:
                    rows, u = job.result()
                    cache[k] = {"t": int(now), "f": rows}
                    fetched += 1
                    used += u
                except Exception:
                    failed += 1
                    used += 1
            if failed > 200 and failed > fetched:
                print("::warning::Mapillary keeps failing; using what we have", flush=True)
                for j in running:
                    j.cancel()
                break
    return {"tiles_wanted": len(tiles), "tiles_fetched": fetched, "requests": used, "failed": failed}


# ---------------------------------------------------------------- signs → roads

class Sign:
    __slots__ = ("lon", "lat", "mph", "travel", "best", "second")

    def __init__(self, lon, lat, mph, travel):
        self.lon, self.lat, self.mph, self.travel = lon, lat, mph, travel
        self.best = None     # (distance, way id, name)
        self.second = None


def usable_signs(cache, now):
    out = []
    for entry in cache.values():
        for lon, lat, mph, seen, aligned in entry.get("f") or []:
            if seen and now - seen / 1000 > MAX_AGE_S:
                continue
            if mph not in UK_MPH:
                continue
            # The sign's face points at the drivers who read it: they travel the opposite way.
            travel = None if aligned is None else (aligned + 180) % 360
            out.append(Sign(lon, lat, mph, travel))
    return out


def project(p, coords, cum):
    """(distance from line in m, position along it in m, segment bearing) of point p."""
    kx, ky = 111320.0 * math.cos(math.radians(p[1])), 110540.0
    best = None
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        ax, ay = (a[0] - p[0]) * kx, (a[1] - p[1]) * ky
        bx, by = (b[0] - p[0]) * kx, (b[1] - p[1]) * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if best is None or d < best[0]:
            best = (d, cum[i] + t * (cum[i + 1] - cum[i]), bearing(a, b))
    return best


def cumulative(coords):
    cum = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum.append(cum[-1] + length_m([a, b]))
    return cum


def sign_dir(sign, seg_bearing, oneway):
    """Which way along the road the sign is for: +1, -1, or None (not this road / unknown)."""
    if sign.travel is None:
        return oneway if oneway else None
    d = angle_diff(sign.travel, seg_bearing)
    direction = 1 if d <= 45 else -1 if d >= 135 else None
    if direction is None or (oneway and direction != oneway):
        return None
    return direction


def assign_signs(roads_path, signs):
    """Each sign → the road it stands beside. Returns {way id: (tags, coords)} for roads given a sign."""
    cell = 0.0005
    grid = {}
    for i, s in enumerate(signs):
        cx, cy = math.floor(s.lon / cell), math.floor(s.lat / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                grid.setdefault((cx + dx, cy + dy), []).append(i)
    keep = {}
    if not grid:
        return keep
    with open(roads_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            g = feat.get("geometry") or {}
            c = g.get("coordinates") or []
            if g.get("type") != "LineString" or len(c) < 2:
                continue
            near = set()
            for a, b in zip(c, c[1:]):
                n = max(1, int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / cell) + 1)
                for k in range(n + 1):
                    x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
                    hit = grid.get((math.floor(x / cell), math.floor(y / cell)))
                    if hit:
                        near.update(hit)
            if not near:
                continue
            t = feat.get("properties") or {}
            wid = t.get("@id") or feat.get("id")
            ow = oneway_of(t)
            cum = cumulative(c)
            used = False
            for i in near:
                s = signs[i]
                d, _, seg_b = project((s.lon, s.lat), c, cum)
                if d > NEAR_M or sign_dir(s, seg_b, ow) is None:
                    continue
                cand = (d, wid, t.get("name") or t.get("ref") or "")
                if s.best is None or d < s.best[0]:
                    s.second, s.best = s.best, cand
                elif s.second is None or d < s.second[0]:
                    s.second = cand
                used = True
            if used:
                keep[wid] = (t, c)
    return keep


def confident(sign):
    """The nearest road is clearly the one: no other road nearly as close (unless it's the same
    named road carrying on past a junction)."""
    if sign.best is None:
        return False
    if sign.second is None or sign.second[0] > sign.best[0] * 1.5 + 3:
        return True
    return bool(sign.best[2]) and sign.best[2] == sign.second[2]


def sign_pieces(coords, oneway, signs):
    """Limits along one road from its signs. Returns (both, single): both = [(s0, s1, mph)] known
    for every direction the road can be driven; single = [(s0, s1, mph, direction)]."""
    cum = cumulative(coords)
    total = cum[-1]
    by_dir = {1: [], -1: []}
    for s in signs:
        _, pos, seg_b = project((s.lon, s.lat), coords, cum)
        d = sign_dir(s, seg_b, oneway)
        if d:
            by_dir[d].append((pos, s.mph))
    spans = {}
    for d, lst in by_dir.items():
        # Two signs within 20 m of each other that disagree: can't tell which is ours.
        lst.sort()
        bad = {i for i in range(len(lst)) for j in range(len(lst))
               if i != j and abs(lst[i][0] - lst[j][0]) < 20 and lst[i][1] != lst[j][1]}
        lst = [x for i, x in enumerate(lst) if i not in bad]
        out = []
        if d == 1:
            for i, (pos, mph) in enumerate(lst):
                end = min(lst[i + 1][0] if i + 1 < len(lst) else total, pos + SPAN_M, total)
                if end > pos:
                    out.append((pos, end, mph))
        else:
            for i, (pos, mph) in enumerate(lst):
                start = max(lst[i - 1][0] if i > 0 else 0.0, pos - SPAN_M, 0.0)
                if pos > start:
                    out.append((start, pos, mph))
        spans[d] = out

    def value(d, x):
        for a, b, mph in spans[d]:
            if a <= x < b:
                return mph
        return None

    cuts = sorted({0.0, total} | {v for d in spans for a, b, _ in spans[d] for v in (a, b)})
    both, single = [], []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 1:
            continue
        mid = (a + b) / 2
        f, r = value(1, mid), value(-1, mid)
        if oneway:
            mine = f if oneway == 1 else r
            if mine is not None:
                both.append([a, b, mine])
            continue
        if f is not None and f == r:
            both.append([a, b, f])
        else:
            if f is not None:
                single.append([a, b, f, 1])
            if r is not None:
                single.append([a, b, r, -1])
    return merge(both), merge(single)


def merge(pieces):
    out = []
    for p in pieces:
        if out and abs(out[-1][1] - p[0]) < 1e-6 and out[-1][2:] == p[2:]:
            out[-1][1] = p[1]
        else:
            out.append(list(p))
    return out


def substring(coords, cum, a, b):
    """The part of the line between a and b metres along it."""
    def at(x):
        for i in range(len(cum) - 1):
            if cum[i] <= x <= cum[i + 1]:
                t = 0 if cum[i + 1] == cum[i] else (x - cum[i]) / (cum[i + 1] - cum[i])
                p, q = coords[i], coords[i + 1]
                return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]
        return list(coords[-1])
    pts = [at(a)] + [list(coords[i]) for i in range(len(coords)) if a < cum[i] < b] + [at(b)]
    return [[round(p[0], 5), round(p[1], 5)] for p in pts]


# ---------------------------------------------------------------- the build

def build(src, out_dir, motorways_src=None, checks_path=None, roads=None, cache_in=None, cache_out=None):
    now = time.time()
    squares = {}

    def file_way(kmh, pts, src_code, key="ways"):
        for k in {f"{math.floor(p[1] * 2)}_{math.floor(p[0] * 2)}" for p in pts}:
            sq = squares.setdefault(k, {"ways": [], "src": [], "dir": []})
            if key == "ways":
                sq["ways"].append([round(kmh, 1), pts])
                sq["src"].append(src_code)
            else:
                sq["dir"].append([round(kmh, 1), pts])

    # --- signs: fetch/cache, then which road each stands beside
    overrides = {}      # OSM way id → pieces replacing (part of) it
    wales_checks = []   # (text, way id, name)
    sign_stats = {}
    if roads:
        cache = {}
        if cache_in and os.path.exists(cache_in):
            try:
                with gzip.open(cache_in, "rt", encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, ValueError):
                cache = {}
        tiles = set()
        with open(roads, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip("\x1e")
                if not line:
                    continue
                feat = json.loads(line)
                t = feat.get("properties") or {}
                c = (feat.get("geometry") or {}).get("coordinates") or []
                if not c or not isinstance(c[0], list):
                    continue
                kmh = parse_speed(t.get("maxspeed"))
                if kmh is None or (mph_of(kmh) == 30 and in_wales(*c[0])):
                    tiles.update(tile_of(p[0], p[1]) for p in c)
        budget = int(os.environ.get("MAPILLARY_SIGNS_MAX_FETCH", "4000"))
        sign_stats = update_cache(tiles, cache, os.environ.get("MAPILLARY_TOKEN"), budget, now)
        if cache_out:
            with gzip.open(cache_out, "wt", encoding="utf-8") as f:
                json.dump(cache, f, separators=(",", ":"))
        signs = usable_signs({k: v for k, v in cache.items() if k in tiles}, now)
        roads_hit = assign_signs(roads, signs)
        per_way = {}
        for s in signs:
            if confident(s):
                per_way.setdefault(s.best[1], []).append(s)
        filled = 0
        for wid, lst in per_way.items():
            t, c = roads_hit[wid]
            ow = oneway_of(t)
            base = parse_speed(t.get("maxspeed"))
            both, single = sign_pieces(c, ow, lst)
            cum = cumulative(c)
            name = t.get("name") or t.get("ref") or ""
            if base is None:
                for a, b, mph in both:
                    file_way(mph * MPH, substring(c, cum, a, b), "m")
                    filled += 1
                for a, b, mph, d in single:
                    pts = substring(c, cum, a, b)
                    file_way(mph * MPH, pts if d == 1 else pts[::-1], "m", key="dir")
            elif mph_of(base) == 30 and in_wales(*c[0]):
                said20 = [p for p in both if p[2] == 20]
                one20 = [p for p in single if p[2] == 20]
                if said20:
                    overrides[str(wid)] = (c, cum, said20)
                    wales_checks.append(("mapped 30 mph but 20 mph signs both ways: using 20 from the signs", wid, name))
                elif one20:
                    wales_checks.append(("mapped 30 mph but a 20 mph sign faces one direction: left at 30", wid, name))
        sign_stats.update({"signs": len(signs), "signs_placed": sum(len(v) for v in per_way.values()),
                           "stretches_from_signs": filled})

    # --- OpenStreetMap limits
    count = 0
    suspects = []  # (reason, way id, road name, limit text)
    ends = {}  # rounded end point -> [(way index, mph)]
    ways_info = []  # (id, name, highway, mph, length_m, first, last)
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
            wid = props.get("@id") or feat.get("id") or ""
            plain = str(wid).lstrip("w")
            if plain in overrides:
                c, cum, said20 = overrides[plain]
                last = 0.0
                for a, b, _ in said20:
                    if a - last > 1:
                        file_way(kmh, substring(c, cum, last, a), "o")
                    file_way(20 * MPH, substring(c, cum, a, b), "m")
                    last = b
                if cum[-1] - last > 1:
                    file_way(kmh, substring(c, cum, last, cum[-1]), "o")
                count += 1
                continue
            pts = [[round(p[0], 5), round(p[1], 5)] for p in simplify(geom["coordinates"])]
            if len(pts) < 2:
                continue
            # Checks: limits that don't fit the kind of road.
            hw, mph, name = props.get("highway", ""), mph_of(kmh), props.get("name") or props.get("ref") or ""
            if hw in ("residential", "living_street", "service") and mph > 40:
                suspects.append((f"{mph} mph on a {hw.replace('_', ' ')} road", wid, name, props.get("maxspeed")))
            if hw == "motorway" and mph <= 30:
                suspects.append((f"only {mph} mph on a motorway", wid, name, props.get("maxspeed")))
            ways_info.append((wid, name, hw, mph, length_m(pts), tuple(pts[0]), tuple(pts[-1])))
            for end in (tuple(pts[0]), tuple(pts[-1])):
                ends.setdefault(end, []).append((len(ways_info) - 1, mph))
            file_way(kmh, pts, "o")
            count += 1

    signed = any("m" in sq["src"] or sq["dir"] for sq in squares.values())
    source = OSM_CREDIT + ("; " + SIGN_CREDIT if signed else "")
    os.makedirs(out_dir, exist_ok=True)
    for key, sq in squares.items():
        sq["source"] = source
        with open(os.path.join(out_dir, f"limits-{key}.json"), "w", encoding="utf-8") as f:
            json.dump(sq, f, separators=(",", ":"))
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

    def link(wid):
        ref = str(wid).lstrip("w")
        return f"https://www.openstreetmap.org/way/{ref}" if ref.isdigit() else ""

    if checks_path:
        with open(checks_path, "w", encoding="utf-8") as f:
            f.write(f"## Speed limits to check ({len(suspects) + len(wales_checks)})\n\n")
            f.write("Each links to the road on OpenStreetMap; fixing it there fixes the app the next week.\n\n")
            if wales_checks:
                f.write(f"### Welsh roads mapped at 30 mph where street photos show 20 mph signs ({len(wales_checks)})\n\n")
                for reason, wid, name in wales_checks[:300]:
                    f.write(f"- {reason}" + (f" — {name}" if name else "") + (f" — {link(wid)}" if link(wid) else "") + "\n")
                if len(wales_checks) > 300:
                    f.write(f"\n…and {len(wales_checks) - 300} more.\n")
                f.write("\n### Other limits that look wrong\n\n")
            for reason, wid, name, raw in suspects[:300]:
                f.write(f"- {reason}" + (f" — {name}" if name else "") + (f" ({raw})" if raw else "") + (f" — {link(wid)}" if link(wid) else "") + "\n")
            if len(suspects) > 300:
                f.write(f"\n…and {len(suspects) - 300} more.\n")
    stats = {"limit_ways": count, "limit_squares": len(squares), "limits_to_check": len(suspects),
             "welsh_30_vs_20": len(wales_checks), **sign_stats}
    return stats


def selftest():
    import tempfile

    now = time.time()
    lat0, lon0 = 52.0, -1.5   # England (not Wales)
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0

    def pt(east, north, lon=lon0, lat=lat0):
        return [lon + east / kx, lat + north / ky]

    assert sign_mph("regulatory--maximum-speed-limit-30--g1") == 30
    assert sign_mph("regulatory--maximum-speed-limit-30--g3") == 30
    assert sign_mph("regulatory--maximum-speed-limit-led-50--g1") is None   # variable sign
    assert sign_mph("regulatory--maximum-speed-limit-35--g1") is None       # not a UK value
    assert sign_mph("regulatory--end-of-maximum-speed-limit--g1") is None   # national limit: depends on road
    assert in_wales(-3.18, 51.48) and in_wales(-4.08, 52.41) and in_wales(-2.99, 53.04)  # Cardiff, Aberystwyth, Wrexham
    assert not in_wales(-2.89, 53.19) and not in_wales(-2.24, 53.48) and not in_wales(-2.59, 51.45)  # Chester, Manchester, Bristol

    # Fetching (made-up answers, no network): a full answer (2000) is split into four boxes.
    calls = []

    def fake(url, token):
        calls.append(url)
        if len(calls) == 1:
            return [{}] * 2000
        return [{"object_value": "regulatory--maximum-speed-limit-30--g1", "geometry": {"coordinates": [-1.5, 52.0]},
                 "last_seen_at": 1, "aligned_direction": 90},
                {"object_value": "regulatory--maximum-speed-limit-led-60--g1", "geometry": {"coordinates": [-1.5, 52.0]}}]
    rows, used = fetch_box(tile_box(tile_of(-1.5, 52.0)), "t", 0, fake)
    assert used == 5 and len(rows) == 4 and rows[0][2:] == [30, 1, 90.0], (used, rows)
    assert "object_values=regulatory--maximum-speed-limit-*" in calls[0]
    cache = {}
    st = update_cache({"1_1", "1_2", "1_3"}, cache, "t", 2, now, lambda u, t: [])
    assert st["tiles_fetched"] == 2 and len(cache) == 2, st   # budget of two requests
    assert update_cache({"1_1"}, cache, None, 10, now)["tiles_fetched"] == 0   # no key: nothing fetched

    # A two-way road heading north, 2 km long.
    road = [pt(0, 0), pt(0, 1000), pt(0, 2000)]
    north, south = 0.0, 180.0
    # Signs for northbound traffic face south (aligned 180), for southbound face north (aligned 0).
    s1 = Sign(*pt(-4, 500), 30, north)
    s2 = Sign(*pt(4, 520), 30, south)
    both, single = sign_pieces(road, 0, [s1, s2])
    # Northbound: 500 → 1500 (1 km cap). Southbound: 520 → 0 (start of road). Shared: 500–520.
    assert len(both) == 1 and abs(both[0][0] - 500) < 2 and abs(both[0][1] - 520) < 2 and both[0][2] == 30, both
    assert any(p[3] == 1 and abs(p[1] - 1500) < 2 for p in single) and any(p[3] == -1 and p[0] < 1 for p in single), single
    # One-way road, sign with no known facing: used for the road's one direction.
    both, single = sign_pieces(road, 1, [Sign(*pt(-4, 300), 40, None)])
    assert both == [[both[0][0], both[0][1], 40]] and abs(both[0][0] - 300) < 2 and abs(both[0][1] - 1300) < 2 and not single
    # One-way road, sign facing the other carriageway: ignored.
    assert sign_pieces(road, 1, [Sign(*pt(4, 300), 40, south)]) == ([], [])
    # Two-way road, unknown facing: not used (can't tell which direction).
    assert sign_pieces(road, 0, [Sign(*pt(-4, 300), 40, None)]) == ([], [])
    # A sign on a side road (facing east-west traffic) doesn't count for this road.
    assert sign_pieces(road, 0, [Sign(*pt(-4, 300), 20, 90.0)]) == ([], [])
    # Two disagreeing signs at the same spot, same direction: neither used.
    assert sign_pieces(road, 1, [Sign(*pt(-4, 300), 20, north), Sign(*pt(-5, 305), 40, north)]) == ([], [])
    # A sign then a change: 30 from 200 m, 40 from 700 m (northbound, one-way).
    both, _ = sign_pieces(road, 1, [Sign(*pt(-4, 200), 30, north), Sign(*pt(-4, 700), 40, north)])
    assert [p[2] for p in both] == [30, 40] and abs(both[0][1] - 700) < 2, both

    # Whole build with files: a road with no limit, signs both ways; a Welsh road mapped 30, signs say 20.
    tmp = tempfile.mkdtemp()
    wl = (-3.18, 51.50)   # Cardiff
    welsh = [pt(0, 0, *wl), pt(0, 800, *wl)]
    side = [pt(0, 1000), pt(300, 1000)]   # a side road joining at the north end of `road`
    with open(os.path.join(tmp, "roads.geojsonseq"), "w", encoding="utf-8") as f:
        for i, (t, c) in enumerate([({"highway": "secondary", "name": "Test Road"}, road),
                                    ({"highway": "residential", "name": "Side Street"}, side),
                                    ({"highway": "residential", "name": "Heol Prawf", "maxspeed": "30 mph"}, welsh)]):
            f.write("\x1e" + json.dumps({"type": "Feature", "geometry": {"type": "LineString", "coordinates": c},
                                         "properties": {"@type": "way", "@id": 100 + i, **t}}) + "\n")
    with open(os.path.join(tmp, "maxspeed.geojsonseq"), "w", encoding="utf-8") as f:
        f.write("\x1e" + json.dumps({"type": "Feature", "id": "w102", "geometry": {"type": "LineString", "coordinates": welsh},
                                     "properties": {"highway": "residential", "name": "Heol Prawf", "maxspeed": "30 mph"}}) + "\n")
    ms = int(now * 1000)
    cache = {
        tile_of(*road[0]): {"t": int(now), "f": [
            pt(-4, 100) + [40, ms, 180.0], pt(4, 900) + [40, ms, 0.0],          # Test Road: 40 both ways, 100–900 m
            pt(250, 1004) + [20, ms, 90.0],                                      # Side Street sign (eastbound traffic faces west)
            pt(-4, 400) + [30, int((now - 7 * 365 * 86400) * 1000), 180.0]]},    # too old: ignored
        tile_of(*welsh[0]): {"t": int(now), "f": [pt(-4, 50, *wl) + [20, ms, 180.0], pt(4, 750, *wl) + [20, ms, 0.0]]},
    }
    with gzip.open(os.path.join(tmp, "cache.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(cache, f)
    os.environ.pop("MAPILLARY_TOKEN", None)   # no network in the self-test
    stats = build(os.path.join(tmp, "maxspeed.geojsonseq"), os.path.join(tmp, "out"), None, os.path.join(tmp, "checks.md"),
                  os.path.join(tmp, "roads.geojsonseq"), os.path.join(tmp, "cache.json.gz"), os.path.join(tmp, "cache-out.json.gz"))
    files = {n: json.load(open(os.path.join(tmp, "out", n), encoding="utf-8")) for n in os.listdir(os.path.join(tmp, "out"))}
    eng = files[f"limits-{math.floor(lat0 * 2)}_{math.floor(lon0 * 2)}.json"]
    # The app's reader: "ways" = [[kmh, [[lon, lat], ...]], ...], nothing else in each entry.
    for sq in files.values():
        assert all(len(w) == 2 and isinstance(w[0], float) and all(len(p) == 2 for p in w[1]) for w in sq["ways"])
        assert len(sq["src"]) == len(sq["ways"])
    mph_from_signs = sorted(round(w[0] / MPH) for w, s in zip(eng["ways"], eng["src"]) if s == "m")
    assert mph_from_signs == [40], (mph_from_signs, eng)   # Test Road, both directions signed
    # Side Street: two-way with a sign for one direction only → "dir", in travel order (westbound).
    side20 = [w for w in eng["dir"] if round(w[0] / MPH) == 20]
    assert len(side20) == 1 and side20[0][1][0][0] > side20[0][1][-1][0], eng["dir"]
    # Test Road's one-direction ends (north of 900 m northbound, south of 100 m southbound) are in "dir" too.
    assert sorted(round(w[0] / MPH) for w in eng["dir"]) == [20, 40, 40], eng["dir"]
    cym = files[f"limits-{math.floor(wl[1] * 2)}_{math.floor(wl[0] * 2)}.json"]
    kinds = sorted((round(w[0] / MPH), s) for w, s in zip(cym["ways"], cym["src"]))
    assert kinds == [(20, "m"), (30, "o"), (30, "o")], kinds   # 20 between the signs (50–750 m), OSM's 30 outside
    report = open(os.path.join(tmp, "checks.md"), encoding="utf-8").read()
    assert "Heol Prawf" in report and "using 20 from the signs" in report, report
    assert "Mapillary" in eng["source"] and stats["welsh_30_vs_20"] == 1, stats
    print("selftest ok")


def main():
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("motorways", nargs="?")
    ap.add_argument("checks", nargs="?")
    ap.add_argument("--roads")
    ap.add_argument("--signs-cache-in")
    ap.add_argument("--signs-cache-out")
    a = ap.parse_args()
    stats = build(a.src, a.out_dir, a.motorways, a.checks, a.roads, a.signs_cache_in, a.signs_cache_out)
    print(json.dumps(stats))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and a.roads:
        with open(summary, "a", encoding="utf-8") as s:
            s.write(f"Speed limits from street-photo signs (Mapillary): {stats.get('stretches_from_signs', 0):,} stretches filled "
                    f"where OpenStreetMap has none ({stats.get('signs_placed', 0):,} of {stats.get('signs', 0):,} signs placed on a road; "
                    f"{stats.get('tiles_fetched', 0):,} areas checked this week). Welsh 30-vs-20 to check: {stats['welsh_30_vs_20']}\n\n")
    # A real UK build has hundreds of thousands of limited roads: a tiny result means it broke.
    if stats["limit_ways"] < int(os.environ.get("LIMITS_MIN_WAYS", "1000")):
        raise SystemExit(f"::error::only {stats['limit_ways']} roads with a speed limit - build failed")


if __name__ == "__main__":
    main()
