"""Deterministic route connectivity diagnostics without downloading UK data."""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from routing_connectivity import crow_km, check_route, evaluate


class FakeActor:
    def __init__(self, ratio=1.2, broken=False):
        self.ratio = ratio
        self.broken = broken

    def route(self, request):
        points = json.loads(request)["locations"]
        a, b = [(v["lat"], v["lon"]) for v in points]
        if self.broken:
            raise ValueError("No suitable route")
        return json.dumps({"trip": {"summary": {"length": crow_km(a, b) * self.ratio}}})


class ConnectivityTests(unittest.TestCase):
    def test_diagnostics_pass_with_plausible_length(self):
        cases = {"UK test": ((53.4, -2.2), (53.7, -1.8))}
        report = evaluate(FakeActor(), cases)
        self.assertEqual((1, 1, 0),
                         (report["checked"], report["route_found"], report["investigate"]))

    def test_missing_graph_route_is_reported_not_invented(self):
        case = check_route(FakeActor(broken=True), "Test", (53.4, -2.2), (53.7, -1.8))
        self.assertEqual("investigate", case["status"])
        self.assertIn("No suitable route", case["reason"])

    def test_implausible_shortcut_rejected(self):
        case = check_route(FakeActor(ratio=0.2), "Test", (53.4, -2.2), (53.7, -1.8))
        self.assertEqual("investigate", case["status"])

    def test_long_detour_flagged(self):
        case = check_route(FakeActor(ratio=6.0), "Test", (53.4, -2.2), (53.7, -1.8))
        self.assertEqual("investigate", case["status"])


if __name__ == "__main__":
    unittest.main()
