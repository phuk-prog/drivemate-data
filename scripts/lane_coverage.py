"""How many motorway/trunk exits could show lane guidance from OSM data alone?

For each diverge (a *_link leaving a motorway or trunk carriageway) it classifies:
  arrows         turn:lanes on the approach: lanes can be shown exactly as tagged
  counts_add_up  lanes before = lanes continuing + lanes on the slip: exit lanes follow exactly
  inconsistent   all counts known but they don't add up (lane drop/gain or a shared lane)
  missing        a lane count is missing
Informational only: it never fills gaps or guesses lanes.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import restriction_acceptance as ra  # noqa: E402

MAIN = {"motorway", "trunk"}


def lanes(tags):
    try:
        n = int(tags.get("lanes", ""))
    except ValueError:
        return None
    return n if 1 <= n <= 10 else None


def classify(ways):
    starts, ends = defaultdict(list), defaultdict(list)
    for wid, (tags, nodes) in ways.items():
        if len(nodes) >= 2:
            starts[nodes[0]].append(wid)
            ends[nodes[-1]].append(wid)
    results = []
    for node, outgoing in starts.items():
        links = [w for w in outgoing if ways[w][0].get("highway") in ("motorway_link", "trunk_link")]
        mains_out = [w for w in outgoing if ways[w][0].get("highway") in MAIN]
        mains_in = [w for w in ends.get(node, []) if ways[w][0].get("highway") in MAIN]
        if len(links) != 1 or len(mains_out) != 1 or len(mains_in) != 1:
            continue
        before_tags = ways[mains_in[0]][0]
        before, after, slip = lanes(before_tags), lanes(ways[mains_out[0]][0]), lanes(ways[links[0]][0])
        if any(k.startswith("turn:lanes") for k in before_tags):
            status = "arrows"
        elif None in (before, after, slip):
            status = "missing"
        elif before == after + slip:
            status = "counts_add_up"
        else:
            status = "inconsistent"
        results.append({"node": node, "status": status, "road": before_tags.get("ref", ""),
                        "lanes_before": before, "lanes_after": after, "lanes_slip": slip,
                        "approach_way": mains_in[0], "slip_way": links[0],
                        "osm_url": f"https://www.openstreetmap.org/node/{node}"})
    return results


def summarise(results):
    counts = Counter(r["status"] for r in results)
    total = len(results)
    usable = counts["arrows"] + counts["counts_add_up"]
    return {"exits": total, "counts": dict(counts),
            "usable_for_lane_guidance": usable,
            "usable_percent": round(100.0 * usable / total, 1) if total else 0.0}


def markdown(summary, results):
    lines = ["### Lane guidance coverage at motorway/trunk exits (OSM only)", "",
             f"Exits found: **{summary['exits']}**, usable for lane guidance: "
             f"**{summary['usable_for_lane_guidance']} ({summary['usable_percent']}%)**", "",
             "| Status | Exits |", "|---|---:|"]
    for key in ("arrows", "counts_add_up", "inconsistent", "missing"):
        lines.append(f"| {key} | {summary['counts'].get(key, 0)} |")
    roads = Counter((r["road"] or "?", r["status"]) for r in results)
    lines += ["", "| Road | Status | Exits |", "|---|---|---:|"]
    lines += [f"| {road} | {status} | {n} |" for (road, status), n in sorted(roads.items())]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pbf", type=Path, required=True)
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--summary", type=Path)
    a = p.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        opl = Path(tmp) / "roads.opl"
        ra.pbf_to_opl(a.pbf, opl)
        ways, _ = ra.read_opl(opl)
    results = classify(ways)
    summary = summarise(results)
    a.json.write_text(json.dumps({"summary": summary, "exits": results}, indent=1) + "\n")
    text = markdown(summary, results)
    if a.summary:
        with a.summary.open("a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
