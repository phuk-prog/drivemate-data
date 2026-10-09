"""Small, blocking *presence* check for regional DriveMate map layers.

City-centre probes intentionally do not claim geographic completeness, address
coverage or legal road correctness. Those require independent evidence.
"""
import gzip
import json
import math
from pathlib import Path

# Representative populated tiles in each UK nation. This is a regression
# tripwire, not a territorial boundary or representative sample of all roads.
NATION_PROBES = {
    "England": ("Manchester", 53.4808, -2.2426),
    "Scotland": ("Glasgow", 55.8642, -4.2518),
    "Wales": ("Cardiff", 51.4816, -3.1791),
    "Northern Ireland": ("Belfast", 54.5973, -5.9301),
}

LAYER_SPECS = {
    "lanes": (2, "ways", ".json"),
    "limits": (2, "ways", ".json"),
    "roadinfo": (2, "elements", ".json"),
    "places": (4, None, ".json.gz"),
}


def audit(out):
    """Check that populated city tiles exist and contain records in all layers."""
    out = Path(out)
    probes = {}
    errors = []
    for nation, (city, lat, lon) in NATION_PROBES.items():
        probes[nation] = {"city": city, "layers": {}}
        for layer, (scale, field, suffix) in LAYER_SPECS.items():
            row, col = math.floor(lat * scale), math.floor(lon * scale)
            path = out / layer / f"{layer}-{row}_{col}{suffix}"
            result = {"tile": path.name, "present": path.is_file(), "populated": False}
            if path.is_file():
                try:
                    with (gzip.open(path, "rt", encoding="utf-8") if suffix == ".json.gz"
                          else path.open("r", encoding="utf-8")) as stream:
                        data = json.load(stream)
                    entries = data.get(field) if field is not None and isinstance(data, dict) else data
                    result["populated"] = isinstance(entries, list) and len(entries) > 0
                except (OSError, UnicodeError, ValueError, TypeError) as exc:
                    result["error"] = type(exc).__name__
            probes[nation]["layers"][layer] = result
            if not result["populated"]:
                errors.append(f"Missing or empty {layer} data near {city}, {nation}: {path.name}")
    return {
        "method": "Four city-centre tile presence probes; NOT proof of UK geographic or address completeness",
        "probes": probes,
        "errors": errors,
        "warnings": [
            "OS Open Names offline postcode/street search covers Great Britain, not Northern Ireland; "
            "Belfast places data does not establish Northern Ireland address coverage."
        ],
    }
