"""Independent explicit fixed-effect solves and policy/weight checks."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, csr_matrix, diags, hstack
from scipy.sparse.linalg import lsmr
from scipy.stats import false_discovery_control, t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("seconds", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def sample_for(model, d, positions):
    lateral = model["kind"] == "lateral"
    base = positions if lateral else d
    g = base[base.meet.eq(model["meet"])]
    if lateral:
        g = g[g.point.eq(model["point"])]
    if model["distance_m"]:
        g = g[g.distance_m.eq(model["distance_m"])]
    return A.select(g, model["period"], lateral=lateral)


def explicit_fit(g, x, y, w, lateral, adjustment):
    unit = pd.factorize(g.pack_id if lateral else g.race_key)[0]
    columns = [csr_matrix(x)]
    if adjustment == "dual":
        horse = pd.factorize(g.horse_distance if lateral else g.horse_id)[0]
        columns.append(coo_matrix((np.ones(len(g)), (np.arange(len(g)), horse))).tocsr())
    columns.append(coo_matrix((np.ones(len(g)), (np.arange(len(g)), unit))).tocsr())
    design = hstack(columns, format="csr").multiply(np.sqrt(w)[:, None]).tocsr()
    norm = np.sqrt(np.asarray(design.power(2).sum(axis=0)).ravel())
    norm = np.maximum(norm, 1e-12)
    normalized = design @ diags(1 / norm)
    solution = lsmr(normalized, np.sqrt(w) * y, atol=1e-11, btol=1e-11, conlim=1e12, maxiter=20000)
    assert solution[1] in [1, 2, 4, 5], (solution[1], solution[2])
    return (solution[0] / norm)[: x.shape[1]], int(solution[2])


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(A.sha(A.ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    d, positions, audit = A.load()
    assert audit == summary["population"]
    assert (
        positions.groupby("pack_id").size().eq(positions.groupby("pack_id").pack_size.first()).all()
    )
    history = pd.to_datetime(d.last_history_date)
    assert (history[history.notna()] < d.loc[history.notna(), "date"]).all()
    models = json.loads((OUT / "models.json").read_text())
    matrices = np.load(OUT / "model_matrices.npz", allow_pickle=False)
    profiles = pd.read_csv(OUT / "seconds_profiles.csv", dtype={"level": str})
    c = pd.read_csv(OUT / "gate_correction_candidates.csv", dtype={"level": str})
    field = pd.read_csv(OUT / "field_gate_lookup.csv", dtype={"level": str})
    checks, covchecks, weightchecks, max_error, max_iterations = 0, 0, 0, 0.0, 0
    for model in models:
        key = model["matrix_key"]
        beta = matrices[f"{key}_beta"]
        vectors = matrices[f"{key}_vectors"]
        subset = profiles[
            profiles.kind.eq(model["kind"])
            & profiles.meet.eq(model["meet"])
            & profiles.distance_m.eq(model["distance_m"])
            & profiles.point.eq(model["point"])
            & profiles.period.eq(model["period"])
            & profiles.adjustment.eq(model["adjustment"])
        ]
        for j, metric in enumerate(model["targets"]):
            part = subset[subset.metric.eq(metric)]
            assert len(part) == len(vectors)
            assert np.allclose(part.effect_seconds, vectors @ beta[:, j], atol=1e-10)
            covs = [matrices[f"{key}_{metric}_{name}"] for name in ["cov", "cov_horse", "cov_day"]]
            variance = np.maximum.reduce(
                [np.einsum("ij,jk,ik->i", vectors, cov, vectors) for cov in covs]
            )
            se = np.sqrt(np.maximum(variance, 0))
            assert np.allclose(part.se, se, atol=1e-9)
            assert np.allclose(
                part.ci_low, part.effect_seconds - t.ppf(0.975, model["df"]) * se, atol=1e-9
            )
            assert np.allclose(
                part.ci_high, part.effect_seconds + t.ppf(0.975, model["df"]) * se, atol=1e-9
            )
        lateral = model["kind"] == "lateral"
        independent = model["adjustment"] == "dual" and (
            (
                not lateral
                and model["distance_m"] in [1200, 1600]
                and model["period"] in ["all_mad4", "recent_mad4"]
            )
            or (lateral and model["distance_m"] == 0 and model["period"] == "all_mad4")
            or (
                lateral
                and model["meet"] == "서울"
                and model["point"] == "4C"
                and model["distance_m"] == 1200
                and model["period"] == "recent_mad4"
            )
        )
        if not independent:
            continue
        g = sample_for(model, d, positions)
        if lateral:
            x, labels = A.lateral_design(g)
        else:
            x, labels, _ = A.gate_design(g)
        assert labels == model["labels"] and len(g) == model["rows"]
        w = A.weights(g, lateral)
        assert np.allclose(pd.Series(w).groupby(g.race_key).sum(), 1)
        if lateral:
            assert g.groupby("pack_id").size().eq(g.groupby("pack_id").pack_size.first()).all()
            sideweights = pd.Series(w).groupby([g.pack_id, g.lateral_side]).sum()
            assert np.allclose(
                sideweights.groupby(level=0).max(), sideweights.groupby(level=0).min()
            )
        weightchecks += 1
        for j, metric in enumerate(model["targets"]):
            b, iterations = explicit_fit(
                g, x, g[metric].to_numpy(float), w, lateral, model["adjustment"]
            )
            estimable = subset[subset.metric.eq(metric)].estimable.to_numpy(bool)
            error = float(np.max(abs((vectors @ (b - beta[:, j]))[estimable])))
            assert error < 3e-5, (model, metric, error)
            max_error = max(max_error, error)
            max_iterations = max(max_iterations, iterations)
            checks += 1
        if (not lateral and model["period"] == "all_mad4") or (
            lateral and model["point"] in ["S1F", "G1F"]
        ):
            groups, _ = A.fe_groups(g, lateral, model["adjustment"])
            centered, _, _ = A.absorb(
                np.column_stack([x, g[model["targets"]].to_numpy(float)]), groups, w
            )
            xd = centered[:, : len(labels)]
            y = centered[:, len(labels) :]
            inv = np.linalg.pinv(xd.T @ (w[:, None] * xd), rcond=1e-11)
            for j, metric in enumerate(model["targets"]):
                score = pd.DataFrame(xd * (w * (y[:, j] - xd @ beta[:, j]))[:, None])
                covs = []
                for cluster in [g.horse_id, g.date, g.horse_id + ":" + g.date.astype(str)]:
                    sums = score.groupby(cluster).sum().to_numpy()
                    n = len(sums)
                    cov = (
                        inv
                        @ (sums.T @ sums)
                        @ inv
                        * n
                        / (n - 1)
                        * (len(g) - 1)
                        / model["residual_df"]
                    )
                    covs.append(cov)
                for name, cov in [
                    ("cov_horse", covs[0]),
                    ("cov_day", covs[1]),
                    ("cov", covs[0] + covs[1] - covs[2]),
                ]:
                    assert np.allclose(
                        matrices[f"{key}_{metric}_{name}"], cov, atol=1e-7, rtol=1e-6
                    )
                covchecks += 1
        print(
            "independent",
            model["kind"],
            model["meet"],
            model["point"],
            model["distance_m"],
            model["period"],
            flush=True,
        )
    for _, g in profiles.groupby(["kind", "adjustment", "period", "metric", "family"]):
        supported = g[g.supported]
        if len(supported):
            assert np.allclose(
                supported.q, false_discovery_control(supported.p.to_numpy()), atol=1e-10
            )
        assert g.loc[~g.supported, "q"].eq(1).all()
    keys = ["meet", "distance_m", "family", "block", "level"]
    expected = A.gate_candidates(profiles, d)
    pd.testing.assert_frame_equal(c, expected, check_dtype=False, atol=1e-9, rtol=1e-9)
    # Independently check the numeric cap/shrink/truncation from exported decision fields.
    for r in c.itertuples():
        amount = min(
            0.15 if r.tier == "A" else 0.05,
            0.5 * r.nearest_ci_bound * r.minimum_rows / (r.minimum_rows + 100),
        )
        evidence = (
            -np.sign(r.full_effect) * int((amount + 1e-12) * 100) / 100
            if np.isfinite(r.full_effect)
            else 0
        )
        assert abs(evidence - r.evidence_add_seconds) < 1e-12
    for (meet, distance, block, n, family), g in field.groupby(
        ["meet", "distance_m", "block", "field_size", "family"]
    ):
        if family == "number":
            assert len(g) == n
            assert abs(g.add_seconds.mean()) < 1e-12
        else:
            roster = d[
                d.meet.eq(meet) & d.distance_m.eq(distance) & d.gate_block.eq(block) & d.n.eq(n)
            ]
            shares = {"middle": roster.p_middle.iloc[0], "outer": roster.p_outer.iloc[0]}
            shares["inner"] = 1 - shares["middle"] - shares["outer"]
            assert abs(sum(r.add_seconds * shares[r.level] for r in g.itertuples())) < 1e-12
        assert np.allclose(g.add_seconds, g.evidence_add_seconds + g.centering_shift)
    assert not c.duplicated(keys).any()
    assert all(A.sha(A.ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    result = {
        "passed": True,
        "independent_explicit_fixed_effect_solves": checks,
        "independent_covariance_checks": covchecks,
        "weight_and_pack_checks": weightchecks,
        "max_contrast_error_seconds": max_error,
        "maximum_independent_solver_iterations": max_iterations,
        "profile_rows_checked": len(profiles),
        "candidate_rows_checked": len(c),
        "field_centering_rows_checked": len(field),
        "input_hashes_unchanged": True,
        "actual_lateral_automatic_correction": "pending_zero",
        "next_race_prediction_validation": False,
    }
    A.dump(OUT / "verification.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
