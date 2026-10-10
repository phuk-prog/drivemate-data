"""Synthetic regressions for the speed-limit and camera acceptance checker (no network)."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import limit_acceptance as la

LAT, LON = 53.4000, -2.2000
KMH_30 = 30 * la.MPH
KMH_70 = 70 * la.MPH


def write_square(d, ways):
    p = pathlib.Path(d) / la.square_name(LAT, LON)
    p.write_text(json.dumps({"ways": ways}))


# East-west road through the checkpoint.
EW = [[LON - 0.002, LAT], [LON + 0.002, LAT]]
# North-south road crossing it.
NS = [[LON, LAT - 0.002], [LON, LAT + 0.002]]


class LimitAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def cp(self, **kw):
        base = {"id": "x", "name": "x", "lat": LAT, "lon": LON, "heading": 90}
        base.update(kw)
        return base

    def test_square_name_matches_generator(self):
        self.assertEqual(la.square_name(53.3956, -2.1942), "limits-106_-5.json")

    def test_match(self):
        write_square(self.d, [[KMH_70, EW]])
        r = la.check_one(self.cp(expect_mph=70), self.d, None)
        self.assertEqual((r["status"], r["found_mph"]), ("MATCH", 70))

    def test_mismatch(self):
        write_square(self.d, [[KMH_30, EW]])
        self.assertEqual(la.check_one(self.cp(expect_mph=70), self.d, None)["status"], "MISMATCH")

    def test_no_data_when_far_or_missing(self):
        write_square(self.d, [[KMH_30, [[LON - 0.002, LAT + 0.001], [LON + 0.002, LAT + 0.001]]]])
        self.assertEqual(la.check_one(self.cp(expect_mph=30), self.d, None)["status"], "NO_DATA")
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(la.check_one(self.cp(expect_mph=30), empty, None)["status"], "NO_DATA")

    def test_crossing_road_ignored_by_heading(self):
        write_square(self.d, [[KMH_30, NS], [KMH_70, EW]])
        self.assertEqual(la.check_one(self.cp(expect_mph=70, heading=90), self.d, None)["status"], "MATCH")
        self.assertEqual(la.check_one(self.cp(expect_mph=30, heading=0), self.d, None)["status"], "MATCH")
        # Opposite direction along the same road still counts.
        self.assertEqual(la.check_one(self.cp(expect_mph=70, heading=270), self.d, None)["status"], "MATCH")

    def test_expect_no_data(self):
        write_square(self.d, [[KMH_30, EW]])
        self.assertEqual(la.check_one(self.cp(expect_no_data=True), self.d, None)["status"], "MISMATCH")
        write_square(self.d, [])
        self.assertEqual(la.check_one(self.cp(expect_no_data=True), self.d, None)["status"], "MATCH")

    def test_camera(self):
        cams = {"elements": [{"type": "node", "id": 1, "lat": LAT + 0.0001, "lon": LON, "tags": {}},
                             {"type": "relation", "id": 2, "tags": {}, "members": []}]}
        near = la.check_one(self.cp(expect_camera_within_m=30), self.d, cams)
        self.assertEqual(near["status"], "MATCH")
        far = la.check_one(self.cp(expect_camera_within_m=5), self.d, cams)
        self.assertEqual(far["status"], "MISMATCH")
        self.assertEqual(la.check_one(self.cp(expect_camera_within_m=5), self.d, {"elements": []})["status"], "MISMATCH")
        self.assertEqual(la.check_one(self.cp(expect_camera_within_m=5), self.d, None)["status"], "NO_DATA")

    def test_main_exit_code_and_report(self):
        write_square(self.d, [[KMH_70, EW]])
        cpf = pathlib.Path(self.d) / "cp.json"
        rep = pathlib.Path(self.d) / "rep.json"
        cpf.write_text(json.dumps({"region": "t", "checkpoints": [self.cp(id="a", expect_mph=70)]}))
        self.assertEqual(la.main(["--limits-dir", self.d, "--checkpoints", str(cpf), "--report", str(rep)]), 0)
        self.assertEqual(json.loads(rep.read_text())["counts"]["MATCH"], 1)
        cpf.write_text(json.dumps({"region": "t", "checkpoints": [self.cp(id="a", expect_mph=30)]}))
        self.assertEqual(la.main(["--limits-dir", self.d, "--checkpoints", str(cpf)]), 1)

    def test_shipped_checkpoints_are_well_formed(self):
        p = pathlib.Path(__file__).resolve().parents[1] / "docs/validation/manchester-limits-checkpoints.json"
        spec = json.loads(p.read_text())
        self.assertGreaterEqual(len(spec["checkpoints"]), 10)
        for cp in spec["checkpoints"]:
            self.assertTrue(cp["source"].startswith("OSM "))
            self.assertTrue(any(k in cp for k in ("expect_mph", "expect_no_data", "expect_camera_within_m")))


if __name__ == "__main__":
    unittest.main()
