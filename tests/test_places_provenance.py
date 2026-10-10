"""Places provenance sidecar: written beside unchanged five-field tiles and checked by the publisher."""
import gzip
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / 'scripts/places.py'

spec = importlib.util.spec_from_file_location('places_provenance', ROOT / 'scripts/places_provenance.py')
provenance_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance_module)

# Test double for pyarrow.parquet that reads a JSON fixture, so the Overture path
# (including the `sources` column) runs without pyarrow installed.
FAKE_PARQUET = '''import json


class _Schema:
    def __init__(self, names):
        self.names = names


class _Batch:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return self._rows


class ParquetFile:
    def __init__(self, path):
        with open(path, encoding="utf-8") as stream:
            document = json.load(stream)
        self.schema_arrow = _Schema(document["columns"])
        self._rows = document["rows"]

    def iter_batches(self, columns, batch_size):
        rows = []
        for row in self._rows:
            item = {c: row.get(c) for c in columns}
            if item.get("geometry") is not None:
                item["geometry"] = bytes.fromhex(item["geometry"])
            rows.append(item)
        yield _Batch(rows)
'''

# Decompressed tile payloads produced for this fixture by places.py BEFORE the
# sidecar was added (commit 6f5a7fc). The tile bytes must not change.
GOLDEN = {
    'places-205_-13.json.gz': '[["Cardiff Library","amenity library","2 Hayes",51.4825,-3.175]]',
    'places-209_-8.json.gz': '[["Tesco","shop supermarket","",52.4862,-1.8904]]',
    'places-213_-9.json.gz': '[["Costa Coffee","coffee shop","1 Market Street, Manchester, M1 1AA",53.4808,-2.2426]]',
    'places-218_-24.json.gz': '[["Corner Shop","convenience store","",54.5973,-5.9301]]',
    'places-223_-18.json.gz': '[["Glasgow Bakery","bakery","5 High Street, Glasgow",55.8642,-4.2518]]',
}


def point(lon, lat):
    return (struct.pack('<BI', 1, 1) + struct.pack('<dd', lon, lat)).hex()


def overture_rows():
    return [
        {'names': {'primary': 'Costa Coffee'}, 'categories': {'primary': 'coffee_shop'},
         'addresses': [{'freeform': '1 Market Street', 'locality': 'Manchester', 'postcode': 'M1 1AA'}],
         'confidence': 0.9, 'geometry': point(-2.2426, 53.4808), 'brand': {'names': {'primary': 'Costa'}},
         'sources': [{'dataset': 'meta', 'property': ''},
                     {'dataset': 'Foursquare', 'property': '/properties/addresses'}]},
        {'names': {'primary': 'Corner Shop'}, 'categories': {'primary': 'convenience_store'},
         'addresses': [], 'confidence': 0.8, 'geometry': point(-5.9301, 54.5973), 'brand': None,
         'sources': [{'dataset': 'AllThePlaces', 'property': ''}]},
        {'names': {'primary': 'Low Confidence Cafe'}, 'categories': {'primary': 'cafe'},
         'addresses': [], 'confidence': 0.2, 'geometry': point(-3.1791, 51.4816), 'brand': None,
         'sources': [{'dataset': 'meta', 'property': ''}]},
        {'names': {'primary': 'Glasgow Bakery'}, 'categories': {'primary': 'bakery'},
         'addresses': [{'freeform': '5 High Street', 'locality': 'Glasgow', 'postcode': None}],
         'confidence': 0.7, 'geometry': point(-4.2518, 55.8642), 'brand': None, 'sources': []},
        {'names': {'primary': 'Overseas Shop'}, 'categories': {'primary': 'shop'},
         'addresses': [], 'confidence': 0.9, 'geometry': point(4.625, 52.375), 'brand': None,
         'sources': [{'dataset': 'meta', 'property': ''}]},
    ]


def osm_features():
    return [
        # Same place as the Overture coffee shop with a shorter address: removed as a duplicate.
        {'type': 'Feature', 'properties': {'name': 'Costa Coffee', 'amenity': 'cafe', 'addr:city': 'Manchester'},
         'geometry': {'type': 'Point', 'coordinates': [-2.2427, 53.4808]}},
        {'type': 'Feature', 'properties': {'name': 'Cardiff Library', 'amenity': 'library',
                                           'addr:housenumber': '2', 'addr:street': 'Hayes'},
         'geometry': {'type': 'Polygon', 'coordinates': [[[-3.18, 51.48], [-3.17, 51.48],
                                                         [-3.17, 51.49], [-3.18, 51.48]]]}},
        {'type': 'Feature', 'properties': {'brand': 'Tesco', 'shop': 'supermarket'},
         'geometry': {'type': 'Point', 'coordinates': [-1.8904, 52.4862]}},
    ]


def write_inputs(root, columns=None):
    root = Path(root)
    package = root / 'fakearrow' / 'pyarrow'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'parquet.py').write_text(FAKE_PARQUET)
    columns = columns or ['id', 'names', 'categories', 'addresses', 'confidence', 'geometry', 'brand', 'sources']
    rows = [{k: v for k, v in row.items() if k in columns} for row in overture_rows()]
    (root / 'places.parquet').write_text(json.dumps({'columns': columns, 'rows': rows}))
    (root / 'pois.geojsonseq').write_text(''.join(json.dumps(f) + '\n' for f in osm_features()))
    return root / 'fakearrow'


def run_generator(root, *extra, generator=GENERATOR, columns=None, check=True):
    root = Path(root)
    fake = write_inputs(root, columns)
    env = dict(os.environ, PYTHONPATH=str(fake))
    env.pop('GITHUB_STEP_SUMMARY', None)
    return subprocess.run([sys.executable, str(generator), str(root / 'out'),
                           '--overture', str(root / 'places.parquet'),
                           '--osm', str(root / 'pois.geojsonseq'), *extra],
                          env=env, capture_output=True, text=True, check=check)


def tile_payloads(out):
    result = {}
    for path in sorted(Path(out).glob('places-*.json.gz')):
        with gzip.open(path, 'rb') as stream:
            result[path.name] = stream.read()
    return result


class PlacesProvenanceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_tiles_unchanged_and_sidecar_counts_add_up(self):
        result = run_generator(self.root, '--overture-release', '2026-09-17.0')
        out = self.root / 'out'
        self.assertEqual(GOLDEN, {name: data.decode('utf-8') for name, data in tile_payloads(out).items()})
        records = [row for data in tile_payloads(out).values() for row in json.loads(data)]
        self.assertTrue(all(len(row) == 5 for row in records))

        sidecar = provenance_module.read(out / 'places-provenance.json')
        self.assertEqual(len(records), sidecar['total_records'])
        self.assertEqual(len(records), sum(sidecar['records_by_primary_source'].values()))
        self.assertEqual({'overture': 3, 'osm': 2, 'osnames': 0}, sidecar['records_by_primary_source'])
        self.assertEqual({'overture': 3, 'osm': 3, 'osnames': 0}, sidecar['input_records_before_merge'])
        self.assertEqual({'overture': 1, 'osm': 0, 'osnames': 0}, sidecar['rejected_coordinate_records'])
        self.assertEqual(len(tile_payloads(out)), sidecar['tile_files'])
        self.assertEqual('2026-09-17.0', sidecar['overture']['release'])
        self.assertTrue(sidecar['overture']['input_present'])
        self.assertEqual({'AllThePlaces': 1, 'Foursquare': 1, 'meta': 1, '_no_sources_recorded': 1},
                         sidecar['overture']['upstream_datasets'])
        self.assertEqual('not_independently_verified', sidecar['rights_review_status'])
        self.assertEqual('ODbL-1.0', sidecar['sources']['osm']['licence'])
        self.assertEqual(['Ordnance Survey', 'Royal Mail', 'National Statistics'],
                         sidecar['sources']['osnames']['required_notices'])
        licences = {item['upstream']: item for item in sidecar['sources']['overture']['upstream_licences']}
        self.assertEqual('Apache-2.0', licences['Foursquare']['licence'])
        self.assertIn('NOTICE', licences['Foursquare']['requires'])
        self.assertEqual('CC0', licences['AllThePlaces']['licence'])
        self.assertEqual('2026-09-17.0', json.loads(result.stdout)['overture_release'])

    def test_missing_sources_column_and_release_are_not_guessed(self):
        columns = ['names', 'categories', 'addresses', 'confidence', 'geometry', 'brand']
        run_generator(self.root, columns=columns)
        sidecar = provenance_module.read(self.root / 'out' / 'places-provenance.json')
        self.assertEqual('unavailable', sidecar['overture']['upstream_datasets'])
        self.assertEqual('unknown', sidecar['overture']['release'])
        # The tile payload does not depend on the provenance-only column.
        self.assertEqual(GOLDEN, {k: v.decode('utf-8') for k, v in tile_payloads(self.root / 'out').items()})

    def test_malformed_release_identifier_is_refused(self):
        result = run_generator(self.root, '--overture-release', 'latest; rm -rf /', check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.root / 'out' / 'places-provenance.json').exists())

    def test_os_open_names_records_are_counted(self):
        names = self.root / 'osnames'
        (names / 'DOC').mkdir(parents=True)
        (names / 'DATA').mkdir()
        header = ['ID', 'NAMES_URI', 'NAME1', 'NAME1_LANG', 'NAME2', 'NAME2_LANG', 'TYPE', 'LOCAL_TYPE',
                  'GEOMETRY_X', 'GEOMETRY_Y', 'MOST_DETAIL_VIEW_RES', 'LEAST_DETAIL_VIEW_RES', 'MBR_XMIN',
                  'MBR_YMIN', 'MBR_XMAX', 'MBR_YMAX', 'POSTCODE_DISTRICT', 'POSTCODE_DISTRICT_URI',
                  'POPULATED_PLACE', 'POPULATED_PLACE_URI', 'POPULATED_PLACE_TYPE', 'DISTRICT_BOROUGH']
        (names / 'DOC' / 'OS_Open_Names_Header.csv').write_text(','.join(header) + '\n')

        def row(name, local_type, x, y):
            values = [''] * len(header)
            values[2], values[7], values[8], values[9] = name, local_type, str(x), str(y)
            values[16], values[18], values[21] = 'SW1A', 'London', 'Westminster'
            return ','.join(values) + '\n'
        (names / 'DATA' / 'TQ37.csv').write_text(
            row('Whitehall', 'Named Road', 530047, 180050) +
            row('Westminster', 'Suburban Area', 529900, 179400) +
            row('Ignored Hill', 'Hill Or Mountain', 529000, 179000))
        run_generator(self.root, '--osnames', str(names))
        out = self.root / 'out'
        records = [row for data in tile_payloads(out).values() for row in json.loads(data)]
        sidecar = provenance_module.read(out / 'places-provenance.json')
        self.assertEqual(2, sidecar['records_by_primary_source']['osnames'])
        self.assertEqual(len(records), sidecar['total_records'])


class PlacesProvenanceStructureTests(unittest.TestCase):
    def valid(self):
        return provenance_module.build({'overture': 2, 'osm': 1}, {'overture': 3, 'osm': 1},
                                       {}, 2, '2026-09-17.0', True, {'meta': 2})

    def test_valid_document_round_trips(self):
        document = json.loads(json.dumps(self.valid()))
        self.assertIs(document, provenance_module.validate(document))
        self.assertEqual(3, document['total_records'])

    def test_malformed_documents_are_rejected(self):
        mutations = [
            lambda d: d.update(schema=2),
            lambda d: d.update(rights_review_status='cleared'),
            lambda d: d.pop('sources'),
            lambda d: d['sources'].pop('osnames'),
            lambda d: d['records_by_primary_source'].update(osm=-1),
            lambda d: d['records_by_primary_source'].update(osm=1.0),
            lambda d: d['records_by_primary_source'].update(osm=True),
            lambda d: d.update(total_records=99),
            lambda d: d['input_records_before_merge'].pop('osm'),
            lambda d: d['overture'].update(release='latest'),
            lambda d: d['overture'].update(upstream_datasets={'meta': -1}),
            lambda d: d['overture'].update(upstream_datasets='guessed'),
            lambda d: d.update(tile_files=-1),
        ]
        for mutate in mutations:
            document = json.loads(json.dumps(self.valid()))
            mutate(document)
            with self.assertRaises(ValueError):
                provenance_module.validate(document)


if __name__ == '__main__':
    unittest.main()
