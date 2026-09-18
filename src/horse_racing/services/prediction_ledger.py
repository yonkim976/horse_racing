"""Immutable publication and settlement ledger for pre-race probabilities."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from horse_racing.analysis.metrics import evaluate_probabilities, log_loss
from horse_racing.db.models import (
    ModelPrediction,
    ModelPredictionExplanation,
    PredictionModelComponent,
    PredictionOutcome,
    PredictionRun,
    PredictionSettlement,
    Race,
    RaceEntry,
    RaceResult,
)

PREDICTION_COLUMNS = (
    "race_id",
    "race_entry_id",
    "horse_number",
    "prob_win",
    "prob_top2",
    "prob_top3",
)
PROBABILITY_TOLERANCE = 1e-6
KST = ZoneInfo("Asia/Seoul")


class PredictionLedgerError(ValueError):
    """Raised when a publication would violate the public-ledger contract."""


@dataclass(frozen=True, slots=True)
class PredictionModelMetadata:
    experiment_run_id: str
    model_type: str
    dataset_version: str
    as_of_policy: str
    feature_hash: str
    model_artifact_sha256: str


@dataclass(frozen=True, slots=True)
class PredictionPublicationContext:
    domain: str
    prediction_stage: str
    registry_sha256: str
    input_card_sha256: str
    source_card_at_ms: int
    history_cutoff_date: date
    data_availability_status: str
    probability_contract: str
    combination_algorithm_version: str
    parent_public_id: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionComponentMetadata:
    component: str
    model_version: str
    candidate_name: str
    artifact_sha256: str
    metadata_sha256: str | None = None
    algorithm_version: str | None = None
    parameters: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PublicationSummary:
    public_id: str
    prediction_run_id: int
    race_date_local: str
    publication_mode: str
    race_count: int
    entry_count: int
    predictions_sha256: str
    publication_content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SettlementSummary:
    public_id: str
    settlement_id: int
    race_count: int
    entry_count: int
    excluded_races: int
    win_log_loss: float
    win_brier: float
    win_ece: float
    win_top1_hit_rate: float
    win_top3_inclusion_rate: float
    top2_log_loss: float
    top3_log_loss: float
    outcomes_sha256: str


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_prediction_rows(frame: pl.DataFrame) -> list[dict[str, int | float]]:
    def database_float(value: object) -> float:
        # The production Postgres path round-trips IEEE doubles through the
        # pooler at 15 significant digits.  Hash the stable database value,
        # rather than driver-specific extra digits, so read-back verification
        # remains deterministic across SQLite and Postgres.
        return float(format(float(value), ".15g"))

    ordered = frame.select(PREDICTION_COLUMNS).sort("race_id", "horse_number")
    return [
        {
            "race_id": int(row["race_id"]),
            "race_entry_id": int(row["race_entry_id"]),
            "horse_number": int(row["horse_number"]),
            "prob_win": database_float(row["prob_win"]),
            "prob_top2": database_float(row["prob_top2"]),
            "prob_top3": database_float(row["prob_top3"]),
        }
        for row in ordered.to_dicts()
    ]


def prediction_payload_hash(frame: pl.DataFrame) -> str:
    return _sha256_json(_canonical_prediction_rows(frame))


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _validate_publication_context(context: PredictionPublicationContext) -> None:
    if context.domain not in {"thoroughbred", "jeju"}:
        raise PredictionLedgerError("domain은 thoroughbred 또는 jeju여야 합니다.")
    if context.prediction_stage not in {"initial_card", "pre_race_update"}:
        raise PredictionLedgerError(
            "prediction_stage는 initial_card 또는 pre_race_update여야 합니다."
        )
    if context.data_availability_status not in {"complete", "partial", "not_available"}:
        raise PredictionLedgerError("지원하지 않는 data_availability_status입니다.")
    for label, value in (
        ("registry_sha256", context.registry_sha256),
        ("input_card_sha256", context.input_card_sha256),
    ):
        if not _valid_sha256(value):
            raise PredictionLedgerError(f"{label}는 64자리 SHA-256이어야 합니다.")
    if context.source_card_at_ms <= 0:
        raise PredictionLedgerError("source_card_at_ms는 양수여야 합니다.")
    if context.prediction_stage == "initial_card" and context.parent_public_id is not None:
        raise PredictionLedgerError("initial_card 실행은 parent_public_id를 가질 수 없습니다.")
    if context.prediction_stage == "pre_race_update" and context.parent_public_id is None:
        raise PredictionLedgerError("pre_race_update 실행에는 parent_public_id가 필요합니다.")


def _canonical_component_rows(
    components: tuple[PredictionComponentMetadata, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for component in sorted(components, key=lambda item: item.component):
        if component.component in seen:
            raise PredictionLedgerError(f"중복 모델 component: {component.component}")
        seen.add(component.component)
        if not _valid_sha256(component.artifact_sha256):
            raise PredictionLedgerError(
                f"component={component.component} artifact_sha256가 올바르지 않습니다."
            )
        if component.metadata_sha256 is not None and not _valid_sha256(
            component.metadata_sha256
        ):
            raise PredictionLedgerError(
                f"component={component.component} metadata_sha256가 올바르지 않습니다."
            )
        rows.append(
            {
                "component": component.component,
                "model_version": component.model_version,
                "candidate_name": component.candidate_name,
                "artifact_sha256": component.artifact_sha256,
                "metadata_sha256": component.metadata_sha256,
                "algorithm_version": component.algorithm_version,
                "parameters": component.parameters or {},
            }
        )
    if not rows:
        raise PredictionLedgerError("모델 component 메타데이터가 비어 있습니다.")
    return rows


COMMON_DETAIL_COLUMNS = {
    "race_entry_id",
    "a_rank_in_race",
    "field_size",
    "starter_status",
}
THOROUGHBRED_DETAIL_COLUMNS = {
    "raw_a_top3_score",
    "raw_bc_top3_score",
    "raw_win_score",
}
JEJU_DETAIL_COLUMNS = {"raw_rank_score", "raw_order_score", "beta_set", "beta_order"}
OPTIONAL_DETAIL_COLUMNS = (
    "runner_identifier",
    "jockey_identifier",
    "trainer_identifier",
    "owner_identifier",
    "cancellation_status",
    "body_weight_kg",
    "body_weight_change_kg",
    "data_quality_flags_json",
)


def _validate_runner_details(
    frame: pl.DataFrame,
    selected: pl.DataFrame,
    domain: str,
) -> list[dict[str, object]]:
    required = COMMON_DETAIL_COLUMNS | (
        THOROUGHBRED_DETAIL_COLUMNS if domain == "thoroughbred" else JEJU_DETAIL_COLUMNS
    )
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PredictionLedgerError(f"말별 상세 컬럼 없음: {', '.join(missing)}")
    detail_columns = sorted(required) + [
        column for column in OPTIONAL_DETAIL_COLUMNS if column in frame.columns
    ]
    details = frame.select(detail_columns)
    if details["race_entry_id"].n_unique() != details.height:
        raise PredictionLedgerError("말별 상세에 중복 race_entry_id가 있습니다.")
    expected_ids = set(selected["race_entry_id"].to_list())
    actual_ids = set(details["race_entry_id"].to_list())
    if actual_ids != expected_ids:
        raise PredictionLedgerError("말별 상세와 확률 payload의 race_entry_id가 다릅니다.")
    required_without_status = sorted(required - {"starter_status"})
    if details.select(required_without_status).null_count().select(
        pl.sum_horizontal(pl.all())
    ).item():
        raise PredictionLedgerError("필수 말별 상세값에 null이 있습니다.")
    if details.filter(pl.col("starter_status").is_null()).height:
        raise PredictionLedgerError("starter_status가 null인 말이 있습니다.")
    selected_by_entry = {
        int(row["race_entry_id"]): row for row in selected.iter_rows(named=True)
    }
    for row in details.iter_rows(named=True):
        probability_row = selected_by_entry[int(row["race_entry_id"])]
        if int(row["field_size"]) <= 0 or int(row["a_rank_in_race"]) <= 0:
            raise PredictionLedgerError("field_size와 a_rank_in_race는 양수여야 합니다.")
        if int(row["a_rank_in_race"]) > int(row["field_size"]):
            raise PredictionLedgerError("a_rank_in_race가 field_size보다 큽니다.")
        if probability_row["horse_number"] <= 0:
            raise PredictionLedgerError("horse_number는 양수여야 합니다.")
    joined = selected.select("race_id", "race_entry_id").join(
        details.select("race_entry_id", "a_rank_in_race", "field_size"),
        on="race_entry_id",
    )
    for race_id, group in joined.group_by("race_id"):
        key = race_id[0] if isinstance(race_id, tuple) else race_id
        sizes = group["field_size"].unique().to_list()
        ranks = sorted(group["a_rank_in_race"].cast(pl.Int64).to_list())
        if sizes != [group.height]:
            raise PredictionLedgerError(f"race_id={key} field_size가 출전마 수와 다릅니다.")
        if ranks != list(range(1, group.height + 1)):
            raise PredictionLedgerError(f"race_id={key} A 순위가 순열이 아닙니다.")
    return sorted(details.to_dicts(), key=lambda row: int(row["race_entry_id"]))


EXPLANATION_COLUMNS = {
    "race_entry_id",
    "component",
    "feature_name",
    "readable_feature_name",
    "feature_value",
    "field_percentile",
    "contribution_direction",
    "contribution_value",
    "contribution_rank",
    "explanation_type",
    "explanation_method",
    "source_cutoff_at_ms",
}


def _canonical_explanation_rows(
    frame: pl.DataFrame,
    entry_ids: set[int],
) -> list[dict[str, object]]:
    missing = sorted(EXPLANATION_COLUMNS - set(frame.columns))
    if missing:
        raise PredictionLedgerError(f"설명 컬럼 없음: {', '.join(missing)}")
    rows = frame.select(sorted(EXPLANATION_COLUMNS)).to_dicts()
    if not rows:
        raise PredictionLedgerError("말별 설명이 비어 있습니다.")
    by_runner: dict[int, dict[str, list[int]]] = {}
    canonical: list[dict[str, object]] = []
    for row in rows:
        entry_id = int(row["race_entry_id"])
        if entry_id not in entry_ids:
            raise PredictionLedgerError(f"설명에 알 수 없는 race_entry_id={entry_id}")
        direction = str(row["contribution_direction"])
        rank = int(row["contribution_rank"])
        contribution = float(row["contribution_value"])
        if direction not in {"positive", "negative"} or rank not in {1, 2, 3}:
            raise PredictionLedgerError("설명 방향 또는 순위가 올바르지 않습니다.")
        if (direction == "positive" and contribution < 0) or (
            direction == "negative" and contribution > 0
        ):
            raise PredictionLedgerError("설명 방향과 기여도 부호가 다릅니다.")
        explanation_type = str(row["explanation_type"])
        if explanation_type not in {
            "interpretable",
            "categorical_model_effect",
            "data_quality_flag",
        }:
            raise PredictionLedgerError("지원하지 않는 explanation_type입니다.")
        percentile = row["field_percentile"]
        if percentile is not None and not 0 <= float(percentile) <= 1:
            raise PredictionLedgerError("field_percentile은 0~1이어야 합니다.")
        feature_name = str(row["feature_name"])
        id_tokens = ("jockey_id", "trainer_id", "owner_id", "horse_id")
        if any(token in feature_name.lower() for token in id_tokens) and explanation_type != (
            "categorical_model_effect"
        ):
            raise PredictionLedgerError(
                f"ID 효과는 categorical_model_effect여야 합니다: {feature_name}"
            )
        ranks = by_runner.setdefault(entry_id, {"positive": [], "negative": []})
        ranks[direction].append(rank)
        canonical.append(
            {
                **row,
                "race_entry_id": entry_id,
                "field_percentile": None if percentile is None else float(percentile),
                "contribution_value": contribution,
                "contribution_rank": rank,
                "feature_value": row["feature_value"],
            }
        )
    if set(by_runner) != entry_ids:
        missing_ids = sorted(entry_ids - set(by_runner))
        raise PredictionLedgerError(f"설명이 없는 race_entry_id: {missing_ids[:10]}")
    for entry_id, directions in by_runner.items():
        for direction, ranks in directions.items():
            if sorted(ranks) != [1, 2, 3]:
                raise PredictionLedgerError(
                    f"race_entry_id={entry_id} {direction} 설명은 정확히 3개여야 합니다."
                )
    return sorted(
        canonical,
        key=lambda row: (
            int(row["race_entry_id"]),
            str(row["component"]),
            str(row["contribution_direction"]),
            int(row["contribution_rank"]),
        ),
    )


def _publication_content_hash(
    selected: pl.DataFrame,
    context: PredictionPublicationContext,
    components: list[dict[str, object]],
    details: list[dict[str, object]],
    explanations: list[dict[str, object]],
) -> str:
    context_payload = asdict(context)
    context_payload["history_cutoff_date"] = context.history_cutoff_date.isoformat()
    return _sha256_json(
        {
            "context": context_payload,
            "components": components,
            "predictions": _canonical_prediction_rows(selected),
            "runner_details": details,
            "explanations": explanations,
        }
    )


def _validate_probability_frame(frame: pl.DataFrame) -> pl.DataFrame:
    missing = sorted(set(PREDICTION_COLUMNS) - set(frame.columns))
    if missing:
        raise PredictionLedgerError(f"예측 컬럼 없음: {', '.join(missing)}")
    selected = frame.select(PREDICTION_COLUMNS)
    if selected.height == 0:
        raise PredictionLedgerError("예측 파일이 비어 있습니다.")
    duplicate_count = selected.select(
        pl.struct("race_entry_id").is_duplicated().sum()
    ).item()
    if duplicate_count:
        raise PredictionLedgerError(f"중복 race_entry_id가 {duplicate_count}건 있습니다.")
    if selected.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise PredictionLedgerError("예측값 또는 식별자에 null이 있습니다.")
    for column in ("prob_win", "prob_top2", "prob_top3"):
        invalid = selected.filter(
            ~pl.col(column).is_finite() | (pl.col(column) < 0) | (pl.col(column) > 1)
        ).height
        if invalid:
            raise PredictionLedgerError(f"{column} 범위 밖 값이 {invalid}건 있습니다.")
    monotonic_violations = selected.filter(
        (pl.col("prob_win") > pl.col("prob_top2") + PROBABILITY_TOLERANCE)
        | (pl.col("prob_top2") > pl.col("prob_top3") + PROBABILITY_TOLERANCE)
    ).height
    if monotonic_violations:
        raise PredictionLedgerError(
            f"P(win) ≤ P(top2) ≤ P(top3) 위반이 {monotonic_violations}건 있습니다."
        )
    for race_id, group in selected.group_by("race_id"):
        runner_count = group.height
        targets = {
            "prob_win": 1.0,
            "prob_top2": float(min(2, runner_count)),
            "prob_top3": float(min(3, runner_count)),
        }
        for column, target in targets.items():
            total = float(group[column].sum())
            if not math.isclose(total, target, abs_tol=PROBABILITY_TOLERANCE):
                key = race_id[0] if isinstance(race_id, tuple) else race_id
                raise PredictionLedgerError(
                    f"race_id={key} {column} 합={total:.8f}, 기대값={target:.1f}"
                )
    return selected.sort("race_id", "horse_number")


def _as_of_deadline_ms(as_of_policy: str, race_date, scheduled_at_ms: int) -> int:
    if as_of_policy == "start_minus_30m":
        return scheduled_at_ms - 30 * 60 * 1000
    if as_of_policy == "day_before_18":
        deadline_date = race_date - timedelta(days=1)
        deadline = datetime.combine(deadline_date, datetime_time(18, 0), tzinfo=KST)
        return int(deadline.timestamp() * 1000)
    raise PredictionLedgerError(f"지원하지 않는 as-of 정책: {as_of_policy}")


def publish_predictions(
    session: Session,
    predictions: pl.DataFrame,
    *,
    metadata: PredictionModelMetadata,
    feature_cutoff_at_ms: int,
    publication_mode: str = "live",
    published_at_ms: int | None = None,
    notes: str | None = None,
    publication_context: PredictionPublicationContext | None = None,
    model_components: tuple[PredictionComponentMetadata, ...] = (),
    runner_details: pl.DataFrame | None = None,
    explanations: pl.DataFrame | None = None,
) -> PublicationSummary:
    """Atomically append one complete prediction publication.

    ``live`` publications must be written no later than every included race's
    model as-of deadline.
    ``historical`` is available for UI/settlement testing, but public summaries
    keep it separate from prospective performance.
    """
    if publication_mode not in {"live", "historical"}:
        raise PredictionLedgerError("publication_mode은 live 또는 historical이어야 합니다.")
    published = now_ms() if published_at_ms is None else published_at_ms
    if feature_cutoff_at_ms > published:
        raise PredictionLedgerError("feature cutoff은 실제 발행시각보다 늦을 수 없습니다.")
    selected = _validate_probability_frame(predictions)
    component_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    explanation_rows: list[dict[str, object]] = []
    content_hash: str | None = None
    parent_prediction_run_id: int | None = None
    parent_run: PredictionRun | None = None
    if publication_context is not None:
        _validate_publication_context(publication_context)
        if runner_details is None or explanations is None:
            raise PredictionLedgerError(
                "확장 publication에는 말별 상세와 설명 데이터가 모두 필요합니다."
            )
        component_rows = _canonical_component_rows(model_components)
        detail_rows = _validate_runner_details(
            runner_details,
            selected,
            publication_context.domain,
        )
        explanation_rows = _canonical_explanation_rows(
            explanations,
            set(int(value) for value in selected["race_entry_id"].to_list()),
        )
        content_hash = _publication_content_hash(
            selected,
            publication_context,
            component_rows,
            detail_rows,
            explanation_rows,
        )
        if session.scalar(
            select(PredictionRun.id).where(
                PredictionRun.publication_content_sha256 == content_hash
            )
        ) is not None:
            raise PredictionLedgerError(
                f"동일 확장 publication payload가 이미 발행됐습니다: {content_hash}"
            )
        if publication_context.parent_public_id is not None:
            parent = session.scalar(
                select(PredictionRun).where(
                    PredictionRun.public_id == publication_context.parent_public_id
                )
            )
            if parent is None:
                raise PredictionLedgerError(
                    "알 수 없는 parent_public_id: "
                    f"{publication_context.parent_public_id}"
                )
            if parent.prediction_stage != "initial_card":
                raise PredictionLedgerError("pre_race_update의 부모는 initial_card여야 합니다.")
            if parent.publication_mode != "live":
                raise PredictionLedgerError("pre_race_update의 부모는 live 발행이어야 합니다.")
            if parent.domain != publication_context.domain:
                raise PredictionLedgerError("부모 실행과 domain이 다릅니다.")
            parent_prediction_run_id = parent.id
            parent_run = parent
    entry_ids = selected["race_entry_id"].to_list()
    db_rows = session.execute(
        select(
            RaceEntry.id,
            RaceEntry.race_id,
            RaceEntry.horse_number,
            RaceEntry.scratched,
            Race.race_date_local,
            Race.scheduled_at_ms,
        )
        .join(Race, Race.id == RaceEntry.race_id)
        .where(RaceEntry.id.in_(entry_ids))
    ).all()
    if len(db_rows) != len(entry_ids):
        found = {row.id for row in db_rows}
        missing = sorted(set(entry_ids) - found)
        raise PredictionLedgerError(f"DB에 없는 race_entry_id: {missing[:10]}")
    db_by_entry = {row.id: row for row in db_rows}
    for row in selected.iter_rows(named=True):
        db_row = db_by_entry[row["race_entry_id"]]
        if db_row.race_id != row["race_id"] or db_row.horse_number != row["horse_number"]:
            raise PredictionLedgerError(
                f"race_entry_id={row['race_entry_id']}의 race/horse_number가 DB와 다릅니다."
            )
        if db_row.scratched:
            raise PredictionLedgerError(
                f"발행 시점 출전취소 entry가 예측에 포함됐습니다: {row['race_entry_id']}"
            )

    race_ids = sorted(selected["race_id"].unique().to_list())
    if publication_mode == "live":
        existing_live = session.execute(
            select(
                ModelPrediction.race_id,
                PredictionRun.id,
                PredictionRun.parent_prediction_run_id,
            )
            .join(
                PredictionRun,
                PredictionRun.id == ModelPrediction.prediction_run_id,
            )
            .where(
                PredictionRun.publication_mode == "live",
                ModelPrediction.race_id.in_(race_ids),
            )
        ).all()
        if existing_live:
            is_update = (
                publication_context is not None
                and publication_context.prediction_stage == "pre_race_update"
                and parent_run is not None
            )
            if not is_update:
                existing_live_races = sorted({row.race_id for row in existing_live})
                raise PredictionLedgerError(
                    "이미 live 예측이 발행된 경주는 initial_card로 다시 발행할 수 없습니다: "
                    f"{existing_live_races}"
                )
            parent_race_ids = set(
                session.scalars(
                    select(ModelPrediction.race_id).where(
                        ModelPrediction.prediction_run_id == parent_run.id
                    )
                )
            )
            if not set(race_ids).issubset(parent_race_ids):
                raise PredictionLedgerError(
                    "pre_race_update 경주는 부모 initial_card 경주의 부분집합이어야 합니다."
                )
            unrelated = sorted(
                {
                    row.race_id
                    for row in existing_live
                    if row.id != parent_run.id
                    and row.parent_prediction_run_id != parent_run.id
                }
            )
            if unrelated:
                raise PredictionLedgerError(
                    "다른 live 계보가 이미 존재하는 경주입니다: " f"{unrelated}"
                )
    expected_rows = session.execute(
        select(RaceEntry.id, RaceEntry.race_id)
        .where(RaceEntry.race_id.in_(race_ids), RaceEntry.scratched.is_(False))
    ).all()
    expected_entry_ids = {row.id for row in expected_rows}
    supplied_entry_ids = set(entry_ids)
    if supplied_entry_ids != expected_entry_ids:
        missing = sorted(expected_entry_ids - supplied_entry_ids)
        extra = sorted(supplied_entry_ids - expected_entry_ids)
        raise PredictionLedgerError(
            f"경주 출전마 전체 예측이 필요합니다. 누락={missing[:10]}, 초과={extra[:10]}"
        )
    race_dates = {row.race_date_local for row in db_rows}
    if len(race_dates) != 1:
        raise PredictionLedgerError("한 publication에는 같은 경주일만 포함할 수 있습니다.")
    if publication_mode == "live":
        missing_schedule = sorted(
            {row.race_id for row in db_rows if row.scheduled_at_ms is None}
        )
        if missing_schedule:
            raise PredictionLedgerError(f"예정 출발시각 없는 race_id: {missing_schedule}")
        late_races = sorted(
            {row.race_id for row in db_rows if published >= row.scheduled_at_ms}
        )
        if late_races:
            raise PredictionLedgerError(
                f"발행시각이 출발시각 이후인 race_id: {late_races}. live 원장에 기록하지 않습니다."
            )
        as_of_late_races = sorted(
            {
                row.race_id
                for row in db_rows
                if max(feature_cutoff_at_ms, published)
                > _as_of_deadline_ms(
                    metadata.as_of_policy,
                    row.race_date_local,
                    row.scheduled_at_ms,
                )
            }
        )
        if as_of_late_races:
            raise PredictionLedgerError(
                "feature cutoff 또는 발행시각이 모델 as-of 시각을 지난 race_id: "
                f"{as_of_late_races}. live 원장에 기록하지 않습니다."
            )

    payload_hash = prediction_payload_hash(selected)
    if session.scalar(
        select(PredictionRun.id).where(PredictionRun.predictions_sha256 == payload_hash)
    ) is not None:
        raise PredictionLedgerError(f"동일 예측 payload가 이미 발행됐습니다: {payload_hash}")
    prediction_run = PredictionRun(
        public_id=str(uuid.uuid4()),
        experiment_run_id=metadata.experiment_run_id,
        model_type=metadata.model_type,
        dataset_version=metadata.dataset_version,
        as_of_policy=metadata.as_of_policy,
        race_date_local=next(iter(race_dates)),
        feature_cutoff_at_ms=feature_cutoff_at_ms,
        published_at_ms=published,
        publication_mode=publication_mode,
        model_artifact_sha256=metadata.model_artifact_sha256,
        feature_hash=metadata.feature_hash,
        predictions_sha256=payload_hash,
        publication_content_sha256=content_hash,
        domain=publication_context.domain if publication_context else None,
        prediction_stage=(
            publication_context.prediction_stage if publication_context else None
        ),
        parent_prediction_run_id=parent_prediction_run_id,
        registry_sha256=(publication_context.registry_sha256 if publication_context else None),
        input_card_sha256=(
            publication_context.input_card_sha256 if publication_context else None
        ),
        source_card_at_ms=(
            publication_context.source_card_at_ms if publication_context else None
        ),
        history_cutoff_date=(
            publication_context.history_cutoff_date if publication_context else None
        ),
        data_availability_status=(
            publication_context.data_availability_status if publication_context else None
        ),
        probability_contract=(
            publication_context.probability_contract if publication_context else None
        ),
        combination_algorithm_version=(
            publication_context.combination_algorithm_version
            if publication_context
            else None
        ),
        notes=notes,
    )
    session.add(prediction_run)
    session.flush()
    for row in component_rows:
        parameters = row.pop("parameters")
        session.add(
            PredictionModelComponent(
                prediction_run_id=prediction_run.id,
                parameters_json=json.dumps(
                    parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                **row,
            )
        )
    details_by_entry = {
        int(row["race_entry_id"]): row.copy() for row in detail_rows
    }
    predictions_by_entry: dict[int, ModelPrediction] = {}
    for row in _canonical_prediction_rows(selected):
        entry_id = int(row["race_entry_id"])
        details = details_by_entry.get(entry_id, {})
        details.pop("race_entry_id", None)
        prediction = ModelPrediction(
            prediction_run_id=prediction_run.id,
            **row,
            **details,
        )
        session.add(prediction)
        predictions_by_entry[entry_id] = prediction
    session.flush()
    for row in explanation_rows:
        entry_id = int(row.pop("race_entry_id"))
        feature_value = row.pop("feature_value")
        session.add(
            ModelPredictionExplanation(
                model_prediction_id=predictions_by_entry[entry_id].id,
                feature_value_json=json.dumps(
                    feature_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                **row,
            )
        )
    session.commit()
    return PublicationSummary(
        public_id=prediction_run.public_id,
        prediction_run_id=prediction_run.id,
        race_date_local=prediction_run.race_date_local.isoformat(),
        publication_mode=publication_mode,
        race_count=len(race_ids),
        entry_count=selected.height,
        predictions_sha256=payload_hash,
        publication_content_sha256=content_hash,
    )


def _binary_row_loss(probability: float, label: bool) -> float:
    clipped = min(max(probability, 1e-15), 1 - 1e-15)
    return -math.log(clipped if label else 1 - clipped)


def settle_prediction_run(
    session: Session,
    public_id: str,
    *,
    settled_at_ms: int | None = None,
) -> SettlementSummary:
    prediction_run = session.scalar(
        select(PredictionRun)
        .where(PredictionRun.public_id == public_id)
        .options(selectinload(PredictionRun.predictions))
    )
    if prediction_run is None:
        raise PredictionLedgerError(f"알 수 없는 prediction public_id: {public_id}")
    if prediction_run.settlement is not None:
        raise PredictionLedgerError(
            f"이미 정산된 prediction입니다: {prediction_run.settlement.public_id}"
        )
    prediction_ids = [item.id for item in prediction_run.predictions]
    rows = session.execute(
        select(
            ModelPrediction,
            Race.status,
            RaceEntry.scratched,
            RaceResult.finish_position,
        )
        .join(RaceEntry, RaceEntry.id == ModelPrediction.race_entry_id)
        .join(Race, Race.id == ModelPrediction.race_id)
        .outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(ModelPrediction.id.in_(prediction_ids))
    ).all()
    if len(rows) != len(prediction_ids):
        raise PredictionLedgerError("예측과 DB 출전마 join 행 수가 다릅니다.")
    incomplete_races = sorted({row[0].race_id for row in rows if row[1] != "completed"})
    if incomplete_races:
        raise PredictionLedgerError(f"아직 완료되지 않은 race_id: {incomplete_races}")

    exclusion_by_race: dict[int, str] = {}
    for prediction, _, scratched, finish_position in rows:
        if scratched:
            exclusion_by_race[prediction.race_id] = "post_publication_scratch"
        elif finish_position is None:
            exclusion_by_race[prediction.race_id] = "missing_finish_position"
        elif finish_position >= 90:
            exclusion_by_race[prediction.race_id] = "special_finish_code"

    scored_rows: list[dict[str, int | float]] = []
    outcome_payload: list[dict[str, object]] = []
    outcome_specs: list[dict[str, object]] = []
    for prediction, _, _, finish_position in sorted(
        rows, key=lambda item: (item[0].race_id, item[0].horse_number)
    ):
        exclusion_reason = exclusion_by_race.get(prediction.race_id)
        if exclusion_reason is not None:
            spec = {
                "model_prediction_id": prediction.id,
                "finish_position": finish_position,
                "is_scored": False,
                "exclusion_reason": exclusion_reason,
                "win": None,
                "top2": None,
                "top3": None,
                "win_log_loss": None,
            }
        else:
            win = finish_position == 1
            top2 = finish_position <= 2
            top3 = finish_position <= 3
            row_loss = _binary_row_loss(prediction.prob_win, win)
            spec = {
                "model_prediction_id": prediction.id,
                "finish_position": finish_position,
                "is_scored": True,
                "exclusion_reason": None,
                "win": win,
                "top2": top2,
                "top3": top3,
                "win_log_loss": row_loss,
            }
            scored_rows.append(
                {
                    "race_id": prediction.race_id,
                    "prob_win": prediction.prob_win,
                    "prob_top2": prediction.prob_top2,
                    "prob_top3": prediction.prob_top3,
                    "win": int(win),
                    "top2": int(top2),
                    "top3": int(top3),
                }
            )
        outcome_specs.append(spec)
        outcome_payload.append(
            {
                "race_id": prediction.race_id,
                "race_entry_id": prediction.race_entry_id,
                **spec,
            }
        )
    if not scored_rows:
        raise PredictionLedgerError("정산 가능한 정상 경주가 없습니다.")
    scored = pl.DataFrame(scored_rows)
    win_metrics = evaluate_probabilities(scored, "prob_win", label_column="win")
    top2_loss = log_loss(scored["prob_top2"].to_list(), scored["top2"].to_list())
    top3_loss = log_loss(scored["prob_top3"].to_list(), scored["top3"].to_list())
    outcomes_hash = _sha256_json(outcome_payload)
    settlement = PredictionSettlement(
        public_id=str(uuid.uuid4()),
        prediction_run_id=prediction_run.id,
        settled_at_ms=now_ms() if settled_at_ms is None else settled_at_ms,
        outcomes_sha256=outcomes_hash,
        n_races=len({item.race_id for item in prediction_run.predictions}),
        n_entries=len(prediction_run.predictions),
        n_excluded_races=len(exclusion_by_race),
        win_log_loss=win_metrics["log_loss"],
        win_brier=win_metrics["brier"],
        win_ece=win_metrics["ece"],
        win_top1_hit_rate=win_metrics["top1_hit_rate"],
        win_top3_inclusion_rate=win_metrics["top3_inclusion_rate"],
        top2_log_loss=top2_loss,
        top3_log_loss=top3_loss,
    )
    session.add(settlement)
    session.flush()
    for spec in outcome_specs:
        session.add(PredictionOutcome(settlement_id=settlement.id, **spec))
    session.commit()
    return SettlementSummary(
        public_id=settlement.public_id,
        settlement_id=settlement.id,
        race_count=settlement.n_races,
        entry_count=settlement.n_entries,
        excluded_races=settlement.n_excluded_races,
        win_log_loss=settlement.win_log_loss,
        win_brier=settlement.win_brier,
        win_ece=settlement.win_ece,
        win_top1_hit_rate=settlement.win_top1_hit_rate,
        win_top3_inclusion_rate=settlement.win_top3_inclusion_rate,
        top2_log_loss=settlement.top2_log_loss,
        top3_log_loss=settlement.top3_log_loss,
        outcomes_sha256=outcomes_hash,
    )


def verify_prediction_hash(session: Session, public_id: str) -> bool:
    prediction_run = session.scalar(
        select(PredictionRun)
        .where(PredictionRun.public_id == public_id)
        .options(selectinload(PredictionRun.predictions))
    )
    if prediction_run is None:
        raise PredictionLedgerError(f"알 수 없는 prediction public_id: {public_id}")
    frame = pl.DataFrame(
        [
            {
                column: getattr(prediction, column)
                for column in PREDICTION_COLUMNS
            }
            for prediction in prediction_run.predictions
        ]
    )
    return prediction_payload_hash(frame) == prediction_run.predictions_sha256
