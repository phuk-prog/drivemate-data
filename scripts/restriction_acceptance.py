"""Routing-engine acceptance for OSM turn restrictions (detection only).

For simple, well-formed node-via restriction relations, asks the routing
engine (Valhalla, ``auto`` costing) for short probe routes approaching the via
node along the ``from`` way, and checks the decoded OSM way sequence:

* ``no_*``: FAIL if any route turns directly from the ``from`` way into the
  ``to`` way at the via node. A legal detour is a pass.
* ``only_*``: FAIL if any route continues from the ``from`` way through the via
  node and leaves it on a way other than the ``to`` way.

Nothing is fixed, invented or uploaded. A pass only means the engine did not
take the prohibited manoeuvre for these probes; it does not prove the OSM data
matches signage on the ground.
"""
import argparse
from collections import Counter
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from restriction_audit import evaluate_relation, load_ways, parse_relation  # noqa: E402

SIMPLE_TYPES = {"no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn"}
MOTORCAR_EXCEPTIONS = {"motorcar", "motor_vehicle", "vehicle", "car"}
TIMED_TAGS = {"day_on", "day_off", "hour_on", "hour_off"}
IMPLIED_ONEWAY_HIGHWAYS = {"motorway", "motorway_link"}
FORWARD, BACKWARD = 1, -1
ONEWAY_FLAGS = {"from_possible_oneway_orientation_conflict", "to_possible_oneway_orientation_conflict",
                "from_oneway_via_is_internal_node", "to_oneway_via_is_internal_node"}
VIA_MATCH_METRES = 3.0
MIN_LEG_METRES = 4.0  # shorter from/to stretches cannot hold a probe point clear of both nodes
UTURN_DEGREES = 135.0
MAX_FAILURE_DETAIL = 10000
# Restriction types Valhalla 3.6.3 does not build into its graph (checked in its tile builder).
ENGINE_UNSUPPORTED = {"only_u_turn"}
NODE = re.compile(r"n([0-9]+)\Z")


# --------------------------------------------------------------------------- geometry

def haversine(a, b):
    """Metres between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(h)))


def bearing(a, b):
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_between(h1, h2):
    d = abs(h1 - h2) % 360.0
    return 360.0 - d if d > 180.0 else d


def walk(points, distance):
    """Point and travel heading ``distance`` metres along ``points`` (a polyline)."""
    remaining = distance
    for a, b in zip(points, points[1:]):
        seg = haversine(a, b)
        if seg <= 0:
            continue
        if remaining <= seg:
            t = remaining / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), bearing(a, b)
        remaining -= seg
    return None


def length(points):
    return sum(haversine(a, b) for a, b in zip(points, points[1:]))


# --------------------------------------------------------------------------- OSM semantics

def drivable_directions(tags):
    """Directions (along node order) a motor car may drive, from explicit or implied oneway tags."""
    value = None
    for key in ("oneway:motorcar", "oneway:motor_vehicle", "oneway:vehicle", "oneway"):
        if key in tags:
            value = tags[key].strip().lower()
            break
    if value is None and (tags.get("junction") in ("roundabout", "circular")
                          or tags.get("highway") in IMPLIED_ONEWAY_HIGHWAYS):
        value = "yes"
    if value in (None, "no", "false", "0"):
        return {FORWARD, BACKWARD}
    if value in ("yes", "true", "1"):
        return {FORWARD}
    if value in ("-1", "reverse"):
        return {BACKWARD}
    return set()  # reversible, alternating, or unknown: never assume


def leg_towards(nodes, via, direction):
    """Node IDs of the stretch that is driven *towards* ``via`` in ``direction``."""
    i = nodes.index(via)
    return nodes[: i + 1] if direction == FORWARD else nodes[i:][::-1]


def leg_away(nodes, via, direction):
    """Node IDs of the stretch driven *away from* ``via`` in ``direction``."""
    i = nodes.index(via)
    return nodes[i:] if direction == FORWARD else nodes[: i + 1][::-1]


def classify(relation, ways):
    """Return (selected: bool, skip_reason or None, audit_result)."""
    ident, tags, members = relation
    kind = tags.get("restriction")
    audit_result = evaluate_relation(relation, ways)
    if any(k.endswith(":conditional") for k in tags) or TIMED_TAGS.intersection(tags):
        return False, "conditional_or_timed", audit_result
    if any(k.startswith("restriction:") for k in tags):
        return False, "vehicle_specific", audit_result
    excepted = {v.strip() for v in tags.get("except", "").split(";")}
    if excepted & MOTORCAR_EXCEPTIONS:
        return False, "motorcar_exception", audit_result
    if kind is None:
        return False, "missing_restriction_value", audit_result
    if not (kind in SIMPLE_TYPES or (kind.startswith("only_") and kind != "only_")):
        return False, "unsupported_type", audit_result
    if audit_result["via"] == "way":
        return False, "way_via", audit_result
    # One-way orientation is re-derived (including implied one-ways) by build_case,
    # which skips with a precise reason; every other review flag excludes the relation.
    if [r for r in audit_result["review_reasons"] if r not in ONEWAY_FLAGS]:
        return False, "needs_review", audit_result
    froms = [n for k, n, r in members if r == "from"]
    tos = [n for k, n, r in members if r == "to"]
    vias = [(k, n) for k, n, r in members if r == "via"]
    if len(froms) != 1 or len(tos) != 1 or len(vias) != 1 or vias[0][0] != "n":
        return False, "not_single_from_via_node_to", audit_result
    unknown_roles = {r for _, _, r in members} - {"from", "via", "to"}
    if unknown_roles:
        return False, "unexpected_member_roles", audit_result
    return True, None, audit_result


# --------------------------------------------------------------------------- router interface

@dataclass
class Point:
    lat: float
    lon: float
    heading: float


@dataclass
class Edge:
    """One routed edge decoded to its OSM way and end-node coordinate."""
    way_id: int
    end_lat: float
    end_lon: float
    begin_heading: float = None
    end_heading: float = None


@dataclass
class Probe:
    target_way: int
    start: Point
    end: Point
    forbidden: bool  # True: the direct manoeuvre into target_way is prohibited.
    target_fraction: float = 0.8  # Diagnostic destination distance along the target leg.


@dataclass
class Case:
    relation: int
    restriction: str
    from_way: int
    via_node: int
    to_way: int
    via: tuple
    probes: list = field(default_factory=list)


class ProbeInconclusive(Exception):
    """The router could not place or decode a probe; never counted as a pass."""


class Router:
    """Minimal router interface: return decoded edges, or None when no route exists.

    Raise ProbeInconclusive when locations cannot be snapped or the route cannot be decoded.
    """

    def route(self, start, end):  # pragma: no cover - interface only
        raise NotImplementedError


def decode_polyline(encoded, precision=6):
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10.0 ** precision
    while index < len(encoded):
        for axis in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords


def _heading(attributes, key):
    value = attributes.get(key)
    return None if value is None else float(value)


def error_code(error):
    match = re.search(r'"error_code"\s*:\s*([0-9]+)', str(error))
    return int(match.group(1)) if match else None


class ValhallaRouter(Router):
    """pyvalhalla Actor: plain ``auto`` route, then edge_walk of its own shape to recover OSM way IDs."""

    def __init__(self, graph):
        from valhalla import Actor, get_config  # imported lazily: tests never need pyvalhalla
        graph = Path(graph)
        self._tmp = tempfile.TemporaryDirectory(prefix="drivemate-acceptance-")
        if graph.is_dir():
            config = get_config(tile_dir=str(graph), verbose=False)
        else:
            config = get_config(tile_extract=str(graph), tile_dir=self._tmp.name, verbose=False)
        self.actor = Actor(config)
        self.last_decoder = None

    @staticmethod
    def _location(p):
        # node_snap_tolerance=0: Valhalla otherwise snaps a point within 5 m of a node onto
        # the node itself, so a probe on a short from way would start *at* the via node,
        # with no approach edge for the restriction to apply to.
        return {"lat": p.lat, "lon": p.lon, "heading": round(p.heading), "heading_tolerance": 45,
                "node_snap_tolerance": 0}

    def route(self, start, end):
        self.last_decoder = None
        request = {"locations": [self._location(start), self._location(end)],
                   "costing": "auto", "directions_type": "none"}
        try:
            trip = json.loads(self.actor.route(json.dumps(request)))["trip"]
        except RuntimeError as error:
            code = error_code(error)
            if code == 442:  # no path between correctly snapped locations
                return None
            if code is not None and 170 <= code <= 172:  # no suitable edge near a location
                raise ProbeInconclusive(f"location not snapped (Valhalla error {code})") from error
            raise
        shape = trip["legs"][0]["shape"]
        attributes, last_error = None, None
        # edge_walk follows the route's own shape exactly; map_snap is the fallback when
        # edge_walk cannot (recorded per probe, so a reviewer can weigh the evidence).
        for mode in ("edge_walk", "map_snap"):
            try:
                attributes = json.loads(self.actor.trace_attributes(json.dumps({
                    "encoded_polyline": shape, "shape_match": mode, "costing": "auto",
                    "filters": {"action": "include", "attributes": [
                        "edge.way_id", "edge.begin_heading", "edge.end_heading",
                        "edge.end_shape_index", "shape"]}})))
                self.last_decoder = mode
                break
            except RuntimeError as error:
                last_error = error
        if attributes is None:
            raise ProbeInconclusive(f"route not decodable to OSM ways: {str(last_error)[:160]}")
        points = decode_polyline(attributes["shape"])
        edges = []
        for e in attributes.get("edges", []):
            lat, lon = points[e["end_shape_index"]]
            edges.append(Edge(int(e["way_id"]), lat, lon,
                              _heading(e, "begin_heading"), _heading(e, "end_heading")))
        return edges


# --------------------------------------------------------------------------- probe construction

def build_case(relation, ways, coords, node_ways):
    """Return (Case, None) or (None, skip_reason). Never alters the relation."""
    ident, tags, members = relation
    from_way = next(n for _, n, r in members if r == "from")
    to_way = next(n for _, n, r in members if r == "to")
    via = next(n for _, n, r in members if r == "via")
    kind = tags["restriction"]
    if via not in coords:
        return None, "via_node_location_missing"
    from_tags, from_nodes = ways[from_way]
    if from_nodes.count(via) != 1 or ways[to_way][1].count(via) != 1:
        return None, "via_repeated_in_way"
    internal = via not in (from_nodes[0], from_nodes[-1])
    approach = [d for d in sorted(drivable_directions(from_tags), reverse=True)
                if len(leg_towards(from_nodes, via, d)) > 1]
    if not approach:
        return None, "from_way_not_drivable_towards_via"
    if internal and len(approach) > 1:
        return None, "ambiguous_from_direction"
    direction = approach[0]
    approach_leg = leg_towards(from_nodes, via, direction)
    if any(n not in coords for n in approach_leg):
        return None, "node_location_missing"
    same_way_uturn = to_way == from_way
    start_target = 30.0 if same_way_uturn else 40.0
    approach_pts = [coords[n] for n in approach_leg]
    approach_len = length(approach_pts)
    if approach_len < MIN_LEG_METRES:
        return None, "from_way_too_short"
    # Walk backwards from the via node, then report travel heading towards it.
    back = walk(approach_pts[::-1], min(start_target, approach_len * 0.4))
    start = Point(back[0][0], back[0][1], (back[1] + 180.0) % 360.0)
    case = Case(ident, kind, from_way, via, to_way, coords[via])

    def exits(way_id):
        tags_, nodes = ways[way_id]
        if nodes.count(via) != 1:
            return []
        found = []
        for d in sorted(drivable_directions(tags_), reverse=True):
            leg = leg_away(nodes, via, d)
            if len(leg) < 2 or any(n not in coords for n in leg):
                continue
            if way_id == from_way and leg[1] != approach_leg[-2]:
                continue  # continuing ahead on the from way is not a U-turn on it
            found.append(leg)
        return found

    def probe(way_id, leg, forbidden, fraction=0.8):
        pts = [coords[n] for n in leg]
        total = length(pts)
        if total < MIN_LEG_METRES:
            return None
        target = 70.0 if way_id == from_way else 40.0
        along = walk(pts, min(target, total * fraction))
        return Probe(way_id, start, Point(along[0][0], along[0][1], along[1]),
                     forbidden, fraction)

    to_legs = exits(to_way)
    if not to_legs:
        return None, "to_way_not_drivable_away_from_via"
    if kind.startswith("no_"):
        case.probes = [p for p in (probe(to_way, leg, True) for leg in to_legs) if p]
        # Real Greater Manchester r14551046: a prohibited left turn on a
        # two-node service driveway may be destination-sensitive. Preserve
        # the original probe and add a nearer one. Any failing probe still
        # fails the relation; neither result grants a routing exception.
        target_tags, target_nodes = ways[to_way]
        if (target_tags.get("highway") == "service"
                and target_tags.get("service") == "driveway"
                and len(target_nodes) == 2):
            case.probes += [p for p in (probe(to_way, leg, True, fraction=0.35)
                                       for leg in to_legs) if p]
    else:
        case.probes = [p for p in (probe(to_way, leg, False) for leg in to_legs[:1]) if p]
        for other in sorted(node_ways.get(via, ())):
            if other == to_way:
                continue
            for leg in exits(other):
                p = probe(other, leg, True)
                if p:
                    case.probes.append(p)
    if not case.probes or (kind.startswith("no_") and not any(p.forbidden for p in case.probes)):
        return None, "to_way_too_short"
    return case, None


# --------------------------------------------------------------------------- judgement

def via_transitions(edges, via):
    """(incoming_way, outgoing_way, turn_angle) for each edge change exactly at the via node."""
    for a, b in zip(edges, edges[1:]):
        if haversine((a.end_lat, a.end_lon), via) <= VIA_MATCH_METRES:
            angle = (None if a.end_heading is None or b.begin_heading is None
                     else angle_between(a.end_heading, b.begin_heading))
            yield a.way_id, b.way_id, angle


def judge_probe(case, probe, edges):
    """Return (status, detail) for one probe route."""
    if edges is None:
        return "no_route", "router found no route"
    if not edges:
        return "inconclusive", "empty route"
    if edges[0].way_id != case.from_way:
        return "inconclusive", f"route starts on way {edges[0].way_id}, not the from way"
    if edges[-1].way_id != probe.target_way:
        return "inconclusive", f"route ends on way {edges[-1].way_id}, not way {probe.target_way}"
    if edges[0].begin_heading is not None and angle_between(edges[0].begin_heading, probe.start.heading) > 60:
        return "inconclusive", "route does not start in the probe direction (towards the via node)"
    if edges[-1].end_heading is not None and angle_between(edges[-1].end_heading, probe.end.heading) > 60:
        return "inconclusive", "route does not end in the probe direction (away from the via node)"
    for incoming, outgoing, angle in via_transitions(edges, case.via):
        if incoming != case.from_way:
            continue
        if case.from_way == outgoing and angle is not None and angle < UTURN_DEGREES:
            continue  # straight through on the same way, not a U-turn
        if case.restriction.startswith("no_") and outgoing == case.to_way:
            return "fail", f"direct {case.restriction} manoeuvre w{incoming} -> n{case.via_node} -> w{outgoing}"
        if case.restriction.startswith("only_") and outgoing != case.to_way:
            return "fail", (f"{case.restriction} ignored: w{incoming} -> n{case.via_node} -> "
                            f"w{outgoing} instead of w{case.to_way}")
    return "pass", "complies"


def judge_case(case, router):
    results = []
    for p in case.probes:
        try:
            status, detail = judge_probe(case, p, router.route(p.start, p.end))
        except ProbeInconclusive as error:
            status, detail = "inconclusive", str(error)
        result = {"target_way": p.target_way, "forbidden_target": p.forbidden,
                  "target_fraction": p.target_fraction,
                  "status": status, "detail": detail}
        decoder = getattr(router, "last_decoder", None)
        if decoder:
            result["decoder"] = decoder
        results.append(result)
    statuses = [r["status"] for r in results]
    # Every probe of the relation matters. Previously a single successful
    # route could conceal an inconclusive or unroutable alternative exit.
    # A relation only passes when *all* its probes have been examined and
    # none violates the restriction; unresolved probes retain their status.
    if "fail" in statuses:
        overall = "fail"
    elif "inconclusive" in statuses:
        overall = "inconclusive"
    elif "no_route" in statuses:
        overall = "no_route"
    elif statuses and all(s == "pass" for s in statuses):
        overall = "pass"
    else:
        overall = "inconclusive"
    return overall, results


# --------------------------------------------------------------------------- OSM input

def read_opl(path):
    """Two passes: highway ways and restriction relations, then only the node locations needed."""
    with open(path, "rt", encoding="utf-8") as handle:
        ways = load_ways(line for line in handle if line.startswith("w"))
    relations = []
    with open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("r"):
                parsed = parse_relation(line)
                if parsed is not None:
                    relations.append(parsed)
    return ways, relations


def read_node_coords(path, wanted):
    coords = {}
    with open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("n"):
                continue
            fields = line.split()
            match = NODE.fullmatch(fields[0])
            if not match or int(match.group(1)) not in wanted:
                continue
            x = next((f[1:] for f in fields[1:] if f.startswith("x")), "")
            y = next((f[1:] for f in fields[1:] if f.startswith("y")), "")
            if x and y:
                coords[int(match.group(1))] = (float(y), float(x))
    return coords


def pbf_to_opl(pbf, opl):
    """Highway ways, restriction relations and their referenced nodes (osmium-tool or pyosmium)."""
    if shutil.which("osmium"):
        subprocess.run(["osmium", "tags-filter", str(pbf), "w/highway", "r/type=restriction",
                        "-f", "opl,add_metadata=false", "-o", str(opl), "--overwrite"], check=True)
        return
    import osmium  # pyosmium fallback: writes the whole extract as OPL
    writer = osmium.SimpleWriter(str(opl), overwrite=True)
    try:
        for obj in osmium.FileProcessor(str(pbf)):
            writer.add(obj)
    finally:
        writer.close()


# --------------------------------------------------------------------------- driver

def run(ways, relations, coords_loader, router, region):
    counts, skipped, failures, by_type = Counter(), Counter(), [], Counter()
    examples = {"no_route": [], "inconclusive": []}
    selected = []
    seen = set()
    for relation in relations:
        if relation[0] in seen:
            raise ValueError("Duplicate restriction relation ID")
        seen.add(relation[0])
        ok, reason, audit_result = classify(relation, ways)
        if not ok:
            skipped[reason] += 1
            if reason == "needs_review":
                for flag in audit_result["review_reasons"]:
                    skipped["needs_review:" + flag] += 1
            continue
        selected.append(relation)
    wanted = set()
    via_nodes = set()
    for _, _, members in selected:
        for kind, ident, role in members:
            if role == "via":
                via_nodes.add(ident)
    node_ways = {}
    for wid, (_, nodes) in ways.items():
        hits = via_nodes.intersection(nodes)
        for n in hits:
            node_ways.setdefault(n, set()).add(wid)
            wanted.update(nodes)
    coords = coords_loader(wanted)
    unsupported = []
    for relation in selected:
        case, reason = build_case(relation, ways, coords, node_ways)
        if case is None:
            skipped[reason] += 1
            continue
        status, probes = judge_case(case, router)
        if status == "fail" and case.restriction in ENGINE_UNSUPPORTED:
            # Known routing-engine gap, listed separately so that it is never
            # hidden yet cannot mask a new, unexpected failure.
            status = "engine_unsupported"
        counts[status] += 1
        by_type[case.restriction + ":" + status] += 1
        target_tags, target_nodes = ways[case.to_way]
        record = {
            "relation": case.relation, "restriction": case.restriction,
            "target_way_context": {
                "highway": target_tags.get("highway"),
                "service": target_tags.get("service"),
                "oneway": target_tags.get("oneway"),
                "node_count": len(target_nodes),
                "two_node_driveway": (target_tags.get("highway") == "service"
                                      and target_tags.get("service") == "driveway"
                                      and len(target_nodes) == 2),
            },
            "from_way": case.from_way, "via_node": case.via_node, "to_way": case.to_way,
            "via_location": [round(case.via[0], 7), round(case.via[1], 7)],
            "osm_url": f"https://www.openstreetmap.org/relation/{case.relation}",
            "from_url": f"https://www.openstreetmap.org/way/{case.from_way}",
            "via_url": f"https://www.openstreetmap.org/node/{case.via_node}",
            "to_url": f"https://www.openstreetmap.org/way/{case.to_way}",
            "probes": probes,
        }
        if status == "fail" and len(failures) < MAX_FAILURE_DETAIL:
            failures.append(record)
        elif status == "engine_unsupported":
            unsupported.append(record)
        elif status in examples and len(examples[status]) < 50:
            examples[status].append(record)
    tested = sum(counts.values())
    return {
        "schema": 1, "region": region,
        "restriction_relations": len(seen), "tested": tested,
        "counts": {s: counts.get(s, 0) for s in ("pass", "fail", "engine_unsupported", "no_route", "inconclusive")},
        "engine_unsupported": unsupported,
        "engine_unsupported_note": ("Valhalla 3.6.3 tile building does not recognise these restriction "
                                    "types (only_u_turn), so they are not enforced. A real navigation "
                                    "risk, tracked separately; not a pass."),
        "skipped": dict(sorted(skipped.items())),
        "skipped_total": sum(v for k, v in skipped.items() if ":" not in k),
        "by_type": dict(sorted(by_type.items())),
        "failures": failures, "no_route_examples": examples["no_route"],
        "inconclusive_examples": examples["inconclusive"],
        # Supported-probe violations and known-unsupported OSM restrictions
        # *both* keep this acceptance job red. Neither can safely be called
        # accepted until the routing engine or a verified route guard fixes it.
        "accepted": counts.get("fail", 0) == 0 and counts.get("engine_unsupported", 0) == 0,
        "known_routing_safety_blockers": counts.get("fail", 0) + counts.get("engine_unsupported", 0),
        "scope": ("Routing-engine compliance with simple node-via OSM restrictions for auto costing. "
                  "Detection only: no data is repaired, invented or uploaded."),
        "limitations": [
            "Accepted means no detected violations or known unsupported restrictions; skipped, no_route and inconclusive cases still require independent safety review.",
            "Assumes the OSM relation is correct; does not verify signage or ground truth.",
            "Conditional, timed, vehicle-specific, way-via and flagged relations are skipped, not tested.",
            "A pass covers only the probed approach and destinations, not every possible route.",
            "no_route and inconclusive (probe snapped to another way) are not passes.",
        ],
    }


def summary_markdown(report):
    lines = [f"### Turn-restriction acceptance: {report['region']}", "",
             "| Status | Relations |", "|---|---:|"]
    for key, value in report["counts"].items():
        lines.append(f"| {key} | {value:,} |")
    lines.append(f"| skipped | {report['skipped_total']:,} |")
    lines.append(f"| **total relations** | {report['restriction_relations']:,} |")
    if report["skipped"]:
        lines += ["", "| Skip reason | Relations |", "|---|---:|"]
        lines += [f"| {k} | {v:,} |" for k, v in report["skipped"].items()]
    if report.get("engine_unsupported"):
        lines += ["", "**Not enforced by the routing engine (Valhalla 3.6.3 ignores only_u_turn):**", "",
                  "| Relation | Type | from | via | to |", "|---|---|---|---|---|"]
        for f in report["engine_unsupported"][:50]:
            lines.append(f"| [r{f['relation']}]({f['osm_url']}) | {f['restriction']} | "
                         f"w{f['from_way']} | n{f['via_node']} | w{f['to_way']} |")
    if report["failures"]:
        lines += ["", "| Failing relation | Type | from | via | to |", "|---|---|---|---|---|"]
        for f in report["failures"][:50]:
            lines.append(f"| [r{f['relation']}]({f['osm_url']}) | {f['restriction']} | "
                         f"w{f['from_way']} | n{f['via_node']} | w{f['to_way']} |")
    if report["failures"]:
        for f in report["failures"][:20]:
            if f.get("target_way_context", {}).get("two_node_driveway"):
                probes = ", ".join(f"{p['target_fraction']:.2f}: {p['status']}" for p in f["probes"])
                lines.append(f"- r{f['relation']} two-node driveway probe positions: {probes} (no suppression).")
    lines += ["", "**Known routing-safety blockers: " + str(report["known_routing_safety_blockers"]) + "** (failed restriction probes and unsupported engine restrictions; other skipped/inconclusive cases are not cleared)."]
    lines += ["", "Accepted: **" + ("yes" if report["accepted"] else "NO") + "**. "
              "Detection only; OSM correctness and signage are not verified."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--pbf", type=Path, help="OSM extract the graph was built from")
    source.add_argument("--opl", type=Path, help="pre-extracted OPL with highway ways, restrictions and nodes")
    p.add_argument("--graph", type=Path, required=True, help="Valhalla tile tar or tile directory")
    p.add_argument("--region", default="greater-manchester")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--summary", type=Path, help="append a Markdown table here (e.g. $GITHUB_STEP_SUMMARY)")
    args = p.parse_args(argv)
    if not args.graph.exists():
        p.error("Valhalla graph not found")
    with tempfile.TemporaryDirectory(prefix="drivemate-acceptance-opl-") as tmp:
        opl = args.opl
        if args.pbf is not None:
            if not args.pbf.is_file():
                p.error("PBF not found")
            opl = Path(tmp) / "restrictions.opl"
            pbf_to_opl(args.pbf, opl)
        elif not opl.is_file():
            p.error("OPL not found")
        ways, relations = read_opl(opl)
        report = run(ways, relations, lambda wanted: read_node_coords(opl, wanted),
                     ValhallaRouter(args.graph), args.region)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text = summary_markdown(report)
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(text)
    for f in report["failures"]:
        print(f"::error::Restriction r{f['relation']} ({f['restriction']}) violated by router: {f['osm_url']}")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
