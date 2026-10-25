"""Publish a reproducible retrospective result without promoting any model."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(frame):
    def cell(value):
        if pd.isna(value):
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    rows = [
        "| " + " | ".join(map(str, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    rows.extend(
        "| " + " | ".join(cell(v) for v in values) + " |"
        for values in frame.itertuples(index=False, name=None)
    )
    return "\n".join(rows)


def main():
    e.check()
    verification = json.loads((e.OUT / "verification.json").read_text())
    assert verification["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    p = pd.read_parquet(e.OUT / "risk_predictions.parquet")
    m = pd.read_csv(e.OUT / "race_metrics.csv")
    summary = pd.read_csv(e.OUT / "summary.csv")
    quality = pd.read_csv(e.OUT / "risk_quality.csv")
    flags = pd.read_csv(e.OUT / "risk_flags.csv")
    differences = pd.read_csv(e.OUT / "paired_differences.csv")
    contract = json.loads((e.OUT / "feature_contract.json").read_text())
    base = m[m.policy.eq("fixed7")].set_index("race_key")
    free = m[m.policy.eq("global6")].set_index("race_key")
    costs, events, gains = [], [], []
    for variant, g in p.groupby("variant"):
        g = g.set_index("race_key").loc[base.index]
        for action in ["trigger_free", "trigger_exclude", "reweight"]:
            policy = variant + "_" + action
            candidate = m[m.policy.eq(policy)].set_index("race_key").loc[base.index]
            d = candidate.hit - base.hit
            for collapse in [0, 1]:
                sel = g.collapsed.eq(collapse)
                costs.append(
                    dict(
                        variant=variant,
                        action=action,
                        collapsed=collapse,
                        races=int(sel.sum()),
                        flagged=int((g.flag & sel).sum()),
                        rescued=int(((d == 1) & sel).sum()),
                        lost=int(((d == -1) & sel).sum()),
                        candidate_hits=int(candidate.loc[sel, "hit"].sum()),
                        baseline_hits=int(base.loc[sel, "hit"].sum()),
                    )
                )
            for rid in g.index:
                events.append(
                    dict(
                        race_key=rid,
                        variant=variant,
                        action=action,
                        axis_number=int(g.loc[rid, "axis_number"]),
                        collapsed=int(g.loc[rid, "collapsed"]),
                        risk=float(g.loc[rid, "risk"]),
                        flag=bool(g.loc[rid, "flag"]),
                        baseline_hit=int(base.loc[rid, "hit"]),
                        free_hit=int(free.loc[rid, "hit"]),
                        candidate_hit=int(candidate.loc[rid, "hit"]),
                        delta=int(d.loc[rid]),
                    )
                )
    for path in sorted((e.OUT / "risk_models").glob("*/metadata.json")):
        meta = json.loads(path.read_text())
        variant = path.parent.name.rsplit("_", 1)[0]
        for feature, gain in meta["gain"].items():
            gains.append(
                dict(variant=variant, year=meta["evaluation_year"], feature=feature, gain=gain)
            )
    costs = pd.DataFrame(costs)
    costs.to_csv(e.OUT / "action_costs.csv", index=False)
    pd.DataFrame(events).to_parquet(e.OUT / "action_events.parquet", index=False)
    gains = pd.DataFrame(gains)
    gains.to_csv(e.OUT / "risk_feature_gains.csv", index=False)
    primary = differences[
        (differences.scope.eq("all"))
        & differences.candidate.eq("context_reweight")
        & differences.control.eq("global6")
    ].iloc[0]
    brier = differences[
        (differences.scope.eq("all"))
        & differences.candidate.eq("context")
        & differences.control.eq("base_raw")
        & differences.metric.eq("brier")
    ].iloc[0]
    decision = dict(
        status="retrospective_research_only_not_selected",
        conclusion="No added collapse-prediction benefit established; forced exclusion worsened hits",
        base=e.CFG["base"],
        primary_policy="context_reweight",
        control="global6",
        hit_delta=float(primary.difference),
        hit_ci=[float(primary.ci_low), float(primary.ci_high)],
        brier_delta=float(brier.difference),
        brier_ci=[float(brier.ci_low), float(brier.ci_high)],
        production_changed=False,
        selected_baseline_changed=False,
        jeju_access=False,
        independent_future_evaluation_required=True,
    )
    e.save(e.OUT / "decision.json", decision)
    all_summary = summary[summary.scope.eq("all")].copy()
    all_summary["hit_percent"] = all_summary.hit_rate * 100
    all_quality = quality[quality.scope.eq("all")]
    all_flags = flags[flags.scope.eq("all")]
    selected_diff = differences[differences.scope.eq("all")]
    top = (
        gains[gains.variant.eq("context")]
        .groupby("feature")
        .gain.sum()
        .sort_values(ascending=False)
        .head(12)
        .reset_index()
    )
    text = f"""# 축 붕괴 사전 예측 — 더러브랫 연구

2026-10-09 완료. **과거 구간·각질·상대 비교를 더한 붕괴 학습의 추가 개선 근거를 확인하지 못했다. 고위험이라고 원축을 제외한 정책은 적중이 감소했다.** 축은 현재 선택 연구모델 `month_gate_weight22` 점수 1위 말이며 붕괴는 **실제 3위 밖**이다. 전개상 선행 실패와 다르다. 운영 모델의 축을 직접 예측한 실험은 아니다.

2024–2026년 동일 **4,799경주**, 원축 붕괴 **1,937경주(40.36%)**다. 새 위험 학습의 주 정책은 기존 축자유6개 대비 **{primary.difference * 100:+.3f}%p**, 날짜 군집95% 구간 **{primary.ci_low * 100:+.3f}~{primary.ci_high * 100:+.3f}%p**다. 위험 Brier 차이는 **{brier.difference:+.6f}**(작을수록 좋음, 구간 {brier.ci_low:+.6f}~{brier.ci_high:+.6f})다. 두 지표를 구분하여 판단한다.

## 위험을 어떻게 예측했는가

기본 모델22개의 학습은 2017년부터이며 이전 자료는 기존 이력 구축에만 쓰인 동결 입력을 재사용했다. 2020–2023년 축을 만드는 기본 모형8개는 각 평가연도 Y−2까지 학습, Y−1 삼복분포 온도보정으로 별도 생성했다. 2024–2026년 기본 모형6개는 원본과 점수가 완전히 일치한다.

위험 모형은 2020–Y−3 학습, Y−2 조기종료, Y−2까지 재학습, Y−1 Platt 확률보정, Y년 평가했다. 각 과거 학습 축도 해당 경주 이후 자료를 보지 않은 OOF 축이다. `base_raw`는 기존 공동분포의 1−축입상확률, `base_cal`은 이것만 전년도 확률보정, `score`는 점수 차이·분산·집중도 {len(contract["score"])}개, `context`는 이 점수 변수와 축의 보정기록·부중·구간·각질 및 자기 제외 상대 비교 등 {len(contract["context"])}개다. 기수/조교사와 현재 결과·현재 구간·현재 통과조는 입력하지 않았다. 현재 마번과 상대 게이트 위치는 사전 대리변수이며 실제 주행경로가 아니다.

과거 S1F/G3F/G1F 기록과 통과조 성향은 기존53개 이력 계약 그대로 사용했다. 새 경주의 선행/추입을 확정한 값이 아니며, 알려지지 않은 현재 전술 의도를 관측한 것도 아니다. 원본 전체/구간 보정은 이번에 재추정하지 않았다.

{table(all_quality[["variant", "races", "actual_risk", "mean_risk", "auc", "brier", "logloss"]])}

AUC는 0.5가 무작위 구분, Brier/logloss는 작을수록 좋다. 확률의 평균이 맞는 것과 개별 붕괴를 잘 찾아내는 것은 다르다.

## 위험 신호의 정확도

위험 신호 문턱은 각 전년도 보정 예측의70백분위다. 평가연도 결과를 보고 상위30%를 골라낸 것이 아니므로 실제 선택 비율은30%와 다를 수 있다. precision은 신호를 보낸 경주 중 실제 붕괴 비율, recall은 전체 붕괴 중 포착 비율이다. 낮은 위험에서도 붕괴는 남는다.

{table(all_flags[["variant", "races", "flagged", "coverage", "predicted_risk", "collapse_precision", "collapse_recall"]])}

전체 위험 구간별 실제 붕괴율은 [risk_bins.csv](outputs/risk_bins.csv)에 있다.

## 같은6조합으로 연결한 결과

`fixed7`: 원축+상대6두에서 최고6개. `global6`: 원축 강제 없이 전 출전마의 기존 공동확률 최고6개. `trigger_free`: 고위험 때만 global6. `trigger_exclude`: 고위험 때만 원축이 없는 조합6개. `reweight`: 모든 경주에서 축포함 조합의 합을1−새 붕괴확률로, 미포함 조합의 합을 새 붕괴확률로 맞춘 뒤 최고6개. 재배분은 각 집합 안의 상대 확률은 유지하므로 새로운 동반관계를 학습한 것은 아니다. 모든 정책은 경주당 정확히6개다.

{table(all_summary[["policy", "races", "hits", "hit_percent"]])}

{table(selected_diff[["candidate", "control", "metric", "difference", "ci_low", "ci_high", "rescued", "lost"]])}

조합 차이는 비율 단위다(0.01=1%p). CI는 날짜를 단위로2,000회 paired bootstrap한95% 구간이며 여러 후보/하위군에 대한 다중비교 보정은 없다. 주 비교는 미리 고정했다. 가장 좋아 보이는 정책을 선택/승격하지 않았다.

## 구조한 경주와 잘못 버린 경주

아래는 fixed7 대비 변화이며 실제 붕괴 여부는 **사후 진단용**이다. 정책 선택에 실제 붕괴 여부를 넣지 않았다. collapsed=0에서 잃은 적중은 원축이 살아왔는데 위험 판단/조합변경으로 놓친 비용이다. collapsed=1에서 구조한 경주는 실제 축 붕괴를 살린 적중이다.

{table(costs)}

모든 경주의 변경 기록을 [action_events.parquet](outputs/action_events.parquet), 전체6조합을 [six_tickets.parquet](outputs/six_tickets.parquet)에 보존했다. 성공 사례만 골라 제시하지 않았다.

## 연도·지역과 변수 사용

{table(summary[(summary.scope != "all") & summary.policy.isin(["fixed7", "global6", "context_trigger_free", "context_trigger_exclude", "context_reweight"])])}

context 모델이 분할에 사용한 gain 상위 변수(연도별 합)는 아래와 같다. 원인·영향방향·인과효과를 뜻하지 않으며 대체 입력과 중복될 수 있다.

{table(top)}

## 검증과 적용 범위

기본 모형14개/새 위험 모형6개 재예측, 전년도 보정·문턱, {verification["race_policies_enumerated"]:,} 경주-정책/{verification["tickets_verified"]:,}조합 전수 독립 재구성, 결과 변조 불변성, 기준선1,204/1,228적중 재현, 원본 해시 보존을 통과했다. [검증](outputs/verification.json).

이미 여러 연구에서 본2024–2026년을 재사용한 후향 평가다. 전후 학습 누수 방지는 새 미사용 검증기간을 대신하지 못한다. 원천의 당일 부담중량 PIT 검증 미완료 한계도 그대로다. 위험 구분의 개선과6조합 적중 개선, 수익률 개선은 각각 다른 주장이다. 배당/수익률은 이번에 검증하지 않았다. `month_gate_weight22` 선택과 운영 레지스트리는 유지했고 제주·DB에 접근하지 않았다.

[사전 계획](PLAN.md) · [입력 계약](outputs/feature_contract.json) · [연도/지역 결과](outputs/summary.csv) · [paired 차이](outputs/paired_differences.csv) · [판정](outputs/decision.json) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(text)
    publication = f"""# 게시용 요약: 축 붕괴 예측

추가 붕괴 학습의 개선 근거를 확인하지 못했고, 원축 강제 제외는 적중이 줄었다. 기존 점수1위 말이3위 밖으로 밀릴 위험을 따로 학습했다. 현재 선택된 더러브랫22입력 연구 기준으로2024–2026년4,799경주의 원축 붕괴는40.36%였다. 과거 구간·각질·상대 비교를 더한 위험확률로 공동 삼복분포를 재배분했을 때 기존 축자유6개 대비 {primary.difference * 100:+.2f}%p(날짜95% {primary.ci_low * 100:+.2f}~{primary.ci_high * 100:+.2f}%p)였다.

위험 신호를 받았다는 이유만으로 원축을 제외하는 것에는 오판 비용이 있다. 위험 예측 정확도와 조합 적중을 함께 판단해야 한다. 같은6개 예산의 전체 결과와 구조/손실 경주를 원 보고서에서 확인할 수 있다. 새 미사용 기간의 검증 전이며 운영/선택 모델에는 반영하지 않았다.

[전체 연구](README.md) · [검증](outputs/verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(publication)
    shared = [
        e.R / "README.md",
        e.R / "ARTIFACT_SIZE_LOG.md",
        e.R / "conclusions/README.md",
        e.R / "conclusions/SOURCES.md",
        e.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for pth in shared:
        name = str(pth.relative_to(e.ROOT))
        before[name] = dict(bytes=pth.stat().st_size, sha256=e.sha(pth))
        dest = e.OUT / "publication_before" / pth.relative_to(e.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pth.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target = e.R / "conclusions/31_AXIS_COLLAPSE.md"
    assert not target.exists()
    target.write_text(
        publication.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- axis_collapse_v1_20261009 -->"
    for pth in shared[:4]:
        if pth.name == "ARTIFACT_SIZE_LOG.md":
            continue
        link = f"{e.HERE.name}/README.md" if pth.parent == e.R else "31_AXIS_COLLAPSE.md"
        with pth.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[축 붕괴 사전 예측]({link}): 현재22개 기준4,799경주에서 위험 학습과 고정 해제·원축 제외·공동확률 재배분을 비교했다. context 재배분은 축자유6개 대비 {primary.difference * 100:+.2f}%p(95% {primary.ci_low * 100:+.2f}~{primary.ci_high * 100:+.2f}%p). 새 미사용 기간 검증 전, 선택/운영 유지.\n"
            )
    manifest_path = shared[-1]
    manifest = json.loads(manifest_path.read_text())
    add = [e.HERE / n for n in ["README.md", "PLAN.md", "config.json", "PUBLICATION.md"]]
    add += [e.OUT / n for n in ["source_lock.json", "verification.json", "decision.json"]]
    add += [target, shared[0], shared[2], shared[3]]
    for pth in add:
        name = str(pth.relative_to(e.ROOT))
        manifest["sources"] = [r for r in manifest["sources"] if r["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(pth), bytes=pth.stat().st_size))
    e.save(manifest_path, manifest)
    e.save(
        e.OUT / "publication.json",
        dict(
            status="prepared_local_only",
            central=str(target.relative_to(e.ROOT)),
            website_deployed=False,
            production_changed=False,
        ),
    )
    completion = json.loads((e.OUT / "completion.json").read_text())
    completion.update(status="complete_verified_published_locally", verification="passed")
    e.save(e.OUT / "completion.json", completion)
    e.check()
    print(publication, flush=True)


if __name__ == "__main__":
    main()
