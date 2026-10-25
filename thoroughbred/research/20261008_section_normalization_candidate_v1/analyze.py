"""Direct sectional effects and small trial corrections from fixed local sources."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREV = HERE.parent / "20261008_gate_model_candidate_v1"
SPEC = importlib.util.spec_from_file_location("gate_builder", PREV / "build.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
A = B.A
L = A.L
OLD = L.OLD
PARTS = ["early", "last600", "late"]
CAPS = {"early": (0.05, 0.02, 0.03), "last600": (0.08, 0.03, 0.06), "late": (0.04, 0.02, 0.03)}
MOISTURE = HERE.parent / "20261002_moisture_section_strength/outputs/reference_seconds.csv"


def specs_for(d, model_type):
    if model_type == "base":
        x, labels, specs = L.gate_design(d)
        specs = L.contrast_specs(d, labels, specs, False)
    elif model_type == "state":
        x, labels, entries = A.design(d)
        specs = A.contrast_specs(d, labels, entries)
    else:
        x, labels, _, _ = OLD.design(d)
        specs = []
        for month in range(1, 13):
            theta = 2 * np.pi * (month - 1) / 12
            v = np.zeros(len(labels))
            v[:4] = [np.sin(theta), np.cos(theta), np.sin(2 * theta), np.cos(2 * theta)]
            g = d[d.month.eq(month)]
            support = [
                dict(
                    rows=len(g),
                    races=int(g.race_key.nunique()),
                    days=int(g.date.nunique()),
                    years=int(g.year.nunique()),
                )
            ]
            z = support[0]
            specs.append(
                (
                    v,
                    dict(
                        family="month",
                        block="annual",
                        level=str(month),
                        support=support,
                        supported=bool(
                            z["rows"] >= 100
                            and z["races"] >= 20
                            and z["days"] >= 10
                            and z["years"] >= 2
                        ),
                    ),
                )
            )
    return x, labels, specs


def fit(d, meta, matrices):
    kind = meta["model_type"]
    x, labels, specs = specs_for(d, kind)
    w = L.weights(d, False)
    if kind == "month":
        groups = [OLD.codes(d.horse_id)]
        fe_rank = d.horse_id.nunique()
    else:
        groups, fe_rank = L.fe_groups(d, False, "dual")
    z, _, orth = L.absorb(np.column_stack([x, d[PARTS].to_numpy(float)]), groups, w)
    xd, y = z[:, : len(labels)], z[:, len(labels) :]
    gram = xd.T @ (w[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    rank = int(np.linalg.matrix_rank(gram, tol=np.linalg.norm(gram, 2) * 1e-11))
    dof = len(d) - fe_rank - rank
    assert dof > 5
    beta = inv @ (xd.T @ (w[:, None] * y))
    residual = y - xd @ beta
    vectors = np.vstack([s[0] for s in specs])
    projection = inv @ gram
    estimable = np.array([np.allclose(v @ projection, v, atol=1e-6) for v in vectors])
    df = min(d.horse_id.nunique(), d.date.nunique()) - 1
    critical = t.ppf(0.975, df)
    records = []
    variance = []
    key = str(len(matrices))
    for j, part in enumerate(PARTS):
        score = xd * (w * residual[:, j])[:, None]
        factor = (len(d) - 1) / dof
        vh = inv @ OLD.cluster(score, d.horse_id) @ inv * factor
        vd = inv @ OLD.cluster(score, d.date) @ inv * factor
        vi = inv @ OLD.cluster(score, d.horse_id + ":" + d.date.astype(str)) @ inv * factor
        var = np.maximum.reduce(
            [np.einsum("ij,jk,ik->i", vectors, c, vectors) for c in [vh + vd - vi, vh, vd]]
        )
        se = np.sqrt(np.maximum(var, 0))
        values = vectors @ beta[:, j]
        variance.append(se**2)
        for i, (_, identity) in enumerate(specs):
            ok = bool(estimable[i])
            records.append(
                meta
                | identity
                | dict(
                    section=part,
                    estimable=ok,
                    supported=bool(ok and identity["supported"]),
                    effect_seconds=float(values[i]) if ok else None,
                    se=float(se[i]) if ok else None,
                    ci_low=float(values[i] - critical * se[i]) if ok else None,
                    ci_high=float(values[i] + critical * se[i]) if ok else None,
                    p=float(2 * t.sf(abs(values[i]) / max(se[i], 1e-15), df)) if ok else None,
                    matrix_key=key,
                    contrast_index=i,
                )
            )
    matrices[key] = dict(beta=beta, vectors=vectors, variance=np.column_stack(variance))
    model = meta | dict(
        matrix_key=key,
        labels=labels,
        parts=PARTS,
        rows=len(d),
        races=int(d.race_key.nunique()),
        days=int(d.date.nunique()),
        horses=int(d.horse_id.nunique()),
        fe_rank=int(fe_rank),
        rank=rank,
        residual_df=int(dof),
        df=int(df),
        orthogonality_error=orth,
    )
    return records, model


def main():
    sources = [
        L.POP,
        L.GATES,
        L.LEDGER,
        A.HERE / "analyze.py",
        A.PREV / "analyze.py",
        L.PREVIOUS / "analyze.py",
        PREV / "build.py",
        PREV / "apply.py",
        PREV / "outputs/gate_correction_lookup.csv",
        PREV / "outputs/moisture_reference.csv",
        PREV / "outputs/month_candidate_reference.csv",
        PREV / "outputs/runner_trial_normalization.parquet",
        MOISTURE,
        HERE / "PLAN.md",
        HERE / "analyze.py",
        HERE / "apply.py",
    ]
    hashes = {str(p.relative_to(ROOT)): A.sha(p) for p in sources}
    population, d = A.load()
    assert np.allclose(
        population.early + population.middle1 + population.middle2 + population.late,
        population.finish,
    )
    records = []
    models = []
    matrices = {}
    for (meet, dist), g in d.groupby(["meet", "distance_m"], observed=True):
        for period in ["all_mad4", "recent_mad4"]:
            s = L.select(g, period)
            if not L.minimum(s, False):
                continue
            for kind in ["base", "state", "month"]:
                print(meet, dist, period, kind, len(s), flush=True)
                r, m = fit(
                    s,
                    dict(meet=meet, distance_m=int(dist), period=period, model_type=kind),
                    matrices,
                )
                records.extend(r)
                models.append(m)
    p = pd.DataFrame(records)
    p["q"] = 1.0
    for _, ix in p.groupby(
        ["model_type", "period", "section", "family"], observed=True
    ).groups.items():
        active = p.loc[ix].index[p.loc[ix].supported & p.loc[ix].p.notna()]
        if len(active):
            p.loc[active, "q"] = OLD.bh(p.loc[active, "p"].to_numpy())
    p["support"] = p.support.map(json.dumps)
    p.to_csv(OUT / "section_seconds_profiles.csv", index=False)
    tables = []
    for part in PARTS:
        B.POLICY["base_cap_seconds"] = CAPS[part][0]
        B.POLICY["state_cap_seconds"] = CAPS[part][1]
        base = p[p.model_type.eq("base") & p.section.eq(part)]
        state = p[p.model_type.eq("state") & p.section.eq(part)]
        table = B.build_table(population, base, state)
        table["section"] = part
        tables.append(table)
    gates = pd.concat(tables, ignore_index=True)
    gates.to_csv(OUT / "section_gate_lookup.csv", index=False)
    month = []
    for (meet, dist, part, period), g in p[p.model_type.eq("month")].groupby(
        ["meet", "distance_m", "section", "period"], observed=True
    ):
        g = g.copy()
        g["month"] = g.level.astype(int)
        g = g.sort_values("month")
        available = len(g) == 12 and g.estimable.all()
        n = np.array([json.loads(v)[0]["rows"] for v in g.support])
        raw = 0.30 * n / (n + 100) * g.effect_seconds.to_numpy() if available else np.zeros(len(g))
        centered = raw - raw.mean()
        scale = min(1.0, CAPS[part][2] / max(float(abs(centered).max()), 1e-15))
        add = -centered * scale
        for j, r in enumerate(g.itertuples()):
            month.append(
                dict(
                    meet=meet,
                    distance_m=int(dist),
                    section=part,
                    period=period,
                    month=r.month,
                    n=int(n[j]),
                    raw_effect=r.effect_seconds,
                    month_add_seconds=float(add[j]),
                    available=bool(available),
                    cap_scale=scale,
                    center=float(raw.mean()),
                )
            )
    pd.DataFrame(month).to_csv(OUT / "section_month_lookup.csv", index=False)
    moist = pd.read_csv(MOISTURE)
    moist["meet"] = moist.meet.map({1: "서울", 3: "부산"})
    moist["section"] = moist.part.map(
        {"start_200": "early", "last_600": "last600", "last_200": "late"}
    )
    moist["moisture_add_seconds"] = moist.add_seconds_retain80.where(moist.supported)
    moist.to_csv(OUT / "section_moisture_reference.csv", index=False)
    config = dict(
        version="section_candidate_v1_20261008",
        status="trial_only",
        available_from="2026-10-08",
        data_end={"서울": "2026-09-20", "부산": "2026-09-18"},
        parts=PARTS,
        caps=CAPS,
        base_fraction=0.30,
        state_fraction=0.15,
        month_fraction=0.30,
        shrink_k=100.0,
        full_time_version="gate_candidate_v1_20261008",
        middle_method="identity_residual",
        input_sha256=hashes,
    )
    A.dump(OUT / "config.json", config)
    A.dump(OUT / "models.json", models)
    np.savez_compressed(
        OUT / "model_matrices.npz",
        **{f"{key}_{name}": v for key, arrays in matrices.items() for name, v in arrays.items()},
    )
    spec = importlib.util.spec_from_file_location("section_apply", HERE / "apply.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    normalizer = helper.SectionNormalizer(OUT)
    ledger = normalizer.apply_population(population, as_of="2026-10-08")
    ledger.to_parquet(OUT / "runner_section_candidates.parquet", index=False)
    summary = dict(
        model_count=len(models),
        target_count=3,
        profile_rows=len(p),
        gate_lookup_rows=len(gates),
        month_lookup_rows=len(month),
        population_rows=len(population),
        common_full_mad4_rows=int(d.mad4_keep.sum()),
        complete_core_records=int(
            ledger[["early_candidate", "middle1_candidate", "middle2_candidate", "late_candidate"]]
            .notna()
            .all(axis=1)
            .sum()
        ),
        direct_supported_records={
            part: int(ledger[f"{part}_candidate"].notna().sum()) for part in PARTS
        },
        max_orthogonality=max(m["orthogonality_error"] for m in models),
        input_sha256=hashes,
        prediction_validation=False,
        production_changed=False,
    )
    A.dump(OUT / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "input_sha256"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
