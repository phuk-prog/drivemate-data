"""Synthetic desktop experiment; does not measure Android, GPS or UK coverage."""
import argparse
import gzip
import hashlib
import json
import platform
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

from search_index import build, search


def legacy(path, query):
    found = []
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            if line.startswith('#'):
                continue
            fields = line.rstrip('\n').split('\t')
            key = fields[0]
            if key < query:
                continue
            if not key.startswith(query):
                break
            found.append((key, fields[1], fields[2], fields[3], float(fields[4]), float(fields[5]),
                          'postcode_area' if fields[1] == 'P' else 'named_feature'))
            if len(found) == 400:
                break
    return found


def measure(callback, repeats):
    times = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = callback()
        times.append((time.perf_counter_ns() - start) / 1_000_000)
    return result, {'median_ms': statistics.median(times), 'max_ms': max(times), 'samples_ms': times}


def benchmark(count, repeats):
    if not 1000 <= count <= 5_000_000 or not 1 <= repeats <= 50:
        raise ValueError('Benchmark bounds exceeded')
    with tempfile.TemporaryDirectory(prefix='drivemate-synthetic-benchmark-') as directory:
        path = Path(directory) / 'synthetic.tsv.gz'
        database = Path(directory) / 'synthetic.sqlite'
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            stream.write('#drivemate-search-offline\t1\t2026-10-09\tSynthetic benchmark; no real locations\n')
            for i in range(count):
                stream.write(f'place{i:07d}\tT\tSynthetic Place {i}\tSynthetic Area\t0\t0\n')
        start = time.perf_counter()
        indexed = build(path, database)
        build_seconds = time.perf_counter() - start
        queries = ['place0000000', f'place{count // 2:07d}', f'place{count - 1:07d}', 'zzzz', 'place']
        cases = []
        with sqlite3.connect(database) as connection:
            for query in queries:
                old, old_time = measure(lambda: legacy(path, query), repeats)
                new, new_time = measure(lambda: search(connection, query), repeats)
                if old != new:
                    raise AssertionError('Benchmark correctness mismatch')
                cases.append({'query': query, 'candidate_count': len(new), 'equivalent': True,
                              'gzip_scan': old_time, 'sqlite_index': new_time})
        return {'scope': 'synthetic desktop candidate retrieval; not Android application timing',
                'fixture': 'generated names at (0,0); no driving traces or UK data',
                'fixture_sha256': hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest(),
                'rows': indexed, 'repeats': repeats, 'python': platform.python_version(),
                'platform': platform.platform(), 'sqlite': sqlite3.sqlite_version,
                'build_seconds': build_seconds, 'gzip_bytes': path.stat().st_size,
                'sqlite_bytes': database.stat().st_size, 'queries': cases,
                'unmeasured': ['Android latency', 'memory', 'battery', 'cold disk cache',
                               'destination ranking', 'actual UK data coverage']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=250_000)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.rows, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'queries'}))
    for case in report['queries']:
        print(case['query'], 'gzip median ms', round(case['gzip_scan']['median_ms'], 3),
              'sqlite median ms', round(case['sqlite_index']['median_ms'], 3), 'equivalent', case['equivalent'])


if __name__ == '__main__':
    main()
