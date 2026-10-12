import unittest
from scripts.region_verifier_evidence import reconcile

class RegionalEvidenceTests(unittest.TestCase):
    def test_missing_manifest_is_rejected(self):
        with self.assertRaises(ValueError):
            reconcile({}, ".", 1)

    def test_invalid_index_is_rejected(self):
        manifest = {"schema": 1, "status": "pilot_unpublished",
                    "source_sha256": "a" * 64,
                    "packages": {"base": {}, "region-z8-x126-y82": {}}}
        with self.assertRaises(ValueError):
            reconcile(manifest, ".", 0)
