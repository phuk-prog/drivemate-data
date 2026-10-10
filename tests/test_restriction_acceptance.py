"""Synthetic routing-acceptance checks with an injected fake router (no network, no pyvalhalla)."""
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import restriction_acceptance as ra  # noqa: E402

# A plus-shaped junction at node 2; driving north on w10, w11 (east) is a right turn.
COORDS = {
    1: (53.4790, -2.2400), 2: (53.4800, -2.2400), 3: (53.4800, -2.2385),
    4: (53.4810, -2.2400), 5: (53.4800, -2.2415), 6: (53.4810, -2.2385),
}
SOUTH, EAST, NORTH, WEST = 10, 11, 12, 13
VIA = COORDS[2]


def way(ident, refs, **tags):
    parts = {"highway": "residential", **tags}
    return "w%d T%s N%s\n" % (ident, ",".join(f"{k}={v}" for k, v in parts.items()),
                              ",".join("n%d" % n for n in refs))


def rel(ident, members, **tags):
    fields = {"type": "restriction", "restriction": "no_right_turn", **tags}
    return "r%d T%s M%s\n" % (ident, ",".join(f"{k}={v}" for k, v in fields.items()),
                              ",".join(f"{kind}{wid}@{role}" for kind, wid, role in members))


def ways(**south_tags):
    lines = [way(SOUTH, [1, 2], **south_tags), way(EAST, [2, 3]), way(NORTH, [2, 4]),
             way(WEST, [2, 5]), way(20, [4, 6]), way(21, [6, 3])]
    return ra.load_ways(lines)


def members(from_way=SOUTH, to_way=EAST):
    return [("w", from_way, "from"), ("n", 2, "via"), ("w", to_way, "to")]


def edge(way_id, node, begin=None, end=None):
    lat, lon = COORDS[node]
    return ra.Edge(way_id, lat, lon, begin, end)


def target_of(end):
    """Which arm a probe's destination lies on, by bearing from the via node."""
    b = ra.bearing(VIA, (end.lat, end.lon))
    return {0: NORTH, 90: EAST, 180: SOUTH, 270: WEST}[int(round(b / 90.0)) % 4 * 90]


class FakeRouter(ra.Router):
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def route(self, start, end):
        target = target_of(end)
        self.calls.append(target)
        return self.routes.get(target)


DIRECT = {EAST: [edge(SOUTH, 2), edge(EAST, 3)]}
DETOUR = {EAST: [edge(SOUTH, 2), edge(NORTH, 4), edge(20, 6), edge(21, 3), edge(EAST, 2)]}


def run(relations, router, road_ways=None):
    road_ways = road_ways if road_ways is not None else ways()
    parsed = [ra.parse_relation(line) for line in relations]
    return ra.run(road_ways, parsed, lambda wanted: {n: COORDS[n] for n in wanted if n in COORDS},
                  router, "synthetic")


class EngineLimitationTests(unittest.TestCase):
    def test_ignored_only_u_turn_is_listed_separately_and_does_not_mask_new_failures(self):
        ignoring = FakeRouter({NORTH: [edge(SOUTH, 2), edge(NORTH, 4)],
                               EAST: [edge(SOUTH, 2), edge(EAST, 3)],
                               WEST: [edge(SOUTH, 2), edge(WEST, 5)]})
        report = run([rel(30, members(SOUTH, SOUTH), restriction="only_u_turn")], ignoring)
        self.assertEqual(0, report["counts"]["fail"])
        self.assertEqual(1, report["counts"]["engine_unsupported"])
        self.assertEqual(1, report["known_routing_safety_blockers"])
        self.assertEqual(30, report["engine_unsupported"][0]["relation"])
        self.assertFalse(report["accepted"])  # unsupported is a safety blocker, not accepted
        self.assertIn("only_u_turn", ra.summary_markdown(report))
        # The graph-builder limitation persists even when all probes find no
        # route, otherwise a real but untested only_u_turn could disappear.
        unroutable = run([rel(32, members(SOUTH, SOUTH), restriction="only_u_turn")],
                         FakeRouter({}))
        self.assertEqual(1, unroutable["counts"]["engine_unsupported"])
        self.assertEqual(0, unroutable["counts"]["no_route"])
        self.assertFalse(unroutable["accepted"])
        # An ordinary restriction failing alongside it still rejects the run.
        both = run([rel(30, members(SOUTH, SOUTH), restriction="only_u_turn"), rel(31, members())],
                   FakeRouter({**DIRECT, NORTH: [edge(SOUTH, 2), edge(NORTH, 4)],
                               WEST: [edge(SOUTH, 2), edge(WEST, 5)]}))
        self.assertEqual(1, both["counts"]["fail"])
        self.assertFalse(both["accepted"])

    def _run_rewritten(self, router, rewritten):
        parsed = [ra.parse_relation(rel(30, members(SOUTH, SOUTH), restriction="only_u_turn"))]
        return ra.run(ways(), parsed, lambda wanted: {n: COORDS[n] for n in wanted if n in COORDS},
                      router, "synthetic", rewritten)

    def test_rewritten_only_u_turn_is_probed_not_waived(self):
        ignoring = FakeRouter({NORTH: [edge(SOUTH, 2), edge(NORTH, 4)],
                               EAST: [edge(SOUTH, 2), edge(EAST, 3)],
                               WEST: [edge(SOUTH, 2), edge(WEST, 5)]})
        report = self._run_rewritten(ignoring, {("only_u_turn", 30)})
        self.assertEqual(0, report["counts"]["engine_unsupported"])
        self.assertEqual(1, report["counts"]["fail"])  # a rewrite that did not work still fails
        self.assertTrue(report["failures"][0]["enforced_by_rewrite"])
        self.assertFalse(report["accepted"])
        obeying = self._run_rewritten(FakeRouter({}), {("only_u_turn", 30)})
        self.assertEqual(0, obeying["counts"]["engine_unsupported"])
        self.assertEqual([30], obeying["rewritten_tested"])
        self.assertIn("rewritten", ra.summary_markdown(obeying))

    def test_unrewritten_only_u_turn_stays_unsupported(self):
        report = self._run_rewritten(FakeRouter({}), {("only_u_turn", 99)})
        self.assertEqual(1, report["counts"]["engine_unsupported"])
        self.assertFalse(report["accepted"])

    def test_split_way_parts_are_translated_back_to_the_osm_way(self):
        # OSM: w40 runs west-east straight through the via node (5 - 2 - 3). The rewrite split it
        # at node 2 in the routing copy; Valhalla reports the east part as PART.
        part = 9_000_000_000_000
        road = ra.load_ways([way(SOUTH, [1, 2]), way(40, [5, 2, 3])])
        parsed = [ra.parse_relation(rel(30, members(SOUTH, SOUTH), restriction="only_u_turn"))]
        coords = lambda wanted: {n: COORDS[n] for n in wanted if n in COORDS}  # noqa: E731
        uturn = [edge(SOUTH, 2), edge(SOUTH, 1)]
        ignoring = FakeRouter({SOUTH: uturn, EAST: [edge(SOUTH, 2), edge(part, 3)],
                               WEST: [edge(SOUTH, 2), edge(40, 5)]})
        untranslated = ra.run(road, parsed, coords, ignoring, "synthetic", {("only_u_turn", 30)})
        caught = ra.run(road, parsed, coords, ignoring, "synthetic", {("only_u_turn", 30)}, {part: 40})
        self.assertEqual(["pass", "inconclusive", "fail"],
                         [p["status"] for p in untranslated["failures"][0]["probes"]])
        self.assertEqual(["pass", "fail", "fail"], [p["status"] for p in caught["failures"][0]["probes"]])
        self.assertEqual(1, caught["split_ways_translated"])
        # Legal detours ending on either part pass once translated.
        detour = FakeRouter({SOUTH: uturn, EAST: uturn + [edge(20, 6), edge(part, 3)],
                             WEST: uturn + [edge(20, 4), edge(40, 5)]})
        ok = ra.run(road, parsed, coords, detour, "synthetic", {("only_u_turn", 30)}, {part: 40})
        self.assertEqual({"pass": 1}, {k: v for k, v in ok["counts"].items() if v})
        self.assertEqual(0, ok["known_routing_safety_blockers"])

    def test_split_way_mapping_must_be_in_reserved_range(self):
        import json
        import tempfile
        body = {"schema": 2, "restriction": "only_u_turn", "input": {"sha256": "a" * 64},
                "way_id_base": 9_000_000_000_000, "rewritten": [],
                "split_ways": {"9000000000000": 40}}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "rewrite.json"
            path.write_text(json.dumps(body))
            self.assertEqual({9_000_000_000_000: 40}, ra.load_split_ways(path, "a" * 64))
            with self.assertRaises(ValueError):
                ra.load_split_ways(path, "b" * 64)
            body["split_ways"] = {"41": 40}
            path.write_text(json.dumps(body))
            with self.assertRaises(ValueError):
                ra.load_split_ways(path, "a" * 64)

    def test_decoded_turn_must_match_the_routes_own_shape(self):
        # Real case r14551046 (George Street): the route went legally round a 5-7 m triangle, but
        # the shape decoder assigned it to the forbidden driveway. A verdict at the via node needs
        # the route's own shape to lie on the decoded ways.
        decoded = [edge(SOUTH, 2), edge(EAST, 3)]
        on_east = ra.RouteEdges(decoded, [COORDS[1], COORDS[2], COORDS[3]])
        went_north = ra.RouteEdges(decoded, [COORDS[1], COORDS[2], COORDS[4]])
        confirmed = run([rel(31, members())], FakeRouter({EAST: on_east}))
        self.assertEqual(1, confirmed["counts"]["fail"])  # shape agrees: a real violation still fails
        mismatch = run([rel(31, members())], FakeRouter({EAST: went_north}))
        self.assertEqual(0, mismatch["counts"]["fail"])
        self.assertEqual(0, mismatch["counts"]["pass"])  # never a pass either
        self.assertEqual(1, mismatch["counts"]["decode_mismatch"])
        self.assertEqual(31, mismatch["decode_mismatch"][0]["relation"])
        self.assertIn("decode_mismatch", mismatch["decode_mismatch"][0]["probes"][0]["status"])
        self.assertIn("relation/31", ra.summary_markdown(mismatch))
        # A decoded *legal* exit contradicted by the shape is not a pass.
        only = run([rel(32, members(SOUTH, NORTH), restriction="only_straight_on")],
                   FakeRouter({NORTH: ra.RouteEdges([edge(SOUTH, 2), edge(NORTH, 4)],
                                                    [COORDS[1], COORDS[2], COORDS[3]]),
                               EAST: None, WEST: None}))
        self.assertEqual(0, only["counts"]["pass"])
        self.assertEqual(1, only["counts"]["decode_mismatch"])

    def test_shape_check_ignores_stretches_decoded_to_other_ways(self):
        # Out-and-back on the exit (a U-turn 1 m along it) then away on another way: only the
        # stretch decoded to each way is compared with that way.
        via, east, north = COORDS[2], COORDS[3], COORDS[4]
        one_metre_east = (via[0], via[1] + (east[1] - via[1]) * 1.0 / ra.haversine(via, east))
        shape = [COORDS[1], via, one_metre_east, via, north]
        geometry = {SOUTH: [COORDS[1], via], EAST: [via, east], NORTH: [via, north]}
        self.assertLess(ra.shape_supports(shape, via, geometry[SOUTH], geometry[EAST], None, via), 0.1)
        self.assertGreater(ra.shape_supports(shape, via, geometry[SOUTH], geometry[EAST]), 1.5)

    def test_rewrite_report_must_match_source(self):
        import json
        import tempfile
        body = {"schema": 1, "restriction": "only_u_turn", "input": {"sha256": "a" * 64},
                "rewritten": [{"relation": 30, "generated": [{"id": 9000000000000}]},
                              {"relation": 31, "generated": []}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "rewrite.json"
            path.write_text(json.dumps(body))
            self.assertEqual({("only_u_turn", 30)}, ra.load_rewrite_report(path, "a" * 64))
            with self.assertRaises(ValueError):
                ra.load_rewrite_report(path, "b" * 64)
            with self.assertRaises(ValueError):
                ra.load_rewrite_report(path, None)


class NoTurnTests(unittest.TestCase):
    def test_no_right_turn_passes_with_legal_detour(self):
        report = run([rel(1, members())], FakeRouter(DETOUR))
        self.assertEqual(1, report["counts"]["pass"])
        self.assertTrue(report["accepted"])
        self.assertEqual([], report["failures"])

    def test_short_driveway_near_and_far_destinations_preserve_violation(self):
        road = ra.load_ways([
            way(SOUTH, [1, 2], oneway="yes"),
            way(EAST, [2, 3], highway="service", service="driveway", oneway="yes"),
        ])
        class TerminalEdgeRouter(ra.Router):
            def route(self, start, end):
                # Near-endpoint routing is different; illegal far endpoint still fails.
                if ra.haversine(VIA, (end.lat, end.lon)) < 38.0:
                    return None
                return [edge(SOUTH, 2), edge(EAST, 3)]
        result = run([rel(14551046, members(), restriction="no_left_turn")],
                     TerminalEdgeRouter(), road)
        self.assertEqual(1, result["counts"]["fail"])
        self.assertFalse(result["accepted"])
        failure = result["failures"][0]
        self.assertTrue(failure["target_way_context"]["two_node_driveway"])
        self.assertEqual({0.35, 0.8}, {p["target_fraction"] for p in failure["probes"]})
        self.assertEqual({"fail", "no_route"}, {p["status"] for p in failure["probes"]})
        self.assertIn("two-node driveway probe positions", ra.summary_markdown(result))

    def test_no_right_turn_fails_on_direct_turn(self):
        report = run([rel(2, members())], FakeRouter(DIRECT))
        self.assertEqual(1, report["counts"]["fail"])
        self.assertFalse(report["accepted"])
        self.assertEqual(1, report["known_routing_safety_blockers"])
        failure = report["failures"][0]
        self.assertEqual((2, "no_right_turn", SOUTH, 2, EAST), (
            failure["relation"], failure["restriction"], failure["from_way"],
            failure["via_node"], failure["to_way"]))
        self.assertEqual("https://www.openstreetmap.org/relation/2", failure["osm_url"])
        self.assertIn("r2", ra.summary_markdown(report))

    def test_probe_starts_on_from_way_heading_to_via(self):
        relation = ra.parse_relation(rel(3, members()))
        r_ways = ways()
        case, reason = ra.build_case(relation, r_ways, COORDS, {2: {SOUTH, EAST, NORTH, WEST}})
        self.assertIsNone(reason)
        probe = case.probes[0]
        self.assertLess(probe.start.lat, VIA[0])
        self.assertLess(ra.angle_between(probe.start.heading, 0.0), 1.0)
        self.assertLess(ra.angle_between(probe.end.heading, 90.0), 1.0)
        self.assertTrue(30 <= ra.haversine(VIA, (probe.start.lat, probe.start.lon)) <= 80)

    def test_no_route_recorded_not_passed(self):
        report = run([rel(4, members())], FakeRouter({EAST: None}))
        self.assertEqual(1, report["counts"]["no_route"])
        self.assertEqual(0, report["counts"]["pass"])
        self.assertEqual(4, report["no_route_examples"][0]["relation"])
        self.assertTrue(report["accepted"])  # only FAIL rejects

    def test_route_snapped_to_other_way_is_inconclusive(self):
        report = run([rel(5, members())], FakeRouter({EAST: [edge(WEST, 2), edge(EAST, 3)]}))
        self.assertEqual(1, report["counts"]["inconclusive"])
        self.assertEqual(0, report["counts"]["pass"])

    def test_route_against_probe_direction_is_inconclusive(self):
        # A short same-way "route" that never reverses must not count as a legal U-turn detour.
        router = FakeRouter({SOUTH: [edge(SOUTH, 1, 0, 0)]})
        report = run([rel(9, members(SOUTH, SOUTH), restriction="no_u_turn")], router)
        self.assertEqual(1, report["counts"]["inconclusive"])

    def test_router_snapping_error_is_inconclusive(self):
        class Unsnapped(ra.Router):
            def route(self, start, end):
                raise ra.ProbeInconclusive("location not snapped")
        report = run([rel(10, members())], Unsnapped())
        self.assertEqual(1, report["counts"]["inconclusive"])
        self.assertEqual("location not snapped",
                         report["inconclusive_examples"][0]["probes"][0]["detail"])

    def test_no_u_turn_on_same_way_fails_when_reversed_at_via(self):
        router = FakeRouter({SOUTH: [edge(SOUTH, 2, 0, 0), edge(SOUTH, 1, 180, 180)]})
        report = run([rel(6, members(SOUTH, SOUTH), restriction="no_u_turn")], router)
        self.assertEqual(1, report["counts"]["fail"])

    def test_no_u_turn_detour_passes(self):
        router = FakeRouter({SOUTH: [edge(SOUTH, 2, 0, 0), edge(NORTH, 4, 0, 0), edge(NORTH, 2, 180, 180),
                                     edge(SOUTH, 1, 180, 180)]})
        report = run([rel(7, members(SOUTH, SOUTH), restriction="no_u_turn")], router)
        self.assertEqual(1, report["counts"]["pass"])


class OnlyTurnTests(unittest.TestCase):
    def only(self, routes):
        return run([rel(8, members(SOUTH, NORTH), restriction="only_straight_on")], FakeRouter(routes))

    def test_only_straight_on_fails_when_route_turns_off(self):
        report = self.only({NORTH: [edge(SOUTH, 2), edge(NORTH, 4)],
                            EAST: [edge(SOUTH, 2), edge(EAST, 3)]})
        self.assertEqual(1, report["counts"]["fail"])
        failure = report["failures"][0]
        bad = [p for p in failure["probes"] if p["status"] == "fail"]
        self.assertEqual([EAST], [p["target_way"] for p in bad])

    def test_only_straight_on_mandated_route_and_detours_pass(self):
        # A full PASS requires all four exits to have actual decoded routes.
        # The previous fixture omitted SOUTH and WEST yet expected PASS.
        legal_route = [edge(SOUTH, 2), edge(NORTH, 4)]
        around = [edge(SOUTH, 2), edge(NORTH, 4), edge(NORTH, 2)]
        report = self.only({
            NORTH: legal_route,
            EAST: [*around, edge(EAST, 3)],
            SOUTH: [*around, edge(SOUTH, 1)],
            WEST: [*around, edge(WEST, 5)],
        })
        self.assertEqual(1, report["counts"]["pass"])
        self.assertEqual(0, report["counts"]["fail"])
        self.assertEqual(0, report["counts"]["inconclusive"])
        self.assertEqual(0, report["counts"]["no_route"])

    def test_only_turn_mixed_success_and_inconclusive_is_not_a_pass(self):
        result = self.only({
            NORTH: [edge(SOUTH, 2), edge(NORTH, 4)],
            EAST: [edge(SOUTH, 2), edge(NORTH, 4), edge(20, 6), edge(21, 3), edge(EAST, 2)],
            WEST: [edge(WEST, 2), edge(WEST, 5)],  # snapped onto another road
            # SOUTH is unroutable; neither result is a verified pass.
        })
        self.assertEqual(0, result["counts"]["pass"])
        self.assertEqual(1, result["counts"]["inconclusive"])
        western_probe = next(p for p in result["inconclusive_examples"][0]["probes"]
                             if p["target_way"] == WEST)
        self.assertEqual("inconclusive", western_probe["status"])

    def test_only_turn_mixed_success_and_no_route_is_not_a_pass(self):
        result = self.only({NORTH: [edge(SOUTH, 2), edge(NORTH, 4)]})
        self.assertEqual(0, result["counts"]["pass"])
        self.assertEqual(1, result["counts"]["no_route"])
        self.assertEqual(0, result["counts"]["fail"])

    def test_only_probes_every_other_exit_including_u_turn(self):
        router = FakeRouter({})
        relation = ra.parse_relation(rel(9, members(SOUTH, NORTH), restriction="only_straight_on"))
        case, _ = ra.build_case(relation, ways(), COORDS, {2: {SOUTH, EAST, NORTH, WEST}})
        self.assertEqual({NORTH: False, EAST: True, WEST: True, SOUTH: True},
                         {p.target_way: p.forbidden for p in case.probes})
        ra.judge_case(case, router)
        self.assertEqual(4, len(router.calls))


class SkipTests(unittest.TestCase):
    def test_one_way_from_way_not_towards_via_is_skipped(self):
        report = run([rel(20, members())], FakeRouter(DIRECT), ways(oneway="-1"))
        self.assertEqual({"from_way_not_drivable_towards_via": 1}, report["skipped"])
        self.assertEqual(0, report["tested"])

    def test_one_way_from_way_towards_via_is_tested(self):
        report = run([rel(21, members())], FakeRouter(DIRECT), ways(oneway="yes"))
        self.assertEqual(1, report["counts"]["fail"])

    def test_way_via_skipped(self):
        road = ra.load_ways([way(SOUTH, [1, 2]), way(30, [2, 4]), way(EAST, [4, 6])])
        relations = [rel(22, [("w", SOUTH, "from"), ("w", 30, "via"), ("w", EAST, "to")])]
        report = run(relations, FakeRouter(DIRECT), road)
        self.assertEqual({"way_via": 1}, report["skipped"])

    def test_conditional_and_timed_skipped(self):
        relations = [rel(23, members(), **{"restriction:conditional": "no_right_turn%20%@%20%(Mo-Fr)"}),
                     rel(24, members(), hour_on="07:00", hour_off="10:00")]
        report = run(relations, FakeRouter(DIRECT))
        self.assertEqual({"conditional_or_timed": 2}, report["skipped"])
        self.assertTrue(report["accepted"])

    def test_motorcar_exception_and_vehicle_specific_skipped(self):
        relations = [rel(25, members(), **{"except": "bicycle;motorcar"}),
                     rel(26, members(), **{"restriction:hgv": "no_right_turn"})]
        report = run(relations, FakeRouter(DIRECT))
        self.assertEqual({"motorcar_exception": 1, "vehicle_specific": 1}, report["skipped"])

    def test_malformed_relation_skipped_as_needing_review(self):
        report = run([rel(27, members()[1:])], FakeRouter(DIRECT))
        self.assertEqual(1, report["skipped"]["needs_review"])
        self.assertEqual(1, report["skipped"]["needs_review:missing_required_role"])
        self.assertEqual(1, report["skipped_total"])

    def test_no_entry_unsupported(self):
        report = run([rel(28, members(), restriction="no_entry")], FakeRouter(DIRECT))
        self.assertEqual({"unsupported_type": 1}, report["skipped"])


class HelperTests(unittest.TestCase):
    def test_polyline_decoding(self):
        points = ra.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
        self.assertEqual([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)], points)

    def test_oneway_semantics(self):
        self.assertEqual({ra.FORWARD}, ra.drivable_directions({"junction": "roundabout"}))
        self.assertEqual({ra.FORWARD}, ra.drivable_directions({"highway": "motorway"}))
        self.assertEqual({ra.BACKWARD}, ra.drivable_directions({"oneway": "-1"}))
        self.assertEqual(set(), ra.drivable_directions({"oneway": "reversible"}))
        self.assertEqual({ra.FORWARD, ra.BACKWARD},
                         ra.drivable_directions({"oneway": "yes", "oneway:motorcar": "no"}))

    def test_opl_reading(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.opl"
            path.write_text("n1 v1 x-2.24 y53.479\nn2 v1 x-2.24 y53.48\n" + way(SOUTH, [1, 2])
                            + rel(1, members()), encoding="utf-8")
            road, relations = ra.read_opl(path)
            self.assertEqual([SOUTH], list(road))
            self.assertEqual(1, relations[0][0])
            self.assertEqual({2: (53.48, -2.24)}, ra.read_node_coords(path, {2}))

    def test_module_does_not_require_pyvalhalla(self):
        import subprocess
        code = ("import sys; sys.modules['valhalla'] = None; sys.modules['osmium'] = None; "
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); import restriction_acceptance")
        subprocess.run([sys.executable, "-c", code], check=True)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/manchester-acceptance.yml").read_text())

    def test_serialised_with_map_jobs_and_bounded(self):
        self.assertEqual({"group": "map-data", "cancel-in-progress": False}, self.workflow["concurrency"])
        job = self.workflow["jobs"]["acceptance"]
        self.assertLessEqual(job["timeout-minutes"], 45)

    def test_triggers_limited_to_own_files(self):
        triggers = self.workflow.get("on", self.workflow.get(True))
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(["codex/architecture-foundation"], triggers["push"]["branches"])
        self.assertEqual({"scripts/restriction_acceptance.py", "tests/test_restriction_acceptance.py",
                          "scripts/restriction_rewrite.py", "tests/test_restriction_rewrite.py",
                          ".github/workflows/manchester-acceptance.yml"}, set(triggers["push"]["paths"]))

    def test_actions_are_pinned_and_router_version_fixed(self):
        steps = self.workflow["jobs"]["acceptance"]["steps"]
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[0-9a-f]{40}\Z")
        text = (ROOT / ".github/workflows/manchester-acceptance.yml").read_text()
        self.assertIn("pyvalhalla==3.6.3", text)
        self.assertIn("greater-manchester-latest.osm.pbf", text)
        self.assertIn("restriction_acceptance.py", text)

    def test_graph_built_from_rewritten_extract_and_checked_against_original(self):
        text = (ROOT / ".github/workflows/manchester-acceptance.yml").read_text()
        self.assertIn("restriction_rewrite.py --input work/base.osm.pbf \\\n            --output work/rewritten.osm.pbf", text)
        self.assertIn("valhalla_build_tiles -c work/valhalla.json work/rewritten.osm.pbf", text)
        self.assertIn("--pbf work/base.osm.pbf", text)
        self.assertIn("--rewrite-report work/restriction-rewrite.json", text)


if __name__ == "__main__":
    unittest.main()
