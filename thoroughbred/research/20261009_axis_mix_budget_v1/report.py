"""Prepare a local research report and preserve the existing model selection."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(frame):
    def cell(v):
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    lines = [
        "| " + " | ".join(frame.columns) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    lines += [
        "| " + " | ".join(cell(v) for v in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def main():
    e.check()
    assert json.loads((e.OUT / "verification.json").read_text())["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    s = pd.read_csv(e.OUT / "summary.csv")
    a = s[s.scope.eq("all")].set_index("policy")
    diff = pd.read_csv(e.OUT / "paired_differences.csv")
    mixdiff = diff[diff.candidate.eq("in6_out6")].iloc[0]
    text = f"""# 축 포함·제외 동시 사용과 조합 수

2026-10-09. 선택된 더러브랫 연구 기준선 `month_gate_weight22`, 2024-01-05~2026-09-20 동일4,799경주 후향 비교다. 가장 이른 경주 날짜는 동결 입력의 실제 평가 날짜를 따른다. 운영 모델의 결과나 새 미사용 검증기간으로 해석하지 않는다. 모델/선택/운영을 변경하지 않았다.

## 질문에 대한 결과

축 포함6개와 원축 제외6개를 **모든 경주에 함께 쓰면12개, {int(a.loc["in6_out6", "hits"]):,}경주 적중({a.loc["in6_out6", "hit_rate"] * 100:.2f}%)**다. 기존 축 포함6개의 {a.loc["in6_out0", "hit_rate"] * 100:.2f}%보다 높지만 구매 조합 수가2배다. 같은12개 예산의 기존 전체확률 최고12개는 {a.loc["global12", "hit_rate"] * 100:.2f}%다. 포함6+제외6 대 전체12개 차이는 {mixdiff.delta * 100:+.3f}%p(날짜95% {mixdiff.ci_low * 100:+.3f}~{mixdiff.ci_high * 100:+.3f}%p)다.

**총6개를 유지하는 혼합과 각6개를 합친12개는 다른 비교다.** 결과를 보고 가장 높은 혼합비를 채택하지 않았다. 입력은 모두 이미 검토한 기간의 동결 예측이고 새 학습은 없다.

{table(s[s.scope.eq("all")])}

policy `inK_outL`은 축 포함K개+원축 제외L개다. 포함 후보는 기존과 같은 상위7두에서 원축을 포함한 조합, 제외 후보는 전 출전마에서 원축이 없는 조합이다. 각 집합 안에서 기존 공동확률 순으로 선택한다. `global6/12`는 포함 여부를 강제하지 않은 전체확률 최고6/12개다. `risk_add6`는 이전 context 위험 신호 때만 제외6개를 추가하며 평소6개, 고위험12개다. 항상 고정 조합 수인 정책과 비용이 다르다.

위험시 추가형의 적중은 {a.loc["risk_add6", "hit_rate"] * 100:.2f}%, 평균 {a.loc["risk_add6", "mean_tickets"]:.3f}개, 총 {int(a.loc["risk_add6", "total_tickets"]):,}조합이다. 조합당 동일금액이라는 가정의 총 노출만 비교한 것이며 배당/환급을 사용하지 않아 **수익률을 뜻하지 않는다.** hits_per_100_tickets도 단지 적중 경주 수÷전체 조합 수×100이며 배당 가중 수익이 아니다.

축 포함/제외 집합은 서로 겹치지 않으며 한 경주의 실제 삼복 정답은 한 집합에만 속한다. 따라서 두6개를 합친 적중수는 각각의 적중수 합과 같다. 축이 살아도 상대2두를 못 잡으면 놓치고, 축이 무너져도 제외 조합6개 안에 정답이 없으면 놓친다.

## 지금 무엇을 예측하는가

1. **기본 연구모델:** 각 말의 실제3위 이내 여부를 이진 목표로 학습한다. 보정기록·최근 프로필·부중 등22입력을 쓰는 LightGBM이며 현재 순위가 아니라 미래 입상 점수를 낸다. ‘모델1위’는 이 입상 점수가 가장 높은 말이다. 우승 확률1위 또는 실제1착 예측과 동의어가 아니다.
2. **삼복 조합 층:** 세 말의 원점수 합/전년도 보정 온도를 모든 가능한3두 집합에 대해 softmax하여 순서 없는 삼복 분포를 만든다. 개별 입상확률을 독립 곱한 값이 아니며, 세 말의 동반관계를 직접 학습한 조합 모형도 아니다. 말별 입상확률은 그 말이 포함된 모든 조합 확률의 합이다.
3. **축 붕괴 연구:** 원래 점수1위 말이3위 밖으로 밀릴지를 따로 학습한다. ‘선행 실패’, ‘1착 실패’와 다르다. 구간·각질·자기제외 상대 비교90개 입력의 context 위험 모형은 연구 후보이며 이번 검증의 축을 새로 선정하지 않는다. 이전 연구에서 기존 입상확률보다 추가 개선 근거를 확인하지 못했다.
4. **6개/12개 선택 규칙:** 위 확률로 어떤 조합을 고를지 정하는 단계다. 학습 목표와 구매/선택 규칙을 구분한다. 여기의 적중률은 **선택한 조합 안에 실제1·2·3착 말의 순서 없는 집합이 있었던 경주 비율**이다. 1개 말의 입상률, 우승률, 정확한 착순 예측률, 수익률과 다르다.

현재 실험은 원축과 붕괴 위험을 함께 고려한 예산 배분의 측정이다. 현재 경주의 실제 전개나 전술 의도를 확정적으로 예측하는 실험은 아니다.

## 연도별·같은 경주 차이

{table(s[s.scope != "all"])}

{table(diff)}

차이는 비율 단위다(0.01=1%p). 날짜 군집2,000회 paired bootstrap95% 구간이다. 여러 혼합비의 우열을 사후 선택하지 않으며 비용/배당을 포함한 최적 비율을 뜻하지 않는다.

## 검증·한계

4,799경주×11정책의 모든 조합을 별도 스칼라 구현으로 재구성했다. 원축 포함/제외 분리, 중복 없음, 6/12개 및 위험시 가변 예산, 기존1,204/1,228적중 재현, 날짜bootstrap 재계산, 원본/선택/운영 레지스트리 해시를 확인했다. 기수·조교사 입력/DB/제주 접근과 신규 학습은 없다. 원래 동결 입력의 당일 부담중량 PIT 검증 한계는 유지된다. [검증](outputs/verification.json).

[사전 계획](PLAN.md) · [전체 표](outputs/summary.csv) · [경주별 결과](outputs/race_metrics.parquet) · [선택 조합](outputs/tickets.parquet) · [차이/구간](outputs/paired_differences.csv) · [용량](outputs/artifact_inventory.json).
"""
    f = pd.read_parquet(e.OUT / "race_metrics.parquet")
    start = str(pd.to_datetime(f.race_date).min().date())
    text = text.replace("2024-01-05~2026-09-20", f"{start}~2026-09-20")
    (e.HERE / "README.md").write_text(text)
    pub = f"""# 게시 요약: 축 포함·제외 조합을 함께 쓰면

현재 더러브랫22입력 연구 기준선의4,799경주에서 축 포함6개+제외6개를 동시에 쓰면12개, 적중 {a.loc["in6_out6", "hit_rate"] * 100:.2f}%였다. 포함6개만의 {a.loc["in6_out0", "hit_rate"] * 100:.2f}%보다 높지만 비용은2배다. 같은12개 예산의 전체확률 최고12개는 {a.loc["global12", "hit_rate"] * 100:.2f}%다. 총6개 안에서의 혼합은 별도로 비교했다.

기본 모형은 말별3위 이내 입상 점수, 삼복 층은 순서 없는3두 집합 확률, 축 붕괴 모형은 원축의3위 밖 위험을 예측한다. 여기의 적중률은 선택 조합의 경주 적중률이며 우승률이나 수익률이 아니다. 후향 비교 결과로 모델/운영을 변경하지 않았다.

[전체 연구](README.md) · [검증](outputs/verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="descriptive_budget_comparison_not_selected",
            new_training=False,
            production_changed=False,
            selected_baseline_changed=False,
            jeju_access=False,
            database_access=False,
            warning="Retrospective reused cohort; budget expansion is not equal-budget prediction improvement.",
        ),
    )
    shared = [
        e.R / "README.md",
        e.R / "ARTIFACT_SIZE_LOG.md",
        e.R / "conclusions/README.md",
        e.R / "conclusions/SOURCES.md",
        e.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for path in shared:
        name = str(path.relative_to(e.ROOT))
        before[name] = dict(bytes=path.stat().st_size, sha256=e.sha(path))
        dest = e.OUT / "publication_before" / path.relative_to(e.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target = e.R / "conclusions/32_AXIS_MIX_BUDGET.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- axis_mix_budget_v1_20261009 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else "32_AXIS_MIX_BUDGET.md"
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[축 포함·제외 조합과 예산]({link}): 현재22입력4,799경주에서 포함6+제외6은12개로 {a.loc['in6_out6', 'hit_rate'] * 100:.2f}%, 전체확률12개는 {a.loc['global12', 'hit_rate'] * 100:.2f}%. 총6개 혼합과 구분하며 추가비용을 모델 개선으로 해석하지 않는다. 선택/운영 유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    add = (
        [e.HERE / n for n in ["PLAN.md", "README.md", "PUBLICATION.md"]]
        + [e.OUT / n for n in ["source_lock.json", "verification.json", "decision.json"]]
        + [target, shared[0], shared[2], shared[3]]
    )
    for path in add:
        name = str(path.relative_to(e.ROOT))
        manifest["sources"] = [r for r in manifest["sources"] if r["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(path), bytes=path.stat().st_size))
    e.save(shared[-1], manifest)
    e.save(
        e.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            races=4799,
            policies=11,
            website_deployed=False,
            production_changed=False,
            selected_baseline_changed=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()
