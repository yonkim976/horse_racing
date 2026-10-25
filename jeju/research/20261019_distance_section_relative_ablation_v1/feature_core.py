"""Independent benchmark and target-history aggregation for relative sections.

This module accepts normalized, frozen source tables only. It has no database,
network, model-fit, or file-writing behavior. Source adapters are responsible
for mapping the frozen parquet schema to the explicit columns below.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


SUPPORTED_DISTANCES = (900, 1000, 1110, 1200)
SEGMENTS = (1, 2, 3, 4, 5)
MIN_REFERENCE_RACES = 20
MAX_HISTORY_SLOTS = 5
ADDED_FEATURES = [
    column
    for segment in SEGMENTS
    for column in (f"hist_relative_seg_{segment}_mean5", f"hist_relative_seg_{segment}_n")
]

SOURCE_COLUMNS = {
    "api_record_id", "race_id", "race_date", "horse_id", "distance_m", "started",
    "valid_time", "segment_id", "raw_delta_seconds", "quality_eligible",
    "feature_eligible", "feature_seconds",
}
TARGET_COLUMNS = {
    "api_record_id", "race_id", "race_date", "horse_id", "distance_m",
    "history_cutoff", "last5_same_source_ids",
}
LINEAGE_COLUMNS = {
    "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id",
    "source_race_id", "source_race_date", "target_cutoff", "target_horse_id",
    "source_horse_id", "target_distance_m", "source_distance_m", "source_started",
}


def _bool(series: pd.Series, name: str) -> pd.Series:
    if series.isna().any():
        raise AssertionError(f"{name} has NULL values")
    values = set(series.unique().tolist())
    if not values.issubset({True, False, 0, 1, np.bool_(True), np.bool_(False)}):
        raise AssertionError(f"{name} is outside explicit boolean domain: {values}")
    return series.astype(bool)


def _ids(value: Any) -> list[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise AssertionError(f"saved history IDs have unexpected type {type(value)!r}")
    return [int(item) for item in value]


def _required(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise AssertionError(f"{label} missing columns: {sorted(missing)}")


def _normalize_dates(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_datetime(result[column], errors="raise").dt.strftime("%Y-%m-%d")
    return result


def validate_source_intervals(source: pd.DataFrame) -> pd.DataFrame:
    """Validate event/participant/segment rows and make numeric types explicit."""
    _required(source, SOURCE_COLUMNS, "source intervals")
    result = _normalize_dates(source, ("race_date",))
    result["api_record_id"] = pd.to_numeric(result.api_record_id, errors="raise").astype("int64")
    result["race_id"] = result.race_id.astype("string")
    result["horse_id"] = result.horse_id.astype("string")
    result["distance_m"] = pd.to_numeric(result.distance_m, errors="raise").astype("int64")
    result["segment_id"] = pd.to_numeric(result.segment_id, errors="raise").astype("int64")
    result["raw_delta_seconds"] = pd.to_numeric(result.raw_delta_seconds, errors="coerce")
    result["feature_seconds"] = pd.to_numeric(result.feature_seconds, errors="coerce")
    result["started"] = _bool(result.started, "started")
    result["valid_time"] = _bool(result.valid_time, "valid_time")
    result["quality_eligible"] = _bool(result.quality_eligible, "quality_eligible")
    result["feature_eligible"] = _bool(result.feature_eligible, "feature_eligible")

    assert result.api_record_id.gt(0).all()
    assert result.race_id.notna().all() and result.horse_id.notna().all()
    assert result.distance_m.isin(SUPPORTED_DISTANCES).all()
    assert result.segment_id.isin(SEGMENTS).all()
    assert result.started.all(), "reference source roster must contain started entries only"
    assert not result.duplicated(["api_record_id", "segment_id"]).any()
    assert result.groupby("api_record_id", sort=False).segment_id.apply(
        lambda values: sorted(values.astype("int64").tolist()) == list(SEGMENTS)
    ).all(), "each source participant must have exactly five segment rows"

    # Candidate eligibility is a closed conjunction, not inferred from time
    # positivity alone. The source worker supplies the quality/status gate.
    raw = result.raw_delta_seconds
    if {"endpoint_measurement_eligible", "point_quality_clear"}.issubset(result.columns):
        result["endpoint_measurement_eligible"] = _bool(
            result.endpoint_measurement_eligible, "endpoint_measurement_eligible"
        )
        result["point_quality_clear"] = _bool(result.point_quality_clear, "point_quality_clear")
        expected_quality = (
            result.endpoint_measurement_eligible & result.point_quality_clear
            & np.isfinite(raw) & raw.gt(0)
        )
        assert result.quality_eligible.equals(expected_quality), (
            "quality_eligible must equal endpoint gate & full-race point gate & positive finite raw interval"
        )
    expected_eligible = (
        result.quality_eligible
        & result.valid_time
        & np.isfinite(raw)
        & raw.gt(0)
    )
    assert result.feature_eligible.equals(expected_eligible), (
        "feature_eligible must equal quality_eligible & valid_time & finite positive raw interval"
    )
    assert result.feature_seconds.notna().equals(result.feature_eligible)
    assert np.allclose(
        result.feature_seconds.to_numpy(dtype="float64"),
        raw.where(result.feature_eligible).to_numpy(dtype="float64"),
        rtol=0, atol=1e-12, equal_nan=True,
    )
    return result


def compute_race_segment_medians(source_intervals: pd.DataFrame) -> pd.DataFrame:
    """Compute one median per source race, distance, and segment."""
    source = validate_source_intervals(source_intervals)
    eligible = source.loc[source.feature_eligible].copy()
    medians = eligible.groupby(
        ["race_id", "race_date", "distance_m", "segment_id"], sort=True, as_index=False
    ).agg(
        race_median_seconds=("feature_seconds", "median"),
        eligible_runner_n=("api_record_id", "nunique"),
    )
    events = source[["race_id", "race_date", "distance_m"]].drop_duplicates()
    assert not events.duplicated(["race_id"]).any(), "reference race key maps to multiple dates/distances"
    full_keys = events.assign(_join=1).merge(
        pd.DataFrame({"segment_id": list(SEGMENTS), "_join": 1}),
        on="_join", validate="many_to_many",
    ).drop(columns="_join")
    medians = full_keys.merge(
        medians,
        on=["race_id", "race_date", "distance_m", "segment_id"],
        how="left", validate="one_to_one",
    )
    medians["eligible_runner_n"] = medians.eligible_runner_n.fillna(0).astype("int64")
    medians["reference_race_eligible"] = medians.eligible_runner_n.gt(0)
    assert not medians.duplicated(["race_id", "distance_m", "segment_id"]).any()
    eligible_rows = medians.reference_race_eligible
    assert np.isfinite(medians.loc[eligible_rows, "race_median_seconds"]).all()
    assert medians.loc[eligible_rows, "race_median_seconds"].gt(0).all()
    assert medians.loc[~eligible_rows, "race_median_seconds"].isna().all()
    return medians


def compute_source_event_benchmarks(race_medians: pd.DataFrame,
                                    source_intervals: pd.DataFrame) -> pd.DataFrame:
    """Calculate each source event's prior, equal-race expanding benchmark.

    For source event s, only race medians dated no later than s_date minus two
    calendar days are eligible. Each prior event median has equal weight.
    """
    med_required = {
        "race_id", "race_date", "distance_m", "segment_id", "race_median_seconds",
        "eligible_runner_n",
    }
    _required(race_medians, med_required, "race segment medians")
    source = validate_source_intervals(source_intervals)
    events = source[["race_id", "race_date", "distance_m"]].drop_duplicates()
    assert not events.duplicated(["race_id"]).any(), "race identity maps to multiple dates/distances"
    event_segments = events.assign(_key=1).merge(
        pd.DataFrame({"segment_id": list(SEGMENTS), "_key": 1}), on="_key", validate="many_to_many"
    ).drop(columns="_key")

    med = race_medians.copy()
    med = _normalize_dates(med, ("race_date",))
    med["distance_m"] = pd.to_numeric(med.distance_m, errors="raise").astype("int64")
    med["segment_id"] = pd.to_numeric(med.segment_id, errors="raise").astype("int64")
    med["race_median_seconds"] = pd.to_numeric(med.race_median_seconds, errors="raise")
    assert not med.duplicated(["race_id", "distance_m", "segment_id"]).any()
    usable_medians = med.loc[
        med.reference_race_eligible.astype(bool)
        & pd.to_numeric(med.eligible_runner_n, errors="raise").gt(0)
    ].copy()

    rows: list[dict[str, Any]] = []
    for key, event_group in event_segments.groupby(["distance_m", "segment_id"], sort=True):
        event_group = event_group.sort_values(["race_date", "race_id"], kind="stable").reset_index(drop=True)
        group = usable_medians.loc[
            usable_medians.distance_m.eq(key[0]) & usable_medians.segment_id.eq(key[1])
        ].sort_values(
            ["race_date", "race_id"], kind="stable"
        ).reset_index(drop=True)
        dates = pd.to_datetime(group.race_date).to_numpy(dtype="datetime64[D]")
        values = group.race_median_seconds.to_numpy(dtype="float64")
        prefix = np.concatenate(([0.0], np.cumsum(values, dtype="float64")))
        for row in event_group.itertuples(index=False):
            cutoff = (pd.Timestamp(row.race_date) - pd.Timedelta(days=2)).date().isoformat()
            cutoff64 = np.datetime64(cutoff, "D")
            prior_n = int(np.searchsorted(dates, cutoff64, side="right"))
            # Source event itself cannot be included: its date exceeds cutoff.
            assert not group.iloc[:prior_n].race_id.eq(row.race_id).any()
            exists = prior_n >= MIN_REFERENCE_RACES
            prior_dates = group.iloc[:prior_n].race_date
            rows.append({
                "race_id": str(row.race_id),
                "race_date": str(row.race_date),
                "distance_m": int(key[0]),
                "segment_id": int(key[1]),
                "reference_cutoff_T_minus_2": cutoff,
                "minimum_prior_eligible_races": MIN_REFERENCE_RACES,
                "prior_eligible_race_n": prior_n,
                "reference_first_date": str(prior_dates.min()) if prior_n else None,
                "reference_last_date": str(prior_dates.max()) if prior_n else None,
                "mean_of_prior_race_medians": float(prefix[prior_n] / prior_n) if exists else np.nan,
                "benchmark_exists": bool(exists),
            })
    stats = pd.DataFrame(rows)
    # The benchmark table is intentionally sparse for races with no usable
    # prior median in a segment; every source event/segment still appears.
    all_keys = event_segments[["race_id", "race_date", "distance_m", "segment_id"]].sort_values(
        ["race_date", "race_id", "distance_m", "segment_id"], kind="stable"
    ).reset_index(drop=True)
    stats_keys = stats[["race_id", "race_date", "distance_m", "segment_id"]]
    assert len(stats) == len(stats_keys.drop_duplicates())
    # Medians and event index must refer to the exact same race set.
    median_event_keys = med[["race_id", "race_date", "distance_m", "segment_id"]]
    # Each segment with no eligible runner has no race median, but still has a
    # benchmark-stat row. Its prior race count is based on existing medians.
    assert set(map(tuple, stats_keys.to_numpy())) == set(map(tuple, all_keys.to_numpy()))
    assert set(map(tuple, med[["race_id", "distance_m", "segment_id"]].to_numpy())).issubset(
        set(map(tuple, stats[["race_id", "distance_m", "segment_id"]].to_numpy()))
    )
    return stats.sort_values(
        ["race_date", "race_id", "distance_m", "segment_id"], kind="stable"
    ).reset_index(drop=True)


def _compare_keyed(left: pd.DataFrame, right: pd.DataFrame, keys: list[str],
                   numbers: list[str], booleans: list[str] = (), strings: list[str] = (),
                   atol: float = 1e-12) -> None:
    a = left.sort_values(keys, kind="stable").reset_index(drop=True)
    b = right.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(a) == len(b), f"keyed row count mismatch: {len(a)} != {len(b)}"
    for column in keys + list(strings):
        av = a[column].astype("string").fillna("<NA>")
        bv = b[column].astype("string").fillna("<NA>")
        assert av.equals(bv), f"keyed text mismatch: {column}"
    for column in booleans:
        assert _bool(a[column], f"left.{column}").equals(_bool(b[column], f"right.{column}")), column
    for column in numbers:
        av = pd.to_numeric(a[column], errors="coerce").to_numpy(dtype="float64")
        bv = pd.to_numeric(b[column], errors="coerce").to_numpy(dtype="float64")
        assert np.allclose(av, bv, rtol=0, atol=atol, equal_nan=True), column


def compare_precomputed_source_artifacts(race_medians: pd.DataFrame,
                                         benchmark_stats: pd.DataFrame,
                                         independently_computed_medians: pd.DataFrame,
                                         independently_computed_stats: pd.DataFrame) -> None:
    """Fail closed unless source reference artifacts match independent rebuild."""
    _compare_keyed(
        race_medians, independently_computed_medians,
        ["race_id", "distance_m", "segment_id"],
        ["race_median_seconds", "eligible_runner_n"],
        booleans=["reference_race_eligible"], strings=["race_date"],
    )
    source_keys = benchmark_stats[["race_id", "distance_m", "segment_id"]].drop_duplicates()
    independent_benchmarks = independently_computed_stats.merge(
        source_keys, on=["race_id", "distance_m", "segment_id"],
        how="inner", validate="one_to_one",
    )
    _compare_keyed(
        benchmark_stats, independent_benchmarks,
        ["race_id", "distance_m", "segment_id"],
        ["minimum_prior_eligible_races", "prior_eligible_race_n", "mean_of_prior_race_medians"],
        booleans=["benchmark_exists"],
        strings=["race_date", "reference_cutoff_T_minus_2", "reference_first_date", "reference_last_date"],
    )


def _validate_targets(base_features: pd.DataFrame, target_roster: pd.DataFrame,
                      target_slots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    _required(base_features, {"api_record_id", "race_id", "race_date", "horse_id", "distance_m",
                              "history_cutoff", "last5_same_source_ids"}, "baseline features")
    _required(target_roster, TARGET_COLUMNS, "target roster")
    _required(target_slots, LINEAGE_COLUMNS, "target last5 lineage")
    assert base_features.api_record_id.is_unique
    assert target_roster.api_record_id.is_unique
    base = base_features.copy()
    roster = _normalize_dates(target_roster, ("race_date", "history_cutoff"))
    slots = _normalize_dates(target_slots, ("source_race_date", "target_cutoff"))
    for frame, column in ((base, "api_record_id"), (roster, "api_record_id"),
                          (slots, "target_api_record_id"), (slots, "source_api_record_id"),
                          (slots, "slot_oldest_to_newest")):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for frame, column in ((base, "distance_m"), (roster, "distance_m"),
                          (slots, "target_distance_m"), (slots, "source_distance_m")):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for frame, column in ((base, "horse_id"), (roster, "horse_id"), (slots, "target_horse_id"),
                          (slots, "source_horse_id")):
        frame[column] = frame[column].astype("string")
    base["race_date"] = _normalize_dates(base, ("race_date",))["race_date"]
    roster["race_id"] = roster.race_id.astype("string")
    slots["source_race_id"] = slots.source_race_id.astype("string")
    slots["source_started"] = _bool(slots.source_started, "source_started")
    if "valid_time" in slots.columns:
        slots["valid_time"] = _bool(slots.valid_time, "lineage.valid_time")

    expected = base.loc[base.distance_m.isin(SUPPORTED_DISTANCES)].copy()
    assert set(roster.api_record_id) == set(expected.api_record_id)
    roster_cmp_cols = ["api_record_id", "race_id", "race_date", "horse_id", "distance_m", "history_cutoff"]
    a = expected[roster_cmp_cols].sort_values("api_record_id", kind="stable").reset_index(drop=True)
    b = roster[roster_cmp_cols].sort_values("api_record_id", kind="stable").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=True)
    target_date = pd.to_datetime(roster.race_date, errors="raise")
    cutoff = pd.to_datetime(roster.history_cutoff, errors="raise")
    assert cutoff.equals(target_date - pd.Timedelta(days=2)), "target cutoff must be race_date−2 inclusive"

    target_ids = set(roster.api_record_id)
    assert slots.target_api_record_id.isin(target_ids).all()
    assert not slots.duplicated(["target_api_record_id", "slot_oldest_to_newest"]).any()
    assert not slots.duplicated(["target_api_record_id", "source_api_record_id"]).any()
    assert slots.source_started.all()
    assert slots.target_horse_id.equals(slots.source_horse_id), "history horse ID mismatch"
    assert slots.target_distance_m.equals(slots.source_distance_m), "history distance mismatch"
    assert slots.source_race_date.le(slots.target_cutoff).all(), "history exceeds T−2 cutoff"
    assert slots.groupby("target_api_record_id", sort=False).slot_oldest_to_newest.apply(
        lambda values: sorted(values.astype("int64").tolist()) == list(range(1, len(values) + 1))
    ).all()
    roster_ids = {
        int(row.api_record_id): _ids(row.last5_same_source_ids)
        for row in roster[["api_record_id", "last5_same_source_ids"]].itertuples(index=False)
    }
    actual_ids = {
        int(target_id): group.sort_values("slot_oldest_to_newest", kind="stable")
        .source_api_record_id.astype("int64").tolist()
        for target_id, group in slots.groupby("target_api_record_id", sort=False)
    }
    for target_id, expected_ids in roster_ids.items():
        assert actual_ids.get(target_id, []) == expected_ids, f"saved F1 last5 lineage mismatch: {target_id}"
    return roster, slots


def add_relative_history_features(
    base_features: pd.DataFrame,
    target_roster: pd.DataFrame,
    target_slots: pd.DataFrame,
    source_intervals: pd.DataFrame,
    source_race_segment_medians: pd.DataFrame | None = None,
    source_benchmark_stats: pd.DataFrame | None = None,
    source_target_relative_history: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Append the fixed 10 features and return reference/target audit ledgers.

    The input tables must already be mapped to this module's normalized schema.
    No invalid slot is removed from lineage; it contributes no residual and no
    older source ID is substituted.
    """
    if set(ADDED_FEATURES) & set(base_features.columns):
        raise AssertionError("refusing to overwrite existing baseline columns")
    roster, slots = _validate_targets(base_features, target_roster, target_slots)
    source = validate_source_intervals(source_intervals)
    race_medians = compute_race_segment_medians(source)
    reference_stats = compute_source_event_benchmarks(race_medians, source)
    if source_benchmark_stats is not None:
        if source_race_segment_medians is None:
            raise AssertionError("source race medians must be supplied for independent comparison")
        compare_precomputed_source_artifacts(
            source_race_segment_medians,
            source_benchmark_stats, race_medians, reference_stats,
        )

    interval_lookup = source.rename(columns={
        "api_record_id": "source_api_record_id",
        "race_id": "source_race_id",
        "race_date": "source_race_date",
        "horse_id": "source_horse_id",
        "distance_m": "source_distance_m",
    })
    merged = slots.merge(
        interval_lookup[[
            "source_api_record_id", "source_race_id", "source_race_date", "source_horse_id",
            "source_distance_m", "started", "valid_time", "segment_id", "raw_delta_seconds",
            "quality_eligible", "feature_eligible", "feature_seconds",
            *(["nominal_length_m"] if "nominal_length_m" in interval_lookup.columns else []),
            *(["endpoint_measurement_eligible"] if "endpoint_measurement_eligible" in interval_lookup.columns else []),
            *(["point_quality_clear"] if "point_quality_clear" in interval_lookup.columns else []),
        ]],
        on="source_api_record_id", how="left", validate="many_to_many", suffixes=("_lineage", "_source"),
    )
    assert len(merged) == len(slots) * len(SEGMENTS), "each lineage slot must join to five source intervals"
    for column in ("source_race_id", "source_race_date", "source_horse_id", "source_distance_m"):
        source_column = f"{column}_source"
        lineage_column = f"{column}_lineage"
        assert merged[source_column].astype("string").equals(merged[lineage_column].astype("string")), (
            f"lineage/source identity mismatch: {column}"
        )
        merged[column] = merged[lineage_column]
    assert _bool(merged.started, "interval.started").all()
    if "valid_time_lineage" in merged.columns:
        assert _bool(merged.valid_time_source, "interval.valid_time").equals(
            _bool(merged.valid_time_lineage, "lineage.valid_time")
        )
        merged["valid_time"] = merged["valid_time_source"]
    else:
        merged["valid_time"] = _bool(merged.valid_time, "interval.valid_time")
    assert merged.source_distance_m.astype("int64").equals(merged.target_distance_m.astype("int64"))

    target_identity = roster[[
        "api_record_id", "race_id", "race_date", "distance_m", "history_cutoff",
    ]].rename(columns={
        "api_record_id": "target_api_record_id", "race_id": "target_race_id",
        "race_date": "target_race_date", "distance_m": "target_roster_distance_m",
        "history_cutoff": "target_roster_cutoff",
    })
    merged = merged.merge(
        target_identity, on="target_api_record_id", how="left", validate="many_to_one"
    )
    assert merged.target_roster_cutoff.astype("string").equals(merged.target_cutoff.astype("string"))
    assert merged.target_roster_distance_m.astype("int64").equals(merged.target_distance_m.astype("int64"))

    reference_columns = [
        "race_id", "race_date", "distance_m", "segment_id", "reference_cutoff_T_minus_2",
        "minimum_prior_eligible_races", "prior_eligible_race_n", "reference_first_date", "reference_last_date",
        "mean_of_prior_race_medians", "benchmark_exists",
    ]
    stats_join = reference_stats.rename(columns={
        "race_id": "source_race_id", "race_date": "source_race_date", "distance_m": "source_distance_m",
    })
    merged = merged.merge(
        stats_join[["source_race_id", "source_race_date", "source_distance_m", "segment_id",
                    *[c for c in reference_columns if c not in {"race_id", "race_date", "distance_m", "segment_id"}]]],
        on=["source_race_id", "source_race_date", "source_distance_m", "segment_id"],
        how="left", validate="many_to_one",
    )
    assert merged.benchmark_exists.notna().all()
    merged["benchmark_exists"] = _bool(merged.benchmark_exists, "benchmark_exists")
    merged["relative_performance_seconds"] = (
        pd.to_numeric(merged.mean_of_prior_race_medians, errors="coerce")
        - pd.to_numeric(merged.raw_delta_seconds, errors="coerce")
    ).where(merged.feature_eligible & merged.benchmark_exists)
    merged["relative_feature_eligible"] = merged.feature_eligible & merged.benchmark_exists
    assert merged.relative_performance_seconds.notna().equals(merged.relative_feature_eligible)
    # Keep the frozen source convention: the reason is NULL when eligible and
    # populated only for slots that lack a residual.
    null_reason = pd.Series(np.full(len(merged), None, dtype=object), index=merged.index)
    null_reason.loc[~merged.feature_eligible] = "source_interval_ineligible"
    null_reason.loc[merged.feature_eligible & ~merged.benchmark_exists] = (
        "fewer_than_20_prior_reference_races"
    )
    merged["relative_null_reason"] = null_reason

    if source_target_relative_history is not None:
        compare_source_target_relative_history(source_target_relative_history, merged)

    ledger = merged.rename(columns={
        "source_race_id": "history_source_race_id",
        "source_race_date": "history_source_race_date",
        "source_horse_id": "history_source_horse_id",
        "source_distance_m": "history_source_distance_m",
    })
    audit_columns = [
        "target_api_record_id", "target_race_id", "target_race_date", "target_horse_id", "target_distance_m",
        "target_cutoff", "slot_oldest_to_newest", "source_api_record_id", "history_source_race_id",
        "history_source_race_date", "history_source_horse_id", "history_source_distance_m",
        "segment_id", "nominal_length_m", "raw_delta_seconds", "quality_eligible", "valid_time",
        "feature_eligible", "feature_seconds", "reference_cutoff_T_minus_2",
        "minimum_prior_eligible_races", "prior_eligible_race_n", "reference_first_date", "reference_last_date",
        "mean_of_prior_race_medians", "benchmark_exists", "relative_performance_seconds",
        "relative_feature_eligible", "relative_null_reason",
    ]
    for context_column in ("endpoint_measurement_eligible", "point_quality_clear"):
        if context_column in ledger.columns:
            audit_columns.append(context_column)
    # nominal_length_m is descriptive source metadata and optional in normalized
    # unit tests; source adapters add it to the ledger when available.
    if "nominal_length_m" not in ledger.columns:
        ledger["nominal_length_m"] = np.nan
    audit = ledger[audit_columns].sort_values(
        ["target_api_record_id", "slot_oldest_to_newest", "segment_id"], kind="stable"
    ).reset_index(drop=True)

    additions = pd.DataFrame({"api_record_id": roster.api_record_id.to_numpy(dtype="int64")})
    target_group = ledger.groupby(["target_api_record_id", "segment_id"], sort=False)
    summary = target_group.relative_performance_seconds.agg(["mean", "count"]).reset_index()
    summary["target_api_record_id"] = summary.target_api_record_id.astype("int64")
    for segment in SEGMENTS:
        group = summary.loc[summary.segment_id.eq(segment)].set_index("target_api_record_id")
        additions[f"hist_relative_seg_{segment}_mean5"] = additions.api_record_id.map(group["mean"])
        counts = additions.api_record_id.map(group["count"]).fillna(0).astype("int64")
        additions[f"hist_relative_seg_{segment}_n"] = counts.astype("float64")
        additions.loc[counts.eq(0), f"hist_relative_seg_{segment}_mean5"] = np.nan
    result = base_features.merge(additions, on="api_record_id", how="left", validate="one_to_one", sort=False)
    assert len(result) == len(base_features)
    assert result.api_record_id.astype("int64").equals(base_features.api_record_id.astype("int64"))
    target_mask = result.distance_m.astype("int64").isin(SUPPORTED_DISTANCES)
    roster_mask = result.api_record_id.astype("int64").isin(set(roster.api_record_id))
    assert target_mask.equals(roster_mask), "supported-distance roster must exactly cover the baseline rows"
    for segment in SEGMENTS:
        mean_col, n_col = f"hist_relative_seg_{segment}_mean5", f"hist_relative_seg_{segment}_n"
        assert pd.api.types.is_numeric_dtype(result[mean_col])
        assert pd.api.types.is_numeric_dtype(result[n_col])
        assert result.loc[~target_mask, [mean_col, n_col]].isna().all().all()
        assert result.loc[target_mask, n_col].notna().all()
        assert result.loc[target_mask, n_col].between(0, MAX_HISTORY_SLOTS).all()
        assert result.loc[target_mask & result[n_col].eq(0), mean_col].isna().all()
        assert result.loc[target_mask & result[n_col].gt(0), mean_col].notna().all()
    pd.testing.assert_frame_equal(
        result[base_features.columns].reset_index(drop=True),
        base_features.reset_index(drop=True), check_exact=True,
    )
    assert len(result.columns) == len(base_features.columns) + len(ADDED_FEATURES)
    return result, audit, race_medians, reference_stats


def compare_source_target_relative_history(source_relative: pd.DataFrame,
                                           computed_ledger: pd.DataFrame) -> None:
    """Compare independently computed target-slot residuals to source artifact.

    The source adapter should map its columns to the keys and value names used
    here before calling this check.
    """
    required = {
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id", "segment_id",
        "raw_delta_seconds", "mean_of_prior_race_medians", "prior_eligible_race_n",
        "relative_performance_seconds", "relative_feature_eligible",
    }
    _required(source_relative, required, "source target relative-history artifact")
    right = computed_ledger.copy()
    keys = ["target_api_record_id", "slot_oldest_to_newest", "source_api_record_id", "segment_id"]
    assert not source_relative.duplicated(keys).any()
    assert not right.duplicated(keys).any()
    _compare_keyed(
        source_relative, right, keys,
        ["raw_delta_seconds", "mean_of_prior_race_medians", "prior_eligible_race_n",
         "relative_performance_seconds"],
        booleans=["relative_feature_eligible"],
        strings=["relative_null_reason"],
    )
