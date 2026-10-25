"""Frozen-feature support and candidate-pool audit; no fitting or rule search."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PAIR = HERE / "ROOT_PAIR_FEATURES.parquet"
PRED = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"


def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    pairs = pd.read_parquet(PAIR)
    d = pairs.loc[~pairs.same_pick].copy()
    features = pd.read_parquet(FEATURES, columns=["api_record_id", "same_starts"])
    zero = d.loc[d.f_valid_n5.eq(0)].merge(
        features, left_on="f_api_record_id", right_on="api_record_id", validate="one_to_one")
    assert len(zero) == 158 and zero.same_starts.eq(0).all()
    zero["history_group"] = np.where(zero.f_observed_starts.eq(0), "no_observed_start", "other_distance_history_only")
    support = []
    for group, g in zero.groupby("history_group"):
        for period, part in [("all", g), ("2024-25", g.loc[g.year.le(2025)]), ("2026", g.loc[g.year.eq(2026)])]:
            support.append({"history_group": group, "period": period, "n": len(part),
                            "cases": part.case.value_counts().to_dict()})

    pred = pd.read_parquet(PRED).sort_values(
        ["race_id", "score", "horse_number"], ascending=[True, False, True], kind="stable")
    pred["rank"] = pred.groupby("race_id").cumcount() + 1
    mo = d.loc[d.case.eq("favourite_only_hit"), ["race_id", "year"]]
    pool = mo.copy()
    for k in [3, 5]:
        count = pred.loc[pred["rank"].le(k)].groupby("race_id").y.sum()
        pool[f"actual_top3_in_top{k}"] = pool.race_id.map(count).astype(int)
    assert len(pool) == 248
    assert pool.actual_top3_in_top3.value_counts().to_dict() == {1: 149, 2: 69, 0: 30}
    assert pool.actual_top3_in_top5.gt(0).sum() == 245
    pool_summary = []
    for period, part in [("all", pool), ("2024-25", pool.loc[pool.year.le(2025)]), ("2026", pool.loc[pool.year.eq(2026)])]:
        pool_summary.append({"period": period, "n": len(part),
                             "top3_contains_any_actual_top3": int(part.actual_top3_in_top3.gt(0).sum()),
                             "top5_contains_any_actual_top3": int(part.actual_top3_in_top5.gt(0).sum()),
                             "top5_contains_all_actual_top3": int(part.actual_top3_in_top5.eq(3).sum()),
                             "top3_actual_count_distribution": part.actual_top3_in_top3.value_counts().sort_index().to_dict()})

    # Descriptive paired difference, conditioned on this already examined cohort.
    d["hit_difference"] = d.model_hit.astype(int) - d.favourite_hit.astype(int)
    dates = d.groupby("race_date").hit_difference.agg(["sum", "count"]).sort_index()
    rng = np.random.default_rng(20261020)
    indices = rng.integers(0, len(dates), size=(5000, len(dates)))
    sums, counts = dates["sum"].to_numpy(), dates["count"].to_numpy()
    draws = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    report = {
        "passed": True,
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in [PAIR, PRED, FEATURES]},
        "favorite_valid_n5_zero": support,
        "market_only_candidate_pool": pool_summary,
        "conditional_model_minus_favorite_top3": {
            "races": len(d), "dates": len(dates), "point": float(d.hit_difference.mean()),
            "date_cluster_bootstrap_percentile95": np.quantile(draws, [.025, .975]).tolist(),
            "seed": 20261020, "replicates": 5000},
        "limitations": [
            "Pool coverage is hindsight oracle availability, not reranker accuracy.",
            "All periods were previously examined; no fresh validation.",
            "Final favorite identity is unavailable as a pre-race input in this project.",
            "Zero observed starts is a frozen-history definition, not a proven lifetime debut.",
            "Conditional uncertainty does not establish causal feature effects or subgroup rules."],
        "database_opened": False, "models_fitted": 0}
    with (HERE / "ROOT_ADDITIONAL_DIAGNOSTICS.json").open("x") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    pool.to_csv(HERE / "ROOT_MARKET_ONLY_POOL.csv", index=False, mode="x")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
