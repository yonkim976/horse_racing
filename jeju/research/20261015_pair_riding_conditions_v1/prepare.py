"""Freeze official started-event rider IDs and build label-safe runner conditions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from riding_conditions_basis import PAIR_COLUMNS, RUNNER_COLUMNS, fit_race_equal_moments


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261015_pair_riding_conditions_v1"
OUT = STUDY / "outputs"
FEATURE_OUT = STUDY / "outputs_prefit_v2"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
SNAPSHOT_RETRY = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/PREPARATION_RETRY.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STARTS = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
BASE_INPUT = ROOT / "jeju/research/20261012_pair_jockey_basic_v1/jockey_input.py"
ID_PREDICTIONS = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
SOURCE_LOCK = STUDY / "SOURCE_HASHES.json"
SOURCE_CACHE = OUT / "source_started_event_rider.parquet"
SOURCE_CACHE_RECEIPT = OUT / "SOURCE_CACHE_RECEIPT.json"
RUNNER_BASIS = FEATURE_OUT / "riding_conditions_runner_basis.parquet"
PREFLIGHT = FEATURE_OUT / "FEATURE_PREFLIGHT.json"
DRY_RUN = FEATURE_OUT / "DESIGN_DRY_RUN.json"
EXPECTED_STARTED = 90428
EXPECTED_TARGET_ROWS = 42690
EXPECTED_EVAL_ROWS = 17412
EXPECTED_EVAL_RACES = 1779
EXPECTED_EVAL_DATES = 269
EXPECTED_H1 = {2024: 2147, 2025: 2818, 2026: 3458}
EXPECTED_H2 = {2024: 336, 2025: 311, 2026: 325}
UNKNOWN_IDS = {"000000", "999999"}


class PrepareError(RuntimeError):
    """Raised when a pinned source or feature contract is violated."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PrepareError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink input is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def output_path(path: Path) -> Path:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink(), f"symlink output is not allowed: {path}")
    return path


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    path = output_path(path)
    require(not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    path = output_path(path)
    require(not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot import pinned helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_source_lock() -> dict[str, str]:
    lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    require(lock.get("status") == "PINNED_SOURCE_FILES", "source lock status changed")
    hashes = {str(row["path"]): str(row["sha256"]) for row in lock.get("sources", [])}
    require(len(hashes) == int(lock.get("source_count", -1)), "source lock is incomplete or duplicate")
    return hashes


def verify_pinned_sources(*, skip_database: bool) -> dict[str, str]:
    hashes = load_source_lock()
    verified = {}
    for relative, expected in sorted(hashes.items()):
        path = ROOT / relative
        if skip_database and path == DB:
            continue
        observed = sha256(checked(path))
        require(observed == expected, f"pinned source changed: {relative}")
        verified[relative] = observed
    return verified


def canonical_rider_id(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if len(text) != 6 or not text.isascii() or not text.isdigit():
        return None
    return text


def build_started_event_rider_cache() -> dict[str, Any]:
    cache_exists = SOURCE_CACHE.exists()
    receipt_exists = SOURCE_CACHE_RECEIPT.exists()
    require(cache_exists == receipt_exists,
            "event-rider cache/receipt are only partially present; inspect before continuing")
    if cache_exists:
        receipt = json.loads(checked(SOURCE_CACHE_RECEIPT).read_text(encoding="utf-8"))
        require(receipt.get("status") == "PASS", "event-rider cache receipt is not PASS")
        require(receipt.get("database_sha256_at_extraction") == load_source_lock().get(str(DB.relative_to(ROOT))),
                "event-rider cache receipt does not match the pinned extraction database hash")
        require(receipt.get("source_lock_sha256") == sha256(checked(SOURCE_LOCK)),
                "event-rider cache receipt was built against another source lock")
        require(receipt.get("snapshot_sha256") == sha256(checked(SNAPSHOT)),
                "source snapshot changed after event-rider cache extraction")
        require(sha256(checked(SOURCE_CACHE)) == receipt.get("cache_sha256"),
                "event-rider cache hash differs from its receipt")
        frame = pd.read_parquet(checked(SOURCE_CACHE))
        require(len(frame) == EXPECTED_STARTED and frame["api_record_id"].is_unique,
                "event-rider cache row contract changed")
        return receipt

    require(not SOURCE_CACHE.exists() and not SOURCE_CACHE_RECEIPT.exists(),
            "refusing to replace an existing event-rider cache")
    pinned = load_source_lock()
    expected_database_hash = pinned.get(str(DB.relative_to(ROOT)))
    require(expected_database_hash, "database hash is missing from source lock")
    # Hash the large database once at cache creation. Later steps use the immutable
    # event-rider cache and never reconnect to the shared database.
    database_hash = sha256(checked(DB))
    require(database_hash == expected_database_hash,
            "database changed after the initial source audit; stop and reconcile before extraction")
    database_stat_before = DB.stat()

    source = pd.read_parquet(checked(SNAPSHOT))
    expected_started = (pd.to_numeric(source["finish_position"], errors="coerce").between(1, 89)
                        | pd.to_numeric(source["finish_position"], errors="coerce").isin([91, 92]))
    require(source["api_record_id"].is_unique, "source snapshot api_record_id is not unique")
    require(expected_started.equals(source["started"].astype(bool)), "snapshot started flag changed")
    started = source.loc[expected_started, [
        "api_record_id", "race_id", "race_date", "meet_code", "race_number", "horse_id",
        "horse_number", "race_distance_m", "finish_position",
    ]].copy()
    require(len(started) == EXPECTED_STARTED, "started source row count changed")
    started["api_record_id"] = pd.to_numeric(started["api_record_id"], errors="raise").astype("int64")
    started["race_date"] = pd.to_datetime(started["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(started["race_date"].notna().all(), "started source date is invalid")
    started["horse_id"] = started["horse_id"].astype("string")
    started["race_id"] = started["race_id"].astype("string")

    database_uri = checked(DB).as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        query_only = int(connection.execute("PRAGMA query_only").fetchone()[0])
        require(query_only == 1, "SQLite query_only could not be enabled")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        require(journal_mode == "delete", "unexpected SQLite journal mode; stop before event extraction")
        connection.execute("BEGIN")
        db_rows: list[tuple[Any, ...]] = []
        ids = started["api_record_id"].astype("int64").tolist()
        for offset in range(0, len(ids), 500):
            chunk = ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            statement = (
                "SELECT api_record_id, race_date, meet_code, race_number, horse_id, horse_number, "
                "race_distance_m, finish_position, jockey_id "
                f"FROM race_result_rows WHERE api_record_id IN ({placeholders})"
            )
            db_rows.extend(connection.execute(statement, tuple(chunk)).fetchall())
    finally:
        connection.close()
    database_stat_after = DB.stat()
    require((database_stat_before.st_dev, database_stat_before.st_ino, database_stat_before.st_size,
             database_stat_before.st_mtime_ns) ==
            (database_stat_after.st_dev, database_stat_after.st_ino, database_stat_after.st_size,
             database_stat_after.st_mtime_ns), "database file changed during read-only event extraction")

    native = pd.DataFrame.from_records(db_rows, columns=[
        "api_record_id", "race_date", "meet_code", "race_number", "horse_id", "horse_number",
        "race_distance_m", "finish_position", "jockey_id_native",
    ])
    native["api_record_id"] = pd.to_numeric(native["api_record_id"], errors="raise").astype("int64")
    require(native["api_record_id"].is_unique, "native API id is duplicated for started events")
    native["race_date"] = pd.to_datetime(native["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    native["horse_id"] = native["horse_id"].astype("string")
    native["race_id"] = (
        native["race_date"].astype("string") + "_" +
        pd.to_numeric(native["meet_code"], errors="raise").astype("int64").astype("string") + "_" +
        pd.to_numeric(native["race_number"], errors="raise").astype("int64").astype("string")
    )
    native["event_jockey_id"] = native["jockey_id_native"].map(canonical_rider_id).astype("string")
    joined = started.merge(
        native[["api_record_id", "race_date", "race_id", "horse_id", "horse_number", "race_distance_m",
                "finish_position", "event_jockey_id"]],
        how="left", on="api_record_id", validate="one_to_one", indicator=True, suffixes=("", "_native"),
    )
    require(joined["_merge"].eq("both").all() and len(joined) == EXPECTED_STARTED,
            "started source is missing an official native event row")
    comparisons = {}
    for column in ("race_date", "race_id", "horse_id", "horse_number", "race_distance_m", "finish_position"):
        left = joined[column]
        right = joined[f"{column}_native"]
        if column == "race_distance_m":
            a = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
            equal = (a == b) | (np.isnan(a) & np.isnan(b))
        elif column in {"horse_number", "finish_position"}:
            a = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
            equal = (a == b) | (np.isnan(a) & np.isnan(b))
        else:
            equal = left.astype("string").eq(right.astype("string")).fillna(False).to_numpy()
        comparisons[column] = int((~equal).sum())
    require(all(value == 0 for value in comparisons.values()),
            f"source/native key mismatch: {comparisons}")
    rider_ids = joined["event_jockey_id"].astype("string")
    invalid_rider = rider_ids.isna() | ~rider_ids.str.fullmatch(r"\d{6}").fillna(False)
    cache = joined.loc[:, [
        "api_record_id", "race_id", "race_date", "horse_id", "horse_number", "race_distance_m",
        "finish_position", "event_jockey_id",
    ]].copy()
    cache["api_record_id"] = cache["api_record_id"].astype("int64").astype("string")
    cache["horse_number"] = pd.to_numeric(cache["horse_number"], errors="raise").astype("int16")
    cache["finish_position"] = pd.to_numeric(cache["finish_position"], errors="raise").astype("int16")
    cache["race_id"] = cache["race_id"].astype("string")
    cache["race_date"] = cache["race_date"].astype("string")
    cache["horse_id"] = cache["horse_id"].astype("string")
    cache["event_jockey_id"] = cache["event_jockey_id"].astype("string")
    write_parquet_once(SOURCE_CACHE, cache)
    receipt = {
        "status": "PASS",
        "scope": "one-time read-only event jockey extraction from started source snapshot",
        "database_path": str(DB.relative_to(ROOT)),
        "database_sha256_at_extraction": database_hash,
        "database_hash_passes_source_lock": True,
        "database_access": "SQLite URI mode=ro; PRAGMA query_only=ON; fixed SELECT; parameterized api_record_id batches",
        "database_journal_mode": journal_mode,
        "database_file_signature_stable_during_query": True,
        "original_snapshot_database_reference_sha256": json.loads(
            checked(SNAPSHOT_RETRY).read_text(encoding="utf-8")
        )["database_reference_sha256"],
        "snapshot_sha256": sha256(checked(SNAPSHOT)),
        "source_lock_sha256": sha256(checked(SOURCE_LOCK)),
        "source_rows": int(len(started)),
        "joined_rows": int(len(cache)),
        "one_to_one_api_record_id": bool(cache["api_record_id"].is_unique and len(cache) == len(started)),
        "key_mismatches": comparisons,
        "event_jockey_id_missing_or_invalid": int(invalid_rider.sum()),
        "event_jockey_id_sentinel_000000": int(rider_ids.eq("000000").sum()),
        "event_jockey_id_sentinel_999999": int(rider_ids.eq("999999").sum()),
        "cache_path": str(SOURCE_CACHE.relative_to(ROOT)),
        "cache_rows": int(len(cache)),
        "cache_sha256": sha256(checked(SOURCE_CACHE)),
        "prepare_code_sha256": sha256(checked(STUDY / "prepare.py")),
    }
    write_json_once(SOURCE_CACHE_RECEIPT, receipt)
    return receipt


def make_rider_prefixes(starts: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Prefix arrays for exact selected-starts rolling Top3 residuals."""
    frame = starts.loc[:, ["jockey_id", "race_date", "field_n", "finish_position", "api_record_id"]].copy()
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    frame["field_n"] = pd.to_numeric(frame["field_n"], errors="coerce")
    frame["finish_position"] = pd.to_numeric(frame["finish_position"], errors="coerce")
    require(frame["race_date"].notna().all() and frame["field_n"].ge(4).all(),
            "selected-start source date/field changed")
    frame = frame.sort_values(["jockey_id", "race_date", "api_record_id"], kind="mergesort")
    prefixes = {}
    for rider_id, group in frame.groupby("jockey_id", sort=False):
        dates = group["race_date"].to_numpy(dtype="datetime64[D]")
        top3 = group["finish_position"].to_numpy(dtype=float) <= 3.0
        expected = 3.0 / group["field_n"].to_numpy(dtype=float)
        prefixes[str(rider_id)] = (
            dates,
            np.concatenate(([0], np.cumsum(np.ones(len(group), dtype=np.int64)))),
            np.concatenate(([0], np.cumsum(top3.astype(np.int64)))),
            np.concatenate(([0.0], np.cumsum(expected, dtype=float))),
        )
    return prefixes


def rider365_value(prefixes, rider_id: str | None, cutoff: np.datetime64) -> tuple[int, float]:
    if rider_id is None or rider_id in UNKNOWN_IDS:
        return 0, 0.0
    values = prefixes.get(rider_id)
    if values is None:
        return 0, 0.0
    dates, counts, successes, expected = values
    lower_exclusive = cutoff - np.timedelta64(365, "D")
    left = int(np.searchsorted(dates, lower_exclusive, side="right"))
    right = int(np.searchsorted(dates, cutoff, side="right"))
    n = int(counts[right] - counts[left])
    if n == 0:
        return 0, 0.0
    value = float((successes[right] - successes[left] - (expected[right] - expected[left])) / (n + 20.0))
    return n, value


def is_valid_rider(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 6 and value.isascii()
            and value.isdigit() and value not in UNKNOWN_IDS)


def build_runner_basis(source_receipt: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(not RUNNER_BASIS.exists() and not PREFLIGHT.exists() and not DRY_RUN.exists(),
            "refusing to overwrite existing basis or preflight output")
    verified_sources = verify_pinned_sources(skip_database=True)
    helper = import_module("frozen_pair_jockey_input_for_riding_conditions", BASE_INPUT)
    require(sha256(checked(BASE_INPUT)) == verified_sources[str(BASE_INPUT.relative_to(ROOT))],
            "frozen base input helper changed")
    roster = helper.load_roster(years=tuple(range(2019, 2027)))
    starts = helper.load_starts(include_results=True)
    event = helper.attach_event_jockey(roster, starts)
    distance_rows = pd.read_parquet(checked(FEATURES), columns=["api_record_id", "distance_m"])
    distance_rows["api_record_id"] = distance_rows["api_record_id"].astype("string")
    event = event.merge(distance_rows, on="api_record_id", how="left", validate="one_to_one")
    require(event["distance_m"].notna().all(), "frozen roster has missing race distance")
    require(len(event) == EXPECTED_TARGET_ROWS and event["api_record_id"].is_unique,
            "frozen 2019–2026 target roster changed")
    require(event["horse_id"].astype("string").notna().all(), "target roster has missing horse ID")

    source = pd.read_parquet(checked(SOURCE_CACHE))
    require(len(source) == EXPECTED_STARTED and source["api_record_id"].is_unique,
            "frozen full-started event-rider source changed")
    source["api_record_id"] = source["api_record_id"].astype("string")
    source["horse_id"] = source["horse_id"].astype("string")
    source["race_date"] = pd.to_datetime(source["race_date"], errors="coerce").dt.normalize()
    source["event_jockey_id"] = source["event_jockey_id"].astype("string")
    require(source["race_date"].notna().all(), "full-history event date is invalid")
    current_map = source.set_index("api_record_id")["event_jockey_id"]
    current_id = event["jockey_id"].astype("string")
    source_id = event["api_record_id"].astype("string").map(current_map)
    mismatch = current_id.ne(source_id).fillna(True)
    require(not mismatch.any(), "selected current event rider differs from frozen full-started cache")

    history: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    sorted_history = source.sort_values(["horse_id", "race_date", "api_record_id"], kind="mergesort")
    for horse_id, group in sorted_history.groupby("horse_id", sort=False):
        dates = group["race_date"].to_numpy(dtype="datetime64[D]")
        riders = group["event_jockey_id"].astype("string").tolist()
        ids = group["api_record_id"].astype("string").tolist()
        history[str(horse_id)] = (dates, np.asarray(riders, dtype=object), np.asarray(ids, dtype=object))
    pair_history: dict[tuple[str, str], np.ndarray] = {}
    valid_history = source.loc[
        source["event_jockey_id"].map(is_valid_rider), ["horse_id", "event_jockey_id", "race_date"]
    ].sort_values(["horse_id", "event_jockey_id", "race_date"], kind="mergesort")
    for (horse_id, rider_id), group in valid_history.groupby(["horse_id", "event_jockey_id"], sort=False):
        pair_history[(str(horse_id), str(rider_id))] = group["race_date"].to_numpy(dtype="datetime64[D]")

    rider_prefixes = make_rider_prefixes(starts)
    rolling = helper.rolling_features(event, starts)
    rolling_by_api = rolling.set_index("api_record_id")
    rider_current_r = event["api_record_id"].map(rolling_by_api["jockey365_field_relative_top3"]).to_numpy(dtype=float)
    rider_current_n = event["api_record_id"].map(rolling_by_api["jockey365_n"]).to_numpy(dtype=np.int64)
    current_ids = current_id.tolist()
    horse_ids = event["horse_id"].astype("string").tolist()
    api_ids = event["api_record_id"].astype("string").tolist()
    dates = event["race_date"].to_numpy(dtype="datetime64[D]")

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(event.itertuples(index=False)):
        cutoff = dates[idx] - np.timedelta64(2, "D")
        horse = str(horse_ids[idx])
        curr = canonical_rider_id(current_ids[idx])
        if not is_valid_rider(curr):
            curr = None
        history_data = history.get(horse)
        previous_id = None
        previous_date = None
        previous_api_id = None
        horse_past_n = 0
        if history_data is not None:
            h_dates, h_riders, h_ids = history_data
            h_right = int(np.searchsorted(h_dates, cutoff, side="right"))
            horse_past_n = h_right
            if h_right:
                previous_id = canonical_rider_id(h_riders[h_right - 1])
                if not is_valid_rider(previous_id):
                    previous_id = None
                previous_date = pd.Timestamp(h_dates[h_right - 1]).date().isoformat()
                previous_api_id = str(h_ids[h_right - 1])
        current_valid = is_valid_rider(curr)
        previous_valid = is_valid_rider(previous_id)
        unknown_previous = not (current_valid and previous_valid)
        retained = bool(current_valid and previous_valid and curr == previous_id)

        current_n, current_value = rider365_value(rider_prefixes, curr, cutoff)
        previous_n, previous_value = rider365_value(rider_prefixes, previous_id, cutoff)
        delta_unavailable = not (current_valid and previous_valid and current_n > 0 and previous_n > 0)
        delta = 0.0 if delta_unavailable else float(current_value - previous_value)
        same_dates = pair_history.get((horse, curr)) if current_valid else None
        same_n = 0 if same_dates is None else int(np.searchsorted(same_dates, cutoff, side="right"))
        if not current_valid or horse_past_n == 0:
            experience_unavailable = True
            first_observed = False
            recency_days = None
        elif same_n == 0:
            experience_unavailable = False
            first_observed = True
            recency_days = None
        else:
            experience_unavailable = False
            first_observed = False
            most_recent = same_dates[same_n - 1]
            recency_days = int((cutoff - most_recent).astype("timedelta64[D]").astype(int))
            require(recency_days >= 0, "same-horse rider recency is negative at T−2")

        # Same-date pandas and prefix-array arithmetic as the established scalar.
        require(abs(float(current_value) - float(rider_current_r[idx])) <= 1e-12,
                "current rider365 scalar differs from frozen baseline formula")
        require(int(current_n) == int(rider_current_n[idx]),
                "current rider365 support differs from frozen baseline formula")
        out.append({
            "api_record_id": api_ids[idx],
            "race_id": str(row.race_id),
            "race_date": pd.Timestamp(row.race_date).date().isoformat(),
            "year": int(row.year),
            "distance_m": int(row.distance_m),
            "horse_id": horse,
            "horse_number": int(row.horse_number),
            "tminus2_cutoff": pd.Timestamp(cutoff).date().isoformat(),
            "previous_started_api_record_id": previous_api_id,
            "previous_started_date": previous_date,
            "previous_rider_retained": float(retained),
            "previous_rider_unknown": float(unknown_previous),
            "rider365_delta": delta,
            "rider365_current_support_log1p": float(np.log1p(current_n)),
            "rider365_previous_support_log1p": float(np.log1p(previous_n)),
            "rider365_delta_unavailable": float(delta_unavailable),
            "horse_current_rider_rides_log1p": float(np.log1p(same_n)),
            "horse_current_rider_recency_log1p": 0.0 if recency_days is None else float(np.log1p(recency_days)),
            "horse_current_rider_first_observed": float(first_observed),
            "horse_current_rider_history_unavailable": float(experience_unavailable),
            "rider365_current_support_n": int(current_n),
            "rider365_previous_support_n": int(previous_n),
            "horse_prior_started_n": int(horse_past_n),
            "horse_current_rider_prior_n": int(same_n),
            "horse_current_rider_recency_days": recency_days,
            "rider365_current_R_diagnostic": float(current_value),
        })
    runner = pd.DataFrame(out)
    require(len(runner) == len(event) and runner["api_record_id"].is_unique,
            "runner basis row coverage/key changed")
    require(set(RUNNER_COLUMNS).issubset(runner.columns), "runner basis schema changed")
    require(np.isfinite(runner.loc[:, RUNNER_COLUMNS].to_numpy(dtype=float)).all(),
            "runner basis contains a non-finite model input")
    require(runner["tminus2_cutoff"].eq(
        (pd.to_datetime(runner["race_date"]) - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    ).all(), "runner T−2 cutoff is not target date minus two calendar days")
    valid_previous = runner["previous_started_date"].notna()
    require((pd.to_datetime(runner.loc[valid_previous, "previous_started_date"])
             <= pd.to_datetime(runner.loc[valid_previous, "tminus2_cutoff"])).all(),
            "previous started event occurs after T−2")

    # Preserve the existing pair-ID scalar/support exactly on every saved evaluation pair.
    baseline = pd.read_parquet(checked(ID_PREDICTIONS), columns=[
        "race_id", "horse_i", "horse_j", "jockey365_n_i_new", "jockey365_n_j_new",
        "jockey365_d_i_new", "jockey365_d_j_new",
    ])
    runner_lookup = runner.set_index(["race_id", "horse_number"])
    scalar_checks = 0
    for pair in baseline.itertuples(index=False):
        for horse_number, expected_n, expected_value in (
            (int(pair.horse_i), int(pair.jockey365_n_i_new), float(pair.jockey365_d_i_new)),
            (int(pair.horse_j), int(pair.jockey365_n_j_new), float(pair.jockey365_d_j_new)),
        ):
            observed = runner_lookup.loc[(str(pair.race_id), horse_number)]
            require(int(observed["rider365_current_support_n"]) == expected_n,
                    "current rider365 support changed against saved pair-ID predictions")
            require(abs(float(observed["rider365_current_R_diagnostic"]) - expected_value) <= 1e-12,
                    "current rider365 value changed against saved pair-ID predictions")
            scalar_checks += 1
    require(scalar_checks == 2 * len(baseline), "not all existing pair-ID scalar endpoints were checked")

    runner.sort_values(["race_date", "race_id", "horse_number"], kind="mergesort", inplace=True)
    write_parquet_once(RUNNER_BASIS, runner)
    runner_hash = sha256(checked(RUNNER_BASIS))

    eval_rows = runner.loc[runner["year"].between(2024, 2026)]
    require(len(eval_rows) == EXPECTED_EVAL_ROWS, "evaluation runner count changed")
    require(eval_rows["race_id"].nunique() == EXPECTED_EVAL_RACES, "evaluation race count changed")
    require(eval_rows["race_date"].nunique() == EXPECTED_EVAL_DATES, "evaluation date count changed")
    preflight = {
        "status": "PASS",
        "scope": "source cache, runner-level history features, frozen current-rider scalar and cutoff checks; no fitting or prediction",
        "historical_results_read": True,
        "historical_results_used_only_if_event_date_at_or_before_tminus2": True,
        "target_current_outcome_used_in_features": False,
        "future_history_after_cutoff_used": False,
        "database_reopened_after_event_rider_cache_creation": False,
        "database_write": False,
        "source_cache_sha256": source_receipt["cache_sha256"],
        "runner_basis_sha256": runner_hash,
        "prepare_code_sha256": sha256(checked(STUDY / "prepare.py")),
        "basis_code_sha256": sha256(checked(STUDY / "riding_conditions_basis.py")),
        "verified_pinned_sources": verified_sources,
        "source_cache_receipt_sha256": sha256(checked(SOURCE_CACHE_RECEIPT)),
        "source_lock_sha256": sha256(checked(SOURCE_LOCK)),
        "roster": {
            "rows_2019_2026": int(len(runner)),
            "evaluation_rows_2024_2026": int(len(eval_rows)),
            "evaluation_races": int(eval_rows["race_id"].nunique()),
            "evaluation_dates": int(eval_rows["race_date"].nunique()),
        },
        "baseline_scalar_reconciliation": {
            "saved_pair_rows": int(len(baseline)),
            "runner_endpoints_checked": int(scalar_checks),
            "support_mismatches": 0,
            "rider365_value_abs_tolerance": 1e-12,
        },
        "feature_definitions": {
            "target_cutoff": "target race_date minus 2 calendar days; T−2 inclusive",
            "actual_previous_start": "latest unique full-started horse event on or before T−2; unknown event rider is not skipped",
            "rider365_population": "same selected starts.csv cohort for current and actual previous rider",
            "rider365_window": "(T−2−365 days, T−2]",
            "rider365_formula": "sum(Top3−3/field_n)/(n+20); delta=current−previous only when both IDs valid and both supports n>0",
            "horse_rider_history": "all official-ID started events for same horse and current event rider on or before T−2",
            "unknown_id_policy": "missing, non-six-digit and 000000/999999 IDs are unknown; no historical ID substitution",
            "pair_inputs": list(PAIR_COLUMNS),
        },
        "evaluation_state_counts": {
            "previous_rider_unknown_runner_count": int(eval_rows["previous_rider_unknown"].sum()),
            "rider365_delta_unavailable_runner_count": int(eval_rows["rider365_delta_unavailable"].sum()),
            "horse_current_rider_history_unavailable_runner_count": int(eval_rows["horse_current_rider_history_unavailable"].sum()),
            "horse_current_rider_first_observed_runner_count": int(eval_rows["horse_current_rider_first_observed"].sum()),
            "horse_current_rider_repeat_runner_count": int(eval_rows["horse_current_rider_prior_n"].gt(0).sum()),
            "tminus1_started_rows_used": 0,
        },
    }
    write_json_once(PREFLIGHT, preflight)

    dry_run = build_design_dry_run(runner, source_receipt, verified_sources, runner_hash)
    write_json_once(DRY_RUN, dry_run)
    return preflight, dry_run


def h1_h2_rows(rows: pd.DataFrame, evaluation_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = rows.loc[rows["year"].eq(evaluation_year - 1)].copy()
    h2 = source.loc[pd.to_datetime(source["race_date"]).dt.month.ge(7)].copy()
    require(not h2.empty, f"empty H2 roster for {evaluation_year}")
    first_h2 = pd.to_datetime(h2["race_date"]).min().date()
    cutoff = first_h2 - timedelta(days=2)
    earlier = rows.loc[rows["year"].between(2019, evaluation_year - 2)].copy()
    current = source.loc[
        pd.to_datetime(source["race_date"]).dt.month.le(6)
        & pd.to_datetime(source["race_date"]).dt.date.map(lambda date: date <= cutoff)
    ].copy()
    h1 = pd.concat([earlier, current], ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique,
            f"duplicate H1/H2 target API key in {evaluation_year}")
    require(pd.to_datetime(h1["race_date"]).max().date() <= first_h2 - timedelta(days=2),
            f"H1/H2 two-day purge failed in {evaluation_year}")
    require(int(h1["race_id"].nunique()) == EXPECTED_H1[evaluation_year],
            f"H1 race count changed in {evaluation_year}")
    require(int(h2["race_id"].nunique()) == EXPECTED_H2[evaluation_year],
            f"H2 race count changed in {evaluation_year}")
    return h1, h2


def build_design_dry_run(runner: pd.DataFrame, source_receipt: dict[str, Any],
                         verified_sources: dict[str, str], runner_hash: str) -> dict[str, Any]:
    folds: dict[str, Any] = {}
    for year in (2024, 2025, 2026):
        h1, h2 = h1_h2_rows(runner, year)
        moments = fit_race_equal_moments(h1)
        require(moments["h1_races"] == EXPECTED_H1[year], "dry-run H1 moment race count changed")
        require(moments["h1_unordered_pairs"] > moments["h1_races"], "dry-run H1 pair rows implausible")
        folds[str(year)] = {
            "h1_runner_rows": int(len(h1)),
            "h1_races": int(h1["race_id"].nunique()),
            "h1_dates": int(h1["race_date"].nunique()),
            "h1_unordered_pair_rows": int(moments["h1_unordered_pairs"]),
            "h1_first_date": str(pd.to_datetime(h1["race_date"]).min().date()),
            "h1_last_date": str(pd.to_datetime(h1["race_date"]).max().date()),
            "h2_runner_rows": int(len(h2)),
            "h2_races": int(h2["race_id"].nunique()),
            "h2_first_date": str(pd.to_datetime(h2["race_date"]).min().date()),
            "candidate_pair_columns_before_degenerate_drop": len(PAIR_COLUMNS),
            "candidate_pair_columns_after_degenerate_drop": len(moments["fit_retained_columns"]),
            "candidate_pair_exact_duplicate_columns": moments["exact_duplicate_columns"],
            "candidate_pair_fit_excluded_columns": moments["fit_excluded_columns"],
            "h1_candidate_pair_moments": moments,
            "joint_candidate_columns_before_degenerate_drop": 70,
            "joint_candidate_columns_after_degenerate_drop": 60 + len(moments["fit_retained_columns"]),
        }
    return {
        "status": "PASS",
        "scope": "fixed H1/H2 roster, 10-column candidate pair schema and H1-only moments; no labels or model optimization used for the dry-run",
        "optimizer_runs": 0,
        "candidate_h1_fit_runs": 0,
        "candidate_h2_platt_runs": 0,
        "evaluation_predictions_created": False,
        "performance_metrics_computed": False,
        "historical_results_read_for_feature_source": True,
        "target_labels_used_for_split_or_moments": False,
        "pair_input_columns": list(PAIR_COLUMNS),
        "existing_pair_id_reference": {
            "preserved_columns": "all columns from saved ID reference prediction artifact will be retained in final candidate prediction output",
            "candidate_probability_column": "riding_conditions_candidate_calibrated_probability",
            "selector_column": "selected_riding_conditions_candidate",
            "source_prediction_sha256": sha256(checked(ID_PREDICTIONS)),
        },
        "candidate_optimization_budget_after_separate_root_approval": {
            "h1_fits": 3,
            "h2_positive_slope_platt_fits": 3,
            "total_fit_or_calibration_calls": 6,
            "no_retry_or_tuning": True,
        },
        "source_cache_sha256": source_receipt["cache_sha256"],
        "source_lock_sha256": sha256(checked(SOURCE_LOCK)),
        "runner_basis_sha256": runner_hash,
        "prepare_code_sha256": sha256(checked(STUDY / "prepare.py")),
        "basis_code_sha256": sha256(checked(STUDY / "riding_conditions_basis.py")),
        "verified_pinned_sources": verified_sources,
        "folds": folds,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FEATURE_OUT.mkdir(parents=True, exist_ok=True)
    verify_pinned_sources(skip_database=True)
    source_receipt = build_started_event_rider_cache()
    preflight, dry_run = build_runner_basis(source_receipt)
    print(json.dumps({
        "status": "PASS",
        "source_cache": str(SOURCE_CACHE.relative_to(ROOT)),
        "runner_basis": str(RUNNER_BASIS.relative_to(ROOT)),
        "feature_preflight": str(PREFLIGHT.relative_to(ROOT)),
        "design_dry_run": str(DRY_RUN.relative_to(ROOT)),
        "target_rows": preflight["roster"]["rows_2019_2026"],
        "evaluation_rows": preflight["roster"]["evaluation_rows_2024_2026"],
        "candidate_pair_columns": len(PAIR_COLUMNS),
        "fit_or_prediction_started": False,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
