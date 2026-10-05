"""Builds DriveMate's own list of businesses, places and streets by merging the best open
sources into one, without duplicates:

  - Overture Maps (businesses from Meta, Microsoft, Amazon, TomTom and others)
  - OpenStreetMap (shops, pubs, fuel, parking… anything Overture lacks)
  - Ordnance Survey Open Names (every official street and place name in Great Britain)

When two sources have the same place (same name within ~80 m) one entry is kept, with the
fullest address. Output is split into quarter-degree squares (about 28 x 17 km), gzipped:
  places-<floor(lat*4)>_<floor(lon*4)>.json.gz  →  [[name, category, address, lat, lon], ...]

Usage: places.py out_dir [--overture places.parquet] [--osm pois.geojsonseq] [--osnames dir]
"""
import argparse
import csv
import glob
import gzip
import json
import math
import os
import re
import struct

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--overture")
ap.add_argument("--osm")
ap.add_argument("--osnames")
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

squares = {}  # (row, col) -> list of [name, cat, addr, lat, lon]
counts = {}


def norm(name):
    return re.sub(r"[^a-z0-9&]", "", name.lower())


def add(source, name, cat, addr, lat, lon):
    if not name or lat is None or lon is None:
        return
    key = (math.floor(lat * 4), math.floor(lon * 4))
    squares.setdefault(key, []).append([name, cat or "", addr or "", round(lat, 6), round(lon, 6), source])
    counts[source] = counts.get(source, 0) + 1


# ---------- Overture ----------
def wkb_point(wkb):
    if wkb is None or len(wkb) < 21:
        return None
    order = "<" if wkb[0] == 1 else ">"
    if struct.unpack(order + "I", wkb[1:5])[0] & 0xFF != 1:
        return None
    return struct.unpack(order + "dd", wkb[5:21])


if args.overture and os.path.exists(args.overture):
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(args.overture)
    cols = [c for c in ("names", "categories", "addresses", "confidence", "geometry", "brand") if c in pf.schema_arrow.names]
    for batch in pf.iter_batches(columns=cols, batch_size=50_000):
        for r in batch.to_pylist():
            if (r.get("confidence") or 1) < 0.4:
                continue
            name = (r.get("names") or {}).get("primary")
            pt = wkb_point(r.get("geometry"))
            if not name or not pt:
                continue
            cat = ((r.get("categories") or {}).get("primary") or "").replace("_", " ")
            brand = (((r.get("brand") or {}).get("names") or {}) or {}).get("primary") or ""
            if brand and brand.lower() not in name.lower():
                cat = f"{cat} {brand}".strip()
            a = (r.get("addresses") or [None])[0] or {}
            addr = ", ".join(x for x in (a.get("freeform"), a.get("locality"), a.get("postcode")) if x)
            add("overture", name, cat, addr, pt[1], pt[0])

# ---------- OpenStreetMap points of interest ----------
POI_KEYS = ["amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "railway", "aeroway", "public_transport"]
if args.osm and os.path.exists(args.osm):
    with open(args.osm, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            p = feat.get("properties", {})
            name = p.get("name") or p.get("brand")
            if not name:
                continue
            g = feat.get("geometry") or {}
            coords = g.get("coordinates")
            if g.get("type") == "Point":
                lon, lat = coords
            else:
                # Middle of the outline (good enough to drive to).
                ring = coords[0][0] if g.get("type") == "MultiPolygon" else coords[0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
            kind = next((f"{k} {p[k]}".replace("_", " ") for k in POI_KEYS if k in p), "")
            addr = ", ".join(x for x in (
                " ".join(x for x in (p.get("addr:housenumber"), p.get("addr:street")) if x),
                p.get("addr:city"), p.get("addr:postcode")) if x)
            add("osm", name, kind, addr, lat, lon)

# ---------- Ordnance Survey Open Names (streets and places) ----------
if args.osnames and os.path.isdir(args.osnames):
    from pyproj import Transformer

    to_wgs = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    KEEP = {"Named Road", "Section Of Named Road", "City", "Town", "Village", "Hamlet", "Suburban Area", "Other Settlement"}
    # Column positions come from the header file shipped with the data (defaults as documented).
    col = {"NAME1": 2, "LOCAL_TYPE": 7, "GEOMETRY_X": 8, "GEOMETRY_Y": 9, "POSTCODE_DISTRICT": 16,
           "POPULATED_PLACE": 18, "DISTRICT_BOROUGH": 21}
    headers = [p for p in glob.glob(os.path.join(args.osnames, "**", "*.csv"), recursive=True) if "header" in p.lower()]
    if headers:
        with open(headers[0], encoding="utf-8", errors="replace") as f:
            names = next(csv.reader(f))
        col.update({n.strip(): i for i, n in enumerate(names) if n.strip() in col})
    width = max(col.values()) + 1
    for path in glob.glob(os.path.join(args.osnames, "**", "*.csv"), recursive=True):
        if "header" in path.lower():
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                if len(row) < width or row[col["LOCAL_TYPE"]] not in KEEP:
                    continue
                try:
                    lon, lat = to_wgs.transform(float(row[col["GEOMETRY_X"]]), float(row[col["GEOMETRY_Y"]]))
                except ValueError:
                    continue
                town, borough = row[col["POPULATED_PLACE"]], row[col["DISTRICT_BOROUGH"]]
                area = ", ".join(x for x in (town, borough if borough != town else "", row[col["POSTCODE_DISTRICT"]]) if x)
                kind = "street" if "Road" in row[col["LOCAL_TYPE"]] else row[col["LOCAL_TYPE"]].lower()
                add("osnames", row[col["NAME1"]], kind, area, lat, lon)

# ---------- Merge duplicates and write ----------
total = 0
for (row, col), items in squares.items():
    # Same name within ~80 m = the same place: keep the one with the fullest address.
    items.sort(key=lambda x: -len(x[2]))
    kept = []
    seen = {}
    for it in items:
        n = norm(it[0])
        cell = (round(it[3] * 1400), round(it[4] * 900))  # ~80 m cells
        dup = False
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (n, cell[0] + dy, cell[1] + dx) in seen:
                    dup = True
        if dup:
            # Keep the extra category words (e.g. "wholesale") for search.
            other = seen.get((n, cell[0], cell[1]))
            if other is not None and it[1] and it[1] not in other[1]:
                other[1] = (other[1] + " " + it[1]).strip()[:80]
            continue
        seen[(n, cell[0], cell[1])] = it
        kept.append(it[:5])
    total += len(kept)
    with gzip.open(os.path.join(args.out, f"places-{row}_{col}.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(kept, f, separators=(",", ":"))

stats = {"sources": counts, "merged": total, "squares": len(squares)}
print(json.dumps(stats))
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as s:
        s.write(f"Places: {total:,} after merging ({', '.join(f'{k} {v:,}' for k, v in counts.items())}) in {len(squares)} squares\n\n")
