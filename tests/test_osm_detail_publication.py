import gzip
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import test_publish_map_data as fixtures
import daily_source_probe
import osm_feature_packs
import osm_relation_packs
from region_companions import annotate


class OSMDetailPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublisherTest('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare_navigation_sample()
        self.out = self.fixture.out
        self.publisher = fixtures.publisher
        self.source = self.out.parent / 'synthetic.osm.pbf'
        self.url = 'https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf'

    def complete(self):
        self.publisher.osm_snapshot.retain(self.source, self.out / 'source', self.url, 4)
        geo = self.out.parent / 'synthetic.geojsonseq'
        geo.write_text(json.dumps({'type': 'Feature', 'id': 'node/1',
            'properties': {'highway': 'traffic_signals', 'future:key': 'keep'},
            'geometry': {'type': 'Point', 'coordinates': [-2.2, 53.4]}}) + '\n')
        osm_feature_packs.build(geo, self.out / 'features')
        opl = self.out.parent / 'synthetic.opl'
        opl.write_text('r1 Ttype=connectivity,connectivity=1:1 Mw7@from,w8@to\n')
        osm_relation_packs.build_packs(opl, self.out / 'relations')
        import hashlib
        signal = hashlib.md5(self.source.read_bytes(), usedforsecurity=False).hexdigest() + '  united-kingdom-latest.osm.pbf\n'
        checkpoint = daily_source_probe.build_checkpoint(self.url, signal, signal, 'a' * 64, self.source)
        (self.out / 'source-checkpoint.json').write_text(json.dumps(checkpoint))
        self.bind_report()

    def bind_report(self):
        consistency = self.publisher._load('publication_consistency')
        (self.out / 'build-quality.json').write_text(json.dumps({
            'errors': [], 'asset_snapshot': consistency.snapshot_assets(self.out)}))

    def test_complete_app_readable_datasets_publish_together(self):
        self.complete()
        self.publisher.publish(self.fixture.github, self.out, 'map-data-osm-fixture', navigation_data=True)
        manifest = json.loads(self.fixture.github.files['map-data-osm-fixture']['manifest.json'])
        for name in ('source-checkpoint.json', 'feature-packs-manifest.json', 'relation-packs-manifest.json',
                     'feature-packs-106_-5.jsonl.gz', 'relation-packs-0.jsonl.gz'):
            self.assertIn(name, manifest['files'])

    def test_new_checkpoint_requires_every_dataset(self):
        self.complete()
        (self.out / 'relations/relation-packs-manifest.json').unlink()
        self.bind_report()
        with self.assertRaises(ValueError):
            self.publisher.publish(self.fixture.github, self.out, 'map-data-partial-osm', navigation_data=True)
        self.assertEqual([], self.fixture.github.actions)

    def test_corrupt_detail_bytes_cannot_move_pointer(self):
        self.complete()
        pack = self.out / 'features/feature-packs-106_-5.jsonl.gz'
        pack.write_bytes(b'corrupt')
        self.bind_report()
        with self.assertRaises(ValueError):
            self.publisher.publish(self.fixture.github, self.out, 'map-data-corrupt-osm', navigation_data=True)
        self.assertEqual([], self.fixture.github.actions)

    def test_checkpoint_from_another_download_cannot_publish(self):
        self.complete()
        path = self.out / 'source-checkpoint.json'
        checkpoint = json.loads(path.read_text())
        checkpoint['source_sha256'] = 'b' * 64
        path.write_text(json.dumps(checkpoint))
        self.bind_report()
        with self.assertRaisesRegex(ValueError, 'checkpoint differs'):
            self.publisher.publish(self.fixture.github, self.out, 'map-data-other-input', navigation_data=True)
        self.assertEqual([], self.fixture.github.actions)

    def test_optional_details_do_not_break_old_android_companion_contract(self):
        manifest = {'packages': {'base': {}, 'region-z8-x126-y82': {'bounds': [-2.5, 53.0, -2.0, 53.5]}}}
        available = {'feature-packs-manifest.json', 'relation-packs-manifest.json',
                     'feature-packs-106_-5.jsonl.gz', 'feature-packs-global.jsonl.gz'}
        result = annotate(manifest, available)
        info = result['packages']['region-z8-x126-y82']
        self.assertEqual({'lanes', 'limits', 'roadinfo', 'places'}, set(info['companions']))
        self.assertEqual(['feature-packs-106_-5.jsonl.gz', 'feature-packs-global.jsonl.gz'], info['osm_detail_files'])
        self.assertEqual([], result['national_files'])
        self.assertEqual(['feature-packs-manifest.json', 'relation-packs-manifest.json'], result['osm_detail_catalogs'])

    def test_android_manifest_limits_block_before_any_upload(self):
        self.complete()
        for limit in ('MAX_MANIFEST_ENTRIES', 'MAX_MANIFEST_BYTES'):
            with self.subTest(limit=limit), patch.object(self.publisher, limit, 1):
                with self.assertRaisesRegex(ValueError, 'Android'):
                    self.publisher.publish(self.fixture.github, self.out, 'map-data-too-big', navigation_data=True)
            self.assertEqual([], self.fixture.github.actions)


if __name__ == '__main__':
    unittest.main()
