"""Generate the final axis-failure experiment report and research records."""
import json,importlib.util
import failure_common as c
import pandas as pd
import duckdb

spec=importlib.util.spec_from_file_location('axis_failure_archive',c.HERE/'archive.py')
arc=importlib.util.module_from_spec(spec);spec.loader.exec_module(arc)

def pct(x):return f'{100*x:.2f}%'
def ci_pp(x):return f'{100*x[0]:+.2f}~{100*x[1]:+.2f}%p'

def main():
    c.check();r=json.loads((c.OUT/'results.json').read_text());d=json.loads((c.OUT/'diagnostics.json').read_text())
    v=json.loads((c.OUT/'verification.json').read_text());decision=json.loads((c.OUT/'decision.json').read_text())
    assert v['status']=='passed' and not decision['risk_improvement_criterion_passed'] and not decision['axis_improvement_criterion_passed']
    a=r['all'];p=a['probability'];selected=a['axis_policies']['selected'];m=pd.read_parquet(c.OUT/'race_predictions.parquet')
    assert selected['candidate_total']==3057 and selected['baseline_total']==3051
    names={'base_risk':'기존 1−입상확률','control_risk':'기존 위험 단순 보정','model_risk':'새 축 실패 위험 모델'}
    probabilities=['| 방법 | 평균 위험 | Brier ↓ | NLL ↓ | AUC ↑ | Average precision ↑ |',
        '|---|---:|---:|---:|---:|---:|']
    for key in names:
        z=p[key];probabilities.append(f'| {names[key]} | {pct(z["mean_prediction"])} | {z["brier"]:.6f} | {z["logloss"]:.6f} | {z["auc"]:.4f} | {z["average_precision"]:.4f} |')
    warnings=['| 경고 방법 | 경고 경주 | 실제 실패 | 정상 입상 축에 오경고 | 경고 중 실패율 | 전체 실패 포착률 |',
        '|---|---:|---:|---:|---:|---:|']
    for key in names:
        z=a['warning'][key];warnings.append(f'| {names[key]} | {z["races"]} | {z["failures"]} | {z["false_warnings"]} | {pct(z["precision"])} | {pct(z["failure_recall"])} |')
    policies=['| 축 선택 | 적중 / 4,799 | 적중률 | 변경 | 새 적중 / 기존 적중 상실 | 순증 |',
        '|---|---:|---:|---:|---:|---:|',f'| 기존 축 | 3,051 | {pct(selected["baseline_mean"])} | 0 | — | 0 |']
    for key,label in [('control','단순 보정 전부 반영'),('raw','새 위험 전부 반영'),('selected','전년도에서 반영 강도 선택')]:
        z=a['axis_policies'][key]
        policies.append(f'| {label} | {z["candidate_total"]:,.0f} | {pct(z["candidate_mean"])} | {z["switches"]} | '
            f'{z["gained_races"]} / {z["lost_races"]} | {z["candidate_total"]-z["baseline_total"]:+.0f} |')
    groups=['| 범위 | 경주 | 기존 축 | 위험 반영 축 | 순증 | 기존 → 새 위험 Brier |',
        '|---|---:|---:|---:|---:|---:|']
    for key,label in [('all','서울·부산 전체'),('seoul','서울'),('busan','부산'),('2024','2024년'),('2025','2025년'),
        ('2026','2026년(~9/20)'),('busan_grade5_1300_1600','부산 국5 1300·1600m'),('busan_grade5_1300_1600_2026','위 대상 2026년')]:
        z=r[key];q=z['axis_policies']['selected'];bp=z['probability']
        groups.append(f'| {label} | {z["races"]:,} | {q["baseline_total"]:,.0f} ({pct(q["baseline_mean"])}) | '
            f'{q["candidate_total"]:,.0f} ({pct(q["candidate_mean"])}) | {q["candidate_total"]-q["baseline_total"]:+.0f} | '
            f'{bp["base_risk"]["brier"]:.6f} → {bp["model_risk"]["brier"]:.6f} |')
    folds=['| 장소·평가연도 | 위험 학습 경주 | 전년도 보정 경주 | 트리 수 | 선택 λ | 전년도 적중 (λ=0/.25/.5/1) |',
        '|---|---:|---:|---:|---:|---|']
    for z in d['folds']:
        label={1:'서울',3:'부산'}[z['meet']]
        folds.append(f'| {label} {z["year"]} | {z["training_races"]:,} | {z["calibration_races"]:,} | {z["trees"]} | {z["lambda"]} | '
            +' / '.join(str(x) for x in z['calibration_policy_hits'].values())+' |')
    bins=['| 새 모델 예측 위험 구간 | 경주 | 실제 실패 | 평균 예측 위험 | 실제 실패율 |',
        '|---|---:|---:|---:|---:|']
    for z in json.loads((c.OUT/'calibration_bins.json').read_text()):
        if z['risk']=='model_risk':bins.append(f'| {z["bin"]} | {z["races"]:,} | {z["failures"]:,} | {pct(z["mean_probability"])} | {pct(z["actual_failure_rate"])} |')

    note='축 실패 위험의 Brier·AUC는 기존 위험을 넘지 못했다. 전년도 선택 축 정책은 3,051→3,057적중(+0.13%p)이지만 95% 구간이 0을 포함해 채택하지 않았다.'
    risk_ci=a['brier_comparisons']['base_risk']['difference_ci95'];control_ci=a['brier_comparisons']['control_risk']['difference_ci95']
    report=f'''# 선택된 축의 3착 밖 위험 모델: 추가 예측력 미확인

2026-10-24 · 연구58G · 서울·부산 · 시간순 역사적 개발 평가 · 운영 미반영.

**{note}** 위험 모델 6개와 과거 축 재현 모델 8개를 만들었다. 새 모델은 위험을 구분하지만 기존 입상확률에 비해 추가 정보가 있다는 증거를 확보하지 못했다. 이번 위험 모델과 축 변경 정책은 채택하지 않고 기존 연구 기준 state_gbm을 유지한다. 상대 10% 적중 개선은 달성하지 못했다.

## 기존 축만 대상으로 학습했다

각 경주에서 기존 모델이 고른 축 한 두만 표본으로 사용했다. 정상 4위 이하와 비완주·실격 등 미입상을 '축 실패=1', 공식 1~3위를 '축 실패=0'으로 학습했다. 하위 3두 모델과 달리 4·5위 등 중위권으로 밀리는 실패도 포함한다. 비완주에 임의의 착순을 붙이지 않았다. 평가 대상은 종전과 동일한 2024-01-05~2026-09-20의 4,799경주이며 기존 축 실패는 1,748건(36.42%), 적중은 3,051건(63.58%)이다. 기준은 연구 모델이며 당시 운영 추천의 성적이 아니다.

기존 축의 탈락확률은 이미 **1−입상확률**로 계산할 수 있다. 따라서 새 분류기를 만들었다는 사실만으로 새 정보가 생겼다고 볼 수 없다. 이 값을 기본 기준으로 두고, 전년도 자료에서 절편·기울기만 보정한 대조군도 함께 비교했다. 새 모델은 이 기본 위험의 logit을 초기 점수로 받아, 축의 상황이 기본 위험을 얼마나 더 높이거나 낮추는지 잔차를 학습한다.

입력은 기존 연구 특징에서 사전 고정한 숫자 50개다. 축의 전적수·휴양·나이·기록 수준/변동·과거 초반/종반·선행 후 후퇴·동적 능력/폼/종반 상태와 불확실성·부중 변화 38개, 거리·등급·두수·기본 위험·차순위와의 확률 및 상태 차이·편성 불확실성 등의 12개다. 현재 실제 구간·착순·배당이나 마명/마번 식별자는 입력하지 않았다. 세부 목록은 [동결 계약](outputs/protocol_frozen.json)에 있다.

## 위험 확률 자체가 나아졌는가

{chr(10).join(probabilities)}

Brier와 NLL은 낮을수록, AUC와 average precision은 높을수록 좋다. AUC는 실패마와 입상마를 구별하는 순위 지표이며 적중률이 아니다. 새 모델의 Brier는 기존보다 +0.000359 악화했고 날짜 단위 paired bootstrap 95% 구간은 [{risk_ci[0]:+.6f}, {risk_ci[1]:+.6f}]였다. 단순 보정 대조군 대비 차이도 +0.000137, 95% [{control_ci[0]:+.6f}, {control_ci[1]:+.6f}]로 개선을 확인하지 못했다. NLL과 AUC도 수치상 소폭 낮은 성능이었다.

새 모델과 기본 위험의 상관은 {d['risk_score_correlation']:.4f}, 확률 차이의 평균 절댓값은 {100*d['mean_absolute_probability_change']:.2f}%p였다. 위험 모형의 조기중단 결과는 1~32개 트리였으며 모든 입력을 길게 학습해도 전년도 성능이 계속 좋아지는 형태가 아니었다. 이 버전의 입력·학습 방식에서 추가 예측력을 확인하지 못했다는 의미이며, 모든 위험 모델이 원천적으로 불가능하다는 결론은 아니다.

## 위험 경고는 얼마나 맞았는가

장소·연도별 전년도 위험 분포의 상위 20% 문턱을 저장하고 다음 연도에 그대로 적용했다. 평가연도 경고 비율은 분포 변화 때문에 정확히 20%일 필요가 없다.

{chr(10).join(warnings)}

새 모델은 전체 경주의 19.42%인 932경주에 경고했고 실제 축 실패 487건을 포착했다. 나머지 **445건은 실제로 입상한 축에 대한 경고**였다. 전체 실패 1,748건 중 포착률은 27.86%로, 1,261건은 경고하지 못했다. 기존 위험보다 경고 중 실패율은 조금 높아 보이지만 경고 수가 달라 이 차이만으로 개선을 주장하지 않는다.

동일하게 위험 상위 960경주(약 20%)씩 고르는 사후 순위 진단에서는 기존 위험이 실패 **497건(51.77%)**, 새 모델이 **495건(51.56%)**을 잡았다. 단순 보정 대조군은 491건이었다. 따라서 '위험한 축을 더 잘 골랐다'는 주장도 뒷받침되지 않았다. 이 상위 960경주 비교는 평가 자료 전체의 순위 진단이며 실제 미래 경고 문턱과 구별한다.

{chr(10).join(bins)}

위험이 높은 구간에서 실제 실패가 더 잦으므로 위험 구분 자체는 작동한다. 하지만 기존 확률도 이미 이 구분을 하고 있었고, 새 모델이 그보다 좋아졌다는 결과는 아니다. 경고 경주를 빼고 남은 경주만 채점한 수치를 전체 축 개선으로 제시하지 않았다.

## 위험을 반영해 축을 바꾼 결과

새 위험 모형은 기존 축에서만 학습했으므로 2순위 말에 그대로 적용하지 않았다. 대신 원래 공동착순 분포를 '기존 축 입상'과 '기존 축 실패' 시나리오로 나누고, 두 상황의 질량만 새 위험에 맞게 바꿨다. 각 상황 안의 상대 분포는 유지했다. 그 결과 모든 말의 입상확률이 함께 조정되고 합3을 유지한다. 그 주변확률이 가장 큰 한 두를 새 축으로 선택했다.

원래 축 입상확률 p, 새 실패 위험 r에 대해 목표 입상확률은 p'=(1−λ)p+λ(1−r)이다. 축 입상 시나리오는 p'/p, 실패 시나리오는 (1−p')/(1−p)로 재가중한다. λ=1로 전부 반영한 원형과, 전년도 축 적중이 최대인 λ∈{{0,.25,.5,1}}을 고른 정책을 모두 평가했다. 동률이면 작은 λ를 썼다. 경주별 축 1두와 전체 경주 참여를 유지했고, 복승·복연 기존 1/3쌍 추천은 바꾸지 않았다.

{chr(10).join(policies)}

새 위험을 전부 반영하면 461경주를 바꿔 새 적중 125·기존 적중 상실 130, 총 **−5경주**였다. 전년도에서 강도를 정하면 221경주를 바꿔 새 적중 63·기존 적중 상실 57·동일 101로 **+6경주**였다. 이 정책의 축 적중률은 **63.58→63.70%, +0.13%p**, 상대 **+0.20%**다. 차이의 95% 구간은 **{ci_pp(selected['difference_ci95'])}**로 0을 포함한다. 사전 축 개선 조건을 통과하지 못했다.

{chr(10).join(groups)}

서울 +2·부산 +4경주였고, 연도별 +1/+2/+3경주로 점추정은 모두 양수였다. 그러나 부산 차이의 95% 구간도 {ci_pp(r['busan']['axis_policies']['selected']['difference_ci95'])}로 확정 개선이 아니다. 앞서 약했던 **부산 국5등급 1,300m·1,600m는 120→119**, 그중 2026년은 **36→35**로 나빠졌다. 전체 +6을 이 집단의 문제 해결로 해석하지 않는다.

## 학습 자료에서 고른 축을 다시 학습하지 않았다

2020~2023년 각각을 평가연도로 삼아 서울·부산 8개 과거 재현 모델을 만들었다. 원래 state_gbm과 같은 118입력·설정으로, 2017~Y−3 초기 학습→Y−2 조기중단→2017~Y−2 재학습→Y−1 온도 보정→Y 예측을 적용했다. 2024~2026년은 원래 6개 모델의 예측을 참조했다. 총 **10,770경주·117,501두**의 과거 예측을 생성했고 경주마다 하나의 축 표본을 만들었다. 모든 축과 보정 온도는 해당 경주보다 이전 연도의 자료에서 나온다.

위험 모델은 평가연도 Y마다 2020~Y−3 초기 학습, Y−2 조기중단, 2020~Y−2 최종 재학습, Y−1 확률 보정·반영 강도 선택, Y 평가를 사용했다. 예를 들어 2024년 위험 모델은 2020~2022년 축만 최종 학습하고 2023년에서 보정했다. 경주 전체가 시간순으로 분리되며 랜덤 출전마 분할은 사용하지 않았다.

위험 모델 설정은 학습률 .03·7잎·최소잎75·L2=10·최대400·조기중단30·seed20261024·CPU4threads·경주 균등가중이다. 저장 모델은 잔차만 출력하므로 예측 때 기본 위험 logit을 반드시 더한다. 전년도 확률 보정은 절편[-2,2]·양의 기울기[.25,4], 평균 NLL + .01/2×(절편²+(기울기−1)²), L-BFGS-B 최대300회다. 전년도 보정과 강도 선택의 성적은 모델 선택 자료이며 미래 평가 성적으로 제시하지 않는다.

{chr(10).join(folds)}

## 검산과 보관

- 공식 DB로 축 정답 **{v['official_axis_training_labels_checked']:,}건**, 후보 축 추천 **{v['official_candidate_axis_predictions_checked']:,}건**을 직접 채점했다.
- 과거 재현 8개·기존 6개 모델 점수 **{v['base_score_rows_replayed']:,}행**, 새 위험 예측 **{v['new_risk_predictions_replayed']:,}건**을 저장 모델에서 다시 계산했고 최대 오차는 모두 0이었다.
- 축 입력 **{v['axis_feature_records_reconstructed']:,}건**과 조건부 확률을 원자료에서 재구성했다. 현재 정답을 변조해도 입력·예측·선택이 변하지 않음을 검사했다.
- 축 정책 **{v['coherent_policy_records_checked']:,}건**을 원래 3두 집합 질량의 직접 재가중과 대조했다. 주변확률 최대 오차 {v['coherent_marginal_max_error']:.3g}, 전체 착순 분포도 장소·연도 {v['full_ordered_distribution_folds_checked']}개에서 확인했다.
- 전년도 보정·경고 문턱·강도 선택, 과거 출처≤T−2, 상태 출처 감사, 원천 DB·기존 모델·운영 등록부 해시 불변을 확인했다. 합성 자료에서 잔차 초기점수·보정 gradient·공동확률 재가중을 검사했다. 외부 독립 리뷰어의 검증은 아니다.

현재 결과는 반복 사용한 과거 개발 자료다. 새 과거 예측을 정직하게 생성했어도 같은 2024~2026 기간에서 연구 방향을 반복 선택한 편향이 사라지지 않는다. 날짜 bootstrap2,000회·seed20261027은 말별 날짜 간 의존성과 다중비교를 완전히 처리하지 않는다. 부산 국5 대상은 이전 결과를 보고 정한 탐색 집단이다. 2026년은 9/20까지(부산9/18) 부분연도다. 당시 부담중량/확정 명단 공시 시각, 후기 원자료의 완전한 특징 재현 미완료 한계도 남는다. 금전 수익률·새 미래 기간 성능은 검증하지 않았다.

이번 **축 실패 위험 모형은 연구 후보로만 보관**한다. 운영 `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`와 원천 DB를 유지했고 추가 수집·게시·배포·예약은 없다. 기존 DB·전체 특징·상태·기본모델은 복사하지 않았다. 새 최종모델은 과거 재현8개·위험6개이며, 앞선 일곱 연구148,849,873bytes와 신규 보관량 합계가300,000,000bytes 미만임을 검사한다.

[사전계획](PLAN.md) · [전체 수치](outputs/results.json) · [경고와 교체 사례](CASES.md) · [학습 표본 감사](outputs/examples_audit.json) · [재현 검증](outputs/verification.json) · [진단](outputs/diagnostics.json) · [미게시 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json) · [선행 하위 3두 모델](../20261023_bottom3_risk_v1/README.md).
'''
    (c.HERE/'README.md').write_text(report)
    (c.HERE/'PUBLICATION.md').write_text(f'''# 축이 3착 밖으로 밀릴 위험을 따로 학습한 결과

2026-10-24 · 연구58G · 웹사이트 미게시 · 운영 미반영.

{note}

기존 모델이 고른 축만 대상으로 실패 여부를 학습했다. 자기 학습 자료에서 고른 축을 다시 학습하지 않도록 2020~2023년 과거 예측부터 만들었고, 서울·부산 4,799경주를 기존과 동일하게 평가했다.

새 모델의 Brier는 0.219713→0.220072, 실패 구별 AUC는 0.6348→0.6326으로 기존 위험(1−입상확률)을 넘지 못했다. 동일하게 위험 상위 960경주를 골랐을 때 실제 실패는 기존 497건·새 모델 495건이었다.

전년도 문턱으로 위험 경고를 하면 932경주 중 487건의 실패를 잡았지만, 실제 입상한 축 445건에도 경고했다. 전체 실패 포착률은 27.86%다. 위험 경고가 곧 안전한 축 제외를 뜻하지 않는다.

새 위험을 축 선택에 전부 반영하면 3,051→3,046적중으로 5경주 줄었다. 전년도에서 반영 강도를 고르면 3,057적중(+6), 63.58→63.70%였다. 하지만 차이 95% 구간 −0.34~+0.59%p로 확정 개선이 아니다. 부산 전체는 +4였으나 국5 1300·1600m는 120→119, 2026년만은 36→35였다.

연구 후보로 보관하고 운영에는 적용하지 않는다. 상대 10% 축 개선은 미달성이다. 반복 사용한 과거 개발 자료이며 새 미래 검증이나 수익률 개선 결과가 아니다. [전체 방법·수치·검증](README.md) · [사례](CASES.md).
''')
    with duckdb.connect(str(c.old.DB),read_only=True) as con:
        official=con.execute("""SELECT CAST(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||CAST(race_no AS VARCHAR) race_key,
            chul_no program_no,horse_name_raw,finish_order,result_status FROM entry_result WHERE canonical_meet IN (1,3)""").df()
    official=official.set_index(['race_key','program_no'])
    def horse(key,program):
        z=official.loc[(key,int(program))]
        finish=f'{int(z.finish_order)}위' if z.result_status=='finished' else str(z.result_status)
        return f'{z.horse_name_raw}({int(program)}번)·{finish}'
    table=['| 경주 | 기존 축·실제 | 기존 실패 위험 | 새 실패 위험 | 축 변경 |',
        '|---|---|---:|---:|---|']
    high=m[m.meet.eq(3)&m.year.eq(2026)].sort_values(['model_risk','race_key'],ascending=[False,True]).head(12)
    for row in high.itertuples():
        table.append(f'| {row.race_key} | {horse(row.race_key,row.axis_program_no)} | {pct(row.base_risk)} | {pct(row.model_risk)} | '
            f'{"유지" if row.selected_program_no==row.axis_program_no else horse(row.race_key,row.selected_program_no)} |')
    target=m.meet.eq(3)&m.grade_raw.eq('국5등급')&m.distance_m.isin([1300,1600])&m.selected_program_no.ne(m.axis_program_no)
    changed=['| 경주 | 기존 축·실제 | 변경 축·실제 | 기존 → 새 실패 위험 | 적중 변화 |',
        '|---|---|---|---:|---:|']
    for row in m[target].sort_values('race_key').itertuples():
        changed.append(f'| {row.race_key} | {horse(row.race_key,row.axis_program_no)} | {horse(row.race_key,row.selected_program_no)} | '
            f'{pct(row.base_risk)} → {pct(row.model_risk)} | {row.selected_hit-row.axis_hit:+d} |')
    (c.HERE/'CASES.md').write_text(f'''# 축 실패 위험 경고와 교체 사례

2026-10-24 · 연구58G. 당시 운영 추천이 아닌 역사적 개발 평가다. 위험은 기존 축이 Top3에 들지 못할 확률이며, 변경 축 자체의 실패 확률은 아니다. 선택 강도는 전년도에서 정했다.

## 2026년 부산 전체 중 새 모델 위험 상위 12경주

실제 결과를 기준으로 고르지 않고 새 위험 순으로 나열했다. 입상한 말도 포함된다. 높은 위험은 실패 확정이 아니다.

{chr(10).join(table)}

## 부산 국5 1300·1600m에서 축이 바뀐 전체 11경주

새 적중 2·기존 적중 상실 3·동일 6, 총 −1경주다. 2026년만은 10경주가 바뀌어 36→35적중이었다.

{chr(10).join(changed)}

[전체 경주별 예측](outputs/race_predictions.parquet) · [위험 구간별 보정](outputs/calibration_bins.json) · [보고서](README.md).
''')
    arc.CONCLUSION.write_text(f'''# 선택된 축의 3착 밖 위험 모델

2026-10-24 · 연구58G · 구현·학습·평가·재현 검증 완료 · 운영 미반영.

**{note}** 위험6모델과 과거 축 재현8모델을 생성했다. 기존 축만 학습 표본으로 사용하고 기본 실패 logit의 잔차를50개 사전 고정 입력으로 학습했다. 자기 학습 경주에서 고른 축을 다시 학습하지 않도록 2020~2026년10,770경주의 시간순 예측을 구성했다.

{chr(10).join(probabilities)}

새 모델의 위험 상위960경주에서 실제 실패495건, 기존 위험에서는497건이었다. 전년도 문턱 경고는932경주·실패487·입상 축 오경고445, 전체 실패 포착27.86%였다. 단순 보정 대조군 대비 추가 예측력도 확인하지 못했다.

{chr(10).join(groups)}

새 위험을 전부 반영한 축은3,051→3,046으로−5경주였다. 전년도에서 강도를 선택한 정책은221경주 변경, 새 적중63·상실57로3,057적중(+6·+0.13%p·상대+0.20%)이지만95%구간−0.34~+0.59%p로0을 포함했다. 축 입상/실패 시나리오 질량만 재가중해 공동분포를 보존했으며, 복승·복연 쌍 추천은 고정했다. 부산 국5 대상은 전체120→119·2026년36→35로 개선되지 않았다.

기본 점수241,923행·위험 예측10,070건 재현 오차0, 축 정답10,770건·후보 추천14,397건 공식 DB 채점, 모든10,770축 입력 재구성, 공동분포·전년도 선택·정답변조 불변을 검증했다. 새 모델과 축 정책은 연구 후보로만 보관하고 운영 및 state_gbm 연구 기준을 유지한다. 상대10%축 개선은 미달성이다. 반복 개발 자료·당시 공시 시각·부분연도 한계와 미래 독립 검증 부재를 명시한다.

[전체 원문](../{c.HERE.name}/README.md) · [사전계획](../{c.HERE.name}/PLAN.md) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [미게시 요약](../{c.HERE.name}/PUBLICATION.md) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json).
''')
    arc.finish(note)

if __name__=='__main__':main()
