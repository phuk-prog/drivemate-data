"""Deterministic route connectivity diagnostics without downloading UK data."""
import json
import pathlib
import sys
import unittest
import hashlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from routing_connectivity import crow_km, check_route, evaluate, evaluate_file


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

    def test_diagnostic_proof_names_exact_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'graph.tar'
            path.write_bytes(b'synthetic graph')
            report = evaluate_file(path, lambda _: evaluate(FakeActor()))
            self.assertEqual(report['graph_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(report['graph_bytes'], path.stat().st_size)

    def test_rejects_graph_changed_during_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'graph.tar'
            path.write_bytes(b'before')
            def changed(graph):
                graph.write_bytes(b'after!')  # same length; byte hashing still catches replacement
                return evaluate(FakeActor())
            with self.assertRaises(ValueError):
                evaluate_file(path, changed)

    def test_missing_graph_never_runs_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'missing.tar'
            called = []
            with self.assertRaises(ValueError):
                evaluate_file(path, lambda _: called.append(True))
            self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
