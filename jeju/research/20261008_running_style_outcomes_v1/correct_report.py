"""Preserve the initial report and correct one prose count, without changing data."""
from pathlib import Path
import json
import re
import pandas as pd
from extract import HERE, ROOT, sha, save


def main():
    central = ROOT / 'jeju/research/conclusions'
    manifest = json.loads((central / 'source_manifest.json').read_text())
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in manifest['files'])
    a = pd.read_csv(HERE / 'run01/runner_types_and_evidence.csv', low_memory=False)
    h = pd.read_csv(HERE / 'run01/horse_distance_profiles.csv')
    row = h[(h.horse_id == 3101513) & (h.distance_m == 1110)].iloc[0]
    ids = list(map(int, row.source_api_record_ids.split('|')))
    phases = a[a.api_record_id.isin(ids) & a.fade_any].fade_phase.value_counts().to_dict()
    assert phases == {'막판': 3, '후반': 1}
    original = HERE / 'README.md'
    content = original.read_text()
    before = '후반 약화2회·막판 약화2회'
    assert before in content
    content = content.replace(before, '후반 약화1회·막판 약화3회')
    content = content.replace('[보관 크기와 해시](artifact_manifest.json)', '[최종 보관 크기와 해시](artifact_manifest_v2.json)')
    content += '\n보고서 v2는 마마골드1110m 약화4회의 시점별 설명을 후반1회·막판3회로 바로잡았다. [초기 보고서](README.md)와 [정정 근거](REPORT_CORRECTION.json)는 보존했고 계산표·분류·후속 결론은 동일하다.\n'
    (HERE / 'README_v2.md').write_text(content)
    save(HERE / 'REPORT_CORRECTION.json', {'status': 'corrected_prose_only', 'initial_report': 'README.md',
        'initial_report_sha256': sha(original), 'current_report': 'README_v2.md',
        'horse_id': '3101513', 'distance_m': 1110, 'issue': 'phase counts in one prose example were not reconciled before the first report save',
        'initial_phase_counts': {'late': 2, 'final': 2}, 'correct_phase_counts': {'late': 1, 'final': 3},
        'runner_ids': ids, 'analysis_data_changed': False, 'classification_or_findings_changed': False,
        'data_source': 'run01/runner_types_and_evidence.csv'})
    for name in ['07_RUNNING_STYLE.md', 'SOURCES.md']:
        p = central / name
        s = p.read_text().replace('../20261008_running_style_outcomes_v1/README.md', '../20261008_running_style_outcomes_v1/README_v2.md')
        if name == 'SOURCES.md':
            s = s.replace('이전 위치 성향 연구의 후속이며 첫 검증의 극소 오차 허용 문제와 최종검증을 함께 보존',
                          '이전 위치 성향 연구의 후속. 보고서v2에서 마마골드 약화 시점 설명 오기를 수정했고 원보고서·초기 검증·계산 결과를 보존')
        p.write_text(s)
    reg = json.loads((central / 'research_register.json').read_text())
    t = next(t for t in reg['topics'] if t['id'] == 'running_style')
    t['latest_source'] = '../20261008_running_style_outcomes_v1/README_v2.md'
    t['report_correction'] = '../20261008_running_style_outcomes_v1/REPORT_CORRECTION.json'
    save(central / 'research_register.json', reg)
    links = 0
    for p in list(central.glob('*.md')) + [HERE / 'README_v2.md']:
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            if '://' in target or target.startswith('#') or target.endswith('artifact_manifest_v2.json'):
                continue
            assert (p.parent / target.split('#')[0]).resolve().exists(), (p, target)
            links += 1
    save(HERE / 'publication_verification_v2.json', {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
        'local_links_checked': links, 'case_phase_counts_reconciled_to_entry_ids': True,
        'original_report_preserved': True, 'analysis_data_changed': False,
        'final_independent_verification': 'run01/verification_independent.json', 'operational_change': False})
    files = [{'path': str(p.relative_to(HERE)), 'bytes': p.stat().st_size, 'sha256': sha(p)}
             for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'artifact_manifest_v2.json']
    save(HERE / 'artifact_manifest_v2.json', {'self_excluded': True, 'supersedes_inventory': 'artifact_manifest.json',
        'files': files, 'total_bytes_excluding_this_manifest': sum(r['bytes'] for r in files)})
    records = {r['path']: r for r in manifest['files']}
    for p in central.iterdir():
        if p.is_file() and p.name != 'source_manifest.json':
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'conclusion_or_management', 'sha256': sha(p), 'bytes': p.stat().st_size}
    for p in HERE.rglob('*'):
        if p.is_file():
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'source_running_style_outcomes', 'sha256': sha(p), 'bytes': p.stat().st_size}
    manifest['files'] = list(records.values())
    manifest['verification'] = {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
        'latest_study': str(HERE.relative_to(ROOT)), 'latest_verification': str((HERE/'publication_verification_v2.json').relative_to(ROOT)), 'local_links_checked': links}
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in manifest['files'])
    save(central / 'source_manifest.json', manifest)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in manifest['files'])
    print(json.dumps({'current_report': str(HERE/'README_v2.md'), 'verified_phase_counts': phases,
        'archived_files': len(files)+1, 'bytes': sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file()), 'local_links_checked': links}, ensure_ascii=False))


if __name__ == '__main__':
    main()
