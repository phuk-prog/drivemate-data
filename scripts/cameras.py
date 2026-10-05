"""All UK speed / red-light / average-speed cameras and level crossings from OpenStreetMap,
in the same JSON layout the app already reads from the live map-data server — so the app
has every camera from our own file instead of relying on that (often busy) server.

Usage: cameras.py cameras.opl cameras-uk.json   (OPL from: osmium cat -f opl,add_metadata=false)
"""
import json
import re
import sys

src, dst = sys.argv[1], sys.argv[2]


def unescape(s):
    # OPL escapes special characters as %<hex>%
    return re.sub(r"%([0-9a-fA-F]+)%", lambda m: chr(int(m.group(1), 16)), s)


def tags_of(field):
    out = {}
    if not field:
        return out
    for kv in field.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[unescape(k)] = unescape(v)
    return out


elements = []
counts = {"node": 0, "relation": 0}
with open(src, encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split(" ")
        kind, oid = parts[0][0], int(parts[0][1:])
        fields = {p[0]: p[1:] for p in parts[1:] if p}
        tags = tags_of(fields.get("T"))
        if kind == "n" and "x" in fields and fields["x"]:
            elements.append({"type": "node", "id": oid, "lat": float(fields["y"]), "lon": float(fields["x"]), "tags": tags})
            counts["node"] += 1
        elif kind == "r" and tags.get("type") == "enforcement":
            members = []
            for m in (fields.get("M") or "").split(","):
                if not m:
                    continue
                ref, _, role = m.partition("@")
                members.append({"type": {"n": "node", "w": "way", "r": "relation"}[ref[0]], "ref": int(ref[1:]), "role": unescape(role)})
            elements.append({"type": "relation", "id": oid, "tags": tags, "members": members})
            counts["relation"] += 1

with open(dst, "w", encoding="utf-8") as f:
    json.dump({"source": "© OpenStreetMap contributors (ODbL)", "elements": elements}, f, separators=(",", ":"))
print(json.dumps(counts))
