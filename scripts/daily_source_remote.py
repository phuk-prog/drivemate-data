"""Observe the source and read the last checkpoint through the verified release chain."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import daily_source_probe as probe
import publish_map_data as publisher

CHECKPOINT = "source-checkpoint.json"


def bounded_json(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("Missing or oversized release metadata")
    return json.loads(path.read_text(encoding="utf-8"))


def published_checkpoint(github, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    pointer_path = github.download(publisher.LEGACY, "latest.json", directory)
    pointer = bounded_json(pointer_path, 16_384)
    if not isinstance(pointer, dict) or pointer.get("schema") != 1:
        raise ValueError("Unsupported published pointer")
    tag = publisher.checked_tag(pointer.get("manifest_tag") or pointer.get("tag"))
    expected = pointer.get("manifest_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Published pointer lacks a manifest checksum")
    manifest_path = github.download(tag, "manifest.json", directory)
    if publisher.digest(manifest_path) != expected:
        raise ValueError("Published manifest checksum mismatch")
    manifest = bounded_json(manifest_path, 4_000_000)
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported release manifest")
    info = manifest["files"].get(CHECKPOINT)
    if info is None:
        return None  # Migration: older verified generations have no source checkpoint.
    if (not isinstance(info, dict) or type(info.get("bytes")) is not int
            or not 0 < info["bytes"] <= 16_384
            or not re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256", "")))):
        raise ValueError("Invalid published checkpoint inventory")
    checkpoint_tag = publisher.checked_tag(info.get("tag") or tag)
    path = github.download(checkpoint_tag, CHECKPOINT, directory)
    if path.stat().st_size != info["bytes"] or publisher.digest(path) != info["sha256"]:
        raise ValueError("Published checkpoint checksum mismatch")
    value = bounded_json(path, 16_384)
    probe.validate_checkpoint(value)
    if (not re.fullmatch(r"[0-9a-f]{64}", str(value.get("source_sha256", "")))
            or type(value.get("source_bytes")) is not int or value["source_bytes"] <= 0):
        raise ValueError("Checkpoint lacks the downloaded source identity")
    return value


def graph_matches_map(github, checkpoint, directory):
    """A failed/missing routing build must remain retryable when OSM is unchanged."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        inventory = github.inventory('routing-uk')
    except publisher.GitHubError as error:
        if 'HTTP 404' not in str(error):
            raise
        return False
    if 'routing-uk.json' not in inventory:
        return False
    path = github.download('routing-uk', 'routing-uk.json', directory)
    publisher.verify_inventory(inventory, {'routing-uk.json': publisher.metadata(path, 'routing-uk')}, 'routing-uk')
    pointer = bounded_json(path, 2_000_000)
    source = pointer.get('source') if isinstance(pointer, dict) else None
    if not isinstance(source, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(source.get('sha256', ''))):
        return False
    return source['sha256'] == checkpoint['source_sha256']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--github-repo", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    url = probe.source_url(args.source_url)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    signal_path = args.output_dir / "source-before.md5"
    subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                    "--proto", "=https", "--max-time", "30", "--max-filesize", "4096",
                    url + ".md5", "--output", str(signal_path)], check=True, timeout=40)
    github = publisher.GitHub(args.github_repo)
    previous = published_checkpoint(github, args.output_dir / "published")
    pipeline = probe.pipeline_fingerprint(args.repo)
    (args.output_dir / "pipeline.json").write_text(json.dumps(pipeline, sort_keys=True) + "\n")
    decision = probe.decide(url, signal_path.read_text(), pipeline["pipeline_sha256"], previous, args.force)
    if previous is not None and not graph_matches_map(github, previous, args.output_dir / 'routing'):
        decision['rebuild'] = True
        decision['reasons'].append('routing graph missing or not matching the published map source')
    (args.output_dir / "decision.json").write_text(json.dumps(decision, sort_keys=True) + "\n")
    print(json.dumps({"rebuild": decision["rebuild"], "reasons": decision["reasons"]}))


if __name__ == "__main__":
    main()
