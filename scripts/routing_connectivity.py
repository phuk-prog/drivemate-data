"""Extra real-graph UK driving connectivity probes, not a legality audit.

The six existing required journeys remain authoritative release smoke gates.
These diagnostic cases survey more UK regions; a failure is reported clearly
as a candidate network or endpoint-matching gap for investigation, NOT an
automatic OSM correction. Do not treat a passing route as proof of legal turns.
"""
import argparse
import json
import math
from pathlib import Path
import tempfile

# Different long-distance corridors, cross-border routes and nations.
EXTRA_PROBES = {
    "Leeds–York": ((53.7996, -1.5491), (53.9591, -1.0815)),
    "Cardiff–Swansea": ((51.4816, -3.1791), (51.6214, -3.9436)),
    "Edinburgh–Glasgow": ((55.9533, -3.1883), (55.8642, -4.2518)),
    "Aberdeen–Inverness": ((57.1497, -2.0943), (57.4778, -4.2247)),
    "Derry–Belfast": ((54.9970, -7.3190), (54.5973, -5.9301)),
    "London–Brighton": ((51.5074, -0.1278), (50.8225, -0.1372)),
    "Bristol–Exeter": ((51.4545, -2.5879), (50.7184, -3.5339)),
    "Norwich–Ipswich": ((52.6309, 1.2974), (52.0567, 1.1482)),
    "Newcastle–Carlisle": ((54.9783, -1.6178), (54.8925, -2.9329)),
    "Wrexham–Chester": ((53.0466, -2.9925), (53.1934, -2.8931)),
    "Belfast–Newry": ((54.5973, -5.9301), (54.1766, -6.3391)),
}


def crow_km(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    v = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(max(0.0, v))))


def check_route(actor, name, start, end):
    direct = crow_km(start, end)
    request = {"locations": [{"lat": start[0], "lon": start[1]},
                             {"lat": end[0], "lon": end[1]}],
               "costing": "auto", "units": "kilometers"}
    result = {"name": name, "straight_km": round(direct, 2)}
    try:
        response = json.loads(actor.route(json.dumps(request)))
        trip = response.get("trip") if isinstance(response, dict) else None
        summary = trip.get("summary") if isinstance(trip, dict) else None
        length = summary.get("length") if isinstance(summary, dict) else None
        if type(length) not in (int, float) or not math.isfinite(length):
            raise ValueError("No finite route length returned")
        result["road_km"] = round(length, 2)
        if not (direct <= length <= 4 * direct):
            raise ValueError("Route length implausible relative to endpoints")
        result["status"] = "route_found"
    except (ValueError, KeyError, TypeError, RuntimeError, OverflowError) as exc:
        result["status"] = "investigate"
        result["reason"] = (str(exc) or type(exc).__name__)[:180]
    return result


def evaluate(actor, probes=EXTRA_PROBES):
    cases = [check_route(actor, name, start, end)
             for name, (start, end) in probes.items()]
    return {
        "scope": "Sampled offline routing connections, not complete UK graph or legal correctness",
        "checked": len(cases),
        "route_found": sum(c["status"] == "route_found" for c in cases),
        "investigate": sum(c["status"] != "route_found" for c in cases),
        "cases": cases,
        "limitations": [
            "Endpoint snapping may differ; sample failures are diagnostic, not proof of a missing road.",
            "Passing probes cannot establish every connected component, legal turn or regional boundary.",
            "This diagnostic report does not authorise new junction geometry or legal restrictions.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--graph", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    from valhalla import Actor, get_config
    graph = Path(args.graph)
    if not graph.is_file():
        raise ValueError("Cannot test missing UK graph")
    # pyvalhalla resolves tile_dir strictly even when using a tile extract.
    # Do not depend on a caller having created a neighbouring empty directory.
    with tempfile.TemporaryDirectory(prefix='drivemate-connectivity-') as directory:
        actor = Actor(get_config(tile_extract=str(graph), tile_dir=directory,
                                 verbose=False))
        report = evaluate(actor)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    print(f"Extra UK connectivity diagnostics: {report['route_found']}/{report['checked']} routes found; "
          f"{report['investigate']} need investigation.")
    for item in report["cases"]:
        if item["status"] != "route_found":
            print("::warning::Connectivity probe: " + item["name"] + ": " + item["reason"])


if __name__ == "__main__":
    main()
