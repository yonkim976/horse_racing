"""Render measured joint-model development outcomes into the Korean report."""

# Report Markdown keeps each paragraph/table row intact.
# ruff: noqa: E501
from __future__ import annotations

import json
import shutil

import polars as pl

from scripts.run_jeju_joint_top3 import OUT, ROOT, save


def main():
    summaries = {r["model"]: r for r in json.loads((OUT / "summary.json").read_text())}
    pairs = {
        (r["candidate"], r["reference"]): r
        for r in json.loads((OUT / "paired_comparisons.json").read_text())
    }
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    error_rows = []
    for name in summaries:
        s = p.filter(pl.col("model") == name)
        wrong_set = s.filter(~pl.col("set_hit")).height
        wrong_order_after_correct_set = s.filter(pl.col("set_hit") & ~pl.col("order_hit")).height
        error_rows.append(
            dict(
                model=name,
                wrong_set=wrong_set,
                correct_set_wrong_order=wrong_order_after_correct_set,
                correct_order=int(s["order_hit"].sum()),
                interpretation="post-hoc descriptive error decomposition, no additional fitting or selection",
            )
        )
    save("error_decomposition.json", error_rows)
    table = "\n".join(
        f"| {name} | {summaries[name]['single_hits']}/715 ({100 * summaries[name]['pick_hit']:.2f}%) | {summaries[name]['set_hits']}/715 ({100 * summaries[name]['set_hit']:.2f}%) | {summaries[name]['order_hits']}/715 ({100 * summaries[name]['order_hit']:.2f}%) |"
        for name in ["P_H3", "R_H3", "M0_H2", "J_H3_w05", "J_H3_w10"]
    )

    def contrast(reference, metric, scale=100):
        v = pairs[("J_H3_w10", reference)][metric]
        return f"{v['delta'] * scale:+.2f}, 95% 구간 [{v['day_ci'][0] * scale:+.2f}, {v['day_ci'][1] * scale:+.2f}]"

    scoretable = "\n".join(
        f"| {name} | {s['place_brier']:.6f} | {s['set_nll']:.6f} | {s['order_nll']:.6f} |"
        for name, s in summaries.items()
    )
    iterations = [e["diagnostics"]["selected_iteration_"] for e in ledger["estimator_fits"]]
    text = f"""# 제주마 공동 입상·순위 모델 v4 결과

## 결론

새로운 공동 모델 구현과 실제 학습·평가를 완료했다. **한 마리 입상은 수치상1경주 더 맞혔으나, 세 마리 조합과 정확한 순위에서는 기존 최고 모델을 넘지 못했다.** 이번 결과로 기존 모델을 교체하거나100%에 가까워졌다고 판단하지 않는다.

현재 개발 데이터에서의 수치상 최고 기록은 한 마리 입상446/715(62.38%), 세 마리 조합57/715(7.97%), 정확 순위18/715(2.52%)다. 이 세 기록은 서로 다른 모델의 결과이며 한 모델이 동시에 달성한 기록이 아니다. 한 마리 최고 기록의1경주 증가는 확인된 개선이 아니다.

## 1. 수행한 작업

-68개 H3 변수에서 공동 숨은층16개와 입상/순위 두 출력을 학습했다. 결측 처리·범주 처리 후 실제 입력은 모든 폴드83열이다.
-입상 집합 확률과 그 집합 안에서의 순위 확률을 곱해 하나의 일관된 전체 순위 분포를 만들었다. 한 마리 입상 확률은 그 말을 포함한 집합 확률을 합산한다.
-입상 집합 손실을 추가로 강조한 J_H3_w05와 전체 순위 확률을 학습한 J_H3_w10을 학습 전에 지정했다.
-네 시계열 폴드 × 두 후보 × 시드17·43 =16회 학습, CAL 구간에서8회 두 온도 보정,8개 모델 묶음을 저장했다.
-기존 P_H3·R_H3·M0_H2의 저장된 예측을 그대로 비교했다. 기존 참조 모델은 다시 학습하지 않았다.

## 2. 공통715경주 적중 결과

2025년 네 분기,98경주일의 동일715경주다. 예측 정책은 가장 확률이 높은 세 마리 집합을 선택하고 그 집합 안에서 순위를 선택하는 기존 정책을 유지했다.

| 모델 | 한 마리 공식3위 이내 | 세 마리 집합 모두 | 1·2·3위와 순서 모두 |
|---|---:|---:|---:|
{table}

J_H3_w05와 J_H3_w10은 모두 한 마리446회 적중이지만 선택한 말이 항상 같은 것은 아니다. 입상 집합 손실을 더 강조한 w05가 집합 적중을 늘리지는 못했다. 추가 세트 손실은 이 구조·조건에서 유용하다는 근거를 얻지 못했다.

## 3. 차이의 불확실성

경주일 단위로 묶어5000회 재표본한 차이의95% 구간이다. 단위는 퍼센트포인트다. 동일 경주 비교이며 반복 개발 평가에 대한 다중비교 보정은 적용하지 않은 탐색 결과다.

| J_H3_w10 비교 | 적중률 차이와95% 구간 |
|---|---|
| 한 마리: P_H3 대비 | {contrast("P_H3", "pick_hit")} |
| 세 마리: R_H3 대비 | {contrast("R_H3", "set_hit")} |
| 정확 순위: M0_H2 대비 | {contrast("M0_H2", "order_hit")} |

한 마리1경주의 차이는 표본 변동으로도 설명될 수 있다. 집합 적중은 R_H3보다13경주 적었으며, 경주일 구간은[-3.76, 0.00]퍼센트포인트로 개선 근거를 얻지 못했다. 정확 순위도 기존 최고보다1경주 적었다.

## 4. 확률 추정과 적중률을 구분

아래 오차는 낮을수록 좋다. Brier는 말별 입상 확률과0/1 정답 사이의 제곱오차를 경주별 평균한 값이다. NLL은 실제 정답 조합에 부여한 확률이 작을수록 커지는 오차다.

| 모델 | 입상 Brier | 집합 NLL | 전체 순위 NLL |
|---|---:|---:|---:|
{scoretable}

-입상 Brier는3위 경계 동착6경주를 제외한709경주에서 비교한다. 집합·순위 NLL과 적중률은 가능한 동착 정답 확률을 합산해715경주에서 계산한다.
-J_H3_w10의 전체 순위 NLL은 P_H3보다0.028657 낮지만 경주일95% 차이 구간은[-0.071924, +0.013331]로0을 포함한다. R_H3 대비는0.066417 낮고 구간은[-0.111855, -0.020785]다.
-확률 오차가 개선되더라도 가장 확률이 높은 한 조합을 맞히는 횟수가 증가한다는 뜻은 아니다. 이번 결과에서 그 차이가 확인됐다.

## 5. 실패 구조와 다음 단계

J_H3_w10의715경주를 사후 진단하면 다음과 같다. 이 진단을 보고 새 후보를 추가 학습하지 않았다.

| 결과 | 경주 수 |
|---|---:|
| 세 마리 집합부터 틀림 | 671 |
| 세 마리 집합은 맞고 순서만 틀림 | 27 |
| 집합과 순서 모두 맞음 | 17 |

정확 순위 오답698경주 중671경주(96.13%)는 집합 선택부터 틀렸다. 따라서 다음 우선순위는 **기존 R_H3 수준의 집합 선택력을 유지하면서 별도 순위 출력의 가치를 검증하는 것**이다.

1. 다음 실험 전에 집합 후보 생성·점수 결합·순위 선택 정책을 고정한다. R_H3의 집합 선택과 공동 모델의 순위 학습을 결합하는 후보 및 기존 정책을 비교한다.
2. 결합 모델의 각 구성 요소도 FIT에서만 학습하고, 조합 가중치·선택은 TUNE, 확률 보정은 CAL에서 정한다. 이번2025년 정답으로 최적 조합을 고른 뒤 검증 성능처럼 보고하지 않는다.
3. 경주 내 상대 능력·전개 등 말 사이 상호작용은 별도 제한된 가설로 실험한다. 상대 변수14개를 단순 추가했던 H3R의 이전 실패를 고려한다.
4. 최종 파이프라인을 잠근 뒤 미사용2026년 구간으로 넘어간다.2025년을 반복 비교해 얻은 결과는 독립 최종 성능으로 간주하지 않는다.

집합을 맞힌 경주 안에서 w10은17/44=38.64%의 순위를 맞혔다. 기존 R_H3의15/57=26.32%와는 대상 경주가 다르므로, 이 비율만으로 순위 학습이 우수하다고 결론 내릴 수 없다.

## 6. 현재 변수와 한계

이번 후보는 기존 상태49개와 H3 출마표·기수·조교사19개를 사용했다. 모든 변수의 의미·출처·시점·결측 조건은 [변수 목록](/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_VARIABLE_CATALOG_2026-09-16.md)에 있다. 전체 연구 후보82개 중 상대 비교14개를 이번 후보에서는 제외했다.

-출마표 날짜는 경주일 이틀 전까지로 제한했지만 당시 최초 공개·수정 이력은 입증되지 않았다.
-확정 출전마 집단을 안다는 가정이다. 실제 운영 시점의 출전 취소·변경 반영은 아직 별도 검증이 필요하다.
-이번 신경망은 말을 개별적으로 입력받는다. 말 사이 직접 상호작용이나 경주 전체를 입력받는 구조는 아직 없다.
-16회 모두 사전 지정100회 반복 한도에 도달했다. 수학적 수렴 완료로 기록하지 않았다. TUNE이 선택한 모델은{min(iterations)}~{max(iterations)}회 시점이며, 최대 반복 후 모델을 무조건 사용하지 않았다. 모든 보정8회는 수렴했고 경계에 걸리지 않았다.
-2026년 예측·평가는0건이다. 반복 개발 비교의 편향과 미확인 가용성 가정 때문에 실전 성능이나100% 근접 정확도를 주장하지 않는다.

## 7. 검증·산출물

-관련 테스트72개 통과, 신규 확률·손실·미분 검증 포함.
-8개 저장 모델을 별도 프로세스에서 다시 불러와 점수·선택·확률·오차를 재현했다.
-FIT 자료로 전처리 통계를 다시 계산해 저장 값과 일치함을 확인했다.
-모델별715경주·6953마리 행을 대조했고 확률 합, 정답, 참조 예측 불변을 확인했다.
-경주 예측3575행, 말별 예측34765행. 원본 데이터25개·H3 특성9개·기존 실험51개 파일의 해시를 확인했다.

[실험 폴더](/Users/kimyongjin/Desktop/horse_racing/data/research/jeju_native_joint_top3_v4_20260916/README.md) · [검증 결과](/Users/kimyongjin/Desktop/horse_racing/data/research/jeju_native_joint_top3_v4_20260916/verification.json) · [학습 전 계획](/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_JOINT_TOP3_PLAN_2026-09-16.md)
"""
    # Standard Markdown list syntax for the Korean prose above.
    text = text.replace("\n-", "\n- ")
    (OUT / "REPORT.md").write_text(text)
    report = ROOT / "docs/JEJU_NATIVE_JOINT_TOP3_REPORT_2026-09-16.md"
    report.write_text(text)
    shutil.copy2(__file__, OUT / "reproduce" / "write_jeju_joint_report.py")
    print(report)


if __name__ == "__main__":
    main()
