import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from regional_addresses import build, record, search, validate


def feature(number='12', identity='node/1', **tags):
    return {'id': identity, 'properties': dict({'addr:housenumber': number, 'addr:street': 'Example Road',
                                              'addr:postcode': 'M1 1AA'}, **tags),
            'geometry': {'type': 'Point', 'coordinates': [-2.24, 53.48]}}


class RegionalAddressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'addresses.sqlite'

    def generate(self, features=None):
        return build(features or [feature()], self.path, {'licence': 'ODbL-1.0', 'sha256': 'a' * 64})

    def test_number_and_postcode_search_keep_full_precision_and_evidence(self):
        report = self.generate([feature(), feature('13', 'node/2')])
        self.assertEqual(2, report['counts']['records'])
        self.assertEqual('12', search(self.path, '12 Example')[0]['house_number'])
        self.assertEqual(2, len(search(self.path, 'M11AA')))
        item = search(self.path, '12')[0]
        self.assertEqual(53.48, item['lat'])
        self.assertFalse(item['full_postal_address_verified'])
        self.assertFalse(item['entrance_verified'])
        self.assertEqual('mapped_node', item['coordinate_kind'])
        self.assertEqual(2, validate(self.path)['records'])

    def test_street_without_number_uses_android_fts4(self):
        self.generate()
        self.assertEqual('12', search(self.path, 'Example Road')[0]['house_number'])
        with sqlite3.connect(self.path) as db:
            self.assertIn('fts4', db.execute("SELECT sql FROM sqlite_master WHERE name='address_words'").fetchone()[0])

    def test_fts_operators_are_plain_search_text(self):
        self.generate()
        self.assertEqual([], search(self.path, 'Example OR missing'))
        self.assertEqual('12', search(self.path, '"Example"')[0]['house_number'])
        with self.assertRaises(ValueError):
            search(self.path, 'a' * 257)

    def test_outline_is_never_a_verified_entrance(self):
        f = feature(identity='way/3', entrance='main')
        f['geometry'] = {'type': 'Polygon', 'coordinates': [[[-2.24, 53.48], [-2.23, 53.48],
            [-2.23, 53.49], [-2.24, 53.48]]]}
        item = record(f)
        self.assertEqual('outline_average', item['coordinate_kind'])
        self.assertEqual('main', item['entrance_tag'])
        self.assertFalse(item['entrance_verified'])

    def test_missing_fields_and_invalid_geometry_are_measurable_gaps(self):
        missing = feature(); del missing['properties']['addr:street']
        invalid = feature(identity='node/2'); invalid['geometry']['coordinates'] = [float('nan'), 53]
        report = self.generate([feature(), missing, invalid])
        self.assertEqual({'seen': 3, 'records': 1, 'missing_fields': 1, 'invalid_features': 1}, report['counts'])

    def test_failed_duplicate_build_does_not_replace_working_database(self):
        self.generate()
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.IntegrityError):
            self.generate([feature(), feature()])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.path.parent.glob('.addresses-*')))

    def test_no_addresses_does_not_replace_working_database(self):
        self.generate()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            build([], self.path, {})
        self.assertEqual(before, self.path.read_bytes())

    def test_tampered_records_and_missing_fts_rows_fail(self):
        self.generate()
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM address_words')
        with self.assertRaises(ValueError):
            validate(self.path)
        self.generate()
        with sqlite3.connect(self.path) as db:
            payload = json.loads(db.execute('SELECT record_json FROM addresses').fetchone()[0])
            payload['entrance_verified'] = True
            db.execute('UPDATE addresses SET record_json=?', (json.dumps(payload),))
        with self.assertRaises(ValueError):
            validate(self.path)

    def test_named_properties_and_units_preserved_without_invention(self):
        f = feature('', **{'addr:housename': 'Rose Cottage', 'addr:unit': '2', 'addr:city': 'Manchester'})
        self.generate([f])
        item = search(self.path, 'Rose')[0]
        self.assertEqual('Rose Cottage', item['house_name'])
        self.assertEqual('2', item['unit'])
        self.assertEqual('Manchester', item['locality'])
        self.assertNotIn('addr:country', item['address_fields'])

    def test_unknown_source_rights_are_rejected(self):
        with self.assertRaises(ValueError):
            build([feature()], self.path, {'licence': 'unknown', 'sha256': 'a' * 64})

    def test_corrupt_word_index_is_rejected(self):
        self.generate()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE address_words SET search_text='invented location'")
        with self.assertRaises(ValueError):
            validate(self.path)
