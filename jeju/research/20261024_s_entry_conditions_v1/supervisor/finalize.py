"""Verify preservation and seal this compact study; never modify its sources."""
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from preservation import sha, verify_prior

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = HERE.parents[3]


def main():
    destination = STUDY / 'FINAL_MANIFEST.json'
    assert not destination.exists()
    pins = verify_prior()
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    for name in ('INPUT_VERIFICATION.json', 'RESULT_VERIFICATION.json'):
        assert json.loads((HERE / name).read_text())['passed']
    result = json.loads((HERE / 'RESULT_VERIFICATION.json').read_text())
    report = json.loads((STUDY / 'experiment/outputs/report.json').read_text())
    assert result['research_gate_pass'] == report['overall_research_candidate_gate_pass']
    review = json.loads((STUDY / 'review/RESULT_REVIEW.json').read_text())
    assert review['passed'], review
    source = json.loads((STUDY / 'audit/source_contract.json').read_text())
    for item in source['source_references']:
        path = (ROOT / item['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert sha(path) == item['sha256'], str(path)
        assert path.stat().st_size == item['bytes'], str(path)
    records = []
    groups = defaultdict(int)
    for path in sorted(STUDY.rglob('*')):
        if not path.is_file():
            continue
        assert not path.is_symlink() and '__pycache__' not in path.parts
        size = path.stat().st_size
        records.append({'path': str(path.relative_to(ROOT)), 'bytes': size, 'sha256': sha(path)})
        groups[path.relative_to(STUDY).parts[0]] += size
    total = sum(x['bytes'] for x in records)
    manifest = {
        'status': 'COMPLETED_VERIFIED_RESEARCH',
        'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'study': str(STUDY.relative_to(ROOT)),
        'research_gate_pass': result['research_gate_pass'],
        'operating_model_changed': False, 'future_independent_validation': False,
        'market_edge_verified': False, 'first_publication_time_verified': False,
        'study_budget_bytes': 40000000, 'session_budget_bytes': 300000000,
        'prior_session_bytes': start['prior_total_bytes'],
        'preserved_prior_files': len(pins),
        'verified_source_reference_count': len(source['source_references']),
        'files_excluding_manifest': records, 'file_count_including_manifest': len(records) + 1,
        'manifest_bytes': 0, 'new_study_bytes_including_manifest': 0,
        'session_bytes_including_manifest': 0,
        'storage_groups_bytes_excluding_manifest': dict(groups),
        'largest_new_files': sorted(records, key=lambda x: x['bytes'], reverse=True)[:10],
        'disk_free_bytes_at_finalize': shutil.disk_usage(ROOT).free,
        'byte_accounting': 'Logical regular-file bytes including code, audit evidence, results and this manifest; existing sources are referenced, never copied.',
        'self_hash_omitted': True,
    }
    for _ in range(12):
        encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
        new_total = total + len(encoded)
        if manifest['manifest_bytes'] == len(encoded) and manifest['new_study_bytes_including_manifest'] == new_total:
            break
        manifest.update(manifest_bytes=len(encoded), new_study_bytes_including_manifest=new_total,
                        session_bytes_including_manifest=start['prior_total_bytes'] + new_total)
    else:
        raise RuntimeError('Manifest size did not stabilize')
    assert new_total <= 40000000 and start['prior_total_bytes'] + new_total <= 300000000
    with destination.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps({'new_study_bytes': new_total, 'session_bytes': start['prior_total_bytes'] + new_total,
                      'new_files': len(records) + 1, 'free_bytes': manifest['disk_free_bytes_at_finalize'],
                      'manifest_sha256': sha(destination)}, indent=2))


if __name__ == '__main__':
    main()
