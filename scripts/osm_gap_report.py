"""Informational list of places where OpenStreetMap lacks navigation data.

Reads an OSM extract (PBF, or OPL for tests) and lists, for people to survey and
add in OSM by hand:
  (a) approaches to junctions on motorway/trunk/primary/secondary roads with
      lanes >= 2 but no turn:lanes within ~150 m of the junction;
  (b) motorway/trunk/primary/secondary/tertiary ways with no maxspeed;
  (c) motorway_link / trunk_link slips with no lanes tag.
Nothing is filled in or guessed: this only reports what is absent. Never fails
because of gaps.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from restriction_acceptance import haversine, pbf_to_opl, read_node_coords, read_opl  # noqa: E402

APPROACH_METRES = 150.0
NEAR_METRES = 300.0
JUNCTION_CLASSES = ("motorway", "trunk", "primary", "secondary")
SPEED_CLASSES = JUNCTION_CLASSES + ("tertiary",)
SLIP_CLASSES = ("motorway_link", "trunk_link")
CLASS_WEIGHT = {"motorway": 6, "motorway_link": 5, "trunk": 5, "trunk_link": 4,
                "primary": 4, "secondary": 3, "tertiary": 2}
SK8_2EZ = (53.395466, -2.194193)
# Rough areas (south, west, north, east) matched by road ref, then widened by 300 m.
# Approximations for flagging only; override with --corridors.
CORRIDORS = [
    {"name": "M60 J1-J4 (Stockport)", "ref": "M60", "bbox": [53.375, -2.240, 53.425, -2.120]},
    {"name": "M56 J1-J3", "ref": "M56", "bbox": [53.340, -2.320, 53.405, -2.215]},
    {"name": "A34 Cheadle/Gatley", "ref": "A34", "bbox": [53.360, -2.260, 53.415, -2.195]},
    {"name": "A560 Stockport-Cheadle", "ref": "A560", "bbox": [53.380, -2.235, 53.420, -2.130]},
    {"name": "SK8 2EZ", "ref": None, "point": list(SK8_2EZ)},
]


def metres_to_deg(metres):
    return metres / 111320.0


def way_length(points):
    return sum(haversine(a, b) for a, b in zip(points, points[1:]))


def has_key(tags, prefix):
    return any(k.startswith(prefix) and tags[k].strip() for k in tags)


def lane_count(tags):
    try:
        return int(tags.get("lanes", "").split(";")[0])
    except ValueError:
        return 0


def corridor_hits(tags, points, corridors):
    pad = metres_to_deg(NEAR_METRES)
    refs = {r.strip() for r in tags.get("ref", "").split(";")}
    hits = []
    for c in corridors:
        if c.get("point"):
            if any(haversine(tuple(c["point"]), p) <= NEAR_METRES for p in points):
                hits.append(c["name"])
            continue
        s, w, n, e = c["bbox"]
        pad_lon = pad / max(math.cos(math.radians((s + n) / 2)), 0.1)
        inside = any(s - pad <= p[0] <= n + pad and w - pad_lon <= p[1] <= e + pad_lon for p in points)
        if inside and (c["ref"] in refs or tags.get("highway", "").endswith("_link")):
            hits.append(c["name"])
    return hits


def junction_nodes(ways):
    """Nodes where two or more different road ways meet."""
    users = {}
    for wid, (_, nodes) in ways.items():
        for n in set(nodes):
            users.setdefault(n, set()).add(wid)
    return {n for n, w in users.items() if len(w) >= 2}


def approach_has_junction(nodes, junctions):
    """A junction node on the way: its final ~APPROACH_METRES approach is the way itself."""
    return any(n in junctions for n in nodes)


def build_report(ways, coords, corridors=None, source=None):
    corridors = CORRIDORS if corridors is None else corridors
    junctions = junction_nodes(ways)
    items = []
    for wid, (tags, nodes) in ways.items():
        cls = tags.get("highway")
        points = [coords[n] for n in nodes if n in coords]
        if len(points) < 2:
            continue
        found = []
        if cls in JUNCTION_CLASSES and lane_count(tags) >= 2 and not has_key(tags, "turn:lanes") \
                and approach_has_junction(nodes, junctions):
            found.append(("turn_lanes", "lanes=%s but no turn:lanes near a junction" % tags.get("lanes")))
        if cls in SPEED_CLASSES and not has_key(tags, "maxspeed"):
            found.append(("maxspeed", "no maxspeed"))
        if cls in SLIP_CLASSES and not has_key(tags, "lanes"):
            found.append(("slip_lanes", "no lanes on slip road"))
        if not found:
            continue
        length = round(way_length(points), 1)
        near = corridor_hits(tags, points, corridors)
        for kind, why in found:
            items.append({
                "kind": kind, "way_id": wid, "highway": cls, "name": tags.get("name", ""),
                "ref": tags.get("ref", ""), "length_m": length, "problem": why,
                "near_owner_routes": near, "priority": bool(near),
                "lat": round(points[0][0], 6), "lon": round(points[0][1], 6),
                "osm_url": "https://www.openstreetmap.org/way/%d" % wid,
                "id_editor_url": "https://www.openstreetmap.org/edit?editor=id&way=%d" % wid,
            })
    items.sort(key=lambda i: (not i["priority"], -CLASS_WEIGHT.get(i["highway"], 0),
                              -i["length_m"], i["way_id"]))
    counts = {"total": len(items), "priority": sum(i["priority"] for i in items)}
    for kind in ("turn_lanes", "maxspeed", "slip_lanes"):
        counts[kind] = sum(1 for i in items if i["kind"] == kind)
    return {"source": source, "approach_metres": APPROACH_METRES, "near_metres": NEAR_METRES,
            "corridors": corridors, "counts": counts, "items": items,
            "note": "Informational only. Verify on the ground; add to OSM from your own observation."}


TITLES = {"turn_lanes": "Missing turn:lanes at junctions", "maxspeed": "Missing maxspeed",
          "slip_lanes": "Slip roads missing lanes"}


def table(items):
    lines = ["| Priority | Road | Class | Length m | Problem | Links |", "|---|---|---|---|---|---|"]
    for i in items:
        label = " ".join(x for x in (i["name"], i["ref"]) if x) or "(unnamed)"
        prio = ("owner route: " + ", ".join(i["near_owner_routes"])) if i["priority"] else "-"
        lines.append("| %s | %s | %s | %.0f | %s | [OSM](%s) / [iD](%s) |" % (
            prio, label.replace("|", "/"), i["highway"], i["length_m"], i["problem"],
            i["osm_url"], i["id_editor_url"]))
    return lines


def markdown(report, top=50):
    c = report["counts"]
    out = ["# OpenStreetMap gap report", "",
           "Informational list for surveying and adding to OpenStreetMap by hand. Nothing here is filled in automatically.", "",
           "- Total items: %d (owner-route priority: %d)" % (c["total"], c["priority"]),
           "- Missing turn:lanes: %d; missing maxspeed: %d; slips without lanes: %d" % (
               c["turn_lanes"], c["maxspeed"], c["slip_lanes"]), ""]
    for kind, title in TITLES.items():
        items = [i for i in report["items"] if i["kind"] == kind][:top]
        out += ["## %s (top %d)" % (title, len(items)), ""] + table(items) + [""]
    return "\n".join(out)


def top_markdown(report, top=30):
    c = report["counts"]
    head = ["### OSM gaps (informational)", "", "Total %d, near owner routes %d." % (c["total"], c["priority"]), ""]
    return "\n".join(head + table(report["items"][:top]) + [""])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pbf")
    p.add_argument("--opl", help="OPL file instead of a PBF (tests)")
    p.add_argument("--json", required=True)
    p.add_argument("--markdown", required=True)
    p.add_argument("--summary", help="append the top 30 to this file")
    p.add_argument("--corridors", help="JSON file replacing the built-in corridors")
    p.add_argument("--top", type=int, default=50)
    a = p.parse_args(argv)
    if bool(a.pbf) == bool(a.opl):
        p.error("give exactly one of --pbf or --opl")
    corridors = json.loads(Path(a.corridors).read_text()) if a.corridors else None
    with tempfile.TemporaryDirectory() as tmp:
        opl = a.opl or str(Path(tmp) / "roads.opl")
        if a.pbf:
            pbf_to_opl(a.pbf, opl)
        ways, _ = read_opl(opl)
        wanted = {n for _, nodes in ways.values() for n in nodes}
        report = build_report(ways, read_node_coords(opl, wanted), corridors,
                              source=Path(a.pbf or a.opl).name)
    Path(a.json).write_text(json.dumps(report, indent=1) + "\n")
    Path(a.markdown).write_text(markdown(report, a.top))
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as handle:
            handle.write(top_markdown(report))
    print(json.dumps(report["counts"]))
    return 0  # gaps never fail the run


if __name__ == "__main__":
    sys.exit(main())
