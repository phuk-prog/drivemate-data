"""Exercise the road exporter without inventing lane or boundary information."""
import json
import gzip
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lanes.py"


def feature(way_id, tags, coordinates):
    return {"type": "Feature", "properties": {"@id": way_id, "@type": "way", **tags},
            "geometry": {"type": "LineString", "coordinates": coordinates}}


class LaneDetailPreservationTests(unittest.TestCase):
    def export(self, features, squares=False, details=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "roads.geojsonseq"
            source.write_text("".join("\x1e" + json.dumps(f) + "\n" for f in features), encoding="utf-8")
            output = root / ("squares" if squares else "lanes.json")
            environment = dict(os.environ)
            environment.pop("GITHUB_STEP_SUMMARY", None)
            command = [sys.executable, str(SCRIPT), str(source), str(output)]
            detail_output = root / "details"
            if details:
                command += ["--details-out", str(detail_output)]
            run = subprocess.run(command,
                                 check=True, capture_output=True, text=True, env=environment)
            stats = json.loads(run.stdout)
            if details:
                return {p.name: json.loads(gzip.decompress(p.read_bytes()))
                        for p in detail_output.glob("*.json.gz")}, stats
            if squares:
                return {p.name: json.loads(p.read_text()) for p in output.glob("*.json")}, stats
            return json.loads(output.read_text()), stats

    def test_preserves_tags_and_original_geometry_without_direction_rewrite(self):
        tags = {"highway": "primary", "lanes:backward": "2", "oneway": "-1",
                "turn:lanes:backward": "left|through", "change:lanes:backward": "no|not_left",
                "layer": "-2", "bridge": "yes", "tunnel": "building_passage",
                "width": "7.25", "width:lanes": "3.1|3.6", "kerb": "raised",
                "destination:lanes": "Centre|Airport", "future:road:detail": "keep me"}
        coordinates = [[-2.123456789, 53.456789123], [-2.123451234, 53.456781234]]
        result, stats = self.export([feature("way/7", tags, coordinates)])
        way = result["ways"][0]
        self.assertEqual("way/7", way["id"])
        self.assertEqual({k: v for k, v in tags.items() if k not in ("kerb", "future:road:detail")}, way["t"])
        self.assertEqual(coordinates, way["g"])
        self.assertNotIn("ctx", way)
        self.assertEqual((1, 1, 0), (stats["with_lanes"], stats["with_turn_lanes"], stats["context_only"]))

    def test_context_roads_are_retained_without_lane_claims(self):
        tags = {"highway": "residential", "name": "Unsurveyed Road", "layer": "1", "bridge": "yes"}
        result, stats = self.export([feature("way/8", tags, [[-2.2, 53.4], [-2.19, 53.41]])])
        self.assertEqual([], result["ways"])
        self.assertEqual((1, 0, 0), (stats["context_only"], stats["with_lanes"], stats["with_turn_lanes"]))

    def test_arrows_without_count_remain_lane_data(self):
        result, stats = self.export([feature("way/9", {"highway": "primary", "turn:lanes": "left|through"},
                                                 [[-2.2, 53.4], [-2.19, 53.41]])])
        self.assertNotIn("ctx", result["ways"][0])
        self.assertNotIn("lanes", result["ways"][0]["t"])
        self.assertEqual((0, 1, 0), (stats["with_lanes"], stats["with_turn_lanes"], stats["context_only"]))

    def test_complete_context_geometry_reaches_intermediate_and_seam_squares(self):
        coordinates = [[-2.75, 53.25], [-1.25, 53.25]]
        seam = [[-2.0, 53.1], [-2.0, 53.2]]
        result, _ = self.export([feature("way/10", {"highway": "primary"}, coordinates),
                                feature("way/11", {"highway": "service"}, seam)], details=True)
        for col in (-6, -5, -4, -3):
            way = next(w for w in result[f"road-details-106_{col}.json.gz"]["ways"] if w["id"] == "way/10")
            self.assertEqual(coordinates, way["g"])
            self.assertEqual(1, way["ctx"])
        for col in (-5, -4):
            way = next(w for w in result[f"road-details-106_{col}.json.gz"]["ways"] if w["id"] == "way/11")
            self.assertEqual(seam, way["g"])
            self.assertEqual(1, way["ctx"])

    def test_backend_details_preserve_unknown_tags_and_context_identity(self):
        tags = {"highway": "primary", "future:tag": "original", "kerb": "raised", "lanes": "2"}
        context = {"highway": "service", "future:tag": "context", "tunnel": "yes"}
        geometry = [[-2.123456789, 53.234567891], [-2.123451234, 53.234561234]]
        result, _ = self.export([feature("way/12", tags, geometry),
                                feature("way/13", context, geometry)], details=True)
        ways = result["road-details-106_-5.json.gz"]["ways"]
        self.assertEqual(tags, ways[0]["t"])
        self.assertEqual(geometry, ways[0]["g"])
        self.assertNotIn("ctx", ways[0])
        self.assertEqual(context, ways[1]["t"])
        self.assertEqual(1, ways[1]["ctx"])

    def test_backend_compression_is_deterministic_and_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "roads.geojsonseq"
            source.write_text(json.dumps(feature("way/14", {"highway": "service"},
                                                [[-2.2, 53.4], [-2.19, 53.41]])))
            outputs = []
            environment = dict(os.environ)
            environment.pop("GITHUB_STEP_SUMMARY", None)
            for name in ("first", "second"):
                destination = root / name
                subprocess.run([sys.executable, str(SCRIPT), str(source), str(root / f"{name}.json"),
                                "--details-out", str(destination)], check=True,
                               capture_output=True, env=environment)
                outputs.append(next(destination.glob("*.json.gz")).read_bytes())
            self.assertEqual(outputs[0], outputs[1])
            subprocess.run([sys.executable, str(SCRIPT), str(source), str(root / "plain.json")],
                           check=True, capture_output=True, env=environment)
            self.assertEqual([], json.loads((root / "plain.json").read_text())["ways"])


if __name__ == "__main__":
    unittest.main()
