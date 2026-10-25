"""Carried-weight feature bundle: frozen retrospective inputs, no production writes."""

import argparse
import importlib.util
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


B = module("profile_reference", RESEARCH / "20261008_horse_profile_model_v1/run.py")
ENV = RESEARCH / "20261008_profile_environment_ablation_v1/outputs"
KEY = B.KEY
BASE = B.CONTRACTS["profile19"]
WEIGHT = ["previous_carried_weight", "current_carried_weight", "current_vs_previous_carried_weight"]
COLS = BASE + WEIGHT
sha, save = B.sha, B.save


def config():
    return json.loads((HERE / "config.json").read_text())


def source_frames():
    return {
        "profile19": B.HERE / "outputs/features.parquet",
        "month_gate19": ENV / "features_month_gate19.parquet",
    }


def check_inputs():
    for path, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / path) == expected, path
    if (OUT / "features_complete.json").exists():
        for name, expected in json.loads((OUT / "features_complete.json").read_text())[
            "hashes"
        ].items():
            assert sha(OUT / name) == expected, name


def read_weights():
    # Static SQL and read-only connection; do not load current outcome or body weight.
    with duckdb.connect(str(DB), read_only=True) as connection:
        weights = connection.execute("""
            SELECT cast(source_meet AS int) meet,
                   strptime(result_date, '%Y%m%d')::DATE race_date,
                   cast(result_race_no AS int) race_no,
                   cast(horse_program_no_raw AS int) program_no,
                   horse_id_raw horse_id,
                   try_cast(carried_weight_raw AS double) current_carried_weight
            FROM confirmed_runners
            WHERE source_meet IN ('1','3')
            ORDER BY race_date,meet,race_no,program_no
        """).fetchdf()
    weights["race_date"] = pd.to_datetime(weights.race_date)
    weights["race_key"] = (
        weights.meet.astype(str)
        + ":"
        + weights.race_date.dt.strftime("%Y%m%d")
        + ":"
        + weights.race_no.astype(str)
    )
    assert not weights.duplicated(KEY).any()
    weights["current_carried_weight"] = weights.current_carried_weight.where(
        weights.current_carried_weight.between(40, 70)
    )
    return weights


def weight_inputs(f, weights):
    history_keys = pd.read_parquet(B.RECORDS, columns=KEY + ["race_date"])
    history = history_keys.merge(
        weights[KEY + ["current_carried_weight"]], on=KEY, how="left", validate="one_to_one"
    )
    history = history.sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    assert not history.duplicated(["horse_id", "race_date"]).any()
    states = history[["horse_id", "race_date", "current_carried_weight"]].rename(
        columns={
            "race_date": "weight_source_date",
            "current_carried_weight": "previous_carried_weight",
        }
    )
    query = f[KEY + ["cutoff_date"]].copy()
    query["_row"] = np.arange(len(query))
    previous = (
        pd.merge_asof(
            query.sort_values("cutoff_date"),
            states.sort_values("weight_source_date"),
            by="horse_id",
            left_on="cutoff_date",
            right_on="weight_source_date",
            direction="backward",
        )
        .sort_values("_row")
        .reset_index(drop=True)
    )
    current = f[KEY].merge(
        weights[KEY + ["current_carried_weight"]], on=KEY, how="left", validate="one_to_one"
    )
    result = pd.concat(
        [
            previous[KEY + ["previous_carried_weight", "weight_source_date"]],
            current[["current_carried_weight"]],
        ],
        axis=1,
    )
    result["current_vs_previous_carried_weight"] = (
        result.current_carried_weight - result.previous_carried_weight
    )
    assert result[KEY].equals(f[KEY])
    assert (result.weight_source_date.isna() | result.weight_source_date.le(f.cutoff_date)).all()
    assert result.weight_source_date.equals(f.history_source_date)
    frozen = pd.read_parquet(B.RAW, columns=KEY + ["previous_carried_weight"])
    frozen = f[KEY].merge(frozen, on=KEY, validate="one_to_one")
    assert np.allclose(
        result.previous_carried_weight,
        frozen.previous_carried_weight,
        equal_nan=True,
        atol=0,
        rtol=0,
    )
    return result, history


def prepare():
    if OUT.exists():
        raise FileExistsError("Existing experiment; do not overwrite")
    c = config()
    paths = [
        DB,
        HERE / "run.py",
        HERE / "PLAN.md",
        HERE / "config.json",
        B.HERE / "run.py",
        B.RECORDS,
        B.RAW,
        ROOT / "config/prediction_model_registry.json",
        *source_frames().values(),
    ]
    for folder, variant in [(B.HERE / "outputs", "profile19"), (ENV, "month_gate19")]:
        paths += [
            folder / "race_metrics.csv",
            folder / "runner_predictions.parquet",
            folder / "recommendations.parquet",
        ]
        paths += list((folder / "models").glob(f"*_{variant}/top3.txt"))
        paths += list((folder / "models").glob(f"*_{variant}/metadata.json"))
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    reference_config = B.cfg()
    for field in ["training", "seed", "temperature_bounds", "evaluation_years", "venues"]:
        assert c[field] == reference_config[field]
    f = pd.read_parquet(source_frames()["profile19"])
    weights = read_weights()
    features, history = weight_inputs(f, weights)
    OUT.mkdir()
    save(OUT / "input_manifest.json", hashes)
    weights.to_parquet(OUT / "weight_source.parquet", index=False)
    history.to_parquet(OUT / "weight_history.parquet", index=False)
    features.to_parquet(OUT / "weight_inputs.parquet", index=False)
    for baseline, variant in c["pairs"]:
        one = pd.read_parquet(source_frames()[baseline])
        assert one[KEY + ["outcome", "cutoff_date"]].equals(f[KEY + ["outcome", "cutoff_date"]])
        candidate = pd.concat([one, features[WEIGHT + ["weight_source_date"]]], axis=1)
        assert len(candidate) == 178497 and len(COLS) == len(set(COLS)) == 22
        candidate.to_parquet(OUT / f"features_{variant}.parquet", index=False)
    coverage = []
    for (meet, year), ids in f.groupby(["meet", "year"]).groups.items():
        one = features.loc[ids]
        coverage.append(
            dict(
                meet=int(meet),
                year=int(year),
                rows=len(one),
                current_missing=int(one.current_carried_weight.isna().sum()),
                previous_missing=int(one.previous_carried_weight.isna().sum()),
                delta_missing=int(one.current_vs_previous_carried_weight.isna().sum()),
            )
        )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    save(
        OUT / "feature_contract.json",
        {**{b: BASE for b, _ in c["pairs"]}, **{v: COLS for v in c["variants"]}},
    )
    save(
        OUT / "features_complete.json",
        dict(
            rows=len(f),
            features=22,
            original_features=19,
            weight_features=WEIGHT,
            previous_reproduced_rows=len(f),
            current_weight_pit_verified=False,
            current_weight_source="confirmed_runners.carried_weight_raw",
            hashes={p.name: sha(p) for p in OUT.glob("*.parquet")},
        ),
    )
    check_inputs()
    print("Prepared", len(f), "rows; 19 + 3 carried-weight inputs", flush=True)


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
    c = config()
    rows, differences, slices = [], [], []
    rng = np.random.default_rng(c["bootstrap_seed"])
    for meet in [0, 1, 3]:
        subset = r if not meet else r[r.meet.eq(meet)]
        for variant, group in subset.groupby("variant"):
            for period, one in [
                ("all", group),
                *[(str(y), g) for y, g in group.groupby("evaluation_year")],
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
        for baseline, variant in c["pairs"]:
            pair = subset[subset.variant.eq(baseline)].merge(
                subset[subset.variant.eq(variant)],
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
                        base=baseline,
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
    for (meet, variant), group in r.groupby(["meet", "variant"]):
        for dim in ["new_horse_present", "low_history_present", "distance_m", "grade"]:
            for value, one in group.groupby(dim, dropna=False):
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
        raise FileExistsError("Completed experiment")
    c = config()
    races, runners, tickets = [], [], []
    for folder, variant in [(B.HERE / "outputs", "profile19"), (ENV, "month_gate19")]:
        for name, outputs in [
            ("race_metrics.csv", races),
            ("runner_predictions.parquet", runners),
            ("recommendations.parquet", tickets),
        ]:
            p = folder / name
            old = pd.read_csv(p, low_memory=False) if p.suffix == ".csv" else pd.read_parquet(p)
            outputs.append(old[old.variant.eq(variant)].copy())
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
                    score, meta = B.fit(one, COLS, year, c, directory)
                    cal, test = one.year.eq(year - 1), one.year.eq(year)
                    temperature = B.fit_temperature(
                        B.parts(one[cal].reset_index(drop=True), score[cal]), c
                    )
                    meta.update(
                        temperature=temperature,
                        calibration_races=int(one.loc[cal, "race_key"].nunique()),
                        variant=variant,
                        current_weight_pit_verified=False,
                    )
                    save(directory / "metadata.json", meta)
                    r, p, t = B.evaluate(
                        one[test].reset_index(drop=True), score[test], temperature, variant
                    )
                    p.to_parquet(directory / "runners.parquet", index=False)
                    t.to_parquet(directory / "tickets.parquet", index=False)
                    r.to_csv(directory / "race_metrics.csv", index=False)
                    print(
                        "Evaluated",
                        meet,
                        year,
                        variant,
                        "hits",
                        int(r.trio6_hit.sum()),
                        "trees",
                        meta["trees"],
                        flush=True,
                    )
                races.append(pd.read_csv(directory / "race_metrics.csv"))
                runners.append(pd.read_parquet(directory / "runners.parquet"))
                tickets.append(pd.read_parquet(directory / "tickets.parquet"))
    r, p, t = [pd.concat(items, ignore_index=True) for items in [races, runners, tickets]]
    r.to_csv(OUT / "race_metrics.csv", index=False)
    p.to_parquet(OUT / "runner_predictions.parquet", index=False)
    t.to_parquet(OUT / "recommendations.parquet", index=False)
    summarize(r)
    check_inputs()
    save(
        OUT / "summary.json",
        dict(
            new_heads=12,
            baseline_heads_reused=12,
            features=22,
            added=WEIGHT,
            evaluation_races=4799,
            evaluation_runners=50754,
            production_changed=False,
            current_weight_pit_verified=False,
            independent_future_test=False,
            fixed_weight_time_correction=False,
            model_hashes={
                str(p.relative_to(OUT)): sha(p) for p in (OUT / "models").rglob("top3.txt")
            },
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "train"])
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        {"prepare": prepare, "train": train}[args.mode]()
