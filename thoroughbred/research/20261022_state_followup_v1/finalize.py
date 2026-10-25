"""Publish local research documents from completed, verified measurements."""
import json
import pandas as pd
import support as s
import document_support as docs
import analyze_followup as analysis

LABELS={'additive89':'기존 EL89','full103':'기존 F103','strong89':'충분학습 EL89',
    'state_gbm':'전체 상태29 + GBM','state_joint':'전체 상태29 + 공동착순 신경망',
    'rank_only':'순위 상태9 + GBM','no_rank':'순위 외 상태20 + GBM','simple_rank':'단순 착순9 + GBM',
    'cal_candidate':'보정 항상 적용','cal_selected':'전년도 검증으로 보정 선택'}
ORDER=['additive89','full103','strong89','state_gbm','state_joint','rank_only','no_rank','simple_rank']

def delta(x,scale=1,digits=6):
    lo,hi=x['difference_ci95']
    return f"{scale*x['difference']:+.{digits}f} [{scale*lo:+.{digits}f}, {scale*hi:+.{digits}f}]"

def main():
    s.check();r=json.loads((s.OUT/'results.json').read_text())
    verification=json.loads((s.OUT/'verification.json').read_text());assert verification['status']=='passed'
    by={row['variant']:row for row in r['overall']}
    assert [by[v]['hits']['quinella_three'] for v in ['state_gbm','rank_only','no_rank','simple_rank']]==[1505,1499,1459,1431]
    assert all(not r['decisions'][v]['retain_over_state_gbm'] for v in s.contracts())
    assert not r['decisions']['cal_selected']['probability_improvement_confirmed']
    table=['| 모델 | 축 Top3 | 복승1 | 복승3 | 복연1 | 복연3 | 복연 적중 수/경주 | 공동착순 NLL |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for v in ORDER:
        row=by[v];cells=[f"{100*row['means'][k]:.2f}% ({row['hits'][k]:,})" for k in ['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three']]
        table.append('| '+LABELS[v]+' | '+' | '.join(cells)+f" | {row['means']['qpl_count']:.5f} | {row['means']['ordered_logloss']:.6f} |")
    differences=['| 후보 / 기준 | 축 차이 %p [95%] | 복승3 차이 %p [95%] | 복연3 차이 %p [95%] | 공동착순 NLL 차이 [95%] |',
        '|---|---:|---:|---:|---:|']
    for cand,ref in [('rank_only','state_gbm'),('no_rank','state_gbm'),('simple_rank','state_gbm'),
                     ('rank_only','strong89'),('no_rank','strong89'),('simple_rank','strong89'),
                     ('rank_only','simple_rank'),('rank_only','no_rank')]:
        m=r['comparisons'][f'{cand}_vs_{ref}']['all']['metrics']
        cells=[delta(m[k],100,3) for k in ['axis_top3','quinella_three','qpl_three']]+[delta(m['ordered_logloss'],digits=5)]
        differences.append('| '+LABELS[cand]+' / '+LABELS[ref]+' | '+' | '.join(cells)+' |')
    relative=['| 새 후보 | EL89 대비 | F103 대비 | 충분학습 EL89 대비 | 전체 상태29 대비 |',
        '|---|---:|---:|---:|---:|']
    for v in s.contracts():
        cells=[]
        for ref in ['additive89','full103','strong89','state_gbm']:
            m=r['comparisons'][f'{v}_vs_{ref}']['all']['metrics']['quinella_three'];lo,hi=m['relative_percent_ci95']
            cells.append(f"{m['relative_percent']:+.2f}% [{lo:+.2f}, {hi:+.2f}]")
        relative.append('| '+LABELS[v]+' | '+' | '.join(cells)+' |')
    calibration=['| 확률 정책 | 같은 세 사건 평균 Brier | 차이 [95%] | 공동착순 NLL | 차이 [95%] |',
        '|---|---:|---:|---:|---:|']
    for v in ['state_gbm','cal_candidate','cal_selected']:
        m=by[v]['means'];b=n='—'
        if v!='state_gbm':
            d=r['comparisons'][f'{v}_vs_state_gbm']['all']['metrics']
            b=delta(d['selected_mean_brier']);n=delta(d['ordered_logloss'])
        calibration.append(f"| {LABELS[v]} | {m['selected_mean_brier']:.6f} | {b} | {m['ordered_logloss']:.6f} | {n} |")
    calibration_details=['| 확률 정책 | 사건 | 평균 예측 | 실제 적중 | 고정10구간 ECE |',
        '|---|---|---:|---:|---:|']
    for v in ['state_gbm','cal_candidate','cal_selected']:
        for item in r['calibration_descriptive']:
            if item['variant']!=v:continue
            name={'axis':'축 Top3','qnl3':'복승3','qpl3':'복연3'}[item['target']]
            calibration_details.append(f"| {LABELS[v]} | {name} | {100*item['predicted_mean']:.3f}% | {100*item['observed_mean']:.3f}% | {100*item['fixed_ten_bin_ece']:.3f}%p |")
    pilots=['| 지역 | 평가연도 | 전년도 H2 평균 Brier 차이 | 전년도 H2 NLL 차이 | 보정 선택 |',
        '|---|---:|---:|---:|---|']
    for path in sorted((s.OUT/'calibrators').glob('*.json')):
        m=json.loads(path.read_text());venue={1:'서울',3:'부산'}[m['meet']]
        pilots.append(f"| {venue} | {m['evaluation_year']} | {m['prior_validation_mean_brier_difference']:+.7f} | {m['prior_validation_order_nll_difference']:+.7f} | {'적용' if m['selected_from_prior_year'] else '항등변환'} |")
    strata=['| 구간 | 모델 | 경주 | 축 | 복승3 | 복연3 |','|---|---|---:|---:|---:|---:|']
    frame=analysis.all_rows()
    for col in ['year','meet']:
        for value in sorted(frame[col].unique()):
            label=str(value) if col=='year' else {1:'서울',3:'부산'}[int(value)]
            for v in ['strong89','state_gbm','rank_only','no_rank','simple_rank']:
                g=frame[frame[col].eq(value)&frame.variant.eq(v)]
                strata.append(f"| {label} | {LABELS[v]} | {len(g):,} | {100*g.axis_top3.mean():.2f}% | {100*g.quinella_three.mean():.2f}% | {100*g.qpl_three.mean():.2f}% |")
    training=['| 모델 | 지역 | 평가연도 | 변수 수 | 선택 트리 수 | 집합 온도 | 순서 온도 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for path in sorted((s.OUT/'models').glob('*/metadata.json')):
        m=json.loads(path.read_text());venue={1:'서울',3:'부산'}[m['venue']]
        training.append(f"| {LABELS[m['variant']]} | {venue} | {m['evaluation_year']} | {len(m['features'])} | {m['trees']} | {m['temperature']:.4f} | {m['order_temperature']:.4f} |")
    note='순위 상태9는 단순 착순보다 복승3 +68경주였지만 전체 상태29 모델을 넘지 못했다. 추가 확률 보정도 채택하지 않았다.'
    body=f'''# 상태 입력 분해와 고정 추천의 공동확률 보정 결과

2026-10-22 · 연구58D · 서울·부산 · 구현·학습·개발 평가·검산 완료 · 운영 미반영.

**{note}** 이번 결과는 직전 연구에서 얻은 개선의 근거를 좁혔다. 추가 10% 적중 개선을 만든 실험은 아니다. 다음 연구의 기준은 기존 state_gbm(전체 상태29 + GBM)을 유지한다. 이전 state_joint 결과는 참조하며 새로 학습하지 않았다.

## 동일 경주·동일 추천 수의 결과

같은 4,799경주·50,754출전마(2024-01-05~2026-09-20)를 평가했다. 축1두, 복승/복연 각각1쌍·3쌍의 예산을 고정했다. 복승/복연3은 세 쌍 중 하나 이상 맞은 경주 비율이며 괄호는 적중 경주 수다. 아래 첫5행은 선행 연구의 확정 결과를 재사용하고 마지막3행만 이번에 학습했다. 수익률은 측정하지 않았다.

{chr(10).join(table)}

{chr(10).join(differences)}

차이의 구간은 같은 경주끼리 짝지어 날짜 406개를 단위로 재표집한 bootstrap 2,000회·시드20261024의 95% 구간이다. 적중은 높을수록, NLL/Brier는 낮을수록 좋다. 지표별 구간이며 다중비교 보정은 하지 않았다. 같은 말의 서로 다른 날짜 사이 잔여 상관까지 완전히 처리한 구간은 아니다. 모든 지표·연도·지역별 비교는 [결과 JSON](outputs/results.json)에 있다.

## 이번에 더 분명해진 점

**상대를 반영하는 순위 상태 묶음의 실용적인 근거가 강해졌다.** 순위 상태9만 추가한 모델은 단순 착순9보다 복승3 +68경주(+1.417%p, 95% +0.517~+2.314%p), 축 +81경주, 복연3 +76경주였다. 공동착순 NLL도 5.955005에서 5.912707로 낮아졌다. 두 후보 모두 같은 원천 이력·T−2 cutoff·변수 수·학습 절차를 사용했다. 따라서 단순 과거 착순 요약만으로 같은 성과를 낼 수 있다는 가설은 이 개발 자료에서 지지되지 않았다.

다만 순위 상태9에는 상대의 능력, 거리 반응, 시간 갱신, 불확실성, 편성 내 위치가 묶여 있다. 이번 비교만으로 어느 하나의 독립적인 인과 효과를 입증하지 않는다. 과거 능력을 정확하게 관측한 것도 아니며 근사 필터가 추정한 상태다.

**이득의 대부분은 서울에서 관측됐다.** 단순 착순 대비 복승3 순증68경주 중 서울65·부산3이었다. 서울 차이는 +2.290%p(95% +1.132~+3.450%p), 부산은 +0.153%p(−1.212~+1.547%p)다. 부산에서도 같은 효과가 확실하다고 일반화하지 않는다. 연도별 순증은 2024년28·2025년15·2026년25이며, 연도 각각에서 모두 구간이 0을 넘은 것은 아니다. 사후 지역 선별 모델은 만들지 않았다.

**전체29를9로 줄일 근거는 아직 충분하지 않다.** 순위 상태9는 충분학습 EL89보다 복승3 +92경주였고, 전체29의 같은 기준 이득은 +98경주였다. 그러나 전체29 대비 축−21·복승3−6·복연3−14이며 NLL은 +0.006799(95% +0.001805~+0.012014) 악화했다. 복승3 차이 구간이 0을 포함한다는 이유만으로 동등하거나 손실 없이 단순화했다고 결론내리지 않는다. 별도 동등성/비열등성 한계도 사전에 정하지 않았다.

순위 상태를 뺀 나머지20도 충분학습 EL89보다 복승3 +52경주(+1.084%p, 양의 구간)였다. 따라서 순위 상태만 유효하고 다른 상태는 무가치하다는 해석도 틀리다. 다만 전체29에서 순위9를 빼면 복승3 −46경주(−0.959%p, 95% −1.817~−0.105%p)로 감소했다. 입력 묶음끼리 정보와 상호작용이 겹치므로 개선량을 더하거나 특정 변수의 기여율로 환산하지 않는다.

## 상대 10% 목표 판정

아래는 주지표 복승3의 상대변화와 95% 구간이다. %p 차이와 구분한다.

{chr(10).join(relative)}

새 후보 중 어떤 것도 직전 전체 상태29 모델을 넘거나 복승3의 상대10% 목표를 달성하지 못했다. 가장 좋은 새 후보 순위 상태9는 EL89 대비 +7.92%, 충분학습 EL89 대비 +6.54%, 직전 상태29 대비 −0.40%였다. 이전 공동착순 신경망의 복승3 EL89 대비 +9.86% 결과도 그대로이며 이번에 추가로 높아진 것이 아니다.

다른 지표·분모도 숨기지 않는다. 순위 상태9의 복승1은 F103 대비 +10.25%(595→656경주, 95% +2.99~+17.70%)라는 점추정이 나온다. 그러나 EL89 대비 +5.98%, 직전 상태29 대비 −0.61%(660→656)다. 이 한 항목을 골라 이번 후속 연구가 최소10% 개선에 성공했다고 판정할 수 없다. 모든 비교의 분모·구간은 결과 JSON에 보존했다.

## 확률 보정은 채택하지 않는다

이 실험에서는 state_gbm의 축과 복승/복연 세 쌍을 고정했다. 축Top3·복승3·복연3 세 사건의 진위 조합8개를 한 공동착순 분포 안에서 보정했다. 여섯 계수의 지수 가중 q′∝q·exp(β·φ)를 사용하며 중복 착순을 금지하고 모든 주변확률을 같은 분포에서 합산한다. 보정 후 추천 순위를 다시 정하는 정책은 시험하지 않았다. 따라서 아래 결과는 같은 사건을 대상으로 확률 숫자만 비교한 것이며, 모든 적중 수와 추천 수는 정확히 같다.

{chr(10).join(calibration)}

전년도 검증으로 선택한 정책의 평균 Brier는 0.217279→0.217370, 차이 +0.000091(95% −0.000171~+0.000349)로 개선이 확인되지 않았다. NLL도 5.905907→5.906776으로 약간 높아졌다. 항상 보정하는 원형도 평균 Brier·NLL 점추정이 나빠졌다. 오차 구간은 0을 포함하므로 유의한 악화라고 단정하지 않지만, 사전 채택 조건도 통과하지 못했다.

{chr(10).join(calibration_details)}

고정10구간 ECE와 전체 평균 확률은 일부 좋아졌다. 예를 들어 선택정책 복승3 ECE는 1.825→1.626%p, 축 ECE는 0.794→0.506%p다. 하지만 ECE는 구간에 민감하며 이번 평균 Brier·NLL의 개선 근거를 대신하지 못한다. 전체 평균을 맞춘 것만으로 개별 경주의 확률이 더 유용해졌다고 결론내리지 않는다. 서로 다른 추천을 하는 ablation 모델의 선택사건 Brier를 이 고정추천 보정 비교와 같은 의미로 비교하지 않는다.

보정 적용 여부는 평가 전년도 상반기 적합·하반기 검증으로 선택했다. 이 사전시험의 기반 온도도 상반기로만 맞췄다. 그 뒤 전년도 전체로 최종 보정계수를 재적합하고 다음 연도를 평가했다. 즉, 두 반기의 역할이 사전시험에서는 분리되지만 최종 재적합 모형은 사전시험 모형과 같지 않다. 전년도에서 통과한 선택이 다음 기간의 개선을 보장하지 않는다는 결과다.

{chr(10).join(pilots)}

6개 분할 중 서울·부산의 2026평가용 두 분할만 선택됐다. 2024·2025는 항등변환이었다. 최종 평가에서 2026의 평균 Brier 차이는 +0.000339(95% −0.000636~+0.001319)였다. 실패한 분할이나 항상 적용한 원형도 모두 보고하며 재튜닝하지 않았다.

## 입력 분해·학습 방법

- 순위 상태9: 기존 EL89 89변수 + 상대 순위 능력/불확실성, 거리 반응/불확실성, 현재거리 능력/불확실성, 이력수, 현재거리 능력의 편성 차이·순위 = 98변수.
- 순위 외 상태20: 기존89 + 기록 수준/추세·초반/종반 상태·불완주 위험·지원량/휴양·편성 상대 상태 = 109변수. 구간 상태에도 상대정보가 있으므로 모든 상대정보를 제거한 모델은 아니다.
- 단순 착순9: 기존89 + 정상완주 상대 중 이긴 비율의 직전·최근3/5평균·최근5표준편차·전체평균·전체유효수·최근5유효수·전체평균의 편성 차이/순위 = 98변수. 동착 상대는0.5, 비완주/실격은 결측으로 두며 최근3/5 출전 슬롯은 유지했다. 상대의 신원이나 추정 능력은 사용하지 않았다.

입력의 정확한 이름은 [계약](outputs/feature_contract.json), 단순 착순178,497행의 시점 검사는 [특징 감사](outputs/feature_audit.json)에 있다. 기존 전체 특징/동적 상태/모델/원천DB는 복제하지 않고 경로·해시로 참조했다.

서울·부산 × 2024/2025/2026 총6분할. 초기학습2017..Y−3, 조기중단Y−2, 재학습2017..Y−2, 확률 온도보정Y−1, 평가Y다. 과거 상태 warmup은2010년부터다. 전체 경주 단위 분할, 58C와 같은 LightGBM 설정·시드20261004·상한800·조기중단25를 사용했다. 최종18모델·초기+재학습36회, 보정은1계열·6계수·사전시험+최종재적합 총12회였다. 추가 시드나 평가 후 파라미터 탐색은 하지 않았다.

{chr(10).join(training)}

후보 유지 조건은 직전 state_gbm 대비 복승3 차이95%하한>0, 축/복연3 하한>−1%p, NLL 악화 없음이다. 세 후보 모두 통과하지 못했다. 보정 채택 조건은 고정 세 사건 평균 Brier 차이95%상한<0 및 NLL 차이<=0이며 역시 실패했다. 기술통계상 좋은 일부 지표로 이 기준을 바꾸지 않았다.

## 연도·지역별 적중

{chr(10).join(strata)}

## 새 기간의 원천은 있으나 미래 검증은 아직 아니다

기준 DB의 확정 경주는 서울2026-09-20·부산2026-09-18까지다. 별도의 로컬 staged DB에서 이후 서울52경주567행(10-03~11), 부산27경주289행(10-02~16), 합계79경주856행을 확인했다. 대응 출전표는 모두10-17 한국시간에 수집되어 해당 경주 이후 자료였다. 이79경주의 후보용 완전한118변수 입력을 재구축하거나 예측 성능을 계산하지 않았다. 원천이 없다는 뜻도, 경기 전 입력을 확보했다는 뜻도 아니다. [날짜·수집시각·조회·해시 감사](outputs/later_period_readiness.json).

다음 실전 검증에는 동일 특징계약의 재현, cutoff 이전 최신 이력 연결, 경기 전 명단·부담중량의 공시시각 증거, 결과가 나오기 전 모델/입력/예측 해시 봉인이 필요하다. 나중에79경주를 재구축하더라도 사후 역사평가와 진짜 경기 전 검증을 구별해야 한다. 이번에는 원천 수집·DB 갱신·운영 예측 게시·예약을 하지 않았다.

## 재현 검증과 한계

- 합성 자료의 미래변조 불변성, 실제 cutoff, 비완주 결측, 순열/항등변환, 전체착순 열거 대8패턴 확률, 보정 gradient를 검사했다. gradient 최대오차1.07e−10, 전체분포/패턴 차이6.11e−16. [학습 전 검증](outputs/preflight.json).
- 최종18모델을 저장 파일에서 재로드하여 보정/평가점수 {verification['model_replayed_rows']:,}행을 재현했고 차이0이었다. 각 분할 처음·마지막 경주의 보정 주변확률 {verification['calibrator_replayed_runner_rows']:,}행도 차이0이었다.
- 새 추천 티켓 {verification['tickets_independently_scored']:,}장을 정답에서 별도 재채점했다. 전체 주변확률 {verification['runner_probabilities_checked']:,}행의 합·단조성, 중복 없는 세 쌍, 두 보정정책의 원래 축/티켓/적중 수 완전 동일성을 확인했다.
- 평가 출전마120행의 과거 착순을 원관측에서 수작업 수식으로 다시 집계해 최대오차9.86e−16이었다. 모든 단순 착순 source_date<=T−2를 검사했다.
- 동결 입력49개, 새 모델파일, 원천DB 두 개와 운영레지스트리의 해시를 검사했다. [검증 원문](outputs/verification.json). 학습 전 보정 온도의 시간분리를 강화한 변경은 [변경기록](outputs/protocol_amendments.json)에 남겼다. 이후 학습/평가 코드는 바꾸지 않았고 검산·문서 코드는 별도 추가했다. 외부 독립 리뷰어가 수행한 검증은 아니다.

2024~2026은 반복 사용한 역사적 개발 자료다. 새 기간의 독립 시험으로 해석할 수 없으며 후기 fold에는 앞선 연도가 과거 학습/보정으로 들어간다. 과거 상태는 해당 경주의T−2까지 순차 갱신했다. 현재 부담중량과 확정명단의 당시 공시시각 문제도 남아 있다. 주로빠르기, 현재 경주의 실제 구간/착순/배당을 입력으로 추가하지 않았다. 신마·불완주를 사후 제외하지 않았다. 좋은 개발 결과가 미래10% 향상을 보장하지 않는다.

## 후속 판단과 산출물

전체 상태29 + GBM을 다음 연구 기준으로 유지한다. 순위 상태9는 의미 있는 간소화 비교 후보로 남기되 동등성을 주장하거나 교체하지 않는다. 추가 공동확률 보정은 보류한다. 다음에 우선 확인할 것은 이 순위 상태 이득이 경기 전 입력을 봉인한 새 기간에서도 재현되는지이며, 서울에서 확인된 차이를 부산에도 적용할 수 있다고 가정하지 않는다.

운영 모델 `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`는 그대로다. 연구용 기준 선정과 운영 승격은 구별한다. 연구 보고서·중앙결론58D·미게시 요약·5개 중앙문서 및 자기포함 [파일별 용량 명세](outputs/artifact_inventory.json)를 완성했다. 신규/수정 파일의 비용은 별도로 기록하며 앞선4연구와 합쳐300,000,000bytes 미만을 검사한다.

[계획](PLAN.md) · [결과](outputs/results.json) · [미게시 요약](PUBLICATION.md) · [선행 연구58C](../20261022_dynamic_race_model_v1/README.md).

확률 정확도와 보정을 구분하는 일반 배경으로 [Guo 등, On Calibration of Modern Neural Networks, 2017](https://proceedings.mlr.press/v70/guo17a.html)을 참고했다. 이 논문은 이번 경마 모델이나 지수 가중 보정법의 개선을 증명하는 자료가 아니다.
'''
    (s.HERE/'README.md').write_text(body)
    short=f'''# 상대를 고려한 순위 상태는 유효했지만 추가 개선은 확인하지 못했다

2026-10-22 · 연구58D · 웹사이트 미게시 · 운영 미반영.

{note}

서울·부산 같은4,799경주에서 세 새 모델을 비교했다. 복승3 적중률은 기존 전체 상태29가31.36%(1,505경주), 순위 상태9가31.24%(1,499), 나머지 상태20이30.40%(1,459), 단순 과거 착순9가29.82%(1,431)였다. 추천 수는 모두 같다.

순위 상태9는 단순 착순 대비68경주 더 맞혔고 차이의95%구간은 +0.52~+2.31%p다. 이득68경주 중 서울65·부산3이므로 지역 전체에 같은 효과를 확정하지 않는다. 전체29에서 변수20개를 덜어도 손실이 없다는 동등성은 입증하지 못했다.

원래 추천을 고정한 추가 확률 보정은 평균 Brier와 공동착순 NLL을 개선하지 못해 채택하지 않았다. 직전 기준보다 적중10%를 추가로 높이지도 못했다. 따라서 전체 상태29 + GBM을 다음 연구 기준으로 유지한다.

이 결과는 반복 사용한2024~2026 개발 자료다. 이후79경주의 원천도 발견했으나 당시 입력이 봉인되지 않았으며 이번 평가에 넣지 않았다. 미래 성능이나 수익률을 보증하는 결과가 아니다. [전체 방법·결과·검증](README.md).
'''
    (s.HERE/'PUBLICATION.md').write_text(short)
    docs.CONCLUSION.write_text(f'''# 상태 입력 분해와 고정 추천 공동확률 보정

2026-10-22 · 연구58D · 구현·학습·검산 완료 · 운영 미반영.

**{note}** 전체 상태29 + GBM을 다음 연구 기준으로 유지한다. 새18모델·초기+재학습36회·보정12회, 동일4,799경주를 평가했다.

{chr(10).join(table)}

순위 상태9 대 단순 착순9의 복승3 차이+1.417%p(95% +0.517~+2.314), +68경주다. 이득은 서울+65·부산+3으로 지역 일반화 근거는 다르다. 전체29 대비 순위9는 복승3−6경주이고 NLL은악화해 동등한 대체재로 판정하지 않는다. 세 새 후보 모두 사전 후보 유지 조건에 실패했다.

고정추천 보정 선택정책의 평균 Brier는0.217279→0.217370, NLL은5.905907→5.906776이다. 일부 ECE는 낮아졌지만 사전 확률개선 조건은 통과하지 못했다. 추천·적중 수는 완전히 같다.

복승3에서 새후보의 상대10% 개선은 없었다. 순위9의 복승1 F103대비+10.25% 점추정은 있으나 직전상태29 대비−0.61%이며 최소10% 개선 증명이 아니다. 자료는 반복 사용한2024~2026 개발기간이다. 후속 원천79경주는 입력 봉인/재구축/평가를 완료하지 않았으며 미래검증으로 주장하지 않는다.

모델점수319,866행 재현차이0, 티켓143,970장 직접채점, 주변확률253,770행, 실제과거120행 검산을 통과했다. 원천DB와 운영레지스트리 해시 동일. DB 쓰기·운영승격·게시·배포 없음.

[전체 보고서](../{s.HERE.name}/README.md) · [사전계획](../{s.HERE.name}/PLAN.md) · [결과](../{s.HERE.name}/outputs/results.json) · [검증](../{s.HERE.name}/outputs/verification.json) · [용량](../{s.HERE.name}/outputs/artifact_inventory.json).
''')
    docs.finish(note)

if __name__=='__main__':main()
