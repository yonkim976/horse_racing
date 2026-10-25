"""Read-only integrity checks; never copy or modify earlier research assets."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = HERE.parents[3]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def verify_prior():
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    pins = {}

    def verify(path, size, digest):
        assert not path.is_symlink()
        path = path.resolve(strict=True)
        assert path.is_relative_to(ROOT), str(path)
        assert path.stat().st_size == size, str(path)
        assert sha(path) == digest, str(path)
        key = str(path.relative_to(ROOT))
        pins[key] = {'path': key, 'bytes': size, 'sha256': digest}

    for item in start['protected_pins']:
        verify(ROOT / item['path'], item['bytes'], item['sha256'])
    total = 0
    for study in start['prior_studies']:
        directory = ROOT / study['path']
        manifest = json.loads((directory / 'FINAL_MANIFEST.json').read_text())
        for item in manifest.get('files', manifest.get('files_excluding_manifest')):
            path = ROOT / item['path'] if item['path'].startswith('jeju/') else directory / item['path']
            verify(path, item.get('bytes', item.get('size_bytes')), item['sha256'])
        files = [p for p in directory.rglob('*') if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        assert size == study['bytes'] and len(files) == study['files'], study['path']
        total += size
    assert total == start['prior_total_bytes'] == 57799506
    return pins


if __name__ == '__main__':
    pins = verify_prior()
    print(json.dumps({'passed': True, 'preserved_files': len(pins),
                      'prior_study_bytes': 57799506, 'operating_registry_and_model_unchanged': True}, indent=2))
