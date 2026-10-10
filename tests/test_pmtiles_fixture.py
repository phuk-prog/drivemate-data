"""Real-data test fixtures copy exact tiles, include every ancestor and are reproducible."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pmtiles_fixture import build, wanted_tiles, z14_tile


def synthetic_archive(path, cells):
    from pmtiles.writer import write
    from pmtiles.tile import zxy_to_tileid, TileType, Compression
    cells = sorted(cells, key=lambda c: zxy_to_tileid(*c[:3]))
    with write(str(path)) as out:
        for z, x, y, payload in cells:
            out.write_tile(zxy_to_tileid(z, x, y), gzip.compress(payload, mtime=0))
        out.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
                      "min_lon_e7": -90000000, "min_lat_e7": 490000000,
                      "max_lon_e7": 30000000, "max_lat_e7": 600000000,
                      "center_zoom": 8, "center_lon_e7": -25000000, "center_lat_e7": 540000000},
                     {"name": "synthetic UK", "format": "pbf"})


class FixtureTests(unittest.TestCase):
    def test_st_peters_square_tile(self):
        self.assertEqual((8089, 5300), z14_tile(53.4778, -2.2446))
        wanted, centre = wanted_tiles(53.4778, -2.2446, 0)
        self.assertEqual(15, len(wanted))  # one tile per zoom 0..14
        self.assertIn((8, 126, 82), wanted)
        with self.assertRaises(ValueError):
            wanted_tiles(53.4, -2.2, 4)

    def test_fixture_splits_base_detail_and_is_reproducible(self):
        from pmtiles.reader import Reader, MmapSource
        wanted, _ = wanted_tiles(53.4778, -2.2446, 0)
        cells = [(z, x, y, f"{z}/{x}/{y}".encode()) for z, x, y in wanted]
        cells.append((14, 1, 1, b"elsewhere"))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "uk.pmtiles"
            synthetic_archive(src, cells)
            a = build(src, Path(tmp) / "a", 53.4778, -2.2446, 0)
            b = build(src, Path(tmp) / "b", 53.4778, -2.2446, 0)
            self.assertEqual(a["packages"], b["packages"])
            self.assertEqual(10, a["packages"]["base"]["tiles"])
            self.assertEqual(5, a["packages"]["region-z8-x126-y82"]["tiles"])
            with open(Path(tmp) / "a" / "region-z8-x126-y82.pmtiles", "rb") as f:
                r = Reader(MmapSource(f))
                self.assertEqual(b"14/8089/5300", gzip.decompress(r.get(14, 8089, 5300)))
                self.assertIsNone(r.get(14, 1, 1))
                self.assertIsNone(r.get(9, 252, 165))
            meta = json.loads((Path(tmp) / "a" / "fixture.json").read_text())
            self.assertIn("OpenStreetMap", meta["attribution"])
            with self.assertRaises(ValueError):
                build(src, Path(tmp) / "a", 53.4778, -2.2446, 0)  # never overwrite

    def test_missing_source_tiles_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "uk.pmtiles"
            synthetic_archive(src, [(0, 0, 0, b"x"), (10, 504, 328, b"y")])
            with self.assertRaises(ValueError):
                build(src, Path(tmp) / "out", 53.4778, -2.2446, 0)


if __name__ == "__main__":
    unittest.main()
