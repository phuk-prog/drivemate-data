"""Sample regional data coverage and validate *every* compressed places tile.

Coverage probes are regression tripwires, not proof of comprehensive UK data,
routability, individual addresses, or accuracy of legal road restrictions.
"""
import gzip
import json
import math
from pathlib import Path
import re

# Strong existing checks for one central city per UK nation.
NATION_PROBES = {
    "England": ("Manchester", 53.4808, -2.2426),
    "Scotland": ("Glasgow", 55.8642, -4.2518),
    "Wales": ("Cardiff", 51.4816, -3.1791),
    "Northern Ireland": ("Belfast", 54.5973, -5.9301),
}

# Wider sample of populated centres, including geographical extremes and
# different urban densities. Only places are required at *every* additional
# sample: mapped lane tags, speed limits and road furniture are genuinely
# optional and their absence should trigger a warning, not fabricated data.
REGIONAL_PROBES = {
    "England": (
        ("London", 51.5074, -0.1278),
        ("Birmingham", 52.4862, -1.8904),
        ("Bristol", 51.4545, -2.5879),
        ("Newcastle", 54.9783, -1.6178),
        ("Plymouth", 50.3755, -4.1427),
        ("Norwich", 52.6309, 1.2974),
    ),
    "Scotland": (
        ("Edinburgh", 55.9533, -3.1883),
        ("Aberdeen", 57.1497, -2.0943),
        ("Inverness", 57.4778, -4.2247),
        ("Dundee", 56.4620, -2.9707),
        ("Dumfries", 55.0709, -3.6051),
    ),
    "Wales": (
        ("Swansea", 51.6214, -3.9436),
        ("Wrexham", 53.0461, -2.9925),
        ("Bangor", 53.2274, -4.1293),
        ("Aberystwyth", 52.4140, -4.0829),
    ),
    "Northern Ireland": (
        ("Derry/Londonderry", 54.9970, -7.3190),
        ("Newry", 54.1766, -6.3390),
        ("Omagh", 54.5970, -7.3090),
        ("Enniskillen", 54.3445, -7.6375),
    ),
}

LAYER_SPECS = {
    "lanes": (2, "ways", ".json"),
    "limits": (2, "ways", ".json"),
    "roadinfo": (2, "elements", ".json"),
    "places": (4, None, ".json.gz"),
}
PLACE_PATTERN = re.compile(r"^places-(-?\d+)_(-?\d+)\.json\.gz$")


def _check_places(records, filename):
    if not isinstance(records, list):
        raise ValueError("Places root must be a list")
    match = PLACE_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError("Invalid places tile filename")
    tile_row, tile_col = map(int, match.groups())
    for index, record in enumerate(records):
        if not isinstance(record, list) or len(record) != 5:
            raise ValueError(f"Place {index}: expected [name,category,address,lat,lon]")
        name, category, address, lat, lon = record
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Place {index}: missing name")
        if not isinstance(category, str) or not isinstance(address, str):
            raise ValueError(f"Place {index}: invalid category or address")
        if (type(lat) not in (float, int) or type(lon) not in (float, int)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not 49 <= lat <= 61.5 or not -9.5 <= lon <= 3):
            raise ValueError(f"Place {index}: invalid/out-of-UK coordinates")
        # Generator rounds to six decimals after choosing its quarter-degree
        # tile, so allow a small epsilon at boundaries.
        if (not tile_row / 4 - 0.000001 <= lat < (tile_row + 1) / 4 + 0.000001
            or not tile_col / 4 - 0.000001 <= lon < (tile_col + 1) / 4 + 0.000001):
            raise ValueError(f"Place {index}: coordinate outside declared tile")


def _inspect(path, layer, cache):
    path = Path(path)
    if path in cache:
        return cache[path]
    result = {"tile": path.name, "present": path.is_file(), "populated": False, "records": 0}
    if result["present"]:
        try:
            if not path.is_file() or path.is_symlink():
                raise ValueError("Tile is not a regular file")
            opener = gzip.open if layer == "places" else open
            with opener(path, "rt", encoding="utf-8") as stream:
                data = json.load(stream)  # consumes gzip stream; CRC checked
            if layer == "places":
                _check_places(data, path.name)
                entries = data
            else:
                field = LAYER_SPECS[layer][1]
                entries = data.get(field) if isinstance(data, dict) else None
                if not isinstance(entries, list):
                    raise ValueError(f"Missing '{field}' array")
            result["records"] = len(entries)
            result["populated"] = bool(entries)
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
            result["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    cache[path] = result
    return result


def _tile(out, layer, lat, lon, cache):
    scale, _, suffix = LAYER_SPECS[layer]
    path = out / layer / f"{layer}-{math.floor(lat * scale)}_{math.floor(lon * scale)}{suffix}"
    return _inspect(path, layer, cache)


def audit(out):
    """Inspect 23 populated sample centres, plus ALL places tile archives."""
    out = Path(out)
    cache = {}
    errors, warnings = [], []
    core = {}
    expanded = {}
    for nation, (city, lat, lon) in NATION_PROBES.items():
        layers = {layer: _tile(out, layer, lat, lon, cache) for layer in LAYER_SPECS}
        core[nation] = {"city": city, "layers": layers}
        for layer, result in layers.items():
            if not result["populated"]:
                errors.append(f"Missing, empty or invalid {layer} near {city}, {nation}: {result['tile']}")

    for nation, cities in REGIONAL_PROBES.items():
        expanded[nation] = []
        for city, lat, lon in cities:
            layers = {layer: _tile(out, layer, lat, lon, cache) for layer in LAYER_SPECS}
            expanded[nation].append({"city": city, "layers": layers})
            if not layers["places"]["populated"]:
                errors.append(f"Missing, empty or invalid places near {city}, {nation}: {layers['places']['tile']}")
            for layer in ("lanes", "limits", "roadinfo"):
                if not layers[layer]["populated"]:
                    warnings.append(
                        f"No verified {layer} records in sampled tile near {city}, {nation}: "
                        f"{layers[layer]['tile']} (not proof of a data error)")

    place_dir = out / "places"
    archives = sorted(place_dir.glob("*.json.gz")) if place_dir.is_dir() else []
    valid_records, invalid = 0, 0
    for path in archives:
        item = _inspect(path, "places", cache)
        if not item["populated"]:
            invalid += 1
            reason = item.get("error", "archive contains no records")
            errors.append(f"Invalid or empty places archive {path.name}: {reason}")
        else:
            valid_records += item["records"]
    if not archives:
        errors.append("No places archives found")

    warnings.append(
        "OS Open Names postcode/street search covers Great Britain, not Northern Ireland; "
        "presence of Northern Ireland places is not individual-address coverage.")
    return {
        "method": "23 sampled populated centres and full places-archive integrity scan; NOT nationwide geographic coverage",
        "probes": core,
        "regional_probes": expanded,
        "place_archive_audit": {
            "files_checked": len(archives), "records_checked": valid_records,
            "invalid_or_empty": invalid,
        },
        "errors": errors,
        "warnings": warnings,
    }
