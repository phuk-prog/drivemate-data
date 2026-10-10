"""Queue safety tests; never download or publish map content."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from region_batch_queue import SOURCE_SHA, region_root, next_region, mark_complete

RUN = "https://github.com/phuk-prog/drivemate-data/actions/runs/38031100907"


def fixture():
    roots = {
        "base": {"tiles": 10},
        "region-z8-x126-y82": {"tiles": 2},
        "region-z9-x254-y164": {"tiles": 2},
        "region-z10-x508-y328": {"tiles": 2},
        "region-z8-x128-y82": {"tiles": 2},
    }
    plan = {"schema": 1, "status": "unpublished", "source_sha256": SOURCE_SHA,
            "base_zoom_max": 9, "detail_zoom_min": 10, "packages": roots}
    ledger = {"schema": 1, "source_sha256": SOURCE_SHA,
              "completed": {"8/126/82": {"passed": True, "run_url": RUN}}}
    return plan, ledger


class RegionQueueTests(unittest.TestCase):
    def test_hierarchical_children_own_unique_root(self):
        self.assertEqual("8/127/82", region_root("region-z9-x254-y164"))
        self.assertEqual("8/127/82", region_root("region-z10-x508-y328"))
        with self.assertRaises(ValueError):
            region_root("region-z8-x257-y82")

    def test_resume_picks_nearest_uncompleted_root(self):
        plan, ledger = fixture()
        selection = next_region(plan, ledger)
        self.assertEqual("selected", selection["status"])
        self.assertEqual("8/127/82", selection["root"])
        self.assertEqual(["region-z10-x508-y328","region-z9-x254-y164"],selection["packages"])
        self.assertEqual(1,selection["completed_roots"])

    def test_replay_sequence_rejected(self):
        plan, ledger = fixture()
        req = {"schema":1, "enabled":True,"sequence":3}
        self.assertEqual(3,next_region(plan,ledger,req)["sequence"])
        ledger["last_sequence"] = 3
        with self.assertRaises(ValueError):
            next_region(plan,ledger,req)

    def test_source_drift_refuses_prior_success(self):
        plan, ledger = fixture()
        plan["source_sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            next_region(plan, ledger)

    def test_success_requires_every_subdivided_package(self):
        plan, ledger = fixture()
        sel = next_region(plan, ledger)
        samples = ["base", *sel["packages"]]
        def info(i):
            return {"tiles": 2, "verified_tile_payloads": 2, "bytes": 1000,
                    "sha256": format(i + 1, "064x")}
        manifest = {"schema":1, "status":"pilot_unpublished", "source_sha256":SOURCE_SHA,
                    "pilot_root":sel["root"], "base_zoom_max":9, "detail_zoom_min":10,
                    "packages": {name: info(i) for i,name in enumerate(samples)}}
        good = mark_complete(sel, manifest, ledger, RUN)
        self.assertIn("8/127/82",good["completed"])
        self.assertNotIn("8/127/82",ledger["completed"])
        with self.assertRaises(ValueError):
            mark_complete(sel,manifest,good,RUN)
        partial = copy.deepcopy(manifest)
        del partial["packages"][sel["packages"][0]]
        with self.assertRaises(ValueError):
            mark_complete(sel,partial,ledger,RUN)
        damaged = copy.deepcopy(manifest)
        damaged["packages"][sel["packages"][0]]["verified_tile_payloads"] = 0
        with self.assertRaises(ValueError):
            mark_complete(sel,damaged,ledger,RUN)

    def test_all_done_stops_without_rebuilding(self):
        plan, ledger = fixture()
        for root in ("8/127/82","8/128/82"):
            ledger["completed"][root] = {"passed":True,"run_url":RUN}
        self.assertEqual("all_validated",next_region(plan,ledger)["status"])

    def test_bad_ledger_cannot_claim_unavailable_region(self):
        plan,ledger=fixture()
        ledger["completed"]["8/1/1"]={"passed":True,"run_url":RUN}
        with self.assertRaises(ValueError):
            next_region(plan,ledger)


if __name__=="__main__":
    unittest.main()
