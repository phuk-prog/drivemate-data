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

An exit way that runs *through* the via node (Valhalla 3.6.3 can restrict only one of its
two edges there) is split at the via node in this routing copy only: the first part keeps
the OSM ID, the second gets a new ID from ``WAY_ID_BASE`` with the same tags, and every
relation naming the way is re-pointed (or, if that would be ambiguous, nothing is split
and the relation is skipped). The report's ``split_ways`` maps new IDs to OSM way IDs.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ID_BASE = 9_000_000_000_000  # far above any OSM relation ID; checked against the input
WAY_ID_BASE = 9_000_000_000_000  # split-off way parts (routing copy only); checked against the input
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


class SplitConflict(Exception):
    """A relation would become ambiguous if a way were split."""


@dataclass(frozen=True)
class Split:
    """Routing-copy split of ``way`` at ``node``: ``way`` keeps ``first``, ``new_way`` gets ``second``."""
    way: int
    new_way: int
    node: int
    first: tuple
    second: tuple


def _via_anchors(members, original_nodes, splits_by_way):
    """Nodes a from/to member must touch: the via node, or the end nodes of the via way chain."""
    anchors = set()
    for kind, ref, role in members:
        if role != "via":
            continue
        if kind == "n":
            anchors.add(ref)
        elif kind == "w":
            if ref in splits_by_way:
                raise SplitConflict("split way is a via way")
            nodes = original_nodes.get(ref)
            if not nodes:
                raise SplitConflict(f"via way w{ref} geometry missing")
            anchors.update((nodes[0], nodes[-1]))
        else:
            raise SplitConflict("unexpected via member type")
    return anchors


def resolve_members(members, splits, original_nodes):
    """Members after applying ``splits`` (list of Split). Raises SplitConflict when ambiguous.

    Relations with a ``via`` member (restrictions and similar): a ``from``/``to`` split way
    becomes the one part holding the via node (or a via-way end); if both parts hold it, or
    the split way is itself a via, the relation is ambiguous. Any other relation (routes,
    multipolygons...) lists both parts, in node order, in place of the original way.
    """
    by_way = {s.way: s for s in splits}
    if not any(kind == "w" and ref in by_way for kind, ref, _ in members):
        return list(members)
    via_based = any(role == "via" for _, _, role in members)
    anchors = _via_anchors(members, original_nodes, by_way) if via_based else set()
    out = []
    for kind, ref, role in members:
        split = by_way.get(ref) if kind == "w" else None
        if split is None:
            out.append((kind, ref, role))
        elif not via_based:
            out += [(kind, split.way, role), (kind, split.new_way, role)]
        elif role not in ("from", "to"):
            raise SplitConflict(f"split way has role {role!r}")
        else:
            hits = [part for part, nodes in ((split.way, split.first), (split.new_way, split.second))
                    if anchors.intersection(nodes)]
            if len(hits) != 1:
                raise SplitConflict(f"both or neither split parts of w{ref} touch the via")
            out.append((kind, hits[0], role))
    return out


def plan(relations, ways, coords, max_relation_id=0, id_base=ID_BASE, others=(),
         max_way_id=0, way_id_base=WAY_ID_BASE):
    """Plan the rewrite for the routing-graph copy.

    ``relations``: every candidate relation (non-candidates ignored). ``others``: every other
    relation that may reference a way in ``ways`` (any type); they are re-pointed when a way
    is split. ``ways`` maps way id -> (tags, nodes) and must hold every highway way at each
    via node plus the via ways of relations in ``others``.

    Returns a dict: ``new_relations`` [(id, tags, members)], ``dropped`` [ids],
    ``relation_edits`` {id: members} for kept input relations whose members changed,
    ``way_edits`` {way id: nodes} (first parts), ``new_ways`` [(id, tags, nodes)], ``report``.
    """
    if max_relation_id >= id_base:
        raise ValueError(f"input relation id {max_relation_id} reaches the generated id range {id_base}")
    if max_way_id >= way_id_base:
        raise ValueError(f"input way id {max_way_id} reaches the generated way id range {way_id_base}")
    original_nodes = {w: list(nodes) for w, (_, nodes) in ways.items()}
    work = dict(ways)
    splits = []                       # committed, in order
    generated = []                    # (id, tags, members, splits already applied)
    rewritten, skipped, dropped = [], [], []
    next_id, next_way = id_base, way_id_base
    candidates = []
    seen = set()
    for relation in sorted(relations, key=lambda r: r[0]):
        if not is_candidate(relation[1]):
            continue
        if relation[0] in seen:
            raise ValueError(f"duplicate relation r{relation[0]}")
        seen.add(relation[0])
        candidates.append(relation)
    candidate_ids = {r[0] for r in candidates}
    kept_inputs = [r for r in others if r[0] not in candidate_ids] + candidates
    referencing = {}
    for rel in kept_inputs:
        for kind, ref, _ in rel[2]:
            if kind == "w":
                referencing.setdefault(ref, []).append(rel)

    def check_relations(trial):
        """Raise SplitConflict if any relation would become ambiguous under ``trial`` splits."""
        new_split = trial[-1]
        for rel in referencing.get(new_split.way, ()):
            resolve_members(rel[2], trial, original_nodes)
        for _, _, members, applied in generated:
            resolve_members(members, trial[applied:], original_nodes)

    for relation in candidates:
        ident, tags, members = relation
        try:
            members = resolve_members(members, splits, original_nodes)
        except SplitConflict as error:
            skipped.append(_skip(ident, "member_split_ambiguous", detail=str(error)))
            continue
        relation = (ident, tags, members)
        trial_ways, trial = dict(work), list(splits)
        specs, skip = plan_relation(relation, trial_ways, coords)
        while skip is not None and skip["reason"] == "exit_way_passes_through_via":
            way_id = skip["way"]
            via = next(r for k, r, role in members if role == "via")
            way_tags, nodes = trial_ways[way_id]
            produced = {s.way for s in trial} | {s.new_way for s in trial}
            if way_id in produced:
                skip = _skip(ident, "exit_way_already_split", way=way_id)
                break
            if nodes.count(via) != 1 or nodes[0] == nodes[-1]:
                skip = _skip(ident, "exit_way_not_splittable", way=way_id)
                break
            at = nodes.index(via)
            split = Split(way_id, next_way + len(trial) - len(splits), via,
                          tuple(nodes[:at + 1]), tuple(nodes[at:]))
            try:
                check_relations(trial + [split])
            except SplitConflict as error:
                skip = _skip(ident, "split_conflicts_with_relation", way=way_id, detail=str(error))
                break
            trial.append(split)
            trial_ways[way_id] = (way_tags, list(split.first))
            trial_ways[split.new_way] = (dict(way_tags), list(split.second))
            specs, skip = plan_relation(relation, trial_ways, coords)
        if skip is not None:
            skipped.append(skip)
            continue
        new_splits = trial[len(splits):]
        splits, work = trial, trial_ways
        next_way += len(new_splits)
        from_way = next(r for k, r, role in members if role == "from")
        via = next(r for k, r, role in members if role == "via")
        to_way = next(r for k, r, role in members if role == "to")
        entries = []
        for spec in specs:
            assert spec["restriction"] in GENERATED_TYPES
            generated.append((next_id, generated_tags(tags, spec["restriction"], ident),
                              [("w", from_way, "from"), ("n", via, "via"), ("w", spec["to_way"], "to")],
                              len(splits)))
            entries.append(dict(spec, id=next_id))
            next_id += 1
        dropped.append(ident)
        copied = sorted(k for k in tags if k not in ("type", "restriction"))
        rewritten.append({"relation": ident, "from_way": from_way, "via_node": via, "to_way": to_way,
                          "u_turn_onto": "same_way" if to_way == from_way else "opposite_carriageway",
                          "tags_preserved": copied, "generated": entries,
                          "split_ways": [s.new_way for s in new_splits],
                          "osm_url": f"https://www.openstreetmap.org/relation/{ident}"})

    # Re-point members for splits made after each relation was planned or read.
    new_relations = [(i, t, resolve_members(m, splits[applied:], original_nodes))
                     for i, t, m, applied in generated]
    relation_edits = {}
    input_members = {r[0]: r[2] for r in kept_inputs}
    drop = set(dropped)
    for ident, _, members in kept_inputs:
        if ident in drop:
            continue
        resolved = resolve_members(members, splits, original_nodes)
        if resolved != list(members):
            relation_edits[ident] = resolved
    for ident in relation_edits:
        for s in skipped:
            if s["relation"] == ident:
                s["members_repointed_to_split_ways"] = True
    ids = [r[0] for r in new_relations]
    if len(ids) != len(set(ids)):
        raise AssertionError("generated relation ids are not unique")
    reasons = {}
    for s in skipped:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    split_records = [{"original_way": s.way, "new_way": s.new_way, "at_node": s.node,
                      "first_part_nodes": len(s.first), "second_part_nodes": len(s.second),
                      "relations_repointed": sorted(
                          i for i in relation_edits
                          if any(k == "w" and ref == s.way for k, ref, _ in input_members[i])),
                      "osm_url": f"https://www.openstreetmap.org/way/{s.way}"} for s in splits]
    report = {
        "schema": 2,
        "restriction": TARGET,
        "engine": "valhalla 3.6.3 (tile builder ignores only_u_turn)",
        "id_base": id_base,
        "way_id_base": way_id_base,
        "counts": {"candidates": len(candidates), "rewritten": len(rewritten), "skipped": len(skipped),
                   "generated_relations": len(new_relations), "split_ways": len(splits),
                   "relations_repointed": len(relation_edits)},
        "skipped_by_reason": dict(sorted(reasons.items())),
        "rewritten": rewritten,
        "skipped": skipped,
        # Routing-graph copy only: these way IDs do not exist in OSM. Consumers judging routes
        # must translate them back to the original OSM way.
        "split_ways": {str(s.new_way): s.way for s in splits},
        "splits": split_records,
        "limitations": [
            "Assumes the OSM relation is correct; signage is not verified.",
            "Only simple node-via relations are rewritten; skipped ones stay unenforced by Valhalla.",
            "Exits on non-motor highways are not prohibited; exits with unknown one-way state are.",
            "An exit way through the via node is split there in the routing copy only (same nodes, "
            "tags and connectivity); the new part's ID is listed in split_ways.",
        ],
    }
    return {"new_relations": new_relations, "dropped": dropped, "relation_edits": relation_edits,
            "way_edits": {s.way: list(s.first) for s in splits},
            "new_ways": [(s.new_way, dict(ways[s.way][0]), list(s.second)) for s in splits],
            "report": report}


def rewrite(relations, ways, coords, max_relation_id=0, id_base=ID_BASE, **kwargs):
    """Plan the rewrite. Returns (new relations, dropped ids, report dict); see ``plan``."""
    result = plan(relations, ways, coords, max_relation_id, id_base, **kwargs)
    return result["new_relations"], result["dropped"], result["report"]


# --------------------------------------------------------------------------- PBF I/O (pyosmium)

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_inputs(pbf):
    """Candidates, highway ways at their via nodes (plus via ways of referencing relations),
    node coordinates, the max relation ID, and every relation referencing a way at a via node."""
    import osmium
    candidates, max_id = [], 0
    for rel in osmium.FileProcessor(str(pbf), osmium.osm.RELATION):
        max_id = max(max_id, rel.id)
        tags = {t.k: t.v for t in rel.tags}
        if is_candidate(tags):
            candidates.append((rel.id, tags, [(m.type, m.ref, m.role) for m in rel.members]))
    vias = {r for _, _, members in candidates for k, r, role in members if role == "via" and k == "n"}
    ways, others = {}, []
    if vias:
        proc = osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway"))
        for way in proc:
            refs = [n.ref for n in way.nodes]
            if vias.intersection(refs):
                ways[way.id] = ({t.k: t.v for t in way.tags}, refs)
        # A way through a via node may be split; every relation that names it must be re-pointed.
        through = {w for w, (_, refs) in ways.items() if vias.intersection(refs[1:-1])}
        candidate_ids = {c[0] for c in candidates}
        if through:
            for rel in osmium.FileProcessor(str(pbf), osmium.osm.RELATION):
                members = [(m.type, m.ref, m.role) for m in rel.members]
                if rel.id not in candidate_ids and any(k == "w" and r in through for k, r, _ in members):
                    others.append((rel.id, {t.k: t.v for t in rel.tags}, members))
        via_ways = {r for _, _, members in others for k, r, role in members
                    if role == "via" and k == "w"} - set(ways)
        if via_ways:
            for way in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(via_ways)):
                ways[way.id] = ({t.k: t.v for t in way.tags}, [n.ref for n in way.nodes])
    wanted = {n for _, nodes in ways.values() for n in nodes} | vias
    coords = {}
    if wanted:
        proc = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(wanted))
        for node in proc:
            if node.location.valid():
                coords[node.id] = (node.location.lat, node.location.lon)
    return candidates, ways, coords, max_id, others


def write_output(src, dst, result, way_id_base=WAY_ID_BASE):
    """Copy ``src`` with the planned edits; refuses if any input way reaches ``way_id_base``."""
    import osmium
    drop = set(result["dropped"])
    way_edits, relation_edits = result["way_edits"], result["relation_edits"]
    pending_ways = sorted(result["new_ways"])
    writer = osmium.SimpleWriter(str(dst), overwrite=True)

    def flush_ways():
        while pending_ways:  # after every input way (higher IDs), before the first relation
            ident, tags, nodes = pending_ways.pop(0)
            writer.add_way(osmium.osm.mutable.Way(id=ident, version=1, tags=tags, nodes=nodes))

    try:
        for obj in osmium.FileProcessor(str(src)):
            if isinstance(obj, osmium.osm.Way):
                if obj.id >= way_id_base:
                    raise ValueError(f"input way id {obj.id} reaches the split way id range {way_id_base}")
                if obj.id in way_edits:
                    nodes = way_edits[obj.id]
                    if [n.ref for n in obj.nodes][:len(nodes)] != nodes:
                        raise AssertionError(f"w{obj.id} changed since it was read")
                    writer.add_way(obj.replace(nodes=nodes))
                    continue
            elif isinstance(obj, osmium.osm.Relation):
                flush_ways()
                if obj.id in drop:
                    continue
                if obj.id in relation_edits:
                    writer.add_relation(obj.replace(members=relation_edits[obj.id]))
                    continue
            writer.add(obj)
        flush_ways()
        for ident, tags, members in result["new_relations"]:  # highest IDs, so order stays sorted
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
    candidates, ways, coords, max_id, others = read_inputs(args.input)
    result = plan(candidates, ways, coords, max_id, others=others,
                  max_way_id=max(ways, default=0))
    write_output(args.input, args.output, result)
    report = result["report"]
    report["input"] = {"path": str(args.input), "sha256": sha256(args.input), "max_relation_id": max_id}
    report["output"] = {"path": str(args.output), "sha256": sha256(args.output)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    c = report["counts"]
    print(f"only_u_turn: {c['candidates']} found, {c['rewritten']} rewritten into "
          f"{c['generated_relations']} no_* relations ({c['split_ways']} ways split at a via node), "
          f"{c['skipped']} skipped {report['skipped_by_reason']}")
    for s in report["skipped"]:
        print(f"::warning::only_u_turn r{s['relation']} not rewritten ({s['reason']}); Valhalla will not enforce it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
