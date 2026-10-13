"""Bounded immutable shards and independently verified unchanged-asset reuse."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_publish_map_data as fixtures

publisher = fixtures.publisher


class PublicationShardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = {}
        for index in range(11):
            name = f'asset-{index:02}.json'
            path = self.root / name
            path.write_text(json.dumps({'fixture': index}))
            self.files[name] = path
        self.github = fixtures.FakeGitHub()
        self.local = patch.object(publisher, 'local_files', return_value=self.files)
        self.capacity = patch.object(publisher, 'ASSET_LIMIT', 3)
        self.main = patch.object(publisher, 'MAIN_FILES', 2)
        for mock in (self.local, self.capacity, self.main):
            mock.start()
            self.addCleanup(mock.stop)
        self.addCleanup(self.temp.cleanup)

    def test_more_than_two_shards_manifest_pins_actual_tags_and_publishes_last(self):
        publisher.publish(self.github, self.root, 'map-data-many')
        tags = ['map-data-many', 'map-data-many-extra', 'map-data-many-part2', 'map-data-many-part3']
        self.assertEqual(set(tags) | {publisher.LEGACY}, set(self.github.files))
        self.assertTrue(all(len(self.github.files[tag]) <= 3 for tag in tags))
        manifest = json.loads(self.github.files[tags[0]]['manifest.json'])
        self.assertEqual(set(self.files), set(manifest['files']))
        for name, record in manifest['files'].items():
            self.assertEqual(self.files[name].read_bytes(), self.github.files[record['tag']][name])
        uploads = [action for action in self.github.actions if action[0] == 'upload']
        self.assertEqual('manifest.json', uploads[-2][2])
        self.assertEqual('latest.json', uploads[-1][2])

    def test_later_shard_failure_keeps_pointer_and_resume_is_deterministic(self):
        self.github.files[publisher.LEGACY]['latest.json'] = b'{"old":"pointer"}'
        self.github.fail_upload = ('map-data-retry-part2', 'asset-05.json')
        with self.assertRaises(publisher.GitHubError):
            publisher.publish(self.github, self.root, 'map-data-retry')
        self.assertEqual(b'{"old":"pointer"}', self.github.files[publisher.LEGACY]['latest.json'])
        before = {tag: dict(files) for tag, files in self.github.files.items()}
        self.github.fail_upload = None
        publisher.publish(self.github, self.root, 'map-data-retry')
        for tag, assets in before.items():
            if tag != publisher.LEGACY:
                for name, data in assets.items():
                    self.assertEqual(data, self.github.files[tag][name])
        uploads = [a for a in self.github.actions if a[0] == 'upload' and a[1] != publisher.LEGACY]
        # Successful existing assets were not overwritten on resume.
        self.assertEqual(1, sum(a[1:3] == ('map-data-retry-extra', 'asset-02.json') for a in uploads))

    def test_tag_collision_fails_before_remote_changes(self):
        with self.assertRaisesRegex(ValueError, 'collision'):
            publisher.publish(self.github, self.root, 'map-data-collision', extra_tag='map-data-collision-part2')
        self.assertEqual([], self.github.actions)

    def test_reuse_uploads_only_changed_assets_and_manifest(self):
        publisher.publish(self.github, self.root, 'map-data-old')
        self.github.actions.clear()
        self.files['asset-05.json'].write_text('{"changed": true}')
        publisher.publish(self.github, self.root, 'map-data-new', reuse_unchanged=True)
        uploads = [a[2] for a in self.github.actions if a[0] == 'upload' and a[1] != publisher.LEGACY]
        self.assertEqual(['asset-05.json', 'manifest.json'], uploads)
        manifest = json.loads(self.github.files['map-data-new']['manifest.json'])
        self.assertEqual('map-data-new', manifest['files']['asset-05.json']['tag'])
        self.assertEqual('map-data-old', manifest['files']['asset-00.json']['tag'])

    def test_corrupt_previous_metadata_cannot_be_reused(self):
        publisher.publish(self.github, self.root, 'map-data-old')
        pointer = self.github.files[publisher.LEGACY]['latest.json']
        self.github.corrupt = ('map-data-old-extra', 'asset-02.json')
        with self.assertRaisesRegex(ValueError, 'verification'):
            publisher.publish(self.github, self.root, 'map-data-new', reuse_unchanged=True)
        self.assertEqual(pointer, self.github.files[publisher.LEGACY]['latest.json'])
        self.assertNotIn('map-data-new', self.github.files)

    def test_pointer_pinned_manifest_hash_is_required(self):
        publisher.publish(self.github, self.root, 'map-data-old')
        pointer = json.loads(self.github.files[publisher.LEGACY]['latest.json'])
        pointer['manifest_sha256'] = '0' * 64
        self.github.files[publisher.LEGACY]['latest.json'] = json.dumps(pointer).encode()
        with self.assertRaisesRegex(ValueError, 'published pointer'):
            publisher.publish(self.github, self.root, 'map-data-new', reuse_unchanged=True)
        self.assertNotIn('map-data-new', self.github.files)

    def test_large_inventory_uses_bounded_groups(self):
        with patch.object(publisher, 'ASSET_LIMIT', 1000), patch.object(publisher, 'MAIN_FILES', 900):
            groups = publisher.release_groups({f'asset-{i}': Path('fixture') for i in range(2101)}, 'map-data-large', 'map-data-large-extra')
        self.assertEqual([900, 1000, 201], [len(files) for _, files in groups])
        self.assertEqual('map-data-large-part2', groups[-1][0])

    def test_same_generation_resume_with_reuse_keeps_original_grouping(self):
        publisher.publish(self.github, self.root, 'map-data-old')
        self.github.actions.clear()
        publisher.publish(self.github, self.root, 'map-data-old', reuse_unchanged=True)
        self.assertEqual([], [a for a in self.github.actions if a[0] == 'upload' and a[1] != publisher.LEGACY])

    def test_country_archive_remains_at_new_main_tag_for_existing_app(self):
        path = self.root / 'drivemate.pmtiles'
        path.write_bytes(b'fixture')
        self.files[path.name] = path
        publisher.publish(self.github, self.root, 'map-data-old')
        publisher.publish(self.github, self.root, 'map-data-new', reuse_unchanged=True)
        manifest = json.loads(self.github.files['map-data-new']['manifest.json'])
        self.assertEqual('map-data-new', manifest['files']['drivemate.pmtiles']['tag'])
        self.assertIn('drivemate.pmtiles', self.github.files['map-data-new'])


if __name__ == '__main__':
    unittest.main()
