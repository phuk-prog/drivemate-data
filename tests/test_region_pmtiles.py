"""Synthetic regions verify deterministic ownership, size splitting and archive output."""
import gzip
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from region_pmtiles import parent_key, region_bounds, plan_tile_sets, build


class RegionPartitionTests(unittest.TestCase):
    def test_parent_tile_assignment_exact(self):
        self.assertEqual((8,126,82),parent_key(14,8070,5280,8))
        self.assertEqual((8,126,82),parent_key(9,252,164,8))
        with self.assertRaises(ValueError):
            parent_key(7,1,2,8)

    def test_webmercator_bounds_and_size(self):
        w,s,e,n=region_bounds((8,126,82))
        self.assertTrue(w < -2.2426 < e and s < 53.4808 < n)
        self.assertGreater(e-w,1)
        self.assertGreater(n-s,0.6)

    def test_base_and_two_regions_unique(self):
        rows=[
            (1,0,0,0,0,30),
            (2,8,126,82,30,30),
            (3,10,504,328,60,30),
            (4,10,505,328,90,30),
            (5,10,508,340,120,30),
        ]
        packs=plan_tile_sets(rows,200)
        self.assertEqual(2,len(packs["base"]))
        self.assertEqual(2,len(packs["region-z8-x126-y82"]))
        self.assertEqual(1,len(packs["region-z8-x127-y85"]))
        self.assertEqual(5,sum(map(len,packs.values())))

    def test_dense_region_auto_splits_to_smaller_sections(self):
        rows=[(1,8,126,82,0,5)]
        rows += [(n+2,10,504+n,328,5+n*60,60) for n in range(4)]
        packs=plan_tile_sets(rows,95)
        self.assertNotIn("region-z8-x126-y82", packs)
        self.assertTrue(any(p.startswith("region-z10-") for p in packs))
        self.assertEqual(len(rows),sum(map(len,packs.values())))
        self.assertTrue(all(sum(r[5] for r in rows)<=95 for name,rows in packs.items() if name!="base"))

    def test_no_duplicate_tile_and_bad_minimums(self):
        with self.assertRaises(ValueError):
            plan_tile_sets([(1,8,126,82,0,10)],200)
        with self.assertRaises(ValueError):
            plan_tile_sets([(1,8,126,82,0,10),(2,10,504,328,10,250)],100)

    def test_writing_pilot_pmtiles_preserves_compressed_payload(self):
        from pmtiles.writer import write
        from pmtiles.reader import Reader
        from pmtiles.tile import zxy_to_tileid,TileType,Compression
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"whole.pmtiles"
            cells=[
                (0,0,0,b"base"),
                (8,126,82,b"boundary"),
                (10,504,328,b"manchester-west"),
                (10,505,328,b"manchester-east"),
                (11,1009,656,b"manchester-detail-mid"),
                (10,508,340,b"london"),
            ]
            cells.sort(key=lambda v:zxy_to_tileid(*v[:3]))
            with write(str(path)) as out:
                for z,x,y,payload in cells:
                    out.write_tile(zxy_to_tileid(z,x,y),gzip.compress(payload,mtime=0))
                out.finalize({"tile_type":TileType.MVT,"tile_compression":Compression.GZIP,
                              "min_lon_e7":-90000000,"min_lat_e7":490000000,
                              "max_lon_e7":30000000,"max_lat_e7":600000000,
                              "center_zoom":8,"center_lon_e7":-25000000,
                              "center_lat_e7":540000000},
                             {"name":"synthetic UK","format":"pbf"})
            output=Path(tmp)/"out"
            manifest=build(path,output,pilot="8/126/82",max_bytes=200000)
            self.assertEqual("pilot_unpublished",manifest["status"])
            self.assertEqual(set(manifest["packages"]),{"base","region-z8-x126-y82"})
            with (output/"region-z8-x126-y82.pmtiles").open("rb") as f:
                data=f.read()
            reader=Reader(lambda a,b:data[a:a+b])
            self.assertEqual(gzip.compress(b"manchester-west",mtime=0),
                             reader.get(10,504,328))
            self.assertIsNone(reader.get(10,508,340))
            self.assertEqual(3,reader.header()["addressed_tiles_count"])
            self.assertEqual(3,manifest["packages"]["region-z8-x126-y82"]["verified_tile_payloads"])
            self.assertEqual(2,manifest["packages"]["base"]["verified_tile_payloads"])
            self.assertEqual(6,manifest["source_addressed_tiles"])
            # Offline companions for the region are listed; base has none.
            companions=manifest["packages"]["region-z8-x126-y82"]["companions"]
            self.assertIn("lanes-106_-5.json",companions["lanes"])
            self.assertIn("places-213_-9.json.gz",companions["places"])
            self.assertNotIn("companions",manifest["packages"]["base"])
            self.assertIn("cameras-uk.json",manifest["national_files"])
            self.assertEqual(5,manifest["selected_addressed_tiles"])

    def test_zoom9_is_base_only_when_region_subdivides(self):
        from pmtiles.tile import zxy_to_tileid
        rows = [
            (zxy_to_tileid(8,126,82),8,126,82,0,15),
            (zxy_to_tileid(9,252,164),9,252,164,15,15),
            (zxy_to_tileid(10,504,328),10,504,328,30,120),
            (zxy_to_tileid(10,505,328),10,505,328,150,120),
            (zxy_to_tileid(10,506,328),10,506,328,270,120),
        ]
        groups = plan_tile_sets(rows,130)
        self.assertEqual(2,len(groups["base"]))
        self.assertTrue(any(n.startswith("region-z10") for n in groups if n!="base"))
        self.assertTrue(all(all(row[1] >= 10 for row in items)
                            for name, items in groups.items() if name != "base"))
        self.assertEqual(len(rows), sum(len(v) for v in groups.values()))


if __name__ == "__main__":
    unittest.main()
