"""Search acceptance port: synthetic data only, no network."""
import contextlib
import gzip
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import search_acceptance as sa

ROWS = [
    # key, type, name, area, lat, lon
    ("menai grove", "R", "Menai Grove", "Cheadle, SK8", 53.3955, -2.1942),
    ("piccadilly", "R", "Piccadilly", "London, W1J", 51.5074, -0.1400),
    ("piccadilly", "R", "Piccadilly", "Manchester, M1", 53.4810, -2.2370),
    ("piccadilly gardens", "V", "Piccadilly Gardens", "Manchester, M1", 53.4806, -2.2368),
    ("sk82ez", "P", "", "Cheadle", 53.395466, -2.194193),
    ("sk82ey", "P", "", "Cheadle", 53.3950, -2.1950),
    ("stockport", "T", "Stockport", "Stockport, SK1", 53.4106, -2.1575),
    ("stockport", "R", "Stockport", "Nowhere, XX1", 53.4106, -2.1575),
    ("stockport road", "R", "Stockport Road", "Manchester, M12", 53.46, -2.20),
    ("stockportx", "H", "Stockportx", "Far, YY1", 55.0, -3.0),
]


def write(path, rows=ROWS):
    lines = ["#drivemate-search-offline\t1\t2026-10-10\tcredits"] + ["\t".join(map(str, r)) for r in sorted(rows)]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class KeyTests(unittest.TestCase):
    def test_key_matches_kotlin(self):
        self.assertEqual(sa.key("  Caerdydd & Ŵrecsam!! "), "caerdydd and wrecsam")
        self.assertEqual(sa.key("St. Mary's-Road"), "st mary s road")
        self.assertEqual(sa.key("SK8 2EZ"), "sk8 2ez")


class RankingTests(unittest.TestCase):
    def lines(self):
        return ["\t".join(map(str, r)) for r in sorted(ROWS)]

    def test_exact_before_longer_keys(self):
        res = sa.search_lines(self.lines(), "stockport", None)
        self.assertEqual(res[0]["name"], "Stockport")
        self.assertIn("Stockport Road", [r["name"] for r in res])
        self.assertEqual(res[-1]["name"], "Stockportx")

    def test_type_order_is_pctnrsvhoba_when_no_position(self):
        # same key, no position: town (T) before street (R) per "PCTNRSVHOBAFMEU"
        res = sa.search_lines(self.lines(), "stockport", None)
        self.assertEqual([r["address"] for r in res[:2]], ["Stockport, SK1", "Nowhere, XX1"])
        self.assertEqual(sa.ORDER, "PCTNRSVHOBAFMEU")

    def test_distance_beats_type_and_picks_local_piccadilly(self):
        res = sa.search_lines(self.lines(), "piccadilly", (53.48, -2.24))
        self.assertEqual(res[0]["address"], "Manchester, M1")
        res = sa.search_lines(self.lines(), "piccadilly", (51.5, -0.14))
        self.assertEqual(res[0]["address"], "London, W1J")

    def test_exact_beats_nearer_prefix_match(self):
        res = sa.search_lines(self.lines(), "stockport", (53.46, -2.20))
        self.assertEqual(res[0]["name"], "Stockport")  # exact, though Stockport Road is nearer

    def test_postcode_name_and_dedupe(self):
        res = sa.search_lines(self.lines() + self.lines(), "sk82ez", None)
        self.assertEqual([r["name"] for r in res], ["SK8 2EZ"])

    def test_caps_results(self):
        rows = [("aa%03d" % i, "R", "Aa%03d" % i, "T", 53.0, -2.0) for i in range(30)]
        res = sa.search_lines(["\t".join(map(str, r)) for r in sorted(rows)], "aa", None)
        self.assertEqual(len(res), 12)


class EndToEndTests(unittest.TestCase):
    def test_run_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            write(d / "s.tsv.gz")
            qs = {"queries": [
                {"query": "SK8 2EZ", "near": [53.395466, -2.194193], "radius_m": 200, "types": ["P"]},
                {"query": "sk8 2ez", "near": [53.5, -2.5], "radius_m": 200},
                {"query": "Stokport", "near": [53.4106, -2.1575], "radius_m": 3000, "known_fail": True},
                {"query": "Stockport", "near": [53.4106, -2.1575], "radius_m": 100, "known_fail": True},
            ]}
            (d / "q.json").write_text(json.dumps(qs))
            rep = sa.run(str(d / "s.tsv.gz"), qs["queries"])
            self.assertEqual([r["status"] for r in rep], ["PASS", "FAIL", "KNOWN-FAIL", "XPASS"])
            # The deliberately wrong "near" above makes main() print a FAIL line (23 km away). That is
            # this test's own fixture, so keep it out of the CI log where it looks like a real failure.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sa.main([str(d / "s.tsv.gz"), str(d / "q.json"), "--out", str(d / "o.json")]), 1)
            qs["queries"].pop(1)
            (d / "q.json").write_text(json.dumps(qs))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sa.main([str(d / "s.tsv.gz"), str(d / "q.json"), "--out", str(d / "o.json"),
                                          "--summary", str(d / "s.md")]), 0)
            self.assertIn("SK8 2EZ", (d / "s.md").read_text())

    def test_postcode_spellings_all_find_the_same_point(self):
        # Regression: the 23350 m "FAIL sk8 2ez" in CI came from the fixture above, not from search.
        # Every spelling of the postcode must normalise like OfflineSearch.kt and hit the exact point.
        with tempfile.TemporaryDirectory() as d:
            write(pathlib.Path(d) / "s.tsv.gz")
            for spelling in ("SK8 2EZ", "sk8 2ez", "sk82ez", " Sk8  2eZ ", "SK8-2EZ"):
                with self.subTest(spelling=spelling):
                    res = sa.search(str(pathlib.Path(d) / "s.tsv.gz"), spelling, (53.5, -2.5))
                    self.assertEqual(res[0]["name"], "SK8 2EZ")
                    self.assertLess(sa.distance_m((53.395466, -2.194193), (res[0]["lat"], res[0]["lon"])), 10)

    def test_shipped_queries_are_well_formed(self):
        data = json.loads((ROOT / "docs/validation/manchester-search-queries.json").read_text())
        qs = data["queries"]
        self.assertGreaterEqual(len(qs), 18)
        self.assertTrue(any(q.get("known_fail") for q in qs))
        for q in qs:
            self.assertEqual(len(q["near"]), 2)
            self.assertGreater(q["radius_m"], 0)


if __name__ == "__main__":
    unittest.main()
