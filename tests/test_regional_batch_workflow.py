"""Static guards for the regional batch workflow: serialized, budgeted, never uploads map payloads."""
from pathlib import Path
import unittest

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/regional-batch.yml"


class RegionalBatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(WORKFLOW.read_text())
        self.steps = self.doc["jobs"]["batch"]["steps"]
        self.text = WORKFLOW.read_text()

    def test_shares_the_single_expensive_map_lane(self):
        self.assertEqual({"group": "map-data", "cancel-in-progress": False}, self.doc["concurrency"])

    def test_disabled_request_skips_every_expensive_step(self):
        for step in self.steps[3:]:
            if step.get("name", "").startswith("Retain"):
                continue
            self.assertIn("steps.permission.outputs.enabled == 'true'", step.get("if", ""), step.get("name"))

    def test_loop_is_bounded_by_request_budget_and_checkpoints_each_region(self):
        loop = next(s for s in self.steps if s.get("name", "").startswith("Verify and checkpoint"))["run"]
        self.assertIn("region_batch_queue.py budget", loop)
        self.assertIn('seq 1 "$budget"', loop)
        self.assertIn("START_DEADLINE_SECONDS", loop)
        # Commit + push happen inside the loop, before the next region starts.
        self.assertLess(loop.index("git push origin HEAD:codex/architecture-foundation"), loop.rindex("done"))
        self.assertNotIn("--force", loop)
        self.assertIn('rm -rf "$out"', loop)

    def test_evidence_upload_never_includes_map_archives(self):
        upload = next(s for s in self.steps if s.get("name", "").startswith("Retain"))
        paths = upload["with"]["path"]
        self.assertNotIn(".pmtiles", paths)
        self.assertNotIn("work/region-", paths)


if __name__ == "__main__":
    unittest.main()
