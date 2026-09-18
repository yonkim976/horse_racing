"""Three-target development report with fixed-reference paired uncertainty."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_joint_top3_v4_20260916"


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    frame = pl.read_parquet(OUT / "race_predictions.parquet")
    models = sorted(frame["model"].unique().to_list())
    keys = [
        "pick_hit",
        "set_hit",
        "order_hit",
        "place_brier",
        "place_logloss",
        "set_nll",
        "order_nll",
    ]
    arrays = []
    for m in models:
        s = frame.filter(pl.col("model") == m).sort("race_id")
        a = s.select(keys).to_numpy().astype(float)
        a[s["boundary_tie"].to_numpy(), 3:5] = np.nan
        arrays.append(a)
    values = np.array(arrays)
    first = frame.filter(pl.col("model") == models[0]).sort("race_id")
    dates = first["event_date"].to_numpy()
    days, dayids = np.unique(dates, return_inverse=True)
    rng = np.random.default_rng(17)
    racedraw = rng.integers(0, len(first), size=(5000, len(first)))
    daydraw = rng.integers(0, len(days), size=(5000, len(days)))
    race_boot, day_boot = [], []
    for a in values:
        race_boot.append(np.nanmean(a[racedraw], axis=1))
        totals = np.zeros((len(days), len(keys)))
        counts = np.zeros_like(totals)
        np.add.at(totals, dayids, np.nan_to_num(a))
        np.add.at(counts, dayids, np.isfinite(a).astype(float))
        day_boot.append(totals[daydraw].sum(axis=1) / counts[daydraw].sum(axis=1))
    race_boot = np.array(race_boot)
    day_boot = np.array(day_boot)
    summary = []
    for i, m in enumerate(models):
        s = frame.filter(pl.col("model") == m)
        nt = s.filter(~pl.col("boundary_tie"))
        row = {
            "model": m,
            "races": len(s),
            "race_days": len(days),
            "probability_races": len(nt),
            "single_hits": int(s["pick_hit"].sum()),
            "set_hits": int(s["set_hit"].sum()),
            "order_hits": int(s["order_hit"].sum()),
            "order_hit_given_set_hit": float(s["order_hit"].sum() / s["set_hit"].sum())
            if s["set_hit"].sum()
            else None,
            "tie_expected_pick_hit": float(s["tie_expected_pick_hit"].mean()),
            "mean_pick_probability": float(s["pick_probability"].mean()),
        }
        for j, k in enumerate(keys):
            row[k] = float(np.nanmean(values[i, :, j]))
            row[k + "_race_ci"] = np.quantile(race_boot[i, :, j], [0.025, 0.975]).tolist()
            row[k + "_day_ci"] = np.quantile(day_boot[i, :, j], [0.025, 0.975]).tolist()
        if m.startswith("P_"):
            row.update(
                native_brier=float(nt["native_brier"].mean()),
                native_logloss=float(nt["native_logloss"].mean()),
                mean_native_pick_probability=float(s["native_pick_probability"].mean()),
            )
        else:
            row.update(native_brier=None, native_logloss=None, mean_native_pick_probability=None)
        summary.append(row)
    comparisons = []
    pairs = [
        (candidate, reference)
        for candidate in ["J_H3_w05", "J_H3_w10"]
        for reference in ["M0_H2", "P_H3", "R_H3"]
    ]
    pairs += [("J_H3_w05", "J_H3_w10")]
    for candidate, reference in pairs:
        i, ref = models.index(candidate), models.index(reference)
        row = {
            "candidate": candidate,
            "reference": reference,
            "interpretation": "exploratory unadjusted development comparisons",
        }
        for j, k in enumerate(keys):
            row[k] = {
                "delta": float(np.nanmean(values[i, :, j] - values[ref, :, j])),
                "race_ci": np.quantile(
                    race_boot[i, :, j] - race_boot[ref, :, j], [0.025, 0.975]
                ).tolist(),
                "day_ci": np.quantile(
                    day_boot[i, :, j] - day_boot[ref, :, j], [0.025, 0.975]
                ).tolist(),
            }
        comparisons.append(row)
    slices = []
    reliability = []
    thresholds = []
    for m in models:
        s = frame.filter(pl.col("model") == m)
        for dim in ["fold", "distance_m", "field_size", "podium_tie", "boundary_tie"]:
            for val in sorted(s[dim].unique().to_list()):
                part = s.filter(pl.col(dim) == val)
                slices.append(
                    {
                        "model": m,
                        "dimension": dim,
                        "value": str(val),
                        "races": len(part),
                        "single_hits": int(part["pick_hit"].sum()),
                        "set_hits": int(part["set_hit"].sum()),
                        "order_hits": int(part["order_hit"].sum()),
                    }
                )
        for source, col in [("PL", "pick_probability"), ("native", "native_pick_probability")]:
            if source == "native" and not m.startswith("P_"):
                continue
            # Probability reliability uses the same non-boundary population.
            usable = s.filter(~pl.col("boundary_tie")).sort(col)
            for bucket, idx in enumerate(np.array_split(np.arange(len(usable)), 5), 1):
                part = usable[idx.tolist()]
                reliability.append(
                    {
                        "model": m,
                        "source": "joint_factorized"
                        if source == "PL" and m.startswith("J_")
                        else source,
                        "bucket": bucket,
                        "races": len(part),
                        "hits": int(part["pick_hit"].sum()),
                        "mean_probability": float(part[col].mean()),
                        "hit_rate": float(part["pick_hit"].mean()),
                        "min_probability": float(part[col].min()),
                        "max_probability": float(part[col].max()),
                    }
                )
            for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
                part = s.filter(pl.col(col) >= threshold)
                thresholds.append(
                    {
                        "model": m,
                        "source": "joint_factorized"
                        if source == "PL" and m.startswith("J_")
                        else source,
                        "threshold": threshold,
                        "races": len(part),
                        "coverage": len(part) / len(s),
                        "hits": int(part["pick_hit"].sum()),
                        "hit_rate": float(part["pick_hit"].mean()) if len(part) else None,
                        "interpretation": (
                            "predeclared threshold diagnostic; not a validated selective policy"
                        ),
                    }
                )
    for name, value in [
        ("summary.json", summary),
        ("paired_comparisons.json", comparisons),
        ("subgroups.json", slices),
        ("reliability.json", reliability),
        ("confidence_thresholds.json", thresholds),
    ]:
        save(name, value)
    save(
        "analysis_metadata.json",
        {
            "models": len(models),
            "common_races": 715,
            "race_days": len(days),
            "excluded_boundary_races_for_probability": int(first["boundary_tie"].sum()),
            "bootstrap_iterations": 5000,
            "seed": 17,
            "2026_evaluated": False,
            "references": ["M0_H2", "P_H3", "R_H3"],
            "single_target": "one selected horse officially top3",
            "probability_population": (
                "same nonboundary races for coherent joint marginals and native "
                "Brier/logloss/reliability; hitandthresholdcountsall715"
            ),
        },
    )
    print(
        pl.DataFrame(summary).select(
            "model",
            "single_hits",
            "pick_hit",
            "set_hits",
            "set_hit",
            "order_hits",
            "order_hit",
            "place_brier",
            "native_brier",
        )
    )


if __name__ == "__main__":
    main()
