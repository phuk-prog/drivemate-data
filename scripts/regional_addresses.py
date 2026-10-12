"""Optional OSM regional property-search index. Unpublished; no verified postal/entrance claim.

Uses portable SQLite B-tree indices and FTS4, without FTS5 or a new Android dependency.
The existing five-field places packages remain unchanged.
"""
import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from address_geometry import clean, mapped_coordinate
from search_acceptance import key
from source_inventory import fingerprint

SCHEMA = 1
NOTICE = '© OpenStreetMap contributors. Database under ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/'
LIMITATIONS = ['OSM mapped addresses are incomplete and not authoritative postal verification.',
               'Outline-average coordinates are approximate building locations, not verified vehicle entrances.',
               'Entrance tags are observations; access and routable connections remain unverified.',
               'No UPRN, restricted NI postcode source, proprietary address data or inferred street was used.',
               'Relations and address interpolation are not expanded; mapped number expressions remain unexpanded.']


def record(feature):
    identity = feature.get('id')
    if not isinstance(identity, str) or not re.fullmatch(r'(node|way)/[1-9][0-9]{0,17}', identity):
        raise ValueError('Missing stable OSM identity')
    tags = feature.get('properties') or {}
    number, name = clean(tags.get('addr:housenumber')), clean(tags.get('addr:housename'))
    street = clean(tags.get('addr:street'))
    place = clean(tags.get('addr:place'))
    if not (number or name) or not (street or place):
        return None
    lon, lat, precision = mapped_coordinate(feature.get('geometry') or {})
    if (type(lat) not in (int, float) or type(lon) not in (int, float) or
            not math.isfinite(lat) or not math.isfinite(lon) or
            not 49 <= lat <= 61.5 or not -9.5 <= lon <= 3):
        raise ValueError('Invalid UK-envelope address coordinates')
    retained = {k: clean(v) for k, v in tags.items() if k.startswith('addr:') and clean(v)}
    if any(len(k) > 128 or len(v) > 2048 for k, v in retained.items()):
        raise ValueError('Oversized address field')
    locality = next((clean(tags.get(k)) for k in ('addr:city', 'addr:town', 'addr:village', 'addr:suburb', 'addr:hamlet')
                     if clean(tags.get(k))), '')
    postcode = clean(tags.get('addr:postcode'))
    display = ' '.join(x for x in (number or name, street or place) if x)
    typ, ident = identity.split('/')
    return {'osm_type': typ, 'osm_id': int(ident), 'search_key': key(display),
            'postcode_key': re.sub('[^A-Z0-9]', '', postcode.upper()),
            'display': display, 'house_number': number, 'house_name': name,
            'street': street, 'place': place, 'unit': clean(tags.get('addr:unit')),
            'locality': locality, 'postcode': postcode, 'lat': lat, 'lon': lon,
            'coordinate_kind': precision, 'entrance_tag': clean(tags.get('entrance')),
            'full_postal_address_verified': False, 'entrance_verified': False,
            'address_fields': retained}


def word_text(item):
    return key(' '.join((item['display'], item['house_name'], item['unit'],
                         item['locality'], item['postcode'])))


def build(features, destination, source):
    """Validate complete input and SQLite before same-directory atomic replacement."""
    if (not isinstance(source, dict) or source.get('licence') != 'ODbL-1.0' or
            not re.fullmatch('[0-9a-f]{64}', source.get('sha256', ''))):
        raise ValueError('Missing OSM source identity or licence')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError('Unsafe output database')
    descriptor, name = tempfile.mkstemp(prefix='.addresses-', suffix='.sqlite', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    counts = {'seen': 0, 'records': 0, 'missing_fields': 0, 'invalid_features': 0}
    try:
        with sqlite3.connect(temporary) as db:
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE addresses (osm_type TEXT NOT NULL, osm_id INTEGER NOT NULL, '
                       'search_key TEXT NOT NULL, postcode_key TEXT NOT NULL, record_json TEXT NOT NULL, '
                       'PRIMARY KEY (osm_type, osm_id))')
            db.execute('CREATE VIRTUAL TABLE address_words USING fts4(search_text, tokenize=unicode61)')
            for feature in features:
                counts['seen'] += 1
                if counts['seen'] > 2_000_000:
                    raise ValueError('Regional address input exceeds row limit')
                try:
                    item = record(feature)
                except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, AttributeError):
                    counts['invalid_features'] += 1
                    continue
                if item is None:
                    counts['missing_fields'] += 1
                    continue
                # Duplicate OSM identities are an input error; never silently choose a version.
                db.execute('INSERT INTO addresses VALUES (?,?,?,?,?)',
                           (item['osm_type'], item['osm_id'], item['search_key'], item['postcode_key'],
                            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':'))))
                db.execute('INSERT INTO address_words(rowid,search_text) VALUES (?,?)',
                           (db.execute('SELECT last_insert_rowid()').fetchone()[0],
                            word_text(item)))
                counts['records'] += 1
            if not counts['records']:
                raise ValueError('No usable regional addresses')
            db.execute('CREATE INDEX address_prefix ON addresses(search_key)')
            db.execute('CREATE INDEX address_postcode ON addresses(postcode_key)')
            manifest = {'schema': SCHEMA, 'format': 'drivemate-osm-addresses', 'source': source,
                        'counts': counts, 'notice': NOTICE, 'limitations': LIMITATIONS,
                        'status': 'experimental_unpublished', 'full_postal_address_verified': False,
                        'entrance_verified': False, 'query_engine': 'SQLite B-tree and FTS4 unicode61; no FTS5'}
            db.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(manifest, sort_keys=True)))
            db.execute('PRAGMA user_version=1')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity failure')
        validate(temporary)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return dict(manifest, package=fingerprint(destination))
    finally:
        temporary.unlink(missing_ok=True)


def validate(path):
    """Fully inspect a candidate index; never mark postal/entrance facts verified."""
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA:
            raise ValueError('Unsupported regional address schema')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Corrupt regional address index')
        manifest = json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if (manifest.get('schema') != SCHEMA or manifest.get('notice') != NOTICE or
                manifest.get('full_postal_address_verified') is not False or
                manifest.get('entrance_verified') is not False):
            raise ValueError('Invalid regional address metadata')
        if (manifest.get('source', {}).get('licence') != 'ODbL-1.0' or
                not re.fullmatch('[0-9a-f]{64}', manifest.get('source', {}).get('sha256', ''))):
            raise ValueError('Missing OSM source provenance')
        count = 0
        for identity, osm_id, prefix, code, payload in db.execute(
                'SELECT osm_type,osm_id,search_key,postcode_key,record_json FROM addresses'):
            item = json.loads(payload)
            regenerated = record({'id': f'{identity}/{osm_id}', 'properties': item['address_fields'],
                                  'geometry': {'type': 'Point', 'coordinates': [item['lon'], item['lat']]}})
            if (regenerated is None or prefix != regenerated['search_key'] or
                    code != regenerated['postcode_key'] or item['osm_id'] != osm_id or
                    item['osm_type'] != identity or item['coordinate_kind'] not in ('mapped_node', 'outline_average') or
                    item.get('full_postal_address_verified') is not False or item.get('entrance_verified') is not False):
                raise ValueError('Invalid regional address record')
            if any(item.get(field) != value for field, value in regenerated.items()
                   if field not in ('coordinate_kind', 'entrance_tag')):
                raise ValueError('Address payload differs from source fields')
            if clean(item.get('entrance_tag')) != item.get('entrance_tag'):
                raise ValueError('Invalid entrance observation tag')
            count += 1
        if (not count or count != manifest['counts']['records'] or manifest['counts']['seen'] !=
                sum(manifest['counts'][name] for name in ('records', 'missing_fields', 'invalid_features'))):
            raise ValueError('Address count mismatch')
        for payload, indexed_text in db.execute('SELECT a.record_json,f.search_text FROM addresses a '
                                               'JOIN address_words f ON a.rowid=f.rowid'):
            item = json.loads(payload)
            if indexed_text != word_text(item):
                raise ValueError('Address word index mismatch')
        words = db.execute('SELECT COUNT(*) FROM address_words').fetchone()[0]
        if words != count or db.execute('SELECT COUNT(*) FROM addresses a LEFT JOIN address_words f '
                                        'ON a.rowid=f.rowid WHERE f.rowid IS NULL').fetchone()[0]:
            raise ValueError('Missing address word index')
    return {'records': count, 'manifest': manifest, 'package': fingerprint(path)}


def search(path, query, limit=12):
    if not 1 <= limit <= 100:
        raise ValueError('Invalid result limit')
    if not isinstance(query, str) or len(query) > 256:
        raise ValueError('Invalid query')
    q = key(query)
    if not q:
        return []
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA:
            raise ValueError('Unsupported regional address schema')
        code = re.sub('[^A-Z0-9]', '', query.upper())
        if re.fullmatch(r'(GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2})', code):
            rows = db.execute('SELECT record_json FROM addresses WHERE postcode_key=? '
                              'ORDER BY search_key,osm_type,osm_id LIMIT ?', (code, limit))
        elif q.isdigit():
            rows = []
        else:
            rows = db.execute('SELECT record_json FROM addresses WHERE search_key>=? AND search_key<? '
                              'ORDER BY search_key,osm_type,osm_id LIMIT ?', (q, q + '\uffff', limit))
        results = [json.loads(row[0]) for row in rows]
        if not results and not re.fullmatch(r'(GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2})', code):
            # Numeric house/unit terms are exact; prefixing 12 would also match 123.
            expression = ' AND '.join(token if token.isdigit() else token + '*' for token in q.split())
            rows = db.execute('SELECT a.record_json FROM addresses a JOIN address_words f ON a.rowid=f.rowid '
                              'WHERE address_words MATCH ? ORDER BY a.search_key,a.osm_type,a.osm_id LIMIT ?',
                              (expression, limit))
            results = [json.loads(row[0]) for row in rows]
        return results


def pbf_features(path, target):
    """Write bounded GeoJSON sequence from public OSM nodes and closed ways only."""
    import osmium
    if importlib.metadata.version('osmium') != '4.2.0':
        raise ValueError('PBF export requires osmium==4.2.0')
    stats = {'nodes': 0, 'ways': 0, 'unsupported_or_incomplete_geometry': 0}
    with target.open('w', encoding='utf-8') as out:
        class Handler(osmium.SimpleHandler):
            def emit(self, obj, typ, geometry):
                feature = {'type': 'Feature', 'id': f'{typ}/{obj.id}', 'properties': dict(obj.tags),
                           'geometry': geometry}
                out.write(json.dumps(feature, ensure_ascii=False) + '\n')
                stats['nodes' if typ == 'node' else 'ways'] += 1

            def node(self, obj):
                if 'addr:housenumber' not in obj.tags and 'addr:housename' not in obj.tags:
                    return
                if obj.location.valid():
                    self.emit(obj, 'node', {'type': 'Point', 'coordinates': [obj.location.lon, obj.location.lat]})
                else:
                    stats['unsupported_or_incomplete_geometry'] += 1

            def way(self, obj):
                if 'addr:housenumber' not in obj.tags and 'addr:housename' not in obj.tags:
                    return
                if obj.is_closed() and all(node.location.valid() for node in obj.nodes):
                    coordinates = [[node.location.lon, node.location.lat] for node in obj.nodes]
                    self.emit(obj, 'way', {'type': 'Polygon', 'coordinates': [coordinates]})
                else:
                    stats['unsupported_or_incomplete_geometry'] += 1
        Handler().apply_file(str(path), locations=True)
    return stats


def json_features(path):
    with Path(path).open(encoding='utf-8') as source:
        for line in source:
            if len(line.encode('utf-8')) > 1_000_000:
                raise ValueError('Oversized address input line')
            if line.strip():
                yield json.loads(line.strip().lstrip('\x1e'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pbf', type=Path, required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not args.source_url.startswith('https://download.geofabrik.de/') or not args.source_url.endswith('.osm.pbf'):
        raise ValueError('Unsupported public OSM extract URL')
    identity = fingerprint(args.pbf)
    if identity is None:
        raise ValueError('Missing PBF source')
    import osmium
    with osmium.io.Reader(str(args.pbf)) as reader:
        header = reader.header()
        source = dict(identity, url=args.source_url, licence='ODbL-1.0',
                      snapshot_utc=header.get('osmosis_replication_timestamp'),
                      declared_extract_bbox=str(header.box()))
    with tempfile.TemporaryDirectory(prefix='drivemate-addresses-') as directory:
        exported = Path(directory) / 'addresses.geojsonseq'
        source['export_counts'] = pbf_features(args.pbf, exported)
        if fingerprint(args.pbf) != identity:
            raise ValueError('PBF source changed during export')
        report = build(json_features(exported), args.out, source)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
