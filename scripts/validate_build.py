#!/usr/bin/env python3
"""Final quality gate for a complete DriveMate UK data build."""
from pathlib import Path
import gzip
import json
import sys
from coverage_audit import audit as audit_coverage
from source_inventory import read as read_source_inventory

out = Path(sys.argv[1])
previous_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
json_out = Path(sys.argv[3]) if len(sys.argv) > 3 else out / "build-quality.json"
md_out = out / "build-quality.md"

def files(pattern):
    return list(out.glob(pattern))

def total_bytes(items):
    return sum(p.stat().st_size for p in items if p.is_file())

def json_items(items, key):
    n = 0
    bad = 0
    for p in items:
        try:
            o = json.loads(p.read_text())
            v = o.get(key, []) if isinstance(o, dict) else o
            n += len(v) if isinstance(v, list) else 0
        except Exception:
            bad += 1
    return n, bad

lane_files = files("lanes/*.json")
limit_files = files("limits/*.json")
road_files = files("roadinfo/*.json")
place_files = files("places/*.json.gz")
lane_ways, bad_lanes = json_items(lane_files, "ways")
limit_ways, bad_limits = json_items(limit_files, "ways")
road_items, bad_road = json_items(road_files, "elements")
regional_coverage = audit_coverage(out)

def count_json(path):
    try:
        o = json.loads(path.read_text())
        if isinstance(o, list): return len(o)
        for k in ("elements", "features", "cameras", "zones"):
            if isinstance(o.get(k), list): return len(o[k])
    except Exception:
        pass
    return 0

metrics = {
    "map_bytes": (out / "drivemate.pmtiles").stat().st_size if (out / "drivemate.pmtiles").exists() else 0,
    "lane_files": len(lane_files),
    "lane_ways": lane_ways,
    "limit_files": len(limit_files),
    "limit_ways": limit_ways,
    "roadinfo_files": len(road_files),
    "roadinfo_items": road_items,
    "place_files": len(place_files),
    "place_bytes": total_bytes(place_files),
    "camera_items": count_json(out / "cameras-uk.json"),
    "zone_items": count_json(out / "charge-zones-uk.json"),
    "offline_search_bytes": (out / "search-offline-uk.tsv.gz").stat().st_size if (out / "search-offline-uk.tsv.gz").exists() else 0,
}
errors = list(regional_coverage["errors"])
warnings = list(regional_coverage["warnings"])
try:
    source_inventory = read_source_inventory(out / "source-inventory.json")
    for item in source_inventory["sources"]:
        if not item["present"]:
            warnings.append(f"Optional source not available: {item['id']}")
    warnings.append("Licence declarations require separate legal review; file fingerprints alone do not prove reuse rights.")
except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
    errors.append(f"Source inventory invalid or missing: {exc}")

for name, bad in (("lane files", bad_lanes), ("limit files", bad_limits), ("road-info files", bad_road)):
    if bad:
        errors.append(f"{bad} damaged/unreadable {name}")

minimums = {
    "map_bytes": 50_000_000,
    "lane_files": 80,
    "lane_ways": 5_000,
    "limit_files": 80,
    "limit_ways": 5_000,
    "roadinfo_files": 80,
    "roadinfo_items": 500,
    "place_files": 150,
    "place_bytes": 5_000_000,
    "camera_items": 100,
    "offline_search_bytes": 1_000_000,
}
for key, minimum in minimums.items():
    if metrics[key] < minimum:
        errors.append(f"{key} is unexpectedly small: {metrics[key]:,} < {minimum:,}")

previous = {}
if previous_path and previous_path.exists():
    try:
        previous = json.loads(previous_path.read_text()).get("metrics", {})
    except Exception as e:
        warnings.append(f"previous quality file unreadable: {e}")

stable = ("map_bytes","lane_files","lane_ways","limit_files","limit_ways","roadinfo_files","roadinfo_items","place_files","place_bytes","camera_items","offline_search_bytes")
for key in stable:
    old = previous.get(key)
    new = metrics[key]
    if isinstance(old, (int, float)) and old > 0:
        ratio = new / old
        if ratio < 0.60:
            errors.append(f"{key} dropped {100*(1-ratio):.0f}% from last published build ({old:,} -> {new:,})")
        elif ratio < 0.80:
            warnings.append(f"{key} dropped {100*(1-ratio):.0f}% ({old:,} -> {new:,})")
        elif ratio > 3.0:
            warnings.append(f"{key} grew to {ratio:.1f}x last build ({old:,} -> {new:,})")

report = {
    "version": 1,
    "metrics": metrics,
    "nation_tile_probes": regional_coverage,
    "errors": errors,
    "warnings": warnings,
}
json_out.write_text(json.dumps(report, indent=2) + "\n")

lines = ["## DriveMate weekly data quality", "", "| Metric | This build | Previous |", "|---|---:|---:|"]
for k, v in metrics.items():
    lines.append(f"| {k} | {v:,} | {previous.get(k, '—') if previous.get(k) is not None else '—'} |")
lines += ["", "### Four-nation data presence (city-centre probes only; not completeness)",
          "", "| Nation | Lanes | Limits | Road information | Places |", "|---|---|---|---|---|"]
for nation, probe in regional_coverage["probes"].items():
    flags = ["yes" if probe["layers"][layer]["populated"] else "MISSING"
             for layer in ("lanes", "limits", "roadinfo", "places")]
    lines.append(f"| {nation} | " + " | ".join(flags) + " |")
if warnings:
    lines += ["", "### Warnings"] + [f"- ⚠️ {x}" for x in warnings]
if errors:
    lines += ["", "### Blocking problems"] + [f"- ❌ {x}" for x in errors]
else:
    lines += ["", "✅ Whole-build data quality gate passed."]
md_out.write_text("\n".join(lines) + "\n")
print(md_out.read_text())
if errors:
    raise SystemExit(1)
