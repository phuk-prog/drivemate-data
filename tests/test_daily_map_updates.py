"""Daily planning never confuses a failed/missing source with verified new coverage."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daily_map_updates as daily

A, B = "a" * 64, "b" * 64


def catalog(pipeline=A):
    return {"schema": 1, "pipeline": pipeline, "regions": [
        {"id": i, "url": f"https://download.geofabrik.de/europe/{i}-latest.osm.pbf", "sha256": A}
        for i in ("north", "south")]}


def receipts(plan):
    return {"schema": 1, "regions": [{k: v for k, v in record.items() if k != "reasons"}
                                      | {"verified": True} for record in plan["selected"]]}


class DailyMapUpdatesTests(unittest.TestCase):
    def installed(self):
        plan = daily.plan_updates(catalog(), budget=2)
        return daily.advance_checkpoint(plan, receipts(plan))

    def test_stable_is_noop_and_does_not_mutate_inputs(self):
        state = self.installed()
        before = copy.deepcopy(state)
        result = daily.plan_updates(catalog(), state)
        self.assertEqual([], result["selected"])
        self.assertEqual(["north", "south"], result["unchanged"])
        self.assertEqual(before, state)

    def test_priority_and_budget_defer_work(self):
        plan = daily.plan_updates(catalog(), priorities=["south"], budget=1)
        self.assertEqual(["south"], [r["id"] for r in plan["selected"]])
        self.assertEqual(["north"], [r["id"] for r in plan["deferred"]])

    def test_content_and_pipeline_changes_rebuild(self):
        new = catalog(B)
        new["regions"][0]["sha256"] = B
        plan = daily.plan_updates(new, self.installed(), budget=2)
        self.assertEqual(["source content changed", "pipeline or schema changed"], plan["selected"][0]["reasons"])
        self.assertEqual(["pipeline or schema changed"], plan["selected"][1]["reasons"])

    def test_partial_success_keeps_failed_pipeline_for_retry(self):
        state = self.installed()
        plan = daily.plan_updates(catalog(B), state, budget=2)
        result = receipts(plan)
        result["regions"][1] = {"id": "south", "verified": False}
        checkpoint = daily.advance_checkpoint(plan, result)
        self.assertEqual(state["regions"]["south"], checkpoint["regions"]["south"])
        retry = daily.plan_updates(catalog(B), checkpoint)
        self.assertEqual(["south"], [r["id"] for r in retry["selected"]])

    def test_missing_sources_block_and_preserve_old_coverage(self):
        new = catalog()
        new["regions"].pop()
        state = self.installed()
        plan = daily.plan_updates(new, state)
        self.assertTrue(plan["blocked"])
        self.assertEqual([], plan["selected"])
        self.assertIn("south", plan["previous"]["regions"])
        with self.assertRaises(ValueError):
            daily.advance_checkpoint(plan, {"schema": 1, "regions": []})
        self.assertTrue(daily.plan_updates(catalog(), priorities=["unknown"])["blocked"])

    def test_receipt_identity_and_budget_are_enforced(self):
        plan = daily.plan_updates(catalog())
        for field in ("url", "sha256", "pipeline"):
            result = receipts(plan)
            result["regions"][0][field] = B if field != "url" else "https://download.geofabrik.de/europe/other.osm.pbf"
            with self.assertRaises(ValueError):
                daily.advance_checkpoint(plan, result)
        result = receipts(plan)
        result["regions"][0]["id"] = "south"
        with self.assertRaises(ValueError):
            daily.advance_checkpoint(plan, result)

    def test_untrusted_urls_and_malformed_catalogs_are_rejected(self):
        for url in ("http://download.geofabrik.de/a.osm.pbf", "https://evil.example/a.osm.pbf",
                    "https://download.geofabrik.de@evil.example/a.osm.pbf",
                    "https://download.geofabrik.de:443/a.osm.pbf",
                    "https://download.geofabrik.de/../a.osm.pbf",
                    "https://download.geofabrik.de/%2e%2e/a.osm.pbf",
                    "https://download.geofabrik.de/a.osm.pbf?redirect=evil",
                    "https://download.geo\nfabrik.de/a.osm.pbf"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                daily.source_url(url)
        for budget in (0, 101, True):
            with self.assertRaises(ValueError):
                daily.plan_updates(catalog(), budget=budget)
        bad = catalog()
        bad["regions"].append(bad["regions"][0])
        with self.assertRaises(ValueError):
            daily.plan_updates(bad)
        with self.assertRaises(ValueError):
            daily.plan_updates(catalog(), {"schema": 1, "verified": False, "regions": {}})
        for bad in ({"schema": 1, "pipeline": A, "regions": []}, catalog() | {"schema": True}):
            with self.assertRaises(ValueError):
                daily.plan_updates(bad)

    def test_cli_json_roundtrip_and_failed_checkpoint_preserves_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, planned, received, output = [root / n for n in ("catalog.json", "plan.json", "receipts.json", "state.json")]
            source.write_text(json.dumps(catalog()))
            self.assertEqual(0, daily.main(["plan", "--catalog", str(source), "--output", str(planned), "--priority", "south"]))
            plan = json.loads(planned.read_text())
            received.write_text(json.dumps(receipts(plan)))
            self.assertEqual(0, daily.main(["checkpoint", "--plan", str(planned), "--receipts", str(received), "--output", str(output)]))
            saved = output.read_text()
            received.write_text('{"schema":1,"regions":[{"id":"north","verified":true}]}')
            with self.assertRaises(SystemExit):
                daily.main(["checkpoint", "--plan", str(planned), "--receipts", str(received), "--output", str(output)])
            self.assertEqual(saved, output.read_text())


if __name__ == "__main__":
    unittest.main()
