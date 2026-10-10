"""Synthetic regressions for the lane acceptance checker (no network, no real data)."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import lane_acceptance as la

# A straight east-west road at about 53.4 N: 0.003 degrees of longitude is roughly 200 m.
LAT = 53.40000
WEST, EAST = -2.20300, -2.20000
NORTH_OFFSET = 0.00010  # about 11 m north


def way(wid, tags, coords):
    return {"id": wid, "t": tags, "g": [[lon, lat] for lat, lon in coords]}


def doc(*ways):
    return {"source": "synthetic", "ways": list(ways)}


def cp(name, heading, lanes=None, arrows=None, lat=LAT + 0.00002, lon=-2.20150):
    out = {"name": name, "lat": lat, "lon": lon, "heading": heading}
    if lanes is not None:
        out["expected_lanes"] = lanes
    if arrows is not None:
        out["expected_arrows"] = arrows
    return out


EASTBOUND = way(101, {"oneway": "yes", "lanes": "2", "turn:lanes": "through|right", "name": "Test Road",
                      "ref": "A1"}, [(LAT, WEST), (LAT, EAST)])


class LaneAcceptanceTests(unittest.TestCase):
    def check(self, documents, checkpoint):
        return la.evaluate(la.LaneIndex(documents), checkpoint)

    def test_match_lane_count_and_arrows(self):
        r = self.check([doc(EASTBOUND)], cp("east", 90, lanes=2, arrows=["straight", "right"]))
        self.assertEqual("MATCH", r["verdict"])
        self.assertEqual(101, r["matched"]["way_id"])
        self.assertEqual("https://www.openstreetmap.org/way/101", r["matched"]["osm_url"])
        self.assertEqual([["straight"], ["right"]], r["arrows"])
        self.assertEqual(2, r["shown_lane_count"])

    def test_osm_arrow_names_are_accepted_in_expectations(self):
        r = self.check([doc(EASTBOUND)], cp("east", 90, arrows=["through", "right"]))
        self.assertEqual("MATCH", r["arrows_verdict"])

    def test_mismatch_count_and_arrows(self):
        r = self.check([doc(EASTBOUND)], cp("east", 90, lanes=3, arrows=["left", "straight", "right"]))
        self.assertEqual("MISMATCH", r["verdict"])
        self.assertEqual("MISMATCH", r["count_verdict"])
        self.assertEqual("MISMATCH", r["arrows_verdict"])
        r = self.check([doc(EASTBOUND)], cp("east", 90, lanes=2, arrows=["left", "right"]))
        self.assertEqual("MATCH", r["count_verdict"])
        self.assertEqual("MISMATCH", r["verdict"])

    def test_no_data_when_nothing_within_twenty_metres(self):
        far = cp("far", 90, lanes=2, lat=LAT + 0.0005)  # about 55 m away
        r = self.check([doc(EASTBOUND)], far)
        self.assertEqual("NO_DATA", r["verdict"])
        self.assertIsNone(r["matched"])

    def test_no_data_when_lane_count_present_but_no_arrows(self):
        w = way(102, {"oneway": "yes", "lanes": "2"}, [(LAT, WEST), (LAT, EAST)])
        r = self.check([doc(w)], cp("east", 90, lanes=2, arrows=["straight", "right"]))
        self.assertEqual("MATCH", r["count_verdict"])
        self.assertEqual("NO_DATA", r["arrows_verdict"])
        self.assertEqual("NO_DATA", r["verdict"])

    def test_crossing_road_is_ignored_by_heading(self):
        crossing = way(103, {"oneway": "yes", "lanes": "4"}, [(LAT - 0.001, -2.20150), (LAT + 0.001, -2.20150)])
        r = self.check([doc(crossing)], cp("east", 90, lanes=4))
        self.assertEqual("NO_DATA", r["verdict"])  # 90 degrees off: a road crossing yours

    def test_heading_tolerance_boundaries(self):
        ok = self.check([doc(EASTBOUND)], cp("east+39", 90 + 39, lanes=2))
        self.assertEqual("MATCH", ok["verdict"])
        self.assertTrue(ok["matched"]["forward"])
        crossing = self.check([doc(EASTBOUND)], cp("east+41", 90 + 41, lanes=2))
        self.assertEqual("NO_DATA", crossing["verdict"])
        backward = self.check([doc(EASTBOUND)], cp("west-ish", 270 - 39, lanes=2))
        self.assertFalse(backward["matched"]["forward"])

    def test_two_way_road_uses_direction_specific_tags(self):
        w = way(104, {"lanes": "4", "lanes:forward": "3", "lanes:backward": "1",
                      "turn:lanes:forward": "left|through|through"}, [(LAT, WEST), (LAT, EAST)])
        east = self.check([doc(w)], cp("east", 90, lanes=3, arrows=["left", "straight", "straight"]))
        self.assertEqual("MATCH", east["verdict"])
        west = self.check([doc(w)], cp("west", 270, lanes=1, arrows=["straight"]))
        self.assertFalse(west["matched"]["forward"])
        self.assertEqual(1, west["lane_count_app"])
        self.assertIsNone(west["arrows"])  # forward arrows are never used for the other direction
        self.assertEqual("NO_DATA", west["arrows_verdict"])

    def test_two_way_without_direction_counts_halves_total(self):
        w = way(105, {"lanes": "2"}, [(LAT, WEST), (LAT, EAST)])
        r = self.check([doc(w)], cp("east", 90, lanes=2))
        self.assertEqual(1, r["lane_count_app"])
        self.assertEqual("MISMATCH", r["verdict"])

    def test_wrong_direction_oneway_is_flagged_and_skipped_in_strict_match(self):
        # Dual carriageway: our eastbound carriageway is 11 m north; the nearer westbound one
        # (one-way, 3 lanes) runs along the checkpoint. The app's matcher ignores oneway, so it
        # picks the westbound way; the report flags that and gives the strict match too.
        westbound = way(201, {"oneway": "yes", "lanes": "3"}, [(LAT, EAST), (LAT, WEST)])
        eastbound = way(202, {"oneway": "yes", "lanes": "2"},
                        [(LAT + NORTH_OFFSET, WEST), (LAT + NORTH_OFFSET, EAST)])
        r = self.check([doc(westbound, eastbound)], cp("east", 90, lanes=2, lat=LAT + 0.00003))
        self.assertEqual(201, r["matched"]["way_id"])
        self.assertTrue(r["matched"]["against_oneway"])
        self.assertEqual(202, r["strict_oneway_match"]["way_id"])
        self.assertEqual(2, r["strict_oneway_match"]["lane_count_app"])
        self.assertTrue(any("against its direction" in n for n in r["notes"]))

    def test_wrong_direction_oneway_ignored_when_correct_carriageway_is_nearer(self):
        westbound = way(201, {"oneway": "yes", "lanes": "3"}, [(LAT, EAST), (LAT, WEST)])
        eastbound = way(202, {"oneway": "yes", "lanes": "2"},
                        [(LAT + NORTH_OFFSET, WEST), (LAT + NORTH_OFFSET, EAST)])
        r = self.check([doc(westbound, eastbound)], cp("east", 90, lanes=2, lat=LAT + 0.00009))
        self.assertEqual(202, r["matched"]["way_id"])
        self.assertFalse(r["matched"]["against_oneway"])
        self.assertNotIn("strict_oneway_match", r)
        self.assertEqual("MATCH", r["verdict"])

    def test_checkpoint_road_without_lane_data_is_not_a_match_on_a_neighbour(self):
        # The intended slip road (id 999) has no lane tags, so it is not in the file; the app
        # falls back to the parallel main road, whose count happens to equal the expectation.
        point = cp("slip", 90, lanes=2)
        point["expected_way_ids"] = [999]
        r = self.check([doc(EASTBOUND)], point)
        self.assertEqual("MATCH", r["count_verdict"])
        self.assertEqual("MISMATCH", r["way_verdict"])
        self.assertEqual("MISMATCH", r["verdict"])
        self.assertEqual({"999": False}, r["expected_ways_in_lane_data"])
        point["expected_way_ids"] = [101]
        self.assertEqual("MATCH", self.check([doc(EASTBOUND)], point)["verdict"])

    def test_duplicate_way_across_squares_is_indexed_once(self):
        index = la.LaneIndex([doc(EASTBOUND), doc(EASTBOUND)])
        self.assertEqual(1, index.ways)

    def test_cli_writes_json_and_markdown_without_changing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            lanes = tmp / "lanes-106_-5.json"
            lanes.write_text(json.dumps(doc(EASTBOUND)))
            before = lanes.read_bytes()
            cps = tmp / "cps.json"
            cps.write_text(json.dumps({"checkpoints": [cp("east", 90, lanes=2, arrows=["straight", "right"]),
                                                       cp("far", 90, lanes=2, lat=LAT + 0.01)]}))
            la.main(["--lanes", str(lanes), "--checkpoints", str(cps),
                     "--json-out", str(tmp / "out.json"), "--md-out", str(tmp / "out.md")])
            report = json.loads((tmp / "out.json").read_text())
            self.assertEqual({"MATCH": 1, "NO_DATA": 1}, report["summary"])
            self.assertIn("**MATCH**", (tmp / "out.md").read_text())
            self.assertEqual(before, lanes.read_bytes())


if __name__ == "__main__":
    unittest.main()
