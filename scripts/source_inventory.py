"""Fingerprints observed source files for reproducible map builds.

This records selected input files, NOT feature-level provenance or a legal
permission decision. Planetiler ancillary downloads remain out of scope.
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


def build(osm, osm_url, others):
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
    return {"schema": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Observed source files; not per-feature provenance",
            "sources": out,
            "limitations": [
                "Declared licences do not establish legal permission to redistribute every derived feature.",
                "Planetiler ancillary downloads and per-feature source lineage are not inventoried.",
                "Presence does not prove that the source was actually incorporated or covers all UK regions."]}


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
    return doc


def read(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 131072:
        raise ValueError("Inventory missing or too large")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("osm", "osm-url", "overture", "os-names", "mapillary-arrows", "mapillary-signs", "out", "validate"):
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
        doc = validate(build(a.osm, a.osm_url, sources))
        path = Path(a.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("Recorded map source files: " + ", ".join(
            f"{s['id']}={s['present']}" for s in doc["sources"]))


if __name__ == "__main__":
    main()
