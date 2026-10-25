"""Chronological whole-time environment ablation; fixed local files, no DB writes."""

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


B = module("profile_reference", RESEARCH / "20261008_horse_profile_model_v1/run.py")
N = module("seconds_reference", RESEARCH / "20261008_record_normalization_seconds/analyze.py")
G = module("gate_reference", RESEARCH / "20261008_gate_model_candidate_v1/build.py")
L = G.A.L
A = G.A
KEY = B.KEY
COLS = B.CONTRACTS["profile19"]
DERIVED = COLS[len(B.BASE) :]
sha, save = B.sha, B.save


def config():
    return json.loads((HERE / "config.json").read_text())


def freeze():
    OUT.mkdir(exist_ok=True)
    paths = [
        HERE / "run.py",
        HERE / "PLAN.md",
        HERE / "config.json",
        B.HERE / "run.py",
        B.HERE / "outputs/features.parquet",
        B.HERE / "outputs/race_metrics.csv",
        B.HERE / "outputs/runner_predictions.parquet",
        B.HERE / "outputs/recommendations.parquet",
        B.RECORDS,
        N.HERE / "analyze.py",
        N.POP,
        N.GATES,
        G.HERE / "build.py",
        A.HERE / "analyze.py",
        L.HERE / "analyze.py",
        ROOT / "config/prediction_model_registry.json",
    ]
    paths += list((B.HERE / "outputs/models").glob("*_profile19/top3.txt"))
    paths += list((B.HERE / "outputs/models").glob("*_profile19/metadata.json"))
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    p = OUT / "input_manifest.json"
    if p.exists():
        assert json.loads(p.read_text()) == hashes, "Frozen source changed"
    else:
        save(p, hashes)


def check_inputs():
    for path, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / path) == expected, path


def population():
    # Only historical covariates used by the fixed descriptive estimators.
    pcols = [
        "row_key",
        "meet",
        "distance_m",
        "date",
        "year",
        "month",
        "grade",
        "band",
        "moisture",
        "sex_condition",
        "horse_id",
        "finish",
        "last_history_date",
        *N.NUMS,
    ]
    d = pd.read_parquet(N.POP, columns=[c for c in dict.fromkeys(pcols) if c != "race_no"])
    g = pd.read_parquet(
        N.GATES,
        columns=[
            "meet",
            "date",
            "race_no",
            "horse_number",
            "horse_id",
            "n",
            "gate_side",
            "finish",
            "race_key",
        ],
    )
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
        g.drop(columns=["meet", "date", "horse_id"]),
        on="row_key",
        validate="one_to_one",
        suffixes=("", "_gate"),
    )
    assert len(d) == 151074 and d.finish.eq(d.finish_gate).all()
    d["date"] = pd.to_datetime(d.date)
    assert (
        pd.to_datetime(d.last_history_date).dropna() < d.loc[d.last_history_date.notna(), "date"]
    ).all()
    exact = g.groupby("race_key").horse_number.agg(lambda v: set(v) == set(range(1, len(v) + 1)))
    d["gate_block"] = "other_" + d.n.map(
        lambda n: "6to9" if n <= 9 else str(n) if n <= 12 else "13plus"
    )
    use = d.race_key.map(exact) & d.n.isin([10, 12])
    d.loc[use, "gate_block"] = "exact" + d.loc[use, "n"].astype(str)
    for side in G.A.SIDES:
        d["p_" + side] = d.race_key.map(g.gate_side.eq(side).groupby(g.race_key).mean())
    # Exact moisture factors absorb any fixed moisture offset in monthly FE fit.
    d["moisture_offset"] = 0.0
    return d


def metadata(model, year, sample, family):
    excluded = {"cov", "cov_horse", "cov_day", "vectors", "identities"}
    return {k: v for k, v in model.items() if k not in excluded} | dict(
        coefficient_year=year,
        family=family,
        source_min=str(sample.date.min().date()),
        source_max=str(sample.date.max().date()),
        source_years=sorted(sample.year.unique().tolist()),
    )


def coefficients():
    freeze()
    if (OUT / "coefficients_complete.json").exists():
        check_inputs()
        print("Using completed frozen chronological coefficients", flush=True)
        return
    d = population()
    c = config()
    (OUT / "coefficients").mkdir(exist_ok=True)
    for year in c["coefficient_years"]:
        dest = OUT / "coefficients" / str(year)
        if (dest / "complete.json").exists():
            print("Coefficients already complete", year, flush=True)
            continue
        dest.mkdir(exist_ok=True)
        prior = d[d.year.lt(year)].copy()
        assert prior.year.max() < year and prior.year.nunique() >= 2
        month_rows, base_rows, state_rows, models, masks = [], [], [], [], []
        for (meet, dist), g in prior.groupby(["meet", "distance_m"], observed=True, sort=True):
            number = {"서울": 1, "부산": 3}[meet]
            if dist not in c["gate_distances"][str(number)] or not L.minimum(g, False):
                continue
            start = time.monotonic()
            g = g.reset_index(drop=True)
            meta = dict(meet=meet, distance_m=int(dist), period="all_raw")
            rows, model, residual = N.fit(g, meta)
            mad, trim, _, _ = N.mask_outliers(g, residual)
            masks.append(g[["row_key"]].assign(mad4_keep=mad, trim5_keep=trim))
            # All outlier masks and every sensitivity use only this annual prior.
            if dist in c["month_distances"][str(number)]:
                month_rows.extend(rows)
                models.append(metadata(model, year, g, "month"))
                periods = [
                    ("all_mad4", mad),
                    ("all_trim5", trim),
                    ("recent_mad4", mad & g.year.ge(year - 3)),
                    ("complete_mad4", mad & g.year.ge(year - 2)),
                ]
                for period, mask in periods:
                    sample = g[mask].reset_index(drop=True)
                    if not L.minimum(sample, False):
                        continue
                    rows, model, _ = N.fit(sample, meta | {"period": period})
                    month_rows.extend(rows)
                    models.append(metadata(model, year, sample, "month"))
            sample = g[mad].reset_index(drop=True)
            if L.minimum(sample, False):
                gm = dict(
                    kind="gate",
                    meet=meet,
                    distance_m=int(dist),
                    point="start",
                    period="all_mad4",
                    adjustment="dual",
                )
                matrices = {}
                rows, model = L.fit(sample, gm, matrices)
                if model is not None:
                    base_rows.extend(rows)
                    models.append(metadata(model, year, sample, "gate_base"))
                    rows, model = A.fit(
                        sample,
                        {k: v for k, v in gm.items() if k not in ["kind", "point"]},
                        matrices,
                    )
                    state_rows.extend(rows)
                    models.append(metadata(model, year, sample, "gate_state"))
            print(
                "Coefficients",
                year,
                meet,
                int(dist),
                len(g),
                "seconds",
                round(time.monotonic() - start, 1),
                flush=True,
            )
        month = pd.DataFrame(month_rows)
        month["q"] = 1.0
        for _, ids in month.groupby(["period", "kind"], observed=True).groups.items():
            active = month.loc[ids].index[month.loc[ids, "supported"]]
            if len(active):
                month.loc[active, "q"] = N.bh(month.loc[active, "p"].to_numpy())
        candidates = N.candidates(month)
        candidates = candidates[candidates.kind.eq("month")].copy()
        base, state = pd.DataFrame(base_rows), pd.DataFrame(state_rows)
        # build_table consumes serialized support and emits all/recent; only annual
        # all-prior estimates are used. No future or full-2026 table is read.
        for frame in [base, state]:
            frame["q"] = 1.0
            for _, ids in frame.groupby(["period", "family"], observed=True).groups.items():
                active = frame.loc[ids].index[
                    frame.loc[ids, "supported"] & frame.loc[ids, "p"].notna()
                ]
                if len(active):
                    frame.loc[active, "q"] = N.bh(frame.loc[active, "p"].to_numpy())
            frame["support"] = frame.support.map(json.dumps)
        gate = G.build_table(prior, base, state)
        gate = gate[gate.period.eq("all_mad4")].copy()
        for frame in [candidates, gate]:
            frame["coefficient_year"] = year
            frame["trained_through"] = year - 1
            frame["source_max_date"] = str(prior.date.max().date())
        month["support"] = month.support.map(json.dumps)
        month.to_parquet(dest / "month_effects.parquet", index=False)
        candidates.to_parquet(dest / "month_candidates.parquet", index=False)
        base.to_parquet(dest / "base_effects.parquet", index=False)
        state.to_parquet(dest / "state_effects.parquet", index=False)
        gate.to_parquet(dest / "gate_candidates.parquet", index=False)
        pd.concat(masks).to_parquet(dest / "outlier_masks.parquet", index=False)
        save(dest / "models.json", models)
        save(
            dest / "complete.json",
            dict(
                year=year,
                source_max=str(prior.date.max().date()),
                rows=len(prior),
                month_nonzero=int(candidates.candidate_nonzero.sum()),
                gate_nonzero=int(gate.gate_add_seconds.abs().gt(1e-12).sum()),
                hashes={
                    p.name: sha(p)
                    for p in dest.iterdir()
                    if p.is_file() and p.name != "complete.json"
                },
            ),
        )
    check_inputs()
    save(
        OUT / "coefficients_complete.json",
        dict(years=c["coefficient_years"], future_coefficients_used=False),
    )


def add_components(records, d):
    r = records.copy()
    r["row_key"] = (
        r.meet.map({1: "서울", 3: "부산"})
        + ":"
        + r.race_date.dt.strftime("%Y%m%d")
        + ":"
        + r.race_key.str.rsplit(":", n=1).str[-1]
        + ":"
        + r.horse_id
    )
    columns = ["row_key", "month", "band", "n", "horse_number", "gate_side", "gate_block"]
    r = r.merge(d[columns], on="row_key", how="left", validate="one_to_one", sort=False)
    r["month_add_seconds"] = 0.0
    r["gate_add_seconds"] = 0.0
    r["month_candidate_known"] = False
    r["gate_candidate_known"] = False
    r["coefficient_source_max"] = pd.NaT
    for year in config()["coefficient_years"]:
        dest = OUT / "coefficients" / str(year)
        month = pd.read_parquet(dest / "month_candidates.parquet")
        gate = pd.read_parquet(dest / "gate_candidates.parquet")
        mm = month.set_index(["meet", "distance_m", "level"]).candidate_add_seconds.to_dict()
        gg = gate.set_index(["meet", "distance_m", "field_size", "mode", "band", "level"])
        eligible = r.year.eq(year) & r.supported & r.original_finish_valid.notna() & r.n.notna()
        source_date = pd.Timestamp(json.loads((dest / "complete.json").read_text())["source_max"])
        for row in r[eligible].itertuples():
            meet = {1: "서울", 3: "부산"}[row.meet]
            mk = (meet, row.result_distance, str(int(row.month)))
            mode = "number" if row.gate_block.startswith("exact") else "group"
            level = str(int(row.horse_number)) if mode == "number" else row.gate_side
            gk = (meet, row.result_distance, int(row.n), mode, row.band, level)
            r.at[row.Index, "month_add_seconds"] = mm.get(mk, 0.0)
            r.at[row.Index, "month_candidate_known"] = mk in mm
            if gk in gg.index:
                cell = gg.loc[gk]
                r.at[row.Index, "gate_add_seconds"] = cell.gate_add_seconds
                r.at[row.Index, "gate_candidate_known"] = bool(cell.base_available)
            r.at[row.Index, "coefficient_source_max"] = source_date
        assert (
            r.loc[eligible, "coefficient_source_max"]
            <= r.loc[eligible, "race_date"] - pd.Timedelta(days=2)
        ).all()
    return r


def record_indices(r, variant):
    s = r.copy()
    delta = {
        "month19": s.month_add_seconds,
        "gate19": s.gate_add_seconds,
        "month_gate19": s.month_add_seconds + s.gate_add_seconds,
        "profile19": np.zeros(len(s)),
    }[variant]
    s["candidate_finish"] = s.finish_valid + delta
    s["candidate_index"] = np.nan
    references = []
    for year in sorted(s.year.unique()):
        prior = s[s.year.lt(year) & s.candidate_finish.notna()]
        stats = prior.groupby(["meet", "result_distance"]).candidate_finish.agg(["count", "median"])
        mad = prior.groupby(["meet", "result_distance"]).candidate_finish.agg(
            lambda x: np.median(np.abs(x - np.median(x)))
        )
        stats["scale"] = np.maximum(0.5, 1.4826 * mad)
        stats = stats[stats["count"].ge(50)]
        current = s[s.year.eq(year)].merge(
            stats, left_on=["meet", "result_distance"], right_index=True, how="left"
        )
        s.loc[current.index, "candidate_index"] = (
            (current["median"] - current.candidate_finish) / current.scale
        ).clip(-10, 10)
        if len(prior):
            assert prior.race_date.max() <= s.loc[
                s.year.eq(year), "race_date"
            ].min() - pd.Timedelta(days=2)
        references.append(stats.reset_index().assign(source_year=year, trained_through=year - 1))
    return s, pd.concat(references, ignore_index=True)


def profile_frame(r, f):
    h = r.sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    assert not h.duplicated(["horse_id", "race_date"]).any()
    g = h.groupby("horse_id", sort=False).candidate_index
    states = h[["horse_id", "race_date"]].rename(columns={"race_date": "candidate_source_date"})
    states["moist_last_record_index"] = h.candidate_index
    states["moist_last3_record_index_mean"] = g.transform(
        lambda x: x.rolling(3, min_periods=1).mean()
    )
    states["moist_last5_record_index_best"] = g.transform(
        lambda x: x.rolling(5, min_periods=1).max()
    )
    states["moist_last5_record_index_count"] = g.transform(
        lambda x: x.rolling(5, min_periods=1).count()
    )
    states["profile_count3"] = g.transform(lambda x: x.rolling(3, min_periods=1).count())
    states["profile_previous3_count"] = g.transform(
        lambda x: x.shift(3).rolling(3, min_periods=1).count()
    )
    states["profile_previous3"] = g.transform(lambda x: x.shift(3).rolling(3, min_periods=1).mean())
    recent = states.moist_last3_record_index_mean
    states["profile_trend"] = (recent - states.profile_previous3).where(
        states.profile_count3.ge(2) & states.profile_previous3_count.ge(2)
    )
    states["profile_std5"] = g.transform(lambda x: x.rolling(5, min_periods=3).std())
    top2 = np.full(len(h), np.nan)
    values = h.candidate_index.to_numpy(float)
    for ids in h.groupby("horse_id", sort=False).indices.values():
        w = np.lib.stride_tricks.sliding_window_view(
            np.pad(values[ids], (4, 0), constant_values=np.nan), 5
        )
        known = np.isfinite(w).sum(axis=1)
        ordered = np.sort(np.where(np.isfinite(w), w, -np.inf), axis=1)
        top2[ids] = np.where(known >= 2, ordered[:, -2:].mean(axis=1), np.nan)
    states["profile_top2mean5"] = top2
    h["support_valid"] = h.supported.astype(float).where(h.candidate_index.notna())
    states["profile_valid5_support_fraction"] = h.groupby(
        "horse_id", sort=False
    ).support_valid.transform(lambda x: x.rolling(5, min_periods=1).mean())
    query = f[KEY + ["cutoff_date"]].copy()
    query["_row"] = np.arange(len(f))
    joined = pd.merge_asof(
        query.sort_values("cutoff_date"),
        states.sort_values("candidate_source_date"),
        by="horse_id",
        left_on="cutoff_date",
        right_on="candidate_source_date",
        direction="backward",
    )
    joined = joined.sort_values("_row").reset_index(drop=True)
    for col in ["moist_last5_record_index_count", "profile_count3", "profile_previous3_count"]:
        joined[col] = joined[col].fillna(0)
    result = f.copy()
    result[DERIVED] = joined[DERIVED]
    result["candidate_source_date"] = joined.candidate_source_date
    assert (
        result.candidate_source_date.isna() | result.candidate_source_date.le(result.cutoff_date)
    ).all()
    return result


def prepare():
    check_inputs()
    if (OUT / "features_complete.json").exists():
        print("Using completed prepared features", flush=True)
        return
    f = pd.read_parquet(B.HERE / "outputs/features.parquet")
    r = add_components(pd.read_parquet(B.RECORDS), population())
    r.to_parquet(OUT / "record_components.parquet", index=False)
    zero, _ = record_indices(r, "profile19")
    assert np.allclose(zero.candidate_index, zero.record_index, equal_nan=True, atol=1e-12, rtol=0)
    neutral = profile_frame(zero, f)
    assert np.allclose(neutral[DERIVED], f[DERIVED], equal_nan=True, atol=1e-10, rtol=0)
    coverage = []
    for variant in config()["variants"]:
        records, refs = record_indices(r, variant)
        records[KEY + ["candidate_finish", "candidate_index"]].to_parquet(
            OUT / f"records_{variant}.parquet", index=False
        )
        refs.to_csv(OUT / f"references_{variant}.csv", index=False)
        candidate = profile_frame(records, f)
        candidate.to_parquet(OUT / f"features_{variant}.parquet", index=False)
        print("Features", variant, len(candidate), flush=True)
    for (meet, year), one in r.groupby(["meet", "year"]):
        coverage.append(
            dict(
                meet=int(meet),
                year=int(year),
                rows=len(one),
                valid=int(one.finish_valid.notna().sum()),
                month_known=int(one.month_candidate_known.sum()),
                gate_known=int(one.gate_candidate_known.sum()),
                month_nonzero=int(one.month_add_seconds.abs().gt(1e-12).sum()),
                gate_nonzero=int(one.gate_add_seconds.abs().gt(1e-12).sum()),
                month_max_abs=float(one.month_add_seconds.abs().max()),
                gate_max_abs=float(one.gate_add_seconds.abs().max()),
            )
        )
    pd.DataFrame(coverage).to_csv(OUT / "record_coverage.csv", index=False)
    save(OUT / "feature_contract.json", {v: COLS for v in ["profile19", *config()["variants"]]})
    save(
        OUT / "features_complete.json",
        dict(
            rows=len(f),
            neutral_parity_values=int(len(f) * len(DERIVED)),
            hashes={p.name: sha(p) for p in OUT.glob("*.parquet")},
        ),
    )
    check_inputs()


def summarize(r):
    metrics = [
        "trio6_hit",
        "trio_nll",
        "top3_brier",
        "top3_first_hit",
        "top3_contains_podium",
        "top5_contains_podium",
        "trio6_probability",
    ]
    rows, differences, slices = [], [], []
    c = config()
    rng = np.random.default_rng(c["bootstrap_seed"])
    for meet in [0, 1, 3]:
        s = r if not meet else r[r.meet.eq(meet)]
        for variant, g in s.groupby("variant"):
            for period, one in [
                ("all", g),
                *[(str(y), v) for y, v in g.groupby("evaluation_year")],
            ]:
                rows.append(
                    dict(
                        meet=meet,
                        variant=variant,
                        period=period,
                        races=len(one),
                        hits=int(one.trio6_hit.sum()),
                        **{m: float(one[m].mean()) for m in metrics},
                    )
                )
        for variant in c["variants"]:
            pair = s[s.variant.eq("profile19")].merge(
                s[s.variant.eq(variant)],
                on="race_key",
                suffixes=("_a", "_b"),
                validate="one_to_one",
            )
            for metric in ["trio6_hit", "trio_nll", "top3_brier", "top5_contains_podium"]:
                delta = pair[metric + "_b"] - pair[metric + "_a"]
                daily = (
                    pd.DataFrame({"date": pair.race_date_a, "delta": delta})
                    .groupby("date")
                    .delta.agg(["sum", "size"])
                    .to_numpy()
                )
                draws = daily[
                    rng.integers(len(daily), size=(c["bootstrap_draws"], len(daily)))
                ].sum(axis=1)
                differences.append(
                    dict(
                        meet=meet,
                        base="profile19",
                        candidate=variant,
                        metric=metric,
                        races=len(pair),
                        difference=float(delta.mean()),
                        date_bootstrap_95=np.quantile(
                            draws[:, 0] / draws[:, 1], [0.025, 0.975]
                        ).tolist(),
                        newly_hit=int(((pair.trio6_hit_a == 0) & (pair.trio6_hit_b == 1)).sum()),
                        lost_hit=int(((pair.trio6_hit_a == 1) & (pair.trio6_hit_b == 0)).sum()),
                    )
                )
    for (meet, variant), g in r.groupby(["meet", "variant"]):
        for dim in ["new_horse_present", "low_history_present", "distance_m", "grade"]:
            for value, one in g.groupby(dim, dropna=False):
                slices.append(
                    dict(
                        meet=int(meet),
                        variant=variant,
                        dimension=dim,
                        value=str(value),
                        races=len(one),
                        hits=int(one.trio6_hit.sum()),
                        **{m: float(one[m].mean()) for m in metrics},
                    )
                )
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    pd.DataFrame(slices).to_csv(OUT / "slices.csv", index=False)
    save(OUT / "paired_differences.json", differences)


def train():
    check_inputs()
    if (OUT / "summary.json").exists():
        raise FileExistsError("Completed experiment; do not overwrite")
    c = config()
    race_outputs, runner_outputs, ticket_outputs = [], [], []
    for file, outputs in [
        ("race_metrics.csv", race_outputs),
        ("runner_predictions.parquet", runner_outputs),
        ("recommendations.parquet", ticket_outputs),
    ]:
        path = B.HERE / "outputs" / file
        old = (
            pd.read_csv(path, low_memory=False) if path.suffix == ".csv" else pd.read_parquet(path)
        )
        outputs.append(old[old.variant.eq("profile19")].copy())
    for variant in c["variants"]:
        f = pd.read_parquet(OUT / f"features_{variant}.parquet")
        for meet in c["venues"]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in c["evaluation_years"]:
                directory = OUT / "models" / f"{meet}_{year}_{variant}"
                if (directory / "race_metrics.csv").exists():
                    print("Using completed model", meet, year, variant, flush=True)
                else:
                    print("Train", meet, year, variant, flush=True)
                    scores, meta = B.fit(one, COLS, year, c, directory)
                    cal, test = one.year.eq(year - 1), one.year.eq(year)
                    temp = B.fit_temperature(
                        B.parts(one[cal].reset_index(drop=True), scores[cal]), c
                    )
                    meta.update(
                        temperature=temp,
                        calibration_races=int(one.loc[cal, "race_key"].nunique()),
                        variant=variant,
                    )
                    save(directory / "metadata.json", meta)
                    race, runner, ticket = B.evaluate(
                        one[test].reset_index(drop=True), scores[test], temp, variant
                    )
                    runner.to_parquet(directory / "runners.parquet", index=False)
                    ticket.to_parquet(directory / "tickets.parquet", index=False)
                    race.to_csv(directory / "race_metrics.csv", index=False)
                    print(
                        "Evaluated",
                        meet,
                        year,
                        variant,
                        "hits",
                        int(race.trio6_hit.sum()),
                        "trees",
                        meta["trees"],
                        flush=True,
                    )
                race_outputs.append(pd.read_csv(directory / "race_metrics.csv"))
                runner_outputs.append(pd.read_parquet(directory / "runners.parquet"))
                ticket_outputs.append(pd.read_parquet(directory / "tickets.parquet"))
    r, p, t = [
        pd.concat(items, ignore_index=True)
        for items in [race_outputs, runner_outputs, ticket_outputs]
    ]
    r.to_csv(OUT / "race_metrics.csv", index=False)
    p.to_parquet(OUT / "runner_predictions.parquet", index=False)
    t.to_parquet(OUT / "recommendations.parquet", index=False)
    summarize(r)
    check_inputs()
    save(
        OUT / "summary.json",
        dict(
            new_heads=18,
            baseline_heads_reused=6,
            inputs=19,
            evaluation_races=4799,
            evaluation_runners=50754,
            production_changed=False,
            independent_future_test=False,
            future_coefficients_used=False,
            section_correction=False,
            jockey_features=False,
            model_hashes={
                str(p.relative_to(OUT)): sha(p) for p in (OUT / "models").rglob("top3.txt")
            },
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["coefficients", "prepare", "train"])
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        {"coefficients": coefficients, "prepare": prepare, "train": train}[args.mode]()
