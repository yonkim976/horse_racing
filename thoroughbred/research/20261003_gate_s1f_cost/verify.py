"""Independent source, chronology and weighted least-squares checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import false_discovery_control, t

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("analysis", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def matrix(frame):
    arrays = [frame.gate_side.eq(side).to_numpy(float) for side in ["middle", "outer"]]
    for key in A.NUMERIC:
        v = frame[key].to_numpy(float)
        missing = ~np.isfinite(v)
        clean = np.where(missing, np.nanmedian(v) if (~missing).any() else 0, v)
        sd = clean.std()
        arrays.append((clean - clean.mean()) / (sd if sd > 1e-10 else 1))
        if missing.any():
            arrays.append(missing.astype(float))
    return np.column_stack(arrays)


def check_primary(one, expected):
    x = pd.DataFrame(matrix(one), index=one.index)
    within_x = x - x.groupby(one.race_key).transform("mean")
    within_y = one.s1f - one.groupby("race_key").s1f.transform("mean")
    weights = 1 / one.groupby("race_key").race_key.transform("size")
    xw = within_x.to_numpy() * np.sqrt(weights.to_numpy()[:, None])
    yw = within_y.to_numpy() * np.sqrt(weights.to_numpy())
    beta, _, _, _ = np.linalg.lstsq(xw, yw, rcond=1e-5)
    score = pd.DataFrame(xw * (yw - xw @ beta)[:, None], index=one.index)
    grouped = score.groupby(one.day_key).sum().to_numpy()
    rank = int(np.linalg.matrix_rank(xw, tol=1e-4))
    days, races, n = one.day_key.nunique(), one.race_key.nunique(), len(one)
    bread = np.linalg.pinv(xw.T @ xw, rcond=1e-10)
    covariance = bread @ (grouped.T @ grouped) @ bread
    covariance *= days / (days - 1) * (n - 1) / (n - races - rank)
    se = np.sqrt(covariance[1, 1])
    interval = beta[1] + np.array([-1, 1]) * t.ppf(0.975, days - 1) * se
    assert np.isclose(beta[1], expected.effect_seconds, atol=1e-8, rtol=0)
    assert np.allclose(interval, json.loads(expected.ci95_seconds), atol=1e-8, rtol=0)
    raw = one.groupby(["race_key", "gate_side"]).s1f.mean().unstack()
    assert np.isclose((raw.outer - raw.inner).mean(), expected.raw_outer_minus_inner_seconds)
    return float(beta[1])


def check_horse(one, expected):
    x = matrix(one)
    race, _ = pd.factorize(one.race_key)
    horse, _ = pd.factorize(one.horse_id)
    nr, nh, n = race.max() + 1, horse.max() + 1, len(one)
    indices = np.arange(n)
    fe = sparse.coo_matrix(
        (np.ones(2 * n), (np.tile(indices, 2), np.r_[race, nr + horse])), shape=(n, nr + nh)
    ).tocsr()
    full = sparse.hstack([sparse.csr_matrix(x), fe], format="csr")
    w = 1 / np.bincount(race)[race]
    solved = lsmr(
        full.multiply(np.sqrt(w[:, None])),
        one.s1f.to_numpy() * np.sqrt(w),
        atol=1e-12,
        btol=1e-12,
        maxiter=20000,
    )
    assert solved[1] in [1, 2, 4, 5]
    assert np.isclose(solved[0][1], expected.effect_seconds, atol=2e-6, rtol=0)
    return {
        "meet": int(expected.meet),
        "distance_m": int(expected.distance_m),
        "direct_sparse_effect_seconds": float(solved[0][1]),
        "iterations": solved[2],
    }


def main():
    summary = json.loads((A.OUT / "summary.json").read_text())
    r = pd.read_parquet(A.OUT / "runners.parquet")
    effects = pd.read_csv(A.OUT / "effects.csv")
    assert summary["inputs_sha256"] == {p: A.BIAS.sha(Path(p)) for p in summary["inputs_sha256"]}
    source = A.source_times()
    observed = r[A.KEY + ["s1f", "horse_number"]].merge(
        source[A.KEY + ["time_ms", "horse_program_no"]], on=A.KEY, validate="one_to_one"
    )
    assert np.allclose(observed.s1f * 1000, observed.time_ms)
    assert observed.horse_number.eq(observed.horse_program_no).all()
    assert (r.groupby("race_key").size() == r.groupby("race_key").n.first()).all()
    assert not r.duplicated(A.KEY).any()
    assert (r.last_s1f_date.isna() | r.last_s1f_date.lt(r.date)).all()
    percentile = (r.groupby("race_key").horse_number.rank() - 0.5) / r.n
    side = np.where(
        percentile.le(1 / 3), "inner", np.where(percentile.le(2 / 3), "middle", "outer")
    )
    assert np.array_equal(side, r.gate_side)
    history = A.histories(source)
    histories = {horse: one for horse, one in history.groupby("horse_id")}
    selected = r.sample(1000, random_state=20261003)
    for row in selected.itertuples():
        h = histories.get(row.horse_id, history.iloc[:0])
        prior = h[h.date.lt(row.date)]
        last5 = prior.tail(5)
        same = prior[prior.meet.eq(row.meet) & prior.distance_m.eq(row.distance_m)].tail(5)
        assert len(last5) == row.prior_s1f_n
        assert np.isclose(last5.relative.mean(), row.prior_s1f_relative, equal_nan=True)
        assert np.isclose(same.relative.mean(), row.prior_course_s1f_relative, equal_nan=True)
        if len(prior):
            assert prior.date.max() == row.last_s1f_date
        else:
            assert pd.isna(row.last_s1f_date)
    primary = effects[effects.scenario.eq("primary") & effects.contrast.eq("gate:None:outer")]
    checked = []
    for row in primary.itertuples():
        one = r[r.meet.eq(row.meet) & r.distance_m.eq(row.distance_m)]
        checked.append(
            {
                "meet": int(row.meet),
                "distance_m": int(row.distance_m),
                "independent_effect_seconds": check_primary(one, row),
            }
        )
    assert np.allclose(primary.q, false_discovery_control(primary.p.to_numpy(), method="bh"))
    horse_checks = []
    for meet, distance in [(1, 1200), (3, 1200), (3, 1600)]:
        row = effects[
            effects.scenario.eq("horse_fe")
            & effects.contrast.eq("gate:None:outer")
            & effects.meet.eq(meet)
            & effects.distance_m.eq(distance)
        ].iloc[0]
        horse_checks.append(check_horse(r[r.meet.eq(meet) & r.distance_m.eq(distance)], row))
    competition = pd.read_csv(A.OUT / "competition_effects.csv")
    changes = competition[competition.contrast.str.contains("gate:3+:outer minus", regex=False)]
    assert np.allclose(changes.q, false_discovery_control(changes.p.to_numpy(), method="bh"))
    output = {
        "status": "passed",
        "inputs_unchanged": True,
        "source_s1f_and_numbers_checked": len(r),
        "complete_race_rosters_checked": int(r.race_key.nunique()),
        "strict_prior_features_sample": 1000,
        "independent_primary_lstsq": checked,
        "independent_two_way_sparse_lstsq": horse_checks,
        "primary_and_competition_BH_checked": True,
    }
    (A.OUT / "verification.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
