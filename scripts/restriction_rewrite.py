"""Rewrite OSM ``only_u_turn`` restrictions into prohibitions Valhalla enforces.

Valhalla 3.6.3's tile builder does not recognise ``restriction=only_u_turn``
(its restriction table knows only ``no_left_turn``, ``no_right_turn``,
``no_straight_on``, ``no_u_turn``, ``only_left_turn``, ``only_right_turn``,
``only_straight_on``, ``no_entry``, ``no_exit`` and ``no_turn``), so such
relations are silently ignored and routes may leave the via node on any exit.

This script writes a copy of the input PBF in which each *simple* node-via
``only_u_turn`` relation (one ``from`` way, one ``via`` node, one ``to`` way,
where ``to`` is the ``from`` way itself or a separately tagged opposite
carriageway) is replaced by the logically equivalent set of prohibitions:
for every other drivable exit at the via node, a ``no_left_turn``,
``no_right_turn``, ``no_straight_on`` or ``no_u_turn`` relation from the same
``from`` way via the same node to that exit (type chosen from the bearing
change). Every other tag of the original relation (``except``, ``day_on``,
``hour_on``, ``restriction:conditional``, vehicle-specific ``restriction:*``
keys, ...) is copied unchanged, with only the restriction type substituted.

Nothing is invented beyond that equivalent. Anything ambiguous (way via,
several from/to members, a from or to way passing *through* the via node,
mixed restriction values, missing geometry) is left untouched and counted in
the JSON report. Only relations in the ``rewritten`` list are removed from
the output. Generated relations use IDs from ``ID_BASE`` upwards and carry
``drivemate:rewritten_from=<original id>``.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ID_BASE = 9_000_000_000_000  # far above any OSM relation ID; checked against the input
TARGET = "only_u_turn"
STRAIGHT_DEGREES = 45.0  # |bearing change| below this is "straight on" (project rule: keep < 45 deg)
NON_MOTOR_HIGHWAYS = {"footway", "cycleway", "path", "pedestrian", "steps", "bridleway", "corridor",
                      "elevator", "platform", "proposed", "construction", "abandoned", "razed",
                      "disused", "bus_stop", "via_ferrata"}
# Only these types are generated; all are in Valhalla 3.6.3's restriction table.
GENERATED_TYPES = {"no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn"}
_RULE = re.compile(r"\s*only_u_turn\s*(@\s*)?\Z")
_TOKEN = re.compile(r"\bonly_u_turn\b")


# --------------------------------------------------------------------------- geometry

def bearing(a, b):
    """Initial bearing in degrees from (lat, lon) a to b."""
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def turn_type(approach, exit_bearing):
    """Signed change (-180, 180]: negative is a left turn, positive a right turn."""
    change = (exit_bearing - approach + 540.0) % 360.0 - 180.0
    if change == -180.0:
        change = 180.0
    if abs(change) < STRAIGHT_DEGREES:
        return "no_straight_on", change
    return ("no_left_turn" if change < 0 else "no_right_turn"), change


def oneway(tags):
    """+1 forward only, -1 backward only, 0 both ways or unknown (unknown never removes an exit)."""
    for key in ("oneway:motorcar", "oneway:motor_vehicle", "oneway:vehicle", "oneway"):
        if key in tags:
            value = tags[key].strip().lower()
            return {"yes": 1, "true": 1, "1": 1, "-1": -1, "reverse": -1}.get(value, 0)
    if tags.get("junction") in ("roundabout", "circular") or tags.get("highway") in ("motorway", "motorway_link"):
        return 1
    return 0


def legs_away(nodes, via):
    """Node sequences leaving ``via`` along a way, with their direction (+1 along node order)."""
    legs = []
    for i, n in enumerate(nodes):
        if n != via:
            continue
        if i + 1 < len(nodes):
            legs.append((nodes[i:], 1))
        if i > 0:
            legs.append((nodes[: i + 1][::-1], -1))
    return legs


# --------------------------------------------------------------------------- transformation

def restriction_keys(tags):
    return [k for k in tags if k == "restriction" or k.startswith("restriction:")]


def is_candidate(tags):
    return tags.get("type") == "restriction" and any(
        _TOKEN.search(tags[k] or "") for k in restriction_keys(tags))


def _values_are_pure(tags):
    """Every restriction-valued key holds only ``only_u_turn`` rules (optionally conditional)."""
    for key in restriction_keys(tags):
        value = re.sub(r"\([^)]*\)", "", tags[key] or "")  # drop condition text
        if not value.strip() or not all(_RULE.match(part) for part in value.split(";")):
            return False
    return True


def _skip(relation_id, reason, **extra):
    return dict(relation=relation_id, reason=reason, **extra)


def plan_relation(relation, ways, coords):
    """Return (generated specs, None) or (None, skip record) for one candidate relation.

    ``relation`` is (id, tags, members) with members as (type 'n'/'w'/'r', ref, role);
    ``ways`` maps way id -> (tags, node list) for highway ways touching the via node;
    ``coords`` maps node id -> (lat, lon).
    """
    ident, tags, members = relation
    if not _values_are_pure(tags):
        return None, _skip(ident, "mixed_restriction_values")
    froms = [(k, r) for k, r, role in members if role == "from"]
    vias = [(k, r) for k, r, role in members if role == "via"]
    tos = [(k, r) for k, r, role in members if role == "to"]
    if {role for _, _, role in members} - {"from", "via", "to"}:
        return None, _skip(ident, "unexpected_member_roles")
    if len(vias) == 1 and vias[0][0] == "w" or len(vias) > 1:
        return None, _skip(ident, "way_via")
    if len(froms) != 1 or len(tos) != 1 or len(vias) != 1:
        return None, _skip(ident, "not_single_from_via_to")
    if froms[0][0] != "w" or tos[0][0] != "w" or vias[0][0] != "n":
        return None, _skip(ident, "unexpected_member_types")
    from_way, via, to_way = froms[0][1], vias[0][1], tos[0][1]
    if from_way not in ways or to_way not in ways:
        return None, _skip(ident, "member_way_missing")
    if via not in coords:
        return None, _skip(ident, "via_node_missing")
    from_tags, from_nodes = ways[from_way]
    to_tags, to_nodes = ways[to_way]
    if from_nodes.count(via) != 1 or to_nodes.count(via) != 1:
        return None, _skip(ident, "via_not_once_on_member_ways")
    if via not in (from_nodes[0], from_nodes[-1]):
        return None, _skip(ident, "from_way_passes_through_via")
    if via not in (to_nodes[0], to_nodes[-1]):
        return None, _skip(ident, "to_way_passes_through_via")
    # Approach: the from way driven towards the via node.
    approach_dir = 1 if from_nodes[-1] == via else -1
    if oneway(from_tags) == -approach_dir:
        return None, _skip(ident, "from_way_oneway_away_from_via")
    prev = from_nodes[-2] if approach_dir == 1 else from_nodes[1]
    if prev not in coords:
        return None, _skip(ident, "geometry_missing")
    approach = bearing(coords[prev], coords[via])
    # The permitted manoeuvre must itself be drivable, otherwise the relation is contradictory.
    to_dir = 1 if to_nodes[0] == via else -1
    if oneway(to_tags) == -to_dir:
        return None, _skip(ident, "to_way_not_drivable_away_from_via")

    generated, seen = [], set()
    for way_id in sorted(w for w, (_, nodes) in ways.items() if via in nodes):
        if way_id == to_way:
            continue
        way_tags, nodes = ways[way_id]
        if way_tags.get("highway") in NON_MOTOR_HIGHWAYS or "highway" not in way_tags:
            continue
        legs = legs_away(nodes, via)
        if len(legs) > 1:
            # Valhalla 3.6.3 applies a simple restriction to only ONE edge of a to-way that
            # passes through the via node, whatever the turn type (verified with a synthetic
            # T-junction build), so the other leg would stay open. Leave the relation alone.
            return None, _skip(ident, "exit_way_passes_through_via", way=way_id)
        for leg, direction in legs:
            if oneway(way_tags) == -direction:
                continue  # cannot be driven away from the via node
            if way_id == from_way:
                kind, change = "no_u_turn", 180.0
            else:
                nxt = leg[1]
                if nxt not in coords:
                    return None, _skip(ident, "geometry_missing")
                kind, change = turn_type(approach, bearing(coords[via], coords[nxt]))
            if (way_id, kind) in seen:
                continue
            seen.add((way_id, kind))
            generated.append({"to_way": way_id, "restriction": kind, "bearing_change": round(change, 1)})
    if not generated:
        return None, _skip(ident, "no_other_exits")
    return generated, None


def generated_tags(tags, kind, original_id):
    out = {}
    for key, value in tags.items():
        out[key] = _TOKEN.sub(kind, value) if key in restriction_keys(tags) else value
    out["drivemate:rewritten_from"] = str(original_id)
    return out


def rewrite(relations, ways, coords, max_relation_id=0, id_base=ID_BASE):
    """Plan the rewrite. Returns (new relations, dropped ids, report dict).

    New relations are (id, tags, members). ``relations`` holds every candidate
    relation (non-candidates are ignored). Deterministic for a given input.
    """
    if max_relation_id >= id_base:
        raise ValueError(f"input relation id {max_relation_id} reaches the generated id range {id_base}")
    new, dropped, rewritten, skipped = [], [], [], []
    next_id = id_base
    seen = set()
    for relation in sorted(relations, key=lambda r: r[0]):
        ident, tags, members = relation
        if not is_candidate(tags):
            continue
        if ident in seen:
            raise ValueError(f"duplicate relation r{ident}")
        seen.add(ident)
        specs, skip = plan_relation(relation, ways, coords)
        if skip is not None:
            skipped.append(skip)
            continue
        from_way = next(r for k, r, role in members if role == "from")
        via = next(r for k, r, role in members if role == "via")
        to_way = next(r for k, r, role in members if role == "to")
        entries = []
        for spec in specs:
            assert spec["restriction"] in GENERATED_TYPES
            new.append((next_id, generated_tags(tags, spec["restriction"], ident),
                        [("w", from_way, "from"), ("n", via, "via"), ("w", spec["to_way"], "to")]))
            entries.append(dict(spec, id=next_id))
            next_id += 1
        dropped.append(ident)
        copied = sorted(k for k in tags if k not in ("type", "restriction"))
        rewritten.append({"relation": ident, "from_way": from_way, "via_node": via, "to_way": to_way,
                          "u_turn_onto": "same_way" if to_way == from_way else "opposite_carriageway",
                          "tags_preserved": copied, "generated": entries,
                          "osm_url": f"https://www.openstreetmap.org/relation/{ident}"})
    ids = [r[0] for r in new]
    if len(ids) != len(set(ids)):
        raise AssertionError("generated relation ids are not unique")
    reasons = {}
    for s in skipped:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    report = {
        "schema": 1,
        "restriction": TARGET,
        "engine": "valhalla 3.6.3 (tile builder ignores only_u_turn)",
        "id_base": id_base,
        "counts": {"candidates": len(seen), "rewritten": len(rewritten), "skipped": len(skipped),
                   "generated_relations": len(new)},
        "skipped_by_reason": dict(sorted(reasons.items())),
        "rewritten": rewritten,
        "skipped": skipped,
        "limitations": [
            "Assumes the OSM relation is correct; signage is not verified.",
            "Only simple node-via relations are rewritten; skipped ones stay unenforced by Valhalla.",
            "Exits on non-motor highways are not prohibited; exits with unknown one-way state are.",
        ],
    }
    return new, dropped, report


# --------------------------------------------------------------------------- PBF I/O (pyosmium)

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_inputs(pbf):
    import osmium
    candidates, max_id = [], 0
    for rel in osmium.FileProcessor(str(pbf), osmium.osm.RELATION):
        max_id = max(max_id, rel.id)
        tags = {t.k: t.v for t in rel.tags}
        if is_candidate(tags):
            candidates.append((rel.id, tags, [(m.type, m.ref, m.role) for m in rel.members]))
    vias = {r for _, _, members in candidates for k, r, role in members if role == "via" and k == "n"}
    ways = {}
    if vias:
        proc = osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway"))
        for way in proc:
            refs = [n.ref for n in way.nodes]
            if vias.intersection(refs):
                ways[way.id] = ({t.k: t.v for t in way.tags}, refs)
    wanted = {n for _, nodes in ways.values() for n in nodes} | vias
    coords = {}
    if wanted:
        proc = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(wanted))
        for node in proc:
            if node.location.valid():
                coords[node.id] = (node.location.lat, node.location.lon)
    return candidates, ways, coords, max_id


def write_output(src, dst, dropped, new_relations):
    import osmium
    drop = set(dropped)

    class Drop:
        def relation(self, rel):
            return rel.id in drop  # True stops the object reaching the writer

    writer = osmium.SimpleWriter(str(dst), overwrite=True)
    try:
        osmium.apply(str(src), Drop(), writer)
        for ident, tags, members in new_relations:  # highest IDs, so appended order stays sorted
            writer.add_relation(osmium.osm.mutable.Relation(id=ident, version=1, tags=tags, members=members))
    finally:
        writer.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True, help="OSM PBF extract")
    p.add_argument("--output", type=Path, required=True, help="rewritten PBF (must differ from --input)")
    p.add_argument("--report", type=Path, required=True, help="JSON report of rewritten and skipped relations")
    args = p.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        p.error("--output must differ from --input")
    if not args.input.is_file():
        p.error("input PBF not found")
    candidates, ways, coords, max_id = read_inputs(args.input)
    new, dropped, report = rewrite(candidates, ways, coords, max_id)
    write_output(args.input, args.output, dropped, new)
    report["input"] = {"path": str(args.input), "sha256": sha256(args.input), "max_relation_id": max_id}
    report["output"] = {"path": str(args.output), "sha256": sha256(args.output)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    c = report["counts"]
    print(f"only_u_turn: {c['candidates']} found, {c['rewritten']} rewritten into "
          f"{c['generated_relations']} no_* relations, {c['skipped']} skipped {report['skipped_by_reason']}")
    for s in report["skipped"]:
        print(f"::warning::only_u_turn r{s['relation']} not rewritten ({s['reason']}); Valhalla will not enforce it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
