"""Coverage spot checks across four UK nations; full places integrity tests."""
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
        all_points = list(coverage.NATION_PROBES.values())
        all_points.extend(point for items in coverage.REGIONAL_PROBES.values() for point in items)
        for _, lat, lon in all_points:
            for layer, (scale, key, suffix) in coverage.LAYER_SPECS.items():
                path = self.out / layer / f"{layer}-{math.floor(lat * scale)}_{math.floor(lon * scale)}{suffix}"
                path.parent.mkdir(exist_ok=True)
                value = {key: [{"id": 1}]} if key else [["Example", "", "", lat, lon]]
                opener = gzip.open if suffix == ".json.gz" else open
                with opener(path, "wt", encoding="utf-8") as stream:
                    json.dump(value, stream)

    def test_all_23_anchors_with_populated_tiles_pass(self):
        self.populate()
        report = coverage.audit(self.out)
        self.assertEqual([], report["errors"])
        self.assertEqual(4, len(report["probes"]))
        self.assertEqual(19, sum(len(rows) for rows in report["regional_probes"].values()))
        self.assertGreaterEqual(report["place_archive_audit"]["files_checked"], 19)
        self.assertEqual(0, report["place_archive_audit"]["invalid_or_empty"])

    def test_missing_original_city_core_layer_is_blocking(self):
        self.populate()
        (self.out / "limits" / "limits-109_-12.json").unlink()
        report = coverage.audit(self.out)
        self.assertEqual(1, len(report["errors"]))
        self.assertIn("Belfast", report["errors"][0])
        self.assertFalse(report["probes"]["Northern Ireland"]["layers"]["limits"]["present"])

    def test_missing_new_region_place_tile_blocks_publish(self):
        self.populate()
        (self.out / "places" / "places-201_-17.json.gz").unlink()  # Plymouth
        report = coverage.audit(self.out)
        self.assertTrue(any("Plymouth" in x for x in report["errors"]))

    def test_unmapped_optional_lane_detail_is_warning_not_fake_lane(self):
        self.populate()
        (self.out / "lanes" / "lanes-100_-9.json").unlink()  # Plymouth
        report = coverage.audit(self.out)
        self.assertEqual([], report["errors"])
        self.assertTrue(any("Plymouth" in x and "lanes" in x for x in report["warnings"]))

    def test_corrupted_gzip_and_coordinates_detected_across_whole_region(self):
        self.populate()
        tile = self.out / "places" / "places-201_-17.json.gz"
        tile.write_bytes(b"not gzip")
        report = coverage.audit(self.out)
        self.assertTrue(any("Plymouth" in x for x in report["errors"]))
        self.assertTrue(any("places-201_-17.json.gz" in x for x in report["errors"]))
        self.populate()
        # A plausible looking but wrong geographical assignment must be rejected.
        with gzip.open(tile, "wt", encoding="utf-8") as stream:
            json.dump([["Wrong", "", "", 60.0, -1.0]], stream)
        report = coverage.audit(self.out)
        self.assertTrue(any("coordinate outside declared tile" in x for x in report["errors"]))

    def test_invalid_archive_elsewhere_not_covered_by_city_probes_blocks(self):
        self.populate()
        extra = self.out / "places" / "places-220_-20.json.gz"
        with gzip.open(extra, "wt", encoding="utf-8") as stream:
            json.dump([["Imaginary", "", "", "not-latitude", -5]], stream)
        report = coverage.audit(self.out)
        self.assertTrue(any("places-220_-20.json.gz" in x for x in report["errors"]))
        self.assertEqual(1, report["place_archive_audit"]["invalid_or_empty"])

    def test_bad_place_shape_and_empty_archive_fail(self):
        self.populate()
        tile = self.out / "places" / "places-218_-24.json.gz"
        with gzip.open(tile, "wt", encoding="utf-8") as stream:
            json.dump([], stream)
        report = coverage.audit(self.out)
        self.assertTrue(any("Belfast" in x and "places" in x for x in report["errors"]))
        self.assertGreaterEqual(report["place_archive_audit"]["invalid_or_empty"], 1)


if __name__ == "__main__":
    unittest.main()
