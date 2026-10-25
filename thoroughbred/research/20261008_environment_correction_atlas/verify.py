"""Independent regression and lookup checks for the environmental atlas."""

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
SPEC = importlib.util.spec_from_file_location("atlas", HERE / "build.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
E = B.E
SPEC2 = importlib.util.spec_from_file_location("atlas_helper", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(H)


def explicit(d, x, y, lateral):
    weights = E.L.weights(d, lateral)
    columns = [csr_matrix(x)]
    groups = [d.horse_distance, d.pack_id] if lateral else [d.horse_id]
    for values in groups:
        c = pd.factorize(values)[0]
        columns.append(coo_matrix((np.ones(len(d)), (np.arange(len(d)), c))).tocsr())
    design = hstack(columns, format="csr").multiply(np.sqrt(weights)[:, None]).tocsr()
    norms = np.maximum(np.sqrt(np.asarray(design.power(2).sum(axis=0)).ravel()), 1e-12)
    result = lsmr(
        design @ diags(1 / norms),
        np.sqrt(weights) * y,
        atol=1e-11,
        btol=1e-11,
        conlim=1e12,
        maxiter=30000,
    )
    assert result[1] in [1, 2, 4, 5]
    return (result[0] / norms)[: x.shape[1]]


def main():
    summaries = [
        json.loads((OUT / name).read_text())
        for name in ["analysis_summary.json", "build_summary.json"]
    ]
    for summary in summaries:
        for name, digest in summary["input_sha256"].items():
            assert E.A.sha(E.ROOT / name) == digest, name
    flags = pd.read_parquet(
        E.TAIL / "outputs/runner_tail_flags.parquet", columns=["row_key", "tail25"]
    )
    population, d = E.A.load()
    d = d.merge(flags, on="row_key", validate="one_to_one")
    joint = pd.read_csv(
        OUT / "joint_sensitivity_profiles.csv", dtype={"level": str, "matrix_key": str}
    )
    lat = pd.read_csv(OUT / "lateral_moisture_period_profiles.csv", dtype={"matrix_key": str})
    jm = json.loads((OUT / "joint_models.json").read_text())
    lm = json.loads((OUT / "lateral_models.json").read_text())
    jp = np.load(OUT / "joint_parameters.npz", allow_pickle=False)
    lp = np.load(OUT / "lateral_parameters.npz", allow_pickle=False)
    explicit_solves, maxerror = 0, 0.0
    for m in jm:
        key = m["matrix_key"]
        beta, vectors, variance = (jp[key + "_" + name] for name in ["beta", "vectors", "variance"])
        frame = joint[joint.matrix_key.eq(key)]
        for j, part in enumerate(E.PARTS):
            g = frame[frame.section.eq(part)].sort_values("contrast_index")
            good = g.estimable.to_numpy(bool)
            assert np.allclose(
                g.loc[good, "effect_seconds"], (vectors @ beta[:, j])[good], atol=1e-9
            )
            assert np.allclose(g.loc[good, "se"], np.sqrt(variance[:, j][good]), atol=1e-9)
        if (m["meet"], m["distance_m"]) not in [("서울", 1600), ("부산", 1200)]:
            continue
        s = E.L.select(d[d.meet.eq(m["meet"]) & d.distance_m.eq(m["distance_m"])], m["period"])
        E.set_mix(s)
        if m["variant"] == "tail25":
            s = s[~s.tail25]
        x, labels, _ = E.joint_specs(s, "month")
        assert labels == m["labels"] and len(s) == m["rows"]
        for j, part in enumerate(E.PARTS):
            b = explicit(s, x, s[part].to_numpy(), False)
            good = (
                frame[frame.section.eq(part)].sort_values("contrast_index").estimable.to_numpy(bool)
            )
            error = float(abs(vectors @ (b - beta[:, j]))[good].max())
            assert error < 3e-5
            explicit_solves += 1
            maxerror = max(maxerror, error)
    _, p, _ = E.L.load()
    p = p.merge(flags, on="row_key", validate="many_to_one")
    pack_checks = 0
    for period in E.PERIODS:
        s = E.L.select(p, period, True)
        for variant in E.VARIANTS:
            z = s if variant == "baseline" else s[~s.groupby("pack_id").tail25.transform("any")]
            assert z.groupby("pack_id").size().eq(z.groupby("pack_id").pack_size.first()).all()
            w = E.L.weights(z, True)
            assert np.allclose(pd.Series(w).groupby(z.race_key.reset_index(drop=True)).sum(), 1)
            pack_checks += 1
    for m in lm:
        key = m["matrix_key"]
        beta, vectors = lp[key + "_beta"], lp[key + "_vectors"]
        frame = lat[lat.matrix_key.eq(key)]
        for j, target in enumerate(m["targets"]):
            g = frame[frame.metric.eq(target)]
            if not len(g):
                continue
            assert len(g) == len(vectors)
            good = g.estimable.to_numpy(bool)
            cov = [lp[key + "_" + target + "_" + name] for name in ["cov", "cov_horse", "cov_day"]]
            var = np.maximum.reduce([np.einsum("ij,jk,ik->i", vectors, c, vectors) for c in cov])
            assert np.allclose(
                g.loc[good, "effect_seconds"], (vectors @ beta[:, j])[good], atol=1e-9
            )
            assert np.allclose(g.loc[good, "se"], np.sqrt(np.maximum(var, 0))[good], atol=1e-9)
            assert np.allclose(
                g.loc[good, "ci_low"],
                g.loc[good, "effect_seconds"] - t.ppf(0.975, m["df"]) * g.loc[good, "se"],
                atol=1e-9,
            )
            assert g.loc[~good, "effect_seconds"].isna().all()
        focus = (m["meet"], m["point"], m["distance_m"]) in [
            ("서울", "3C", 1200),
            ("서울", "G1F", 1200),
            ("부산", "G4F", 1600),
            ("부산", "G3F", 1600),
        ]
        if not focus or m["scope"] != "all":
            continue
        s = p[p.meet.eq(m["meet"]) & p.point.eq(m["point"]) & p.distance_m.eq(m["distance_m"])]
        s = E.L.select(s, m["period"], True)
        if m["variant"] == "tail25":
            s = s[~s.groupby("pack_id").tail25.transform("any")]
        x, labels = E.lateral_design(s)
        assert labels == m["labels"] and len(s) == m["rows"]
        for j, target in enumerate(m["targets"]):
            b = explicit(s, x, s[target].to_numpy(), True)
            good = frame[frame.metric.eq(target)].estimable.to_numpy(bool)
            error = float(abs(vectors @ (b - beta[:, j]))[good].max())
            assert error < 3e-5
            explicit_solves += 1
            maxerror = max(maxerror, error)
    for data, keys in [
        (joint, ["period", "variant", "section", "family"]),
        (lat, ["period", "variant", "metric", "block"]),
    ]:
        for _, g in data.groupby(keys, observed=True):
            s = g[g.supported]
            if len(s):
                assert np.allclose(s.q, false_discovery_control(s.p.to_numpy()), atol=1e-10)
    cube = pd.read_parquet(OUT / "combined_correction_lookup.parquet")
    assert not cube.duplicated(B.KEYS + ["target"]).any()
    cols = ["moisture_add_seconds", "month_add_seconds", "gate_add_seconds"]
    assert np.allclose(cube.partial_add_seconds, cube[cols].fillna(0).sum(axis=1), atol=1e-12)
    assert np.allclose(
        cube.loc[cube.complete, "total_add_seconds"],
        cube.loc[cube.complete, cols].sum(axis=1),
        atol=1e-12,
    )
    assert cube.loc[~cube.complete, "total_add_seconds"].isna().all()
    indexed = cube.set_index(B.KEYS + ["target"])
    for part, operands in [
        ("middle1", ["finish", "early", "last600"]),
        ("middle2", ["last600", "late"]),
    ]:
        z = indexed.xs(part, level="target")
        for col in cols + ["total_add_seconds"]:
            expected = indexed.xs(operands[0], level="target")[col] - sum(
                indexed.xs(a, level="target")[col] for a in operands[1:]
            )
            assert np.allclose(z[col], expected, equal_nan=True, atol=1e-12)
    for part, g in cube.groupby("target", observed=True):
        assert np.array_equal(B.symbols(g.total_add_seconds, part), g.symbol)
    gates = pd.read_parquet(OUT / "gate_components.parquet")
    for _, g in gates.groupby(
        ["meet", "distance_m", "field_size", "mode", "band", "period", "target"], observed=True
    ):
        if g["mode"].iloc[0] == "number":
            weights = np.ones(len(g))
        else:
            n = int(g.field_size.iloc[0])
            sides = np.array(["inner", "middle", "outer"])[
                np.minimum((3 * (np.arange(n) + 0.5) / n).astype(int), 2)
            ]
            weights = np.array([(sides == level).sum() for level in g.level])
        assert abs(np.average(g.gate_add_seconds, weights=weights)) < 1e-10
    prior = pd.read_csv(B.SECTION / "outputs/section_gate_lookup.csv", dtype={"level": str}).rename(
        columns={"section": "target"}
    )
    merged = gates[gates.target.ne("finish")].merge(
        prior[B.KEYS[:-1] + ["target", "gate_add_seconds"]],
        on=B.KEYS[:-1] + ["target"],
        suffixes=("", "_prior"),
        validate="one_to_one",
    )
    assert len(merged) == len(prior) and np.allclose(
        merged.gate_add_seconds, merged.gate_add_seconds_prior, atol=1e-12
    )
    rows = pd.read_parquet(OUT / "runner_combined_candidates.parquet")
    assert rows.row_key.nunique() == 151074
    good = rows[[part + "_complete" for part in B.PARTS]].all(axis=1)
    assert np.allclose(
        rows.loc[good, "finish_candidate"],
        rows.loc[
            good, [part + "_candidate" for part in ["early", "middle1", "middle2", "late"]]
        ].sum(axis=1),
        atol=1e-10,
    )
    roster = pd.read_parquet(E.L.GATES).groupby("race_key").horse_number.agg(list).to_dict()
    moisture = population.set_index("row_key").moisture.to_dict()
    atlas = H.EnvironmentAtlas()
    single = 0
    for row in rows.sample(180, random_state=20261008).itertuples():
        result = atlas.normalize_record(
            meet=row.meet,
            distance=int(row.distance_m),
            moisture=float(moisture[row.row_key]),
            roster=roster[row.race_key],
            horse_number=int(row.horse_number),
            as_of="2026-10-08",
            period=row.period,
            finish=row.finish,
            early=row.early,
            last600=row.last600,
            late=row.late,
            record_date=row.date,
        )
        for part in B.PARTS:
            expected = getattr(row, part + "_total_add_seconds")
            actual = result["parts"][part]["total_add"]
            assert (actual is None and pd.isna(expected)) or abs(actual - expected) < 1e-12
            single += 1
    defaults = dict(
        meet="서울",
        distance=1200,
        moisture=16,
        month=7,
        horse_number=10,
        roster=list(range(1, 11)),
        as_of="2026-10-08",
    )
    invalid = 0
    for delta in [
        dict(as_of="2026-09-01"),
        dict(month=13),
        dict(roster=[1, 1, 10]),
        dict(moisture=np.nan),
        dict(distance=-1),
        dict(target="lateral"),
    ]:
        try:
            atlas.lookup(**(defaults | delta))
        except ValueError:
            invalid += 1
    assert invalid == 6 and not atlas.config["lateral_included"]
    E.dump(
        OUT / "verification.json",
        dict(
            passed=True,
            independent_target_solves=explicit_solves,
            max_contrast_error_seconds=maxerror,
            joint_profiles=len(joint),
            lateral_profiles=len(lat),
            complete_pack_weight_checks=pack_checks,
            combined_lookup_rows=len(cube),
            ledger_rows=len(rows),
            single_batch_target_checks=single,
            invalid_cases=invalid,
            overlap_identities=True,
            previous_section_gate_values_preserved=True,
            lateral_included=False,
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
