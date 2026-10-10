import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PlacesGenerationTests(unittest.TestCase):
    def test_real_release_outlier_tiles_never_enter_new_uk_packages(self):
        # Tile centres corresponding to the six failures in the 2026-10-10
        # published-data audit. These are public synthetic regression inputs.
        points = [(43.375, -3.875), (48.625, -2.125), (51.375, 3.125),
                  (51.875, 4.125), (52.375, 4.625), (56.625, -9.875),
                  (53.4808, -2.2426), (54.5973, -5.9301),
                  (55.8642, -4.2518), (51.4816, -3.1791)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'pois.geojsonseq'
            source.write_text('\n'.join(json.dumps({
                'type': 'Feature', 'properties': {'name': 'Place ' + str(i),
                    'addr:housenumber': '12', 'addr:street': 'Example Road'},
                'geometry': {'type': 'Point', 'coordinates': [lon, lat]}})
                for i, (lat, lon) in enumerate(points)) + '\n')
            generator = Path(__file__).resolve().parents[1] / 'scripts/places.py'
            result = subprocess.run([sys.executable, str(generator), str(root / 'out'),
                                     '--osm', str(source)], capture_output=True, text=True, check=True)
            stats = json.loads(result.stdout)
            self.assertEqual(stats['rejected_coordinate_records'], {'osm': 6})
            self.assertEqual(stats['merged'], 4)
            records = []
            for path in (root / 'out').glob('*.json.gz'):
                with gzip.open(path, 'rt') as stream:
                    records.extend(json.load(stream))
            self.assertEqual(len(records), 4)
            self.assertTrue(all(row[2] == '12 Example Road' for row in records))

    def test_nonfinite_coordinates_are_counted_before_tile_indexing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'pois.geojsonseq'
            source.write_text(json.dumps({'properties': {'name': 'Invalid'},
                'geometry': {'type': 'Point', 'coordinates': [float('nan'), 53]}}) + '\n')
            generator = Path(__file__).resolve().parents[1] / 'scripts/places.py'
            result = subprocess.run([sys.executable, str(generator), str(root / 'out'),
                                     '--osm', str(source)], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['rejected_coordinate_records'], {'osm': 1})
            self.assertEqual(list((root / 'out').glob('*.json.gz')), [])


def _run(root, *extra):
    generator = Path(__file__).resolve().parents[1] / 'scripts/places.py'
    result = subprocess.run([sys.executable, str(generator), str(root / 'out'), *extra],
                            capture_output=True, text=True, check=True)
    records = []
    for path in (root / 'out').glob('places-*.json.gz'):
        with gzip.open(path, 'rt') as stream:
            records.extend(json.load(stream))
    return json.loads(result.stdout), records, json.loads((root / 'out/places-provenance.json').read_text())


def _feature(coords, kind='Point', **tags):
    return json.dumps({'type': 'Feature', 'properties': tags,
                       'geometry': {'type': kind, 'coordinates': coords}})


class OsmAddressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, *lines):
        path = self.root / name
        path.write_text('\n'.join(lines) + '\n')
        return str(path)

    def test_addresses_become_five_field_records(self):
        square = [[-2.1942, 53.3954], [-2.1940, 53.3954], [-2.1940, 53.3956], [-2.1942, 53.3956], [-2.1942, 53.3954]]
        addr = self.write('a.geojsonseq',
            _feature([-2.194193, 53.395466], **{'addr:housenumber': '12', 'addr:street': 'Menai Grove',
                                                'addr:city': 'Cheadle', 'addr:postcode': 'SK8 2EZ'}),
            _feature([square], 'Polygon', **{'addr:housenumber': '14', 'addr:street': 'Menai Grove'}),
            _feature([-2.19, 53.39], **{'addr:housenumber': '5'}),
            _feature([-2.19, 53.39], **{'addr:street': 'Menai Grove'}))
        stats, records, prov = _run(self.root, '--osm-addresses', addr)
        self.assertEqual(len(records), 2)
        self.assertIn(['12 Menai Grove', 'address', 'Cheadle, SK8 2EZ', 53.395466, -2.194193], records)
        poly = [r for r in records if r[0] == '14 Menai Grove'][0]
        self.assertEqual(poly[1:3], ['address', ''])
        self.assertAlmostEqual(poly[3], 53.39548, places=4)
        self.assertTrue(all(len(r) == 5 for r in records))
        self.assertEqual(prov['records_by_primary_source']['osm_addresses'], 2)
        self.assertEqual(prov['input_records_before_merge']['osm_addresses'], 2)
        self.assertEqual(prov['total_records'], sum(prov['records_by_primary_source'].values()))

    def test_duplicates_within_30m_merge_but_other_streets_and_far_copies_stay(self):
        tags = {'addr:housenumber': '12', 'addr:street': 'Menai Grove'}
        addr = self.write('a.geojsonseq',
            _feature([-2.1942, 53.3954], **tags),
            _feature([-2.19421, 53.39541], **dict(tags, **{'addr:postcode': 'SK8 2EZ'})),
            _feature([-2.1942, 53.3954], **{'addr:housenumber': '12', 'addr:street': 'Other Road'}),
            _feature([-2.1842, 53.3954], **tags))
        stats, records, prov = _run(self.root, '--osm-addresses', addr)
        self.assertEqual(len(records), 3)
        self.assertIn(['12 Menai Grove', 'address', 'SK8 2EZ', 53.39541, -2.19421], records)
        self.assertEqual(prov['input_records_before_merge']['osm_addresses'], 4)
        self.assertEqual(prov['records_by_primary_source']['osm_addresses'], 3)

    def test_pois_unaffected_and_not_merged_with_addresses(self):
        poi = self.write('p.geojsonseq', _feature([-2.1942, 53.3954], name='12 Menai Grove', amenity='cafe'))
        addr = self.write('a.geojsonseq', _feature([-2.1942, 53.3954],
                          **{'addr:housenumber': '12', 'addr:street': 'Menai Grove'}))
        _, base, base_prov = _run(self.root, '--osm', poi)
        stats, records, prov = _run(self.root, '--osm', poi, '--osm-addresses', addr)
        self.assertEqual([r for r in records if r[1] != 'address'], base)
        self.assertEqual(len(records), 2)
        self.assertEqual(prov['records_by_primary_source']['osm'], base_prov['records_by_primary_source']['osm'])
        self.assertEqual(prov['records_by_primary_source']['osm_addresses'], 1)
        self.assertEqual(prov['total_records'], 2)

    def test_out_of_envelope_addresses_are_rejected_and_counted(self):
        addr = self.write('a.geojsonseq', _feature([4.0, 48.0], **{'addr:housenumber': '1', 'addr:street': 'Rue'}))
        stats, records, prov = _run(self.root, '--osm-addresses', addr)
        self.assertEqual(records, [])
        self.assertEqual(prov['rejected_coordinate_records']['osm_addresses'], 1)
