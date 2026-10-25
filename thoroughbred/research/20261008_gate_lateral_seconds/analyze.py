"""Seconds contrasts within races/packs and horses; retrospective research only."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261008_record_normalization_seconds"
SPEC = importlib.util.spec_from_file_location("normalization", PREVIOUS / "analyze.py")
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
POP = OLD.POP
GATES = OLD.GATES
POSITIONS = HERE.parent / "20261003_joint_gate_lateral_smoothing/outputs/observations.parquet"
FOURC = HERE.parent / "20261004_seoul4c_finish/outputs/runner_4c_analysis.parquet"
LEDGER = PREVIOUS / "outputs/runner_normalization_candidates.parquet"
OLD_EFFECTS = PREVIOUS / "outputs/joint_seconds_profiles.csv"
PERIODS = OLD.PERIODS
NUMS = [name for name in OLD.NUMS if name != "race_no"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load():
    d = pd.read_parquet(POP)
    g = pd.read_parquet(GATES)
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
    masks = pd.read_parquet(LEDGER, columns=["row_key", "mad4_keep", "trim5_keep"])
    d = d.merge(masks, on="row_key", how="inner", validate="one_to_one")
    assert len(d) == 149624
    d["date"] = pd.to_datetime(d.date)
    d["horse_distance"] = d.horse_id + ":" + d.distance_m.astype(str)
    roster = g.groupby("race_key").horse_number.agg(lambda v: set(v) == set(range(1, len(v) + 1)))
    exact = d.race_key.map(roster) & d.n.isin([10, 12])
    d["gate_block"] = "other_" + d.n.map(
        lambda n: "6to9" if n <= 9 else str(n) if n <= 12 else "13plus"
    )
    d.loc[exact, "gate_block"] = "exact" + d.loc[exact, "n"].astype(str)
    for side in ["middle", "outer"]:
        fractions = g.gate_side.eq(side).groupby(g.race_key).mean()
        d[f"p_{side}"] = d.race_key.map(fractions)
    four = pd.read_parquet(FOURC, columns=["row_key", "finish", "closing4c"])
    d = d.merge(four, on="row_key", how="left", validate="one_to_one", suffixes=("", "_4c"))
    known = d.finish_4c.notna()
    assert d.loc[known, "finish"].eq(d.loc[known, "finish_4c"]).all()
    p = pd.read_parquet(
        POSITIONS,
        columns=[
            "race_key",
            "horse_number",
            "point",
            "pack_id",
            "pack_size",
            "lateral_side",
            "finish",
        ],
    )
    original_position_rows = len(p)
    p = p.merge(
        d,
        on=["race_key", "horse_number"],
        how="inner",
        validate="many_to_one",
        suffixes=("_position", ""),
    )
    assert p.finish_position.eq(p.finish).all()
    complete = p.groupby("pack_id").row_key.transform("size").eq(p.pack_size)
    removed_incomplete = int((~complete).sum())
    p = p[complete].copy()
    p["remaining"] = np.nan
    p.loc[p.point.eq("S1F"), "remaining"] = p.finish - p.early
    p.loc[p.point.eq("G1F"), "remaining"] = p.late
    p.loc[p.meet.eq("부산") & p.point.eq("G3F"), "remaining"] = p.last600
    use = p.meet.eq("서울") & p.point.eq("4C") & p.distance_m.eq(1200)
    p.loc[use, "remaining"] = p.closing4c
    audit = {
        "population_joined": 151074,
        "eligible_runner_rows": len(d),
        "position_source_rows": original_position_rows,
        "position_joined_complete_rows": len(p),
        "position_joined_incomplete_rows_removed": removed_incomplete,
        "position_complete_packs": p.pack_id.nunique(),
    }
    return d, p, audit


def select(frame, period, lateral=False):
    mask = pd.Series(True, index=frame.index)
    if period.endswith("mad4"):
        mask &= frame.mad4_keep
    if period == "all_trim5":
        mask &= frame.trim5_keep
    if period == "recent_mad4":
        mask &= frame.year.ge(2024)
    if period == "complete_mad4":
        mask &= frame.year.isin([2024, 2025])
    if lateral:
        mask = mask.groupby(frame.pack_id).transform("all")
    return frame[mask].reset_index(drop=True)


def controls(d):
    columns, names = [], []
    for name in NUMS:
        v = pd.to_numeric(d[name], errors="coerce")
        median = float(v.median()) if v.notna().any() else 0
        scale = max(float(v.quantile(0.75) - v.quantile(0.25)), 1) if v.notna().any() else 1
        z = (v.fillna(median).to_numpy(float) - median) / scale
        columns.append(z)
        names.append("control:" + name)
        if name in ["age", "rating", "body_weight"]:
            columns.append(z**2)
            names.append("control:" + name + "2")
        if v.isna().any():
            columns.append(v.isna().to_numpy(float))
            names.append("control:" + name + "_missing")
    return columns, names


def gate_design(d):
    original, labels, specs, _ = OLD.design(d)
    indices = [i for i, name in enumerate(labels) if name.startswith("gate:")]
    columns, names = controls(d)
    return (
        np.column_stack([original[:, indices], *columns]),
        [labels[i] for i in indices] + names,
        specs,
    )


def lateral_design(d):
    triple = d.pack_size.ge(3).to_numpy(float)
    columns = [
        triple * d.lateral_side.eq("middle").to_numpy(float),
        triple * d.lateral_side.eq("outer").to_numpy(float),
        (1 - triple) * d.lateral_side.eq("outer").to_numpy(float),
        d.gate_side.eq("middle").to_numpy(float),
        d.gate_side.eq("outer").to_numpy(float),
        d.gate_pct.to_numpy(float),
        d.gate_pct.to_numpy(float) ** 2,
    ]
    names = [
        "triple_middle",
        "triple_outer",
        "pair_outer",
        "gate_middle",
        "gate_outer",
        "gate_pct",
        "gate_pct2",
    ]
    c, n = controls(d)
    return np.column_stack(columns + c), names + n


def weights(d, lateral):
    if not lateral:
        return 1 / d.groupby("race_key").row_key.transform("size").to_numpy(float)
    packs = d.groupby("race_key").pack_id.transform("nunique")
    sides = np.where(d.pack_size.eq(2), 2, 3)
    middle = d.groupby(["pack_id", "lateral_side"]).row_key.transform("size")
    return 1 / (packs.to_numpy(float) * sides * middle.to_numpy(float))


def fe_groups(d, lateral, adjustment):
    unit = OLD.codes(d.pack_id if lateral else d.race_key)
    if adjustment == "unit_only":
        return [unit], len(np.unique(unit))
    horse = OLD.codes(d.horse_distance if lateral else d.horse_id)
    nh, nu = horse.max() + 1, unit.max() + 1
    adjacency = coo_matrix((np.ones(len(d)), (horse, unit + nh)), shape=(nh + nu, nh + nu)).tocsr()
    components = connected_components(adjacency, directed=False, return_labels=False)
    return [horse, unit], int(nh + nu - components)


def absorb(matrix, groups, w):
    original = np.asarray(matrix, float)
    if len(groups) == 1:
        current, _ = OLD.within(original, groups[0], w)
    else:
        horse, unit = groups
        nh, nu = int(horse.max()) + 1, int(unit.max()) + 1
        adjacency = coo_matrix(
            (np.ones(len(horse)), (horse, unit + nh)), shape=(nh + nu, nh + nu)
        ).tocsr()
        _, labels = connected_components(adjacency, directed=False)
        _, first_units = np.unique(labels[nh:], return_index=True)
        keep = np.ones(nh + nu, dtype=bool)
        keep[nh + first_units] = False
        row = np.concatenate([np.arange(len(horse)), np.arange(len(horse))])
        col = np.concatenate([horse, nh + unit])
        fixed = coo_matrix((np.ones(len(row)), (row, col)), shape=(len(horse), nh + nu)).tocsr()[
            :, keep
        ]
        gram = (fixed.T @ fixed.multiply(w[:, None])).tocsc()
        factor = splu(gram)
        coefficients = factor.solve(np.asarray(fixed.T @ (w[:, None] * original)))
        current = original - fixed @ coefficients
    orthogonality = max(float(np.max(abs(OLD.within(current, group, w)[1]))) for group in groups)
    assert orthogonality < 1e-8, orthogonality
    return current, 1, orthogonality


def contrast_specs(d, labels, specs, lateral):
    result = []

    def add(vector, family, block, level, samples):
        details = [
            {
                "rows": len(g),
                "races": g.race_key.nunique(),
                "days": g.date.nunique(),
                "packs": g.pack_id.nunique() if lateral else 0,
            }
            for g in samples
        ]
        if lateral:
            supported = all(
                s["rows"] >= 100 and s["packs"] >= 50 and s["races"] >= 30 and s["days"] >= 20
                for s in details
            )
            strict = supported
        else:
            supported = all(
                s["rows"] >= 50 and s["races"] >= 50 and s["days"] >= 20 for s in details
            )
            strict = supported and all(s["rows"] >= 100 for s in details)
        result.append(
            (
                vector,
                {
                    "family": family,
                    "block": block,
                    "level": str(level),
                    "supported": bool(supported),
                    "strict_supported": bool(strict),
                    "minimum_rows": min(s["rows"] for s in details),
                    "support": details,
                },
            )
        )

    if lateral:
        for block, level, coefficients, sides in [
            ("pair", "outer-inner", [0, 0, 1], ["inner", "outer"]),
            ("triple", "middle-inner", [1, 0, 0], ["middle", "inner"]),
            ("triple", "outer-inner", [0, 1, 0], ["outer", "inner"]),
            ("triple", "outer-middle", [-1, 1, 0], ["outer", "middle"]),
        ]:
            b = d[d.pack_size.eq(2) if block == "pair" else d.pack_size.ge(3)]
            v = np.zeros(len(labels))
            v[:3] = coefficients
            add(v, block, block, level, [b[b.lateral_side.eq(s)] for s in sides])
    else:
        for block, levels in specs.items():
            b = d[d.gate_block.eq(block)]
            numbered = {}
            for level in levels:
                v = np.zeros(len(labels))
                if block.startswith("exact"):
                    for other in levels[1:]:
                        v[labels.index(f"gate:{block}:{other}")] = float(level == other) - 1 / len(
                            levels
                        )
                    numbered[level] = v
                    samples = [b[b.horse_number.eq(level)], b]
                    family = "number"
                else:
                    for side in levels[1:]:
                        share = b.groupby("race_key")[f"p_{side}"].first().mean()
                        v[labels.index(f"gate:{block}:{side}")] = float(level == side) - share
                    samples = [b[b.gate_side.eq(s)] for s in levels]
                    family = "group"
                add(v, family, block, level, samples)
            if block.startswith("exact"):
                for side in ["inner", "middle", "outer"]:
                    numbers = sorted(b[b.gate_side.eq(side)].horse_number.unique())
                    v = np.mean([numbered[int(number)] for number in numbers], axis=0)
                    add(
                        v,
                        "group",
                        block,
                        side,
                        [b[b.gate_side.eq(s)] for s in ["inner", "middle", "outer"]],
                    )
    return result


def fit(d, meta, matrices):
    lateral = meta["kind"] == "lateral"
    if lateral:
        x, labels = lateral_design(d)
        specs = None
    else:
        x, labels, specs = gate_design(d)
    targets = ["finish"]
    if lateral and d.remaining.notna().all():
        targets.append("remaining")
    w = weights(d, lateral)
    groups, fe_rank = fe_groups(d, lateral, meta["adjustment"])
    joint, iterations, orthogonality = absorb(
        np.column_stack([x, d[targets].to_numpy(float)]), groups, w
    )
    xd, y = joint[:, : len(labels)], joint[:, len(labels) :]
    gram = xd.T @ (w[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    rank = int(np.linalg.matrix_rank(gram, tol=np.linalg.norm(gram, 2) * 1e-11))
    dof = len(d) - fe_rank - rank
    if dof <= 5:
        return [], None
    beta = inv @ (xd.T @ (w[:, None] * y))
    residual = y - xd @ beta
    contrasts = contrast_specs(d, labels, specs, lateral)
    vectors = np.vstack([r[0] for r in contrasts])
    projection = inv @ gram
    df = min(d.horse_id.nunique(), d.date.nunique()) - 1
    key = str(len(matrices))
    arrays = {"beta": beta, "vectors": vectors}
    records = []
    for j, metric in enumerate(targets):
        score = xd * (w * residual[:, j])[:, None]
        correction = (len(d) - 1) / dof
        vh = inv @ OLD.cluster(score, d.horse_id) @ inv * correction
        vd = inv @ OLD.cluster(score, d.date) @ inv * correction
        vi = inv @ OLD.cluster(score, d.horse_id + ":" + d.date.astype(str)) @ inv * correction
        cov = vh + vd - vi
        for name, array in [("cov", cov), ("cov_horse", vh), ("cov_day", vd)]:
            arrays[f"{metric}_{name}"] = array
        variance = np.maximum.reduce(
            [np.einsum("ij,jk,ik->i", vectors, c, vectors) for c in [cov, vh, vd]]
        )
        se = np.sqrt(np.maximum(variance, 0))
        values = vectors @ beta[:, j]
        for i, (_, identity) in enumerate(contrasts):
            estimable = bool(np.allclose(vectors[i] @ projection, vectors[i], atol=1e-6))
            critical = t.ppf(0.975, df)
            records.append(
                meta
                | identity
                | {
                    "metric": metric,
                    "effect_seconds": float(values[i]),
                    "se": float(se[i]),
                    "ci_low": float(values[i] - critical * se[i]),
                    "ci_high": float(values[i] + critical * se[i]),
                    "p": float(2 * t.sf(abs(values[i]) / max(se[i], 1e-15), df)),
                    "supported": bool(identity["supported"] and estimable),
                    "estimable": estimable,
                    "model_rows": len(d),
                    "model_races": d.race_key.nunique(),
                    "model_days": d.date.nunique(),
                    "model_packs": d.pack_id.nunique() if lateral else 0,
                    "year_min": int(d.year.min()),
                    "year_max": int(d.year.max()),
                }
            )
    matrices[key] = arrays
    model = meta | {
        "matrix_key": key,
        "labels": labels,
        "targets": targets,
        "rows": len(d),
        "fe_rank": fe_rank,
        "rank": rank,
        "residual_df": int(dof),
        "df": int(df),
        "iterations": iterations,
        "orthogonality_error": orthogonality,
        "normal_error": float(np.max(abs(xd.T @ (w[:, None] * residual)))),
    }
    return records, model


def minimum(d, lateral):
    if lateral:
        return (
            d.pack_id.nunique() >= 100
            and d.race_key.nunique() >= 50
            and d.date.nunique() >= 20
            and d.horse_id.nunique() >= 30
        )
    return d.race_key.nunique() >= 100 and d.date.nunique() >= 30 and d.horse_id.nunique() >= 100


def gate_candidates(profiles, population):
    gates = profiles[profiles.kind.eq("gate")]
    prior = pd.read_csv(OLD_EFFECTS, dtype={"level": str}).query("kind != 'month'")
    old_lookup = prior.set_index(["meet", "distance_m", "kind", "block", "level", "period"])
    keys = ["meet", "distance_m", "family", "block", "level"]
    lookup = gates.set_index(keys + ["adjustment", "period"])
    result = []
    for key, _ in gates.groupby(keys, observed=True):
        rows = [
            lookup.loc[(*key, "dual", period)] if (*key, "dual", period) in lookup.index else None
            for period in PERIODS
        ]
        other = [
            lookup.loc[(*key, "unit_only", period)]
            if (*key, "unit_only", period) in lookup.index
            else None
            for period in ["all_mad4", "recent_mad4"]
        ]
        olds = [
            old_lookup.loc[(*key, period)] if (*key, period) in old_lookup.index else None
            for period in PERIODS
        ]
        support = all(row is not None and row.supported for row in rows)
        values = rows + other + olds
        stable = (
            all(row is not None for row in values)
            and len({np.sign(row.effect_seconds) for row in values}) == 1
        )
        full, recent = rows[1], rows[3]
        significant = full is not None and recent is not None and full.q < 0.05 and recent.q < 0.05
        tier = (
            "A"
            if support and all(row.strict_supported for row in rows)
            else "B"
            if support
            else "unsupported"
        )
        n = min(row.minimum_rows for row in rows if row is not None)
        bound = 0
        if support and stable and significant:
            bound = min(
                min(abs(row.ci_low), abs(row.ci_high)) if row.ci_low * row.ci_high > 0 else 0
                for row in [full, recent]
            )
        amount = min(0.15 if tier == "A" else 0.05, 0.5 * bound * n / (n + 100))
        evidence = (
            -np.sign(full.effect_seconds) * np.floor((amount + 1e-12) * 100) / 100
            if full is not None
            else 0
        )
        result.append(
            dict(zip(keys, key, strict=True))
            | {
                "tier": tier,
                "all_five_supported": bool(support),
                "all_twelve_directions_stable": bool(stable),
                "full_recent_q_pass": bool(significant),
                "minimum_rows": int(n),
                "nearest_ci_bound": float(bound),
                "evidence_add_seconds": float(evidence),
                "full_effect": float(full.effect_seconds) if full is not None else np.nan,
                "recent_effect": float(recent.effect_seconds) if recent is not None else np.nan,
            }
        )
    c = pd.DataFrame(result)
    c["centering_shift"] = 0.0
    c["centered_add_seconds"] = c.evidence_add_seconds
    for _, g in c[c.family.eq("number")].groupby(["meet", "distance_m", "block"]):
        shift = -g.evidence_add_seconds.mean()
        c.loc[g.index, "centering_shift"] = shift
        c.loc[g.index, "centered_add_seconds"] += shift
    for (meet, distance, block), g in c[c.family.eq("group")].groupby(
        ["meet", "distance_m", "block"]
    ):
        base = population[
            population.meet.eq(meet)
            & population.distance_m.eq(distance)
            & population.gate_block.eq(block)
        ].drop_duplicates("race_key")
        shares = {"middle": base.p_middle.mean(), "outer": base.p_outer.mean()}
        shares["inner"] = 1 - shares["middle"] - shares["outer"]
        shift = -sum(r.evidence_add_seconds * shares[r.level] for r in g.itertuples())
        c.loc[g.index, "centering_shift"] = shift
        c.loc[g.index, "centered_add_seconds"] += shift
    return c


def field_lookup(candidates, population):
    rows = []
    for (meet, distance, block), c in candidates.groupby(["meet", "distance_m", "block"]):
        base = population[
            population.meet.eq(meet)
            & population.distance_m.eq(distance)
            & population.gate_block.eq(block)
        ]
        numbers = c[c.family.eq("number")]
        if len(numbers) and numbers.evidence_add_seconds.ne(0).any():
            for r in numbers.itertuples():
                rows.append(
                    {
                        "meet": meet,
                        "distance_m": int(distance),
                        "block": block,
                        "field_size": int(block[5:]),
                        "family": "number",
                        "level": r.level,
                        "evidence_add_seconds": r.evidence_add_seconds,
                        "centering_shift": r.centering_shift,
                        "add_seconds": r.centered_add_seconds,
                        "tier": r.tier,
                    }
                )
        else:
            group = c[c.family.eq("group")]
            for n, b in base.groupby("n"):
                shares = {"middle": float(b.p_middle.iloc[0]), "outer": float(b.p_outer.iloc[0])}
                shares["inner"] = 1 - shares["middle"] - shares["outer"]
                shift = -sum(r.evidence_add_seconds * shares[r.level] for r in group.itertuples())
                for r in group.itertuples():
                    rows.append(
                        {
                            "meet": meet,
                            "distance_m": int(distance),
                            "block": block,
                            "field_size": int(n),
                            "family": "group",
                            "level": r.level,
                            "evidence_add_seconds": r.evidence_add_seconds,
                            "centering_shift": shift,
                            "add_seconds": r.evidence_add_seconds + shift,
                            "tier": r.tier,
                        }
                    )
    return pd.DataFrame(rows)


def main():
    assert not (OUT / "summary.json").exists()
    inputs = [
        POP,
        GATES,
        POSITIONS,
        FOURC,
        LEDGER,
        OLD_EFFECTS,
        PREVIOUS / "analyze.py",
        HERE / "PLAN.md",
        HERE / "analyze.py",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    d, positions, audit = load()
    records, models, matrices, coverage = [], [], {}, []
    for (meet, distance), base in d.groupby(["meet", "distance_m"], observed=True):
        for adjustment in ["dual", "unit_only"]:
            for period in PERIODS if adjustment == "dual" else ["all_mad4", "recent_mad4"]:
                sample = select(base, period)
                if not minimum(sample, False):
                    continue
                meta = {
                    "kind": "gate",
                    "meet": meet,
                    "distance_m": int(distance),
                    "point": "start",
                    "period": period,
                    "adjustment": adjustment,
                }
                rows, model = fit(sample, meta, matrices)
                records.extend(rows)
                if model is not None:
                    models.append(model)
        print("gate", meet, int(distance), "done", flush=True)
    for (meet, point), base in positions.groupby(["meet", "point"], observed=True):
        for distance in [0] + sorted(base.distance_m.unique()):
            subset = base if distance == 0 else base[base.distance_m.eq(distance)]
            periods = PERIODS if distance == 0 else ["all_mad4", "recent_mad4", "complete_mad4"]
            for period in periods:
                sample = select(subset, period, lateral=True)
                supported = minimum(sample, True)
                coverage.append(
                    {
                        "meet": meet,
                        "point": point,
                        "distance_m": int(distance),
                        "period": period,
                        "rows": len(sample),
                        "packs": sample.pack_id.nunique(),
                        "fit_supported": bool(supported),
                    }
                )
                if not supported:
                    continue
                meta = {
                    "kind": "lateral",
                    "meet": meet,
                    "distance_m": int(distance),
                    "point": point,
                    "period": period,
                    "adjustment": "dual",
                }
                rows, model = fit(sample, meta, matrices)
                records.extend(rows)
                if model is not None:
                    models.append(model)
        print("lateral", meet, point, "done", flush=True)
    profiles = pd.DataFrame(records)
    profiles["q"] = 1.0
    for _, g in profiles.groupby(
        ["kind", "adjustment", "period", "metric", "family"], observed=True
    ):
        ix = g.index[g.supported]
        if len(ix):
            profiles.loc[ix, "q"] = OLD.bh(profiles.loc[ix, "p"].to_numpy())
    profiles["support"] = profiles.support.map(json.dumps)
    profiles.to_csv(OUT / "seconds_profiles.csv", index=False)
    candidates = gate_candidates(profiles, d)
    candidates.to_csv(OUT / "gate_correction_candidates.csv", index=False)
    field_lookup(candidates, d).to_csv(OUT / "field_gate_lookup.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "lateral_coverage.csv", index=False)
    dump(OUT / "models.json", models)
    arrays = {
        f"{key}_{name}": value for key, matrix in matrices.items() for name, value in matrix.items()
    }
    np.savez_compressed(OUT / "model_matrices.npz", **arrays)
    summary = {
        "completed_on": "2026-10-08",
        "input_sha256": hashes,
        "population": audit,
        "model_count": len(models),
        "profile_rows": len(profiles),
        "gate_nonzero_evidence_cells": int(candidates.evidence_add_seconds.ne(0).sum()),
        "gate_nonzero_evidence_by_tier": candidates[candidates.evidence_add_seconds.ne(0)]
        .groupby("tier")
        .size()
        .to_dict(),
        "lateral_automatic_add": "pending_zero",
        "new_prediction_validation": False,
        "new_correction_adopted": False,
        "production_changed": False,
        "max_absorption_iterations": max(m["iterations"] for m in models),
        "max_absorption_orthogonality_error": max(m["orthogonality_error"] for m in models),
    }
    assert all(sha(ROOT / name) == digest for name, digest in hashes.items())
    dump(OUT / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "input_sha256"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
