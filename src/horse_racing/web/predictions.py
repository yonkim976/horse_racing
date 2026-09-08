from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from horse_racing.analysis.metrics import evaluate_probabilities
from horse_racing.db.models import (
    ModelPrediction,
    PredictionOutcome,
    PredictionRun,
)

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class PredictionLedgerRow:
    public_id: str
    mode: str
    mode_label: str
    race_date: str
    published_at: str
    race_count: int
    entry_count: int
    status: str
    status_label: str
    win_log_loss: str
    top1: str
    hash_short: str


@dataclass(frozen=True, slots=True)
class PredictionLedgerPage:
    live_publications: int
    live_settlements: int
    live_races: int
    historical_publications: int
    aggregate_win_log_loss: str
    aggregate_ece: str
    aggregate_top1: str
    aggregate_scored_races: int
    rows: list[PredictionLedgerRow]


def _format_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_prediction_ledger(session: Session) -> PredictionLedgerPage:
    runs = session.scalars(
        select(PredictionRun)
        .options(
            selectinload(PredictionRun.predictions),
            selectinload(PredictionRun.settlement),
        )
        .order_by(PredictionRun.published_at_ms.desc())
    ).all()
    live_runs = [run for run in runs if run.publication_mode == "live"]
    aggregate_rows = session.execute(
        select(
            ModelPrediction.race_id,
            ModelPrediction.prob_win,
            PredictionOutcome.win,
        )
        .join(PredictionRun, PredictionRun.id == ModelPrediction.prediction_run_id)
        .join(
            PredictionOutcome,
            PredictionOutcome.model_prediction_id == ModelPrediction.id,
        )
        .where(
            PredictionRun.publication_mode == "live",
            PredictionOutcome.is_scored.is_(True),
        )
    ).all()
    aggregate_metrics: dict[str, float] | None = None
    if aggregate_rows:
        frame = pl.DataFrame(
            {
                "race_id": [row.race_id for row in aggregate_rows],
                "prob_win": [row.prob_win for row in aggregate_rows],
                "win": [int(row.win) for row in aggregate_rows],
            }
        )
        aggregate_metrics = evaluate_probabilities(frame, "prob_win", label_column="win")

    rows = []
    for run in runs:
        settlement = run.settlement
        rows.append(
            PredictionLedgerRow(
                public_id=run.public_id,
                mode=run.publication_mode,
                mode_label="사전 공개" if run.publication_mode == "live" else "과거 검증",
                race_date=run.race_date_local.isoformat(),
                published_at=_format_ms(run.published_at_ms),
                race_count=len({item.race_id for item in run.predictions}),
                entry_count=len(run.predictions),
                status="settled" if settlement else "published",
                status_label="정산 완료" if settlement else "예측 고정",
                win_log_loss=(f"{settlement.win_log_loss:.4f}" if settlement else "—"),
                top1=(f"{settlement.win_top1_hit_rate:.1%}" if settlement else "—"),
                hash_short=run.predictions_sha256[:12],
            )
        )
    return PredictionLedgerPage(
        live_publications=len(live_runs),
        live_settlements=sum(run.settlement is not None for run in live_runs),
        live_races=sum(len({item.race_id for item in run.predictions}) for run in live_runs),
        historical_publications=sum(run.publication_mode == "historical" for run in runs),
        aggregate_win_log_loss=(
            f"{aggregate_metrics['log_loss']:.4f}" if aggregate_metrics else "—"
        ),
        aggregate_ece=f"{aggregate_metrics['ece']:.4f}" if aggregate_metrics else "—",
        aggregate_top1=(
            f"{aggregate_metrics['top1_hit_rate']:.1%}" if aggregate_metrics else "—"
        ),
        aggregate_scored_races=(
            int(aggregate_metrics["n_races"]) if aggregate_metrics else 0
        ),
        rows=rows,
    )
