"""Publication identity is checked against files, not a bare 'passed' flag."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "publication_consistency",
    Path(__file__).resolve().parents[1] / "scripts/publication_consistency.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        (self.directory / "drivemate.pmtiles").write_bytes(b"PMTiles" + b"x" * 14)
        (self.directory / "lanes").mkdir()
        (self.directory / "lanes" / "lanes-1_2.json").write_text('{"ways": []}')

    def report(self):
        return {"version": 1, "errors": [], "asset_snapshot": module.snapshot_assets(self.directory)}

    def test_original_snapshot_verified(self):
        report = self.report()
        self.assertEqual(2, len(report["asset_snapshot"]["files"]))
        self.assertEqual(report["asset_snapshot"], module.verify_snapshot(self.directory, report))

    def test_changed_bytes_are_rejected(self):
        report = self.report()
        (self.directory / "lanes" / "lanes-1_2.json").write_text('{"ways": [1]}')
        with self.assertRaisesRegex(ValueError, "differs from"):
            module.verify_snapshot(self.directory, report)

    def test_removed_and_extra_assets_rejected(self):
        report = self.report()
        (self.directory / "lanes" / "lanes-1_2.json").unlink()
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            module.verify_snapshot(self.directory, report)
        (self.directory / "lanes" / "lanes-1_2.json").write_text('{"ways": []}')
        (self.directory / "lanes" / "lanes-2_3.json").write_text('{"ways": []}')
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            module.verify_snapshot(self.directory, report)

    def test_report_and_markdown_not_self_hashed(self):
        report = self.report()
        (self.directory / "build-quality.json").write_text(json.dumps(report))
        (self.directory / "build-quality.md").write_text("pass\n")
        self.assertEqual(report["asset_snapshot"], module.verify_snapshot(self.directory, report))

    def test_legacy_bare_success_and_malformed_snapshot_fail(self):
        for report in ({"errors": []}, {"errors": ["failure"]}, {"errors": [],
                         "asset_snapshot": {"schema": 1, "files": {}}}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                module.verify_snapshot(self.directory, report)
        report = self.report()
        broken = copy.deepcopy(report)
        broken["asset_snapshot"]["files"]["drivemate.pmtiles"]["sha256"] = "short"
        with self.assertRaisesRegex(ValueError, "Invalid quality"):
            module.verify_snapshot(self.directory, broken)

    def test_duplicate_basename_or_symlink_rejected(self):
        report = self.report()
        (self.directory / "copy").mkdir()
        (self.directory / "copy" / "lanes-1_2.json").write_text('{"ways": []}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            module.verify_snapshot(self.directory, report)
        (self.directory / "copy" / "lanes-1_2.json").unlink()
        (self.directory / "copy" / "link").symlink_to(self.directory / "drivemate.pmtiles")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            module.verify_snapshot(self.directory, report)


if __name__ == "__main__":
    unittest.main()
