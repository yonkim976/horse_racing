"""Deterministic first-start trial feature aggregation from a frozen API20 bundle.

This module never opens a database, fits a model, or reads raw API files. The
source audit must normalize the audited event key/order and time eligibility
into the strict dataframe columns below before calling :func:`add_features`.
"""
from __future__ import annotations

import math
import json
from typing import Any

import numpy as np
import pandas as pd


ADDED_FEATURES = [
    "trial_peer_relative_time_mean3",
    "trial_peer_relative_time_n3",
    "trial_days_since_latest_event_pre",
    "trial_event_count_pre",
]
MAX_TRIAL_SLOTS = 3
MIN_VALID_PEERS = 2
JEJU_LABEL = "제주"
COMPLETED_JUDGMENT_LABELS = {
    "합격", "불합격", "주행불합격", "출발불합격", "불합격(능검)",
    "발주불합격", "불합격(발검)",
}

TARGET_REQUIRED = {
    "api_record_id", "race_id", "race_date", "history_cutoff", "horse_id",
    "observed_starts",
}
TRIAL_REQUIRED = {
    "source_api_record_id", "trial_event_key", "trial_event_order", "trial_date",
    "meet_code", "trial_day_serial", "horse_id", "breed_label_raw",
    "finish_time_seconds", "trial_ord_raw", "trial_judgment_raw", "time_eligible",
}


def _explicit_bool(values: pd.Series, name: str) -> pd.Series:
    if values.isna().any():
        raise AssertionError(f"{name} contains NULL")
    domain = set(values.unique().tolist())
    if not domain.issubset({True, False, 0, 1, np.bool_(True), np.bool_(False)}):
        raise AssertionError(f"{name} is not an explicit boolean domain: {domain}")
    return values.astype(bool)


def _normalize_horse_ids(values: pd.Series, name: str) -> pd.Series:
    normalized = values.astype("string").str.strip()
    if normalized.isna().any() or normalized.eq("").any():
        raise AssertionError(f"{name} contains a missing official horse ID")
    if normalized.str.contains(r"\D", regex=True).any():
        raise AssertionError(f"{name} contains a nonnumeric horse ID")
    return normalized


def _parse_dates(values: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(values.astype("string"), format="%Y-%m-%d", errors="raise")
    if parsed.isna().any():
        raise AssertionError(f"{name} contains NULL")
    return parsed.dt.normalize()


def _valid_trial_ordinal(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)) or value is None or value is pd.NA:
        return False
    if isinstance(value, (int, np.integer)):
        return 1 <= int(value) <= 89
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return False
        ordinal = int(text)
        return 1 <= ordinal <= 89 and str(ordinal) == text
    return False


def _trial_time_status(row: Any) -> tuple[bool, str]:
    reasons: list[str] = []
    try:
        numeric_time = float(row.finish_time_seconds)
        time_ok = math.isfinite(numeric_time) and numeric_time > 0
    except (TypeError, ValueError, OverflowError):
        time_ok = False
    if not time_ok:
        reasons.append("rcTime_not_finite_positive")
    if not _valid_trial_ordinal(row.trial_ord_raw):
        reasons.append("ord_not_integer_1_to_89")
    if row.trial_judgment_raw not in COMPLETED_JUDGMENT_LABELS:
        reasons.append("passFlag_outside_known_judgment_allowlist")
    return not reasons, ";".join(reasons)


def add_features(
    baseline_features: pd.DataFrame,
    target_roster: pd.DataFrame,
    audited_trial_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append four first-start-only features and return a selected-event ledger.

    `audited_trial_rows` is expected to contain API20 rows with exact official
    IDs and an audit-created, event-stable `trial_event_key` plus numeric
    within-date `trial_event_order`. Eligibility is independently re-derived
    from finite positive rcTime, raw integer `ord` 1..89, and the frozen
    explicit completed-judgment allowlist. Positive times with special ranks
    remain ineligible. The peer median uses only exact `majong=제주` rows in
    the same event, excludes the target horse, and requires at least two peers.
    Invalid event slots remain in the newest-three window and are never
    replaced by older valid events.
    """
    missing = TARGET_REQUIRED - set(target_roster.columns)
    if missing:
        raise AssertionError(f"target roster missing columns: {sorted(missing)}")
    missing = TRIAL_REQUIRED - set(audited_trial_rows.columns)
    if missing:
        raise AssertionError(f"trial source missing audited columns: {sorted(missing)}")
    if not ADDED_FEATURES or set(ADDED_FEATURES) & set(baseline_features.columns):
        raise AssertionError("refusing to overwrite an existing input feature")
    if "api_record_id" not in baseline_features or not baseline_features.api_record_id.is_unique:
        raise AssertionError("baseline features require unique api_record_id")
    if not target_roster.api_record_id.is_unique:
        raise AssertionError("target roster requires unique api_record_id")

    base_ids = baseline_features.api_record_id.astype("int64")
    roster = target_roster.copy()
    roster["api_record_id"] = roster.api_record_id.astype("int64")
    if not set(roster.api_record_id).issubset(set(base_ids)):
        raise AssertionError("target roster contains rows outside the saved F1 cohort")
    roster["horse_id"] = _normalize_horse_ids(roster.horse_id, "target horse_id")
    race_date = _parse_dates(roster.race_date, "race_date")
    cutoff = _parse_dates(roster.history_cutoff, "history_cutoff")
    if not cutoff.equals(race_date - pd.Timedelta(days=2)):
        raise AssertionError("history_cutoff must be race_date minus two calendar days")
    starts = pd.to_numeric(roster.observed_starts, errors="raise")
    if starts.isna().any() or (starts < 0).any() or not np.equal(starts, np.floor(starts)).all():
        raise AssertionError("observed_starts must be nonnegative integers")
    roster["observed_starts"] = starts.astype("int64")
    baseline_starts = pd.to_numeric(baseline_features.observed_starts, errors="raise")
    baseline_cold_ids = set(
        baseline_features.loc[baseline_starts.eq(0), "api_record_id"].astype("int64")
    )
    if set(roster.api_record_id) != baseline_cold_ids:
        raise AssertionError("target roster must contain every and only baseline observed_starts=0 row")
    if not roster.observed_starts.eq(0).all():
        raise AssertionError("target roster is reserved for baseline observed_starts=0 rows")
    baseline_by_id = baseline_features.set_index("api_record_id", drop=False)
    for column in ("race_id", "race_date", "history_cutoff", "horse_id", "observed_starts"):
        if column not in baseline_features:
            raise AssertionError(f"saved baseline lacks required target context: {column}")
        expected = baseline_by_id.loc[roster.api_record_id, column].astype("string").reset_index(drop=True)
        actual = roster[column].astype("string").reset_index(drop=True)
        if not expected.equals(actual):
            raise AssertionError(f"target roster does not exactly match saved baseline {column}")
    roster["race_date_parsed"] = race_date.to_numpy()
    roster["cutoff_parsed"] = cutoff.to_numpy()
    cold = roster.copy()

    trials = audited_trial_rows.copy()
    if len(trials):
        trials["source_api_record_id"] = pd.to_numeric(
            trials.source_api_record_id, errors="raise"
        ).astype("int64")
        if trials.source_api_record_id.duplicated().any():
            raise AssertionError("API20 source row IDs must be unique")
        trials["horse_id"] = _normalize_horse_ids(trials.horse_id, "trial horse_id")
        trials["trial_event_key"] = trials.trial_event_key.astype("string").str.strip()
        if trials.trial_event_key.isna().any() or trials.trial_event_key.eq("").any():
            raise AssertionError("trial_event_key must be populated from audited event identity")
        trials["trial_event_order"] = pd.to_numeric(
            trials.trial_event_order, errors="raise"
        )
        if trials.trial_event_order.isna().any():
            raise AssertionError("trial_event_order must be populated")
        if not np.equal(trials.trial_event_order, np.floor(trials.trial_event_order)).all():
            raise AssertionError("trial_event_order must be integer-valued")
        trials["trial_event_order"] = trials.trial_event_order.astype("int64")
        trials["trial_date_parsed"] = _parse_dates(trials.trial_date, "trial_date")
        if not pd.to_numeric(trials.meet_code, errors="raise").eq(2).all():
            raise AssertionError("trial source must be limited to meet=2")
        trials["time_eligible"] = _explicit_bool(trials.time_eligible, "time_eligible")
        time_values = pd.to_numeric(trials.finish_time_seconds, errors="coerce")
        finite_positive = np.isfinite(time_values.to_numpy(dtype="float64", na_value=np.nan)) & time_values.gt(0).to_numpy()
        trials["finish_time_seconds"] = time_values.astype("float64")
        recalculated_eligibility: list[bool] = []
        recalculated_reasons: list[str] = []
        for row in trials.itertuples(index=False):
            reasons: list[str] = []
            if not math.isfinite(row.finish_time_seconds) or row.finish_time_seconds <= 0:
                reasons.append("rcTime_not_finite_positive")
            if not _valid_trial_ordinal(row.trial_ord_raw):
                reasons.append("ord_not_integer_1_to_89")
            judgment = row.trial_judgment_raw
            if not isinstance(judgment, str) or judgment not in COMPLETED_JUDGMENT_LABELS:
                reasons.append("passFlag_outside_known_judgment_allowlist")
            recalculated_eligibility.append(not reasons)
            recalculated_reasons.append(";".join(reasons))
        if not trials.time_eligible.equals(pd.Series(recalculated_eligibility, index=trials.index)):
            raise AssertionError("time_eligible differs from the frozen rcTime+ord+passFlag rule")
        trials["time_ineligible_reasons"] = pd.Series(recalculated_reasons, index=trials.index, dtype="string")
        if not trials.breed_label_raw.astype("string").eq(JEJU_LABEL).all():
            raise AssertionError("peer source bundle must contain only explicit majong=제주 API20 rows")
        event_identity = trials.groupby("trial_event_key", sort=False).agg(
            dates=("trial_date_parsed", "nunique"), orders=("trial_event_order", "nunique"),
            meets=("meet_code", "nunique"), day_serials=("trial_day_serial", "nunique"),
        )
        if not event_identity.eq(1).all().all():
            raise AssertionError("event key maps to inconsistent date/order/meet values")
        expected_keys = (
            trials.trial_date_parsed.dt.strftime("%Y-%m-%d").astype("string")
            + "|2|"
            + trials.trial_event_order.astype("string")
        ).astype("string")
        if not trials.trial_event_key.astype("string").reset_index(drop=True).equals(
            expected_keys.reset_index(drop=True)
        ):
            raise AssertionError("event key must equal normalized (trial_date, meet=2, trial_number)")
        if trials.duplicated(["trial_event_key", "horse_id"]).any():
            raise AssertionError("duplicate horse rows within audited trial event")
        event_keys = trials[["trial_date_parsed", "trial_event_order", "trial_event_key"]].drop_duplicates()
        if event_keys.duplicated(["trial_date_parsed", "trial_event_order"]).any():
            raise AssertionError("two event keys share a date and trial-number order")
    else:
        trials["trial_date_parsed"] = pd.Series(dtype="datetime64[ns]")
        trials["finish_time_seconds"] = pd.Series(dtype="float64")
        trials["time_eligible"] = pd.Series(dtype="bool")
        trials["trial_event_order"] = pd.Series(dtype="int64")
        trials["trial_event_key"] = pd.Series(dtype="string")
        trials["horse_id"] = pd.Series(dtype="string")
        trials["trial_day_serial"] = pd.Series(dtype="Int64")
        trials["time_ineligible_reasons"] = pd.Series(dtype="string")

    # Compute a per-event peer median from all usable explicit-Jeju times.
    valid = trials.loc[trials.time_eligible].copy()
    event_stats: dict[tuple[str, str], tuple[int, float | None, str, str]] = {}
    for event_key, group in trials.groupby("trial_event_key", sort=False):
        good = group.loc[group.time_eligible]
        for row in group.itertuples(index=False):
            peer_rows = good.loc[good.horse_id.ne(row.horse_id)]
            peer_times = peer_rows["finish_time_seconds"]
            peer_n = int(len(peer_rows))
            peer_median = float(peer_times.median()) if peer_n >= MIN_VALID_PEERS else None
            peer_api_ids_json = json.dumps(sorted(map(int, peer_rows.source_api_record_id)), separators=(",", ":"))
            peer_horse_ids_json = json.dumps(sorted(map(str, peer_rows.horse_id)), separators=(",", ":"))
            event_stats[(str(event_key), str(row.horse_id))] = (
                peer_n, peer_median, peer_api_ids_json, peer_horse_ids_json
            )

    trial_groups = {
        str(horse_id): group.sort_values(
            ["trial_date_parsed", "trial_event_order", "source_api_record_id"], kind="stable"
        )
        for horse_id, group in trials.groupby("horse_id", sort=False)
    }

    records: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    for target in cold.itertuples(index=False):
        target_id = int(target.api_record_id)
        horse_id = str(target.horse_id)
        race_day = target.race_date_parsed
        cutoff_day = target.cutoff_parsed
        observed = trial_groups.get(horse_id)
        if observed is None:
            observed = trials.iloc[:0]
        historical = observed.loc[observed.trial_date_parsed.le(cutoff_day)]
        historical = historical.sort_values(
            ["trial_date_parsed", "trial_event_order", "source_api_record_id"], kind="stable"
        )
        # At most one row per horse/event is source-audit-verified. Count every
        # registered record, including canceled or otherwise unusable trials.
        event_count = int(historical.trial_event_key.nunique())
        latest_days = (
            int((race_day - historical.trial_date_parsed.max()).days) if event_count else np.nan
        )
        recent = historical.tail(MAX_TRIAL_SLOTS)
        relative_values: list[float] = []
        if len(recent):
            for slot_no, row in enumerate(recent.itertuples(index=False), start=1):
                peer_n, peer_median, peer_api_ids_json, peer_horse_ids_json = event_stats[
                    (str(row.trial_event_key), horse_id)
                ]
                if not bool(row.time_eligible):
                    reason = str(row.time_ineligible_reasons)
                    relative = np.nan
                elif peer_median is None or not math.isfinite(peer_median) or peer_median <= 0:
                    reason = "fewer_than_two_positive_explicit_jeju_peers"
                    relative = np.nan
                else:
                    relative = float((float(row.finish_time_seconds) - peer_median) / peer_median)
                    if not math.isfinite(relative):
                        raise AssertionError("relative-time calculation is not finite")
                    reason = "eligible"
                    relative_values.append(relative)
                ledger_rows.append({
                    "target_api_record_id": target_id,
                    "target_race_id": str(target.race_id),
                    "target_race_date": str(target.race_date),
                    "target_cutoff": str(target.history_cutoff),
                    "target_horse_id": horse_id,
                    "slot_oldest_to_newest": slot_no,
                    "slot_rank_desc": len(recent) - slot_no + 1,
                    "source_api_record_id": int(row.source_api_record_id),
                    "source_trial_event_key": str(row.trial_event_key),
                    "source_trial_event_order": int(row.trial_event_order),
                    "source_trial_date": str(row.trial_date),
                    "source_day_serial": int(row.trial_day_serial),
                    "source_horse_id": str(row.horse_id),
                    "source_time_seconds": float(row.finish_time_seconds) if pd.notna(row.finish_time_seconds) else np.nan,
                    "source_ord_raw": row.trial_ord_raw,
                    "source_judgment_raw": row.trial_judgment_raw,
                    "source_time_ineligible_reasons": str(row.time_ineligible_reasons),
                    "source_time_eligible": bool(row.time_eligible),
                    "peer_positive_time_n": peer_n,
                    "peer_median_time_seconds": peer_median if peer_median is not None else np.nan,
                    "peer_api_record_ids_json": peer_api_ids_json,
                    "peer_horse_ids_json": peer_horse_ids_json,
                    "relative_time": relative,
                    "ineligible_reason": reason,
                })
        n = len(relative_values)
        records.append({
            "api_record_id": target_id,
            ADDED_FEATURES[0]: float(np.mean(relative_values)) if n else np.nan,
            ADDED_FEATURES[1]: float(n),
            ADDED_FEATURES[2]: float(latest_days) if event_count else np.nan,
            ADDED_FEATURES[3]: float(event_count),
        })

    additions = pd.DataFrame(records, columns=["api_record_id", *ADDED_FEATURES])
    result = baseline_features.merge(additions, on="api_record_id", how="left", validate="one_to_one", sort=False)
    if len(result) != len(baseline_features) or not result.api_record_id.astype("int64").equals(base_ids):
        raise AssertionError("feature join changed row count/order")
    ledger = pd.DataFrame(ledger_rows)
    if ledger.empty:
        ledger = pd.DataFrame(columns=[
            "target_api_record_id", "target_race_id", "target_race_date", "target_cutoff",
            "target_horse_id", "slot_oldest_to_newest", "slot_rank_desc", "source_api_record_id",
            "source_trial_event_key", "source_trial_event_order", "source_trial_date",
            "source_day_serial", "source_horse_id", "source_time_seconds", "source_ord_raw",
            "source_judgment_raw", "source_time_ineligible_reasons", "source_time_eligible",
            "peer_positive_time_n", "peer_median_time_seconds", "peer_api_record_ids_json",
            "peer_horse_ids_json", "relative_time", "ineligible_reason",
        ])

    cold_mask = pd.to_numeric(result.observed_starts, errors="raise").eq(0)
    if not cold_mask.equals(result.api_record_id.astype("int64").isin(set(cold.api_record_id))):
        raise AssertionError("target roster must include exactly all saved observed_starts=0 rows")
    if result.loc[~cold_mask, ADDED_FEATURES].notna().any().any():
        raise AssertionError("experienced horses must have NULL in all four added fields")
    if result.loc[cold_mask, ADDED_FEATURES[1]].isna().any() or result.loc[cold_mask, ADDED_FEATURES[3]].isna().any():
        raise AssertionError("cold horses require n/count, including zero for no observed trial")
    if not result.loc[cold_mask, ADDED_FEATURES[1]].between(0, MAX_TRIAL_SLOTS).all():
        raise AssertionError("relative-time valid n must be in 0..3")
    if not result.loc[cold_mask & result[ADDED_FEATURES[1]].eq(0), ADDED_FEATURES[0]].isna().all():
        raise AssertionError("relative-time mean must be NULL when n=0")
    if result.loc[cold_mask & result[ADDED_FEATURES[3]].eq(0), [ADDED_FEATURES[0], ADDED_FEATURES[2]]].notna().any().any():
        raise AssertionError("no-trial cold horses must have NULL mean/days and n/count zero")
    pd.testing.assert_frame_equal(
        result[baseline_features.columns].reset_index(drop=True),
        baseline_features.reset_index(drop=True),
        check_exact=True,
    )
    ledger = ledger.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    return result, ledger
