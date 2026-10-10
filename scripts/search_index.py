"""Experimental indexed alternative to the legacy offline search TSV.

Builds OS Open Names records only. A matching postcode/name is not an exact
property or vehicle entrance. Not wired into publication or the Android app.
"""
import argparse
from datetime import date
import gzip
import math
import os
from pathlib import Path
import sqlite3
import tempfile

SCHEMA = 1
MAX_LINE_BYTES = 16_384
MAX_ROWS = 10_000_000
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
QUERY = ('SELECT key, kind, name, area, lat, lon, precision FROM places '
         'WHERE key >= ? AND key < ? ORDER BY key, id LIMIT ?')


def read_header(stream):
    header = stream.readline(MAX_LINE_BYTES + 1)
    fields = header.decode('utf-8').rstrip('\n').split('\t')
    if (len(header) > MAX_LINE_BYTES or not header.endswith(b'\n') or len(fields) != 4
            or fields[:2] != ['#drivemate-search-offline', '1'] or not fields[3]):
        raise ValueError('Unsupported source header')
    date.fromisoformat(fields[2])
    return fields[2], fields[3], len(header)


def rows(path):
    previous = ''
    with gzip.open(path, 'rb') as stream:
        _, _, consumed = read_header(stream)
        count = 0
        while line := stream.readline(MAX_LINE_BYTES + 1):
            consumed += len(line)
            if consumed > MAX_SOURCE_BYTES:
                raise ValueError('Search source exceeds decompression limit')
            if len(line) > MAX_LINE_BYTES or not line.endswith(b'\n'):
                raise ValueError('Oversized or unterminated search row')
            fields = line.decode('utf-8').rstrip('\n').split('\t')
            if len(fields) != 6:
                raise ValueError('Invalid search row')
            key, kind, name, area, latitude, longitude = fields
            if not key or key < previous or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789 ' for c in key):
                raise ValueError('Invalid or unsorted search key')
            if len(kind) != 1 or kind not in 'PCTNRSVHOBAFMEU' or (not name and kind != 'P'):
                raise ValueError('Invalid place type or name')
            if kind == 'P':
                if ' ' in key or len(key) < 5:
                    raise ValueError('Invalid postcode key')
                name = key[:-3].upper() + ' ' + key[-3:].upper()
            lat, lon = float(latitude), float(longitude)
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError('Invalid search coordinates')
            count += 1
            if count > MAX_ROWS:
                raise ValueError('Too many search rows')
            previous = key
            precision = 'postcode_area' if kind == 'P' else 'named_feature'
            yield key, kind, name, area, lat, lon, precision
        if not count:
            raise ValueError('Empty search input')


def build(source, destination):
    """Validate the whole gzip including CRC before atomically replacing output."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.search-index-', suffix='.sqlite', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    connection = None
    try:
        with gzip.open(source, 'rb') as stream:
            built_at, attribution, _ = read_header(stream)
        connection = sqlite3.connect(temporary)
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute(f'PRAGMA user_version={SCHEMA}')
        connection.execute('CREATE TABLE places (id INTEGER PRIMARY KEY, key TEXT NOT NULL COLLATE BINARY, '
                           'kind TEXT NOT NULL, name TEXT NOT NULL, area TEXT NOT NULL, '
                           'lat REAL NOT NULL, lon REAL NOT NULL, precision TEXT NOT NULL)')
        connection.executemany('INSERT INTO places (key,kind,name,area,lat,lon,precision) VALUES (?,?,?,?,?,?,?)', rows(source))
        connection.execute('CREATE INDEX places_key ON places(key, id)')
        connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.executemany('INSERT INTO metadata VALUES (?,?)', [
            ('format', 'OS Open Names legacy TSV v1'), ('source_build_date', built_at),
            ('attribution', attribution),
            ('property_coverage', 'not provided'), ('entrance_coverage', 'not provided'),
            ('scope', 'Great Britain; not whole UK'),
        ])
        count = connection.execute('SELECT count(*) FROM places').fetchone()[0]
        connection.commit()
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Search index integrity check failed')
        connection.close()
        connection = None
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return count
    finally:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + '-journal').unlink(missing_ok=True)


def search(connection, key, limit=400):
    if not key or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789 ' for c in key):
        return []
    if not 1 <= limit <= 400:
        raise ValueError('Invalid search limit')
    # ASCII keys only: '{' sorts after every permitted suffix, including 'z'.
    return connection.execute(QUERY, (key, key + '{', limit)).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(f'Indexed {build(args.source, args.destination)} records; property entrances are unknown')


if __name__ == '__main__':
    main()
