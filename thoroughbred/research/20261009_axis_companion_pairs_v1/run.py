"""Frozen-axis conditional companion experiments, local immutable inputs only."""

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from threadpoolctl import threadpool_limits

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CFG = json.loads((HERE / "config.json").read_text())
SPECIES = CFG["species"]
TB = ROOT / "thoroughbred/research/20261009_section_style_finish_v1/outputs"
JJ = ROOT / "jeju/research/20261009_field_relative_ability_v1/outputs"
JP = ROOT / "jeju/research/20261008_gate_region_pace_prediction_v2"
TB_HISTORY = [
    "history_count",
    "days_since_last",
    "moist_last3_record_index_mean",
    "profile_trend",
    "current_carried_weight",
    "section_early_mean3",
    "section_early_n5",
    "section_last600_mean3",
    "section_last600_n5",
    "section_late_mean3",
    "section_late_n5",
    "style_role0_rate5",
    "style_role_n5",
    "style_recovery_mean5",
    "style_fade_mean5",
]
JJ_HISTORY = [
    "observed_starts",
    "days_since_start",
    "mean5_s",
    "valid_n5",
    "mean5_minus_opp_median_s",
    "h_any_s1ftime_mean",
    "h_any_s1ftime_n",
    "h_any_s1f_first_mean",
    "h_any_s1f_n",
    "h_any_g3ftime_mean",
    "h_any_g1ftime_mean",
    "h_any_n",
    "h_same_s1ftime_mean",
    "h_same_s1f_first_mean",
    "h_same_n",
]
HISTORY = TB_HISTORY if SPECIES == "thoroughbred" else JJ_HISTORY
FRONT = "style_role0_rate5" if SPECIES == "thoroughbred" else "h_any_s1f_first_mean"
EARLY = "section_early_mean3" if SPECIES == "thoroughbred" else "h_any_s1ftime_mean"
LATE = (
    ["section_last600_mean3", "section_late_mean3"]
    if SPECIES == "thoroughbred"
    else ["h_any_g3ftime_mean", "h_any_g1ftime_mean"]
)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(
            value,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
            default=lambda x: x.item() if isinstance(x, np.generic) else str(x),
        )
        f.write("\n")


def refs():
    paths = [
        HERE / "PLAN.md",
        HERE / "config.json",
        HERE / "run.py",
        HERE / "verify.py",
        ROOT / "config/prediction_model_registry.json",
    ]
    if SPECIES == "thoroughbred":
        paths += [
            TB / n
            for n in [
                "features.parquet",
                "feature_contract.json",
                "runner_predictions.parquet",
                "verification.json",
            ]
        ]
        for y in CFG["evaluation_years"]:
            for meet in [1, 3]:
                paths += [
                    TB / "finish_models" / f"3_style_history_{meet}_{y}" / n
                    for n in ["model.txt", "metadata.json"]
                ]
    else:
        paths += [
            JJ / n
            for n in [
                "features.parquet",
                "feature_contract.json",
                "runner_predictions.parquet",
                "final_verification.json",
            ]
        ]
        paths += [
            JP / "features01" / n
            for n in [
                "features_and_targets.csv",
                "history_lineage.csv",
                "verification.json",
                "source_manifest.json",
            ]
        ]
        paths += [JP / "features.py", ROOT / "jeju/data/horse_exclusions.json"]
        for y in CFG["evaluation_years"]:
            paths += [JJ / f"R1_{y}" / n for n in ["top3.txt", "meta.json"]]
        paths += [
            ROOT / "jeju/research/20261009_operating_model_comparison_v1/outputs" / n
            for n in ["runner_predictions.parquet", "six_combinations.csv", "race_metrics.csv"]
        ]
    return paths


def check():
    lock = json.loads((OUT / "source_lock.json").read_text())
    for p, h in lock.items():
        assert sha(ROOT / p) == h, p


def load():
    if SPECIES == "thoroughbred":
        f = pd.read_parquet(TB / "features.parquet")
        cols = json.loads((TB / "feature_contract.json").read_text())["style_history"]
        f["rid"] = f.race_key.astype(str)
        f["number"] = f.program_no.astype(int)
        f["finish"] = f.outcome.astype(int)
        f["n"] = f.field_size.astype(int)
        f["grade_numeric"] = f.grade
    else:
        f = pd.read_parquet(JJ / "features.parquet")
        cols = json.loads((JJ / "feature_contract.json").read_text())["R1"]["inputs"]
        keys = ["api_record_id", "race_id", "horse_id", "horse_number", "race_date"]
        extra = [c for c in HISTORY if c not in f]
        h = pd.read_csv(
            JP / "features01/features_and_targets.csv",
            usecols=keys + extra,
            dtype={"horse_id": str},
        )
        h.horse_id = h.horse_id.astype(str)
        f.horse_id = f.horse_id.astype(str)
        assert len(f) == len(h) and set(f.api_record_id) == set(h.api_record_id)
        f = f.merge(h, on=keys, how="left", validate="one_to_one")
        f["rid"] = f.race_id.astype(str)
        f["number"] = f.horse_number.astype(int)
        f["finish"] = f.finish_position.astype(int)
        f["n"] = f.field_n.astype(int)
        f["meet"] = 2
        f["grade_numeric"] = pd.to_numeric(
            f.grade_raw.astype(str).str.extract(r"(\d+)")[0], errors="coerce"
        )
        exclusions = json.loads((ROOT / "jeju/data/horse_exclusions.json").read_text())["horses"]
        assert not set(f.horse_id) & {k for k, v in exclusions.items() if not v["reimport_allowed"]}
    f.race_date = pd.to_datetime(f.race_date)
    f.horse_id = f.horse_id.astype(str)
    f = f.sort_values(["race_date", "rid", "number"]).reset_index(drop=True)
    assert not f.duplicated(["rid", "horse_id"]).any()
    assert not f.duplicated(["rid", "number"]).any()
    assert f.groupby("rid").size().eq(f.groupby("rid").n.first()).all()
    assert f.groupby("rid").finish.apply(
        lambda s: sorted(s[s.between(1, 3)]) == [1, 2, 3]
    ).all()
    return f, cols


def encode(f, cols, vocab=None, mask=None):
    x = f[cols].copy()
    if vocab is None:
        vocab = {
            c: sorted(f.loc[mask, c].dropna().unique().tolist())
            for c in cols
            if not pd.api.types.is_numeric_dtype(f[c])
        }
    for c, levels in vocab.items():
        x[c] = pd.Categorical(x[c], categories=levels)
    return x, vocab


def base_temperature(f, scores):
    energies, truths = [], []
    for _, ix in f.groupby("rid", sort=False).indices.items():
        g = f.iloc[ix]
        sets = np.array(list(itertools.combinations(range(len(ix)), 3)), int)
        e = np.sort(scores[ix][sets], axis=1).sum(axis=1)
        true = np.flatnonzero(g.finish.between(1, 3).to_numpy())
        ti = np.flatnonzero(np.all(sets == true, axis=1))[0]
        energies.append(e)
        truths.append(e[ti])
    width = max(map(len, energies))
    matrix = np.full((len(energies), width), -np.inf)
    for i, v in enumerate(energies):
        matrix[i, : len(v)] = v
    truths = np.array(truths)
    fit = minimize_scalar(
        lambda t: float(np.mean(logsumexp(matrix / t, axis=1) - truths / t)),
        bounds=CFG["temperature_bounds"],
        method="bounded",
    )
    assert fit.success
    return float(fit.x)


def base_predictions(f, cols):
    folder = OUT / "base_models"
    folder.mkdir(exist_ok=True)
    all_rows = []
    for meet, one in f.groupby("meet", sort=True):
        one = one.reset_index(drop=True)
        for year in CFG["base_oof_years"]:
            dest = folder / f"{meet}_{year}"
            dest.mkdir(exist_ok=True)
            if (dest / "runners.parquet").exists():
                all_rows.append(pd.read_parquet(dest / "runners.parquet"))
                continue
            tr = one.year.between(2017, year - 3)
            va = one.year.eq(year - 2)
            ca = one.year.eq(year - 1)
            te = one.year.eq(year)
            assert all(m.any() for m in [tr, va, ca, te])
            if year >= 2024:
                origin = (
                    TB / "finish_models" / f"3_style_history_{meet}_{year}"
                    if SPECIES == "thoroughbred"
                    else JJ / f"R1_{year}"
                )
                meta = json.loads(
                    (
                        origin / ("metadata.json" if SPECIES == "thoroughbred" else "meta.json")
                    ).read_text()
                )
                vocab = meta["category_vocabulary" if SPECIES == "thoroughbred" else "vocabulary"]
                x, _ = encode(one, cols, vocab=vocab)
                model_path = origin / ("model.txt" if SPECIES == "thoroughbred" else "top3.txt")
                model = lgb.Booster(model_file=str(model_path))
                tau = meta["temperature" if SPECIES == "thoroughbred" else "tau"]
                meta = dict(
                    reused=True,
                    model_path=str(model_path.relative_to(ROOT)),
                    features=cols,
                    vocabulary=vocab,
                    tau=tau,
                )
            else:
                x, vocab = encode(one, cols, mask=tr)
                params = CFG["training"].copy()
                rounds = params.pop("max_rounds")
                early = params.pop("early_stopping_rounds")
                params.update(
                    seed=20261004 if SPECIES == "thoroughbred" else 20261008,
                    lambda_l2=5.0,
                    min_data_in_leaf=150 if SPECIES == "thoroughbred" else 100,
                )
                y = one.finish.between(1, 3).astype(int)

                def ds(mask, x=x, y=y, one=one):
                    return lgb.Dataset(
                        x[mask], label=y[mask], weight=1 / one.loc[mask, "n"], free_raw_data=False
                    )

                initial = lgb.train(
                    params,
                    ds(tr),
                    num_boost_round=rounds,
                    valid_sets=[ds(va)],
                    callbacks=[lgb.early_stopping(early, verbose=False)],
                )
                model = lgb.train(params, ds(tr | va), num_boost_round=initial.best_iteration)
                model_path = dest / "model.txt"
                model.save_model(str(model_path))
                cs = model.predict(x[ca], raw_score=True, num_threads=4)
                tau = base_temperature(one[ca].reset_index(drop=True), cs)
                pd.DataFrame(
                    {
                        "rid": one.loc[ca, "rid"].to_numpy(),
                        "number": one.loc[ca, "number"].to_numpy(),
                        "score": cs,
                    }
                ).to_parquet(dest / "calibration.parquet", index=False)
                meta = dict(
                    reused=False,
                    model_path=str(model_path.relative_to(ROOT)),
                    features=cols,
                    vocabulary=vocab,
                    tau=tau,
                    trees=initial.best_iteration,
                )
            z = model.predict(x[te], raw_score=True, num_threads=4)
            r = one.loc[
                te,
                [
                    "rid",
                    "number",
                    "horse_id",
                    "race_date",
                    "year",
                    "meet",
                    "finish",
                    "n",
                    "distance_m",
                    "grade_numeric",
                ],
            ].copy()
            r["score"] = z
            r["tau"] = tau
            if year >= 2024:
                old = pd.read_parquet(
                    TB / "runner_predictions.parquet"
                    if SPECIES == "thoroughbred"
                    else JJ / "runner_predictions.parquet"
                )
                if SPECIES == "thoroughbred":
                    old = old[
                        (old.target == 3)
                        & (old.variant == "style_history")
                        & (old.year == year)
                        & (old.meet == meet)
                    ].rename(
                        columns={
                            "race_key": "rid",
                            "program_no": "number",
                            "raw_score": "old_score",
                        }
                    )
                else:
                    old = old[(old.variant == "R1") & (old.year == year)].rename(
                        columns={"race_id": "rid", "horse_number": "number", "score": "old_score"}
                    )
                aligned = r.merge(
                    old[["rid", "number", "old_score"]], on=["rid", "number"], validate="one_to_one"
                )
                assert (
                    len(aligned) == len(r)
                    and np.max(abs(aligned.score - aligned.old_score)) < 1e-12
                )
            meta.update(
                meet=int(meet),
                year=year,
                initial_train_max=str(one.loc[tr, "race_date"].max().date()),
                refit_max=str(one.loc[va, "race_date"].max().date()),
                calibration_min=str(one.loc[ca, "race_date"].min().date()),
                calibration_max=str(one.loc[ca, "race_date"].max().date()),
                evaluation_min=str(one.loc[te, "race_date"].min().date()),
                evaluation_max=str(one.loc[te, "race_date"].max().date()),
                model_sha256=sha(model_path),
            )
            save(dest / "meta.json", meta)
            r.to_parquet(dest / "runners.parquet", index=False)
            all_rows.append(r)
            print("Base OOF", SPECIES, meet, year, len(r), "reused", year >= 2024, flush=True)
    r = (
        pd.concat(all_rows, ignore_index=True)
        .sort_values(["race_date", "rid", "number"])
        .reset_index(drop=True)
    )
    r.to_parquet(OUT / "oof_runners.parquet", index=False)
    return r


def pair_card(g):
    """No outcome column is ever read while computing model inputs or axis."""
    g = g.sort_values("number").reset_index(drop=True)
    order = np.lexsort((g.number.to_numpy(), -g.score.to_numpy()))
    axis = int(order[0])
    others = [i for i in range(len(g)) if i != axis]
    pairs = np.array(list(itertools.combinations(others, 2)), int)
    i, j = pairs.T
    rank = np.empty(len(g), int)
    rank[order] = np.arange(1, len(g) + 1)
    z = g.score.to_numpy(float) / float(g.tau.iloc[0])
    sets = np.array(list(itertools.combinations(range(len(g)), 3)), int)
    e = np.sort(z[sets], axis=1).sum(axis=1)
    probs = np.exp(e - logsumexp(e))
    axis_probability = float(probs[np.any(sets == axis, axis=1)].sum())
    def const(v):
        return np.repeat(v, len(pairs))
    x = {
        "distance": const(g.distance_m.iloc[0]),
        "grade": const(g.grade_numeric.iloc[0]),
        "field_n": const(len(g)),
        "venue": const(g.meet.iloc[0]),
        "axis_score": const(z[axis]),
        "axis_p_top3": const(axis_probability),
        "axis_gap_second": const(z[axis] - z[order[1]]),
        "field_score_sd": const(z.std()),
        "pair_score_sum": z[i] + z[j],
        "pair_score_min": np.minimum(z[i], z[j]),
        "pair_score_max": np.maximum(z[i], z[j]),
        "pair_score_gap": abs(z[i] - z[j]),
        "pair_rank_min": np.minimum(rank[i], rank[j]),
        "pair_rank_max": np.maximum(rank[i], rank[j]),
    }
    base_cols = list(x)
    for c in HISTORY:
        v = g[c].to_numpy(float)
        x["axis_" + c] = const(v[axis])
        x["pair_min_" + c] = np.minimum(v[i], v[j])
        x["pair_max_" + c] = np.maximum(v[i], v[j])
        x["pair_mean_minus_axis_" + c] = (v[i] + v[j]) / 2 - v[axis]
        x["pair_known_" + c] = np.isfinite(v[i]).astype(float) + np.isfinite(v[j]).astype(float)
    gate = g.number.to_numpy(float)
    x["axis_gate"] = const(gate[axis])
    x["pair_gate_min"] = np.minimum(gate[i], gate[j])
    x["pair_gate_max"] = np.maximum(gate[i], gate[j])
    x["pair_gate_spacing"] = abs(gate[i] - gate[j])
    x["pair_inner_of_axis_n"] = (gate[i] < gate[axis]).astype(float) + (
        gate[j] < gate[axis]
    ).astype(float)
    lead = g[FRONT].to_numpy(float)
    x["pair_front_product"] = lead[i] * lead[j]
    x["axis_x_pair_front_sum"] = lead[axis] * (lead[i] + lead[j])
    x["other_front_mass"] = (
        np.nansum(lead)
        - np.nan_to_num(lead[axis])
        - np.nan_to_num(lead[i])
        - np.nan_to_num(lead[j])
    )
    x["field_front_known_n"] = const(np.isfinite(lead).sum())
    early = g[EARLY].to_numpy(float)
    faster_i = early[i] < early[axis]
    faster_j = early[j] < early[axis]
    x["pair_faster_early_than_axis_n"] = np.where(
        np.isfinite(early[axis]) & np.isfinite(early[i]) & np.isfinite(early[j]),
        faster_i.astype(float) + faster_j.astype(float),
        np.nan,
    )
    for part, col in zip(["g3f", "g1f"], LATE, strict=True):
        v = g[col].to_numpy(float)
        x["pair_best_" + part + "_adv_axis"] = v[axis] - np.minimum(v[i], v[j])
        x["pair_worst_" + part + "_adv_axis"] = v[axis] - np.maximum(v[i], v[j])
        x["axis_front_x_pair_best_" + part] = lead[axis] * (v[axis] - np.minimum(v[i], v[j]))
    features = pd.DataFrame(x).astype(np.float32)
    meta = pd.DataFrame(
        dict(
            rid=const(g.rid.iloc[0]),
            race_date=const(str(g.race_date.iloc[0].date())),
            year=const(int(g.year.iloc[0])),
            meet=const(int(g.meet.iloc[0])),
            distance_m=const(float(g.distance_m.iloc[0])),
            grade=const(g.grade_numeric.iloc[0]),
            axis_number=const(int(g.number.iloc[axis])),
            axis_horse_id=const(g.horse_id.iloc[axis]),
            first_number=g.number.to_numpy()[i],
            second_number=g.number.to_numpy()[j],
            first_horse_id=g.horse_id.to_numpy()[i],
            second_horse_id=g.horse_id.to_numpy()[j],
            rank_min=np.minimum(rank[i], rank[j]),
            rank_max=np.maximum(rank[i], rank[j]),
            axis_probability=const(axis_probability),
            base_energy=z[i] + z[j],
            pair_count=const(len(pairs)),
        )
    )
    # Targets are attached only after the feature computation has ended.
    if "finish" in g:
        place = g.finish.between(1, 3).to_numpy()
        meta["axis_placed"] = int(place[axis])
        meta["truth"] = (place[axis] & place[i] & place[j]).astype(int)
        assert meta.truth.sum() == int(place[axis])
    return features, meta, {"score_pair": base_cols, "context_pair": list(features)}


def prepare():
    OUT.mkdir(exist_ok=False)
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs()})
    f, cols = load()
    save(
        OUT / "input_audit.json",
        dict(
            rows=len(f),
            races=f.rid.nunique(),
            baseline_features=cols,
            historical_features=HISTORY,
            current_targets_never_features=True,
            source_time_policy=("Inherited frozen T-2 /730d histories; publication/correction "
                                "timestamps not independently reconstructable"),
            species=SPECIES,
        ),
    )
    r = base_predictions(f, cols)
    g = r.merge(
        f[["rid", "number", *HISTORY]], on=["rid", "number"], how="left", validate="one_to_one"
    )
    xs, ms, contracts = [], [], None
    for _, card in g.groupby("rid", sort=True):
        x, m, contracts = pair_card(card)
        xs.append(x)
        ms.append(m)
    x = pd.concat(xs, ignore_index=True)
    m = pd.concat(ms, ignore_index=True)
    assert len(x) == len(m)
    x.to_parquet(OUT / "pair_features.parquet", index=False)
    m.to_parquet(OUT / "pair_metadata.parquet", index=False)
    save(OUT / "feature_contract.json", contracts)
    support = m.groupby(["year", "meet"]).agg(
        pairs=("rid", "size"),
        races=("rid", "nunique"),
        conditional_races=(
            "axis_placed",
            lambda s: int(m.loc[s.index].drop_duplicates("rid").axis_placed.sum()),
        ),
    )
    support.to_csv(OUT / "support.csv")
    check()
    save(
        OUT / "prepared.json",
        dict(
            pairs=len(m),
            races=m.rid.nunique(),
            conditional_races=int(m.drop_duplicates("rid").axis_placed.sum()),
            inputs={v: len(c) for v, c in contracts.items()},
            sha256={
                p.name: sha(p)
                for p in [
                    OUT / "pair_features.parquet",
                    OUT / "pair_metadata.parquet",
                    OUT / "oof_runners.parquet",
                    OUT / "feature_contract.json",
                ]
            },
        ),
    )
    print("Prepared pairs", SPECIES, len(m), flush=True)


def conditional_temperature(m, z):
    use = m.axis_placed.eq(1).to_numpy()
    frame = m[use].reset_index(drop=True)
    groups = frame.groupby("rid", sort=False).indices
    width = max(map(len, groups.values()))
    mat = np.full((len(groups), width), -np.inf)
    truth = np.empty(len(groups))
    pred = z[use]
    for k, ix in enumerate(groups.values()):
        mat[k, : len(ix)] = pred[ix]
        true = frame.iloc[ix].truth.to_numpy(bool)
        assert true.sum() == 1
        truth[k] = pred[ix][true][0]
    opt = minimize_scalar(
        lambda t: float(np.mean(logsumexp(mat / t, axis=1) - truth / t)),
        bounds=CFG["temperature_bounds"],
        method="bounded",
    )
    assert opt.success
    return float(opt.x)


def fit():
    check()
    assert json.loads((OUT / "preflight_verification.json").read_text())["passed"]
    x = pd.read_parquet(OUT / "pair_features.parquet")
    m = pd.read_parquet(OUT / "pair_metadata.parquet")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    folder = OUT / "pair_models"
    folder.mkdir(exist_ok=True)
    predictions = []
    # Species-specific models. Venue is a context input within the TB model.
    for year in CFG["evaluation_years"]:
        for variant in CFG["variants"]:
            dest = folder / f"{variant}_{year}"
            dest.mkdir(exist_ok=True)
            if (dest / "predictions.parquet").exists():
                predictions.append(pd.read_parquet(dest / "predictions.parquet"))
                continue
            eligible = m.axis_placed.eq(1)
            tr = m.year.between(2020, year - 3) & eligible
            va = m.year.eq(year - 2) & eligible
            ca = m.year.eq(year - 1)
            te = m.year.eq(year)
            params = CFG["training"].copy()
            rounds = params.pop("max_rounds")
            early = params.pop("early_stopping_rounds")
            params["seed"] = CFG["seed"]
            cols = contracts[variant]

            def ds(mask, cols=cols):
                return lgb.Dataset(
                    x.loc[mask, cols],
                    label=m.loc[mask, "truth"],
                    weight=1 / m.loc[mask, "pair_count"],
                    free_raw_data=False,
                )

            initial = lgb.train(
                params,
                ds(tr),
                num_boost_round=rounds,
                valid_sets=[ds(va)],
                callbacks=[lgb.early_stopping(early, verbose=False)],
            )
            model = lgb.train(params, ds(tr | va), num_boost_round=initial.best_iteration)
            model.save_model(str(dest / "model.txt"))
            cz = model.predict(x.loc[ca, cols], raw_score=True, num_threads=4)
            tz = model.predict(x.loc[te, cols], raw_score=True, num_threads=4)
            tau = conditional_temperature(m[ca].reset_index(drop=True), cz)
            pd.DataFrame({"pair_index": np.flatnonzero(ca), "score": cz}).to_parquet(
                dest / "calibration.parquet", index=False
            )
            p = pd.DataFrame(
                {
                    "pair_index": np.flatnonzero(te),
                    "year": year,
                    "variant": variant,
                    "score": tz,
                    "tau": tau,
                }
            )
            p.to_parquet(dest / "predictions.parquet", index=False)
            predictions.append(p)
            save(
                dest / "meta.json",
                dict(
                    year=year,
                    variant=variant,
                    features=cols,
                    trees=initial.best_iteration,
                    tau=tau,
                    initial_train_max=m.loc[tr, "race_date"].max(),
                    refit_max=m.loc[va, "race_date"].max(),
                    calibration_min=m.loc[ca, "race_date"].min(),
                    calibration_max=m.loc[ca, "race_date"].max(),
                    evaluation_min=m.loc[te, "race_date"].min(),
                    evaluation_max=m.loc[te, "race_date"].max(),
                    training_races=m.loc[tr | va, "rid"].nunique(),
                    model_sha256=sha(dest / "model.txt"),
                    gain=dict(
                        zip(
                            cols,
                            model.feature_importance(importance_type="gain").astype(float),
                            strict=True,
                        )
                    ),
                ),
            )
            print(
                "Companion",
                SPECIES,
                year,
                variant,
                "trees",
                initial.best_iteration,
                "tau",
                round(tau, 4),
                flush=True,
            )
    pd.concat(predictions, ignore_index=True).to_parquet(
        OUT / "pair_predictions.parquet", index=False
    )
    check()
    save(
        OUT / "training_complete.json",
        dict(
            base_new_models=8 if SPECIES == "thoroughbred" else 4,
            conditional_new_models=6,
            operating_changed=False,
            database_opened=False,
        ),
    )


def distribution(m, z):
    q = np.empty(len(m), float)
    for ix in m.groupby("rid", sort=False).indices.values():
        q[ix] = np.exp(z[ix] - logsumexp(z[ix]))
    return q


def evaluate_policy(m, q, policy, pool, fixed=False):
    races, tickets = [], []
    for rid, ix in m.groupby("rid", sort=False).indices.items():
        g = m.iloc[ix]
        qq = q[ix]
        allowed = g.rank_max.le(5 if fixed else pool).to_numpy()
        candidates = np.flatnonzero(allowed)
        order = np.lexsort(
            (
                g.second_number.to_numpy()[candidates],
                g.first_number.to_numpy()[candidates],
                -qq[candidates],
            )
        )
        chosen = candidates[order[:6]]
        assert len(chosen) == 6
        truth = g.truth.to_numpy(int)
        axis_placed = int(g.axis_placed.iloc[0])
        conditional_hit = int(truth[chosen].sum())
        conditional_nll = (
            float(-np.log(max(qq[truth.astype(bool)][0], 1e-300))) if axis_placed else np.nan
        )
        conditional_brier = float(np.sum((qq - truth) ** 2)) if axis_placed else np.nan
        r = g.iloc[0]
        cp = float(qq[chosen].sum())
        races.append(
            dict(
                rid=rid,
                race_date=r.race_date,
                year=int(r.year),
                meet=int(r.meet),
                distance_m=r.distance_m,
                grade=r.grade,
                policy=policy,
                axis_number=int(r.axis_number),
                axis_placed=axis_placed,
                six_hit=conditional_hit,
                pool_contains_truth=int(truth[allowed].sum()),
                conditional_nll=conditional_nll,
                conditional_brier=conditional_brier,
                selected_conditional_probability=cp,
                selected_joint_probability=cp * r.axis_probability,
                axis_probability=r.axis_probability,
                probability_sum_error=abs(float(qq.sum()) - 1),
            )
        )
        for j in chosen:
            t = g.iloc[j]
            tickets.append(
                dict(
                    rid=rid,
                    policy=policy,
                    axis=int(t.axis_number),
                    first=int(t.first_number),
                    second=int(t.second_number),
                    first_rank=int(t.rank_min),
                    second_rank=int(t.rank_max),
                    conditional_probability=float(qq[j]),
                    joint_probability=float(qq[j] * t.axis_probability),
                    hit=int(t.truth),
                )
            )
    return pd.DataFrame(races), pd.DataFrame(tickets)


def bootstrap(a, b, col, conditional=False):
    keys = ["rid", "race_date", "axis_placed", col]
    v = a[keys].merge(b[["rid", col]], on="rid", validate="one_to_one", suffixes=("", "_base"))
    assert len(v) == len(a) == len(b)
    if conditional:
        v = v[v.axis_placed.eq(1)]
    v = v.dropna(subset=[col, col + "_base"])
    v["delta"] = v[col] - v[col + "_base"]
    d = v.groupby("race_date").delta.agg(["sum", "size"])
    rng = np.random.default_rng(CFG["seed"])
    ix = rng.integers(0, len(d), size=(CFG["bootstrap_draws"], len(d)))
    bs = d["sum"].to_numpy()[ix].sum(axis=1) / d["size"].to_numpy()[ix].sum(axis=1)
    return dict(
        delta=float(v.delta.mean()),
        lo=float(np.quantile(bs, 0.025)),
        hi=float(np.quantile(bs, 0.975)),
        races=len(v),
        days=len(d),
    )


def summarize(r):
    rows, diffs, capture = [], [], []
    groups = [("all", "all", r)]
    for c in ["year", "meet", "distance_m", "grade"]:
        groups += [(c, str(k), g) for k, g in r.groupby(c, dropna=False)]
    for scope, value, g in groups:
        for policy, one in g.groupby("policy"):
            eligible = one[one.axis_placed.eq(1)]
            rows.append(
                dict(
                    scope=scope,
                    value=value,
                    policy=policy,
                    races=len(one),
                    axis_places=len(eligible),
                    axis_rate=float(one.axis_placed.mean()),
                    six_hit=float(one.six_hit.mean()),
                    hits=int(one.six_hit.sum()),
                    companion_given_axis=float(eligible.six_hit.mean()),
                    pool_ceiling=float(one.pool_contains_truth.mean()),
                    conditional_nll=float(eligible.conditional_nll.mean()),
                    conditional_brier=float(eligible.conditional_brier.mean()),
                    forecast_joint_mean=float(one.selected_joint_probability.mean()),
                )
            )
        if scope not in ["all", "year", "meet"]:
            continue
        base = g[g.policy.eq("fixed_axis_next4_all6")]
        for policy, one in g.groupby("policy"):
            if policy == "fixed_axis_next4_all6":
                continue
            for metric, cond in [
                ("six_hit", False),
                ("six_hit", True),
                ("conditional_nll", True),
                ("conditional_brier", True),
            ]:
                diffs.append(
                    dict(
                        scope=scope,
                        value=value,
                        policy=policy,
                        baseline="fixed_axis_next4_all6",
                        metric="companion_given_axis" if cond and metric == "six_hit" else metric,
                        **bootstrap(one, base, metric, cond),
                    )
                )
            b = base[["rid", "six_hit"]].merge(
                one[["rid", "six_hit"]], on="rid", suffixes=("_old", "_new"), validate="one_to_one"
            )
            capture.append(
                dict(
                    scope=scope,
                    value=value,
                    policy=policy,
                    newly_hit=int(((b.six_hit_old == 0) & (b.six_hit_new == 1)).sum()),
                    lost_hit=int(((b.six_hit_old == 1) & (b.six_hit_new == 0)).sum()),
                )
            )
            if policy.startswith(("score_pair_", "context_pair_")):
                pool = policy.rsplit("pool", 1)[1]
                same = g[g.policy.eq("sum_score_pool" + pool + "_best6")]
                for metric, cond in [
                    ("six_hit", False),
                    ("six_hit", True),
                    ("conditional_nll", True),
                ]:
                    diffs.append(
                        dict(
                            scope=scope,
                            value=value,
                            policy=policy,
                            baseline="sum_score_pool" + pool + "_best6",
                            metric="companion_given_axis"
                            if cond and metric == "six_hit"
                            else metric,
                            **bootstrap(one, same, metric, cond),
                        )
                    )
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(diffs).to_csv(OUT / "paired_differences.csv", index=False)
    pd.DataFrame(capture).to_csv(OUT / "capture.csv", index=False)
    bins = []
    for policy, one in r.groupby("policy"):
        for band, g in one.groupby(
            pd.cut(one.selected_joint_probability, np.linspace(0, 1, 11), include_lowest=True),
            observed=True,
        ):
            bins.append(
                dict(
                    policy=policy,
                    band=str(band),
                    races=len(g),
                    forecast=float(g.selected_joint_probability.mean()),
                    actual=float(g.six_hit.mean()),
                )
            )
    pd.DataFrame(bins).to_csv(OUT / "six_ticket_calibration.csv", index=False)


def analyze():
    check()
    m = pd.read_parquet(OUT / "pair_metadata.parquet")
    p = pd.read_parquet(OUT / "pair_predictions.parquet")
    use = m.year.ge(2024)
    test = m[use].reset_index(drop=True)
    baseq = distribution(test, test.base_energy.to_numpy())
    results = [evaluate_policy(test, baseq, "fixed_axis_next4_all6", 5, fixed=True)]
    for pool in [6, 7]:
        results.append(evaluate_policy(test, baseq, f"sum_score_pool{pool}_best6", pool))
    qs = []
    for variant in CFG["variants"]:
        z = p[p.variant.eq(variant)].set_index("pair_index").loc[np.flatnonzero(use)]
        q = distribution(test, (z.score / z.tau).to_numpy())
        qs.append(
            pd.DataFrame({"pair_index": np.flatnonzero(use), "variant": variant, "probability": q})
        )
        for pool in [6, 7]:
            results.append(evaluate_policy(test, q, f"{variant}_pool{pool}", pool))
    r = pd.concat([v[0] for v in results], ignore_index=True)
    t = pd.concat([v[1] for v in results], ignore_index=True)
    r.to_csv(OUT / "race_metrics.csv", index=False)
    t.to_parquet(OUT / "six_tickets.parquet", index=False)
    pd.concat(qs, ignore_index=True).to_parquet(
        OUT / "conditional_probabilities.parquet", index=False
    )
    summarize(r)
    print(
        pd.read_csv(OUT / "summary.csv").query('scope == "all"').to_string(index=False), flush=True
    )
    save(
        OUT / "analysis_complete.json",
        dict(
            races=test.rid.nunique(),
            runners=int(pd.read_parquet(OUT / "oof_runners.parquet").year.ge(2024).sum()),
            policies=r.policy.nunique(),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "fit", "analyze"])
    args = parser.parse_args()
    with threadpool_limits(limits=4):
        {"prepare": prepare, "fit": fit, "analyze": analyze}[args.phase]()
