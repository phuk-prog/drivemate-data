import unittest
from scripts.region_verifier_evidence import reconcile

class RegionalEvidenceTest(unittest.TestCase):
    def test_invalid_manifest_rejected(self):
        with self.assertRaises(ValueError):
            reconcile({}, ".", 1)
