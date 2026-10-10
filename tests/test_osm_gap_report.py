"""Synthetic OPL checks for the OSM gap report (no network)."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import osm_gap_report as gap  # noqa: E402


def node(i, lat, lon):
    return "n%d x%.6f y%.6f\n" % (i, lon, lat)


def way(i, refs, **tags):
    return "w%d T%s N%s\n" % (i, ",".join("%s=%s" % kv for kv in tags.items()), ",".join("n%d" % n for n in refs))


def run(opl_text, corridors=None):
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "x.opl"
        p.write_text(opl_text)
        ways, _ = gap.read_opl(p)
        coords = gap.read_node_coords(p, {n for _, ns in ways.values() for n in ns})
        return gap.build_report(ways, coords, corridors)


FAR = [node(1, 51.0, -1.0), node(2, 51.001, -1.0), node(3, 51.002, -1.0), node(4, 51.001, -0.999)]
NEAR = [node(11, 53.4000, -2.2000), node(12, 53.4010, -2.2000), node(13, 53.4020, -2.2000)]


class GapReport(unittest.TestCase):
    def kinds(self, report):
        return sorted((i["kind"], i["way_id"]) for i in report["items"])

    def test_turn_lanes_missing_at_junction(self):
        text = "".join(FAR) + way(100, [1, 2], highway="primary", lanes="3", maxspeed="40") \
            + way(101, [2, 3], highway="primary", lanes="3", maxspeed="40", **{"turn:lanes": "left|through|right"}) \
            + way(102, [2, 4], highway="residential")
        report = run(text)
        self.assertEqual(self.kinds(report), [("turn_lanes", 100)])

    def test_directional_turn_lanes_and_single_lane_not_reported(self):
        text = "".join(FAR) + way(100, [1, 2], highway="secondary", lanes="2", maxspeed="30", **{"turn:lanes:forward": "left|right"}) \
            + way(101, [2, 3], highway="secondary", lanes="1", maxspeed="30") + way(102, [2, 4], highway="service")
        self.assertEqual(run(text)["items"], [])

    def test_no_junction_no_turn_lane_item(self):
        text = "".join(FAR) + way(100, [1, 2], highway="trunk", lanes="2", maxspeed="70")
        self.assertEqual(run(text)["counts"]["total"], 0)

    def test_maxspeed_classes(self):
        text = "".join(FAR) + way(1, [1, 2], highway="tertiary") + way(2, [2, 3], highway="residential") \
            + way(3, [1, 3], highway="motorway", maxspeed="70")
        self.assertEqual(self.kinds(run(text)), [("maxspeed", 1)])

    def test_slip_without_lanes(self):
        text = "".join(FAR) + way(5, [1, 2], highway="motorway_link", maxspeed="40") \
            + way(6, [2, 3], highway="trunk_link", maxspeed="40", lanes="1")
        self.assertEqual(self.kinds(run(text)), [("slip_lanes", 5)])

    def test_ranking_links_and_counts(self):
        text = "".join(FAR) + way(1, [1, 2], highway="tertiary") + way(2, [2, 3], highway="motorway")
        report = run(text)
        self.assertEqual([i["way_id"] for i in report["items"]], [2, 1])
        item = report["items"][0]
        self.assertEqual(item["osm_url"], "https://www.openstreetmap.org/way/2")
        self.assertEqual(item["id_editor_url"], "https://www.openstreetmap.org/edit?editor=id&way=2")
        self.assertEqual(report["counts"], {"total": 2, "priority": 0, "turn_lanes": 0, "maxspeed": 2, "slip_lanes": 0})

    def test_owner_route_priority_ranks_first(self):
        text = "".join(FAR) + "".join(NEAR) + way(1, [1, 2], highway="motorway") \
            + way(2, [11, 12, 13], highway="primary", ref="A34")
        report = run(text)
        first = report["items"][0]
        self.assertEqual(first["way_id"], 2)
        self.assertTrue(first["priority"])
        self.assertIn("A34 Cheadle/Gatley", first["near_owner_routes"])
        self.assertEqual(report["counts"]["priority"], 1)

    def test_sk8_point_buffer(self):
        lat, lon = gap.SK8_2EZ
        text = node(1, lat + 0.001, lon) + node(2, lat + 0.002, lon) + node(3, lat + 0.02, lon) + node(4, lat + 0.021, lon) \
            + way(1, [1, 2], highway="secondary") + way(2, [3, 4], highway="secondary")
        flags = {i["way_id"]: i["priority"] for i in run(text)["items"]}
        self.assertEqual(flags, {1: True, 2: False})

    def test_cli_writes_outputs_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = pathlib.Path(tmp)
            (t / "a.opl").write_text("".join(FAR) + way(1, [1, 2], highway="primary"))
            code = gap.main(["--opl", str(t / "a.opl"), "--json", str(t / "r.json"),
                             "--markdown", str(t / "r.md"), "--summary", str(t / "s.md")])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((t / "r.json").read_text())["counts"]["maxspeed"], 1)
            self.assertIn("iD", (t / "r.md").read_text())
            self.assertIn("OSM gaps", (t / "s.md").read_text())


if __name__ == "__main__":
    unittest.main()
