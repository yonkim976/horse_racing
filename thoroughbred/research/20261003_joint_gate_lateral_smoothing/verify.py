"""Independent weighted solver, source links and strict pre-day correction replay."""

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
    result = np.empty(len(p))
    result[order] = np.minimum(q, 1)
    return result


def separate_center(frame, x):
    pack_count = frame.groupby(["race_key", "point"]).pack_id.transform("nunique")
    side_count = frame.groupby("pack_id").lateral_side.transform("nunique")
    members = frame.groupby(["pack_id", "lateral_side"]).horse_number.transform("size")
    w = 1 / (pack_count * side_count * members)
    xf = pd.DataFrame(x, index=frame.index)
    total = w.groupby(frame.pack_id).transform("sum")
    mean = xf.mul(w, axis=0).groupby(frame.pack_id).transform("sum").div(total, axis=0)
    ymean = (frame.top3 * w).groupby(frame.pack_id).transform("sum") / total
    return (xf - mean).to_numpy(), (frame.top3 - ymean).to_numpy(), w.to_numpy()


def refit(frame, model):
    x, _ = STUDY.coefficients_design(frame, model["numeric_metadata"], model["temporal"])
    xc, yc, weight = separate_center(frame, x)
    xw, yw = xc * np.sqrt(weight[:, None]), yc * np.sqrt(weight)
    beta = np.linalg.lstsq(xw, yw, rcond=1e-5)[0]
    bread = np.linalg.pinv(xw, rcond=1e-5)
    inverse = bread @ bread.T
    score = (
        pd.DataFrame(xw * (yw - xw @ beta)[:, None], index=frame.index).groupby(frame.day_key).sum()
    )
    days = len(score)
    n = len(frame)
    groups = frame.pack_id.nunique()
    rank = np.linalg.matrix_rank(xw.T @ xw, tol=1e-8)
    cov = (
        inverse
        @ (score.to_numpy().T @ score.to_numpy())
        @ inverse
        * days
        / (days - 1)
        * (n - 1)
        / max(n - groups - rank, 1)
    )
    return beta, cov


def independent_correction(prior, gram, rhs, dates, day, setting):
    if setting["mode"] == "zero":
        return np.zeros(11)
    chosen = np.where(
        (dates < np.datetime64(day)) & (dates >= np.datetime64(day) - np.timedelta64(84, "D"))
    )[0]
    if not len(chosen):
        return np.zeros(11)
    information = np.zeros((11, 11))
    moment = np.zeros(11)
    for i in chosen:
        days = int((np.datetime64(day) - dates[i]) / np.timedelta64(1, "D"))
        weight = np.exp(-np.log(2) * days / setting["half_life"])
        information += gram[i] * weight
        moment += rhs[i] * weight
    indices = STUDY.MODES[setting["mode"]]
    matrix = (
        information[np.ix_(indices, indices)]
        + setting["prior_races"] * prior[np.ix_(indices, indices)]
    )
    delta = np.zeros(11)
    delta[indices] = np.linalg.lstsq(matrix, moment[indices], rcond=1e-8)[0]
    values = [
        STUDY.cell_vector(gate, side, pair) @ delta
        for pair in [False, True]
        for gate in STUDY.THREE.SIDES
        for side in (["inner", "outer"] if pair else STUDY.THREE.SIDES)
    ]
    spread = max(values) - min(values)
    if spread > 0.05:
        delta *= 0.05 / spread
    return delta


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for path, sha in summary["inputs_sha256"].items():
        assert STUDY.BIAS.sha(Path(path)) == sha
    # Verify transitive imported code and source files against the prior study manifest.
    transitive = json.loads((STUDY.PREVIOUS / "outputs/summary.json").read_text())["input_sha256"]
    for path, sha in transitive.items():
        assert STUDY.BIAS.sha(Path(path)) == sha
    all_pos = pd.read_parquet(OUT / "all_positions.parquet")
    observations = pd.read_parquet(OUT / "observations.parquet")
    original = pd.read_parquet(STUDY.BIAS.HERE / "outputs/runners.parquet")
    pairs = pd.read_parquet(STUDY.BIAS.HERE / "outputs/pack_pairs.parquet")
    triples = pd.read_parquet(STUDY.PREVIOUS / "outputs/three_position_runners.parquet")
    assert len(all_pos) == summary["all_position_rows"]
    assert len(observations) == summary["observed_rows"]
    assert not all_pos.duplicated(["race_key", "point", "horse_number"]).any()
    assert (
        all_pos.groupby(["race_key", "point"]).horse_number.size()
        == all_pos.groupby(["race_key", "point"]).n.first()
    ).all()
    assert observations.pack_size.ge(2).all()
    assert not observations[observations.pack_size.eq(2)].lateral_side.eq("middle").any()
    assert observations[observations.pack_size.eq(2)].lateral_side.isin(["inner", "outer"]).all()
    endpoints = observations[observations.lateral_side.isin(["inner", "outer"])].pivot(
        index=["race_key", "point", "pack_index"], columns="lateral_side", values="horse_number"
    )
    old = pairs.set_index(["race_key", "point", "pack_index"]).loc[endpoints.index]
    np.testing.assert_array_equal(endpoints.inner, old.inner_number)
    np.testing.assert_array_equal(endpoints.outer, old.outer_number)
    assert len(endpoints) == len(pairs) == 175814
    keys = ["race_key", "point", "horse_number"]
    a = observations[observations.pack_size.ge(3)].sort_values(keys).reset_index(drop=True)
    b = triples.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        a[keys + ["lateral_side", "pack_size"]],
        b[keys + ["lateral_side", "pack_size"]],
        check_dtype=False,
    )
    joined = all_pos.merge(
        original, on=["race_key", "horse_number"], suffixes=("", "_source"), validate="many_to_one"
    )
    np.testing.assert_array_equal(joined.gate_side, joined.gate_side_source)
    for key in STUDY.BIAS.CONTROLS + ["top3", "moisture"]:
        np.testing.assert_allclose(joined[key], joined[key + "_source"], atol=1e-12, equal_nan=True)
    assert (all_pos.last_history_date.isna() | all_pos.last_history_date.lt(all_pos.dt)).all()
    np.testing.assert_allclose(
        observations.groupby(["race_key", "point"]).observation_weight.sum(), 1, atol=1e-12
    )
    side_weights = (
        observations.groupby(["pack_id", "lateral_side"]).observation_weight.sum().unstack()
    )
    np.testing.assert_allclose(side_weights.inner, side_weights.outer, atol=1e-12)
    np.testing.assert_allclose(
        side_weights.dropna().inner, side_weights.dropna().middle, atol=1e-12
    )
    results = pd.read_json(OUT / "joint_contrasts.json")
    models = json.loads((OUT / "main_models.json").read_text())
    checked = []
    for model in models:
        if model["distance_m"] is not None:
            continue
        frame = observations[
            observations.meet.eq(model["meet"]) & observations.point.eq(model["point"])
        ]
        if model["period"] == "2024plus":
            frame = frame[frame.year.ge(2024)]
        beta, cov = refit(frame, model)
        np.testing.assert_allclose(beta, model["coefficients"], atol=1e-7)
        subset = results[
            results.meet.eq(model["meet"])
            & results.point.eq(model["point"])
            & results.period.eq(model["period"])
            & results.distance_m.isna()
        ]
        for row in subset.itertuples():
            a, b = row.contrast.split("-")
            if row.kind == "lateral_at_middle_gate":
                v = STUDY.cell_vector("middle", a) - STUDY.cell_vector("middle", b)
            elif row.kind == "gate_at_middle_lateral":
                v = STUDY.cell_vector(a, "middle") - STUDY.cell_vector(b, "middle")
            else:
                v = STUDY.cell_vector("middle", "outer", True) - STUDY.cell_vector(
                    "middle", "inner", True
                )
                if row.kind == "pair_minus_triple":
                    v -= STUDY.cell_vector("middle", "outer") - STUDY.cell_vector("middle", "inner")
            padded = np.pad(v, (0, len(beta) - len(v)))
            effect = padded @ beta
            se = np.sqrt(max(0, padded @ cov @ padded))
            np.testing.assert_allclose(effect * 100, row.effect_pp, atol=1e-7)
            np.testing.assert_allclose(
                (effect + np.array([-1, 1]) * t.ppf(0.975, model["days"] - 1) * se) * 100,
                row.ci95_pp,
                atol=1e-7,
            )
        checked.append({"meet": model["meet"], "point": model["point"], "period": model["period"]})
    for period in ["all", "2024plus"]:
        family = results[
            results.period.eq(period)
            & results.distance_m.isna()
            & results.kind.ne("pair_outer_inner_at_middle_gate")
            & results.estimable
        ]
        np.testing.assert_allclose(family.q_family, bh(family.p), atol=1e-8)
    number_results = pd.read_json(OUT / "number_contrasts.json")
    number_refits = []
    number_models = json.loads((OUT / "number_models.json").read_text())
    full_keys = {
        key
        for key, group in original[original.n.eq(12)].groupby("race_key")
        if set(group.horse_number.astype(int)) == set(range(1, 13))
    }
    for model in number_models:
        if model["point"] != "S1F":
            continue
        frame = observations[
            observations.race_key.isin(full_keys)
            & observations.meet.eq(model["meet"])
            & observations.point.eq("S1F")
        ]
        if model["period"] == "2024plus":
            frame = frame[frame.year.ge(2024)]
        assert frame.race_key.nunique() == model["races"]
        numeric, _ = STUDY.THREE.TWIN.ability_columns(frame, model["metadata"])
        vectors = [frame.horse_number.eq(i).to_numpy(float) for i in range(2, 13)]
        if model["joint"]:
            vectors += list(STUDY.environment(frame)[:, 2:5].T)
        x = np.column_stack(vectors + numeric)
        xc, yc, weight = separate_center(frame, x)
        xw, yw = xc * np.sqrt(weight[:, None]), yc * np.sqrt(weight)
        beta = np.linalg.lstsq(xw, yw, rcond=1e-5)[0]
        np.testing.assert_allclose(beta, model["coefficients"], atol=1e-7)
        number_refits.append(
            {"meet": model["meet"], "period": model["period"], "joint": model["joint"]}
        )
    for period in ["all", "2024plus"]:
        for joint in [False, True]:
            sample = number_results[
                number_results.period.eq(period)
                & number_results.joint.eq(joint)
                & number_results.number.gt(1)
                & number_results.estimable
            ]
            np.testing.assert_allclose(sample.q_number, bh(sample.p), atol=1e-8)
    scores = pd.read_parquet(OUT / "temporal_scores.parquet")
    assert scores.loss_sum.ge(-1e-10).all()
    assert len(scores) == summary["temporal_score_rows"]
    assert not scores.duplicated(["meet", "point", "distance_m", "date", "setting_id"]).any()
    group = scores.groupby(["meet", "point", "distance_m", "date"])
    assert group.setting_id.nunique().eq(28).all()
    assert group.baseline_loss_sum.nunique().eq(1).all()
    zero = scores[scores.setting_id.eq(0)]
    np.testing.assert_allclose(zero.loss_sum, zero.baseline_loss_sum, atol=1e-12)
    audits = json.loads((OUT / "temporal_audit.json").read_text())
    for item in audits:
        assert item["last_history_date"] is None or item["last_history_date"] < item["date"]
        delta = np.asarray(item["delta"])
        values = [
            STUDY.cell_vector(g, side, p) @ delta
            for p in [False, True]
            for g in STUDY.THREE.SIDES
            for side in (["inner", "outer"] if p else STUDY.THREE.SIDES)
        ]
        assert np.ptp(values) <= 0.05 + 1e-10
    temporal_models = json.loads((OUT / "temporal_models.json").read_text())
    selected = {r["meet"]: r for r in summary["selected_settings"]}
    replays = []
    for model in temporal_models:
        assert model["trained_through"] < model["year"]
        if model["year"] != 2026 or model["distance_m"] != 1200:
            continue
        source = observations[
            observations.meet.eq(model["meet"])
            & observations.point.eq(model["point"])
            & observations.distance_m.eq(1200)
        ]
        train = source[source.year.lt(2026)]
        assert len(train) == model["rows"]
        independent, _ = refit(train, model)
        np.testing.assert_allclose(independent, model["coefficients"], atol=1e-6)
        first = source[source.year.eq(2026)].dt.min()
        combined = source[source.dt.ge(first - pd.Timedelta(days=84)) & source.year.le(2026)]
        x, _ = STUDY.coefficients_design(combined, model["numeric_metadata"], True)
        xc, yc, w = separate_center(combined, x)
        e = xc[:, :11]
        residual = yc - xc @ np.asarray(model["coefficients"])
        days = sorted(combined.date.unique())
        dates = np.array(days, dtype="datetime64[D]")
        grams, rhs = [], []
        for date in days:
            mask = combined.date.eq(date).to_numpy()
            ed, wd, rd = e[mask], w[mask], residual[mask]
            grams.append((ed * wd[:, None]).T @ ed)
            rhs.append(ed.T @ (wd * rd))
        prior = np.array(model["training_prior_environment_gram"])
        setting = STUDY.SETTINGS[selected[model["meet"]]["setting_id"]]
        test_days = [d for d in days if d.startswith("2026")]
        for day in [test_days[0], test_days[len(test_days) // 2], test_days[-1]]:
            delta = independent_correction(
                prior, np.array(grams), np.array(rhs), dates, day, setting
            )
            mask = combined.date.eq(day).to_numpy()
            actual_loss = np.dot(w[mask], np.square(residual[mask] - e[mask] @ delta))
            row = scores[
                scores.meet.eq(model["meet"])
                & scores.point.eq(model["point"])
                & scores.distance_m.eq(1200)
                & scores.date.eq(day)
                & scores.setting_id.eq(selected[model["meet"]]["setting_id"])
            ].iloc[0]
            assert abs(actual_loss - row.loss_sum) < 1e-8
            replays.append(
                {
                    "meet": model["meet"],
                    "point": model["point"],
                    "date": day,
                    "loss_recomputed": True,
                }
            )
    for meet, choice in selected.items():
        development = (
            scores[scores.meet.eq(meet) & scores.year.between(2022, 2023)]
            .groupby("setting_id")
            .agg(loss=("loss_sum", "sum"), n=("races", "sum"))
        )
        losses = development.loss / development.n
        eligible = losses[losses.le(losses.min() + 0.0001)].index

        def key(i):
            s = STUDY.SETTINGS[i]
            return (
                ["zero", "gate", "lateral", "joint"].index(s["mode"]),
                -s["prior_races"],
                -s["half_life"],
            )

        assert min(eligible, key=key) == choice["setting_id"]
    for row in summary["evaluation"]:
        one = scores[
            scores.meet.eq(row["meet"])
            & scores.year.ge(2024)
            & scores.setting_id.eq(row["selected_setting_id"])
        ]
        if row["point"] is not None:
            one = one[one.point.eq(row["point"])]
        assert one.date.nunique() == row["days"]
        np.testing.assert_allclose(
            [one.loss_sum.sum() / one.races.sum(), one.baseline_loss_sum.sum() / one.races.sum()],
            [row["corrected_mse"], row["baseline_mse"]],
            atol=1e-12,
        )
    result = {
        "status": "passed",
        "source_endpoint_packs_checked": len(endpoints),
        "three_pack_rows_match_prior": len(triples),
        "source_runner_point_rows": len(all_pos),
        "two_body_middle_not_imputed": True,
        "equal_race_pack_side_weights": True,
        "independent_main_refits": checked,
        "independent_full12_S1F_number_refits": number_refits,
        "independent_2026_1200_baselines": 8,
        "independent_pre_day_replays": replays,
        "temporal_scores_checked": len(scores),
        "past_only_audits_checked": len(audits),
        "all_audited_caps_checked": True,
        "selection_development_only": True,
        "heldout_aggregate_losses_checked": True,
        "conditional_target_not_prerace_prediction": True,
        "transitive_inputs_sha256": transitive,
        "verification_sha256": STUDY.BIAS.sha(HERE / "verify.py"),
    }
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "transitive_inputs_sha256"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
