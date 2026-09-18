"""Predefined entry-level group audit with day-cluster uncertainty; descriptive only."""

import json

import numpy as np
import polars as pl

from scripts.run_jeju_experience_calibration import OUT, save


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    ctx = pl.read_parquet(OUT / "audit_context.parquet").select(
        "race_id", "horse_id", "experience_bin", "section_missing"
    )
    fixed = h.filter(pl.col("model") == "HY_R_FORM").select(
        "race_id", "horse_id", pl.col("selected").alias("baseline_selected")
    )
    full = h.join(ctx, on=["race_id", "horse_id"], validate="m:1").join(
        fixed, on=["race_id", "horse_id"], validate="m:1"
    )
    frame = full.filter(~pl.col("boundary_tie"))
    days = sorted(frame["event_date"].unique())
    lookup = {d: i for i, d in enumerate(days)}
    draw = np.random.default_rng(17).integers(0, len(days), size=(5000, len(days)))
    records = []
    reliability = []
    overalls = []
    for model in sorted(frame["model"].unique()):
        for population in ["all_entries", "baseline_selected"]:
            part = frame.filter(pl.col("model") == model)
            if population == "baseline_selected":
                part = part.filter(pl.col("baseline_selected"))
            strata = [("overall", "all", part)]
            for val in protocol["experience_bins"]:
                strata.append(
                    ("distance_experience", val, part.filter(pl.col("experience_bin") == val))
                )
            for miss in [False, True]:
                strata.append(
                    (
                        "section_missing",
                        str(miss).lower(),
                        part.filter(pl.col("section_missing") == miss),
                    )
                )
                for val in protocol["experience_bins"]:
                    strata.append(
                        (
                            "experience_x_section",
                            val + "|" + str(miss).lower(),
                            part.filter(
                                (pl.col("experience_bin") == val)
                                & (pl.col("section_missing") == miss)
                            ),
                        )
                    )
            for dim, value, s in strata:
                row = dict(
                    model=model,
                    population=population,
                    dimension=dim,
                    value=value,
                    entries=len(s),
                    races=s["race_id"].n_unique(),
                    days=s["event_date"].n_unique(),
                )
                row["sparse"] = (
                    len(s) < protocol["audit_min_entries"]
                    or row["days"] < protocol["audit_min_days"]
                )
                if len(s):
                    p = s["pl_place_probability"].to_numpy()
                    y = s["official_top3"].to_numpy()
                    q = np.clip(p, 1e-12, 1 - 1e-12)
                    residual = p - y
                    totals = np.zeros(len(days))
                    counts = np.zeros(len(days))
                    idx = np.array([lookup[d] for d in s["event_date"]])
                    np.add.at(totals, idx, residual)
                    np.add.at(counts, idx, 1)
                    den = counts[draw].sum(axis=1)
                    num = totals[draw].sum(axis=1)
                    boot = num[den > 0] / den[den > 0]
                    row.update(
                        hits=int(y.sum()),
                        mean_probability=float(p.mean()),
                        observed_rate=float(y.mean()),
                        overprediction=float(residual.mean()),
                        brier=float(np.mean((p - y) ** 2)),
                        logloss=float(np.mean(-y * np.log(q) - (1 - y) * np.log1p(-q))),
                        bias_day_ci=np.quantile(boot, [0.025, 0.975]).tolist(),
                        defined_bootstrap_draws=len(boot),
                    )
                else:
                    row.update(
                        hits=0,
                        mean_probability=None,
                        observed_rate=None,
                        overprediction=None,
                        brier=None,
                        logloss=None,
                        bias_day_ci=None,
                        defined_bootstrap_draws=0,
                    )
                records.append(row)
            p = part["pl_place_probability"].to_numpy()
            y = part["official_top3"].to_numpy()
            ece = 0.0
            bins = protocol["probability_bins"]
            for i, (lo, hi) in enumerate(zip(bins[:-1], bins[1:], strict=True)):
                mask = (p >= lo) & ((p <= hi) if i == len(bins) - 2 else (p < hi))
                n = int(mask.sum())
                mean = float(p[mask].mean()) if n else None
                rate = float(y[mask].mean()) if n else None
                if n:
                    ece += n / len(p) * abs(mean - rate)
                reliability.append(
                    dict(
                        model=model,
                        population=population,
                        lower=lo,
                        upper=hi,
                        entries=n,
                        mean_probability=mean,
                        observed_rate=rate,
                    )
                )
            overalls.append(
                dict(
                    model=model,
                    population=population,
                    entries=len(part),
                    races=part["race_id"].n_unique(),
                    ece_fixed_bins=ece,
                )
            )
    save("experience_audit.json", records)
    save("experience_reliability.json", reliability)
    save(
        "experience_audit_metadata.json",
        dict(
            population="Nonboundary EVAL only",
            entries_per_model=int(frame.filter(pl.col("model") == "HY_R_FORM").height),
            races=709,
            weighted="Entry-weighted within subgroup; performance report is equal race weight.",
            bootstrap="5000 draws of the same full 98 race days; ratio-of-sums; undefined draws omitted.",  # noqa: E501
            overall_bias="Coherent probabilities and exactly3 labels imply overall residual zero; "
            "subgroup/confidence-bin/selected-horse diagnostics are essential.",
            summary=overalls,
            probability_bins=protocol["probability_bins"],
            baseline_selected="Fixed original selected horses for every candidate, not newly selected horses.",  # noqa: E501
        ),
    )
    print(json.dumps(overalls, indent=2))


if __name__ == "__main__":
    main()
