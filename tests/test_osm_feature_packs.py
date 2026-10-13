import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("feature_packs", Path(__file__).parents[1] / "scripts/osm_feature_packs.py")
packs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packs)


def feature(kind, coordinates, tags, identity="way/1"):
    return {"type": "Feature", "id": identity,
            "properties": {"@id": identity, "@type": identity.split("/")[0], **tags},
            "geometry": {"type": kind, "coordinates": coordinates}}


class FeaturePackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "features.geojsonseq"
        self.output = self.root / "packs"

    def write(self, features):
        self.source.write_text("".join("\x1e" + json.dumps(f) + "\n" for f in features))

    def read(self, name="feature-packs-106_-5.jsonl.gz"):
        return [json.loads(line) for line in gzip.decompress((self.output / name).read_bytes()).splitlines()]

    def test_full_unnamed_features_tags_ids_precision_and_polygon_holes(self):
        signal = feature("Point", [-2.123456789, 53.123456789],
                         {"highway": "traffic_signals", "future:tag": "unknown"}, "node/3")
        line = feature("LineString", [[-2.14, 53.12], [-2.13, 53.13]],
                       {"road_marking": "lane", "width": "0.15", "change:lanes": "no|yes"})
        polygon = feature("Polygon", [
            [[-2.2, 53.1], [-2.1, 53.1], [-2.1, 53.2], [-2.2, 53.1]],
            [[-2.18, 53.12], [-2.17, 53.12], [-2.17, 53.13], [-2.18, 53.12]]],
            {"area:highway": "primary", "width": "7.25"}, "way/2")
        entrance = feature("Point", [-2.13, 53.14], {"entrance": "yes", "kerb": "lowered"}, "node/4")
        expected = [signal, line, polygon, entrance]
        self.write(expected)
        result = packs.build(self.source, self.output)
        self.assertEqual(4, result["features"])
        self.assertEqual(expected, self.read())

    def test_exact_seam_point_and_long_line_are_in_all_intersecting_cells(self):
        point = feature("Point", [-2.0, 53.0], {"kerb": "raised"}, "node/1")
        self.assertEqual({(105, -5), (105, -4), (106, -5), (106, -4)}, set(packs.feature_cells(point)))
        line = feature("LineString", [[-2.75, 53.25], [-1.25, 53.25]], {})
        self.assertEqual({(106, col) for col in (-6, -5, -4, -3)}, set(packs.feature_cells(line)))
        self.write([point, line])
        packs.build(self.source, self.output)
        self.assertIn(point, self.read())

    def test_multigeometries_and_collections(self):
        geometry = {"type": "GeometryCollection", "geometries": [
            {"type": "MultiPoint", "coordinates": [[-2.1, 53.1], [-2.2, 53.2]]},
            {"type": "MultiLineString", "coordinates": [[[-2.1, 53.1], [-2.2, 53.2]]]},
            {"type": "MultiPolygon", "coordinates": [[[[-2.2, 53.1], [-2.1, 53.1],
                [-2.1, 53.2], [-2.2, 53.1]]]]}]}
        item = {"type": "Feature", "properties": {}, "geometry": geometry}
        self.write([item])
        packs.build(self.source, self.output)
        self.assertEqual([item], self.read())

    def test_deterministic_bytes_with_handle_eviction(self):
        items = [feature("Point", [-2.123, 53.123], {"highway": "traffic_signals"}),
                 feature("Point", [-1.123, 53.123], {"entrance": "yes"}),
                 feature("Point", [-2.123, 53.123], {"kerb": "raised"})]
        self.write(items)
        with mock.patch.object(packs, "OPEN_SPOOLS", 1):
            packs.build(self.source, self.output)
        self.assertEqual([items[0], items[2]], self.read())
        self.assertEqual(3, packs.validate_directory(self.output)["features"])
        other = self.root / "other"
        packs.build(self.source, other)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (other / path.name).read_bytes())

    def test_malformed_feature_aborts_without_partial_output(self):
        valid = feature("Point", [-2.123, 53.123], {"entrance": "yes"})
        for invalid in [feature("Point", [float("nan"), 53], {}),
                        feature("Point", [True, 53], {}),
                        feature("Point", [181, 53], {}),
                        feature("LineString", [[-2, 53]], {}),
                        feature("Polygon", [[[-2, 53], [-1, 53], [-1, 54], [-2, 54]]], {}),
                        feature("MultiPoint", [], {})]:
            with self.subTest(invalid=invalid):
                self.write([valid, invalid])
                with self.assertRaises(ValueError):
                    packs.build(self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_existing_output_and_record_limits_fail(self):
        self.write([feature("Point", [-2.1, 53.1], {})])
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("existing")
        with self.assertRaises(ValueError):
            packs.build(self.source, self.output)
        self.assertEqual("existing", sentinel.read_text())
        sentinel.unlink()
        self.output.rmdir()
        self.write([feature("Point", [-2.1, 53.1], {})] * 2)
        with mock.patch.object(packs, "MAX_RECORDS_PER_PACK", 1):
            with self.assertRaises(ValueError):
                packs.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_large_admin_boundary_is_retained_once_in_global_pack(self):
        boundary = feature("Polygon", [[[-8, 50], [2, 50], [2, 60], [-8, 60], [-8, 50]]],
                           {"boundary": "administrative", "admin_level": "2", "future:tag": "retained"},
                           "relation/123")
        small = feature("Point", [-2.123, 53.123], {"highway": "traffic_signals"}, "node/5")
        self.write([boundary, small])
        packs.build(self.source, self.output)
        self.assertEqual([boundary], self.read("feature-packs-global.jsonl.gz"))
        self.assertEqual([small], self.read())
        manifest = packs.validate_directory(self.output)
        self.assertEqual((2, 2), (manifest["features"], manifest["pack_records"]))
        self.assertEqual("global", manifest["files"]["feature-packs-global.jsonl.gz"]["scope"])
        self.assertIsNone(manifest["files"]["feature-packs-global.jsonl.gz"]["cell"])

    def test_validator_rejects_changed_payload_metadata_and_unlisted_files(self):
        self.write([feature("Point", [-2.123, 53.123], {})])
        packs.build(self.source, self.output)
        path = self.output / packs.MANIFEST
        original = path.read_text()
        manifest = json.loads(original)
        manifest["files"]["feature-packs-106_-5.jsonl.gz"]["records"] += 1
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            packs.validate_directory(self.output)
        path.write_text(original)
        extra = self.output / "unlisted"
        extra.write_text("not a pack")
        with self.assertRaises(ValueError):
            packs.validate_directory(self.output)
        extra.unlink()
        pack = self.output / "feature-packs-106_-5.jsonl.gz"
        pack.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            packs.validate_directory(self.output)

    def test_stdin_preserves_stream_hash_and_matches_file_output(self):
        self.write([feature("Point", [-2.123456789, 53.123456789],
                            {"highway": "traffic_signals", "future": "preserved"}, "node/21")])
        payload = self.source.read_bytes()
        result = subprocess.run([sys.executable, str(Path(packs.__file__)), "--source", "-",
                                 "--output", str(self.output)], input=payload,
                                capture_output=True, check=True)
        self.assertEqual(1, json.loads(result.stdout)["features"])
        manifest = packs.validate_directory(self.output)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["source_sha256"])
        file_output = self.root / "file-output"
        packs.build(self.source, file_output)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (file_output / path.name).read_bytes())

    def test_invalid_stdin_removes_staging_and_never_commits_output(self):
        payload = json.dumps(feature("Point", [-2.123, 53.123], {})).encode() + b"\n{truncated"
        result = subprocess.run([sys.executable, str(Path(packs.__file__)), "--source", "-",
                                 "--output", str(self.output)], input=payload,
                                capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.output.exists())
        self.assertEqual([], list(self.root.glob(".feature-packs-*")))


if __name__ == "__main__":
    unittest.main()
