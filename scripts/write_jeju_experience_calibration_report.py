"""Write a faithful report of the preregistered v9 audit and calibration comparison."""
# ruff: noqa: E501

import json

import polars as pl

from scripts.run_jeju_experience_calibration import OUT, ROOT, save


def main():
    summary = {r["model"]: r for r in json.loads((OUT / "summary.json").read_text())}
    pairs = json.loads((OUT / "paired_comparisons.json").read_text())
    contrasts = {(r["candidate"], r["reference"]): r for r in pairs}
    audit = json.loads((OUT / "experience_audit.json").read_text())
    stats = json.loads((OUT / "experience_audit_metadata.json").read_text())
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    cal = contrasts[("C_EXPERIENCE_FIXED", "HY_R_FORM")]
    sel = contrasts[("C_EXPERIENCE_SELECT", "HY_R_FORM")]
    cal_pass = cal["place_brier"]["day_ci"][1] < 0 and cal["place_logloss"]["delta"] <= 0
    sel_pass = (
        sel["set_hit"]["day_ci"][0] > 0
        and sel["pick_hit"]["delta"] >= 0
        and sel["order_hit"]["delta"] >= 0
    )
    save(
        "decision.json",
        dict(
            calibration_research_candidate=cal_pass,
            reselection_candidate=sel_pass,
            base_action_policy="HY_R_FORM",
            calibration_candidate="C_EXPERIENCE_FIXED" if cal_pass else None,
            production_probability_replacement=False,
            requires_untouched_period_validation=True,
            caveat="Exploratory unadjusted repeated2025 development; Brier CI upper bound near zero; "
            "fixed-bin ECE worsened, residual section-missing bias persists.",
        ),
    )
    frame = pl.read_parquet(OUT / "race_predictions.parquet")
    base = frame.filter(pl.col("model") == "HY_R_FORM").sort("race_id").to_dicts()
    new = frame.filter(pl.col("model") == "C_EXPERIENCE_SELECT").sort("race_id").to_dicts()
    changes = []
    for key, col in [
        ("pick", "pick_horse_id"),
        ("set", "predicted_set"),
        ("order", "predicted_order"),
    ]:
        hit = key + "_hit"
        changes.append(
            dict(
                target=key,
                posthoc=True,
                changed=sum(a[col] != b[col] for a, b in zip(base, new, strict=True)),
                lost=sum(a[hit] and not b[hit] for a, b in zip(base, new, strict=True)),
                gained=sum(not a[hit] and b[hit] for a, b in zip(base, new, strict=True)),
            )
        )
    save("policy_changes.json", changes)
    text = """# 제주마 경험·구간 결측별 확률 보정 v9 결과

작성일: 2026-09-16

## 결론과 결정

**전체 표본에서 해당 거리 경험이 없는 말과 일부 구간 기록이 결측인 말의 입상 확률 과대 예측을 확인했다.** 경험·결측 보정은 확률 오차를 소폭 줄였지만, 선택 변경으로 적중률이 높아지지는 않았다.

- 경험·결측 보정 C_EXPERIENCE_FIXED는 사전 고정한 확률 오차 기준을 통과해 **독립 검증을 위한 연구 후보**로 남긴다. 기존 한 마리·세 마리·순서 선택을 유지한다.
- 보정 확률로 선택까지 바꾼 C_EXPERIENCE_SELECT는 한 마리 454회·집합 57회로 동일하고, 순서는 21→19회로 줄어 채택하지 않는다.
- 실제 운영 확률을 교체하지 않았다. 2025년 반복 개발, 다중비교 미보정, 0에 매우 가까운 Brier 차이 구간 상한, 구간별 잔여 과신과 ECE 악화를 함께 고려해야 한다. 2026년 예측·평가는 하지 않았다.

## 1. 전체 출전마에서 확인한 과신

확률 진단은 경계 동착 6경주를 제외한 **709경주·6,894두 출전 행**을 사용했다. 같은 말의 여러 출전이 포함되므로 고유 말 수가 아니다. 아래 ‘평균 예측’은 구간 내 출전 행 동일 비중이며, 실제 입상률과 차이를 비교했다. 경험 0회는 **해당 거리 첫 출전**이며 생애 첫 출전을 뜻하지 않는다.

| 구간 | 출전 행 | 기존 평균 예측 | 실제 입상률 | 기존 과대 예측 차이 [경주일 95% 구간] | 보정 평균 예측 |
|---|---:|---:|---:|---:|---:|
"""
    labels = {
        "0": "같은 거리 경험 0회",
        "1-2": "같은 거리 경험 1~2회",
        "3-5": "같은 거리 경험 3~5회",
        "6+": "같은 거리 경험 6회 이상",
        "false": "지정 구간 변수 관측",
        "true": "지정 구간 변수 결측",
    }
    for r in audit:
        if (
            r["model"] != "HY_R_FORM"
            or r["population"] != "all_entries"
            or r["dimension"] not in ["distance_experience", "section_missing"]
            or not r["entries"]
        ):
            continue
        b = next(
            a
            for a in audit
            if a["model"] == "C_EXPERIENCE_FIXED"
            and a["population"] == r["population"]
            and a["dimension"] == r["dimension"]
            and a["value"] == r["value"]
        )
        lo, hi = r["bias_day_ci"]
        text += (
            f"| {labels[r['value']]} | {r['entries']:,} | {100 * r['mean_probability']:.2f}% | {100 * r['observed_rate']:.2f}% | "
            f"{100 * r['overprediction']:+.2f}%p [{100 * lo:+.2f}, {100 * hi:+.2f}] | {100 * b['mean_probability']:.2f}% |\n"
        )
    text += """
‘구간 결측’은 과거 초반 상위 3 빈도 또는 최근 막판 상대속도 중 하나라도 유효값이 없는 경우다. 원본 모든 구간 기록이 없다는 뜻은 아니다. 경험 미상은 이번 평가에서 0행이다.

- 해당 거리 경험 0회의 평균 과신은 **+2.88%p→+0.49%p**로 줄었다.
- 지정 구간 변수 결측의 평균 과신은 **+9.01%p→+5.21%p**로 줄었다. 보정 후에도 경주일 구간 [+1.24, +9.39]%p로 양수여서 과신이 남는다.
- 경험 1~2회가 모두 과신한다는 확실한 증거는 없다. 해당 구간의 기존 오차 구간은 0을 포함하며 보정 후에도 평균 차이가 비슷하다.
- 모든 출전마에서 예측 확률 합과 정답 수가 경주마다 3이므로 전체 평균 차이는 구조적으로 0이다. 하위 구간과 확률 구간을 봐야 과신을 찾을 수 있다.

## 2. 기존에 고른 한 마리에서는 불확실성이 더 크다

모든 후보에서 기존 HY_R_FORM이 선택한 말을 동일하게 추적했다. 경계 동착 제외 709개 선택 중 지정 구간 변수 결측은 **51개**로 사전 기준 100개보다 적다.

- 전체 기존 선택마: 평균 예측 65.50%, 실제 입상 63.47%. 평균 과신 +2.03%p의 구간은 [−1.58, +5.41]%p다.
- 구간 결측 선택마 51개: 평균 예측 57.69%, 실제 입상 50.98%. 차이 +6.71%p의 구간은 [−6.44, +20.19]%p다.
- 해당 거리 경험 0회 선택마 232개: 예측 67.65%, 실제 68.10%로 전체 출전마의 경험 0회 과신과 양상이 다르다.

따라서 ‘경험이 없거나 기록이 부족한 말은 선택에서 무조건 제외’하는 규칙을 만들지 않는다. 전체 표본의 확률 오류가 선택된 한 마리의 적중 손실로 그대로 이어진다고 단정할 수 없다.

## 3. 세 목표의 적중 결과

적중은 동착을 포함한 전체 **715경주**가 분모다. FIXED는 보정된 확률을 표시하지만 기존 행동을 유지하는 정책이며, SELECT는 같은 보정 확률로 행동을 다시 정한다.

| 모델/정책 | 한 마리 입상 | 세 마리 전체 | 정확한 순서 |
|---|---:|---:|---:|
"""
    names = {
        "HY_R_FORM": "기존 모델",
        "C_GLOBAL_FIXED": "전체 온도 보정·선택 유지",
        "C_EXPERIENCE_FIXED": "경험·결측 보정·선택 유지",
        "C_EXPERIENCE_SELECT": "경험·결측 보정·다시 선택",
    }
    for name, label in names.items():
        r = summary[name]
        cells = [
            f"{r[k]}/715 ({100 * r[k] / 715:.2f}%)"
            for k in ["single_hits", "set_hits", "order_hits"]
        ]
        text += f"| {label} | " + " | ".join(cells) + " |\n"
    text += """
| 선택 변경 항목 | 선택이 달라진 경주 | 기존 정답을 잃음 | 새 정답을 얻음 |
|---|---:|---:|---:|
"""
    for row in changes:
        text += f"| {row['target']} | {row['changed']} | {row['lost']} | {row['gained']} |\n"
    text += """
세 마리 선택은 97경주에서 달라졌지만 정답을 5개 얻고 5개 잃어 총 적중은 같았다. 정확한 순서는 2개를 잃고 새 정답은 없었다. 확률 오차를 줄이는 작업과 가장 높은 확률의 한 선택을 맞히는 작업은 결과가 다를 수 있다.

## 4. 확률 오차 결과와 사전 판정

Brier와 로그손실은 낮을수록 좋다. 아래 입상 확률 지표는 709경주에서 먼저 경주 내 말별 평균을 구하고 경주 동일 비중으로 집계했다. 앞의 하위 구간 진단은 출전 행 동일 비중이므로 집계 단위가 다르다.

| 모델/정책 | 입상 Brier | 입상 로그손실 | 집합 NLL | 순서 NLL |
|---|---:|---:|---:|---:|
"""
    for name, label in names.items():
        r = summary[name]
        text += f"| {label} | {r['place_brier']:.6f} | {r['place_logloss']:.6f} | {r['set_nll']:.6f} | {r['order_nll']:.6f} |\n"
    text += """
아래 차이는 후보−기준이며 경주일 단위 짝지은 재표본 5,000회의 95% 구간이다.

| 후보 − 기준 | Brier 차이 [구간] | 입상 로그손실 차이 [구간] |
|---|---:|---:|
"""
    for pair in pairs:
        cells = []
        for k in ["place_brier", "place_logloss"]:
            v = pair[k]
            lo, hi = v["day_ci"]
            cells.append(f"{v['delta']:+.8f} [{lo:+.8f}, {hi:+.8f}]")
        text += f"| {pair['candidate']} − {pair['reference']} | " + " | ".join(cells) + " |\n"
    text += """
경험·결측 보정의 기존 대비 Brier 감소는 약 0.000431, 상대 감소 약 0.23%다. 구간 상한은 **−0.00000141**로 0에 매우 가깝다. 로그손실도 소폭 감소했다. 사전에 고정한 ‘Brier 구간 상한 <0, 로그손실 점추정 비악화’를 만족하므로 확률 보정 연구 후보로 보존한다. 다중비교 보정 없는 반복 개발 결과를 확정적인 실전 향상으로 해석하지 않는다.

선택 변경의 집합 적중 차이는 0%p, 구간 [−0.85, +0.85]%p이며 순서 점추정은 감소했다. 선택 변경 후보 기준은 통과하지 못했다.

### 모든 보정 지표가 개선된 것은 아니다

고정된 다섯 확률 구간에서 평균 예측−실제 입상률의 절댓값을 가중한 ECE도 계산했다. 이 값은 구간 경계에 민감하며 Brier와 다른 측면을 측정한다.

| 정책 | 전체 출전 행 ECE | 기존 선택마 ECE |
|---|---:|---:|
"""
    for name in ["HY_R_FORM", "C_GLOBAL_FIXED", "C_EXPERIENCE_FIXED"]:
        a = next(
            r for r in stats["summary"] if r["model"] == name and r["population"] == "all_entries"
        )
        b = next(
            r
            for r in stats["summary"]
            if r["model"] == name and r["population"] == "baseline_selected"
        )
        text += f"| {names[name]} | {a['ece_fixed_bins']:.6f} | {b['ece_fixed_bins']:.6f} |\n"
    text += """
ECE는 악화했다. 그러므로 ‘확률이 모든 면에서 잘 보정되었다’거나 ‘결측 과신이 해결되었다’고 보고하지 않는다. ECE에 별도 유의성 판정은 하지 않았다. 이번 사전 판정은 Brier·로그손실 기준의 연구 후보 판정이며, 실전 교체는 보류한다.

## 5. 구현·학습 방식

새 점수는 `exp(log_scale) × 기존 log 집합 확률 + 세 말의 경험·결측 보정 합`이다. 모든 세 마리 조합을 다시 정규화하고, 기존 조건부 순서 모델을 곱해 순서 확률을 만든다. 입상 주변확률 합은 3, 집합과 순서의 전체 확률 합은 각각 1이다.

- 전체 온도 대조군은 모수 1개다. 경험 보정은 온도와 경험 0회·1~2회·3~5회·미상·구간 결측의 가산 보정 5개다. 경험 6회 이상·구간 관측을 기준으로 한다.
- 보정 방향을 강제하지 않는다. 미상 경험은 관측이 없어 해당 계수가 0으로 남았다.
- CAL에서만 경주 동일 비중의 입상 이진 로그손실을 최소화했다. L2=.01로 무보정에 가까운 값을 선호하고, 모든 모수 범위를 [-2,2], 최대 150회로 고정했다.
- 기존 모델의 원래 온도와 새 보정은 같은 CAL 구간을 사용한다. 독립된 두 번째 보정 표본이 아니다. FIT/TUNE의 원모델과 전처리, 기존 순서 출력·온도는 바꾸지 않았다.
- 새 보정 8회는 모두 수렴했고 경계 모수는 없었다. 전체 온도는 5회, 경험 보정은 11~12회 반복으로 종료했다. CAL에서 경계 동착을 제외한 경주 수는 181·166·189·191개다.

| 폴드 | 온도 log_scale | 경험 0회 보정 | 경험 1~2회 보정 | 경험 3~5회 보정 | 미상 보정 | 구간 결측 보정 |
|---|---:|---:|---:|---:|---:|---:|
"""
    for row in ledger["calibration_fits"]:
        if row["model"] == "C_EXPERIENCE":
            text += (
                f"| {row['fold']} | " + " | ".join(f"{v:+.4f}" for v in row["parameters"]) + " |\n"
            )
    text += """
보정값은 확률 퍼센트포인트가 아니라 집합 점수에 더하는 계수다. 같은 계수라도 다른 출전마와 조합에 따라 말별 확률 변화가 달라진다. 경험과 결측은 서로 연관되어 있으므로 각 계수를 독립적인 원인 효과로 해석하지 않는다.

## 6. 검증과 저장

- 관련 테스트 **34개 통과**: 보정 목적함수의 수치 기울기, 구간 경계·결측, 확률 합, 무보정 동일성, 결정적 학습, 경계 동착 제외, 기존 행동 보존, N=3 특수 사례를 포함한다.
- 저장한 보정기 **8개**를 다시 불러 전체 평가 예측을 재현했다. 보정기 8개를 원래 CAL 자료만으로 다시 적합해 계수를 재현했다.
- 기존 참조 예측 불변, 기존 순서 출력·온도 불변, FIXED 행동 보존, 두 경험 정책의 확률 손실 동일성, 144개 하위 구간의 건수·오차를 검증했다.
- 기존 부모 자료 10개 묶음과 새 산출물의 해시를 검증한다. 최종 상태는 `verification.json`에 보존한다.
- 원본 모형 재학습은 0회, 2026년 결과·예측 사용도 0회다. 평가 715경주와 말별 예측 6,953행을 각 정책에 저장했다.

## 7. 다음 방향

1. **선택 규칙 유지:** HY_R_FORM의 한 마리·세 마리·순서 선택을 유지한다. 경험이 적다는 이유만으로 일괄 제외하지 않는다.
2. **보정 연구 후보 고정:** C_EXPERIENCE_FIXED의 정의·모수 추정 방식·비교 기준을 유지해 미사용 기간에서 재확인한다. 이번 평가를 보고 계수를 더 세게 낮추거나 구간을 다시 나누지 않는다.
3. **남은 결측 과신의 자료 원인 확인:** 지정 구간 변수 결측 292건을 출전 이력 자체 부족과 원본 구간 수집·연결 누락으로 구분할 수 있는지 원천 자료 계보를 점검한다. 실제 없는 정보를 복원했다고 처리하지 않는다.
4. **실전 정보 시점 검증:** 미사용 기간 또는 실제 사전 수집 자료로 넘어갈 때 출마표 시점·취소 처리·필수 변수·결측 정책과 최종 후보를 함께 잠근다.

현재 결과는 2025년 반복 개발, 실제 출전마 기준이며 과거 출마표 공개·수정 시각이 입증되지 않았다. 전체 표본 감사로 v8의 실패 사례 선택 편향 일부를 줄였어도, 새 독립 평가 자료에서 확인한 결과는 아니다. 100% 근접 목표에 대한 실제 적중 향상으로 이번 보정 결과를 포장하지 않는다.

## 산출물

- 계획: `docs/JEJU_NATIVE_EXPERIENCE_CALIBRATION_PLAN_2026-09-16.md`
- 실험: `data/research/jeju_native_experience_calibration_v9_20260916/`
- 진단: `audit_context.parquet`, `experience_audit.json`, `experience_reliability.json`, `experience_audit_metadata.json`
- 비교: `summary.json`, `paired_comparisons.json`, `policy_changes.json`, `decision.json`
- 재현: `protocol.json`, `run_ledger.json`, `bundles/`, `reproduce/`, `manifest.json`, `verification.json`
- 재검증: `.venv/bin/python -m scripts.verify_jeju_experience_calibration`

manifest는 자기 자신과 재검증 시 갱신되는 verification.json을 제외한 산출물 SHA-256을 보존한다.
"""
    (OUT / "report.md").write_text(text)
    (ROOT / "docs/JEJU_NATIVE_EXPERIENCE_CALIBRATION_REPORT_2026-09-16.md").write_text(text)


if __name__ == "__main__":
    main()
