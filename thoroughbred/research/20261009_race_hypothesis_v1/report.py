"""Render the fixed retrospective hypothesis experiment and preserve its inventory."""
# ruff: noqa: E501

import json
from pathlib import Path

import pandas as pd
import run as experiment

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ORDER = ["style_history", *experiment.CONFIG["variants"]]
NAMES = {
    "style_history": "기존 구간·회복/후퇴53",
    "hypothesis_trend": "최근 구간 변화 추가",
    "hypothesis_distance": "거리조건부 이력 추가",
    "hypothesis_pace": "선행경쟁·후반능력 관계 추가",
    "hypothesis_all": "세 묶음 모두 추가",
}
LABELS = {
    "axis_top3": "축3위이내",
    "top5_all": "상위5두 입상3두 포괄",
    "axis_top2": "축2위이내",
    "top6_all": "상위6두 입상3두 포괄",
    "top3_all": "상위3두 전부입상",
    "quinella_one": "복승1조합",
    "axis_next3": "축복승3조합",
    "target_brier": "입상Brier",
    "set_logloss": "삼복조합NLL",
}


def main():
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    experiment.check_inputs()
    metrics = pd.read_csv(OUT / "metrics.csv")
    comparisons = json.loads((OUT / "paired_differences.json").read_text())
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    runners = pd.read_parquet(OUT / "runner_predictions.parquet")
    runners = runners.sort_values(
        ["variant", "race_key", "raw_score", "program_no"], ascending=[True, True, False, True]
    )
    runners["prediction_rank"] = runners.groupby(["variant", "race_key"]).cumcount() + 1
    base = runners[runners.variant.eq("style_history")]
    keys = ["race_key", "program_no", "horse_id"]
    changes = []
    for variant in experiment.CONFIG["variants"]:
        g = runners[runners.variant.eq(variant)].merge(
            base[keys + ["prediction_rank", "outcome"]],
            on=keys,
            suffixes=("", "_base"),
            validate="one_to_one",
        )
        assert g.outcome.equals(g.outcome_base)
        actual = g.outcome.between(1, 3)
        outside = actual & g.prediction_rank_base.gt(5)
        rescued = outside & g.prediction_rank.le(5)
        dropped = actual & g.prediction_rank_base.le(5) & g.prediction_rank.gt(5)
        changes.append(
            dict(
                variant=variant,
                baseline_outside5_podium_horses=int(outside.sum()),
                rescued_into5=int(rescued.sum()),
                dropped_out_of5=int(dropped.sum()),
                net_podium_horses=int(rescued.sum() - dropped.sum()),
            )
        )
    pd.DataFrame(changes).to_csv(OUT / "outsider_capture.csv", index=False)
    gains = []
    for folder in sorted((OUT / "models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        total = sum(meta["gain"].values())
        for feature, gain in meta["gain"].items():
            gains.append(
                dict(
                    variant=meta["variant"],
                    model=folder.name,
                    feature=feature,
                    new_hypothesis=feature.startswith("hyp_"),
                    gain=gain,
                    gain_fraction=gain / total if total else 0,
                )
            )
    pd.DataFrame(gains).to_csv(OUT / "feature_gain.csv", index=False)
    text = [
        "# 경주별 가설을 입력으로 추가한 검증",
        "",
        "2026-10-09. 기존 연구53개 기준선 비교. 현재 선택22개/운영/DB/웹 변경 없음.",
        "",
        "최근 구간 상승, 이번 거리대의 각질·회복 이력, 상대 선행성향과 자기 후반능력의 관계를 각각 변수로 만들었다. 고정 보너스 대신 기존 학습기가 결과와의 관계를 학습한다. 세 묶음 단독과 전체 추가를 사전에 고정했다. 이 실험은 말별 입력의 추가 효과이며 조합별 전개 점수를 새로 학습한 결과는 아니다.",
        "",
        "## 같은4,799경주의 결과",
        "",
        "2024-01-05~2026-09-20,50,754출전.2026부분연도. 축은3위이내확률1순위. 상위5/6두 포괄은 실제입상3두가 모두 후보집합에 포함됐다는 뜻이며 구매조합 적중률이 아니다. 복승1조합은1·2순위, 축복승3조합은1순위와2/3/4순위다.",
        "",
        "| 후보 | 입력수 | 축3위이내 | 상위5두 입상3두 포괄 | 축2위이내 | 복승1조합 | 축복승3조합 | 상위6두 포괄 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in ORDER:
        g = metrics[metrics.variant.eq(variant) & metrics.scope.eq("all")].iloc[0]
        vals = [
            f"{g[c] * 100:.2f}%"
            for c in [
                "axis_top3",
                "top5_all",
                "axis_top2",
                "quinella_one",
                "axis_next3",
                "top6_all",
            ]
        ]
        text.append(f"|{NAMES[variant]}|{len(contracts[variant])}|" + "|".join(vals) + "|")
    all_primary = [
        r for r in comparisons if r["period"] == "all" and r["metric"] in ["axis_top3", "top5_all"]
    ]
    if all(r["interval95"][0] <= 0 <= r["interval95"][1] for r in all_primary):
        text += [
            "",
            "현재의 네 추가후보 모두 두 주지표 차이의95%구간이0을 포함했다. 가설을 데이터 입력으로 구현하고 학습할 수 있었지만, 기존53개보다 개선됐다는 근거는 확보하지 못했다.97개 전체추가의 상위5두 포괄 상승도 불확실하며 축입상은 점추정에서 낮아졌다. 이 결과를 가설 자체의 반증으로 읽지 않는다.",
            "",
        ]
    text += [
        "",
        "## 주지표의 해석",
        "",
        "아래는 사전에 정한 두 주지표만의 비교다. 방향이 남았다는 판단도 다중비교를 보정하지 않은 탐색적 구간에 한정한다. 운영 대체·확정 채택·미래 적중 보장을 뜻하지 않는다.",
        "",
    ]
    for variant in experiment.CONFIG["variants"]:
        findings = []
        for metric in ["axis_top3", "top5_all"]:
            row = next(
                r
                for r in comparisons
                if r["variant"] == variant and r["period"] == "all" and r["metric"] == metric
            )
            lo, hi = row["interval95"]
            conclusion = (
                "증가 방향이 구간에 남음"
                if lo > 0
                else "감소 방향이 구간에 남음"
                if hi < 0
                else "방향 불확실"
            )
            findings.append(
                f"{LABELS[metric]} {row['difference']:+.2f}%p(95% {lo:+.2f}~{hi:+.2f}, {conclusion})"
            )
        text.append(f"- {NAMES[variant]}: " + "; ".join(findings) + ".")
    text += [
        "",
        "## 53개 대비 같은경주 차이",
        "",
        "날짜 단위 paired bootstrap2,000회, 탐색적95%구간.0을 포함하면 방향을 확정하지 않는다. 여러 후보/지표를 비교했으며 다중비교를 보정하지 않았다.2024~2026은 반복 연구한 과거 기간이므로 독립 미래검증이 아니다.",
        "",
        "| 후보 | 지표 | 차이%p | 95%구간%p |",
        "|---|---|---:|---:|",
    ]
    for row in comparisons:
        if row["period"] == "all" and row["metric"] not in ["target_brier", "set_logloss"]:
            lo, hi = row["interval95"]
            text.append(
                f"|{NAMES[row['variant']]}|{LABELS[row['metric']]}|{row['difference']:+.2f}|{lo:+.2f}~{hi:+.2f}|"
            )
    text += [
        "",
        "## 확률 품질",
        "",
        "목표가 같은3위이내 모델끼리 비교했다. Brier와조합NLL은 낮을수록 좋으며 적중률과 구분한다.",
        "",
        "| 후보 | Brier | 삼복조합NLL |",
        "|---|---:|---:|",
    ]
    for variant in ORDER:
        g = metrics[metrics.variant.eq(variant) & metrics.scope.eq("all")].iloc[0]
        text.append(f"|{NAMES[variant]}|{g.target_brier:.6f}|{g.set_logloss:.6f}|")
    text += [
        "",
        "## 연도별 주지표",
        "",
        "| 연도 | 후보 | 경주수 | 축3위이내 | 상위5두 포괄 |",
        "|---|---|---:|---:|---:|",
    ]
    for year in [2024, 2025, 2026]:
        for variant in ORDER:
            g = metrics[
                metrics.scope.eq("year") & metrics.variant.eq(variant) & metrics.label.eq(str(year))
            ].iloc[0]
            text.append(
                f"|{year}|{NAMES[variant]}|{g.races}|{g.axis_top3 * 100:.2f}%|{g.top5_all * 100:.2f}%|"
            )
    text += [
        "",
        "## 기존 후순위 입상마를 올렸는가",
        "",
        "기존 평가5순위 밖의 실제입상마가 새 후보에서5순위 안으로 올라온 수와, 기존5순위 안의 입상마가 밖으로 내려간 수를 별도로 센다. 말 단위 변화이므로 경주 포괄 개선과 같지 않다. 결과는 평가에만 사용하고 입력/학습후 선택에 넣지 않았다.",
        "",
        "| 후보 | 기존밖 입상마→5순위안 | 기존안 입상마→5순위밖 | 순증 입상마 |",
        "|---|---:|---:|---:|",
    ]
    for row in changes:
        text.append(
            f"|{NAMES[row['variant']]}|{row['rescued_into5']}|{row['dropped_out_of5']}|{row['net_podium_horses']:+d}|"
        )
    text += [
        "",
        "전체추가에서 기존밖 입상마567두를 새로 포착했지만 기존안 입상마573두를 놓쳤다. 상위5두에 포착한 입상마 수의 순증은−6두였다. 경주별3두 전부포괄은+32경주로, 말별 포착수와 경주별 공동포괄은 다른 지표임을 보여준다. [변수 중요도](outputs/feature_gain.csv)는 학습 사용 여부를 점검하는 자료이며 인과효과나 성능 향상의 증거가 아니다.",
    ]
    text += [
        "",
        "## 입력과 해석 범위",
        "",
        "- 최근 변화12개는 구간별 직전/최근3의 개선초와 최근/이전 슬롯 지원수다. 보정된초가 없는 과거는 기존 원초 규칙을 유지한다. 최근 두세 번만 있는 말도 제외하지 않으며 결측을 좋은 출전으로 대체하지 않는다.",
        "- 거리조건부16개는 이번 거리대와 일치하는 최근5 실제슬롯의 선행/회복/후퇴/후반600 이력이다. 거리대0은≤1300,1은1400~1600,2는≥1700m다. 같은 거리대 안에서도 정확 거리 차이는 남는다. 거리별 전용모형 또는 길게 확장한 동거리 이력 실험이 아니다.",
        "- 선행경쟁16개는 자기 제외 상대의 과거성향과 기록을 사용한다. 선행빈도0.4,초반차이0.15초는 사전 고정 가설치다. 다른 임계치를 결과에 맞춰 탐색하지 않았다. 관측 지원수와 결측을 유지하며 실제 경합·작전·내외측 주행을 측정한 값으로 읽지 않는다.",
        "- 마지막600과200은 겹치지만 별도 변수로 사용하며 더해서 능력점수를 만들지 않는다. 현재 상대 기록 비교에는 과거 거리구성 차이가 남을 수 있다. 기수/조교사/새 게이트/당일 결과·실측 전개/당일 실측함수율·배당을 추가하지 않았다.",
        "",
        "## 학습과 검증",
        "",
        "2017부터 목표학습,2010~2016기존warm-up. 기존178,497행/기존53개 열/과거슬롯은 그대로다. Y−2조기종료후재학습,Y−1온도교정,Y시험,서울/부산별 동일LightGBM설정/seed/1두수가중치. 기준53개는 기존저장모형/예측을 재사용했다. 현재 부담중량과 출전명단의 사전공개시각 미감사 등 기존연구 한계를 유지한다.",
        "",
        f"검증 통과: 신규 저장모형{verification['new_models_replayed']}개 재추론, 최대 원점수 오차{verification['max_raw_score_error']}. 기존53개 불변,실제슬롯의마필/시점/730일,현재정답변조불변,독립상대합/구간변화표본계산,전체순위포괄·확률합/확률재계산,원천/운영해시를 확인했다. 운영 승격 없음.",
        "",
        "[사전계획](PLAN.md) · [전체입력](outputs/feature_contract.json) · [집계/거리/등급](outputs/metrics.csv) · [차이와구간](outputs/paired_differences.json) · [후순위포착](outputs/outsider_capture.csv) · [검증](outputs/verification.json) · [원천해시](outputs/input_manifest.json).",
        "",
        "```sh",
        ".venv/bin/python thoroughbred/research/20261009_race_hypothesis_v1/run.py prepare",
        ".venv/bin/python thoroughbred/research/20261009_race_hypothesis_v1/run.py train",
        ".venv/bin/python thoroughbred/research/20261009_race_hypothesis_v1/run.py analyze",
        ".venv/bin/python thoroughbred/research/20261009_race_hypothesis_v1/run.py verify",
        ".venv/bin/python thoroughbred/research/20261009_race_hypothesis_v1/report.py",
        "```",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(text))
    files = [
        p
        for p in sorted(HERE.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.name != "artifact_inventory.json"
    ]
    items = [
        dict(path=str(p.relative_to(HERE)), bytes=p.stat().st_size, sha256=experiment.sha(p))
        for p in files
    ]
    inventory = OUT / "artifact_inventory.json"
    others = sum(p.stat().st_size for p in files)
    own = 0
    for _ in range(12):
        experiment.save(
            inventory,
            dict(
                files=len(files) + 1,
                bytes=others + own,
                mib=(others + own) / 1048576,
                self_hash_omitted=True,
                items=items
                + [dict(path="outputs/artifact_inventory.json", bytes=own, sha256=None)],
            ),
        )
        actual = inventory.stat().st_size
        if actual == own:
            break
        own = actual
    else:
        raise AssertionError("Inventory self-size did not converge")
    print("Report saved", HERE / "README.md")


if __name__ == "__main__":
    main()
