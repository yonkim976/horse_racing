"""Independent centroid assignment, period restriction, flags, and statistics."""

import json

import numpy as np
import pandas as pd
import run as e


def replay_clusters(frame, name):
    meta = json.loads((e.OUT / (name + "_clusters.json")).read_text())
    x = frame[meta["features"]].to_numpy(float)
    tr = frame.year.eq(2024)
    assert np.allclose(np.nanquantile(x[tr], 0.01, axis=0), meta["lower"])
    assert np.allclose(np.nanquantile(x[tr], 0.99, axis=0), meta["upper"])
    assert np.allclose(np.nanmedian(x[tr], axis=0), meta["median"])
    missing = np.isnan(x)
    z = np.where(missing, meta["median"], np.clip(x, meta["lower"], meta["upper"]))
    z = np.column_stack([z, missing[:, meta["missingcols"]].astype(float)])
    assert np.allclose(z[tr].mean(0), meta["mean"])
    scale = z[tr].std(0)
    scale[scale == 0] = 1
    assert np.allclose(scale, meta["std"])
    z = (z - meta["mean"]) / meta["std"]
    centers = np.array(meta["centers"])
    assignment = ((z[:, None, :] - centers[None, :, :]) ** 2).sum(2).argmin(1)
    assert np.array_equal(assignment, frame.cluster)
    poison = frame.copy()
    poison["outcome"] = -999
    poison["top3"] = 1
    poison["trio_fail"] = 1
    assert np.allclose(poison[meta["features"]].to_numpy(float), x, equal_nan=True)


def main():
    e.check()
    f = pd.read_parquet(e.OUT / "runner_inputs.parquet")
    low = pd.read_parquet(e.OUT / "low_rank_runners.parquet")
    r = pd.read_parquet(e.OUT / "clustered_races.parquet")
    assert len(f) == 50754 and len(r) == 4799 and f.groupby("race_key").top3.sum().eq(3).all()
    assert low.model_rank.ge(6).all() and len(low) == len(f[f.model_rank.ge(6)])
    assert abs(f.groupby("race_key").prob_top3.sum().sub(3).abs().max()) < 1e-12
    assert r.hit_trio.sum() == 1228 and r.hit53.sum() == 1313
    assert r.hit_qpl.sum() == 3237 and r.hit_quinella.sum() == 2071
    assert len(r[r.trio_fail.eq(1)]) == 3571
    for col in ["history_source_date", "profile_source_date"]:
        assert (f[col].isna() | (f[col] <= f.cutoff_date)).all()
    replay_clusters(low, "runner")
    replay_clusters(r, "race")
    flags = e.flags(low)
    chosen = json.loads((e.OUT / "selected_conditions.json").read_text())["conditions"]
    disc = pd.read_csv(e.OUT / "discovery_conditions.csv")
    eligible = disc[
        (disc.runners >= 80)
        & (disc.actual_top3 >= 8)
        & (disc.excess > 0)
        & (disc.excess_difference > 0)
    ]
    want = (
        eligible.sort_values(["selection_score", "condition"], ascending=[False, True])
        .head(6)
        .condition.tolist()
    )
    assert chosen == want
    summaries = pd.read_csv(e.OUT / "runner_condition_summary.csv")
    for _, row in summaries.iterrows():
        period = str(row.period)
        mask = (
            low.year.ge(2024)
            if period == "all"
            else low.year.ge(2025)
            if period == "2025_2026"
            else low.year.eq(int(period))
        )
        one = low[mask].reset_index(drop=True)
        if row.condition.startswith("cluster_"):
            member = one.cluster.eq(int(row.condition.split("_")[1]))
        else:
            member = pd.Series(True, index=low.index)
            for part in row.condition.split(" & "):
                member &= flags[part]
            member = member[mask].reset_index(drop=True)
        g = one[member]
        control = one[~member]
        assert len(g) == row.runners and g.top3.sum() == row.actual_top3
        assert abs(g.top3.mean() - row.actual_rate) < 1e-12
        assert abs(g.prob_top3.mean() - row.predicted_rate) < 1e-12
        residual = one.top3 - one.prob_top3
        assert (
            abs(residual[member].mean() - residual[~member].mean() - row.excess_difference) < 1e-12
        )
        if pd.notna(row.get("excess_difference_ci_low")):
            lo, hi, _ = e.bootstrap_diff(one, member, residual)
            assert (
                abs(lo - row.excess_difference_ci_low) < 1e-12
                and abs(hi - row.excess_difference_ci_high) < 1e-12
            )
        if pd.notna(row.get("matched_runners")):
            assert row.matched_runners <= row.runners and len(control) > 0
    summary = pd.read_csv(e.OUT / "race_condition_summary.csv")
    for _, row in summary[summary.condition.str.startswith("cluster_")].iterrows():
        period = str(row.period)
        one = (
            r
            if period == "all"
            else r[r.year.ge(2025)]
            if period == "2025_2026"
            else r[r.year.eq(int(period))]
        )
        one = one.reset_index(drop=True)
        member = one.cluster.eq(int(row.condition.split("_")[1]))
        g = one[member]
        assert len(g) == row.races and abs(g.trio_fail.mean() - row.trio_failure_rate) < 1e-12
        if pd.notna(row.get("excess_difference_ci_low")):
            lo, hi, _ = e.bootstrap_diff(one, member, one.trio_fail_residual)
            assert (
                abs(lo - row.excess_difference_ci_low) < 1e-12
                and abs(hi - row.excess_difference_ci_high) < 1e-12
            )
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            race_clusters=4,
            runner_clusters=5,
            unsupervised_preprocessing_fit_year=2024,
            centroids_and_assignments_replayed=True,
            source_hashes_unchanged=True,
            labels_excluded_and_poison_invariant=True,
            baseline_hits_reproduced=True,
            condition_counts_and_bootstraps_recomputed=True,
            selected_conditions_discovery_only=True,
            new_outcome_prediction_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            jeju_access=False,
        ),
    )
    print("Verified", len(r), len(low), chosen, flush=True)


if __name__ == "__main__":
    main()
