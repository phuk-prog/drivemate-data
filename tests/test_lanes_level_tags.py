"""lanes.py keeps OSM level/shape tags and level-only roads (new optional keys, old format intact)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINE = [[-2.2, 53.4], [-2.19, 53.4]]


def feat(i, **props):
    return {"type": "Feature", "properties": {"@id": f"w{i}", "highway": "primary", **props},
            "geometry": {"type": "LineString", "coordinates": LINE}}


class LaneLevelTagTests(unittest.TestCase):
    def build(self, feats):
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "roads.geojsonseq"
            src.write_text("".join("\x1e" + json.dumps(f) + "\n" for f in feats), encoding="utf-8")
            out = pathlib.Path(d) / "out.json"
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lanes.py"), str(src), str(out)],
                               capture_output=True, text=True, check=True)
            doc = json.loads(out.read_text(encoding="utf-8"))
            return {w["id"]: w for w in doc["ways"]}, json.loads(r.stdout)

    def test_new_tags_kept_on_lane_way(self):
        ways, _ = self.build([feat(1, lanes="3", oneway="yes", layer="1", bridge="viaduct",
                                   width="11", est_width="10", level="1", kerb="raised")])
        self.assertEqual({"highway": "primary", "lanes": "3", "oneway": "yes", "layer": "1",
                          "bridge": "viaduct", "width": "11", "est_width": "10", "level": "1",
                          "kerb": "raised"}, ways["w1"]["t"])
        self.assertNotIn("ctx", ways["w1"])

    def test_roundabout_flag_and_untagged_stay_compatible(self):
        ways, _ = self.build([feat(2, lanes="2", junction="roundabout")])
        self.assertEqual("roundabout", ways["w2"]["t"]["junction"])
        self.assertNotIn("layer", ways["w2"]["t"])

    def test_level_only_road_is_kept_and_flagged(self):
        ways, stats = self.build([feat(3, tunnel="yes", layer="-1", name="Underpass"),
                                  feat(4, bridge="yes"), feat(5, layer="0"), feat(6, bridge="no"),
                                  feat(7, name="Plain")])
        self.assertEqual({"w3", "w4"}, set(ways))
        self.assertEqual(1, ways["w3"]["ctx"])
        self.assertEqual("-1", ways["w3"]["t"]["layer"])
        self.assertEqual(2, stats["level_only"])
        self.assertEqual(0, stats["with_lanes"])


if __name__ == "__main__":
    unittest.main()
