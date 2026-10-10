import gzip
import importlib.util
from pathlib import Path
import tempfile
import unittest
from pmtiles.writer import write
from pmtiles.tile import Compression, TileType
from mapbox_vector_tile.Mapbox.vector_tile_pb2 import tile as Tile

spec = importlib.util.spec_from_file_location('verify_pmtiles',
    Path(__file__).resolve().parents[1] / 'scripts/verify_pmtiles.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class PMTilesVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'map.pmtiles'

    def payload(self, invalid_tags=False):
        tile = Tile()
        layer = tile.layers.add()
        layer.name, layer.version, layer.extent = 'transportation', 2, 4096
        if invalid_tags:
            layer.features.add().tags.extend([0, 0])
        return gzip.compress(tile.SerializeToString())

    def archive(self, payload):
        with write(self.path) as writer:
            writer.write_tile(0, payload)
            writer.write_tile(1, payload)
            writer.finalize({'tile_compression': Compression.GZIP, 'tile_type': TileType.MVT}, {})

    def test_deduplicated_tile_runs_validate_with_physical_counts(self):
        self.archive(self.payload())
        report = verifier.verify(self.path)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['addressed_tiles_checked'], 2)
        self.assertEqual(report['physical_contents_checked'], 1)

    def test_truncated_gzip_cannot_pass_archive_verification(self):
        self.archive(self.payload()[:-2])
        with self.assertRaisesRegex(ValueError, 'gzip payload'):
            verifier.verify(self.path)

    def test_mvt_property_indices_cannot_reference_missing_values(self):
        self.archive(self.payload(invalid_tags=True))
        with self.assertRaisesRegex(ValueError, 'property indices'):
            verifier.verify(self.path)

    def test_forged_directory_counts_fail(self):
        self.archive(self.payload())
        with self.path.open('r+b') as stream:
            stream.seek(72)
            stream.write((100).to_bytes(8, 'little'))
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            verifier.verify(self.path)

    def test_tiny_archive_cannot_claim_detailed_uk_coverage(self):
        self.archive(self.payload())
        with self.assertRaisesRegex(ValueError, 'requires zoom 14'):
            verifier.verify(self.path, uk_samples=True)
