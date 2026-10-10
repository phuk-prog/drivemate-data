"""Resumable, deterministic UK regional verification queue.

Never publishes map payloads. One z8-root area per run, prioritised by
proximity to Greater Manchester; all subdivision children are kept together.
Only signed-off local verification may advance the durable ledger.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

SOURCE_SHA = "8ec2a5cd5e4373a5d75243c1aa46ccb40adb3a8dd9b821f06a3b2c765f9cf069"
MANCHESTER = (126, 82)
NAME = re.compile(r"region-z(8|9|10)-x([0-9]{1,4})-y([0-9]{1,4})\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def region_root(name):
    m = NAME.fullmatch(name)
    if m is None:
        raise ValueError(f"Malformed regional package name: {name}")
    z, x, y = map(int, m.groups())
    if x >= (1 << z) or y >= (1 << z):
        raise ValueError(f"Out-of-grid region: {name}")
    shift = z - 8
    return f"8/{x >> shift}/{y >> shift}"


def validate_plan(plan):
    if (plan.get("schema") != 1 or plan.get("status") != "unpublished"
            or not SHA.fullmatch(plan.get("source_sha256", ""))
            or plan.get("base_zoom_max") != 9
            or plan.get("detail_zoom_min") != 10):
        raise ValueError("Unexpected regional plan structure")
    packages = plan.get("packages")
    if not isinstance(packages, dict) or "base" not in packages:
        raise ValueError("Missing nationwide base package")
    roots = {}
    for name, info in packages.items():
        if not isinstance(info, dict) or not isinstance(info.get("tiles"), int) or info["tiles"] <= 0:
            raise ValueError("Empty or invalid plan package")
        if name == "base":
            continue
        root = region_root(name)
        roots.setdefault(root, []).append(name)
    if not roots:
        raise ValueError("No UK detail regions in plan")
    return {root: sorted(names) for root, names in roots.items()}


def validate_ledger(ledger, source, roots):
    if ledger.get("schema") != 1 or ledger.get("source_sha256") != source:
        raise ValueError("Ledger belongs to a different map generation")
    done = ledger.get("completed", {})
    if not isinstance(done, dict):
        raise ValueError("Invalid completion ledger")
    for root, proof in done.items():
        if root not in roots or not isinstance(proof, dict) or proof.get("passed") is not True:
            raise ValueError(f"Unsubstantiated completion entry: {root}")
        if not isinstance(proof.get("run_url"), str) or not proof["run_url"].startswith(
                "https://github.com/phuk-prog/drivemate-data/actions/runs/"):
            raise ValueError(f"Missing immutable workflow evidence: {root}")
    return done


def order_roots(roots):
    def key(root):
        _, x, y = map(int, root.split("/"))
        dx, dy = abs(x - MANCHESTER[0]), abs(y - MANCHESTER[1])
        return max(dx, dy), dx + dy, dy, dx, y, x
    return sorted(roots, key=key)


def next_region(plan, ledger, request=None):
    roots = validate_plan(plan)
    completed = validate_ledger(ledger, plan["source_sha256"], roots)
    if request is not None:
        sequence = request.get("sequence")
        if (request.get("schema") != 1 or request.get("enabled") is not True
                or type(sequence) is not int or sequence <= ledger.get("last_sequence", 0)):
            raise ValueError("Batch request disabled, repeated or malformed")
    remaining = [r for r in order_roots(roots) if r not in completed]
    if not remaining:
        return {
            "status": "all_validated", "source_sha256": plan["source_sha256"],
            "total_roots": len(roots), "completed_roots": len(completed),
        }
    root = remaining[0]
    return {
        "status": "selected", "source_sha256": plan["source_sha256"],
        "root": root, "packages": roots[root],
        "all_roots": order_roots(roots),
        "sequence": request["sequence"] if request else None,
        "total_roots": len(roots), "completed_roots": len(completed),
        "remaining_roots": len(remaining),
    }


def mark_complete(selection, manifest, ledger, run_url):
    roots = validate_plan_from_selection(selection)
    validate_ledger(ledger, selection["source_sha256"], roots)
    if selection.get("status") != "selected" or manifest.get("schema") != 1:
        raise ValueError("No selected region")
    if (manifest.get("status") != "pilot_unpublished"
            or manifest.get("source_sha256") != selection["source_sha256"]
            or manifest.get("pilot_root") != selection["root"]
            or manifest.get("base_zoom_max") != 9
            or manifest.get("detail_zoom_min") != 10):
        raise ValueError("Mismatched output map generation")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or set(packages) != {"base", *selection["packages"]}:
        raise ValueError("Partial or incorrect output packages")
    for name, info in packages.items():
        if (info.get("verified_tile_payloads") != info.get("tiles")
                or not isinstance(info.get("tiles"), int) or info["tiles"] < 1
                or not isinstance(info.get("bytes"), int) or info["bytes"] < 127
                or not SHA.fullmatch(info.get("sha256", ""))):
            raise ValueError(f"Package missing complete independent verification: {name}")
        if name != "base" and info["bytes"] > 200_000_000:
            raise ValueError("Oversize detailed package")
    if not run_url.startswith("https://github.com/phuk-prog/drivemate-data/actions/runs/"):
        raise ValueError("Invalid workflow evidence URL")
    prior = ledger["completed"].get(selection["root"])
    proof = {
        "passed": True, "run_url": run_url,
        "packages": {name: {"sha256": info["sha256"], "bytes": info["bytes"],
                            "tiles": info["tiles"]} for name, info in sorted(packages.items())},
    }
    if prior is not None:
        raise ValueError("Region already committed; refuse accidental overwrite")
    updated = json.loads(json.dumps(ledger))
    updated["completed"][selection["root"]] = proof
    sequence = selection.get("sequence")
    if sequence is not None:
        if type(sequence) is not int or sequence <= ledger.get("last_sequence",0):
            raise ValueError("Repeated batch request")
        updated["last_sequence"] = sequence
    return updated


def validate_plan_from_selection(selection):
    if not SHA.fullmatch(selection.get("source_sha256", "")):
        raise ValueError("Bad plan SHA")
    root = selection.get("root")
    packages = selection.get("packages")
    if not isinstance(root, str) or not isinstance(packages, list) or not packages:
        raise ValueError("Bad queue selection")
    all_roots = selection.get("all_roots")
    if (not isinstance(all_roots, list) or root not in all_roots
            or len(set(all_roots)) != len(all_roots)):
        raise ValueError("Missing global region inventory")
    if any(region_root(n) != root for n in packages):
        raise ValueError("Selected packages cross a root boundary")
    for other in all_roots:
        parts = other.split("/")
        if (len(parts) != 3 or parts[0] != "8" or
                any(not n.isdigit() or int(n) >= 256 for n in parts[1:])):
            raise ValueError("Invalid global region inventory")
    return {root: packages, **{x: [] for x in all_roots if x != root}}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="command", required=True)
    a = cmds.add_parser("next")
    a.add_argument("--plan", required=True)
    a.add_argument("--ledger", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--request", help="Scheduled run request and replay gate")
    b = cmds.add_parser("complete")
    b.add_argument("--selection", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--ledger", required=True)
    b.add_argument("--output", required=True)
    b.add_argument("--run-url", required=True)
    args = parser.parse_args()
    if args.command == "next":
        plan = json.loads(Path(args.plan).read_text())
        ledger = json.loads(Path(args.ledger).read_text())
        request = json.loads(Path(args.request).read_text()) if args.request else None
        result = next_region(plan, ledger, request)
    else:
        selection = json.loads(Path(args.selection).read_text())
        ledger = json.loads(Path(args.ledger).read_text())
        manifest = json.loads(Path(args.manifest).read_text())
        result = mark_complete(selection, manifest, ledger, args.run_url)
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
