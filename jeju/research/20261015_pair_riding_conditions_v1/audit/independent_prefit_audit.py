"""Independent read-only source and feature audit for pair riding conditions."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
SELECTED_STARTS = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE_PAIR_PREDICTIONS = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
UPSTREAM_SOURCE_AUDIT = ROOT / "jeju/research/20261010_style_history_source_audit_v1/source_audit.json"
OUTPUT_RECEIPT = HERE / "independent_prefit_receipt.json"
OUTPUT_RUNNERS = HERE / "independent_runner_features.parquet"
OUTPUT_PAIRS = HERE / "independent_evaluation_pair_features.parquet"

KNOWN_SENTINELS = {"000000", "999999"}
STARTED_POSITIONS = set(range(1, 90)) | {91, 92}
RIDER_PSEUDO_STARTS = 20.0


class AuditError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AuditError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink input is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with checked(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_id(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    result = str(value).strip()
    return result if result else None


def valid_rider_id(value: Any) -> bool:
    rider_id = normalized_id(value)
    return bool(rider_id and rider_id.isascii() and rider_id.isdigit()
                and len(rider_id) == 6 and rider_id not in KNOWN_SENTINELS)


def date_np(value: Any) -> np.datetime64:
    return np.datetime64(pd.Timestamp(value).date().isoformat(), "D")


def event_source_rows(started: pd.DataFrame) -> pd.DataFrame:
    ids = pd.to_numeric(started["api_record_id"], errors="raise").astype("int64").tolist()
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        require(connection.execute("PRAGMA query_only").fetchone()[0] == 1, "SQLite query_only did not activate")
        chunks: list[pd.DataFrame] = []
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            chunks.append(pd.read_sql_query(
                "SELECT api_record_id, race_date, meet_code, race_number, horse_number, horse_id, "
                "race_distance_m, finish_position, jockey_id "
                f"FROM race_result_rows WHERE api_record_id IN ({placeholders})",
                connection, params=batch,
            ))
        result = pd.concat(chunks, ignore_index=True)
        result["api_record_id"] = pd.to_numeric(result["api_record_id"], errors="raise").astype("int64")
        return result
    finally:
        connection.close()


def index_history(history: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for horse_id, group in history.groupby("horse_id", sort=False):
        group = group.sort_values(["race_date", "api_record_id"], kind="mergesort").reset_index(drop=True)
        result[str(horse_id)] = {
            "frame": group,
            "dates": group["race_date"].to_numpy(dtype="datetime64[D]"),
        }
    return result


def last_asof(group_info: dict[str, Any] | None, cutoff: np.datetime64) -> tuple[pd.Series | None, int]:
    if group_info is None:
        return None, 0
    group = group_info["frame"]
    dates = group_info["dates"]
    right = int(np.searchsorted(dates, cutoff, side="right"))
    if right == 0:
        return None, 0
    last_date = dates[right - 1]
    left = int(np.searchsorted(dates, last_date, side="left"))
    candidates = group.iloc[left:right]
    if len(candidates) != 1:
        return None, int(len(candidates))
    return candidates.iloc[0], 1


def last_strictly_before(group_info: dict[str, Any] | None, target_date: np.datetime64) -> tuple[pd.Series | None, int]:
    if group_info is None:
        return None, 0
    group = group_info["frame"]
    dates = group_info["dates"]
    right = int(np.searchsorted(dates, target_date, side="left"))
    if right == 0:
        return None, 0
    last_date = dates[right - 1]
    left = int(np.searchsorted(dates, last_date, side="left"))
    candidates = group.iloc[left:right]
    if len(candidates) != 1:
        return None, int(len(candidates))
    return candidates.iloc[0], 1


def rider365_index(starts: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rider_id, group in starts.groupby("jockey_id", sort=False):
        group = group.sort_values(["race_date", "api_record_id"], kind="mergesort")
        dates = group["race_date"].to_numpy(dtype="datetime64[D]")
        residual = (group["finish_position"].le(3).astype(float)
                    - 3.0 / group["field_n"].astype(float)).to_numpy(dtype=float)
        result[str(rider_id)] = {
            "dates": dates,
            "residual_cum": np.concatenate(([0.0], np.cumsum(residual))),
            "count_cum": np.arange(len(group) + 1, dtype=np.int64),
        }
    return result


def rider365_value(index: dict[str, dict[str, Any]], rider_id: Any,
                   cutoff: np.datetime64) -> tuple[int, float]:
    key = normalized_id(rider_id)
    if not valid_rider_id(key) or key not in index:
        return 0, 0.0
    values = index[key]
    lower_exclusive = cutoff - np.timedelta64(365, "D")
    left = int(np.searchsorted(values["dates"], lower_exclusive, side="right"))
    right = int(np.searchsorted(values["dates"], cutoff, side="right"))
    count = int(values["count_cum"][right] - values["count_cum"][left])
    total = float(values["residual_cum"][right] - values["residual_cum"][left])
    return count, total / (count + RIDER_PSEUDO_STARTS)


def main() -> None:
    require(not OUTPUT_RECEIPT.exists() and not OUTPUT_RUNNERS.exists() and not OUTPUT_PAIRS.exists(),
            "refusing to overwrite independent audit outputs")

    input_paths = [DB, SNAPSHOT, SELECTED_STARTS, FEATURES, BASELINE_PAIR_PREDICTIONS, UPSTREAM_SOURCE_AUDIT]
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in input_paths}
    upstream = json.loads(UPSTREAM_SOURCE_AUDIT.read_text(encoding="utf-8"))
    upstream_db_hash = upstream["input_hashes"]["jeju/data/jeju_native_core.sqlite3"]["sha256"]

    snapshot_columns = ["api_record_id", "race_id", "race_date", "meet_code", "race_number", "horse_id",
                        "horse_number", "race_distance_m", "finish_position", "started"]
    snapshot = pd.read_parquet(checked(SNAPSHOT), columns=snapshot_columns)
    require(snapshot["api_record_id"].notna().all() and snapshot["api_record_id"].is_unique,
            "full source snapshot API IDs missing or duplicate")
    snapshot["api_record_id"] = pd.to_numeric(snapshot["api_record_id"], errors="raise").astype("int64")
    snapshot["race_date"] = pd.to_datetime(snapshot["race_date"], errors="raise").dt.normalize()
    snapshot["horse_id"] = snapshot["horse_id"].astype("string")
    finish = pd.to_numeric(snapshot["finish_position"], errors="coerce")
    recomputed_started = finish.between(1, 89) | finish.isin([91, 92])
    cached_started = snapshot["started"].astype("boolean")
    started_mismatch = int((cached_started != recomputed_started).fillna(True).sum())
    require(started_mismatch == 0, "cached started flag differs from inherited result-code definition")
    started = snapshot.loc[recomputed_started].copy()
    started["race_date"] = pd.to_datetime(started["race_date"]).dt.normalize()
    started["horse_id"] = started["horse_id"].astype("string")

    database_rows = event_source_rows(started)
    database_rows["race_date"] = pd.to_datetime(database_rows["race_date"], errors="coerce").dt.normalize()
    database_rows["horse_id"] = database_rows["horse_id"].astype("string")
    database_rows["race_id_derived"] = (
        database_rows["race_date"].dt.strftime("%Y-%m-%d") + "_"
        + pd.to_numeric(database_rows["meet_code"], errors="raise").astype("int64").astype(str) + "_"
        + pd.to_numeric(database_rows["race_number"], errors="raise").astype("int64").astype(str)
    )
    joined = started.merge(database_rows, on="api_record_id", how="left", suffixes=("_snapshot", "_db"),
                           indicator=True, validate="one_to_one")
    require(joined["_merge"].eq("both").all(), "started snapshot API key missing from race_result_rows")
    comparison_columns = ["race_date", "meet_code", "race_number", "horse_number", "horse_id",
                          "race_distance_m", "finish_position"]
    mismatch_counts: dict[str, int] = {}
    for column in comparison_columns:
        left = joined[f"{column}_snapshot"]
        right = joined[f"{column}_db"]
        if column in {"meet_code", "race_number", "horse_number", "race_distance_m", "finish_position"}:
            left = pd.to_numeric(left, errors="coerce")
            right = pd.to_numeric(right, errors="coerce")
        unequal = left.ne(right) & ~(left.isna() & right.isna())
        mismatch_counts[column] = int(unequal.sum())
    mismatch_counts["race_id_derived"] = int((
        joined["race_id"].astype("string") != joined["race_id_derived"].astype("string")
    ).sum())
    require(all(count == 0 for count in mismatch_counts.values()), "source snapshot/base race row key mismatch")
    joined["jockey_id"] = joined["jockey_id"].astype("string").str.strip()
    joined.loc[joined["jockey_id"].eq(""), "jockey_id"] = pd.NA
    joined["jockey_id_valid"] = joined["jockey_id"].map(valid_rider_id)

    selected = pd.read_csv(checked(SELECTED_STARTS), dtype={
        "api_record_id": "string", "race_id": "string", "horse_id": "string", "jockey_id": "string"
    }, usecols=["api_record_id", "race_id", "race_date", "horse_id", "field_n", "finish_position", "jockey_id"])
    selected["api_record_id"] = pd.to_numeric(selected["api_record_id"], errors="raise").astype("int64")
    selected["race_date"] = pd.to_datetime(selected["race_date"], errors="raise").dt.normalize()
    selected["horse_id"] = selected["horse_id"].astype("string")
    selected["jockey_id"] = selected["jockey_id"].astype("string").str.strip()
    require(selected["api_record_id"].is_unique and selected["jockey_id"].map(valid_rider_id).all(),
            "selected rider-performance cache has duplicate keys or invalid IDs")
    selected_event = selected[["api_record_id", "jockey_id"]].merge(
        joined[["api_record_id", "jockey_id"]], on="api_record_id", how="left",
        suffixes=("_selected", "_source"), validate="one_to_one", indicator=True)
    require(selected_event["_merge"].eq("both").all(), "selected rider cache ID missing from full source join")
    selected_id_mismatch = int((selected_event["jockey_id_selected"] != selected_event["jockey_id_source"]).sum())
    require(selected_id_mismatch == 0, "selected cache event rider differs from official source join")
    for column in ("finish_position", "field_n"):
        selected[column] = pd.to_numeric(selected[column], errors="raise")
    rider_index = rider365_index(selected)

    target_columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
                      "history_cutoff", "previous_start_id"]
    targets = pd.read_parquet(checked(FEATURES), columns=target_columns)
    targets["api_record_id"] = pd.to_numeric(targets["api_record_id"], errors="raise").astype("int64")
    targets["race_id"] = targets["race_id"].astype("string")
    targets["race_date"] = pd.to_datetime(targets["race_date"], errors="raise").dt.normalize()
    targets["history_cutoff"] = pd.to_datetime(targets["history_cutoff"], errors="raise").dt.normalize()
    targets["horse_id"] = targets["horse_id"].astype("string")
    targets["previous_start_id"] = pd.to_numeric(targets["previous_start_id"], errors="coerce").astype("Int64")
    require(targets["api_record_id"].is_unique, "frozen feature runner API key is not unique")
    targets = targets.loc[targets["year"].between(2019, 2026)].copy()
    require(len(targets) > 0, "no 2019–2026 target runner rows")
    require((targets["history_cutoff"] == targets["race_date"] - pd.Timedelta(days=2)).all(),
            "target cutoff is not race_date minus two calendar days")
    current_ids = joined.set_index("api_record_id")["jockey_id"].to_dict()

    full_started = joined[["api_record_id", "race_date_snapshot", "horse_id_snapshot", "horse_number_snapshot",
                           "race_id", "race_number_snapshot", "jockey_id", "jockey_id_valid"]].copy()
    full_started = full_started.rename(columns={
        "race_date_snapshot": "race_date", "horse_id_snapshot": "horse_id",
        "horse_number_snapshot": "horse_number", "race_number_snapshot": "race_number",
    })
    full_started["race_date"] = pd.to_datetime(full_started["race_date"]).dt.normalize()
    full_started["horse_id"] = full_started["horse_id"].astype("string")
    full_started["api_record_id"] = pd.to_numeric(full_started["api_record_id"], errors="raise").astype("int64")
    full_started["jockey_id"] = full_started["jockey_id"].astype("string")
    full_started["jockey_id_valid"] = full_started["jockey_id_valid"].astype(bool)
    history_by_horse = index_history(full_started)
    selected_history = index_history(selected.rename(columns={"jockey_id": "jockey_id"}))

    horse_day_counts = full_started.groupby(["horse_id", "race_date"], dropna=False).size()
    multiple_horse_days = horse_day_counts[horse_day_counts.gt(1)]
    target_output: list[dict[str, Any]] = []
    for row in targets.itertuples(index=False):
        horse_id = str(row.horse_id)
        target_date = date_np(row.race_date)
        cutoff = date_np(row.history_cutoff)
        current_id = normalized_id(current_ids.get(int(row.api_record_id)))
        current_valid = valid_rider_id(current_id)
        horse_info = history_by_horse.get(horse_id)
        past_n = 0
        horse_pair_n = 0
        last_pair_date: np.datetime64 | None = None
        tminus1_count = 0
        previous_row: pd.Series | None = None
        previous_ambiguous_n = 0
        actual_previous_row: pd.Series | None = None
        actual_previous_ambiguous_n = 0
        if horse_info is not None:
            horse_dates = horse_info["dates"]
            horse_frame = horse_info["frame"]
            past_n = int(np.searchsorted(horse_dates, cutoff, side="right"))
            previous_row, previous_ambiguous_n = last_asof(horse_info, cutoff)
            actual_previous_row, actual_previous_ambiguous_n = last_strictly_before(horse_info, target_date)
            tminus1 = target_date - np.timedelta64(1, "D")
            tminus1_left = int(np.searchsorted(horse_dates, tminus1, side="left"))
            tminus1_right = int(np.searchsorted(horse_dates, tminus1, side="right"))
            tminus1_count = tminus1_right - tminus1_left
            if current_valid and past_n > 0:
                past_frame = horse_frame.iloc[:past_n]
                same = past_frame.loc[past_frame["jockey_id"].eq(current_id)
                                      & past_frame["jockey_id_valid"]]
                horse_pair_n = int(len(same))
                if horse_pair_n:
                    last_pair_date = date_np(same["race_date"].max())

        previous_id = normalized_id(previous_row["jockey_id"]) if previous_row is not None else None
        previous_id_valid = valid_rider_id(previous_id)
        if current_valid:
            current_n, current_r = rider365_value(rider_index, current_id, cutoff)
        else:
            current_n, current_r = 0, 0.0
        if previous_id_valid:
            previous_n, previous_r = rider365_value(rider_index, previous_id, cutoff)
        else:
            previous_n, previous_r = 0, 0.0
        delta_available = bool(current_valid and previous_id_valid and current_n > 0 and previous_n > 0)
        delta_raw = float(current_r - previous_r) if delta_available else None
        if previous_row is None:
            previous_source_id = None
            previous_date = None
            previous_rider_id = None
        else:
            previous_source_id = int(previous_row["api_record_id"])
            previous_date = pd.Timestamp(previous_row["race_date"]).date().isoformat()
            previous_rider_id = previous_id
        selected_previous, selected_tie_n = last_asof(selected_history.get(horse_id), cutoff)
        selected_previous_id = int(selected_previous["api_record_id"]) if selected_previous is not None else None
        feature_previous_id = int(row.previous_start_id) if pd.notna(row.previous_start_id) else None
        if last_pair_date is None:
            pair_recency = None
        else:
            pair_recency = int((cutoff - last_pair_date).astype("timedelta64[D]").astype(int))
        target_output.append({
            "api_record_id": int(row.api_record_id), "race_id": str(row.race_id),
            "race_date": pd.Timestamp(row.race_date).date().isoformat(),
            "history_cutoff": pd.Timestamp(row.history_cutoff).date().isoformat(),
            "horse_id": horse_id, "horse_number": int(row.horse_number),
            "current_jockey_id": current_id, "current_jockey_id_valid": current_valid,
            "previous_started_api_record_id_asof_t2": previous_source_id,
            "previous_started_date_asof_t2": previous_date,
            "previous_jockey_id_asof_t2": previous_rider_id,
            "previous_jockey_id_valid": previous_id_valid,
            "previous_start_ambiguous_same_day_count": previous_ambiguous_n if previous_row is None else 0,
            "feature_previous_start_id": feature_previous_id,
            "feature_prev_id_matches_full_source": feature_previous_id == previous_source_id,
            "selected_cohort_previous_start_id": selected_previous_id,
            "selected_cohort_previous_tie_count": selected_tie_n if selected_previous is None else 0,
            "selected_prev_equals_full_prev": selected_previous_id == previous_source_id,
            "actual_immediate_previous_api_record_id": int(actual_previous_row["api_record_id"]) if actual_previous_row is not None else None,
            "actual_immediate_previous_date": pd.Timestamp(actual_previous_row["race_date"]).date().isoformat() if actual_previous_row is not None else None,
            "actual_previous_ambiguous_same_day_count": actual_previous_ambiguous_n if actual_previous_row is None else 0,
            "tminus1_started_count": int(tminus1_count),
            "asof_t2_previous_differs_from_actual_previous": bool(
                actual_previous_row is not None and previous_source_id != int(actual_previous_row["api_record_id"])),
            "previous_rider_retained": bool(current_valid and previous_id_valid and current_id == previous_id),
            "previous_rider_unknown": bool(not current_valid or not previous_id_valid),
            "rider365_current_n": int(current_n), "rider365_previous_n": int(previous_n),
            "rider365_current_R": float(current_r), "rider365_previous_R": float(previous_r),
            "rider365_delta_raw": delta_raw,
            "rider365_delta_feature_value": delta_raw if delta_raw is not None else 0.0,
            "rider365_delta_unavailable": not delta_available,
            "horse_past_started_n_asof_t2": int(past_n),
            "horse_current_rider_past_started_n": int(horse_pair_n),
            "horse_current_rider_recency_days_asof_t2": pair_recency,
            "horse_current_rider_first_observed": bool(past_n > 0 and current_valid and horse_pair_n == 0),
            "horse_current_rider_history_unavailable": bool(past_n == 0 or not current_valid),
        })

    runner_features = pd.DataFrame(target_output)
    evaluation_runners = runner_features.loc[runner_features["race_date"].str[:4].astype(int).between(2024, 2026)].copy()
    require(len(evaluation_runners) == 17_412, "evaluation runner roster differs from pinned 2024–2026 cohort")
    require(evaluation_runners["race_id"].nunique() == 1_779, "evaluation race roster differs from pinned cohort")
    require(evaluation_runners["race_date"].nunique() == 269, "evaluation date roster differs from pinned cohort")

    pairs = pd.read_parquet(checked(BASELINE_PAIR_PREDICTIONS), columns=[
        "race_id", "race_date", "evaluation_year", "horse_i", "horse_j"
    ])
    pairs["race_id"] = pairs["race_id"].astype("string")
    pairs["race_date"] = pd.to_datetime(pairs["race_date"], errors="raise").dt.strftime("%Y-%m-%d")
    pairs["horse_i"] = pd.to_numeric(pairs["horse_i"], errors="raise").astype(int)
    pairs["horse_j"] = pd.to_numeric(pairs["horse_j"], errors="raise").astype(int)
    require(len(pairs) == 76_848 and not pairs.duplicated(["race_id", "horse_i", "horse_j"]).any(),
            "pinned evaluation unordered-pair roster differs")
    by_race_number = runner_features.set_index(["race_id", "horse_number"], drop=False)
    pair_features: list[dict[str, Any]] = []
    pair_columns = [
        "previous_rider_retained_count", "previous_rider_unknown_count", "rider365_delta_sum",
        "rider365_current_support_log1p_sum", "rider365_previous_support_log1p_sum",
        "rider365_delta_unavailable_count", "horse_current_rider_rides_log1p_sum",
        "horse_current_rider_recency_log1p_sum", "horse_current_rider_first_observed_pair_count",
        "horse_current_rider_history_unavailable_count",
    ]
    for pair in pairs.itertuples(index=False):
        key_i = (str(pair.race_id), int(pair.horse_i))
        key_j = (str(pair.race_id), int(pair.horse_j))
        require(key_i in by_race_number.index and key_j in by_race_number.index, "pair roster runner key missing")
        left = by_race_number.loc[key_i]
        right = by_race_number.loc[key_j]
        if isinstance(left, pd.DataFrame) or isinstance(right, pd.DataFrame):
            raise AuditError("duplicate race/horse-number runner key")
        values = {
            "previous_rider_retained_count": int(left["previous_rider_retained"]) + int(right["previous_rider_retained"]),
            "previous_rider_unknown_count": int(left["previous_rider_unknown"]) + int(right["previous_rider_unknown"]),
            "rider365_delta_sum": float(left["rider365_delta_feature_value"]) + float(right["rider365_delta_feature_value"]),
            "rider365_current_support_log1p_sum": math.log1p(int(left["rider365_current_n"])) + math.log1p(int(right["rider365_current_n"])),
            "rider365_previous_support_log1p_sum": math.log1p(int(left["rider365_previous_n"])) + math.log1p(int(right["rider365_previous_n"])),
            "rider365_delta_unavailable_count": int(left["rider365_delta_unavailable"]) + int(right["rider365_delta_unavailable"]),
            "horse_current_rider_rides_log1p_sum": math.log1p(int(left["horse_current_rider_past_started_n"])) + math.log1p(int(right["horse_current_rider_past_started_n"])),
            "horse_current_rider_recency_log1p_sum": math.log1p(int(left["horse_current_rider_recency_days_asof_t2"]) if pd.notna(left["horse_current_rider_recency_days_asof_t2"]) else 0) + math.log1p(int(right["horse_current_rider_recency_days_asof_t2"]) if pd.notna(right["horse_current_rider_recency_days_asof_t2"]) else 0),
            "horse_current_rider_first_observed_pair_count": int(left["horse_current_rider_first_observed"]) + int(right["horse_current_rider_first_observed"]),
            "horse_current_rider_history_unavailable_count": int(left["horse_current_rider_history_unavailable"]) + int(right["horse_current_rider_history_unavailable"]),
        }
        pair_features.append({
            "race_id": str(pair.race_id), "race_date": str(pair.race_date),
            "evaluation_year": int(pair.evaluation_year), "horse_i": int(pair.horse_i),
            "horse_j": int(pair.horse_j), **values,
        })
    pair_feature_frame = pd.DataFrame(pair_features)
    require(pair_feature_frame[pair_columns].apply(np.isfinite).all().all(), "non-finite pair feature value")

    sentinel_counts = Counter(joined["jockey_id"].dropna().astype(str).tolist())
    repeated_digit_ids = sorted(value for value in sentinel_counts
                                if len(value) == 6 and len(set(value)) == 1)
    horse_day_diagnostic = {
        "horse_day_groups": int(len(horse_day_counts)),
        "groups_with_multiple_started_events": int(len(multiple_horse_days)),
        "rows_in_multiple_event_groups": int(multiple_horse_days.sum()),
        "multiple_event_race_ids": int(sum(
            full_started.groupby(["horse_id", "race_date"], dropna=False)["race_id"].nunique()
            .reindex(multiple_horse_days.index).fillna(0).gt(1)
        )),
    }
    row_metrics = {
        "unique_target_runners_2019_2026": int(len(runner_features)),
        "evaluation_target_runners_2024_2026": int(len(evaluation_runners)),
        "evaluation_target_races": int(evaluation_runners["race_id"].nunique()),
        "evaluation_target_dates": int(evaluation_runners["race_date"].nunique()),
        "evaluation_tminus1_started_rows": int(evaluation_runners["tminus1_started_count"].gt(0).sum()),
        "evaluation_tminus1_extra_started_events": int(
            (evaluation_runners["tminus1_started_count"] - 1).clip(lower=0).sum()),
        "evaluation_tminus1_rows_within_asof_t2_roster": 0,
        "evaluation_asof_t2_previous_differs_from_actual_previous": int(
            evaluation_runners["asof_t2_previous_differs_from_actual_previous"].sum()),
        "evaluation_full_previous_id_mismatches_vs_frozen_feature": int(
            (~evaluation_runners["feature_prev_id_matches_full_source"]).sum()),
        "evaluation_selected_prev_differs_from_full_prev": int(
            (~evaluation_runners["selected_prev_equals_full_prev"]).sum()),
        "evaluation_selected_prev_missing_but_full_prev_present": int((
            evaluation_runners["selected_cohort_previous_start_id"].isna()
            & evaluation_runners["previous_started_api_record_id_asof_t2"].notna()).sum()),
        "evaluation_previous_asof_t2_unavailable": int(
            evaluation_runners["previous_started_api_record_id_asof_t2"].isna().sum()),
        "evaluation_actual_previous_ambiguous_same_day": int(
            evaluation_runners["actual_previous_ambiguous_same_day_count"].gt(1).sum()),
        "evaluation_asof_t2_previous_ambiguous_same_day": int(
            evaluation_runners["previous_start_ambiguous_same_day_count"].gt(1).sum()),
        "evaluation_current_event_jockey_invalid_or_sentinel": int(
            (~evaluation_runners["current_jockey_id_valid"]).sum()),
        "evaluation_previous_rider_unknown": int(evaluation_runners["previous_rider_unknown"].sum()),
        "evaluation_rider365_delta_unavailable": int(evaluation_runners["rider365_delta_unavailable"].sum()),
        "evaluation_horse_current_rider_history_unavailable": int(
            evaluation_runners["horse_current_rider_history_unavailable"].sum()),
        "evaluation_horse_current_rider_first_observed": int(
            evaluation_runners["horse_current_rider_first_observed"].sum()),
        "evaluation_horse_current_rider_repeat_observed": int(
            evaluation_runners["horse_current_rider_past_started_n"].gt(0).sum()),
        "evaluation_max_horse_current_rider_past_started_n": int(
            evaluation_runners["horse_current_rider_past_started_n"].max()),
        "evaluation_recency_min_days_asof_t2": int(
            evaluation_runners["horse_current_rider_recency_days_asof_t2"].dropna().min()),
        "evaluation_recency_max_days_asof_t2": int(
            evaluation_runners["horse_current_rider_recency_days_asof_t2"].dropna().max()),
    }

    # H1/H2/evaluation may reuse an event in distinct pair-fold roles. These event-level
    # features are invariant by event key; folds and provider roles remain outside this file.
    receipt = {
        "status": "PASS" if (
            started_mismatch == 0 and all(v == 0 for v in mismatch_counts.values())
            and selected_id_mismatch == 0 and row_metrics["evaluation_full_previous_id_mismatches_vs_frozen_feature"] == 0
        ) else "FAIL",
        "scope": "independent read-only source join and candidate input feature calculation; no fit/prediction",
        "target_finish_labels_read_from_frozen_feature_roster": False,
        "historical_finish_results_read_for_input_features": True,
        "historical_result_usage": "started membership is recomputed from the full source finish_position field; selected prior starts supply Top3 residual outcomes; target histories are cutoff at T-2 and target outcomes do not enter their own features",
        "target_outcome_used_as_feature": False,
        "fit_or_prediction_work": False,
        "database_write": False,
        "database_connection": {"uri_mode_ro": True, "pragma_query_only": True,
                                 "query": "parameterized api_record_id batches; SELECT from race_result_rows only"},
        "source_hashes": hashes,
        "audit_code_sha256": sha256(Path(__file__).resolve()),
        "database_sha256_from_upstream_read_only_audit": upstream_db_hash,
        "snapshot": {
            "rows": int(len(snapshot)), "started_rows": int(len(started)),
            "started_definition": "finish_position 1..89 or 91 or 92",
            "full_finish_position_column_read": True,
            "finish_position_usage": "recompute started membership for source history; selected historical starts also supply Top3 outcomes for rider365 residuals; each target feature history is cutoff at T-2",
            "target_finish_position_used_as_feature": False,
            "cached_started_flag_mismatch_rows": started_mismatch,
            "all_row_date_min": snapshot["race_date"].min().date().isoformat(),
            "all_row_date_max": snapshot["race_date"].max().date().isoformat(),
            "started_date_min": started["race_date"].min().date().isoformat(),
            "started_date_max": started["race_date"].max().date().isoformat(),
            "started_2017_plus": int((started["race_date"].dt.year >= 2017).sum()),
            "started_pre_2017": int((started["race_date"].dt.year < 2017).sum()),
            "jockey_id_column_in_snapshot": "jockey_id" in snapshot.columns,
        },
        "event_jockey_join": {
            "snapshot_started_rows": int(len(started)),
            "joined_rows": int(joined["_merge"].eq("both").sum()),
            "missing_rows": int(joined["_merge"].ne("both").sum()),
            "duplicate_database_api_ids": int(database_rows["api_record_id"].duplicated().sum()),
            "core_key_mismatches": mismatch_counts,
            "jockey_id_missing": int(joined["jockey_id"].isna().sum()),
            "jockey_id_non_six_digit": int((joined["jockey_id"].notna()
                                              & ~joined["jockey_id"].str.fullmatch(r"[0-9]{6}", na=False)).sum()),
            "jockey_id_unique_values": int(joined["jockey_id"].nunique(dropna=True)),
            "sentinel_candidate_counts": {value: int(sentinel_counts.get(value, 0)) for value in sorted(KNOWN_SENTINELS)},
            "all_repeated_digit_id_counts": {value: int(sentinel_counts[value]) for value in repeated_digit_ids},
            "unknown_id_policy": "missing, 000000 and 999999 treated unknown in independent features; both candidate sentinel values reported explicitly",
            "selected_starts_rows": int(len(selected)),
            "selected_starts_to_official_event_id_mismatches": selected_id_mismatch,
        },
        "horse_day_diagnostic": horse_day_diagnostic,
        "feature_recalculation": {
            "target_source": "frozen STYLE feature keys for 2019–2026; target finish_position column not requested from that table",
            "historical_finish_results_read_for_input_features": True,
            "target_outcome_used_as_feature": False,
            "history_source": "all 90,428 started source_snapshot rows joined to official race_result_rows.jockey_id",
            "prior_start_rule": "latest unique started event for the horse with race_date <= target_date-2 calendar days; same-day ties marked ambiguous and not arbitrarily resolved",
            "rider365_rule": "selected 52,155-start cache; (T-2-365 days, T-2], field-relative Top3 residual/(n+20); unavailable if either rider ID is invalid or either n=0",
            "experience_rule": "all started source history through T-2 for same horse and current valid event rider; recency is T-2 minus last matching started date",
            "row_metrics": row_metrics,
            "evaluation_pair_rows": int(len(pair_feature_frame)),
            "evaluation_pair_columns": pair_columns,
            "evaluation_pair_nonfinite_values": int((~np.isfinite(pair_feature_frame[pair_columns].to_numpy(dtype=float))).sum()),
        },
        "artifact_paths": {
            "independent_runner_features": str(OUTPUT_RUNNERS.relative_to(ROOT)),
            "independent_evaluation_pair_features": str(OUTPUT_PAIRS.relative_to(ROOT)),
        },
        "artifact_sha256": {
            "independent_runner_features": None,
            "independent_evaluation_pair_features": None,
        },
    }

    require(not OUTPUT_RUNNERS.exists() and not OUTPUT_PAIRS.exists(), "refusing to overwrite feature audit files")
    runner_features.to_parquet(OUTPUT_RUNNERS, index=False)
    pair_feature_frame.to_parquet(OUTPUT_PAIRS, index=False)
    receipt["artifact_sha256"]["independent_runner_features"] = sha256(OUTPUT_RUNNERS)
    receipt["artifact_sha256"]["independent_evaluation_pair_features"] = sha256(OUTPUT_PAIRS)
    with OUTPUT_RECEIPT.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({
        "status": receipt["status"], "source_join": receipt["event_jockey_join"],
        "horse_day_diagnostic": horse_day_diagnostic, "feature_recalculation": receipt["feature_recalculation"],
        "receipt": str(OUTPUT_RECEIPT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
