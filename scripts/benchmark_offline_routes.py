"""Desktop Valhalla baseline using DriveMate's existing Manchester graph.

Public landmark endpoints are synthetic test inputs, not recorded driving traces.
Requires pyvalhalla==3.6.3. This does not validate Android JNI, legal ground truth,
lane correctness, battery usage or navigation guidance.
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import statistics
import tempfile
import time

GRAPH_SHA256 = '7f26427538706de8f9918c33ca1846aef6269699f144bab08dcc6c514c5e039b'
CASES = {
    'manchester_to_stockport': [(53.4808, -2.2426), (53.4106, -2.1575)],
    'stockport_to_manchester': [(53.4106, -2.1575), (53.4808, -2.2426)],
    'airport_to_manchester': [(53.365, -2.272), (53.4808, -2.2426)],
    'bolton_to_stockport': [(53.578, -2.429), (53.4106, -2.1575)],
}


def benchmark(tilepack, repeats):
    import valhalla
    if importlib.metadata.version('pyvalhalla') != '3.6.3':
        raise ValueError('Benchmark requires pyvalhalla 3.6.3')
    if not 3 <= repeats <= 100:
        raise ValueError('Use 3..100 repeats')
    report = {'scope': 'desktop native offline routing, not Android or legal correctness',
              'python': platform.python_version(), 'platform': platform.platform(),
              'pyvalhalla': '3.6.3', 'graph_sha256': GRAPH_SHA256, 'cases': {}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        graph = root / 'tiles.tar'
        sha = hashlib.sha256()
        size = 0
        started = time.perf_counter()
        with gzip.open(tilepack, 'rb') as source, graph.open('wb') as destination:
            while block := source.read(256 * 1024):
                size += len(block)
                if size > 512 * 1024 * 1024:
                    raise ValueError('Graph exceeds app decompression bound')
                sha.update(block)
                destination.write(block)
        if sha.hexdigest() != GRAPH_SHA256:
            raise ValueError('Graph checksum mismatch')
        report['unpack_verify_ms'] = 1000 * (time.perf_counter() - started)
        report['graph_bytes'] = size
        empty = root / 'empty'
        empty.mkdir()
        started = time.perf_counter()
        actor = valhalla.Actor(valhalla.get_config(tile_extract=graph, tile_dir=empty))
        report['actor_init_ms'] = 1000 * (time.perf_counter() - started)
        for name, points in CASES.items():
            request = {'locations': [{'lat': lat, 'lon': lon} for lat, lon in points],
                       'costing': 'auto', 'units': 'kilometers'}
            timings = []
            summaries = []
            for _ in range(repeats):
                started = time.perf_counter()
                response = actor.route(request)
                timings.append(1000 * (time.perf_counter() - started))
                if isinstance(response, str):
                    response = json.loads(response)
                trip = response['trip']
                summary = trip['summary']
                if summary['length'] <= 0 or summary['time'] <= 0 or not trip['legs']:
                    raise ValueError('No usable route')
                summaries.append((summary['length'], summary['time']))
            if len(set(summaries)) != 1:
                raise ValueError('Identical requests produced inconsistent summary')
            report['cases'][name] = {'request': request, 'first_ms': timings[0],
                                    'warm_median_ms': statistics.median(timings[1:]),
                                    'all_ms': timings, 'length_km': summaries[0][0],
                                    'duration_seconds': summaries[0][1]}
        report['process_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tilepack', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    report = benchmark(args.tilepack, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({name: row['warm_median_ms'] for name, row in report['cases'].items()}))


if __name__ == '__main__':
    main()
