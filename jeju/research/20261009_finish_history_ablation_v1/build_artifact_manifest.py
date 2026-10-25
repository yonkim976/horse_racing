"""Create a hash/size inventory for this study; the manifest does not hash itself."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
MANIFEST = HERE / 'ARTIFACT_MANIFEST.json'
REVIEW = HERE.parent / '20261009_finish_and_condition_review_v1' / 'independent_verification.json'


def entry(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def main():
    lock = json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    source_references = {}
    for relative, expected in lock['references'].items():
        path = HERE.parents[2] / relative
        actual = entry(path)
        assert actual['sha256'] == expected, f'reference hash changed: {relative}'
        source_references[relative] = actual
    local_files = {}
    for path in sorted(HERE.rglob('*')):
        if not path.is_file() or path == MANIFEST:
            continue
        local_files[str(path.relative_to(HERE))] = entry(path)
    payload = {
        'scope': 'This study folder only; ARTIFACT_MANIFEST.json excludes its own hash.',
        'source_references': source_references,
        'protected_files': lock['protected'],
        'local_files': local_files,
        'independent_review_receipt': {
            'path_relative_to_jeju_research': str(REVIEW.relative_to(HERE.parent)),
            **entry(REVIEW),
        },
        'file_count_excluding_manifest': len(local_files),
        'bytes_excluding_manifest': sum(item['bytes'] for item in local_files.values()),
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'manifest': str(MANIFEST),
        'local_file_count': payload['file_count_excluding_manifest'],
        'local_bytes': payload['bytes_excluding_manifest'],
        'review_receipt': payload['independent_review_receipt'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
