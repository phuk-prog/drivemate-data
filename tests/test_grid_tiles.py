"""Regression tests: no lane/speed limit segment silently disappears at grid seams."""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from grid_tiles import tiles_for_polyline


class GridTilesTests(unittest.TestCase):
    def test_intermediate_region_without_vertex_included(self):
        # Existing pipeline used vertices only: middle tile (row 1) was lost.
        tiles = tiles_for_polyline([[0.2, 0.2], [0.2, 1.2]], 2)
        self.assertTrue({(0, 0), (1, 0), (2, 0)} <= tiles)

    def test_two_directions_and_negative_longitudes(self):
        forward = [[-2.8, 53.2], [-1.7, 53.2]]
        self.assertEqual(tiles_for_polyline(forward, 2),
                         tiles_for_polyline(list(reversed(forward)), 2))
        self.assertTrue({(106, -6), (106, -5), (106, -4)} <=
                        tiles_for_polyline(forward, 2))

    def test_diagonal_near_grid_corner_includes_all_touched_tiles(self):
        tiles = tiles_for_polyline([[0.25, 0.25], [0.75, 0.75]], 2)
        self.assertTrue({(0, 0), (1, 1), (0, 1), (1, 0)} <= tiles)

    def test_road_exactly_on_tile_edge_delivered_to_both_sides(self):
        tiles = tiles_for_polyline([[0.5, 0.1], [0.5, 0.4]], 2)
        self.assertIn((0, 0), tiles)
        self.assertIn((0, 1), tiles)

    def test_single_cell_matches_existing_behavior(self):
        self.assertEqual({(106, -5)}, tiles_for_polyline([[-2.35, 53.2], [-2.3, 53.3]], 2))

    def test_invalid_geometry_is_not_silently_accepted(self):
        for geometry in ([], [[1, 2]], [[0, 0], [float("nan"), 0]]):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                tiles_for_polyline(geometry, 2)


if __name__ == "__main__":
    unittest.main()
