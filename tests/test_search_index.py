import gzip
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('search_index', Path(__file__).resolve().parents[1] / 'scripts/search_index.py')
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


class SearchIndexTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'search.tsv.gz'
        self.destination = Path(self.directory.name) / 'search.sqlite'

    def write(self, body):
        with gzip.open(self.source, 'wt') as stream:
            stream.write('#drivemate-search-offline\t1\t2026-10-09\tOS Open Names\n' + body)

    def test_prefix_exact_postcode_and_approximate_precision(self):
        self.write('alpha\tT\tAlpha\tArea\t53.4\t-2.1\n'
                   'alpha road\tR\tAlpha Road\tArea\t53.4\t-2.1\n'
                   'sk82ez\tP\t\tArea\t53.4\t-2.1\n')
        self.assertEqual(3, index.build(self.source, self.destination))
        with sqlite3.connect(self.destination) as connection:
            self.assertEqual(['alpha', 'alpha road'], [r[0] for r in index.search(connection, 'alpha')])
            self.assertEqual('postcode_area', index.search(connection, 'sk82ez')[0][-1])
            self.assertEqual('SK8 2EZ', index.search(connection, 'sk82ez')[0][2])
            self.assertEqual([], index.search(connection, 'zzzz'))
            self.assertEqual('not provided', connection.execute("SELECT value FROM metadata WHERE key='entrance_coverage'").fetchone()[0])
            plan = connection.execute('EXPLAIN QUERY PLAN ' + index.QUERY, ('alpha', 'alpha{', 400)).fetchall()
            self.assertTrue(any('SEARCH places USING INDEX places_key' in row[-1] for row in plan))

    def test_bad_rows_preserve_previous_database(self):
        self.write('alpha\tT\tAlpha\tArea\t53.4\t-2.1\n')
        index.build(self.source, self.destination)
        old = self.destination.read_bytes()
        for body in ('', 'alpha\tT\tAlpha\tArea\tnan\t-2.1\n',
                     'alpha\tT\tAlpha\tArea\t91\t-2.1\n',
                     'zeta\tT\tZeta\tArea\t53\t-2\nalpha\tT\tAlpha\tArea\t53\t-2\n',
                     'a' * 17000 + '\n', 'alpha\tT\tAlpha\tArea\t53\t-2'):
            self.write(body)
            with self.assertRaises(ValueError):
                index.build(self.source, self.destination)
            self.assertEqual(old, self.destination.read_bytes())
            self.assertEqual([], list(self.destination.parent.glob('.search-index-*')))

    def test_corrupt_or_truncated_gzip_never_replaces_previous(self):
        self.write('alpha\tT\tAlpha\tArea\t53.4\t-2.1\n')
        index.build(self.source, self.destination)
        old = self.destination.read_bytes()
        compressed = self.source.read_bytes()
        for damaged in (compressed[:-5], compressed[:-8] + b'\0' * 8):
            self.source.write_bytes(damaged)
            with self.assertRaises((OSError, EOFError)):
                index.build(self.source, self.destination)
            self.assertEqual(old, self.destination.read_bytes())


if __name__ == '__main__':
    unittest.main()
