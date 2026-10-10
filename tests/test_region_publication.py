"""Regional publication staging: only a complete verified UK set of the exact map is published."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import region_publication as rp

spec = importlib.util.spec_from_file_location("publisher_regional", ROOT / "scripts/publish_map_data.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

MAP = b"PMTiles" + b"x" * 30


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RegionPublicationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "drivemate.pmtiles").write_bytes(MAP)
        self.regions = self.root / "regions"
        self.regions.mkdir()
        self.payloads = {"base": b"PMTiles\x03" + b"b" * 200, "region-z8-x126-y82": b"PMTiles\x03" + b"m" * 300}
        packages = {}
        for name, data in self.payloads.items():
            (self.regions / f"{name}.pmtiles").write_bytes(data)
            packages[name] = {"filename": f"{name}.pmtiles", "bytes": len(data), "sha256": sha(data),
                              "tiles": 3, "verified_tile_payloads": 3}
        self.manifest = {"schema": 1, "status": "unpublished", "source_sha256": sha(MAP),
                         "base_zoom_max": 9, "detail_zoom_min": 10, "pilot_root": None,
                         "source_addressed_tiles": 6, "selected_addressed_tiles": 6, "packages": packages}
        self.write_manifest()

    def write_manifest(self):
        (self.regions / "regional-manifest.json").write_text(json.dumps(self.manifest))

    def test_stage_moves_verified_set_and_marks_published(self):
        staged = rp.stage(self.regions, self.out / "regions", self.out / "drivemate.pmtiles")
        self.assertEqual("published", staged["status"])
        self.assertEqual("regional-base.pmtiles", staged["packages"]["base"]["filename"])
        names = sorted(p.name for p in (self.out / "regions").iterdir())
        self.assertEqual(["region-z8-x126-y82.pmtiles", "regional-base.pmtiles", "regional-manifest.json"], names)
        files = {p.name: p for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual("published", rp.validate_staged(files)["status"])

    def test_stage_refuses_pilot_partial_or_foreign_exports(self):
        for change in ({"pilot_root": "8/126/82"}, {"selected_addressed_tiles": 5},
                       {"source_sha256": "f" * 64}):
            self.manifest.update(change)
            self.write_manifest()
            with self.assertRaises(ValueError):
                rp.stage(self.regions, self.out / "r", self.out / "drivemate.pmtiles")
            self.setUp()

    def test_stage_refuses_tampered_or_unverified_archive(self):
        (self.regions / "region-z8-x126-y82.pmtiles").write_bytes(b"PMTiles\x03" + b"z" * 300)
        with self.assertRaises(ValueError):
            rp.stage(self.regions, self.out / "r", self.out / "drivemate.pmtiles")
        self.setUp()
        self.manifest["packages"]["base"]["verified_tile_payloads"] = 2
        self.write_manifest()
        with self.assertRaises(ValueError):
            rp.stage(self.regions, self.out / "r", self.out / "drivemate.pmtiles")

    def test_validate_staged_catches_extra_missing_or_swapped_assets(self):
        rp.stage(self.regions, self.out / "regions", self.out / "drivemate.pmtiles")
        files = {p.name: p for p in self.out.rglob("*") if p.is_file()}
        self.assertIsNone(rp.validate_staged({"drivemate.pmtiles": files["drivemate.pmtiles"]}))
        missing = dict(files)
        del missing["regional-base.pmtiles"]
        with self.assertRaises(ValueError):
            rp.validate_staged(missing)
        no_manifest = dict(files)
        del no_manifest["regional-manifest.json"]
        with self.assertRaises(ValueError):
            rp.validate_staged(no_manifest)
        (self.out / "drivemate.pmtiles").write_bytes(MAP + b"changed")
        with self.assertRaises(ValueError):
            rp.validate_staged(files)

    def test_publisher_accepts_staged_set_and_rejects_orphans(self):
        (self.out / "build-info.txt").write_text("Synthetic\n")
        (self.out / "cameras-uk.json").write_text('{"elements": []}')
        (self.out / "lanes-106_-5.json").write_text('{"ways": []}')
        with gzip.open(self.out / "places-212_-9.json.gz", "wt") as stream:
            json.dump([["Synthetic place", "", "", 53.0, -2.0]], stream)
        with patch.object(publisher, "MIN_MAP_BYTES", 20):
            rp.stage(self.regions, self.out / "regions", self.out / "drivemate.pmtiles")
            files = publisher.local_files(self.out)
            self.assertIn("region-z8-x126-y82.pmtiles", files)
            self.assertIn("regional-manifest.json", files)
            (self.out / "regions" / "region-z8-x127-y82.pmtiles").write_bytes(b"PMTiles\x03" + b"o" * 200)
            with self.assertRaises(ValueError):
                publisher.local_files(self.out)


if __name__ == "__main__":
    unittest.main()
