"""Conservative geographic tile assignment for complete polyline segments.

Each segment is assigned to EVERY tile that its geometry touches, including
intermediate squares containing no vertices. Features on a tile edge are
present in adjacent squares. Does not infer new roads or legal connections.
"""
import math


def _bins(coordinate):
    nearby = round(coordinate)
    if abs(coordinate - nearby) < 1e-10:
        return (nearby - 1, nearby)
    return (math.floor(coordinate),)


def tiles_for_polyline(points, scale):
    """Return {(floor(lat*scale), floor(lon*scale))} for entire centreline."""
    if type(scale) not in (int, float) or scale <= 0 or not math.isfinite(scale):
        raise ValueError("Invalid tile scale")
    if not isinstance(points, (tuple, list)) or len(points) < 2:
        raise ValueError("Road needs at least two points")
    result = set()
    xy = []
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) < 2:
            raise ValueError("Invalid road point")
        lon, lat = point[:2]
        if (type(lon) not in (int, float) or type(lat) not in (int, float)
            or not math.isfinite(lon) or not math.isfinite(lat)
            or not (-180 <= lon <= 180 and -90 <= lat <= 90)):
            raise ValueError("Invalid road coordinates")
        xy.append((lon * scale, lat * scale))

    def visit(x, y):
        for row in _bins(y):
            for col in _bins(x):
                result.add((row, col))

    for (ax, ay), (bx, by) in zip(xy, xy[1:]):
        # Fast path for the common case: no grid boundary anywhere nearby.
        if (math.floor(ax) == math.floor(bx)
            and math.floor(ay) == math.floor(by)
            and not (abs(ax - round(ax)) < 1e-10
                     or abs(ay - round(ay)) < 1e-10
                     or abs(bx - round(bx)) < 1e-10
                     or abs(by - round(by)) < 1e-10)):
            result.add((math.floor(ay), math.floor(ax)))
            continue
        ts = {0.0, 1.0}
        for v0, v1 in ((ax, bx), (ay, by)):
            if v0 == v1:
                continue
            for edge in range(math.floor(min(v0, v1)) + 1, math.ceil(max(v0, v1))):
                t = (edge - v0) / (v1 - v0)
                if 0 < t < 1:
                    ts.add(t)
        times = sorted(ts)
        for t in times:
            visit(ax + (bx - ax) * t, ay + (by - ay) * t)
        for start, end in zip(times, times[1:]):
            t = (start + end) / 2
            visit(ax + (bx - ax) * t, ay + (by - ay) * t)
    return result
