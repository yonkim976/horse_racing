"""Render the research report from saved evaluation tables; never fit a model."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ROOT = HERE.parents[2]
CONCLUSION = HERE.parent / "conclusions/58_THOROUGHBRED_PROBABILITY_COMPARISON.md"
NAMES = {"ability22": "A 능력22", "early47": "E 초반47", "late66": "L 종반66",
         "additive89": "EL 합집합89", "full103": "F 기존103", "full103_pair": "FP 관계계수 추가"}
MAIN = ["full103", "additive89", "full103_pair"]
HITS = ["axis_top3", "quinella_one", "quinella_three", "qpl_one", "qpl_three"]


def table(headers, rows):
    return "\n".join(["| " + " | ".join(map(str, headers)) + " |",
                      "|" + "---|" * len(headers),
                      *["| " + " | ".join(map(str, row)) + " |" for row in rows]])


def pct(x):
    return f"{100 * x:.2f}%"


def ci(row, scale=100, digits=2):
    return f"{row.difference * scale:+.{digits}f} [{row.ci_low * scale:+.{digits}f}, {row.ci_high * scale:+.{digits}f}]"


def render(storage=None):
    metrics = pd.read_csv(OUT / "metrics.csv", dtype={"level": str})
    main = metrics[metrics.scope.eq("all_starters")]
    overall = main[main.dimension.eq("overall")].set_index("variant")
    diffs = pd.read_csv(OUT / "paired_differences.csv", dtype={"period": str})
    diffs = diffs[diffs.scope.eq("all_starters")]
    cal = pd.read_csv(OUT / "calibration_summary.csv")
    gains = pd.read_csv(OUT / "gain_loss_conditions.csv", dtype={"level": str})
    policy = pd.read_csv(OUT / "policy_comparison.csv", dtype={"period": str})
    evaluation = json.loads((OUT / "evaluation_complete.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["status"] == "passed"

    def delta(new, old, metric, period="all"):
        z = diffs[(diffs.candidate == new) & (diffs.baseline == old) &
                  (diffs.metric == metric) & (diffs.period == period)]
        assert len(z) == 1
        return z.iloc[0]

    performance = table(["후보", "경주", "축 Top3", "복승1", "복승3", "복연1", "복연3", "복연 적중수/경주"],
        [[NAMES[v], f"{int(overall.loc[v].races):,}", *[pct(overall.loc[v, c]) for c in HITS],
          f"{overall.loc[v, 'qpl_count']:.4f}"] for v in NAMES])
    annual_rows = []
    for year in ["2024", "2025", "2026"]:
        z = main[(main.dimension == "year") & (main.level == year)].set_index("variant")
        d = delta("additive89", "full103", "axis_top3", year)
        annual_rows.append([year + ("*" if year == "2026" else ""), int(z.loc["full103", "races"]),
            f"{int(z.loc['full103','axis_top3_hits'])} / {pct(z.loc['full103','axis_top3'])}",
            f"{int(z.loc['additive89','axis_top3_hits'])} / {pct(z.loc['additive89','axis_top3'])}",
            ci(d), f"{d.gains}/{d.losses}",
            f"{pct(z.loc['full103','quinella_three'])} → {pct(z.loc['additive89','quinella_three'])}",
            f"{pct(z.loc['full103','qpl_three'])} → {pct(z.loc['additive89','qpl_three'])}"])
    annual = table(["연도", "n", "F 축 적중/율", "EL 축 적중/율", "축 차이 [95% 구간], %p", "회복/상실", "복승3 F→EL", "복연3 F→EL"], annual_rows)
    delta_rows = []
    labels = ["축 Top3", "복승1", "복승3", "복연1", "복연3", "복연 적중수/경주"]
    for metric, label in zip(HITS + ["qpl_count"], labels):
        d = delta("additive89", "full103", metric)
        delta_rows.append([label, ci(d, 1 if metric == "qpl_count" else 100, 4 if metric == "qpl_count" else 2),
                           "—" if metric == "qpl_count" else f"{d.gains}/{d.losses}"])
    delta_table = table(["EL−F", "차이 [날짜 paired 95% 구간]", "회복/상실 경주"], delta_rows)
    counts = table(["후보", "0개 적중", "1개", "2개", "3개", "총 적중조합", "평균"],
        [[NAMES[v], *[int(overall.loc[v, f"qpl_count_{j}_races"]) for j in range(4)],
          int(overall.loc[v, "qpl_hits_total"]), f"{overall.loc[v,'qpl_count']:.4f}"] for v in MAIN])
    contrast_rows = []
    for new, old in [("early47","ability22"),("late66","ability22"),("additive89","early47"),
                     ("additive89","late66"),("full103","additive89"),("full103_pair","full103")]:
        contrast_rows.append([f"{NAMES[new]} − {NAMES[old]}",
            *[ci(delta(new, old, c)) for c in ["axis_top3", "quinella_three", "qpl_three"]],
            ci(delta(new, old, "qpl_count"), 1, 4)])
    contrasts = table(["사전 대비", "축 차이, %p", "복승3 차이, %p", "복연3 차이, %p", "복연 적중수 차이"], contrast_rows)
    policy_rows = []
    for _, d in policy[policy.metric.eq("quinella_three")].iterrows():
        policy_rows.append([d.period, int(d.races), f"{int(d.old_hits)} / {pct(d.old_hits/d.races)}",
            f"{int(d.new_hits)} / {pct(d.new_hits/d.races)}", ci(d), f"{int(d.gains)}/{int(d.losses)}"])
    policy_table = table(["기간", "n", "축 고정3", "전체 쌍 상위3", "차이 [95% 구간], %p", "회복/상실"], policy_rows)
    scores = table(["후보", "말 Top3 Brier", "복승 전체쌍 Brier", "복연 전체쌍 Brier", "삼복 집합 NLL"],
        [[NAMES[v], *[f"{overall.loc[v,c]:.6f}" for c in ["runner_brier","quinella_brier","qpl_brier","trio_logloss"]]] for v in NAMES])
    score_delta = table(["EL−F", "차이 [95% 구간], 낮을수록 좋음"],
        [[c, ci(delta("additive89","full103",c),1,6)] for c in ["runner_brier","quinella_brier","qpl_brier","trio_logloss"]])
    cal_rows = []
    for v in MAIN:
        for target, name in [("axis","축"),("quinella_one","복승1"),("quinella_three_union","복승3 union"),("qpl_one","복연1"),("qpl_three_union","복연3 union")]:
            c = cal[(cal.variant == v) & (cal.target == target)].iloc[0]
            cal_rows.append([NAMES[v], name, pct(c.predicted), pct(c.observed), pct(c.ece)])
    calibration = table(["후보", "대상", "평균 예측", "실제", "10구간 ECE"], cal_rows)

    def stratum_table(dimension):
        z = main[(main.dimension == dimension) & main.variant.isin(["full103", "additive89"])]
        rows = []
        for level in z.level.unique():
            q = z[z.level.eq(level)].set_index("variant")
            loss = gains[(gains.candidate == "additive89") & (gains.dimension == dimension) &
                         (gains.level == level) & (gains.metric == "axis_top3")].iloc[0]
            name = {"1":"서울", "3":"부산"}.get(level, level) if dimension == "meet" else level
            rows.append([name, int(q.loc["full103","races"]),
                *[f"{pct(q.loc['full103',c])} → {pct(q.loc['additive89',c])}" for c in ["axis_top3","quinella_three","qpl_three"]],
                f"{int(loss.gains)}/{int(loss.losses)}"])
        return table(["조건", "n", "축 F→EL", "복승3 F→EL", "복연3 F→EL", "축 회복/상실"], rows)

    sens_rows=[]
    for scope, source, description in [
        ("all_starters", metrics, "전체 출발자"),
        ("normal_finishers_conditioned", metrics, "정상완주 조건부"),
        ("all_starters", pd.read_csv(OUT/"unambiguous_metrics.csv"), "미해결 2경주 제외")]:
        z=source[(source.scope==scope)&(source.dimension=="overall")].set_index("variant")
        for v in MAIN:
            q=z.loc[v]
            sens_rows.append([description,NAMES[v],int(q.races),int(q.starts),
                *[pct(q[c]) for c in ["axis_top3","quinella_three","qpl_three"]]])
    sensitivity=table(["모집단", "후보", "경주", "출발/조건부 행", "축", "복승3", "복연3"],sens_rows)
    storage_line = "용량 명세는 최종 파일 확정 후 갱신한다."
    if storage:
        storage_line = (f"신규 보관 {storage['new_file_count']:,}파일, {storage['new_bytes']:,} bytes "
            f"({storage['new_bytes']/1048576:.6f} MiB). 가장 큰 파일은 `{storage['largest_file']['path']}` "
            f"{storage['largest_file']['bytes']:,} bytes. 기존 수정 {storage['modified_file_count']}파일의 "
            f"최종 합계 {storage['modified_final_bytes']:,} bytes, 순증감 {storage['modified_delta_bytes']:+,} bytes. "
            "300,000,000 bytes 상한 및 개별 100,000,000 bytes 제한 이내다.")

    text = f"""# 더러브렛 축·복승·복연 확률 비교

2026-10-22 · 연구58 · 서울·부산 · 연구 후보 검증 완료 · 운영 미반영·미게시.

**축마는 기존 연구 모델보다 좋아진 신호가 있다. 모든 승식이 함께 개선됐다는 근거는 부족하다.**
89개 변수 후보(EL)는 기존103(F)보다 4,799경주에서 축을 39경주 더 맞혔다(60.47%→61.28%, +0.81%p, 날짜 paired 95% 구간 +0.10~+1.58%p). 연도별 순증은 +15/+7/+17이다. 반면 복승3은 16경주 감소했고 세 연도 모두 하락했다. 사전에 고정한 전체 승식 개선 조건을 통과한 후보는 없다. EL을 축 연구 후보로 보존하며 운영 교체는 하지 않는다.

같은 F 모델에서 복승3 선택을 축 고정 방식에서 전체 쌍 확률 상위3으로 바꾸면 58경주가 늘었다(+1.21%p, 95% 구간 +0.59~+1.92%p). 이는 **조합 선택 정책**의 후향 개선 신호이며, 입력 변수 추가 효과나 운영 모델 대비 성능이 아니다. 두 결과를 합친 임의의 혼합 모델은 실험하지 않았다.

## 비교 대상을 먼저 구분한다

| 구분 | 확인된 대상 | 이번 역할 |
|---|---|---|
| 실제 운영 | registry `thoroughbred-main-20260919-v1`, champion `thoroughbred-abc-current-a-b-c-20260919` | A/B/C 별도 모형. 변경·직접 성능 비교 없음 |
| 선택 연구 기본선 | `20261008_profile_carried_weight_v1`의 `month_gate_weight22` | 능력22(A), 저장 모형 재사용 |
| 기존 연구 비교 모델 | `20261009_gate_front_late_v1`의 `full103` | F, 저장 모형과 Top3 확률 재현 |
| 최근57G~57K | 부산 정상완주 기록 회귀·전개/종반 연구 | 가설 배경. F나 운영 모형과 동일하지 않음 |

[모델 감사](audit_model.md)와 [최근 연구·상류 입력 감사](audit_recent.md)에 실제 경로·변수·학습 타깃을 기록했다. 57G의 B3−B0 축 차이 +4/1,976은 불확실하지만 B3−B2의 +15는 양의 구간을 가진다. 57I의 실제 선두 성적은 사후 관측이고, 57K의 관계쌍 추가는 복연1을 세 연도 모두 낮췄다. 기존 결론을 새 비교의 정답으로 가정하지 않았다.

## 대상·설계·확률

주 평가기간은 **2024-01-05~2026-09-20**, 서울2,838·부산1,961경주, 총4,799경주·50,754 출발행이다. 406개 날짜를 동일하게 비교했다. 학습/이력 표는 2017~2026년 178,497행·16,435경주이며 2010~2016년은 기존 과거이력 warm-up이다. 제주와 영천은 이번 학습·평가에 없다.

[사전계획](PLAN.md)은 2026-10-21 22:48:49 UTC(10월22일07:48 KST)에 해시와 함께 고정했다. 새 최종모형은 E/L/EL의 지역×평가연도 **18개**(초기 선택+재학습36회), 기존 A/F **12개 재사용**, FP 관계계수 최적화6회로 종료했다. 추가 후보·후속 튜닝·거리별 선택 규칙은 만들지 않았다.

| 후보 | 입력·변경 | 분리해서 읽을 효과 |
|---|---|---|
| A22 | 기존 능력22 | 연구 기본선 |
| E47 | A+과거 S1F/초반역할/게이트, 공통지원 열 | 초반 묶음. 종반 입력으로 만든 선행 보조확률은 제외 |
| L66 | A+과거 G3F/G1F/회복·유지력/역할별 종반 | 종반 묶음. 과거 초반 역할로 층화된 이력 포함 |
| EL89 | E와 L의 합집합 | 초반+종반 통합 |
| F103 | EL+기존 선행 보조2·편성 종반 관계12 | 통합14열의 증분. 각 열 또는 순수 초반 효과 아님 |
| FP | F 점수 고정+3개 pair 관계계수 | 3두 공동집합 분포에 제한된 관계 보정 |

평가연도 Y마다 초기학습2017..Y−3, 조기종료Y−2 후2017..Y−2 재학습, 확률교정Y−1, 평가Y로 분리했다. 같은 경주의 말은 분할되지 않는다. 과거이력은 경주2일 전 cutoff이고 현재 실제 구간·착순은 정답/진단으로만 사용했다. 부담중량과 최종 출발명단의 공개시각은 입증되지 않아 완전한 시점 봉인 검증은 아니다.

말별 binary Top3 raw score는 확률이 아니다. 3두 집합 `q(T)=softmax(sum(score[T])/temperature + X[T]β)`를 이전 연도로 교정하고, 집합 내 6개 순서를 별도 온도의 조건부 Plackett–Luce로 배분했다. 하나의 `P(a,b,c)`에서 우승·Top2·Top3·복승·복연·쌍승·삼복·삼쌍을 합산한다. 말별 입상확률의 곱을 조합확률로 표시하지 않았다. FP의 선행확률 곱은 설명 변수일 뿐 확률 출력이 아니다.

[승식별 정답·확률·평가 계약](TARGETS.md)에 정의와 지원 범위를 명시했다. 연승은 공식 인정순위 계약을 확보하지 못해 채점하지 않았고, Top3를 연승으로 바꾸어 부르지 않았다. 단승·쌍승·삼쌍은 확장 구조를 제공하지만 별도 추천 성능 검증을 마쳤다는 뜻은 아니다.

## 같은 경주·출발마·추천 수의 성능

복승/복연은 각 승식 확률의 전체 쌍 상위1·3조합이며 중복 쌍은 없다. 아래 복연3은 하나 이상 맞힌 경주 비율이다. 적중수 평균은 그3조합에서 맞은 개수다.

{performance}

EL−F 적중률 차이의 단위는 %p, 마지막 행만 조합수/경주다. 구간은 날짜 단위 paired bootstrap 2,000회(seed20261022), 복수 가설 미보정이다.

{delta_table}

{annual}

*2026년은 9월20일까지다. 연도별 축 점차이는 모두 양수지만 **개별 연도 구간은 모두 0을 포함**한다. 복연3은 2025년에 감소하므로 전체의 작은 증가를 안정적 개선으로 부르지 않는다. 모든 후보·승식·연도 및 연도×지역/거리/등급 원표는 [metrics.csv](outputs/metrics.csv), 연도별·지역별 paired 구간은 [paired_differences.csv](outputs/paired_differences.csv)에 있다.

복연3 적중수 분포는 다음과 같다. 3쌍 확률의 합은 예상 적중조합 수이며, 하나 이상 적중확률은 공동분포에서 합집합으로 계산했다.

{counts}

## 정보 묶음과 선택 정책에서 알게 된 점

아래 각 칸은 차이와 95% 구간이다. 초반·종반은 점수에 더해서 평가한 것이 아니라 고정된 정보 묶음별 모델을 다시 학습해 비교했다.

{contrasts}

종반 묶음은 A 대비 축·복승3·복연3·복연 적중수에서 양의 신호가 있으며, E에 추가했을 때도 조합 지표를 개선했다. 초반의 단독 축 증분은 불확실하지만 종반에 추가한 복연 적중수에는 양의 신호가 있다. 따라서 종반 이력을 보존하고 EL89를 다음 비교 후보로 남긴다. F의 추가14열은 축을 낮추고 복승3을 소폭 올리는 혼합 결과이므로 전면 무효라고 단정하거나 순수 선행 효과로 설명하지 않는다.

FP의 적중 지표 구간은 모두 0을 포함한다. 2025년 축은 F보다2경주 줄었으며, 2026 복연 적중수 차이는 −0.0101/경주(95% −0.0189~−0.0015)였다. 집합 NLL과 일부 Brier 개선은 있으나 사용자 우선순위인 선택 적중 개선은 확인하지 못해 관계계수 추가를 채택하지 않는다.

**모형을 바꾸지 않은 정책 대조:** 아래는 F 하나에서 축+차순위3두의 기존 복승3과 전체 쌍 확률 상위3을 비교한 결과다. 같은3조합 예산이며 복승1은595경주로 동일하다.

{policy_table}

이 대조는 사전계획에 포함됐다. 2024의 정책 차이 구간은 0을 포함한다. 배당과 구매비용을 평가하지 않았으므로 +58경주를 수익 증가로 해석할 수 없다. 독립 확인은 [정책 검증](policy_audit.md)을 참조한다.

## 확률 보정과 일관성

Brier는 경주 내 말/쌍을 평균한 뒤 경주에 동일 가중을 줬다. 낮을수록 좋다.

{scores}

{score_delta}

EL의 전체 말/쌍 Brier는 F보다 작지만 선택한 복승1 Brier는 증가한다. `decision.json`의 `all_brier_nonworse`는 전체 말/복승쌍/복연쌍의 세 Brier에만 해당한다. 선택 추천 전체의 비악화나 완전한 보정을 뜻하지 않는다.

{calibration}

EL 축 ECE는 F보다 작지만 복승3·복연3 합집합 확률을 평균적으로 과대예측한다. 전체 말Top3 합3, 복승쌍 합1, 복연쌍 합3 때문에 전체 평균 예측·관측은 구성상 일치할 수 있다. 이것을 보정 성공의 증거로 삼지 않는다. 고정10구간의 ECE도 낮은 확률이 한 구간에 몰리면 분해능이 약하다. [확률구간 원표](outputs/calibration_overall.csv), [선택 보정 요약](outputs/calibration_summary.csv), [진단 절편/기울기](outputs/calibration_diagnostic_slopes.csv)를 함께 보존했다. 평가자료로 진단한 기울기를 예측에 다시 적용하지 않았다.

우승≤Top2≤Top3, 복승≤복연≤각 말Top3, 순서/집합합1, 말Top3합3, 복승합1, 복연합3, 각 말의 쌍 주변확률 합을 검사했다. 최대 수치오차는 **{evaluation['max_coherence_error']:.3g}**였다. 정규화 일관성과 경험적 보정은 별개다.

## 지역·거리·등급과 회복/상실 조건

{stratum_table('meet')}

{stratum_table('distance_m')}

{stratum_table('grade')}

거리·등급 표는 기술적 진단이며 개별 채택 규칙으로 사용하지 않았다. 1900m 1경주·2200m2경주·2300m6경주는 일반화 근거가 부족하다. 축 회복189/상실150은 서울112/87, 부산77/63이다. 과거이력이 모두 있는3,983경주에서는158/124, 이력이 없는 말이 포함된816경주에서는31/26이었다. 이 조건 차이를 인과 효과로 해석하지 않는다.

[경주별 회복·상실](outputs/gain_loss_races.parquet)은 각 경주의 기존/후보 선택마, 과거이력·사전 선행확률·종반기록과 모든 적중차이를 보존한다. [조건별 집계](outputs/gain_loss_conditions.csv)는 연도·지역·거리·등급·두수·이력에 따른 회복/상실을 제공한다. 사후 실제 선행 성공 여부로 새 필터를 만들지 않았다.

## 완주·취소·실격·동착·결측 처리

주 모집단50,754행은 정상완주50,608, 확인된 DNF140, 실격3, 미해결 `special_result`3이다. DNF/DQ는 Top3=0으로 남겼다. 미해결3행은 기존92 라벨을 유지한 한계이며 해당2경주를 제외한 민감도도 제공한다. 완주시간 결측·비양수는 정상완주로 바꾸지 않았다. 같은4,799경주의 DB 추가697행(취소/경주제외/출발제외)은 비출발자라 예측 슬롯에서 제외했다. 취소를 실패로 추가해 분모를 늘리지 않았다.

평가기간의4,827경주 중 상위3위 동착28경주는 기존 feature cohort 밖이다. 이 연구는 이들에 대한 공식 정산/예측을 지원하지 않는다. 2017+ 전체에서는100경주 제외=상위 동착98+미상결과2로 원천 ledger와 일치했다. [데이터 감사](audit_data.md)와 [상태·키 증거](audit_data.json)에 연도별 분모와 제외 키를 남겼다.

{sensitivity}

정상완주 조건부는 사후에 비완주 말을 포함한 공동순서를 제거하고 재정규화한 결과다. 경주 수는 같아도 예측 시점에 알 수 없는 정보를 사용하므로 실전 적중률로 읽으면 안 된다. 미해결2경주 제외 결과에서도 EL 축 증가·복승3 감소 방향은 같다.

## 검증·한계·다음 판단

[독립 검증](outputs/verification.json)은31개 동결 입력 해시,30개 모델 분할의 재추론, 동일 경주·출발마,36개 확률교정 캐시, 저장 정답/추천/적중수,108개 표본의 순서 전수열거를 검사했다. 모델 raw score 재추론 최대 차이는0이고 기존 F Top3 주변확률도 최대8.88e−16 차이로 재현했다. 검증자는 조기종료 학습을 다시 수행하지 않았으므로 반복수 선택 자체는 학습 코드·메타데이터에 근거한다.

독립 감사에서 동률인 raw score가 주변확률 합산 오차로 약1e−16 차이를 보이면서 마번 동률 규칙을 어긴 사례를 발견했다. 추천 비교만 소수12자리 반올림으로 고친 뒤 모든 후보를 재평가했다. 모형·교정계수·저장 확률은 바꾸지 않았다. [수정 기록](outputs/implementation_repairs.json)에 이전 결과/해시와 변경 범위를 남겼고 확률 테스트8개 및 평가 테스트3개가 통과했다. [독립 결과 해석](audit_results.md)도 최종 수정 결과를 기준으로 한다.

제한은 다음과 같다.

- 2024~2026은 이미 반복 분석한 후향 개발자료이며 새로운 미사용 시험자료가 아니다. 2026은 부분연도다. 입력 가용시각이 완전히 입증되지 않아 미래 카드 예측으로 일반화할 수 없다.
- 날짜 bootstrap은 같은 날짜의 상관을 반영하지만 재학습 불확실성, 반복 말·긴 시계열 상관, 과거 연구의 선택 편향까지 모두 반영하지 않는다. 복수 대비 구간은 미보정이다.
- 28개 podium 동착경주, 실제 연승 인정순위·동착 정산, 미해결3행의 원인, 모든 출마표의 예측 시점 상태는 아직 미지원/미확정이다.
- 선택 적중과 전체분포 proper score는 다른 목표다. 배당·구매비용을 검증하지 않았고 수익성을 주장하지 않는다.

| 판단 | 유지·보류할 내용 | 근거 |
|---|---|---|
| 유지 | 능력 기본선·과거 종반 이력·EL89 후보 | 축과 정보 묶음 증분에 후향 개선 신호 |
| 정책 후보 유지 | 전체 쌍 확률 상위3 복승 | F 고정에서 +58경주, 같은3조합 |
| 비교 기준 유지 | F103 및 추가14열의 원본 | 복승3에서 EL보다 높음. 축 목표에는 불리한 신호 |
| 채택 제외 | 이번 FP3계수 추가 | 선택 적중 개선 불확실·일부 연도 적중수 감소 |
| 미검증 | 운영 대비 성능, 전향 입력 가용성, 연승/동착 정산, 수익성 | 이번 계약·자료 범위 밖 |

**다음 우선순위는 한 번의 사전 고정 전향 비교**다. 예측 시점의 출마표·부담중량을 timestamp와 함께 봉인하고, EL89와 F103의 모형·확률교정·1/3조합 선택방식·기간·최소 표본·판정기준을 결과 전에 확정해야 한다. 축 개선과 복승3 비악화를 함께 확인한다. 이 제안은 향후 실험이며 이번에 실행·예약하지 않았다. 현재 기간에 맞춘 추가 탐색은 중단했다.

## 재현과 보관

아래 명령은 저장소 루트와 기존 동결 원천을 전제로 한다. `freeze`는 최초 동결 때만, `audit_population.py`는 플래그가 없는 새 재현 폴더에서만 실행한다. 완료 산출물을 가진 현재 폴더에서는 해시 검증과 저장 모델 재사용을 우선한다. 원천 DB·전체 feature·기존 모델 폴더는 복사하지 않았다.

```sh
# 최초 재현: 기존 outputs를 덮어쓰지 않고 입력/모집단을 고정
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/run.py freeze
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/audit_population.py
# 이미 저장한 모형/점수는 재사용. 새 실험을 추가하지 않음
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/run.py train
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/test_probability.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/test_evaluation.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/evaluate.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/summarize.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/verify.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/report.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_comparison_v1/finalize_inventory.py
```

환경은 [environment.json](outputs/environment.json), 입력 해시는 [input_manifest.json](outputs/input_manifest.json), 고정 계획은 [protocol_frozen.json](outputs/protocol_frozen.json), 정확한 변수 목록은 [feature_contract.json](outputs/feature_contract.json), 학습·교정값은 `outputs/models/`와 [calibration_parameters.json](outputs/calibration_parameters.json)에 보존했다. 출력 parquet는 저장소 ignore 규칙에 걸리지만 로컬 연구 폴더에 보존돼 있다. 별도 배포/커밋은 하지 않았다.

{storage_line}

[파일별 용량 명세](outputs/artifact_inventory.json) · [완수 조건 감사](COMPLETION_AUDIT.md) · [일반 이용자용 미게시 요약](PUBLICATION.md).
"""
    (HERE / "README.md").write_text(text, encoding="utf-8")
    conclusion = """# 더러브렛 축·복승·복연 확률 비교

2026-10-22 · 연구58 · 서울·부산 · 운영 미반영·미게시.

기존 연구 full103 대비 additive89는 축 적중률을60.47%에서61.28%로 높였다. 같은4,799경주에서+39경주이며 날짜 paired95% 구간은+0.10~+1.58%p다. 연도별 순증은+15/+7/+17이지만 개별 연도 구간은0을 포함한다. 복승3은29.28%에서28.94%로16경주 감소했다. 복연3은51.64%→51.76%, 평균 적중수는0.6820→0.6839로 불확실한 작은 변화였다. 축 개선 신호는 보존하되 전체 승식 개선·승격 조건은 통과하지 못했다.

능력22에 종반 이력을 추가한66개 묶음과 초반47에 종반을 추가한89개 묶음에서 조합 성적 개선 신호를 확인했다. 기존103의 통합14열 추가는 축 감소·복승3 소폭 증가로 목적별 효과가 갈렸다.3개 관계계수 추가는 집합NLL과 일부Brier를 낮췄지만 선택 적중 개선은 확인하지 못했다.

같은full103에서 축 고정 복승3 대신 전체 쌍 확률 상위3을 고르면1,347→1,405경주(+58, +1.21%p,95%+0.59~+1.92)였다. 이는 선택 정책의 후향 효과이며 모델 입력 개선이나 수익성·운영 성능 비교가 아니다.

서로 일관된 순서3두 공동분포에서 말Top3와 복승·복연을 계산했다. 확률 곱을 조합확률로 표시하지 않았고, 복연3의 적중확률과 예상 적중수를 구분했다. 연승은 공식 경주별 인정순위 규칙 미확보로 검증하지 않았다. 새18모형·기존12재사용으로 사전 탐색을 종료했다.

정상완주50,608+DNF140+DQ3+미해결3=50,754 출발행을 평가했다. 별도 취소/제외697행과 podium동착28경주를 구분했고 완주 조건부 민감도를 주 성능과 분리했다.2024~2026은 반복 사용한 후향자료이며9월20일 종료 부분연도, 현재 부담중량/최종출발명단의 공개시각 미확인 한계가 있다. 다음 우선순위는 입력시점을 봉인한89대103의 전향 비교다.

[전체 보고서](../20261022_probability_comparison_v1/README.md) · [승식 계약](../20261022_probability_comparison_v1/TARGETS.md) · [성능표](../20261022_probability_comparison_v1/outputs/metrics.csv) · [paired 구간](../20261022_probability_comparison_v1/outputs/paired_differences.csv) · [독립 검증](../20261022_probability_comparison_v1/outputs/verification.json).
"""
    CONCLUSION.write_text(conclusion, encoding="utf-8")
    publication = """# 축마와 조합 예측에서 확인한 차이

상태: 연구 요약 초안. 웹사이트 게시·운영 반영 없음. 서울·부산2024-01-05~2026-09-20의 반복 사용 후향자료.

축마1두의3위 이내 적중에서는 더 단순한89개 변수 후보가 기존103개 연구모형보다 나았다.4,799경주에서2,902→2,941경주로39경주 늘었다. 하지만 복승3조합은16경주 줄었다. 따라서 축에서 확인한 개선을 모든 조합의 개선으로 읽으면 안 된다.

복승은 실제1·2위 두 마리, 복연은3위 안에 함께 든 두 마리의 사건이다. 복연3조합은 동시에 여러 개 맞을 수 있어 ‘한 개 이상 맞힌 확률’과 ‘맞힌 개수’를 따로 표시했다. 예를 들어 세 쌍의 확률 합1.8은 예상 적중개수이고, 공동분포에서 계산한 하나 이상 적중확률0.9와 의미가 다르다. 이 숫자는 수학 검증 예시이며 실제 경주 추천이 아니다.

기존103개 모델을 유지하고 복승3조합만 고르는 방법을 바꾸어도 차이가 있었다. 축마를 반드시 포함한3쌍은1,347경주, 전체 쌍에서 확률이 높은3쌍은1,405경주를 맞혔다. 같은3조합이므로 선택 방식 자체의 개선 신호다. 새로운 입력 변수가 좋아졌다는 뜻은 아니다.

이 결과는 미래 실전 성적이나 수익성을 보장하지 않는다. 이미 여러 번 분석한 과거자료이고,28개 상위 동착경주는 모델 범위 밖이다. 연승의 실제 인정순위·정산규칙도 별도 검증이 필요하다. 운영모델은 다른A/B/C 구성으로 유지했으며, 다음에는 경기 전 출마표와 중량을 시각과 함께 고정한 새 경주 비교가 우선이다.

[표·불확실성·데이터 처리 전체 근거](README.md) · [확률과 정답의 정의](TARGETS.md).
"""
    (HERE / "PUBLICATION.md").write_text(publication, encoding="utf-8")


if __name__ == "__main__":
    inventory = OUT / "artifact_inventory.json"
    storage = json.loads(inventory.read_text()).get("summary") if inventory.exists() else None
    render(storage)
    print("Rendered README.md, PUBLICATION.md, and conclusion 58 from saved results.")
