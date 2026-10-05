"""Independent weight arithmetic, history boundaries, metrics and source verification."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    d = pd.read_parquet(OUT / "weight_population.parquet")
    assert len(d) == 41623 and not d.row_key.duplicated().any()
    valid = d[d.weight_status.eq("valid")]
    # Parse only the mass prefix independently of the analysis's full-format regex.
    raw_mass = d.body_raw.str.split("(", regex=False).str[0].str.strip().astype(float)
    assert np.allclose(raw_mass, d.body_kg, equal_nan=True)
    assert np.allclose(d.weight_raw, d.weight)
    assert np.allclose(valid.total_kg, valid.body_kg + valid.weight)
    assert np.allclose(
        valid.load_share_pct, 100 / (1 + valid.body_kg / valid.weight), atol=1e-12, rtol=0
    )
    assert np.allclose(
        valid.load_share_pct,
        100 * valid.body_load_pct / (100 + valid.body_load_pct),
        atol=1e-12,
        rtol=0,
    )
    history_checks = 0
    for _horse, a in d.sort_values(["horse_id", "date"]).groupby("horse_id", sort=False):
        last_body, last_date = None, None
        for row in a.itertuples():
            if last_body is None:
                assert pd.isna(row.prior_body_kg) and pd.isna(row.prior_body_date)
            else:
                assert abs(last_body - row.prior_body_kg) < 1e-10
                assert last_date == row.prior_body_date and last_date < row.date
                assert (
                    abs(row.prior_load_share_pct - 100 * row.weight / (last_body + row.weight))
                    < 1e-10
                )
            if row.weight_status == "valid":
                last_body, last_date = row.body_kg, row.date
            history_checks += 1
    pred = pd.read_parquet(OUT / "prediction_rows.parquet")
    assert len(pred) == len(valid[valid.year.ge(2024)]) and not pred.row_key.duplicated().any()
    for date_col in ["prior_body_date", "history1200_last_date"]:
        known = pred[date_col].notna()
        assert (pred.loc[known, date_col] < pred.loc[known, "date"]).all()
    metrics = pd.read_csv(OUT / "prediction_metrics.csv")
    contrasts = pd.read_csv(OUT / "paired_comparisons.csv")
    metric_checks = 0
    for row in metrics.itertuples():
        a = pred[pred.meet.eq(row.meet)]
        if row.year:
            a = a[a.year.eq(row.year)]
            assert pd.Timestamp(row.train_max) < pd.Timestamp(row.test_min)
        assert len(a) == row.n
        error = abs(a["pred_" + row.model] - a.finish)
        assert np.allclose(error, a["err_" + row.model])
        race = error.groupby(a.source_key).mean()
        assert len(race) == row.races and abs(race.mean() - row.mae_seconds) < 1e-10
        metric_checks += 1
    for row in contrasts.itertuples():
        a = pred[pred.meet.eq(row.meet)]
        if row.year:
            a = a[a.year.eq(row.year)]
        errors = a.groupby("source_key")[["err_" + row.model, "err_" + row.baseline]].mean()
        assert abs((errors.iloc[:, 0] - errors.iloc[:, 1]).mean() - row.delta_seconds) < 1e-10
        assert row.ci_low <= row.ci_high
    old = pd.read_parquet(
        HERE.parent / "20261004_relative_speed_par_v1/outputs/history_prediction_rows.parquet"
    )
    replay = pred.merge(
        old[["row_key", "baseline", "with_relative_history"]], on="row_key", validate="one_to_one"
    )
    # When the mass fields are complete, the unchanged baseline must reproduce the previous study.
    baseline_replay = False
    if len(valid) == len(d):
        assert len(replay) == 13313
        assert np.allclose(replay.pred_absolute, replay.baseline, atol=1e-8, rtol=0)
        assert np.allclose(replay.pred_absolute_rs, replay.with_relative_history, atol=1e-8, rtol=0)
        baseline_replay = True
    summary = json.loads((OUT / "summary.json").read_text())
    for entry in summary["source_hashes"] + summary["input_hashes"] + summary["reused_code_hashes"]:
        assert sha(ROOT / entry["path"]) == entry["sha256"]
    report = dict(
        status="passed",
        runners=len(d),
        valid_weight_runners=len(valid),
        raw_weight_pairs=len(d),
        history_boundaries=history_checks,
        forecast_rows=len(pred),
        metric_rows=metric_checks,
        comparison_rows=len(contrasts),
        previous_baseline_reproduced=baseline_replay,
        input_hashes_unchanged=True,
        mismatches=0,
    )
    (OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
