"""Read-only body/carried-weight normalization and historical sectional ablations."""

import gzip
import importlib.util
import json
import platform
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261004_relative_speed_par_v1"
spec = importlib.util.spec_from_file_location("previous", PREVIOUS / "analyze.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
bench = previous.bench
SEED = 20261005
MODELS = dict(
    absolute=["weight"],
    total_ratio=["load_share_pct"],
    weight_body=["weight", "body_kg"],
    weight_body_ratio=["weight", "body_kg", "load_share_pct"],
    body_ratio=["body_load_pct"],
    past_body_ratio=["weight", "prior_body_kg", "prior_load_share_pct"],
)


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load():
    d = bench.population()
    hashes = []
    body, raw_body, raw_weight = {}, {}, {}
    # Empty parentheses mean the weight change is absent, not that body mass is absent.
    pattern = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:\(\s*(?:[+-]?\d+(?:\.\d+)?)?\s*\))?\s*$")
    for filename, group in d.groupby("source_file"):
        path = ROOT / filename
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            r = raw[int(row.source_item_index)]
            assert str(r["rcDate"]) == row.date.strftime("%Y%m%d")
            assert int(r["rcNo"]) == int(row.source_key.split(":")[-1])
            assert str(r["hrNo"]).zfill(7) == row.horse_id
            assert int(r["rcDist"]) == 1200
            burden = float(r["wgBudam"])
            assert abs(burden - row.weight) < 1e-7
            text = str(r.get("wgHr", ""))
            match = pattern.fullmatch(text)
            body[row.row_key] = float(match[1]) if match else np.nan
            raw_body[row.row_key], raw_weight[row.row_key] = text, burden
        hashes.append(dict(path=filename, sha256=bench.sha(path), checked_rows=len(group)))
    d["body_raw"] = d.row_key.map(raw_body)
    d["body_kg"] = d.row_key.map(body)
    d["weight_raw"] = d.row_key.map(raw_weight)
    d["weight_status"] = np.select(
        [d.body_kg.isna(), ~d.body_kg.between(260, 700), ~d.weight.between(35, 70)],
        ["unparseable_body", "body_out_of_range", "burden_out_of_range"],
        default="valid",
    )
    d["total_kg"] = d.body_kg + d.weight
    d["load_share_pct"] = 100 * d.weight / d.total_kg
    d["body_load_pct"] = 100 * d.weight / d.body_kg
    old = pd.read_parquet(PREVIOUS / "outputs/population_relative_speed.parquet")
    cols = [x for x in old if x.startswith("rs_")]
    d = d.merge(old[["row_key", *cols]], on="row_key", validate="one_to_one")
    d = previous.history_features(d)
    valid = d.body_kg.where(d.weight_status.eq("valid"))
    ordered = d.sort_values(["horse_id", "date", "row_key"]).copy()
    ordered["valid_body"] = valid.reindex(ordered.index)
    ordered["valid_body_date"] = ordered.date.where(ordered.valid_body.notna())
    ordered["prior_body_kg"] = ordered.groupby("horse_id").valid_body.transform(
        lambda s: s.ffill().shift(1)
    )
    ordered["prior_body_date"] = ordered.groupby("horse_id").valid_body_date.transform(
        lambda s: s.ffill().shift(1)
    )
    ordered["prior_load_share_pct"] = (
        100 * ordered.weight / (ordered.prior_body_kg + ordered.weight)
    )
    known = ordered.prior_body_date.notna()
    assert (ordered.loc[known, "prior_body_date"] < ordered.loc[known, "date"]).all()
    return ordered.sort_index(), hashes


def preprocessing(weight_fields):
    pre = bench.Model(0).pre
    numbers = [x for x in bench.NUMS if x != "weight"] + weight_fields
    pre.transformers = [
        (name, transformer, numbers if name == "num" else cols)
        for name, transformer, cols in pre.transformers
    ]
    return pre


def comparisons(race, meet, year, stage, rng):
    columns = [x for x in race.columns if x.startswith("err_")]
    dates = np.sort(race.date.unique())
    sampled = [
        pd.Series(rng.choice(dates, len(dates)), dtype="datetime64[ns]").value_counts()
        for _ in range(2000)
    ]
    weights = np.array([race.date.map(counts).fillna(0).to_numpy() for counts in sampled])
    denominator = weights.sum(axis=1)
    pairs = []
    for model in MODELS:
        for history in [False, True]:
            name = model + ("_rs" if history else "")
            if name != "absolute":
                pairs.append((name, "absolute", "vs_absolute"))
        pairs.append((model + "_rs", model, "sectional_increment"))
    pairs += [
        ("weight_body_ratio", "weight_body", "ratio_beyond_body"),
        ("weight_body_ratio_rs", "weight_body_rs", "ratio_beyond_body"),
        ("body_ratio", "total_ratio", "denominator_sensitivity"),
        ("body_ratio_rs", "total_ratio_rs", "denominator_sensitivity"),
    ]
    rows = []
    for added, baseline, contrast in pairs:
        delta = (race["err_" + added] - race["err_" + baseline]).to_numpy()
        draws = weights @ delta / denominator
        lo, hi = np.quantile(draws, [0.025, 0.975])
        rows.append(
            dict(
                meet=meet,
                year=year,
                stage=stage,
                model=added,
                baseline=baseline,
                contrast=contrast,
                delta_seconds=float(delta.mean()),
                ci_low=float(lo),
                ci_high=float(hi),
                races=len(race),
                dates=len(dates),
                ci_condition="fixed fitted models; date clusters",
                inferential_status="exploratory; no multiplicity adjustment",
            )
        )
    assert len(columns) == 12
    return rows


def evaluate(d):
    valid = d[d.weight_status.eq("valid")].copy()
    summaries, contrasts, predictions, coefficients = [], [], [], []
    rng = np.random.default_rng(SEED)
    for meet, region in valid.groupby("meet"):
        regional = []
        history_fields = [
            "history_rs_" + p
            for p in bench.CORE + ["last600"] + (["closing4c"] if meet == "서울" else ["last400"])
        ] + ["history1200_count"]
        for year in [2024, 2025, 2026]:
            tr = region[region.year.lt(year)].copy()
            te = region[region.year.eq(year)].copy()
            assert tr.date.max() < te.date.min()
            for a in [tr, te]:
                a["band"] = "건조"
                a["interaction"] = a.grade + "|건조"
            history_impute = SimpleImputer(strategy="median", add_indicator=True)
            history_scale = StandardScaler()
            z = history_scale.fit_transform(history_impute.fit_transform(tr[history_fields]))
            zz = history_scale.transform(history_impute.transform(te[history_fields]))
            result = te[
                [
                    "row_key",
                    "date",
                    "source_key",
                    "horse_id",
                    "meet",
                    "finish",
                    "grade",
                    "body_kg",
                    "weight",
                    "load_share_pct",
                    "prior_body_kg",
                    "prior_body_date",
                    "history1200_count",
                    "history1200_last_date",
                ]
            ].copy()
            result["year"] = year
            w = bench.race_weights(tr)
            for model, fields in MODELS.items():
                pre = preprocessing(fields)
                x, xx = pre.fit_transform(tr), pre.transform(te)
                for history in [False, True]:
                    name = model + ("_rs" if history else "")
                    train_x = np.column_stack([x, z]) if history else x
                    test_x = np.column_stack([xx, zz]) if history else xx
                    reg = Ridge(alpha=10, solver="cholesky").fit(
                        train_x, tr.finish, sample_weight=w
                    )
                    result["pred_" + name] = reg.predict(test_x)
                    result["err_" + name] = abs(result["pred_" + name] - result.finish)
                    error = result.groupby("source_key")["err_" + name].mean()
                    summaries.append(
                        dict(
                            meet=meet,
                            year=year,
                            model=name,
                            weight_encoding=model,
                            relative_history=history,
                            n=len(te),
                            races=len(error),
                            dates=te.date.nunique(),
                            train_n=len(tr),
                            mae_seconds=error.mean(),
                            train_max=str(tr.date.max().date()),
                            test_min=str(te.date.min().date()),
                            current_body_input=model
                            in {"total_ratio", "weight_body", "weight_body_ratio", "body_ratio"},
                            current_outcomes_input=False,
                        )
                    )
                    if not history:
                        numeric = pre.named_transformers_["num"]
                        numeric_cols = pre.transformers_[3][2]
                        start = pre.output_indices_["num"].start
                        scales = numeric.named_steps["scale"].scale_
                        for field in fields:
                            offset = numeric_cols.index(field)
                            coefficients.append(
                                dict(
                                    meet=meet,
                                    year=year,
                                    model=model,
                                    field=field,
                                    coefficient_seconds_per_unit=float(
                                        reg.coef_[start + offset] / scales[offset]
                                    ),
                                    interpretation="conditional association; not causal correction",
                                )
                            )
            predictions.append(result)
            race = (
                result.groupby(["date", "source_key"])[[c for c in result if c.startswith("err_")]]
                .mean()
                .reset_index()
            )
            regional.append(race)
            contrasts.extend(comparisons(race, meet, year, "year", rng))
            print(f"{meet} {year}: {len(te)} runners, 12 models", flush=True)
        pooled = pd.concat(regional, ignore_index=True)
        contrasts.extend(comparisons(pooled, meet, 0, "pooled2024_2026", rng))
        for model in [m + s for m in MODELS for s in ["", "_rs"]]:
            summaries.append(
                dict(
                    meet=meet,
                    year=0,
                    model=model,
                    weight_encoding=model.removesuffix("_rs"),
                    relative_history=model.endswith("_rs"),
                    n=sum(len(p) for p in predictions if p.meet.iloc[0] == meet),
                    races=len(pooled),
                    dates=pooled.date.nunique(),
                    train_n=np.nan,
                    mae_seconds=float(pooled["err_" + model].mean()),
                    train_max="per-year split",
                    test_min="2024-01-01",
                    current_body_input=model.removesuffix("_rs")
                    in {"total_ratio", "weight_body", "weight_body_ratio", "body_ratio"},
                    current_outcomes_input=False,
                )
            )
    return (
        pd.DataFrame(summaries),
        pd.DataFrame(contrasts),
        pd.concat(predictions, ignore_index=True),
        pd.DataFrame(coefficients),
    )


def distributions(d):
    rows = []
    recent = d[d.weight_status.eq("valid") & d.year.ge(2024)]
    for meet, region in recent.groupby("meet"):
        for grade in ["ALL", *bench.GRADES]:
            a = region if grade == "ALL" else region[region.grade.eq(grade)]
            q = a.load_share_pct.quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
            bins = np.searchsorted(q, a.load_share_pct, side="left") + 1
            a = a.assign(load_quintile=bins)
            for quintile, g in a.groupby("load_quintile"):
                rows.append(
                    dict(
                        meet=meet,
                        grade=grade,
                        quintile=quintile,
                        n=len(g),
                        races=g.source_key.nunique(),
                        mean_load_share=g.load_share_pct.mean(),
                        min_load_share=g.load_share_pct.min(),
                        max_load_share=g.load_share_pct.max(),
                        mean_body_kg=g.body_kg.mean(),
                        mean_carried_kg=g.weight.mean(),
                        mean_finish=g.finish.mean(),
                        mean_rs_late=g.rs_late.mean(),
                        mean_rs_last600=g.rs_last600.mean(),
                        top3_share=float(g["rank"].le(3).mean()),
                    )
                )
    return pd.DataFrame(rows)


def main():
    d, hashes = load()
    d[
        [
            "row_key",
            "meet",
            "date",
            "source_key",
            "horse_id",
            "grade",
            "band",
            "year",
            "finish",
            "rank",
            "weight",
            "body_raw",
            "body_kg",
            "weight_status",
            "weight_raw",
            "total_kg",
            "load_share_pct",
            "body_load_pct",
            "prior_body_kg",
            "prior_body_date",
            "prior_load_share_pct",
            "history1200_count",
            "history1200_last_date",
        ]
    ].to_parquet(OUT / "weight_population.parquet", index=False)
    metrics, contrasts, predictions, coefficients = evaluate(d)
    metrics.to_csv(OUT / "prediction_metrics.csv", index=False)
    contrasts.to_csv(OUT / "paired_comparisons.csv", index=False)
    predictions.to_parquet(OUT / "prediction_rows.parquet", index=False)
    coefficients.to_csv(OUT / "conditional_coefficients.csv", index=False)
    distributions(d).to_csv(OUT / "observed_load_quintiles.csv", index=False)
    inputs = [bench.PRIOR, bench.HISTORY, PREVIOUS / "outputs/population_relative_speed.parquet"]
    code = [Path(bench.__file__), PREVIOUS / "analyze.py"]
    save_json(
        OUT / "summary.json",
        dict(
            runners=len(d),
            status=d.groupby(["meet", "weight_status"])
            .size()
            .reset_index(name="n")
            .to_dict("records"),
            recent_status=d[d.year.ge(2024)]
            .groupby(["meet", "weight_status"])
            .size()
            .reset_index(name="n")
            .to_dict("records"),
            models=MODELS,
            main_comparison="absolute/total_ratio/weight_body/weight_body_ratio",
            sensitivity="body_ratio/past_body_ratio",
            model_selection_performed=False,
            current_body_availability="historical publication times not verified",
            weight_share_formula="100*carried/(body+carried)",
            source_hashes=hashes,
            input_hashes=[dict(path=str(p.relative_to(ROOT)), sha256=bench.sha(p)) for p in inputs],
            reused_code_hashes=[
                dict(path=str(p.relative_to(ROOT)), sha256=bench.sha(p)) for p in code
            ],
            runtime=dict(
                python=platform.python_version(),
                numpy=np.__version__,
                pandas=pd.__version__,
                sklearn=bench.sklearn.__version__,
            ),
        ),
    )
    print(
        metrics[metrics.year.eq(0)][["meet", "model", "mae_seconds"]].to_string(index=False),
        flush=True,
    )
    print("Done", flush=True)


if __name__ == "__main__":
    main()
