"""Regression tests for four-nation regional map presence checks."""
import gzip
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/coverage_audit.py"
spec = importlib.util.spec_from_file_location("coverage_audit", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)

    def populate(self):
        for _, lat, lon in coverage.NATION_PROBES.values():
            for layer, (scale, key, suffix) in coverage.LAYER_SPECS.items():
                path = self.out / layer / f"{layer}-{math.floor(lat * scale)}_{math.floor(lon * scale)}{suffix}"
                path.parent.mkdir(exist_ok=True)
                value = {key: [{"id": 1}]} if key else [["Example", "", "", lat, lon]]
                opener = gzip.open if suffix == ".json.gz" else open
                with opener(path, "wt", encoding="utf-8") as stream:
                    json.dump(value, stream)

    def test_four_nations_and_all_layers_pass_with_populated_tiles(self):
        self.populate()
        report = coverage.audit(self.out)
        self.assertEqual([], report["errors"])
        self.assertEqual(4, len(report["probes"]))
        self.assertTrue(all(v["populated"] for p in report["probes"].values()
                            for v in p["layers"].values()))
        self.assertIn("not Northern Ireland", report["warnings"][0])

    def test_missing_country_layer_fails_even_if_other_tiles_exist(self):
        self.populate()
        filepath = self.out / "limits" / "limits-109_-12.json"
        filepath.unlink()
        report = coverage.audit(self.out)
        self.assertEqual(1, len(report["errors"]))
        self.assertIn("Belfast", report["errors"][0])
        self.assertFalse(report["probes"]["Northern Ireland"]["layers"]["limits"]["present"])

    def test_corrupt_or_empty_tile_fails_closed(self):
        self.populate()
        (self.out / "lanes" / "lanes-102_-7.json").write_text("{broken", encoding="utf-8")
        path = self.out / "places" / "places-218_-24.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            stream.write("[]")
        report = coverage.audit(self.out)
        self.assertEqual(2, len(report["errors"]))
        self.assertEqual("JSONDecodeError", report["probes"]["Wales"]["layers"]["lanes"]["error"])
        self.assertFalse(report["probes"]["Northern Ireland"]["layers"]["places"]["populated"])


if __name__ == "__main__":
    unittest.main()
