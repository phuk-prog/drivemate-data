import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import osm_relation_packs as packs


class RelationPackTests(unittest.TestCase):
    def test_connectivity_and_unknown_facts_preserve_order(self):
        result = packs.parse_relation(
            "r42 Ttype=connectivity,connectivity=1:1%7c%2:2,unknown%3d%key=x%2c%y Mw30@from,n20@via,r10@unknown%20%role,w40@to")
        self.assertEqual({"type": "connectivity", "connectivity": "1:1|2:2", "unknown=key": "x,y"}, result["tags"])
        self.assertEqual([("way", 30, "from"), ("node", 20, "via"), ("relation", 10, "unknown role"), ("way", 40, "to")],
                         [(m["type"], m["ref"], m["role"]) for m in result["members"]])

    def test_empty_roles_unicode_and_literal_percent(self):
        result = packs.parse_relation("r1 Tname=Caf%e9%%20%%25% Mw2@,n3@role%40%name")
        self.assertEqual("Café %", result["tags"]["name"])
        self.assertEqual("", result["members"][0]["role"])
        self.assertEqual("role@name", result["members"][1]["role"])
        self.assertIsNone(packs.parse_relation("w2 Tname=ignored Nn1,n2"))
        self.assertEqual([], packs.parse_relation("r1 T M")["members"])

    def test_malformed_relations_fail(self):
        for line in ("r1 Ttype=restriction", "r1 T Mx1@via", "r1 Tkey Mw2@",
                     "r1 Tkey=a%xx% Mw2@", "r1 Tkey=a,key=b M", "r0 T M", "r1 T M Mw2@",
                     "r1 T Mw0@via", "r1 T Mw2@via,", "r1 Tkey=%d800% M"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                packs.parse_relation(line)

    def test_deterministic_sorted_output_and_bucket_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "relations.opl"
            records = ["r100000 Ttype=multipolygon Mw7@outer,w8@inner\n", "r99999 Ttype=restriction Mw3@from,n4@via,w5@to\n",
                       "r1 Ttype=connectivity Mw2@from,w6@to\n"]
            source.write_text("".join(records))
            first = packs.build_packs(source, root / "first")
            source.write_text("".join(reversed(records)))
            second = packs.build_packs(source, root / "second")
            self.assertEqual(first | {"source_opl_sha256": None}, second | {"source_opl_sha256": None})
            self.assertEqual(["relation-packs-0.jsonl.gz", "relation-packs-1.jsonl.gz"], [entry["name"] for entry in first["files"]])
            for name in [entry["name"] for entry in first["files"]]:
                self.assertEqual((root / "first" / name).read_bytes(), (root / "second" / name).read_bytes())
            self.assertEqual(first, packs.validate_directory(root / "first"))
            packs.build_packs(source, root / "third")
            self.assertEqual((root / "second/relation-packs-manifest.json").read_bytes(),
                             (root / "third/relation-packs-manifest.json").read_bytes())
            with gzip.open(root / "first/relation-packs-0.jsonl.gz", "rt") as stream:
                self.assertEqual([1, 99999], [json.loads(line)["id"] for line in stream])

    def test_duplicate_and_bad_input_do_not_expose_partial_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output = root / "relations.opl", root / "out"
            for text in ("r1 T M\nr1 T M\n", "r1 T M\nr2 Ttype=oops Mbad\n"):
                source.write_text(text)
                with self.assertRaises(ValueError):
                    packs.build_packs(source, output)
                self.assertFalse(output.exists())
                self.assertEqual([source], list(root.iterdir()))

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output = root / "relations.opl", root / "out"
            source.write_text("r1 T M\n")
            output.mkdir()
            (output / "keep").write_text("existing")
            with self.assertRaises(ValueError):
                packs.build_packs(source, output)
            self.assertEqual("existing", (output / "keep").read_text())

    def test_validation_checks_hash_record_schema_counts_and_bucket_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "relations.opl"
            source.write_text("r1 Ttype=connectivity Mw2@from\n")
            for index, content in enumerate((
                    '{"id":100001,"tags":{},"members":[]}\n',
                    '{"id":1,"tags":{"a":"first","a":"lost"},"members":[]}\n',
                    '{"id":1,"tags":{},"members":[{"type":"guess","ref":2,"role":"via"}]}\n',
                    '{"id":1,"tags":{},"members":[]}\n' * 2)):
                output = root / str(index)
                manifest = packs.build_packs(source, output)
                pack = output / manifest["files"][0]["name"]
                pack.write_bytes(gzip.compress(content.encode(), mtime=0))
                manifest["files"][0].update(bytes=pack.stat().st_size, sha256=packs.file_digest(pack))
                (output / "relation-packs-manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    packs.validate_directory(output)
            output = root / "integrity"
            manifest = packs.build_packs(source, output)
            pack = output / manifest["files"][0]["name"]
            pack.write_bytes(pack.read_bytes() + b"damage")
            with self.assertRaises(ValueError):
                packs.validate_directory(output)
            count_output = root / "count"
            manifest = packs.build_packs(source, count_output)
            manifest["files"][0]["records"] += 1
            (count_output / "relation-packs-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                packs.validate_directory(count_output)

    def test_empty_manifest_and_whole_input_fingerprint(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "relations.opl"
            data = b"n1 T x1 y2\nw2 T Nn1\n"
            source.write_bytes(data)
            manifest = packs.build_packs(source, root / "out")
            self.assertEqual(0, manifest["relations"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["source_opl_sha256"])
            self.assertEqual(manifest, packs.validate_directory(root / "out"))


if __name__ == "__main__":
    unittest.main()
