"""Seal completed research; verify prior files without copying or editing them."""
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = HERE.parents[3]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_prior(start):
    pins = {}
    def pin(path, digest, size):
        path = path.resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert path.stat().st_size == size and sha(path) == digest, str(path)
        pins[str(path.relative_to(ROOT))] = {'path': str(path.relative_to(ROOT)), 'bytes': size, 'sha256': digest}
    for item in start['protected_pins']:
        pin(ROOT / item['path'], item['sha256'], item['bytes'])
    total = 0
    for study in start['prior_studies']:
        directory = ROOT / study['path']
        old = json.loads((directory / 'FINAL_MANIFEST.json').read_text())
        entries = old.get('files', old.get('files_excluding_manifest'))
        for item in entries:
            path = ROOT / item['path'] if item['path'].startswith('jeju/') else directory / item['path']
            pin(path, item['sha256'], item.get('bytes', item.get('size_bytes')))
        files = [p for p in directory.rglob('*') if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        assert size == study['bytes'] and len(files) == study['files'], study['path']
        total += size
    assert total == start['prior_total_bytes'] == 54709908
    return pins


def main():
    destination = STUDY / 'FINAL_MANIFEST.json'
    assert not destination.exists()
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    verification = json.loads((HERE / 'RESULT_VERIFICATION.json').read_text())
    assert verification['passed']
    review = json.loads((STUDY / 'review/RESULT_REVIEW.json').read_text())
    assert review['passed'], review
    assert (STUDY / 'README.md').is_file()
    pins = verify_prior(start)
    # The audit's source manifest is intentionally small; no DB snapshot is needed.
    sources = json.loads((STUDY / 'audit/SOURCE_AUDIT.json').read_text())
    assert sources['passed']
    for item in sources['source_references']:
        path = (ROOT / item['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], item['path']
        pins[str(path.relative_to(ROOT))] = {'path': str(path.relative_to(ROOT)),
                                           'bytes': item['bytes'], 'sha256': item['sha256']}
    records, groups = [], defaultdict(int)
    for path in sorted(STUDY.rglob('*')):
        if not path.is_file():
            continue
        assert not path.is_symlink()
        size = path.stat().st_size
        records.append({'path': str(path.relative_to(ROOT)), 'bytes': size, 'sha256': sha(path)})
        groups[path.relative_to(STUDY).parts[0]] += size
    total = sum(x['bytes'] for x in records)
    passed = verification['overall_gate_pass']
    manifest = {'status': 'COMPLETED_VERIFIED_RESEARCH', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'study': str(STUDY.relative_to(ROOT)),
        'decision': ('E passes frozen gates; research candidate only' if passed else
                     'E fails frozen gates; hold E and retain S as research candidate'),
        'operating_model_changed': False, 'F1_STYLE6_research_baseline_retained': True,
        'future_independent_validation': False, 'market_edge_verified': False,
        'new_model_fits': 0, 'new_calibrations': 0, 'mixture_weights': {'R': 0.5, 'S': 0.5},
        'study_budget_bytes': start['new_study_budget_bytes'], 'session_budget_bytes': start['session_budget_bytes'],
        'files_excluding_manifest': records, 'file_count_including_manifest': len(records)+1,
        'preserved_source_references': list(pins.values()), 'prior_session_studies': start['prior_studies'],
        'prior_session_bytes': start['prior_total_bytes'], 'manifest_bytes': 0,
        'new_study_bytes_including_manifest': 0, 'session_bytes_including_manifest': 0,
        'disk_free_bytes_at_finalize': shutil.disk_usage(ROOT).free,
        'storage_groups_bytes_excluding_manifest': dict(groups),
        'largest_new_files': sorted(records, key=lambda x: x['bytes'], reverse=True)[:10],
        'byte_accounting': 'Logical file bytes including code, compact Parquet, documentation and manifest; existing inputs referenced only',
        'self_hash_omitted': True}
    for _ in range(12):
        encoded = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
        new_total = total+len(encoded)
        if manifest['manifest_bytes'] == len(encoded) and manifest['new_study_bytes_including_manifest'] == new_total:
            break
        manifest.update(manifest_bytes=len(encoded), new_study_bytes_including_manifest=new_total,
                        session_bytes_including_manifest=start['prior_total_bytes']+new_total)
    else:
        raise RuntimeError('Manifest byte count did not converge')
    assert new_total <= start['new_study_budget_bytes']
    assert manifest['session_bytes_including_manifest'] <= start['session_budget_bytes']
    with destination.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps({'passed': True, 'new_bytes': new_total,
        'session_bytes': manifest['session_bytes_including_manifest'], 'new_files': len(records)+1,
        'source_pins': len(pins), 'free_bytes': manifest['disk_free_bytes_at_finalize'],
        'manifest_sha256': sha(destination)}, indent=2))


if __name__ == '__main__':
    main()
