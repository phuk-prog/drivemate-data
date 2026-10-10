"""Fingerprints observed source files for reproducible map builds.

This records input files, NOT feature-level provenance or a legal permission
decision. Known Planetiler ancillary downloads can also be fingerprinted.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

SOURCES = {
    "osm_uk": ("OpenStreetMap", "ODbL-1.0", "© OpenStreetMap contributors", True),
    "overture_places": ("Overture places", "varies by feature/source", "Overture Maps and upstream contributors", False),
    "os_open_names": ("OS Open Names", "OGL-v3; third-party rights apply", "OS, Royal Mail and National Statistics", False),
    "mapillary_arrows": ("Mapillary-derived observations", "Mapillary derivative-data terms: review required", "Mapillary contributors", False),
    "mapillary_signs": ("Mapillary-derived observations", "Mapillary derivative-data terms: review required", "Mapillary contributors", False),
}

# URLs are those selected by the pinned Planetiler 0.10.1 executable/profile.
PLANETILER_SOURCES = {
    'lake_centerline.shp.zip': ('OSM lake centre lines',
        'https://github.com/acalcutt/osm-lakelines/releases/download/v12/lake_centerline.shp.zip',
        'OSM-derived data; software MIT licence is not data clearance', True),
    'water-polygons-split-3857.zip': ('OSM water polygons',
        'https://osmdata.openstreetmap.de/download/water-polygons-split-3857.zip',
        'ODbL-1.0', True),
    'natural_earth_vector.sqlite.zip': ('Natural Earth',
        'https://naciscdn.org/naturalearth/packages/natural_earth_vector.sqlite.zip',
        'Public domain declaration', True),
    'wikidata_names.json': ('Wikidata name translations',
        'https://www.wikidata.org/', 'CC0 structured data; query/version not captured', False),
}


def planetiler_inventory(directory):
    rows = []
    for filename, (label, url, licence, required) in PLANETILER_SOURCES.items():
        meta = fingerprint(Path(directory) / filename)
        if required and meta is None:
            raise ValueError('Required Planetiler source missing: ' + filename)
        rows.append({'file': filename, 'label': label, 'origin_url': url,
                     'declared_licence': licence, 'required': required,
                     'present': meta is not None,
                     'bytes': meta['bytes'] if meta else None,
                     'sha256': meta['sha256'] if meta else None,
                     'rights_review': 'not_independently_verified'})
    return rows


def fingerprint(filename):
    if filename is None:
        return None
    path = Path(filename)
    if not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_size <= 0:
        raise ValueError("Source input is empty")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": sha.hexdigest()}


def build(osm, osm_url, others, planetiler_sources=None):
    if not isinstance(osm_url, str) or not osm_url.startswith("https://download.geofabrik.de/") or not osm_url.endswith(".osm.pbf"):
        raise ValueError("Unrecognised OSM source URL")
    if set(others) != (set(SOURCES) - {"osm_uk"}):
        raise ValueError("Incorrect source registry")
    out = []
    for sid, (label, licence, attribution, required) in SOURCES.items():
        meta = fingerprint(osm if required else others[sid])
        if required and meta is None:
            raise ValueError("Required OSM input missing")
        out.append({
            "id": sid, "label": label, "declared_licence": licence,
            "attribution": attribution, "required": required, "present": meta is not None,
            "bytes": meta["bytes"] if meta else None,
            "sha256": meta["sha256"] if meta else None,
            "origin_url": osm_url if required else None,
            "rights_review": "not_independently_verified",
        })
    document = {"schema": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Observed source files; not per-feature provenance",
            "sources": out,
            "limitations": [
                "Declared licences do not establish legal permission to redistribute every derived feature.",
                "Known Planetiler ancillary inputs are recorded only when a source directory is supplied; per-feature lineage and redirects are not captured.",
                "Presence does not prove that the source was actually incorporated or covers all UK regions."]}
    if planetiler_sources is not None:
        document['planetiler_ancillary'] = planetiler_inventory(planetiler_sources)
    return document


def validate(doc):
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise ValueError("Unsupported source inventory schema")
    try:
        date = datetime.fromisoformat(doc["generated_utc"])
        if date.tzinfo is None:
            raise ValueError("Timestamp requires timezone")
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Invalid inventory timestamp") from exc
    if not isinstance(doc.get("scope"), str) or not doc["scope"]:
        raise ValueError("Missing inventory scope")
    if not isinstance(doc.get("limitations"), list) or len(doc["limitations"]) < 3:
        raise ValueError("Inventory limitations not recorded")
    entries = doc.get("sources")
    if not isinstance(entries, list) or len(entries) != len(SOURCES):
        raise ValueError("Source list incomplete")
    seen = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("Malformed source entry")
        sid = row.get("id")
        if sid in seen or sid not in SOURCES:
            raise ValueError("Duplicate or unexpected source")
        seen.add(sid)
        label, licence, attr, required = SOURCES[sid]
        if (row.get("label"), row.get("declared_licence"), row.get("attribution"),
            row.get("required"), row.get("rights_review")) != (label, licence, attr, required, "not_independently_verified"):
            raise ValueError("Source licence/identity declarations changed")
        present = row.get("present")
        if type(present) is not bool:
            raise ValueError("Source presence invalid")
        if required and not present:
            raise ValueError("Required OSM source not present")
        if present:
            if (type(row.get("bytes")) is not int or row["bytes"] <= 0
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch("[0-9a-f]{64}", row["sha256"])):
                raise ValueError("Source fingerprint invalid")
        elif row.get("bytes") is not None or row.get("sha256") is not None:
            raise ValueError("Absent source has fingerprint")
        url = row.get("origin_url")
        if required:
            if not isinstance(url, str) or not url.startswith("https://download.geofabrik.de/") or not url.endswith(".osm.pbf"):
                raise ValueError("Required source URL invalid")
        elif url is not None:
            raise ValueError("Unverified optional source URL")
    if 'planetiler_ancillary' in doc:
        rows = doc['planetiler_ancillary']
        if not isinstance(rows, list) or len(rows) != len(PLANETILER_SOURCES):
            raise ValueError('Incomplete Planetiler ancillary inventory')
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid Planetiler source entry')
            filename = row.get('file')
            if filename not in PLANETILER_SOURCES or filename in seen:
                raise ValueError('Duplicate or unknown Planetiler source')
            seen.add(filename)
            label, url, licence, required = PLANETILER_SOURCES[filename]
            if (row.get('label'), row.get('origin_url'), row.get('declared_licence'),
                row.get('required'), row.get('rights_review')) != (
                    label, url, licence, required, 'not_independently_verified'):
                raise ValueError('Planetiler source declarations changed')
            if type(row.get('present')) is not bool or (required and not row['present']):
                raise ValueError('Required Planetiler source absent')
            if row['present']:
                if (type(row.get('bytes')) is not int or row['bytes'] <= 0
                    or not isinstance(row.get('sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
                    raise ValueError('Invalid Planetiler source fingerprint')
            elif row.get('bytes') is not None or row.get('sha256') is not None:
                raise ValueError('Absent Planetiler source has fingerprint')
    return doc


def read(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 131072:
        raise ValueError("Inventory missing or too large")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("osm", "osm-url", "overture", "os-names", "mapillary-arrows", "mapillary-signs", "planetiler-sources", "out", "validate"):
        p.add_argument("--" + flag)
    a = p.parse_args()
    if a.validate:
        read(a.validate)
        print("Source inventory validated (not proof of legal clearance)")
    else:
        if not a.osm or not a.osm_url or not a.out:
            p.error("--osm, --osm-url and --out required")
        sources = {
            "overture_places": a.overture,
            "os_open_names": a.os_names,
            "mapillary_arrows": a.mapillary_arrows,
            "mapillary_signs": a.mapillary_signs,
        }
        doc = validate(build(a.osm, a.osm_url, sources, a.planetiler_sources))
        path = Path(a.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("Recorded map source files: " + ", ".join(
            f"{s['id']}={s['present']}" for s in doc["sources"]))


if __name__ == "__main__":
    main()
