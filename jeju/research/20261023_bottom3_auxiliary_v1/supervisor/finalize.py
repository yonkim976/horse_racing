"""Seal verified research and exact storage without modifying earlier work."""
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone

from preservation import HERE, STUDY, ROOT, sha, verify_prior


def main():
    destination = STUDY / 'FINAL_MANIFEST.json'
    assert not destination.exists()
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    proof = json.loads((HERE / 'RESULT_VERIFICATION.json').read_text())
    review = json.loads((STUDY / 'review/RESULT_REVIEW.json').read_text())
    audit = json.loads((STUDY / 'audit/SOURCE_AUDIT.json').read_text())
    assert proof['passed'] and review['passed'] and audit['passed']
    assert (STUDY / 'README.md').is_file()
    pins = verify_prior()
    for entry in audit['source_references']:
        path = (ROOT / entry['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
        pins[entry['path']] = {k: entry[k] for k in ('path', 'bytes', 'sha256')}
    entries, groups = [], defaultdict(int)
    for path in sorted(STUDY.rglob('*')):
        if not path.is_file():
            continue
        assert not path.is_symlink()
        size = path.stat().st_size
        entries.append({'path': str(path.relative_to(ROOT)), 'bytes': size, 'sha256': sha(path)})
        groups[path.relative_to(STUDY).parts[0]] += size
    total = sum(item['bytes'] for item in entries)
    manifest = {
        'status': 'COMPLETED_VERIFIED_RESEARCH',
        'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'study': str(STUDY.relative_to(ROOT)),
        'prediction_followup_gate_pass': proof['prediction_followup_gate_pass'],
        'exclusion_followup_gate_pass': proof['exclusion_followup_gate_pass'],
        'operating_model_changed': False,
        'F1_STYLE6_research_baseline_retained': True,
        'upper_ranking_and_wager_probabilities_changed': False,
        'future_independent_validation': False,
        'market_edge_verified': False,
        'new_lightgbm_fit_calls': 6,
        'new_saved_models': 3,
        'new_temperature_calibrations': 6,
        'study_budget_bytes': start['study_budget_bytes'],
        'session_budget_bytes': start['session_budget_bytes'],
        'files_excluding_manifest': entries,
        'file_count_including_manifest': len(entries) + 1,
        'preserved_source_references': list(pins.values()),
        'prior_session_studies': start['prior_studies'],
        'prior_session_bytes': start['prior_total_bytes'],
        'manifest_bytes': 0,
        'new_study_bytes_including_manifest': 0,
        'session_bytes_including_manifest': 0,
        'disk_free_bytes_at_finalize': shutil.disk_usage(ROOT).free,
        'storage_groups_bytes_excluding_manifest': dict(groups),
        'largest_new_files': sorted(entries, key=lambda x: x['bytes'], reverse=True)[:10],
        'byte_accounting': 'Logical file bytes including code, compressed Parquet, text models, documentation and manifest; prior sources referenced only',
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
        raise RuntimeError('Manifest byte count did not converge')
    assert new_total <= start['study_budget_bytes']
    assert manifest['session_bytes_including_manifest'] <= start['session_budget_bytes']
    with destination.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps({'passed': True, 'new_bytes': new_total,
                     'session_bytes': manifest['session_bytes_including_manifest'],
                     'files': len(entries) + 1, 'source_pins': len(pins),
                     'disk_free_bytes': manifest['disk_free_bytes_at_finalize'],
                     'manifest_sha256': sha(destination)}, indent=2))


if __name__ == '__main__':
    main()
