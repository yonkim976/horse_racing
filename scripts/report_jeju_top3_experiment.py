"""Summarize 2025 development predictions, paired uncertainty and error slices."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_top3_experiment_v1_20260915"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def main():
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    meta = pl.read_parquet(DATA / "races.parquet").select("race_id", "podium_tie", "boundary_tie")
    p = p.join(meta, on="race_id", validate="m:1")
    states = pl.read_parquet(DATA / "horse_states.parquet").join(
        p.select("race_id").unique(), on="race_id", how="semi"
    )
    state_meta = states.group_by("race_id").agg(
        pl.col("regime").first(),
        *[
            pl.col(feature).max().alias(alias)
            for feature, alias in [
                ("training_28d_observed_any", "training_observed"),
                ("medical_90d_observed_any", "medical_observed"),
                ("trial_observed_any", "trial_observed"),
                ("weight_observed_any", "weight_observed"),
            ]
        ],
    )
    p = p.join(state_meta, on="race_id", validate="m:1")
    models = sorted(p["model"].unique().to_list())
    ids = sorted(p["race_id"].unique().to_list())
    dates = p.filter(pl.col("model") == models[0]).sort("race_id")["event_date"].to_numpy()
    days, dayids = np.unique(dates, return_inverse=True)
    keys = ["set_hit", "order_hit", "set_nll", "order_nll"]
    values = np.array(
        [
            p.filter(pl.col("model") == m).sort("race_id").select(keys).to_numpy().astype(float)
            for m in models
        ]
    )
    rng = np.random.default_rng(17)
    draws = rng.integers(0, len(ids), size=(5000, len(ids)))
    race_means = np.stack([v[draws].mean(axis=1) for v in values])
    daydraws = rng.integers(0, len(days), size=(5000, len(days)))
    sizes = np.bincount(dayids)
    cluster_means = []
    for v in values:
        totals = np.zeros((len(days), len(keys)))
        np.add.at(totals, dayids, v)
        cluster_means.append(totals[daydraws].sum(axis=1) / sizes[daydraws].sum(axis=1)[:, None])
    cluster_means = np.array(cluster_means)
    summary = []
    for i, m in enumerate(models):
        s = p.filter(pl.col("model") == m)
        row = {
            "model": m,
            "races": len(s),
            "race_days": len(days),
            "coverage": 1.0,
            "set_hits": int(s["set_hit"].sum()),
            "order_hits": int(s["order_hit"].sum()),
            "order_given_set": float(s["order_hit"].sum() / s["set_hit"].sum())
            if s["set_hit"].sum()
            else None,
        }
        row["conditional_order_accuracy"] = row["order_given_set"]
        for k, key in enumerate(keys):
            row[key] = float(values[i, :, k].mean())
            row[key + "_race_ci"] = np.quantile(race_means[i, :, k], [0.025, 0.975]).tolist()
            row[key + "_day_ci"] = np.quantile(cluster_means[i, :, k], [0.025, 0.975]).tolist()
        for key in [
            "top1_hit",
            "winner_in3",
            "max_tie_expected_set_hit",
            "max_tie_expected_order_hit",
            "global_order_hit",
            "set_confidence",
            "order_confidence",
        ]:
            row[key] = float(s[key].mean())
        row["error_counts"] = {
            "set_miss": len(s) - int(s["set_hit"].sum()),
            "set_hit_order_miss": int(s["set_hit"].sum() - s["order_hit"].sum()),
            "order_hit": int(s["order_hit"].sum()),
        }
        row["overlap_counts"] = {
            str(n): int((s["compatible_max_overlap"] == n).sum()) for n in range(4)
        }
        summary.append(row)
    comparisons = []
    pairs = [(m, b) for m in models if m.startswith("M") for b in ["B1_elo", "B2_speed"]]
    pairs += [
        (f"{family}_{hi}", f"{family}_{lo}")
        for family in ["M0", "M1"]
        for hi, lo in [("H1", "H0"), ("H2", "H1")]
    ]
    pairs += [(f"M1_{arm}", f"M0_{arm}") for arm in ["H0", "H1", "H2"]]
    for candidate, reference in pairs:
        i, j = models.index(candidate), models.index(reference)
        row = {"candidate": candidate, "reference": reference}
        for k, key in enumerate(keys):
            row[key] = {
                "delta": float((values[i, :, k] - values[j, :, k]).mean()),
                "race_ci": np.quantile(
                    race_means[i, :, k] - race_means[j, :, k], [0.025, 0.975]
                ).tolist(),
                "day_ci": np.quantile(
                    cluster_means[i, :, k] - cluster_means[j, :, k], [0.025, 0.975]
                ).tolist(),
            }
        row["passes_predeclared_improvement_gate"] = all(
            row["order_hit"][c][0] > 0
            and row["set_hit"][c][0] > -0.01
            and row["set_nll"][c][1] < 0.01
            and row["order_nll"][c][1] < 0.01
            for c in ["race_ci", "day_ci"]
        )
        comparisons.append(row)
    slices = []
    p = p.with_columns(pl.col("event_date").str.slice(0, 7).alias("month"))
    for model in models:
        s = p.filter(pl.col("model") == model)
        for dimension in [
            "fold",
            "distance_m",
            "field_size",
            "month",
            "new_horse",
            "long_layoff",
            "has_dq_dnf",
            "podium_tie",
            "boundary_tie",
            "regime",
            "training_observed",
            "medical_observed",
            "trial_observed",
            "weight_observed",
        ]:
            for v in s[dimension].unique().to_list():
                part = s.filter(pl.col(dimension) == v)
                slices.append(
                    {
                        "model": model,
                        "dimension": dimension,
                        "value": str(v),
                        "races": len(part),
                        "set_hits": int(part["set_hit"].sum()),
                        "order_hits": int(part["order_hit"].sum()),
                        "set_accuracy": float(part["set_hit"].mean()),
                        "order_accuracy": float(part["order_hit"].mean()),
                        "set_nll": float(part["set_nll"].mean()),
                        "order_nll": float(part["order_nll"].mean()),
                    }
                )
    reliability = []
    for model in models:
        for target in ["set", "order"]:
            s = p.filter(pl.col("model") == model).sort(target + "_confidence")
            for bucket, idx in enumerate(np.array_split(np.arange(len(s)), 5), start=1):
                part = s[idx.tolist()]
                reliability.append(
                    {
                        "model": model,
                        "target": target,
                        "bucket": bucket,
                        "races": len(part),
                        "mean_confidence": float(part[target + "_confidence"].mean()),
                        "observed_accuracy": float(part[target + "_hit"].mean()),
                        "min_confidence": float(part[target + "_confidence"].min()),
                        "max_confidence": float(part[target + "_confidence"].max()),
                    }
                )
    for name, obj in [
        ("summary.json", summary),
        ("paired_comparisons.json", comparisons),
        ("subgroups.json", slices),
        ("reliability.json", reliability),
    ]:
        save(name, obj)
    pl.DataFrame(summary).write_parquet(OUT / "summary.parquet")
    importance = []
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as f:
            b = pickle.load(f)
        if "models" not in b:
            continue
        names = b["preprocessor"].names
        for number, model in enumerate(b["models"]):
            vals = (
                model.booster_.feature_importance(importance_type="gain")
                if hasattr(model, "booster_")
                else model.coef_
            )
            for feature, value in zip(names, vals, strict=True):
                importance.append(
                    {
                        "bundle": path.name,
                        "model": b["model_name"],
                        "member": number,
                        "feature": feature,
                        "value": float(value),
                        "type": "gain"
                        if hasattr(model, "booster_")
                        else "standardized_linear_coefficient",
                    }
                )
    save("feature_importance.json", importance)
    # Rank-specific error attribution excludes podium ties to keep ranks unique.
    best = max(summary, key=lambda r: (r["order_hit"], r["set_hit"]))["model"]
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() == 2025)
    ranks = {}
    for row in labels.iter_rows(named=True):
        ranks.setdefault(row["race_id"], {})[row["horse_id"]] = row["finish_position"]
    detail = {
        "model": best,
        "population": "non-podium-tied development races",
        "two_hit_races": 0,
        "two_hit_missed_rank1": 0,
        "two_hit_missed_rank2": 0,
        "two_hit_missed_rank3": 0,
        "two_hit_extra_horse_rank4": 0,
        "exact_set_order_patterns": {},
    }
    for row in p.filter((pl.col("model") == best) & ~pl.col("podium_tie")).iter_rows(named=True):
        selected = [ranks[row["race_id"]][h] for h in row["predicted_order"]]
        if row["compatible_max_overlap"] == 2:
            detail["two_hit_races"] += 1
            for rank in [1, 2, 3]:
                if rank not in selected:
                    detail[f"two_hit_missed_rank{rank}"] += 1
            if 4 in selected:
                detail["two_hit_extra_horse_rank4"] += 1
        if row["set_hit"]:
            key = "-".join(map(str, selected))
            detail["exact_set_order_patterns"][key] = (
                detail["exact_set_order_patterns"].get(key, 0) + 1
            )
    save("error_detail.json", detail)

    save(
        "analysis_metadata.json",
        {
            "iterations": 5000,
            "seed": 17,
            "days": len(days),
            "coverage": "715 identical races for all9 candidates",
            "ci": (
                "percentile paired race and race-day cluster; exploratory selected "
                "development candidates, no multiplicity adjustment"
            ),
            "2026_evaluated": False,
        },
    )
    print(
        pl.DataFrame(summary).select(
            "model",
            "races",
            "set_hits",
            "order_hits",
            "set_hit",
            "order_hit",
            "set_nll",
            "order_nll",
        )
    )
    save(
        "manifest.json",
        {
            str(f.relative_to(OUT)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(OUT.rglob("*"))
            if f.is_file() and f.name not in {"manifest.json", "verification.json"}
        },
    )


if __name__ == "__main__":
    main()
