"""Reproduce default/adapted Ferrostar OSRM parser compatibility experiments.

First clone the pinned Ferrostar source and run its locked upstream Rust tests
to populate the Cargo cache. Fixture files remain local; the output contains
hashes, filenames, timings and parser results, not coordinate sequences.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCE_SHA = '4e2d7f647952c0a4060efd584e6edfc6148092b9'


def encode(coordinates):
    previous = [0, 0]
    result = []
    for longitude, latitude in coordinates:
        for axis, value in enumerate((latitude, longitude)):
            current = round(value * 1_000_000)
            delta = current - previous[axis]
            previous[axis] = current
            unsigned = delta << 1 if delta >= 0 else ~(delta << 1)
            while unsigned >= 32:
                result.append(chr(((unsigned & 31) | 32) + 63))
                unsigned >>= 5
            result.append(chr(unsigned + 63))
    return ''.join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ferrostar-repo', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo', default='cargo')
    args = parser.parse_args()
    source, fixtures = args.ferrostar_repo.resolve(), args.fixtures.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if head != SOURCE_SHA or subprocess.check_output(['git', 'status', '--porcelain'], cwd=source):
        raise ValueError('A clean checkout of the pinned Ferrostar source is required')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'src').mkdir()
        adapted = root / 'adapted'
        adapted.mkdir()
        shutil.copyfile(Path(__file__).with_suffix('.rs'), root / 'src/main.rs')
        # JSON string quoting is valid for these TOML basic-string path values.
        manifest = ('[package]\nname="drivemate-ferrostar-compatibility"\nversion="0.1.0"\n'
                    'edition="2024"\npublish=false\n[dependencies]\n'
                    f'ferrostar={{path={json.dumps(str(source / "common/ferrostar"))}}}\n'
                    'serde_json="=1.0.150"\n')
        (root / 'Cargo.toml').write_text(manifest)
        shutil.copyfile(source / 'common/Cargo.lock', root / 'Cargo.lock')
        hashes = {}
        expected_counts = {}
        for path in sorted(fixtures.glob('*.osrm.json')):
            raw = path.read_bytes()
            document = json.loads(raw)
            hashes[path.name] = hashlib.sha256(raw).hexdigest()
            expected_counts[path.name] = len(document['routes'])
            for route in document['routes']:
                route['geometry'] = encode(route['geometry']['coordinates'])
                for leg in route['legs']:
                    for step in leg['steps']:
                        step['geometry'] = encode(step['geometry']['coordinates'])
            (adapted / path.name).write_text(json.dumps(document, separators=(',', ':')))
        if not hashes:
            raise ValueError('No shared OSRM fixtures')
        report = {'scope': 'OSRM parser compatibility, not route-following or Android',
                  'ferrostar_source': SOURCE_SHA, 'input_sha256': hashes,
                  'build_profile': 'unoptimized debug', 'geometry_precision': 6,
                  'cargo': subprocess.check_output([args.cargo, '--version'], text=True).strip()}
        for name, directory in [('default', fixtures), ('polyline6', adapted)]:
            command = [args.cargo, 'run', '--offline', '--manifest-path', str(root / 'Cargo.toml')]
            if name == 'polyline6':
                command.append('--locked')
            result = subprocess.run(command + ['--', str(directory)], check=True, capture_output=True, text=True)
            rows = json.loads(result.stdout)['results']
            report[name] = rows
            if name == 'polyline6' and any(not row['accepted'] or row['routes'] != expected_counts[row['fixture']] for row in rows):
                raise ValueError('Geometry-adapted parser rejected fixtures or changed route counts')
        report['cargo_lock_sha256'] = hashlib.sha256((root / 'Cargo.lock').read_bytes()).hexdigest()
        # Preserve the resolved lock for reproducible dependency versions.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / 'Cargo.lock', args.output.with_suffix('.Cargo.lock'))
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print('Accepted default/adapted:', *(sum(row['accepted'] for row in report[name]) for name in ['default', 'polyline6']))


if __name__ == '__main__':
    main()
