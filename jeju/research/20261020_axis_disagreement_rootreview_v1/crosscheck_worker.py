"""Independent verification of Luna's frozen cohort, features, summaries and hashes."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "jeju/research/20261020_axis_disagreement_conditions_v1"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"


def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ids(s):
    return pd.to_numeric(s, errors="raise").astype("Int64").astype("string")


def main():
    w = pd.read_parquet(WORK / "race_pair_features.parquet").sort_values("race_id").reset_index(drop=True)
    r = pd.read_parquet(HERE / "ROOT_PAIR_FEATURES.parquet").sort_values("race_id").reset_index(drop=True)
    f = pd.read_parquet(FEATURES).set_index("api_record_id")
    assert f.index.is_unique
    assert len(w) == len(r) == 1477 and w.race_id.equals(r.race_id)
    mapped = {"same_hit": "same_pick", "same_miss": "same_pick", "model_only_hit": "model_only",
              "favourite_only_hit": "market_only", "both_hit": "both", "neither_hit": "neither"}
    assert w.case.equals(r.case.map(mapped))
    cells = 0
    feature_columns = []
    for side, prefix, key in [("axis", "m", "model_horse_id"), ("favorite", "f", "favourite_horse_id")]:
        assert ids(w[f"{side}_horse_id"]).equals(ids(r[key]))
        assert ids(w[f"{side}_api_record_id"]).equals(ids(r[f"{prefix}_api_record_id"]))
        frozen = f.loc[pd.to_numeric(w[f"{side}_api_record_id"]).to_numpy()].reset_index(drop=True)
        for col in f.columns:
            name = f"{side}_{col}"
            if name not in w:
                continue
            if col == "horse_id":
                assert ids(w[name]).equals(ids(frozen[col]))
            else:
                pd.testing.assert_series_equal(w[name], frozen[col], check_names=False,
                                               check_dtype=False, check_exact=False, atol=1e-12, rtol=1e-12)
            cells += len(w)
            feature_columns.append(name)
        for wc, rc in [(f"{side}_p_top3", f"{prefix}_p_top3"), (f"{side}_score", f"{prefix}_score")]:
            np.testing.assert_allclose(w[wc], r[rc], atol=1e-12, rtol=1e-12)

    # Reconstruct every worker condition row from verified pair rows and independent case labels.
    checked_rows = 0
    for source in [WORK / "condition_summary.csv", WORK / "condition_summary_by_period.csv"]:
        if not source.exists():
            if source.name == "condition_summary.csv":
                raise FileNotFoundError(source)
            continue
        table = pd.read_csv(source, keep_default_na=False)
        for _, row in table.iterrows():
            part = w if row.population == "unique_favorite_background_1477" else w.loc[w.disagreement]
            if "period" in row.index:
                value = str(row.period)
                if value in ["2024", "2025", "2026"]:
                    part = part.loc[part.year.eq(int(value))]
                elif value in ["2024-25", "2024-25_pooled"]:
                    part = part.loc[part.year.le(2025)]
                elif value in ["2026_partial", "2026-partial"]:
                    part = part.loc[part.year.eq(2026)]
                elif value not in ["all", "all_periods"]:
                    raise AssertionError(f"Unknown period: {value}")
            if row.condition != "_overall":
                vals = part[row.condition].map(lambda v: "missing" if pd.isna(v) else str(int(v)) if isinstance(v, (float, np.floating)) and float(v).is_integer() else str(v))
                part = part.loc[vals.eq(str(row.condition_value))]
            assert len(part) == int(row.n), (source.name, row.condition, row.condition_value)
            for case in ["model_only", "market_only", "both", "neither", "same_pick"]:
                assert int(part.case.eq(case).sum()) == int(row[f"{case}_n"])
            for side, label in [("axis", "model"), ("favorite", "favorite")]:
                assert int(part[f"{side}_top3"].sum()) == int(row[f"{label}_hit_n"])
                assert abs(part[f"{side}_top3"].mean() - float(row[f"{label}_hit_rate"])) < 1e-12
            checked_rows += 1

    # Independently generated bins match the worker on each race, apart from same-pick rank=1.
    condition_map = {"m_career_bin": "axis_observed_starts_bin", "f_career_bin": "favorite_observed_starts_bin",
                     "m_n5_bin": "axis_valid_n5_bin", "f_n5_bin": "favorite_valid_n5_bin",
                     "m_gap_bin": "axis_days_since_start_bin", "f_gap_bin": "favorite_days_since_start_bin",
                     "p_gap_bin": "p_gap_bin", "f_rank_bin": "favorite_model_rank_bin",
                     "paired_mean5_direction": "paired_mean5_status", "paired_previous_top3": "previous_top3_pair"}
    labels = {">=5": "5+", ">=4": "4+", "<.05": "<0.05", ".05-.10": "0.05-<0.10", ">=.10": ">=0.10",
              "model_no_slower": "axis_mean5_le_favorite", "model_slower": "axis_mean5_gt_favorite",
              "0_0": "axis_no_favorite_no", "0_1": "axis_no_favorite_yes",
              "1_0": "axis_yes_favorite_no", "1_1": "axis_yes_favorite_yes"}
    discord = ~r.same_pick
    for rc, wc in condition_map.items():
        translated = r.loc[discord, rc].map(lambda v: labels.get(str(v), str(v))).astype("string")
        assert translated.equals(w.loc[discord, wc].astype("string")), (rc, wc)

    distributions = pd.read_csv(WORK / "exclusive_distribution.csv")
    checked_distribution_rows = 0
    for _, row in distributions.loc[distributions.value_type.eq("numeric")].iterrows():
        part = w.loc[w.case.eq(row.case)]
        if row.side == "race_pair":
            v = part[row.feature]
        elif row.side == "axis_minus_favorite":
            v = part[f"axis_{row.feature}"] - part[f"favorite_{row.feature}"]
        else:
            v = part[f"{row.side}_{row.feature}"]
        v = pd.to_numeric(v, errors="coerce").dropna()
        assert len(v) == int(row.n)
        for col, value in [("mean", v.mean()), ("median", v.median()), ("q25", v.quantile(.25)), ("q75", v.quantile(.75))]:
            if len(v):
                assert np.isclose(value, row[col], atol=1e-12, rtol=1e-12)
            else:
                assert pd.isna(row[col])
        checked_distribution_rows += 1

    pred = pd.read_parquet(ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet")
    pred = pred.sort_values(["race_id", "score", "horse_number"], ascending=[True, False, True], kind="stable")
    pred["rank"] = pred.groupby("race_id").cumcount() + 1
    pool_table = pd.read_csv(WORK / "model_topk_pool_diagnostic.csv")
    for _, row in pool_table.iterrows():
        part = w.loc[w.disagreement] if row.population == "all_disagreements_678" else w.loc[w.case.eq(row.population.removeprefix("case_"))]
        count = pred.loc[pred["rank"].le(int(row.model_top_k))].groupby("race_id").y.sum()
        actual = int(part.race_id.map(count).gt(0).sum())
        assert len(part) == int(row.race_n) and actual == int(row.races_with_any_actual_top3_in_model_top_k)
        assert abs(actual / len(part) - row.candidate_pool_coverage_rate) < 1e-12

    manifest = json.loads((WORK / "OUTPUT_MANIFEST.json").read_text())
    for item in manifest["artifacts"]:
        p = WORK / item["path"]
        assert p.stat().st_size == item["size_bytes"] and digest(p) == item["sha256"], p
    result = {"passed": True, "paired_races": len(w), "verified_frozen_feature_cells": cells,
              "feature_columns": feature_columns, "independent_bin_columns": len(condition_map),
              "condition_summary_rows_checked": checked_rows, "numeric_distribution_rows_checked": checked_distribution_rows,
              "candidate_pool_summary_rows_checked": len(pool_table),
              "worker_artifact_hashes_checked": len(manifest["artifacts"]),
              "worker_manifest_sha256": digest(WORK / "OUTPUT_MANIFEST.json"),
              "database_opened": False, "models_fitted": 0}
    with (HERE / "ROOT_WORKER_CROSSCHECK.json").open("w") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
    print(json.dumps({k:v for k,v in result.items() if k != "feature_columns"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
