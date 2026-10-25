"""Reload frozen R1 outputs and, after the approved gate, fit only F1 and F2."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

import prepare as e

HERE = e.HERE
OUT = e.OUT
R1_OUT = e.R1_OUT
OLD = e.base
YEARS = [2024, 2025, 2026]
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = e.SEED
MODEL_CATS = OLD.CATS + ['previous_result_status']
RACE_METRICS = OLD.METRICS
RUNNER_METRICS = ['log_loss', 'brier']


def ensure_absent(path):
    assert not path.exists(), f'refusing to overwrite existing result: {path}'


def write_frame_new(path, frame, parquet=False):
    ensure_absent(path)
    if parquet:
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def output_lock():
    return json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))


def verify_refs_and_protection(lock):
    for relative, expected in lock['references'].items():
        assert e.sha(e.ROOT / relative) == expected, f'reference changed: {relative}'
    for relative, info in lock['protected'].items():
        path = e.ROOT / relative
        assert e.sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], relative


def verify_pretraining_gate():
    pre = json.loads((OUT / 'preflight_verification.json').read_text(encoding='utf-8'))
    r1 = json.loads((OUT / 'r1_pretraining_gate.json').read_text(encoding='utf-8'))
    assert pre['passed'] and r1['passed']
    verify_refs_and_protection(output_lock())


def transform(data, columns, vocabulary):
    x = data[columns].copy()
    for column in MODEL_CATS:
        if column in columns:
            x[column] = pd.Categorical(x[column], categories=vocabulary[column])
    return x


def compare_frame(saved, actual, key_columns, numeric_columns, atol=1e-12):
    left = saved.sort_values(key_columns, kind='stable').reset_index(drop=True)
    right = actual.sort_values(key_columns, kind='stable').reset_index(drop=True)
    for key in key_columns:
        assert left[key].astype(str).equals(right[key].astype(str)), key
    for column in numeric_columns:
        assert np.allclose(left[column].to_numpy(float), right[column].to_numpy(float),
                           rtol=0, atol=atol, equal_nan=True), column


def replay_r1():
    """Apply existing R1 models; do not fit or refit R1."""
    lock = output_lock()
    verify_refs_and_protection(lock)
    pre = json.loads((OUT / 'preflight_verification.json').read_text(encoding='utf-8'))
    assert pre['passed']
    features = pd.read_parquet(OUT / 'features.parquet')
    frozen = pd.read_parquet(R1_OUT / 'runner_predictions.parquet')
    frozen = frozen.loc[frozen.variant.eq('R1')].copy()
    frozen_races = pd.read_csv(R1_OUT / 'race_metrics.csv')
    frozen_races = frozen_races.loc[frozen_races.variant.eq('R1')].copy()
    frozen_tickets = pd.read_csv(R1_OUT / 'six_combinations.csv')
    frozen_tickets = frozen_tickets.loc[frozen_tickets.variant.eq('R1')].copy()
    runners, races, tickets, model_hashes = [], [], [], {}
    for year in YEARS:
        folder = R1_OUT / f'R1_{year}'
        meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
        model_path = folder / 'top3.txt'
        assert e.sha(model_path) == meta['model_sha256']
        assert meta['features'] == e.CONTRACTS['R1']
        assert set(meta['vocabulary']) == set(OLD.CATS)
        model = lgb.Booster(model_file=str(model_path))
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        x = transform(test, e.CONTRACTS['R1'], meta['vocabulary'])
        scores = model.predict(x, raw_score=True, num_threads=4)
        race_result, runner_result, ticket_result = OLD.evaluate(test, scores, float(meta['tau']), 'R1')
        old_runner = frozen.loc[frozen.year.eq(year)].copy()
        compare_frame(old_runner, runner_result,
                      ['api_record_id'], ['score', 'p_top3', 'log_loss', 'brier'])
        old_race = frozen_races.loc[frozen_races.year.eq(year)].copy()
        compare_frame(old_race, race_result,
                      ['race_id'], RACE_METRICS)
        old_ticket = frozen_tickets.loc[frozen_tickets.race_id.isin(ticket_result.race_id)].copy()
        old_ticket = old_ticket.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
        new_ticket = ticket_result.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
        assert old_ticket[['race_id', 'selection_rank', 'numbers', 'hit']].astype(str).equals(
            new_ticket[['race_id', 'selection_rank', 'numbers', 'hit']].astype(str))
        assert np.allclose(old_ticket.probability.to_numpy(float), new_ticket.probability.to_numpy(float),
                           rtol=0, atol=1e-12)
        runners.append(runner_result)
        races.append(race_result)
        tickets.append(ticket_result)
        model_hashes[str(year)] = e.sha(model_path)
        print(f'R1 replay {year}: {len(runner_result)} runners, {len(race_result)} races', flush=True)

    replay_runner = pd.concat(runners, ignore_index=True)
    replay_races = pd.concat(races, ignore_index=True)
    replay_tickets = pd.concat(tickets, ignore_index=True)
    assert len(replay_runner) == 17412 and replay_races.race_id.nunique() == 1779
    write_frame_new(OUT / 'r1_reproduced_runner_predictions.parquet', replay_runner, parquet=True)
    write_frame_new(OUT / 'r1_reproduced_race_metrics.csv', replay_races)
    write_frame_new(OUT / 'r1_reproduced_six_combinations.csv', replay_tickets)
    summary = dict(
        passed=True,
        reloaded_models=3,
        refit_models=0,
        runner_rows_reproduced=int(len(replay_runner)),
        distinct_races_reproduced=int(replay_races.race_id.nunique()),
        race_metrics_reproduced=int(len(replay_races)),
        six_combination_rows_reproduced=int(len(replay_tickets)),
        frozen_model_sha256=model_hashes,
        original_predictions_and_race_metrics_match=True,
        original_six_combinations_match=True,
        production_changed=False,
        database_changed=False,
    )
    e.save_json(OUT / 'r1_replay_verification.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def fit_candidate(features, variant, year):
    columns = e.CONTRACTS[variant]
    x = features[columns].copy()
    train = features.year.between(2017, year - 3)
    valid = features.year.eq(year - 2)
    calibration = features.year.eq(year - 1)
    test = features.year.eq(year)
    assert all(mask.any() for mask in [train, valid, calibration, test])
    vocabulary = {}
    for column in MODEL_CATS:
        if column in columns:
            vocabulary[column] = sorted(features.loc[train, column].dropna().astype(str).unique().tolist())
            x[column] = pd.Categorical(x[column].astype('string'), categories=vocabulary[column])
    target = features.finish_position.le(3).astype(int)
    weight = 1 / features.field_n

    def dataset(mask):
        return lgb.Dataset(x.loc[mask], label=target.loc[mask], weight=weight.loc[mask],
                           free_raw_data=False)

    initial = lgb.train(
        OLD.PARAMS, dataset(train), num_boost_round=200, valid_sets=[dataset(valid)],
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )
    model = lgb.train(OLD.PARAMS, dataset(train | valid), num_boost_round=initial.best_iteration)
    folder = OUT / f'{variant}_{year}'
    folder.mkdir(exist_ok=False)
    model_path = folder / 'top3.txt'
    model.save_model(str(model_path))
    calibration_data = features.loc[calibration].reset_index(drop=True)
    evaluation_data = features.loc[test].reset_index(drop=True)
    cal_scores = model.predict(x.loc[calibration], raw_score=True, num_threads=4)
    test_scores = model.predict(x.loc[test], raw_score=True, num_threads=4)
    tau = OLD.temperature(calibration_data, cal_scores)
    meta = dict(
        variant=variant, evaluation_year=year, features=columns, vocabulary=vocabulary,
        trees=int(initial.best_iteration), tau=float(tau), seed=OLD.SEED,
        parameters=OLD.PARAMS, lightgbm_train_calls=2, temperature_optimizations=1,
        training_min=str(features.loc[train, 'race_date'].min()),
        initial_training_max=str(features.loc[train, 'race_date'].max()),
        early_stopping_min=str(features.loc[valid, 'race_date'].min()),
        refit_max=str(features.loc[valid, 'race_date'].max()),
        calibration_min=str(features.loc[calibration, 'race_date'].min()),
        calibration_max=str(features.loc[calibration, 'race_date'].max()),
        evaluation_min=str(features.loc[test, 'race_date'].min()),
        evaluation_max=str(features.loc[test, 'race_date'].max()),
        train_races=int(features.loc[train | valid, 'race_id'].nunique()),
        calibration_races=int(features.loc[calibration, 'race_id'].nunique()),
        evaluation_races=int(features.loc[test, 'race_id'].nunique()),
        evaluation_rows=int(test.sum()), model_sha256=e.sha(model_path),
        gain=dict(zip(columns, map(float, model.feature_importance(importance_type='gain')))),
    )
    e.save_json(folder / 'meta.json', meta)
    write_frame_new(folder / 'calibration_scores.parquet', pd.DataFrame({
        'api_record_id': calibration_data.api_record_id.to_numpy(), 'score': cal_scores,
    }), parquet=True)
    race_result, runner_result, ticket_result = OLD.evaluate(evaluation_data, test_scores, tau, variant)
    print(f'{variant} {year}: trees={initial.best_iteration}, tau={tau:.6f}', flush=True)
    return race_result, runner_result, ticket_result


def bootstrap_race(a, b, metric):
    left = a[['race_id', 'race_date', metric]].rename(columns={metric: 'left'})
    right = b[['race_id', metric]].rename(columns={metric: 'right'})
    pair = left.merge(right, on='race_id', how='inner', validate='one_to_one')
    assert len(pair) == len(a) == len(b)
    pair['delta'] = pair.left - pair.right
    daily = pair.groupby('race_date').delta.agg(['sum', 'size'])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
    values = (daily['sum'].to_numpy()[indices].sum(axis=1)
              / daily['size'].to_numpy()[indices].sum(axis=1))
    return dict(delta=float(pair.delta.mean()), lo=float(np.quantile(values, .025)),
                hi=float(np.quantile(values, .975)), races=len(pair), days=len(daily),
                resamples=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED)


def bootstrap_runner(a, b, metric):
    left = a[['api_record_id', 'race_date', metric]].rename(columns={metric: 'left'})
    right = b[['api_record_id', metric]].rename(columns={metric: 'right'})
    pair = left.merge(right, on='api_record_id', how='inner', validate='one_to_one')
    assert len(pair) == len(a) == len(b)
    pair['delta'] = pair.left - pair.right
    daily = pair.groupby('race_date').delta.agg(['sum', 'size'])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
    values = (daily['sum'].to_numpy()[indices].sum(axis=1)
              / daily['size'].to_numpy()[indices].sum(axis=1))
    return dict(delta=float(pair.delta.mean()), lo=float(np.quantile(values, .025)),
                hi=float(np.quantile(values, .975)), rows=len(pair), days=len(daily),
                resamples=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED)


def add_prediction_context(predictions, features):
    context_columns = [
        'api_record_id', 'previous_result_status', 'previous_top3',
        'observed_starts', 'same_starts', 'same_distance_last5_actual_n',
        'same_distance_last5_normal_n', 'same_distance_last5_top3_rate',
    ]
    return predictions.merge(features[context_columns], on='api_record_id', how='left',
                             validate='many_to_one')


def group_metric_tables(races, runners):
    race_groups = [('all', 'all', races)]
    for year, group in races.groupby('year'):
        race_groups.append(('year', str(year), group))
    for distance, group in races.groupby('distance_m'):
        race_groups.append(('distance_m', str(int(distance)), group))
    race_rows, race_diffs = [], []
    for kind, value, group in race_groups:
        for variant, one in group.groupby('variant'):
            race_rows.append(dict(group=kind, value=value, variant=variant,
                                  races=len(one), days=one.race_date.nunique(),
                                  **{metric: float(one[metric].mean()) for metric in RACE_METRICS}))
        for left_variant, right_variant in [('F1', 'R1'), ('F2', 'F1'), ('F2', 'R1')]:
            left = group.loc[group.variant.eq(left_variant)]
            right = group.loc[group.variant.eq(right_variant)]
            for metric in RACE_METRICS:
                race_diffs.append(dict(group=kind, value=value,
                    comparison=f'{left_variant}-{right_variant}', metric=metric,
                    **bootstrap_race(left, right, metric)))

    runner_groups = [('all', 'all', runners)]
    for year, group in runners.groupby('year'):
        runner_groups.append(('year', str(year), group))
    for distance, group in runners.groupby('distance_m'):
        runner_groups.append(('distance_m', str(int(distance)), group))
    for column, labels in [
        ('observed_starts', ['0', '1_4', '5_plus']),
        ('same_starts', ['0', '1_4', '5_plus']),
    ]:
        bins = pd.cut(runners[column], [-1, 0, 4, np.inf], labels=labels)
        for label in labels:
            runner_groups.append((column, label, runners.loc[bins.astype('string').eq(label)]))
    for column in ['previous_result_status']:
        for label in ['normal', 'non_normal_or_incomplete', 'unobserved']:
            runner_groups.append((column, label, runners.loc[runners[column].eq(label)]))
    top3_state = runners.previous_top3.map({0.0: 'not_top3', 1.0: 'top3'}).fillna('unknown')
    for label in ['not_top3', 'top3', 'unknown']:
        runner_groups.append(('previous_top3', label, runners.loc[top3_state.eq(label)]))

    runner_rows, runner_diffs = [], []
    for kind, value, group in runner_groups:
        if group.empty:
            continue
        for variant, one in group.groupby('variant'):
            weights = 1 / one.field_n
            runner_rows.append(dict(
                group=kind, value=value, variant=variant,
                rows=len(one), races=one.race_id.nunique(), days=one.race_date.nunique(),
                log_loss=float(one.log_loss.mean()), brier=float(one.brier.mean()),
                weighted_log_loss=float(np.average(one.log_loss, weights=weights)),
                weighted_brier=float(np.average(one.brier, weights=weights)),
                predicted=float(np.average(one.p_top3, weights=weights)),
                actual=float(np.average(one.y, weights=weights)),
            ))
        for left_variant, right_variant in [('F1', 'R1'), ('F2', 'F1'), ('F2', 'R1')]:
            left = group.loc[group.variant.eq(left_variant)]
            right = group.loc[group.variant.eq(right_variant)]
            if left.empty or right.empty:
                continue
            for metric in RUNNER_METRICS:
                runner_diffs.append(dict(group=kind, value=value,
                    comparison=f'{left_variant}-{right_variant}', metric=metric,
                    **bootstrap_runner(left, right, metric)))
    return pd.DataFrame(race_rows), pd.DataFrame(race_diffs), pd.DataFrame(runner_rows), pd.DataFrame(runner_diffs)


def calibration_bins(runners):
    rows = []
    edges = np.linspace(0, 1, 11)
    for variant, group in runners.groupby('variant'):
        bins = pd.cut(group.p_top3, edges, include_lowest=True)
        for interval, one in group.groupby(bins, observed=True):
            weights = 1 / one.field_n
            rows.append(dict(variant=variant, probability_bin=str(interval), rows=len(one),
                races=one.race_id.nunique(), predicted=float(np.average(one.p_top3, weights=weights)),
                observed=float(np.average(one.y, weights=weights))))
    return pd.DataFrame(rows)


def operating_common_comparison(runners, races, tickets):
    op = HERE.parent / '20261009_operating_model_comparison_v1' / 'outputs'
    operating_runners = pd.read_parquet(op / 'runner_predictions.parquet')
    operating_races = pd.read_csv(op / 'race_metrics.csv')
    operating_tickets = pd.read_csv(op / 'six_combinations.csv')
    common_ids = set(operating_races.loc[operating_races.variant.eq('HY_R_FORM'), 'race_id'])
    assert len(common_ids) == 467
    candidate = runners.loc[runners.race_id.isin(common_ids) & runners.year.eq(2026)].copy()
    operating = operating_runners.loc[operating_runners.race_id.isin(common_ids)].copy()
    for variant in ['R1', 'F1', 'F2']:
        a = candidate.loc[candidate.variant.eq(variant)]
        b = operating.loc[operating.variant.eq('HY_R_FORM')]
        assert len(a) == len(b) == 4475
        aa = a.sort_values(['race_id', 'horse_id'], kind='stable').reset_index(drop=True)
        bb = b.sort_values(['race_id', 'horse_id'], kind='stable').reset_index(drop=True)
        assert aa[['race_id', 'horse_id', 'y']].astype(str).equals(bb[['race_id', 'horse_id', 'y']].astype(str))
    base = operating_runners.loc[operating_runners.variant.eq('HY_R_FORM')].copy()
    race_base = operating_races.loc[operating_races.variant.eq('HY_R_FORM')].copy()
    ticket_base = operating_tickets.loc[operating_tickets.variant.eq('HY_R_FORM')].copy()
    race_out, runner_out, ticket_out = [], [], []
    for variant in ['R1', 'F1', 'F2']:
        selected = candidate.loc[candidate.variant.eq(variant)].copy()
        for race_id, group in selected.groupby('race_id', sort=False):
            group = group.sort_values('horse_number', kind='stable')
            rank = np.argsort(-group.score.to_numpy(float), kind='stable')
            group_truth = set(np.flatnonzero(group.y.to_numpy(int)))
            combo = tickets.loc[tickets.variant.eq(variant) & tickets.race_id.eq(race_id)].sort_values('selection_rank')
            race_out.append(dict(
                race_id=race_id, race_date=str(group.race_date.iloc[0]),
                distance_m=int(group.distance_m.iloc[0]), field_n=len(group), variant=variant,
                brier=float(group.brier.mean()), log_loss=float(group.log_loss.mean()),
                pick_hit=int(group.y.iloc[rank[0]]),
                top3_all3=int(group_truth.issubset(set(rank[:3]))),
                top5_all3=int(group_truth.issubset(set(rank[:5]))),
                top5_capture=len(group_truth.intersection(set(rank[:5]))) / 3,
                six_combo_hit=int(combo.hit.max()),
            ))
        runner_out.extend(selected[['race_id', 'race_date', 'horse_id', 'horse_number',
            'variant', 'y', 'p_top3', 'brier', 'log_loss']].to_dict('records'))
        ticket_out.extend(tickets.loc[tickets.variant.eq(variant) & tickets.race_id.isin(common_ids)].to_dict('records'))
    result = pd.DataFrame(race_out)
    runner_frame = pd.DataFrame(runner_out)
    ticket_frame = pd.DataFrame(ticket_out)
    result = pd.concat([race_base, result], ignore_index=True)
    runner_frame = pd.concat([base, runner_frame], ignore_index=True)
    ticket_frame = pd.concat([ticket_base, ticket_frame], ignore_index=True)
    assert result.groupby('variant').race_id.nunique().eq(467).all()
    assert runner_frame.groupby('variant').size().eq(4475).all()
    summaries = []
    differences = []
    metrics = ['brier', 'log_loss', 'pick_hit', 'top3_all3', 'top5_all3', 'top5_capture', 'six_combo_hit']
    for variant, group in result.groupby('variant'):
        summaries.append(dict(variant=variant, races=len(group), days=group.race_date.nunique(),
                              **{metric: float(group[metric].mean()) for metric in metrics}))
    for variant in ['R1', 'F1', 'F2']:
        for metric in metrics:
            differences.append(dict(comparison=f'{variant}-HY_R_FORM', metric=metric,
                                    **bootstrap_race(result.loc[result.variant.eq(variant)],
                                                     result.loc[result.variant.eq('HY_R_FORM')], metric)))
    return result, runner_frame, ticket_frame, pd.DataFrame(summaries), pd.DataFrame(differences)


def train():
    verify_pretraining_gate()
    features = pd.read_parquet(OUT / 'features.parquet')
    results = []
    for year in YEARS:
        for variant in ['F1', 'F2']:
            results.append(fit_candidate(features, variant, year))
    candidate_races = pd.concat([result[0] for result in results], ignore_index=True)
    candidate_runners = pd.concat([result[1] for result in results], ignore_index=True)
    candidate_tickets = pd.concat([result[2] for result in results], ignore_index=True)
    replay_races = pd.read_csv(OUT / 'r1_reproduced_race_metrics.csv')
    replay_runners = pd.read_parquet(OUT / 'r1_reproduced_runner_predictions.parquet')
    replay_tickets = pd.read_csv(OUT / 'r1_reproduced_six_combinations.csv')
    all_races = pd.concat([replay_races, candidate_races], ignore_index=True)
    all_runners = pd.concat([replay_runners, candidate_runners], ignore_index=True)
    all_tickets = pd.concat([replay_tickets, candidate_tickets], ignore_index=True)
    all_runners = add_prediction_context(all_runners, features)
    assert set(all_races.variant) == {'R1', 'F1', 'F2'}
    assert len(all_runners) == 3 * 17412 and all_races.groupby('variant').size().eq(1779).all()
    write_frame_new(OUT / 'race_metrics.csv', all_races)
    write_frame_new(OUT / 'runner_predictions.parquet', all_runners, parquet=True)
    write_frame_new(OUT / 'six_combinations.csv', all_tickets)
    race_group, race_diff, runner_group, runner_diff = group_metric_tables(all_races, all_runners)
    write_frame_new(OUT / 'metrics_by_group.csv', race_group)
    write_frame_new(OUT / 'paired_differences.csv', race_diff)
    write_frame_new(OUT / 'runner_metrics_by_group.csv', runner_group)
    write_frame_new(OUT / 'runner_paired_differences.csv', runner_diff)
    write_frame_new(OUT / 'calibration_bins.csv', calibration_bins(all_runners))
    op_races, op_runners, op_tickets, op_summary, op_diff = operating_common_comparison(
        all_runners, all_races, all_tickets)
    write_frame_new(OUT / 'operating_common_467_race_metrics.csv', op_races)
    write_frame_new(OUT / 'operating_common_467_runner_predictions.parquet', op_runners, parquet=True)
    write_frame_new(OUT / 'operating_common_467_six_combinations.csv', op_tickets)
    write_frame_new(OUT / 'operating_common_467_summary.csv', op_summary)
    write_frame_new(OUT / 'operating_common_467_paired_differences.csv', op_diff)
    verify_refs_and_protection(output_lock())
    completion = dict(
        passed=True,
        final_candidate_models=6,
        lightgbm_train_calls=12,
        temperature_optimizations=6,
        variants=['R1', 'F1', 'F2'],
        runner_rows=int(len(all_runners)), races_per_variant=1779,
        evaluation_rows_per_variant=17412,
        r1_reloaded_without_refit=True,
        bootstrap_repetitions=BOOTSTRAP_REPS,
        bootstrap_seed=BOOTSTRAP_SEED,
        operating_common_races=467,
        operating_common_runner_rows_per_variant=4475,
        production_changed=False,
        database_changed=False,
        outputs={path.name: e.sha(path) for path in OUT.iterdir() if path.is_file()},
    )
    e.save_json(OUT / 'training_completion.json', completion)
    print(op_summary.to_string(index=False), flush=True)
    print(json.dumps(completion, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['replay', 'fit'])
    args = parser.parse_args()
    {'replay': replay_r1, 'fit': train}[args.phase]()
