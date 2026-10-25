"""Write the completed research report; preserve frozen modeling decisions."""
import json,importlib.util
import risk_common as c
import pandas as pd

spec=importlib.util.spec_from_file_location('bottom_archive',c.HERE/'archive.py')
arc=importlib.util.module_from_spec(spec);spec.loader.exec_module(arc)

def pct(x):return f'{100*x:.2f}%'
def ci(x):return f'{100*x[0]:+.2f}~{100*x[1]:+.2f}%p'

def main():
    c.check()
    r=json.loads((c.OUT/'results.json').read_text())
    d=json.loads((c.OUT/'diagnostics.json').read_text())
    v=json.loads((c.OUT/'verification.json').read_text())
    assert v['status']=='passed'
    allr=r['all'];b=allr['baseline'];n=allr['model'];comp=allr['bottom_comparison'];axis=allr['selected_axis_comparison']
    m=pd.read_parquet(c.OUT/'race_metrics.parquet')
    ax=pd.read_parquet(c.OUT/'axis_details.parquet')
    assert int(m.base_axis_hit.sum())==3051 and int(m.selected_axis_hit.sum())==3049
    note='하위 3두 지목 적중은 47.38→49.45%로 개선됐지만 입상마 오제외가 늘었고, 축 보조 정책은 3,051→3,049적중으로 개선되지 않았다.'

    quality=['| 지표 | 기존 입상확률 하위 3두 | 새 하위 3두 모델 |','|---|---:|---:|']
    quality += [f'| 지목한 말 중 실제 하위 3두 | {pct(b["precision"])} | {pct(n["precision"])} |',
        f'| 경주당 평균 맞힌 수 | {3*b["precision"]:.3f}/3두 | {3*n["precision"]:.3f}/3두 |',
        f'| 2두 이상 맞힌 경주 | {b["atleast2_races"]:,}/4,799 | {n["atleast2_races"]:,}/4,799 |',
        f'| 3두 모두 맞힌 경주 | {b["exact3_races"]:,}/4,798 ({pct(b["exact3_races"]/4798)}) | {n["exact3_races"]:,}/4,798 ({pct(n["exact3_races"]/4798)}) |',
        f'| 지목한 말 중 실제 입상마 | {pct(b["podium_horses_excluded"]/14397)} | {pct(n["podium_horses_excluded"]/14397)} |',
        f'| 입상마를 1두 이상 지목한 경주 | {b["races_any_podium_excluded"]:,}/4,799 ({pct(b["races_any_podium_excluded"]/4799)}) | {n["races_any_podium_excluded"]:,}/4,799 ({pct(n["races_any_podium_excluded"]/4799)}) |',
        f'| 실제 우승마를 지목한 경주 | {b["winner_excluded_races"]:,}/4,799 ({pct(b["winner_excluded_races"]/4799)}) | {n["winner_excluded_races"]:,}/4,799 ({pct(n["winner_excluded_races"]/4799)}) |',
        f'| 경주 균등 Brier (낮을수록 좋음) | {b["race_mean_brier"]:.6f} | {n["race_mean_brier"]:.6f} |',
        f'| 하위 3두 집합 NLL (낮을수록 좋음) | {b["mean_set_nll"]:.6f} | {n["mean_set_nll"]:.6f} |']
    venues=['| 범위 | 경주 | 기존 하위 지목 적중률 | 새 모델 | 기존 축 → 보조 축 적중 |',
        '|---|---:|---:|---:|---:|']
    for key,label in [('all','전체'),('seoul','서울'),('busan','부산'),('2024','2024년'),('2025','2025년'),
        ('2026','2026년(~9/20)'),('busan_grade5_1300_1600','부산 국5 1300·1600m'),
        ('busan_grade5_1300_1600_2026','위 대상의 2026년')]:
        z=r[key];q=z['selected_axis_comparison']
        venues.append(f'| {label} | {z["races"]:,} | {pct(z["baseline"]["precision"])} | {pct(z["model"]["precision"])} | {q["baseline_total"]:.0f} → {q["candidate_total"]:.0f} |')
    policies=['| 축 1두 선택법 | 적중 / 4,799 | 적중률 | 바꾼 경주 | 새 적중 / 기존 적중 상실 |',
        '|---|---:|---:|---:|---:|',f'| 기존 축 | 3,051 | {pct(axis["baseline_rate"])} | 0 | — |']
    for key,label in [('exclude','하위 3두 제외'),('selected','전년도 선택 위험 감점')]:
        z=allr[key+'_axis_comparison']
        policies.append(f'| {label} | {z["candidate_total"]:.0f} | {pct(z["candidate_rate"])} | {allr[key+"_switches"]} | {z["gained_races"]} / {z["lost_races"]} |')
    folds=['| 장소·평가연도 | 트리 수 | 전년도 선택 λ | 전년도 축 적중 (λ=0/.25/.5/1) |',
        '|---|---:|---:|---|']
    for path in sorted((c.OUT/'models').glob('*/metadata.json')):
        z=json.loads(path.read_text());name={1:'서울',3:'부산'}[z['meet']]
        folds.append(f'| {name} {z["evaluation_year"]} | {z["trees"]} | {z["policy_lambda"]} | '+ ' / '.join(map(str,z['calibration_policy_hits'].values()))+' |')
    failure=d['axis_failure_composition'][0]
    assert sum(failure[k] for k in ['miss_actual_bottom_any_credit','miss_normal_nonbottom_fourth_fifth',
        'miss_normal_nonbottom_sixth_or_lower','miss_nonfinishers'])==failure['axis_misses']

    report=f'''# 하위 3두 독립 모델: 예측은 개선, 축 보조는 미개선

2026-10-23 · 연구58F · 서울·부산 · 역사적 개발 평가 · 운영 미반영.

**{note}** 하위권을 따로 학습할 가치는 확인했지만, 이 모델의 세 말을 자동으로 제외하는 정책은 채택하지 않는다. 모델 6개와 재현 가능한 코드를 진단 후보로 보관하고 기존 연구 기준 state_gbm을 유지한다. 상대 10% 축 적중 개선은 달성하지 못했다.

## 무엇을 만들었는가

입상 여부를 뒤집어 사용하는 것에 그치지 않고, **정상 완주마 중 마지막 3두**를 정답으로 새 LightGBM을 학습했다. 4위 이하 전체가 정답은 아니다. 서울·부산을 별도로 학습했고, 기존 118개 입력(능력·기록·과거 구간/전개89 + 동적 상태29)을 동일하게 사용했다. 장소별 2024·2025·2026 평가용 최종 6개 모델, 트리 수 선택용 초기 6회 적합이다.

불완주·실격·특수결과에는 임의의 꼴찌 순위를 주지 않았다. 이들은 학습 손실에서만 제외하고 실제 예측 명단에는 남겼다. 평가에서 이들을 지목해도 정상 하위 3두 적중으로 세지 않는다. 평가 50,754두 중 정상 완주 50,608두, 불완주 140두·실격 3두·특수결과 3두다. 새 모델은 이런 146두 중 53두를 하위권으로 지목했고 기준은 48두였다. 별도 불완주 위험 모델을 학습했다는 뜻은 아니다.

하위권 경계에 동착이 있는 경우 남은 세 자리의 지분을 동착마에게 나눴다. 전체 학습/평가 16,435경주 중 14경주, 이번 평가에서는 1경주가 해당한다. 해당 경주는 학습·조기중단·온도 보정에서 제외하고 평가의 말별 적중에는 분수 점수를 줬다. 3두 모두 적중의 분모만 4,798이며 축 성적은 모두 4,799경주다. 정상 완주 최소 두수는 6이었다.

## 하위 3두는 더 잘 찾았는가

비교 기준은 기존 state_gbm이 부여한 입상확률이 가장 낮은 3두다. 새 모델도 매 경주 정확히 3두를 지목했다. 표의 '지목 적중률'은 총 14,397두 지목 중 실제 정상 하위 3두에 해당하는 비율이며, 세 말을 한꺼번에 맞힌 경주 비율과 다르다. 무작위로 세 말을 고를 때 경주별 기대 비율은 평균 **{pct(allr['random_precision'])}**다.

{chr(10).join(quality)}

말별 하위 지목 적중은 **+{100*comp['difference']:.2f}%p**, 상대 **+{comp['relative_percent']:.2f}%**, 날짜 단위 paired bootstrap 95% 구간 **{ci(comp['difference_ci95'])}**였다. 정상 하위권을 맞힌 수는 동착 지분 포함 6,821.5→7,120두다. 하위 집합 확률의 Brier와 NLL도 좋아졌다.

그러나 실제 입상마를 잘못 지목한 수는 **1,561→1,643두**, 82두 증가했다. 지목 중 오제외 비율 변화의 95% 구간은 {ci(allr['false_podium_comparison']['difference_ci95'])}였다. 새 모델의 세 말을 전부 제외하면 **1,520/4,799경주({pct(1520/4799)})에서 실제 입상마를 최소 1두 제외**한다. 우승마도 376경주에서 제외한다. 따라서 하위권 적중 향상을 '안전하게 버릴 말 3두를 확보했다'고 해석할 수 없다. 사전 조건 중 오제외 증가 없음은 통과하지 못했다.

## 부산 기준 결과도 따로 보았다

{chr(10).join(venues)}

부산 하위 지목 적중은 **45.45→48.84%, +3.38%p**(95% {ci(r['busan']['bottom_comparison']['difference_ci95'])}), 상대 +7.44%였다. 서울은 +1.17%p다. 다만 부산에서 입상마 오제외는 615→681두로 늘었다.

앞서 약했던 부산 국5등급 1,300m·1,600m에서는 하위 지목 적중이 43.65→49.21%, 상대 +12.73%였다. **이 10% 이상 수치는 하위 지목이라는 다른 지표이고 축 적중 향상이 아니다.** 그 집단의 축은 120→119, 2026년만은 36→36이었다. 해당 집단은 이전 결과에서 선정한 탐색 집단이므로 독립적인 확인 결과로 보지 않는다.

## 축 선택에 도움이 되었는가

하위 3두를 제외한 뒤 기존 점수 최상위를 고르는 고정 정책과, 기존 원점수에서 λ×하위 원점수를 뺀 효용점수로 축을 고르는 정책을 시험했다. 모든 경주에서 축 1두를 유지했다. 효용점수는 새 입상확률이 아니며 기존 공동착순 분포와 복승·복연 1/3쌍 추천은 그대로다. 선택된 축의 표시 확률은 기존 분포의 주변확률을 참조한다.

{chr(10).join(policies)}

자동 제외 정책은 기존 축이 하위 3두로 지목된 단 2경주만 바꿨다. 두 원래 축 모두 실패했고 그중 1경주만 대체 축이 입상했다. +1경주·+0.02%p, 95% 구간 {ci(allr['exclude_axis_comparison']['difference_ci95'])}로 일반적인 개선 근거가 없다.

전년도 선택 감점 정책은 364경주를 바꿨고 새 적중 102·기존 적중 상실 104·동일 158이었다. 전체 축은 **63.58→63.53%, −2경주**, 차이 95% 구간 **{ci(axis['difference_ci95'])}**다. 2026년도 834→833이었다. 사전 축 개선 조건을 통과하지 못했다.

부산 전체의 축은 1,210→1,222, **61.70→62.32%**로 12경주 늘었지만 차이 95% 구간은 **{ci(r['busan']['selected_axis_comparison']['difference_ci95'])}**로 0을 포함한다. 2024 +6·2025 +7·2026 −1경주이며, 전체 연구가 서울의 손실을 상쇄하지 못했다. 부산만 사후 골라 성공으로 선언하거나 평가 결과를 보고 λ를 다시 고르지 않았다.

왜 하위권 개선이 축 개선으로 이어지지 않는지도 구분할 필요가 있다. 기존 축 실패 1,748경주 중 정상 하위 3두로 끝난 것은 **392경주({pct(392/1748)})**였다. 정상 완주이면서 하위 3두 밖의 4~5위가 773경주, 6위 이하가 571경주, 비완주 등이 12경주였다. 축은 3착 밖이면 실패하므로 중위권 결과도 모두 손실이다. 또한 실제로 크게 무너진 유력마와 원래부터 약해 보이는 말을 구별해야 한다. 이번 모델이 축을 하위 3두로 분류한 것은 2경주뿐이었다. 두 하위 명단의 평균 겹침은 {d['mean_bottom_selection_overlap']:.3f}/3두다. 이는 사후 설명이며 새로운 실패 예측 규칙을 검증한 결과는 아니다.

## 시간 분할과 재현

평가연도 Y마다 2017~Y−3 초기 학습, Y−2 조기중단, 2017~Y−2 최종 재학습, Y−1 보정·정책 선택, Y 평가를 적용했다. 경주 전체가 같은 연도에 묶인다. 2010년 이후 전적은 기존 상태 계산의 워밍업에 사용됐다. 학습률 .04, 잎 15, 최소 잎 자료 150, L2=5, 최대 800회, 조기중단 25회, seed20261004, CPU 4threads, 행 가중치 1/출전두수다. 범주 사전은 초기 학습 구간에서만 정했다.

하위 세 말의 부분집합마다 exp(원점수 합/온도)를 계산해 정규화했다. 온도는 전년도에서 .35~4 범위로 한 번 정했다. 기준도 기존 점수를 음수로 바꾼 뒤 같은 절차로 보정했다. 하위 주변확률의 합은 3이다. 상위 분포와 하위 분포는 별도 모델이며 둘을 합친 일관된 전체 착순 분포로 주장하지 않는다.

λ는 사전에 고정한 0/.25/.5/1 중 전년도 축 적중 수가 가장 큰 값, 동률이면 작은 값을 선택했다. 당해 연도 정답을 채점하기 전에 선택 파일을 저장했다. 선택 연도의 최대치를 고른 만큼 전년도 성적 자체는 검증 성적이 아니며 다음 연도를 평가했다.

{chr(10).join(folds)}

공식 DB의 정답 178,497행을 독립적인 순위군 할당으로 다시 계산했고 오차 0이었다. 새 모델과 기존 모델 각각 저장 점수 106,622행을 다시 예측해 최대 차이 0을 확인했다. 세 축 정책 총 14,397건을 공식 착순으로 직접 채점했고, 기준 하위 명단이 기존 입상확률 하위 3두와 전 경주 일치했다. 전년도 λ·온도 선택을 재현하고 현재 착순·결과 상태를 변조해도 입력과 예측이 바뀌지 않음을 검사했다. 과거 자료 출처≤T−2, 상태 출처 감사의 해시, 원천·운영 등록부 불변, 모든 하위 주변확률 합3을 확인했다. 외부 독립 리뷰어의 검증은 아니다. [검증 기록](outputs/verification.json).

## 판단과 한계

하위권 전용 정답은 입상 모델을 거꾸로 읽는 것보다 하위권 자체를 잘 설명했다. 그렇지만 안전한 제외 모델이나 축 대체 모델로 채택할 수준은 아니다. 이번 버전은 **진단용 후보로 보관하고 자동 제외·축 감점은 적용하지 않는다.** 다음 연구가 필요하다면 전체 말 중 약한 3두보다 기존 유력 후보가 예상보다 크게 무너지는 위험을 별도로 검증하는 쪽이 이번 실패와 더 직접적으로 연결된다. 이번 실험은 그 후속 방식의 성공을 입증하지 않았다.

대상은 2024-01-05~2026-09-20의 반복 사용한 개발 자료다(부산 마지막 경주 9/18). 경주 단위 시간 분할을 지켰어도 연구자가 이미 본 기간이라는 선택 편향이 남는다. 날짜 bootstrap 2,000회·seed20261026은 동일 말의 날짜 간 상관이나 다중비교를 완전히 처리하지 않는다. 거리·등급 분해는 설명용이며 새 규칙을 고르는 데 쓰지 않았다. 2026년은 부분연도이고 정상 하위 3두 정답은 불완주 위험 전체를 나타내지 않는다. 현재 부담중량과 확정 명단의 당시 공시시각 한계도 유지한다. 10월의 후기 원자료는 일부 있으나 완전한 118개 특징과 사전 시점 재현이 없어 새 독립 평가를 수행하지 않았다. 배당·수익률 개선은 측정하지 않았다.

운영 `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`는 유지한다. DB 쓰기·새 수집·예측 게시·배포·예약은 없다. 기존 DB·특징·상태·기본모델은 참조했고, 신규 보관량은 앞선 여섯 연구 140,831,211 bytes와 합쳐 300,000,000 bytes 미만이다.

[사전계획](PLAN.md) · [전체 결과](outputs/results.json) · [사례](CASES.md) · [등급·거리별 설명](outputs/diagnostics.json) · [모델](outputs/models) · [미게시 요약](PUBLICATION.md) · [자기포함 용량 명세](outputs/artifact_inventory.json) · [선행 연구58E](../20261022_busan_grade5_axis_v1/README.md).
'''
    (c.HERE/'README.md').write_text(report)
    short=f'''# 하위 3두 모델을 따로 만들어 본 결과

2026-10-23 · 연구58F · 웹사이트 미게시 · 운영 미반영.

{note}

정상 완주마 중 마지막 3두를 맞히도록 서울·부산 6개 모델을 학습했다. 2024~2026년 4,799경주에서 매번 3두씩 지목했다. 무작위 지목의 기대 적중률은 28.79%, 기존 입상 모델의 하위 3두는 47.38%, 새 모델은 49.45%였다. 세 말을 모두 맞힌 경주는 323/4,798(6.73%)이었다.

그러나 실제 입상마를 하위권으로 잘못 지목한 비율은 10.84→11.41%로 늘었다. 세 말을 모두 제외하면 31.67%의 경주에서 실제 입상마를 최소 1두 버린다. 하위권을 더 잘 맞힌다는 사실과 안전하게 제외할 수 있다는 주장은 다르다.

부산만 보면 하위 지목 적중은 45.45→48.84%, 축 보조는 1,210→1,222적중이었다. 축 차이의 95% 구간이 0을 포함하고 2026년은 1경주 줄어 확정 개선으로 보지 않는다. 앞서 약했던 부산 국5 1300·1600m 축은 전체 120→119, 2026년 36→36이었다.

하위 3두 진단 후보로 보관하되 자동 제외와 축 감점은 채택하지 않는다. 상대 10% 축 개선은 미달성이다. 과거 개발 자료를 반복 사용한 실험이며 새 미래 검증·수익률 검증 결과는 아니다.

[전체 방법·결과·검증](README.md) · [선택이 바뀐 사례](CASES.md).
'''
    (c.HERE/'PUBLICATION.md').write_text(short)
    details=ax.set_index(['race_key','policy'])
    case_lines=['| 경주 | 기존 축·실제 | 새 축·실제 | 기존 축 하위확률 | 새 축 하위확률 | 적중 변화 |',
        '|---|---|---|---:|---:|---:|']
    def case(row,policy):
        a=details.loc[(row.race_key,'base')];b=details.loc[(row.race_key,policy)]
        def label(q):return f'{int(q.program_no)}번·{int(q.finish_order)}위' if q.result_status=='finished' else f'{int(q.program_no)}번·{q.result_status}'
        return f'| {row.race_key} | {label(a)} | {label(b)} | {pct(a.model_bottom_probability)} | {pct(b.model_bottom_probability)} | {getattr(row,policy+"_axis_hit")-row.base_axis_hit:+d} |'
    hard=[*case_lines]+[case(row,'exclude') for row in m[m.exclude_axis.ne(m.base_axis)].sort_values('race_key').itertuples()]
    target=m.meet.eq(3)&m.grade.eq('국5등급')&m.distance_m.isin([1300,1600])&m.year.eq(2026)&m.selected_axis.ne(m.base_axis)
    recent=[*case_lines]+[case(row,'selected') for row in m[target].sort_values('race_key').itertuples()]
    (c.HERE/'CASES.md').write_text(f'''# 하위 위험 모델이 축 선택을 바꾼 사례

2026-10-23 · 연구58F. 당시 운영 추천이 아니라 역사적 개발 평가의 후보 정책이다. 아래 하위확률은 정상 마지막 3두 분포의 주변확률이며 4위 이하 전체의 확률이 아니다.

## 하위 3두 자동 제외로 바뀐 전체 2경주

{chr(10).join(hard)}

두 기존 축 모두 실패했지만 대체 축이 입상한 것은 한 경주다. 4,799경주에서 단 두 번 바뀌었으므로 폭넓은 축 개선 근거로 삼지 않는다.

## 2026년 부산 국5 1300·1600m 위험 감점으로 바뀐 전체 3경주

{chr(10).join(recent)}

새 적중 1·기존 적중 상실 1로 이 집단의 2026년 축은 36/72 그대로다. [모든 경주별 결과](outputs/race_metrics.parquet) · [축과 확률 상세](outputs/axis_details.parquet) · [전체 보고서](README.md).
''')
    arc.CONCLUSION.write_text(f'''# 하위 3두 모델: 하위 예측 개선과 축 개선의 차이

2026-10-23 · 연구58F · 서울·부산 4,799경주 · 운영 미반영.

**{note}** 정상 완주마 마지막 3두라는 새 목표로 기존 118개 입력을 학습한 최종 6모델이다. 학습·보정·정책 선택은 평가연도 이전에 한정했다.

{chr(10).join(venues)}

전체 하위 지목 적중 차이는 +2.07%p(날짜 bootstrap 95% +1.49~+2.65%p), 상대 +4.38%였다. 세 두 모두 적중은 253→323/4,798경주다. 반면 입상마 오제외는 1,561→1,643두, 우승마 오제외는 319→376경주로 증가했다.

하위 3두를 자동 제외하면 축 변경은 단 2경주, 적중은 3,051→3,052였다. 전년도에 λ를 선택한 위험 감점 정책은 364경주 변경, 새 적중 102·기존 적중 상실 104로 3,049적중이었다. 부산의 +12경주는 95% 구간 −0.41~+1.65%p로 확정 개선이 아니고 2026년에는 1경주 줄었다.

기존 축 실패 1,748경주 중 실제 정상 하위 3두는 392경주(22.43%)였다. 하위 3두와 축 실패는 상당 부분 다른 목표다. 하위권 진단 후보로 보관하되 자동 제외·축 감점은 채택하지 않고 state_gbm 연구 기준을 유지한다. 상대 10% 축 개선은 달성하지 못했다.

정답 178,497행 독립 검산, 새·기존 점수 각각 106,622행 재현 오차 0, 축 14,397건 공식 착순 직접 채점, 현재 정답 변조 불변, 원천·운영 해시 유지 검사를 통과했다. 불완주/실격에 임의 순위를 부여하지 않았고 경계 동착은 지분 처리했다. 반복 개발 자료·공시 시각·부분연도 한계가 남으며 미래 실전이나 수익률 개선을 입증하지 않았다.

[전체 원문](../{c.HERE.name}/README.md) · [계획](../{c.HERE.name}/PLAN.md) · [수치](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [미게시 요약](../{c.HERE.name}/PUBLICATION.md) · [용량 명세](../{c.HERE.name}/outputs/artifact_inventory.json).
''')
    arc.finish(note)

if __name__=='__main__':main()
