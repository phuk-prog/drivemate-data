"""Corrupted offline indices must fail before they can be published."""
import gzip
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from search_integrity import audit

HEADER = "#drivemate-search-offline\t1\t2026-10-11\tSource attribution\n"
ROW = "cardiff\tC\tCardiff\tWales\t51.48\t-3.18\n"


class SearchIntegrityTests(unittest.TestCase):
    def check(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.gz"
            path.write_bytes(gzip.compress(content.encode("utf-8")))
            return audit(path)

    def test_complete_valid_index_and_fingerprint(self):
        result = self.check(HEADER + ROW + "sk82ez\tP\t\tCheadle\t53.39\t-2.19\n")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["records_checked"], 2)
        self.assertEqual(result["by_type"], {"C": 1, "P": 1})
        self.assertEqual(len(result["asset"]["sha256"]), 64)

    def test_rejects_empty_and_missing_attribution(self):
        for text in (HEADER, HEADER.replace("Source attribution", "") + ROW):
            self.assertTrue(self.check(text)["errors"])

    def test_rejects_unsorted_keys(self):
        self.assertTrue(self.check(HEADER + ROW + ROW.replace("cardiff", "aberdeen"))["errors"])

    def test_rejects_invalid_coordinates(self):
        for value in ("nan", "inf", "-91", "0"):
            self.assertTrue(self.check(HEADER + ROW.replace("51.48", value))["errors"])

    def test_rejects_malformed_rows(self):
        for row in (ROW.replace("\tC\t", "\tX\t"), ROW.replace("Cardiff", ""),
                    ROW.replace("cardiff", "Cardiff"), ROW.replace("\tWales", ""),
                    ROW.rstrip("\n"), "a" * 20000 + "\n"):
            self.assertTrue(self.check(HEADER + row)["errors"])

    def test_rejects_truncated_gzip_and_crc_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.gz"
            original = gzip.compress((HEADER + ROW).encode())
            for data in (original[:-4], original[:-8] + bytes(8)):
                path.write_bytes(data)
                self.assertTrue(audit(path)["errors"])

    def test_rejects_non_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.gz"
            path.write_bytes(gzip.compress(HEADER.encode() + b"\xff\n"))
            self.assertTrue(audit(path)["errors"])

    def test_invalid_deflate_is_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.gz"
            # Valid gzip header followed by the forbidden DEFLATE block type 3.
            path.write_bytes(bytes.fromhex("1f8b0800000000000003") + b"\x07" + bytes(8))
            self.assertTrue(audit(path)["errors"])

    def test_rejects_missing_and_symlinked_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "missing.gz"
            self.assertTrue(audit(path)["errors"])
            real = pathlib.Path(directory) / "real.gz"
            real.write_bytes(gzip.compress((HEADER + ROW).encode()))
            path.symlink_to(real)
            self.assertTrue(audit(path)["errors"])


if __name__ == "__main__":
    unittest.main()
