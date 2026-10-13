import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("snapshot", Path(__file__).parents[1] / "scripts/osm_source_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)
URL = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.osm.pbf"
        self.payload = bytes(range(256)) * 3
        self.source.write_bytes(self.payload)
        self.out = self.root / "out"

    def test_exact_reassembly_and_deterministic_manifest(self):
        manifest = snapshot.retain(self.source, self.out, URL, 100)
        actual = b"".join((self.out / part["name"]).read_bytes() for part in manifest["chunks"])
        self.assertEqual(self.payload, actual)
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(), manifest["source_sha256"])
        self.assertEqual(8, len(manifest["chunks"]))
        second = self.root / "other"
        snapshot.retain(self.source, second, URL, 100)
        self.assertEqual((self.out / "osm-source-manifest.json").read_bytes(),
                         (second / "osm-source-manifest.json").read_bytes())

    def test_corruption_and_missing_chunks_fail(self):
        snapshot.retain(self.source, self.out, URL, 100)
        part = self.out / "osm-source.part00000"
        part.write_bytes(b"x" * 100)
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)
        part.unlink()
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)

    def test_source_and_destination_guardrails(self):
        for bad in ("http://download.geofabrik.de/a.osm.pbf", "https://evil.test/a.osm.pbf",
                    "https://download.geofabrik.de/a.osm.pbf?secret=x"):
            with self.assertRaises(ValueError):
                snapshot.retain(self.source, self.out, bad)
        self.out.mkdir()
        sentinel = self.out / "existing"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            snapshot.retain(self.source, self.out, URL)
        self.assertEqual("keep", sentinel.read_text())

    def test_manifest_path_escape_is_rejected(self):
        snapshot.retain(self.source, self.out, URL, 100)
        path = self.out / "osm-source-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["chunks"][0]["name"] = "../source.osm.pbf"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)

    def test_exact_multiple_and_small_source(self):
        snapshot.retain(self.source, self.out, URL, 256)
        self.assertEqual(3, len(snapshot.verify(self.out)["chunks"]))

    def test_same_size_source_mutation_aborts_atomic_capture(self):
        original_verify = snapshot.verify
        def mutate_after_check(directory):
            result = original_verify(directory)
            self.source.write_bytes(b"x" * len(self.payload))
            return result
        with mock.patch.object(snapshot, "verify", side_effect=mutate_after_check):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                snapshot.retain(self.source, self.out, URL, 100)
        self.assertFalse(self.out.exists())

    def test_symlink_sources_parents_manifests_and_parts_are_rejected(self):
        link = self.root / "link.osm.pbf"
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            snapshot.retain(link, self.out, URL)
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            snapshot.retain(parent / self.source.name, self.out, URL)
        snapshot.retain(self.source, self.out, URL, 100)
        part = self.out / "osm-source.part00000"
        saved = self.root / "part"
        part.rename(saved)
        part.symlink_to(saved)
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)
        part.unlink()
        saved.rename(part)
        manifest = self.out / "osm-source-manifest.json"
        saved_manifest = self.root / "manifest"
        manifest.rename(saved_manifest)
        manifest.symlink_to(saved_manifest)
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)

    def test_noncanonical_urls_fail(self):
        for url in ("https://download.geofabrik.de//a.osm.pbf",
                    "https://download.geofabrik.de/a/../b.osm.pbf",
                    "https://download.geofabrik.de/a/%2e%2e/b.osm.pbf",
                    "https://download.geofabrik.de:443/a.osm.pbf",
                    "https://download.geofabrik.de/a.osm.pbf#", None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                snapshot.check_url(url)

    def test_malformed_manifest_values_and_reordered_parts_fail(self):
        snapshot.retain(self.source, self.out, URL, 100)
        path = self.out / "osm-source-manifest.json"
        original = json.loads(path.read_text())
        for key, value in (("schema", True), ("source_bytes", True),
                           ("source_bytes", snapshot.MAX_SOURCE_BYTES + 1),
                           ("source_sha256", "invalid"), ("chunks", [None]),
                           ("chunks", list(reversed(original["chunks"]))),
                           ("chunks", original["chunks"] * snapshot.MAX_CHUNKS)):
            with self.subTest(key=key, value_type=type(value).__name__):
                altered = dict(original, **{key: value})
                path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    snapshot.verify(self.out)
        path.write_bytes(b" " * (snapshot.MAX_MANIFEST_BYTES + 1))
        with self.assertRaises(ValueError):
            snapshot.verify(self.out)

    def test_one_byte_source_and_chunk_count_limit(self):
        self.source.write_bytes(b"z")
        snapshot.retain(self.source, self.out, URL, 1)
        self.assertEqual(1, snapshot.verify(self.out)["source_bytes"])
        self.source.write_bytes(b"z" * (snapshot.MAX_CHUNKS + 1))
        with self.assertRaises(ValueError):
            snapshot.retain(self.source, self.root / "too-many", URL, 1)


if __name__ == "__main__":
    unittest.main()
