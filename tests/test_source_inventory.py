"""Tests for source fingerprint capture and tampering protections."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "source_inventory", Path(__file__).resolve().parents[1] / "scripts/source_inventory.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
URL = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.osm = self.dir / "base.osm.pbf"
        self.osm.write_bytes(b"synthetic OSM")
        self.optional = {k: self.dir / (k + ".dat") for k in source.SOURCES if k != "osm_uk"}

    def test_absent_optional_sources_explicit_and_required_hashed(self):
        result = source.validate(source.build(self.osm, URL, self.optional))
        self.assertEqual(5, len(result["sources"]))
        self.assertTrue(result["sources"][0]["present"])
        self.assertEqual(64, len(result["sources"][0]["sha256"]))
        self.assertTrue(all(not r["present"] for r in result["sources"][1:]))
        self.assertTrue(all(r["rights_review"] == "not_independently_verified" for r in result["sources"]))

    def test_present_optional_source_hashed_and_readable(self):
        self.optional["os_open_names"].write_bytes(b"fake zip")
        result = source.build(self.osm, URL, self.optional)
        f = self.dir / "source-inventory.json"
        f.write_text(json.dumps(result))
        self.assertEqual(result, source.read(f))
        self.assertTrue(next(x for x in result["sources"] if x["id"] == "os_open_names")["present"])

    def test_missing_or_empty_osm_fails(self):
        self.osm.unlink()
        with self.assertRaisesRegex(ValueError, "Required OSM"):
            source.build(self.osm, URL, self.optional)
        self.osm.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            source.build(self.osm, URL, self.optional)

    def test_invalid_fingerprint_or_licence_fails(self):
        result = source.build(self.osm, URL, self.optional)
        result["sources"][0]["sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            source.validate(result)
        result = source.build(self.osm, URL, self.optional)
        result["sources"][0]["declared_licence"] = "unlicensed"
        with self.assertRaisesRegex(ValueError, "declarations"):
            source.validate(result)

    def test_duplicate_record_fails(self):
        result = source.build(self.osm, URL, self.optional)
        result["sources"][1] = result["sources"][0].copy()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            source.validate(result)


if __name__ == "__main__":
    unittest.main()
