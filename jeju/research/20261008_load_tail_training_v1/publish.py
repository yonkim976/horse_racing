"""Preserve estimates, correct planned multiplicity, publish research only."""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
ROOT = H.parents[2]
C = H.parent / 'conclusions'

def sha(p):
    v = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            v.update(chunk)
    return v.hexdigest()

def save(name, value):
    with (H / name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)

def put(p, text):
    p.write_text(text, encoding='utf-8')

def table(headers, rows):
    return '| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' + ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in rows)

prior = json.loads((C / 'source_manifest.json').read_text())
for r in prior['files']:
    assert sha(ROOT / r['path']) == r['sha256'], r['path']
verification = json.loads((H / 'independent_verification.json').read_text())
assert verification['status'] == 'passed'
for r in json.loads((H / 'source_manifest.json').read_text()):
    assert sha(Path(r['path'])) == r['sha256']

# The plan pools both outcomes. Preserve the initial per-outcome BH file and
# recompute only q values, without changing estimates, intervals, or p values.
effects = pd.read_csv(H / 'burden_effects.csv')
original = effects.copy()
for _, g in effects.groupby(['family', 'period', 'variant', 'exposure']):
    p = g.p.to_numpy(); order = np.argsort(p)
    q = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1].clip(0, 1)
    out = np.empty(len(q)); out[order] = q
    effects.loc[g.index, 'q_BH'] = out
assert effects.drop(columns='q_BH').equals(original.drop(columns='q_BH'))
with (H / 'burden_effects_bh_v2.csv').open('x') as f:
    effects.to_csv(f, index=False)
models = json.loads((H / 'training_prediction_models.json').read_text())
assert len(models) == json.loads((H / 'training_baseline_reproduction.json').read_text())['models']
save('publication_correction_provenance.json', {
    'initial_estimates_preserved': 'burden_effects.csv',
    'final_burden_inference': 'burden_effects_bh_v2.csv',
    'reason': 'PLAN pools both targets within family/period/variant/exposure; initial burden BH grouped by target. Only BH q values recomputed; all effects/CI/p/support unchanged.',
    'metadata_erratum': 'Independent verifier used literal13 for serialized model count; actual loop verified all12 models. Final verification records len(models)=12.',
    'no_refitting_or_candidate_selection': True
})
verification['serialized_prediction_reproductions'] = len(models)
verification['burden_BH_final_file'] = 'burden_effects_bh_v2.csv'
verification['burden_BH_pools_both_targets_as_planned'] = True
verification['initial_verifier_metadata_corrected_from_13_to_12'] = True
save('final_verification.json', verification)

raw = pd.read_csv(H / 'burden_raw_risks.csv')
full = raw[raw.period.eq('full')].set_index(['distance', 'burden_group'])
raw_rows = []
for dist in [800, 900, 1000, 1110, 1200]:
    s = full.loc[(dist, 'stableUnder1')]; u = full.loc[(dist, 'up3plus')]
    raw_rows.append([f'{dist}m', f'{int(s.raw_slow2_count):,}/{int(s.rows):,} ({100*s.raw_slow2_rate:.1f}%)', f'{int(u.raw_slow2_count):,}/{int(u.rows):,} ({100*u.raw_slow2_rate:.1f}%)'])
risk_rows = []
for period, label in [('full', '2017~2026 부분'), ('confirmation', '2024~2025'), ('2026partial', '2026 부분')]:
    g = effects[effects.family.eq('burden_risk') & effects.variant.eq('primary') & effects.period.eq(period) & effects.target.eq('relative_slow1') & effects.distance.isin([1000, 1110, 1200])]
    for r in g.itertuples():
        risk_rows.append([label, f'{r.distance}m', f'{r.rows:,}', f'{r.effect:+.1f}%p', f'{r.ci_lo:+.1f}~{r.ci_hi:+.1f}', f'{r.q_BH:.4f}'])
cases = pd.read_csv(H / 'burden_case_examples.csv', dtype={'horse_id': str})
case_rows = [[r.current_horse_name, r.horse_id, f'{r.distance}m', f'{r.previous_date} → {r.race_date}', f'{r.previous_burden_kg:g} → {r.burden_kg:g}kg', f'{r.previous_time:.1f} → {r.time:.1f}초', f'{r.relative_time_delta:+.2f}초'] for r in cases.itertuples()]
corr = pd.read_csv(H / 'training_raw_correlations.csv').set_index(['distance', 'exposure'])
corr_rows = [[f'{d}m', f"{corr.loc[(d,'training_days5'),'spearman_with_positive_time_improvement']:.3f}", f"{corr.loc[(d,'training_mean5'),'spearman_with_positive_time_improvement']:.3f}"] for d in [800, 900, 1000, 1110, 1200]]
metrics = pd.read_csv(H / 'training_prediction_metrics.csv').set_index(['period','distance','model'])
improve = pd.read_csv(H / 'training_prediction_improvements.csv').set_index(['period','distance','metric'])
prediction_rows = []
for period, label in [('2024_2025', '2024~2025'), ('2026partial', '2026 부분')]:
    for d in [1000, 1110, 1200]:
        base = metrics.loc[(period,d,'B')]; new = metrics.loc[(period,d,'E')]; r = improve.loc[(period,d,'mae')]
        prediction_rows.append([label, f'{d}m', f'{int(r.rows):,}', f'{base.mae_s:.4f}', f'{new.mae_s:.4f}', f'{r.effect:+.4f}', f'{r.ci_lo:+.4f}~{r.ci_hi:+.4f}', f'{r.q_BH:.4f}'])

decision = {
    'period_start': '2017-01-01', 'period_end': '2026-09-19', 'partial_2026': True,
    'source_rows': 52155, 'races': 5206, 'pairs': 27230,
    'increased_burden_large_worsening_cases_observed': True,
    'full_raw_slow2_adjusted_BH_distances': [1000],
    'full_relative_slow1_adjusted_BH_distances': [1000,1110,1200],
    'confirmation_relative_slow1_adjusted_BH_distances': [1000,1110,1200],
    'partial_2026_relative_slow1_adjusted_BH_distances': [],
    'threshold_above3kg_extra_time_slope_confirmed': False,
    'causal_load_attribution_established': False,
    'fixed_load_seconds_or_risk_penalty_adopted': False,
    'training_observed_days_not_intensity': True,
    'training_rows': 706222, 'training_prediction_eval_rows': 7709,
    'training_prediction_eval_races': 1273,
    'training_recent_association_BH_distances': [],
    'training_prediction_absolute_MAE_improved_BH_2024_2025_distances': [],
    'training_prediction_absolute_MAE_worsened_BH_2024_2025_distances': [1110],
    'training_prediction_absolute_MAE_improved_BH_2026_distances': [],
    'training_prediction_relative_MAE_improved_BH_distances': [],
    'all_possible_training_features_ruled_out': False,
    'historical_training_publication_verified': False,
    'independent_future_holdout': False,
    'fixed_training_correction_or_condition_score_adopted': False,
    'operational_change': False,
    'final_burden_inference_file': 'burden_effects_bh_v2.csv'
}
save('decision.json', decision)
report = '''# 부담중량 증량 뒤 큰 기록 악화와 조교의 기록 연관

2026년 10월 8일 연구 완료. **증량 뒤 크게 느려진 사례가 있으며, 3kg 이상 증량과 상대적 부진 위험의 연관도 관찰됐다. 조교 관측 일수·시간만으로 꾸준한 기록 향상이나 추가 예측 개선은 확인하지 못했다.** 증량의 순수 원인 효과나 조교 처방을 확정한 결과는 아니다.

## 대상과 비교 방법

기간은 2017-01-01~2026-09-19이며 2026년은 부분연도다. 정상 완전순위 52,155출전·5,206경주·2,813두, 7~13두 편성을 사용했다. 동일 말·정확 거리·원문 등급·연도, 7~60일 간격의 적격 출전 27,230쌍이다. 전체 경력의 바로 다음 출전이라는 보장은 없다. 기존 중량 연구의 품질 선정과 제외마 정책을 유지했다. 400m는 과거 워밍업으로 제외했다.

큰 악화의 연구용 기준은 원기록 2초 이상 증가와, 각 경주의 중앙 기록 대비 편차가 1초 이상 증가하는 것이다. 후자는 경주 전체가 느려진 부분을 일부 걷어내지만 상대편 능력·편성·페이스까지 완벽히 같게 만들지는 않는다. 둘 다 건강 이상 진단 기준이 아니다.

증량군은 +3kg 이상, 비교군은 변화 절댓값 1kg 미만이다. 부담 감소와 +1~3kg 미만은 별도 항으로 고려했다. 마체중 변화·이전 부담·간격·사건 나이·직전 성적과 과거 기록·두수 변화·함수율 등급과 게이트 변화·연중 주기·연도와 등급을 조정했다. 선형 확률 대비는 %p 단위의 조건부 연관이며 개별 확률로 사용하지 않는다. 조정 계수 외 nuisance에는 ridge1을 사용했다.

## 증량과 큰 기록 악화

아래는 **조정 전 실제 빈도**다. 출전쌍 단위이며, 이 비율 전부를 부담중량의 효과로 해석하지 않는다.

''' + table(['거리','부담 변화 1kg 미만: 2초 이상 악화','3kg 이상 증량: 2초 이상 악화'], raw_rows) + '''
증량군의 직전 성적이 훨씬 좋았다. 예를 들어 1000m 직전 순위 비율 평균은 안정군 0.588, 증량군 0.217이다(0에 가까울수록 상위). 좋은 성적 뒤 증량되는 선택과 평균 회귀가 섞이므로 원시 비율 차이를 고정 감점으로 바꾸지 않는다.

원기록 2초 이상 악화의 조정 위험 차이는 전체기간 1000m +6.88%p(점별95% +2.33~+11.42, q=0.0153)에서 BH 근거가 남았다. 1110m +6.02%p, 1200m +5.52%p는 불확실했고, 2024~2025년 원기록 악화는 어느 거리에서도 BH 근거가 남지 않았다.

경주 중앙 기록 대비 편차가 1초 이상 악화할 위험의 조정 차이는 아래와 같다. **최근 2024~2025년에도 1000·1110·1200m의 상대적 부진 위험과 증량의 연관은 남았다.** 2026년만 보면 구간이 넓고 모든 거리가 불확실하다. %p는 안정군 대비 차이이며 두 배 같은 배수가 아니다.

''' + table(['기간','거리','전체 비교쌍','상대 부진 위험 차이','점별95% 구간 %p','BH q'], risk_rows) + '''
같은 달·함수율 등급·마체중 변화 5kg 이내의 민감도 결과와 직전 성적 통제를 뺀 결과도 전체 표에 보존했다. 쌍 날짜 군집은 뒤 출전일 기준이어서 앞 출전일을 공유하는 서로 다른 말의 상관을 완전히 반영하지 못할 수 있다. 신뢰구간은 날짜+말 군집 공분산을 합한 보수적 구간으로, 교집합 공분산을 빼지 않았다.

시간에 대한 +3kg 전후 기울기 모형에서는 +3kg를 넘어서 감속이 급격히 커진다는 추가 기울기의 근거가 없었다. 전체기간 +5kg 대비의 시간 연관은 900m +0.498초(0.216~0.781), 1000m +0.329초(0.114~0.544)였지만, 기간·조건 제한에 안정적이지 않았다. 따라서 모든 말에 +3kg부터 큰 페널티를 주거나 +5kg면 2~3초 느려진다는 환산은 채택하지 않았다.

## 실제 사례

아래는 2024년 이후 +3~5kg, 원기록 2~5초 악화, 상대편차 1초 이상 악화, 같은 달·함수율 등급, 마체중 변화 5kg 이내 조건을 만족하는 최근 사례다. 모든 사례를 양 끝 원천 API/DB와 공식 말 ID로 확인했다. 이름은 현재 프로필 값이다. **발생 사례이며 증량만이 원인이라는 증거가 아니다.**

''' + table(['말','공식 ID','거리','이전 → 이후 날짜','부담중량','기록','상대편차 악화'], case_rows) + '''
## 조교와 기록 향상의 상관

일별 API18에서 연구 말 2,813두의 706,222행을 사용했다. 말·날짜는 고유하며 유효 시간이 없는 394행은 결측으로 남겼다. 경주일 D 기준 현재 28일은 D−29~D−2, 이전 28일은 D−57~D−30이다. 7·14일 창과 마지막 관측 경과일도 저장했다. 모든 특징은 T−2까지의 사건 날짜로 제한했다.

일수는 **조교가 관측된 날짜 수**, 시간은 유효한 일별 평균 분이다. 조교 속도·강도·거리·실제 운동 횟수와 같지 않다. run1/run2의 0을 운동 횟수로 사용하지 않았다. 관측 부재도 미훈련으로 취급하지 않았다. 현재28일은 모두 관측됐지만 이전28일은 7,559출전에서 관측이 없어 연관 모형의 완전 사례에서는 제외했다. 예측 모형은 결측 지표와 과거 학습 중앙값으로 처리했다.

두 출전 사이 관측 일수·평균 시간 변화와 기록 향상(이전 기록−현재 기록)의 단순 Spearman 상관은 다음과 같다. 양수는 더 많이 관측될수록 빨라진 방향이다. 값은 모두 작으며 교란을 조정한 효과가 아니다.

''' + table(['거리','관측 일수 변화 ↔ 기록 향상','일별 평균 시간 변화 ↔ 기록 향상'], corr_rows) + '''
같은 말·경주 효과와 이전 기록·체중·부담중량 등을 고려한 수준 비교에서는 전체기간 900m 관측 일수 +5일이 −0.167초(−0.273~−0.060)와 연관됐다. 같은 말의 두 출전 변화 비교에서는 800m 관측 일수 +5일이 −0.160초(−0.262~−0.058)와 연관됐다. 두 결과는 주로 2017~2023년 자료의 신호이며, 2024~2025년과 2026년에는 BH 기준을 충족한 일수·시간 연관이 없었다. 평균 시간 +5분의 연관도 어느 지원 거리·기간에서든 확정하지 못했다. 더 긴 조교가 효과가 없다는 동등성 증명이나 5일 추가 조교 권장이 아니다.

## 최근 기록에 조교를 추가한 예측 비교

앞선 최근 경기력 연구의 B(오래된 기록+최근1~5회 기록·추세)를 그대로 재현하고, E에 7·14·28일 관측 일수·평균 시간, 이전28일 대비 변화, 마지막 관측 경과일, 유효 시간 비율을 추가했다. 전년도까지 학습한 고정 ridge10이며 조교 창이나 하이퍼파라미터를 결과에 맞춰 선택하지 않았다. 7,709출전·1,273경주의 같은 평가행에서 비교했다. MAE는 작을수록 좋고 개선은 B−E다.

''' + table(['평가기간','거리','출전','B MAE 초','E MAE 초','개선 초','점별95% 구간 초','BH q'], prediction_rows) + '''
2024~2025년 확실한 개선은 없고 1110m에서는 약 0.011초 악화했다. 2026년 1000m 약 0.020초 개선은 명목상 구간이 양수지만 거리 다중비교 후 불확실(q=0.0661)하다. 경주 공통 오차를 제거한 상대 MAE에서도 어느 거리에서든 BH 근거가 있는 개선은 없었다. 800·900m는 2024~2025년 합계 표에 2024년만 들어가며 2026년은 900m만 지원했다. 1300·1400·1610m는 기존 예측 최소 표본 조건을 충족하지 못했다.

사건 날짜가 과거 공개 시각을 증명하지 않는다. 이번 예측은 사건 날짜 기준의 후향 실험이며, 반복 사용한 과거 자료이므로 독립 미래 검증도 아니다. 조교 시간 요약의 불확실성을 조교의 모든 정보나 훈련의 생리적 효과 부재로 확대하지 않는다.

## 판정과 저장·검증

증량은 평균 감속뿐 아니라 상대적 부진 위험 후보로도 남긴다. 다만 인과계수·개별 위험 확률·급격한 감속 임계값·고정 초 보정은 채택하지 않는다. 조교 관측 일수·시간은 설명 정보와 연구 후보로 보존하며 고정 가점·컨디션 점수·운영 입력 채택은 하지 않았다. HY_R_FORM, 공통 DB, 스키마, 모델 레지스트리와 더러브렛은 변경하지 않았다.

입력 DB SHA256은 `a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e`다. DB는 읽기 전용으로 사용했고 원천·기존 연구 해시를 확인했다. 모든 52,155개 출전의 1,848,287개 조교 창 원행 연결과 256개 창의 DB 독립 재조회, 12개 쌍 모형의 계수·공분산 독립 계산, 모든 12개 E 모형의 직렬화 예측과 4개 가중 ridge 독립 해를 확인했다. FE 모형은 별도 결합 해와의 최대 계수 차이 3.64e−8 미만이다.

초기 부담중량 표의 BH가 결과변수별로 나뉜 점을 출판 점검에서 발견했다. 계획대로 두 결과변수를 함께 보정한 **[burden_effects_bh_v2.csv](burden_effects_bh_v2.csv)**를 최종 판단에 사용한다. 계수·신뢰구간·p·원시 비율은 변경하지 않았고 초기 표도 보존했다. 독립 검증의 모형 개수 표기 13도 실제 검증한 12개로 정정했다. [정정 이력](publication_correction_provenance.json)과 [최종 검증](final_verification.json)에 남겼다.

질문·방법 고정은 [PLAN.json](PLAN.json), 실행은 [analyze.py](analyze.py), 전체 지원은 [burden_support.csv](burden_support.csv)·[training_support.csv](training_support.csv), 조교 효과는 [training_effects.csv](training_effects.csv), 전체 예측 비교는 [training_prediction_improvements.csv](training_prediction_improvements.csv), 최종 판정은 [decision.json](decision.json)을 따른다. [원천 연결](source_manifest.json)·[조교 창 ID 연결](training_window_lineage.json)·[보관 파일 크기와 해시](artifact_manifest.json)를 함께 보존한다. 같은 자료의 후속 연구를 독립 반복 검증으로 세지 않는다.
'''
with (H / 'README.md').open('x', encoding='utf-8') as f:
    f.write(report)

weight = C / '04_WEIGHT_SPEED.md'
text = weight.read_text()
section = '''## 큰 증량과 기록 악화 위험 후속

2017~2026-09-19 동일 말·정확 거리·등급·연도, 7~60일 27,230쌍에서 3kg 이상 증량을 변화 절댓값 1kg 미만과 비교했다. 원기록 2초 이상 악화의 원시 빈도는 1000m 10.5%→21.7%(4,079→871쌍), 1110m 14.3%→27.0%(2,562→593), 1200m 17.2%→26.5%(1,163→257)였다. 직전 성적이 좋은 말의 증량 선택과 평균 회귀가 섞인다.

직전 성적·체중·간격·함수율·계절·게이트 등을 조정한 원기록 악화 차이는 전체기간 1000m +6.88%p(점별95% +2.33~+11.42)에서 BH 근거가 남았다. 각 경주의 중앙 기록 대비 편차가 1초 이상 악화할 위험의 전체기간 차이는 1000m +5.95%p(+1.03~+10.87), 1110m +10.13%p(+3.62~+16.63), 1200m +13.28%p(+3.55~+23.01)다. 같은 상대 부진 기준은 2024~2025년에도 각각 +20.07·+18.95·+25.77%p로 BH 근거가 남았으나 2026년 부분기간에는 모두 불확실했다. 상대 부진은 경주 편성·상대 능력과도 연결돼 순수 중량 효과가 아니다.

+3kg 이후 추가 감속 기울기는 확정하지 못했다. 증량 뒤 2~4초 느려진 실제 사례는 있지만, 모든 말에 그만큼 보정하거나 임계값을 채택하지 않는다. [상세 후속과 사례](../20261008_load_tail_training_v1/README.md), [최종 부담중량 표](../20261008_load_tail_training_v1/burden_effects_bh_v2.csv), [판정](../20261008_load_tail_training_v1/decision.json)을 따른다. 조교 연구는 [별도 주제](06_TRAINING_RECORD.md)에 관리한다. 기존 체중·58kg·평균 감속 결과는 아래에 보존한다.

'''
text = text.replace('## 마체중 증감과 적정 체중 후속', section + '## 마체중 증감과 적정 체중 후속', 1)
put(weight, text)
training_topic = '''# 제주 조교 관측과 기록 향상

2026년 10월 8일 완료. 2017-01-01~2026-09-19(2026 부분연도), 52,155출전·5,206경주·2,813두의 일별 API18 706,222행을 사용했다. 조교 관측 일수·유효 평균 시간을 분석했으며 강도·속도·거리·실제 횟수는 분석하지 않았다.

**관측 일수 증가와 기록 향상의 단순 상관은 작고, 최근 기간에서 안정적인 조정 연관이나 최근 기록을 넘어선 추가 예측 개선을 확인하지 못했다.** 조교의 생리적 효과나 모든 조교 특징의 무용함을 뜻하지 않는다.

## 관찰 연관

동일 말·정확 거리·등급·연도 7~60일 27,230쌍에서 관측 일수 변화와 기록 향상의 Spearman r은 800·900·1000·1110·1200m 각각 0.086·0.086·0.081·0.024·0.034였다. 평균 시간 변화의 r은 −0.036~+0.017 범위다.

말·경주 효과와 이전 기록·부담·체중 등을 고려한 전체기간 900m 관측 일수 +5일은 −0.167초(점별95% −0.273~−0.060, 7,582출전), 출전쌍 변화 비교의 800m +5일은 −0.160초(−0.262~−0.058, 6,811쌍)와 연관됐다. 주로 2017~2023년의 신호이며 2024~2025년과 2026년에는 일수·시간 모두 BH 근거가 남지 않았다. 일별 평균 시간 +5분의 효과도 어느 지원 거리·기간에서든 확정하지 못했다.

## 최근 기록에 대한 추가 예측 비교

[최근 기록 연구](05_RECENT_FORM.md)의 B를 그대로 재현하고 조교 7·14·28일 요약·이전28일 대비 변화 등을 더한 E를 비교했다. 전년도까지 학습한 고정 ridge10, 같은 7,709출전·1,273경주의 후향 비교다. 2024~2025년 MAE는 1000m 1.2728→1.2705초(2,089출전), 1110m 1.5596→1.5703초(2,244), 1200m 1.8854→1.8681초(1,156)다. 1110m 약 0.011초 악화는 BH 근거가 남았고 확실한 개선은 없었다.

2026년 1000m 개선 0.0195초는 점별95% 0.0026~0.0365지만 BH q=0.0661로 불확실하다. 어느 거리에서도 경주 공통 오차를 제거한 상대 MAE의 BH 개선 근거는 없었다. 800·900m 최근 평가는 주로 2024년만 지원하고 1300·1400·1610m의 예측 비교 표본은 부족했다. 독립 미래 검증이나 HY_R_FORM 운영 모형의 비교는 아니다.

## 시간 계약과 한계

현재28일 창은 경주일 D의 D−29~D−2, 이전28일은 D−57~D−30이다. 모든 특징은 사건 날짜 T−2까지 제한했다. 날짜가 공개 시각을 증명하지 않아 운영 사전 가용성은 미검증이다. 관측 부재는 미훈련·건강함이 아니다. 유효 시간이 없는 원행 394개는 결측으로 남겼다. 최근 상태에 맞춰 조교량이 결정되는 역인과가 가능하므로 훈련 처방이나 인과계수로 쓰지 않는다.

고정 조교 가점·기록 환산·컨디션 점수와 운영 반영은 채택하지 않았다. [상세 연구](../20261008_load_tail_training_v1/README.md), [전체 조교 효과](../20261008_load_tail_training_v1/training_effects.csv), [전체 예측 비교](../20261008_load_tail_training_v1/training_prediction_improvements.csv), [최종 검증](../20261008_load_tail_training_v1/final_verification.json)을 따른다.
'''
assert not (C / '06_TRAINING_RECORD.md').exists()
put(C / '06_TRAINING_RECORD.md', training_topic)
recent = C / '05_RECENT_FORM.md'
put(recent, recent.read_text() + '\n## 조교 후속 연구 연결\n\n앞선 연구에서는 조교의 관측 범위만 확인했다. 이후 [조교와 기록 연구](06_TRAINING_RECORD.md)에서 일수·시간의 연관과 최근 기록 대비 추가 예측력을 비교했고, 안정적 개선은 확인하지 못했다. 진료 특징의 추가 예측력은 여전히 미검증이다.\n')
readme = C / 'README.md'
text = readme.read_text().replace('·최근 경기력 상태 연구다.', '·최근 경기력 상태·조교 연구다.')
text = text.replace('체중증감과기록의연관관찰.말별·암수별·거리별확정적정체중미확보.같은58kg의체중별추가감속은불확실', '체중 증감 연관과 큰 증량 뒤 상대 부진 위험 관찰. 확정 적정 체중·고정 보정은 미채택')
text = text.replace('| [원 연구와 버전 목록]', '| [조교와 기록 향상](06_TRAINING_RECORD.md) | 조교 관측 일수·시간의 최근 기록 대비 안정적 추가 개선 미확인 | 후향 비교 완료, 운영 미반영 |\n| [원 연구와 버전 목록]', 1)
put(readme, text)
sources = C / 'SOURCES.md'
text = sources.read_text().replace('같은 출전 자료가 여러 버전에 중복되므로', '| [20261008_load_tail_training_v1](../20261008_load_tail_training_v1/README.md) | 큰 증량과 기록 악화 위험·일별 조교와 기록 향상·최근 기록 대비 추가 예측 연구. 증량의 상대 부진 연관은 최근에도 관찰, 조교의 안정적 추가 개선 미확인. 최종 부담 BH는 계획대로 두 결과변수 공동 보정한 v2 표를 사용 |\n\n같은 출전 자료가 여러 버전에 중복되므로', 1)
put(sources, text)
register = json.loads((C / 'research_register.json').read_text())
register['scope'] = '2026-10-07부터 다시 시작한 기초·환경·번호·체중·부담중량·최근 경기력·조교 연구. 과거 제주 연구 전체의 재검토 목록은 아님.'
for topic in register['topics']:
    if topic['id'] == 'weight_speed':
        topic['body_optimum_source'] = topic['latest_source']
        topic['latest_source'] = '../20261008_load_tail_training_v1/README.md'
        topic['status'] = 'load_tail_risk_followup_completed_no_fixed_weight_correction'
        topic['latest_load_tail_followup'] = {k: v for k, v in decision.items() if k.startswith(('full_', 'confirmation_', 'partial_', 'causal_', 'threshold_', 'fixed_load'))}
        topic['latest_load_tail_followup']['source'] = '../20261008_load_tail_training_v1/README.md'
    if topic['id'] == 'recent_form':
        topic['training_followup'] = '../20261008_load_tail_training_v1/README.md'
        topic['decision']['training_medical_predictive_value_tested'] = False
        topic['decision']['training_observed_days_duration_predictive_value_tested_in_followup'] = True
        topic['decision']['medical_predictive_value_tested'] = False
register['topics'].append({'id': 'training_record', 'title': '조교 관측과 기록 향상', 'conclusion': '06_TRAINING_RECORD.md', 'latest_source': '../20261008_load_tail_training_v1/README.md', 'period_start': '2017-01-01', 'period_end': '2026-09-19', 'training_rows': 706222, 'evaluation_rows': 7709, 'evaluation_races': 1273, 'status': 'retrospective_training_association_and_incremental_prediction_completed_no_fixed_correction', 'operationally_applied': False, 'historical_publication_verified': False, 'stable_incremental_prediction_improvement_confirmed': False})
put(C / 'research_register.json', json.dumps(register, ensure_ascii=False, indent=2) + '\n')

links = 0
for p in [H / 'README.md'] + list(C.glob('*.md')):
    for dest in re.findall(r'\]\(([^)]+)\)', p.read_text()):
        if '://' in dest or dest.startswith('#'):
            continue
        target = (p.parent / dest.split('#', 1)[0]).resolve()
        assert target.exists(), (p, dest)
        links += 1
save('publication_verification.json', {'status': 'passed', 'local_markdown_links_checked': links, 'prior_source_files_unchanged': sum(r['role'] != 'conclusion_or_management' for r in prior['files']), 'burden_BH_matches_plan': True, 'all_effects_intervals_p_values_unchanged': True, 'training_serialized_models_verified': len(models), 'operational_change': False, 'archive_sizes_in': 'artifact_manifest.json', 'modified_management_sizes_in': '../conclusions/source_manifest.json'})
archive = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(H.iterdir()) if p.is_file()]
save('artifact_manifest.json', {'self_excluded': True, 'files': archive, 'bytes_excluding_this_manifest': sum(r['bytes'] for r in archive), 'count_excluding_this_manifest': len(archive)})
files = []
for r in prior['files']:
    if r['role'] == 'conclusion_or_management':
        p = ROOT / r['path']; r = dict(r, sha256=sha(p), bytes=p.stat().st_size)
    else:
        assert sha(ROOT / r['path']) == r['sha256'], r['path']
    files.append(r)
if not any(r['path'] == str((C / '06_TRAINING_RECORD.md').relative_to(ROOT)) for r in files):
    p = C / '06_TRAINING_RECORD.md'; files.append({'path': str(p.relative_to(ROOT)), 'role': 'conclusion_or_management', 'bytes': p.stat().st_size, 'sha256': sha(p)})
for p in sorted(H.iterdir()):
    if p.is_file():
        files.append({'path': str(p.relative_to(ROOT)), 'role': 'source_load_tail_training', 'bytes': p.stat().st_size, 'sha256': sha(p)})
final = {'updated_at': '2026-10-08', 'files': files, 'verification': {'status': 'passed', 'all_previous_source_hashes_unchanged': True, 'local_links_checked': links, 'latest_study': str(H.relative_to(ROOT)), 'latest_verification': str((H / 'final_verification.json').relative_to(ROOT))}, 'managed_files_bytes_excluding_this_manifest': sum(r['bytes'] for r in files)}
put(C / 'source_manifest.json', json.dumps(final, ensure_ascii=False, indent=2) + '\n')
assert all(sha(ROOT / r['path']) == r['sha256'] for r in files)
print(json.dumps({'status': 'published_research_only', 'new_archive_files': len(archive) + 1, 'new_archive_bytes': sum(p.stat().st_size for p in H.iterdir() if p.is_file()), 'local_links': links, 'previous_sources_preserved': True}, ensure_ascii=False))
