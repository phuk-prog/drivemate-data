"""Regional packages list the real companion data squares they overlap, never invented ones."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from region_companions import squares_for_bounds, companion_names, annotate
from region_pmtiles import region_bounds


class CompanionSquareTests(unittest.TestCase):
    def test_manchester_root_covers_city_squares(self):
        bounds = region_bounds((8, 126, 82))
        names = companion_names(bounds)
        # Manchester city centre 53.4808, -2.2426 → half-degree 106_-5, quarter 213_-9.
        self.assertIn("lanes-106_-5.json", names["lanes"])
        self.assertIn("limits-106_-5.json", names["limits"])
        self.assertIn("roadinfo-106_-5.json", names["roadinfo"])
        self.assertIn("places-213_-9.json.gz", names["places"])
        for layer in ("lanes", "limits", "roadinfo", "places"):
            self.assertEqual(names[layer], sorted(set(names[layer])))

    def test_grid_line_bound_does_not_pull_in_empty_neighbour(self):
        self.assertEqual([(106, -5)], squares_for_bounds([-2.5, 53.0, -2.0, 53.5], 2))
        self.assertEqual(4, len(squares_for_bounds([-2.6, 52.9, -2.0, 53.5], 2)))

    def test_adjacent_regions_share_seam_square(self):
        west = companion_names(region_bounds((8, 126, 82)))["lanes"]
        east = companion_names(region_bounds((8, 127, 82)))["lanes"]
        self.assertTrue(set(west) & set(east), "a square straddling the seam belongs to both")

    def test_inventory_filter_drops_absent_squares(self):
        bounds = region_bounds((8, 126, 82))
        names = companion_names(bounds, available={"lanes-106_-5.json", "places-213_-9.json.gz"})
        self.assertEqual(["lanes-106_-5.json"], names["lanes"])
        self.assertEqual([], names["limits"])
        self.assertEqual(["places-213_-9.json.gz"], names["places"])

    def test_rejects_bad_or_huge_bounds(self):
        for bad in ([1, 2, 3], [0, 0, 0, 0], [0, 50, float("nan"), 51], [-10, 49, 10, 61], [5, 50, 4, 51]):
            with self.assertRaises(ValueError):
                squares_for_bounds(bad, 2)

    def test_annotate_adds_companions_and_keeps_input(self):
        inventory = {"schema": 1, "packages": {
            "base": {"tiles": 3, "bounds": None},
            "region-z8-x126-y82": {"tiles": 5, "bounds": region_bounds((8, 126, 82))},
        }}
        out = annotate(inventory, available={"cameras-uk.json", "lanes-106_-5.json"})
        self.assertNotIn("companions", inventory["packages"]["region-z8-x126-y82"])
        self.assertNotIn("companions", out["packages"]["base"])
        self.assertEqual(["lanes-106_-5.json"], out["packages"]["region-z8-x126-y82"]["companions"]["lanes"])
        self.assertEqual(["cameras-uk.json"], out["national_files"])
        self.assertTrue(out["companion_grids"]["filtered_to_release_inventory"])
        with self.assertRaises(ValueError):
            annotate({"packages": {"region-z8-x1-y1": {"tiles": 1}}})


if __name__ == "__main__":
    unittest.main()
