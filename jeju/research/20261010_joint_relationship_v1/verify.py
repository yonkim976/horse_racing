"""Independent, outcome-free verification of the locked structural preflight."""
from __future__ import annotations

from itertools import combinations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
OUT = HERE / "outputs"
PLAN_SHA = "e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3"
FOLDS = (2024, 2025, 2026)
EXPECTED = {"races": 1779, "runner_rows": 17412, "race_days": 269}
TOL = 1e-10


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def verify_locked_files(source_lock: dict) -> dict:
    checks = {}
    for relative, entry in source_lock["sources"].items():
        path = ROOT / relative
        actual = digest(path)
        if actual != entry["sha256"]:
            raise AssertionError(f"locked source changed: {relative}")
        declarations = entry.get("verified_references", [])
        for declaration in declarations:
            if declaration["sha256"] != actual:
                raise AssertionError(f"declared frozen hash differs for {relative}")
        checks[relative] = actual
    return checks


def verify_finish_ranks(frame: pd.DataFrame) -> tuple[int, int, set[str]]:
    races = 0
    rows = 0
    dates = set()
    for race_id, group in frame.groupby("race_id", sort=True, observed=True):
        n = len(group)
        if n < 5 or math.comb(n, 3) < 6:
            raise AssertionError(f"unsupported full field at {race_id}, N={n}")
        if group.horse_id.nunique() != n or group.horse_number.nunique() != n:
            raise AssertionError(f"duplicate roster identity at {race_id}")
        if not np.array_equal(np.sort(group.finish_position.to_numpy(int)), np.arange(1, n + 1)):
            raise AssertionError(f"finish ranks are not a unique complete 1..N at {race_id}")
        if set(group.loc[group.finish_position.le(3), "finish_position"].tolist()) != {1, 2, 3}:
            raise AssertionError(f"top-three labels are not exactly 1,2,3 at {race_id}")
        if group.field_n.nunique() != 1 or int(group.field_n.iloc[0]) != n:
            raise AssertionError(f"field_n does not match roster at {race_id}")
        races += 1
        rows += n
        dates.add(pd.Timestamp(group.race_date.iloc[0]).strftime("%Y-%m-%d"))
    return races, rows, dates


def verify_history_cutoff(frame: pd.DataFrame) -> dict:
    race_date = pd.to_datetime(frame.race_date, errors="raise").dt.normalize()
    cutoff = pd.to_datetime(frame.history_cutoff, errors="raise").dt.normalize()
    latest = pd.to_datetime(frame.latest_history_date, errors="raise").dt.normalize()
    if not cutoff.equals(race_date - pd.Timedelta(days=2)):
        raise AssertionError("history_cutoff != race_date - 2 days")
    nonnull = latest.notna()
    if (nonnull & latest.gt(cutoff)).any():
        raise AssertionError("latest_history_date exceeds history_cutoff")
    return {"rows": int(len(frame)), "nonnull_latest_history_rows": int(nonnull.sum()),
            "null_latest_history_rows_preserved": int((~nonnull).sum()),
            "future_latest_history_violations": 0}


def verify_baseline_six(eval_frames: list[pd.DataFrame]) -> dict:
    saved = pd.read_csv(STYLE_OUT / "report/canonical_six_combinations.csv",
                        dtype={"race_id": "string", "numbers": "string"})
    saved = saved.loc[saved.variant.eq("F1_STYLE6"), ["race_id", "selection_rank", "numbers"]]
    saved["selection_rank"] = saved.selection_rank.astype(int)
    saved = saved.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    actual = []
    for frame in eval_frames:
        for race_id, group in frame.groupby("race_id", sort=True, observed=True):
            group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
            numbers = group.horse_number.to_numpy(int)
            triples = list(combinations(range(len(group)), 3))
            score = group.score.to_numpy(float)
            energy = np.asarray([np.sort(score[list(t)]).sum() for t in triples])
            order = np.argsort(-energy, kind="stable")[:6]
            for rank, index in enumerate(order, 1):
                ticket = ",".join(str(int(n)) for n in sorted(numbers[list(triples[index])]))
                actual.append({"race_id": str(race_id), "selection_rank": rank, "numbers": ticket})
    recreated = pd.DataFrame(actual).astype(
        {"race_id": "string", "selection_rank": "int64", "numbers": "string"})
    recreated = recreated.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    if len(saved) != EXPECTED["races"] * 6 or not recreated.equals(saved.astype(
            {"race_id": "string", "selection_rank": "int64", "numbers": "string"})):
        raise AssertionError("independent frozen baseline-six parity check failed")
    return {"passed": True, "rows": int(len(saved)),
            "fields": ["race_id", "selection_rank", "numbers"]}


def verify_saved_style_runner(eval_frames: list[pd.DataFrame]) -> dict:
    saved = pd.read_parquet(STYLE_OUT / "report/runner_predictions.parquet")
    required = {"api_record_id", "race_id", "variant", "p_top3", "y"}
    if not required.issubset(saved.columns):
        raise AssertionError("saved style runner output schema is incomplete")
    style = saved.loc[saved.variant.eq("F1_STYLE6")].copy()
    expected_ids = set(pd.concat([frame.api_record_id.astype("int64") for frame in eval_frames]))
    if len(style) != EXPECTED["runner_rows"] or style.api_record_id.duplicated().any():
        raise AssertionError("saved F1_STYLE6 runner output has invalid row count/IDs")
    if set(style.api_record_id.astype("int64")) != expected_ids:
        raise AssertionError("saved F1_STYLE6 runner output key coverage differs")
    p = pd.to_numeric(style.p_top3, errors="raise").to_numpy(float)
    y = pd.to_numeric(style.y, errors="raise").to_numpy(float)
    if not np.isfinite(p).all() or (p < 0).any() or (p > 1).any() or not np.isin(y, [0, 1]).all():
        raise AssertionError("saved F1_STYLE6 runner probabilities or labels are invalid")
    return {"passed": True, "variant_counts": {
                str(key): int(value) for key, value in saved.variant.value_counts().sort_index().items()},
            "f1_style6_rows": int(len(style)), "f1_style6_races": int(style.race_id.nunique()),
            "key_coverage_exact": True}


def verify_projection_identity() -> dict:
    rng = np.random.default_rng(20261010)
    checks = []
    for n in (5, 7, 10):
        pairs = list(combinations(range(n), 2))
        triples = list(combinations(range(n), 3))
        unary = rng.normal(size=(n, 2))
        constant = rng.normal(size=2)
        phi = np.asarray([unary[i] + unary[j] + constant for i, j in pairs])
        degree = np.zeros((n, phi.shape[1]))
        for row, (i, j) in enumerate(pairs):
            degree[i] += phi[row]
            degree[j] += phi[row]
        total = phi.sum(axis=0)
        fitted_unary = (degree - total / (n - 1)) / (n - 2)
        residual = np.asarray([phi[row] - fitted_unary[i] - fitted_unary[j]
                               for row, (i, j) in enumerate(pairs)])
        max_abs = float(np.max(np.abs(residual)))
        residual[:, np.max(np.abs(residual), axis=0) <= 1e-12] = 0.0
        row_sums = np.zeros_like(degree)
        for row, (i, j) in enumerate(pairs):
            row_sums[i] += residual[row]
            row_sums[j] += residual[row]
        triple_values = np.asarray([
            residual[pairs.index((i, j))] + residual[pairs.index((i, k))] +
            residual[pairs.index((j, k))] for i, j, k in triples
        ])
        incidence = np.zeros((len(triples), n))
        for row, triple in enumerate(triples):
            incidence[row, list(triple)] = 1.0
        checks.append({"field_n": n, "unary_only_max_abs_before_clean": max_abs,
                       "cleaned_exact_zero": bool(np.max(np.abs(residual)) == 0.0),
                       "max_row_sum_abs": float(np.max(np.abs(row_sums))),
                       "max_A_transpose_G_abs": float(np.max(np.abs(incidence.T @ triple_values)))})
    if any(not row["cleaned_exact_zero"] or row["max_row_sum_abs"] > TOL or
           row["max_A_transpose_G_abs"] > TOL for row in checks):
        raise AssertionError("independent projection/unary negative control failed")
    return {"passed": True, "checks": checks}


def main() -> None:
    if digest(HERE / "PLAN.md") != PLAN_SHA:
        raise AssertionError("independent verifier found plan hash mismatch")
    source_lock = load_json(OUT / "source_lock.json")
    preflight = load_json(OUT / "preflight_receipt.json")
    if source_lock.get("plan_sha256") != PLAN_SHA or preflight.get("plan_sha256") != PLAN_SHA:
        raise AssertionError("preflight artifacts do not name the approved plan")
    if preflight.get("source_lock_sha256") != digest(OUT / "source_lock.json"):
        raise AssertionError("preflight receipt/source lock hash mismatch")
    if (OUT / "a_verification_receipt.json").exists():
        raise FileExistsError("independent verification receipt already exists")
    hashes_before = verify_locked_files(source_lock)

    feature_path = STYLE_OUT / "features.parquet"
    features = pd.read_parquet(feature_path)
    if len(features) != 52155 or features.api_record_id.duplicated().any():
        raise AssertionError("independent verifier found unexpected locked feature table")
    eval_frames = []
    h1_h2_counts = []
    history_rows = 0
    eval_races = eval_rows = 0
    eval_days = set()
    eval_race_ids = set()
    triple_rows = 0
    for year in FOLDS:
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        meta = load_json(folder / "meta.json")
        cal = pd.read_parquet(folder / "calibration_scores.parquet")
        eva = pd.read_parquet(folder / "evaluation_scores.parquet")
        for scores, key in ((cal, "calibration"), (eva, "evaluation")):
            if list(scores.columns) != ["api_record_id", "score"] or scores.api_record_id.duplicated().any():
                raise AssertionError(f"independent {key} score schema/key mismatch for {year}")
        cal_base = features.loc[features.year.eq(year - 1)].copy()
        eval_base = features.loc[features.year.eq(year)].copy()
        for base, scores, label in ((cal_base, cal, "cal"), (eval_base, eva, "eval")):
            base["api_record_id"] = base.api_record_id.astype("int64")
            scores["api_record_id"] = scores.api_record_id.astype("int64")
            if set(base.api_record_id) != set(scores.api_record_id):
                raise AssertionError(f"independent {label} join key mismatch for {year}")
            mapped = scores.set_index("api_record_id").score
            base["score"] = base.api_record_id.map(mapped)
            if base.score.isna().any() or not np.isfinite(base.score.to_numpy(float)).all():
                raise AssertionError(f"independent {label} scores invalid for {year}")
            history_rows += verify_history_cutoff(base)["rows"]
        cal_min, cal_max = pd.to_datetime(cal_base.race_date).min(), pd.to_datetime(cal_base.race_date).max()
        eval_min, eval_max = pd.to_datetime(eval_base.race_date).min(), pd.to_datetime(eval_base.race_date).max()
        for key, actual in (("calibration_min", cal_min), ("calibration_max", cal_max),
                            ("evaluation_min", eval_min), ("evaluation_max", eval_max)):
            if pd.Timestamp(meta[key]).normalize() != pd.Timestamp(actual).normalize():
                raise AssertionError(f"independent {key} metadata mismatch for {year}")
        cal_dates = pd.to_datetime(cal_base.race_date).dt.normalize()
        h1 = cal_base.loc[cal_dates.dt.month.le(6)].copy()
        h2 = cal_base.loc[cal_dates.dt.month.ge(7)].copy()
        h2_min = pd.to_datetime(h2.race_date).dt.normalize().min()
        h1_dates = pd.to_datetime(h1.race_date).dt.normalize()
        keep = h1_dates.le(h2_min - pd.Timedelta(days=2))
        h1_purged = h1.loc[keep].copy()
        if pd.to_datetime(h1_purged.race_date).max() > h2_min - pd.Timedelta(days=2):
            raise AssertionError("independent H1/H2 T-2 boundary failed")
        if pd.to_datetime(h2.race_date).max() > pd.Timestamp(eval_min).normalize() - pd.Timedelta(days=2):
            raise AssertionError("independent H2/evaluation T-2 boundary failed")
        if pd.Timestamp(meta["refit_max"]).normalize() > pd.to_datetime(h1_purged.race_date).min() - pd.Timedelta(days=2):
            raise AssertionError("independent refit/H1 T-2 boundary failed")
        h1_counts = verify_finish_ranks(h1_purged)
        h2_counts_this = verify_finish_ranks(h2)
        eval_counts = verify_finish_ranks(eval_base)
        h1_h2_counts.append({"evaluation_year": year, "h1_races_after_purge": h1_counts[0],
                             "h2_races": h2_counts_this[0],
                             "h1_last_date": str(pd.to_datetime(h1_purged.race_date).max().date()),
                             "h2_first_date": str(pd.to_datetime(h2.race_date).min().date()),
                             "evaluation_first_date": str(pd.Timestamp(eval_min).date())})
        eval_races += eval_counts[0]
        eval_rows += eval_counts[1]
        eval_days.update(eval_counts[2])
        eval_race_ids.update(eval_base.race_id.astype(str).unique())
        triple_rows += sum(math.comb(len(group), 3) for _, group in eval_base.groupby("race_id", sort=True))
        eval_frames.append(eval_base)

    if ((eval_races, eval_rows, len(eval_days)) !=
            (EXPECTED["races"], EXPECTED["runner_rows"], EXPECTED["race_days"]) or
            len(eval_race_ids) != eval_races):
        raise AssertionError("independent evaluation cohort differs from fixed contract")
    if triple_rows != 201404:
        raise AssertionError("independent evaluation triple count differs from fixed contract")
    parity = verify_baseline_six(eval_frames)
    saved_runner = verify_saved_style_runner(eval_frames)
    projection = verify_projection_identity()
    hashes_after = verify_locked_files(source_lock)
    if hashes_before != hashes_after:
        raise AssertionError("locked source hashes changed during independent verification")

    receipt = {
        "passed": True,
        "mode": "independent outcome-free structural verification",
        "plan_sha256": PLAN_SHA,
        "source_lock_sha256": digest(OUT / "source_lock.json"),
        "preflight_receipt_sha256": digest(OUT / "preflight_receipt.json"),
        "source_hashes_unchanged_during_verification": True,
        "database_query_or_connection": False,
        "protected_database_read_only_hash_only": True,
        "network_access": False,
        "checked_locked_source_count": len(hashes_before),
        "history_cutoff_checked_rows": history_rows,
        "evaluation_cohort": {"races": eval_races, "runner_rows": eval_rows,
                              "race_days": len(eval_days), "all_triples": triple_rows,
                              "unique_race_ids": len(eval_race_ids),
                              "six_ticket_rows": eval_races * 6},
        "fold_boundaries": h1_h2_counts,
        "baseline_six_exact_parity": parity,
        "saved_f1_style6_runner_reference_contract": saved_runner,
        "independent_projection_negative_control": projection,
        "outcome_metrics_computed": False,
        "coefficients_fitted": False,
        "temperature_optimized": False,
    }
    target = OUT / "a_verification_receipt.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
