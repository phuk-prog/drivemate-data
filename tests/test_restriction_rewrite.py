"""only_u_turn -> no_* rewrite on parsed structures (no network, no pyosmium, no pyvalhalla)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import restriction_rewrite as rr  # noqa: E402

# Plus junction at node 2 (lat, lon). Driving north on SOUTH: NORTH straight, EAST right, WEST left.
COORDS = {1: (53.4790, -2.2400), 2: (53.4800, -2.2400), 3: (53.4800, -2.2385),
          4: (53.4810, -2.2400), 5: (53.4800, -2.2415), 7: (53.4790, -2.2399)}
SOUTH, EAST, NORTH, WEST = 10, 11, 12, 13


def road(nodes, **tags):
    return ({"highway": "residential", **tags}, nodes)


def plus(overrides=None):
    ways = {SOUTH: road([1, 2]), EAST: road([2, 3]), NORTH: road([2, 4]), WEST: road([2, 5])}
    ways.update(overrides or {})
    return ways


def uturn(ident=1, from_way=SOUTH, to_way=SOUTH, **tags):
    return (ident, {"type": "restriction", "restriction": "only_u_turn", **tags},
            [("w", from_way, "from"), ("n", 2, "via"), ("w", to_way, "to")])


def generated(new):
    return {(members[2][1], tags["restriction"]) for _, tags, members in new}


class RewriteTests(unittest.TestCase):
    def test_four_way_gives_straight_left_right(self):
        new, dropped, report = rr.rewrite([uturn()], plus(), COORDS)
        self.assertEqual({(NORTH, "no_straight_on"), (EAST, "no_right_turn"), (WEST, "no_left_turn")},
                         generated(new))
        self.assertEqual([1], dropped)
        for _, tags, members in new:
            self.assertEqual([("w", SOUTH, "from"), ("n", 2, "via")], members[:2])
            self.assertEqual("1", tags["drivemate:rewritten_from"])
            self.assertEqual("restriction", tags["type"])
        self.assertEqual(3, report["counts"]["generated_relations"])

    def test_t_junction_with_split_main_road(self):
        ways = plus()
        del ways[NORTH]
        new, _, _ = rr.rewrite([uturn()], ways, COORDS)
        self.assertEqual({(EAST, "no_right_turn"), (WEST, "no_left_turn")}, generated(new))

    def test_exit_way_through_via_is_split_and_both_parts_banned(self):
        # Valhalla restricts only one edge of a to-way passing through the via node, so the
        # routing copy splits that way at the via node and bans each part separately.
        ways = {SOUTH: road([1, 2]), 20: road([5, 2, 3], name="Cross Road", maxspeed="20 mph")}
        result = rr.plan([uturn()], ways, COORDS)
        new, report = result["new_relations"], result["report"]
        part = rr.WAY_ID_BASE
        self.assertEqual({(20, "no_left_turn"), (part, "no_right_turn")}, generated(new))
        self.assertEqual([1], result["dropped"])
        self.assertEqual({20: [5, 2]}, result["way_edits"])
        self.assertEqual([(part, {"highway": "residential", "name": "Cross Road", "maxspeed": "20 mph"},
                           [2, 3])], result["new_ways"])
        self.assertEqual({str(part): 20}, report["split_ways"])
        self.assertEqual(1, report["counts"]["split_ways"])
        self.assertEqual([part], report["rewritten"][0]["split_ways"])
        self.assertEqual(2, report["schema"])
        # Same nodes overall, shared node at the via: geometry and connectivity unchanged.
        first, (_, _, second) = result["way_edits"][20], result["new_ways"][0]
        self.assertEqual([5, 2, 3], first + second[1:])

    def test_one_way_through_via_bans_only_the_drivable_part(self):
        ways = {SOUTH: road([1, 2]), 20: road([5, 2, 3], oneway="yes")}
        new, _, report = rr.rewrite([uturn()], ways, COORDS)
        self.assertEqual({(rr.WAY_ID_BASE, "no_right_turn")}, generated(new))  # 5 -> 2 only arrives
        self.assertEqual(1, report["counts"]["split_ways"])

    def test_split_repoints_other_relations(self):
        ways = {SOUTH: road([1, 2]), 20: road([5, 2, 3]), 40: road([3, 4])}
        part = rr.WAY_ID_BASE
        other_restriction = (50, {"type": "restriction", "restriction": "no_left_turn"},
                             [("w", 20, "from"), ("n", 3, "via"), ("w", 40, "to")])
        route = (51, {"type": "route", "route": "road", "ref": "B1"},
                 [("w", 40, ""), ("w", 20, ""), ("w", 99, "")])
        result = rr.plan([uturn()], ways, COORDS, others=[other_restriction, route])
        self.assertEqual({50: [("w", part, "from"), ("n", 3, "via"), ("w", 40, "to")],
                          51: [("w", 40, ""), ("w", 20, ""), ("w", part, ""), ("w", 99, "")]},
                         result["relation_edits"])
        self.assertEqual([50, 51], result["report"]["splits"][0]["relations_repointed"])

    def test_split_refused_when_another_relation_becomes_ambiguous(self):
        ways = {SOUTH: road([1, 2]), 20: road([5, 2, 3])}
        at_same_via = (50, {"type": "restriction", "restriction": "no_right_turn"},
                       [("w", 20, "from"), ("n", 2, "via"), ("w", SOUTH, "to")])
        as_via_way = (52, {"type": "restriction", "restriction": "no_u_turn"},
                      [("w", SOUTH, "from"), ("w", 20, "via"), ("w", SOUTH, "to")])
        for other in (at_same_via, as_via_way):
            result = rr.plan([uturn()], ways, COORDS, others=[other])
            self.assertEqual(([], [], {}, {}), (result["new_relations"], result["dropped"],
                                                result["way_edits"], result["relation_edits"]))
            self.assertEqual({"split_conflicts_with_relation": 1}, result["report"]["skipped_by_reason"])
            self.assertEqual({}, result["report"]["split_ways"])

    def test_closed_way_through_via_is_not_split(self):
        ways = {SOUTH: road([1, 2]), 20: road([5, 2, 3, 4, 5])}
        new, dropped, report = rr.rewrite([uturn()], ways, COORDS)
        self.assertEqual(([], []), (new, dropped))
        self.assertEqual({"exit_way_not_splittable": 1}, report["skipped_by_reason"])

    def test_later_split_repoints_earlier_generated_relation(self):
        coords = {**COORDS, 8: (53.4800, -2.2370), 9: (53.4810, -2.2385)}
        ways = {SOUTH: road([1, 2]), 20: road([8, 3, 2]), 30: road([9, 3]), WEST: road([2, 5])}
        second = (2, {"type": "restriction", "restriction": "only_u_turn"},
                  [("w", 30, "from"), ("n", 3, "via"), ("w", 30, "to")])
        new, dropped, report = rr.rewrite([uturn(), second], ways, coords)
        part = rr.WAY_ID_BASE
        self.assertEqual([1, 2], dropped)
        self.assertEqual({str(part): 20}, report["split_ways"])
        by_origin = {}
        for _, tags, members in new:
            by_origin.setdefault(tags["drivemate:rewritten_from"], set()).add((members[2][1], tags["restriction"]))
        # r1 at node 2: its east exit is now the split-off part [3, 2], not w20 [8, 3].
        self.assertEqual({(part, "no_right_turn"), (WEST, "no_left_turn")}, by_origin["1"])
        # r2 at node 3, driving south: east part (w20 [8, 3]) is a left, west part a right.
        self.assertEqual({(20, "no_left_turn"), (part, "no_right_turn")}, by_origin["2"])

    def test_way_ids_must_stay_below_split_range(self):
        with self.assertRaises(ValueError):
            rr.rewrite([uturn()], plus(), COORDS, max_way_id=rr.WAY_ID_BASE)

    def test_opposite_carriageway_target_adds_u_turn_ban_on_from_way(self):
        ways = plus({70: road([2, 7], oneway="yes")})
        del ways[NORTH]
        new, _, report = rr.rewrite([uturn(to_way=70)], ways, COORDS)
        self.assertEqual({(SOUTH, "no_u_turn"), (EAST, "no_right_turn"), (WEST, "no_left_turn")},
                         generated(new))
        self.assertEqual("opposite_carriageway", report["rewritten"][0]["u_turn_onto"])

    def test_inbound_one_way_and_footway_exits_need_no_ban(self):
        ways = plus({EAST: road([3, 2], oneway="yes"), WEST: road([2, 5], highway="footway")})
        new, _, _ = rr.rewrite([uturn()], ways, COORDS)
        self.assertEqual({(NORTH, "no_straight_on")}, generated(new))

    def test_unknown_one_way_exit_is_still_banned(self):
        new, _, _ = rr.rewrite([uturn()], plus({EAST: road([2, 3], oneway="reversible")}), COORDS)
        self.assertIn((EAST, "no_right_turn"), generated(new))

    def test_conditional_except_and_vehicle_tags_are_preserved(self):
        rel = uturn(**{"except": "bus;bicycle", "day_on": "Monday", "hour_on": "07:00",
                       "restriction:hgv": "only_u_turn",
                       "restriction:conditional": "only_u_turn @ (Mo-Fr 07:00-09:00)"})
        new, _, report = rr.rewrite([rel], plus(), COORDS)
        self.assertEqual(3, len(new))
        for _, tags, members in new:
            kind = tags["restriction"]
            self.assertEqual("bus;bicycle", tags["except"])
            self.assertEqual("Monday", tags["day_on"])
            self.assertEqual("07:00", tags["hour_on"])
            self.assertEqual(kind, tags["restriction:hgv"])
            self.assertEqual(f"{kind} @ (Mo-Fr 07:00-09:00)", tags["restriction:conditional"])
        self.assertIn("except", report["rewritten"][0]["tags_preserved"])
        # Conditional-only relation (no plain restriction tag) is rewritten in the same way.
        cond = (2, {"type": "restriction", "restriction:conditional": "only_u_turn @ (Sa,Su)"},
                uturn()[2])
        new, _, _ = rr.rewrite([cond], plus(), COORDS)
        self.assertEqual({"no_straight_on @ (Sa,Su)", "no_left_turn @ (Sa,Su)", "no_right_turn @ (Sa,Su)"},
                         {t["restriction:conditional"] for _, t, _ in new})
        self.assertTrue(all("restriction" not in t for _, t, _ in new))

    def test_mixed_values_skipped(self):
        rel = uturn(**{"restriction:conditional": "no_left_turn @ (Mo-Fr)"})
        mixed = uturn(2, **{"restriction:conditional": "only_u_turn @ (Sa); no_straight_on @ (Su)"})
        new, dropped, report = rr.rewrite([rel, mixed], plus(), COORDS)
        self.assertEqual(([], []), (new, dropped))
        self.assertEqual({"mixed_restriction_values": 2}, report["skipped_by_reason"])

    def test_ambiguous_relations_skipped(self):
        way_via = (3, {"type": "restriction", "restriction": "only_u_turn"},
                   [("w", SOUTH, "from"), ("w", NORTH, "via"), ("w", SOUTH, "to")])
        two_from = (4, {"type": "restriction", "restriction": "only_u_turn"},
                    [("w", SOUTH, "from"), ("w", EAST, "from"), ("n", 2, "via"), ("w", SOUTH, "to")])
        through = uturn(5)  # from way passes through the via node
        ways = plus({SOUTH: road([1, 2, 4])})
        del ways[NORTH]
        missing = uturn(6, to_way=99)
        _, dropped, report = rr.rewrite([way_via, two_from], plus(), COORDS)
        self.assertEqual([], dropped)
        self.assertEqual({"way_via": 1, "not_single_from_via_to": 1}, report["skipped_by_reason"])
        _, _, report = rr.rewrite([through], ways, COORDS)
        self.assertEqual({"from_way_passes_through_via": 1}, report["skipped_by_reason"])
        _, _, report = rr.rewrite([missing], plus(), COORDS)
        self.assertEqual({"member_way_missing": 1}, report["skipped_by_reason"])
        _, _, report = rr.rewrite([uturn(7)], plus({SOUTH: road([1, 2], oneway="-1")}), COORDS)
        self.assertEqual({"from_way_oneway_away_from_via": 1}, report["skipped_by_reason"])

    def test_non_candidates_ignored(self):
        other = (8, {"type": "restriction", "restriction": "no_left_turn"}, uturn()[2])
        new, dropped, report = rr.rewrite([other], plus(), COORDS)
        self.assertEqual((0, [], []), (report["counts"]["candidates"], new, dropped))

    def test_output_ids_unique_and_out_of_osm_range(self):
        rels = [uturn(i) for i in (5, 1, 3)]
        new, dropped, _ = rr.rewrite(rels, plus(), COORDS, max_relation_id=20_000_000)
        ids = [r[0] for r in new]
        self.assertEqual(9, len(set(ids)))
        self.assertEqual(list(range(rr.ID_BASE, rr.ID_BASE + 9)), ids)  # deterministic, sorted
        self.assertEqual([1, 3, 5], dropped)
        with self.assertRaises(ValueError):
            rr.rewrite(rels, plus(), COORDS, max_relation_id=rr.ID_BASE)
        with self.assertRaises(ValueError):
            rr.rewrite([uturn(1), uturn(1)], plus(), COORDS)

    def test_only_valhalla_supported_types_generated(self):
        self.assertTrue(rr.GENERATED_TYPES <= {"no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn"})
        self.assertEqual(("no_left_turn", -90.0), rr.turn_type(0.0, 270.0))
        self.assertEqual(("no_right_turn", 90.0), rr.turn_type(0.0, 90.0))
        self.assertEqual("no_straight_on", rr.turn_type(350.0, 20.0)[0])

    def test_module_does_not_require_pyosmium_at_import(self):
        source = (ROOT / "scripts/restriction_rewrite.py").read_text()
        self.assertNotIn("\nimport osmium", source)


class WorkflowWiringTests(unittest.TestCase):
    def test_rewrite_runs_before_each_graph_build(self):
        import yaml
        for name, job, step_name in (("manchester-acceptance.yml", "acceptance", None),
                                     ("route-crosscheck.yml", "crosscheck", None),
                                     ("map-data.yml", "routing", "Build the road graph")):
            wf = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            runs = "\n".join(s.get("run", "") for s in wf["jobs"][job]["steps"]
                             if step_name is None or s.get("name") == step_name)
            self.assertIn("scripts/restriction_rewrite.py", runs, name)
            self.assertLess(runs.index("restriction_rewrite.py"), runs.index("valhalla_build_tiles"), name)


if __name__ == "__main__":
    unittest.main()
