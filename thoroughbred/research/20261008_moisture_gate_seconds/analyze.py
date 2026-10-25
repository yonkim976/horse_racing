"""Retrospective moisture-by-gate contrasts; fixed local inputs, no database writes."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREV = HERE.parent / "20261008_gate_lateral_seconds"
SPEC = importlib.util.spec_from_file_location("gate_seconds", PREV / "analyze.py")
L = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L)
BANDS = ["건조", "양호", "다습", "포화", "불량"]
BLOCKS = ["exact10", "exact12", "other_6to9", "other_10", "other_11", "other_12", "other_13plus"]
SIDES = ["inner", "middle", "outer"]
PERIODS = L.PERIODS
sha, dump = L.sha, L.dump


def load():
    d = pd.read_parquet(L.POP)
    g = pd.read_parquet(L.GATES)
    g["row_key"] = (
        g.meet.map({1: "서울", 3: "부산"})
        + ":"
        + g.date.str.replace("-", "")
        + ":"
        + g.race_no.astype(str)
        + ":"
        + g.horse_id
    )
    d = d.merge(
        g[
            [
                "row_key",
                "race_key",
                "race_no",
                "horse_number",
                "n",
                "gate_side",
                "gate_pct",
                "finish",
            ]
        ],
        on="row_key",
        validate="one_to_one",
        suffixes=("", "_gate"),
    )
    assert len(d) == 151074 and d.finish.eq(d.finish_gate).all()
    d["date"] = pd.to_datetime(d.date)
    roster = g.groupby("race_key").horse_number.agg(lambda v: set(v) == set(range(1, len(v) + 1)))
    exact = d.race_key.map(roster) & d.n.isin([10, 12])
    d["gate_block"] = "other_" + d.n.map(
        lambda n: "6to9" if n <= 9 else str(n) if n <= 12 else "13plus"
    )
    d.loc[exact, "gate_block"] = "exact" + d.loc[exact, "n"].astype(str)
    for side in SIDES:
        d[f"p_{side}"] = d.race_key.map(g.gate_side.eq(side).groupby(g.race_key).mean())
    masks = pd.read_parquet(L.LEDGER, columns=["row_key", "mad4_keep", "trim5_keep"])
    return d, d.merge(masks, on="row_key", validate="one_to_one")


def levels(block):
    return list(range(1, int(block[5:]) + 1)) if block.startswith("exact") else SIDES


def design(d):
    cols, labels, entries = [], [], []
    for (band, block), _g in d.groupby(["band", "gate_block"], observed=True, sort=True):
        lv = levels(block)
        local = []
        mask = (d.band.eq(band) & d.gate_block.eq(block)).to_numpy(float)
        for level in lv[1:]:
            test = d.horse_number.eq(level) if block.startswith("exact") else d.gate_side.eq(level)
            local.append(len(cols))
            cols.append(mask * test.to_numpy(float))
            labels.append(f"gate:{band}:{block}:{level}")
        entries.append((band, block, lv, local))
    controls, names = L.controls(d)
    return np.column_stack(cols + controls), labels + names, entries


def contrast_specs(d, labels, entries):
    result, effects = [], {}

    def stats(g):
        return dict(rows=len(g), races=int(g.race_key.nunique()), days=int(g.date.nunique()))

    def add(v, band, block, family, level, samples, reference=""):
        counts = [stats(g) for g in samples]
        supported = all(s["rows"] >= 50 and s["races"] >= 50 and s["days"] >= 20 for s in counts)
        strict = supported and all(s["rows"] >= 100 for s in counts)
        result.append(
            (
                v,
                dict(
                    band=band,
                    block=block,
                    family=family,
                    level=str(level),
                    reference_band=reference,
                    supported=supported,
                    strict_supported=strict,
                    minimum_rows=min(s["rows"] for s in counts),
                    support=counts,
                ),
            )
        )

    for band, block, lv, indices in entries:
        b = d[d.band.eq(band) & d.gate_block.eq(block)]
        numbered = {}
        if block.startswith("exact"):
            for level in lv:
                v = np.zeros(len(labels))
                v[indices] = [float(level == other) - 1 / len(lv) for other in lv[1:]]
                samples = [b[b.horse_number.eq(level)], b]
                add(v, band, block, "number", level, samples)
                effects[(band, block, "number", str(level))] = (v, samples)
                numbered[level] = v
            n = len(lv)
            for side in SIDES:
                nums = [i for i in lv if SIDES[min(int(3 * (i - 0.5) / n), 2)] == side]
                v = np.mean([numbered[i] for i in nums], axis=0)
                samples = [b[b.gate_side.eq(s)] for s in SIDES]
                add(v, band, block, "group", side, samples)
                effects[(band, block, "group", side)] = (v, samples)
        else:
            shares = b.groupby("race_key")[["p_middle", "p_outer"]].first().mean().to_numpy()
            for side in SIDES:
                v = np.zeros(len(labels))
                v[indices] = [float(side == s) - p for s, p in zip(SIDES[1:], shares, strict=True)]
                samples = [b[b.gate_side.eq(s)] for s in SIDES]
                add(v, band, block, "group", side, samples)
                effects[(band, block, "group", side)] = (v, samples)
        outer = effects[(band, block, "group", "outer")][0]
        inner = effects[(band, block, "group", "inner")][0]
        samples = [b[b.gate_side.eq(s)] for s in ["inner", "outer"]]
        add(outer - inner, band, block, "outer_inner", "outer-inner", samples)
        effects[(band, block, "outer_inner", "outer-inner")] = (outer - inner, samples)
    for (band, block, family, level), (v, samples) in list(effects.items()):
        ref = effects.get(("건조", block, family, level))
        if band == "건조" or ref is None or family == "group":
            continue
        add(
            v - ref[0],
            band,
            block,
            "interaction",
            family + ":" + level,
            samples + ref[1],
            reference="건조",
        )
    return result


def fit(d, meta, matrices):
    x, labels, entries = design(d)
    w = L.weights(d, False)
    groups, fe_rank = L.fe_groups(d, False, meta["adjustment"])
    z, _, orth = L.absorb(np.column_stack([x, d.finish]), groups, w)
    xd, y = z[:, : len(labels)], z[:, -1]
    gram = xd.T @ (w[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    rank = int(np.linalg.matrix_rank(gram, tol=np.linalg.norm(gram, 2) * 1e-11))
    dof = len(d) - fe_rank - rank
    assert dof > 5
    beta = inv @ (xd.T @ (w * y))
    residual = y - xd @ beta
    score = xd * (w * residual)[:, None]
    factor = (len(d) - 1) / dof
    vh = inv @ L.OLD.cluster(score, d.horse_id) @ inv * factor
    vd = inv @ L.OLD.cluster(score, d.date) @ inv * factor
    vi = inv @ L.OLD.cluster(score, d.horse_id + ":" + d.date.astype(str)) @ inv * factor
    cov = vh + vd - vi
    specs = contrast_specs(d, labels, entries)
    vectors = np.vstack([s[0] for s in specs])
    values = vectors @ beta
    variance = np.maximum.reduce(
        [np.einsum("ij,jk,ik->i", vectors, c, vectors) for c in [cov, vh, vd]]
    )
    se = np.sqrt(np.maximum(variance, 0))
    df = min(d.horse_id.nunique(), d.date.nunique()) - 1
    critical = t.ppf(0.975, df)
    projection = inv @ gram
    key = str(len(matrices))
    matrices[key] = dict(beta=beta, vectors=vectors, cov=cov, cov_horse=vh, cov_day=vd)
    records = []
    for i, (v, identity) in enumerate(specs):
        estimable = bool(np.allclose(v @ projection, v, atol=1e-6))
        records.append(
            meta
            | identity
            | dict(
                estimable=estimable,
                supported=bool(identity["supported"] and estimable),
                strict_supported=bool(identity["strict_supported"] and estimable),
                effect_seconds=float(values[i]) if estimable else None,
                se=float(se[i]) if estimable else None,
                ci_low=float(values[i] - critical * se[i]) if estimable else None,
                ci_high=float(values[i] + critical * se[i]) if estimable else None,
                p=float(2 * t.sf(abs(values[i]) / max(se[i], 1e-15), df)) if estimable else None,
                matrix_key=key,
                contrast_index=i,
            )
        )
    model = meta | dict(
        matrix_key=key,
        labels=labels,
        rows=len(d),
        races=int(d.race_key.nunique()),
        days=int(d.date.nunique()),
        horses=int(d.horse_id.nunique()),
        fe_rank=fe_rank,
        rank=rank,
        residual_df=dof,
        df=int(df),
        orthogonality_error=orth,
        normal_error=float(np.max(abs(xd.T @ (w * residual)))),
    )
    return records, model


def coverage(d):
    rows = []
    for (meet, dist), allg in d.groupby(["meet", "distance_m"], observed=True):
        for band in BANDS:
            for block in BLOCKS:
                b = allg[allg.band.eq(band) & allg.gate_block.eq(block)]
                families = ["group", "outer_inner"] + (
                    ["number"] if block.startswith("exact") else []
                )
                for family in families:
                    for level in (
                        levels(block)
                        if family == "number"
                        else SIDES
                        if family == "group"
                        else ["outer-inner"]
                    ):
                        cell = (
                            b[b.horse_number.eq(level)]
                            if family == "number"
                            else b[b.gate_side.eq(level)]
                            if family == "group"
                            else b
                        )
                        rows.append(
                            dict(
                                meet=meet,
                                distance_m=int(dist),
                                band=band,
                                block=block,
                                family=family,
                                level=str(level),
                                observed_rows=len(cell),
                                observed_races=int(cell.race_key.nunique()),
                                observed_days=int(cell.date.nunique()),
                                observed=bool(len(cell)),
                            )
                        )
    return pd.DataFrame(rows)


def candidates(p):
    keys = ["meet", "distance_m", "band", "block", "family", "level"]
    lookup = p.set_index(keys + ["adjustment", "period"])
    result = []
    for key, _ in p[p.family.isin(["number", "group"])].groupby(keys, observed=True):
        main = [
            lookup.loc[(*key, "dual", period)] if (*key, "dual", period) in lookup.index else None
            for period in PERIODS
        ]
        extra = [
            lookup.loc[(*key, "unit_only", period)]
            if (*key, "unit_only", period) in lookup.index
            else None
            for period in ["all_mad4", "recent_mad4"]
        ]
        rows = main + extra
        strict = all(r is not None and r.strict_supported for r in main)
        supported = all(r is not None and r.supported for r in rows)
        stable = supported and len({np.sign(r.effect_seconds) for r in rows}) == 1
        full, recent = main[1], main[3]
        sig = full is not None and recent is not None and full.q < 0.05 and recent.q < 0.05
        n = min([r.minimum_rows for r in main if r is not None], default=0)
        raw = 0.0
        if strict and stable and sig:
            boundary = min(
                min(abs(r.ci_low), abs(r.ci_high)) if r.ci_low * r.ci_high > 0 else 0
                for r in [full, recent]
            )
            amount = min(0.1, 0.5 * boundary * n / (n + 100))
            raw = -np.sign(full.effect_seconds) * np.floor(amount * 100 + 1e-9) / 100
        result.append(
            dict(zip(keys, key, strict=True))
            | dict(
                all_strict=strict,
                all_supported=supported,
                stable=stable,
                full_recent_q_pass=bool(sig),
                minimum_rows=int(n),
                raw_candidate_add=float(raw),
            )
        )
    c = pd.DataFrame(result)
    c["candidate_add"] = 0.0
    c["block_complete_strict"] = False
    for _, indices in c.groupby(keys[:5], observed=True).groups.items():
        g = c.loc[indices]
        expected = int(g.block.iloc[0][5:]) if g.family.iloc[0] == "number" else 3
        complete = len(g) == expected and g.all_strict.all()
        c.loc[indices, "block_complete_strict"] = complete
        if complete:
            # Exact numbered and exact grouped shares are fixed; other group shares from source.
            if g.family.iloc[0] == "number":
                weights = np.ones(len(g))
            else:
                weights = g["level"].map({"inner": 1.0, "middle": 1.0, "outer": 1.0}).to_numpy()
                block = g.block.iloc[0]
                if block == "exact10":
                    weights = g["level"].map({"inner": 3.0, "middle": 4.0, "outer": 3.0}).to_numpy()
                elif not block.startswith("exact"):
                    # This path is finalized with population shares in main below.
                    weights = np.ones(len(g))
            c.loc[indices, "candidate_add"] = g.raw_candidate_add - np.average(
                g.raw_candidate_add, weights=weights
            )
    return c


def main():
    OUT.mkdir(exist_ok=True)
    sources = [
        L.POP,
        L.GATES,
        L.LEDGER,
        PREV / "analyze.py",
        L.PREVIOUS / "analyze.py",
        HERE / "PLAN.md",
        HERE / "analyze.py",
    ]
    input_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    population, d = load()
    assert len(d) == 149624
    cover = coverage(population)
    matrices, models, records = {}, [], []
    for (meet, dist), g in d.groupby(["meet", "distance_m"], observed=True, sort=True):
        for adjustment in ["dual", "unit_only"]:
            for period in PERIODS if adjustment == "dual" else ["all_mad4", "recent_mad4"]:
                s = L.select(g, period)
                if not L.minimum(s, False):
                    continue
                print(meet, dist, adjustment, period, len(s), flush=True)
                r, m = fit(
                    s,
                    dict(meet=meet, distance_m=int(dist), adjustment=adjustment, period=period),
                    matrices,
                )
                records.extend(r)
                models.append(m)
    p = pd.DataFrame(records)
    p["q"] = 1.0
    for _, ix in p.groupby(["adjustment", "period", "family"], observed=True).groups.items():
        valid = p.loc[ix].supported & p.loc[ix].p.notna()
        active = p.loc[ix].index[valid]
        if len(active):
            p.loc[active, "q"] = L.OLD.bh(p.loc[active, "p"].to_numpy())
    c = candidates(p)
    for (meet, dist, band, block, family), ix in c.groupby(
        ["meet", "distance_m", "band", "block", "family"], observed=True
    ).groups.items():
        if (
            family == "group"
            and not block.startswith("exact")
            and c.loc[ix].block_complete_strict.all()
        ):
            b = population[
                population.meet.eq(meet)
                & population.distance_m.eq(dist)
                & population.band.eq(band)
                & population.gate_block.eq(block)
            ]
            shares = b.groupby("race_key")[[f"p_{s}" for s in SIDES]].first().mean()
            w = c.loc[ix, "level"].map({s: shares[f"p_{s}"] for s in SIDES})
            c.loc[ix, "candidate_add"] = c.loc[ix, "raw_candidate_add"] - np.average(
                c.loc[ix, "raw_candidate_add"], weights=w
            )
    p["support"] = p.support.map(json.dumps)
    p.to_csv(OUT / "seconds_profiles.csv", index=False)
    c.to_csv(OUT / "correction_candidates.csv", index=False)
    for period in PERIODS:
        v = p[p.adjustment.eq("dual") & p.period.eq(period) & ~p.family.eq("interaction")]
        cols = ["meet", "distance_m", "band", "block", "family", "level"]
        v = v[
            cols
            + [
                "supported",
                "strict_supported",
                "estimable",
                "effect_seconds",
                "ci_low",
                "ci_high",
                "q",
                "minimum_rows",
            ]
        ]
        v = v.rename(columns={name: period + "_" + name for name in v if name not in cols})
        cover = cover.merge(v, on=cols, how="left", validate="one_to_one")
    cover["status"] = np.select(
        [
            ~cover.observed,
            cover.all_mad4_estimable.isna(),
            ~cover.all_mad4_estimable.fillna(False).astype(bool),
            ~cover.all_mad4_supported.fillna(False).astype(bool),
        ],
        ["unobserved", "model_unavailable", "nonestimable", "low_support"],
        default="supported",
    )
    cover.to_csv(OUT / "coverage_grid.csv", index=False)
    dump(OUT / "models.json", models)
    np.savez_compressed(
        OUT / "model_matrices.npz",
        **{f"{key}_{name}": v for key, arrays in matrices.items() for name, v in arrays.items()},
    )
    summary = dict(
        population_rows=len(population),
        population_races=int(population.race_key.nunique()),
        eligible_rows=len(d),
        mad4_rows=int(d.mad4_keep.sum()),
        venue_distance_pairs=population.groupby(["meet", "distance_m"]).ngroups,
        model_count=len(models),
        profile_rows=len(p),
        coverage_rows=len(cover),
        status_counts=cover.status.value_counts().to_dict(),
        candidate_nonzero=int(c.candidate_add.abs().gt(1e-12).sum()),
        raw_candidate_nonzero=int(c.raw_candidate_add.ne(0).sum()),
        q_pass_counts=p[p.adjustment.eq("dual") & p.q.lt(0.05)]
        .groupby(["period", "family"])
        .size()
        .rename("count")
        .reset_index()
        .to_dict("records"),
        input_sha256=input_hashes,
        max_orthogonality=max(m["orthogonality_error"] for m in models),
        predictive_validation=False,
        new_correction_adopted=False,
        production_changed=False,
    )
    dump(OUT / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "input_sha256"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
