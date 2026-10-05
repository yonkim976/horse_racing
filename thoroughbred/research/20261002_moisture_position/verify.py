"""Independent aggregation, history and race-within regression checks."""

from __future__ import annotations

import json

import analyze as study
import numpy as np
import pandas as pd


def main():
    saved = json.loads((study.OUT / "summary.json").read_text())
    for path, digest in saved["inputs_sha256"].items():
        assert study.sha(study.ROOT / path) == digest
    frame = pd.read_parquet(study.OUT / "position_runners.parquet")
    assert not frame.duplicated(study.KEY + ["point"]).any()
    grouped = frame.groupby(["race_key", "point"])
    assert grouped.win.sum().eq(1).all()
    assert grouped.top3.sum().eq(3).all()
    assert grouped.horse_id.size().eq(grouped.n.first()).all()
    assert grouped.apply(
        lambda g: sorted(g["rank"].astype(int)) == list(range(1, len(g) + 1)), include_groups=False
    ).all()
    assert grouped.apply(
        lambda g: int(g.role.eq("solo").sum()) in (0, 1), include_groups=False
    ).all()
    assert (frame.last_history_date.isna() | frame.last_history_date.lt(frame.dt)).all()
    cells = pd.read_csv(study.OUT / "raw_position_cells.csv")
    fresh = study.raw_cells(frame)
    for column in ["runners", "races", "days", "win_rate", "top3_rate"]:
        assert np.allclose(cells[column], fresh[column])
    # Independently recompute 30 dated prior Top3 averages from the source rows,
    # across both venues, ignoring current and same-date results.
    source = pd.read_parquet(study.OUT / "core_runner_snapshot.parquet")
    source["date"] = pd.to_datetime(source.result_date, format="%Y%m%d")
    source["rank"] = pd.to_numeric(source.result_rank_raw)
    source["finish"] = pd.to_numeric(source.finish_time_seconds_raw)
    prior_checks = 0
    sample = frame[frame.point.eq("S1F")].sample(30, random_state=20261002)
    for row in sample.itertuples():
        past = source[
            (source.horse_id_raw == row.horse_id)
            & (source.date < row.dt)
            & source["rank"].between(1, 20)
            & source.finish.gt(0)
        ]
        past = past.sort_values(["date", "result_race_no", "source_meet"]).tail(5)
        expected = float(past["rank"].le(3).mean()) if len(past) else np.nan
        assert np.isclose(expected, row.prior_top3, equal_nan=True)
        prior_checks += 1
    # Invariance to group members' inner/outer order: membership, size and front
    # group are unchanged. Do not interpret that order as longitudinal rank.
    a, b = study.parse("(3,^1,2),4-5=6"), study.parse("(2,3,^1),4-5=6")
    assert [set(g["members"]) for g in a] == [set(g["members"]) for g in b]
    study.check_parser()
    # Check a fitted 1200m cell using a separately expressed weighted within fit,
    # and verify race-constant changes to the design do not affect coefficients.
    one = frame[frame.meet.eq(1) & frame.point.eq("S1F") & frame.distance_m.eq(1200)].copy()
    x, labels = study.design(one, 1200)
    beta, _, projection, _, _ = study.cluster_fit(one, x)
    race = pd.factorize(one.race_key)[0]
    counts = np.bincount(race)
    means = np.column_stack([np.bincount(race, weights=v)[race] / counts[race] for v in x.T])
    xw = (x - means) / np.sqrt(counts[race])[:, None]
    y = one.top3.to_numpy(float)
    yw = (y - np.bincount(race, weights=y)[race] / counts[race]) / np.sqrt(counts[race])
    direct = np.linalg.lstsq(xw, yw, rcond=1e-5)[0]
    vector = np.zeros(len(labels))
    vector[labels.index("interaction:leading_pack:포화")] = 1
    assert np.max(np.abs(vector - vector @ projection)) < 1e-6
    assert np.isclose(vector @ direct, vector @ beta, atol=1e-8)
    modified = x + (race % 7)[:, None] * 0.03
    changed, _, _, _, _ = study.cluster_fit(one, modified)
    assert np.isclose(vector @ changed, vector @ beta, atol=1e-8)
    family = [r for r in saved["modes"]["primary"]["rows"] if "q" in r]
    qvalues = study.bh([r["change"]["p"] for r in family])
    assert np.allclose(qvalues, [r["q"] for r in family])
    report = {
        "passed": True,
        "input_hashes_match": True,
        "complete_rankings_and_rosters": True,
        "one_win_three_top3_per_race_point": True,
        "raw_aggregates_reproduced": True,
        "independent_prior_history_checks": prior_checks,
        "within_pack_member_order_not_used_as_rank": True,
        "weighted_within_regression_contrast_reproduced": True,
        "race_constant_design_invariance": True,
        "multiple_comparison_tests": len(family),
        "q_below_005": sum(r["q"] < 0.05 for r in family),
    }
    (study.OUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
