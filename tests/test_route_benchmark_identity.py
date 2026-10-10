import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('route_benchmark',
    Path(__file__).resolve().parents[1] / 'scripts/benchmark_offline_routes.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkIdentityTest(unittest.TestCase):
    def test_default_remains_the_integrity_pinned_bundled_graph(self):
        identity = benchmark.graph_identity()
        self.assertEqual(identity['sha256'], benchmark.GRAPH_SHA256)
        self.assertEqual(identity['bytes'], 99_502_080)

    def test_explicit_large_graph_preserves_its_published_identity(self):
        document = {'engine': 'valhalla-3.6.3', 'sha256': 'a' * 64, 'bytes': 2_800_936_960}
        self.assertEqual(benchmark.graph_identity(document), document)

    def test_bad_identity_never_weakens_unpacked_bounds(self):
        good = {'engine': 'valhalla-3.6.3', 'sha256': 'a' * 64, 'bytes': 100}
        for key, value in [('engine', 'unknown'), ('sha256', 'bad'), ('bytes', 0),
                           ('bytes', 100.1), ('bytes', True), ('bytes', 65 * 1024**3)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                benchmark.graph_identity({**good, key: value})
