"""Independent enumeration, frozen model replay and bootstrap checks."""

import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e
from scipy.special import softmax


def categorical(frame, meta):
    x = frame[meta["features"]].copy()
    for col, levels in meta.get("category_vocabulary", meta.get("vocabulary", {})).items():
        values = x[col].where(x[col].isin(levels))
        x[col] = pd.Categorical(values, categories=levels)
    return x


def replay(runners):
    source = {
        "month_gate_weight22": pd.read_parquet(e.W / "features_month_gate_weight22.parquet"),
        "style_history53": pd.read_parquet(e.S / "features.parquet"),
    }
    checks = []
    for (model, year, meet), g in runners.groupby(["model", "year", "meet"]):
        if model == "month_gate_weight22":
            folder = e.W / "models" / f"{meet}_{year}_month_gate_weight22"
            path, meta_path = folder / "top3.txt", folder / "metadata.json"
        elif year >= 2024:
            folder = e.S / "finish_models" / f"3_style_history_{meet}_{year}"
            path, meta_path = folder / "model.txt", folder / "metadata.json"
        else:
            folder = e.P / "base_models" / f"{meet}_{year}"
            path, meta_path = folder / "model.txt", folder / "meta.json"
        meta = json.loads(meta_path.read_text())
        assert e.sha(path) == meta["model_sha256"]
        if "train_end" in meta:
            assert pd.Timestamp(meta["train_end"]).year <= year - 2
            assert meta["calibration_year"] == year - 1
        else:
            assert (
                meta["refit_max"]
                < meta["calibration_min"]
                <= meta["calibration_max"]
                < meta["evaluation_min"]
            )
        f = source[model]
        f = f[(f.year == year) & (f.meet == meet)].copy()
        f.horse_id = f.horse_id.astype(str)
        aligned = g[e.KEY + ["score", "tau"]].merge(f, on=e.KEY, validate="one_to_one")
        assert len(aligned) == len(g)
        x = categorical(aligned, meta)
        prediction = lgb.Booster(model_file=str(path)).predict(x, raw_score=True, num_threads=4)
        error = float(abs(prediction - aligned.score).max())
        assert error < 1e-12
        tau = meta.get("temperature", meta.get("tau"))
        assert np.allclose(aligned.tau, tau, atol=0, rtol=0)
        checks.append(dict(model=model, year=int(year), meet=int(meet), max_error=error))
    return checks


def verify_tickets(runners, races, tickets):
    all_lookup = {
        (m, p, k): g.sort_values("program_no")
        for (m, p, k), g in runners.groupby(["model", "period", "race_key"])
    }
    saved = {
        (m, p, k, pol): g
        for (m, p, k, pol), g in tickets.groupby(["model", "period", "race_key", "policy"])
    }
    metrics = races.set_index(["model", "period", "race_key", "policy"])
    n_checks = 0
    poison_checks = 0
    for pos, ((model, period, key), g) in enumerate(all_lookup.items()):
        values = {int(z.program_no): float(z.score / z.tau) for z in g.itertuples()}
        ordered = sorted(values, key=lambda n: (-values[n], n))
        axis = ordered[0]
        combos = list(itertools.combinations(sorted(values), 3))
        energy = [sum(sorted(values[n] for n in triple)) for triple in combos]
        probabilities = softmax(np.array(energy))
        distribution = dict(zip(combos, probabilities, strict=True))
        axis_probability = sum(prob for triple, prob in distribution.items() if axis in triple)
        truth = tuple(sorted(g[g.outcome.between(1, 3)].program_no.astype(int)))
        assert len(truth) == 3
        for policy in e.POLICIES:
            if policy == "global6":
                possible = combos
            elif policy == "axis_all":
                possible = [triple for triple in combos if axis in triple]
            else:
                top = set(ordered[: int(policy.removeprefix("axis_pool"))])
                possible = [triple for triple in combos if axis in triple and set(triple) <= top]
            chosen = sorted(possible, key=lambda t: (-sum(sorted(values[n] for n in t)), t))[:6]
            table = saved[(model, period, key, policy)].sort_values("selection_rank")
            actual = [tuple(map(int, z.split(","))) for z in table.programs]
            assert actual == chosen, (key, policy)
            expected = np.array([distribution[t] for t in chosen])
            assert np.allclose(expected, table.probability, atol=1e-12, rtol=0)
            metric = metrics.loc[(model, period, key, policy)]
            assert metric.six_hit == int(truth in chosen)
            assert metric.axis_placed == int(axis in truth)
            assert metric.pool_contains_truth == int(truth in possible)
            assert abs(metric.p_axis - axis_probability) < 1e-12
            assert abs(metric.six_probability - expected.sum()) < 1e-12
            assert abs(metric.set_nll + np.log(distribution[truth])) < 1e-12
            n_checks += 1
        if pos % 100 == 0:
            first = e.card(g.drop(columns="outcome"))
            second = e.card(g.sample(frac=1, random_state=42).assign(outcome=99))
            assert all(np.array_equal(first[6][pol], second[6][pol]) for pol in e.POLICIES)
            assert np.array_equal(first[4], second[4])
            poison_checks += 1
    assert len(tickets) == n_checks * 6
    return dict(
        race_policies=n_checks,
        ticket_rows=len(tickets),
        outcome_removed_and_shuffled_cards=poison_checks,
    )


def verify_intervals(races):
    recorded = pd.read_csv(e.OUT / "paired_differences.csv")
    scoped = races.copy()
    scoped["distance_band"] = np.select(
        [scoped.distance_m.le(1300), scoped.distance_m.le(1600)],
        ["through1300", "1400_1600"],
        default="1700plus",
    )
    scoped["grade_band"] = np.select(
        [scoped.grade.eq(6), scoped.grade.eq(5), scoped.grade.between(1, 4)],
        ["grade6", "grade5", "grade1_4"],
        default="unknown",
    )
    scoped["field_band"] = np.select(
        [scoped.field_size.le(9), scoped.field_size.le(11)], ["6_9", "10_11"], default="12plus"
    )
    scoped["history_band"] = np.select(
        [scoped.minimum_history.eq(0), scoped.minimum_history.lt(5)],
        ["any_zero", "min1_4"],
        default="all5plus",
    )
    max_error = 0
    for z in recorded.itertuples():
        data = scoped[(scoped.model == z.model) & (scoped.period == z.period)]
        if z.scope != "all":
            data = data[data[z.scope].astype(str) == str(z.value)]
        a = data[data.policy == z.policy].set_index("race_key").sort_index()
        b = data[data.policy == z.baseline].set_index("race_key").loc[a.index]
        if z.metric == "companion_given_axis":
            keep = a.axis_placed.eq(1)
            a, b = a[keep], b[keep]
        delta = a.six_hit - b.six_hit
        daily = (
            pd.DataFrame({"date": a.race_date, "delta": delta})
            .groupby("date")
            .delta.agg(["sum", "size"])
        )
        ix = np.random.default_rng(e.CFG["bootstrap_seed"]).integers(
            0, len(daily), size=(e.CFG["bootstrap_draws"], len(daily))
        )
        boot = daily["sum"].to_numpy()[ix].sum(axis=1) / daily["size"].to_numpy()[ix].sum(axis=1)
        expected = np.array([delta.mean(), *np.quantile(boot, [0.025, 0.975])])
        observed = np.array([z.mean, z.lo, z.hi])
        err = float(abs(expected - observed).max())
        assert err < 1e-12
        max_error = max(err, max_error)
    return dict(comparisons=len(recorded), max_error=max_error)


def legacy(races, tickets):
    previous = pd.read_csv(e.P / "race_metrics.csv")
    previous = previous[
        previous.policy.isin(
            ["fixed_axis_next4_all6", "sum_score_pool6_best6", "sum_score_pool7_best6"]
        )
    ]
    policies = {
        "fixed_axis_next4_all6": "axis_pool5",
        "sum_score_pool6_best6": "axis_pool6",
        "sum_score_pool7_best6": "axis_pool7",
    }
    previous["new_policy"] = previous.policy.map(policies)
    new = races[(races.model == "style_history53") & (races.period == "development_2024_2026")]
    z = previous.merge(
        new, left_on=["rid", "new_policy"], right_on=["race_key", "policy"], validate="one_to_one"
    )
    assert len(z) == 4799 * 3
    assert np.array_equal(z.six_hit_x, z.six_hit_y)
    assert np.allclose(z.selected_joint_probability, z.six_probability, atol=1e-12, rtol=0)
    # Original unconstrained22-feature recommendations must also replay exactly.
    old = pd.read_parquet(e.W / "recommendations.parquet")
    old = old[old.variant == "month_gate_weight22"]
    new = tickets[(tickets.model == "month_gate_weight22") & (tickets.policy == "global6")]
    aligned = new.merge(
        old, on=["race_key", "selection_rank"], validate="one_to_one", suffixes=("", "_old")
    )
    assert len(aligned) == 4799 * 6
    assert aligned.programs.eq(aligned.programs_old).all()
    assert np.allclose(aligned.probability, aligned.probability_old, atol=1e-12, rtol=0)
    assert aligned.hit.eq(aligned.hit_old).all()
    return dict(previous_axis_policies=4799 * 3, original_global6_tickets=len(aligned))


def main():
    e.check()
    done = json.loads((e.OUT / "completion.json").read_text())
    for name, expected in done["artifact_hashes"].items():
        assert e.sha(e.OUT / name) == expected
    runners = pd.read_parquet(e.OUT / "runner_inputs.parquet")
    races = pd.read_csv(e.OUT / "race_metrics.csv")
    tickets = pd.read_parquet(e.OUT / "six_tickets.parquet")
    assert not tickets.duplicated(["model", "period", "race_key", "policy", "programs"]).any()
    assert tickets.groupby(["model", "period", "race_key", "policy"]).size().eq(6).all()
    replayed = replay(runners)
    print("Frozen model replays", len(replayed), flush=True)
    rebuilt = verify_tickets(runners, races, tickets)
    print("Independent ticket reconstruction", rebuilt, flush=True)
    stats = verify_intervals(races)
    old = legacy(races, tickets)
    assert races.groupby(["model", "period", "race_key"]).axis_program.nunique().eq(1).all()
    assert races.groupby(["model", "period", "race_key"]).set_nll.nunique().eq(1).all()
    assert (races.six_probability.between(0, 1)).all()
    # Enlarging candidate pools cannot reduce selected probability in the same model.
    mass = races.pivot(
        index=["model", "period", "race_key"], columns="policy", values="six_probability"
    )
    for a, b in [
        ("axis_pool5", "axis_pool6"),
        ("axis_pool6", "axis_pool7"),
        ("axis_pool7", "axis_all"),
        ("axis_all", "global6"),
    ]:
        assert (mass[b] + 1e-14 >= mass[a]).all()
    matched = pd.read_csv(e.OUT / "operating_matched_metrics.csv")
    assert matched.groupby(["model", "policy"]).size().eq(1258).all()
    assert matched.groupby(["model", "policy"]).operating_hit.sum().eq(384).all()
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            passed=True,
            frozen_model_replays=replayed,
            independent_tickets=rebuilt,
            paired_statistics=stats,
            original_predictions_reproduced=old,
            input_and_registry_unchanged=True,
            new_model_fits=0,
            new_calibrations=0,
            jeju_accessed=False,
            database_opened=False,
            production_changed=False,
        ),
    )
    print("Verification passed", flush=True)


if __name__ == "__main__":
    main()
