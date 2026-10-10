"""Exit classification uses only tagged data."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lane_coverage import classify, summarise  # noqa: E402


def ways(before, after, slip, arrows=False):
    t_before = {"highway": "motorway", "ref": "M60"}
    if before is not None:
        t_before["lanes"] = str(before)
    if arrows:
        t_before["turn:lanes"] = "left|through|through"
    t_after = {"highway": "motorway", **({"lanes": str(after)} if after is not None else {})}
    t_slip = {"highway": "motorway_link", **({"lanes": str(slip)} if slip is not None else {})}
    return {1: (t_before, [10, 11]), 2: (t_after, [11, 12]), 3: (t_slip, [11, 13])}


class LaneCoverageTests(unittest.TestCase):
    def status(self, *args, **kw):
        return classify(ways(*args, **kw))[0]["status"]

    def test_statuses(self):
        self.assertEqual("counts_add_up", self.status(4, 3, 1))
        self.assertEqual("inconsistent", self.status(4, 4, 1))
        self.assertEqual("missing", self.status(None, 3, 1))
        self.assertEqual("arrows", self.status(4, 4, 1, arrows=True))

    def test_summary_and_non_diverge_ignored(self):
        w = ways(4, 3, 1)
        w[4] = ({"highway": "primary"}, [20, 21])
        s = summarise(classify(w))
        self.assertEqual((1, 1, 100.0), (s["exits"], s["usable_for_lane_guidance"], s["usable_percent"]))


if __name__ == "__main__":
    unittest.main()
