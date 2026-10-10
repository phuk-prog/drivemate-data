"""Publish immutable map assets; switch the legacy pointer only after hash verification.

Uses GitHub CLI argument vectors, never shell commands. Bootstrap describes only the
existing legacy inventory; it does not claim that a previously partial build is complete.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

LEGACY = 'map-data-uk'
ASSET_LIMIT = 1000
MAIN_FILES = 900
MIN_MAP_BYTES = 50_000_000
MAX_ASSET_BYTES = 1_950_000_000
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,150}')
TAG = re.compile(r'map-data-[A-Za-z0-9][A-Za-z0-9._-]{0,100}')
LICENSE_DIR = Path(__file__).resolve().parent.parent / 'licenses'
LICENSE_ASSETS = ('LICENSE-ODbL.txt', 'LICENSE-CDLA-Permissive-2.0.txt', 'LICENSE-Apache-2.0.txt',
                  'NOTICE-Foursquare.txt', 'NOTICE.md')
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


def checked_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError('Unsafe asset name')
    return value


def checked_tag(value):
    if not isinstance(value, str) or not TAG.fullmatch(value):
        raise ValueError('Invalid map release tag')
    return value


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def metadata(path, tag):
    return {'sha256': digest(path), 'bytes': Path(path).stat().st_size, 'tag': tag}


def asset_metadata(asset, tag):
    checked_name(asset.get('name'))
    sha = asset.get('digest')
    size = asset.get('size')
    if not isinstance(sha, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', sha):
        raise ValueError('GitHub asset digest unavailable or invalid')
    if type(size) is not int or size < 0:
        raise ValueError('GitHub asset size unavailable or invalid')
    return {'sha256': sha[7:], 'bytes': size, 'tag': tag}


def inventory_identity(assets, tag):
    """Ignore download_count/timestamps, which can change during our own downloads."""
    result = {}
    for name, asset in assets.items():
        asset_id = asset.get('id')
        if type(asset_id) is not int or asset_id <= 0:
            raise ValueError('Invalid asset ID')
        result[name] = {**asset_metadata(asset, tag), 'id': asset_id}
    return result


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, repo):
        if not REPO.fullmatch(repo):
            raise ValueError('Invalid repository')
        self.repo = repo

    def run(self, *args):
        result = subprocess.run(['gh', *map(str, args)], capture_output=True, text=True, check=False)
        if result.returncode:
            raise GitHubError(result.stderr.strip() or 'GitHub CLI failed')
        return result.stdout

    def release(self, tag):
        checked_tag(tag)
        return json.loads(self.run('api', f'repos/{self.repo}/releases/tags/{tag}'))

    def ensure_release(self, tag):
        try:
            return self.release(tag)
        except GitHubError as exc:
            if 'HTTP 404' not in str(exc):
                raise
        self.run('release', 'create', tag, '--repo', self.repo, '--prerelease', '--title', tag,
                 '--notes', 'DriveMate map data. OpenStreetMap contributors (ODbL); see build metadata.')
        return self.release(tag)

    def inventory(self, tag):
        release = self.release(tag)
        release_id = release.get('id')
        if type(release_id) is not int or release_id <= 0:
            raise ValueError('Invalid release ID')
        pages = json.loads(self.run('api', '--paginate', '--slurp',
                                  f'repos/{self.repo}/releases/{release_id}/assets?per_page=100'))
        assets = {}
        for page in pages:
            if not isinstance(page, list):
                raise ValueError('Invalid release inventory')
            for asset in page:
                name = checked_name(asset.get('name'))
                if name in assets:
                    raise ValueError('Duplicate release asset')
                assets[name] = asset
        return assets

    def upload(self, tag, path, mutable=False):
        args = ['release', 'upload', tag, str(Path(path).resolve()), '--repo', self.repo]
        if mutable:
            if tag != LEGACY or Path(path).name != 'latest.json':
                raise ValueError('Only the legacy pointer may be replaced')
            args.append('--clobber')
        self.run(*args)

    def download(self, tag, name, directory):
        checked_name(name)
        self.run('release', 'download', tag, '--repo', self.repo, '--pattern', name,
                 '--dir', str(Path(directory).resolve()))
        return Path(directory) / name

    def delete(self, asset):
        asset_id = asset.get('id')
        if type(asset_id) is not int or asset_id <= 0:
            raise ValueError('Invalid asset ID')
        self.run('api', '-X', 'DELETE', f'repos/{self.repo}/releases/assets/{asset_id}')


def _load(name):
    # Import by path: publisher tests load this file as a standalone module.
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


regional = _load('region_publication')
places_provenance = _load('places_provenance')
PLACE_TILE = re.compile(r'places--?\d+_-?\d+\.json\.gz')


def local_files(out):
    out = Path(out)
    if not out.is_dir() or out.is_symlink():
        raise ValueError('Output directory missing or unsafe')
    files = {}
    for path in sorted(out.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in map output')
        if not path.is_file():
            continue
        name = checked_name(path.name)
        if name in files:
            raise ValueError('Duplicate map asset basename')
        if not (name in {'drivemate.pmtiles', 'cameras-uk.json', 'build-info.txt',
                         'charge-zones-uk.json', 'search-offline-uk.tsv.gz',
                         'build-quality.json', 'build-quality.md', 'limit-checks.md',
                         'mapillary-arrows-cache.json.gz', 'mapillary-signs-cache.json.gz',
                         'source-inventory.json', places_provenance.FILENAME, *LICENSE_ASSETS} or
                re.fullmatch(r'(?:lanes|limits|roadinfo)--?\d+_-?\d+\.json', name) or
                PLACE_TILE.fullmatch(name) or
                regional.is_regional_asset(name)):
            raise ValueError('Unexpected map output file')
        size = path.stat().st_size
        if not 0 < size <= MAX_ASSET_BYTES:
            raise ValueError('Empty or oversized map asset')
        if regional.is_regional_asset(name):
            # Whole-set consistency is checked by validate_staged() below.
            if name.endswith('.pmtiles'):
                with path.open('rb') as stream:
                    if stream.read(8) != b'PMTiles\x03':
                        raise ValueError('Invalid regional map archive')
            files[name] = path
            continue
        if name == 'drivemate.pmtiles':
            with path.open('rb') as stream:
                if size < MIN_MAP_BYTES or stream.read(7) != b'PMTiles':
                    raise ValueError('Map archive too small or invalid')
        elif name == 'search-offline-uk.tsv.gz':
            # Validate sorted records, attribution, bounds and the entire gzip CRC.
            spec = importlib.util.spec_from_file_location('search_index', Path(__file__).with_name('search_index.py'))
            validator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(validator)
            for _ in validator.rows(path):
                pass
        elif name.endswith('.json.gz'):
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                data = json.load(stream)
            if name.startswith('mapillary-'):
                if not isinstance(data, dict):
                    raise ValueError('Invalid observation cache')
            elif not isinstance(data, list) or not all(isinstance(row, list) and len(row) == 5 for row in data):
                raise ValueError('Invalid places data')
        elif name.endswith('.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            if name == 'source-inventory.json':
                # Import by path: publisher tests load this file as a standalone module.
                spec = importlib.util.spec_from_file_location(
                    'source_inventory', Path(__file__).with_name('source_inventory.py'))
                inventory = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(inventory)
                inventory.read(path)
                files[name] = path
                continue
            if name == places_provenance.FILENAME:
                # Structural only: schema, required keys, non-negative integer counts.
                places_provenance.validate(data)
                files[name] = path
                continue
            if name == 'build-quality.json':
                if not isinstance(data, dict) or data.get('errors') != []:
                    raise ValueError('Missing or failing quality report')
                files[name] = path
                continue
            key = ('zones' if name == 'charge-zones-uk.json' else
                   'elements' if name == 'cameras-uk.json' or name.startswith('roadinfo-') else 'ways')
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError('Invalid road or camera data')
        files[name] = path
    if not {'drivemate.pmtiles', 'cameras-uk.json', 'build-info.txt'} <= files.keys():
        raise ValueError('Required map assets missing')
    if not any(name.startswith('lanes-') for name in files) or not any(PLACE_TILE.fullmatch(name) for name in files):
        raise ValueError('Lane or place tiles missing')
    regional.validate_staged(files)
    return files


def licence_files(directory=None):
    """Licence texts always come from the repository folder, never from build output."""
    directory = Path(directory or LICENSE_DIR)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Licence folder missing or unsafe')
    result = {}
    for name in LICENSE_ASSETS:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ASSET_BYTES:
            raise ValueError(f'Licence file missing or unsafe: {name}')
        result[name] = path
    return result


def verify_inventory(assets, expected, tag, exact=False):
    if exact and set(assets) != set(expected):
        raise ValueError('Immutable release inventory differs')
    for name, wanted in expected.items():
        if name not in assets or asset_metadata(assets[name], tag) != wanted:
            raise ValueError(f'Asset verification failed: {name}')


def upload_immutable(github, tag, files):
    checked_tag(tag)
    if tag == LEGACY or len(files) > ASSET_LIMIT:
        raise ValueError('Invalid immutable release or too many assets')
    wanted = {name: metadata(path, tag) for name, path in files.items()}
    github.ensure_release(tag)
    existing = github.inventory(tag)
    if not set(existing) <= set(wanted):
        raise ValueError('Immutable release contains unexpected assets')
    for name in existing:
        verify_inventory(existing, {name: wanted[name]}, tag)
    for name, path in files.items():
        if name not in existing:
            github.upload(tag, path)
    verify_inventory(github.inventory(tag), wanted, tag, exact=True)
    return wanted


def write_json(directory, name, document):
    path = Path(directory) / name
    path.write_text(json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return path


def pointer(github, tag, manifest_tag, manifest_path, directory, extra_tag=None):
    # Validate the currently published pointer before any destructive replacement.
    existing = github.inventory(LEGACY)
    prior = None
    if 'latest.json' in existing:
        prior = github.download(LEGACY, 'latest.json', Path(directory) / 'prior')
        verify_inventory(existing, {'latest.json': metadata(prior, LEGACY)}, LEGACY)
        old = json.loads(prior.read_text(encoding='utf-8'))
        if not isinstance(old, dict):
            raise ValueError('Invalid previous pointer')
    elif len(existing) >= ASSET_LIMIT:
        raise ValueError('Legacy release has no pointer slot; run bootstrap first')
    document = {'schema': 1, 'tag': tag, 'manifest_tag': manifest_tag,
                'manifest_sha256': digest(manifest_path)}
    if extra_tag:
        document['extra_tag'] = checked_tag(extra_tag)
    path = write_json(directory, 'latest.json', document)
    # GitHub clobber deletes the old asset before uploading its replacement.
    # This is recoverable, but is not an atomic pointer swap.
    try:
        github.upload(LEGACY, path, mutable='latest.json' in existing)
        verify_inventory(github.inventory(LEGACY), {'latest.json': metadata(path, LEGACY)}, LEGACY)
    except Exception as promotion_error:
        if prior is not None:
            try:
                current = github.inventory(LEGACY)
                github.upload(LEGACY, prior, mutable='latest.json' in current)
                verify_inventory(github.inventory(LEGACY), {'latest.json': metadata(prior, LEGACY)}, LEGACY)
            except Exception as recovery_error:
                raise GitHubError(f'Pointer promotion failed and previous pointer recovery failed: {recovery_error}') from promotion_error
        raise


def publish(github, out, tag, extra_tag=None, navigation_data=False, licenses_dir=None):
    checked_tag(tag)
    extra_tag = checked_tag(extra_tag or tag + '-extra')
    if tag == LEGACY or tag == extra_tag or extra_tag == LEGACY:
        raise ValueError('Distinct immutable tags required')
    files = local_files(out)
    if navigation_data:
        required = {'charge-zones-uk.json', 'search-offline-uk.tsv.gz', 'build-quality.json', 'source-inventory.json'}
        if not required <= files.keys() or not all(any(name.startswith(prefix) for name in files)
                                                  for prefix in ('limits-', 'roadinfo-')):
            raise ValueError('Required navigation datasets missing')
        if any(PLACE_TILE.fullmatch(name) for name in files) and places_provenance.FILENAME not in files:
            raise ValueError('Places provenance sidecar missing')
    if navigation_data:
        # A report saying errors=[] is not proof it checked this exact output.
        # Compare every asset hash and filename before any remote release action.
        spec = importlib.util.spec_from_file_location(
            'publication_consistency', Path(__file__).with_name('publication_consistency.py'))
        consistency = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consistency)
        consistency.verify_snapshot(out, consistency.read_report(files['build-quality.json']))
    if navigation_data:
        # Checked after the snapshot comparison: these are not build output.
        files.update(licence_files(licenses_dir))
    # Keep the map and build metadata in the main release; stable ordering for restartability.
    names = sorted(files, key=lambda name: (name != 'drivemate.pmtiles', name != 'build-info.txt', name))
    main = {name: files[name] for name in names[:MAIN_FILES]}
    extra = {name: files[name] for name in names[MAIN_FILES:]}
    if len(extra) > ASSET_LIMIT:
        raise ValueError('Map inventory exceeds two release capacity')
    manifest_files = {name: metadata(path, tag if name in main else extra_tag) for name, path in files.items()}
    with tempfile.TemporaryDirectory(prefix='drivemate-publish-') as temporary:
        manifest_doc = {'schema': 1, 'files': manifest_files}
        if 'source-inventory.json' in files:
            manifest_doc['source_inventory'] = {
                'asset': 'source-inventory.json',
                'sha256': digest(files['source-inventory.json']),
                'scope': 'Selected inputs; rights not independently verified'}
        manifest = write_json(temporary, 'manifest.json', manifest_doc)
        main['manifest.json'] = manifest
        if extra:
            upload_immutable(github, extra_tag, extra)
        # Upload the main manifest last, after all extra and main data assets exist.
        upload_immutable(github, tag, main)
        # Re-inventory both releases immediately before making this version discoverable.
        verify_inventory(github.inventory(tag), {name: metadata(path, tag) for name, path in main.items()}, tag, exact=True)
        if extra:
            verify_inventory(github.inventory(extra_tag), {name: metadata(path, extra_tag) for name, path in extra.items()}, extra_tag, exact=True)
        github.ensure_release(LEGACY)
        pointer(github, tag, tag, manifest, temporary, extra_tag if extra else None)


def bootstrap(github, tag):
    checked_tag(tag)
    if tag == LEGACY:
        raise ValueError('Bootstrap metadata must use an immutable tag')
    assets = github.inventory(LEGACY)
    identity = inventory_identity(assets, LEGACY)
    files = {name: asset_metadata(asset, LEGACY) for name, asset in assets.items()
             if name not in {'build-info.txt', 'latest.json', 'manifest.json'}}
    if 'drivemate.pmtiles' not in files or files['drivemate.pmtiles']['bytes'] < MIN_MAP_BYTES:
        raise ValueError('Legacy map inventory is incomplete or invalid')
    if 'latest.json' not in assets and len(assets) >= ASSET_LIMIT and 'build-info.txt' not in assets:
        raise ValueError('No safely removable metadata asset to make pointer slot')
    with tempfile.TemporaryDirectory(prefix='drivemate-bootstrap-') as temporary:
        manifest = write_json(temporary, 'manifest.json', {
            'schema': 1, 'files': files, 'inventory_snapshot': True,
            'coverage': 'Existing legacy assets only; previous partial builds may omit lane or place tiles.'})
        archive = {'manifest.json': manifest}
        if 'build-info.txt' in assets:
            info = github.download(LEGACY, 'build-info.txt', Path(temporary) / 'archive')
            verify_inventory(assets, {'build-info.txt': metadata(info, LEGACY)}, LEGACY)
            archive['build-info.txt'] = info
        else:
            # Resume after a verified archive was written and its legacy copy removed.
            # Retain the archived original in the exact immutable inventory on reruns.
            github.ensure_release(tag)
            prior_archive = github.inventory(tag)
            if 'build-info.txt' in prior_archive:
                info = github.download(tag, 'build-info.txt', Path(temporary) / 'archive')
                verify_inventory(prior_archive, {'build-info.txt': metadata(info, tag)}, tag)
                archive['build-info.txt'] = info
        upload_immutable(github, tag, archive)
        # Refuse deletion/promotion if the legacy data changed while metadata was prepared.
        current = github.inventory(LEGACY)
        if inventory_identity(current, LEGACY) != identity:
            raise ValueError('Legacy inventory changed during bootstrap')
        if 'latest.json' not in current and len(current) >= ASSET_LIMIT:
            # The original build-info was downloaded and verified, and its archive verified above.
            github.delete(current['build-info.txt'])
            after = github.inventory(LEGACY)
            expected_after = {name: value for name, value in identity.items() if name != 'build-info.txt'}
            if inventory_identity(after, LEGACY) != expected_after:
                raise ValueError('Unexpected inventory after metadata removal')
        pointer(github, LEGACY, tag, manifest, temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='mode', required=True)
    for mode in ('publish', 'bootstrap'):
        command = subparsers.add_parser(mode)
        command.add_argument('--repo', required=True)
        command.add_argument('--tag', required=True)
        if mode == 'publish':
            command.add_argument('--out', type=Path, required=True)
            command.add_argument('--extra-tag')
            command.add_argument('--navigation-data', action='store_true')
    args = parser.parse_args()
    try:
        github = GitHub(args.repo)
        if args.mode == 'publish':
            publish(github, args.out, args.tag, args.extra_tag, args.navigation_data)
        else:
            bootstrap(github, args.tag)
    except (ValueError, OSError, GitHubError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Publication stopped without claiming success: {exc}\n')


if __name__ == '__main__':
    main()
