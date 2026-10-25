"""Seal the supervisor report and verify the preserved input/output inventory."""
import hashlib
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = HERE.parents[3]
OLD = STUDY.parent / '20261022_joint_wager_baseline_v1'
DESTINATION = STUDY / 'FINAL_MANIFEST.json'


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    assert not DESTINATION.exists(), 'Refusing to replace the finalized manifest.'
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    assert sha(OLD / 'FINAL_MANIFEST.json') == start['prior_manifest_sha256']
    old_manifest = json.loads((OLD / 'FINAL_MANIFEST.json').read_text())
    for item in old_manifest['files']:
        path = (OLD / item['path']).resolve()
        assert path.is_relative_to(OLD)
        assert sha(path) == item['sha256'] and path.stat().st_size == item['size_bytes'], path
    old_total = sum(path.stat().st_size for path in OLD.rglob('*') if path.is_file())
    assert old_total == start['prior_study_bytes']
    checked = {}
    for item in json.loads((HERE / 'SOURCE_REVIEW.json').read_text())['references']:
        path = (ROOT / item['path']).resolve()
        assert path.is_relative_to(ROOT)
        assert sha(path) == item['sha256'] and path.stat().st_size == item['size_bytes'], path
        checked[item['path']] = item['sha256']
    out = STUDY / 'experiment/outputs'
    report = json.loads((out / 'report.json').read_text())
    decision = json.loads((HERE / 'DECISION.json').read_text())
    verification = json.loads((HERE / 'RESULT_REVIEW.json').read_text())
    assert report['code_sha256'] == sha(STUDY / 'experiment/rank_stage.py')
    assert report['plan_sha256'] == sha(STUDY / 'experiment/PLAN.md')
    assert report['source_preflight_sha256'] == sha(out / 'source_preflight.json')
    assert report['approval']['sha256'] == sha(HERE / 'RANK_STAGE_EXECUTION_APPROVAL.json')
    assert decision['source_report_sha256'] == sha(out / 'report.json')
    assert verification['passed'] and not verification['overall_gate_pass']
    assert decision['decision'] == 'HOLD' and report['candidate_gate_status'] == 'FAIL_OR_PARTIAL'
    document = (STUDY / 'README.md').read_text()
    labels = ['단승', '연승', '복승', '쌍승', '복연승', '삼복승', '삼쌍승']
    keys = ['common_t_mean_race_nll', 'candidate_mean_race_nll', 'candidate_minus_common_nll',
            'common_t_mean_race_brier', 'candidate_mean_race_brier', 'candidate_minus_common_brier']
    for label, row in zip(labels, report['pool_comparisons_vs_common_T']):
        line = next(line for line in document.splitlines() if line.startswith(f'| {label} |'))
        cells = [value.strip().replace('−', '-') for value in line.strip('|').split('|')]
        assert int(cells[1]) == row['races']
        for value, key in zip(cells[2:], keys):
            assert abs(float(value) - row[key]) <= 5.001e-10, (label, key)
    annual = pd.read_parquet(out / 'pool_year_comparisons.parquet')
    for row in annual.loc[annual.pool.eq('TRI')].to_dict('records'):
        line = next(line for line in document.splitlines() if line.startswith(f"| {row['year']} |"))
        cells = [value.strip().replace('−', '-') for value in line.strip('|').split('|')]
        assert int(cells[1]) == row['races']
        assert abs(float(cells[2]) - row['candidate_minus_common_nll']) <= 5.001e-7
        assert abs(float(cells[3]) - row['candidate_minus_common_brier']) <= 5.001e-7
    decomposition = decision['decomposition']
    assert math.isclose(decomposition['nll_top3_set'] + decomposition['nll_order_given_top3_set'],
                        decomposition['nll_ordered_top3'], abs_tol=1e-12)
    assert math.isclose(sum(decomposition[key] for key in ['nll_first', 'nll_second_given_first',
                                                         'nll_third_given_first_two']),
                        decomposition['nll_ordered_top3'], abs_tol=1e-12)
    for link in re.findall(r'\]\(([^)]+)\)', document):
        if '://' not in link and link != 'FINAL_MANIFEST.json':
            assert (STUDY / link.split('#')[0]).exists(), link
    files = []
    for path in sorted(STUDY.rglob('*')):
        assert not path.is_symlink(), path
        if path.is_file():
            files.append(dict(path=str(path.relative_to(STUDY)), size_bytes=path.stat().st_size,
                              sha256=sha(path)))
    base_size = sum(item['size_bytes'] for item in files)
    groups = {}
    for item in files:
        group = item['path'].split('/')[0]
        groups[group] = groups.get(group, 0) + item['size_bytes']
    payload = dict(
        finalized_at_utc=datetime.now(timezone.utc).isoformat(),
        study_directory=str(STUDY),
        decision='HOLD',
        independent_calculation_verification_passed=True,
        all_pool_table_and_annual_tri_table_verified=True,
        source_and_prior_artifact_hashes_unchanged=True,
        new_study_target_bytes=start['new_study_target_bytes'],
        combined_new_research_budget_bytes=start['combined_new_research_budget_bytes'],
        prior_study_file_bytes=old_total,
        prior_manifest_sha256=start['prior_manifest_sha256'],
        prior_study_file_count=len(old_manifest['files']) + 1,
        logical_file_bytes_excluding_this_manifest=base_size,
        manifest_size_bytes=0,
        total_new_file_bytes_including_manifest=0,
        combined_new_research_file_bytes=0,
        new_file_count_including_manifest=len(files) + 1,
        disk_free_bytes_at_measurement=shutil.disk_usage(STUDY).free,
        byte_accounting='logical regular-file sizes; existing input artifacts referenced without copies',
        self_hash_omitted=True,
        unchanged_input_references=checked,
        bytes_by_top_level_path_excluding_manifest=groups,
        files=files)
    for _ in range(10):
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        size = len(encoded)
        if (payload['manifest_size_bytes'] == size
                and payload['total_new_file_bytes_including_manifest'] == base_size + size
                and payload['combined_new_research_file_bytes'] == old_total + base_size + size):
            break
        payload['manifest_size_bytes'] = size
        payload['total_new_file_bytes_including_manifest'] = base_size + size
        payload['combined_new_research_file_bytes'] = old_total + base_size + size
    else:
        raise AssertionError('Manifest size accounting did not stabilize.')
    assert base_size + size <= payload['new_study_target_bytes']
    assert old_total + base_size + size <= payload['combined_new_research_budget_bytes']
    with DESTINATION.open('xb') as handle:
        handle.write(encoded)
    actual_size = sum(path.stat().st_size for path in STUDY.rglob('*') if path.is_file())
    assert actual_size == payload['total_new_file_bytes_including_manifest']
    print(json.dumps(dict(new_file_bytes=actual_size,
                          new_file_count=payload['new_file_count_including_manifest'],
                          combined_new_research_file_bytes=old_total + actual_size,
                          disk_free_bytes=payload['disk_free_bytes_at_measurement'],
                          unchanged_references=len(checked),
                          manifest_sha256=sha(DESTINATION)), indent=2))


if __name__ == '__main__':
    main()
