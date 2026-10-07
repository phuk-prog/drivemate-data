"""Offline postcode and place search for the phone: every postcode in Great Britain, every named
street, and towns, villages, stations, hospitals, schools, airports, ferry ports and services,
each with a point to drive to. Built from Ordnance Survey Open Names (Open Government Licence).

Usage: search_offline.py osnames_dir search-offline-uk.tsv.gz
       search_offline.py --selftest

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

  The same street name in the same area is listed once. Northern Ireland is not in OS Open Names,
  so its postcodes and streets are not in this file (the app's online search covers them).

Credits (must be shown): Contains OS data © Crown copyright and database rights; Contains Royal
Mail data © Royal Mail copyright and database right; Contains National Statistics data © Crown
copyright and database right (OS Open Names, Open Government Licence v3).
"""
import csv
import glob
import gzip
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


def build(osnames_dir, dst, to_wgs=None):
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
    lines.sort()
    header = f"#drivemate-search-offline\t1\t{time.strftime('%Y-%m-%d', time.gmtime())}\t{CREDITS}"
    tmp = dst + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9, newline="\n") as f:
        f.write(header + "\n")
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, dst)
    return {"records": len(lines), "by_type": counts, "bytes": os.path.getsize(dst)}


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
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        stats = build(sys.argv[1], sys.argv[2])
        import json

        print(json.dumps(stats))
        # A real build has well over two million lines (1.7 million postcodes alone) and tens of MB.
        if stats["records"] < int(os.environ.get("SEARCH_MIN_RECORDS", "1000000")) or stats["bytes"] < 5_000_000:
            raise SystemExit("::error::offline search file is far too small - build failed")
