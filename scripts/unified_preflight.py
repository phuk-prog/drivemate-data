"""Inexpensive data-source gates. Does not build UK packages or publish releases."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

SKIP = {'.git', '__pycache__', '.venv', 'build', 'work', 'out', 'node_modules'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--base-sha', required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    report = {'scope': 'source, publication regressions and generator selftests',
              'plugin_evals': 'NOT_APPLICABLE: no local plugin package',
              'release_ready': False, 'uk_build': 'NOT_EXECUTED', 'gates': {}}
    report['head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    report['base_sha'] = subprocess.check_output(['git', 'rev-parse', args.base_sha], cwd=repo, text=True).strip()
    report['gates']['base_ancestor'] = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', report['base_sha'], 'HEAD'], cwd=repo).returncode == 0
    report['diff_sha256'] = hashlib.sha256(subprocess.check_output(
        ['git', 'diff', report['base_sha']], cwd=repo)).hexdigest()
    digest = hashlib.sha256()
    findings = []
    for path in sorted(repo.rglob('*')):
        relative = path.relative_to(repo)
        if set(relative.parts) & SKIP or not path.is_file():
            continue
        if path.is_symlink():
            findings.append({'path': str(relative), 'rule': 'source symlink'})
            continue
        data = path.read_bytes()
        digest.update(relative.as_posix().encode() + b'\0' + data + b'\0')
        if path.suffix in {'.jks', '.keystore', '.p12', '.pfx'} or re.search(
                rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----$', data):
            findings.append({'path': str(relative), 'rule': 'private key material'})
        if path.name.endswith('.trace.json'):
            findings.append({'path': str(relative), 'rule': 'raw trace files prohibited in public data repo'})
        if path.suffix == '.py':
            try:
                ast.parse(data, filename=str(relative))
            except SyntaxError:
                findings.append({'path': str(relative), 'rule': 'invalid Python syntax'})
    report['source_sha256'] = digest.hexdigest()
    report['findings'] = findings
    report['gates']['source'] = not findings
    import yaml
    workflow = yaml.safe_load((repo / '.github/workflows/map-data.yml').read_text())
    report['gates']['serialized_generation'] = (
        workflow['concurrency']['cancel-in-progress'] is False and
        workflow['jobs']['routing']['needs'] == 'build')
    if all(report['gates'].values()):
        suite = unittest.defaultTestLoader.discover(str(repo / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report['unit_counts'] = {'tests': result.testsRun, 'failures': len(result.failures),
                                 'errors': len(result.errors), 'skipped': len(result.skipped)}
        report['gates']['unit_tests'] = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        for name in ('search_offline', 'zones', 'arrows', 'limits', 'roadinfo'):
            report['gates'][name] = subprocess.run(
                [sys.executable, str(repo / 'scripts' / (name + '.py')), '--selftest'], cwd=repo).returncode == 0
    report['validation_passed'] = all(report['gates'].values())
    output = repo / 'build/reports/unified-preflight.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['validation_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
