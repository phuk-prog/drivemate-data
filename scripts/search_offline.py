"""Offline postcode and place search for the phone: every postcode in Great Britain, every named
street, and towns, villages, stations, hospitals, schools, airports, ferry ports and services,
each with a point to drive to. Built from Ordnance Survey Open Names (Open Government Licence).
Optionally adds Northern Ireland street and place names from the OSNI Open Data Gazetteers
(Land & Property Services, Open Government Licence) - never NI postcodes.

Usage: search_offline.py osnames_dir search-offline-uk.tsv.gz [--osni-streets FILE] [--osni-places FILE]
       search_offline.py --selftest

  --osni-streets / --osni-places take a CSV or GeoJSON file. Field names are not fixed: a name
  column and either X/Y (Irish Grid EPSG:29902, or Irish Transverse Mercator EPSG:2157), lat/lon
  columns or a GeoJSON geometry are detected; the build stops with a clear error when they are not.

FILE FORMAT (search-offline-uk.tsv.gz) — gzip-compressed UTF-8 text, one record per line ('\\n'):

  line 1 (header):  #drivemate-search-offline <TAB> 1 <TAB> <build date YYYY-MM-DD> <TAB> <credits>
  every other line: key <TAB> type <TAB> name <TAB> area <TAB> lat <TAB> lon

  key   what to match against: the name in lower case, accents removed (ŵ → w), "&" → "and",
        anything that isn't a-z, 0-9 or a space removed, runs of spaces made one.
        Postcodes have no space at all: "sk82ez" for SK8 2EZ.
        Lines are sorted by key (plain byte order), so all names starting with what the driver has
        typed sit together: the phone can stream through and stop once past them, or binary-search
        an unpacked copy.
  type  one letter:
          P postcode           R street / road        C city            T town
          V village            H hamlet               S suburb / area   O other settlement
          N railway station    B bus or coach station A airport / airfield / heliport
          F ferry terminal / harbour                  M hospital / hospice / care home
          E school / college / university             U motorway services
  name  as shown to the driver ("Menai Grove", "Caerdydd"). Welsh and Gaelic names are extra
        lines pointing at the same place. EMPTY for postcodes (to keep the file small): show the
        key in capitals with a space before the last three characters ("sk82ez" → "SK8 2EZ").
  area  where it is, for telling same-named places apart: "Town, Postcode district"
        ("Cheadle, SK8"); the council or county instead of the town when there is no town.
        For postcodes: just the town.
  lat, lon  WGS84 degrees, 4 decimal places (about 10 m). For a postcode: its centre point;
        for a street: a point on the street.

  The same street name in the same area is listed once. Northern Ireland is not in OS Open Names.
  When the OSNI gazetteers are given, NI streets (type R) and towns/villages (C/T/V/H, or O when
  the file does not say which) are added with the same six fields; their area is the town,
  council or "Northern Ireland" (there is no postcode district), and NI postcodes are never
  listed (the ONSPD BT rows may not be redistributed; the app's online search covers them).

Credits (must be shown): Contains OS data © Crown copyright and database rights; Contains Royal
Mail data © Royal Mail copyright and database right; Contains National Statistics data © Crown
copyright and database right (OS Open Names, Open Government Licence v3). When OSNI records are
included, the header also carries: Contains LPS Intellectual Property © Crown copyright and
database right (year) This information is licensed under the terms of the Open Government Licence
"""
import argparse
import csv
import glob
import gzip
import json
import math
import os
import re
import sys
import time
import unicodedata

CREDITS = ("Contains OS data © Crown copyright and database rights; Contains Royal Mail data © Royal Mail "
           "copyright and database right; Contains National Statistics data © Crown copyright and database right "
           "(OS Open Names, Open Government Licence v3)")
TYPES = {
    "Postcode": "P", "Named Road": "R", "Section Of Named Road": "R",
    "City": "C", "Town": "T", "Village": "V", "Hamlet": "H", "Suburban Area": "S", "Other Settlement": "O",
    "Railway Station": "N", "Bus Station": "B", "Coach Station": "B",
    "Airport": "A", "Airfield": "A", "Heliport": "A", "Helicopter Station": "A",
    "Vehicular Ferry Terminal": "F", "Passenger Ferry Terminal": "F", "Vehicular Rail Terminal": "F", "Harbour": "F",
    "Hospital": "M", "Hospice": "M", "Medical Care Accommodation": "M",
    "Primary Education": "E", "Secondary Education": "E", "Special Needs Education": "E",
    "Non State Primary Education": "E", "Non State Secondary Education": "E",
    "Further Education": "E", "Higher or University Education": "E",
    "Road User Services": "U",
}
# Column names in the header file shipped with the data (OS_Open_Names_Header.csv).
WANT = ["NAME1", "NAME2", "LOCAL_TYPE", "GEOMETRY_X", "GEOMETRY_Y", "POSTCODE_DISTRICT", "POPULATED_PLACE", "DISTRICT_BOROUGH", "COUNTY_UNITARY"]
DEFAULT_COLS = {"NAME1": 2, "NAME2": 4, "LOCAL_TYPE": 7, "GEOMETRY_X": 8, "GEOMETRY_Y": 9, "POSTCODE_DISTRICT": 16,
                "POPULATED_PLACE": 18, "DISTRICT_BOROUGH": 21, "COUNTY_UNITARY": 24}


def key_of(text, postcode=False):
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    if postcode:
        return re.sub(r"[^a-z0-9]", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s.replace("-", " ").replace("/", " "))
    return re.sub(r" +", " ", s).strip()


def clean(text):
    return (text or "").replace("\t", " ").replace("\n", " ").strip()


def columns(osnames_dir):
    cols = dict(DEFAULT_COLS)
    headers = [p for p in glob.glob(os.path.join(osnames_dir, "**", "*.csv"), recursive=True) if "header" in p.lower()]
    if headers:
        with open(headers[0], encoding="utf-8-sig", errors="replace") as f:
            names = [n.strip() for n in next(csv.reader(f))]
        cols.update({n: i for i, n in enumerate(names) if n in cols})
    return cols


# ---- Northern Ireland: OSNI Open Data Gazetteers (Land & Property Services, OGL v3) ----
OSNI_CREDITS = ("Contains LPS Intellectual Property © Crown copyright and database right ({year}) "
                "This information is licensed under the terms of the Open Government Licence")
# Northern Ireland envelope (WGS84). Points outside it are rejected and counted.
NI_LON = (-8.3, -5.3)
NI_LAT = (53.9, 55.4)
DEDUPE_METRES = 50.0
# Header names are compared upper-case with everything but A-Z/0-9 removed ("Street Name" -> STREETNAME).
OSNI_NAME_COLS = {
    "streets": ["STREETNAME", "STREET", "STRNAME", "STNAME", "ROADNAME", "THOROUGHFARE", "NAME", "NAME1"],
    "places": ["PLACENAME", "PLACE", "PLACENAMES", "SETTLEMENT", "SETTLEMENTNAME", "TOWNNAME", "NAME", "NAME1", "TOWN"],
}
OSNI_AREA_COLS = ["TOWN", "TOWNNAME", "POSTTOWN", "LOCALITY", "SETTLEMENT", "SETTLEMENTNAME", "TOWNLAND",
                  "LGD", "LGDNAME", "COUNCIL", "COUNCILNAME", "LOCALGOVERNMENTDISTRICT", "DISTRICT", "COUNTY"]
OSNI_TYPE_COLS = ["TYPE", "PLACETYPE", "SETTLEMENTTYPE", "CLASS", "CATEGORY", "FEATURETYPE", "LOCALTYPE"]
OSNI_X_COLS = ["X", "EASTING", "EASTINGS", "XCOORD", "XCOORDINATE", "XCOR", "XCO", "XCOORDS", "IGEASTING", "ITMEASTING", "POINTX"]
OSNI_Y_COLS = ["Y", "NORTHING", "NORTHINGS", "YCOORD", "YCOORDINATE", "YCOR", "YCO", "YCOORDS", "IGNORTHING", "ITMNORTHING", "POINTY"]
OSNI_LON_COLS = ["LON", "LONG", "LONGITUDE", "LNG"]
OSNI_LAT_COLS = ["LAT", "LATITUDE"]
# Place-type words a gazetteer may carry, mapped onto the existing settlement codes; anything else is O.
OSNI_PLACE_TYPES = {"CITY": "C", "TOWN": "T", "LARGETOWN": "T", "MEDIUMTOWN": "T", "SMALLTOWN": "T",
                    "VILLAGE": "V", "HAMLET": "H", "SUBURB": "S", "SUBURBANAREA": "S"}


class OsniError(ValueError):
    pass


def _norm(name):
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _pick(fields, wanted):
    """First field (original spelling) whose normalised name is in `wanted`, by preference order."""
    by = {}
    for f in fields:
        by.setdefault(_norm(f), f)
    for w in wanted:
        if w in by:
            return by[w]
    return None


def _crs_of(text):
    """EPSG code named in a CRS string ('urn:ogc:def:crs:EPSG::29902', 'EPSG:2157', 'CRS84'), else None."""
    if not text:
        return None
    t = str(text).upper()
    if "CRS84" in t:
        return 4326
    m = re.search(r"EPSG[^0-9]*(\d{4,5})", t)
    return int(m.group(1)) if m else None


def _classify(x, y):
    """CRS of one point from its magnitude when the file does not say. NI in Irish Grid is about
    E 180-370 km, N 310-460 km; in Irish Transverse Mercator about E 630-740 km, N 800-980 km."""
    if abs(x) <= 180 and abs(y) <= 90:
        return 4326
    return 2157 if y > 600_000 else 29902


def _float(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _point(geom):
    """A representative coordinate for a GeoJSON geometry: the point, or the middle vertex."""
    if not isinstance(geom, dict):
        return None
    if geom.get("type") == "GeometryCollection":
        for g in geom.get("geometries") or []:
            p = _point(g)
            if p:
                return p
        return None
    flat = []

    def walk(c):
        if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(v, (int, float)) for v in c[:2]):
            flat.append((float(c[0]), float(c[1])))
        elif isinstance(c, (list, tuple)):
            for v in c:
                walk(v)
    walk(geom.get("coordinates"))
    return flat[len(flat) // 2] if flat else None


def read_osni(path, kind):
    """Rows {name, area, type_word, x, y, crs} from an OSNI CSV or GeoJSON (crs None = detect per point).
    Raises OsniError when no name column or no coordinates can be found."""
    with open(path, "rb") as f:
        head = f.read(4096).lstrip(b"\xef\xbb\xbf").lstrip()
    out = []
    if head[:1] in (b"{", b"["):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        feats = data.get("features") if isinstance(data, dict) else None
        if not isinstance(feats, list):
            raise OsniError(f"{path}: GeoJSON has no features list")
        declared = _crs_of(((data.get("crs") or {}).get("properties") or {}).get("name"))
        fields = []
        for ft in feats[:500]:
            for k in ((ft or {}).get("properties") or {}):
                if k not in fields:
                    fields.append(k)
        name_col = _pick(fields, OSNI_NAME_COLS[kind])
        if not name_col:
            raise OsniError(f"{path}: no {kind} name property found (have: {', '.join(fields[:20]) or 'none'})")
        x_col, y_col = _pick(fields, OSNI_X_COLS), _pick(fields, OSNI_Y_COLS)
        if feats and not (x_col and y_col) and not any(_point((ft or {}).get("geometry")) for ft in feats[:500]):
            raise OsniError(f"{path}: features have no geometry and no X/Y properties")
        records = []
        for ft in feats:
            props = (ft or {}).get("properties") or {}
            p, crs = _point((ft or {}).get("geometry")), declared
            if p is None and x_col and y_col:
                p, crs = (_float(props.get(x_col)), _float(props.get(y_col))), None
            records.append((props, p, crs))
    else:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            name_col = _pick(fields, OSNI_NAME_COLS[kind])
            if not name_col:
                raise OsniError(f"{path}: no {kind} name column found (have: {', '.join(fields[:20]) or 'none'})")
            x_col, y_col, crs = _pick(fields, OSNI_X_COLS), _pick(fields, OSNI_Y_COLS), None
            if not (x_col and y_col):
                x_col, y_col, crs = _pick(fields, OSNI_LON_COLS), _pick(fields, OSNI_LAT_COLS), 4326
            if not (x_col and y_col):
                raise OsniError(f"{path}: no coordinate columns found (want X/Y, Easting/Northing or Lat/Lon; "
                                f"have: {', '.join(fields[:20])})")
            records = [(r, (_float(r.get(x_col)), _float(r.get(y_col))), crs) for r in reader]
    area_col = _pick([f for f in fields if f != name_col], OSNI_AREA_COLS)
    type_col = _pick([f for f in fields if f != name_col], OSNI_TYPE_COLS) if kind == "places" else None
    for props, p, crs in records:
        out.append({"name": props.get(name_col), "area": props.get(area_col) if area_col else "",
                    "type_word": props.get(type_col) if type_col else "",
                    "x": p[0] if p else None, "y": p[1] if p else None, "crs": crs})
    return out


def _transformers():
    from pyproj import Transformer

    cache = {}

    def to_wgs(epsg, xs, ys):
        if epsg not in cache:
            cache[epsg] = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
        return cache[epsg](xs, ys)
    return to_wgs


def _near(a, b):
    """Rough metres test between two (lat, lon) points; plenty for a 50 m duplicate check."""
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy) <= DEDUPE_METRES


def _tidy(text):
    return text.title() if text.isupper() else text


def osni_lines(sources, existing, osni_to_wgs=None):
    """Search lines for NI streets/places. `sources` is [(kind, path)]; `existing` maps (key, type) to the
    (lat, lon) points already in the file near NI, so nothing is listed twice. Returns (lines, stats)."""
    to_wgs = osni_to_wgs or _transformers()
    stats = {"streets": 0, "places": 0, "outside_ni": 0, "no_name_or_point": 0, "duplicates": 0}
    taken = {k: list(v) for k, v in existing.items()}
    lines = []
    for kind, path in sources:
        rows = read_osni(path, kind)
        groups = {}
        for i, r in enumerate(rows):
            name = clean(str(r["name"] or ""))
            if not key_of(name) or r["x"] is None or r["y"] is None:
                stats["no_name_or_point"] += 1
                continue
            x, y, crs = r["x"], r["y"], r["crs"]
            if crs is None:
                if 50 <= x <= 60 and -11 <= y <= 0:   # obviously lat/lon written the wrong way round
                    x, y = y, x
                crs = _classify(x, y)
            groups.setdefault(crs, []).append((i, name, x, y))
        points = {}
        for crs, items in groups.items():
            xs, ys = [it[2] for it in items], [it[3] for it in items]
            lons, lats = (xs, ys) if crs == 4326 else to_wgs(crs, xs, ys)
            for (i, name, _, _), lon, lat in zip(items, lons, lats):
                points[i] = (name, lat, lon)
        for i in sorted(points):
            name, lat, lon = points[i]
            if not (math.isfinite(lat) and math.isfinite(lon)
                    and NI_LAT[0] <= lat <= NI_LAT[1] and NI_LON[0] <= lon <= NI_LON[1]):
                stats["outside_ni"] += 1
                continue
            r = rows[i]
            t = "R" if kind == "streets" else OSNI_PLACE_TYPES.get(_norm(r["type_word"] or ""), "O")
            area = _tidy(clean(str(r["area"] or "")))
            if not key_of(area) or key_of(area) == key_of(name):
                area = "Northern Ireland"
            key = key_of(name)
            pt = (round(lat, 4), round(lon, 4))
            if any(_near(pt, q) for q in taken.get((key, t), ())):
                stats["duplicates"] += 1
                continue
            taken.setdefault((key, t), []).append(pt)
            lines.append(f"{key}\t{t}\t{_tidy(name)}\t{area}\t{lat:.4f}\t{lon:.4f}")
            stats[kind] += 1
    return lines, stats


def build(osnames_dir, dst, to_wgs=None, osni_streets=None, osni_places=None, osni_to_wgs=None):
    if to_wgs is None:
        from pyproj import Transformer

        to_wgs = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True).transform
    col = columns(osnames_dir)
    width = max(col.values()) + 1
    seen = set()
    lines = []
    counts = {}
    files = sorted(p for p in glob.glob(os.path.join(osnames_dir, "**", "*.csv"), recursive=True) if "header" not in p.lower())
    for path in files:
        rows = []
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            for row in csv.reader(f):
                if len(row) < width:
                    continue
                t = TYPES.get(row[col["LOCAL_TYPE"]])
                if not t:
                    continue
                try:
                    rows.append((t, row, float(row[col["GEOMETRY_X"]]), float(row[col["GEOMETRY_Y"]])))
                except ValueError:
                    continue
        if not rows:
            continue
        lons, lats = to_wgs([r[2] for r in rows], [r[3] for r in rows])
        for (t, row, _, _), lon, lat in zip(rows, lons, lats):
            if not (49.0 < lat < 61.5 and -9.0 < lon < 2.5):
                continue
            town, borough, county, district = (clean(row[col[k]]) for k in ("POPULATED_PLACE", "DISTRICT_BOROUGH", "COUNTY_UNITARY", "POSTCODE_DISTRICT"))
            if t == "P":
                names = [(key_of(row[col["NAME1"]], postcode=True), "")]
                area = town or borough or county
            else:
                names = [(key_of(n), n) for n in (clean(row[col["NAME1"]]), clean(row[col["NAME2"]])) if n]
                area = ", ".join(p for p in (town or borough or county, district) if p)
            for key, name in names:
                if not key:
                    continue
                ident = (key, t, area)
                if ident in seen:     # same street listed again (another section of it)
                    continue
                seen.add(ident)
                lines.append(f"{key}\t{t}\t{name}\t{area}\t{lat:.4f}\t{lon:.4f}")
                counts[t] = counts.get(t, 0) + 1
    sources = [(k, p) for k, p in (("streets", osni_streets), ("places", osni_places)) if p]
    osni_stats = None
    credits = CREDITS
    if sources:
        near_ni = {}
        for line in lines:
            key, t, _, _, lat, lon = line.split("\t")
            if NI_LAT[0] - 0.1 <= float(lat) <= NI_LAT[1] + 0.1 and NI_LON[0] - 0.1 <= float(lon) <= NI_LON[1] + 0.1:
                near_ni.setdefault((key, t), []).append((float(lat), float(lon)))
        extra, osni_stats = osni_lines(sources, near_ni, osni_to_wgs)
        lines.extend(extra)
        for line in extra:
            t = line.split("\t")[1]
            counts[t] = counts.get(t, 0) + 1
        if extra:
            credits = CREDITS + "; " + OSNI_CREDITS.format(year=time.gmtime().tm_year)
    lines.sort()
    header = f"#drivemate-search-offline\t1\t{time.strftime('%Y-%m-%d', time.gmtime())}\t{credits}"
    tmp = dst + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9, newline="\n") as f:
        f.write(header + "\n")
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, dst)
    stats = {"records": len(lines), "by_type": counts, "bytes": os.path.getsize(dst)}
    if osni_stats is not None:
        stats["osni"] = osni_stats
    return stats


def selftest():
    import tempfile

    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "Doc"))
    os.makedirs(os.path.join(tmp, "Data"))
    header = ("ID,NAMES_URI,NAME1,NAME1_LANG,NAME2,NAME2_LANG,TYPE,LOCAL_TYPE,GEOMETRY_X,GEOMETRY_Y,MOST_DETAIL_VIEW_RES,"
              "LEAST_DETAIL_VIEW_RES,MBR_XMIN,MBR_YMIN,MBR_XMAX,MBR_YMAX,POSTCODE_DISTRICT,POSTCODE_DISTRICT_URI,POPULATED_PLACE,"
              "POPULATED_PLACE_URI,POPULATED_PLACE_TYPE,DISTRICT_BOROUGH,DISTRICT_BOROUGH_URI,DISTRICT_BOROUGH_TYPE,COUNTY_UNITARY,"
              "COUNTY_UNITARY_URI,COUNTY_UNITARY_TYPE,REGION,REGION_URI,COUNTRY,COUNTRY_URI,RELATED_SPATIAL_OBJECT,SAME_AS_DBPEDIA,SAME_AS_GEONAMES")
    with open(os.path.join(tmp, "Doc", "OS_Open_Names_Header.csv"), "w", encoding="utf-8-sig") as f:
        f.write(header + "\n")

    def row(name1, local, x, y, district="", town="", borough="", county="", name2=""):
        r = [""] * 34
        r[2], r[4], r[7], r[8], r[9], r[16], r[18], r[21], r[24] = name1, name2, local, str(x), str(y), district, town, borough, county
        return r
    rows = [
        row("SK8 2EZ", "Postcode", 384900, 387100, town="Cheadle", borough="Stockport"),
        row("Menai Grove", "Named Road", 384950, 387150, "SK8", "Cheadle", "Stockport"),
        row("Menai Grove", "Section Of Named Road", 384960, 387160, "SK8", "Cheadle", "Stockport"),   # same street again
        row("Menai Grove", "Named Road", 250000, 370000, "LL59", "Menai Bridge", county="Isle of Anglesey"),   # another one
        row("Heol Wiliam", "Named Road", 217882, 246203, "SA43", "Cardigan", county="Ceredigion", name2="William Street"),
        row("Stockport", "Railway Station", 389300, 389900, "SK3", "Stockport", "Stockport"),
        row("Ben Nevis", "Hill Or Mountain", 216600, 771200),   # not a driving destination: left out
        row("St. Mary's & St. John's", "Primary Education", 390000, 390000, "SK1", "Stockport", "Stockport"),
    ]
    with open(os.path.join(tmp, "Data", "SJ88.csv"), "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    # British National Grid → lon/lat without pyproj: a rough stand-in good enough for the test.
    rough = lambda xs, ys: ([-7.556 + x / 69000 for x in xs], [49.766 + y / 111200 for y in ys])
    out = os.path.join(tmp, "search.tsv.gz")
    st = build(tmp, out, rough)
    with gzip.open(out, "rt", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    assert lines[0].startswith("#drivemate-search-offline\t1\t") and "Royal Mail" in lines[0]
    recs = [l.split("\t") for l in lines[1:] if l]
    assert all(len(r) == 6 for r in recs), recs
    keys = [r[0] for r in recs]
    assert keys == sorted(keys), keys
    by = {(r[0], r[1], r[3]): r for r in recs}
    assert ("sk82ez", "P", "Cheadle") in by and by[("sk82ez", "P", "Cheadle")][2] == ""
    assert sum(1 for r in recs if r[0] == "menai grove") == 2          # duplicate section dropped, other town kept
    assert ("menai grove", "R", "Cheadle, SK8") in by and ("menai grove", "R", "Menai Bridge, LL59") in by
    assert ("william street", "R", "Cardigan, SA43") in by and ("heol wiliam", "R", "Cardigan, SA43") in by
    assert ("stockport", "N", "Stockport, SK3") in by
    assert ("st marys and st johns", "E", "Stockport, SK1") in by
    assert not any(r[0] == "ben nevis" for r in recs)
    lat, lon = float(by[("sk82ez", "P", "Cheadle")][4]), float(by[("sk82ez", "P", "Cheadle")][5])
    assert 53 < lat < 54 and -2.5 < lon < -1.5, (lat, lon)
    assert key_of("Pen-y-Ŵal") == "pen y wal" and key_of("sk8 2ez", postcode=True) == "sk82ez"
    assert st["records"] == len(recs) == 7, st
    assert "LPS" not in lines[0]
    # Northern Ireland: OSNI street gazetteer in Irish Grid (EPSG:29902), converted with pyproj.
    streets = os.path.join(tmp, "osni_streets.csv")
    with open(streets, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([["STREETNAME", "TOWN", "X", "Y"],
                                 ["DONEGALL SQUARE NORTH", "BELFAST", "333900", "374000"],   # Belfast City Hall
                                 ["Donegall Square North", "Belfast", "333920", "374010"],   # same street within 50 m
                                 ["Nowhere Road", "", "100000", "100000"]])                    # outside Northern Ireland
    st = build(tmp, out, rough, osni_streets=streets)
    with gzip.open(out, "rt", encoding="utf-8") as f:
        lines = f.read().split("\n")
    assert "Contains LPS Intellectual Property" in lines[0] and "Royal Mail" in lines[0], lines[0]
    ni = [l.split("\t") for l in lines[1:] if l.startswith("donegall square north")]
    assert len(ni) == 1 and ni[0][1:4] == ["R", "Donegall Square North", "Belfast"], ni
    assert abs(float(ni[0][4]) - 54.596) < 0.001 and abs(float(ni[0][5]) + 5.930) < 0.0015, ni
    assert st["osni"]["outside_ni"] == 1 and st["osni"]["duplicates"] == 1 and st["records"] == 8, st
    assert not any(l.split("\t")[1] == "P" and l.startswith("bt") for l in lines[1:] if l)
    print("selftest ok")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the offline postcode, street and place search file.")
    parser.add_argument("osnames_dir")
    parser.add_argument("output")
    parser.add_argument("--osni-streets", help="OSNI Open Data Gazetteer - Streetnames (CSV or GeoJSON)")
    parser.add_argument("--osni-places", help="OSNI Open Data Gazetteer - Place Names (CSV or GeoJSON)")
    args = parser.parse_args(argv)
    try:
        stats = build(args.osnames_dir, args.output, osni_streets=args.osni_streets, osni_places=args.osni_places)
    except OsniError as error:
        raise SystemExit(f"OSNI gazetteer not usable: {error}")
    print(json.dumps(stats))
    # A real build has well over two million lines (1.7 million postcodes alone) and tens of MB.
    if stats["records"] < int(os.environ.get("SEARCH_MIN_RECORDS", "1000000")) or stats["bytes"] < 5_000_000:
        raise SystemExit("::error::offline search file is far too small - build failed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        main()
