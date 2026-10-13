import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import daily_source_remote as remote


class FakeDownloads:
    def __init__(self, checkpoint=True):
        self.data = {}
        cp = {"schema": 1, "source_url": "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf",
              "change_signal": {"algorithm": "md5", "value": "a" * 32},
              "pipeline_sha256": "b" * 64, "source_sha256": "c" * 64, "source_bytes": 100}
        cp_data = json.dumps(cp).encode()
        files = {"source-checkpoint.json": {"tag": "map-data-test-extra", "bytes": len(cp_data),
                  "sha256": hashlib.sha256(cp_data).hexdigest()}} if checkpoint else {}
        manifest = json.dumps({"schema": 1, "files": files}).encode()
        self.data[("map-data-uk", "latest.json")] = json.dumps({"schema": 1,
            "tag": "map-data-test", "manifest_sha256": hashlib.sha256(manifest).hexdigest()}).encode()
        self.data[("map-data-test", "manifest.json")] = manifest
        self.data[("map-data-test-extra", "source-checkpoint.json")] = cp_data

    def download(self, tag, name, directory):
        path = directory / name
        path.write_bytes(self.data[(tag, name)])
        return path


class PublishedCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "probe"

    def test_manifest_chain_and_split_release(self):
        cp = remote.published_checkpoint(FakeDownloads(), self.directory)
        self.assertEqual(100, cp["source_bytes"])

    def test_legacy_generation_requires_migration_build(self):
        self.assertIsNone(remote.published_checkpoint(FakeDownloads(False), self.directory))

    def test_changed_manifest_or_checkpoint_is_rejected(self):
        for key in (("map-data-test", "manifest.json"), ("map-data-test-extra", "source-checkpoint.json")):
            with self.subTest(key=key):
                gh = FakeDownloads()
                gh.data[key] += b" "
                with self.assertRaises(ValueError):
                    remote.published_checkpoint(gh, self.directory / key[1])

    def test_unsafe_release_tag_is_rejected(self):
        gh = FakeDownloads()
        pointer = json.loads(gh.data[("map-data-uk", "latest.json")])
        pointer["tag"] = "../not-a-release"
        gh.data[("map-data-uk", "latest.json")] = json.dumps(pointer).encode()
        with self.assertRaises(ValueError):
            remote.published_checkpoint(gh, self.directory)

    def test_failed_or_missing_graph_remains_retryable(self):
        class GraphDownloads:
            def __init__(self, sha):
                self.data = json.dumps({'source': {'sha256': sha}}).encode() if sha else None

            def inventory(self, tag):
                return {} if self.data is None else {'routing-uk.json': {
                    'name': 'routing-uk.json', 'size': len(self.data),
                    'digest': 'sha256:' + hashlib.sha256(self.data).hexdigest()}}

            def download(self, tag, name, directory):
                path = directory / name
                path.write_bytes(self.data)
                return path

        for sha, expected in ((None, False), ('b' * 64, False), ('c' * 64, True)):
            with self.subTest(sha=sha):
                checkpoint = {'source_sha256': 'c' * 64}
                self.assertEqual(expected, remote.graph_matches_map(
                    GraphDownloads(sha), checkpoint, self.directory / str(sha)))


if __name__ == "__main__":
    unittest.main()
