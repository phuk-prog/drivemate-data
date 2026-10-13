"""Conservative change planner; does not fetch, build, publish, or verify map payloads.

Catalog: {schema: 1, pipeline: SHA256, regions: [{id, url, sha256}]}.
State: {schema: 1, verified: true, regions: {id: {url, sha256, pipeline}}}.
Only a separate builder's matching verified receipts can advance state.
"""
import argparse
import copy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[a-z0-9][a-z0-9_-]{0,100}\Z")


def fingerprint(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("Expected a lowercase SHA-256 fingerprint")
    return value


def source_url(value):
    if not isinstance(value, str):
        raise ValueError("Source URL must be a string")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "download.geofabrik.de"
            or parsed.query or parsed.fragment or not parsed.path.endswith(".osm.pbf")
            or not parsed.path.startswith("/") or "%" in parsed.path
            or any(p in (".", "..", "") for p in parsed.path.split("/")[1:])
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", parsed.path)
            or value != "https://download.geofabrik.de" + parsed.path):
        raise ValueError("Only canonical HTTPS download.geofabrik.de OSM PBF URLs are allowed")
    return value


def region_id(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("Invalid region ID")
    return value


def validate_state(state):
    if type(state.get("schema")) is not int or state["schema"] != 1 or state.get("verified") is not True:
        raise ValueError("Previous state must have supported schema and verified=true")
    if not isinstance(state.get("regions"), dict):
        raise ValueError("State regions must be an object")
    for ident, record in state["regions"].items():
        region_id(ident)
        source_url(record["url"])
        fingerprint(record["sha256"])
        fingerprint(record["pipeline"])
    return state


def empty_state():
    return {"schema": 1, "verified": True, "regions": {}}


def plan_updates(catalog, previous=None, priorities=(), budget=1):
    if type(budget) is not int or not 1 <= budget <= 100:
        raise ValueError("Budget must be between 1 and 100 regions")
    previous = validate_state(previous if previous is not None else empty_state())
    if (type(catalog.get("schema")) is not int or catalog["schema"] != 1
            or not isinstance(catalog.get("regions"), list) or not catalog["regions"]):
        raise ValueError("Unsupported source catalog")
    pipeline = fingerprint(catalog["pipeline"])
    current = {}
    for record in catalog["regions"]:
        ident = region_id(record["id"])
        if ident in current:
            raise ValueError("Duplicate catalog region")
        current[ident] = {"url": source_url(record["url"]),
                          "sha256": fingerprint(record["sha256"]), "pipeline": pipeline}
    ordered_priorities = list(dict.fromkeys(region_id(i) for i in priorities))
    blockers = [{"id": i, "reason": "previously verified source missing from catalog"}
                for i in sorted(previous["regions"].keys() - current.keys())]
    blockers += [{"id": i, "reason": "priority source missing from catalog"}
                 for i in ordered_priorities if i not in current]
    changed, unchanged = [], []
    for ident in sorted(current):
        record = current[ident]
        old = previous["regions"].get(ident)
        reasons = ["new source"] if old is None else [
            label for key, label in (("url", "source URL changed"),
                                    ("sha256", "source content changed"),
                                    ("pipeline", "pipeline or schema changed")) if old[key] != record[key]]
        if reasons:
            changed.append({"id": ident, **record, "reasons": reasons})
        else:
            unchanged.append(ident)
    rank = {ident: idx for idx, ident in enumerate(ordered_priorities)}
    changed.sort(key=lambda r: (rank.get(r["id"], len(rank)), r["id"]))
    # A missing old source is not an empty extract and must not silently remove coverage.
    selected = [] if blockers else changed[:budget]
    return {"schema": 1, "blocked": bool(blockers), "blockers": blockers,
            "budget": budget, "selected": selected,
            "deferred": changed if blockers else changed[budget:], "unchanged": unchanged,
            "previous": copy.deepcopy(previous)}


def advance_checkpoint(plan, receipts):
    """Apply externally verified successes only; failed/deferred regions keep old state.

    Receipts: {schema: 1, regions: [{id, verified, url, sha256, pipeline}]}.
    This validates receipt identity, not the underlying builder's evidence.
    """
    if (type(plan.get("schema")) is not int or plan["schema"] != 1
            or type(receipts.get("schema")) is not int or receipts["schema"] != 1):
        raise ValueError("Unsupported plan or receipt schema")
    state = copy.deepcopy(validate_state(plan["previous"]))
    if plan.get("blocked") is not False or plan.get("blockers"):
        raise ValueError("Blocked plans cannot advance a checkpoint")
    selected = {record["id"]: record for record in plan["selected"]}
    if not isinstance(receipts.get("regions"), list):
        raise ValueError("Receipt regions must be a list")
    seen = set()
    for receipt in receipts["regions"]:
        ident = region_id(receipt["id"])
        if ident in seen or ident not in selected:
            raise ValueError("Receipt is duplicate or outside the selected budget")
        seen.add(ident)
        if receipt.get("verified") is not True:
            continue
        record = selected[ident]
        candidate = {"url": source_url(receipt["url"]),
                     "sha256": fingerprint(receipt["sha256"]),
                     "pipeline": fingerprint(receipt["pipeline"])}
        if any(candidate[key] != record[key] for key in candidate):
            raise ValueError("Receipt does not match the planned source and pipeline")
        state["regions"][ident] = candidate
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--catalog", type=Path, required=True)
    planning.add_argument("--state", type=Path)
    planning.add_argument("--priority", action="append", default=[])
    planning.add_argument("--budget", type=int, default=1)
    planning.add_argument("--output", type=Path, required=True)
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--plan", type=Path, required=True)
    checkpoint.add_argument("--receipts", type=Path, required=True)
    checkpoint.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        def read(path):
            return json.loads(path.read_text(encoding="utf-8"))
        if args.command == "plan":
            result = plan_updates(read(args.catalog), read(args.state) if args.state else None,
                                  args.priority, args.budget)
        else:
            result = advance_checkpoint(read(args.plan), read(args.receipts))
        # Validate completely before writing. Preserve an existing output on every error.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".part")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        return 2 if result.get("blocked") else 0
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        parser.exit(1, f"daily map planner: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
