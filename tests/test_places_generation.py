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
