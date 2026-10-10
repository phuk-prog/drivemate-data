"""Northern Ireland (OSNI gazetteer) records in the offline search file."""
import csv
import gzip
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


search = load('search_offline')
index = load('search_index')
publisher = load('publish_map_data')

GB_HEADER = ['ID', 'NAMES_URI', 'NAME1', 'NAME1_LANG', 'NAME2', 'NAME2_LANG', 'TYPE', 'LOCAL_TYPE', 'GEOMETRY_X',
             'GEOMETRY_Y', 'MOST_DETAIL_VIEW_RES', 'LEAST_DETAIL_VIEW_RES', 'MBR_XMIN', 'MBR_YMIN', 'MBR_XMAX', 'MBR_YMAX',
             'POSTCODE_DISTRICT', 'POSTCODE_DISTRICT_URI', 'POPULATED_PLACE', 'POPULATED_PLACE_URI', 'POPULATED_PLACE_TYPE',
             'DISTRICT_BOROUGH', 'DISTRICT_BOROUGH_URI', 'DISTRICT_BOROUGH_TYPE', 'COUNTY_UNITARY', 'COUNTY_UNITARY_URI',
             'COUNTY_UNITARY_TYPE', 'REGION', 'REGION_URI', 'COUNTRY', 'COUNTRY_URI', 'RELATED_SPATIAL_OBJECT',
             'SAME_AS_DBPEDIA', 'SAME_AS_GEONAMES']
LPS = ('Contains LPS Intellectual Property © Crown copyright and database right ({}) This information is licensed '
       'under the terms of the Open Government Licence')


def metres(lat1, lon1, lat2, lon2):
    dy = (lat1 - lat2) * 111_320
    dx = (lon1 - lon2) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


class OsniSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        osnames = self.tmp / 'osnames'
        (osnames / 'Doc').mkdir(parents=True)
        (osnames / 'Data').mkdir()
        (osnames / 'Doc' / 'OS_Open_Names_Header.csv').write_text(','.join(GB_HEADER) + '\n', encoding='utf-8')
        rows = []
        for name, local, x, y, district, town in (('SK8 2EZ', 'Postcode', 384900, 387100, '', 'Cheadle'),
                                                  ('Menai Grove', 'Named Road', 384950, 387150, 'SK8', 'Cheadle'),
                                                  ('Cheadle', 'Town', 385000, 387000, 'SK8', 'Cheadle')):
            row = [''] * 34
            row[2], row[7], row[8], row[9], row[16], row[18] = name, local, str(x), str(y), district, town
            rows.append(row)
        with (osnames / 'Data' / 'SJ88.csv').open('w', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerows(rows)
        self.osnames = osnames
        self.out = self.tmp / 'search-offline-uk.tsv.gz'

    def write_csv(self, name, rows):
        path = self.tmp / name
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            csv.writer(stream).writerows(rows)
        return str(path)

    def write_json(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return str(path)

    def read(self):
        with gzip.open(self.out, 'rt', encoding='utf-8') as stream:
            lines = stream.read().split('\n')
        return lines[0], [line.split('\t') for line in lines[1:] if line]

    def build(self, **osni):
        return search.build(str(self.osnames), str(self.out), **osni)

    def test_irish_grid_csv_converted_and_attributed(self):
        streets = self.write_csv('streets.csv', [
            ['OBJECTID', 'Street Name', 'Town', 'X_COORD', 'Y_COORD'],
            ['1', 'DONEGALL SQUARE NORTH', 'BELFAST', '333900', '374000'],     # Belfast City Hall
            ['2', 'Donegall Square North', 'Belfast', '333930', '374020'],     # same street, ~36 m away
            ['3', 'Donegall Square North', 'Belfast', '334500', '374000'],     # 600 m away: kept
            ['4', 'Strand Road', 'Londonderry', '243300', '417200'],
            ['5', '', 'Belfast', '333900', '374000'],                          # no name
            ['6', 'Broken Road', 'Belfast', 'x', '374000'],                    # no point
            ['7', 'Far Away Lane', '', '100000', '100000'],                    # outside NI
        ])
        stats = self.build(osni_streets=streets)
        header, records = self.read()
        fields = header.split('\t')
        self.assertEqual(['#drivemate-search-offline', '1'], fields[:2])
        self.assertEqual(4, len(fields))
        self.assertIn('Contains Royal Mail data', fields[3])
        self.assertTrue(fields[3].startswith(search.CREDITS))
        self.assertIn(LPS.format(time.gmtime().tm_year), fields[3])
        donegall = [r for r in records if r[0] == 'donegall square north']
        self.assertEqual(2, len(donegall))
        first = min(donegall, key=lambda r: float(r[5]))
        self.assertEqual(['R', 'Donegall Square North', 'Belfast'], first[1:4])
        self.assertLess(metres(float(first[4]), float(first[5]), 54.596, -5.930), 100)
        self.assertIn(['strand road', 'R', 'Strand Road', 'Londonderry'], [r[:4] for r in records])
        self.assertEqual({'streets': 3, 'places': 0, 'outside_ni': 1, 'no_name_or_point': 2, 'duplicates': 1},
                         stats['osni'])
        # Never a postcode for Northern Ireland.
        self.assertFalse([r for r in records if r[1] == 'P' and r[0].startswith('bt')])
        self.assertEqual(sorted(r[0] for r in records), [r[0] for r in records])
        self.assertTrue(all(len(r) == 6 for r in records))

    def test_geojson_places_itm_and_lonlat(self):
        places = self.write_json('places.geojson', {
            'type': 'FeatureCollection',
            'crs': {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:EPSG::2157'}},
            'features': [
                {'type': 'Feature', 'properties': {'PLACENAME': 'Belfast', 'TYPE': 'City', 'LGD': 'Belfast'},
                 'geometry': {'type': 'Point', 'coordinates': [733754, 873983]}},
                {'type': 'Feature', 'properties': {'PLACENAME': 'Cushendun', 'TYPE': 'Village', 'LGD': 'Causeway Coast and Glens'},
                 'geometry': {'type': 'Point', 'coordinates': [724900, 932600]}},
                {'type': 'Feature', 'properties': {'PLACENAME': 'Dublin', 'TYPE': 'City'},
                 'geometry': {'type': 'Point', 'coordinates': [715830, 734697]}},   # Republic of Ireland: rejected
                {'type': 'Feature', 'properties': {'PLACENAME': 'Nowhere'}, 'geometry': None},
            ]})
        streets = self.write_json('streets.geojson', {
            'type': 'FeatureCollection',
            'features': [{'type': 'Feature', 'properties': {'STREET_NAME': 'Royal Avenue', 'TOWN': 'Belfast'},
                          'geometry': {'type': 'LineString',
                                       'coordinates': [[-5.9320, 54.6000], [-5.9325, 54.6005], [-5.9330, 54.6010]]}}]})
        stats = self.build(osni_places=places, osni_streets=streets)
        header, records = self.read()
        by = {(r[0], r[1]): r for r in records}
        belfast = by[('belfast', 'C')]
        self.assertEqual('Northern Ireland', belfast[3])   # council same as the name: no help, so the fallback
        self.assertLess(metres(float(belfast[4]), float(belfast[5]), 54.5964, -5.9301), 100)
        self.assertEqual('Causeway Coast and Glens', by[('cushendun', 'V')][3])
        self.assertNotIn(('dublin', 'C'), by)
        royal = by[('royal avenue', 'R')]
        self.assertEqual(('54.6005', '-5.9325'), (royal[4], royal[5]))
        self.assertEqual(1, stats['osni']['outside_ni'])
        self.assertEqual(1, stats['osni']['no_name_or_point'])
        self.assertIn('LPS Intellectual Property', header)

    def test_places_without_type_use_other_settlement_and_area_fallback(self):
        places = self.write_csv('places.csv', [['PLACE_NAME', 'Easting', 'Northing'], ['Moira', '315000', '360000']])
        self.build(osni_places=places)
        _, records = self.read()
        self.assertIn(['moira', 'O', 'Moira', 'Northern Ireland'], [r[:4] for r in records])

    def test_lat_lon_columns(self):
        streets = self.write_csv('streets.csv', [['Name', 'Latitude', 'Longitude'], ['Main Street', '54.5', '-6.0'],
                                                 ['Rue de Paris', '48.85', '2.35']])
        stats = self.build(osni_streets=streets)
        self.assertEqual(1, stats['osni']['streets'])
        self.assertEqual(1, stats['osni']['outside_ni'])

    def test_missing_columns_fail_clearly(self):
        no_coords = self.write_csv('a.csv', [['STREETNAME', 'TOWN'], ['Main Street', 'Lisburn']])
        with self.assertRaisesRegex(search.OsniError, 'no coordinate columns'):
            self.build(osni_streets=no_coords)
        no_name = self.write_csv('b.csv', [['ID', 'X', 'Y'], ['1', '333900', '374000']])
        with self.assertRaisesRegex(search.OsniError, 'no streets name column'):
            self.build(osni_streets=no_name)
        no_geometry = self.write_json('c.geojson', {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'PLACENAME': 'Lisburn'}, 'geometry': None}]})
        with self.assertRaisesRegex(search.OsniError, 'no geometry'):
            self.build(osni_places=no_geometry)
        with self.assertRaises(SystemExit) as caught:
            search.main([str(self.osnames), str(self.out), '--osni-streets', no_coords])
        self.assertIn('OSNI gazetteer not usable', str(caught.exception))

    def test_no_attribution_without_osni(self):
        self.build()
        header, _ = self.read()
        self.assertNotIn('LPS', header)
        self.assertEqual(search.CREDITS, header.split('\t')[3])
        # Nothing usable from OSNI: no LPS credit either.
        empty = self.write_csv('empty.csv', [['STREETNAME', 'X', 'Y'], ['Far Lane', '100000', '100000']])
        self.build(osni_streets=empty)
        header, _ = self.read()
        self.assertNotIn('LPS', header)

    def test_no_duplicate_of_existing_records(self):
        # A GB record in the file near NI: the same name and type within 50 m is not listed again.
        existing = {('main street', 'R'): [(54.5, -6.0)]}
        path = self.write_csv('s.csv', [['STREETNAME', 'LAT', 'LON'], ['Main Street', '54.5002', '-6.0'],
                                        ['Main Street', '54.51', '-6.0']])
        lines, stats = search.osni_lines([('streets', path)], existing)
        self.assertEqual(1, len(lines))
        self.assertEqual(1, stats['duplicates'])

    def test_output_passes_index_validator_and_publisher(self):
        streets = self.write_csv('streets.csv', [['STREETNAME', 'TOWN', 'X', 'Y'],
                                                 ['Cheadle', 'Belfast', '333900', '374000'],   # NI street, GB town name
                                                 ['Ormeau Road', 'Belfast', '334300', '372000']])
        places = self.write_csv('places.csv', [['PLACENAME', 'X', 'Y'], ['Lisburn', '326700', '364300']])
        self.build(osni_streets=streets, osni_places=places)
        rows = list(index.rows(self.out))
        self.assertTrue(any(r[0] == 'ormeau road' and r[1] == 'R' for r in rows))
        self.assertEqual(1, sum(1 for r in rows if r[0] == 'cheadle' and r[1] == 'R'))
        self.assertTrue(any(r[0] == 'cheadle' and r[1] == 'T' for r in rows))
        database = self.tmp / 'search.sqlite'
        self.assertEqual(len(rows), index.build(self.out, database))
        with sqlite3.connect(database) as connection:
            self.assertIn('LPS Intellectual Property',
                          connection.execute("SELECT value FROM metadata WHERE key='attribution'").fetchone()[0])
        staged = self.tmp / 'staged'
        staged.mkdir()
        shutil.copy(self.out, staged / 'search-offline-uk.tsv.gz')
        # The publisher validates each file, then insists on the full asset set: reaching that second
        # check means the search file with NI records passed the publisher's own per-file validation.
        with self.assertRaisesRegex(ValueError, 'Required map assets missing'):
            publisher.local_files(staged)
        # Control: a broken search file is rejected by the per-file check itself.
        with gzip.open(staged / 'search-offline-uk.tsv.gz', 'wt', encoding='utf-8') as stream:
            stream.write('#drivemate-search-offline\t1\t2026-10-09\tCredits\nzeta\tR\tZeta\tA\t54\t-6\nalpha\tR\tA\tA\t54\t-6\n')
        with self.assertRaisesRegex(ValueError, 'unsorted'):
            publisher.local_files(staged)


if __name__ == '__main__':
    unittest.main()
