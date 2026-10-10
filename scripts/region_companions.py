"""Companion data squares that a regional map download needs for offline use.

A regional PMTiles package only holds map pictures. Offline navigation in that
area also needs the lane, speed-limit and road-information squares
(half-degree, ``<floor(lat*2)>_<floor(lon*2)>``) and the places squares
(quarter-degree, ``<floor(lat*4)>_<floor(lon*4)>``) that overlap it, plus the
small nationwide files. These grids are distinct from Web Mercator z8 tiles,
so each package lists every square its bounds overlap; a square on a seam is
listed by both neighbours. Squares are never invented: when the release
inventory is supplied, names absent from it are dropped (an area with no
lanes simply has no lane square).
"""
import math

HALF_DEGREE_LAYERS = ("lanes", "limits", "roadinfo")
QUARTER_DEGREE_LAYERS = ("places",)
NATIONAL_FILES = ("cameras-uk.json", "charge-zones-uk.json", "search-offline-uk.tsv.gz")
# Above this many squares a single package's bounds are implausible for a
# z8 (or smaller) area at UK latitudes; refuse rather than list half a globe.
MAX_SQUARES_PER_LAYER = 64


def squares_for_bounds(bounds, scale):
    """(row, col) squares with positive-area overlap of [west, south, east, north]."""
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError("Bounds must be [west, south, east, north]")
    west, south, east, north = bounds
    for v in bounds:
        if type(v) not in (int, float) or not math.isfinite(v):
            raise ValueError("Non-finite bounds")
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Empty or out-of-range bounds")
    # Half-open: a bound lying exactly on a grid line does not pull in the
    # neighbouring square, which has no area inside this package.
    rows = range(math.floor(south * scale), math.ceil(north * scale))
    cols = range(math.floor(west * scale), math.ceil(east * scale))
    if len(rows) * len(cols) > MAX_SQUARES_PER_LAYER:
        raise ValueError("Package bounds cover too many data squares")
    return [(r, c) for r in rows for c in cols]


def companion_names(bounds, available=None):
    """Per-layer file names for one package, filtered to ``available`` if given."""
    result = {}
    for layers, scale, suffix in ((HALF_DEGREE_LAYERS, 2, ".json"),
                                  (QUARTER_DEGREE_LAYERS, 4, ".json.gz")):
        squares = squares_for_bounds(bounds, scale)
        for layer in layers:
            names = [f"{layer}-{r}_{c}{suffix}" for r, c in squares]
            if available is not None:
                names = [n for n in names if n in available]
            result[layer] = sorted(names)
    return result


def annotate(inventory, available=None):
    """Add ``companions`` to every detail package and ``national_files`` once.

    ``available`` is an optional set of asset names from the release manifest.
    Returns a new dict; the input inventory is unchanged.
    """
    if not isinstance(inventory, dict) or not isinstance(inventory.get("packages"), dict):
        raise ValueError("Regional inventory has no packages")
    if available is not None:
        available = set(available)
    out = dict(inventory)
    packages = {}
    for name, info in inventory["packages"].items():
        info = dict(info)
        if name != "base":
            if info.get("bounds") is None:
                raise ValueError(f"Detail package without bounds: {name}")
            info["companions"] = companion_names(info["bounds"], available)
        packages[name] = info
    out["packages"] = packages
    out["national_files"] = [n for n in NATIONAL_FILES if available is None or n in available]
    out["companion_grids"] = {
        "half_degree": {"layers": list(HALF_DEGREE_LAYERS), "key": "floor(lat*2)_floor(lon*2)"},
        "quarter_degree": {"layers": list(QUARTER_DEGREE_LAYERS), "key": "floor(lat*4)_floor(lon*4)"},
        "filtered_to_release_inventory": available is not None,
    }
    return out
