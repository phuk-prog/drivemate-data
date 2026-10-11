"""Verify immutable graph chunks before promoting the backward-compatible pointer.

Byte integrity is not proof of geographical completeness or legal correctness.
GitHub pointer replacement is recoverable, not atomic. Old chunks are retained.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import tempfile

from publish_map_data import (GitHub, GitHubError, checked_name, metadata,
                              verify_inventory, write_json)
from graph_archive import validate as validate_graph_archive

LEGACY = 'routing-uk'
POINTER = 'routing-uk.json'
TAG = re.compile(r'routing-uk-[A-Za-z0-9][A-Za-z0-9._-]{0,100}')
SHA = re.compile(r'[0-9a-f]{64}')
MAX_GRAPH = 64 * 1024**3
MAX_PART = 2_000_000_000


def checked_tag(tag):
    if tag != LEGACY and not TAG.fullmatch(tag):
        raise ValueError('Invalid routing release tag')
    return tag


class RoutingGitHub(GitHub):
    def release(self, tag):
        checked_tag(tag)
        return json.loads(self.run('api', f'repos/{self.repo}/releases/tags/{tag}'))

    def ensure_release(self, tag):
        try:
            return self.release(tag)
        except GitHubError as exc:
            if 'HTTP 404' not in str(exc):
                raise
        self.run('release', 'create', tag, '--repo', self.repo, '--prerelease',
                 '--title', tag, '--notes',
                 'DriveMate routing graph. © OpenStreetMap contributors, ODbL. '
                 'See manifest for source fingerprint and build identity.')
        return self.release(tag)

    def upload(self, tag, path, mutable=False):
        checked_tag(tag)
        checked_name(Path(path).name)
        if mutable and (tag != LEGACY or Path(path).name != POINTER):
            raise ValueError('Only the routing pointer may be replaced')
        args = ['release', 'upload', tag, str(Path(path).resolve()), '--repo', self.repo]
        if mutable:
            args.append('--clobber')
        self.run(*args)


def validate_manifest(document):
    if not isinstance(document, dict) or document.get('engine') != 'valhalla-3.6.3':
        raise ValueError('Unsupported graph engine')
    if not isinstance(document.get('sha256'), str) or not SHA.fullmatch(document['sha256']):
        raise ValueError('Invalid graph fingerprint')
    if type(document.get('bytes')) is not int or not 0 < document['bytes'] <= MAX_GRAPH:
        raise ValueError('Invalid graph size')
    if type(document.get('download_bytes')) is not int or not 0 < document['download_bytes'] <= MAX_GRAPH:
        raise ValueError('Invalid compressed graph size')
    parts = document.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 100:
        raise ValueError('Invalid graph parts')
    for name in parts:
        checked_name(name)
        if not re.fullmatch(r'valhalla-uk-[A-Za-z0-9._-]+\.tar\.gz\.part[0-9]{2}', name):
            raise ValueError('Invalid graph part name')
    if len(set(parts)) != len(parts):
        raise ValueError('Duplicate graph part')
    prefix = parts[0].rsplit('.part', 1)[0]
    if parts != [prefix + f'.part{number:02d}' for number in range(len(parts))]:
        raise ValueError('Graph chunks must be contiguous and from one archive')
    source = document.get('source')
    if (not isinstance(source, dict) or source.get('licence') != 'ODbL-1.0' or
            not isinstance(source.get('sha256'), str) or not SHA.fullmatch(source['sha256']) or
            not isinstance(source.get('url'), str) or
            not source['url'].startswith('https://download.geofabrik.de/') or
            not source['url'].endswith('.osm.pbf')):
        raise ValueError('Missing licensed source provenance')
    try:
        retrieved = datetime.fromisoformat(source['retrieved_at'])
        built = datetime.fromisoformat(document['built'])
        if retrieved.tzinfo is None or built.tzinfo is None or built < retrieved:
            raise ValueError('Source/build timestamps require timezone and chronological order')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid source/build timestamps') from exc


def publish(github, out, tag):
    checked_tag(tag)
    if tag == LEGACY:
        raise ValueError('An immutable generation tag is required')
    out = Path(out)
    if out.is_symlink() or not out.is_dir():
        raise ValueError('Unsafe output directory')
    manifest = out / POINTER
    if manifest.is_symlink():
        raise ValueError('Unsafe manifest')
    document = json.loads(manifest.read_text())
    validate_manifest(document)
    files = {}
    with tempfile.TemporaryDirectory(prefix='drivemate-routing-') as temporary:
        joined = Path(temporary) / 'joined.gz'
        with joined.open('wb') as stream:
            for name in document['parts']:
                path = out / name
                if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_PART:
                    raise ValueError('Missing or invalid graph part')
                files[name] = path
                with path.open('rb') as piece:
                    for block in iter(lambda: piece.read(1024 * 1024), b''):
                        stream.write(block)
        if document.get('download_bytes') != joined.stat().st_size:
            raise ValueError('Compressed byte count differs')
        validate_graph_archive(joined, compressed=True, expected_bytes=document['bytes'],
                               expected_sha256=document['sha256'])
        document['generation'] = tag
        document['part_metadata'] = {name: metadata(path, tag) for name, path in files.items()}
        candidate = write_json(temporary, POINTER, document)
        archive = {**files, POINTER: candidate}
        github.ensure_release(tag)
        existing = github.inventory(tag)
        expected = {name: metadata(path, tag) for name, path in archive.items()}
        if not set(existing) <= set(expected):
            raise ValueError('Unexpected immutable assets')
        for name in existing:
            verify_inventory(existing, {name: expected[name]}, tag)
        for name, path in archive.items():
            if name not in existing:
                github.upload(tag, path)
        verify_inventory(github.inventory(tag), expected, tag, exact=True)
        github.ensure_release(LEGACY)
        existing = github.inventory(LEGACY)
        if len(existing) + len(set(files) - set(existing)) + (POINTER not in existing) > 1000:
            raise ValueError('Routing release capacity exhausted; no data deleted')
        prior = None
        if POINTER in existing:
            prior_dir = Path(temporary) / 'prior'
            prior_dir.mkdir()
            prior = github.download(LEGACY, POINTER, prior_dir)
            verify_inventory(existing, {POINTER: metadata(prior, LEGACY)}, LEGACY)
            old = json.loads(prior.read_text())
            validate_manifest(old)
            if not set(old['parts']) <= set(existing):
                raise ValueError('Previous graph chunks missing')
        for name, path in files.items():
            wanted = {name: metadata(path, LEGACY)}
            if name in existing:
                verify_inventory(existing, wanted, LEGACY)
            else:
                github.upload(LEGACY, path)
        verify_inventory(github.inventory(LEGACY),
                         {name: metadata(path, LEGACY) for name, path in files.items()}, LEGACY)
        try:
            github.upload(LEGACY, candidate, mutable=POINTER in existing)
            verify_inventory(github.inventory(LEGACY), {POINTER: metadata(candidate, LEGACY)}, LEGACY)
        except Exception as promotion_error:
            if prior is not None:
                try:
                    github.upload(LEGACY, prior, mutable=POINTER in github.inventory(LEGACY))
                    verify_inventory(github.inventory(LEGACY), {POINTER: metadata(prior, LEGACY)}, LEGACY)
                except Exception as recovery_error:
                    raise GitHubError('Graph promotion and previous pointer recovery both failed') from recovery_error
            raise promotion_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    publish(RoutingGitHub(args.repo), args.out, args.tag)


if __name__ == '__main__':
    main()
