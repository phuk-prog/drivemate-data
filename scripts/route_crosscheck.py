"""Differential route cross-check: Valhalla vs OSRM on the same OSM extract (detection only).

Runs the same deterministic journeys across Greater Manchester through two independent
open-source routing engines built from the *same* OpenStreetMap extract:

* Valhalla 3.6.3 (``auto`` costing, the engine DriveMate ships), via pyvalhalla;
* OSRM (car profile), via a local ``osrm-routed`` HTTP API with ``annotations=nodes``.

Each route is reduced to distance, duration and its OSM way sequence, then flagged for human
review:

* ``no_route_one_engine``: one engine routes, the other does not;
* ``distance_ratio``: the longer route is more than ``--ratio`` (default 1.25) times the shorter;
* ``restriction_violation``: a turn that breaks a simple node-via OSM ``no_*``/``only_*``
  restriction (parsed and selected exactly as ``restriction_acceptance.py`` does);
* ``oneway_violation``: a stretch driven against an explicit or implied one-way;
* ``u_turn``: the heading reverses part way along the route.

A disagreement is a lead, not proof: OSM may be wrong, either engine may be wrong, or both
may be legal. Nothing is corrected automatically, and no Google/TomTom/Waze/Apple data is
used. The job fails only on restriction or one-way violations made by Valhalla, plus restriction
types Valhalla 3.6.3 is known not to enforce (the same blockers as restriction_acceptance).
"""
import argparse
from collections import Counter
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import restriction_acceptance as ra  # noqa: E402

SCHEMA = 1
DEFAULT_SEED = 20261010
DEFAULT_RATIO = 1.25
# Greater Manchester (approximate county bounds): south, west, north, east.
GM_BBOX = (53.34, -2.73, 53.69, -1.91)
# Straight-line distance bands (km); road distance is usually 1.2-1.5x longer.
BANDS = {"short": (0.5, 3.0), "medium": (3.0, 15.0), "long": (15.0, 40.0)}
UTURN_DEGREES = 150.0
APPROACH_TOLERANCE = 60.0
MIN_DIRECTION_METRES = 2.0
# A heading is only trusted over a stretch at least this long; shorter hops (duplicate or
# near-duplicate points, zigzags between neighbouring nodes) are noise, not driving direction.
UTURN_WINDOW_METRES = 15.0
UTURN_MIN_CHORD_METRES = 10.0
UTURN_MERGE_METRES = 30.0
VIA_HINT_METRES = 400.0

# Fixed journeys from the user's reported drives. Coordinates other than SK8 2EZ are
# approximate town-centre/junction points; ``via`` is checked only as information.
NAMED_JOURNEYS = [
    {"id": "named-stockport-sk8-2ez", "name": "Stockport town centre to SK8 2EZ (Menai Grove)",
     "origin": (53.4106, -2.1575), "destination": (53.395466, -2.194193)},
    {"id": "named-piccadilly-airport", "name": "Manchester Piccadilly to Manchester Airport",
     "origin": (53.4774, -2.2309), "destination": (53.3650, -2.2728)},
    {"id": "named-pyramid-m60-j1", "name": "Stockport centre to Cheadle through the Pyramid roundabout (M60 J1)",
     "origin": (53.4087, -2.1560), "destination": (53.3936, -2.2120),
     "via": (53.4106, -2.1655), "via_name": "Pyramid roundabout, M60 J1"},
    {"id": "named-m60-j4-m56", "name": "Stockport to Wythenshawe through M60 J4 (the M56 split)",
     "origin": (53.4106, -2.1575), "destination": (53.3830, -2.2650),
     "via": (53.4128, -2.2095), "via_name": "M60 J4 / M56 split"},
]

BLOCKING_TYPES = {"restriction_violation", "oneway_violation"}
WEIGHTS = {"restriction_violation": 100.0, "oneway_violation": 100.0, "no_route_one_engine": 50.0,
           "u_turn": 10.0}


# --------------------------------------------------------------------------- data model

@dataclass
class Journey:
    id: str
    category: str
    origin: tuple
    destination: tuple
    name: str = None
    via: tuple = None
    via_name: str = None

    def as_dict(self):
        d = {"id": self.id, "category": self.category, "origin": list(self.origin),
             "destination": list(self.destination)}
        if self.name:
            d["name"] = self.name
        if self.via:
            d["via"], d["via_name"] = list(self.via), self.via_name
        return d


@dataclass
class Segment:
    """A routed stretch on one OSM way (``way_id`` None when it could not be mapped)."""
    way_id: int
    start: tuple
    end: tuple
    begin_heading: float = None
    end_heading: float = None
    start_node: int = None
    end_node: int = None
    # Node-pair routes only: (way, directions) for every way holding this pair as two consecutive
    # nodes. ``directions`` are FORWARD/BACKWARD: how the way's node order is walked start -> end.
    candidates: tuple = ()


@dataclass
class Route:
    distance_m: float
    duration_s: float
    segments: list = field(default_factory=list)
    # Why the node-based checks (restriction, one-way, U-turn) cannot be trusted for this route.
    unverifiable: str = None

    def way_sequence(self):
        out = []
        for s in self.segments:
            if s.way_id is not None and (not out or out[-1] != s.way_id):
                out.append(s.way_id)
        return out


class Router:
    """Minimal router interface. ``route`` returns a Route, or None when no route exists
    (``last_reason`` then says why). Raise for unexpected engine failures."""
    name = "router"
    last_reason = None

    def route(self, origin, destination):  # pragma: no cover - interface only
        raise NotImplementedError


# --------------------------------------------------------------------------- journeys

def destination_point(origin, bearing_deg, distance_m):
    r = 6371008.8
    la1, lo1, b = math.radians(origin[0]), math.radians(origin[1]), math.radians(bearing_deg)
    d = distance_m / r
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def inside(point, bbox=GM_BBOX):
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def generate_journeys(n, seed=DEFAULT_SEED, bbox=GM_BBOX, include_named=True):
    """``n`` seeded random journeys split evenly across the distance bands, plus named ones."""
    rng = random.Random(seed)
    journeys = []
    if include_named:
        for j in NAMED_JOURNEYS:
            journeys.append(Journey(j["id"], "named", tuple(j["origin"]), tuple(j["destination"]),
                                    j["name"], tuple(j["via"]) if j.get("via") else None,
                                    j.get("via_name")))
    names = list(BANDS)
    for i in range(n):
        category = names[i % len(names)]
        low, high = BANDS[category]
        for _ in range(1000):
            origin = (rng.uniform(bbox[0], bbox[2]), rng.uniform(bbox[1], bbox[3]))
            dest = destination_point(origin, rng.uniform(0.0, 360.0), rng.uniform(low, high) * 1000.0)
            if inside(dest, bbox):
                break
        else:  # pragma: no cover - the bands all fit comfortably in the box
            raise ValueError("could not place a journey inside the bounding box")
        journeys.append(Journey(f"{category}-{i:04d}", category,
                                (round(origin[0], 6), round(origin[1], 6)),
                                (round(dest[0], 6), round(dest[1], 6))))
    return journeys


# --------------------------------------------------------------------------- OSM index

@dataclass
class Restriction:
    relation: int
    kind: str
    from_way: int
    via_node: int
    to_way: int
    via: tuple
    approach_headings: list
    engine_unsupported: bool = False


class OsmIndex:
    """Highway ways, node coordinates, node-pair to way lookup and selected restrictions."""

    def __init__(self, ways, relations, coords, rewritten=frozenset()):
        self.ways, self.coords = ways, coords
        # (restriction, relation id) pairs restriction_rewrite.py turned into enforced no_* relations.
        self.rewritten = frozenset(rewritten)
        self.pairs = {}
        self.edges = {}  # (u, v) -> {way: {FORWARD/BACKWARD as walked u -> v}}, both orders stored
        for wid, (_, nodes) in ways.items():
            for u, v in zip(nodes, nodes[1:]):
                if u == v:
                    continue
                self.pairs.setdefault((min(u, v), max(u, v)), wid)
                self.edges.setdefault((u, v), {}).setdefault(wid, set()).add(ra.FORWARD)
                self.edges.setdefault((v, u), {}).setdefault(wid, set()).add(ra.BACKWARD)
        self.restrictions = {}
        self.skipped = Counter()
        self.unsupported_relations = []
        for relation in relations:
            ok, reason, _ = ra.classify(relation, ways)
            if not ok:
                self.skipped[reason] += 1
                continue
            r = self._restriction(relation)
            if r is None:
                self.skipped["no_drivable_approach_or_location"] += 1
                continue
            self.restrictions.setdefault(r.from_way, []).append(r)
            if r.engine_unsupported:
                self.unsupported_relations.append(r)

    def _restriction(self, relation):
        ident, tags, members = relation
        from_way = next(n for _, n, role in members if role == "from")
        to_way = next(n for _, n, role in members if role == "to")
        via = next(n for _, n, role in members if role == "via")
        if from_way not in self.ways or to_way not in self.ways or via not in self.coords:
            return None
        from_tags, from_nodes = self.ways[from_way]
        if from_nodes.count(via) != 1:
            return None
        headings = []
        for d in ra.drivable_directions(from_tags):
            leg = ra.leg_towards(from_nodes, via, d)
            if len(leg) > 1 and leg[-2] in self.coords:
                headings.append(ra.bearing(self.coords[leg[-2]], self.coords[via]))
        if not headings:
            return None
        kind = tags["restriction"]
        return Restriction(ident, kind, from_way, via, to_way, self.coords[via], headings,
                           kind in ra.ENGINE_UNSUPPORTED and (kind, ident) not in self.rewritten)

    def way_for_pair(self, u, v):
        return self.pairs.get((min(u, v), max(u, v)))

    def edge_ways(self, u, v):
        """{way: directions walked going u -> v} for ways with u, v as consecutive nodes."""
        return self.edges.get((u, v), {})

    def direction(self, seg):
        """FORWARD/BACKWARD along the way's node order, or None when it cannot be told."""
        tags_nodes = self.ways.get(seg.way_id)
        if tags_nodes is None:
            return None
        nodes = tags_nodes[1]
        if seg.start_node is not None and seg.end_node is not None:
            iu = [i for i, n in enumerate(nodes) if n == seg.start_node]
            iv = [i for i, n in enumerate(nodes) if n == seg.end_node]
            for a in iu:
                for b in iv:
                    if abs(a - b) == 1:
                        return ra.FORWARD if b > a else ra.BACKWARD
            return None
        pts = [self.coords[n] for n in nodes if n in self.coords]
        if len(pts) != len(nodes):
            return None
        a, b = _position(pts, seg.start), _position(pts, seg.end)
        if a is None or b is None:
            return None
        diff = b - a
        if nodes[0] == nodes[-1]:  # closed way (e.g. a roundabout): take the shorter way round
            total = ra.length(pts)
            diff = (diff + total / 2.0) % total - total / 2.0
        if abs(diff) < MIN_DIRECTION_METRES:
            return None
        return ra.FORWARD if diff > 0 else ra.BACKWARD


def _position(points, p, tolerance=15.0):
    """Distance along ``points`` of the projection of ``p`` (None when farther than tolerance)."""
    best, best_pos, run = None, None, 0.0
    lat0 = math.radians(p[0])
    for a, b in zip(points, points[1:]):
        seg = ra.haversine(a, b)
        ax, ay = (a[1] - p[1]) * math.cos(lat0), a[0] - p[0]
        bx, by = (b[1] - p[1]) * math.cos(lat0), b[0] - p[0]
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        t = 0.0 if denom == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / denom))
        q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        dist = ra.haversine(q, p)
        if best is None or dist < best:
            best, best_pos = dist, run + seg * t
        run += seg
    return best_pos if best is not None and best <= tolerance else None


def load_index(opl, rewritten=frozenset()):
    ways, relations = ra.read_opl(opl)
    wanted = {n for _, nodes in ways.values() for n in nodes}
    return OsmIndex(ways, relations, ra.read_node_coords(opl, wanted), rewritten)


# --------------------------------------------------------------------------- engines

class OsrmRouter(Router):
    """Local osrm-routed HTTP API; ``annotations=nodes`` gives OSM node IDs mapped to ways."""
    name = "osrm"

    def __init__(self, base_url, index, timeout=30):
        self.base, self.index, self.timeout = base_url.rstrip("/"), index, timeout

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:  # osrm-routed answers 400 for NoRoute/NoSegment
            return json.loads(error.read() or b"{}")

    def nearest(self, point):
        data = self._get(f"/nearest/v1/driving/{point[1]:.6f},{point[0]:.6f}?number=1")
        if data.get("code") != "Ok" or not data.get("waypoints"):
            return None
        lon, lat = data["waypoints"][0]["location"]
        return round(lat, 6), round(lon, 6)

    def route(self, origin, destination):
        self.last_reason = None
        query = urllib.parse.urlencode({"overview": "false", "steps": "false", "annotations": "nodes"})
        data = self._get(f"/route/v1/driving/{origin[1]:.6f},{origin[0]:.6f};"
                         f"{destination[1]:.6f},{destination[0]:.6f}?{query}")
        if data.get("code") in ("NoRoute", "NoSegment"):
            self.last_reason = data["code"]
            return None
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message', '')}"[:200])
        best = data["routes"][0]
        nodes = []
        for leg in best["legs"]:
            for n in leg.get("annotation", {}).get("nodes", []):
                if not nodes or nodes[-1] != n:
                    nodes.append(n)
        segments = segments_from_nodes(nodes, self.index)
        return Route(best["distance"], best["duration"], segments, node_list_problem(nodes, segments))


def segments_from_nodes(nodes, index):
    """One Segment per consecutive node pair; a pair that is a real OSM edge gets its way(s).

    Consecutive duplicate nodes are dropped. A pair that is not two consecutive nodes of any
    indexed way is left unmapped (``way_id`` None) instead of being guessed. Where several ways
    share the pair, the previous segment's way is kept if possible.
    """
    clean = [n for i, n in enumerate(nodes) if i == 0 or n != nodes[i - 1]]
    segments, previous = [], None
    for u, v in zip(clean, clean[1:]):
        a, b = index.coords.get(u), index.coords.get(v)
        heading = ra.bearing(a, b) if a and b and a != b else None
        found = index.edge_ways(u, v)
        way_id, candidates = None, ()
        if found:
            candidates = tuple((w, frozenset(d)) for w, d in found.items())
            way_id = previous if previous in found else candidates[0][0]
        segments.append(Segment(way_id, a, b, heading, heading, u, v, candidates))
        previous = way_id
    return segments


def node_list_problem(nodes, segments):
    """Why an OSRM ``annotations=nodes`` list is not a trustworthy path (None when it is).

    The first real run (304 journeys) showed every flagged OSRM route contained node pairs that
    are not consecutive nodes of any indexed way, and none of the 31 routes with every pair mapped
    was flagged. OSRM compresses its graph and drops or reorders nodes (ferries and ways the index
    does not hold also appear), so such a list does not reproduce the driven path: one-way, U-turn
    and restriction judgements on it are tool artefacts. A path that returns to the node it came
    from is also not something a route can do.
    """
    unmapped = sum(1 for s in segments if s.way_id is None)
    if unmapped:
        return f"{unmapped} of {len(segments)} node pairs are not edges of an indexed way"
    clean = [n for i, n in enumerate(nodes) if i == 0 or n != nodes[i - 1]]
    if any(a == c for a, c in zip(clean, clean[2:])):
        return "node list doubles back on itself"
    return None


class ValhallaRouter(Router):
    """pyvalhalla Actor (``auto``); the route's own shape is decoded to OSM ways with edge_walk."""
    name = "valhalla"

    def __init__(self, graph):
        self._inner = ra.ValhallaRouter(graph)  # same config and tile handling as the acceptance job
        self.actor = self._inner.actor

    def route(self, origin, destination):
        self.last_reason = None
        request = {"locations": [{"lat": origin[0], "lon": origin[1]},
                                 {"lat": destination[0], "lon": destination[1]}],
                   "costing": "auto", "directions_type": "none"}
        try:
            trip = json.loads(self.actor.route(json.dumps(request)))["trip"]
        except RuntimeError as error:
            code = ra.error_code(error)
            if code == 442 or (code is not None and 170 <= code <= 172):
                self.last_reason = f"Valhalla error {code}"
                return None
            raise
        shape = trip["legs"][0]["shape"]
        attributes = None
        for mode in ("edge_walk", "map_snap"):
            try:
                attributes = json.loads(self.actor.trace_attributes(json.dumps({
                    "encoded_polyline": shape, "shape_match": mode, "costing": "auto",
                    "filters": {"action": "include", "attributes": [
                        "edge.way_id", "edge.begin_heading", "edge.end_heading",
                        "edge.begin_shape_index", "edge.end_shape_index", "shape"]}})))
                break
            except RuntimeError:
                continue
        if attributes is None:
            raise RuntimeError("Valhalla route not decodable to OSM ways")
        points = ra.decode_polyline(attributes["shape"])
        segments = []
        for e in attributes.get("edges", []):
            begin = points[e.get("begin_shape_index", 0)]
            end = points[e["end_shape_index"]]
            segments.append(Segment(int(e["way_id"]), begin, end,
                                    ra._heading(e, "begin_heading"), ra._heading(e, "end_heading")))
        summary = trip["summary"]
        return Route(summary["length"] * 1000.0, summary["time"], segments)


# --------------------------------------------------------------------------- checks

def _at_via(seg, r):
    if seg.end_node is not None:
        return seg.end_node == r.via_node
    return seg.end is not None and ra.haversine(seg.end, r.via) <= ra.VIA_MATCH_METRES


def _turn_angle(a, b):
    if a.end_heading is None or b.begin_heading is None:
        return None
    return ra.angle_between(a.end_heading, b.begin_heading)


def restriction_violations(route, index):
    found, seen = [], set()
    for a, b in zip(route.segments, route.segments[1:]):
        if b.way_id is None:
            continue
        for r in index.restrictions.get(a.way_id, ()):
            if not _at_via(a, r):
                continue
            if a.end_heading is not None and min(
                    ra.angle_between(a.end_heading, h) for h in r.approach_headings) > APPROACH_TOLERANCE:
                continue  # arrived from the other side of the via node: not this restriction's approach
            angle = _turn_angle(a, b)
            uturn = angle is not None and angle >= ra.UTURN_DEGREES
            same = b.way_id == r.from_way
            if r.kind.startswith("no_"):
                bad = b.way_id == r.to_way and (r.to_way != r.from_way or uturn)
            else:
                ok = b.way_id == r.to_way and (r.to_way != r.from_way or uturn)
                bad = not ok and not (same and angle is None)
            if bad and r.relation not in seen:
                seen.add(r.relation)
                found.append({"relation": r.relation, "restriction": r.kind, "from_way": r.from_way,
                              "via_node": r.via_node, "to_way": r.to_way, "taken_way": b.way_id,
                              "engine_unsupported": r.engine_unsupported,
                              "osm_url": f"https://www.openstreetmap.org/relation/{r.relation}"})
    return found


def _restricted(index, wid):
    """Allowed directions when the way is a one-way, else None (two-way/unknown: never assumed)."""
    allowed = ra.drivable_directions(index.ways[wid][0])
    return allowed if allowed and len(allowed) == 1 else None


def oneway_violations(route, index):
    """Stretches driven against a one-way.

    Node-pair routes (OSRM) are judged by the pair itself: it must be two consecutive nodes of
    the way, walked opposite to the allowed direction, and no other way sharing that pair may
    permit it. Shared junction nodes, crossings of unrelated ways and unmapped pairs never count.
    """
    found, seen = [], set()
    for s in route.segments:
        if s.way_id is None or s.way_id not in index.ways:
            continue
        wid = None
        if s.candidates:
            for cand, directions in s.candidates:
                allowed = _restricted(index, cand) if cand in index.ways else None
                if allowed is None or directions & allowed:
                    wid = None
                    break
                wid = wid or cand
        else:
            allowed = _restricted(index, s.way_id)
            d = index.direction(s) if allowed is not None else None
            if d is not None and d not in allowed:
                wid = s.way_id
        if wid is None or wid in seen:
            continue
        seen.add(wid)
        found.append({"way": wid, "oneway": index.ways[wid][0].get("oneway", "implied"),
                      "at": [round(s.start[0], 6), round(s.start[1], 6)] if s.start else None,
                      "osm_url": f"https://www.openstreetmap.org/way/{wid}"})
    return found


def _usable(seg):
    """Both ends known and not an unmapped (non-edge) node pair."""
    if seg.start is None or seg.end is None:
        return False
    return not (seg.way_id is None and seg.start_node is not None)


def _chord_heading(segments, i, forward):
    """Heading of the stretch (>= UTURN_WINDOW_METRES where possible) starting at segment i (forward)
    or ending at segment i (backward)."""
    junction = segments[i].start if forward else segments[i].end
    far = None
    for j in (range(i, len(segments)) if forward else range(i, -1, -1)):
        seg = segments[j]
        if not _usable(seg):
            break
        far = seg.end if forward else seg.start
        if ra.haversine(junction, far) >= UTURN_WINDOW_METRES:
            break
    if far is None or ra.haversine(junction, far) < UTURN_MIN_CHORD_METRES:
        return None
    return ra.bearing(junction, far) if forward else ra.bearing(far, junction)


def u_turns(route):
    """Heading reversals measured over stretches of 10-15 m or more, never point to point.

    Each side of a junction is the chord from the junction to a point about 15 m along the route
    (or the longest available if at least 10 m), so duplicate points and tiny zigzags have no
    heading and cannot produce a reversal. Nearby repeats of one reversal are merged.
    """
    segs, found, last = route.segments, [], None
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if not (_usable(a) and _usable(b)):
            continue
        before, after = _chord_heading(segs, i, False), _chord_heading(segs, i + 1, True)
        if before is None or after is None:
            continue
        angle = ra.angle_between(before, after)
        if angle < UTURN_DEGREES:
            continue
        if last is not None and ra.haversine(last, a.end) <= UTURN_MERGE_METRES:
            continue
        last = a.end
        found.append({"at": [round(a.end[0], 6), round(a.end[1], 6)], "angle": round(angle, 1),
                      "from_way": a.way_id, "to_way": b.way_id})
    return found


def passes_near(route, point, metres=VIA_HINT_METRES):
    return any(s.end is not None and ra.haversine(s.end, point) <= metres for s in route.segments)


def osm_directions_url(journey):
    o, d = journey.origin, journey.destination
    return ("https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route="
            f"{o[0]:.6f}%2C{o[1]:.6f}%3B{d[0]:.6f}%2C{d[1]:.6f}")


def compare(journey, routes, reasons, errors, index, ratio_limit):
    """Flags for one journey from the engines' results (routes: name -> Route or None)."""
    flags = []
    engines = {}
    for name, route in routes.items():
        if name in errors:
            engines[name] = {"status": "error", "detail": errors[name]}
            continue
        if route is None:
            engines[name] = {"status": "no_route", "detail": reasons.get(name)}
            continue
        engines[name] = {"status": "ok", "distance_m": round(route.distance_m, 1),
                         "duration_s": round(route.duration_s, 1), "ways": route.way_sequence(),
                         "unmapped_segments": sum(1 for s in route.segments if s.way_id is None)}
        if journey.via:
            engines[name]["passes_named_via"] = passes_near(route, journey.via)
        if route.unverifiable:
            engines[name]["unverifiable"] = route.unverifiable
            continue  # node-based checks would only measure the tool, not the engine
        for v in restriction_violations(route, index):
            flags.append({"type": "restriction_violation", "engine": name, **v})
        for v in oneway_violations(route, index):
            flags.append({"type": "oneway_violation", "engine": name, **v})
        for v in u_turns(route):
            flags.append({"type": "u_turn", "engine": name, **v})
    ok = [n for n, e in engines.items() if e["status"] == "ok"]
    unroutable = [n for n, e in engines.items() if e["status"] == "no_route"]
    if len(ok) == 1 and unroutable:
        flags.append({"type": "no_route_one_engine", "routed": ok[0], "no_route": unroutable[0]})
    ratio = None
    if len(ok) == 2:
        d = sorted(engines[n]["distance_m"] for n in ok)
        if d[0] > 0:
            ratio = round(d[1] / d[0], 3)
            if ratio > ratio_limit:
                longer = max(ok, key=lambda n: engines[n]["distance_m"])
                flags.append({"type": "distance_ratio", "ratio": ratio, "longer": longer,
                              "limit": ratio_limit})
    score = sum(WEIGHTS.get(f["type"], 0.0) for f in flags)
    score += sum((f["ratio"] - 1.0) * 100.0 for f in flags if f["type"] == "distance_ratio")
    return {**journey.as_dict(), "engines": engines, "distance_ratio": ratio, "flags": flags,
            "score": round(score, 2), "osm_directions_url": osm_directions_url(journey)}


def blocking(flag):
    return flag["type"] in BLOCKING_TYPES and flag.get("engine") == "valhalla"


def run(journeys, routers, index, ratio_limit=DEFAULT_RATIO, snap=None, region="greater-manchester",
        source=None):
    results = []
    for journey in journeys:
        if snap is not None:
            o, d = snap(journey.origin), snap(journey.destination)
            if o and d:
                journey = Journey(journey.id, journey.category, o, d, journey.name, journey.via,
                                  journey.via_name)
        routes, reasons, errors = {}, {}, {}
        for router in routers:
            try:
                routes[router.name] = router.route(journey.origin, journey.destination)
                reasons[router.name] = router.last_reason
            except Exception as error:  # recorded per journey, never a pass
                routes[router.name] = None
                errors[router.name] = str(error)[:200]
        results.append(compare(journey, routes, reasons, errors, index, ratio_limit))
    counts = Counter(f["type"] + ":" + f.get("engine", "both") for r in results for f in r["flags"])
    flag_journeys = Counter(t for r in results for t in {f["type"] for f in r["flags"]})
    statuses = Counter(n + ":" + e["status"] for r in results for n, e in r["engines"].items())
    unverifiable = Counter(n for r in results for n, e in r["engines"].items() if e.get("unverifiable"))
    valhalla_flags = [dict(f, journey=r["id"]) for r in results for f in r["flags"] if blocking(f)]
    unsupported = [{"relation": r.relation, "restriction": r.kind, "from_way": r.from_way,
                    "via_node": r.via_node, "to_way": r.to_way,
                    "osm_url": f"https://www.openstreetmap.org/relation/{r.relation}"}
                   for r in sorted(index.unsupported_relations, key=lambda x: x.relation)]
    blockers = len(valhalla_flags) + len(unsupported)
    flagged = sorted((r for r in results if r["flags"]), key=lambda r: (-r["score"], r["id"]))
    return {
        "schema": SCHEMA, "region": region, "source": source or {},
        "engines": [router.name for router in routers], "ratio_limit": ratio_limit,
        "journeys": len(results), "flagged_journeys": len(flagged),
        "engine_status": dict(sorted(statuses.items())),
        "unverifiable_routes": dict(sorted(unverifiable.items())),
        "flag_counts": dict(sorted(counts.items())),
        "journeys_with_flag": dict(sorted(flag_journeys.items())),
        "restrictions_indexed": sum(len(v) for v in index.restrictions.values()),
        "restrictions_skipped": dict(sorted(index.skipped.items())),
        "valhalla_violations": valhalla_flags,
        "engine_unsupported": unsupported,
        "known_routing_safety_blockers": blockers,
        "accepted": blockers == 0,
        "results": results,
        "top_flagged": [r["id"] for r in flagged[:50]],
        "scope": ("Differential check of Valhalla against OSRM on the same OSM extract. Detection only: "
                  "flags are leads for human review; no map data is corrected."),
        "limitations": [
            "Both engines read the same OSM data, so an error in OSM is invisible when both obey it.",
            "Only simple node-via restrictions are checked; conditional, vehicle-specific and way-via ones are skipped.",
            "Journey bands use straight-line distance; endpoints are snapped to the nearest road by OSRM.",
            "No live traffic, signage or lane checks; agreement is not proof that a route is legal.",
            "only_u_turn restrictions are not enforced by Valhalla 3.6.3 and stay blockers until fixed.",
        ],
    }


# --------------------------------------------------------------------------- output

def _flag_text(f):
    t = f["type"]
    if t == "restriction_violation":
        extra = " (type not enforced by Valhalla 3.6.3)" if f.get("engine_unsupported") else ""
        return (f"{f['engine']}: breaks [{f['restriction']} r{f['relation']}]({f['osm_url']}) "
                f"w{f['from_way']} -> n{f['via_node']} -> w{f['taken_way']}{extra}")
    if t == "oneway_violation":
        return f"{f['engine']}: against one-way [w{f['way']}]({f['osm_url']})"
    if t == "u_turn":
        return f"{f['engine']}: U-turn {f['angle']} deg at {f['at'][0]}, {f['at'][1]}"
    if t == "no_route_one_engine":
        return f"only {f['routed']} found a route ({f['no_route']} did not)"
    if t == "distance_ratio":
        return f"{f['longer']} route is {f['ratio']}x the other (limit {f['limit']})"
    return t


def markdown(report, top=25):
    lines = [f"### Route cross-check (Valhalla vs OSRM): {report['region']}", "",
             f"Journeys: **{report['journeys']}**, flagged for review: **{report['flagged_journeys']}**.", ""]
    src = report.get("source") or {}
    if src.get("sha256"):
        lines += [f"Extract SHA-256: `{src['sha256']}`", ""]
    lines += ["| Engine result | Journeys |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k, v in report["engine_status"].items()]
    for engine, n in (report.get("unverifiable_routes") or {}).items():
        lines += ["", f"{engine}: **{n:,}** routes unverifiable (node list is not a clean path); "
                      "restriction, one-way and U-turn checks skipped for them, not passed."]
    lines += ["", "| Flag (engine) | Count |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k, v in report["flag_counts"].items()] or ["| none | 0 |"]
    if report["engine_unsupported"]:
        lines += ["", "**Restrictions Valhalla 3.6.3 does not enforce (blockers, as in restriction acceptance):**", ""]
        lines += [f"- [{u['restriction']} r{u['relation']}]({u['osm_url']}) w{u['from_way']} -> "
                  f"n{u['via_node']} -> w{u['to_way']}" for u in report["engine_unsupported"][:50]]
    if report["valhalla_violations"]:
        lines += ["", "**Valhalla violations (blockers):**", ""]
        lines += [f"- {v['journey']}: {_flag_text(v)}" for v in report["valhalla_violations"][:50]]
    by_id = {r["id"]: r for r in report["results"]}
    if report["top_flagged"]:
        lines += ["", f"#### Top {min(top, len(report['top_flagged']))} flagged journeys (leads, not proof)", ""]
        for jid in report["top_flagged"][:top]:
            r = by_id[jid]
            label = r.get("name") or r["category"]
            lines.append(f"- **{jid}** ({label}), score {r['score']}: [open on openstreetmap.org]"
                         f"({r['osm_directions_url']})")
            lines += [f"  - {_flag_text(f)}" for f in r["flags"][:6]]
    lines += ["", f"**Known routing-safety blockers: {report['known_routing_safety_blockers']}** "
              "(Valhalla restriction/one-way violations and unenforced restriction types).",
              "", "Accepted: **" + ("yes" if report["accepted"] else "NO") + "**. Detection only; "
              "check signs or street photos before editing OSM by hand."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--pbf", type=Path, help="OSM extract both engines were built from")
    source.add_argument("--opl", type=Path, help="pre-extracted OPL (highway ways, restrictions, nodes)")
    p.add_argument("--graph", type=Path, required=True, help="Valhalla tile tar or tile directory")
    p.add_argument("--osrm-url", default="http://127.0.0.1:5000")
    p.add_argument("--journeys", type=int, default=300)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--ratio", type=float, default=DEFAULT_RATIO)
    p.add_argument("--no-snap", action="store_true", help="do not snap endpoints to roads with OSRM /nearest")
    p.add_argument("--source-sha256", default=None)
    p.add_argument("--region", default="greater-manchester")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--markdown", type=Path)
    p.add_argument("--summary", type=Path, help="append Markdown here (e.g. $GITHUB_STEP_SUMMARY)")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--rewrite-report", type=Path,
                   help="restriction_rewrite.py report for --pbf; rewritten only_u_turn relations are then "
                        "treated as enforced (and still checked on every route)")
    args = p.parse_args(argv)
    if args.journeys < 0 or args.ratio <= 1.0:
        p.error("--journeys must be >= 0 and --ratio > 1")
    if not args.graph.exists():
        p.error("Valhalla graph not found")
    with tempfile.TemporaryDirectory(prefix="drivemate-crosscheck-") as tmp:
        opl = args.opl
        if args.pbf is not None:
            if not args.pbf.is_file():
                p.error("PBF not found")
            opl = Path(tmp) / "roads.opl"
            ra.pbf_to_opl(args.pbf, opl)
        elif not opl.is_file():
            p.error("OPL not found")
        rewritten = frozenset()
        if args.rewrite_report is not None:
            if args.pbf is None:
                p.error("--rewrite-report needs --pbf (its SHA-256 is checked against the report)")
            try:
                rewritten = frozenset(ra.load_rewrite_report(args.rewrite_report, ra.file_sha256(args.pbf)))
            except (ValueError, OSError) as error:
                p.error(f"rewrite report rejected: {error}")
        index = load_index(opl, rewritten)
    osrm = OsrmRouter(args.osrm_url, index)
    routers = [ValhallaRouter(args.graph), osrm]
    report = run(generate_journeys(args.journeys, args.seed), routers, index, args.ratio,
                 None if args.no_snap else osrm.nearest, args.region,
                 {"sha256": args.source_sha256, "seed": args.seed})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text = markdown(report, args.top)
    if args.markdown:
        args.markdown.write_text(text, encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(text)
    for v in report["valhalla_violations"]:
        print(f"::error::Valhalla {v['type']} on {v['journey']}: {v.get('osm_url', '')}")
    for u in report["engine_unsupported"]:
        print(f"::error::Restriction r{u['relation']} ({u['restriction']}) not enforced by Valhalla 3.6.3: {u['osm_url']}")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
