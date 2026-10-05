"""Race and horse adjusted associations between starting-number side and S1F time."""

from __future__ import annotations

import importlib.util
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import t

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "20261002_gate_lateral_bias"
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("bias", PREVIOUS / "analyze.py")
BIAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BIAS)
SECTIONS = BIAS.POSITION.SECTIONS
KEY = BIAS.POSITION.KEY
NUMERIC = BIAS.CONTROLS + ["prior_s1f_relative", "prior_course_s1f_relative"]


def source_times():
    s = pd.read_parquet(
        SECTIONS,
        columns=["meet", "race_date", "race_no", "horse_id", "horse_program_no", "time_ms"],
        filters=[
            ("meet", "in", [1, 3]),
            ("point_code", "=", "S1F"),
            ("measure_kind", "=", "cumulative_time"),
        ],
    )
    s["date"] = pd.to_datetime(s.race_date, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    s["s1f"] = s.time_ms / 1000
    assert not s.duplicated(KEY).any()
    return s


def histories(s):
    core = pd.read_parquet(BIAS.PRIOR / "outputs/core_runner_snapshot.parquet")
    names = {
        "source_meet": "meet",
        "result_date": "raw_date",
        "result_race_no": "race_no",
        "horse_id_raw": "horse_id",
        "race_distance_m_raw": "distance_m",
        "result_rank_raw": "rank",
    }
    core = core.rename(columns=names)
    for key in ["meet", "race_no", "distance_m", "rank"]:
        core[key] = pd.to_numeric(core[key], errors="coerce")
    core["date"] = pd.to_datetime(core.raw_date, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    h = core[KEY + ["distance_m", "rank"]].merge(
        s[KEY + ["s1f"]], on=KEY, how="left", validate="one_to_one"
    )
    h = h[h["rank"].between(1, 20) & h.s1f.between(10, 25)].copy()
    h["race_key"] = (
        h.meet.astype(int).astype(str) + ":" + h.date + ":" + h.race_no.astype(int).astype(str)
    )
    h["relative"] = h.s1f - h.groupby("race_key").s1f.transform("median")
    return h.sort_values(["date", "race_no", "horse_id"]).reset_index(drop=True)


def add_history(runners, h):
    general = defaultdict(lambda: deque(maxlen=5))
    course = defaultdict(lambda: deque(maxlen=5))
    last = {}
    runner_dates = {date: one for date, one in runners.groupby("date")}
    history_dates = {date: one for date, one in h.groupby("date")}
    rows = []
    for date in sorted(set(runner_dates) | set(history_dates)):
        if date in runner_dates:
            for row in runner_dates[date].itertuples():
                a, b = general[row.horse_id], course[(row.horse_id, row.meet, row.distance_m)]
                rows.append(
                    {
                        "index": row.Index,
                        "prior_s1f_relative": np.mean(a) if a else np.nan,
                        "prior_course_s1f_relative": np.mean(b) if b else np.nan,
                        "prior_s1f_n": len(a),
                        "last_s1f_date": last.get(row.horse_id),
                    }
                )
        if date in history_dates:
            for row in history_dates[date].itertuples():
                general[row.horse_id].append(row.relative)
                course[(row.horse_id, row.meet, row.distance_m)].append(row.relative)
                last[row.horse_id] = date
    features = pd.DataFrame(rows).set_index("index").reindex(runners.index)
    result = pd.concat([runners, features], axis=1)
    assert (result.last_s1f_date.isna() | result.last_s1f_date.lt(result.date)).all()
    return result


def design(frame, competition=False):
    vectors, labels = [], []
    groups = ["0-1", "2", "3+"] if competition else [None]
    for group in groups:
        for side in ["middle", "outer"]:
            v = frame.gate_side.eq(side).to_numpy(float)
            if group is not None:
                v *= frame.leader_group.eq(group).to_numpy(float)
            vectors.append(v)
            labels.append(f"gate:{group}:{side}")
    for key in NUMERIC:
        v = frame[key].to_numpy(float)
        missing = ~np.isfinite(v)
        median = float(np.median(v[~missing])) if (~missing).any() else 0
        v = np.where(missing, median, v)
        std = float(v.std())
        vectors.append((v - v.mean()) / (std if std > 1e-10 else 1))
        labels.append(key)
        if missing.any():
            vectors.append(missing.astype(float))
            labels.append(f"missing:{key}")
    return np.column_stack(vectors), labels


def absorb(values, race, horse, weights):
    nr, nh = int(race.max() + 1), int(horse.max() + 1)
    indices = np.arange(len(race))
    nuisance = sparse.coo_matrix(
        (np.ones(2 * len(race)), (np.tile(indices, 2), np.r_[race, nr + horse])),
        shape=(len(race), nr + nh),
    ).tocsr()
    weighted = nuisance.multiply(np.sqrt(weights[:, None])).tocsr()
    matrix, maximum_iterations = values.copy(), 0
    for j, v in enumerate(values.T):
        solved = lsmr(weighted, v * np.sqrt(weights), atol=1e-12, btol=1e-12, maxiter=20000)
        if solved[1] not in [0, 1, 2, 4, 5]:
            raise RuntimeError(f"Fixed-effect least squares did not converge: {solved[1]}")
        matrix[:, j] -= nuisance @ solved[0]
        maximum_iterations = max(maximum_iterations, solved[2])
    residual_scores = nuisance.T @ (matrix * weights[:, None])
    assert np.abs(residual_scores).max() < 1e-7
    return matrix, maximum_iterations


def fit(frame, horse_fe=False, competition=False):
    x, labels = design(frame, competition)
    race = pd.factorize(frame.race_key)[0]
    day = pd.factorize(frame.day_key)[0]
    nr, nd = int(race.max() + 1), int(day.max() + 1)
    n = len(frame)
    counts = np.bincount(race)
    weights = 1 / counts[race]
    if horse_fe:
        horse = pd.factorize(frame.horse_id)[0]
        matrix, iterations = absorb(np.column_stack([x, frame.s1f]), race, horse, weights)
        x, y = matrix[:, :-1], matrix[:, -1]
        # Conservative absorbed df upper bound when FE groups are disconnected.
        absorbed_df = nr + int(horse.max())
    else:
        x -= np.column_stack([np.bincount(race, weights=v)[race] / counts[race] for v in x.T])
        y = frame.s1f.to_numpy(float)
        y = y - np.bincount(race, weights=y)[race] / counts[race]
        iterations, absorbed_df = 1, nr
    xw, yw = x * np.sqrt(weights[:, None]), y * np.sqrt(weights)
    gram = xw.T @ xw
    inv = np.linalg.pinv(gram, rcond=1e-10)
    beta = inv @ (xw.T @ yw)
    projection = inv @ gram
    errors = yw - xw @ beta
    scores = xw * errors[:, None]
    sums = np.column_stack([np.bincount(day, weights=v, minlength=nd) for v in scores.T])
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    correction = nd / (nd - 1) * (n - 1) / max(n - absorbed_df - rank, 1)
    cov = inv @ (sums.T @ sums) @ inv * correction

    def contrast(vector):
        error = float(np.max(np.abs(vector - vector @ projection)))
        effect = float(vector @ beta)
        se = float(np.sqrt(max(0, vector @ cov @ vector)))
        cutoff = float(t.ppf(0.975, nd - 1))
        return {
            "estimable": error < 1e-6,
            "effect_seconds": effect,
            "ci95_seconds": [(effect - cutoff * se), (effect + cutoff * se)],
            "p": float(2 * t.sf(abs(effect / se), nd - 1)) if se > 1e-14 else 1,
            "projection_error": error,
        }

    rows = []
    for j in range(6 if competition else 2):
        vector = np.eye(len(beta))[j]
        rows.append({"contrast": labels[j], **contrast(vector)})
    if competition:
        for j, k in [(5, 1), (3, 1)]:
            vector = np.eye(len(beta))[j] - np.eye(len(beta))[k]
            rows.append({"contrast": f"{labels[j]} minus {labels[k]}", **contrast(vector)})
    return rows, {
        "columns": labels,
        "beta": beta.tolist(),
        "iterations": iterations,
        "rank": rank,
        "absorbed_df_upper_bound": absorbed_df,
    }


def supported(frame):
    return frame.race_key.nunique() >= 50 and frame.day_key.nunique() >= 20


def complete(frame, condition):
    ok = condition.groupby(frame.race_key).transform("all")
    return frame[ok].copy()


def raw_difference(frame):
    means = frame.groupby(["race_key", "gate_side"]).s1f.mean().unstack()
    return float((means.outer - means.inner).mean())


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
        PREVIOUS / "outputs/runners.parquet",
        SECTIONS,
        BIAS.PRIOR / "outputs/core_runner_snapshot.parquet",
        BIAS.PRIOR / "outputs/position_runners.parquet",
    ]
    hashes = {str(p): BIAS.sha(p) for p in paths}
    OUT.mkdir()
    runners = pd.read_parquet(paths[3])
    s = source_times()
    r = runners.merge(
        s[KEY + ["horse_program_no", "s1f"]].rename(columns={"horse_program_no": "s1f_number"}),
        on=KEY,
        how="left",
        validate="one_to_one",
    )
    observed = r.s1f_number.notna()
    assert r.loc[observed, "horse_number"].eq(r.loc[observed, "s1f_number"]).all()
    r = add_history(r, histories(s))
    population = complete(r, np.isfinite(r.s1f) & r.s1f.gt(0) & r.s1f.lt(r.finish))
    population["s1f_relative"] = population.s1f - population.groupby("race_key").s1f.transform(
        "median"
    )
    population["leader"] = population.prior_s1f_n.ge(3) & population.prior_early.le(0.20)
    population["leaders"] = population.groupby("race_key").leader.transform("sum")
    population["leader_group"] = np.where(
        population.leaders.le(1), "0-1", np.where(population.leaders.eq(2), "2", "3+")
    )
    population.to_parquet(OUT / "runners.parquet", index=False)
    median = population.groupby("race_key").s1f.transform("median")
    mad = (population.s1f - median).abs().groupby(population.race_key).transform("median")
    robust = complete(
        population, (population.s1f - median).abs().le(np.maximum(0.8, 4 * 1.4826 * mad))
    )
    samples = {
        "primary": population,
        "2024plus": population[population.year.ge(2024)],
        "no_extreme_delay": complete(population, population.s1f.between(10, 25)),
        "robust_races": robust,
        "experienced": complete(population, population.prior_s1f_n.ge(3)),
        "horse_fe": population,
    }
    results, diagnostics, competition_rows = [], [], []
    for name, sample in samples.items():
        for (meet, distance), one in sample[sample.distance_m.isin(BIAS.DISTANCES)].groupby(
            ["meet", "distance_m"]
        ):
            if not supported(one):
                continue
            fits, diagnostic = fit(one, horse_fe=name == "horse_fe")
            meta = {
                "scenario": name,
                "meet": int(meet),
                "distance_m": int(distance),
                "runners": len(one),
                "races": int(one.race_key.nunique()),
                "days": int(one.day_key.nunique()),
                "raw_outer_minus_inner_seconds": raw_difference(one),
                "mean_s1f": float(one.s1f.mean()),
            }
            results += [{**meta, **row} for row in fits]
            diagnostics.append({**meta, **diagnostic})
        print(f"Scenario {name} done", flush=True)
    experienced = samples["experienced"]
    for (meet, distance), one in experienced[experienced.distance_m.isin(BIAS.DISTANCES)].groupby(
        ["meet", "distance_m"]
    ):
        present = [g for g, cell in one.groupby("leader_group") if supported(cell)]
        if len(present) < 3:
            continue
        fits, diagnostic = fit(one, competition=True)
        for row in fits:
            group = row["contrast"].split(":")[1]
            cell = one[one.leader_group.eq(group)] if " minus " not in row["contrast"] else one
            competition_rows.append(
                {
                    "meet": int(meet),
                    "distance_m": int(distance),
                    "races": int(cell.race_key.nunique()),
                    "days": int(cell.day_key.nunique()),
                    **row,
                }
            )
        diagnostics.append(
            {
                "scenario": "competition",
                "meet": int(meet),
                "distance_m": int(distance),
                **diagnostic,
            }
        )
    for family, select in [
        (results, lambda r: r["scenario"] == "primary" and r["contrast"] == "gate:None:outer"),
        (competition_rows, lambda r: "gate:3+:outer minus" in r["contrast"]),
    ]:
        eligible = [row for row in family if select(row) and row["estimable"]]
        for row, q in zip(eligible, BIAS.POSITION.bh([row["p"] for row in eligible]), strict=True):
            row["q"] = float(q)
    pd.DataFrame(results).to_csv(OUT / "effects.csv", index=False)
    pd.DataFrame(competition_rows).to_csv(OUT / "competition_effects.csv", index=False)
    roles = pd.read_parquet(paths[6])
    roles = roles[roles.point.eq("S1F")][KEY + ["role", "pack_index", "pack_relative"]]
    merged = population.merge(roles, on=KEY, how="left", validate="one_to_one")
    role_table = (
        merged.groupby(["meet", "distance_m", "role", "gate_side"])
        .agg(
            runners=("horse_id", "size"),
            races=("race_key", "nunique"),
            mean_s1f=("s1f", "mean"),
            mean_relative_s1f=("s1f_relative", "mean"),
            mean_prior_relative_s1f=("prior_s1f_relative", "mean"),
            mean_finish_pct=("finish_pct", "mean"),
            top3_rate=("top3", "mean"),
        )
        .reset_index()
    )
    role_table.to_csv(OUT / "observed_s1f_roles.csv", index=False)
    summary = {
        "inputs_sha256": hashes,
        "source_runners": len(runners),
        "source_races": int(runners.race_key.nunique()),
        "analysis_runners": len(population),
        "analysis_races": int(population.race_key.nunique()),
        "excluded_incomplete_races": sorted(set(runners.race_key) - set(population.race_key)),
        "history_coverage": population.groupby("meet")
        .agg(
            runners=("horse_id", "size"),
            any_history=("prior_s1f_n", lambda x: int(x.gt(0).sum())),
            history3=("prior_s1f_n", lambda x: int(x.ge(3).sum())),
        )
        .reset_index()
        .to_dict("records"),
        "scenarios": {
            name: {"runners": len(one), "races": int(one.race_key.nunique())}
            for name, one in samples.items()
        },
        "primary_effects": [
            row
            for row in results
            if row["scenario"] == "primary" and row["contrast"] == "gate:None:outer"
        ],
        "competition_effects": competition_rows,
        "role_missing_runners": int(merged.role.isna().sum()),
        "first_date": population.date.min(),
        "last_date": population.date.max(),
        "inputs_unchanged": True,
    }
    assert hashes == {str(p): BIAS.sha(p) for p in paths}
    (OUT / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary["primary_effects"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
