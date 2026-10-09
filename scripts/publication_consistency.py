"""Bind a passed map quality report to the exact assets later published.

The quality report and its Markdown rendering are excluded because they are
generated *after* the snapshot. All other files must be present, named
uniquely, and byte-for-byte unchanged at the publisher's pre-upload gate.

A matching SHA-256 does NOT verify data licensing, map content accuracy,
signatures, or independence of the build runner.
"""
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 1
EXCLUDED = {"build-quality.json", "build-quality.md"}
SHA256 = re.compile(r"[0-9a-f]{64}")


def snapshot_assets(directory):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe or missing map build output")
    result = {}
    for entry in sorted(root.rglob("*")):
        if entry.is_symlink():
            raise ValueError("Symlink in map assets")
        if not entry.is_file() or entry.name in EXCLUDED:
            continue
        if entry.name in result:
            raise ValueError("Duplicate map asset basename")
        if entry.stat().st_size <= 0:
            raise ValueError("Empty map asset")
        sha = hashlib.sha256()
        with entry.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        result[entry.name] = {"bytes": entry.stat().st_size, "sha256": sha.hexdigest()}
    if not result:
        raise ValueError("Empty build asset inventory")
    return {"schema": SCHEMA, "files": result}


def verify_snapshot(directory, report):
    """Fail before any remote upload if assets changed since quality checks."""
    if not isinstance(report, dict) or report.get("errors") != []:
        raise ValueError("Missing or failing quality report")
    expected = report.get("asset_snapshot")
    if not isinstance(expected, dict) or expected.get("schema") != SCHEMA:
        raise ValueError("Missing or unsupported quality asset snapshot")
    entries = expected.get("files")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Quality snapshot has no assets")
    for name, item in entries.items():
        if (not isinstance(name, str) or name in EXCLUDED or "/" in name or "\\" in name
            or not isinstance(item, dict)
            or type(item.get("bytes")) is not int or item["bytes"] <= 0
            or not isinstance(item.get("sha256"), str)
            or SHA256.fullmatch(item["sha256"]) is None):
            raise ValueError("Invalid quality snapshot asset entry")
    actual = snapshot_assets(directory)
    if set(actual["files"]) != set(entries):
        missing = sorted(set(entries) - set(actual["files"]))
        unexpected = sorted(set(actual["files"]) - set(entries))
        raise ValueError(f"Quality asset inventory changed: missing={missing[:8]}, new={unexpected[:8]}")
    for name, item in entries.items():
        if actual["files"][name] != item:
            raise ValueError(f"Map asset differs from passed quality report: {name}")
    return actual


def read_report(filename):
    path = Path(filename)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError("Quality report missing or unreasonably large")
    return json.loads(path.read_text(encoding="utf-8"))
