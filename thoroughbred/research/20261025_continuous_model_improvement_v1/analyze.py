"""Fixed-budget paired summaries; no model selection using evaluation labels."""

import json
import numpy as np
import pandas as pd
import research as c

METRICS = [
    "axis_top3",
    "quinella_one",
    "quinella_three",
    "qpl_one",
    "qpl_three",
    "trio_six",
    "runner_brier",
    "trio_logloss",
    "ordered_logloss",
]


def baseline():
    old = pd.read_parquet(c.PREVIOUS / "outputs/race_metrics.parquet")
    old = old[old.variant.eq("personal_t2")].copy()
    f = c.base_frame()
    six = {}
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            folder = c.PREVIOUS / "outputs/models" / f"personal_t2_{meet}_{year}"
            meta = json.loads((folder / "metadata.json").read_text())
            scores = (
                pd.read_parquet(folder / "scores.parquet")
                .query("phase=='evaluation'")
                .set_index("row_number")
                .score
            )
            for key, g in f[f.meet.eq(meet) & f.year.eq(year)].groupby("race_key", sort=False):
                score = g.row_number.map(scores).to_numpy()
                q = c.previous.old.prob.trio_distribution(score, meta["temperature"])
                triples = c.previous.old.prob.support(len(g))[0]
                take = np.argsort(-np.round(q, 12), kind="stable")[:6]
                truth = g.outcome.between(1, 3).to_numpy()
                six[key] = int(truth[triples[take]].all(axis=1).any())
    old["trio_six"] = old.race_key.map(six)
    c.require(old.trio_six.notna().all() and old.race_key.nunique() == 4799)
    return old


def paired_summary(base, candidate, year, meet):
    if year:
        base = base[base.year.eq(year)]
        candidate = candidate[candidate.year.eq(year)]
    if meet:
        base = base[base.meet.eq(meet)]
        candidate = candidate[candidate.meet.eq(meet)]
    joined = base.merge(
        candidate, on="race_key", validate="one_to_one", suffixes=("_baseline", "_candidate")
    )
    c.require(len(joined) == len(base) == len(candidate), "Cohort mismatch")
    for col in ["race_date", "meet", "year", "field_size"]:
        c.require(
            joined[col + "_baseline"].equals(joined[col + "_candidate"]), "Runner roster mismatch"
        )
    dates, codes = np.unique(joined.race_date_baseline.astype(str), return_inverse=True)
    count = np.bincount(codes)
    rng = np.random.default_rng(20261025 + year * 10 + meet)
    weights = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), size=2000)
    denominator = weights @ count
    values = {}
    for metric in METRICS:
        b, a = [joined[metric + suffix].to_numpy(float) for suffix in ["_baseline", "_candidate"]]
        sums = np.bincount(codes, weights=a - b)
        draws = (weights @ sums) / denominator
        values[metric] = {
            "baseline_total": float(b.sum()),
            "candidate_total": float(a.sum()),
            "baseline_mean": float(b.mean()),
            "candidate_mean": float(a.mean()),
            "difference": float((a - b).mean()),
            "ci95": np.quantile(draws, [0.025, 0.975]).tolist(),
            "ci_family98_333": np.quantile(draws, [0.05 / 6, 1 - 0.05 / 6]).tolist(),
        }
    gain = int(((joined.axis_top3_baseline == 0) & (joined.axis_top3_candidate == 1)).sum())
    loss = int(((joined.axis_top3_baseline == 1) & (joined.axis_top3_candidate == 0)).sum())
    return {
        "year": year,
        "meet": meet,
        "races": len(joined),
        "race_days": len(dates),
        "metrics": values,
        "axis_changes": int(
            joined.axis_program_no_baseline.ne(joined.axis_program_no_candidate).sum()
        ),
        "axis_rescued": gain,
        "axis_lost": loss,
    }


def main():
    c.check()
    c.require(not (c.OUT / "results.json").exists(), "Analysis already completed")
    old = baseline()
    new = pd.read_parquet(c.OUT / "race_metrics.parquet")
    groups, details, decisions = [], [], []
    for variant in c.VARIANTS:
        candidate = new[new.variant.eq(variant)].copy()
        own = []
        for year in [0, 2024, 2025, 2026]:
            for meet in [0, 1, 3]:
                row = paired_summary(old, candidate, year, meet)
                row["variant"] = variant
                groups.append(row)
                own.append(row)
        lookup = {(x["year"], x["meet"]): x for x in own}
        primary = lookup[2026, 0]["metrics"]["axis_top3"]
        criteria = {
            "primary_ci95_positive": primary["ci95"][0] > 0,
            "primary_family_interval_positive": primary["ci_family98_333"][0] > 0,
            "all_years_axis_nonnegative": lookup[0, 0]["metrics"]["axis_top3"]["difference"] >= 0,
            "seoul_2026_axis_nonnegative": lookup[2026, 1]["metrics"]["axis_top3"]["difference"]
            >= 0,
            "busan_2026_axis_nonnegative": lookup[2026, 3]["metrics"]["axis_top3"]["difference"]
            >= 0,
        }
        decisions.append(
            {
                "variant": variant,
                "criteria": criteria,
                "promising_historical_candidate": all(
                    v for k, v in criteria.items() if k != "primary_family_interval_positive"
                ),
                "independent_future_validation": False,
                "production_changed": False,
            }
        )
        joined = old.merge(
            candidate, on="race_key", validate="one_to_one", suffixes=("_baseline", "_candidate")
        )
        for _, row in joined.iterrows():
            details.append(
                {
                    "variant": variant,
                    "race_key": row.race_key,
                    "race_date": row.race_date_baseline,
                    "meet": row.meet_baseline,
                    "year": row.year_baseline,
                    "baseline_axis": row.axis_program_no_baseline,
                    "candidate_axis": row.axis_program_no_candidate,
                    "baseline_hit": row.axis_top3_baseline,
                    "candidate_hit": row.axis_top3_candidate,
                }
            )
    pd.DataFrame(details).to_parquet(
        c.OUT / "axis_comparison.parquet", index=False, compression="zstd"
    )
    descriptive = (
        new.groupby(["variant", "meet", "grade", "distance_m"], observed=True)
        .agg(
            races=("race_key", "size"),
            axis_hits=("axis_top3", "sum"),
            axis_rate=("axis_top3", "mean"),
        )
        .reset_index()
    )
    descriptive.to_csv(c.OUT / "condition_diagnostics.csv", index=False)
    c.save(
        c.OUT / "results.json",
        {
            "status": "complete",
            "primary_scope": "2026_all1288",
            "reference_profile": "thoroughbred-training-state-20261025-v1",
            "primary_reference_hits": int(old[old.year.eq(2026)].axis_top3.sum()),
            "all_years_reference_hits": int(old.axis_top3.sum()),
            "new_independent_test": False,
            "bootstrap_draws": 2000,
            "candidate_family_size": 3,
            "groups": groups,
            "decisions": decisions,
            "production_changed": False,
        },
    )
    for row in groups:
        if row["meet"] == 0 and row["year"] in [0, 2026]:
            m = row["metrics"]["axis_top3"]
            print(
                json.dumps(
                    {
                        "variant": row["variant"],
                        "year": row["year"],
                        "races": row["races"],
                        "axis_before": m["baseline_total"],
                        "axis_after": m["candidate_total"],
                        "difference_pp": 100 * m["difference"],
                        "ci95_pp": [100 * x for x in m["ci95"]],
                    }
                ),
                flush=True,
            )
    c.storage()


if __name__ == "__main__":
    main()
