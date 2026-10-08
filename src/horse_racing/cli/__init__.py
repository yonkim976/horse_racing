"""horse-racing command line entry point.

Command functions are bound here so ``main`` dispatches through this module's
namespace (tests replace them with ``monkeypatch.setattr(cli, ...)``).
"""

import sys

from horse_racing.cli.collection import (
    backfill_dividends,
    backfill_equipment,
    backfill_gate_numbers,
    backfill_jockey_changes,
    backfill_medical,
    backfill_race_passing,
    backfill_race_passing_years,
    backfill_results,
    backfill_scratches,
    backfill_sections,
    backfill_start_training,
    backfill_steward_reports,
    backfill_training,
    backfill_weights,
    collect_entry_sheet,
    collect_equipment,
    collect_gate_numbers,
    collect_grade_changes,
    collect_horse_profiles,
    collect_jockey_changes,
    collect_medical,
    collect_race_day,
    collect_race_passing,
    collect_race_sections,
    collect_ratings,
    collect_running_trials,
    collect_schedule,
    collect_scratches,
    collect_start_training,
    collect_steward_reports,
    collect_training,
    collect_weights,
    db_info,
    download_text_archive_command,
    ingest_text_results_command,
    repair_entry_links,
    repair_planned_weather_command,
    serve_dashboard,
    sync_daily,
    sync_latest,
)
from horse_racing.cli.modeling import (
    build_dataset_command,
    build_ensemble_command,
    compare_model_runs,
    evaluate_model_command,
    list_model_runs,
    run_ablation_command,
    run_baselines_command,
    run_g1_gate_command,
    run_g2_gate_command,
    run_ordered_triple_value_command,
    run_walk_forward_command,
    train_catboost_command,
    train_model_command,
    train_racefit_command,
    train_ranking_command,
    write_feature_catalog_command,
)
from horse_racing.cli.parser import build_parser
from horse_racing.cli.predictions import (
    build_prediction_frame_command,
    list_predictions_command,
    predict_and_publish_command,
    publish_predictions_command,
    settle_predictions_command,
    verify_predictions_command,
)
from horse_racing.collectors.kra_api import KraApiError
from horse_racing.collectors.kra_text import KraTextError


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "db-info":
        return db_info()
    if args.command == "collect-entry-sheet":
        try:
            return collect_entry_sheet(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-day":
        try:
            return collect_race_day(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-schedule":
        try:
            return collect_schedule(args.dates, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"일정 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-gate-numbers":
        try:
            return collect_gate_numbers(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발번호 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-gates":
        try:
            return backfill_gate_numbers(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발번호 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-results":
        try:
            return backfill_results(
                args.start,
                args.end,
                args.meets,
                args.page_size,
                not args.skip_dividends,
            )
        except (KraApiError, ValueError) as exc:
            print(f"백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-dividends":
        try:
            return backfill_dividends(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"확정배당 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-sections":
        try:
            return collect_race_sections(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"구간기록 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-sections":
        try:
            return backfill_sections(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"구간기록 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-passing":
        try:
            return collect_race_passing(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"공식 통과대열 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-race-passing":
        try:
            return backfill_race_passing(
                args.start, args.end, args.meets, args.page_size
            )
        except (KraApiError, ValueError) as exc:
            print(f"공식 통과대열 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-race-passing-years":
        try:
            return backfill_race_passing_years(
                args.start_year, args.end_year, args.meets, args.page_size
            )
        except (KraApiError, ValueError) as exc:
            print(f"공식 통과대열 연도 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-ratings":
        try:
            return collect_ratings(args.date, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"레이팅 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-weights":
        try:
            return collect_weights(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"체중 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-training":
        try:
            return collect_training(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"훈련 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-medical":
        try:
            return collect_medical(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"진료 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-horse-profiles":
        try:
            return collect_horse_profiles(
                args.meets,
                args.page_size,
                args.include_inactive,
                args.date,
            )
        except (KraApiError, ValueError) as exc:
            print(f"말 상세 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-weights":
        try:
            return backfill_weights(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"체중 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-training":
        try:
            return backfill_training(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"훈련 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-medical":
        try:
            return backfill_medical(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"진료 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-jockey-changes":
        try:
            return collect_jockey_changes(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"기수변경 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-scratches":
        try:
            return collect_scratches(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출전취소 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-equipment":
        try:
            return collect_equipment(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"장구·폐출혈 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-grade-changes":
        try:
            return collect_grade_changes(args.meets, args.page_size, args.date)
        except (KraApiError, ValueError) as exc:
            print(f"등급변동 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-start-training":
        try:
            return collect_start_training(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발훈련 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-steward-reports":
        try:
            return collect_steward_reports(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"심판리포트 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-jockey-changes":
        try:
            return backfill_jockey_changes(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"기수변경 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-scratches":
        try:
            return backfill_scratches(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출전취소 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-equipment":
        try:
            return backfill_equipment(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"장구·폐출혈 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-start-training":
        try:
            return backfill_start_training(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발훈련 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-steward-reports":
        try:
            return backfill_steward_reports(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"심판리포트 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-running-trials":
        try:
            return collect_running_trials(args.start, args.end, args.meets)
        except (KraTextError, ValueError) as exc:
            print(f"주행심사 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "download-text-archive":
        try:
            return download_text_archive_command(
                args.file_type,
                args.code_name,
                args.start,
                args.end,
                args.meets,
                args.max_pages,
                args.max_files,
                args.delay_ms,
            )
        except (KraTextError, ValueError) as exc:
            print(f"Text 자료실 다운로드 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "ingest-text-results":
        try:
            return ingest_text_results_command(
                args.start,
                args.end,
                args.meets,
                validate_only=args.validate_only,
                allow_synthetic_horses=args.allow_synthetic_horses,
            )
        except (KraTextError, ValueError) as exc:
            print(f"dacom11 적재 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "serve-dashboard":
        return serve_dashboard(args.host, args.port, args.reload)
    if args.command == "repair-entry-links":
        return repair_entry_links()
    if args.command == "repair-planned-weather":
        return repair_planned_weather_command()
    if args.command == "sync-daily":
        try:
            return sync_daily(
                args.mode,
                as_of=args.as_of,
                meets=args.meets,
                schedule_days=args.schedule_days,
                result_lookback_days=args.result_lookback_days,
                page_size=args.page_size,
                include_dividends=not args.skip_dividends,
                dry_run=args.dry_run,
            )
        except (KraApiError, ValueError) as exc:
            print(f"일일 동기화 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "sync-latest":
        return sync_latest(
            as_of=args.as_of,
            meets=args.meets,
            schedule_days=args.schedule_days,
            recent_lookback_days=args.recent_lookback_days,
            history_lookback_days=args.history_lookback_days,
            trial_lookback_days=args.trial_lookback_days,
            page_size=args.page_size,
            include_dividends=not args.skip_dividends,
            dry_run=args.dry_run,
        )
    if args.command == "build-dataset":
        return build_dataset_command(
            args.version,
            args.as_of,
            args.start,
            args.end,
            args.output_dir,
            with_features=not args.no_features,
            feature_set=args.feature_set,
            meet_codes=args.meets,
        )
    if args.command == "write-feature-catalog":
        return write_feature_catalog_command(args.output)
    if args.command == "run-baselines":
        return run_baselines_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            include_test=args.include_test,
        )
    if args.command == "train-model":
        return train_model_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
        )
    if args.command == "run-walk-forward":
        return run_walk_forward_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            years=args.years,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
            model_kind=args.model,
            relevance_mode=args.relevance_mode,
            margin_performance=args.margin_performance,
        )
    if args.command == "train-ranking":
        return train_ranking_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
            calibration_objective=args.calibration_objective,
            relevance_depth=args.relevance_depth,
            relevance_mode=args.relevance_mode,
            margin_performance=args.margin_performance,
            regularization=args.regularization,
        )
    if args.command == "train-racefit":
        return train_racefit_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
        )
    if args.command == "train-catboost":
        return train_catboost_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
        )
    if args.command == "run-ablation":
        return run_ablation_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
        )
    if args.command == "build-ensemble":
        configured_weights = {
            label: values
            for label, values in {
                "win": args.win_weights,
                "top2": args.top2_weights,
                "top3": args.top3_weights,
                "top4": args.top4_weights,
                "top5": args.top5_weights,
            }.items()
            if values is not None
        }
        return build_ensemble_command(
            args.run_ids,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            allow_cross_dataset=args.allow_cross_dataset,
            target_member_weights=configured_weights or None,
            reference_version=args.reference_version,
            reference_as_of=args.reference_as_of,
        )
    if args.command == "run-g1-gate":
        return run_g1_gate_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            confirm_test=args.confirm_test,
        )
    if args.command == "run-g2-gate":
        return run_g2_gate_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            confirm_test_market=args.confirm_test_market,
            bootstrap_iterations=args.bootstrap_iterations,
        )
    if args.command == "run-ordered-triple-value":
        return run_ordered_triple_value_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            top_n=args.top_n,
            ev_thresholds=args.ev_thresholds,
            bootstrap_iterations=args.bootstrap_iterations,
        )
    if args.command == "publish-predictions":
        return publish_predictions_command(
            args.run_id,
            args.predictions_file,
            args.feature_cutoff,
            publication_mode=args.mode,
            confirm_historical=args.confirm_historical,
            notes=args.notes,
        )
    if args.command == "build-prediction-frame":
        return build_prediction_frame_command(
            args.run_id,
            args.date,
            publication_mode=args.mode,
            race_ids=args.race_ids,
            output_dir=args.output_dir,
        )
    if args.command == "predict-and-publish":
        return predict_and_publish_command(
            args.run_id,
            args.date,
            publication_mode=args.mode,
            confirm_historical=args.confirm_historical,
            race_ids=args.race_ids,
            output_dir=args.output_dir,
            notes=args.notes,
            probability_calibration_path=args.probability_calibration,
        )
    if args.command == "settle-predictions":
        return settle_predictions_command(args.public_id)
    if args.command == "list-predictions":
        return list_predictions_command(args.mode)
    if args.command == "verify-predictions":
        return verify_predictions_command(args.public_id)
    if args.command == "evaluate-model":
        return evaluate_model_command(
            args.run_id,
            args.dataset_dir,
            include_test=args.include_test,
            report_dir=args.report_dir,
        )
    if args.command == "list-model-runs":
        return list_model_runs(args.metric)
    if args.command == "compare-runs":
        return compare_model_runs(args.run_ids)
    parser.error(f"unknown command: {args.command}")
    return 2
