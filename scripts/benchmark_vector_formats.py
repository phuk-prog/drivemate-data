"""Compare PMTiles/MBTiles with one small, identical OSM road-only profile.

Requires Java 21, verified Planetiler 0.10.1, pmtiles==3.8.1 and the recorded
Geofabrik Isle of Wight PBF. Does not establish full basemap correctness,
whole-UK build capacity, Android rendering or Tilemaker performance.
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
import multiprocessing
from pathlib import Path
import resource
import sqlite3
import statistics
import subprocess
import time

JAR_SHA = '5e5e7d8c4fc89b4573cc9109d0a543c3c2c798b2bcde7c3dcd2214031ee59c29'
INPUT_SHA = 'de5be3939f6b52b9919eb05b7537ca58544bd9f3852d0f60ea9ba3d462fb52a9'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(256 * 1024):
            result.update(block)
    return result.hexdigest()


def build(command, directory, log, queue):
    # Fresh worker per invocation: child RSS belongs to this Java process only.
    started = time.perf_counter()
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT)
    queue.put({'command': command, 'exit_code': result.returncode,
               'elapsed_seconds': time.perf_counter() - started,
               'peak_rss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss})


def inventory(path):
    result = {}
    if path.suffix == '.mbtiles':
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as connection:
            tiles = list(connection.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'))
        iterator = (((z, x, (1 << z) - 1 - y), data) for z, x, y, data in tiles)
    else:
        from pmtiles.reader import MmapSource, all_tiles
        with path.open('rb') as stream:
            iterator = list(all_tiles(MmapSource(stream)))
    for coordinate, data in iterator:
        raw = gzip.decompress(data) if data.startswith(b'\x1f\x8b') else data
        if not raw or coordinate in result:
            raise ValueError('Empty or duplicate tile')
        result[coordinate] = hashlib.sha256(raw).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', required=True)
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--osm', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 2 <= args.repeats <= 10 or importlib.metadata.version('pmtiles') != '3.8.1':
        raise ValueError('Use 2..10 repetitions and pmtiles 3.8.1')
    jar, osm, work = args.jar.resolve(), args.osm.resolve(), args.work.resolve()
    if digest(jar) != JAR_SHA or digest(osm) != INPUT_SHA:
        raise ValueError('Pinned jar or benchmark input checksum mismatch')
    profile = Path(__file__).with_name('benchmark-road-profile.yml').resolve()
    work.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'road-only regional archive-format comparison', 'planetiler': '0.10.1',
              'jar_sha256': JAR_SHA, 'input_sha256': INPUT_SHA, 'profile_sha256': digest(profile),
              'java': subprocess.check_output([args.java, '-version'], stderr=subprocess.STDOUT, text=True),
              'formats': {'pmtiles': {'runs': []}, 'mbtiles': {'runs': []}}}
    for iteration in range(args.repeats):
        # Alternate order to reduce systematic OS-cache/order bias.
        formats = ('pmtiles', 'mbtiles') if iteration % 2 == 0 else ('mbtiles', 'pmtiles')
        for format_name in formats:
            archive = work / ('roads.' + format_name)
            command = [args.java, '-Xmx2g', '-jar', str(jar), str(profile),
                       '--osm-path=' + str(osm), '--output=' + str(archive),
                       '--threads=2', '--maxzoom=14', '--force']
            queue = multiprocessing.Queue()
            worker = multiprocessing.Process(target=build, args=(command, work,
                work / f'{format_name}-{iteration}.log', queue))
            worker.start()
            row = queue.get(timeout=300)
            worker.join(timeout=10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
                raise ValueError('Benchmark worker did not finish')
            report['formats'][format_name]['runs'].append(row)
            if row['exit_code']:
                raise ValueError('Archive build failed; inspect recorded log')
            print(format_name, iteration + 1, row['elapsed_seconds'], flush=True)
    inventories = {}
    for format_name, rows in report['formats'].items():
        archive = work / ('roads.' + format_name)
        rows['median_build_seconds'] = statistics.median(row['elapsed_seconds'] for row in rows['runs'])
        rows['archive_bytes'] = archive.stat().st_size
        rows['archive_sha256'] = digest(archive)
        inventories[format_name] = inventory(archive)
        rows['tiles'] = len(inventories[format_name])
    report['same_tile_coordinates_and_payloads'] = (
        bool(inventories['pmtiles']) and inventories['pmtiles'] == inventories['mbtiles'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('Identical decompressed tile inventories:', report['same_tile_coordinates_and_payloads'])


if __name__ == '__main__':
    main()
