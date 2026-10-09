"""Synthetic OPL regressions protecting legitimate dead ends and grade separation."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from junction_topology import analyze, parse_way, incompatible


def w(wayid, tags, refs):
    return f"w{wayid} T{tags} N" + ",".join("n" + str(n) for n in refs) + "\n"


class JunctionTopologyTests(unittest.TestCase):
    def test_true_shared_osm_node_connects_separate_way_ids(self):
        lines = [w(1, "highway=residential", [1, 2]), w(2, "highway=residential", [2, 3])]
        report = analyze(lines, minimum_ways=2)
        self.assertEqual(1, report["components"])
        self.assertEqual(1, report["junction_nodes"])
        self.assertEqual(2, report["largest_component_ways"])

    def test_geometrically_overlapping_but_distinct_osm_nodes_never_join(self):
        # The auditor deliberately does not infer an intersection from line pixels.
        lines = [w(1, "highway=primary,bridge=yes,layer=1", [1, 2, 3]),
                 w(2, "highway=secondary,tunnel=yes,layer=-1", [4, 5, 6])]
        report = analyze(lines, minimum_ways=2)
        self.assertEqual(2, report["components"])
        self.assertEqual(0, report["junction_nodes"])
        self.assertEqual(0, report["potential_level_conflicts_shown"])

    def test_conflicting_interior_shared_node_is_review_not_validated_turn(self):
        lines = [w(1, "highway=primary,bridge=yes,layer=1", [1, 2, 3]),
                 w(2, "highway=secondary,tunnel=yes,layer=-1", [4, 2, 6])]
        report = analyze(lines, minimum_ways=2)
        self.assertEqual(2, report["components"])
        self.assertEqual(1, report["junction_nodes"])
        self.assertEqual(1, report["potential_level_conflicts_shown"])
        self.assertEqual([1, 2], report["examples"]["possible_level_conflict"][0]["ways"])

    def test_road_bridge_end_node_may_legitimately_connect(self):
        lines = [w(1, "highway=primary,bridge=yes,layer=1", [1, 2]),
                 w(2, "highway=primary,layer=0", [2, 3])]
        report = analyze(lines, minimum_ways=2)
        self.assertEqual(1, report["components"])
        self.assertEqual(0, report["potential_level_conflicts_shown"])

    def test_ordinary_culdesac_is_not_reported_as_major_network_failure(self):
        lines = [w(1, "highway=residential", [1, 2, 3]),
                 w(2, "highway=service,noexit=yes", [2, 4])]
        report = analyze(lines, minimum_ways=2)
        self.assertEqual(0, report["possible_major_road_ends"])
        self.assertGreater(report["ordinary_or_explicit_dead_ends"], 0)

    def test_major_dead_end_is_only_diagnostic(self):
        report = analyze([w(1, "highway=primary", [1, 2])], minimum_ways=1)
        self.assertEqual(2, report["possible_major_road_ends"])
        self.assertEqual(0, report["malformed_segments_shown"])
        self.assertTrue(report["limitations"])

    def test_duplicate_adjacent_node_is_counted_without_fabricated_edge(self):
        report = analyze([w(1, "highway=primary", [5, 5, 6])], minimum_ways=1)
        self.assertEqual(1, report["malformed_segments_shown"])

    def test_percent_escaped_tags_and_opl_coordinate_refs(self):
        item = parse_way("w42 Tname=High%20%Street,highway=primary Nn1x-2.3y53.2,n2x-2.2y53.2")
        # A normal space is encoded in real OPL as %20%.
        self.assertEqual([1, 2], item[2])
        self.assertEqual("High Street", item[1]["name"])

    def test_bad_references_or_duplicate_way_fail(self):
        with self.assertRaisesRegex(ValueError, "invalid node reference"):
            analyze([w(1, "highway=primary", [1, 2]).replace("n2", "foo")], minimum_ways=1)
        with self.assertRaisesRegex(ValueError, "Duplicate OSM"):
            analyze([w(1, "highway=primary", [1, 2])] * 2, minimum_ways=1)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            analyze([w(1, "highway=primary", [1, 2])], minimum_ways=5)


if __name__ == "__main__":
    unittest.main()
