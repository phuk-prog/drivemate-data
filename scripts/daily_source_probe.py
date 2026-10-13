"""Local-input daily probe; MD5 is a change signal, SHA-256 identifies downloaded bytes.

Checkpoint output is a candidate for publication after existing data-quality gates.
This tool never fetches data, changes release pointers, or asserts display support.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

MD5 = re.compile(r"[0-9a-f]{32}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SIGNAL_BYTES = 4096
GENERATED_STATE_NAMES = {"source-checkpoint.json", "daily-source-checkpoint.json",
                         "daily-update-state.json", "daily-map-state.json"}


def source_url(value):
    if not isinstance(value, str):
        raise ValueError("Missing source URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "download.geofabrik.de"
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+\.osm\.pbf", parsed.path)
            or any(p in ("", ".", "..") for p in parsed.path.split("/")[1:])
            or value != "https://download.geofabrik.de" + parsed.path):
        raise ValueError("Expected canonical HTTPS Geofabrik OSM PBF source URL")
    return value


def sha256_value(value):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("Expected SHA-256 pipeline fingerprint")
    return value


def parse_signal(text, url):
    """Accept one bounded md5sum record naming precisely the selected source basename."""
    source_url(url)
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_SIGNAL_BYTES:
        raise ValueError("Missing or oversized Geofabrik checksum response")
    match = re.fullmatch(r"([0-9a-fA-F]{32})[ \t]+\*?([A-Za-z0-9_.-]+\.osm\.pbf)\r?\n?", text)
    if match is None or match[2] != urlsplit(url).path.rsplit("/", 1)[1]:
        raise ValueError("Malformed checksum or unexpected source filename")
    return {"algorithm": "md5", "value": match[1].lower()}


def validate_checkpoint(checkpoint):
    if not isinstance(checkpoint, dict) or type(checkpoint.get("schema")) is not int or checkpoint["schema"] != 1:
        raise ValueError("Unsupported source checkpoint")
    source_url(checkpoint["source_url"])
    signal = checkpoint["change_signal"]
    if (not isinstance(signal, dict) or signal.get("algorithm") != "md5"
            or not isinstance(signal.get("value"), str) or not MD5.fullmatch(signal["value"])):
        raise ValueError("Invalid checkpoint change signal")
    sha256_value(checkpoint["pipeline_sha256"])
    return checkpoint


def decide(url, signal_text, pipeline_sha256, previous=None, force=False):
    signal = parse_signal(signal_text, url)  # Invalid observations never become a no-op.
    sha256_value(pipeline_sha256)
    reasons = []
    try:
        prior = validate_checkpoint(previous)
    except (ValueError, KeyError, TypeError):
        prior = None
        reasons.append("no valid published checkpoint")
    if prior is not None:
        if prior["source_url"] != url:
            reasons.append("source URL changed")
        if prior["change_signal"] != signal:
            reasons.append("source change signal changed")
        if prior["pipeline_sha256"] != pipeline_sha256:
            reasons.append("pipeline or schema changed")
    if force:
        reasons.append("forced weekly rebuild")
    return {"schema": 1, "source_url": url, "change_signal": signal,
            "pipeline_sha256": pipeline_sha256, "rebuild": bool(reasons), "reasons": reasons}


def pipeline_fingerprint(repo, includes=()):
    """Hash code/config content and paths; generated checkpoints/timestamps are excluded.

    Additional explicit config paths allow future build profiles/dependency definitions.
    Missing or symlinked explicit inputs fail rather than disappearing from the identity.
    """
    root = Path(repo).resolve()
    paths = set(root.glob("scripts/**/*.py"))
    paths.add(root / ".github/workflows/map-data.yml")
    for pattern in ("scripts/**/*.yml", "scripts/**/*.yaml", "config/**/*",
                    "profiles/**/*", "requirements*.txt", "pyproject.toml", "uv.lock",
                    "poetry.lock", "pom.xml", "build.gradle*", "settings.gradle*",
                    "gradle/libs.versions.toml"):
        paths.update(p for p in root.glob(pattern) if p.is_file() and p.name not in GENERATED_STATE_NAMES)
    for name in includes:
        path = root / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Pipeline input must be within repository")
        if path.name in GENERATED_STATE_NAMES:
            raise ValueError("Generated checkpoints are not pipeline inputs")
        paths.add(path)
    if not any(p.relative_to(root).parts[0] == "scripts" and p.suffix == ".py" for p in paths):
        raise ValueError("No builder scripts found")
    digest = hashlib.sha256()
    identity = []
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("Missing, symlinked or unsafe pipeline input")
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        # Length-prefix framing avoids collisions between path/content boundaries.
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big") + encoded)
        digest.update(len(data).to_bytes(8, "big") + data)
        identity.append(relative)
    return {"schema": 1, "pipeline_sha256": digest.hexdigest(), "inputs": identity}


def build_checkpoint(url, before, after, pipeline_sha256, pbf):
    signal = parse_signal(before, url)
    if parse_signal(after, url) != signal:
        raise ValueError("Source changed during download; no checkpoint produced")
    sha256_value(pipeline_sha256)
    path = Path(pbf)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing or unsafe downloaded PBF")
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
            size += len(block)
    if size == 0 or md5.hexdigest() != signal["value"]:
        raise ValueError("Downloaded source does not match observed checksum")
    return {"schema": 1, "source_url": url, "change_signal": signal,
            "pipeline_sha256": pipeline_sha256, "source_sha256": sha256.hexdigest(),
            "source_bytes": size}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fp = sub.add_parser("fingerprint")
    fp.add_argument("--repo", type=Path, required=True)
    fp.add_argument("--include", action="append", default=[])
    fp.add_argument("--output", type=Path, required=True)
    decision = sub.add_parser("decide")
    decision.add_argument("--source-url", required=True)
    decision.add_argument("--signal-file", type=Path, required=True)
    decision.add_argument("--pipeline-sha256", required=True)
    decision.add_argument("--previous", type=Path)
    decision.add_argument("--force", action="store_true")
    decision.add_argument("--output", type=Path, required=True)
    cp = sub.add_parser("checkpoint")
    cp.add_argument("--source-url", required=True)
    cp.add_argument("--signal-before", type=Path, required=True)
    cp.add_argument("--signal-after", type=Path, required=True)
    cp.add_argument("--pipeline-sha256", required=True)
    cp.add_argument("--pbf", type=Path, required=True)
    cp.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        def signal_file(path):
            if path.stat().st_size > MAX_SIGNAL_BYTES:
                raise ValueError("Checksum response too large")
            return path.read_text(encoding="utf-8")
        if args.command == "fingerprint":
            result = pipeline_fingerprint(args.repo, args.include)
        elif args.command == "decide":
            previous = None
            if args.previous:
                try:
                    previous = json.loads(args.previous.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass  # Missing/invalid published state requires rebuilding.
            result = decide(args.source_url, signal_file(args.signal_file), args.pipeline_sha256, previous, args.force)
        else:
            result = build_checkpoint(args.source_url, signal_file(args.signal_before),
                                      signal_file(args.signal_after), args.pipeline_sha256, args.pbf)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_name(args.output.name + ".part")
        temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(args.output)
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"daily source probe: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
