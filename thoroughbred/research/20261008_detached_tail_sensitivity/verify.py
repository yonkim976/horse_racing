"""Independent roster calculations, explicit fixed effects and retained result checks."""

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
SPEC = importlib.util.spec_from_file_location("tail_analysis", HERE / "analyze.py")
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


def explicit(d, x, y, kind):
    weights = 1 / d.groupby("race_key").row_key.transform("size").to_numpy()
    columns = [csr_matrix(x)]
    for values in [d.horse_id] + ([] if kind == "month" else [d.race_key]):
        c = pd.factorize(values)[0]
        columns.append(coo_matrix((np.ones(len(d)), (np.arange(len(d)), c))).tocsr())
    design = hstack(columns, format="csr").multiply(np.sqrt(weights)[:, None]).tocsr()
    norms = np.maximum(np.sqrt(np.asarray(design.power(2).sum(axis=0)).ravel()), 1e-12)
    solved = lsmr(
        design @ diags(1 / norms),
        np.sqrt(weights) * y,
        atol=1e-11,
        btol=1e-11,
        conlim=1e12,
        maxiter=30000,
    )
    assert solved[1] in [1, 2, 4, 5]
    return (solved[0] / norms)[: x.shape[1]]


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for path, digest in summary["input_sha256"].items():
        assert T.A.sha(T.ROOT / path) == digest, path
    flags = pd.read_parquet(OUT / "runner_tail_flags.parquet")
    raw = pd.read_parquet(T.L.GATES)
    assert len(flags) == len(raw) == 151115 and flags.row_key.is_unique
    race_checks = 0
    flag_groups = dict(tuple(flags.groupby("race_key")))
    for key, g in raw.groupby("race_key"):
        a = g.finish.to_numpy()
        assert g.n.eq(len(g)).all() and np.isfinite(a).all()
        med = float(np.median(a))
        sig = float(1.4826 * np.median(abs(a - med)))
        f = flag_groups[key].set_index("horse_number").loc[g.horse_number]
        assert np.allclose(f.race_median, med) and np.allclose(f.robust_sigma, sig)
        rank = np.array([1 + (a < v).sum() for v in a])
        bottom = rank > len(a) - int(np.ceil(len(a) / 4))
        for name, mult in [("tail20", 2), ("tail25", 2.5), ("tail30", 3)]:
            keep = (
                bottom
                & ((a - a.min()) > max(3, 0.04 * a.min()))
                & ((a - med) > max(2, 0.02 * med, mult * sig))
            )
            assert np.array_equal(keep, f[name].to_numpy())
        race_checks += 1
    assert (~flags.tail30 | flags.tail25).all() and (~flags.tail25 | flags.tail20).all()
    population, d = T.A.load()
    d = d.merge(flags[["row_key", "tail25", "tail30"]], on="row_key", validate="one_to_one")
    d = d[d.mad4_keep].copy()
    assert len(d) == summary["mad4_rows"] and d.tail25.sum() == summary["additional_tail25_removed"]
    assert d[~d.tail25].race_key.nunique() == d.race_key.nunique()
    T.MOIST_WEIGHTS.update(
        {
            (key.rsplit(":", 1)[0], int(key.rsplit(":", 1)[1])): {
                band: {float(k): v for k, v in shares.items()} for band, shares in values.items()
            }
            for key, values in summary["moisture_mix"].items()
        }
    )
    models = json.loads((OUT / "models.json").read_text())
    p = pd.read_csv(OUT / "adjusted_effect_profiles.csv", dtype={"level": str, "matrix_key": str})
    arrays = np.load(OUT / "model_parameters.npz", allow_pickle=False)
    maximum, solves = 0.0, 0
    for m in models:
        key = m["matrix_key"]
        beta, vectors, var = (arrays[key + "_" + name] for name in ["beta", "vectors", "variance"])
        block = p[p.matrix_key.eq(key)]
        for j, part in enumerate(T.PARTS):
            s = block[block.section.eq(part)].sort_values("contrast_index")
            ok = s.estimable.to_numpy(bool)
            assert np.allclose(s.loc[ok, "effect_seconds"], (vectors @ beta[:, j])[ok], atol=1e-9)
            assert np.allclose(s.loc[ok, "se"], np.sqrt(var[:, j][ok]), atol=1e-9)
            assert np.allclose(
                s.loc[ok, "ci_low"],
                s.loc[ok, "effect_seconds"] - t.ppf(0.975, m["df"]) * s.loc[ok, "se"],
                atol=1e-9,
            )
        if (m["meet"], m["distance_m"]) not in [("서울", 1600), ("부산", 1200)] or m[
            "variant"
        ] == "tail30":
            continue
        s = d[d.meet.eq(m["meet"]) & d.distance_m.eq(m["distance_m"])]
        if m["variant"] != "baseline":
            s = s[~s[m["variant"]]]
        x, labels, specs = T.specs_for(s, m["model_type"])
        assert labels == m["labels"] and len(s) == m["rows"]
        assert np.allclose(np.vstack([v for v, _ in specs]), vectors, atol=1e-12)
        for j, part in enumerate(T.PARTS):
            b = explicit(s, x, s[part].to_numpy(), m["model_type"])
            ok = (
                block[block.section.eq(part)].sort_values("contrast_index").estimable.to_numpy(bool)
            )
            error = float(abs(vectors @ (b - beta[:, j]))[ok].max())
            assert error < 3e-5, (m, part, error)
            maximum = max(maximum, error)
            solves += 1
        print("explicit", m["meet"], m["distance_m"], m["variant"], m["model_type"], flush=True)
    for _, g in p.groupby(["variant", "model_type", "section", "family"]):
        s = g[g.supported]
        if len(s):
            assert np.allclose(s.q, false_discovery_control(s.p.to_numpy()), atol=1e-10)
    desc = pd.read_csv(OUT / "record_baseline_sensitivity.csv")
    for row in desc[desc.variant.isin(["baseline", "tail25", "tail30"])].itertuples():
        s = d[d.meet.eq(row.meet) & d.distance_m.eq(row.distance_m)]
        if row.variant != "baseline":
            s = s[~s[row.variant]]
        assert len(s) == row.rows and abs(s[row.section].mean() - row.mean) < 1e-10
        assert abs(s.groupby("race_key")[row.section].mean().mean() - row.race_equal_mean) < 1e-10
    pairs = pd.read_csv(OUT / "paired_race_changes.csv")
    for row in pairs.itertuples():
        b = desc[
            (desc.meet.eq(row.meet))
            & desc.distance_m.eq(row.distance_m)
            & desc.section.eq(row.section)
        ].set_index("variant")
        assert (
            abs(
                row.mean_change
                - (b.loc["tail25", "race_equal_mean"] - b.loc["baseline", "race_equal_mean"])
            )
            < 1e-10
        )
        assert row.ci_low <= row.mean_change <= row.ci_high
    # The recalculated baseline reproduces the preceding study on its identical targets.
    old = pd.read_csv(T.PREV / "outputs/section_seconds_profiles.csv", dtype={"level": str})
    old = old[old.period.eq("all_mad4") & old.model_type.isin(["base", "month"])]
    keys = ["meet", "distance_m", "model_type", "family", "block", "level", "section"]
    same = p[p.variant.eq("baseline") & ~p.family.eq("moisture")].merge(
        old[keys + ["effect_seconds"]], on=keys, suffixes=("", "_old"), validate="one_to_one"
    )
    assert len(same) == len(old)
    assert np.allclose(same.effect_seconds, same.effect_seconds_old, equal_nan=True, atol=1e-9)
    T.dump(
        OUT / "verification.json",
        dict(
            passed=True,
            original_race_reference_checks=race_checks,
            profiles_checked=len(p),
            independent_target_solves=solves,
            max_contrast_error_seconds=maximum,
            reproduced_prior_profiles=len(same),
            retained_primary=int((~d.tail25).sum()),
            original_rosters_preserved=True,
            original_records_deleted=False,
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
