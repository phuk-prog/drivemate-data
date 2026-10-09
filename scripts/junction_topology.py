"""Read-only OSM road connectivity diagnostics using *shared node IDs*, not pixels.

Consumes Osmium OPL way records with Nn123,n456 references. It does NOT
invent missing connections or assess permission to turn, live restrictions,
legal access or geometric crossings between different OSM nodes.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link", "unclassified", "residential", "living_street",
    "service", "track", "road",
}
MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link",
         "trunk_link", "primary_link", "secondary_link"}
NON_SUSPICIOUS_END = {"service", "track", "residential", "living_street",
                      "unclassified", "road"}
ENC = re.compile(r"%([0-9a-fA-F]{1,6})%")
REF = re.compile(r"n([0-9]+)(?:x[-+0-9.eE]+y[-+0-9.eE]+)?")
LIMIT = 20


def unescape(raw):
    return ENC.sub(lambda m: chr(int(m.group(1), 16)), raw)


def parse_way(line):
    """Return (way_id, tags, node_ids) or None for nodes/relations/blank lines."""
    fields = line.strip().split()
    if not fields or not fields[0].startswith("w"):
        return None
    if not re.fullmatch(r"w[0-9]+", fields[0]):
        raise ValueError("Malformed OPL way identifier")
    rawtags = next((field[1:] for field in fields[1:] if field.startswith("T")), "")
    rawrefs = next((field[1:] for field in fields[1:] if field.startswith("N")), "")
    tags = {}
    for pair in rawtags.split(","):
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError("Malformed OPL way tag")
        key, val = pair.split("=", 1)
        tags[unescape(key)] = unescape(val)
    if tags.get("highway") not in ROAD_CLASSES:
        return None
    refs = []
    for rawref in rawrefs.split(","):
        match = REF.fullmatch(rawref)
        if not match:
            raise ValueError(f"Way {fields[0]} contains invalid node reference")
        refs.append(int(match.group(1)))
    if len(refs) < 2:
        raise ValueError(f"Way {fields[0]} has fewer than two node references")
    return int(fields[0][1:]), tags, refs


def level_signature(tags):
    """Explicit mapping-level labels; missing level stays unknown."""
    layer = tags.get("layer")
    parsed = None
    if layer is not None and re.fullmatch(r"-?[0-9]+", layer):
        parsed = int(layer)
    bridge = tags.get("bridge") not in (None, "no", "0", "false")
    tunnel = tags.get("tunnel") not in (None, "no", "0", "false")
    return parsed, bridge, tunnel


def incompatible(a, b):
    """Potential mismatch, not a legal judgment or correction instruction."""
    la, ba, ta = a
    lb, bb, tb = b
    if la is not None and lb is not None and la != lb:
        return True
    return (ba and tb) or (bb and ta)


def analyze(lines, region="sample", minimum_ways=0):
    ways = {}
    positions = defaultdict(list)
    adjacency_count = Counter()
    classes = Counter()
    examples = {"malformed_segment": [], "possible_level_conflict": [],
                "major_road_end": []}
    for raw in lines:
        item = parse_way(raw)
        if item is None:
            continue
        wid, tags, refs = item
        if wid in ways:
            raise ValueError("Duplicate OSM road way ID")
        ways[wid] = (tags, refs)
        classes[tags["highway"]] += 1
        for index, node in enumerate(refs):
            # Single node shared by a bridge and a ground road is not proof
            # that the roads connect at-grade.
            positions[node].append((wid, index not in (0, len(refs)-1)))
        for a, b in zip(refs, refs[1:]):
            if a == b:
                if len(examples["malformed_segment"]) < LIMIT:
                    examples["malformed_segment"].append({"way": wid, "node": a})
                continue
            adjacency_count[a] += 1
            adjacency_count[b] += 1

    if len(ways) < minimum_ways:
        raise ValueError(f"Insufficient road ways for {region}: {len(ways)} < {minimum_ways}")

    parent = {wid: wid for wid in ways}
    def find(wid):
        while parent[wid] != wid:
            parent[wid] = parent[parent[wid]]
            wid = parent[wid]
        return wid

    for node, members in positions.items():
        if len(members) < 2:
            continue
        # Dedupe a way that contains the same node more than once.
        unique = list(dict.fromkeys(wid for wid, _ in members))
        for idx, wid in enumerate(unique):
            for other in unique[:idx]:
                first = (ways[wid][0], any(w == wid and inside for w, inside in members))
                second = (ways[other][0], any(w == other and inside for w, inside in members))
                conflict = incompatible(level_signature(first[0]), level_signature(second[0]))
                if conflict and first[1] and second[1]:
                    if len(examples["possible_level_conflict"]) < LIMIT:
                        examples["possible_level_conflict"].append(
                            {"node": node, "ways": sorted([wid, other]),
                             "layers": [first[0].get("layer"), second[0].get("layer")],
                             "note": "Two interior roads share OSM node but carry potentially conflicting levels"})
                    # Treat as a potential data error, never an automatically
                    # validated junction or a reason to author a new turn.
                    continue
                a, b = find(wid), find(other)
                if a != b:
                    parent[max(a, b)] = min(a, b)

    component_sizes = Counter(find(wid) for wid in ways)
    possible_ends = 0
    known_dead_ends = 0
    for wid, (tags, refs) in ways.items():
        for node in set([refs[0], refs[-1]]):
            if adjacency_count[node] != 1:
                continue
            if (tags["highway"] in NON_SUSPICIOUS_END or
                tags.get("noexit") == "yes" or tags.get("access") in ("private", "no") or
                tags.get("motor_vehicle") in ("private", "no")):
                known_dead_ends += 1
                continue
            if tags["highway"] in MAJOR:
                possible_ends += 1
                if len(examples["major_road_end"]) < LIMIT:
                    examples["major_road_end"].append(
                        {"node": node, "way": wid, "highway": tags["highway"],
                         "note": "Sample-border or legitimate dead-end possible; review, not a broken-road claim"})

    return {
        "schema": 1,
        "region": region,
        "method": "Shared OpenStreetMap node IDs in a bounded sample; not line crossing or turn legality",
        "road_ways": len(ways),
        "junction_nodes": sum(len({w for w, _ in m}) > 1 for m in positions.values()),
        "components": len(component_sizes),
        "largest_component_ways": max(component_sizes.values(), default=0),
        "components_with_at_most_two_ways": sum(size <= 2 for size in component_sizes.values()),
        "sampled_road_classes": dict(sorted(classes.items())),
        "possible_major_road_ends": possible_ends,
        "ordinary_or_explicit_dead_ends": known_dead_ends,
        "potential_level_conflicts_shown": len(examples["possible_level_conflict"]),
        "malformed_segments_shown": len(examples["malformed_segment"]),
        "examples": examples,
        "limitations": [
            "Road ends and isolated components at extract boundaries are often legitimate.",
            "Bridges, tunnels and surface roads can cross at different levels without sharing a node.",
            "An OSM node shared at an approach or bridge end is not automatically illegal.",
            "Shared nodes do not establish turn permission; restrictions and vehicle access are not evaluated.",
            "Small components and major-road ends are review candidates, never automatic corrections.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opl", type=Path, required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--minimum-ways", type=int, default=100)
    a = p.parse_args()
    if a.minimum_ways < 1 or not a.opl.is_file():
        p.error("Missing OPL sample or invalid minimum")
    with a.opl.open("rt", encoding="utf-8") as stream:
        doc = analyze(stream, region=a.region, minimum_ways=a.minimum_ways)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{a.region}: {doc['road_ways']} mapped road ways, "
          f"{doc['components']} OSM-node components, "
          f"{doc['possible_major_road_ends']} major-road endpoint candidates, "
          f"{doc['potential_level_conflicts_shown']} shown level conflicts. "
          "Diagnostic only; no repairs or new connections.")


if __name__ == "__main__":
    main()
