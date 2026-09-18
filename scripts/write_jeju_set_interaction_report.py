"""Write the fixed v8 comparison and descriptive missing-horse audit in Korean."""
# ruff: noqa: E501

import json

import polars as pl

from scripts.run_jeju_set_interaction import OUT, ROOT, save


def main():
    summary = {r["model"]: r for r in json.loads((OUT / "summary.json").read_text())}
    pairs = json.loads((OUT / "paired_comparisons.json").read_text())
    diag = json.loads((OUT / "missing_horse_diagnostic.json").read_text())
    frame = pl.read_parquet(OUT / "race_predictions.parquet")
    base = frame.filter(pl.col("model") == "HY_R_FORM").sort("race_id")
    transitions = []
    for name in ["S_ADDITIVE", "S_INTERACTION"]:
        new = frame.filter(pl.col("model") == name).sort("race_id")
        transitions.append(
            dict(
                model=name,
                posthoc=True,
                both_set_correct=int((base["set_hit"] & new["set_hit"]).sum()),
                lost_set_correct=int((base["set_hit"] & ~new["set_hit"]).sum()),
                gained_set_correct=int((~base["set_hit"] & new["set_hit"]).sum()),
                old_two_to_three=int(
                    ((base["compatible_max_overlap"] == 2) & new["set_hit"]).sum()
                ),
                overlap_counts={
                    str(i): int((new["compatible_max_overlap"] == i).sum()) for i in range(4)
                },
            )
        )
    save("set_transitions.json", transitions)
    text = """# 제주마 세 마리 조합 직접 학습 v8 결과

작성일: 2026-09-16

## 결론과 채택 결정

**말 사이 상호작용을 추가한 집합 모델을 구현·학습·재현 검증했지만, 기존 HY_R_FORM을 교체하지 않는다.** 상호작용 후보의 세 마리 전체 적중은 44/715로 기존 57/715보다 13회 낮았다. 같은 구조에서 상호작용을 뺀 대조 모델은 46/715였다.

전체 학습 16회, 집합 확률 보정 8회, 저장 모델 묶음 8개를 완료했다. 기존 순서 출력과 온도는 그대로 유지했다. 2026년 예측·평가는 하지 않았다.

## 1. 공통 715경주 결과

각 경주마다 한 마리, 세 마리 집합 하나, 정확한 순서 하나를 선택했다. 2025년 715경주·98일·6,953두 출전 행의 반복 개발 평가다. 한 마리 입상은 선택한 말이 공식 3위 이내인 비율, 집합은 세 말 모두 일치, 순서는 1·2·3위가 모두 일치해야 성공이다. 동착은 가능한 공식 정답을 인정한다.

| 모델 | 설명 | 한 마리 입상 | 세 마리 전체 | 정확한 순서 |
|---|---|---:|---:|---:|
"""
    names = {
        "HY_R_FORM": "기존 유지 후보",
        "S_ADDITIVE": "세 말의 개별 점수를 합하는 집합 모델",
        "S_INTERACTION": "쌍·세 말 상호작용 19개 추가",
        "R_NO_GROWTH": "v6 발전 변수 제거 후보",
        "HY_C_REBOUND": "v7 보강 순서 후보",
    }
    for name, label in names.items():
        r = summary[name]
        cells = [
            f"{r[k]}/715 ({100 * r[k] / 715:.2f}%)"
            for k in ["single_hits", "set_hits", "order_hits"]
        ]
        text += f"| `{name}` | {label} | " + " | ".join(cells) + " |\n"
    text += """
대조 모델의 한 마리 입상은 454→460회로 늘었으나, 차이 +0.84%p의 경주일 95% 구간은 [−2.14, +3.86]%p로 0을 포함한다. 이를 확정된 개선으로 보고하지 않는다. 기존 모델은 모든 개별 목표에서 최고라는 뜻이 아니라 이번 새 후보로 대체하지 않는 기준 모델이다.

## 2. 사전 고정 비교와 불확실성

후보−기준 차이를 퍼센트포인트로 표시한다. 같은 경주/경주일을 짝지어 5,000회 재표본했으며 아래는 경주일 95% 구간이다. 다중비교 보정 없는 탐색적 구간이다.

| 후보 − 기준 | 한 마리 차이 [구간] | 집합 차이 [구간] | 순서 차이 [구간] |
|---|---:|---:|---:|
"""
    for p in pairs:
        cells = []
        for k in ["pick_hit", "set_hit", "order_hit"]:
            v = p[k]
            lo, hi = v["day_ci"]
            cells.append(f"{100 * v['delta']:+.2f} [{100 * lo:+.2f}, {100 * hi:+.2f}]")
        text += f"| {p['candidate']} − {p['reference']} | " + " | ".join(cells) + " |\n"
    text += """
- 상호작용 후보의 기존 대비 집합 차이는 −1.82%p [−3.37, −0.28]%p다. 이 개발 비교에서는 악화 방향의 근거가 있다.
- 상호작용만 추가한 효과는 집합 46→44회, −0.28%p [−1.25, +0.69]%p다. 이 차이 자체는 불확실하다. 기존 대비 감소 전부를 상호작용 탓으로 돌릴 수 없다. 모델 구조와 학습 목적도 기존 LambdaRank와 다르다.
- 승격 조건은 사전에 ‘기존 대비 집합 증가의 95% 하한 >0, 한 마리·순서 점추정 감소 없음’으로 정했다. 두 후보 모두 통과하지 못했다. 결과 확인 후 조합이나 학습 횟수를 추가하지 않았다.

## 3. 확률 손실과 적중은 다르다

| 모델 | 입상 Brier | 집합 NLL | 순서 NLL |
|---|---:|---:|---:|
"""
    for name in names:
        r = summary[name]
        text += f"| {name} | {r['place_brier']:.6f} | {r['set_nll']:.6f} | {r['order_nll']:.6f} |\n"
    text += """
모두 낮을수록 좋다. 입상 Brier는 경계 동착 6경주를 제외한 709경주, 집합·순서 NLL은 715경주를 사용한다. 상호작용 모델은 기존보다 집합 NLL이 0.01618 낮지만 차이의 경주일 구간 [−0.05147, +0.01899]는 0을 포함한다. 더 나은 전체 확률 분포 점추정과 한 조합 적중 개선을 동일시하지 않는다.

## 4. 누락된 입상마 진단

기존 후보의 세 마리 겹침은 0마리 42경주, 1마리 281경주, 2마리 335경주, 3마리 57경주였다. 두 마리가 맞은 335경주 중 경계 동착 3경주를 제외한 **332경주**에서 빠진 입상마 한 마리와 잘못 선택한 비입상마 한 마리를 대응시켰다. 비교 대상 말 ID와 사전 변수 값은 `missing_horse_pairs.parquet`에 보존했다.

아래 평균 차이는 ‘누락 입상마−선택 비입상마’다. 중앙값은 해당 변수 양쪽이 모두 관측된 대응 표본에서 각각 구했다. 결측이 다른 행을 임의로 0점 처리하지 않았다.

| 사전 변수 | 유효 대응 경주 | 누락 말 중앙값 | 선택 말 중앙값 | 평균 차이 | 결측: 누락/선택 |
|---|---:|---:|---:|---:|---:|
"""
    labels = {
        "global_elo_pre": "전체 Elo",
        "distance_elo_pre": "거리별 Elo",
        "distance_starts_pre": "같은 거리 과거 출전 수",
        "days_since_previous_start": "직전 출전 후 일수",
        "historical_early_front_rate": "과거 초반 상위 3 빈도",
        "closing_speed_quality_mean_3": "과거 막판 상대속도",
        "current_vs_previous_rival_elo": "현재−이전 상대 Elo",
        "declared_horse_number_fraction": "선언 출주번호 상대 위치",
        "declared_burden_kg": "선언 부담중량(kg)",
        "current_minus_last_burden_kg": "직전 대비 부담중량(kg)",
        "body_weight_delta_kg": "과거 마체중 변화(kg)",
        "jockey_changed": "기수 교체 여부",
        "distance_surprise_mean3": "거리별 기대 이상 수행",
        "distance_valid_count6": "거리별 유효 이력 수(최대 6)",
    }
    for r in diag["paired_features"]:
        text += (
            f"| {labels[r['feature']]} | {r['paired_observations']} | {r['median_missing']:.3f} | "
            f"{r['median_selected']:.3f} | {r['mean_missing_minus_selected']:+.3f} | "
            f"{r['missing_horse_missing_values']}/{r['selected_horse_missing_values']} |\n"
        )
    text += """
관찰한 주요 차이는 다음과 같다.

- 누락 말은 같은 거리 출전 수 중앙값이 6회, 선택 말은 2회였다. 선택된 비입상마 쪽의 과거 이력 결측도 더 많았다.
- 누락 말의 과거 초반 상위 3 빈도와 막판 상대속도는 선택 말보다 낮았다. 과거 구간 성적이 좋은 쪽만 고르는 방식으로 빠진 말을 찾을 수 있다고 단정하기 어렵다.
- 누락 말의 선언 부담중량은 평균 약 0.26kg 낮고 직전 대비 부담중량 변화도 약 0.46kg 낮았다. 이는 경주 조건·등급·말 능력 등이 섞인 관측 차이다.
- 기수 교체 여부도 대응 표본에서 차이가 있었지만, 교체가 입상을 일으켰다는 인과적 결론을 내리지 않는다.

**이 비교는 이미 ‘두 마리는 맞고 한 마리는 틀린 경우’를 골랐고, 선택된 말은 원래 높은 모델 점수를 받은 말이다.** 변수 차이는 이 선택 과정의 영향을 받는다. 경험이 적은 말을 과대평가했는지, 중량 변화에 덜 반응했는지는 다음 검증 가설이며 여기서 입증된 규칙이 아니다. 이 진단으로 이번 학습 표본이나 후보를 바꾸지 않았다.

## 5. 새 모델은 어느 정답을 얻고 잃었나

다음은 사후 오류 설명용 집계다.

| 새 모델 | 기존과 함께 집합 정답 | 기존 정답을 잃음 | 새 집합 정답을 얻음 | 기존 두 마리 정답 → 세 마리 정답 |
|---|---:|---:|---:|---:|
"""
    for r in transitions:
        text += f"| {r['model']} | {r['both_set_correct']} | {r['lost_set_correct']} | {r['gained_set_correct']} | {r['old_two_to_three']} |\n"
    text += """
상호작용 모델은 기존 ‘두 마리 정답’ 335경주 중 15경주를 세 마리 정답으로 바꾸었으나, 기존 집합 정답 28경주를 잃었다. 누락 입상마 일부를 찾은 것만으로 개선이라고 판단할 수 없음을 보여준다.

## 6. 구현 내용과 한계

기존 108개 사전 변수를 FIT에서만 전처리했다. 대조 모델은 은닉 16개 tanh 신경망의 말별 점수를 합해 모든 세 마리 집합 확률을 정한다. 상호작용 모델은 여기에 다음 19개 조합 변수를 더한다.

- 전체/거리 Elo, 초반 빈도, 막판 상대속도, 출주번호 상대 위치, 부담중량, 상대 강도 변화, 휴양 간격의 경주 내 순위를 −1~1로 변환한다.
- 각 변수별 세 쌍의 곱 평균 8개, 세 말의 곱 8개를 만든다.
- 서로 다른 말 사이 선행×추입, 선행×번호 위치, Elo×중량의 대칭 교차 곱 3개를 만든다.

조합에서 말을 나열하는 순서에 영향받지 않으며 방향을 수작업으로 강제하지 않는다. 실제 선행권 다툼이나 기수의 전개 선택을 관측한 데이터는 아니다. 순위 변환은 절대적인 능력 차이를 버리며 결측을 중간값 0으로 표현하므로, 현재 19개로 경쟁 관계를 충분히 표현했다고 주장하지 않는다.

모든 FIT 경주와 모든 가능한 세 마리 집합을 사용했다. 동착은 가능한 고유 집합 확률을 합한다. TUNE에서 집합 NLL이 가장 낮은 체크포인트를 고른 뒤, 두 시드의 조합 점수를 평균하고 CAL에서 온도 하나를 보정했다. 집합 모델의 주변확률이 가장 높은 말 한 마리와 MAP 집합을 선택한다.

순서 확률은 기존 HY_R_FORM의 출력·온도를 그대로 결합했다. 같은 세 마리를 고른 경우의 순서 규칙은 동일하다. 순서 적중 변화는 주로 세 마리 선택 변화에서 발생한다. 입상 주변확률 합은 3, 모든 집합 확률 합과 모든 순서 확률 합은 각각 1이다.

학습 16회 모두 최적화 100회 상한에 도달해 수렴 판정은 받지 못했다. 저장한 TUNE 선택 체크포인트는 9~25회다. 확률 보정 8회는 모두 성공했고 탐색 경계에 걸리지 않았다. EVAL을 본 뒤 최적화 횟수를 늘리거나 새 후보를 학습하지 않았다.

## 7. 검증과 재현

- 관련 테스트 **27개 통과**: 집합·신경망 기울기, 경계 동착 확률 합, 완전 동착, 대칭성·결측·다른 경주의 영향 분리, 비가산 상호작용, 확률 정규화·주변확률, 동률 선택, 결정적 학습을 포함한다.
- 별도 검증 스크립트로 저장 모델 묶음 **8개**를 다시 불러 모든 평가 예측을 재현했다. 기존 참조 예측 불변, 순서 모델과 온도 불변, FIT 전처리 재구축, 누락 말 대응 332건, 확률 합과 정답 라벨을 확인했다.
- 기존 입력 9개 자료 묶음의 파일 해시와 새 산출물 해시를 검증한다. 최종 상태는 `verification.json`에 저장한다.
- 원본 데이터와 기존 봉인 실험은 변경하지 않았다. 새 자료에는 프로토콜·소스 사본·학습 기록·모델·경주/말별 예측·진단·불확실성 구간을 보존했다.

## 8. 다음 우선순위

1. **현재 HY_R_FORM 유지:** 새 집합 모델 두 개는 채택하지 않는다. 한 마리 입상 목표의 S_ADDITIVE는 불확실한 연구 후보로만 남긴다.
2. **경험과 불확실성 검증:** 다음에는 같은 거리 경험이 적거나 구간 이력이 없는 말의 예측 확률이 과도한지 전체 대상에서 확인한다. 이번 실패 사례만으로 경험 많은 말을 무조건 올리는 규칙을 만들지 않는다. 경험 구간과 판단 기준을 먼저 고정하고 보정·선정 효과를 분리한다.
3. **개발 평가와 실전 평가 분리:** 2025년 반복 개발에서의 추가 시도는 독립 검증이 아니다. 최종 후보·정보 시점·결측 정책을 잠근 후 미사용 기간과 실제 시점에 수집한 출마표로 확인한다.

현재 수치는 실제 출전마 집합에 대한 결과다. 취소 전 수요일 출마표 성능으로 해석할 수 없으며 과거 공개·수정 시각도 입증되지 않았다. 당일 실제 마체중·함수율이나 결과는 사전 입력으로 쓰지 않았다. 2026년 결과와 수집된 206두의 예측은 사용하지 않았다. 100% 근접 목표와 현재 성능의 차이를 그대로 보고한다.

## 산출물

- 계획: `docs/JEJU_NATIVE_SET_INTERACTION_PLAN_2026-09-16.md`
- 실험: `data/research/jeju_native_set_interaction_v8_20260916/`
- 진단: `missing_horse_pairs.parquet`, `missing_horse_diagnostic.json`, `set_transitions.json`
- 재현: `protocol.json`, `run_ledger.json`, `bundles/`, `reproduce/`, `manifest.json`, `verification.json`
- 재검증: `.venv/bin/python -m scripts.verify_jeju_set_interaction`

manifest는 자기 자신과 재검증 시 갱신되는 verification.json을 제외한 산출물의 SHA-256을 저장한다.
"""
    (OUT / "report.md").write_text(text)
    (ROOT / "docs/JEJU_NATIVE_SET_INTERACTION_REPORT_2026-09-16.md").write_text(text)


if __name__ == "__main__":
    main()
