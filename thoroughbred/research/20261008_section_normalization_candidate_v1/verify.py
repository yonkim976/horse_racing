"""Verify direct effects, shrinkage, preserved references and sectional identities."""

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
SPEC = importlib.util.spec_from_file_location("analysis", HERE / "analyze.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
SPEC2 = importlib.util.spec_from_file_location("section_helper", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(H)


def explicit(d, x, y, w, kind):
    columns = [csr_matrix(x)]
    for values in [d.horse_id] + ([] if kind == "month" else [d.race_key]):
        c = pd.factorize(values)[0]
        columns.append(coo_matrix((np.ones(len(d)), (np.arange(len(d)), c))).tocsr())
    design = hstack(columns, format="csr").multiply(np.sqrt(w)[:, None]).tocsr()
    norms = np.maximum(np.sqrt(np.asarray(design.power(2).sum(axis=0)).ravel()), 1e-12)
    z = design @ diags(1 / norms)
    solution = lsmr(z, np.sqrt(w) * y, atol=1e-11, btol=1e-11, conlim=1e12, maxiter=30000)
    assert solution[1] in [1, 2, 4, 5]
    return (solution[0] / norms)[: x.shape[1]]


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(N.A.sha(N.ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    population, d = N.A.load()
    models = json.loads((OUT / "models.json").read_text())
    p = pd.read_csv(OUT / "section_seconds_profiles.csv", dtype={"level": str})
    arrays = np.load(OUT / "model_matrices.npz", allow_pickle=False)
    checks = 0
    maxerror = 0.0
    for m in models:
        key = m["matrix_key"]
        beta = arrays[key + "_beta"]
        vectors = arrays[key + "_vectors"]
        variance = arrays[key + "_variance"]
        subset = p[p.matrix_key.astype(str).eq(key)]
        for j, part in enumerate(N.PARTS):
            g = subset[subset.section.eq(part)].sort_values("contrast_index")
            ok = g.estimable.to_numpy(bool)
            assert np.allclose(g.effect_seconds[ok], (vectors @ beta[:, j])[ok], atol=1e-9)
            assert g.loc[~ok, ["effect_seconds", "se", "ci_low", "ci_high", "p"]].isna().all().all()
            assert np.allclose(g.se[ok], np.sqrt(variance[:, j][ok]), atol=1e-9)
            assert np.allclose(
                g.ci_low[ok], g.effect_seconds[ok] - t.ppf(0.975, m["df"]) * g.se[ok], atol=1e-9
            )
        if m["period"] != "all_mad4" or m["distance_m"] not in [1200, 1600]:
            continue
        sample = N.L.select(d[d.meet.eq(m["meet"]) & d.distance_m.eq(m["distance_m"])], m["period"])
        x, labels, specs = N.specs_for(sample, m["model_type"])
        w = N.L.weights(sample, False)
        assert labels == m["labels"] and len(sample) == m["rows"]
        assert np.allclose(np.vstack([s[0] for s in specs]), vectors)
        for j, part in enumerate(N.PARTS):
            b = explicit(sample, x, sample[part].to_numpy(), w, m["model_type"])
            ok = (
                subset[subset.section.eq(part)]
                .sort_values("contrast_index")
                .estimable.to_numpy(bool)
            )
            error = float(np.max(abs((vectors @ (b - beta[:, j]))[ok])))
            assert error < 3e-5, (m, part, error)
            maxerror = max(maxerror, error)
            checks += 1
        print("independent", m["meet"], m["distance_m"], m["model_type"], flush=True)
    for _, g in p.groupby(["model_type", "period", "section", "family"]):
        valid = g[g.supported]
        if len(valid):
            assert np.allclose(valid.q, false_discovery_control(valid.p.to_numpy()), atol=1e-10)
    gate = pd.read_csv(OUT / "section_gate_lookup.csv", dtype={"level": str})
    shrinkchecks = 0
    for _, g in gate.groupby(
        ["meet", "distance_m", "field_size", "mode", "block", "band", "period", "section"],
        sort=False,
    ):
        e = g.raw_base_effect.to_numpy() if g.base_available.all() else np.zeros(len(g))
        es = g.raw_state_effect.to_numpy() if g.state_available.all() else e
        b = 0.30 * g.base_n.to_numpy() / (g.base_n.to_numpy() + 100) * e
        delta = 0.15 * g.state_n.to_numpy() / (g.state_n.to_numpy() + 100) * (es - e)
        weights = g.group_weight.to_numpy()
        caps = N.CAPS[g.section.iloc[0]]
        for raw, col, cap in [
            (b, "base_add_seconds", caps[0]),
            (delta, "state_add_seconds", caps[1]),
        ]:
            center = raw - np.average(raw, weights=weights)
            expected = -center * min(1.0, cap / max(abs(center).max(), 1e-15))
            assert np.allclose(expected, g[col], atol=1e-12)
            assert abs(np.average(g[col], weights=weights)) < 1e-12
        assert np.allclose(g.gate_add_seconds, g.base_add_seconds + g.state_add_seconds, atol=1e-12)
        shrinkchecks += 1
    month = pd.read_csv(OUT / "section_month_lookup.csv")
    for key, g in month.groupby(["meet", "distance_m", "section", "period"]):
        g = g.sort_values("month")
        raw = (
            0.30 * g.n.to_numpy() / (g.n.to_numpy() + 100) * g.raw_effect.to_numpy()
            if g.available.all()
            else np.zeros(len(g))
        )
        centered = raw - raw.mean()
        expected = -centered * min(1.0, N.CAPS[key[2]][2] / max(abs(centered).max(), 1e-15))
        assert (
            np.allclose(expected, g.month_add_seconds, atol=1e-12)
            and abs(g.month_add_seconds.mean()) < 1e-12
        )
    source = pd.read_csv(N.MOISTURE)
    reference = pd.read_csv(OUT / "section_moisture_reference.csv")
    for col in source.columns:
        if col == "meet":
            assert source.meet.map({1: "서울", 3: "부산"}).eq(reference.meet).all()
        else:
            pd.testing.assert_series_equal(
                source[col], reference[col], check_dtype=False, atol=1e-12
            )
    assert reference.loc[~reference.supported, "moisture_add_seconds"].isna().all()
    ledger = pd.read_parquet(OUT / "runner_section_candidates.parquet")
    assert len(ledger) == 151074 and ledger.row_key.is_unique
    assert np.allclose(
        ledger.early + ledger.middle1 + ledger.middle2 + ledger.late, ledger.finish, atol=1e-10
    )
    for suffix, whole in [
        ("candidate", "moisture_gate_finish"),
        ("with_month_candidate", "moisture_month_gate_finish"),
    ]:
        available = (
            ledger[
                [f"{part}_{suffix}" for part in ["early", "middle1", "middle2", "late"]] + [whole]
            ]
            .notna()
            .all(axis=1)
        )
        summed = ledger.loc[
            available, [f"{part}_{suffix}" for part in ["early", "middle1", "middle2", "late"]]
        ].sum(axis=1)
        assert np.allclose(summed, ledger.loc[available, whole], atol=1e-10)
        avail = (
            ledger[[f"middle2_{suffix}", f"late_{suffix}", f"last600_{suffix}"]].notna().all(axis=1)
        )
        assert np.allclose(
            ledger.loc[avail, f"middle2_{suffix}"] + ledger.loc[avail, f"late_{suffix}"],
            ledger.loc[avail, f"last600_{suffix}"],
            atol=1e-10,
        )
    previous = pd.read_parquet(N.PREV / "outputs/runner_trial_normalization.parquet").set_index(
        "row_key"
    )
    preserved = ledger.set_index("row_key")
    for col in [
        "gate_add_seconds",
        "moisture_add_seconds",
        "month_candidate_add",
        "moisture_gate_finish",
        "moisture_month_gate_finish",
    ]:
        assert np.allclose(
            previous[col].sort_index(), preserved[col].sort_index(), equal_nan=True, atol=1e-12
        )
    norm = H.SectionNormalizer(OUT)
    gates = pd.read_parquet(N.L.GATES)
    rosters = gates.groupby("race_key").horse_number.agg(list).to_dict()
    moistures = population.set_index("row_key").moisture
    singlechecks = 0
    for r in ledger.sample(n=220, random_state=20261008).itertuples():
        kwargs = dict(
            early=r.early,
            last600=r.last600,
            late=r.late,
            meet=r.meet,
            distance=int(r.distance_m),
            finish=r.finish,
            moisture=float(moistures.loc[r.row_key]),
            record_date=r.date,
            horse_number=int(r.horse_number),
            roster=rosters[r.race_key],
            as_of="2026-10-08",
        )
        for enabled in [False, True]:
            result = norm.normalize_record(**kwargs, include_month=enabled)
            suffix = "with_month_candidate" if enabled else "candidate"
            for part in ["early", "middle1", "middle2", "late", "last600"]:
                v = result["parts"][part]["candidate"]
                expected = getattr(r, f"{part}_{suffix}")
                if pd.isna(expected):
                    assert v is None
                else:
                    assert abs(v - expected) < 1e-10
            singlechecks += 1
    valid = dict(
        early=14.0,
        last600=39.0,
        late=13.0,
        meet="서울",
        distance=1200,
        finish=73.0,
        moisture=17.0,
        record_date="2026-09-18",
        horse_number=11,
        roster=list(range(1, 12)),
        as_of="2026-10-08",
    )
    invalid = [
        dict(early=-1.0),
        dict(last600=12.0),
        dict(late=float("nan")),
        dict(finish=45.0),
        dict(as_of="2026-10-07"),
    ]
    for change in invalid:
        try:
            norm.normalize_record(**(valid | change))
        except ValueError:
            pass
        else:
            raise AssertionError(change)
    result = dict(
        passed=True,
        independent_target_solves=checks,
        max_contrast_error_seconds=maxerror,
        profile_rows_checked=len(p),
        shrink_vectors_checked=shrinkchecks,
        ledger_rows_checked=len(ledger),
        single_batch_cases_checked=singlechecks,
        invalid_input_cases_checked=len(invalid),
        whole_time_v1_preserved=True,
        moisture_reference_preserved=True,
        overlap_identities_checked=True,
        source_hashes_unchanged=True,
        production_changed=False,
        prediction_validation=False,
    )
    N.A.dump(OUT / "verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
