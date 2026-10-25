"""Finish reports from the six already-fitted models without fitting again."""
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd

import prepare as e
import run as pipeline

OUT = e.OUT


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_new(path, payload):
    assert not path.exists(), f'refusing to overwrite existing result: {path}'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def ensure_new_frame(path, frame, parquet=False):
    assert not path.exists(), f'refusing to overwrite existing result: {path}'
    if parquet:
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def normalize_runner_context():
    path = OUT / 'runner_predictions.parquet'
    frame = pd.read_parquet(path)
    assert {'observed_starts_x', 'observed_starts_y', 'same_starts'}.issubset(frame.columns)
    assert frame.observed_starts_x.astype(float).equals(frame.observed_starts_y.astype(float))
    stage = OUT / 'runner_predictions_fit_stage.parquet'
    if not stage.exists():
        stage.write_bytes(path.read_bytes())
    else:
        assert sha(stage) == sha(path), 'saved fit-stage copy differs from original intermediate output'
    frame = frame.drop(columns=['observed_starts_y']).rename(columns={'observed_starts_x': 'observed_starts'})
    temp = OUT / 'runner_predictions_canonical.parquet'
    ensure_new_frame(temp, frame, parquet=True)
    path.write_bytes(temp.read_bytes())
    return frame, stage


def model_replay_checks(features, runners, race_metrics, tickets):
    checks = []
    for year in [2024, 2025, 2026]:
        for variant in ['F1', 'F2']:
            folder = OUT / f'{variant}_{year}'
            meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            model_path = folder / 'top3.txt'
            assert meta['variant'] == variant and meta['evaluation_year'] == year
            assert e.sha(model_path) == meta['model_sha256']
            assert meta['lightgbm_train_calls'] == 2 and meta['temperature_optimizations'] == 1
            model = lgb.Booster(model_file=str(model_path))
            columns = e.CONTRACTS[variant]
            test = features.loc[features.year.eq(year)].reset_index(drop=True)
            cal = features.loc[features.year.eq(year - 1)].reset_index(drop=True)
            x_test = pipeline.transform(test, columns, meta['vocabulary'])
            x_cal = pipeline.transform(cal, columns, meta['vocabulary'])
            scores = model.predict(x_test, raw_score=True, num_threads=4)
            cal_scores = model.predict(x_cal, raw_score=True, num_threads=4)
            saved = runners.loc[runners.variant.eq(variant) & runners.year.eq(year)]
            pipeline.compare_frame(saved, pd.DataFrame({
                'api_record_id': test.api_record_id.to_numpy(), 'score': scores,
            }), ['api_record_id'], ['score'])
            saved_cal = pd.read_parquet(folder / 'calibration_scores.parquet')
            pipeline.compare_frame(saved_cal, pd.DataFrame({
                'api_record_id': cal.api_record_id.to_numpy(), 'score': cal_scores,
            }), ['api_record_id'], ['score'])
            tau = e.base.temperature(cal, cal_scores)
            assert abs(tau - float(meta['tau'])) <= 1e-10
            regenerated_races, regenerated_runners, regenerated_tickets = e.base.evaluate(
                test, scores, tau, variant)
            pipeline.compare_frame(saved, regenerated_runners,
                ['api_record_id'], ['score', 'p_top3', 'log_loss', 'brier'])
            saved_races = race_metrics.loc[race_metrics.variant.eq(variant) & race_metrics.year.eq(year)]
            pipeline.compare_frame(saved_races, regenerated_races,
                ['race_id'], e.base.METRICS)
            saved_tickets = tickets.loc[tickets.variant.eq(variant) & tickets.race_id.isin(regenerated_tickets.race_id)]
            saved_tickets = saved_tickets.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
            regenerated_tickets = regenerated_tickets.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
            assert saved_tickets[['race_id', 'selection_rank', 'numbers', 'hit']].astype(str).equals(
                regenerated_tickets[['race_id', 'selection_rank', 'numbers', 'hit']].astype(str))
            assert np.allclose(saved_tickets.probability.to_numpy(float),
                               regenerated_tickets.probability.to_numpy(float), rtol=0, atol=1e-12)
            checks.append(dict(variant=variant, year=year, model_sha256=meta['model_sha256'],
                test_score_rows=len(saved), calibration_rows=len(saved_cal),
                calibration_temperature_reproduced=True, predictions_and_metrics_reproduced=True))
    return checks


def main():
    lock = pipeline.output_lock()
    pipeline.verify_refs_and_protection(lock)
    gate = json.loads((OUT / 'r1_pretraining_gate.json').read_text(encoding='utf-8'))
    assert gate['passed']
    features = pd.read_parquet(OUT / 'features.parquet')
    runners, stage = normalize_runner_context()
    races = pd.read_csv(OUT / 'race_metrics.csv')
    tickets = pd.read_csv(OUT / 'six_combinations.csv')
    assert set(runners.variant) == {'R1', 'F1', 'F2'}
    assert len(runners) == 3 * 17412 and races.groupby('variant').size().eq(1779).all()
    reload_checks = model_replay_checks(features, runners, races, tickets)
    assert len(reload_checks) == 6

    race_group, race_diff, runner_group, runner_diff = pipeline.group_metric_tables(races, runners)
    ensure_new_frame(OUT / 'metrics_by_group.csv', race_group)
    ensure_new_frame(OUT / 'paired_differences.csv', race_diff)
    ensure_new_frame(OUT / 'runner_metrics_by_group.csv', runner_group)
    ensure_new_frame(OUT / 'runner_paired_differences.csv', runner_diff)
    ensure_new_frame(OUT / 'calibration_bins.csv', pipeline.calibration_bins(runners))
    op_races, op_runners, op_tickets, op_summary, op_diff = pipeline.operating_common_comparison(
        runners, races, tickets)
    ensure_new_frame(OUT / 'operating_common_467_race_metrics.csv', op_races)
    ensure_new_frame(OUT / 'operating_common_467_runner_predictions.parquet', op_runners, parquet=True)
    ensure_new_frame(OUT / 'operating_common_467_six_combinations.csv', op_tickets)
    ensure_new_frame(OUT / 'operating_common_467_summary.csv', op_summary)
    ensure_new_frame(OUT / 'operating_common_467_paired_differences.csv', op_diff)
    pipeline.verify_refs_and_protection(lock)

    completion = dict(
        passed=True,
        final_candidate_models=len(reload_checks),
        lightgbm_train_calls=sum(int(json.loads((OUT / f'{variant}_{year}/meta.json').read_text(
            encoding='utf-8'))['lightgbm_train_calls']) for variant in ['F1', 'F2'] for year in [2024, 2025, 2026]),
        temperature_optimizations=sum(int(json.loads((OUT / f'{variant}_{year}/meta.json').read_text(
            encoding='utf-8'))['temperature_optimizations']) for variant in ['F1', 'F2'] for year in [2024, 2025, 2026]),
        variants=['R1', 'F1', 'F2'], evaluation_rows_per_variant=17412,
        races_per_variant=1779, bootstrap_repetitions=pipeline.BOOTSTRAP_REPS,
        bootstrap_seed=pipeline.BOOTSTRAP_SEED, operating_common_races=467,
        operating_common_runner_rows_per_variant=4475,
        r1_reloaded_without_refit=True,
        candidate_model_reloads=reload_checks,
        fit_stage_runner_predictions_preserved_as=stage.name,
        context_columns_normalized_after_fit=True,
        reference_hashes_unchanged=len(lock['references']),
        protected_hashes_unchanged=len(lock['protected']),
        production_changed=False, database_changed=False,
        completion_script_sha256=sha(Path(__file__)),
    )
    completion['outputs'] = {
        path.name: sha(path) for path in OUT.iterdir()
        if path.is_file() and path.name != 'training_completion.json'
    }
    save_new(OUT / 'training_completion.json', completion)
    print(op_summary.to_string(index=False), flush=True)
    print(json.dumps({k: v for k, v in completion.items() if k != 'outputs'},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
