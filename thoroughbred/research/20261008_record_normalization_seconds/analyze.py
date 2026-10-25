"""Retrospective seconds normalization; no next-race prediction experiment."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
POP = HERE.parent / "20261007_sex_ability_gap/outputs/population.parquet"
GATES = HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet"
MOISTURE = HERE.parent / "20261002_moisture_strength_selection/outputs/reference_seconds.csv"
NUMS = [
    "age",
    "weight",
    "body_weight",
    "rating",
    "prior_finish",
    "prior_top3",
    "prior_early",
    "log_starts",
    "log_gap",
    "race_no",
]
PERIODS = ["all_raw", "all_mad4", "all_trim5", "recent_mad4", "complete_mad4"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def bh(p):
    order = np.argsort(p)
    adjusted = np.minimum.accumulate(
        (np.asarray(p)[order] * len(p) / np.arange(1, len(p) + 1))[::-1]
    )[::-1]
    result = np.empty(len(p))
    result[order] = np.minimum(adjusted, 1)
    return result


def codes(values):
    return pd.factorize(values, sort=False)[0]


def within(a, group, weights):
    a = np.asarray(a, float)
    if a.ndim == 1:
        a = a[:, None]
    total = np.bincount(group, weights=weights)
    means = np.column_stack([np.bincount(group, weights=weights * v) / total for v in a.T])
    return a - means[group], means


def cluster(score, values):
    group = codes(values)
    count = int(group.max()) + 1
    sums = np.column_stack([np.bincount(group, weights=x) for x in score.T])
    return sums.T @ sums * count / max(count - 1, 1)


def design(d):
    arrays, labels = [], []
    angle = 2 * np.pi * (d.month.to_numpy(float) - 1) / 12
    for h in [1, 2]:
        for name, values in [("sin", np.sin(h * angle)), ("cos", np.cos(h * angle))]:
            arrays.append(values)
            labels.append(f"month_{name}{h}")
    gate_specs = {}
    for block in sorted(d.gate_block.unique()):
        choose = d.gate_block.eq(block).to_numpy(float)
        if block.startswith("exact"):
            n = int(block[5:])
            gate_specs[block] = list(range(1, n + 1))
            for number in range(2, n + 1):
                arrays.append(choose * (d.horse_number.eq(number).to_numpy(float) - 1 / n))
                labels.append(f"gate:{block}:{number}")
        else:
            gate_specs[block] = ["inner", "middle", "outer"]
            for side in ["middle", "outer"]:
                arrays.append(choose * (d.gate_side.eq(side).to_numpy(float) - d[f"p_{side}"]))
                labels.append(f"gate:{block}:{side}")
    factors = {
        "grade_year": d.year.astype(str) + ":" + d.grade.astype(str),
        "moisture": d.moisture,
        "field_size": d.n,
        "sex_condition": d.sex_condition.fillna("unknown"),
    }
    for name, values in factors.items():
        for level in sorted(values.unique())[1:]:
            arrays.append(values.eq(level).to_numpy(float))
            labels.append(f"control:{name}:{level}")
    scales = {}
    for name in NUMS:
        v = pd.to_numeric(d[name], errors="coerce")
        median = float(v.median()) if v.notna().any() else 0.0
        scale = max(float(v.quantile(0.75) - v.quantile(0.25)), 1.0) if v.notna().any() else 1.0
        z = (v.fillna(median).to_numpy(float) - median) / scale
        arrays.append(z)
        labels.append("control:" + name)
        if name in ["age", "body_weight", "rating"]:
            arrays.append(z**2)
            labels.append("control:" + name + "2")
        if v.isna().any():
            arrays.append(v.isna().to_numpy(float))
            labels.append("control:" + name + "_missing")
        scales[name] = {"median": median, "scale": scale}
    return np.column_stack(arrays), labels, gate_specs, scales


def fit(d, meta):
    x, labels, specs, scales = design(d)
    weights = 1 / d.groupby("race_key").row_key.transform("size").to_numpy(float)
    horse = codes(d.horse_id)
    xd, _ = within(x, horse, weights)
    yd, _ = within(d.finish.to_numpy(float) + d.moisture_offset.to_numpy(float), horse, weights)
    y = yd[:, 0]
    gram = xd.T @ (weights[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    beta = inv @ (xd.T @ (weights * y))
    residual = y - xd @ beta
    rank = int(np.linalg.matrix_rank(gram, tol=np.linalg.norm(gram, 2) * 1e-11))
    dof = len(d) - d.horse_id.nunique() - rank
    score = xd * (weights * residual)[:, None]
    corr = (len(d) - 1) / max(dof, 1)
    vh = inv @ cluster(score, d.horse_id) @ inv * corr
    vd = inv @ cluster(score, d.date) @ inv * corr
    vi = inv @ cluster(score, d.horse_id + ":" + d.date.astype(str)) @ inv * corr
    cov = vh + vd - vi
    df = min(d.horse_id.nunique(), d.date.nunique()) - 1
    projection = inv @ gram
    vectors, identities, supports = [], [], []

    def add(vector, identity, groups, thresholds):
        details = [
            {
                "rows": len(g),
                "races": g.race_key.nunique(),
                "days": g.date.nunique(),
                "years": g.year.nunique(),
            }
            for g in groups
        ]
        supported = dof > 0 and all(
            z["rows"] >= thresholds[0]
            and z["races"] >= thresholds[1]
            and z["days"] >= thresholds[2]
            and z["years"] >= thresholds[3]
            for z in details
        )
        estimable = bool(np.allclose(vector @ projection, vector, atol=1e-6))
        vectors.append(vector)
        identities.append(meta | identity)
        supports.append(
            {"supported": bool(supported and estimable), "estimable": estimable, "support": details}
        )

    for month in range(1, 13):
        angle = 2 * np.pi * (month - 1) / 12
        v = np.zeros(len(labels))
        v[:4] = [np.sin(angle), np.cos(angle), np.sin(2 * angle), np.cos(2 * angle)]
        add(
            v,
            {"kind": "month", "block": "annual", "level": str(month)},
            [d[d.month.eq(month)]],
            (0, 20, 10, 2),
        )
    for block, levels in specs.items():
        b = d[d.gate_block.eq(block)]
        number_vectors = {}
        for level in levels:
            v = np.zeros(len(labels))
            if block.startswith("exact"):
                n = len(levels)
                for other in levels[1:]:
                    v[labels.index(f"gate:{block}:{other}")] = float(level == other) - 1 / n
                g = b[b.horse_number.eq(level)]
                kind = "number"
                number_vectors[level] = v
            else:
                for side in levels[1:]:
                    p = float(b[f"p_{side}"].iloc[0])
                    # All field sizes in the same block have identical middle/outer shares
                    # only within exact n. Generic blocks use race-equal average shares.
                    p = float(b.groupby("race_key")[f"p_{side}"].first().mean())
                    v[labels.index(f"gate:{block}:{side}")] = float(level == side) - p
                g = b[b.gate_side.eq(level)]
                kind = "group"
            groups = [g, b] if kind == "number" else [b[b.gate_side.eq(s)] for s in levels]
            add(v, {"kind": kind, "block": block, "level": str(level)}, groups, (100, 50, 20, 1))
        if block.startswith("exact"):
            for side in ["inner", "middle", "outer"]:
                numbers = sorted(b[b.gate_side.eq(side)].horse_number.unique())
                v = np.mean([number_vectors[int(k)] for k in numbers], axis=0)
                add(
                    v,
                    {"kind": "group", "block": block, "level": side},
                    [b[b.gate_side.eq(s)] for s in ["inner", "middle", "outer"]],
                    (100, 50, 20, 1),
                )
    v = np.vstack(vectors)
    estimates = v @ beta
    variance = np.maximum.reduce([np.einsum("ij,jk,ik->i", v, c, v) for c in [cov, vh, vd]])
    se = np.sqrt(np.maximum(variance, 0))
    critical = t.ppf(0.975, df)
    records = []
    for i, identity in enumerate(identities):
        value = float(estimates[i])
        stderr = float(se[i])
        records.append(
            identity
            | supports[i]
            | {
                "effect_seconds": value,
                "se": stderr,
                "ci_low": value - critical * stderr,
                "ci_high": value + critical * stderr,
                "p": float(2 * t.sf(abs(value) / max(stderr, 1e-15), df)),
                "model_rows": len(d),
                "model_races": d.race_key.nunique(),
                "model_days": d.date.nunique(),
                "model_horses": d.horse_id.nunique(),
            }
        )
    model = meta | {
        "labels": labels,
        "beta": beta.tolist(),
        "cov": cov.tolist(),
        "cov_horse": vh.tolist(),
        "cov_day": vd.tolist(),
        "vectors": v.tolist(),
        "identities": identities,
        "scales": scales,
        "rank": rank,
        "df": int(df),
        "residual_df": int(dof),
        "max_normal_equation_error": float(np.max(abs(xd.T @ (weights * residual)))),
    }
    return records, model, residual


def mask_outliers(d, residual):
    f = d.assign(residual=residual)
    low, high, qlow, qhigh = [pd.Series(np.nan, index=f.index) for _ in range(4)]
    for keys in [["grade", "year"], ["year"], ["meet", "distance_m"]]:
        group = f.groupby(keys, observed=True).residual
        count = group.transform("size")
        use = low.isna() & (count.ge(100) | (len(keys) == 2 and keys[0] == "meet"))
        median = group.transform("median")
        deviation = abs(f.residual - median)
        mad = deviation.groupby([f[k] for k in keys]).transform("median")
        scale = np.maximum(1.4826 * mad, 0.5)
        low.loc[use] = (median - 4 * scale).loc[use]
        high.loc[use] = (median + 4 * scale).loc[use]
        qlow.loc[use] = group.transform("quantile", 0.05).loc[use]
        qhigh.loc[use] = group.transform("quantile", 0.95).loc[use]
    assert low.notna().all()
    return f.residual.between(low, high), f.residual.between(qlow, qhigh), low, high


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
        g[["row_key", "race_key", "race_no", "horse_number", "n", "gate_side", "finish"]],
        on="row_key",
        validate="one_to_one",
        suffixes=("", "_gate"),
    )
    assert len(d) == 151074 and d.finish.eq(d.finish_gate).all()
    d["date"] = pd.to_datetime(d.date)
    assert (
        pd.to_datetime(d.last_history_date).dropna() < d.loc[d.last_history_date.notna(), "date"]
    ).all()
    roster = g.groupby("race_key").horse_number.agg(lambda v: set(v) == set(range(1, len(v) + 1)))
    exact = d.race_key.map(roster) & d.n.isin([10, 12])
    d["gate_block"] = "other_" + d.n.map(
        lambda n: "6to9" if n <= 9 else str(n) if n <= 12 else "13plus"
    )
    d.loc[exact, "gate_block"] = "exact" + d.loc[exact, "n"].astype(str)
    # Compute proportions on the original full roster, not the section-quality subset.
    for side in ["middle", "outer"]:
        p = g.gate_side.eq(side).groupby(g.race_key).mean()
        d[f"p_{side}"] = d.race_key.map(p)
    m = pd.read_csv(MOISTURE)
    m["meet"] = m.meet.map({1: "서울", 3: "부산"})
    m["adopted_distance"] = (
        m.meet.eq("서울") & m.distance_m.isin([1200, 1300, 1400, 1600, 1700, 1800])
    ) | (m.meet.eq("부산") & m.distance_m.isin([1200, 1300, 1400, 1600, 1800]))
    m["adopted_supported"] = m.supported & m.adopted_distance
    m.to_csv(OUT / "moisture_reference_preserved.csv", index=False)
    d = d.merge(
        m[["meet", "distance_m", "band", "add_seconds_conservative", "adopted_supported"]],
        on=["meet", "distance_m", "band"],
        how="left",
        validate="many_to_one",
    )
    d["moisture_offset"] = d.add_seconds_conservative.fillna(0)
    d["adopted_supported"] = d.adopted_supported.fillna(False).astype(bool)
    return d


def candidates(effects):
    keys = ["meet", "distance_m", "kind", "block", "level"]
    lookup = effects.set_index(keys + ["period"])
    records = []
    for key, _group in effects.groupby(keys, observed=True):
        rows = [
            lookup.loc[(*key, period)] if (*key, period) in lookup.index else None
            for period in PERIODS
        ]
        primary, recent = rows[1], rows[3]
        support = all(row is not None and row.supported for row in rows)
        signs = [np.sign(row.effect_seconds) for row in rows if row is not None]
        consistent = len(signs) == 5 and len(set(signs)) == 1 and signs[0] != 0
        significant = (
            primary is not None and recent is not None and primary.q < 0.05 and recent.q < 0.05
        )
        bound = 0.0
        if support and consistent and significant:
            bound = min(
                min(abs(row.ci_low), abs(row.ci_high)) if row.ci_low * row.ci_high > 0 else 0
                for row in [primary, recent]
            )
        cap = 0.30 if key[2] == "month" else 0.20
        unrounded = min(cap, 0.5 * bound)
        add = -signs[0] * np.floor((unrounded + 1e-12) * 100) / 100 if consistent else 0.0
        record = dict(zip(keys, key, strict=True)) | {
            "all_models_supported": bool(support),
            "direction_stable": bool(consistent),
            "full_recent_q_pass": bool(significant),
            "nearest_ci_bound": bound,
            "candidate_add_seconds": float(add),
            "candidate_nonzero": bool(abs(add) >= 0.01),
            "reason": "conservative_candidate"
            if abs(add) >= 0.01
            else "additional_apply_zero_pending",
        }
        for period, row in zip(PERIODS, rows, strict=True):
            record[period + "_effect"] = float(row.effect_seconds) if row is not None else np.nan
        for label, row in [("full", primary), ("recent", recent)]:
            for col in ["q", "ci_low", "ci_high"]:
                record[label + "_" + col] = float(row[col]) if row is not None else np.nan
        records.append(record)
    return pd.DataFrame(records)


def main():
    assert not (OUT / "summary.json").exists(), "Refuse to overwrite a completed analysis"
    hashes = {
        str(p.relative_to(ROOT)): sha(p)
        for p in [POP, GATES, MOISTURE, HERE / "PLAN.md", HERE / "analyze.py"]
    }
    d = load()
    coverage, records, models, ledgers = [], [], [], []
    for (meet, distance), group in d.groupby(["meet", "distance_m"], observed=True):
        supported = (
            group.race_key.nunique() >= 100
            and group.date.nunique() >= 30
            and group.horse_id.nunique() >= 100
        )
        coverage.append(
            {
                "meet": meet,
                "distance_m": int(distance),
                "rows": len(group),
                "races": group.race_key.nunique(),
                "days": group.date.nunique(),
                "fit_supported": bool(supported),
            }
        )
        if not supported:
            continue
        group = group.reset_index(drop=True)
        meta = {"meet": meet, "distance_m": int(distance), "period": "all_raw"}
        raw_rows, raw_model, residual = fit(group, meta)
        records.extend(raw_rows)
        models.append(raw_model)
        mad, trim, lo, hi = mask_outliers(group, residual)
        ledger = group[
            [
                "row_key",
                "race_key",
                "meet",
                "date",
                "distance_m",
                "grade",
                "year",
                "finish",
                "horse_number",
                "gate_side",
                "gate_block",
                "moisture_offset",
                "adopted_supported",
                "month",
            ]
        ].copy()
        ledger["initial_residual"] = residual
        ledger["mad4_keep"] = mad
        ledger["trim5_keep"] = trim
        ledger["mad4_lower"] = lo
        ledger["mad4_upper"] = hi
        ledgers.append(ledger)
        for period, mask in [
            ("all_mad4", mad),
            ("all_trim5", trim),
            ("recent_mad4", mad & group.year.ge(2024)),
            ("complete_mad4", mad & group.year.isin([2024, 2025])),
        ]:
            sample = group[mask].reset_index(drop=True)
            if (
                sample.race_key.nunique() < 100
                or sample.date.nunique() < 30
                or sample.horse_id.nunique() < 100
            ):
                continue
            rows, model, _ = fit(sample, meta | {"period": period})
            records.extend(rows)
            models.append(model)
        print(
            meet,
            int(distance),
            "completed",
            len(group),
            "MAD removed",
            int((~mad).sum()),
            flush=True,
        )
    effects = pd.DataFrame(records)
    effects["q"] = 1.0
    for _, g in effects.groupby(["period", "kind"], observed=True):
        ix = g.index[g.supported]
        effects.loc[ix, "q"] = bh(effects.loc[ix, "p"].to_numpy())
    effects["support"] = effects.support.map(lambda z: json.dumps(z, ensure_ascii=False))
    effects.to_csv(OUT / "joint_seconds_profiles.csv", index=False)
    c = candidates(effects)
    c.to_csv(OUT / "conservative_candidates.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "distance_coverage.csv", index=False)
    ledger = pd.concat(ledgers, ignore_index=True)
    monthly = c[c.kind.eq("month")].set_index(["meet", "distance_m", "level"]).candidate_add_seconds
    gates = (
        c[c.kind.isin(["number", "group"])]
        .set_index(["meet", "distance_m", "kind", "block", "level"])
        .candidate_add_seconds
    )
    ledger["month_candidate_add"] = [
        monthly.get((r.meet, r.distance_m, str(r.month)), 0) for r in ledger.itertuples()
    ]
    ledger["gate_candidate_add"] = [
        gates.get(
            (
                r.meet,
                r.distance_m,
                "number" if r.gate_block.startswith("exact") else "group",
                r.gate_block,
                str(r.horse_number) if r.gate_block.startswith("exact") else r.gate_side,
            ),
            0,
        )
        for r in ledger.itertuples()
    ]
    ledger["total_candidate_add"] = np.where(
        ledger.adopted_supported,
        ledger.moisture_offset + ledger.month_candidate_add + ledger.gate_candidate_add,
        np.nan,
    )
    ledger["candidate_finish"] = ledger.finish + ledger.total_candidate_add
    ledger.to_parquet(OUT / "runner_normalization_candidates.parquet", index=False)
    matrices = {}
    for i, model in enumerate(models):
        model["matrix_key"] = str(i)
        for key in ["beta", "cov", "cov_horse", "cov_day", "vectors"]:
            matrices[f"{i}_{key}"] = np.asarray(model.pop(key))
    np.savez_compressed(OUT / "model_matrices.npz", **matrices)
    dump(OUT / "models.json", models)
    summary = {
        "completed_on": "2026-10-08",
        "input_sha256": hashes,
        "input_rows": len(d),
        "modeled_rows": len(ledger),
        "modeled_races": ledger.race_key.nunique(),
        "model_count": len(models),
        "new_prediction_validation": False,
        "new_correction_adopted": False,
        "actual_lateral_correction": "pending_not_applied",
        "all_mad4_removed": int((~ledger.mad4_keep).sum()),
        "all_trim5_removed": int((~ledger.trim5_keep).sum()),
        "nonzero_candidates": c[c.candidate_nonzero].groupby("kind").size().to_dict(),
        "composite_supported_rows": int(ledger.adopted_supported.sum()),
        "data_end": {meet: str(g.date.max().date()) for meet, g in d.groupby("meet")},
        "candidate_rule": (
            "half nearest full/recent 95% bound; five supported same-sign fits; "
            "full/recent BH<.05; caps .30 month/.20 gate; truncate toward zero .01"
        ),
    }
    assert all(sha(ROOT / p) == h for p, h in hashes.items())
    dump(OUT / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "input_sha256"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
