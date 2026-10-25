"""Fixed-bucket, no-fit independent checks for the F1_STYLE6 disagreement review."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "jeju/research/20261020_axis_disagreement_review_v1"
SOURCE = ROOT / "jeju/research/20261020_model_axis_vs_win_favorite_v1"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
LEDGER = SOURCE / "runner_ledger.csv"
SELECTED = SOURCE / "selected_rows.csv"
SOURCE_MANIFEST = SOURCE / "manifest.json"
DEFINITION_SOURCES = [
    ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py",
    ROOT / "jeju/research/20261009_finish_history_ablation_v1/CONTRACT.md",
    ROOT / "jeju/research/20261009_finish_history_ablation_v1/prepare.py",
    ROOT / "jeju/research/20261010_style_history_ablation_v1/CONTRACT.md",
    ROOT / "jeju/research/20261010_style_history_ablation_v1/prepare.py",
    ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json",
]
REVIEWED_MAIN_ARTIFACTS = [
    ROOT / "jeju/research/20261020_axis_disagreement_conditions_v1/analysis.py",
    ROOT / "jeju/research/20261020_axis_disagreement_conditions_v1/README.md",
    ROOT / "jeju/research/20261020_axis_disagreement_conditions_v1/REPORT.json",
    ROOT / "jeju/research/20261020_axis_disagreement_conditions_v1/OUTPUT_MANIFEST.json",
]


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def four_case(axis_hit: bool, favorite_hit: bool) -> str:
    return {
        (True, False): "model_only",
        (False, True): "market_only",
        (True, True): "both",
        (False, False): "neither",
    }[(bool(axis_hit), bool(favorite_hit))]


def case_counts(group: pd.DataFrame) -> dict[str, int]:
    counts = group["case"].value_counts()
    return {name: int(counts.get(name, 0)) for name in ["model_only", "market_only", "both", "neither"]}


def main() -> None:
    files = [FEATURES, LEDGER, SELECTED, SOURCE_MANIFEST]
    hashes = {str(path.relative_to(ROOT)): {"sha256": sha256(path), "size_bytes": path.stat().st_size} for path in files}
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    for name in ["selected_rows.csv", "runner_ledger.csv"]:
        locked = source_manifest["artifacts"][name]
        if sha256(SOURCE / name) != locked["sha256"] or (SOURCE / name).stat().st_size != locked["bytes"]:
            raise RuntimeError(f"Frozen source manifest mismatch: {name}")
    definition_hashes = {str(path.relative_to(ROOT)): {"sha256": sha256(path), "size_bytes": path.stat().st_size}
                         for path in DEFINITION_SOURCES}
    reviewed_artifact_hashes = {str(path.relative_to(ROOT)): {"sha256": sha256(path), "size_bytes": path.stat().st_size}
                                for path in REVIEWED_MAIN_ARTIFACTS}

    selected = pd.read_csv(SELECTED)
    ledger = pd.read_csv(LEDGER)
    selected = selected.loc[selected.model.eq("F1_STYLE6")].copy()
    ledger = ledger.loc[ledger.model.eq("F1_STYLE6")].copy()
    features = pd.read_parquet(FEATURES)
    assert selected.race_id.is_unique and ledger.api_record_id.is_unique
    assert features.api_record_id.is_unique

    # Build the fixed 678 disagreement rows from the frozen selection and outcomes.
    selected = selected.loc[selected.unique_favorite_horse_id.notna()].copy()
    pair = selected.loc[selected.axis_same_as_unique_favorite.eq(False)].copy()
    pair["case"] = [four_case(a, f) for a, f in zip(pair.axis_top3, pair.unique_favorite_top3)]
    expected = {"model_only": 126, "market_only": 248, "both": 173, "neither": 131}
    assert case_counts(pair) == expected

    # Inspect every market favorite's exact T-2 saved features. This verifies what
    # valid_n5 == 0 means here instead of assuming it means a debut.
    fav = pair[["race_id", "race_date", "year", "distance_m", "unique_favorite_horse_id", "case"]].merge(
        ledger[["race_id", "horse_id", "api_record_id", "horse_number", "actual_top3"]],
        left_on=["race_id", "unique_favorite_horse_id"],
        right_on=["race_id", "horse_id"],
        validate="one_to_one",
    )
    fav = fav.merge(
        features[["api_record_id", "race_id", "horse_id", "observed_starts", "same_starts", "valid_n5", "same_valid_times",
                  "previous_top3", "history_cutoff", "latest_history_date"]].rename(
                      columns={"race_id": "feature_race_id", "horse_id": "feature_horse_id"}),
        on="api_record_id", validate="one_to_one",
    )
    assert len(fav) == len(pair) == 678
    assert fav.race_id.astype("string").eq(fav.feature_race_id.astype("string")).all()
    assert fav.horse_id.astype("string").eq(fav.feature_horse_id.astype("string")).all()
    cutoff = (pd.to_datetime(fav.race_date) - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    assert fav.history_cutoff.astype(str).equals(cutoff)
    available = fav.latest_history_date.notna()
    assert fav.loc[available, "latest_history_date"].astype(str).le(cutoff[available]).all()
    zero_n5 = fav.loc[fav.valid_n5.eq(0)].copy()
    assert len(zero_n5) == 158
    assert zero_n5.same_starts.eq(0).all()
    zero_n5["history_scope"] = np.where(zero_n5.observed_starts.eq(0), "stored_observed_starts_zero", "other_distance_starts_only")
    assert zero_n5.history_scope.value_counts().to_dict() == {"other_distance_starts_only": 124, "stored_observed_starts_zero": 34}

    zero_year_rows = []
    for (year, scope), group in zero_n5.groupby(["year", "history_scope"], sort=True):
        zero_year_rows.append({
            "year": int(year), "history_scope": scope, "n": int(len(group)), **case_counts(group),
            "model_hit_n": int(group.case.isin(["model_only", "both"]).sum()),
            "favorite_hit_n": int(group.case.isin(["market_only", "both"]).sum()),
        })
    zero_year = pd.DataFrame(zero_year_rows)

    # For market-only races, count actual Top3 runners captured by the frozen
    # baseline model's top 3 and top 5. This is retrospective fixed-pool coverage,
    # not an executable reranker result or a prospective ceiling claim.
    market_only = pair.loc[pair.case.eq("market_only"), ["race_id", "year"]].copy()
    runners = ledger.loc[ledger.race_id.isin(market_only.race_id)].copy()
    runners = runners.merge(market_only, on=["race_id", "year"], validate="many_to_one")
    runners = runners.sort_values(["race_id", "score", "horse_number"], ascending=[True, False, True], kind="stable")
    runners["score_rank"] = runners.groupby("race_id", sort=False).cumcount() + 1
    assert runners.groupby("race_id").score_rank.max().ge(5).all()
    coverage = runners.assign(
        top3_hit_runner=runners.score_rank.le(3) & runners.actual_top3,
        top5_hit_runner=runners.score_rank.le(5) & runners.actual_top3,
    ).groupby(["race_id", "year"], as_index=False).agg(
        top3_actual_count=("top3_hit_runner", "sum"),
        top5_actual_count=("top5_hit_runner", "sum"),
        actual_top3_total=("actual_top3", "sum"),
        model_top1_actual=("actual_top3", "first"),
    )
    # Top1 is separately checked against the selected axis row to ensure score-rank tie handling.
    axis_ids = pair[["race_id", "axis_horse_id", "axis_top3"]].rename(columns={"axis_horse_id": "horse_id", "axis_top3": "axis_top3"})
    top1 = runners.loc[runners.score_rank.eq(1), ["race_id", "horse_id", "actual_top3"]].merge(
        axis_ids, on=["race_id", "horse_id"], validate="one_to_one"
    )
    assert len(top1) == 248 and top1.actual_top3.equals(top1.axis_top3)
    coverage = coverage.drop(columns="model_top1_actual")
    coverage_rows = []
    for year, group in coverage.groupby("year", sort=True):
        for k, col, max_count in [(3, "top3_actual_count", 2), (5, "top5_actual_count", 3)]:
            counts = group[col].value_counts().to_dict()
            coverage_rows.append({
                "year": int(year), "model_top_k": k, "n_market_only_races": int(len(group)),
                "races_with_zero_actual_top3_in_topk": int(counts.get(0, 0)),
                "races_with_one_actual_top3_in_topk": int(counts.get(1, 0)),
                "races_with_two_actual_top3_in_topk": int(counts.get(2, 0)) if max_count >= 2 else 0,
                "races_with_three_actual_top3_in_topk": int(counts.get(3, 0)) if k == 5 else 0,
                "races_with_at_least_one_actual_top3_in_topk": int(group[col].gt(0).sum()),
                "races_with_all_actual_top3_in_topk": int(group[col].eq(group.actual_top3_total).sum()),
            })
    coverage_summary = pd.DataFrame(coverage_rows)
    assert coverage_summary.loc[coverage_summary.model_top_k.eq(3), "n_market_only_races"].sum() == 248
    assert coverage_summary.loc[coverage_summary.model_top_k.eq(5), "n_market_only_races"].sum() == 248

    result = {
        "scope": "read-only fixed descriptive checks; no DB access, fitting, threshold search, or source modification",
        "source_hashes": hashes,
        "reviewed_definition_source_hashes": definition_hashes,
        "reviewed_main_artifact_hashes": reviewed_artifact_hashes,
        "disagreement_four_state_counts_n678": expected,
        "favorite_valid_n5_zero": {
            "n": int(len(zero_n5)), "same_starts_all_zero": bool(zero_n5.same_starts.eq(0).all()),
            "history_scope_counts": {k: int(v) for k, v in zero_n5.history_scope.value_counts().items()},
            "by_year_and_scope": zero_year.to_dict(orient="records"),
            "interpretation": "In this 678-row disagreement cohort, all 158 favorites with valid_n5=0 also have same_starts=0; 34 have stored observed_starts=0 (no prior start observed in this feature source), and 124 have prior starts only at other distances. Do not infer lifetime debut status, and do not call all 158 debutants.",
        },
        "market_only_model_fixed_pool_topk": {
            "n": int(len(market_only)),
            "by_year_topk_distribution": coverage_summary.to_dict(orient="records"),
            "all_rows": {
                "top3_actual_count_distribution": {str(k): int(v) for k,v in coverage.top3_actual_count.value_counts().sort_index().items()},
                "top5_actual_count_distribution": {str(k): int(v) for k,v in coverage.top5_actual_count.value_counts().sort_index().items()},
                "top3_at_least_one_race_n": int(coverage.top3_actual_count.gt(0).sum()),
                "top5_at_least_one_race_n": int(coverage.top5_actual_count.gt(0).sum()),
                "top5_all_three_race_n": int(coverage.top5_actual_count.eq(coverage.actual_top3_total).sum()),
            },
            "interpretation": "Retrospective fixed-pool coverage diagnostic. Since these are market-only races, model rank 1 is a miss by construction; coverage of actual Top3 runners at ranks 2-5 distinguishes candidate-ordering errors from runners outside a short fixed candidate pool, but does not establish future reranker performance.",
        },
    }
    target = OUT / "INDEPENDENT_DIAGNOSTICS.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "zero_n5_by_year_scope": zero_year.to_dict(orient="records"),
        "market_only_topk_by_year": coverage_summary.to_dict(orient="records"),
        "market_only_overall_top3_distribution": result["market_only_model_fixed_pool_topk"]["all_rows"]["top3_actual_count_distribution"],
        "market_only_overall_top5_distribution": result["market_only_model_fixed_pool_topk"]["all_rows"]["top5_actual_count_distribution"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
