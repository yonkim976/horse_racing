"""Pre-registered F1 residual tables and full S2 grid; no training or source writes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs_f1_supplement"
PRIMARY = HERE / "outputs"
ABALATION = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs"
FEATURES = PRIMARY / "condition_features.parquet"
R1_FEATURES = ROOT / "jeju/research/20261009_field_relative_ability_v1/outputs/features.parquet"
PRIMARY_STATS = PRIMARY / "condition_statistics.csv"
PRIMARY_INTERVALS = PRIMARY / "date_bootstrap_intervals.csv"
F1_PREDICTIONS = ABALATION / "runner_predictions.parquet"
COMPLETION = ABALATION / "training_completion.json"
SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
SEED = 20261009
BOOTSTRAPS = 2000
FAMILIES = ["S1_gap_sequence", "S2_distance_return", "S3_relative_position_change", "S4_prior_rank_finish_gap"]
PERIODS = ["2024_2025", "2026_partial"]
S2_RELATIONS = ["same", "changed", "unknown"]
S2_EXPERIENCE = ["0", "1_2", "3_plus", "unknown"]
EXPECTED_F1_SHA = "37a9567e87b91e3d3bc8b8bfafa1fdab2853239aac422734259b5f893b231440"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def lock_paths() -> list[Path]:
    return [
        HERE / "SUPPLEMENT_PLAN.md", HERE / "supplement_f1.py", HERE / "audit.py", SOURCE,
        PRIMARY / "source_lock.json", PRIMARY / "preflight.json", PRIMARY / "verification.json",
        PRIMARY_STATS, PRIMARY_INTERVALS, FEATURES, R1_FEATURES, F1_PREDICTIONS, COMPLETION,
        *[ABALATION / f"F1_{year}/meta.json" for year in (2024, 2025, 2026)],
    ]


def make_lock() -> dict:
    paths = lock_paths()
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required frozen inputs missing: " + ", ".join(missing))
    lock = {str(path.relative_to(ROOT)): {"sha256": sha(path), "bytes": path.stat().st_size} for path in paths}
    actual_f1 = lock[str(F1_PREDICTIONS.relative_to(ROOT))]["sha256"]
    if actual_f1 != EXPECTED_F1_SHA:
        raise RuntimeError(f"F1 runner predictions SHA mismatch: {actual_f1}")
    return lock


def assert_lock(lock: dict) -> None:
    for rel, info in lock.items():
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size != info["bytes"] or sha(path) != info["sha256"]:
            raise RuntimeError(f"Supplement frozen input changed: {rel}")


def preflight() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite supplement output: {OUT}")
    lock = make_lock()
    primary_preflight = json.loads((PRIMARY / "preflight.json").read_text(encoding="utf-8"))
    primary_verify = json.loads((PRIMARY / "verification.json").read_text(encoding="utf-8"))
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))
    if not primary_preflight.get("passed") or not primary_verify.get("passed"):
        raise RuntimeError("Primary S1-S4 preflight or verification did not pass")
    if not completion.get("passed") or completion.get("production_changed") or completion.get("database_changed"):
        raise RuntimeError("F1 completion artifact is not passed or reports protected changes")
    if completion.get("evaluation_rows_per_variant") != 17412 or completion.get("races_per_variant") != 1779:
        raise RuntimeError("F1 completion counts differ from the supervisor-approved sample")
    source_lock = json.loads((PRIMARY / "source_lock.json").read_text(encoding="utf-8"))
    target = pd.read_parquet(FEATURES)
    expected_started = 17412
    if len(target[target.year.ge(2024)]) != expected_started:
        raise RuntimeError("Frozen 2024-2026 condition rows do not match expected F1 sample")
    OUT.mkdir()
    save_json(OUT / "source_lock.json", lock)
    save_json(OUT / "preflight.json", {
        "passed": True,
        "purpose": "F1 prediction identity and approved sample check only; no conditional residuals computed",
        "F1_expected_rows": expected_started,
        "F1_expected_races": 1779,
        "primary_source_lock_entries": len(source_lock),
        "F1_runner_predictions_sha256": lock[str(F1_PREDICTIONS.relative_to(ROOT))]["sha256"],
        "training_completion_passed": True,
        "model_training_count_for_supplement": 0,
        "protected_writes": 0,
    })
    assert_lock(lock)
    print("F1 supplement preflight passed; no condition residuals calculated", flush=True)


def period_name(year: int) -> str:
    if year in (2024, 2025):
        return "2024_2025"
    if year == 2026:
        return "2026_partial"
    return "outside_scope"


def cell_summary(g: pd.DataFrame, family: str, category: str, period: str, distance=None) -> dict:
    n = len(g)
    q = g[g.p_F1.notna()]
    top3 = int(g.y.sum())
    r1q = g[g.p_R1.notna()]
    return {
        "family": family, "condition": category, "period": period, "distance_m": distance,
        "rows": n, "F1_rows": int(len(q)), "horses": int(g.horse_id.nunique()),
        "races": int(g.race_id.nunique()), "days": int(g.race_date.nunique()),
        "top3": top3, "non_top3": n - top3,
        "first_date": str(g.race_date.min()) if n else None,
        "last_date": str(g.race_date.max()) if n else None,
        "top3_rate": float(g.y.mean()) if n else np.nan,
        "mean_p_F1": float(q.p_F1.mean()) if len(q) else np.nan,
        "F1_residual": float((q.y - q.p_F1).mean()) if len(q) else np.nan,
        "R1_rows": int(len(r1q)),
        "R1_residual_reference": float((r1q.y - r1q.p_R1).mean()) if len(r1q) else np.nan,
        "low_support": bool(n < 100 or g.race_id.nunique() < 50),
    }


def day_bootstrap(g: pd.DataFrame) -> tuple[float, float]:
    q = g[g.p_F1.notna()].copy()
    if q.empty:
        return np.nan, np.nan
    q["residual"] = q.y - q.p_F1
    by_day = q.groupby("race_date", sort=True).residual.agg(["sum", "size"])
    sums = by_day["sum"].to_numpy(float)
    sizes = by_day["size"].to_numpy(float)
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, len(by_day), size=(BOOTSTRAPS, len(by_day)))
    estimates = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    return tuple(map(float, np.quantile(estimates, [0.025, 0.975])))


def s2_grid(base: pd.DataFrame, primary_stats: pd.DataFrame, primary_intervals: pd.DataFrame,
            f1_stats: pd.DataFrame, f1_intervals: pd.DataFrame) -> pd.DataFrame:
    records = []
    period_masks = {
        "all": np.ones(len(base), dtype=bool),
        "2017_2023": base.year.le(2023).to_numpy(),
        "2024_2025": base.year.between(2024, 2025).to_numpy(),
        "2026_partial": base.year.eq(2026).to_numpy(),
    }
    scopes: list[tuple[str, pd.DataFrame, object]] = [(p, base.loc[mask], None) for p, mask in period_masks.items()]
    for period in ("2017_2023", "2024_2025", "2026_partial"):
        period_scope = base.loc[period_masks[period]]
        for distance, distance_scope in period_scope.groupby("distance_m", sort=True):
            scopes.append((period, distance_scope, int(distance)))
    for period, scope, distance in scopes:
        for relation in S2_RELATIONS:
            for experience in S2_EXPERIENCE:
                label = f"prev_{relation}|same_starts_{experience}"
                group = scope[scope.S2_distance_return.eq(label)]
                if relation == "same" and experience == "0":
                    status = "structural_zero_previous_same_distance_is_counted"
                elif experience == "unknown":
                    status = "no_missing_same_starts_values_in_frozen_cohort"
                elif len(group):
                    status = "observed"
                elif relation == "unknown" and experience in ("1_2", "3_plus"):
                    status = "possible_but_zero_observed"
                else:
                    status = "zero_observed_not_structural"
                key_stats = primary_stats[(primary_stats.family.eq("S2_distance_return")) & primary_stats.condition.eq(label)
                                          & primary_stats.period.eq(period)]
                if distance is None:
                    key_stats = key_stats[key_stats.distance_m.isna()]
                else:
                    key_stats = key_stats[key_stats.distance_m.eq(distance)]
                key_ci = primary_intervals[(primary_intervals.family.eq("S2_distance_return")) & primary_intervals.condition.eq(label)
                                           & primary_intervals.period.eq(period)]
                if distance is None:
                    key_ci = key_ci[key_ci.distance_m.isna()]
                else:
                    key_ci = key_ci[key_ci.distance_m.eq(distance)]
                f1_cell = f1_stats[(f1_stats.family.eq("S2_distance_return")) & f1_stats.condition.eq(label)
                                   & f1_stats.period.eq(period)]
                f1_ci = f1_intervals[(f1_intervals.family.eq("S2_distance_return")) & f1_intervals.condition.eq(label)
                                     & f1_intervals.period.eq(period)]
                if distance is None:
                    f1_cell = f1_cell[f1_cell.distance_m.isna()]
                    f1_ci = f1_ci[f1_ci.distance_m.isna()]
                else:
                    f1_cell = f1_cell[f1_cell.distance_m.eq(distance)]
                    f1_ci = f1_ci[f1_ci.distance_m.eq(distance)]
                row = cell_summary(group, "S2_distance_return", label, period, distance)
                row.update({
                    "grid_definition_status": status,
                    "same_starts_missing_values_in_frozen_cohort": int(base.S2_same_distance_started_n.isna().sum()),
                    "uniform_excess": float(key_stats.excess_over_uniform.iloc[0]) if len(key_stats) else np.nan,
                    "uniform_excess_lo": float(key_ci.uniform_excess_lo.iloc[0]) if len(key_ci) else np.nan,
                    "uniform_excess_hi": float(key_ci.uniform_excess_hi.iloc[0]) if len(key_ci) else np.nan,
                    "R1_residual_reference_from_primary": float(key_stats.R1_observed_minus_predicted.iloc[0]) if len(key_stats) else np.nan,
                    "F1_rows": int(f1_cell.F1_rows.iloc[0]) if len(f1_cell) else 0,
                    "F1_residual": float(f1_cell.F1_residual.iloc[0]) if len(f1_cell) else np.nan,
                    "F1_residual_lo": np.nan,
                    "F1_residual_hi": np.nan,
                })
                # The cell's F1 interval is computed in the main supplement output and copied here.
                if len(f1_ci):
                    row["F1_residual_lo"] = float(f1_ci.F1_residual_lo.iloc[0])
                    row["F1_residual_hi"] = float(f1_ci.F1_residual_hi.iloc[0])
                records.append(row)
    return pd.DataFrame(records)


def _same_value(left, right):
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if left is None or right is None:
        return left is right
    try:
        lm, rm = pd.isna(left), pd.isna(right)
        if isinstance(lm, (bool, np.bool_)) and isinstance(rm, (bool, np.bool_)) and (lm or rm):
            return bool(lm and rm)
    except (TypeError, ValueError):
        pass
    return left == right


def verify_target_outcome_invariance(base: pd.DataFrame, source: pd.DataFrame, r1_features: pd.DataFrame) -> int:
    sys.path.insert(0, str(HERE))
    from audit import condition_row

    sample = base.sample(n=min(200, len(base)), random_state=SEED)
    src_idx = source.set_index("api_record_id", drop=False)
    feat_idx = r1_features.set_index("api_record_id", drop=False)
    source_by_horse = {str(h): g.sort_values(["race_date", "api_record_id"]).reset_index(drop=True)
                       for h, g in source.groupby("horse_id", sort=False)}
    checked = 0
    for row in sample.itertuples(index=False):
        horse = str(row.horse_id)
        target_id = int(row.api_record_id)
        before = condition_row(row, src_idx, feat_idx, source_by_horse)
        # Mutate only this target's later outcome fields in memory; the T-2 history must censor it.
        h = source_by_horse[horse]
        positions = h.index[h.api_record_id.astype(int).eq(target_id)]
        if len(positions) != 1 or target_id not in src_idx.index:
            raise RuntimeError(f"Target outcome source row not uniquely linked at {target_id}")
        loc = positions[0]
        original_h = h.loc[loc, ["finish_position", "finish_time_seconds", "valid_time", "started"]].copy()
        original_i = src_idx.loc[target_id, ["finish_position", "finish_time_seconds", "valid_time", "started"]].copy()
        h.loc[loc, "finish_position"] = 999
        h.loc[loc, "finish_time_seconds"] = 1.0e6
        h.loc[loc, "valid_time"] = False
        h.loc[loc, "started"] = False
        src_idx.loc[target_id, "finish_position"] = 999
        src_idx.loc[target_id, "finish_time_seconds"] = 1.0e6
        src_idx.loc[target_id, "valid_time"] = False
        src_idx.loc[target_id, "started"] = False
        changed = condition_row(row._replace(finish_position=999), src_idx, feat_idx, source_by_horse)
        h.loc[loc, original_h.index] = original_h
        src_idx.loc[target_id, original_i.index] = original_i
        if before.keys() != changed.keys() or not all(_same_value(before[k], changed[k]) for k in before):
            raise RuntimeError(f"Target finish/time perturbation changed pre-race condition at {target_id}")
        checked += 1
    return checked


def build_outputs() -> None:
    if not OUT.is_dir() or not (OUT / "source_lock.json").is_file() or not (OUT / "preflight.json").is_file():
        raise RuntimeError("Run supplement --preflight first")
    lock = json.loads((OUT / "source_lock.json").read_text(encoding="utf-8"))
    assert_lock(lock)
    primary = pd.read_parquet(FEATURES)
    r1_features = pd.read_parquet(R1_FEATURES)
    primary_stats = pd.read_csv(PRIMARY_STATS)
    primary_intervals = pd.read_csv(PRIMARY_INTERVALS)
    prediction_frame = pd.read_parquet(F1_PREDICTIONS)
    predictions = prediction_frame[prediction_frame.variant.eq("F1")].copy()
    source = pd.read_parquet(SOURCE)
    required_prediction = {"api_record_id", "race_id", "race_date", "horse_id", "p_top3", "y", "variant"}
    if required_prediction - set(predictions.columns):
        raise RuntimeError(f"F1 predictions missing columns: {sorted(required_prediction - set(predictions.columns))}")
    if predictions.api_record_id.duplicated().any() or len(predictions) != 17412:
        raise RuntimeError("F1 prediction IDs/count do not match the fixed evaluation cohort")
    recent = primary[primary.year.ge(2024)].copy()
    if len(recent) != len(predictions) or recent.api_record_id.duplicated().any():
        raise RuntimeError("F1-to-condition row count does not match")
    joined = recent.merge(predictions[["api_record_id", "race_id", "race_date", "horse_id", "p_top3", "y"]],
                          on="api_record_id", how="left", suffixes=("", "_F1"), validate="one_to_one", indicator=True)
    if not joined._merge.eq("both").all():
        raise RuntimeError("Some approved condition rows have no F1 probability")
    for col in ["race_id", "race_date", "horse_id"]:
        if not joined[col].astype(str).eq(joined[f"{col}_F1"].astype(str)).all():
            raise RuntimeError(f"F1 identity mismatch in {col}")
    if not joined.y.astype(int).eq(joined.y_F1.astype(int)).all():
        raise RuntimeError("F1 prediction label differs from frozen condition label")
    joined["p_F1"] = joined.p_top3.astype(float)
    if joined.p_F1.isna().any() or (~joined.p_F1.between(0, 1)).any():
        raise RuntimeError("F1 predictions contain a missing or invalid probability")
    if not joined.groupby("race_id").p_F1.sum().sub(3).abs().lt(1e-9).all():
        raise RuntimeError("F1 top-three marginal probability sum is not 3 per race")
    joined["period"] = np.where(joined.year.le(2025), "2024_2025", "2026_partial")
    if joined.groupby("period").size().to_dict() != {"2024_2025": 12739, "2026_partial": 4673}:
        raise RuntimeError("F1 period denominator mismatch")
    if joined.race_id.nunique() != 1779 or joined.groupby("period").race_id.nunique().to_dict() != {
        "2024_2025": 1291, "2026_partial": 488
    }:
        raise RuntimeError("F1 period race count mismatch")

    rows = []
    for period in PERIODS:
        scope = joined[joined.period.eq(period)]
        for family in FAMILIES:
            for category, group in scope.groupby(family, sort=True, dropna=False):
                rows.append(cell_summary(group, family, str(category), period))
            for distance, distance_scope in scope.groupby("distance_m", sort=True):
                for category, group in distance_scope.groupby(family, sort=True, dropna=False):
                    rows.append(cell_summary(group, family, str(category), period, int(distance)))
    table = pd.DataFrame(rows)
    ci_rows = []
    for row in table.itertuples(index=False):
        mask = joined.period.eq(row.period) & joined[row.family].astype(str).eq(row.condition)
        if row.distance_m is not None and not pd.isna(row.distance_m):
            mask &= joined.distance_m.eq(float(row.distance_m))
        group = joined.loc[mask]
        lo, hi = day_bootstrap(group)
        ci_rows.append({"family": row.family, "condition": row.condition, "period": row.period,
                        "distance_m": row.distance_m, "F1_residual_lo": lo, "F1_residual_hi": hi})
    intervals = pd.DataFrame(ci_rows)
    table.to_csv(OUT / "F1_condition_statistics.csv", index=False)
    intervals.to_csv(OUT / "F1_date_bootstrap_intervals.csv", index=False)
    primary_grid = primary.merge(joined[["api_record_id", "p_F1"]], on="api_record_id", how="left", validate="one_to_one")
    s2_grid(primary_grid, primary_stats, primary_intervals, table, intervals).to_csv(
        OUT / "S2_full_grid_support.csv", index=False)

    source_checks = verify_target_outcome_invariance(primary, source, r1_features)
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))
    f1_meta = {str(year): json.loads((ABALATION / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
               for year in (2024, 2025, 2026)}
    assert_lock(lock)
    save_json(OUT / "supplement_verification.json", {
        "passed": True,
        "scope": "root-supervised descriptive supplement after the primary S1-S4 tables; no new model fit",
        "F1_variant_only": True,
        "F1_rows": len(joined), "F1_races": int(joined.race_id.nunique()),
        "F1_period_rows": joined.groupby("period").size().to_dict(),
        "F1_period_races": joined.groupby("period").race_id.nunique().to_dict(),
        "prediction_id_unique": True, "condition_id_join_one_to_one": True,
        "label_identity_matches": True, "F1_top3_probability_sum3_per_race": True,
        "date_bootstrap_repetitions": BOOTSTRAPS, "date_bootstrap_seed": SEED,
        "condition_families": FAMILIES, "condition_cell_rows_including_distance": len(table),
        "S2_full_grid_cells_per_scope": 12, "S2_full_grid_rows": len(pd.read_csv(OUT / "S2_full_grid_support.csv")),
        "same_starts_missing_values_in_cohort": int(primary.S2_same_distance_started_n.isna().sum()),
        "target_finish_and_actual_time_perturbation_invariance_rows": source_checks,
        "F1_meta_sha256s": {str(year): sha(ABALATION / f"F1_{year}/meta.json") for year in (2024, 2025, 2026)},
        "F1_model_sha256s": {str(year): f1_meta[str(year)]["model_sha256"] for year in (2024, 2025, 2026)},
        "training_completion_passed": bool(completion.get("passed")),
        "model_training_count_for_supplement": 0,
        "protected_writes": 0,
        "supplement_lock_unchanged_at_completion": True,
    })
    print("F1 residual supplement and full S2 grid saved under", OUT, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Lock inputs and verify the F1 cohort without residual summaries")
    group.add_argument("--analyze", action="store_true", help="Compute approved F1 residual supplement")
    args = parser.parse_args()
    if args.preflight:
        preflight()
    else:
        build_outputs()


if __name__ == "__main__":
    main()
