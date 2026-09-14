"""Research-only retrospective dataset for confirmed actual starters.

This contract is deliberately distinct from a pre-race sealed field.  Membership
uses post-event evidence and must never be presented as historical T-30 knowledge.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from dataclasses import dataclass, replace
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.analysis.dataset import compute_prediction_at
from horse_racing.analysis.experiments import hash_feature_names, now_ms
from horse_racing.analysis.features import (
    ability,
    canonical_energy,
    competition,
    context,
    early_gate_bias,
    entry,
    feature_names,
    form,
    gate_bias,
    lifecycle,
    load_source_frames,
    people,
    relative,
    speed_figure,
    state,
    style,
)
from horse_racing.analysis.features.base import SourceFrames, as_date
from horse_racing.analysis.model_profiles import select_profile_features
from horse_racing.analysis.pre_race_field_contract import (
    OutcomeState,
    RunnerOutcome,
    SealedFieldManifest,
    classify_outcome,
    validate_exact_keyset,
)

START_DATE = "2025-01-04"
END_DATE = "2026-05-31"
TRAIN_END = "2026-02-28"
VALID_START = "2026-03-01"
MEET_CODE = 1
FEATURE_SET = "racefit_canonical_history"
MODEL_PROFILE = "racefit_v5_sand"
FIELD_KIND = "confirmed_starter_conditional_retrospective"
FLOAT_ABS_TOLERANCE = 1e-10
EXPECTED_COUNTS = {
    "races": 1_488,
    "rows": 15_579,
    "normal_finish": 15_531,
    "started_dnf": 47,
    "disqualified": 1,
    "train_rows": 12_528,
    "valid_rows": 3_051,
}


class ConfirmedStarterContractError(ValueError):
    """Raised when retrospective membership, labels, or predictors are incomplete."""


@dataclass(frozen=True, slots=True)
class ConfirmedStarterConditionalManifest:
    """Immutable post-event statement of confirmed actual starters A."""

    manifest_id: str
    source_ids: tuple[str, ...]
    field_kind: str
    selection_basis: str
    meet_code: int
    date_start: str
    date_end: str
    actual_result_upper_bound: str
    expected_keys: tuple[tuple[int, int], ...]
    key_sha256: str
    complete: bool


@dataclass(slots=True)
class ConfirmedStarterBuildResult:
    frame: pl.DataFrame
    manifest: dict[str, Any]
    comparison: dict[str, Any]


_QUERY = """
SELECT
    r.id AS race_id,
    e.id AS race_entry_id,
    rc.kra_meet_code AS meet_code,
    r.race_date_local,
    r.race_number,
    r.distance_m,
    r.grade AS grade_raw,
    r.burden_type,
    r.age_condition,
    r.sex_condition,
    r.scheduled_at_ms,
    r.weather_planned,
    r.track_condition_planned,
    r.track_moisture_percent_planned,
    e.horse_id,
    e.jockey_id,
    e.trainer_id,
    e.horse_number,
    e.gate_number,
    e.carried_weight_kg,
    e.body_weight_kg,
    e.body_weight_change_kg,
    e.rating,
    e.scratched,
    res.id AS result_id,
    res.finish_position,
    res.finish_time_ms,
    res.margin_text,
    res.rank_remark,
    res.disqualified
FROM race_entries AS e
JOIN races AS r ON r.id = e.race_id
JOIN racecourses AS rc ON rc.id = r.racecourse_id
LEFT JOIN race_results AS res ON res.race_entry_id = e.id
WHERE r.status = 'completed'
  AND rc.kra_meet_code = :meet_code
  AND r.race_date_local BETWEEN :start_date AND :end_date
ORDER BY r.race_date_local, r.race_number, e.horse_number
"""

_HISTORY_MODULES = (form, lifecycle, speed_figure, canonical_energy, ability, style)
_FIELD_MODULES = (competition, gate_bias, early_gate_bias, state, people, relative)
_TARGET_SOURCE_COLUMNS = {
    "result_id",
    "finish_position",
    "finish_time_ms",
    "margin_text",
    "rank_remark",
    "scratched",
    "disqualified",
}
_FIELD_DEPENDENT_FEATURES = {
    "starters",
    "horse_number_pct",
    "carried_weight_rel",
    "known_style_share",
    "front_runner_count",
    "front_rival_count",
    "pace_pressure",
    "gate_band",
    "course_distance_gate_band",
    "style_pace_key",
    "style_gate_key",
    "ability_elo_vs_field",
    *[spec.name for spec in relative.FEATURES],
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_sha256(keys: tuple[tuple[int, int], ...]) -> str:
    """Hash a sorted race/entry key manifest without depending on row order."""
    payload = json.dumps(sorted(keys), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_retrospective_manifest(
    manifest: ConfirmedStarterConditionalManifest | object,
) -> ConfirmedStarterConditionalManifest:
    """Reject incomplete A manifests and accidental pre-race manifest reuse."""
    if isinstance(manifest, SealedFieldManifest):
        raise ConfirmedStarterContractError(
            "pre-race SealedFieldManifest cannot represent retrospective starter A"
        )
    if not isinstance(manifest, ConfirmedStarterConditionalManifest):
        raise ConfirmedStarterContractError("confirmed-starter retrospective manifest required")
    if manifest.field_kind != FIELD_KIND:
        raise ConfirmedStarterContractError(
            f"wrong retrospective field kind: {manifest.field_kind}"
        )
    if not manifest.complete or not manifest.selection_basis or not manifest.source_ids:
        raise ConfirmedStarterContractError("retrospective manifest lacks completeness evidence")
    if manifest.actual_result_upper_bound != END_DATE or manifest.date_end != END_DATE:
        raise ConfirmedStarterContractError("actual-result upper bound must be fixed at 2026-05-31")
    validate_exact_keyset(manifest.expected_keys, manifest.expected_keys)
    if key_sha256(manifest.expected_keys) != manifest.key_sha256:
        raise ConfirmedStarterContractError("retrospective key hash mismatch")
    return manifest


def validate_dataset_against_manifest(
    manifest: ConfirmedStarterConditionalManifest | object, frame: pl.DataFrame
) -> None:
    """Validate dataset keys against independent A before any comparison join."""
    checked = validate_retrospective_manifest(manifest)
    observed = tuple(
        (int(race_id), int(entry_id))
        for race_id, entry_id in frame.select("race_id", "race_entry_id").iter_rows()
    )
    validate_exact_keyset(checked.expected_keys, observed)


def _fetch_rows(session: Session) -> pl.DataFrame:
    rows = session.execute(
        text(_QUERY),
        {"meet_code": MEET_CODE, "start_date": START_DATE, "end_date": END_DATE},
    ).mappings()
    frame = pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)
    if frame.height == 0:
        raise ConfirmedStarterContractError("fixed E2 scope returned no rows")
    return frame


def _classify_rows(frame: pl.DataFrame) -> pl.DataFrame:
    states = []
    for row in frame.select(
        "race_id",
        "race_entry_id",
        "finish_position",
        "rank_remark",
        "scratched",
        "disqualified",
    ).iter_rows(named=True):
        states.append(
            classify_outcome(
                RunnerOutcome(
                    race_id=int(row["race_id"]),
                    race_entry_id=int(row["race_entry_id"]),
                    finish_position=row["finish_position"],
                    rank_remark=row["rank_remark"],
                    scratched=bool(row["scratched"]),
                    disqualified=bool(row["disqualified"]),
                )
            ).value
        )
    return frame.with_columns(pl.Series("outcome_state", states, dtype=pl.Utf8))


def confirmed_starter_labels(frame: pl.DataFrame) -> pl.DataFrame:
    """Keep confirmed starters and mask non-existent rank/time auxiliary targets."""
    classified = _classify_rows(frame)
    allowed = {
        OutcomeState.NORMAL_FINISH.value,
        OutcomeState.STARTED_DNF.value,
        OutcomeState.DISQUALIFIED.value,
    }
    starters = classified.filter(pl.col("outcome_state").is_in(sorted(allowed)))
    normal = pl.col("outcome_state") == OutcomeState.NORMAL_FINISH.value
    return starters.with_columns(
        pl.when(normal)
        .then(pl.col("finish_position"))
        .otherwise(None)
        .cast(pl.Int64)
        .alias("finish_position_target"),
        pl.when(normal)
        .then(pl.col("finish_time_ms"))
        .otherwise(None)
        .cast(pl.Int64)
        .alias("finish_time_ms_target"),
        normal.alias("auxiliary_rank_observed"),
        (normal & pl.col("finish_time_ms").is_not_null()).alias("auxiliary_finish_time_observed"),
        (normal & (pl.col("finish_position") == 1)).cast(pl.Int8).alias("win"),
        (normal & (pl.col("finish_position") <= 2)).cast(pl.Int8).alias("top2"),
        (normal & (pl.col("finish_position") <= 3)).cast(pl.Int8).alias("top3"),
    )


def _predictor_base(starters: pl.DataFrame) -> pl.DataFrame:
    """Remove all target/result columns before predictor construction."""
    base = starters.drop(
        [name for name in _TARGET_SOURCE_COLUMNS if name in starters.columns]
        + [
            name
            for name in (
                "outcome_state",
                "finish_position_target",
                "finish_time_ms_target",
                "auxiliary_rank_observed",
                "auxiliary_finish_time_observed",
                "win",
                "top2",
                "top3",
            )
            if name in starters.columns
        ]
    )
    base = base.with_columns(pl.len().over("race_id").cast(pl.Int64).alias("starters"))
    return compute_prediction_at(base, "start_minus_30m")


def _special_anchor(
    row: pl.DataFrame,
    past: pl.DataFrame,
    *,
    synthetic_race_id: int | None = None,
) -> pl.DataFrame:
    anchor = row.with_columns(
        pl.col("race_date_local").cast(pl.Utf8).str.to_date().alias("race_date")
    ).select(
        "horse_id",
        "jockey_id",
        "trainer_id",
        "race_entry_id",
        "race_id",
        "meet_code",
        "race_date",
        "race_number",
        "scheduled_at_ms",
        "distance_m",
        pl.lit(None).cast(pl.Utf8).alias("track_condition"),
        pl.lit(None).cast(pl.Float64).alias("track_moisture_percent"),
        "gate_number",
        pl.col("horse_number").alias("program_number"),
        pl.lit(None).cast(pl.Utf8).alias("horse_name"),
        "body_weight_kg",
        pl.lit(None).cast(pl.Int64).alias("finish_position"),
        pl.lit(None).cast(pl.Int64).alias("finish_time_ms"),
        "starters",
    )
    if synthetic_race_id is not None:
        anchor = anchor.with_columns(pl.lit(synthetic_race_id).alias("race_id"))
    return pl.concat([past, anchor], how="diagonal_relaxed")


def _apply_modules(
    frame: pl.DataFrame, sources: SourceFrames, modules: tuple[object, ...]
) -> pl.DataFrame:
    result = frame
    if "race_date" not in result.columns:
        result = as_date(
            result.with_columns(pl.col("race_date_local").alias("race_date")), "race_date"
        )
    for module in modules:
        result = module.add_features(result, sources)  # type: ignore[attr-defined]
    return result


def build_predictors(starters: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    """Build predictor values for every A row without target outcomes as inputs."""
    base = _predictor_base(starters)
    result = _apply_modules(base, sources, (context, entry, *_HISTORY_MODULES))
    past_ids = (
        set(sources.past_results["race_entry_id"].to_list())
        if sources.past_results.height and "race_entry_id" in sources.past_results.columns
        else set()
    )
    special_ids = [
        int(entry_id) for entry_id in base["race_entry_id"].to_list() if entry_id not in past_ids
    ]
    history_names = [spec.name for module in _HISTORY_MODULES for spec in module.FEATURES]
    special_base = base.filter(pl.col("race_entry_id").is_in(special_ids))
    synthetic_past = sources.past_results
    for entry_id in special_ids:
        synthetic_past = _special_anchor(
            special_base.filter(pl.col("race_entry_id") == entry_id),
            synthetic_past,
            synthetic_race_id=-int(entry_id),
        )
    global_special = _apply_modules(
        special_base,
        replace(sources, past_results=synthetic_past),
        (context, entry, speed_figure, ability),
    ).select(
        "race_entry_id",
        *[spec.name for module in (speed_figure, ability) for spec in module.FEATURES],
    )
    replacements: list[pl.DataFrame] = []
    for entry_id in special_ids:
        target = base.filter(pl.col("race_entry_id") == entry_id)
        target_date = target.select(pl.col("race_date_local").cast(pl.Utf8).str.to_date()).item()
        prior_past = sources.past_results.filter(pl.col("race_date") < target_date)
        prior_sections = sources.sections.filter(pl.col("race_date") < target_date)
        special_sources = replace(
            sources,
            past_results=_special_anchor(target, prior_past),
            sections=prior_sections,
        )
        calculated = _apply_modules(
            target,
            special_sources,
            (context, entry, form, lifecycle, canonical_energy, style),
        )
        replacements.append(
            calculated.select(
                "race_entry_id",
                *[
                    spec.name
                    for module in (form, lifecycle, canonical_energy, style)
                    for spec in module.FEATURES
                ],
            )
        )
    if replacements:
        replacement = pl.concat(replacements, how="vertical_relaxed").join(
            global_special, on="race_entry_id", how="inner", validate="1:1"
        )
        result = result.join(replacement, on="race_entry_id", how="left", suffix="_e2")
        result = result.with_columns(
            *[
                pl.when(pl.col("race_entry_id").is_in(special_ids))
                .then(pl.col(f"{name}_e2"))
                .otherwise(pl.col(name))
                .alias(name)
                for name in history_names
            ]
        ).drop([f"{name}_e2" for name in history_names])
    result = _apply_modules(result, sources, _FIELD_MODULES)
    result = recompute_horse_jockey_history(result, sources.past_results)
    result = recompute_ability_vs_actual_field(result)
    forbidden = sorted(_TARGET_SOURCE_COLUMNS & set(result.columns))
    if forbidden:
        raise ConfirmedStarterContractError(
            f"target/result columns entered predictors: {forbidden}"
        )
    return result.sort(["race_date_local", "race_number", "horse_number"])


def recompute_horse_jockey_history(frame: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    """Derive E2 combo history by pair and strict prior date, independent of target result rows."""
    dated_past = as_date(past, "race_date")
    events: dict[tuple[int, int], tuple[list[object], list[int]]] = {}
    required = {"horse_id", "jockey_id", "race_date", "finish_position"}
    if dated_past.height and required <= set(dated_past.columns):
        eligible = dated_past.filter(
            pl.col("jockey_id").is_not_null()
            & pl.col("finish_position").is_between(1, 89, closed="both")
        ).sort(["horse_id", "jockey_id", "race_date", "race_entry_id"])
        for horse_id, jockey_id, race_date, finish_position in eligible.select(
            "horse_id", "jockey_id", "race_date", "finish_position"
        ).iter_rows():
            key = (int(horse_id), int(jockey_id))
            dates, cumulative_wins = events.setdefault(key, ([], [0]))
            dates.append(race_date)
            cumulative_wins.append(cumulative_wins[-1] + int(finish_position == 1))

    dated_frame = as_date(frame, "race_date")
    values: list[dict[str, int | None]] = []
    for race_entry_id, horse_id, jockey_id, race_date in dated_frame.select(
        "race_entry_id", "horse_id", "jockey_id", "race_date"
    ).iter_rows():
        if jockey_id is None:
            starts = wins = first = None
        else:
            dates, cumulative_wins = events.get((int(horse_id), int(jockey_id)), ([], [0]))
            starts = bisect_left(dates, race_date)
            wins = cumulative_wins[starts]
            first = int(starts == 0)
        values.append(
            {
                "race_entry_id": int(race_entry_id),
                "horse_jockey_starts": starts,
                "horse_jockey_wins": wins,
                "horse_jockey_first": first,
            }
        )
    replacement = pl.DataFrame(
        values,
        schema={
            "race_entry_id": pl.Int64,
            "horse_jockey_starts": pl.Int64,
            "horse_jockey_wins": pl.Int64,
            "horse_jockey_first": pl.Int64,
        },
    )
    names = ["horse_jockey_starts", "horse_jockey_wins", "horse_jockey_first"]
    return dated_frame.drop([name for name in names if name in dated_frame.columns]).join(
        replacement, on="race_entry_id", how="left", validate="1:1"
    )


def recompute_ability_vs_actual_field(frame: pl.DataFrame) -> pl.DataFrame:
    """Derive Elo-vs-field from completed individual pre-race Elo values over A."""
    count = pl.len().over("race_id")
    total = pl.col("ability_elo_global").sum().over("race_id")
    return frame.with_columns(
        pl.when(count > 1)
        .then(pl.col("ability_elo_global") - (total - pl.col("ability_elo_global")) / (count - 1))
        .otherwise(0.0)
        .alias("ability_elo_vs_field")
    )


def _retrospective_manifest(
    evidence: pl.DataFrame, evidence_path: Path
) -> ConfirmedStarterConditionalManifest:
    allowed = [
        OutcomeState.NORMAL_FINISH.value,
        OutcomeState.STARTED_DNF.value,
        OutcomeState.DISQUALIFIED.value,
    ]
    expected = tuple(
        sorted(
            (int(race_id), int(entry_id))
            for race_id, entry_id in evidence.filter(pl.col("outcome_state_e1").is_in(allowed))
            .select("race_id", "race_entry_id")
            .iter_rows()
        )
    )
    digest = key_sha256(expected)
    return ConfirmedStarterConditionalManifest(
        manifest_id=f"e2-a-{digest[:16]}",
        source_ids=(f"sha256:{_sha256_file(evidence_path)}", "database:read-only-fixed-e2-query"),
        field_kind=FIELD_KIND,
        selection_basis="post-event confirmed normal finish, started DNF, or disqualification",
        meet_code=MEET_CODE,
        date_start=START_DATE,
        date_end=END_DATE,
        actual_result_upper_bound=END_DATE,
        expected_keys=expected,
        key_sha256=digest,
        complete=True,
    )


def _compare_value(left: object, right: object, *, tolerance: float = FLOAT_ABS_TOLERANCE) -> str:
    if left is None and right is None:
        return "both_null_equal"
    if left is None:
        return "value_to_null"
    if right is None:
        return "null_to_value"
    if isinstance(left, Real) and isinstance(right, Real):
        left_float = float(left)
        right_float = float(right)
        if not isfinite(left_float) or not isfinite(right_float):
            return "non_finite"
        if left_float == right_float:
            return "exact_equal"
        if abs(left_float - right_float) <= tolerance:
            return "finite_within_tolerance"
        return "finite_value_change"
    return "exact_equal" if left == right else "non_numeric_value_change"


def _value_equal(left: pl.Series, right: pl.Series) -> pl.Series:
    """Compare null state exactly and apply tolerance only to finite numerics."""
    categories = [
        _compare_value(left_value, right_value)
        for left_value, right_value in zip(left, right, strict=True)
    ]
    equal = {"both_null_equal", "exact_equal", "finite_within_tolerance"}
    return pl.Series([category in equal for category in categories], dtype=pl.Boolean)


def independently_validate_field_features(
    frame: pl.DataFrame, selected_features: list[str]
) -> dict[str, Any]:
    """Check stored A-field derivatives against direct formulas, not a name whitelist."""
    count = pl.len().over("race_id")
    known = pl.col("early_pos_pct_avg5").is_not_null() & (pl.col("section_coverage5") >= 2)
    strong = known & (pl.col("early_pos_pct_avg5") <= 0.25)
    expected = frame.with_columns(
        count.cast(pl.Int64).alias("_expected_starters"),
        (pl.col("horse_number") / count).alias("_expected_horse_number_pct"),
        pl.when(pl.col("horse_number") / count <= 1 / 3)
        .then(pl.lit("안쪽"))
        .when(pl.col("horse_number") / count <= 2 / 3)
        .then(pl.lit("중간"))
        .otherwise(pl.lit("바깥쪽"))
        .alias("_expected_gate_band"),
        (known.cast(pl.Int64).sum().over("race_id") / count).alias("_expected_known_style_share"),
        strong.cast(pl.Int64).sum().over("race_id").alias("_expected_front_runner_count"),
        strong.cast(pl.Int64).alias("_expected_is_front"),
    ).with_columns(
        (pl.col("_expected_front_runner_count") - pl.col("_expected_is_front")).alias(
            "_expected_front_rival_count"
        )
    )
    expected = expected.with_columns(
        pl.when(pl.col("_expected_known_style_share") < 0.70)
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(pl.col("_expected_front_rival_count") == 0)
        .then(pl.lit("경합없음"))
        .when(pl.col("_expected_front_rival_count") == 1)
        .then(pl.lit("1두경합"))
        .otherwise(pl.lit("2두이상경합"))
        .alias("_expected_pace_pressure"),
        (
            pl.col("ability_elo_global")
            - (pl.col("ability_elo_global").sum().over("race_id") - pl.col("ability_elo_global"))
            / (count - 1)
        ).alias("_expected_ability_elo_vs_field"),
    )
    mapping = {
        "starters": "_expected_starters",
        "horse_number_pct": "_expected_horse_number_pct",
        "gate_band": "_expected_gate_band",
        "known_style_share": "_expected_known_style_share",
        "front_runner_count": "_expected_front_runner_count",
        "front_rival_count": "_expected_front_rival_count",
        "pace_pressure": "_expected_pace_pressure",
        "ability_elo_vs_field": "_expected_ability_elo_vs_field",
    }
    for target in relative.RELATIVE_TARGETS:
        if target not in frame.columns:
            continue
        mean = pl.col(target).mean().over("race_id")
        std = pl.col(target).std().over("race_id")
        z_name = f"{target}_race_z"
        rank_name = f"{target}_race_rank"
        expected = expected.with_columns(
            pl.when(std > 0)
            .then((pl.col(target) - mean) / std)
            .otherwise(None)
            .alias(f"_expected_{z_name}"),
            pl.col(target)
            .rank("average", descending=True)
            .over("race_id")
            .cast(pl.Float64)
            .alias(f"_expected_{rank_name}"),
        )
        mapping[z_name] = f"_expected_{z_name}"
        mapping[rank_name] = f"_expected_{rank_name}"

    mismatches: dict[str, int] = {}
    non_finite: dict[str, int] = {}
    verified: list[str] = []
    for name in selected_features:
        expected_name = mapping.get(name)
        if expected_name is None:
            continue
        categories = [
            _compare_value(actual, calculated)
            for actual, calculated in zip(frame[name], expected[expected_name], strict=True)
        ]
        mismatch = sum(
            category not in {"both_null_equal", "exact_equal", "finite_within_tolerance"}
            for category in categories
        )
        invalid = categories.count("non_finite")
        if mismatch:
            mismatches[name] = mismatch
        if invalid:
            non_finite[name] = invalid
        if not mismatch:
            verified.append(name)
    return {
        "verified_features": verified,
        "verified_feature_count": len(verified),
        "mismatches": mismatches,
        "non_finite": non_finite,
        "all_formulas_match": not mismatches and not non_finite,
    }


def independently_validate_horse_jockey_history(
    frame: pl.DataFrame, past: pl.DataFrame
) -> dict[str, Any]:
    """Validate combo features with a separate relational prior-date aggregation."""
    targets = as_date(frame, "race_date").select(
        "race_entry_id", "horse_id", "jockey_id", pl.col("race_date").alias("target_date")
    )
    known = targets.filter(pl.col("jockey_id").is_not_null())
    dated_past = as_date(past, "race_date")
    required = {"horse_id", "jockey_id", "race_date", "finish_position"}
    if dated_past.height and required <= set(dated_past.columns):
        events = dated_past.filter(
            pl.col("jockey_id").is_not_null()
            & pl.col("finish_position").is_between(1, 89, closed="both")
        ).select(
            "horse_id",
            "jockey_id",
            pl.col("race_date").alias("event_date"),
            (pl.col("finish_position") == 1).cast(pl.Int64).alias("event_win"),
        )
        aggregates = (
            known.join(events, on=["horse_id", "jockey_id"], how="inner")
            .filter(pl.col("event_date") < pl.col("target_date"))
            .group_by("race_entry_id")
            .agg(
                pl.len().cast(pl.Int64).alias("_expected_horse_jockey_starts"),
                pl.col("event_win").sum().cast(pl.Int64).alias("_expected_horse_jockey_wins"),
            )
        )
    else:
        aggregates = pl.DataFrame(
            schema={
                "race_entry_id": pl.Int64,
                "_expected_horse_jockey_starts": pl.Int64,
                "_expected_horse_jockey_wins": pl.Int64,
            }
        )
    expected = (
        known.join(aggregates, on="race_entry_id", how="left", validate="1:1")
        .with_columns(
            pl.col("_expected_horse_jockey_starts").fill_null(0),
            pl.col("_expected_horse_jockey_wins").fill_null(0),
        )
        .with_columns(
            (pl.col("_expected_horse_jockey_starts") == 0)
            .cast(pl.Int64)
            .alias("_expected_horse_jockey_first")
        )
        .select(
            "race_entry_id",
            "_expected_horse_jockey_starts",
            "_expected_horse_jockey_wins",
            "_expected_horse_jockey_first",
        )
    )
    checked = frame.join(expected, on="race_entry_id", how="left", validate="1:1")
    names = ["horse_jockey_starts", "horse_jockey_wins", "horse_jockey_first"]
    mismatches: dict[str, int] = {}
    mismatch_ids: set[int] = set()
    for name in names:
        expected_name = f"_expected_{name}"
        categories = [
            _compare_value(actual, calculated)
            for actual, calculated in zip(checked[name], checked[expected_name], strict=True)
        ]
        mask = [
            category not in {"both_null_equal", "exact_equal", "finite_within_tolerance"}
            for category in categories
        ]
        count = sum(mask)
        if count:
            mismatches[name] = count
        mismatch_ids.update(
            int(entry_id)
            for entry_id, mismatch in zip(checked["race_entry_id"], mask, strict=True)
            if mismatch
        )
    examples = {
        str(entry_id): {
            name: checked.filter(pl.col("race_entry_id") == entry_id)[name].item() for name in names
        }
        for entry_id in (19361, 19785, 20871)
        if checked.filter(pl.col("race_entry_id") == entry_id).height
    }
    return {
        "aggregation": (
            "independent relational join on horse_id+jockey_id with event_date < target_date; "
            "normal finishes 1..89 only"
        ),
        "checked_rows": checked.height,
        "mismatch_rows": len(mismatch_ids),
        "mismatches_by_feature": mismatches,
        "all_match": not mismatches,
        "evidence_examples": examples,
    }


def compare_previous_e2(
    frame: pl.DataFrame, previous: pl.DataFrame, selected_features: list[str]
) -> dict[str, Any]:
    """Account for every H1 cell change from the preserved E2 remediation v2."""
    validate_exact_keyset(
        tuple(frame.select("race_id", "race_entry_id").iter_rows()),
        tuple(previous.select("race_id", "race_entry_id").iter_rows()),
    )
    common = [name for name in frame.columns if name in previous.columns]
    payload = [name for name in common if name not in {"race_id", "race_entry_id"}]
    joined = frame.select("race_id", "race_entry_id", *payload).join(
        previous.select("race_id", "race_entry_id", *payload),
        on=["race_id", "race_entry_id"],
        how="inner",
        suffix="_old",
        validate="1:1",
    )
    selected = set(selected_features)
    selected_changes: dict[str, int] = {}
    non_selected_changes: dict[str, int] = {}
    within_tolerance: dict[str, int] = {}
    changed_ids: set[int] = set()
    normal_changed = 0
    for name in common:
        if name in {"race_id", "race_entry_id"}:
            continue
        categories = [
            _compare_value(value, old_value)
            for value, old_value in zip(joined[name], joined[f"{name}_old"], strict=True)
        ]
        changed_mask = [
            category not in {"both_null_equal", "exact_equal", "finite_within_tolerance"}
            for category in categories
        ]
        count = sum(changed_mask)
        tolerance_count = categories.count("finite_within_tolerance")
        if tolerance_count:
            within_tolerance[name] = tolerance_count
        if not count:
            continue
        destination = selected_changes if name in selected else non_selected_changes
        destination[name] = count
        changed_ids.update(
            int(entry_id)
            for entry_id, changed in zip(joined["race_entry_id"], changed_mask, strict=True)
            if changed
        )
        normal_changed += sum(
            changed and state == OutcomeState.NORMAL_FINISH.value
            for changed, state in zip(changed_mask, joined["outcome_state"], strict=True)
        )
    return {
        "previous_rows": previous.height,
        "current_rows": frame.height,
        "finite_float_absolute_tolerance": FLOAT_ABS_TOLERANCE,
        "changed_rows": len(changed_ids),
        "selected_changed_cells": sum(selected_changes.values()),
        "selected_changed_by_feature": selected_changes,
        "non_selected_changed_cells": sum(non_selected_changes.values()),
        "non_selected_changed_by_feature": non_selected_changes,
        "finite_within_tolerance_by_feature": within_tolerance,
        "normal_finish_changed_cells": normal_changed,
    }


def compare_reference_n(
    frame: pl.DataFrame, reference: pl.DataFrame, selected_features: list[str]
) -> dict[str, Any]:
    """Account for every selected-feature cell changed on the shared N key set."""
    normal = frame.filter(pl.col("outcome_state") == OutcomeState.NORMAL_FINISH.value)
    validate_exact_keyset(
        tuple(normal.select("race_id", "race_entry_id").iter_rows()),
        tuple(reference.select("race_id", "race_entry_id").iter_rows()),
    )
    new = normal.select("race_id", "race_entry_id", *selected_features)
    old = reference.select("race_id", "race_entry_id", *selected_features)
    joined = new.join(old, on=["race_id", "race_entry_id"], how="inner", suffix="_old")
    field_validation = independently_validate_field_features(frame, selected_features)
    verified_field = set(field_validation["verified_features"])
    expanded_races = set(
        frame.filter(pl.col("outcome_state") != OutcomeState.NORMAL_FINISH.value)[
            "race_id"
        ].to_list()
    )
    by_feature: dict[str, int] = {}
    transition_counts = {
        "null_to_value": 0,
        "value_to_null": 0,
        "finite_value_change": 0,
        "non_numeric_value_change": 0,
        "finite_within_tolerance": 0,
        "both_null_equal": 0,
        "exact_equal": 0,
        "non_finite": 0,
    }
    outside_expanded: dict[str, int] = {}
    for name in selected_features:
        categories = [
            _compare_value(new_value, old_value)
            for new_value, old_value in zip(joined[name], joined[f"{name}_old"], strict=True)
        ]
        for category in categories:
            transition_counts[category] += 1
        changed_mask = [
            category not in {"both_null_equal", "exact_equal", "finite_within_tolerance"}
            for category in categories
        ]
        changed = sum(changed_mask)
        if changed:
            by_feature[name] = changed
            outside = sum(
                is_changed and race_id not in expanded_races
                for is_changed, race_id in zip(changed_mask, joined["race_id"], strict=True)
            )
            if outside:
                outside_expanded[name] = outside
    explained_field = {
        name: count
        for name, count in by_feature.items()
        if name in verified_field and name in _FIELD_DEPENDENT_FEATURES
    }
    unexplained = {name: count for name, count in by_feature.items() if name not in explained_field}
    for name, count in outside_expanded.items():
        unexplained[name] = max(unexplained.get(name, 0), count)
    return {
        "shared_normal_rows": normal.height,
        "finite_float_absolute_tolerance": FLOAT_ABS_TOLERANCE,
        "nan_or_infinity_policy": "invalid; never equal, including same non-finite value",
        "changed_selected_cells": sum(by_feature.values()),
        "changed_by_feature": by_feature,
        "value_transition_counts": transition_counts,
        "expanded_races": len(expanded_races),
        "changes_outside_expanded_races": outside_expanded,
        "unaffected_races_have_zero_changes": not outside_expanded,
        "independent_field_formula_validation": field_validation,
        "field_expansion_changed_cells": sum(explained_field.values()),
        "field_expansion_changed_by_feature": explained_field,
        "intentional_generation_path_changed_cells": 0,
        "unexplained_changed_cells": sum(unexplained.values()),
        "unexplained_changed_by_feature": unexplained,
    }


def build_confirmed_starter_dataset(
    session: Session,
    *,
    evidence_path: Path,
    reference_dataset_path: Path,
    previous_e2_dataset_path: Path | None = None,
) -> ConfirmedStarterBuildResult:
    """Build the fixed-scope E2 retrospective A dataset in memory."""
    evidence = pl.read_parquet(evidence_path)
    retrospective = _retrospective_manifest(evidence, evidence_path)
    starters = confirmed_starter_labels(_fetch_rows(session))
    validate_dataset_against_manifest(retrospective, starters)
    if starters.filter(pl.col("scheduled_at_ms").is_null()).height:
        raise ConfirmedStarterContractError("confirmed starter has no scheduled time")
    sources = load_source_frames(session, race_date_max=END_DATE)
    predictors = build_predictors(starters, sources)
    targets = starters.select(
        "race_id",
        "race_entry_id",
        "outcome_state",
        "finish_position_target",
        "finish_time_ms_target",
        "auxiliary_rank_observed",
        "auxiliary_finish_time_observed",
        "win",
        "top2",
        "top3",
    )
    frame = predictors.join(targets, on=["race_id", "race_entry_id"], how="left", validate="1:1")
    validate_dataset_against_manifest(retrospective, frame)
    all_features = feature_names(frame, feature_set=FEATURE_SET)
    selected = select_profile_features(all_features, MODEL_PROFILE)
    reference = pl.read_parquet(reference_dataset_path)
    comparison = compare_reference_n(frame, reference, selected)
    combo_validation = independently_validate_horse_jockey_history(frame, sources.past_results)
    if not combo_validation["all_match"]:
        raise ConfirmedStarterContractError(
            "independent horse-jockey validation failed: "
            f"{combo_validation['mismatches_by_feature']}"
        )
    previous_comparison: dict[str, Any] | None = None
    if previous_e2_dataset_path is not None:
        previous_comparison = compare_previous_e2(
            frame, pl.read_parquet(previous_e2_dataset_path), selected
        )
        expected_h1 = {
            "horse_jockey_starts": 30,
            "horse_jockey_wins": 11,
            "horse_jockey_first": 30,
        }
        if (
            previous_comparison["changed_rows"] != 30
            or previous_comparison["selected_changed_cells"] != 71
            or previous_comparison["selected_changed_by_feature"] != expected_h1
            or previous_comparison["non_selected_changed_cells"]
            or previous_comparison["normal_finish_changed_cells"]
        ):
            raise ConfirmedStarterContractError(
                f"unexpected H1 changes from v2: {previous_comparison}"
            )
    if not comparison["independent_field_formula_validation"]["all_formulas_match"]:
        raise ConfirmedStarterContractError(
            "independent A-field formula validation failed: "
            f"{comparison['independent_field_formula_validation']['mismatches']}"
        )
    if comparison["unexplained_changed_cells"]:
        raise ConfirmedStarterContractError(
            f"unexplained selected feature changes: {comparison['unexplained_changed_by_feature']}"
        )

    counts = dict(
        starters.group_by("outcome_state").len().select("outcome_state", "len").iter_rows()
    )
    train = frame.filter(pl.col("race_date_local") <= TRAIN_END)
    valid = frame.filter(pl.col("race_date_local") >= VALID_START)
    observed = {
        "races": frame["race_id"].n_unique(),
        "rows": frame.height,
        "normal_finish": counts.get(OutcomeState.NORMAL_FINISH.value, 0),
        "started_dnf": counts.get(OutcomeState.STARTED_DNF.value, 0),
        "disqualified": counts.get(OutcomeState.DISQUALIFIED.value, 0),
        "train_rows": train.height,
        "valid_rows": valid.height,
    }
    if observed != EXPECTED_COUNTS:
        raise ConfirmedStarterContractError(
            f"fixed E2 counts changed: expected={EXPECTED_COUNTS}, observed={observed}"
        )
    null_rates = {name: float(frame[name].null_count() / frame.height) for name in selected}
    manifest = {
        "version": "confirmed_starter_e2_h1_remediation_retrospective",
        "created_at_ms": now_ms(),
        "field_contract": {
            "manifest_id": retrospective.manifest_id,
            "field_kind": retrospective.field_kind,
            "selection_basis": retrospective.selection_basis,
            "is_pre_race_field": False,
            "is_historical_t_minus_30_field": False,
            "source_ids": list(retrospective.source_ids),
            "complete": retrospective.complete,
            "expected_key_count": len(retrospective.expected_keys),
            "expected_key_sha256": retrospective.key_sha256,
            "expected_keys": [list(key) for key in retrospective.expected_keys],
            "difference_from_normal_finish_n": {
                "added_rows": 48,
                "started_dnf": 47,
                "disqualified": 1,
            },
        },
        "scope": {
            "meet_code": MEET_CODE,
            "date_start": START_DATE,
            "date_end": END_DATE,
            "actual_result_upper_bound": END_DATE,
            "prediction_time": "scheduled_at_ms - 30 minutes",
        },
        "state_mapping": {
            "normal_finish": "confirmed starter; official win/top2/top3; auxiliaries observed",
            "started_dnf": "confirmed starter; win/top2/top3=0; rank/time auxiliaries masked",
            "disqualified": "confirmed starter; win/top2/top3=0; rank/time auxiliaries masked",
            "did_not_start": (
                "excluded retrospectively from A; pre-race cancellation timing unknown"
            ),
            "missing_or_conflict": "not coerced to zero; build fails if admitted to A",
        },
        "counts": observed,
        "split": {
            "train": {"end": TRAIN_END, "rows": train.height},
            "development_validation": {
                "start": VALID_START,
                "end": END_DATE,
                "rows": valid.height,
            },
        },
        "feature_set": FEATURE_SET,
        "model_profile": MODEL_PROFILE,
        "feature_names": all_features,
        "feature_hash": hash_feature_names(all_features),
        "selected_feature_names": selected,
        "selected_feature_hash": hash_feature_names(selected),
        "selected_feature_null_rates": null_rates,
        "history_policy": (
            "Existing normal-finish-only past_results and section history retained. "
            "A DNF/disqualification is a null target anchor only for its own pre-race feature row "
            "and is never inserted into later historical rolling state."
        ),
        "field_feature_policy": (
            "starters, horse-number ratios, within-race relative features, and pace competition "
            "are calculated over retrospective A"
        ),
        "reference_normal_dataset": str(reference_dataset_path),
        "reference_comparison": comparison,
        "independent_horse_jockey_validation": combo_validation,
        "previous_e2_dataset": (
            str(previous_e2_dataset_path) if previous_e2_dataset_path is not None else None
        ),
        "previous_e2_comparison": previous_comparison,
        "limitations": [
            "A is conditioned on post-event confirmed start and is not historical F_t.",
            "Field-dependent predictors therefore also condition on retrospective A.",
            "Existing horse-sex and other documented snapshot PIT limitations remain.",
            "This development validation has already been used and is not an unopened test.",
        ],
    }
    return ConfirmedStarterBuildResult(frame=frame, manifest=manifest, comparison=comparison)
