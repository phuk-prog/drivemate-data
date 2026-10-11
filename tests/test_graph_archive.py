import gzip
import io
from pathlib import Path
import sys
import struct
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graph_archive import validate


def packed(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, contents, typ in members:
            entry = tarfile.TarInfo(name)
            entry.type = typ
            entry.size = len(contents)
            entry.linkname = '/tmp/unsafe' if typ == tarfile.SYMTYPE else ''
            archive.addfile(entry, io.BytesIO(contents))
    return output.getvalue()


GOOD = [('index.bin', struct.pack('<QII', 1536, 3014 * 8, len(b'synthetic tile')), tarfile.REGTYPE),
        ('0/003/014.gph', b'synthetic tile', tarfile.REGTYPE)]


class GraphArchiveTests(unittest.TestCase):
    def run_archive(self, members, compressed=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph'
            payload = packed(members)
            path.write_bytes(gzip.compress(payload) if compressed else payload)
            return validate(path, compressed)

    def test_valid_plain_and_compressed_container(self):
        plain = self.run_archive(GOOD)
        compressed = self.run_archive(GOOD, True)
        self.assertEqual(plain, compressed)
        self.assertEqual(plain['tile_members'], 1)
        self.assertEqual(plain['by_level'], {'0': 1})

    def test_missing_or_inconsistent_index(self):
        for members in (GOOD[1:], GOOD[:1], [('index.bin', bytes(32), tarfile.REGTYPE)] + GOOD[1:]):
            with self.assertRaises(ValueError):
                self.run_archive(members)

    def test_unsafe_paths_links_empty_and_duplicate_members(self):
        for member in [('../outside.gph', b'x', tarfile.REGTYPE),
                       ('/0/003/014.gph', b'x', tarfile.REGTYPE),
                       ('0/003/014.gph', b'x', tarfile.SYMTYPE),
                       ('0/003/014.gph', b'', tarfile.REGTYPE), GOOD[1]]:
            with self.assertRaises(ValueError):
                self.run_archive(GOOD + [member])

    def test_truncated_final_member(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph'
            # index payload/header/padding followed by a tile header with incomplete data.
            path.write_bytes(packed(GOOD)[:1540])
            with self.assertRaises(ValueError):
                validate(path)

    def test_declared_fingerprint_and_size_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph'
            path.write_bytes(packed(GOOD))
            for kwargs in ({'expected_bytes': 100}, {'expected_sha256': '0' * 64}):
                with self.assertRaises(ValueError):
                    validate(path, **kwargs)

    def test_rejects_index_with_forged_offsets_ids_or_sizes(self):
        for offset, graphid, size in ((0, 3014 * 8, 14), (1536, 0, 14), (1536, 3014 * 8, 99)):
            members = [('index.bin', struct.pack('<QII', offset, graphid, size), tarfile.REGTYPE)] + GOOD[1:]
            with self.assertRaises(ValueError):
                self.run_archive(members)
