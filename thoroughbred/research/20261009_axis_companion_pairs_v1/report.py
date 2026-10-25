# ruff: noqa: E501
"""Publish verified retrospective findings without changing model selection."""

import json

import pandas as pd
import run as e

LABELS = {
    "fixed_axis_next4_all6": "기존 축+상대4두 전6조합",
    "sum_score_pool7_best6": "상대6두·기존 점수합6개",
    "score_pair_pool7": "상대6두·점수 기반 동반학습6개",
    "context_pair_pool7": "상대6두·구간/전개 동반학습6개",
    "sum_score_pool6_best6": "상대5두·기존 점수합6개",
    "score_pair_pool6": "상대5두·점수 기반 동반학습6개",
    "context_pair_pool6": "상대5두·구간/전개 동반학습6개",
}


def row(s, policy, scope="all", value="all"):
    return s[(s.scope == scope) & (s.value.astype(str) == str(value)) & (s.policy == policy)].iloc[
        0
    ]


def main():
    e.check()
    assert json.loads((e.OUT / "final_verification.json").read_text())["passed"]
    s = pd.read_csv(e.OUT / "summary.csv")
    d = pd.read_csv(e.OUT / "paired_differences.csv")
    c = pd.read_csv(e.OUT / "capture.csv")
    prepared = json.loads((e.OUT / "prepared.json").read_text())
    base = row(s, "fixed_axis_next4_all6")
    context = row(s, "context_pair_pool7")
    points = d[(d.scope == "all") & (d.policy == "context_pair_pool7")]
    primary = points[
        (points.baseline == "fixed_axis_next4_all6") & (points.metric == "six_hit")
    ].iloc[0]
    matched = points[
        (points.baseline == "sum_score_pool7_best6") & (points.metric == "six_hit")
    ].iloc[0]
    loss = points[
        (points.baseline == "fixed_axis_next4_all6") & (points.metric == "conditional_nll")
    ].iloc[0]
    year_ok = all(
        row(s, "context_pair_pool7", "year", y).six_hit
        >= row(s, "fixed_axis_next4_all6", "year", y).six_hit
        for y in [2024, 2025, 2026]
    )
    promising = bool(primary.lo > 0 and matched.lo > 0 and loss.hi < 0 and year_ok)
    decision = dict(
        species=e.SPECIES,
        status="promising_research_bundle_not_promoted"
        if promising
        else "improvement_not_established_not_promoted",
        primary_hit_difference=dict(delta=primary.delta, lo=primary.lo, hi=primary.hi),
        same_pool_difference=dict(delta=matched.delta, lo=matched.lo, hi=matched.hi),
        conditional_nll_difference=dict(delta=loss.delta, lo=loss.lo, hi=loss.hi),
        no_year_point_decline=year_ok,
        selection_changed=False,
        operating_changed=False,
        independent_future_test=False,
    )
    e.save(e.OUT / "decision.json", decision)
    cap = c[(c.scope == "all") & (c.policy == "context_pair_pool7")].iloc[0]
    name = "더러브랫" if e.SPECIES == "thoroughbred" else "제주"
    chosen_base = (
        "53개 입력 연구 후보" if e.SPECIES == "thoroughbred" else "R1 21개 입력 연구 기준선"
    )
    status = (
        "후속 검증이 필요한 유망 연구 묶음이다. 운영 승격은 하지 않는다."
        if promising
        else "동반 학습의 추가 개선을 확정하지 못했다. 기존 선택 기준과 운영 모델을 유지한다."
    )
    table = "|방식|경주|축 입상|축 입상 시 상대2두 포착|전체6조합 적중|적중 수|\n|---|---:|---:|---:|---:|---:|\n"
    for policy in LABELS:
        z = row(s, policy)
        table += f"|{LABELS[policy]}|{int(z.races):,}|{z.axis_rate:.2%}|{z.companion_given_axis:.2%}|{z.six_hit:.2%}|{int(z.hits):,}|\n"
    years = "|연도|경주|기존4두6개|확대 점수합6개|구간/전개 동반6개|\n|---|---:|---:|---:|---:|\n"
    for y in [2024, 2025, 2026]:
        z = row(s, "fixed_axis_next4_all6", "year", y)
        a = row(s, "sum_score_pool7_best6", "year", y)
        b = row(s, "context_pair_pool7", "year", y)
        years += f"|{y}|{int(z.races)}|{z.six_hit:.2%}|{a.six_hit:.2%}|{b.six_hit:.2%}|\n"
    intervals = "|대조|지표|차이|경주일95%구간|\n|---|---|---:|---:|\n"
    for z in points.itertuples():
        factor = 100 if z.metric in ["six_hit", "companion_given_axis"] else 1
        unit = "%p" if factor == 100 else ""
        intervals += f"|{LABELS[z.baseline]}|{z.metric}|{z.delta * factor:+.4f}{unit}|[{z.lo * factor:+.4f}, {z.hi * factor:+.4f}]{unit}|\n"
    reference = ""
    if e.SPECIES == "jeju":
        old = pd.read_csv(
            e.ROOT / "jeju/research/20261009_operating_model_comparison_v1/outputs/race_metrics.csv"
        )
        r = pd.read_csv(e.OUT / "race_metrics.csv")
        common = set(old.race_id)
        aligned = []
        for policy in ["fixed_axis_next4_all6", "sum_score_pool7_best6", "context_pair_pool7"]:
            q = r[(r.rid.isin(common)) & (r.policy == policy)]
            assert len(q) == len(common) == 467
            aligned.append(
                dict(
                    method=policy,
                    races=len(q),
                    hits=int(q.six_hit.sum()),
                    hit_rate=float(q.six_hit.mean()),
                )
            )
        hy = old[old.variant == "HY_R_FORM"]
        aligned.append(
            dict(
                method="HY_R_FORM_original_joint_best6",
                races=len(hy),
                hits=int(hy.six_combo_hit.sum()),
                hit_rate=float(hy.six_combo_hit.mean()),
            )
        )
        pd.DataFrame(aligned).to_csv(e.OUT / "operating_reference_matched.csv", index=False)
        reference = f"""## 운영 모델과 구분

같은467경주에서 새 동반6조합은{aligned[2]["hit_rate"]:.2%}({aligned[2]["hits"]}/467), 운영 HY_R_FORM의 원래 집합분포 상위6조합은{aligned[3]["hit_rate"]:.2%}({aligned[3]["hits"]}/467)다. 새 모델이 운영을 넘었다는 결과가 아니다. 연구 축을 고정한 인과적 구성요소 비교는 위 R1 내부 비교이며, 운영 참조는 축·입력·학습기간·조합 선정이 다른 완성 방식 비교다. 운영에 조건부 모델을 직접 붙인 실험도 아니다. [공통 경주 참조](outputs/operating_reference_matched.csv).

"""
    tickets = pd.read_parquet(e.OUT / "six_tickets.parquet")
    runners = pd.read_parquet(e.OUT / "oof_runners.parquet")
    last = runners[runners.year == 2026].copy()
    last["race_no"] = (
        last.rid.str.rsplit(":" if e.SPECIES == "thoroughbred" else "_", n=1).str[-1].astype(int)
    )
    rid = last.sort_values(["race_date", "meet", "race_no"]).rid.iloc[-1]
    example = tickets[
        (tickets.rid == rid)
        & tickets.policy.isin(
            ["fixed_axis_next4_all6", "sum_score_pool7_best6", "context_pair_pool7"]
        )
    ].copy()
    example.to_csv(e.OUT / "example_six_tickets.csv", index=False)
    example_text = "\n".join(
        f"- {LABELS[p]}: "
        + ", ".join(f"{int(z.axis)}-{int(z.first)}-{int(z.second)}" for z in g.itertuples())
        for p, g in example.groupby("policy")
    )
    counts = (
        "기본 OOF 새8개+동반6개=최종모형14개"
        if e.SPECIES == "thoroughbred"
        else "기본 OOF 새4개+동반6개=최종모형10개"
    )
    text = f"""# {name} 축 고정·조건부 동반 두 마리 학습

2026-10-09 완료. **{status}** 기준 축은 {chosen_base}의 점수1위로 고정했다. 새 결과는 현재 운영 모델의 실제 게시 성적이 아니다. 이미 반복 사용한2024~2026 기간의 후향 개발 비교다.

## 전체 결과

{table}
주 비교는 상대6두(기존 순위2~7위)의15쌍 중6개다. 상대5두의10쌍 중6개는 사전 고정 보조 비교다. 모든 방식에서 축과 경주·구매6개가 같다. 축 입상 {int(base.axis_places):,}/{int(base.races):,}경주이며 이 분모에서만 상대 포착률을 계산한다. 전체 적중에는 축 탈락 경주도 포함한다.

구간/전개 동반 방식은 기존6개 대비 새로 {int(cap.newly_hit)}경주를 맞히고 이전에 맞힌 {int(cap.lost_hit)}경주를 놓쳐 순 {int(context.hits - base.hits):+}경주다. 후보6두 안에 실제 상대 두 마리가 있어 어떤6개를 골라도 적중 가능성이 있었던 경주의 전체 비율은 {context.pool_ceiling:.2%}이며, 이 값은15조합을 모두 샀을 때의 관측 상한으로 실제6조합 성능과 다르다.

## 차이와 연도별 재현

{intervals}
{years}
경주일2000회 대응 bootstrap·점별95%구간이다. 상대 포착 구간은 축이 실제 입상한 경주일만 사용한다. 두 후보·두 후보군·여러 지표를 비교한 탐색이며 다중검정 조정된 확증 결과가 아니다. 모든 거리·등급·지역별 표본과 점추정은 [전체 표](outputs/summary.csv)에 보존하고 작은 셀에서 최고 정책을 선택하지 않았다.

## 무엇을 학습했나

- 기본 점수·축 선정 방식은 그대로 두었다. 새 학습 target은 `P(상대 두 마리가 나머지 Top3 | 선택한 축이 Top3, 사전 편성)`이다. 각 말의 주변확률을 단순 곱한 값이 아니다.
- score_pair는 기존 점수·순위·축 확률·거리·등급·두수·지역14열이다. context_pair는 같은14열에 과거 기록·초반·종반·성향·지원량의 축 값과 두 상대의 대칭 min/max/차이·관측수 및 원래 마번·선행관계16열을 더한 {prepared["inputs"]["context_pair"]}열이다. 실제 두 상대의 순서를 바꿔도 값과 확률은 같다.
- 더러브랫 G3F/G1F는 이전 연구의 과거 연도별 주로·월·게이트 보정 초값(미지원 원기록)이다. 제주 G3F/G1F는 과거 같은 경주 상대 시간 순위분율의 최근10회 평균이며 초 단위 기록·전체 통과착순과 다르다. 제주 첫 집단은 단독 선행이나 우승을 뜻하지 않는다.
- 이번 실제 출발·통과조·구간시간·착순·현재 이름/2026고정나이는 입력하지 않았다. 기수·조교사도 이번 후보에 추가하지 않았다. 마번은 물리적 주행 경로나 확정 내외측 손실이 아니다.
- context_pair와 기존 방식의 차이는 **조건부 조합 학습+구간/전개 관계 입력 묶음**이다. score_pair 대조는 학습 구조만 바꿨을 때의 참고이며 context 개선을 조건부 구조 하나의 순수 효과로 분리하지 않는다.

## 시간순 계약과 확률

기본 말 모형은 정답2017+에서 초기학습2017..Y−3, 종료선택Y−2, 재학습~Y−2, 온도Y−1, 예측Y다. 2020~2023년 OOF를 새 생성하고2024~2026 점수는 기존 모형·저장 점수와 일치시켰다. 과거 결과를 알고 축을 고르거나 최신 모형으로 과거 학습 점수를 만들지 않았다.

동반 학습은 깨끗한 기본 OOF가 있는2020년부터 시작한다. 초기학습2020..Y−3, 종료선택Y−2, 재학습~Y−2, 조건부 온도Y−1, 평가Y다. 과거 선택 축이 실제 입상한 경주만 조건부 학습에 쓰고, 각 경주에서 나머지 모든 쌍 가운데 정답 한 쌍을 학습한다. 쌍별 가중치1/쌍수로 경주별 학습 비중을 맞춘 binary LightGBM이다. 설정은 [사전 계약](PLAN.md)·[config](config.json)에 고정했으며 출력별 초기/최종 재학습을 포함해 {counts}를 새 보관했다.

전체 남은 쌍에서 softmax로 정규화하고 보정연도 조건부 정답 NLL로 온도를 결정한다. 후보군 밖 쌍도 확률 분모에 포함한다. 선택6개 조건부 확률 합×기존 축Top3 확률이 무조건부 축 포함6조합 확률이다. 이 분해는 독립성 가정이 아니지만 기초 축 확률 오차도 함께 물려받는다. 축이 탈락하는 나머지 경우의 전체 착순 공동분포나 모든 말의 새 우승/Top2/Top3 출력은 이번 범위가 아니다. [6조합 확률 구간 실제빈도](outputs/six_ticket_calibration.csv).

{reference}## 실제 과거 편성 예시

결과로 고르지 않고2026년 자료 최종일·지역·경주번호 순서의 마지막 편성 `{rid}`를 표시했다. 과거 경주 재현 예시이며 새 실시간 추천이 아니다.

{example_text}

[확률·적중 포함 예시 표](outputs/example_six_tickets.csv). 축은 동일하고 상대 조합만 달라진다.

## 검증·한계와 결정

전 쌍 입력 재계산·현재 정답 제거/교란·행 순서 변경·상대 대칭성·T−2 이력·기본 및 동반 모형 전 재로딩·온도·확률합·6개 조합·실제 정답을 독립 재계산했다. 이전 원천·모형·등록부 SHA는 그대로다. [검증](outputs/final_verification.json),[입력 감사](outputs/input_audit.json),[출처 동결](outputs/source_lock.json),[결정](outputs/decision.json).

이전 코호트와 보유 피처를 그대로 쓴 분석이므로 최초 출마표 공개·취소·정정 시점의 완전한 재현은 아니다. 과거 지원 부족·결측·거리별 표본차이, 같은 기간의 반복 개발, 기본 모형의 연도별 변화가 남는다. 초반/종반 입력은 관측된 과거 요약이며 이번 경주의 물리적 선행 유지·추월을 확정하는 시뮬레이션이 아니다. 작은 연도·거리 셀의 불확실성은 전체 성능으로 덮지 않는다.

{status} 더러브랫 선택 month_gate_weight22 및 제주 운영 HY_R_FORM은 변경하지 않았다. 두 종의 자료와 축·기준선이 달라 이 표로 종별 난도를 직접 비교하지 않는다. 웹·DB·새 외부자료 수집·수익률 검증은 이번 작업에 포함하지 않았다.
"""
    (e.HERE / "README.md").write_text(text)
    (e.HERE / "FEATURES.md").write_text(
        "# 입력 사전\n\n"
        + "\n".join(
            f"- `{v}`: {len(cols)}열\n" + "\n".join(f"  - `{c}`" for c in cols)
            for v, cols in json.loads((e.OUT / "feature_contract.json").read_text()).items()
        )
        + "\n\naxis_는 고정 축의 과거 값, pair_min/max는 상대 두 마리 양쪽 값이 있을 때의 min/max다. pair_known은 유효값 수0/1/2이며 결측을 느린 말로 해석하지 않는다. pair_mean_minus_axis는 두 상대 평균에서 축 값을 뺀 차이다. 구간별 단위와 방향은 README.md를 따른다.\n"
    )
    (e.HERE / "PUBLICATION.md").write_text(
        f"# {name} 축과 상대마를 따로 평가하기\n\n{status}\n\n같은 축·6조합에서 기존 {base.six_hit:.2%} → 구간/전개 동반 {context.six_hit:.2%}였다. 축이 맞아도 상대 두 마리를 놓치는 문제를 따로 학습했다. 과거 기록과 상대 관계를 함께 넣은 연구 묶음이며 운영 변경이나 수익 개선 결과는 아니다. 예시는 README.md의 최종일 과거 편성을 따른다.\n\n이미 사용한2024~2026 자료의 후향 결과로, 새로운 미래 기간 확인이 필요하다.\n"
    )
    print(name, status, "hit", context.six_hit, "delta", primary.delta, flush=True)


if __name__ == "__main__":
    main()
