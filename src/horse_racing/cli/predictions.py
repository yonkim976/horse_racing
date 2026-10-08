"""Prediction publication, settlement, and verification commands."""

import json
import sys
import time
from pathlib import Path

from horse_racing.cli._common import _format_cell, _print_aligned_table, parse_timestamp_ms
from horse_racing.db.session import SessionLocal


def publish_predictions_command(
    run_id: str,
    predictions_file: str,
    feature_cutoff: str,
    *,
    publication_mode: str = "live",
    confirm_historical: bool = False,
    notes: str | None = None,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import get_run
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        PredictionModelMetadata,
        publish_predictions,
        sha256_file,
    )

    if publication_mode == "historical" and not confirm_historical:
        print(
            "historical 발행에는 --confirm-historical이 필요합니다. 공개 실적과 분리됩니다.",
            file=sys.stderr,
        )
        return 2
    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_raw = run.hyperparameters.get("artifact_path")
    if not artifact_raw:
        print("model run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_path = Path(str(artifact_raw))
    if not artifact_path.exists():
        print(f"model artifact 없음: {artifact_path}", file=sys.stderr)
        return 1
    prediction_path = Path(predictions_file)
    if not prediction_path.exists():
        print(f"prediction 파일 없음: {prediction_path}", file=sys.stderr)
        return 1
    if prediction_path.suffix.lower() == ".parquet":
        predictions = pl.read_parquet(prediction_path)
    elif prediction_path.suffix.lower() in {".csv", ".tsv"}:
        predictions = pl.read_csv(
            prediction_path,
            separator="\t" if prediction_path.suffix.lower() == ".tsv" else ",",
        )
    else:
        print("prediction 파일은 parquet/csv/tsv만 지원합니다.", file=sys.stderr)
        return 2
    try:
        cutoff_at_ms = parse_timestamp_ms(feature_cutoff)
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            summary = publish_predictions(
                session,
                predictions,
                metadata=PredictionModelMetadata(
                    experiment_run_id=run.run_id,
                    model_type=run.model_type,
                    dataset_version=version,
                    as_of_policy=as_of_policy,
                    feature_hash=run.feature_hash,
                    model_artifact_sha256=sha256_file(artifact_path),
                ),
                feature_cutoff_at_ms=cutoff_at_ms,
                publication_mode=publication_mode,
                notes=notes,
            )
    except (PredictionLedgerError, ValueError) as exc:
        print(f"예측 발행 실패: {exc}", file=sys.stderr)
        return 1
    print(f"예측 원장 발행 완료: public_id={summary.public_id}")
    print(
        f"mode={summary.publication_mode}, date={summary.race_date_local}, "
        f"races={summary.race_count}, entries={summary.entry_count}"
    )
    print(f"predictions_sha256={summary.predictions_sha256}")
    return 0


def build_prediction_frame_command(
    run_id: str,
    race_date: str,
    *,
    publication_mode: str = "live",
    race_ids: list[int] | None = None,
    output_dir: str = "data/predictions",
) -> int:
    """Build and persist the exact label-free frame expected by one fixed run."""
    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.prediction_frame import (
        PredictionFrameError,
        build_prediction_frame,
        validate_prediction_timing,
    )

    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    try:
        _, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            result = build_prediction_frame(
                session,
                race_date=race_date,
                as_of_policy=as_of_policy,
                expected_feature_names=run.feature_names,
                publication_mode=publication_mode,
                race_ids=race_ids,
                expected_meet_codes=run.dataset_manifest.get("meet_codes"),
            )
        cutoff_at_ms = time.time_ns() // 1_000_000
        if publication_mode == "live":
            validate_prediction_timing(result.frame, at_ms=cutoff_at_ms)
    except (PredictionFrameError, ValueError) as exc:
        print(f"prediction frame 생성 실패: {exc}", file=sys.stderr)
        return 1

    target_dir = Path(output_dir) / result.race_date_local.replace("-", "")
    target_dir.mkdir(parents=True, exist_ok=True)
    frame_path = target_dir / f"features_{run_id}_{cutoff_at_ms}.parquet"
    manifest_path = target_dir / f"features_{run_id}_{cutoff_at_ms}.json"
    result.frame.write_parquet(frame_path)
    manifest_path.write_text(
        json.dumps(
            {
                "experiment_run_id": run_id,
                "race_date_local": result.race_date_local,
                "publication_mode": publication_mode,
                "as_of_policy": result.as_of_policy,
                "feature_cutoff_at_ms": cutoff_at_ms,
                "feature_names": result.feature_names,
                "feature_hash": result.feature_hash,
                "race_count": result.frame.select("race_id").n_unique(),
                "entry_count": result.frame.height,
                "excluded_small_field_race_ids": result.excluded_small_field_race_ids,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"prediction frame 생성 완료: {frame_path}")
    print(
        f"date={result.race_date_local}, races={result.frame.select('race_id').n_unique()}, "
        f"entries={result.frame.height}, features={len(result.feature_names)}"
    )
    print(f"feature_hash={result.feature_hash}")
    if result.excluded_small_field_race_ids:
        print(f"최소 두수 미달 제외 race_id={result.excluded_small_field_race_ids}")
    print(f"manifest: {manifest_path}")
    return 0


def predict_and_publish_command(
    run_id: str,
    race_date: str,
    *,
    publication_mode: str = "live",
    confirm_historical: bool = False,
    race_ids: list[int] | None = None,
    output_dir: str = "data/predictions",
    notes: str | None = None,
    probability_calibration_path: str | None = None,
) -> int:
    """Build features, run a fixed artifact, and atomically publish probabilities."""
    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.prediction_frame import (
        PROBABILITY_COHERENCE_METHOD,
        PredictionFrameError,
        build_prediction_frame,
        predict_model_run,
        validate_prediction_timing,
    )
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        PredictionModelMetadata,
        publish_predictions,
        sha256_file,
    )

    if publication_mode == "historical" and not confirm_historical:
        print(
            "historical 발행에는 --confirm-historical이 필요합니다. 공개 실적과 분리됩니다.",
            file=sys.stderr,
        )
        return 2
    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    try:
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            built = build_prediction_frame(
                session,
                race_date=race_date,
                as_of_policy=as_of_policy,
                expected_feature_names=run.feature_names,
                publication_mode=publication_mode,
                race_ids=race_ids,
                expected_meet_codes=run.dataset_manifest.get("meet_codes"),
            )
            calibration_path = (
                Path(probability_calibration_path)
                if probability_calibration_path is not None
                else None
            )
            predictions, artifact_path = predict_model_run(
                run,
                built.frame,
                probability_calibration_path=calibration_path,
            )
            cutoff_at_ms = time.time_ns() // 1_000_000
            if publication_mode == "live":
                validate_prediction_timing(built.frame, at_ms=cutoff_at_ms)

            target_dir = (
                Path(output_dir)
                / built.race_date_local.replace("-", "")
                / f"{cutoff_at_ms}_{run_id[:8]}"
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            frame_path = target_dir / "features.parquet"
            predictions_path = target_dir / "predictions.parquet"
            built.frame.write_parquet(frame_path)
            predictions.write_parquet(predictions_path)
            audit_note = f"inference_artifacts={target_dir}"
            if calibration_path is not None:
                audit_note += f"; probability_calibration={calibration_path}"
            publication_notes = f"{notes}; {audit_note}" if notes else audit_note
            summary = publish_predictions(
                session,
                predictions,
                metadata=PredictionModelMetadata(
                    experiment_run_id=run.run_id,
                    model_type=run.model_type,
                    dataset_version=version,
                    as_of_policy=as_of_policy,
                    feature_hash=run.feature_hash,
                    model_artifact_sha256=sha256_file(artifact_path),
                ),
                feature_cutoff_at_ms=cutoff_at_ms,
                publication_mode=publication_mode,
                notes=publication_notes,
            )
            manifest_path = target_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "public_id": summary.public_id,
                        "experiment_run_id": run_id,
                        "race_date_local": built.race_date_local,
                        "publication_mode": publication_mode,
                        "as_of_policy": as_of_policy,
                        "feature_cutoff_at_ms": cutoff_at_ms,
                        "feature_hash": built.feature_hash,
                        "probability_coherence": PROBABILITY_COHERENCE_METHOD,
                        "predictions_sha256": summary.predictions_sha256,
                        "race_count": summary.race_count,
                        "entry_count": summary.entry_count,
                        "excluded_small_field_race_ids": built.excluded_small_field_race_ids,
                        "model_artifact": str(artifact_path),
                        "probability_calibration_artifact": (
                            str(calibration_path) if calibration_path is not None else None
                        ),
                        "probability_calibration_sha256": (
                            sha256_file(calibration_path) if calibration_path is not None else None
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    except (PredictionFrameError, PredictionLedgerError, ValueError) as exc:
        print(f"예측·발행 실패: {exc}", file=sys.stderr)
        return 1

    print(f"고정 모델 예측·원장 발행 완료: public_id={summary.public_id}")
    print(
        f"mode={summary.publication_mode}, date={summary.race_date_local}, "
        f"races={summary.race_count}, entries={summary.entry_count}"
    )
    print(f"predictions_sha256={summary.predictions_sha256}")
    print(f"audit artifacts: {target_dir}")
    return 0


def settle_predictions_command(public_id: str | None = None) -> int:
    from sqlalchemy import select

    from horse_racing.db.models import PredictionRun, PredictionSettlement
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        settle_prediction_run,
    )

    with SessionLocal() as session:
        if public_id is not None:
            targets = [public_id]
        else:
            targets = list(
                session.scalars(
                    select(PredictionRun.public_id)
                    .outerjoin(
                        PredictionSettlement,
                        PredictionSettlement.prediction_run_id == PredictionRun.id,
                    )
                    .where(PredictionSettlement.id.is_(None))
                    .order_by(PredictionRun.published_at_ms)
                )
            )
        if not targets:
            print("미정산 prediction이 없습니다.")
            return 0
        settled = 0
        pending = 0
        for target in targets:
            try:
                summary = settle_prediction_run(session, target)
            except PredictionLedgerError as exc:
                if public_id is not None:
                    print(f"예측 정산 실패: {exc}", file=sys.stderr)
                    return 1
                pending += 1
                continue
            settled += 1
            print(
                f"정산 완료: prediction={target}, settlement={summary.public_id}, "
                f"races={summary.race_count}, excluded={summary.excluded_races}, "
                f"win_LL={summary.win_log_loss:.6f}"
            )
        print(f"정산 요약: completed={settled}, pending={pending}")
        return 0


def list_predictions_command(publication_mode: str = "all") -> int:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from horse_racing.db.models import PredictionRun

    with SessionLocal() as session:
        statement = select(PredictionRun).options(
            selectinload(PredictionRun.predictions),
            selectinload(PredictionRun.settlement),
        )
        if publication_mode != "all":
            statement = statement.where(PredictionRun.publication_mode == publication_mode)
        runs = session.scalars(statement.order_by(PredictionRun.published_at_ms.desc())).all()
    if not runs:
        print("발행된 prediction이 없습니다.")
        return 0
    headers = ["public_id", "mode", "race_date", "races", "entries", "status", "win_LL"]
    rows: list[list[str]] = []
    for run in runs:
        settlement = run.settlement
        rows.append(
            [
                run.public_id,
                run.publication_mode,
                run.race_date_local.isoformat(),
                str(len({item.race_id for item in run.predictions})),
                str(len(run.predictions)),
                "settled" if settlement else "published",
                _format_cell(settlement.win_log_loss if settlement else None),
            ]
        )
    _print_aligned_table(headers, rows)
    return 0


def verify_predictions_command(public_id: str) -> int:
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        verify_prediction_hash,
    )

    with SessionLocal() as session:
        try:
            verified = verify_prediction_hash(session, public_id)
        except PredictionLedgerError as exc:
            print(f"검증 실패: {exc}", file=sys.stderr)
            return 1
    print(f"prediction hash: {'VERIFIED' if verified else 'MISMATCH'}")
    return 0 if verified else 1
