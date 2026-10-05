"""Verify three-side source assignments, weighted FE solver and temporal contrasts."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("study", HERE / "analyze.py")
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def bh(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    q = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    out = np.empty(len(p))
    out[order] = np.minimum(q, 1)
    return out


def independent_weighted(frame, model, lateral):
    x, _, _ = STUDY.features(frame, model["metadata"], model["levels"])
    xf = pd.DataFrame(x, index=frame.index)
    if lateral:
        weight = 1 / (
            frame.groupby("race_key").pack_id.transform("nunique")
            * 3
            * frame.groupby(["pack_id", "gate_side"]).gate_side.transform("size")
        )
        group = frame.pack_id
    else:
        weight = 1 / frame.groupby("race_key").race_key.transform("size")
        group = frame.race_key
    total = weight.groupby(group).transform("sum")
    meanx = xf.mul(weight, axis=0).groupby(group).transform("sum").div(total, axis=0)
    meany = (frame.top3 * weight).groupby(group).transform("sum") / total
    xw = (xf - meanx).to_numpy() * np.sqrt(weight.to_numpy())[:, None]
    yw = (frame.top3 - meany).to_numpy() * np.sqrt(weight.to_numpy())
    beta, _, _, _ = np.linalg.lstsq(xw, yw, rcond=1e-5)
    pinv = np.linalg.pinv(xw, rcond=1e-5)
    inverse = pinv @ pinv.T
    score = (
        pd.DataFrame(xw * (yw - xw @ beta)[:, None], index=frame.index).groupby(frame.day_key).sum()
    )
    days = len(score)
    n = len(frame)
    rank = np.linalg.matrix_rank(xw.T @ xw, tol=1e-8)
    cov = (
        inverse
        @ (score.to_numpy().T @ score.to_numpy())
        @ inverse
        * days
        / (days - 1)
        * (n - 1)
        / max(n - group.nunique() - rank, 1)
    )
    np.testing.assert_allclose(weight.groupby(frame.race_key).sum(), 1, atol=1e-12)
    if lateral:
        sides = weight.groupby([frame.pack_id, frame.gate_side]).sum().unstack()
        np.testing.assert_allclose(sides.inner, sides.middle, atol=1e-12)
        np.testing.assert_allclose(sides.inner, sides.outer, atol=1e-12)
    return beta, cov, days


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for path, sha in summary["input_sha256"].items():
        assert STUDY.BIAS.sha(Path(path)) == sha, path
    runners = pd.read_parquet(STUDY.PRIOR / "outputs/runners.parquet")
    passing = pd.read_parquet(STUDY.PRIOR / "outputs/passing_snapshot.parquet")
    positions = pd.read_parquet(OUT / "three_position_runners.parquet")
    results = pd.read_json(OUT / "contrasts.json")
    models = json.loads((OUT / "main_models.json").read_text())
    races = pd.read_parquet(OUT / "race_contrasts.parquet")
    periods = pd.read_parquet(OUT / "periods.parquet")
    # Independently assign sides from the original point notation and pack index.
    roster = runners.groupby("race_key").horse_number.agg(set).to_dict()
    expected = []
    for row in passing.itertuples():
        if row.race_key not in roster or row.point not in STUDY.BIAS.POINTS[int(row.meet)]:
            continue
        try:
            packs = STUDY.BIAS.POSITION.parse(row.notation_raw)
        except ValueError:
            continue
        if {n for pack in packs for n in pack["members"]} != roster[row.race_key]:
            continue
        for index, pack in enumerate(packs):
            members = pack["members"]
            if len(members) < 3:
                continue
            for number in members:
                expected.append(
                    {
                        "race_key": row.race_key,
                        "point": row.point,
                        "horse_number": number,
                        "pack_index": index,
                        "pack_size": len(members),
                        "lateral_side": "inner"
                        if number == members[0]
                        else "outer"
                        if number == members[-1]
                        else "middle",
                    }
                )
    keys = ["race_key", "point", "horse_number"]
    source = pd.DataFrame(expected).sort_values(keys).reset_index(drop=True)
    saved = positions.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(source, saved[source.columns], check_dtype=False)
    assert positions.pack_id.nunique() == summary["lateral_coverage"]["packs_3plus"]
    assert not positions.duplicated(keys).any()
    assert positions.pack_size.ge(3).all()
    assert (
        positions.last_history_date.isna()
        .where(positions.last_history_date.isna(), positions.last_history_date.lt(positions.dt))
        .all()
    )
    joined = positions.merge(
        runners, on=["race_key", "horse_number"], suffixes=("", "_source"), validate="many_to_one"
    )
    for key in STUDY.BIAS.CONTROLS + ["gate_pct", "top3"]:
        np.testing.assert_allclose(joined[key], joined[key + "_source"], atol=1e-12, equal_nan=True)
    refits = []
    for model in models:
        if model["period"] != "all" or (
            model["point"] != "gate" and model["distance_m"] is not None
        ):
            continue
        lateral = model["point"] != "gate"
        frame = positions if lateral else runners
        frame = frame[frame.meet.eq(model["meet"])]
        if lateral:
            frame = frame[frame.point.eq(model["point"])]
        if model["distance_m"] is not None:
            frame = frame[frame.distance_m.eq(model["distance_m"])]
        beta, cov, days = independent_weighted(frame, model, lateral)
        rows = results[
            results.meet.eq(model["meet"])
            & results.point.eq(model["point"])
            & results.period.eq("all")
            & (
                results.distance_m.isna()
                if model["distance_m"] is None
                else results.distance_m.eq(model["distance_m"])
            )
        ]
        for row in rows.itertuples():
            vector = np.zeros(len(beta))
            vector[:2] = STUDY.CONTRASTS[row.contrast]
            effect = float(vector @ beta)
            se = np.sqrt(max(0, vector @ cov @ vector))
            np.testing.assert_allclose(effect * 100, row.effect_pp, atol=1e-7)
            np.testing.assert_allclose(
                (effect + np.array([-1, 1]) * t.ppf(0.975, days - 1) * se) * 100,
                row.ci95_pp,
                atol=1e-7,
            )
        refits.append(
            {"meet": model["meet"], "point": model["point"], "distance_m": model["distance_m"]}
        )
    for period in ["all", "2024plus"]:
        for gate in [True, False]:
            family = results[
                results.period.eq(period)
                & results.point.eq("gate").eq(gate)
                & (results.distance_m.notna() if gate else results.distance_m.isna())
            ]
            np.testing.assert_allclose(family.q_family, bh(family.p), atol=1e-8)
    # All three contrasts must share a population and satisfy their exact identity.
    for frame, keys, metrics in [
        (results, ["meet", "point", "period", "distance_m"], ["effect_pp", "raw_pp"]),
        (races, ["meet", "point", "race_key"], STUDY.TWIN.METRICS),
        (
            periods,
            ["meet", "point", "window", "period", "distance_m"],
            [f"{x}_pp" for x in STUDY.TWIN.METRICS],
        ),
    ]:
        frame = frame.copy()
        frame["distance_m"] = frame.distance_m.fillna(-1)
        for metric in metrics:
            wide = frame.pivot(index=keys, columns="contrast", values=metric)
            assert wide.notna().all().all()
            np.testing.assert_allclose(
                wide["outer-middle"], wide["outer-inner"] - wide["middle-inner"], atol=1e-8
            )
    prior = pd.read_parquet(STUDY.TIME / "outputs/race_deviations.parquet")
    old = prior[prior.point.eq("gate")].set_index(["meet", "race_key"])
    new = (
        races[races.point.eq("gate") & races.contrast.eq("outer-inner")]
        .set_index(["meet", "race_key"])
        .loc[old.index]
    )
    np.testing.assert_allclose(new[STUDY.TWIN.METRICS], old[STUDY.TWIN.METRICS], atol=1e-10)
    assert (races.baseline_trained_through < races.year).all()
    assert not races.duplicated(["meet", "point", "race_key", "contrast"]).any()
    baselines = json.loads((OUT / "baseline_models.json").read_text())
    for model in baselines:
        lateral = model["point"] != "gate"
        source = positions if lateral else runners
        source = source[source.meet.eq(model["meet"])]
        if lateral:
            source = source[source.point.eq(model["point"])]
        train, test = (
            source[source.year.lt(model["year"])],
            source[source.year.eq(model["year"])].copy(),
        )
        assert len(train) == model["train_rows"]
        assert train.year.max() == model["trained_through"] < model["year"]
        if lateral:
            for key, values in model["levels"].items():
                assert values == sorted(train[key].unique().tolist())
        for key, info in model["metadata"].items():
            values = train[key].to_numpy(float)
            values = values[np.isfinite(values)]
            median = np.median(values) if len(values) else 0
            scale = values.std() if len(values) and values.std() > 1e-10 else 1
            np.testing.assert_allclose([median, scale], [info["median"], info["scale"]], atol=1e-12)
        x, _, k = STUDY.features(test, model["metadata"], model["levels"])
        beta = np.asarray(model["coefficients"])
        test["condition"] = x[:, :k] @ beta[:k]
        test["ability"] = x[:, k:] @ beta[k:]
        if lateral:
            cells = (
                test.groupby(["race_key", "pack_id", "gate_side"])[["top3", "condition", "ability"]]
                .mean()
                .groupby(["race_key", "gate_side"])
                .mean()
                .unstack()
            )
        else:
            cells = (
                test.groupby(["race_key", "gate_side"])[["top3", "condition", "ability"]]
                .mean()
                .unstack()
            )
        for contrast in STUDY.CONTRASTS:
            a, b = contrast.split("-")
            one = (
                races[
                    races.meet.eq(model["meet"])
                    & races.point.eq(model["point"])
                    & races.year.eq(model["year"])
                    & races.contrast.eq(contrast)
                ]
                .set_index("race_key")
                .loc[cells.index]
            )
            raw = cells.top3[a] - cells.top3[b]
            expected = cells.condition[a] - cells.condition[b]
            adjusted = raw - (cells.ability[a] - cells.ability[b])
            np.testing.assert_allclose(
                one[["raw", "expected", "ability_adjusted"]],
                np.column_stack([raw, expected, adjusted]),
                atol=1e-10,
            )
        if lateral and model["year"] == 2026:
            independent, _, _ = independent_weighted(train, model, lateral)
            np.testing.assert_allclose(x @ independent, x @ beta, atol=1e-7)
    for window in ["date", "weekend", "month"]:
        sample = races[
            races.baseline_supported & (races.weekday.ge(4) if window == "weekend" else True)
        ].copy()
        sample["period"] = sample[
            {"date": "date", "weekend": "weekend_start", "month": "year_month"}[window]
        ]
        for exact in [False, True]:
            keys = ["meet", "point", "contrast", "period"] + (["distance_m"] if exact else [])
            grouped = sample.groupby(keys)
            means = grouped[STUDY.TWIN.METRICS].mean() * 100
            counts = grouped.agg(races=("race_key", "size"), days=("day_key", "nunique"))
            saved = periods[
                periods.window.eq(window)
                & (periods.distance_m.notna() if exact else periods.distance_m.isna())
            ].set_index(keys)
            np.testing.assert_allclose(
                saved[[f"{m}_pp" for m in STUDY.TWIN.METRICS]], means.loc[saved.index], atol=1e-10
            )
            np.testing.assert_array_equal(saved[["races", "days"]], counts.loc[saved.index])
            count = counts.loc[saved.index]
            minimum = (
                {"date": 3, "weekend": 4, "month": 12}[window]
                if exact
                else {"date": 5, "weekend": 10, "month": 40}[window]
            )
            np.testing.assert_array_equal(
                saved.supported,
                count.races.ge(minimum)
                & count.days.ge({"date": 1, "weekend": 2, "month": 6}[window]),
            )
        if window == "month":
            keys = ["meet", "point", "contrast", "period"]
            total = sample.groupby(keys).deviation.transform("mean")
            sample["centered"] = sample.deviation - total
            scores = sample.groupby(keys + ["day_key"]).centered.sum()
            squares = scores.pow(2).groupby(keys).sum()
            check = periods[periods.window.eq("month") & periods.distance_m.isna()].set_index(keys)
            for key, row in check.iterrows():
                if row.days < 2:
                    continue
                se = np.sqrt(squares.loc[key] * row.days / (row.days - 1)) / row.races
                ci = row.deviation_pp + np.array([-1, 1]) * t.ppf(0.975, row.days - 1) * se * 100
                p = 2 * t.sf(abs(row.deviation_pp / (se * 100)), row.days - 1) if se > 1e-14 else 1
                np.testing.assert_allclose(ci, row.ci95_pp, atol=1e-8)
                assert abs(p - row.p) < 1e-10
    for gate in [True, False]:
        family = periods[
            periods.window.eq("month")
            & periods.distance_m.isna()
            & periods.supported
            & periods.point.eq("gate").eq(gate)
        ]
        np.testing.assert_allclose(family.q_month, bh(family.p), atol=1e-12)
    result = {
        "status": "passed",
        "source_runner_rows_checked": len(positions),
        "source_three_packs_checked": positions.pack_id.nunique(),
        "independent_main_refits": refits,
        "independent_2026_lateral_baselines": 8,
        "temporal_race_contrasts_checked": len(races),
        "period_contrasts_checked": len(periods),
        "prior_gate_contrasts_match": True,
        "three_contrast_identity": True,
        "equal_race_and_pack_side_weights": True,
        "bh_verified": True,
        "inputs_unchanged": True,
        "verification_sha256": STUDY.BIAS.sha(HERE / "verify.py"),
    }
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
