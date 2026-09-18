"""Freeze five leave-one-group-out rankers plus expanded joint/order candidates."""

import json
from datetime import UTC, datetime
from pathlib import Path

from horse_racing.analysis.jeju_context_features import FEATURES
from scripts.run_jeju_joint_top3 import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_ablation_order_v6_20260916"
V5 = ROOT / "data/research/jeju_native_context_experiment_v5_20260916"
GROUPS = {
    "strength": [
        "rival_global_elo_mean",
        "rival_global_elo_std",
        "rival_global_elo_max",
        "rival_global_elo_gap",
        "rival_distance_elo_mean",
        "rival_distance_elo_max",
        "rival_distance_elo_gap",
        "previous_rival_elo_mean_3",
        "current_vs_previous_rival_elo",
    ],
    "pace": [
        "declared_horse_number_fraction",
        "historical_early_front_rate",
        "rival_early_pressure_count",
        "rival_early_pressure_mean",
        "field_early_ability_percentile",
        "jockey_early_front_rate",
        "lower_number_early_pressure_count",
        "higher_number_early_pressure_count",
        "last_early_rank",
        "last_late_rank",
        "last_early_late_gain",
        "closing_speed_quality_mean_3",
        "late_rank_mean_3",
        "early_late_gain_mean_3",
        "early_rank_percentile_3",
        "late_rank_percentile_3",
    ],
    "weight_jockey": [
        "last_burden_kg",
        "current_minus_last_burden_kg",
        "last_body_weight_kg",
        "body_weight_delta_kg",
        "body_weight_trend_3",
        "jockey_changed",
    ],
    "growth": [
        "current_minus_previous_elo",
        "progression_last3_vs_prev3",
        "best_last5_performance",
        "poor_last_but_good_late",
    ],
    "track": [
        "wet_performance_mean",
        "wet_performance_count",
        "dry_performance_mean",
        "dry_performance_count",
        "history_time_minus_same_race_median",
    ],
}


def main():
    p = json.loads((V5 / "protocol.json").read_text())
    flat = sum(GROUPS.values(), [])
    assert len(flat) == len(set(flat)) == 40 and set(flat) == set(FEATURES)
    full = p["base_features"] + p["context_features"] + p["form_features"]
    p.update(
        version="jeju_ablation_order_v6",
        created_at=datetime.now(UTC).isoformat(),
        v5_manifest_sha256=sha(V5 / "manifest.json"),
        groups=GROUPS,
        rank_candidates={
            f"R_NO_{name.upper()}": [f for f in full if f not in cols]
            for name, cols in GROUPS.items()
        },
        joint_features=full,
        joint_params={"hidden_dim": 16, "l2": 0.001, "max_iter": 100},
        joint_candidate="J_FORM",
        hybrid_candidate="HY_FORM_ORDER",
        references=["P_H3", "R_H3", "M0_H2", "J_H3_w10", "R_FORM", "HY_R_FORM"],
        counts={"estimator_fits": 48, "calibration_fits": 28, "bundles": 28, "reference_refits": 0},
        ablation="Remove only one NEW feature group; existing correlated H3 features remain. "
        "Estimates incremental group contribution, not causal effect or all-source removal.",
        expanded_order="J_FORM repeats frozen J_H3_w10 architecture/params/objective with108 "
        "features. HY_FORM_ORDER preserves frozen V5 R_FORM sets/marginals/picks and uses "
        "J_FORM order head. Compare against HY_R_FORM to isolate change of order learner.",
        joint_training="FIT joint_weight1; checkpoint minimizing TUNE joint NLL; "
        "100 iteration cap; "
        "seed17/43 mean scores. CAL two positive temperatures bounded log[-4,4]. "
        "Nonconvergence recorded; no extra iterations or retries chosen from EVAL.",
        reporting="13 models,715 races,6953horses2025; 709 nonboundary probability races. "
        "5000 paired race/day bootstrap draws seed17. All ablations vs R_FORM, J_FORM vs "
        "J_H3_w10, HY_FORM_ORDER vs HY_R_FORM and R_FORM. Exploratory unadjusted intervals. "
        "No2026 inference/outcomes or live206 declaration data admitted.",
    )
    # Remove obsolete V5-specific candidate descriptions instead of conflicting protocols.
    for key in ["candidates", "calibration", "selection"]:
        p.pop(key, None)
    p["rank_training"] = (
        "Same V5 LambdaRank params, FIT-only preprocessor, TUNE NDCG@3 early stop30; "
    )
    p["rank_training"] += "two seeds mean raw scores; CAL-only PL temperature, log[-4,4]."
    p["hybrid_calibration"] = (
        "Only conditional order temperature on CAL with fixed R_FORM set scores."
    )
    OUT.mkdir(exist_ok=True)
    with (OUT / "protocol.json").open("x") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    print("FROZEN", {k: len(v) for k, v in GROUPS.items()}, p["counts"])


if __name__ == "__main__":
    main()
