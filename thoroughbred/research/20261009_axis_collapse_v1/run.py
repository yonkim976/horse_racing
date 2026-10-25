"""Frozen thoroughbred-only axis-failure experiment. No DB or network access."""

import hashlib
import itertools
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logit, logsumexp
from sklearn.metrics import roc_auc_score

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / "outputs"
W = R / "20261008_profile_carried_weight_v1/outputs"
S = R / "20261009_section_style_finish_v1/outputs"
V = R / "20261009_axis_pool_validation_v1/outputs"
CFG = json.loads((HERE / "config.json").read_text())
KEY = ["race_key", "program_no", "horse_id"]


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(p, x):
    p.write_text(
        json.dumps(
            x,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
            default=lambda z: z.item() if isinstance(z, np.generic) else str(z),
        )
        + "\n"
    )


def refs():
    paths = [HERE / n for n in ["PLAN.md", "config.json", "run.py", "verify.py"]]
    paths += [ROOT / "config/prediction_model_registry.json"]
    paths += [
        W / n for n in ["features_month_gate_weight22.parquet", "research_baseline_selection.json"]
    ]
    paths += [S / n for n in ["features.parquet", "feature_contract.json"]]
    paths += [V / n for n in ["runner_inputs.parquet", "summary.csv"]]
    for meet in [1, 3]:
        for year in CFG["evaluation_years"]:
            paths += [
                W / "models" / f"{meet}_{year}_month_gate_weight22" / n
                for n in ["top3.txt", "metadata.json"]
            ]
    return paths


def check():
    for p, h in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / p) == h, p


def encode(f, cols, vocabulary=None, mask=None):
    x = f[cols].copy()
    if vocabulary is None:
        vocabulary = {
            c: sorted(f.loc[mask, c].dropna().unique().tolist())
            for c in cols
            if not pd.api.types.is_numeric_dtype(f[c])
        }
    for c, levels in vocabulary.items():
        x[c] = pd.Categorical(x[c].where(x[c].isin(levels)), categories=levels)
    return x, vocabulary


def temperature(f, scores):
    energies, truth = [], []
    for _, ix in f.groupby("race_key", sort=False).indices.items():
        sets = np.array(list(itertools.combinations(range(len(ix)), 3)))
        e = np.sort(scores[ix][sets], axis=1).sum(axis=1)
        winners = np.flatnonzero(f.iloc[ix].outcome.between(1, 3).to_numpy())
        energies.append(e)
        truth.append(e[np.flatnonzero(np.all(sets == winners, axis=1))[0]])
    matrix = np.full((len(energies), max(map(len, energies))), -np.inf)
    for i, e in enumerate(energies):
        matrix[i, : len(e)] = e
    result = minimize_scalar(
        lambda t: float(np.mean(logsumexp(matrix / t, axis=1) - np.array(truth) / t)),
        bounds=CFG["temperature_bounds"],
        method="bounded",
    )
    assert result.success
    return float(result.x)


def base_oof():
    f = pd.read_parquet(W / "features_month_gate_weight22.parquet")
    cols = json.loads((W / "models/1_2024_month_gate_weight22/metadata.json").read_text())[
        "features"
    ]
    rows = []
    for meet, one in f.groupby("meet", sort=True):
        one = one.sort_values(["race_date", "race_key", "program_no"]).reset_index(drop=True)
        for year in CFG["base_oof_years"]:
            dest = OUT / "base_models" / f"{meet}_{year}"
            dest.mkdir(parents=True, exist_ok=True)
            if (dest / "runners.parquet").exists():
                rows.append(pd.read_parquet(dest / "runners.parquet"))
                continue
            tr, va = one.year.between(2017, year - 3), one.year.eq(year - 2)
            ca, te = one.year.eq(year - 1), one.year.eq(year)
            x, vocabulary = encode(one, cols, mask=tr)
            y = one.outcome.between(1, 3).astype(int)
            params = CFG["training"].copy()
            rounds, early = params.pop("max_rounds"), params.pop("early_stopping_rounds")
            params["seed"] = CFG["seed"]

            def ds(mask, x=x, y=y, one=one):
                return lgb.Dataset(x[mask], label=y[mask], weight=1 / one.loc[mask, "field_size"])

            initial = lgb.train(
                params,
                ds(tr),
                num_boost_round=rounds,
                valid_sets=[ds(va)],
                callbacks=[lgb.early_stopping(early, verbose=False)],
            )
            model = lgb.train(params, ds(tr | va), num_boost_round=initial.best_iteration)
            model.save_model(str(dest / "model.txt"))
            cs = model.predict(x[ca], raw_score=True, num_threads=4)
            tau = temperature(one[ca].reset_index(drop=True), cs)
            cal = one.loc[ca, KEY + ["outcome"]].copy()
            cal["score"] = cs
            cal.to_parquet(dest / "calibration.parquet", index=False)
            z = one.loc[
                te,
                KEY
                + [
                    "meet",
                    "race_date",
                    "year",
                    "distance_m",
                    "grade",
                    "field_size",
                    "history_count",
                    "outcome",
                ],
            ].copy()
            z["score"] = model.predict(x[te], raw_score=True, num_threads=4)
            z["tau"] = tau
            z.to_parquet(dest / "runners.parquet", index=False)
            save(
                dest / "metadata.json",
                dict(
                    features=cols,
                    category_vocabulary=vocabulary,
                    trees=initial.best_iteration,
                    temperature=tau,
                    meet=int(meet),
                    evaluation_year=year,
                    train_min=str(one.loc[tr | va, "race_date"].min().date()),
                    train_max=str(one.loc[tr | va, "race_date"].max().date()),
                    calibration_year=year - 1,
                    model_sha256=sha(dest / "model.txt"),
                ),
            )
            rows.append(z)
            print("base OOF", meet, year, len(z), flush=True)
    current = pd.read_parquet(V / "runner_inputs.parquet")
    current = current[current.model.eq(CFG["base"])].drop(columns=["model", "period"])
    current.race_date = pd.to_datetime(current.race_date)
    rows.append(current)
    all_rows = pd.concat(rows, ignore_index=True).sort_values(
        ["race_date", "race_key", "program_no"]
    )
    assert not all_rows.duplicated(KEY).any()
    all_rows.to_parquet(OUT / "oof_runners.parquet", index=False)
    return all_rows


def card(g):
    g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
    sets = np.array(list(itertools.combinations(range(len(g)), 3)))
    # Preserve the existing baseline's summation order and tie rule.
    energy = np.sort((g.score.to_numpy() / g.tau.iloc[0])[sets], axis=1).sum(axis=1)
    q = np.exp(energy - logsumexp(energy))
    return g, sets, q


def race_inputs(runners):
    history = pd.read_parquet(S / "features.parquet")
    cols53 = json.loads((S / "feature_contract.json").read_text())["style_history"]
    assert not runners.duplicated(KEY).any()
    f = runners.merge(
        history[KEY + cols53], on=KEY, how="left", validate="one_to_one", suffixes=("", "_history")
    )
    extras = [
        "moist_last3_record_index_mean",
        "profile_trend",
        "profile_std5",
        "history_count",
        "section_early_mean3",
        "section_last600_mean3",
        "section_late_mean3",
        "style_role0_rate5",
        "style_role1_rate5",
        "style_recovery_mean5",
        "style_fade_mean5",
    ]
    rows = []
    scorecols = [
        "base_risk",
        "score1",
        "gap12",
        "gap13",
        "gap15",
        "score_std",
        "score_entropy",
        "mass_top3",
        "mass_top5",
        "field_size",
    ]
    contextcols = (
        scorecols
        + [
            "meet",
            "gate_number",
            "gate_fraction",
            "field_min_history",
            "field_new_count",
            "field_front_mass",
        ]
        + ["axis_" + c for c in cols53 if c != "field_size"]
    )
    contextcols += [prefix + c for c in extras for prefix in ["others_mean_", "axis_gap_"]]
    for rid, raw in f.groupby("race_key", sort=False):
        g, sets, q = card(raw)
        a = g.iloc[0]
        s = g.score.to_numpy() / g.tau.iloc[0]
        soft = np.exp(s - logsumexp(s))
        rec = dict(
            race_key=rid,
            race_date=a.race_date,
            year=int(a.year),
            meet=int(a.meet),
            axis_number=int(a.program_no),
            axis_horse_id=str(a.horse_id),
            collapsed=int(not 1 <= a.outcome <= 3),
            base_risk=float(q[(sets != 0).all(axis=1)].sum()),
            score1=s[0],
            gap12=s[0] - s[1],
            gap13=s[0] - s[2],
            gap15=s[0] - s[4],
            score_std=float(np.std(s)),
            score_entropy=float(-np.sum(soft * np.log(soft))),
            mass_top3=float(soft[:3].sum()),
            mass_top5=float(soft[:5].sum()),
            field_size=len(g),
            gate_number=int(a.program_no),
            gate_fraction=a.program_no / len(g),
            field_min_history=g.history_count.min(),
            field_new_count=int(g.history_count.eq(0).sum()),
            field_front_mass=g.style_role0_rate5.sum(min_count=1),
        )
        rec.update({"axis_" + c: a[c] for c in cols53 if c != "field_size"})
        for c in extras:
            rec["others_mean_" + c] = g.iloc[1:][c].mean()
            rec["axis_gap_" + c] = a[c] - rec["others_mean_" + c]
        rows.append(rec)
    z = pd.DataFrame(rows).sort_values(["race_date", "race_key"]).reset_index(drop=True)
    z.to_parquet(OUT / "race_inputs.parquet", index=False)
    save(
        OUT / "feature_contract.json",
        dict(
            score=scorecols,
            context=contextcols,
            label="collapsed",
            excluded=["current outcome", "current section/position", "jockey", "trainer"],
        ),
    )
    return z, {"score": scorecols, "context": contextcols}


def calibrate(p, y):
    z = logit(np.clip(p, 1e-6, 1 - 1e-6))

    def objective(ab):
        t = ab[0] + ab[1] * z
        return float(np.mean(np.logaddexp(0, t) - y * t) + 0.001 * (ab[0] ** 2 + (ab[1] - 1) ** 2))

    result = minimize(objective, [0.0, 1.0], method="L-BFGS-B", bounds=[(-5, 5), (0.1, 5)])
    assert result.success
    return result.x.tolist()


def apply_cal(p, ab):
    return expit(ab[0] + ab[1] * logit(np.clip(p, 1e-6, 1 - 1e-6)))


def risk_predictions(f, contracts):
    predictions = []
    for year in CFG["evaluation_years"]:
        tr, va = f.year.between(2020, year - 3), f.year.eq(year - 2)
        ca, te = f.year.eq(year - 1), f.year.eq(year)
        for variant in ["base_cal", "score", "context"]:
            dest = OUT / "risk_models" / f"{variant}_{year}"
            dest.mkdir(parents=True, exist_ok=True)
            if variant == "base_cal":
                cp, tp = f.loc[ca, "base_risk"].to_numpy(), f.loc[te, "base_risk"].to_numpy()
                cols, vocab, trees = ["base_risk"], {}, 0
            else:
                cols = contracts[variant]
                x, vocab = encode(f, cols, mask=tr)
                params = CFG["risk_training"].copy()
                rounds, early = params.pop("max_rounds"), params.pop("early_stopping_rounds")
                params["seed"] = CFG["seed"]
                y = f.collapsed

                def ds(mask, x=x, y=y):
                    return lgb.Dataset(x[mask], label=y[mask])

                initial = lgb.train(
                    params,
                    ds(tr),
                    num_boost_round=rounds,
                    valid_sets=[ds(va)],
                    callbacks=[lgb.early_stopping(early, verbose=False)],
                )
                trees = initial.best_iteration
                model = lgb.train(params, ds(tr | va), num_boost_round=trees)
                model.save_model(str(dest / "model.txt"))
                cp = model.predict(x[ca], num_threads=4)
                tp = model.predict(x[te], num_threads=4)
            ab = calibrate(cp, f.loc[ca, "collapsed"].to_numpy())
            cp_cal, tp_cal = apply_cal(cp, ab), apply_cal(tp, ab)
            threshold = float(np.quantile(cp_cal, CFG["risk_quantile"]))
            cal = f.loc[ca, ["race_key", "collapsed"]].copy()
            cal["raw_risk"], cal["risk"] = cp, cp_cal
            cal.to_parquet(dest / "calibration.parquet", index=False)
            save(
                dest / "metadata.json",
                dict(
                    features=cols,
                    vocabulary=vocab,
                    trees=trees,
                    platt=ab,
                    threshold=threshold,
                    evaluation_year=year,
                    train_year_max=year - 2,
                    train_year_min=2020,
                    validation_year=year - 2,
                    calibration_year=year - 1,
                    gain=dict(
                        zip(
                            cols,
                            model.feature_importance(importance_type="gain").tolist(),
                            strict=True,
                        )
                    )
                    if variant != "base_cal"
                    else {},
                ),
            )
            z = f.loc[
                te,
                ["race_key", "race_date", "year", "meet", "axis_number", "collapsed", "base_risk"],
            ].copy()
            z["variant"], z["raw_risk"], z["risk"], z["threshold"] = variant, tp, tp_cal, threshold
            z["flag"] = tp_cal >= threshold
            predictions.append(z)
            print("risk", variant, year, trees, flush=True)
    p = pd.concat(predictions, ignore_index=True)
    p.to_parquet(OUT / "risk_predictions.parquet", index=False)
    return p


def ordered_indices(q, sets, numbers, mask=None):
    valid = np.arange(len(q)) if mask is None else np.flatnonzero(mask)
    return sorted(valid, key=lambda i: (-q[i], tuple(sorted(numbers[sets[i]]))))[:6]


def policies(g, sets, q, risks):
    numbers = g.program_no.to_numpy()
    contains = (sets == 0).any(axis=1)
    fixed = ordered_indices(q, sets, numbers, contains & (sets < 7).all(axis=1))
    free = ordered_indices(q, sets, numbers)
    exclude = ordered_indices(q, sets, numbers, ~contains)
    result = {"fixed7": (fixed, q), "global6": (free, q)}
    base_axis = q[contains].sum()
    for variant, risk, flag in risks:
        adjusted = q * np.where(contains, (1 - risk) / base_axis, risk / (1 - base_axis))
        assert abs(adjusted.sum() - 1) < 1e-12
        result[variant + "_trigger_free"] = (free if flag else fixed, q)
        result[variant + "_trigger_exclude"] = (exclude if flag else fixed, q)
        result[variant + "_reweight"] = (ordered_indices(adjusted, sets, numbers), adjusted)
    return result


def evaluate(runners, pred):
    lookup = {
        rid: list(zip(g.variant, g.risk, g.flag, strict=True))
        for rid, g in pred.groupby("race_key", sort=False)
    }
    metrics, tickets = [], []
    for rid, raw in runners[runners.year.ge(2024)].groupby("race_key", sort=False):
        g, sets, q = card(raw)
        truth = tuple(sorted(g.loc[g.outcome.between(1, 3), "program_no"].astype(int)))
        axis = int(g.program_no.iloc[0])
        for policy, (indices, mass) in policies(g, sets, q, lookup[rid]).items():
            trios = [tuple(sorted(g.program_no.to_numpy()[sets[i]].astype(int))) for i in indices]
            assert len(trios) == len(set(trios)) == 6
            hit = int(truth in trios)
            metrics.append(
                dict(
                    race_key=rid,
                    race_date=g.race_date.iloc[0],
                    year=int(g.year.iloc[0]),
                    meet=int(g.meet.iloc[0]),
                    policy=policy,
                    hit=hit,
                    collapsed=int(axis not in truth),
                    axis_number=axis,
                    covered_mass=float(mass[indices].sum()),
                    axis_free_tickets=sum(axis not in t for t in trios),
                )
            )
            tickets.extend(
                dict(
                    race_key=rid,
                    policy=policy,
                    selection_rank=j + 1,
                    programs=",".join(map(str, t)),
                    probability=float(mass[i]),
                    hit=int(t == truth),
                )
                for j, (i, t) in enumerate(zip(indices, trios, strict=True))
            )
    m = pd.DataFrame(metrics)
    m.to_csv(OUT / "race_metrics.csv", index=False)
    pd.DataFrame(tickets).to_parquet(OUT / "six_tickets.parquet", index=False)
    return m


def boot_difference(values, dates):
    frame = pd.DataFrame({"value": values, "date": dates})
    ag = frame.groupby("date").value.agg(["sum", "count"])
    rng = np.random.default_rng(CFG["bootstrap_seed"])
    ix = rng.integers(0, len(ag), size=(CFG["bootstrap_draws"], len(ag)))
    draws = ag["sum"].to_numpy()[ix].sum(axis=1) / ag["count"].to_numpy()[ix].sum(axis=1)
    return float(np.mean(values)), *np.quantile(draws, [0.025, 0.975]).tolist()


def summarize(p, m):
    summary, quality, bins, flags, differences = [], [], [], [], []
    for scope, year, meet in (
        [("all", None, None)]
        + [(str(y), y, None) for y in CFG["evaluation_years"]]
        + [("Seoul", None, 1), ("Busan", None, 3)]
    ):
        mask = pd.Series(True, index=m.index)
        pmask = pd.Series(True, index=p.index)
        if year:
            mask &= m.year.eq(year)
            pmask &= p.year.eq(year)
        if meet:
            mask &= m.meet.eq(meet)
            pmask &= p.meet.eq(meet)
        z, pr = m[mask], p[pmask]
        for policy, g in z.groupby("policy"):
            summary.append(
                dict(
                    scope=scope,
                    policy=policy,
                    races=len(g),
                    hits=int(g.hit.sum()),
                    hit_rate=g.hit.mean(),
                )
            )
        base = pr[pr.variant.eq("base_cal")]
        qualities = [("base_raw", base, base.base_risk.to_numpy())]
        qualities += [(v, g, g.risk.to_numpy()) for v, g in pr.groupby("variant")]
        for variant, g, risk in qualities:
            y = g.collapsed.to_numpy()
            brier = (risk - y) ** 2
            ll = -(y * np.log(risk) + (1 - y) * np.log1p(-risk))
            quality.append(
                dict(
                    scope=scope,
                    variant=variant,
                    races=len(g),
                    collapsed=int(y.sum()),
                    mean_risk=risk.mean(),
                    actual_risk=y.mean(),
                    auc=roc_auc_score(y, risk),
                    brier=brier.mean(),
                    logloss=ll.mean(),
                )
            )
            if scope == "all":
                bg = g.copy()
                bg["probability"] = risk
                bg["bin"] = pd.cut(risk, [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1], include_lowest=True)
                for name, h in bg.groupby("bin", observed=True):
                    bins.append(
                        dict(
                            variant=variant,
                            bin=str(name),
                            races=len(h),
                            predicted=h.probability.mean(),
                            actual=h.collapsed.mean(),
                        )
                    )
        for variant, g in pr.groupby("variant"):
            flagged = g[g.flag]
            flags.append(
                dict(
                    scope=scope,
                    variant=variant,
                    races=len(g),
                    flagged=len(flagged),
                    coverage=len(flagged) / len(g),
                    predicted_risk=flagged.risk.mean(),
                    collapse_precision=flagged.collapsed.mean(),
                    collapse_recall=flagged.collapsed.sum() / g.collapsed.sum(),
                )
            )
        wide = z.pivot(index="race_key", columns="policy", values="hit")
        dates = (
            z.drop_duplicates("race_key")
            .set_index("race_key")
            .loc[wide.index, "race_date"]
            .to_numpy()
        )
        for policy in wide.columns:
            if policy in ["fixed7", "global6"]:
                continue
            for control in ["fixed7", "global6"]:
                d = (wide[policy] - wide[control]).to_numpy()
                mean, lo, hi = boot_difference(d, dates)
                differences.append(
                    dict(
                        scope=scope,
                        candidate=policy,
                        control=control,
                        races=len(wide),
                        rescued=int((d == 1).sum()),
                        lost=int((d == -1).sum()),
                        difference=mean,
                        ci_low=lo,
                        ci_high=hi,
                    )
                )
        if scope == "all":
            b = base.set_index("race_key")
            for variant, g in pr.groupby("variant"):
                g = g.set_index("race_key").loc[b.index]
                y = b.collapsed.to_numpy()
                a, c = g.risk.to_numpy(), b.base_risk.to_numpy()
                for metric, d in [
                    ("brier", (a - y) ** 2 - (c - y) ** 2),
                    (
                        "logloss",
                        -(y * np.log(a) + (1 - y) * np.log1p(-a))
                        + (y * np.log(c) + (1 - y) * np.log1p(-c)),
                    ),
                ]:
                    mean, lo, hi = boot_difference(d, b.race_date.to_numpy())
                    differences.append(
                        dict(
                            scope=scope,
                            candidate=variant,
                            control="base_raw",
                            metric=metric,
                            races=len(g),
                            difference=mean,
                            ci_low=lo,
                            ci_high=hi,
                        )
                    )
    for name, rows in [
        ("summary", summary),
        ("risk_quality", quality),
        ("risk_bins", bins),
        ("risk_flags", flags),
        ("paired_differences", differences),
    ]:
        pd.DataFrame(rows).to_csv(OUT / (name + ".csv"), index=False)


def main():
    OUT.mkdir(exist_ok=True)
    if not (OUT / "source_lock.json").exists():
        save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs()})
    check()
    r = base_oof()
    f, cols = race_inputs(r)
    p = risk_predictions(f, cols)
    m = evaluate(r, p)
    summarize(p, m)
    check()
    save(
        OUT / "completion.json",
        dict(
            status="analysis_complete_pending_verification",
            races=int(m.race_key.nunique()),
            runner_rows=len(r),
            race_inputs=len(f),
            risk_models=6,
            new_base_models=8,
            database_access=False,
            jeju_access=False,
            selected_baseline_changed=False,
            production_changed=False,
        ),
    )
    print("Analysis complete", m.race_key.nunique(), flush=True)


if __name__ == "__main__":
    main()
