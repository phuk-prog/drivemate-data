"""Shared existing OSM address geometry approximation; never a verified entrance."""


def clean(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def mapped_coordinate(geometry):
    coordinates = geometry.get('coordinates')
    typ = geometry.get('type')
    if typ == 'Point':
        lon, lat = coordinates
        return lon, lat, 'mapped_node'
    if typ not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Unsupported address geometry')
    ring = coordinates[0][0] if typ == 'MultiPolygon' else coordinates[0]
    lon = sum(c[0] for c in ring) / len(ring)
    lat = sum(c[1] for c in ring) / len(ring)
    return lon, lat, 'outline_average'
