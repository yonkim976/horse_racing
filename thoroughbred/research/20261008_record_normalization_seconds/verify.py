"""Independent least-squares, clustering and conservative policy checks."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import linalg
from scipy.stats import false_discovery_control

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("seconds", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["input_sha256"].items():
        assert A.sha(A.ROOT / name) == digest, name
    source = A.load()
    ledger = pd.read_parquet(OUT / "runner_normalization_candidates.parquet")
    assert not ledger.row_key.duplicated().any()
    ledger_index = ledger.set_index("row_key")
    effects = pd.read_csv(OUT / "joint_seconds_profiles.csv", dtype={"level": str})
    candidates = pd.read_csv(OUT / "conservative_candidates.csv", dtype={"level": str})
    models = json.loads((OUT / "models.json").read_text())
    matrices = np.load(OUT / "model_matrices.npz", allow_pickle=False)
    fits, covariance_checks, offset_checks = 0, 0, 0
    worst = 0.0
    for model in models:
        g = source[source.meet.eq(model["meet"]) & source.distance_m.eq(model["distance_m"])].copy()
        keep = ledger_index.loc[g.row_key]
        period = model["period"]
        mask = np.ones(len(g), dtype=bool)
        if period.endswith("mad4"):
            mask &= keep.mad4_keep.to_numpy()
        if period == "all_trim5":
            mask &= keep.trim5_keep.to_numpy()
        if period == "recent_mad4":
            mask &= g.year.ge(2024).to_numpy()
        if period == "complete_mad4":
            mask &= g.year.isin([2024, 2025]).to_numpy()
        g = g[mask].reset_index(drop=True)
        x, labels, _, _ = A.design(g)
        assert labels == model["labels"]
        w = 1 / g.groupby("race_key").row_key.transform("size").to_numpy(float)
        joined = pd.DataFrame(x)
        joined["y"] = g.finish.to_numpy() + g.moisture_offset.to_numpy()
        weighted = joined.mul(w, axis=0)
        totals = weighted.groupby(g.horse_id).transform("sum")
        denom = pd.Series(w).groupby(g.horse_id).transform("sum")
        demeaned = joined - totals.div(denom, axis=0)
        xd = demeaned.iloc[:, :-1].to_numpy(float)
        y = demeaned.y.to_numpy(float)
        sw = np.sqrt(w)
        beta, _, _, _ = linalg.lstsq(xd * sw[:, None], y * sw, cond=np.sqrt(1e-11))
        key = model["matrix_key"]
        saved_beta = matrices[f"{key}_beta"]
        vectors = matrices[f"{key}_vectors"]
        difference = float(np.max(abs(vectors @ (beta - saved_beta))))
        worst = max(worst, difference)
        assert difference < 2e-5, (model["meet"], model["distance_m"], period, difference)
        subgroup = effects[
            effects.meet.eq(model["meet"])
            & effects.distance_m.eq(model["distance_m"])
            & effects.period.eq(period)
        ]
        assert len(subgroup) == len(vectors)
        assert np.allclose(subgroup.effect_seconds, vectors @ saved_beta, atol=1e-10)
        fits += 1
        if period == "all_raw":
            residual = y - xd @ beta
            original = ledger_index.loc[g.row_key].initial_residual.to_numpy()
            assert np.allclose(original, residual, atol=2e-5)
            raw_y = g.finish.to_numpy(copy=True)
            raw_y -= (
                pd.Series(w * raw_y).groupby(g.horse_id).transform("sum").to_numpy()
                / denom.to_numpy()
            )
            raw_beta, _, _, _ = linalg.lstsq(xd * sw[:, None], raw_y * sw, cond=np.sqrt(1e-11))
            assert np.allclose(vectors @ beta, vectors @ raw_beta, atol=2e-5)
            offset_checks += 1
        if period == "all_mad4":
            residual = y - xd @ saved_beta
            gram = xd.T @ (w[:, None] * xd)
            inv = np.linalg.pinv(gram, rcond=1e-11)
            score = pd.DataFrame(xd * (w * residual)[:, None])
            covariances = []
            labels_to_check = [g.horse_id, g.date, g.horse_id + ":" + g.date.astype(str)]
            for cluster in labels_to_check:
                grouped = score.groupby(cluster).sum().to_numpy()
                n = len(grouped)
                c = inv @ (grouped.T @ grouped) @ inv
                c *= n / (n - 1) * (len(g) - 1) / model["residual_df"]
                covariances.append(c)
            vh, vd, vi = covariances
            for name, cov in [("cov_horse", vh), ("cov_day", vd), ("cov", vh + vd - vi)]:
                assert np.allclose(matrices[f"{key}_{name}"], cov, atol=1e-7, rtol=1e-6)
            variances = np.maximum.reduce(
                [np.einsum("ij,jk,ik->i", vectors, c, vectors) for c in [vh, vd, vh + vd - vi]]
            )
            assert np.allclose(subgroup.se, np.sqrt(np.maximum(variances, 0)), atol=1e-8)
            covariance_checks += 1
        print("verified", model["meet"], model["distance_m"], period, flush=True)
    for (_, kind), g in effects.groupby(["period", "kind"]):
        h = g[g.supported]
        assert np.allclose(h.q, false_discovery_control(h.p.to_numpy()), atol=1e-10)
        assert g.loc[~g.supported, "q"].eq(1).all()
        if kind == "month":
            assert np.allclose(g.groupby(["meet", "distance_m"]).effect_seconds.sum(), 0, atol=1e-9)
        if kind == "number":
            assert np.allclose(
                g.groupby(["meet", "distance_m", "block"]).effect_seconds.sum(), 0, atol=1e-9
            )
    lookup = effects.set_index(["meet", "distance_m", "kind", "block", "level", "period"])
    for row in candidates.itertuples():
        key = (row.meet, row.distance_m, row.kind, row.block, row.level)
        values = [
            lookup.loc[(*key, period)] if (*key, period) in lookup.index else None
            for period in A.PERIODS
        ]
        eligible = all(v is not None and v.supported for v in values)
        eligible &= len({np.sign(v.effect_seconds) for v in values if v is not None}) == 1
        full, recent = values[1], values[3]
        eligible &= full is not None and recent is not None and full.q < 0.05 and recent.q < 0.05
        expected = 0
        if eligible:
            bounds = [
                min(abs(v.ci_low), abs(v.ci_high)) if v.ci_low * v.ci_high > 0 else 0
                for v in [full, recent]
            ]
            value = min(0.30 if row.kind == "month" else 0.20, 0.5 * min(bounds))
            expected = -np.sign(full.effect_seconds) * int((value + 1e-12) * 100) / 100
        assert abs(row.candidate_add_seconds - expected) < 1e-12
    assert np.allclose(
        ledger.mad4_keep, ledger.initial_residual.between(ledger.mad4_lower, ledger.mad4_upper)
    )
    supported = ledger[ledger.adopted_supported]
    assert np.allclose(
        supported.total_candidate_add,
        supported.moisture_offset + supported.month_candidate_add + supported.gate_candidate_add,
    )
    assert np.allclose(supported.candidate_finish, supported.finish + supported.total_candidate_add)
    assert ledger.loc[~ledger.adopted_supported, "candidate_finish"].isna().all()
    assert summary["new_prediction_validation"] is False
    assert summary["new_correction_adopted"] is False
    assert all(A.sha(A.ROOT / p) == h for p, h in summary["input_sha256"].items())
    result = {
        "passed": True,
        "independent_least_squares_fits": fits,
        "independent_two_way_covariance_fits": covariance_checks,
        "moisture_offset_invariance_fits": offset_checks,
        "max_contrast_difference_seconds": worst,
        "bh_profile_rows_checked": len(effects),
        "candidate_rules_checked": len(candidates),
        "runner_composite_rows_checked": len(ledger),
        "input_hashes_unchanged": True,
        "no_next_race_prediction_validation": True,
    }
    A.dump(OUT / "verification.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
