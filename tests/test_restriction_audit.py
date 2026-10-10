"""Synthetic OPL checks for noninvented prohibited-turn diagnostics."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from restriction_audit import audit, parse_relation


def way(ident, refs, **tags):
    parts = {"highway": "residential", **tags}
    return "w%d T%s N%s\n" % (
        ident, ",".join(f"{k}={v}" for k, v in parts.items()),
        ",".join("n%d" % n for n in refs))


def rel(ident, members, **tags):
    fields = {"type": "restriction", "restriction": "no_left_turn", **tags}
    return "r%d T%s M%s\n" % (
        ident, ",".join(f"{k}={v}" for k, v in fields.items()),
        ",".join(f"{kind}{wid}@{role}" for kind, wid, role in members))


VIA = [("w", 1, "from"), ("n", 2, "via"), ("w", 3, "to")]
WAYS = [way(1, [1, 2]), way(3, [2, 4])]


class TurnRestrictionTests(unittest.TestCase):
    def test_simple_no_left_turn_shared_node(self):
        result = audit(WAYS, [rel(10, VIA)], "synthetic")
        self.assertEqual(1, result["restriction_relations"])
        self.assertEqual(0, result["counts"].get("needs_review", 0))

    def test_only_right_turn_also_supported(self):
        result = audit(WAYS, [rel(10, VIA, restriction="only_right_turn")], "synthetic")
        self.assertEqual(0, result["counts"].get("needs_review", 0))

    def test_missing_from_or_to_never_invents_restriction(self):
        report = audit(WAYS, [rel(11, VIA[1:])], "synthetic")
        self.assertIn("missing_required_role", report["examples"][0]["review_reasons"])

    def test_via_node_must_occur_in_both_ways(self):
        bad = [way(1, [1, 9]), way(3, [2, 4])]
        result = audit(bad, [rel(12, VIA)], "synthetic")
        self.assertIn("from_way_does_not_touch_via", result["examples"][0]["review_reasons"])

    def test_via_way_is_not_inherently_invalid(self):
        ways = [way(1, [1, 2]), way(2, [2, 3]), way(3, [3, 4])]
        members = [("w", 1, "from"), ("w", 2, "via"), ("w", 3, "to")]
        result = audit(ways, [rel(13, members)], "synthetic")
        self.assertEqual(0, result["counts"].get("needs_review", 0))
        self.assertEqual(1, result["counts"].get("way_via", 0))

    def test_disconnected_via_way_reported_not_repaired(self):
        ways = [way(1, [1, 2]), way(2, [9, 10]), way(3, [10, 11])]
        members = [("w", 1, "from"), ("w", 2, "via"), ("w", 3, "to")]
        result = audit(ways, [rel(14, members)], "synthetic")
        self.assertIn("from_way_disconnected_from_via_way", result["examples"][0]["review_reasons"])

    def test_explicit_oneway_conflict_flagged_for_review(self):
        ways = [way(1, [2, 1], oneway="yes"), way(3, [2, 4], oneway="yes")]
        report = audit(ways, [rel(15, VIA)], "synthetic")
        self.assertIn("from_possible_oneway_orientation_conflict", report["examples"][0]["review_reasons"])

    def test_motorcar_exception_skips_orientation_assumptions(self):
        ways = [way(1, [2, 1], oneway="yes"), way(3, [2, 4], oneway="yes")]
        result = audit(ways, [rel(16, VIA, **{"except": "motorcar"})], "synthetic")
        self.assertEqual(0, result["counts"].get("needs_review", 0))
        self.assertEqual(1, result["counts"].get("motorcar_exceptions", 0))

    def test_conditional_avoids_unconditional_oneway_assertion(self):
        ways = [way(1, [2, 1], oneway="yes"), way(3, [2, 4])]
        result = audit(ways, [rel(17, VIA, **{"restriction:conditional": "no_left_turn%20%@%20%(Mo-Fr)"})], "synthetic")
        self.assertEqual(1, result["counts"].get("conditional_relations", 0))
        self.assertEqual(0, result["counts"].get("needs_review", 0))

    def test_absent_road_reference_flagged_not_called_bad_turn(self):
        result = audit(WAYS, [rel(20, [("w", 555, "from"), ("n", 2, "via"), ("w", 3, "to")])], "synthetic")
        self.assertEqual([555], result["examples"][0]["missing_sample_way_ids"])

    def test_osmium_opl_percent_escapes_and_no_entry_multiple_from(self):
        members = [("w", 1, "from"), ("w", 5, "from"), ("n", 2, "via"), ("w", 3, "to")]
        result = audit(WAYS + [way(5, [6, 2])], [rel(21, members, restriction="no_entry")], "synthetic")
        self.assertNotIn("multiple_from_members", [reason for x in result["examples"] for reason in x["review_reasons"]])
        self.assertEqual(1, result["restriction_relations"])

    def test_malformed_relation_and_duplicate_block(self):
        with self.assertRaisesRegex(ValueError, "Malformed restriction relation member"):
            parse_relation("r1 Ttype=restriction Mfoo")
        with self.assertRaisesRegex(ValueError, "Duplicate restriction relation"):
            audit(WAYS, [rel(10, VIA), rel(10, VIA)], "synthetic")


if __name__ == "__main__":
    unittest.main()
