"""Independently verify temporal boundaries, marginal probabilities and forecast losses."""

import json

import analyze as study
import numpy as np
import pandas as pd
from scipy.optimize import brentq


def check_projection(raw, expected):
    shift = brentq(lambda v: np.clip(raw + v, 0.001, 0.999).sum() - 3, -100, 100, xtol=1e-13)
    np.testing.assert_allclose(np.clip(raw + shift, 0.001, 0.999), expected, atol=2e-10)


def main():
    out = study.OUT
    audit = json.loads((out / "summary.json").read_text())
    for name, digest in audit["input_hashes"].items():
        assert study.sha(study.ROOT / name) == digest
    data = pd.read_parquet(study.SOURCE)
    assert (data.last_history_date.isna() | data.last_history_date.lt(data.dt)).all()
    assert data.groupby("race_key").top3.sum().eq(3).all()
    p = pd.read_parquet(out / "runner_predictions.parquet")
    expected = data[data.year.ge(2020)].set_index(["race_key", "horse_id"])
    lookup = p.set_index(["race_key", "horse_id"])
    assert len(lookup) == len(expected) and lookup.index.is_unique
    pd.testing.assert_index_equal(lookup.index.sort_values(), expected.index.sort_values())
    for col in ["top3", "n", "horse_number", "distance_m", "year"]:
        np.testing.assert_array_equal(lookup[col], expected.reindex(lookup.index)[col])
    assert (p.trained_through < p.year).all()
    assert p.groupby("race_key").eligible.nunique().eq(1).all()
    values = p[study.CANDIDATES].to_numpy()
    assert np.isfinite(values).all() and values.min() >= 0.001 and values.max() <= 0.999
    sums = p.groupby("race_key")[study.CANDIDATES].sum()
    np.testing.assert_allclose(sums, 3, atol=2e-10)
    cached = json.loads((study.PRIOR / "outputs/baseline_models.json").read_text())
    models = json.loads((out / "forecast_models.json").read_text())
    states = pd.read_parquet(out / "recent_gate_states.parquet")
    snapshots = pd.read_csv(out / "snapshot_20260921.csv")
    recent_checks, projection_checks, beta_checks = 0, 0, 0
    for model in models:
        meet, year = model["meet"], model["year"]
        venue = data[data.meet.eq(meet)]
        train = venue[venue.year.lt(year)].copy()
        frame = (
            venue[
                venue.dt.ge(pd.Timestamp(f"{year}-01-01") - pd.Timedelta(days=84))
                & venue.year.le(year)
            ]
            .copy()
            .reset_index(drop=True)
        )
        old = next(
            m for m in cached if m["meet"] == meet and m["point"] == "gate" and m["year"] == year
        )
        assert old["trained_through"] < year and model["train_last_date"] < f"{year}-01-01"
        assert set(old["numeric_metadata"]) == set(study.LEGACY.CONTROLS)
        assert set(old["levels"]) == {"distance_m", "band", "month", "n"}
        metadata = old["numeric_metadata"]
        # pandas transforms and direct least squares form a separate annual ability fit.
        a = pd.DataFrame(
            np.column_stack(study.TIME.ability_columns(train, metadata)[0]), index=train.index
        )
        a = a - a.groupby(train.race_key).transform("mean")
        response = train.top3 - train.groupby("race_key").top3.transform("mean")
        b = np.linalg.lstsq(
            a.to_numpy() / np.sqrt(train.n.to_numpy()[:, None]),
            response.to_numpy() / np.sqrt(train.n.to_numpy()),
            rcond=1e-10,
        )[0]
        np.testing.assert_allclose(b, model["ability_coefficients"], atol=1e-8)
        beta_checks += 1
        x, labels, _ = study.TIME.design(frame, old["levels"], metadata, False)
        assert labels == old["labels"]
        base1 = pd.Series(x @ np.array(old["coefficients"]))
        base1 -= base1.groupby(frame.race_key).transform("mean")
        base0 = pd.Series(np.column_stack(study.TIME.ability_columns(frame, metadata)[0]) @ b)
        base0 -= base0.groupby(frame.race_key).transform("mean")
        eligible = study.support(train, frame, old["levels"])
        target_keys = frame[frame.year.eq(year) & eligible].race_key.unique()[:3]
        indexed = p.set_index(["race_key", "horse_id"])
        for key in target_keys:
            f = frame[frame.race_key.eq(key)]
            rows = indexed.reindex(pd.MultiIndex.from_arrays([f.race_key, f.horse_id]))
            check_projection(base0.loc[f.index].to_numpy() + 3 / f.n.to_numpy(), rows.ability_only)
            check_projection(base1.loc[f.index].to_numpy() + 3 / f.n.to_numpy(), rows.gate_base)
            projection_checks += 2
        selected_states = (
            states[states.meet.eq(meet) & states.year.eq(year)]
            .iloc[:: max(1, len(states) // 28)]
            .head(2)
        )
        if year == 2026:
            extra = snapshots[snapshots.meet.eq(meet) & snapshots.distance_m.eq(1600)].copy()
            extra["date"] = extra.as_of
            selected_states = pd.concat([selected_states, extra], ignore_index=True)
        for row in selected_states.itertuples():
            half, strength = map(int, row.candidate.replace("recent_h", "").split("_k"))
            date = pd.Timestamp(row.date)
            prior = frame[
                eligible
                & frame.distance_m.eq(row.distance_m)
                & frame.dt.lt(date)
                & frame.dt.ge(date - pd.Timedelta(days=84))
            ].copy()
            z = pd.DataFrame(
                np.column_stack(
                    [prior.gate_side.eq(k).to_numpy(float) for k in ["middle", "outer"]]
                ),
                index=prior.index,
            )
            z -= z.groupby(prior.race_key).transform("mean")
            prior_weights = (
                np.exp(-np.log(2) * (date - prior.dt).dt.days.to_numpy() / half)
                / prior.n.to_numpy()
            )
            residual = (
                prior.top3.to_numpy() - 3 / prior.n.to_numpy() - base1.loc[prior.index].to_numpy()
            )
            training = train[train.distance_m.eq(row.distance_m)]
            zz = pd.DataFrame(
                np.column_stack(
                    [training.gate_side.eq(k).to_numpy(float) for k in ["middle", "outer"]]
                ),
                index=training.index,
            )
            zz -= zz.groupby(training.race_key).transform("mean")
            prior_gram = (
                zz.to_numpy().T
                @ (zz.to_numpy() / training.n.to_numpy()[:, None])
                / training.race_key.nunique()
            )
            cholesky = np.linalg.cholesky(strength * prior_gram)
            augmented = np.vstack([z.to_numpy() * np.sqrt(prior_weights[:, None]), cholesky.T])
            y = np.r_[residual * np.sqrt(prior_weights), 0, 0]
            gamma = np.linalg.lstsq(augmented, y, rcond=1e-12)[0]
            spread = max(0, *gamma) - min(0, *gamma)
            if spread > 0.05:
                gamma *= 0.05 / spread
            np.testing.assert_allclose(gamma * 100, [row.middle_pp, row.outer_pp], atol=1e-8)
            if row.history_races:
                assert row.history_last_date < row.date
            recent_checks += 1
    assert (
        (pd.to_datetime(states.date) - pd.to_datetime(states.history_last_date)).dt.days.dropna()
        > 0
    ).all()
    assert (
        np.max(
            np.maximum.reduce(
                [states.middle_pp.to_numpy(), states.outer_pp.to_numpy(), np.zeros(len(states))]
            )
            - np.minimum.reduce(
                [states.middle_pp.to_numpy(), states.outer_pp.to_numpy(), np.zeros(len(states))]
            )
        )
        <= 5.0000001
    )
    loss = pd.read_parquet(out / "race_losses.parquet")
    checks = []
    for candidate in study.CANDIDATES:
        frame = p[p.eligible]
        probability = frame[candidate].to_numpy()
        y = frame.top3.to_numpy()
        ll = pd.Series(
            -(y * np.log(probability) + (1 - y) * np.log1p(-probability)), index=frame.index
        )
        bb = pd.Series((y - probability) ** 2, index=frame.index)
        ll = ll.groupby(frame.race_key).mean()
        bb = bb.groupby(frame.race_key).mean()
        stored = loss[loss.candidate.eq(candidate)].set_index("race_key")
        np.testing.assert_allclose(stored.log_loss, ll.reindex(stored.index), atol=1e-12)
        np.testing.assert_allclose(stored.brier, bb.reindex(stored.index), atol=1e-12)
        ranked = frame.sort_values(["race_key", "horse_number"])
        top = ranked.groupby("race_key")[candidate].rank(method="first", ascending=False).le(3)
        precision = (ranked.top3 * top).groupby(ranked.race_key).sum() / 3
        np.testing.assert_allclose(
            stored.top3_precision, precision.reindex(stored.index), atol=1e-12
        )
        checks.append(len(stored))
    selection = pd.read_csv(out / "candidate_selection.csv")
    for row in selection.itertuples():
        f = loss[
            loss.meet.eq(row.meet) & loss.year.isin([2022, 2023]) & loss.candidate.eq(row.candidate)
        ]
        np.testing.assert_allclose(row.log_loss, f.log_loss.mean(), atol=1e-12)
    selected = json.loads((out / "selected_candidates.json").read_text())
    priority = ["ability_only", "gate_base"] + [
        f"recent_h{half}_k{strength}" for strength in [120, 80, 40] for half in [56, 28, 14]
    ]
    for meet, f in selection.groupby("meet"):
        acceptable = set(f.loc[f.log_loss.le(f.log_loss.min() + 0.0001), "candidate"])
        assert (
            next(candidate for candidate in priority if candidate in acceptable)
            == selected[str(meet)]
        )
    boot = pd.read_csv(out / "paired_day_bootstrap.csv")
    rng = np.random.default_rng(20261008)
    for meet in sorted(loss.meet.unique()):
        evaluation = loss[loss.meet.eq(meet) & loss.year.ge(2024)]
        for candidate in sorted({"gate_base", selected[str(meet)]}):
            for metric in ["log_loss", "brier", "top3_precision"]:
                wide = evaluation.pivot(
                    index=["race_key", "day_key"], columns="candidate", values=metric
                )
                difference = wide[candidate] - wide.ability_only
                daily = difference.groupby(level="day_key").agg(["sum", "size"])
                draws = rng.integers(0, len(daily), size=(500, len(daily)))
                multiplicity = np.array([np.bincount(draw, minlength=len(daily)) for draw in draws])
                values = (multiplicity @ daily["sum"].to_numpy()) / (
                    multiplicity @ daily["size"].to_numpy()
                )
                observed = boot[
                    boot.meet.eq(meet) & boot.candidate.eq(candidate) & boot.metric.eq(metric)
                ].iloc[0]
                np.testing.assert_allclose(
                    [observed.ci_low, observed.ci_high],
                    np.quantile(values, [0.025, 0.975]),
                    atol=1e-12,
                )
    for filename, keys in [
        ("evaluation.csv", ["meet", "candidate"]),
        ("evaluation_by_year.csv", ["meet", "year", "candidate"]),
        ("evaluation_by_distance.csv", ["meet", "distance_m", "candidate"]),
    ]:
        table = pd.read_csv(out / filename)
        for row in table.to_dict("records"):
            f = loss[loss.year.ge(2024)]
            for key in keys:
                f = f[f[key].eq(row[key])]
            assert len(f) == row["races"]
            for metric in ["log_loss", "brier", "top3_precision"]:
                np.testing.assert_allclose(row[metric], f[metric].mean(), atol=1e-12)
    numbers = pd.read_csv(out / "number_profiles.csv")
    for _, f in numbers.groupby("window"):
        order = np.argsort(f.p.to_numpy())
        q = f.p.to_numpy()[order] * len(f) / np.arange(1, len(f) + 1)
        for i in range(len(q) - 2, -1, -1):
            q[i] = min(q[i], q[i + 1])
        expected_q = np.empty(len(f))
        expected_q[order] = np.minimum(q, 1)
        np.testing.assert_allclose(expected_q, f.q, atol=1e-12)
    for name, digest in audit["input_hashes"].items():
        assert study.sha(study.ROOT / name) == digest
    report = {
        "passed": True,
        "all_runner_predictions_checked": len(p),
        "all_race_probability_sums_checked": len(sums) * len(study.CANDIDATES),
        "independent_ability_fits": beta_checks,
        "independent_probability_projections": projection_checks,
        "independent_augmented_ridge_checks": recent_checks,
        "race_losses_checked_per_metric": sum(checks),
        "candidate_selection_venues_checked": len(selected),
        "paired_bootstrap_intervals_reproduced": len(boot),
        "number_bh_rows_checked": len(numbers),
        "source_hashes_unchanged": True,
        "current_day_excluded": True,
        "actual_current_position_not_a_predictor": True,
    }
    study.dump(out / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
