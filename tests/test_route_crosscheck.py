"""Route cross-check with fake routers (no network, no pyvalhalla, no OSRM)."""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import restriction_acceptance as ra  # noqa: E402
import route_crosscheck as rc  # noqa: E402

# Plus-shaped junction at node 2. Driving north on w10 (1 -> 2), w11 (east) is a right turn.
COORDS = {1: (53.4790, -2.2400), 2: (53.4800, -2.2400), 3: (53.4800, -2.2385),
          4: (53.4810, -2.2400), 5: (53.4800, -2.2415)}
SOUTH, EAST, NORTH, WEST = 10, 11, 12, 13


def way(ident, refs, **tags):
    parts = {"highway": "residential", **tags}
    return "w%d T%s N%s" % (ident, ",".join(f"{k}={v}" for k, v in parts.items()),
                            ",".join("n%d" % n for n in refs))


def rel(ident, kind, from_way=SOUTH, to_way=EAST):
    return "r%d Ttype=restriction,restriction=%s Mw%d@from,n2@via,w%d@to" % (ident, kind, from_way, to_way)


def index(relations=(), north_tags=None, rewritten=frozenset()):
    lines = [way(SOUTH, [1, 2]), way(EAST, [2, 3]), way(NORTH, [2, 4], **(north_tags or {})),
             way(WEST, [2, 5])]
    parsed = [ra.parse_relation(r) for r in relations]
    return rc.OsmIndex(ra.load_ways(lines), parsed, dict(COORDS), rewritten)


def node_route(nodes, idx, distance=1000.0):
    return rc.Route(distance, distance / 10.0, rc.segments_from_nodes(nodes, idx))


def coord_route(idx, legs, distance=1000.0):
    """Valhalla-style segments: way id plus coordinates, no node IDs."""
    segs = []
    for wid, a, b in legs:
        h = ra.bearing(COORDS[a], COORDS[b])
        segs.append(rc.Segment(wid, COORDS[a], COORDS[b], h, h))
    return rc.Route(distance, distance / 10.0, segs)


class FakeRouter(rc.Router):
    def __init__(self, name, route=None, error=None):
        self.name, self._route, self._error = name, route, error

    def route(self, origin, destination):
        self.last_reason = None if self._route else "NoRoute"
        if self._error:
            raise RuntimeError(self._error)
        return self._route


JOURNEY = rc.Journey("short-0000", "short", (53.479, -2.24), (53.48, -2.2385))


class Flags(unittest.TestCase):
    def check(self, routes, idx=None, ratio=1.25):
        idx = idx or index()
        return rc.compare(JOURNEY, routes, {n: None if r else "NoRoute" for n, r in routes.items()},
                          {}, idx, ratio)

    def types(self, result):
        return sorted(f["type"] for f in result["flags"])

    def test_distance_ratio_flag_and_configurable_limit(self):
        idx = index()
        routes = {"valhalla": node_route([1, 2, 3], idx, 1000.0), "osrm": node_route([1, 2, 3], idx, 1300.0)}
        result = self.check(routes, idx)
        self.assertEqual(self.types(result), ["distance_ratio"])
        self.assertEqual(result["flags"][0]["longer"], "osrm")
        self.assertEqual(result["distance_ratio"], 1.3)
        self.assertEqual(self.types(self.check(routes, idx, ratio=1.4)), [])

    def test_no_route_one_engine(self):
        idx = index()
        result = self.check({"valhalla": None, "osrm": node_route([1, 2, 3], idx)}, idx)
        self.assertEqual(self.types(result), ["no_route_one_engine"])
        self.assertEqual(result["flags"][0]["no_route"], "valhalla")
        both = self.check({"valhalla": None, "osrm": None}, idx)
        self.assertEqual(self.types(both), [])

    def test_no_right_turn_violation_attributed_per_engine(self):
        idx = index([rel(500, "no_right_turn")])
        bad_valhalla = coord_route(idx, [(SOUTH, 1, 2), (EAST, 2, 3)])
        good_osrm = node_route([1, 2, 4], idx)
        result = self.check({"valhalla": bad_valhalla, "osrm": good_osrm}, idx)
        violations = [f for f in result["flags"] if f["type"] == "restriction_violation"]
        self.assertEqual([(f["engine"], f["relation"]) for f in violations], [("valhalla", 500)])
        self.assertTrue(rc.blocking(violations[0]))
        result = self.check({"valhalla": node_route([1, 2, 4], idx), "osrm": node_route([1, 2, 3], idx)}, idx)
        violations = [f for f in result["flags"] if f["type"] == "restriction_violation"]
        self.assertEqual([f["engine"] for f in violations], ["osrm"])
        self.assertFalse(rc.blocking(violations[0]))

    def test_only_straight_on_and_wrong_approach(self):
        idx = index([rel(501, "only_straight_on", to_way=NORTH)])
        self.assertEqual(rc.restriction_violations(node_route([1, 2, 4], idx), idx), [])
        found = rc.restriction_violations(node_route([1, 2, 5], idx), idx)
        self.assertEqual([(f["relation"], f["taken_way"]) for f in found], [(501, WEST)])
        # Coming from the east is not the restriction's from way at all.
        self.assertEqual(rc.restriction_violations(node_route([3, 2, 5], idx), idx), [])

    def test_unsupported_type_stays_a_blocker(self):
        idx = index([rel(502, "only_u_turn", to_way=SOUTH)])
        self.assertEqual([r.relation for r in idx.unsupported_relations], [502])
        report = rc.run([JOURNEY], [FakeRouter("valhalla", node_route([1, 2, 1], idx)),
                                    FakeRouter("osrm", node_route([1, 2, 1], idx))], idx)
        self.assertEqual(report["known_routing_safety_blockers"], 1)
        self.assertFalse(report["accepted"])

    def test_rewritten_only_u_turn_is_enforced_and_still_checked(self):
        idx = index([rel(502, "only_u_turn", to_way=SOUTH)], rewritten={("only_u_turn", 502)})
        self.assertEqual(idx.unsupported_relations, [])
        ok = rc.run([JOURNEY], [FakeRouter("valhalla", node_route([1, 2, 1], idx)),
                                FakeRouter("osrm", node_route([1, 2, 1], idx))], idx)
        self.assertEqual(ok["known_routing_safety_blockers"], 0)
        # If the rewrite did not take effect, the turn it forbids is still caught.
        bad = rc.run([JOURNEY], [FakeRouter("valhalla", node_route([1, 2, 5], idx)),
                                 FakeRouter("osrm", node_route([1, 2, 1], idx))], idx)
        self.assertFalse(bad["accepted"])

    def test_oneway_violation_node_and_coordinate_routes(self):
        idx = index(north_tags={"oneway": "-1"})  # only drivable 4 -> 2
        self.assertEqual(rc.oneway_violations(node_route([4, 2, 3], idx), idx), [])
        self.assertEqual([f["way"] for f in rc.oneway_violations(node_route([1, 2, 4], idx), idx)], [NORTH])
        valhalla = coord_route(idx, [(SOUTH, 1, 2), (NORTH, 2, 4)])
        self.assertEqual([f["way"] for f in rc.oneway_violations(valhalla, idx)], [NORTH])
        result = self.check({"valhalla": valhalla, "osrm": node_route([1, 2, 3], idx)}, idx)
        self.assertIn("oneway_violation", self.types(result))
        self.assertTrue(any(rc.blocking(f) for f in result["flags"]))

    def test_implied_oneway_roundabout(self):
        lines = [way(SOUTH, [1, 2]), way(30, [2, 3, 4, 2], junction="roundabout")]
        idx = rc.OsmIndex(ra.load_ways(lines), [], dict(COORDS))
        self.assertEqual(rc.oneway_violations(node_route([1, 2, 3, 4], idx), idx), [])
        self.assertEqual(len(rc.oneway_violations(node_route([1, 2, 4, 3], idx), idx)), 1)

    def test_mid_route_u_turn(self):
        idx = index()
        flags = rc.u_turns(node_route([1, 2, 1], idx))
        self.assertEqual(len(flags), 1)
        self.assertEqual(rc.u_turns(node_route([1, 2, 4], idx)), [])


class OsrmArtifactRegression(unittest.TestCase):
    """False-positive patterns from the first real run (6,191 U-turns, 158 one-way flags)."""

    LAT, LON = 53.4800, -2.2400
    STEP = 0.00018  # about 20 m of latitude

    def idx(self, extra=(), coords=None):
        # One-way street A runs north, nodes 1..6 (node 3 is the junction with the two-way
        # cross street C: 7 - 3 - 8, east-west). Two-way street B continues north from 6.
        lines = [way(100, [1, 2, 3, 4, 5, 6], oneway="yes"),
                 way(101, [7, 3, 8]), way(102, [6, 9, 10]), *extra]
        c = {n: (self.LAT + self.STEP * (n - 1), self.LON) for n in range(1, 7)}
        c[7] = (c[3][0], self.LON - 0.0003)
        c[8] = (c[3][0], self.LON + 0.0003)
        c[9] = (c[6][0] + self.STEP, self.LON)
        c[10] = (c[6][0] + 2 * self.STEP, self.LON)
        c.update(coords or {})
        return rc.OsmIndex(ra.load_ways(lines), [], c)

    def test_shared_junction_node_and_two_way_street_crossing_a_one_way(self):
        idx = self.idx()
        for nodes in ([7, 3, 8], [8, 3, 7], [1, 2, 3, 4, 5, 6], [1, 2, 3, 8], [7, 3, 4, 5, 6, 9, 10]):
            route = node_route(nodes, idx)
            self.assertEqual(rc.oneway_violations(route, idx), [], nodes)
            self.assertEqual(rc.u_turns(route), [], nodes)
            self.assertEqual(route.segments and all(s.way_id is not None for s in route.segments), True)

    def test_true_one_way_violation_still_flagged_by_pair_direction(self):
        idx = self.idx()
        found = rc.oneway_violations(node_route([6, 5, 4], idx), idx)
        self.assertEqual([f["way"] for f in found], [100])
        # Joining the one-way against its direction from the cross street, via the shared node.
        found = rc.oneway_violations(node_route([7, 3, 2, 1], idx), idx)
        self.assertEqual([f["way"] for f in found], [100])

    def test_non_adjacent_pair_is_unmapped_not_a_violation(self):
        idx = self.idx()
        route = node_route([5, 3], idx)  # skips node 4: not an edge of any way
        self.assertIsNone(route.segments[0].way_id)
        self.assertEqual(rc.oneway_violations(route, idx), [])
        self.assertEqual(rc.u_turns(route), [])

    def test_pair_shared_by_a_two_way_way_is_allowed(self):
        idx = self.idx(extra=[way(103, [4, 5])])  # a two-way way over the same pair
        self.assertEqual(rc.oneway_violations(node_route([5, 4], idx), idx), [])

    def test_duplicate_consecutive_nodes_ignored(self):
        idx = self.idx()
        route = node_route([1, 2, 2, 2, 3, 3, 4], idx)
        self.assertEqual(len(route.segments), 3)
        self.assertEqual(rc.oneway_violations(route, idx), [])
        self.assertEqual(rc.u_turns(route), [])

    def test_duplicate_points_with_distinct_ids_have_no_heading(self):
        # Two node ids at the same place (e.g. a split way) must not look like a reversal.
        idx = self.idx(coords={3: (self.LAT + self.STEP * 2, self.LON)})
        idx.coords[11] = idx.coords[3]
        idx.ways[100] = (idx.ways[100][0], [1, 2, 3, 11, 4, 5, 6])
        route = node_route([1, 2, 3, 11, 4, 5, 6], idx)
        self.assertEqual(rc.u_turns(route), [])

    def test_short_zigzag_segments_are_not_u_turns(self):
        zig = self.STEP * 0.1  # about 2 m
        coords = {2: (self.LAT + self.STEP, self.LON), 3: (self.LAT + self.STEP + zig, self.LON),
                  4: (self.LAT + self.STEP, self.LON), 5: (self.LAT + self.STEP + zig, self.LON),
                  6: (self.LAT + self.STEP * 2, self.LON)}
        idx = self.idx(coords=coords)
        route = node_route([1, 2, 3, 4, 5, 6], idx)
        self.assertEqual(rc.u_turns(route), [])

    def test_true_u_turn_over_long_segments_still_flagged_once(self):
        idx = self.idx(extra=[way(104, [4, 12], highway="residential")],
                       coords={12: (self.LAT + self.STEP * 3, self.LON + 0.0003)})
        flags = rc.u_turns(node_route([1, 2, 3, 4, 3, 2, 1], idx))
        self.assertEqual(len(flags), 1)
        self.assertGreaterEqual(flags[0]["angle"], 150.0)

    def test_valhalla_tiny_edge_does_not_make_a_u_turn(self):
        idx = self.idx()
        c = idx.coords
        tiny = (c[3][0], c[3][1] + 0.00001)  # about 0.7 m sideways stub
        segs = [rc.Segment(100, c[1], c[3], 0.0, 0.0), rc.Segment(101, c[3], tiny, 90.0, 90.0),
                rc.Segment(100, tiny, c[6], 0.0, 0.0)]
        self.assertEqual(rc.u_turns(rc.Route(100.0, 10.0, segs)), [])


class Journeys(unittest.TestCase):
    def test_deterministic_and_banded(self):
        a = rc.generate_journeys(30, seed=7)
        b = rc.generate_journeys(30, seed=7)
        self.assertEqual([j.as_dict() for j in a], [j.as_dict() for j in b])
        self.assertNotEqual([j.as_dict() for j in a], [j.as_dict() for j in rc.generate_journeys(30, seed=8)])
        named = [j for j in a if j.category == "named"]
        self.assertEqual(len(named), 4)
        self.assertEqual(named[0].destination, (53.395466, -2.194193))
        counts = {c: sum(1 for j in a if j.category == c) for c in rc.BANDS}
        self.assertEqual(counts, {"short": 10, "medium": 10, "long": 10})
        for j in a:
            self.assertTrue(rc.inside(j.origin) and rc.inside(j.destination))
            if j.category in rc.BANDS:
                low, high = rc.BANDS[j.category]
                km = ra.haversine(j.origin, j.destination) / 1000.0
                self.assertTrue(low - 0.01 <= km <= high + 0.01, (j.id, km))

    def test_default_count(self):
        self.assertEqual(len(rc.generate_journeys(300)), 304)


class Output(unittest.TestCase):
    def test_report_schema_and_markdown(self):
        idx = index([rel(500, "no_right_turn")])
        routers = [FakeRouter("valhalla", node_route([1, 2, 4], idx, 1000.0)),
                   FakeRouter("osrm", node_route([1, 2, 3], idx, 1500.0))]
        report = rc.run([JOURNEY, rc.Journey("short-0001", "short", (53.48, -2.24), (53.481, -2.24))],
                        routers, idx, source={"sha256": "ab" * 32})
        json.loads(json.dumps(report))
        for key in ("schema", "region", "source", "engines", "ratio_limit", "journeys", "flagged_journeys",
                    "engine_status", "flag_counts", "valhalla_violations", "engine_unsupported",
                    "known_routing_safety_blockers", "accepted", "results", "top_flagged", "limitations"):
            self.assertIn(key, report)
        self.assertEqual(report["engines"], ["valhalla", "osrm"])
        self.assertTrue(report["accepted"])  # only OSRM broke the restriction
        self.assertEqual(report["flag_counts"]["restriction_violation:osrm"], 2)
        first = report["results"][0]
        for key in ("id", "category", "origin", "destination", "engines", "flags", "score",
                    "osm_directions_url", "distance_ratio"):
            self.assertIn(key, first)
        self.assertEqual(first["engines"]["valhalla"]["ways"], [SOUTH, NORTH])
        text = rc.markdown(report)
        self.assertIn("openstreetmap.org/relation/500", text)
        self.assertIn("openstreetmap.org/directions", text)
        self.assertIn("Accepted: **yes**", text)

    def test_engine_error_recorded_not_passed(self):
        idx = index()
        report = rc.run([JOURNEY], [FakeRouter("valhalla", error="boom"),
                                    FakeRouter("osrm", node_route([1, 2, 3], idx))], idx)
        self.assertEqual(report["results"][0]["engines"]["valhalla"]["status"], "error")

    def test_osrm_router_maps_nodes_to_ways(self):
        idx = index()
        body = json.dumps({"code": "Ok", "routes": [{"distance": 250.0, "duration": 30.0, "legs": [
            {"annotation": {"nodes": [1, 2, 2, 3]}}]}]}).encode()
        with mock.patch.object(rc.urllib.request, "urlopen", return_value=io.BytesIO(body)):
            route = rc.OsrmRouter("http://osrm", idx).route((53.479, -2.24), (53.48, -2.2385))
        self.assertEqual(route.way_sequence(), [SOUTH, EAST])
        self.assertEqual([(s.start_node, s.end_node) for s in route.segments], [(1, 2), (2, 3)])

    def test_main_writes_outputs_with_fake_engines(self):
        idx = index()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            opl = tmp / "roads.opl"
            opl.write_text("\n".join([way(SOUTH, [1, 2]), way(EAST, [2, 3])] + [
                f"n{n} v0 x{lon} y{lat}" for n, (lat, lon) in COORDS.items()]) + "\n")
            fake = node_route([1, 2, 3], idx)
            with mock.patch.object(rc, "ValhallaRouter", lambda g: FakeRouter("valhalla", fake)), \
                    mock.patch.object(rc.OsrmRouter, "route", lambda self, o, d: fake):
                code = rc.main(["--opl", str(opl), "--graph", str(tmp), "--journeys", "3", "--no-snap",
                                "--report", str(tmp / "r.json"), "--markdown", str(tmp / "r.md")])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((tmp / "r.json").read_text())["journeys"], 7)
            self.assertIn("Route cross-check", (tmp / "r.md").read_text())


class Workflow(unittest.TestCase):
    def test_workflow_contract(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/route-crosscheck.yml").read_text())
        self.assertEqual(wf["concurrency"], {"group": "map-data", "cancel-in-progress": False})
        on = wf[True]  # PyYAML reads the bare "on" key as True
        self.assertIn("workflow_dispatch", on)
        self.assertEqual(on["push"]["branches"], ["codex/architecture-foundation"])
        self.assertEqual(sorted(on["push"]["paths"]), sorted([
            "scripts/route_crosscheck.py", "tests/test_route_crosscheck.py",
            ".github/workflows/route-crosscheck.yml", "docs/validation/route-crosscheck.md"]))
        job = wf["jobs"]["crosscheck"]
        self.assertLessEqual(job["timeout-minutes"], 60)
        text = (ROOT / ".github/workflows/route-crosscheck.yml").read_text()
        self.assertRegex(text, r"ghcr\.io/project-osrm/osrm-backend:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}")
        self.assertIn("pyvalhalla==3.6.3", text)
        self.assertIn("/opt/car.lua", text)


if __name__ == "__main__":
    unittest.main()
