"""Read-only verification of every PMTiles v3/MVT payload, not geographical truth.

Requires pmtiles==3.4.1 and mapbox-vector-tile==2.2.0. No publication occurs.
"""
import argparse
import hashlib
import json
import importlib.metadata
import importlib.util
import math
from pathlib import Path
import zlib


def verify(path, uk_samples=False):
    from pmtiles.reader import Reader
    from pmtiles.tile import Compression, TileType, deserialize_directory
    from mapbox_vector_tile.Mapbox.vector_tile_pb2 import tile as Tile

    for name, version in (('pmtiles', '3.4.1'), ('mapbox-vector-tile', '2.2.0')):
        if importlib.metadata.version(name) != version:
            raise ValueError('Verifier requires ' + name + '==' + version)

    def bounded_gzip(data, limit):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        decoded = decoder.decompress(data, limit + 1)
        if len(decoded) > limit or not decoder.eof or decoder.unused_data:
            raise ValueError('Oversized, truncated or concatenated gzip payload')
        return decoded

    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size < 127:
        raise ValueError('Missing or unsafe PMTiles archive')
    size = path.stat().st_size
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    report = {'scope': 'Complete archive structure, gzip and MVT format; not road or address ground truth',
              'sha256': digest.hexdigest(), 'bytes': size, 'errors': [],
              'tools': {'pmtiles': '3.4.1', 'mapbox-vector-tile': '2.2.0'}}
    # Own the mapping lifetime; the library's MmapSource wrapper has no close API.
    import mmap
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
        def check_range(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise ValueError('Archive reference outside file')

        def get(offset, length):
            check_range(offset, length)
            return mapping[offset:offset + length]

        reader = Reader(get)
        header = reader.header()
        if (header['internal_compression'] != Compression.GZIP or
            header['tile_compression'] != Compression.GZIP or header['tile_type'] != TileType.MVT):
            raise ValueError('Unsupported map compression or tile type')
        for section in ('root', 'metadata', 'leaf_directory', 'tile_data'):
            check_range(header[section + '_offset'], header[section + '_length'])
        bounded_gzip(get(header['metadata_offset'], header['metadata_length']), 16 * 1024**2)
        reader.metadata()
        if uk_samples:
            spec = importlib.util.spec_from_file_location('coverage_audit', Path(__file__).with_name('coverage_audit.py'))
            coverage = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(coverage)
            samples = {}
            if header['max_zoom'] < 14:
                raise ValueError('Detailed UK map requires zoom 14')
            for nation, core in coverage.NATION_PROBES.items():
                samples[nation] = []
                for city, lat, lon in (core, *coverage.REGIONAL_PROBES[nation]):
                    x = int((lon + 180) / 360 * 2**14)
                    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**14)
                    payload = reader.get(14, x, y)
                    if payload is None:
                        raise ValueError('Missing detailed map tile near ' + city)
                    tile = Tile()
                    tile.ParseFromString(bounded_gzip(payload, 64 * 1024**2))
                    counts = {layer.name: len(layer.features) for layer in tile.layers}
                    if not counts.get('transportation'):
                        raise ValueError('Missing transportation layer near ' + city)
                    samples[nation].append({'city': city, 'zxy': [14, x, y], 'layer_features': counts})
            report['uk_samples'] = samples
        directories, contents = set(), set()
        entries = addressed = features = 0
        previous_end = -1

        def walk(offset, length, depth=0):
            if depth > 3:
                raise ValueError('Archive directory nesting exceeds reader compatibility')
            if (offset, length) in directories:
                raise ValueError('Repeated or cyclic directory reference')
            directories.add((offset, length))
            if len(directories) > 100_000:
                raise ValueError('Too many archive directories')
            raw = get(offset, length)
            bounded_gzip(raw, 16 * 1024**2)
            rows = deserialize_directory(raw)
            for entry in rows:
                if entry.run_length == 0:
                    if entry.offset + entry.length > header['leaf_directory_length']:
                        raise ValueError('Leaf reference outside directory section')
                    yield from walk(header['leaf_directory_offset'] + entry.offset, entry.length, depth + 1)
                else:
                    yield entry

        for entry in walk(header['root_offset'], header['root_length']):
            if entry.tile_id <= previous_end:
                raise ValueError('Overlapping or unsorted tile addresses')
            previous_end = entry.tile_id + entry.run_length - 1
            entries += 1
            addressed += entry.run_length
            if entry.length <= 0 or entry.offset + entry.length > header['tile_data_length']:
                raise ValueError('Tile reference outside payload section')
            identity = (entry.offset, entry.length)
            if identity in contents:
                continue
            contents.add(identity)
            data = bounded_gzip(get(header['tile_data_offset'] + entry.offset, entry.length), 64 * 1024**2)
            tile = Tile()
            tile.ParseFromString(data)
            if len({layer.name for layer in tile.layers}) != len(tile.layers):
                raise ValueError('Duplicate MVT layer name')
            for layer in tile.layers:
                if not layer.name or layer.extent <= 0 or layer.version not in (1, 2):
                    raise ValueError('Invalid MVT layer declaration')
                features += len(layer.features)
                for feature in layer.features:
                    if (len(feature.tags) % 2 or
                        any(i >= len(layer.keys) for i in feature.tags[::2]) or
                        any(i >= len(layer.values) for i in feature.tags[1::2])):
                        raise ValueError('Invalid MVT property indices')
        if (entries != header['tile_entries_count'] or addressed != header['addressed_tiles_count'] or
            len(contents) != header['tile_contents_count']):
            raise ValueError('Archive counts differ from directory inventory')
    report.update({'addressed_tiles_checked': addressed, 'physical_contents_checked': len(contents),
                   'tile_entries_checked': entries, 'directory_blocks_checked': len(directories),
                   'features_in_physical_contents': features})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--uk-samples', action='store_true', help='Require road layers at 23 UK city samples')
    args = parser.parse_args()
    try:
        report = verify(args.archive, args.uk_samples)
    except Exception as error:
        report = {'scope': 'Complete archive format validation failed',
                  'errors': [type(error).__name__ + ': ' + str(error)[:240]]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
