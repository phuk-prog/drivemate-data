"""OSM turn-restriction relation *diagnostics*, not permission to perform a turn.

Uses Osmium OPL with highway ways and type=restriction relations. Reports
missing member references, questionable shared via-node/way geometry, and
possible explicit-oneway orientation conflicts. Never edits or repairs routes.
Access, exceptions, conditional rules, implicit restrictions, and signs must
still be verified by the router and independent ground truth.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from junction_topology import parse_way, unescape

MEMBER = re.compile(r"([nwr])([0-9]+)@(.*)\Z")
RELATION_ID = re.compile(r"r([0-9]+)\Z")
SAMPLE_LIMIT = 25


def parse_relation(line):
    parts = line.strip().split()
    if not parts or not parts[0].startswith("r"):
        return None
    found = RELATION_ID.fullmatch(parts[0])
    if not found:
        raise ValueError("Malformed OSM relation ID")
    tags_raw = next((part[1:] for part in parts[1:] if part.startswith("T")), "")
    member_raw = next((part[1:] for part in parts[1:] if part.startswith("M")), "")
    tags = {}
    for item in tags_raw.split(","):
        if item:
            if "=" not in item:
                raise ValueError("Malformed OSM relation tag")
            key, value = item.split("=", 1)
            tags[unescape(key)] = unescape(value)
    if tags.get("type") != "restriction":
        return None
    members = []
    for item in member_raw.split(","):
        if not item:
            continue
        match = MEMBER.fullmatch(item)
        if match is None:
            raise ValueError("Malformed restriction relation member")
        kind, ident, role = match.groups()
        members.append((kind, int(ident), unescape(role)))
    return int(found.group(1)), tags, members


def load_ways(lines):
    """Only explicitly recognised road classes are considered navigable."""
    ways = {}
    for line in lines:
        parsed = parse_way(line)
        if parsed is None:
            continue
        wid, tags, nodes = parsed
        if wid in ways:
            raise ValueError(f"Duplicate OSM way {wid}")
        ways[wid] = (tags, nodes)
    return ways


def member_ways(members, role):
    return [ident for kind, ident, r in members if r == role and kind == "w"]


def evaluate_relation(relation, ways):
    ident, tags, members = relation
    reasons = []
    kind = tags.get("restriction")
    vehicles = [k for k in tags if k.startswith("restriction:")]
    conditional = any(k.endswith(":conditional") for k in vehicles)
    excepted = {v.strip() for v in tags.get("except", "").split(";")}
    protected = bool(excepted.intersection({"motorcar", "motor_vehicle", "vehicle", "car"}))
    froms, tos, vias = member_ways(members, "from"), member_ways(members, "to"), [
        (k, n) for k, n, r in members if r == "via"
    ]
    # The no_entry/no_exit forms legitimately support multiple from/to members.
    if not froms or not tos or not vias:
        reasons.append("missing_required_role")
    if len(froms) > 1 and kind != "no_entry":
        reasons.append("multiple_from_members")
    if len(tos) > 1 and kind != "no_exit":
        reasons.append("multiple_to_members")
    if any(r == "from" and t != "w" or r == "to" and t != "w" for t, _, r in members):
        reasons.append("unexpected_member_type")
    if not kind and not vehicles:
        reasons.append("unknown_restriction_value")
    elif kind and not (kind.startswith("no_") or kind.startswith("only_")):
        reasons.append("unrecognised_restriction_value")
    via_nodes = [n for t, n in vias if t == "n"]
    via_ways = [n for t, n in vias if t == "w"]
    if (len(via_nodes) > 1 or (via_nodes and via_ways)
        or any(t not in ("n", "w") for t, _ in vias)):
        reasons.append("complex_via_members")
    roads = froms + tos + via_ways
    missing = sorted(set(n for n in roads if n not in ways))
    if missing:
        reasons.append("referenced_road_not_in_sample")
    if not missing and len(via_nodes) == 1 and not via_ways:
        via = via_nodes[0]
        for label, references in (("from", froms), ("to", tos)):
            if any(via not in ways[wid][1] for wid in references):
                reasons.append(label + "_way_does_not_touch_via")
        # Only check explicit oneway orientation where we know this is a
        # simple, unconditional motorcar-relevant relation and the via node
        # is the end of both ways. Access and conditional tags are *not*
        # evaluated here, so these are review flags, never legal assertions.
        if len(froms) == 1 and len(tos) == 1 and not conditional and not protected:
            for role, wid in (("from", froms[0]), ("to", tos[0])):
                t, nodes = ways[wid]
                value = t.get("oneway")
                if value is None and t.get("junction") == "roundabout":
                    value = "yes"
                if value not in {"yes", "1", "true", "-1"}:
                    continue
                expected = (nodes[-1] if value in ("yes", "1", "true") else nodes[0]) if role == "from" else (
                    nodes[0] if value in ("yes", "1", "true") else nodes[-1]
                )
                if via not in (nodes[0], nodes[-1]):
                    reasons.append(role + "_oneway_via_is_internal_node")
                elif expected != via:
                    reasons.append(role + "_possible_oneway_orientation_conflict")
    elif not missing and via_ways and not via_nodes and len(froms) == 1 and len(tos) == 1:
        # Via-way restrictions are valid. Only verify topological contact,
        # with no assumption about turn permissions or legally allowed entry.
        first, last = ways[via_ways[0]][1], ways[via_ways[-1]][1]
        if not set(ways[froms[0]][1]).intersection(first):
            reasons.append("from_way_disconnected_from_via_way")
        if not set(ways[tos[0]][1]).intersection(last):
            reasons.append("to_way_disconnected_from_via_way")
        for a, b in zip(via_ways, via_ways[1:]):
            if not set(ways[a][1]).intersection(ways[b][1]):
                reasons.append("via_way_chain_disconnected")
    elif via_ways and via_nodes:
        # Combination is not automatically invalid; needs an expert.
        pass
    # Duplicate flags never give additional useful evidence.
    reasons = list(dict.fromkeys(reasons))
    return {
        "relation": ident, "restriction": kind,
        "conditional": conditional, "motorcar_exception": protected,
        "via": "way" if via_ways and not via_nodes else ("node" if via_nodes and not via_ways else "complex"),
        "review_reasons": reasons,
        "missing_sample_way_ids": missing[:8],
    }


def audit(way_lines, relation_lines, region):
    ways = load_ways(way_lines)
    total = 0
    counts = Counter()
    examples = []
    seen = set()
    for line in relation_lines:
        parsed = parse_relation(line)
        if parsed is None:
            continue
        if parsed[0] in seen:
            raise ValueError("Duplicate restriction relation ID")
        seen.add(parsed[0])
        total += 1
        result = evaluate_relation(parsed, ways)
        counts[result["via"] + "_via"] += 1
        if result["conditional"]:
            counts["conditional_relations"] += 1
        if result["motorcar_exception"]:
            counts["motorcar_exceptions"] += 1
        if result["review_reasons"]:
            counts["needs_review"] += 1
            for reason in result["review_reasons"]:
                counts["flag_" + reason] += 1
            if len(examples) < SAMPLE_LIMIT:
                examples.append(result)
    return {
        "schema": 1, "region": region, "road_ways_in_sample": len(ways),
        "restriction_relations": total, "counts": dict(sorted(counts.items())),
        "examples": examples,
        "scope": "OSM relation-reference diagnostics only; NOT legal-turn proof or routing-engine acceptance",
        "limitations": [
            "Sample edges and missing OSM references may mimic broken relations.",
            "One-way, access, conditional and vehicle exceptions require full routing semantics.",
            "Crossing road geometry never creates a junction without a shared OSM node.",
            "No restrictions or lane connections are invented, altered or uploaded to OpenStreetMap.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ways", type=Path, required=True)
    p.add_argument("--relations", type=Path, required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    for path in (args.ways, args.relations):
        if not path.is_file():
            p.error("Required OPL input not found")
    with args.ways.open("rt", encoding="utf-8") as ways, args.relations.open("rt", encoding="utf-8") as rels:
        report = audit(ways, rels, args.region)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"### OSM turn restrictions in {args.region}")
    print(f"- Road ways sampled: {report['road_ways_in_sample']:,}")
    print(f"- Restriction relations: {report['restriction_relations']:,}")
    print(f"- Relations needing review: {report['counts'].get('needs_review', 0):,}")
    print("- These checks do not establish or authorise legal turns.")


if __name__ == "__main__":
    main()
