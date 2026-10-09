import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).resolve().parents[1] / 'scripts/publish_map_data.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class FakeGitHub:
    def __init__(self):
        self.files = {publisher.LEGACY: {}}
        self.actions = []
        self.corrupt = None
        self.fail_upload = None
        self.downloads = {}
        self.asset_ids = {}

    def ensure_release(self, tag):
        self.files.setdefault(tag, {})
        self.actions.append(('ensure', tag))

    def inventory(self, tag):
        assets = {}
        for name, data in self.files[tag].items():
            asset_id = self.asset_ids.setdefault((tag, name), len(self.asset_ids) + 1)
            digest = hashlib.sha256(data).hexdigest()
            if (tag, name) == self.corrupt:
                digest = '0' * 64
            assets[name] = {'id': asset_id, 'name': name, 'size': len(data), 'digest': 'sha256:' + digest}
        return copy.deepcopy(assets)

    def upload(self, tag, path, mutable=False):
        name = Path(path).name
        self.actions.append(('upload', tag, name, mutable))
        if (tag, name) == self.fail_upload:
            raise publisher.GitHubError('Synthetic upload failure')
        if name in self.files[tag] and not mutable:
            raise AssertionError('Immutable asset overwrite attempted')
        self.files[tag][name] = Path(path).read_bytes()

    def download(self, tag, name, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(self.downloads.get((tag, name), self.files[tag][name]))
        self.actions.append(('download', tag, name))
        return path

    def delete(self, asset):
        self.actions.append(('delete', publisher.LEGACY, asset['name']))
        del self.files[publisher.LEGACY][asset['name']]


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / 'out'
        self.out.mkdir()
        self.min_size = patch.object(publisher, 'MIN_MAP_BYTES', 20)
        self.min_size.start()
        self.addCleanup(self.min_size.stop)
        (self.out / 'drivemate.pmtiles').write_bytes(b'PMTiles' + b'x' * 30)
        (self.out / 'build-info.txt').write_text('Synthetic test data\n')
        (self.out / 'cameras-uk.json').write_text('{"elements": []}')
        (self.out / 'lanes-106_-5.json').write_text('{"ways": []}')
        with gzip.open(self.out / 'places-212_-9.json.gz', 'wt') as stream:
            json.dump([['Synthetic place', '', '', 53.0, -2.0]], stream)
        self.github = FakeGitHub()

    def legacy(self, count=3, pointer=False):
        data = {'drivemate.pmtiles': b'PMTiles' + b'x' * 30, 'build-info.txt': b'Synthetic legacy build\n',
                'lanes-106_-5.json': b'{"ways": []}'}
        if pointer:
            data['latest.json'] = b'{"tag": "map-data-old"}'
        for i in range(count - len(data)):
            data[f'places-{i}_0.json.gz'] = b'synthetic inventory bytes'
        self.github.files[publisher.LEGACY] = data

    def test_standard_publish_verifies_every_asset_then_switches_pointer(self):
        publisher.publish(self.github, self.out, 'map-data-test')
        main = self.github.files['map-data-test']
        manifest = json.loads(main['manifest.json'])
        self.assertEqual(1, manifest['schema'])
        for name, meta in manifest['files'].items():
            self.assertEqual({'sha256': hashlib.sha256(main[name]).hexdigest(), 'bytes': len(main[name]),
                              'tag': 'map-data-test'}, meta)
        pointer = json.loads(self.github.files[publisher.LEGACY]['latest.json'])
        self.assertEqual(hashlib.sha256(main['manifest.json']).hexdigest(), pointer['manifest_sha256'])
        self.assertEqual(('upload', publisher.LEGACY, 'latest.json', False), self.github.actions[-1])
        # Exactly matching immutable assets support safe restart without clobbering data.
        self.github.actions.clear()
        publisher.publish(self.github, self.out, 'map-data-test')
        self.assertEqual([('upload', publisher.LEGACY, 'latest.json', True)],
                         [action for action in self.github.actions if action[0] == 'upload'])

    def test_split_release_manifest_names_the_release_for_every_file(self):
        with patch.object(publisher, 'MAIN_FILES', 3):
            publisher.publish(self.github, self.out, 'map-data-split')
        main = self.github.files['map-data-split']
        extra = self.github.files['map-data-split-extra']
        self.assertEqual(3 + 1, len(main))
        self.assertEqual(2, len(extra))
        self.assertIn('drivemate.pmtiles', main)
        self.assertIn('build-info.txt', main)
        manifest = json.loads(main['manifest.json'])
        self.assertEqual(set(main) - {'manifest.json'} | set(extra), set(manifest['files']))
        for name, meta in manifest['files'].items():
            self.assertIn(name, self.github.files[meta['tag']])
        self.assertEqual('map-data-split-extra', json.loads(self.github.files[publisher.LEGACY]['latest.json'])['extra_tag'])

    def test_corrupt_upload_or_incomplete_extra_never_updates_pointer(self):
        self.github.corrupt = ('map-data-test', 'cameras-uk.json')
        with self.assertRaises(ValueError):
            publisher.publish(self.github, self.out, 'map-data-test')
        self.assertNotIn('latest.json', self.github.files[publisher.LEGACY])
        self.github = FakeGitHub()
        self.github.fail_upload = ('map-data-test-extra', 'places-212_-9.json.gz')
        with patch.object(publisher, 'MAIN_FILES', 3), self.assertRaises(publisher.GitHubError):
            publisher.publish(self.github, self.out, 'map-data-test')
        self.assertNotIn('latest.json', self.github.files[publisher.LEGACY])

    def test_existing_immutable_mismatch_and_unexpected_asset_block(self):
        for files in ({'drivemate.pmtiles': b'wrong'}, {'unrelated.txt': b'wrong'}):
            self.github = FakeGitHub()
            self.github.files['map-data-test'] = files
            with self.assertRaises(ValueError):
                publisher.publish(self.github, self.out, 'map-data-test')
            self.assertNotIn('latest.json', self.github.files[publisher.LEGACY])

    def test_bootstrap_archives_metadata_before_freeing_one_slot_and_promoting(self):
        self.legacy(1000)
        old_info = self.github.files[publisher.LEGACY]['build-info.txt']
        old_data = {k: v for k, v in self.github.files[publisher.LEGACY].items() if k != 'build-info.txt'}
        publisher.bootstrap(self.github, 'map-data-bootstrap')
        self.assertEqual(old_info, self.github.files['map-data-bootstrap']['build-info.txt'])
        self.assertEqual(old_data, {k: v for k, v in self.github.files[publisher.LEGACY].items() if k != 'latest.json'})
        manifest = json.loads(self.github.files['map-data-bootstrap']['manifest.json'])
        self.assertTrue(manifest['inventory_snapshot'])
        self.assertIn('partial', manifest['coverage'])
        self.assertEqual(set(old_data), set(manifest['files']))
        actions = self.github.actions
        archive_at = actions.index(('upload', 'map-data-bootstrap', 'build-info.txt', False))
        delete_at = actions.index(('delete', publisher.LEGACY, 'build-info.txt'))
        self.assertLess(archive_at, delete_at)
        self.assertEqual(('upload', publisher.LEGACY, 'latest.json', False), actions[-1])
        # The pointer is now present and the build info exists only in its verified archive.
        self.github.actions.clear()
        publisher.bootstrap(self.github, 'map-data-bootstrap')
        self.assertEqual(old_info, self.github.files['map-data-bootstrap']['build-info.txt'])
        self.assertFalse(any(action[0] == 'delete' for action in self.github.actions))

    def test_bootstrap_ignores_download_counts_but_rejects_data_identity_changes(self):
        self.legacy(1000)
        inventory = self.github.inventory
        calls = [0]
        def changing_counts(tag):
            calls[0] += 1
            assets = inventory(tag)
            for asset in assets.values():
                asset['download_count'] = calls[0]
                asset['updated_at'] = str(calls[0])
            return assets
        self.github.inventory = changing_counts
        publisher.bootstrap(self.github, 'map-data-bootstrap')
        self.assertIn('latest.json', self.github.files[publisher.LEGACY])

        self.github = FakeGitHub()
        self.legacy(1000)
        upload = self.github.upload
        def mutate_legacy(tag, path, mutable=False):
            upload(tag, path, mutable)
            if tag == 'map-data-bootstrap' and Path(path).name == 'build-info.txt':
                self.github.files[publisher.LEGACY]['lanes-106_-5.json'] = b'changed during bootstrap'
        self.github.upload = mutate_legacy
        with self.assertRaises(ValueError):
            publisher.bootstrap(self.github, 'map-data-bootstrap')
        self.assertIn('build-info.txt', self.github.files[publisher.LEGACY])
        self.assertNotIn('latest.json', self.github.files[publisher.LEGACY])

    def test_bootstrap_does_not_delete_when_pointer_present_or_slot_available(self):
        for has_pointer in (False, True):
            self.github = FakeGitHub()
            self.legacy(1000 if has_pointer else 3, pointer=has_pointer)
            publisher.bootstrap(self.github, 'map-data-bootstrap')
            self.assertIn('build-info.txt', self.github.files[publisher.LEGACY])
            self.assertFalse(any(action[0] == 'delete' for action in self.github.actions))

    def test_bootstrap_requires_verified_archive_and_all_asset_digests(self):
        for mode in ('download', 'archive', 'inventory'):
            self.github = FakeGitHub()
            self.legacy(1000)
            if mode == 'download':
                self.github.downloads[(publisher.LEGACY, 'build-info.txt')] = b'corrupt download'
            elif mode == 'archive':
                self.github.corrupt = ('map-data-bootstrap', 'build-info.txt')
            else:
                inventory = self.github.inventory
                def no_digest(tag):
                    result = inventory(tag)
                    result['drivemate.pmtiles'].pop('digest')
                    return result
                self.github.inventory = no_digest
            with self.assertRaises(ValueError):
                publisher.bootstrap(self.github, 'map-data-bootstrap')
            self.assertIn('build-info.txt', self.github.files[publisher.LEGACY])
            self.assertNotIn('latest.json', self.github.files[publisher.LEGACY])

    def test_malformed_local_output_symlinks_names_and_duplicate_basenames_fail(self):
        (self.out / 'unexpected.json').write_text('{}')
        with self.assertRaises(ValueError):
            publisher.local_files(self.out)
        (self.out / 'unexpected.json').unlink()
        (self.out / 'copy').mkdir()
        (self.out / 'copy' / 'lanes-106_-5.json').write_text('{"ways": []}')
        with self.assertRaises(ValueError):
            publisher.local_files(self.out)
        (self.out / 'copy' / 'lanes-106_-5.json').unlink()
        (self.out / 'copy' / 'linked.json').symlink_to(self.out / 'cameras-uk.json')
        with self.assertRaises(ValueError):
            publisher.local_files(self.out)
        for value in ('../escape', '--evil', 'bad/name'):
            with self.assertRaises(ValueError):
                publisher.checked_name(value)
            with self.assertRaises(ValueError):
                publisher.checked_tag(value)
        with self.assertRaises(ValueError):
            publisher.GitHub('owner/repo/other')

    def test_bad_magic_size_and_data_shapes_fail_before_upload(self):
        map_path = self.out / 'drivemate.pmtiles'
        map_path.write_bytes(b'not-map' + b'x' * 30)
        with self.assertRaises(ValueError):
            publisher.publish(self.github, self.out, 'map-data-test')
        map_path.write_bytes(b'PMTiles')
        with self.assertRaises(ValueError):
            publisher.publish(self.github, self.out, 'map-data-test')
        map_path.write_bytes(b'PMTiles' + b'x' * 30)
        (self.out / 'cameras-uk.json').write_text('{"elements": {}}')
        with self.assertRaises(ValueError):
            publisher.publish(self.github, self.out, 'map-data-test')
        self.assertEqual([], self.github.actions)

    def test_gh_uses_argv_and_prohibits_data_clobber(self):
        github = publisher.GitHub('owner/repo')
        with patch.object(publisher.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            github.upload('map-data-test', self.out / 'drivemate.pmtiles')
            args, kwargs = run.call_args
            self.assertIsInstance(args[0], list)
            self.assertNotIn('shell', kwargs)
            self.assertNotIn('--clobber', args[0])
            with self.assertRaises(ValueError):
                github.upload('map-data-test', self.out / 'drivemate.pmtiles', mutable=True)


if __name__ == '__main__':
    unittest.main()
