"""Joint gate/lateral partial observations and prior-date smooth residual corrections."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261003_three_lateral_positions"
SPEC = importlib.util.spec_from_file_location("three", PREVIOUS / "analyze.py")
THREE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(THREE)
BIAS = THREE.BIAS
NAMES = [
    "gate_middle",
    "gate_outer",
    "lateral_middle",
    "lateral_outer",
    "pair_outer",
    "gm_lm",
    "gm_lo",
    "go_lm",
    "go_lo",
    "pair_gm_lo",
    "pair_go_lo",
]
MODES = {"gate": [0, 1], "lateral": [2, 3, 4], "joint": list(range(11))}
SETTINGS = [{"mode": "zero", "half_life": 0, "prior_races": 0}] + [
    {"mode": mode, "half_life": h, "prior_races": k}
    for mode in MODES
    for h in [14, 28, 56]
    for k in [40, 80, 120]
]


def build(runners, passing):
    roster = runners.groupby("race_key").horse_number.agg(set).to_dict()
    records, counts = (
        [],
        {
            "valid_points": 0,
            "invalid_points": 0,
            "single_packs": 0,
            "pair_packs": 0,
            "three_plus_packs": 0,
        },
    )
    for row in passing.itertuples():
        if row.race_key not in roster or row.point not in BIAS.POINTS[int(row.meet)]:
            continue
        try:
            packs = BIAS.POSITION.parse(row.notation_raw)
        except ValueError:
            counts["invalid_points"] += 1
            continue
        if {n for pack in packs for n in pack["members"]} != roster[row.race_key]:
            counts["invalid_points"] += 1
            continue
        counts["valid_points"] += 1
        for index, pack in enumerate(packs):
            n = len(pack["members"])
            counts[
                "single_packs" if n == 1 else "pair_packs" if n == 2 else "three_plus_packs"
            ] += 1
            for j, number in enumerate(pack["members"]):
                records.append(
                    {
                        "race_key": row.race_key,
                        "point": row.point,
                        "horse_number": number,
                        "pack_index": index,
                        "pack_id": f"{row.race_key}:{row.point}:{index}",
                        "pack_size": n,
                        "lateral_side": "single"
                        if n == 1
                        else "inner"
                        if j == 0
                        else "outer"
                        if j == n - 1
                        else "middle",
                        "notation_raw": row.notation_raw,
                    }
                )
    all_positions = pd.DataFrame(records).merge(
        runners, on=["race_key", "horse_number"], validate="many_to_one"
    )
    observed = all_positions[all_positions.pack_size.ge(2)].copy()
    packs = observed.groupby("race_key").pack_id.transform("nunique")
    # race_key occurs at multiple points: weights must be computed within each point.
    packs = observed.groupby(["race_key", "point"]).pack_id.transform("nunique")
    sides = np.where(observed.pack_size.eq(2), 2, 3)
    per_side = observed.groupby(["pack_id", "lateral_side"]).lateral_side.transform("size")
    observed["observation_weight"] = 1 / (packs * sides * per_side)
    return all_positions, observed, counts


def environment(frame):
    gm, go = [frame.gate_side.eq(s).to_numpy(float) for s in ["middle", "outer"]]
    lm, lo = [frame.lateral_side.eq(s).to_numpy(float) for s in ["middle", "outer"]]
    pair = frame.pack_size.eq(2).to_numpy(float)
    return np.column_stack(
        [
            gm,
            go,
            lm,
            lo,
            lo * pair,
            gm * lm,
            gm * lo,
            go * lm,
            go * lo,
            pair * gm * lo,
            pair * go * lo,
        ]
    )


def cell_vector(gate, side, pair=False):
    gm, go = float(gate == "middle"), float(gate == "outer")
    lm, lo = float(side == "middle"), float(side == "outer")
    p = float(pair)
    return np.array(
        [gm, go, lm, lo, lo * p, gm * lm, gm * lo, go * lm, go * lo, p * gm * lo, p * go * lo]
    )


def coefficients_design(frame, metadata, temporal=False):
    e = environment(frame)
    numeric, names = THREE.TWIN.ability_columns(frame, metadata)
    arrays, labels = [e], NAMES.copy()
    if temporal:
        moisture = (frame.moisture.to_numpy(float) - 8) / 10
        angle = 2 * np.pi * (frame.month.to_numpy(float) - 1) / 12
        for name, values in [
            ("moisture", moisture),
            ("season_sin", np.sin(angle)),
            ("season_cos", np.cos(angle)),
        ]:
            arrays.append(e[:, :5] * values[:, None])
            labels += [f"{c}:{name}" for c in NAMES[:5]]
        arrays.append(e[:, :2] * ((frame.n.to_numpy(float) - 10) / 4)[:, None])
        labels += [f"{c}:field_size" for c in NAMES[:2]]
    arrays.append(np.column_stack(numeric))
    labels += names
    return np.column_stack(arrays), labels


def center(frame, x, y=None):
    code = pd.factorize(frame.pack_id)[0]
    w = frame.observation_weight.to_numpy(float)
    totals = np.bincount(code, weights=w)
    xc = x - np.column_stack([np.bincount(code, weights=w * v)[code] / totals[code] for v in x.T])
    target = frame.top3.to_numpy(float) if y is None else y
    yc = target - np.bincount(code, weights=w * target)[code] / totals[code]
    return xc, yc, w, len(totals)


def fit(frame, temporal=False, inference=True):
    metadata = THREE.TWIN.numeric_metadata(frame, BIAS.CONTROLS)
    x, labels = coefficients_design(frame, metadata, temporal)
    xc, yc, w, groups = center(frame, x)
    xw, yw = xc * np.sqrt(w[:, None]), yc * np.sqrt(w)
    gram = xw.T @ xw
    inv = np.linalg.pinv(gram, rcond=1e-10)
    beta = inv @ (xw.T @ yw)
    model = {
        "numeric_metadata": metadata,
        "labels": labels,
        "coefficients": beta.tolist(),
        "races": int(frame.race_key.nunique()),
        "days": int(frame.day_key.nunique()),
        "rows": len(frame),
        "temporal": temporal,
    }
    if not inference:
        return model
    day = pd.factorize(frame.day_key)[0]
    days = int(day.max()) + 1
    error = yw - xw @ beta
    score = np.column_stack([np.bincount(day, weights=v * error, minlength=days) for v in xw.T])
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    correction = days / (days - 1) * (len(frame) - 1) / max(len(frame) - groups - rank, 1)
    cov = inv @ (score.T @ score) @ inv * correction
    return model, cov, inv @ gram


def compare(model, cov, projection, vector):
    v = np.zeros(len(model["coefficients"]))
    v[: len(vector)] = vector
    return BIAS.POSITION.contrast(
        np.array(model["coefficients"]), cov, projection, model["days"], v
    )


def support_cell(frame, gate, side, pair=False):
    cell = frame[
        frame.gate_side.eq(gate)
        & frame.lateral_side.eq(side)
        & (frame.pack_size.eq(2) if pair else frame.pack_size.ge(3))
    ]
    return {
        "runners": len(cell),
        "races": int(cell.race_key.nunique()),
        "days": int(cell.day_key.nunique()),
        "supported_cell": bool(
            len(cell) >= 100 and cell.race_key.nunique() >= 50 and cell.day_key.nunique() >= 20
        ),
    }


def main_contrasts(observed):
    rows, cells, models = [], [], []
    for (meet, point), venue in observed.groupby(["meet", "point"]):
        for period in ["all", "2024plus"]:
            sample = venue if period == "all" else venue[venue.year.ge(2024)]
            strata = [(None, sample)] + [
                (int(d), one)
                for d, one in sample[sample.distance_m.isin(BIAS.DISTANCES)].groupby("distance_m")
            ]
            for distance, one in strata:
                if not BIAS.supported(one):
                    continue
                model, cov, projection = fit(one)
                base = {
                    "meet": int(meet),
                    "point": point,
                    "period": period,
                    "distance_m": distance,
                    "races": model["races"],
                    "days": model["days"],
                    "pair_packs": int(one[one.pack_size.eq(2)].pack_id.nunique()),
                    "three_packs": int(one[one.pack_size.ge(3)].pack_id.nunique()),
                }
                models.append({**base, **model})
                for a, b in [("middle", "inner"), ("outer", "inner"), ("outer", "middle")]:
                    for kind in ["lateral_at_middle_gate", "gate_at_middle_lateral"]:
                        v = (
                            cell_vector("middle", a) - cell_vector("middle", b)
                            if kind.startswith("lateral")
                            else cell_vector(a, "middle") - cell_vector(b, "middle")
                        )
                        rows.append(
                            {
                                **base,
                                "kind": kind,
                                "contrast": f"{a}-{b}",
                                **compare(model, cov, projection, v),
                            }
                        )
                v = cell_vector("middle", "outer", True) - cell_vector("middle", "inner", True)
                rows.append(
                    {
                        **base,
                        "kind": "pair_outer_inner_at_middle_gate",
                        "contrast": "outer-inner",
                        **compare(model, cov, projection, v),
                    }
                )
                triple = cell_vector("middle", "outer") - cell_vector("middle", "inner")
                rows.append(
                    {
                        **base,
                        "kind": "pair_minus_triple",
                        "contrast": "outer-inner",
                        **compare(model, cov, projection, v - triple),
                    }
                )
                reference = cell_vector("middle", "middle")
                for gate in THREE.SIDES:
                    for side in THREE.SIDES:
                        cells.append(
                            {
                                **base,
                                "gate": gate,
                                "lateral": side,
                                "pair": False,
                                **support_cell(one, gate, side),
                                **compare(
                                    model, cov, projection, cell_vector(gate, side) - reference
                                ),
                            }
                        )
                    reference2 = cell_vector("middle", "inner", True)
                    for side in ["inner", "outer"]:
                        cells.append(
                            {
                                **base,
                                "gate": gate,
                                "lateral": side,
                                "pair": True,
                                **support_cell(one, gate, side, True),
                                **compare(
                                    model,
                                    cov,
                                    projection,
                                    cell_vector(gate, side, True) - reference2,
                                ),
                            }
                        )
        print(f"Joint main models meet={meet} point={point}", flush=True)
    # Pair-only contrast is supplementary. The seven planned families include heterogeneity.
    for period in ["all", "2024plus"]:
        family = [
            r
            for r in rows
            if r["period"] == period
            and r["distance_m"] is None
            and r["kind"] != "pair_outer_inner_at_middle_gate"
            and r["estimable"]
        ]
        for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
            row["q_family"] = float(q)
    return rows, cells, models


def number_contrasts(observed):
    rows, models = [], []
    for (meet, point), venue in observed.groupby(["meet", "point"]):
        full = venue[venue.n.eq(12)]
        # Confirm complete roster through stored n/program rule in the original runner snapshot.
        for period in ["all", "2024plus"]:
            frame = full if period == "all" else full[full.year.ge(2024)]
            if not BIAS.supported(frame):
                continue
            metadata = THREE.TWIN.numeric_metadata(frame, BIAS.CONTROLS)
            numeric, names = THREE.TWIN.ability_columns(frame, metadata)
            gates = [frame.horse_number.eq(i).to_numpy(float) for i in range(2, 13)]
            lateral = environment(frame)[:, 2:5]
            for joint in [False, True]:
                x = np.column_stack(gates + (list(lateral.T) if joint else []) + numeric)
                xc, yc, w, groups = center(frame, x)
                xw, yw = xc * np.sqrt(w[:, None]), yc * np.sqrt(w)
                gram = xw.T @ xw
                inv = np.linalg.pinv(gram, rcond=1e-10)
                beta = inv @ (xw.T @ yw)
                day = pd.factorize(frame.day_key)[0]
                days = int(day.max()) + 1
                errors = yw - xw @ beta
                scores = np.column_stack(
                    [np.bincount(day, weights=v * errors, minlength=days) for v in xw.T]
                )
                rank = np.linalg.matrix_rank(gram, tol=1e-8)
                cov = (
                    inv
                    @ (scores.T @ scores)
                    @ inv
                    * days
                    / (days - 1)
                    * (len(frame) - 1)
                    / max(len(frame) - groups - rank, 1)
                )
                base = {
                    "meet": int(meet),
                    "point": point,
                    "period": period,
                    "joint": joint,
                    "races": int(frame.race_key.nunique()),
                    "days": days,
                }
                models.append(
                    {
                        **base,
                        "metadata": metadata,
                        "coefficients": beta.tolist(),
                        "numeric_labels": names,
                    }
                )
                for number in range(1, 13):
                    v = np.zeros(len(beta))
                    if number > 1:
                        v[number - 2] = 1
                    rows.append(
                        {
                            **base,
                            "number": number,
                            **BIAS.POSITION.contrast(beta, cov, inv @ gram, days, v),
                        }
                    )
        print(f"Number joint models meet={meet} point={point}", flush=True)
    for period in ["all", "2024plus"]:
        for joint in [False, True]:
            family = [
                r
                for r in rows
                if r["period"] == period
                and r["joint"] == joint
                and r["number"] > 1
                and r["estimable"]
            ]
            for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
                row["q_number"] = float(q)
    return rows, models


def temporal_supported(train):
    if not BIAS.supported(train):
        return False
    for pair in [True, False]:
        sample = train[train.pack_size.eq(2) if pair else train.pack_size.ge(3)]
        if sample.race_key.nunique() < 30 or sample.day_key.nunique() < 10:
            return False
    return True


def cap_delta(delta):
    cells = np.array(
        [
            cell_vector(gate, side, pair)
            for pair in [False, True]
            for gate in THREE.SIDES
            for side in (["inner", "outer"] if pair else THREE.SIDES)
        ]
    )
    spread = np.ptp(cells @ delta)
    return delta * min(1, 0.05 / spread) if spread > 1e-12 else delta


def corrections(prior, sums, rhs, dates, target, setting):
    if setting["mode"] == "zero":
        return np.zeros(11), 0.0, None
    age = (np.datetime64(target) - dates) / np.timedelta64(1, "D")
    mask = (age > 0) & (age <= 84)
    if not mask.any():
        return np.zeros(11), 0.0, None
    weights = 2 ** (-age[mask] / setting["half_life"])
    gram = np.einsum("d,dij->ij", weights, sums[mask])
    b = np.einsum("d,di->i", weights, rhs[mask])
    indices = MODES[setting["mode"]]
    a = gram[np.ix_(indices, indices)] + setting["prior_races"] * prior[np.ix_(indices, indices)]
    delta = np.zeros(11)
    delta[indices] = np.linalg.pinv(a, rcond=1e-8) @ b[indices]
    last = str(dates[mask].max())[:10]
    return cap_delta(delta), float(weights.sum()), last


def temporal(observed):
    scores, models, audit, latest = [], [], [], []
    for (meet, point, distance), source in observed[
        observed.distance_m.isin(BIAS.DISTANCES)
    ].groupby(["meet", "point", "distance_m"]):
        for year in range(2020, 2027):
            train = source[source.year.lt(year)]
            test = source[source.year.eq(year)]
            if test.empty or not temporal_supported(train):
                continue
            model = fit(train, temporal=True, inference=False)
            beta = np.asarray(model["coefficients"])
            # Include the previous 84 calendar days to initialize the new year's history.
            first = test.dt.min()
            combined = source[
                (source.dt >= first - pd.Timedelta(days=84)) & source.year.le(year)
            ].copy()
            x, _ = coefficients_design(combined, model["numeric_metadata"], True)
            xc, yc, w, _ = center(combined, x)
            residual = yc - xc @ beta
            e = xc[:, :11]
            trainx, _ = coefficients_design(train, model["numeric_metadata"], True)
            tx, _, tw, _ = center(train, trainx)
            prior = (tx[:, :11] * tw[:, None]).T @ tx[:, :11] / train.race_key.nunique()
            code, days = pd.factorize(combined.date, sort=True)
            dates = np.array(days, dtype="datetime64[D]")
            grams = np.zeros((len(days), 11, 11))
            rhs = np.zeros((len(days), 11))
            loss = np.zeros(len(days))
            count = np.zeros(len(days))
            for i in range(len(days)):
                mask = code == i
                ed, wd, rd = e[mask], w[mask], residual[mask]
                grams[i] = (ed * wd[:, None]).T @ ed
                rhs[i] = ed.T @ (wd * rd)
                loss[i] = np.dot(wd, rd * rd)
                count[i] = wd.sum()
            base = {"meet": int(meet), "point": point, "distance_m": int(distance), "year": year}
            models.append(
                {
                    **base,
                    "trained_through": int(train.year.max()),
                    "training_prior_environment_gram": prior.tolist(),
                    **model,
                }
            )
            for i, day in enumerate(days):
                if str(day)[:4] != str(year):
                    continue
                for sid, setting in enumerate(SETTINGS):
                    delta, history_days_weight, last = corrections(
                        prior, grams, rhs, dates, day, setting
                    )
                    error = loss[i] - 2 * rhs[i] @ delta + delta @ grams[i] @ delta
                    scores.append(
                        {
                            **base,
                            "date": str(day),
                            "setting_id": sid,
                            "races": float(count[i]),
                            "loss_sum": float(error),
                            "baseline_loss_sum": float(loss[i]),
                        }
                    )
                    if sid == 23:  # fixed audit setting: joint H28 K80
                        audit.append(
                            {
                                **base,
                                "date": str(day),
                                "last_history_date": last,
                                "decayed_history_days": history_days_weight,
                                "delta": delta.tolist(),
                                "loss_sum": float(error),
                                "baseline_loss_sum": float(loss[i]),
                                "races": float(count[i]),
                                "delta_before_day": True,
                            }
                        )
            if year == 2026:
                for sid, setting in enumerate(SETTINGS):
                    delta, history_weight, last = corrections(
                        prior, grams, rhs, dates, "2026-09-21", setting
                    )
                    latest.append(
                        {
                            **base,
                            "asof_date": "2026-09-21",
                            "setting_id": sid,
                            "last_history_date": last,
                            "decayed_history_days": history_weight,
                            "delta": delta.tolist(),
                        }
                    )
        print(f"Temporal moments meet={meet} point={point} distance={distance}", flush=True)
    return pd.DataFrame(scores), models, audit, latest


def select_and_evaluate(scores):
    selected, tuning, evaluations = [], [], []
    rng = np.random.default_rng(20261004)
    for meet, venue in scores.groupby("meet"):
        dev = venue[venue.year.between(2022, 2023)]
        sums = dev.groupby("setting_id").agg(loss=("loss_sum", "sum"), n=("races", "sum"))
        sums["mse"] = sums.loss / sums.n
        best = sums.mse.min()
        eligible = sums[sums.mse <= best + 0.0001].index

        def preference(sid):
            s = SETTINGS[sid]
            return (
                ["zero", "gate", "lateral", "joint"].index(s["mode"]),
                -s["prior_races"],
                -s["half_life"],
            )

        sid = int(min(eligible, key=preference))
        setting = SETTINGS[sid]
        selected.append(
            {
                "meet": int(meet),
                "setting_id": sid,
                **setting,
                "development_mse": float(sums.loc[sid, "mse"]),
                "best_development_mse": float(best),
                "baseline_development_mse": float(sums.loc[0, "mse"]),
            }
        )
        tuning += [
            {
                "meet": int(meet),
                "setting_id": int(i),
                **SETTINGS[i],
                "development_mse": float(row.mse),
                "selected": i == sid,
            }
            for i, row in sums.iterrows()
        ]
        test = venue[venue.year.ge(2024) & venue.setting_id.eq(sid)]
        for point in [None] + sorted(test.point.unique().tolist()):
            sample = test if point is None else test[test.point.eq(point)]
            daily = sample.groupby("date").agg(
                n=("races", "sum"),
                corrected=("loss_sum", "sum"),
                baseline=("baseline_loss_sum", "sum"),
            )
            change = (daily.baseline.sum() - daily.corrected.sum()) / daily.n.sum()
            draws = rng.integers(0, len(daily), size=(3000, len(daily)))
            gain = (daily.baseline.to_numpy() - daily.corrected.to_numpy())[draws].sum(
                axis=1
            ) / daily.n.to_numpy()[draws].sum(axis=1)
            ci = np.quantile(gain, [0.025, 0.975]).tolist()
            evaluations.append(
                {
                    "meet": int(meet),
                    "point": point,
                    "days": len(daily),
                    "race_point_distance_evaluations": float(daily.n.sum()),
                    "baseline_mse": float(daily.baseline.sum() / daily.n.sum()),
                    "corrected_mse": float(daily.corrected.sum() / daily.n.sum()),
                    "mse_gain": float(change),
                    "relative_gain_percent": float(
                        100 * change / (daily.baseline.sum() / daily.n.sum())
                    ),
                    "gain_ci95": ci,
                    "statistically_clear_improvement": bool(ci[0] > 0),
                    "selected_setting_id": sid,
                }
            )
    return selected, tuning, evaluations


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
        PREVIOUS / "outputs/verification.json",
        BIAS.HERE / "outputs/runners.parquet",
        BIAS.HERE / "outputs/passing_snapshot.parquet",
    ]
    hashes = {str(p): BIAS.sha(p) for p in paths}
    OUT.mkdir()
    runners = pd.read_parquet(paths[4])
    passing = pd.read_parquet(paths[5])
    all_positions, observed, counts = build(runners, passing)
    # Restrict numbered gate supplement to genuinely full 1..12 rosters.
    full12 = {
        key
        for key, one in runners[runners.n.eq(12)].groupby("race_key")
        if set(one.horse_number.astype(int)) == set(range(1, 13))
    }
    all_positions.to_parquet(OUT / "all_positions.parquet", index=False)
    observed.to_parquet(OUT / "observations.parquet", index=False)
    joint, cells, main_models = main_contrasts(observed)
    pd.DataFrame(joint).to_json(
        OUT / "joint_contrasts.json", orient="records", indent=2, force_ascii=False
    )
    pd.DataFrame(cells).to_json(
        OUT / "joint_cells.json", orient="records", indent=2, force_ascii=False
    )
    (OUT / "main_models.json").write_text(json.dumps(main_models, ensure_ascii=False, indent=2))
    numbers, number_models = number_contrasts(observed[observed.race_key.isin(full12)])
    pd.DataFrame(numbers).to_json(
        OUT / "number_contrasts.json", orient="records", indent=2, force_ascii=False
    )
    (OUT / "number_models.json").write_text(json.dumps(number_models, ensure_ascii=False, indent=2))
    all_positions.groupby(["meet", "point", "gate_side", "lateral_side"]).agg(
        runners=("horse_number", "size"),
        top3_rate=("top3", "mean"),
        mean_gate_number=("horse_number", "mean"),
    ).reset_index().to_csv(OUT / "gate_position_exposure.csv", index=False)
    scores, temporal_models, audit, latest = temporal(observed)
    scores.to_parquet(OUT / "temporal_scores.parquet", index=False)
    (OUT / "temporal_models.json").write_text(
        json.dumps(temporal_models, ensure_ascii=False, indent=2)
    )
    (OUT / "temporal_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    (OUT / "latest_all_candidates.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2)
    )
    selected, tuning, evaluation = select_and_evaluate(scores)
    pd.DataFrame(tuning).to_csv(OUT / "tuning_2022_2023.csv", index=False)
    pd.DataFrame(evaluation).to_csv(OUT / "evaluation_2024_2026.csv", index=False)
    selected_map = {r["meet"]: r["setting_id"] for r in selected}
    chosen_latest = [r for r in latest if r["setting_id"] == selected_map[r["meet"]]]
    (OUT / "latest_selected_corrections.json").write_text(
        json.dumps(chosen_latest, ensure_ascii=False, indent=2)
    )
    assert hashes == {str(p): BIAS.sha(p) for p in paths}
    summary = {
        "inputs_sha256": hashes,
        "coverage": counts,
        "all_position_rows": len(all_positions),
        "observed_rows": len(observed),
        "main_models": len(main_models),
        "number_models": len(number_models),
        "temporal_models": len(temporal_models),
        "temporal_score_rows": len(scores),
        "settings": SETTINGS,
        "selected_settings": selected,
        "evaluation": evaluation,
        "conditional_loss_only_not_prerace_probabilities": True,
        "input_hashes_unchanged": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(selected, ensure_ascii=False), flush=True)
    print(json.dumps(evaluation, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
