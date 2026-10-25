"""Stage and compare-and-swap only the five central research documents."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path('/Users/kimyongjin/Desktop/horse_racing').resolve()
STUDY = ROOT / 'jeju/research/20261012_pair_jockey_basic_v1'
REVIEW = ROOT / 'jeju/research/20261012_pair_jockey_basic_review_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
HERE = Path(__file__).resolve().parent
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md', 'research_register.json', 'source_manifest.json']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'

def prepare():
    before, after = HERE / 'before', HERE / 'after'
    before.mkdir(); after.mkdir()
    old = {n: (CENTRAL / n).read_bytes() for n in NAMES}
    for name, contents in old.items():
        (before / name).write_bytes(contents)
    r = json.loads((STUDY / 'outputs/REPORT.json').read_text())
    assert r['pair_hit_rate_by_policy']['jockey_basic_candidate']['hits'] == 429
    assert not r['combined_pair_improvement_gate_passed']
    doc = '''# 두 말 동시 Top3 직접 pair 모형 평가

## 최신: 기수 기본 이력 한 항목 추가

F1_STYLE6 말 평가와 점수, 기존 20개 pair 입력 및 그 표준화, H1/H2 분리와 평가 경주를 유지하고 기수의 최근 365일 관측 입상 이력 한 열을 추가했다. 말 평가를 다시 학습하지 않았고, 새 후보의 pair 계수만 공동 적합했다. 평가는 2024-01-05~2026-09-19의 1,779경주·269경주일·17,412출전·76,848개 무순서 pair다. 경주마다 한 쌍을 선택해 두 말 모두 Top3에 들었는지 평가했다. 2026년은 부분연도다.

| 방식 | 동시입상 | 경주 | 동시입상률 |
|---|---:|---:|---:|
| 기수 최근 이력 추가 후보 | 429 | 1,779 | 24.11% |
| 기존 확장 H1 직접 pair | 427 | 1,779 | 24.00% |
| 이전 직접 pair | 426 | 1,779 | 23.95% |
| 원시 F1_STYLE6 점수 상위 2두 | 429 | 1,779 | 24.11% |
| 저장 F1_STYLE6 P(Top3) 상위 2두 | 429 | 1,779 | 24.11% |
| 기존 joint 주변확률 상위 2두 | 434 | 1,779 | 24.40% |
| 기존 joint 최대 pair | 422 | 1,779 | 23.72% |
| 기존 matched 최대 pair | 429 | 1,779 | 24.11% |

기수 항목의 사전 지정 추가 효과는 기존 427회 대비 **+0.112423%p**, 같은 날짜 bootstrap 95% CI **[−0.339568,+0.569492]%p**로 개선 기준을 통과하지 못했다. 원시 점수 Top2 429회 대비 차이는 **0%p**, CI **[−0.506201,+0.508776]%p**로 별도 기준도 미통과다. 기존 pair와 선택이 달라진 69경주에서 새 적중 10회·손실 8회·같은 결과 51회였다. 연도별 후보 적중은 153/150/126회, 기존 pair는 153/150/124회로 순증 2회는 2026년 부분연도에 있었다.

전체 pair의 Brier/log loss는 후보 0.062911/0.236507, 기존 0.062973/0.236880으로 소폭 감소했다. 실제 선택 pair에서는 후보 0.175132/0.531468, 기존 0.174929/0.530939로 소폭 증가했다. 이 확률 진단을 동시입상 개선으로 대체하지 않는다. 현재 기준선을 유지하고 후보는 연구 결과로 보존한다.

## 입력·시점·한계

공식 사건 기수 ID로 과거 출전을 묶는다. 경주일 T의 C=T−2일을 기준으로 (C−365일,C] 안의 관측 출전수 n, Top3 횟수 S, 편성 크기별 중립 기대합 E=Σ(3/편성수)를 구해 d=(S−E)/(n+20)으로 축소한다. n=0은 중립 0이며, pair 입력은 d_i+d_j 한 열이다. 20은 사전 고정 안정화 상수이고 최적값을 검증한 것이 아니다. H1에서만 새 열의 표준화와 21개 pair 계수를 학습하고 H2에서 후보 확률을 보정했다. 신규 학습은 3 H1 pair fit과 3 H2 map이며 말 모델 재학습은 0회다.

이 값에는 배정된 말의 질이 섞여 있어 순수 기수 능력이나 인과효과가 아니다. n은 정상완주 완전편성의 저장 cohort에서 관측한 출전수이며 실제 전체 기승수가 아니다. 현재 기수 배정은 후향 사건 snapshot이고, 과거 게시·변경 시각은 복원하지 못했다. 마방·기수 교체·범주형 기수 효과·전문 각질은 이번 후보에 포함하지 않았다. 반복 개발 자료이며 독립 미래 holdout이 아니다. 날짜 bootstrap은 이미 적합된 모델을 조건으로 한다. 운영 모델과 DB는 변경하지 않았다.

## 이전 결과 보존

직전 H1 확장 연구는 2,147/2,818/3,458경주로 학습창을 늘렸지만 427회로 이전 426회보다 1회 늘고 원시 Top2 429회보다 2회 적었다. 원시 Top2 대비 −0.112423%p, CI [−0.340716,+0.056917]%p로 개선이 확인되지 않았다. 이번 연구는 그 확장 학습창과 말 점수를 유지한 기수 항목의 별도 비교다. 이전 원본과 모든 저장 비교값을 보존했다.

## 재현 자료

- [최신 기수 기본정보 비교](../20261012_pair_jockey_basic_v1/README.md) 및 [산출물 manifest](../20261012_pair_jockey_basic_v1/ARTIFACT_MANIFEST.json)
- [최신 독립 검토](../20261012_pair_jockey_basic_review_v1/README.md) 및 [검토 receipt](../20261012_pair_jockey_basic_review_v1/independent_prediction_audit.json)
- [직전 H1 확장 연구](../20261011_pair_top3_oos_expansion_v1/README.md), [직전 독립 검토](../20261011_pair_top3_oos_expansion_review_v1/README.md)
- [최초 직접 pair 연구](../20261011_pair_top3_direct_v1/README.md), [기존 설계·원천 감사](../20261011_pair_top3_direct_design_v1/SOURCE_AUDIT.md)
'''
    (after / NAMES[0]).write_text(doc)
    readme = old['README.md'].decode()
    lines = readme.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('| [두 말 동시 Top3 직접 pair 모형 평가]'):
            lines[i] = '| [두 말 동시 Top3 직접 pair 모형 평가](22_DIRECT_PAIR_TOP3_MODEL.md) | 말 평가 유지·기수 최근 이력 1열 추가: 429/1,779, 기존 pair427 대비 +2; Δ+0.1124%p, 날짜 CI −0.3396~+0.5695%p | 추가 효과·raw429 대비 개선 미확인; 독립 검토 PASS; 운영 미반영 |'
        elif line.startswith('[두 말 동시 Top3 직접 pair 모형 평가](22_'):
            lines[i] = '[두 말 동시 Top3 직접 pair 모형 평가](22_DIRECT_PAIR_TOP3_MODEL.md): 기수 최근 이력 한 열을 추가한 후보는 429회, 기존 pair427회, 원시 Top2 429회였다. 추가 효과 +0.112423%p의 95% CI는 [−0.339568,+0.569492]%p로 개선 미확인이다. [최신 비교](../20261012_pair_jockey_basic_v1/README.md), [독립 검토](../20261012_pair_jockey_basic_review_v1/README.md), [이전 H1 확장](../20261011_pair_top3_oos_expansion_v1/README.md). 운영 미반영.'
    (after / 'README.md').write_text('\n'.join(lines) + '\n')
    sources = old['SOURCES.md'].decode() + '\n후속(2026-10-12): [기수 기본정보 한 열 추가](../20261012_pair_jockey_basic_v1/README.md) — F1_STYLE6 말 평가·확장 H1·기존 20열을 유지하고 T−2 최근 365일 관측 입상 이력 합 한 열을 추가. 429/1,779 대 기존427, 차이 +0.112423%p, 날짜 95% CI [−0.339568,+0.569492]%p. 원시 Top2 429와 동률이며 두 개선 기준 모두 미통과. [독립 검토](../20261012_pair_jockey_basic_review_v1/README.md), [주제 결론](22_DIRECT_PAIR_TOP3_MODEL.md). 운영 미반영.\n'
    (after / 'SOURCES.md').write_text(sources)
    reg = json.loads(old['research_register.json'])
    target = next(t for t in reg['topics'] if t['id'] == 'pair_top3_direct_20261011')
    target.update(previous_latest_source=target['latest_source'], latest_source='../20261012_pair_jockey_basic_v1/README.md', study_manifest='../20261012_pair_jockey_basic_v1/ARTIFACT_MANIFEST.json', independent_review='../20261012_pair_jockey_basic_review_v1/README.md', independent_validation='../20261012_pair_jockey_basic_review_v1/independent_prediction_audit.json', study_date='2026-10-12', publication_date='2026-10-12', primary_comparison='jockey_basic_candidate_vs_latest_expanded_direct427; raw_score_top2_429_secondary_gate; one unordered pair per race', direct_pair_hits=429, direct_minus_raw_top2_rate=0.0, direct_minus_raw_top2_paired_date_bootstrap_95pct_ci_rate=[-0.005062009839262454,0.00508776410132385], latest_baseline_direct_pair_hits=427, jockey_basic_added_columns=1, jockey_basic_minus_expanded_direct_rate=0.0011242270938729624, jockey_basic_yearly_hits={'2024':153,'2025':150,'2026_partial':126}, latest_feature_effect_confirmed=False, performance_improvement_confirmed=False, new_training_calls=3, latest_horse_model_train_calls=0, latest_H2_platt_maps=3, operationally_applied=False, status='retrospective_independent_reproduction_passed_jockey_basic_increment_unconfirmed_no_promotion')
    cmp = r['candidate_minus_fixed_comparator_date_bootstrap']
    target['jockey_basic_minus_expanded_direct_paired_date_bootstrap_95pct_ci_rate'] = [cmp['latest_expanded_direct_pair_427']['paired_date_bootstrap_95pct_ci'][k] for k in ['ci_low','ci_high']]
    target['direct_minus_raw_top2_paired_date_bootstrap_95pct_ci_rate'] = [cmp['raw_F1_STYLE6_score_Top2_429']['paired_date_bootstrap_95pct_ci'][k] for k in ['ci_low','ci_high']]
    target['jockey_basic_selection_changes_vs_expanded'] = r['selection_change_diagnostics']['latest_pair_427']
    target['previous_H2_platt_maps'] = target['H2_platt_maps']
    target['H2_platt_maps'] = 3
    target['previous_historical_F1_STYLE6_lightgbm_train_calls'] = target['historical_F1_STYLE6_lightgbm_train_calls']
    target['historical_F1_STYLE6_lightgbm_train_calls'] = 0
    reg.update(updated_at='2026-10-12', latest_study=str(STUDY.relative_to(ROOT)), latest_verification=str((REVIEW/'independent_prediction_audit.json').relative_to(ROOT)), latest_status='jockey_basic_increment_unconfirmed_no_promotion')
    (after / 'research_register.json').write_text(dump(reg))
    manifest = json.loads(old['source_manifest.json'])
    rows = {e['path']: e for e in manifest['files']}
    added = []
    for folder in [STUDY, REVIEW]:
        fm = json.loads((folder / 'ARTIFACT_MANIFEST.json').read_text())
        entries = fm.get('local_artifacts', fm.get('artifacts', fm.get('files', fm.get('review_artifacts'))))
        assert entries
        paths = []
        for e in entries:
            f = folder / e['path']
            if not f.exists(): f = ROOT / e['path']
            assert f.resolve().is_relative_to(folder) and sha(f) == e['sha256'] and f.stat().st_size == e['bytes']
            paths.append(f)
        paths.append(folder / 'ARTIFACT_MANIFEST.json')
        for f in paths:
            key = str(f.relative_to(ROOT)); assert key not in rows
            rows[key] = {'path':key,'role':'jockey_basic_pair_research_or_independent_review','sha256':sha(f),'bytes':f.stat().st_size}
            added.append(key)
        for rel, expected in fm.get('source_inputs_sha256',{}).items():
            assert sha(ROOT / rel) == expected, rel
    for name in NAMES[:-1]:
        key = str((CENTRAL / name).relative_to(ROOT)); f = after / name
        assert key in rows
        rows[key] = {**rows[key], 'sha256':sha(f), 'bytes':f.stat().st_size}
    manifest['files'] = list(rows.values())
    manifest['updated_at'] = '2026-10-12'
    manifest['latest_study'] = str(STUDY.relative_to(ROOT))
    manifest['latest_status'] = 'jockey_basic_increment_unconfirmed_no_promotion'
    manifest['latest_verification'] = str((REVIEW/'independent_prediction_audit.json').relative_to(ROOT))
    manifest['verification']['jockey_basic_pair_followup'] = 'Independent 21-basis fit, all 76848 predictions, fixed selectors, saved-date bootstrap and probability metrics passed; neither improvement gate passed; no operating change'
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(e['bytes'] for e in manifest['files'])
    (after / 'source_manifest.json').write_text(dump(manifest))
    receipt = {'status':'STAGED','before_sha256':{n:sha(before/n) for n in NAMES},'after_sha256':{n:sha(after/n) for n in NAMES},'new_source_entries':added,'prior_source_entries':len(json.loads(old['source_manifest.json'])['files']),'new_source_entries_count':len(added),'other_topics_preserved':True}
    (HERE / 'STAGING_RECEIPT.json').write_text(dump(receipt))
    print(dump(receipt))

def apply():
    r=json.loads((HERE/'STAGING_RECEIPT.json').read_text())
    assert all(sha(CENTRAL/n)==r['before_sha256'][n] and sha(HERE/'after'/n)==r['after_sha256'][n] for n in NAMES), 'Central or staged files changed; rebuild from fresh state'
    for n in NAMES:
        temp=CENTRAL/(n+'.jockey-publication-tmp')
        with temp.open('xb') as f: f.write((HERE/'after'/n).read_bytes())
        os.replace(temp,CENTRAL/n)
    assert all(sha(CENTRAL/n)==r['after_sha256'][n] for n in NAMES)
    r.update(status='PASS',scope='five central documents only; source study files unchanged')
    (HERE/'PUBLICATION_RECEIPT.json').write_text(dump(r))
    print(dump(r))

if __name__=='__main__':
    {'prepare':prepare,'apply':apply}[sys.argv[1]]()
