"""Read-only E7-A per-start history audit; no training or operational path."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from statistics import median
from typing import Any

import polars as pl

from horse_racing.analysis.confirmed_starter_e6a_v2 import ACTUAL, UNRESOLVED
from horse_racing.analysis.features.canonical_energy import _relative
from horse_racing.analysis.features.canonical_sections import canonicalize_sections

KEY = ("race_id", "race_entry_id")
MEASURES = ("early_rel", "last200_rel", "speed_figure", "days_ago")
FEATURES = tuple(f"sequence_start{slot}_{name}" for slot in (1, 2, 3) for name in MEASURES)
BOUND = "2026-05-31"


class E7AContractError(ValueError):
    """A retrospective source, key or time contract failed."""


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _unique(frame: pl.DataFrame, columns: tuple[str, ...], label: str) -> None:
    if not set(columns) <= set(frame.columns) or frame.select(*columns).n_unique() != frame.height:
        raise E7AContractError(f"{label}: missing key columns or duplicate keys")


def exact_target_keys(targets: pl.DataFrame, actual: pl.DataFrame) -> None:
    _unique(targets, KEY, "H1")
    _unique(actual, KEY, "E7-A")
    expected = targets.select(*KEY)
    found = actual.select(*KEY)
    missing = expected.join(found, on=list(KEY), how="anti").height
    extra = found.join(expected, on=list(KEY), how="anti").height
    if missing or extra:
        raise E7AContractError(f"E7-A target coverage missing={missing}, extra={extra}")


def canonical_relative_observations(
    sections: pl.DataFrame, normal_finish: pl.DataFrame
) -> pl.DataFrame:
    """Use the approved canonical conversion and pre-rolling race-relative policy."""
    canonical = canonicalize_sections(sections)
    if canonical.is_empty():
        raise E7AContractError("no canonical section source")
    _unique(canonical, ("race_entry_id",), "canonical sections")
    _unique(normal_finish, ("race_entry_id",), "normal-finish source")
    raw = sections.filter(pl.col("section_code").is_in(["S1F", "G1F"]))
    raw_status = raw.group_by("race_entry_id", "section_code").agg(
        pl.len().alias("raw_count"),
        pl.col("time_basis").first().alias("raw_basis"),
        pl.col("source_kind").first().alias("raw_source_kind"),
    )
    for code, prefix in (("S1F", "s1f"), ("G1F", "g1f")):
        part = raw_status.filter(pl.col("section_code") == code).select(
            "race_entry_id",
            pl.col("raw_count").alias(f"{prefix}_raw_count"),
            pl.col("raw_basis").alias(f"{prefix}_raw_basis"),
            pl.col("raw_source_kind").alias(f"{prefix}_raw_source_kind"),
        )
        normal_finish = normal_finish.join(part, on="race_entry_id", how="left", validate="1:1")
    base = normal_finish.select(
        "race_id",
        "race_entry_id",
        "s1f_raw_count",
        "s1f_raw_basis",
        "s1f_raw_source_kind",
        "g1f_raw_count",
        "g1f_raw_basis",
        "g1f_raw_source_kind",
    ).join(
        canonical.select(
            "race_entry_id",
            "canonical_s1f_ms",
            "canonical_last_200_ms",
            "canonical_s1f_evidence",
            "canonical_g1f_evidence",
        ),
        on="race_entry_id",
        how="left",
        validate="1:1",
    )
    return base.with_columns(
        _relative("canonical_s1f_ms").alias("early_rel"),
        _relative("canonical_last_200_ms").alias("last200_rel"),
        pl.col("canonical_s1f_ms").is_not_null().sum().over("race_id").alias("early_valid_n"),
        pl.col("canonical_last_200_ms")
        .is_not_null()
        .sum()
        .over("race_id")
        .alias("last200_valid_n"),
    )


def independent_relative_check(
    observations: pl.DataFrame, normal_finish: pl.DataFrame
) -> dict[str, Any]:
    """Recompute the 100*log(median/time), count>=3 and [-20,20] policy in Python."""
    _unique(observations, ("race_entry_id",), "relative observations")
    by_race: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in observations.iter_rows(named=True):
        by_race[int(row["race_id"])].append(row)
    checked = 0
    mismatches = []
    for race in by_race.values():
        for raw, relative in (
            ("canonical_s1f_ms", "early_rel"),
            ("canonical_last_200_ms", "last200_rel"),
        ):
            valid = [float(row[raw]) for row in race if row[raw] is not None and row[raw] > 0]
            center = median(valid) if len(valid) >= 3 else None
            for row in race:
                value = row[raw]
                expected = (
                    max(-20.0, min(20.0, 100.0 * math.log(center / value)))
                    if center is not None and value is not None and value > 0
                    else None
                )
                observed = row[relative]
                checked += 1
                if (expected is None) != (observed is None) or (
                    expected is not None and abs(expected - observed) > 1e-10
                ):
                    mismatches.append((row["race_entry_id"], relative, expected, observed))
    if observations.height > normal_finish.height:
        raise E7AContractError("relative denominator exceeds normal source")
    if mismatches:
        raise E7AContractError(f"relative independent mismatch: {mismatches[:3]}")
    return {
        "checked_cells": checked,
        "mismatch_cells": 0,
        "policy": "valid_n>=3; prior-race median; 100*ln(median/time); clip [-20,20]",
    }


def _section_reason(row: dict[str, Any], measure: str) -> str:
    if row.get(measure) is not None:
        return "observed"
    raw = "canonical_s1f_ms" if measure == "early_rel" else "canonical_last_200_ms"
    evidence = "canonical_s1f_evidence" if measure == "early_rel" else "canonical_g1f_evidence"
    count = "early_valid_n" if measure == "early_rel" else "last200_valid_n"
    prefix = "s1f" if measure == "early_rel" else "g1f"
    if row.get(raw) is not None and (row.get(count) or 0) < 3:
        return "race_reference_insufficient"
    if not row.get(f"{prefix}_raw_count"):
        return "section_measurement_absent_in_db"
    if row[f"{prefix}_raw_count"] > 1:
        return "section_measurement_ambiguous"
    allowed = {"cumulative"} if prefix == "s1f" else {"cumulative", "closing"}
    if row.get(f"{prefix}_raw_basis") not in allowed:
        return "section_time_basis_unconfirmed"
    if row.get(evidence) is None:
        return "physical_conversion_unavailable"
    return "physical_conversion_unavailable"


def build_sequence(
    targets: pl.DataFrame,
    history: pl.DataFrame,
    relative: pl.DataFrame,
    figures: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Select three preceding actual starts by date; unresolved dates block all older slots."""
    _unique(targets, KEY, "targets")
    _unique(history, KEY, "history")
    _unique(relative, ("race_entry_id",), "relative")
    _unique(figures, ("race_entry_id",), "figures")
    if targets.is_empty() or targets["race_date_local"].max() > BOUND:
        raise E7AContractError("target date scope invalid")
    if history.height and history["race_date_local"].max() > BOUND:
        raise E7AContractError("history date upper bound violated")
    if history.filter(~pl.col("start_state").is_in(ACTUAL | UNRESOLVED | {"did_not_start"})).height:
        raise E7AContractError("unsupported start state")
    indexed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in history.iter_rows(named=True):
        indexed[int(row["horse_id"])].append(row)
    rel_index = {int(row["race_entry_id"]): row for row in relative.iter_rows(named=True)}
    fig_index = {int(row["race_entry_id"]): row for row in figures.iter_rows(named=True)}
    feature_rows = []
    evidence_rows = []
    for target in targets.select(*KEY, "horse_id", "race_date_local").iter_rows(named=True):
        target_day = _day(target["race_date_local"])
        earlier = [
            row
            for row in indexed.get(int(target["horse_id"]), [])
            if _day(row["race_date_local"]) < target_day
        ]
        candidates = [row for row in earlier if row["start_state"] in ACTUAL | UNRESOLVED]
        by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            by_day[_day(row["race_date_local"])].append(row)
        sorted_days = sorted(by_day, reverse=True)
        values: dict[str, Any] = {key: target[key] for key in KEY}
        blocked_reason = None
        for slot in (1, 2, 3):
            start = None
            status = "slot_unavailable"
            if blocked_reason is not None:
                status = blocked_reason
            elif len(sorted_days) < slot:
                status = (
                    "no_prior_db_entry_observed_range"
                    if not earlier
                    else "no_more_confirmed_actual_start"
                )
            else:
                day_rows = by_day[sorted_days[slot - 1]]
                if len(day_rows) != 1:
                    blocked_reason = status = "same_day_start_order_ambiguous"
                elif day_rows[0]["start_state"] in UNRESOLVED:
                    blocked_reason = status = "prior_start_unresolved"
                else:
                    start = day_rows[0]
                    status = "actual_start_confirmed"
            row: dict[str, Any] = {
                **{key: target[key] for key in KEY},
                "slot": slot,
                "slot_status": status,
            }
            for name in MEASURES:
                values[f"sequence_start{slot}_{name}"] = None
            if start is not None:
                entry_id = int(start["race_entry_id"])
                row.update(
                    {
                        "prior_race_id": int(start["race_id"]),
                        "prior_race_entry_id": entry_id,
                        "prior_race_date_local": start["race_date_local"],
                        "prior_meet_code": start.get("meet_code"),
                        "prior_start_state": start["start_state"],
                        "prior_distance_m": start.get("distance_m"),
                        "prior_finish_time_ms": start.get("finish_time_ms"),
                    }
                )
                days = (target_day - _day(start["race_date_local"])).days
                if days <= 0:
                    raise E7AContractError("nonpositive prior-start age")
                values[f"sequence_start{slot}_days_ago"] = float(days)
                rel = rel_index.get(entry_id, {})
                fig = fig_index.get(entry_id, {})
                for name in ("early_rel", "last200_rel"):
                    value = rel.get(name)
                    values[f"sequence_start{slot}_{name}"] = value
                    row[f"{name}_reason"] = (
                        "finish_observation_unavailable"
                        if start["start_state"] != "normal_finish"
                        else _section_reason(rel, name)
                    )
                figure = fig.get("speed_figure")
                values[f"sequence_start{slot}_speed_figure"] = figure
                if figure is not None:
                    row["speed_figure_reason"] = "observed"
                elif start["start_state"] != "normal_finish" or start.get("finish_time_ms") is None:
                    row["speed_figure_reason"] = "finish_observation_unavailable"
                elif fig.get("speed_par") is None:
                    row["speed_figure_reason"] = "baseline_par_unavailable"
                else:
                    row["speed_figure_reason"] = "speed_observation_invalid"
                for name in (
                    "canonical_s1f_ms",
                    "canonical_last_200_ms",
                    "canonical_s1f_evidence",
                    "canonical_g1f_evidence",
                    "early_valid_n",
                    "last200_valid_n",
                    "s1f_raw_count",
                    "s1f_raw_basis",
                    "s1f_raw_source_kind",
                    "g1f_raw_count",
                    "g1f_raw_basis",
                    "g1f_raw_source_kind",
                ):
                    row[name] = rel.get(name)
                for name in (
                    "speed_par",
                    "speed_par_sample_n",
                    "speed_censored",
                    "speed_going",
                    "speed_day_variant",
                ):
                    row[name] = fig.get(name)
            else:
                row.update(
                    {
                        "prior_race_id": None,
                        "prior_race_entry_id": None,
                        "prior_race_date_local": None,
                        "prior_meet_code": None,
                        "prior_start_state": None,
                        "prior_distance_m": None,
                        "prior_finish_time_ms": None,
                        "early_rel_reason": status,
                        "last200_rel_reason": status,
                        "speed_figure_reason": status,
                    }
                )
            evidence_rows.append(row)
        feature_rows.append(values)
    features = pl.DataFrame(feature_rows, infer_schema_length=None).sort(*KEY)
    features = features.with_columns(pl.col(name).cast(pl.Float64) for name in FEATURES)
    evidence = pl.DataFrame(evidence_rows, infer_schema_length=None).sort(*KEY, "slot")
    exact_target_keys(targets, features)
    if evidence.height != targets.height * 3:
        raise E7AContractError("evidence slot coverage changed")
    for name in FEATURES:
        if features[name].drop_nulls().is_empty():
            continue
        if not features[name].drop_nulls().is_finite().all():
            raise E7AContractError(f"nonfinite feature: {name}")
    return features, evidence
