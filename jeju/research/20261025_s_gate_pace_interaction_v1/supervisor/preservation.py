"""Supervisor integrity checks for all reused studies and protected assets."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4194304), b''):
            h.update(block)
    return h.hexdigest()


def verify_prior():
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    pins = {}

    def check(path, size, digest):
        path = path.resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert path.stat().st_size == size and sha(path) == digest, str(path)
        pins[str(path.relative_to(ROOT))] = {'bytes': size, 'sha256': digest}

    for item in [*start['protected_pins'], *start['phase_reuse_tree_pins']]:
        check(ROOT / item['path'], item['bytes'], item['sha256'])
    total = 0
    for study in start['prior_studies']:
        directory = ROOT / study['path']
        m = study['manifest']
        check(ROOT / m['path'], m['bytes'], m['sha256'])
        manifest = json.loads((directory / 'FINAL_MANIFEST.json').read_text())
        for item in manifest.get('files', manifest.get('files_excluding_manifest')):
            p = ROOT / item['path'] if item['path'].startswith('jeju/') else directory / item['path']
            check(p, item.get('bytes', item.get('size_bytes')), item['sha256'])
        files = [p for p in directory.rglob('*') if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        assert size == study['bytes'] and len(files) == study['files'], study['path']
        total += size
    assert total == start['prior_total_bytes'] == 73536966
    return pins


if __name__ == '__main__':
    pins = verify_prior()
    print(json.dumps({'passed': True, 'protected_files': len(pins),
                      'prior_session_bytes': 73536966}, indent=2))
