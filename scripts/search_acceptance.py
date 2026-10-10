#!/usr/bin/env python3
"""Acceptance check for DriveMate's offline search file (search-offline-uk.tsv.gz).

Runs a list of queries through a faithful Python port of the app's search
(app/src/main/java/com/drivemate/app/data/OfflineSearch.kt: key(), the postcode rule,
searchStream() and its ranking) and checks the results by POSITION, not by exact text.

Usage: search_acceptance.py SEARCH_FILE QUERIES_JSON [--out report.json] [--summary summary.md]
Exit 0 when there is no unexpected FAIL; 1 otherwise. Queries marked "known_fail": true may fail
(reported as KNOWN-FAIL); if they pass they are reported as XPASS and do not fail the run.

Query fields: query, near ([lat, lon] the result must be close to), radius_m, rank (the expected
place must be within the top N results, default 1), types (optional allowed type letters),
user_near (optional [lat, lon] standing in for the driver's position, used for ranking),
known_fail, note.
"""
import argparse
import gzip
import json
import math
import re
import sys
import unicodedata

ORDER = "PCTNRSVHOBAFMEU"
MAX_FOUND = 400
MAX_RESULTS = 12
_POSTCODE = re.compile(r"^([a-z]{1,2}\d[a-z\d]?) ?(\d[a-z]{2})?$", re.ASCII)


def key(s):
    """OfflineSearch.key: lower case, accents removed, '&' -> ' and ', non a-z0-9 runs -> one space."""
    s = s.lower().replace("&", " and ")
    plain = re.sub(r"[̀-ͯ]+", "", unicodedata.normalize("NFD", s))
    plain = re.sub(r"[^a-z0-9]+", " ", plain).strip()
    return re.sub(r" +", " ", plain)


def distance_m(a, b):
    """Great-circle distance in metres between (lat, lon) pairs."""
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def search_lines(lines, q, near=None):
    """Port of OfflineSearch.searchStream over an iterable of text lines (q already keyed)."""
    found = []
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("#"):
            continue
        tab = line.find("\t")
        if tab <= 0:
            continue
        k = line[:tab]
        if k < q:
            continue
        if not k.startswith(q):
            break  # sorted: nothing further can match
        p = line.split("\t")
        if len(p) < 6 or not p[1]:
            continue
        typ = p[1][0]
        try:
            lat, lon = float(p[4]), float(p[5])
        except ValueError:
            continue
        if typ == "P":
            u = k.upper()
            name = u[:-3] + " " + u[-3:]
        else:
            name = p[2]
        found.append((k, typ, {"name": name, "address": p[3], "lat": lat, "lon": lon, "type": typ}))
        if len(found) >= MAX_FOUND:
            break

    def sort_key(t):
        d = distance_m(near, (t[2]["lat"], t[2]["lon"])) if near else 0.0
        i = ORDER.find(t[1])
        return (0 if t[0] == q else 1, d, i if i >= 0 else 99)

    found.sort(key=sort_key)  # stable, like Kotlin sortedWith
    out, seen = [], set()
    for _, _, pl in found:
        ident = pl["name"] + "|" + pl["address"]
        if ident in seen:
            continue
        seen.add(ident)
        out.append(pl)
    return out[:MAX_RESULTS]


def search(path, query, near=None):
    q = key(query)
    if not q:
        return []
    if _POSTCODE.match(q):
        q = q.replace(" ", "")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return search_lines(f, q, near)


def evaluate(results, exp):
    """Return (ok, detail). The expected place must be in the top `rank` results, within radius."""
    rank = int(exp.get("rank", 1))
    radius = float(exp["radius_m"])
    types = exp.get("types")
    target = tuple(exp["near"])
    best = None
    for i, r in enumerate(results[:rank]):
        if types and r["type"] not in types:
            continue
        d = distance_m(target, (r["lat"], r["lon"]))
        if best is None or d < best[0]:
            best = (d, i + 1)
        if d <= radius:
            return True, "result %d is %.0f m from expected point" % (i + 1, d)
    if best:
        return False, "nearest of top %d is %.0f m away (limit %.0f m)" % (rank, best[0], radius)
    return False, "no suitable result in top %d" % rank


def run(path, queries):
    report = []
    for e in queries:
        near = tuple(e["user_near"]) if e.get("user_near") else None
        res = search(path, e["query"], near)
        ok, detail = evaluate(res, e)
        known = bool(e.get("known_fail"))
        status = ("XPASS" if known else "PASS") if ok else ("KNOWN-FAIL" if known else "FAIL")
        report.append({"query": e["query"], "status": status, "detail": detail, "note": e.get("note", ""),
                       "top3": res[:3]})
    return report


def summary(report):
    lines = ["| Query | Result | Top result | Detail |", "|---|---|---|---|"]
    for r in report:
        t = r["top3"][0] if r["top3"] else None
        top = "%s (%s)" % (t["name"], t["address"]) if t else "none"
        lines.append("| %s | %s | %s | %s |" % (r["query"], r["status"], top, r["detail"]))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("search_file")
    ap.add_argument("queries")
    ap.add_argument("--out")
    ap.add_argument("--summary")
    a = ap.parse_args(argv)
    with open(a.queries, encoding="utf-8") as f:
        queries = json.load(f)["queries"]
    report = run(a.search_file, queries)
    for r in report:
        print("%-10s %-22s %s" % (r["status"], r["query"], r["detail"]))
        for i, p in enumerate(r["top3"], 1):
            print("    %d. [%s] %s, %s (%.4f, %.4f)" % (i, p["type"], p["name"], p["address"], p["lat"], p["lon"]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"results": report}, f, indent=2, ensure_ascii=False)
    text = summary(report)
    if a.summary:
        with open(a.summary, "w", encoding="utf-8") as f:
            f.write(text)
    bad = [r for r in report if r["status"] == "FAIL"]
    print("%d queries, %d unexpected FAIL" % (len(report), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
