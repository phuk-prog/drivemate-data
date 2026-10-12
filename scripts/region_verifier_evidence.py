"""Fail-closed reconciliation of regional PMTiles manifests with full verifier reports.

The exporter compares every copied payload to the original; verify_pmtiles.py
independently decodes each emitted archive. This gate binds those checks to
exact package names, hashes, sizes and addressed tile counts before ledger entry.
It neither publishes map data nor establishes road/legal ground truth.
"""
import argparse
import json
import re
from pathlib import Path

PACKAGE = re.compile(r"(?:base|region-z(?:8|9|10)-x[0-9]{1,4}-y[0-9]{1,4})\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def reconcile(manifest, evidence_dir, index):
    if manifest.get("schema") != 1 or manifest.get("status") != "pilot_unpublished":
        raise ValueError("Expected unpublished regional pilot manifest")
    source = manifest.get("source_sha256")
    if not isinstance(source, str) or not SHA256.fullmatch(source):
        raise ValueError("Invalid source generation fingerprint")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or len(packages) < 2 or "base" not in packages:
        raise ValueError("Missing base or regional packages")
    if type(index) is not int or index < 1:
        raise ValueError("Invalid batch index")
    evidence_dir = Path(evidence_dir)
    expected = set()
    summary = {}
    for name, info in sorted(packages.items()):
        if not PACKAGE.fullmatch(name) or not isinstance(info, dict):
            raise ValueError("Invalid package name or metadata")
        report_name = f"{index}-{name}.json"
        expected.add(report_name)
        report_path = evidence_dir / report_name
        if report_path.is_symlink() or not report_path.is_file():
            raise ValueError(f"Missing independent verification: {name}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("errors") != []:
            raise ValueError(f"PMTiles verifier reported errors: {name}")
        sha = info.get("sha256")
        tiles = info.get("tiles")
        size = info.get("bytes")
        if (not isinstance(sha, str) or not SHA256.fullmatch(sha)
                or type(tiles) is not int or tiles < 1
                or type(size) is not int or size < 127
                or type(info.get("verified_tile_payloads")) is not int
                or info["verified_tile_payloads"] != tiles):
            raise ValueError(f"Invalid exporter verification: {name}")
        if (report.get("sha256") != sha or report.get("bytes") != size
                or report.get("addressed_tiles_checked") != tiles
                or type(report.get("physical_contents_checked")) is not int
                or report["physical_contents_checked"] < 1
                or type(report.get("tile_entries_checked")) is not int
                or report["tile_entries_checked"] < 1
                or type(report.get("directory_blocks_checked")) is not int
                or report["directory_blocks_checked"] < 1):
            raise ValueError(f"Exporter and independent verifier disagree: {name}")
        summary[name] = {"sha256": sha, "bytes": size, "tiles": tiles}
    actual = {p.name for p in evidence_dir.glob(f"{index}-*.json")
              if p.name != f"{index}-regional-manifest.json"}
    if actual != expected:
        raise ValueError("Missing or unexpected package verification reports")
    return {"status": "verified_unpublished", "source_sha256": source,
            "pilot_root": manifest.get("pilot_root"), "packages": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--index", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = reconcile(json.loads(args.manifest.read_text(encoding="utf-8")),
                        args.evidence_dir, args.index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
