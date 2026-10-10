import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_routing_data as routing
from test_publish_map_data import FakeGitHub


class RoutingPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        payload = b'graph-fixture' * 100
        packed = gzip.compress(payload)
        self.name = 'valhalla-uk-test.tar.gz.part00'
        (self.out / self.name).write_bytes(packed)
        self.document = {'engine': 'valhalla-3.6.3', 'sha256': hashlib.sha256(payload).hexdigest(),
                         'bytes': len(payload), 'download_bytes': len(packed), 'built': '2026-10-09T00:00:00Z',
                         'parts': [self.name], 'source': {'licence': 'ODbL-1.0', 'sha256': 'a' * 64,
                         'url': 'https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf',
                         'retrieved_at': '2026-10-09T00:00:00Z'}}
        self.github = FakeGitHub()
        self.github.files[routing.LEGACY] = {}

    def publish(self):
        (self.out / routing.POINTER).write_text(json.dumps(self.document))
        routing.publish(self.github, self.out, 'routing-uk-test')

    def test_verified_publication_and_idempotent_generation(self):
        self.publish()
        self.publish()
        pointer = json.loads(self.github.files[routing.LEGACY][routing.POINTER])
        self.assertEqual(pointer['generation'], 'routing-uk-test')
        self.assertEqual(pointer['part_metadata'][self.name]['sha256'],
                         hashlib.sha256((self.out / self.name).read_bytes()).hexdigest())

    def test_corrupt_gzip_rejected_before_remote_write(self):
        (self.out / self.name).write_bytes(b'x' * self.document['download_bytes'])
        with self.assertRaises(OSError):
            self.publish()
        self.assertEqual(self.github.actions, [])

    def test_wrong_final_hash_rejected_before_remote_write(self):
        self.document['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.github.actions, [])

    def test_missing_piece_rejected_before_remote_write(self):
        (self.out / self.name).unlink()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.github.actions, [])

    def test_remote_digest_mismatch_never_promotes(self):
        self.github.corrupt = ('routing-uk-test', self.name)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertNotIn(routing.POINTER, self.github.files[routing.LEGACY])

    def test_promotion_failure_after_delete_restores_previous_pointer(self):
        old = json.dumps(self.document).encode()
        self.github.files[routing.LEGACY] = {routing.POINTER: old,
                                           self.name: (self.out / self.name).read_bytes()}
        original = self.github.upload
        failed = False
        def upload(tag, path, mutable=False):
            nonlocal failed
            if tag == routing.LEGACY and Path(path).name == routing.POINTER and not failed:
                failed = True
                del self.github.files[tag][routing.POINTER]
                raise routing.GitHubError('Synthetic failure after pointer deletion')
            return original(tag, path, mutable)
        self.github.upload = upload
        with self.assertRaises(routing.GitHubError):
            self.publish()
        self.assertEqual(self.github.files[routing.LEGACY][routing.POINTER], old)

    def test_bad_source_and_duplicate_parts_rejected(self):
        for field, value in [('source', {}), ('parts', [self.name, self.name])]:
            original = self.document[field]
            self.document[field] = value
            with self.assertRaises(ValueError):
                self.publish()
            self.document[field] = original
        self.assertEqual(self.github.actions, [])


if __name__ == '__main__':
    unittest.main()
