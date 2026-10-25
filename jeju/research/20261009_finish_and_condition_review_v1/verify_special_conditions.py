"""Independent read-only checks for S1-S4 condition audit outputs."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
SPECIAL = ROOT / "jeju/research/20261009_special_condition_audit_v1"
OUT = SPECIAL / "outputs"
TOP3 = ROOT / "jeju/research/20261009_top3_condition_profiles_v1"
R1 = ROOT / "jeju/research/20261009_field_relative_ability_v1"
BASELINE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1"
BASE_FEATURES = TOP3 / "outputs/condition_features.parquet"
R1_FEATURES = R1 / "outputs/features.parquet"
SOURCE = BASELINE / "outputs_v2/source_snapshot.parquet"
CONDITIONS = ("S1_gap_sequence", "S2_distance_return", "S3_relative_position_change", "S4_prior_rank_finish_gap")
PERIODS = ("all", "2017_2023", "2024_2025", "2026_partial")
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261009
ATOL = 2e-10


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(raw: str) -> Path:
    rel = PurePosixPath(raw)
    require(not rel.is_absolute() and ".." not in rel.parts, f"unsafe lock path {raw}")
    resolved = (ROOT / Path(*rel.parts)).resolve()
    require(resolved.is_relative_to(ROOT.resolve()), f"lock path escapes project: {raw}")
    return resolved


def is_null(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        x = pd.isna(value)
        return bool(x) if np.ndim(x) == 0 else False
    except (TypeError, ValueError):
        return False


def as_id(value: object) -> int | None:
    return None if is_null(value) else int(value)


def as_ids(value: object) -> list[int]:
    if is_null(value):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    require(isinstance(value, (list, tuple)), f"expected ID list; got {type(value).__name__}")
    return [int(x) for x in value if not is_null(x)]


def close(a: object, b: object, label: str) -> None:
    left = np.asarray(a, dtype=float)
    right = np.asarray(b, dtype=float)
    require(left.shape == right.shape, f"{label}: shape mismatch")
    require(np.allclose(left, right, atol=ATOL, rtol=0, equal_nan=True), f"{label}: value mismatch")


def lock_check() -> dict[str, object]:
    lock = json.loads((OUT / "source_lock.json").read_text(encoding="utf-8"))
    for rel, info in lock.items():
        path = safe_path(rel)
        require(path.is_file(), f"locked source missing: {rel}")
        require(path.stat().st_size == int(info["bytes"]) and sha256(path) == info["sha256"],
                f"locked source changed: {rel}")
    original_outputs = [OUT / name for name in (
        "condition_features.parquet", "condition_statistics.csv", "date_bootstrap_intervals.csv",
        "S1_uncertain_nonstart_lineage.csv", "operating_common467_condition_summary.csv", "verification.json")]
    output_hashes = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in original_outputs}
    return {"locked_input_files": len(lock), "original_output_hashes": output_hashes,
            "original_statistics_rows": int(len(pd.read_csv(OUT / "condition_statistics.csv")))}


def valid_rank(row: pd.Series | dict, n: int) -> int | None:
    raw = row.get("finish_position")
    if is_null(raw):
        return None
    val = float(raw)
    if not val.is_integer() or val < 1 or val > n:
        return None
    return int(val)


def condition_values(row: pd.Series, source_by_id: dict[int, dict], source_by_horse: dict[str, pd.DataFrame],
                     feature_by_id: dict[int, dict], starter_counts: dict[str, int],
                     complete_race: dict[str, bool]) -> dict[str, object]:
    """Rebuild conditions without importing the special audit implementation."""
    target_date = date.fromisoformat(str(row.race_date))
    cutoff = date.fromisoformat(str(row.history_cutoff))
    cutoff_s = cutoff.isoformat()
    horse = str(row.horse_id)
    target_id = int(row.api_record_id)
    target_distance = float(row.distance_m)
    all_horse = source_by_horse.get(horse)
    if all_horse is None:
        historical = pd.DataFrame()
    else:
        historical = all_horse.loc[all_horse.race_date.le(cutoff_s)]
    actual_starts = historical.loc[historical.started.fillna(False).astype(bool)]
    previous_id = as_id(row.previous_start_id)
    require((int(actual_starts.api_record_id.iloc[-1]) if len(actual_starts) else None) == previous_id,
            f"prior-start ID does not match full source sequence at {target_id}")
    previous = source_by_id.get(previous_id) if previous_id is not None else None

    uncertain = historical.loc[~historical.started.fillna(False).astype(bool) &
                               historical.finish_position.isin([0, 93, 98])]
    uncertain_ids: set[int] = set()
    prior2_id = None
    current_gap = np.nan
    if previous is None or actual_starts.empty:
        s1 = "unknown"
    else:
        require(str(previous["horse_id"]) == horse and str(previous["race_date"]) <= cutoff_s,
                f"S1 previous identity/cutoff mismatch at {target_id}")
        current_gap = (target_date - date.fromisoformat(str(previous["race_date"]))).days
        require(current_gap >= 0, f"negative current gap at {target_id}")
        current_uncertain = uncertain.loc[
            uncertain.race_date.ge(str(previous["race_date"])) & uncertain.race_date.le(cutoff_s)]
        uncertain_ids.update(current_uncertain.api_record_id.astype(int).tolist())
        if len(current_uncertain):
            s1 = "unknown"
        elif current_gap >= 91:
            s1 = "first_return_91_plus"
        elif len(actual_starts) < 2:
            s1 = "unknown"
        else:
            prior2 = actual_starts.iloc[-2]
            prior2_id = int(prior2.api_record_id)
            prior_date = str(prior2.race_date)
            prev_date = str(previous["race_date"])
            if prior_date == prev_date:
                s1 = "unknown"
            else:
                preceding_uncertain = uncertain.loc[
                    uncertain.race_date.ge(prior_date) & uncertain.race_date.le(prev_date)]
                uncertain_ids.update(preceding_uncertain.api_record_id.astype(int).tolist())
                previous_gap = (date.fromisoformat(prev_date) - date.fromisoformat(prior_date)).days
                if len(preceding_uncertain):
                    s1 = "unknown"
                elif previous_gap >= 91:
                    s1 = "second_after_return_le90"
                else:
                    s1 = "general"

    same_n = None if is_null(row.same_starts) else int(row.same_starts)
    if same_n is None:
        same_bucket = "unknown"
    elif same_n == 0:
        same_bucket = "0"
    elif same_n <= 2:
        same_bucket = "1_2"
    else:
        same_bucket = "3_plus"
    if previous is None or is_null(previous.get("race_distance_m")):
        relation = "unknown"
        previous_distance = np.nan
    else:
        previous_distance = float(previous["race_distance_m"])
        relation = "same" if previous_distance == target_distance else "changed"
    s2 = f"prev_{relation}|same_starts_{same_bucket}"

    # Independently rebuild every eligible same-distance start, then require that
    # the stored six-ID window is the exact most recent window (no skipping).
    if all_horse is None:
        same_starts = pd.DataFrame()
    else:
        same_starts = all_horse.loc[
            all_horse.race_date.le(cutoff_s) & all_horse.started.fillna(False).astype(bool) &
            pd.to_numeric(all_horse.race_distance_m, errors="coerce").eq(target_distance)]
    expected_same_ids = same_starts.api_record_id.astype(int).iloc[-6:].tolist()
    stored_same_ids = as_ids(row.last6_same_source_ids)
    require(stored_same_ids == expected_same_ids, f"same-distance history window skips/misorders IDs at {target_id}")
    s3_prior_id = stored_same_ids[-1] if stored_same_ids else None
    current_rank = np.nan if is_null(row.mean5_rank_fraction) else float(row.mean5_rank_fraction)
    prior_rank = np.nan
    if s3_prior_id is None or not np.isfinite(current_rank) or s3_prior_id not in feature_by_id:
        s3 = "unknown"
    else:
        prior_feature = feature_by_id[s3_prior_id]
        prior_source = source_by_id[s3_prior_id]
        require(str(prior_source["horse_id"]) == horse and
                float(prior_source["race_distance_m"]) == target_distance and
                str(prior_source["race_date"]) <= cutoff_s and bool(prior_source["started"]),
                f"S3 direct latest same-distance lineage invalid at {target_id}")
        prior_rank = np.nan if is_null(prior_feature.get("mean5_rank_fraction")) else float(prior_feature["mean5_rank_fraction"])
        delta = current_rank - prior_rank
        if not np.isfinite(prior_rank):
            s3 = "unknown"
        elif delta <= -0.25:
            s3 = "improved_ge0_25"
        elif delta >= 0.25:
            s3 = "worsened_ge0_25"
        else:
            s3 = "change_lt0_25"

    s4_id = previous_id
    prior_time_rank = np.nan
    prior_finish_fraction = np.nan
    if previous is None or previous_id not in feature_by_id:
        s4 = "unknown"
    else:
        prior_feature = feature_by_id[previous_id]
        prior_source_for_s4 = source_by_id[previous_id]
        race_id = str(prior_source_for_s4["race_id"])
        n = int(starter_counts.get(race_id, 0))
        rank = valid_rank(prior_source_for_s4, n)
        prior_time_rank = (np.nan if is_null(prior_feature.get("mean5_rank_fraction"))
                           else float(prior_feature["mean5_rank_fraction"]))
        require(str(prior_feature["horse_id"]) == horse and
                str(prior_feature["race_date"]) <= cutoff_s,
                f"S4 exact previous feature identity/cutoff mismatch at {target_id}")
        if not complete_race.get(race_id, False) or rank is None or not np.isfinite(prior_time_rank):
            s4 = "unknown"
        else:
            prior_finish_fraction = (rank - 1) / (n - 1)
            gap = prior_finish_fraction - prior_time_rank
            if gap >= 0.25:
                s4 = "worse_than_prior_time_rank_ge0_25"
            elif gap <= -0.25:
                s4 = "better_than_prior_time_rank_ge0_25"
            else:
                s4 = "close_lt0_25"

    return {
        "S1_gap_sequence": s1,
        "S1_current_gap_days": current_gap,
        "S1_previous_start_id": previous_id,
        "S1_pre_previous_start_id": prior2_id,
        "S1_uncertain_nonstart_n": len(uncertain_ids),
        "S1_uncertain_nonstart_ids": sorted(uncertain_ids),
        "S2_distance_return": s2,
        "S2_previous_distance_m": previous_distance,
        "S2_same_distance_started_n": same_n,
        "S3_relative_position_change": s3,
        "S3_prior_same_distance_id": s3_prior_id,
        "S3_current_rank_fraction": current_rank,
        "S3_prior_rank_fraction": prior_rank,
        "S3_delta_fraction": current_rank - prior_rank if np.isfinite(current_rank) and np.isfinite(prior_rank) else np.nan,
        "S4_prior_rank_finish_gap": s4,
        "S4_prior_start_id": s4_id,
        "S4_prior_time_rank_fraction": prior_time_rank,
        "S4_prior_finish_fraction": prior_finish_fraction,
        "S4_finish_minus_time_rank_fraction": prior_finish_fraction - prior_time_rank
        if np.isfinite(prior_finish_fraction) and np.isfinite(prior_time_rank) else np.nan,
    }


def stats_summary(g: pd.DataFrame, family: str, category: str, period: str,
                  population: pd.DataFrame, distance: int | None = None) -> dict[str, object]:
    y = g.y.to_numpy(float)
    n = len(g)
    top3 = int(y.sum())
    by_race = g.groupby("race_id", sort=False).agg(rows=("y", "size"), hits=("y", "sum"),
                                                  field_n=("field_n", "first"))
    mixed = by_race.loc[by_race.rows.lt(by_race.field_n)]
    within = (((mixed.hits / mixed.rows) - ((3 - mixed.hits) / (mixed.field_n - mixed.rows))).mean()
              if len(mixed) else np.nan)
    result = {
        "family": family, "condition": category, "period": period, "distance_m": distance,
        "rows": n, "top3": top3, "non_top3": n - top3,
        "horses": int(g.horse_id.nunique()), "races": int(g.race_id.nunique()),
        "days": int(g.race_date.nunique()), "first_date": str(g.race_date.min()), "last_date": str(g.race_date.max()),
        "share_of_population": n / max(1, len(population)),
        "share_among_top3": top3 / max(1, int(population.y.sum())),
        "top3_rate": float(y.mean()), "uniform_3_over_n": float(g.uniform_p.mean()),
        "excess_over_uniform": float((y - g.uniform_p.to_numpy(float)).mean()),
        "within_race_risk_difference": float(within) if pd.notna(within) else np.nan,
        "within_race_comparable_races": int(len(mixed)),
        "low_support": bool(n < 100 or g.race_id.nunique() < 50),
    }
    for name, prediction in (("R1", "p_R1"), ("HY_R_FORM", "p_HY")):
        q = g.loc[g[prediction].notna()]
        result[f"{name}_rows"] = len(q)
        result[f"{name}_predicted_top3"] = float(q[prediction].mean()) if len(q) else np.nan
        result[f"{name}_observed_top3"] = float(q.y.mean()) if len(q) else np.nan
        result[f"{name}_observed_minus_predicted"] = float((q.y - q[prediction]).mean()) if len(q) else np.nan
    return result


def bootstrap_ci(g: pd.DataFrame, outcome: str, prediction: str | None = None) -> tuple[float, float]:
    q = g.loc[g[prediction].notna()].copy() if prediction else g.copy()
    if q.empty:
        return np.nan, np.nan
    delta = q[outcome] - q[prediction] if prediction else q[outcome] - q.uniform_p
    by_day = delta.groupby(q.race_date, sort=True).agg(["sum", "size"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(by_day), size=(BOOTSTRAP_REPS, len(by_day)))
    values = by_day["sum"].to_numpy()[indices].sum(axis=1) / by_day["size"].to_numpy()[indices].sum(axis=1)
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def compare_table(actual: pd.DataFrame, expected: pd.DataFrame, key_cols: list[str],
                  numeric_cols: list[str], label: str) -> None:
    left = actual.sort_values(key_cols, kind="stable").reset_index(drop=True)
    right = expected.sort_values(key_cols, kind="stable").reset_index(drop=True)
    require(len(left) == len(right), f"{label}: row counts differ {len(left)} vs {len(right)}")
    for key in key_cols:
        require(left[key].fillna("<NA>").astype(str).equals(right[key].fillna("<NA>").astype(str)),
                f"{label}: key mismatch {key}")
    for col in numeric_cols:
        close(left[col].to_numpy(float), right[col].to_numpy(float), f"{label} {col}")


def verify() -> dict[str, object]:
    lock_report = lock_check()
    source = pd.read_parquet(SOURCE)
    base = pd.read_parquet(BASE_FEATURES)
    r1 = pd.read_parquet(R1_FEATURES)
    derived = pd.read_parquet(OUT / "condition_features.parquet")
    require(len(base) == len(r1) == len(derived) == 52155, "cohort row count mismatch")
    require(base.api_record_id.tolist() == derived.api_record_id.tolist(), "derived row order/API IDs changed")
    inherited = [column for column in base.columns if column != "period"]
    pd.testing.assert_frame_equal(derived[inherited], base[inherited], check_exact=True)
    expected_analysis_period = np.select([derived.year.le(2023), derived.year.le(2025)],
                                         ["2017_2023", "2024_2025"], default="2026_partial")
    require(np.array_equal(derived.period.astype(str).to_numpy(), expected_analysis_period),
            "analysis period labels differ from fixed date ranges")
    require(not source.duplicated("api_record_id").any(), "source API IDs are not unique")

    source_by_id = {int(row.api_record_id): row._asdict() for row in source.itertuples(index=False)}
    source_by_horse = {
        str(horse): group.sort_values(["race_date", "race_number", "horse_number", "api_record_id"],
                                      kind="stable").reset_index(drop=True)
        for horse, group in source.groupby("horse_id", sort=False)
    }
    feature_by_id = {int(row.api_record_id): row._asdict() for row in r1.itertuples(index=False)}
    starter_counts = source.loc[source.started.fillna(False).astype(bool)].groupby("race_id").size().to_dict()
    complete_race = {}
    for race_id, group in source.groupby("race_id", sort=False):
        starters = group.loc[group.started.fillna(False).astype(bool)]
        n = len(starters)
        ranks = pd.to_numeric(starters.finish_position, errors="coerce").dropna().astype(int).tolist()
        complete_race[str(race_id)] = bool(n >= 2 and len(ranks) == n and len(set(ranks)) == n
                                           and sorted(ranks) == list(range(1, n + 1))
                                           and starters.horse_id.nunique() == n)

    condition_columns = [
        "S1_gap_sequence", "S1_current_gap_days", "S1_previous_start_id", "S1_pre_previous_start_id",
        "S1_uncertain_nonstart_n", "S1_uncertain_nonstart_ids", "S2_distance_return",
        "S2_previous_distance_m", "S2_same_distance_started_n", "S3_relative_position_change",
        "S3_prior_same_distance_id", "S3_current_rank_fraction", "S3_prior_rank_fraction",
        "S3_delta_fraction", "S4_prior_rank_finish_gap", "S4_prior_start_id",
        "S4_prior_time_rank_fraction", "S4_prior_finish_fraction", "S4_finish_minus_time_rank_fraction",
    ]
    expected_records = []
    for row in base.itertuples(index=False):
        record = condition_values(pd.Series(row._asdict()), source_by_id, source_by_horse, feature_by_id,
                                 {str(k): int(v) for k, v in starter_counts.items()}, complete_race)
        expected_records.append(record)
    expected_features = pd.DataFrame(expected_records)
    condition_checks = {"rows": len(derived), "feature_values": 0, "source_start_links": 0,
                        "same_distance_windows": 0, "uncertain_ids": 0}
    for column in condition_columns:
        if column.endswith("_ids"):
            for i, (actual, expected) in enumerate(zip(derived[column], expected_features[column])):
                require(as_ids(actual) == as_ids(expected), f"{column} mismatch row {i}")
        elif derived[column].dtype == object or pd.api.types.is_string_dtype(derived[column]):
            require(derived[column].fillna("<NA>").astype(str).equals(
                    expected_features[column].fillna("<NA>").astype(str)), f"{column} mismatch")
        else:
            close(derived[column].to_numpy(float), expected_features[column].to_numpy(float), column)
        condition_checks["feature_values"] += len(derived)
    condition_checks["source_start_links"] = int(derived.S1_previous_start_id.notna().sum())
    condition_checks["same_distance_windows"] = int(derived.S3_prior_same_distance_id.notna().sum())
    condition_checks["uncertain_ids"] = int(derived.S1_uncertain_nonstart_n.sum())

    # Validate exact target labels and field-level denominators.
    close(derived.y.to_numpy(float), base.finish_position.le(3).astype(int).to_numpy(float), "target labels")
    close(derived.uniform_p.to_numpy(float), 3 / base.field_n.to_numpy(float), "uniform 3/N")
    require(derived.groupby("race_id").y.sum().eq(3).all(), "Top3 sums differ from three per race")
    require(derived.groupby("race_id").field_n.first().eq(derived.groupby("race_id").size()).all(),
            "field denominator differs within race")
    require(derived.S2_distance_return.nunique() == 6, "observed S2 condition levels differ")
    s2_grid = [f"prev_{prev}|same_starts_{n}" for prev in ("same", "changed", "unknown")
               for n in ("0", "1_2", "3_plus", "unknown")]
    observed_s2 = derived.S2_distance_return.value_counts().to_dict()
    s2_support = {key: int(observed_s2.get(key, 0)) for key in s2_grid}

    # Recalculate all original summary cells from verified row-level values.
    expected_stats = []
    grouped_periods = [("all", derived)]
    grouped_periods.extend([
        ("2017_2023", derived.loc[derived.year.le(2023)]),
        ("2024_2025", derived.loc[derived.year.between(2024, 2025)]),
        ("2026_partial", derived.loc[derived.year.eq(2026)]),
    ])
    for period, population in grouped_periods:
        for family in CONDITIONS:
            for category, group in population.groupby(family, sort=True, dropna=False):
                expected_stats.append(stats_summary(group, family, str(category), period, population))
        for distance, distance_population in population.groupby("distance_m", sort=True):
            for family in CONDITIONS:
                for category, group in distance_population.groupby(family, sort=True, dropna=False):
                    expected_stats.append(stats_summary(group, family, str(category), period,
                                                        distance_population, int(distance)))
    actual_stats = pd.read_csv(OUT / "condition_statistics.csv")
    numeric_stats = [col for col in actual_stats.columns if col not in {"family", "condition", "period", "first_date", "last_date"}]
    compare_table(actual_stats, pd.DataFrame(expected_stats), ["family", "condition", "period", "distance_m"],
                  numeric_stats, "condition statistics")

    expected_ci = []
    for row in actual_stats.itertuples(index=False):
        if row.period not in ("2024_2025", "2026_partial"):
            continue
        mask = derived[row.family].astype(str).eq(row.condition)
        if not is_null(row.distance_m):
            mask &= derived.distance_m.eq(float(row.distance_m))
        if row.period == "2024_2025":
            mask &= derived.year.between(2024, 2025)
        else:
            mask &= derived.year.eq(2026)
        group = derived.loc[mask]
        u_lo, u_hi = bootstrap_ci(group, "y")
        r_lo, r_hi = bootstrap_ci(group, "y", "p_R1")
        expected_ci.append({"family": row.family, "condition": row.condition, "period": row.period,
                            "distance_m": row.distance_m, "uniform_excess_lo": u_lo,
                            "uniform_excess_hi": u_hi, "R1_residual_lo": r_lo, "R1_residual_hi": r_hi})
    actual_ci = pd.read_csv(OUT / "date_bootstrap_intervals.csv")
    compare_table(actual_ci, pd.DataFrame(expected_ci), ["family", "condition", "period", "distance_m"],
                  ["uniform_excess_lo", "uniform_excess_hi", "R1_residual_lo", "R1_residual_hi"],
                  "date-cluster intervals")

    common = derived.loc[derived.p_HY.notna()].copy()
    require(common.race_id.nunique() == 467 and len(common) == 4475, "HY operating common denominator mismatch")
    expected_common = []
    for family in CONDITIONS:
        for category, group in common.groupby(family, sort=True, dropna=False):
            expected_common.append(stats_summary(group, family, str(category), "2026_operating_common467", common))
    actual_common = pd.read_csv(OUT / "operating_common467_condition_summary.csv")
    numeric_common = [col for col in actual_common.columns if col not in {"family", "condition", "period", "first_date", "last_date"}]
    compare_table(actual_common, pd.DataFrame(expected_common), ["family", "condition", "period"],
                  numeric_common, "operating 467 condition summary")

    candidate_verification = json.loads((OUT / "verification.json").read_text(encoding="utf-8"))
    require(candidate_verification.get("passed") is True, "candidate special verifier reports failure")
    return {"passed": True, "row_level_conditions": condition_checks,
            "S2_12_fixed_cell_support": s2_support,
            "condition_statistics_recalculated_rows": len(actual_stats),
            "date_intervals_recalculated_rows": len(actual_ci),
            "operating_common_races": int(common.race_id.nunique()),
            "operating_common_runner_rows": len(common), "lock_check": lock_report,
            "candidate_verification_claims_checked": ["passed", "cohort rows", "Top3 sums", "denominator"],
            "model_training": 0, "database_changed": False, "production_changed": False,
            "publication_independent_future_validation": False}


if __name__ == "__main__":
    report = verify()
    receipt = REVIEW / "special_condition_independent_verification.json"
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
