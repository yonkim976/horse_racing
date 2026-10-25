# ruff: noqa: E501
"""Preserve verified thoroughbred policy diagnostics and publication records."""

import json

import pandas as pd
import run as e

LABELS = {
    "axis_pool5": "축+상대4두·전6개",
    "axis_pool6": "축+상대5두·10개 중6개",
    "axis_pool7": "축+상대6두·15개 중6개",
    "axis_all": "축+전체 상대·최고6개",
    "global6": "축 강제 없이 전체 삼복 최고6개",
}
MODELS = {"month_gate_weight22": "현재 선택22개", "style_history53": "구간/각질 연구후보53개"}
MARKER = "<!-- axis_pool_validation_v1_20261009 -->"


def metric(s, model, policy, period="development_2024_2026", scope="all", value="all"):
    return s[
        (s.model == model)
        & (s.policy == policy)
        & (s.period == period)
        & (s.scope == scope)
        & (s.value.astype(str) == str(value))
    ].iloc[0]


def main():
    e.check()
    verification = json.loads((e.OUT / "verification.json").read_text())
    assert verification["passed"]
    summary = pd.read_csv(e.OUT / "summary.csv")
    paired = pd.read_csv(e.OUT / "paired_differences.csv")
    failures = pd.read_csv(e.OUT / "failure_decomposition.csv")
    captures = pd.read_csv(e.OUT / "capture_events.csv")
    races = pd.read_csv(e.OUT / "race_metrics.csv")
    primary = paired[
        (paired.model == "month_gate_weight22")
        & (paired.period == "development_2024_2026")
        & (paired.scope == "all")
        & (paired.policy == "axis_pool7")
        & (paired.metric == "six_hit")
    ].iloc[0]
    annual = paired[
        (paired.model == "month_gate_weight22")
        & (paired.period == "development_2024_2026")
        & (paired.scope == "year")
        & (paired.policy == "axis_pool7")
        & (paired.metric == "six_hit")
    ]
    promising = bool(primary.lo > 0 and annual["mean"].ge(0).all())
    decision = dict(
        status="promising_policy_candidate_not_selected"
        if promising
        else "policy_improvement_not_established",
        primary_model="month_gate_weight22",
        primary_policy="axis_pool7",
        prior_policy="axis_pool5",
        difference_pp=float(primary["mean"] * 100),
        date_bootstrap95_pp=[float(primary.lo * 100), float(primary.hi * 100)],
        no_annual_point_decline=bool(annual["mean"].ge(0).all()),
        same_all_races=4799,
        new_fits=0,
        new_calibrations=0,
        existing_selection_maintained=True,
        production_changed=False,
        future_independent_validation=False,
        jeju_accessed=False,
    )
    e.save(e.OUT / "decision.json", decision)
    direct = []
    for model in MODELS:
        g = races[(races.model == model) & (races.period == "development_2024_2026")]
        for baseline in ["global6", "axis_all"]:
            direct.append(
                dict(
                    model=model,
                    policy="axis_pool7",
                    baseline=baseline,
                    **e.comparison(g[g.policy == "axis_pool7"], g[g.policy == baseline]),
                )
            )
    pd.DataFrame(direct).to_csv(e.OUT / "axis_constraint_comparisons.csv", index=False)
    # Report table is generated from independently checked summary values.
    table = (
        "|모형|방식|경주|적중 수|적중률|축 입상시 상대2두 포착|\n|---|---|---:|---:|---:|---:|\n"
    )
    for model in MODELS:
        for policy in LABELS:
            z = metric(summary, model, policy)
            conditional = (
                f"{z.companion_given_axis:.2%}" if policy.startswith("axis_") else "비교 대상 아님"
            )
            table += f"|{MODELS[model]}|{LABELS[policy]}|{int(z.races):,}|{int(z.hits):,}|{z.hit_rate:.2%}|{conditional}|\n"
    subgroup = "|모형|구분|경주|기존→확대|차이 %p|날짜95%구간 %p|\n|---|---|---:|---:|---:|---:|\n"
    group_labels = {
        "1": "서울",
        "3": "부산",
        "through1300": "≤1300m",
        "1400_1600": "1400~1600m",
        "1700plus": "≥1700m",
    }
    selected = paired[
        (paired.period == "development_2024_2026")
        & (paired.policy == "axis_pool7")
        & (paired.metric == "six_hit")
        & paired.scope.isin(["year", "meet", "distance_band", "grade_band"])
    ]
    for z in selected.itertuples():
        label = group_labels.get(str(z.value), str(z.value))
        subgroup += f"|{MODELS[z.model]}|{z.scope}:{label}|{z.races:,}|{z.base_rate:.2%}→{z.new_rate:.2%}|{z.mean * 100:+.2f}|[{z.lo * 100:+.2f}, {z.hi * 100:+.2f}]|\n"
    old = metric(summary, "month_gate_weight22", "axis_pool5")
    new = metric(summary, "month_gate_weight22", "axis_pool7")
    old53 = metric(summary, "style_history53", "axis_pool5")
    new53 = metric(summary, "style_history53", "axis_pool7")
    h0 = metric(summary, "style_history53", "axis_pool5", "historical_2020_2023")
    h1 = metric(summary, "style_history53", "axis_pool7", "historical_2020_2023")
    hist_ci = paired[
        (paired.model == "style_history53")
        & (paired.period == "historical_2020_2023")
        & (paired.scope == "all")
        & (paired.policy == "axis_pool7")
        & (paired.metric == "six_hit")
    ].iloc[0]
    diagnosis = (
        failures[
            (failures.model == "month_gate_weight22")
            & (failures.period == "development_2024_2026")
            & (failures.policy == "axis_pool7")
        ]
        .set_index("failure")
        .races
    )
    fail_n = int(new.races - new.hits)
    cap = captures[
        (captures.model == "month_gate_weight22") & (captures.period == "development_2024_2026")
    ]
    changed = int(cap.added_tickets.gt(0).sum())
    operating = pd.read_csv(e.OUT / "operating_comparisons.csv")
    op22 = operating[
        (operating.model == "month_gate_weight22")
        & (operating.policy == "axis_pool7")
        & (operating.meet == 0)
    ].iloc[0]
    op53 = operating[
        (operating.model == "style_history53")
        & (operating.policy == "axis_pool7")
        & (operating.meet == 0)
    ].iloc[0]
    examples = cap.sort_values(["race_date", "race_key"]).tail(1)
    rid = examples.race_key.iloc[0]
    tickets = pd.read_parquet(e.OUT / "six_tickets.parquet")
    example = tickets[
        (tickets.model == "month_gate_weight22")
        & (tickets.race_key == rid)
        & tickets.policy.isin(["axis_pool5", "axis_pool7"])
    ].copy()
    example.to_csv(e.OUT / "example_tickets.csv", index=False)
    example_text = "\n".join(
        f"- {LABELS[policy]}: "
        + ", ".join(v.replace(",", "-") for v in g.sort_values("selection_rank").programs)
        for policy, g in example.groupby("policy")
    )
    finding = (
        f"현재 선택22개에서 축+상대4두6개 {old.hit_rate:.2%} → 상대6두에서 점수합 최고6개 {new.hit_rate:.2%}"
        f"(+{primary['mean'] * 100:.2f}%p, 날짜95% +{primary.lo * 100:.2f}~+{primary.hi * 100:.2f}%p). "
        f"53개 연구후보는 {old53.hit_rate:.2%}→{new53.hit_rate:.2%}다. 선택 규칙의 후향 개선 신호이며 새 학습·운영 승격은 없다."
    )
    status = (
        "후속 검증할 조합 선택 규칙 후보로 보존한다."
        if promising
        else "조합 선택 규칙의 개선을 확정하지 못했다."
    )
    text = f"""# 더러브랫 축 고정 후보 범위 확대 추가 검증

2026-10-09 완료. **{finding} {status}** 제주 자료·코드·문서는 이번 작업에서 읽거나 변경하지 않았다. 기본 모델을 다시 학습하거나 확률을 보정한 횟수는0이다.

## 무엇을 고정하고 비교했나

현재 선택 기준선은 월+게이트+부담중량22개이며53개는 연구후보다. 기존 각 말 점수·온도·모형1위 축·전체 출전집합·구매6개·경주 수를 고정했다. `axis_pool5`는 축+모형2~5위의 모든6개, 주 정책 `axis_pool7`은 축+모형2~7위의15개에서 기존 로짓합 최고6개다. 전체15개를 샀다는 뜻이 아니다. `axis_pool6`·전체 상대·축 강제 없는 전체최고6개는 사전 고정 진단이며 결과를 보고 주 정책으로 바꾸지 않았다.

## 같은4,799경주 결과

{table}
주 비교22개는 새 적중 {int(primary.rescued)}경주, 기존 적중 손실 {int(primary.lost)}경주, 순 {int(new.hits - old.hits):+}경주다. 실제 조합이 바뀐 경주는 {changed:,}/4,799이고, 교체 조합은 경주당 평균 {cap.added_tickets.mean():.2f}개다. 후보를 더 검토하되6개 예산을 유지한다.

기본 축 입상률은22개 {new.axis_rate:.2%},53개 {new53.axis_rate:.2%}로 정책별 동일하다. 전체 삼복 분포와 집합NLL도 정책별 동일하다. **조합 선택 개선이며 모델이 말 능력·확률을 더 잘 학습했다는 결과가 아니다.** 같은 분포에서 더 넓은 후보군의 최고6개 확률합이 증가하는 것은 기계적 성질이고, 실제 적중 차이는 별도로 평가했다.

축 없는 기존 전체최고6개는22개 {metric(summary, "month_gate_weight22", "global6").hit_rate:.2%},53개 {metric(summary, "style_history53", "global6").hit_rate:.2%}다. 축고정 확대 규칙이 이 기존 방식까지 우월하다고 주장하지 않는다. [축 고정 제약 비교](outputs/axis_constraint_comparisons.csv).

## 연도·지역·거리·등급

{subgroup}
날짜 집단2000회 대응 bootstrap·점별95%구간이다. 주 검증은22개 전체 한 비교이며 하위군은 탐색이다.53개2024~2026의 각 연도와 두 지역에서는 양수 구간이 남지만,22개 서울·2025·2026 및1700m이상에서는 차이 구간이0을 포함한다. 평균 개선을 모든 조건의 확정 개선으로 확대하지 않는다. 100경주·30일 미만 세부 셀은 소표본 표시했고 거리별 최고 규칙을 고르지 않았다. [두수·이력별 포함 전체 표](outputs/summary.csv),[대응 차이](outputs/paired_differences.csv).

## 과거 시기 민감도

이전 연구에서2020~2023년마다 당시 이전 자료만으로 생성한53개 OOF 5,971경주에 같은 규칙을 적용했다. {h0.hit_rate:.2%}→{h1.hit_rate:.2%}, 차이 {hist_ci["mean"] * 100:+.2f}%p [날짜95% {hist_ci.lo * 100:+.2f}~{hist_ci.hi * 100:+.2f}]다. 각 연도의 점추정도 양수였다. 이 기간은 앞 동반모델 학습과 피처 개발에 관련된 자료이므로 새로운 독립 미관측 검증이 아니다.22개2020~2023 OOF는 이번에 새 학습하지 않았다.

## 남은 실패의 위치

현재22개 확대 규칙의 실패 {fail_n:,}경주:

- 축 자체가3위 밖: {int(diagnosis["axis_miss"]):,}경주, 실패의 {diagnosis["axis_miss"] / fail_n:.2%}.
- 축은 입상했지만 상대 두 마리 중 적어도 하나가 모형2~7위 밖: {int(diagnosis["companions_outside_pool"]):,}경주.
- 축도 입상하고 상대 두 마리도 후보6두 안이지만,15개 중 선택6개에 정답 쌍이 없음: {int(diagnosis["companions_inside_unselected"]):,}경주.

따라서 후보 범위 확대만으로 축 탈락을 해결할 수 없고, 후보군 안의 관계 선택에도 개선 여지가 남는다. 실제 선행 붕괴·당일 컨디션 등이 원인이라고 이번 결과만으로 확정하지 않는다. [실패 분해](outputs/failure_decomposition.csv),[신규 적중·손실 경주 전체](outputs/capture_events.csv),[실제 입상마 모형순위별 포착](outputs/capture_by_rank.csv).

## 운영 모델과 같은 경주 비교

전체 말ID·원래 마번·정상착순까지 일치한1,258경주에서22개 확대 규칙은 {op22.new_rate:.2%},53개 확대 규칙은 {op53.new_rate:.2%},기존 운영의 원래6조합은 {op22.operating_rate:.2%}다.22개−운영 차이는 {op22["mean"] * 100:+.2f}%p [날짜95% {op22.lo * 100:+.2f}~{op22.hi * 100:+.2f}],53개−운영은 {op53["mean"] * 100:+.2f}%p [{op53.lo * 100:+.2f}~{op53.hi * 100:+.2f}]다.

운영보다 개선됐다는 근거는 없다. 운영과 연구는 축·입력·학습·분포 구조가 다른 완성 방식이므로 조합 선택 변수 하나의 순수 기여로 비교하지 않는다. 실제 게시 구매나 배당·수익률 평가도 아니다. [운영 대응 비교](outputs/operating_comparisons.csv),[일치 장부](outputs/operating_alignment.json).

## 과거 편성 예시

결과로 고르지 않고 현재22개 자료의 최종일·식별자 순서 마지막 편성 `{rid}`를 표시했다. 실시간 추천이 아니다.

{example_text}

같은 축·6개에서 상대 조합만 바뀐다. [예시 확률과 실제 결과](outputs/example_tickets.csv).

## 재현·제한·결정

이전2017+ 학습·T−2/730일 과거 입력을 유지했다. 평가12개 모형과 과거OOF8개를 재로딩해 모든 점수를 재현했고, 원래22개 전체최고6개와 앞53개 축고정 결과도 재현했다. 별도 코드로 모든 삼복 조합·확률·티켓·정답·bootstrap 구간을 다시 계산했다. 현재 정답 제거/교란·행 순서 변경에도 선택이 같다. 등록부·원천·모형 SHA 불변. [검증](outputs/verification.json),[사전 계약](PLAN.md),[출처 동결](outputs/source_lock.json).

기존2024~2026 개발 자료의 반복 평가이고 과거 실제 출마표 최초 게시·취소·정정 시각까지 재현한 것은 아니다. 부담중량 사전 공개 시각의 원천 한계와 과거 피처의 결측·지원량 한계도 승계한다. 이번 검증으로 운영 모델·선택 기준22개·웹·DB를 바꾸지 않는다. {status} 이후 기간의 독립 검증과 축 선정 개선을 분리해 진행할 필요가 있다.
"""
    (e.HERE / "README.md").write_text(text)
    (e.HERE / "PUBLICATION.md").write_text(
        f"# 더러브랫 축과 상대 후보를 넓혀 읽기\n\n{finding}\n\n기존 상대4두의 모든6조합 대신, 상대6두 중 선택6조합을 검토한다. 축을 고르는 모델의 능력은 그대로이며 전체15조합 구매가 아니다. 예시는 원 보고서의 최종일 과거 편성에 연결했다.\n\n지역·거리별 차이가 남고 운영 우위가 확인되지 않았으므로 후속 연구 후보로 보존한다. 이미 본 과거 기간의 결과이며 운영 적용이나 수익 개선 증거가 아니다.\n"
    )
    publish(finding, decision)


def publish(finding, decision):
    con = e.R / "conclusions"
    title = "30_AXIS_POOL_VALIDATION.md"
    target = con / title
    assert not target.exists()
    targets = [
        con / "README.md",
        con / "SOURCES.md",
        con / "source_manifest.json",
        e.R / "README.md",
        e.R / "ARTIFACT_SIZE_LOG.md",
    ]
    before = {}
    backup = e.HERE / "publication_before"
    backup.mkdir(exist_ok=False)
    for p in targets:
        key = str(p.relative_to(e.ROOT))
        before[key] = dict(bytes=p.stat().st_size, sha256=e.sha(p))
        (backup / key.replace("/", "__")).write_bytes(p.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target.write_text(
        f"# 더러브랫 축 고정 후보 범위 확대 추가 검증\n\n2026-10-09. {finding}\n\n상태 `{decision['status']}`. 22개 기준선의2025·2026·서울·장거리별 개선은 불확실성이 남는다. 실패3,595경주 중1,937경주는 축 탈락이다. 같은1,258경주에서22개 확대27.50%,53개 확대29.41%,운영 원래6개30.52%로 운영 우위 근거는 없다.\n\n현재 선택22개·운영·웹·DB 변경 없음. 새 학습·보정0회. 제주 작업은이번범위밖이다.\n\n[원 보고서](../{e.HERE.name}/README.md),[검증](../{e.HERE.name}/outputs/verification.json),[사전계약](../{e.HERE.name}/PLAN.md). 이전 [축조건부 동반학습](29_AXIS_COMPANION_PAIRS.md)은 별도 결과로 보존한다.\n"
    )
    for p in [con / "README.md", con / "SOURCES.md"]:
        data = p.read_text()
        assert MARKER not in data
        p.write_text(
            data
            + f"\n\n{MARKER}\n[축 고정 후보 범위 추가 검증]({title}): {finding} [원본](../{e.HERE.name}/README.md).\n"
        )
    p = e.R / "README.md"
    p.write_text(
        p.read_text()
        + f"\n\n{MARKER}\n[더러브랫 후보 범위 추가 검증]({e.HERE.name}/README.md): {finding}\n"
    )
    p = con / "source_manifest.json"
    manifest = json.loads(p.read_text())
    entries = manifest["sources"]
    for file in [
        target,
        con / "README.md",
        con / "SOURCES.md",
        e.HERE / "README.md",
        e.HERE / "PLAN.md",
        e.OUT / "decision.json",
        e.OUT / "verification.json",
    ]:
        path = str(file.relative_to(e.ROOT))
        item = dict(path=path, sha256=e.sha(file), bytes=file.stat().st_size)
        prior = next((r for r in entries if r["path"] == path), None)
        if prior is None:
            entries.append(item)
        else:
            prior.update(item)
    manifest["updated_at"] = "2026-10-09"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    e.check()
    e.save(
        e.OUT / "publication_verification.json",
        dict(
            passed=True,
            registry_and_source_unchanged=True,
            previous_reports_preserved=True,
            jeju_accessed=False,
            selection_changed=False,
        ),
    )
    inventory = e.OUT / "artifact_inventory.json"
    inventory.write_text("{}\n")
    size_log = e.R / "ARTIFACT_SIZE_LOG.md"
    log_before = (backup / "thoroughbred__research__ARTIFACT_SIZE_LOG.md").read_text()
    previous = None
    for _ in range(25):
        files = sorted(
            [p for p in e.HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
            + [target]
        )
        rows = [
            dict(
                path=str(p.relative_to(e.ROOT)),
                bytes=p.stat().st_size,
                sha256=None if p == inventory else e.sha(p),
            )
            for p in files
        ]
        total = sum(r["bytes"] for r in rows)
        size_log.write_text(
            log_before
            + f"\n| 2026-10-09 | 더러브랫 축 고정 후보 범위 추가 검증 | {len(rows)} | {total} | {total / 1048576:.6f} | {len(targets)} | 명세 참조 | 명세 참조 | [명세]({e.HERE.name}/outputs/artifact_inventory.json) | {MARKER}\n"
        )
        modified = [
            dict(
                path=str(p.relative_to(e.ROOT)),
                before_bytes=before[str(p.relative_to(e.ROOT))]["bytes"],
                bytes=p.stat().st_size,
                delta_bytes=p.stat().st_size - before[str(p.relative_to(e.ROOT))]["bytes"],
                sha256=e.sha(p),
            )
            for p in targets
        ]
        obj = dict(
            new_file_count=len(rows),
            new_bytes=total,
            new_mib=round(total / 1048576, 6),
            modified_file_count=len(modified),
            modified_delta_bytes=sum(r["delta_bytes"] for r in modified),
            new_files=rows,
            modified_files=modified,
            inventory_self_hash_omitted=True,
        )
        inventory.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        signature = (total, inventory.stat().st_size, tuple(r["bytes"] for r in modified))
        if previous == signature:
            break
        previous = signature
    else:
        raise AssertionError("Artifact inventory did not converge")
    final = json.loads(inventory.read_text())
    for r in final["new_files"] + final["modified_files"]:
        p = e.ROOT / r["path"]
        assert p.stat().st_size == r["bytes"]
        if r["sha256"] is not None:
            assert e.sha(p) == r["sha256"]
    assert sum(r["bytes"] for r in final["new_files"]) == final["new_bytes"]
    e.check()
    print(
        "Report and conclusions saved",
        final["new_file_count"],
        "files",
        final["new_bytes"],
        "bytes",
        final["new_mib"],
        "MiB",
        flush=True,
    )


if __name__ == "__main__":
    main()
