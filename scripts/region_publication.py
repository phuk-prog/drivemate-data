"""Stage verified regional PMTiles for publication, and validate staged sets.

Publication is opt-in (repository variable PUBLISH_REGIONAL_MAPS=true, set only
after the licensing and Manchester acceptance gates are approved). Staging
re-hashes every archive against the full-UK export manifest and the exact
drivemate.pmtiles being published, then moves them into the build output as:

  regions/regional-base.pmtiles             nationwide z0-9 base
  regions/region-z<z>-x<x>-y<y>.pmtiles     z10-14 detail packages
  regions/regional-manifest.json            status "published", asset names

The phone trusts regional-manifest.json only through the release manifest's
SHA-256 (itself pinned by latest.json), the same chain as every other asset.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

BASE_ASSET = "regional-base.pmtiles"
MANIFEST = "regional-manifest.json"
DETAIL = re.compile(r"region-z(8|9|10)-x([0-9]{1,4})-y([0-9]{1,4})\Z")
ASSET = re.compile(r"(?:regional-base|region-z(?:8|9|10)-x[0-9]{1,4}-y[0-9]{1,4})\.pmtiles\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_DETAIL_BYTES = 200_000_000
MAX_ASSET_BYTES = 1_950_000_000


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def asset_name(package):
    if package == "base":
        return BASE_ASSET
    if not DETAIL.fullmatch(package):
        raise ValueError(f"Unexpected regional package name: {package}")
    return package + ".pmtiles"


def is_regional_asset(name):
    return name == MANIFEST or ASSET.fullmatch(name) is not None


def _check_packages(manifest, expected_status):
    if (manifest.get("schema") != 1 or manifest.get("status") != expected_status
            or manifest.get("base_zoom_max") != 9 or manifest.get("detail_zoom_min") != 10
            or not SHA.fullmatch(str(manifest.get("source_sha256", "")))):
        raise ValueError("Unexpected regional manifest structure")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or "base" not in packages or len(packages) < 2:
        raise ValueError("Regional manifest needs a base and detail packages")
    for name, info in packages.items():
        asset_name(name)
        if (not isinstance(info, dict) or type(info.get("tiles")) is not int or info["tiles"] < 1
                or info.get("verified_tile_payloads") != info["tiles"]
                or type(info.get("bytes")) is not int or not 127 <= info["bytes"] <= MAX_ASSET_BYTES
                or not SHA.fullmatch(str(info.get("sha256", "")))):
            raise ValueError(f"Regional package lacks complete verification: {name}")
        if name != "base" and info["bytes"] > MAX_DETAIL_BYTES:
            raise ValueError(f"Oversize detailed package: {name}")
    return packages


def stage(region_dir, out_dir, map_path):
    """Move a complete, verified full-UK regional export into ``out_dir``."""
    region_dir, out_dir = Path(region_dir), Path(out_dir)
    manifest = json.loads((region_dir / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("pilot_root") is not None:
        raise ValueError("A single-region pilot can never be published as the UK set")
    packages = _check_packages(manifest, "unpublished")
    if manifest.get("selected_addressed_tiles") != manifest.get("source_addressed_tiles"):
        raise ValueError("Regional export does not cover every source tile")
    if manifest["source_sha256"] != digest(map_path):
        raise ValueError("Regional export was made from a different map archive")
    for name, info in packages.items():
        path = region_dir / info.get("filename", "")
        if path.name != f"{name}.pmtiles" or not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regional archive: {name}")
        if path.stat().st_size != info["bytes"] or digest(path) != info["sha256"]:
            raise ValueError(f"Regional archive changed after verification: {name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise ValueError("Regional output directory must be empty")
    published = json.loads(json.dumps(manifest))
    published["status"] = "published"
    published["licensing"] = ("Published with the release's source inventory and attribution: "
                              "© OpenStreetMap contributors (ODbL), © OpenMapTiles.")
    for name, info in published["packages"].items():
        target = out_dir / asset_name(name)
        shutil.move(str(region_dir / info["filename"]), target)
        if digest(target) != info["sha256"]:
            raise ValueError(f"Regional archive damaged while staging: {name}")
        info["filename"] = target.name
    (out_dir / MANIFEST).write_text(json.dumps(published, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return published


def validate_staged(files):
    """Publisher gate: ``files`` maps asset name → local path for the whole release.

    Either no regional assets are present, or a published manifest lists
    exactly the staged archives, each with matching size and SHA-256, all cut
    from the exact drivemate.pmtiles in this release.
    """
    regional = {n for n in files if is_regional_asset(n)}
    if not regional:
        return None
    if MANIFEST not in regional:
        raise ValueError("Regional archives without a regional manifest")
    manifest = json.loads(Path(files[MANIFEST]).read_text(encoding="utf-8"))
    packages = _check_packages(manifest, "published")
    expected = {asset_name(n) for n in packages}
    if regional - {MANIFEST} != expected:
        raise ValueError("Staged regional archives differ from the regional manifest")
    if "drivemate.pmtiles" not in files or manifest["source_sha256"] != digest(files["drivemate.pmtiles"]):
        raise ValueError("Regional manifest does not belong to this release's map")
    for name, info in packages.items():
        path = Path(files[asset_name(name)])
        if info.get("filename") != path.name or path.stat().st_size != info["bytes"] or digest(path) != info["sha256"]:
            raise ValueError(f"Staged regional archive does not match manifest: {name}")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regions", required=True, type=Path, help="Full-UK region_pmtiles.py output")
    p.add_argument("--out", required=True, type=Path, help="Empty directory inside the build output")
    p.add_argument("--map", required=True, type=Path, help="The drivemate.pmtiles being published")
    a = p.parse_args()
    result = stage(a.regions, a.out, a.map)
    print(f"Staged {len(result['packages'])} regional archives for publication")


if __name__ == "__main__":
    main()
