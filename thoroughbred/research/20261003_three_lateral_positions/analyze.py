"""Three starting groups and three within-pack lateral positions, frozen priors."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
PRIOR = HERE.parent / "20261002_gate_lateral_bias"
TIME = HERE.parent / "20261003_gate_lateral_time_windows"
SPEC = importlib.util.spec_from_file_location("bias", PRIOR / "analyze.py")
BIAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BIAS)
SPEC2 = importlib.util.spec_from_file_location("time_study", TIME / "analyze.py")
TWIN = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(TWIN)
SIDES = ["inner", "middle", "outer"]
CONTRASTS = {"middle-inner": [1, 0], "outer-inner": [0, 1], "outer-middle": [-1, 1]}


def build_positions(runners, passing):
    look = {key: one.set_index("horse_number") for key, one in runners.groupby("race_key")}
    records, counts = (
        [],
        {"eligible_points": 0, "valid_points": 0, "packs_1": 0, "packs_2": 0, "packs_3plus": 0},
    )
    for row in passing.itertuples():
        if row.race_key not in look or row.point not in BIAS.POINTS[int(row.meet)]:
            continue
        counts["eligible_points"] += 1
        try:
            packs = BIAS.POSITION.parse(row.notation_raw)
        except ValueError:
            continue
        roster = look[row.race_key]
        members = [number for pack in packs for number in pack["members"]]
        if set(members) != set(roster.index):
            continue
        counts["valid_points"] += 1
        for index, pack in enumerate(packs):
            n = len(pack["members"])
            counts["packs_1" if n == 1 else "packs_2" if n == 2 else "packs_3plus"] += 1
            if n < 3:
                continue
            for j, number in enumerate(pack["members"]):
                records.append(
                    {
                        "race_key": row.race_key,
                        "point": row.point,
                        "horse_number": number,
                        "pack_id": f"{row.race_key}:{row.point}:{index}",
                        "pack_index": index,
                        "pack_size": n,
                        "lateral_side": "inner" if j == 0 else "outer" if j == n - 1 else "middle",
                        "notation_raw": row.notation_raw,
                    }
                )
    frame = pd.DataFrame(records).merge(
        runners.drop(columns=["gate_side"]), on=["race_key", "horse_number"], validate="many_to_one"
    )
    frame["gate_side"] = frame.lateral_side
    return frame, counts


def weighted_center(frame, x, y, lateral):
    group = frame.pack_id if lateral else frame.race_key
    code = pd.factorize(group)[0]
    if lateral:
        packs = frame.groupby("race_key").pack_id.transform("nunique").to_numpy()
        per_side = frame.groupby(["pack_id", "gate_side"]).gate_side.transform("size").to_numpy()
        weight = 1 / (packs * 3 * per_side)
    else:
        weight = 1 / frame.groupby("race_key").race_key.transform("size").to_numpy()
    totals = np.bincount(code, weights=weight)
    xc = x - np.column_stack(
        [np.bincount(code, weights=weight * v)[code] / totals[code] for v in x.T]
    )
    yc = y - np.bincount(code, weights=weight * y)[code] / totals[code]
    return xc, yc, weight, len(totals)


def features(frame, metadata, levels=None):
    # Reuse the already verified feature construction; lateral_side uses gate_side field.
    return TWIN.design(frame, levels or {}, metadata, paired=False)


def fit(frame, lateral, temporal=False, inference=True):
    keys = BIAS.CONTROLS + (["gate_pct"] if lateral else [])
    metadata = TWIN.numeric_metadata(frame, keys)
    categories = (
        ["distance_m", "band", "month", "pack_size"]
        if lateral
        else ["distance_m", "band", "month", "n"]
    )
    levels = {key: sorted(frame[key].unique().tolist()) for key in categories} if temporal else {}
    x, labels, k = features(frame, metadata, levels)
    xc, yc, weight, groups = weighted_center(frame, x, frame.top3.to_numpy(float), lateral)
    xw, yw = xc * np.sqrt(weight[:, None]), yc * np.sqrt(weight)
    gram = xw.T @ xw
    inverse = np.linalg.pinv(gram, rcond=1e-10)
    beta = inverse @ (xw.T @ yw)
    model = {
        "metadata": metadata,
        "levels": levels,
        "labels": labels,
        "condition_columns": k,
        "coefficients": beta.tolist(),
    }
    if not inference:
        return model
    day = pd.factorize(frame.day_key)[0]
    days = int(day.max()) + 1
    errors = yw - xw @ beta
    scores = np.column_stack([np.bincount(day, weights=v * errors, minlength=days) for v in xw.T])
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    correction = days / (days - 1) * (len(frame) - 1) / max(len(frame) - groups - rank, 1)
    covariance = inverse @ (scores.T @ scores) @ inverse * correction
    rows = []
    for name, values in CONTRASTS.items():
        vector = np.zeros(x.shape[1])
        vector[:2] = values
        rows.append(
            {
                "contrast": name,
                **BIAS.POSITION.contrast(beta, covariance, inverse @ gram, days, vector),
            }
        )
    return rows, model


def side_races(frame, fields, lateral):
    if lateral:
        cells = frame.groupby(["race_key", "pack_id", "gate_side"])[fields].mean()
        cells = cells.groupby(["race_key", "gate_side"]).mean().unstack("gate_side")
    else:
        cells = frame.groupby(["race_key", "gate_side"])[fields].mean().unstack("gate_side")
    return cells


def contrasts_results(runners, positions):
    rows, models = [], []
    sources = [(meet, "gate", False, one) for meet, one in runners.groupby("meet")]
    sources += [
        (meet, point, True, one) for (meet, point), one in positions.groupby(["meet", "point"])
    ]
    for meet, point, lateral, venue in sources:
        for period in ["all", "2024plus"]:
            sample = venue if period == "all" else venue[venue.year.ge(2024)]
            cells = [(None, sample)] + [
                (int(d), one)
                for d, one in sample[sample.distance_m.isin(BIAS.DISTANCES)].groupby("distance_m")
            ]
            for distance, one in cells:
                if not BIAS.supported(one):
                    continue
                fitted, model = fit(one, lateral)
                raw = side_races(one, ["top3"], lateral)["top3"]
                base = {
                    "meet": int(meet),
                    "point": point,
                    "period": period,
                    "distance_m": distance,
                    "races": one.race_key.nunique(),
                    "days": one.day_key.nunique(),
                    "runner_rows": len(one),
                }
                if lateral:
                    base["packs"] = one.pack_id.nunique()
                models.append({**base, **model})
                for row in fitted:
                    a, b = row["contrast"].split("-")
                    rows.append({**base, "raw_pp": float((raw[a] - raw[b]).mean()) * 100, **row})
        print(f"Main contrasts meet={meet} point={point}", flush=True)
    for period in ["all", "2024plus"]:
        for gate in [True, False]:
            family = [
                r
                for r in rows
                if r["period"] == period
                and (r["point"] == "gate") == gate
                and ((r["distance_m"] is not None) if gate else (r["distance_m"] is None))
                and r["estimable"]
            ]
            for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
                row["q_family"] = float(q)
    return rows, models


def frozen_temporal(runners, positions):
    rows, models = [], []
    previous = json.loads((TIME / "outputs/baseline_models.json").read_text())
    sources = [(meet, "gate", False, one) for meet, one in runners.groupby("meet")]
    sources += [
        (meet, point, True, one) for (meet, point), one in positions.groupby(["meet", "point"])
    ]
    for meet, point, lateral, source in sources:
        for year in range(2020, 2027):
            train, test = source[source.year.lt(year)], source[source.year.eq(year)].copy()
            if test.empty:
                continue
            if lateral:
                model = fit(train, True, temporal=True, inference=False)
            else:
                old = next(
                    m
                    for m in previous
                    if m["meet"] == meet and m["point"] == "gate" and m["year"] == year
                )
                model = {
                    "metadata": old["numeric_metadata"],
                    **{
                        key: old[key]
                        for key in ["levels", "condition_columns", "labels", "coefficients"]
                    },
                }
            x, _, k = features(test, model["metadata"], model["levels"])
            beta = np.asarray(model["coefficients"])
            test["condition"] = x[:, :k] @ beta[:k]
            test["ability"] = x[:, k:] @ beta[k:]
            cells = side_races(test, ["top3", "condition", "ability"], lateral)
            race_meta = (
                test.drop_duplicates("race_key").set_index("race_key")[
                    [
                        "meet",
                        "point",
                        "date",
                        "dt",
                        "year",
                        "month",
                        "race_no",
                        "day_key",
                        "distance_m",
                        "band",
                    ]
                ]
                if lateral
                else test.drop_duplicates("race_key")
                .assign(point="gate")
                .set_index("race_key")[
                    [
                        "meet",
                        "point",
                        "date",
                        "dt",
                        "year",
                        "month",
                        "race_no",
                        "day_key",
                        "distance_m",
                        "band",
                    ]
                ]
            )
            support = train.groupby("distance_m").agg(
                races=("race_key", "nunique"), days=("day_key", "nunique")
            )
            race_meta["baseline_supported"] = race_meta.distance_m.map(
                support.races.ge(50) & support.days.ge(20)
            ).fillna(False)
            race_meta["baseline_trained_through"] = int(train.year.max())
            for name in CONTRASTS:
                a, b = name.split("-")
                race = race_meta.copy()
                race["contrast"] = name
                race["raw"] = cells["top3"][a] - cells["top3"][b]
                ability = cells["ability"][a] - cells["ability"][b]
                race["ability_adjusted"] = race.raw - ability
                race["expected"] = cells["condition"][a] - cells["condition"][b]
                race["deviation"] = race.ability_adjusted - race.expected
                rows.append(race.reset_index())
            models.append(
                {
                    "meet": int(meet),
                    "point": point,
                    "year": year,
                    "trained_through": int(train.year.max()),
                    "train_rows": len(train),
                    **model,
                }
            )
        print(f"Frozen three-side contrasts meet={meet} point={point}", flush=True)
    return pd.concat(rows, ignore_index=True), models


def periods(races):
    rows = []
    for (meet, point, contrast), frame in races[races.baseline_supported].groupby(
        ["meet", "point", "contrast"]
    ):
        for window in ["date", "weekend", "month"]:
            sample = frame if window != "weekend" else frame[frame.weekday.ge(4)]
            key = {"date": "date", "weekend": "weekend_start", "month": "year_month"}[window]
            cells = [(None, sample)] + [
                (int(d), one)
                for d, one in sample[sample.distance_m.isin(BIAS.DISTANCES)].groupby("distance_m")
            ]
            for distance, one in cells:
                for period, cell in one.groupby(key):
                    n, days = len(cell), cell.day_key.nunique()
                    minimum = (
                        {"date": 5, "weekend": 10, "month": 40}[window]
                        if distance is None
                        else {"date": 3, "weekend": 4, "month": 12}[window]
                    )
                    ci, p = TWIN.interval_month(cell) if window == "month" else (None, None)
                    rows.append(
                        {
                            "meet": int(meet),
                            "point": point,
                            "contrast": contrast,
                            "window": window,
                            "period": str(period),
                            "distance_m": distance,
                            "races": n,
                            "days": days,
                            "supported": bool(
                                n >= minimum
                                and days >= {"date": 1, "weekend": 2, "month": 6}[window]
                            ),
                            **{f"{key}_pp": float(cell[key].mean()) * 100 for key in TWIN.METRICS},
                            "ci95_pp": ci,
                            "p": p,
                        }
                    )
    for gate in [True, False]:
        family = [
            r
            for r in rows
            if (r["point"] == "gate") == gate
            and r["window"] == "month"
            and r["distance_m"] is None
            and r["supported"]
            and r["p"] is not None
        ]
        for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
            row["q_month"] = float(q)
    return pd.DataFrame(rows)


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PRIOR / "analyze.py",
        PRIOR / "outputs/runners.parquet",
        PRIOR / "outputs/passing_snapshot.parquet",
        PRIOR / "outputs/verification.json",
        TIME / "analyze.py",
        TIME / "outputs/baseline_models.json",
        TIME / "outputs/verification.json",
    ]
    hashes = {str(p): BIAS.sha(p) for p in paths}
    OUT.mkdir()
    runners = pd.read_parquet(PRIOR / "outputs/runners.parquet")
    passing = pd.read_parquet(PRIOR / "outputs/passing_snapshot.parquet")
    positions, coverage = build_positions(runners, passing)
    positions.to_parquet(OUT / "three_position_runners.parquet", index=False)
    results, main_models = contrasts_results(runners, positions)
    pd.DataFrame(results).to_json(
        OUT / "contrasts.json", orient="records", force_ascii=False, indent=2
    )
    (OUT / "main_models.json").write_text(json.dumps(main_models, ensure_ascii=False, indent=2))
    races, models = frozen_temporal(runners, positions)
    races["weekday"] = races.dt.dt.dayofweek
    races["year_month"] = races.dt.dt.strftime("%Y-%m")
    races["weekend_start"] = (
        races.dt - pd.to_timedelta((races.weekday - 4) % 7, unit="D")
    ).dt.strftime("%Y-%m-%d")
    assert (races.baseline_trained_through < races.year).all()
    assert races[TWIN.METRICS].notna().all().all()
    assert not races.duplicated(["meet", "point", "race_key", "contrast"]).any()
    races.to_parquet(OUT / "race_contrasts.parquet", index=False)
    (OUT / "baseline_models.json").write_text(json.dumps(models, ensure_ascii=False, indent=2))
    print("Aggregating three temporal contrasts", flush=True)
    table = periods(races)
    table.to_parquet(OUT / "periods.parquet", index=False)
    for window in ["date", "weekend", "month"]:
        table[table.window.eq(window)].to_csv(OUT / f"{window}_contrasts.csv", index=False)
    assert hashes == {str(p): BIAS.sha(p) for p in paths}
    summary = {
        "input_sha256": hashes,
        "lateral_coverage": coverage,
        "lateral_runner_rows": len(positions),
        "lateral_by_point": positions.groupby(["meet", "point"])
        .agg(
            runners=("horse_number", "size"),
            races=("race_key", "nunique"),
            packs=("pack_id", "nunique"),
            days=("day_key", "nunique"),
        )
        .reset_index()
        .to_dict("records"),
        "main_contrasts": len(results),
        "baseline_models": len(models),
        "temporal_race_contrasts": len(races),
        "period_contrasts": len(table),
        "inputs_unchanged": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary["lateral_by_point"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
