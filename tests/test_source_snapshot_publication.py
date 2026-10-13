"""A retained source must be the actual map input before any remote mutation."""
import json
import unittest

import test_publish_map_data as publication_fixtures

publisher = publication_fixtures.publisher


class SnapshotPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = publication_fixtures.PublisherTest("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare_navigation_sample()
        self.out = self.fixture.out
        self.github = self.fixture.github
        self.source = self.out.parent / "synthetic.osm.pbf"
        self.parts = self.out / "osm-source"
        self.url = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"

    def retain(self):
        publisher.osm_snapshot.retain(self.source, self.parts, self.url, 4)
        consistency = publisher._load("publication_consistency")
        (self.out / "build-quality.json").write_text(json.dumps({
            "errors": [], "asset_snapshot": consistency.snapshot_assets(self.out)}))

    def test_checked_source_is_in_immutable_release_inventory(self):
        self.retain()
        publisher.publish(self.github, self.out, "map-data-synthetic-snapshot", navigation_data=True)
        manifest = json.loads(self.github.files["map-data-synthetic-snapshot"]["manifest.json"])
        self.assertIn("osm-source-manifest.json", manifest["files"])
        self.assertIn("osm-source.part00000", manifest["files"])

    def test_different_source_input_never_uploads(self):
        self.source.write_bytes(b"another source")
        self.retain()
        with self.assertRaisesRegex(ValueError, "differs from the map input"):
            publisher.publish(self.github, self.out, "map-data-wrong-source", navigation_data=True)
        self.assertEqual([], self.github.actions)

    def test_corrupt_chunk_never_uploads(self):
        self.retain()
        (self.parts / "osm-source.part00000").write_bytes(b"oops")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            publisher.publish(self.github, self.out, "map-data-corrupt-source", navigation_data=True)
        self.assertEqual([], self.github.actions)

    def test_partial_snapshot_never_uploads(self):
        self.parts.mkdir()
        (self.parts / "osm-source.part00000").write_bytes(b"test")
        with self.assertRaisesRegex(ValueError, "requires its manifest"):
            publisher.publish(self.github, self.out, "map-data-partial-source", navigation_data=True)
        self.assertEqual([], self.github.actions)


if __name__ == "__main__":
    unittest.main()
