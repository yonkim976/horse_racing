"""Local pair/trio research report with explicit target and budget definitions."""

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
    a = s[s.scope.eq("all")]
    compact = a.pivot(index="bet", columns="policy", values="hit_rate") * 100
    compact = compact[["in3_out3", "in2_out1", "in3_out0", "global3", "global6"]].reset_index()
    text = f"""# 복승·복연·삼복 조합 수와 축 포함·제외

2026-10-09. 현재 더러브랫22입력 연구 기준, 동결2024-01-05~2026-09-20 동일4,799경주다. 신규 학습/운영/선택 변경은 없다.

## 조합의 의미

지금까지6조합은 삼복승의 서로 다른3두 묶음6개였다. 예: (1,3,7)이 한 조합이다. 복승과 복연승은 (1,3) 같은2두 묶음이 한 조합이다. 축 포함3개+축 제외3개는 조합3개씩 총6개다. 총3개로 줄이는 경우는 포함2개+제외1개 또는 포함3개 등으로 별도 계산했다. 말3두를 고른다는 뜻과 다르다.

## 동일 경주 적중률(%)

{table(compact)}

in3_out3은 총6조합, in2_out1/in3_out0/global3은 총3조합, global6은 총6조합이다. global은 축 포함/제외 수를 강제하지 않고 해당 승식의 추정확률순으로 선택한 규칙이다. 표는 모든 경주에 같은 규칙을 적용한 관측 적중률이다.

복승(quinella)은 실제1·2착 말의 순서 없는 집합, 복연(quinella_place)은 실제3위 이내 두 마리, 삼복(trio)은 실제3위 이내 세 마리 전체를 맞힌다. 적중률은 선택 조합 중 **하나 이상** 맞은 경주 수÷전체경주 수다. 복연은 한 경주에 실제 정답2두조합이3개 있으므로 여러 조합이 동시에 맞을 수 있다. winning_tickets는 실제 맞은 조합 수이며 경주 적중수와 구분한다. 적중률 크기만으로 승식의 수익 우열을 판단할 수 없고 배당·환급·수익률은 계산하지 않았다.

{table(a)}

## 무엇으로 계산했는가

원축은 기존 month_gate_weight22 Top3 점수1위 말로 모든 승식에 통일했다. 복승용 Top2 모형 점수1위로 축을 교체한 실험이 아니다. 따라서 각 승식의 최적 축/최적 배분을 검증했다는 주장이 아니다.

삼복은 기존22입력 Top3 모형의 조합 분포다. 복연 점수는 같은 분포에서 두 말이 함께 들어간 모든3두조합 확률의 합이다. 한 경주 전체 복연2두조합 확률을 합하면3이며, 각 복연 조합이 독립적이거나 합이1인 배타적 사건이라고 취급하지 않았다. 전체확률순 선택은 개별 조합 확률의 순서일 뿐, 하나 이상 맞힐 확률을 직접 최적화한 집합 선택은 아니다. 겹치는 복연 조합의 분산/동반적중 최적화는 다음 별도 가설이다.

복승은 같은22입력의 기존 `baseline22 target2` 연구모형6개를 재사용했다. 2017년부터 학습, 평가연도Y−2까지 학습, Y−1로2두집합 softmax 온도보정, Y년 평가한 모형이다. 현재 선택된 Top3 모형 자체가 복승 확률까지 내고 있다고 표현하지 않는다. Top3 점수에서1·2위 확률을 임의로 추론하지 않았다.

삼복 축포함 후보는 이전 연구와 같은 상위7두 안으로 제한했고 복승/복연 축포함 후보는 모든 상대마를 사용했다. 제외 후보는 전 출전마 중 원축 없는 조합이다. 현재 경주 실제결과로 후보를 제한하지 않았다. 6두 경주2개는 축 포함2두조합이5개뿐이므로 포함6개 비교 대신 포함3개와 혼합3+3을 비교했다.

## 연도별 결과

{table(s[s.scope != "all"])}

## 검증과 한계

복승 Top2 모델6개 재예측, 전체 경주/정답/조합 확률 별도 전수열거, 예산3/6개, 복연 확률합3·한 경주최대3개 당첨, 복승/삼복최대1개당첨, 기존 삼복3+3의1,026적중과global6의1,228적중 재현을 확인했다. 원본·모형·선택·운영 레지스트리 해시는 유지했다. [검증](outputs/verification.json).

이미 검토한2024–2026년 기간의 후향 비교이며 새 독립 기간이 아니다. 당일 부담중량의 원천 PIT 검증 미완료 한계도 유지한다. 표에서 가장 높은 규칙을 새 운영으로 선택하지 않았다. 제주/DB/네트워크 접근과 신규 학습은 없다.

[사전 계획](PLAN.md) · [전체 결과](outputs/summary.csv) · [경주별 결과](outputs/race_metrics.parquet) · [선택 조합](outputs/tickets.parquet) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(text)
    q = compact.set_index("bet")
    pub = f"""# 게시 요약: 복승·복연·삼복의 조합 수

6조합은 삼복3두묶음6개이며 복승/복연은2두묶음이 한 조합이다. 원축 포함3개+제외3개는 총6개로, 동일4,799경주의 복승 {q.loc["quinella", "in3_out3"]:.2f}%, 복연 {q.loc["quinella_place", "in3_out3"]:.2f}%, 삼복 {q.loc["trio", "in3_out3"]:.2f}%였다. 총3개인 포함2+제외1은 각각 {q.loc["quinella", "in2_out1"]:.2f}%, {q.loc["quinella_place", "in2_out1"]:.2f}%, {q.loc["trio", "in2_out1"]:.2f}%다.

복승은 기존22입력 Top2 연구모형, 복연/삼복은 기존 Top3 분포를 사용했고 원축은 기존 Top3 점수1위로 통일했다. 복연은 동시에 여러 조합이 맞을 수 있어 경주 적중률과 당첨조합 수를 구분한다. 승식별 적중 조건·기본 난이도·배당이 달라 수익률 비교가 아니다. 후향 평가이며 선택/운영 변경은 없다.

[전체 연구](README.md) · [검증](outputs/verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="descriptive_budget_comparison_not_selected",
            production_changed=False,
            selected_baseline_changed=False,
            new_training=False,
            database_access=False,
            jeju_access=False,
            axis="original Top3 score leader shared across bet types",
            returns_evaluated=False,
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
    target = e.R / "conclusions/33_PAIR_TRIO_BUDGET.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- pair_trio_budget_v1_20261009 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else "33_PAIR_TRIO_BUDGET.md"
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[복승·복연·삼복의 조합 수]({link}): 원축 포함3+제외3의 총6개에서 복승 {q.loc['quinella', 'in3_out3']:.2f}%, 복연 {q.loc['quinella_place', 'in3_out3']:.2f}%, 삼복 {q.loc['trio', 'in3_out3']:.2f}%. 총3개 예산을 구분하며 수익률 비교/운영 승격이 아니다.\n"
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
            bets=3,
            policies_per_bet=5,
            website_deployed=False,
            new_training=False,
            production_changed=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()
