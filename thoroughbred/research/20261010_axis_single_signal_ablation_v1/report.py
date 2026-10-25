"""Preserve isolated grade calibration effects and the uncertainty of small gains."""

# ruff: noqa: E501

import json

import numpy as np
import pandas as pd
import run as a


def table(d):
    def cell(v):
        return f"{v:.6f}" if isinstance(v, float) else str(v)

    return "\n".join(
        [
            "| " + " | ".join(d.columns) + " |",
            "| " + " | ".join(["---"] * len(d.columns)) + " |",
            *[
                "| " + " | ".join(cell(v) for v in row) + " |"
                for row in d.itertuples(index=False, name=None)
            ],
        ]
    )


def main():
    a.check()
    assert json.loads((a.OUT / "verification.json").read_text())["status"] == "passed"
    assert not (a.HERE / "README.md").exists()
    q = pd.read_csv(a.OUT / "quality.csv", dtype={"period": str})
    dif = pd.read_csv(a.OUT / "paired_differences.csv", dtype={"period": str})
    assert json.loads((a.OUT / "isolation_audit.json").read_text())["status"] == "passed"
    p = pd.read_parquet(a.OUT / "risk_predictions.parquet")
    risk = p.pivot(index="race_key", columns="variant", values="risk")
    flags = p.pivot(index="race_key", columns="variant", values="flag")
    changed = int(risk.grade5_local_raw.ne(risk.raw).sum())
    warnings_changed = int(flags.grade5_local_raw.ne(flags.raw).sum())
    assert changed == 205 and warnings_changed == 0
    a.save(
        a.OUT / "local_audit.json",
        dict(
            status="passed",
            probabilities_changed=changed,
            other_probabilities_unchanged=4799 - changed,
            warning_flags_changed=warnings_changed,
            source_predictions_sha256=a.sha(a.OUT / "risk_predictions.parquet"),
        ),
    )
    full = (
        q.query("period=='all' and group=='all'").set_index("variant").loc[a.VARIANTS].reset_index()
    )
    target = (
        q.query("period=='all' and group=='high_probability_grade5'")
        .set_index("variant")
        .loc[a.VARIANTS]
        .reset_index()
    )
    target["mean_predicted_axis_top3"] = 1 - target.mean_risk
    target["actual_axis_top3"] = 1 - target.observed_risk
    local = dif.query(
        "left=='grade5_local_raw' and right=='raw' and metric=='brier' and group in ['all','high_probability_grade5']"
    )
    primary = dif[dif.primary_family]
    assert len(primary) == 3
    local_full = local.query("period=='all' and group=='all'").iloc[0]
    local_target = local.query("period=='all' and group=='high_probability_grade5'").iloc[0]
    assert local_full.low < 0 < local_full.high and local_target.low < 0 < local_target.high
    year_target = q.query(
        "group=='high_probability_grade5' and variant in ['raw','grade5_local_raw'] and period in ['2024','2025','2026']"
    ).copy()
    year_target["mean_predicted_axis_top3"] = 1 - year_target.mean_risk
    year_target["actual_axis_top3"] = 1 - year_target.observed_risk
    body = f"""# 초반·거리·높은 확률 5등급의 개별 위험 보정 비교

2026-10-10. **높은 확률의 5등급에 해당하는 축만 보정하면 해당 집단의 과신은 줄고, 전체 확률 오차도 소폭 감소했다. 하지만 개선을 확정하지 못했고 2026년에는 과대 보정 방향이었다.** 전체 확률을 다시 맞추며 5등급 조건만 추가한 모형과, 그 집단만 바꾸는 보정을 분리했다.

## 비교 대상과 기준

현재 선택 월·게이트·부중22입력의 서울·부산4,799경주,2024-01-05~2026-09-20이다. 축은 기존 점수1위(동점 마번순),목표는 최종1~3착 밖 여부다. 축확률은 우승이 아닌3위 이내 입상확률이다. 조건은 기존38/39와 동일하게 고정했다.

- 초반: 과거 초반200m 최근3평균이 자기 제외 경쟁마 평균보다 느림(차이≥0).
- 거리: 직전보다200m 이상 연장.
- 높은 확률5등급: **보정 전 원축 입상확률≥70%이면서5등급**. 보정 후70% 아래로 내려가도 평가집단에서 빼지 않는다.

raw/calibration/signals는39의 저장 예측을 정확히 재사용했다. 개별3후보는 단순재보정의 절편·기울기와 함께 조건1개·그 조건의 결측1개만 학습했다. 즉 초반/거리 정보를5등급 단독모형에 함께 넣지 않았다. 이 방식은 전체 절편·기울기를 다시 맞추므로 조건 밖 확률도 바뀔 수 있다.

추가한grade5_local_raw는 **원위험logit을고정하고 높은확률5등급이확인된축만 계수1개로보정**했다. 다른4,594경주의 확률은 정확히 동일하다. 이는 ‘5등급 보정만’의 영향을 전체 확률재보정과 분리하는 비교다.

학습은 평가Y의2020~Y−1만 사용하고L2=10/기울기1중심/그외0중심/절편무벌점을 유지했다. 조건이나벌점재탐색은없다. 신규소형위험모형은12개,기존6개재사용,말능력모형재학습0개다.2017년부터학습한원22입력은유지한다.

## 전체 확률 오차 비교

Brier/로그손실은 작을수록좋다. Brier차이는 적중률의%p가 아니다. AUC차이의 유의성은 별도 검증하지 않았다.

{table(full[["variant", "n", "brier", "logloss", "auc"]])}

- 원확률0.230332,단순재보정0.230591.
- 단순재보정+초반만0.230239,거리만0.230466,5등급만0.230430.
- 세조건동시0.229885는 전체점추정에서 가장낮지만 이전39처럼 개선이 확정된것은아니다.
- **해당5등급축만보정0.230153**,원확률대비−0.000179(CI−0.000548~+0.000184)였다. 전체개선폭은작고95%구간은0을포함한다.

개별3후보−단순재보정의주비교도모두95%구간과3비교보정98.333%구간이0을포함했다.

{table(primary[["left", "right", "difference", "low", "high", "bonferroni3_low", "bonferroni3_high"]])}

5등급만추가한전체재보정은단순재보정보다점추정상개선됐지만 **원확률대비로는0.230332→0.230430으로오히려소폭나빠졌다**. 따라서모형전체재보정효과를‘5등급조건덕분’이라고합쳐해석하지않아야한다.

## 높은 확률5등급205경주만 보면

실제축입상142/205=**69.27%**,실제이탈63/205=30.73%다.아래입상확률/실제입상률 열은0~1이다.

{table(target[["variant", "n", "mean_predicted_axis_top3", "actual_axis_top3", "brier"]])}

원평균예상입상확률 **75.07%→해당집단만보정68.88%**,실제69.27%에가까워졌다. 해당집단Brier도0.208518→0.204322로줄었다. 다만차이−0.004196의95%구간은−0.012916~+0.003908로0을포함한다. 평균보정오차와개별경주확률오차는별개이므로평균이맞는다는이유만으로예측개선을확정하지않는다.

전체재보정+5등급만의해당집단평균입상확률은68.78%/Brier0.205471,세조건은69.43%/0.205790이었다. 이205경주에서는집단만보정의점추정이좋았지만,같은표본으로조건을찾고비교했으므로이를독립선정근거로승격하지않는다.

## 연도별 일관성

{table(year_target[["period", "variant", "n", "mean_predicted_axis_top3", "actual_axis_top3", "brier"]])}

2024년71경주와2025년78경주에서는집단만보정의Brier가줄었다. **2026년56경주는원평균예상74.71%,실제입상73.21%로원확률이이미가까웠는데,보정후68.20%로지나치게낮아졌다.** 해당집단Brier0.194464→0.196698,전체Brier0.227130→0.227227로악화방향이었다. 개별연도표본이작고각구간이넓다. 고정감점을운영기준으로채택할근거는아직부족하다.

{table(local[["period", "group", "n", "difference", "low", "high"]])}

## 실제 축 경고가 바뀌었나

전년도위험분포상위30%경계의경고문턱을유지했다. 해당5등급집단만보정에서 **경고가바뀐경주0개**였다.전체원확률과같이1,427경주경고/735축이탈/692실제축입상,경고없는3,372경주의축입상64.35%였다. 확률보정은움직였지만그문턱을넘을정도가아니었다. 전체축입상률은원축불변이므로모두59.64%다.

{table(full[["variant", "flagged", "flagged_failures", "false_alarms", "quiet", "quiet_axis_top3"]])}

새계수는각연도다르며고정%p감점이아니다. 집단만보정의위험logit계수는2024년0.306677,2025년0.304849,2026년0.323024였다. 예를들어2026년원입상확률75%인5등급축은이후보에서위험25%에계수0.323024를적용해입상약68.47%가된다. 이는공식확률이나미래보장값이아닌동결연구식의계산예다.

## 검증과 판단

원39의예측정확재현,4,799×7예측,허용입력열,12모형학습연도경계/저장재예측/최적화기울기,현재결과변조불변,집단밖원확률4,594개정확불변,280품질행,960paired구간행(95%및98.333%),전년도경고문턱,경고변경0을대조했다. T−2이력감사는원39의검증을해시고정참조했다.

반복후향표본/같은표본조건선택/부분집단탐색/동일말반복상관/당일중량과공개시각PIT한계가유지된다. 미래자료접근과새기간성과는없다. 조합/배당/수익률/자동축제외의추가가치를측정한것은아니다.

**판단:높은확률5등급의과신을줄이는연구후보로는유지할가치가있지만,정식반영이나일괄감점은보류한다.** 특히집단밖을그대로두는방식이이번질문의효과를가장명확히분리했다. 현재22/운영/기존39의미래계약을변경하지않았다. 이번후보를미래계약에자동추가하지않았다.

[계획](PLAN.md) · [전체·집단별품질](outputs/quality.csv) · [같은경주차이](outputs/paired_differences.csv) · [개별계수](outputs/coefficients.csv) · [검증](outputs/verification.json) · [집단보정대조](outputs/local_audit.json) · [용량](outputs/artifact_inventory.json).
"""
    example = float(1 / (1 + np.exp(np.log(0.25 / 0.75) + 0.3230235908840212)))
    assert abs(example - 0.6847) < 0.0001
    (a.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 세 축위험 조건의 개별 기여

초반느림·거리연장·원입상확률70%이상+5등급을각각추가해같은4,799경주에서비교했다.단순재보정대비개별3조건모두확실한전체Brier개선은확인하지못했다.전체확률까지다시맞춘5등급단독모형은원확률대비소폭악화했다.

다른경주는그대로두고높은확률5등급205경주만보정하면평균예상입상75.07%→68.88%,실제69.27%에가까워졌다.해당집단Brier0.208518→0.204322,전체0.230332→0.230153으로줄었으나paired95%구간은0을포함했다.

예를들어2026년해당집단은원평균74.71%/실제73.21%로이미가까웠는데보정후68.20%로과도하게낮아졌다.2024·25와달리2026은악화방향이다.위험경고선택은바뀐경주0개였다.과신보정후보이지축탈락포착개선이나고정감점의확정근거가아니다.

조건을찾을때쓴반복후향자료/작은부분집단/PIT한계를유지한다.현재22입력·운영·이전미래검증계약은그대로두었고새기간성과는없다.

[전체 보고서](README.md) · [검증](outputs/verification.json) · [집단보정 대조](outputs/local_audit.json).
"""
    (a.HERE / "PUBLICATION.md").write_text(pub)
    a.save(
        a.OUT / "decision.json",
        dict(
            status="grade5_local_calibration_promising_but_uncertain",
            primary_single_condition_improvements_confirmed=bool(
                primary.bonferroni3_high.lt(0).any()
            ),
            local_full_brier_delta=float(local_full.difference),
            local_full_ci=[float(local_full.low), float(local_full.high)],
            local_target_brier_delta=float(local_target.difference),
            local_target_ci=[float(local_target.low), float(local_target.high)],
            local_probabilities_changed=changed,
            local_warning_flags_changed=warnings_changed,
            production_changed=False,
            selected_baseline_changed=False,
            prior_future_contract_changed=False,
            new_small_models=12,
            reused_small_models=6,
            prospective_evaluated_races=0,
        ),
    )
    shared = [
        a.R / "README.md",
        a.R / "ARTIFACT_SIZE_LOG.md",
        a.R / "conclusions/README.md",
        a.R / "conclusions/SOURCES.md",
        a.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for path in shared:
        before[str(path.relative_to(a.ROOT))] = dict(bytes=path.stat().st_size, sha256=a.sha(path))
        dest = a.OUT / "publication_before" / path.relative_to(a.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    a.save(a.OUT / "publication_before.json", before)
    target_path = a.R / "conclusions/40_AXIS_SINGLE_SIGNAL_ABLATION.md"
    assert not target_path.exists()
    target_path.write_text(
        pub.replace("(README.md)", f"(../{a.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{a.HERE.name}/outputs/"
        )
    )
    marker = "<!-- axis_single_signal_ablation_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{a.HERE.name}/README.md" if path.parent == a.R else target_path.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[축위험 개별조건과 고확률5등급만 보정]({link}):4,799경주개별3조건확정개선없음.5등급205경주만보정예상입상75.07→68.88%(실제69.27%),전체Brier0.230332→0.230153/CI0포함,2026악화.운영·이전미래계약유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    paths = (
        [
            a.HERE / name
            for name in [
                "PLAN.md",
                "README.md",
                "PUBLICATION.md",
                "run.py",
                "verify.py",
                "report.py",
                "audit_isolation.py",
            ]
        ]
        + [
            a.OUT / name
            for name in [
                "source_lock.json",
                "cohort.json",
                "verification.json",
                "local_audit.json",
                "isolation_audit.json",
                "decision.json",
            ]
        ]
        + list((a.OUT / "models").glob("*.json"))
        + [target_path, shared[0], shared[2], shared[3]]
    )
    for path in paths:
        name = str(path.relative_to(a.ROOT))
        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=a.sha(path), bytes=path.stat().st_size))
    a.save(shared[-1], manifest)
    a.save(
        a.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            new_small_models=12,
            reused_small_models=6,
            new_horse_ability_models=0,
            database_access=False,
            network_access=False,
            jeju_access=False,
            future_data_access=False,
            production_changed=False,
            selected_baseline_changed=False,
            prior_future_contract_changed=False,
        ),
    )
    a.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()
