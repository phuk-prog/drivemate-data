"""Tests for source fingerprint capture and tampering protections."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "source_inventory", Path(__file__).resolve().parents[1] / "scripts/source_inventory.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
URL = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.osm = self.dir / "base.osm.pbf"
        self.osm.write_bytes(b"synthetic OSM")
        self.optional = {k: self.dir / (k + ".dat") for k in source.SOURCES if k != "osm_uk"}

    def test_absent_optional_sources_explicit_and_required_hashed(self):
        result = source.validate(source.build(self.osm, URL, self.optional))
        self.assertEqual(5, len(result["sources"]))
        self.assertTrue(result["sources"][0]["present"])
        self.assertEqual(64, len(result["sources"][0]["sha256"]))
        self.assertTrue(all(not r["present"] for r in result["sources"][1:]))
        self.assertTrue(all(r["rights_review"] == "not_independently_verified" for r in result["sources"]))

    def test_present_optional_source_hashed_and_readable(self):
        self.optional["os_open_names"].write_bytes(b"fake zip")
        result = source.build(self.osm, URL, self.optional)
        f = self.dir / "source-inventory.json"
        f.write_text(json.dumps(result))
        self.assertEqual(result, source.read(f))
        self.assertTrue(next(x for x in result["sources"] if x["id"] == "os_open_names")["present"])

    def test_missing_or_empty_osm_fails(self):
        self.osm.unlink()
        with self.assertRaisesRegex(ValueError, "Required OSM"):
            source.build(self.osm, URL, self.optional)
        self.osm.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            source.build(self.osm, URL, self.optional)

    def test_invalid_fingerprint_or_licence_fails(self):
        result = source.build(self.osm, URL, self.optional)
        result["sources"][0]["sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            source.validate(result)
        result = source.build(self.osm, URL, self.optional)
        result["sources"][0]["declared_licence"] = "unlicensed"
        with self.assertRaisesRegex(ValueError, "declarations"):
            source.validate(result)

    def test_duplicate_record_fails(self):
        result = source.build(self.osm, URL, self.optional)
        result["sources"][1] = result["sources"][0].copy()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            source.validate(result)

    def ancillary_sources(self):
        for name, (_, _, _, required) in source.PLANETILER_SOURCES.items():
            if required:
                (self.dir / name).write_bytes(b'synthetic ' + name.encode())
        return source.build(self.osm, URL, self.optional, self.dir)

    def test_required_ancillary_files_and_optional_names_are_recorded(self):
        result = source.validate(self.ancillary_sources())
        self.assertEqual(len(result['planetiler_ancillary']), 4)
        self.assertEqual(sum(row['present'] for row in result['planetiler_ancillary']), 3)
        self.assertTrue(all(row['rights_review'] == 'not_independently_verified'
                            for row in result['planetiler_ancillary']))

    def test_missing_ancillary_file_blocks_complete_build_inventory(self):
        self.ancillary_sources()
        (self.dir / 'water-polygons-split-3857.zip').unlink()
        with self.assertRaisesRegex(ValueError, 'Required Planetiler source missing'):
            source.build(self.osm, URL, self.optional, self.dir)

    def test_ancillary_duplicate_tampering_and_false_fingerprints_fail(self):
        for mutation in ('duplicate', 'licence', 'hash', 'absent'):
            result = self.ancillary_sources()
            rows = result['planetiler_ancillary']
            if mutation == 'duplicate': rows[1] = rows[0].copy()
            elif mutation == 'licence': rows[0]['declared_licence'] = 'unrestricted'
            elif mutation == 'hash': rows[0]['sha256'] = 'invalid'
            else: rows[-1]['bytes'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                source.validate(result)

    def osni_document(self):
        return source.build(self.osm, URL, self.optional, osni_sources=self.dir)

    def test_absent_osni_sources_explicit_without_changing_legacy_inventory(self):
        result = source.validate(self.osni_document())
        self.assertEqual(len(result['sources']), 5)
        self.assertEqual(len(result['osni_gazetteers']), 2)
        self.assertTrue(all(not row['present'] for row in result['osni_gazetteers']))
        self.assertNotIn('osni_gazetteers', source.build(self.osm, URL, self.optional))

    def test_osni_csv_and_geojson_fingerprints_recorded(self):
        (self.dir / 'streets.csv').write_text('name,lat,lon\nTest street,54.6,-5.9\n')
        (self.dir / 'places.geojson').write_text('{"type":"FeatureCollection","features":[]}')
        result = source.validate(self.osni_document())
        rows = result['osni_gazetteers']
        self.assertTrue(all(row['present'] for row in rows))
        self.assertEqual(rows[0]['file'], 'streets.csv')
        self.assertEqual(rows[1]['file'], 'places.geojson')
        self.assertNotEqual(rows[0]['sha256'], rows[1]['sha256'])

    def test_osni_url_query_and_fragment_removed(self):
        (self.dir / 'streets.csv').write_text('synthetic input')
        (self.dir / 'streets.source-url.txt').write_text('https://example.org/public.csv?sig=temporary#part')
        row = source.validate(self.osni_document())['osni_gazetteers'][0]
        self.assertEqual(row['download_url'], 'https://example.org/public.csv')

    def test_osni_ambiguous_files_and_symlinks_rejected(self):
        (self.dir / 'streets.csv').write_text('synthetic input')
        (self.dir / 'streets.geojson').write_text('synthetic input')
        with self.assertRaises(ValueError):
            self.osni_document()
        (self.dir / 'streets.geojson').unlink()
        (self.dir / 'streets.csv').unlink()
        (self.dir / 'streets.csv').symlink_to(self.osm)
        with self.assertRaises(ValueError):
            self.osni_document()
        (self.dir / 'streets.csv').unlink()
        (self.dir / 'streets.csv').symlink_to(self.dir / 'missing.csv')
        with self.assertRaises(ValueError):
            self.osni_document()

    def test_osni_credential_bearing_and_unsafe_url_records_rejected(self):
        (self.dir / 'streets.csv').write_text('synthetic input')
        reference = self.dir / 'streets.source-url.txt'
        reference.write_text('https://user:pass@example.org/data.csv')
        with self.assertRaises(ValueError):
            self.osni_document()
        reference.unlink()
        reference.symlink_to(self.osm)
        with self.assertRaises(ValueError):
            self.osni_document()

    def test_osni_inventory_tampering_rejected(self):
        (self.dir / 'streets.csv').write_text('synthetic input')
        for mutation in ('duplicate', 'hash', 'licence', 'absent', 'url'):
            result = self.osni_document()
            rows = result['osni_gazetteers']
            if mutation == 'duplicate': rows[1] = rows[0].copy()
            elif mutation == 'hash': rows[0]['sha256'] = 'bad'
            elif mutation == 'licence': rows[0]['declared_licence'] = 'Unrestricted'
            elif mutation == 'absent': rows[1]['bytes'] = 7
            else: rows[0]['download_url'] = 'https://example.org/data.csv?token=temporary'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                source.validate(result)


if __name__ == "__main__":
    unittest.main()
