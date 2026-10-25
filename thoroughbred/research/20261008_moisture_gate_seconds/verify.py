"""Verify contrasts, source invariants and independent sparse fixed-effect solutions."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control, t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("cross", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
SPEC2 = importlib.util.spec_from_file_location("independent_gate", A.PREV / "verify.py")
V = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(V)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(A.sha(A.ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    population, d = A.load()
    assert len(population) == summary["population_rows"] and len(d) == summary["eligible_rows"]
    history = pd.to_datetime(d.last_history_date)
    assert (history[history.notna()] < d.loc[history.notna(), "date"]).all()
    assert d.groupby("race_key").band.nunique().max() == 1
    p = pd.read_csv(OUT / "seconds_profiles.csv", dtype={"level": str})
    c = pd.read_csv(OUT / "correction_candidates.csv", dtype={"level": str})
    grid = pd.read_csv(OUT / "coverage_grid.csv", dtype={"level": str})
    models = json.loads((OUT / "models.json").read_text())
    matrices = np.load(OUT / "model_matrices.npz", allow_pickle=False)
    checks = covchecks = interactions = 0
    maxerror = 0.0
    for m in models:
        key = m["matrix_key"]
        part = p[p.matrix_key.astype(str).eq(key)].sort_values("contrast_index")
        vectors = matrices[key + "_vectors"]
        beta = matrices[key + "_beta"]
        ok = part.estimable.to_numpy(bool)
        assert np.allclose(part.effect_seconds[ok], (vectors @ beta)[ok], atol=1e-9)
        assert part.loc[~ok, ["effect_seconds", "se", "ci_low", "ci_high", "p"]].isna().all().all()
        variances = [
            np.einsum("ij,jk,ik->i", vectors, matrices[key + "_" + name], vectors)
            for name in ["cov", "cov_horse", "cov_day"]
        ]
        se = np.sqrt(np.maximum(np.maximum.reduce(variances), 0))
        assert np.allclose(part.se[ok], se[ok], atol=1e-9)
        crit = t.ppf(0.975, m["df"])
        assert np.allclose(part.ci_low[ok], part.effect_seconds[ok] - crit * se[ok], atol=1e-9)
        assert np.allclose(part.ci_high[ok], part.effect_seconds[ok] + crit * se[ok], atol=1e-9)
        assert np.allclose(
            part.p[ok],
            2 * t.sf(abs(part.effect_seconds[ok]) / np.maximum(se[ok], 1e-15), m["df"]),
            atol=1e-10,
        )
        indexed = part.set_index(["band", "block", "family", "level"])
        for r in part[part.family.eq("interaction") & part.estimable].itertuples():
            family, level = r.level.split(":", 1)
            a = indexed.loc[(r.band, r.block, family, level)]
            b = indexed.loc[("건조", r.block, family, level)]
            assert a.estimable and b.estimable
            assert abs(r.effect_seconds - (a.effect_seconds - b.effect_seconds)) < 1e-8
            interactions += 1
        for _, g in part[part.family.eq("number") & part.estimable].groupby(["band", "block"]):
            n = int(g.block.iloc[0][5:])
            if len(g) == n:
                assert abs(g.effect_seconds.sum()) < 1e-8
        for r in part.itertuples():
            support = json.loads(r.support)
            expected = (
                all(s["rows"] >= 50 and s["races"] >= 50 and s["days"] >= 20 for s in support)
                and r.estimable
            )
            strict = expected and all(s["rows"] >= 100 for s in support)
            assert r.supported == expected and r.strict_supported == strict
        independent = (
            m["distance_m"] in [1200, 1600]
            and m["period"] in ["all_mad4", "recent_mad4"]
            and m["adjustment"] == "dual"
        )
        if not independent:
            continue
        g = A.L.select(d[d.meet.eq(m["meet"]) & d.distance_m.eq(m["distance_m"])], m["period"])
        x, labels, entries = A.design(g)
        assert labels == m["labels"] and len(g) == m["rows"]
        w = A.L.weights(g, False)
        assert np.allclose(pd.Series(w).groupby(g.race_key).sum(), 1)
        specs = A.contrast_specs(g, labels, entries)
        assert np.allclose(np.vstack([s[0] for s in specs]), vectors)
        b, iterations = V.explicit_fit(g, x, g.finish.to_numpy(float), w, False, m["adjustment"])
        error = float(np.max(abs((vectors @ (b - beta))[ok])))
        assert error < 3e-5, (m, error)
        maxerror = max(maxerror, error)
        checks += 1
        if m["period"] == "all_mad4":
            groups, _ = A.L.fe_groups(g, False, m["adjustment"])
            z, _, _ = A.L.absorb(np.column_stack([x, g.finish]), groups, w)
            xd, y = z[:, : len(labels)], z[:, -1]
            inv = np.linalg.pinv(xd.T @ (w[:, None] * xd), rcond=1e-11)
            score = pd.DataFrame(xd * (w * (y - xd @ beta))[:, None])
            covs = []
            for cluster in [g.horse_id, g.date, g.horse_id + ":" + g.date.astype(str)]:
                sums = score.groupby(cluster).sum().to_numpy()
                n = len(sums)
                covs.append(
                    inv @ (sums.T @ sums) @ inv * n / (n - 1) * (len(g) - 1) / m["residual_df"]
                )
            for name, cov in [
                ("cov_horse", covs[0]),
                ("cov_day", covs[1]),
                ("cov", covs[0] + covs[1] - covs[2]),
            ]:
                assert np.allclose(matrices[key + "_" + name], cov, atol=1e-7, rtol=1e-6)
            covchecks += 1
        print("independent", m["meet"], m["distance_m"], m["period"], error, iterations, flush=True)
    for _, g in p.groupby(["adjustment", "period", "family"]):
        supported = g[g.supported]
        if len(supported):
            assert np.allclose(
                supported.q, false_discovery_control(supported.p.to_numpy()), atol=1e-10
            )
        assert g.loc[~g.supported, "q"].eq(1).all()
    observed = A.coverage(population)
    pd.testing.assert_frame_equal(grid[observed.columns], observed, check_dtype=False)
    assert len(grid) == 19 * 5 * 50
    assert grid.loc[grid.status.eq("unobserved"), "observed_rows"].eq(0).all()
    assert grid.loc[grid.status.eq("model_unavailable"), "all_mad4_effect_seconds"].isna().all()
    # Independently enforce candidate decisions and numeric shrinkage policy.
    keys = ["meet", "distance_m", "band", "block", "family", "level"]
    index = p.set_index(keys + ["adjustment", "period"])
    for r in c.itertuples():
        key = tuple(getattr(r, k) for k in keys)
        main = [
            index.loc[(*key, "dual", period)] if (*key, "dual", period) in index.index else None
            for period in A.PERIODS
        ]
        extra = [
            index.loc[(*key, "unit_only", period)]
            if (*key, "unit_only", period) in index.index
            else None
            for period in ["all_mad4", "recent_mad4"]
        ]
        strict = all(row is not None and row.strict_supported for row in main)
        supported = all(row is not None and row.supported for row in main + extra)
        stable = supported and len({np.sign(row.effect_seconds) for row in main + extra}) == 1
        full, recent = main[1], main[3]
        sig = full is not None and recent is not None and full.q < 0.05 and recent.q < 0.05
        assert r.all_strict == strict and r.stable == stable and r.full_recent_q_pass == sig
        raw = 0.0
        if strict and stable and sig:
            boundary = min(
                min(abs(row.ci_low), abs(row.ci_high)) if row.ci_low * row.ci_high > 0 else 0
                for row in [full, recent]
            )
            amount = min(0.1, 0.5 * boundary * r.minimum_rows / (r.minimum_rows + 100))
            raw = -np.sign(full.effect_seconds) * np.floor(amount * 100 + 1e-9) / 100
        assert abs(raw - r.raw_candidate_add) < 1e-10
    for (meet, dist, band, block, family), g in c.groupby(keys[:5]):
        if not g.block_complete_strict.all():
            assert g.candidate_add.eq(0).all()
            continue
        if family == "number":
            w = np.ones(len(g))
        elif block.startswith("exact"):
            w = g.level.map(
                {"inner": 3, "middle": 4, "outer": 3}
                if block == "exact10"
                else dict.fromkeys(A.SIDES, 4)
            )
        else:
            source = population[
                population.meet.eq(meet)
                & population.distance_m.eq(dist)
                & population.band.eq(band)
                & population.gate_block.eq(block)
            ]
            shares = source.groupby("race_key")[[f"p_{s}" for s in A.SIDES]].first().mean()
            w = g.level.map({s: shares[f"p_{s}"] for s in A.SIDES})
        assert abs(np.average(g.candidate_add, weights=w)) < 1e-10
    result = dict(
        passed=True,
        independent_fixed_effect_solves=checks,
        independent_covariance_checks=covchecks,
        max_contrast_error_seconds=maxerror,
        interaction_equations_checked=interactions,
        profile_rows_checked=len(p),
        coverage_cells_checked=len(grid),
        candidate_rows_checked=len(c),
        input_hashes_unchanged=True,
        predictive_validation=False,
        new_correction_adopted=False,
    )
    A.dump(OUT / "verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
