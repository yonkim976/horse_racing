"""Create the frozen comparison report from saved F1_STYLE6 scores; never fit."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

import prepare as e
import run as fit_runner

OLD = e.F1.base
REPORT_DIR = e.OUT / 'report'
REPS = 2000
SEED = 20261008
PRIMARY = ['log_loss', 'brier']
SECONDARY = ['top5_capture', 'top5_all3', 'six_combo_hit', 'pick_hit']


def write_frame(path, frame, parquet=False):
    e.save_frame_new(path, frame, parquet=parquet)


def write_json(path, payload):
    e.save_json_new(path, payload)


def check_fit_artifacts():
    completion_path = e.OUT / 'candidate_training_completion.json'
    approval_path = e.OUT / 'root_fit_approval.json'
    lock_path = e.OUT / 'prepared_lock.json'
    assert completion_path.is_file() and approval_path.is_file() and lock_path.is_file()
    completion = e.load_json(completion_path)
    approval = e.load_json(approval_path)
    lock = e.load_json(lock_path)
    assert completion.get('passed') is True
    assert completion.get('candidate') == e.VARIANT
    assert completion.get('candidate_models') == 3
    assert completion.get('lightgbm_train_calls') == 6
    assert completion.get('temperature_optimizations') == 3
    assert completion.get('candidate_outcome_metrics_computed') is False
    assert approval.get('approved') is True and approval.get('approved_by') == 'root'
    assert approval.get('candidate') == e.VARIANT
    fit_runner.verify_locked_inputs(lock)
    assert completion.get('prepared_lock_sha256') == e.sha256(lock_path)
    assert completion.get('code_sha256') == {
        name: e.sha256(e.HERE / name) for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')
    }
    return completion, approval, lock


def add_pick_hit(races, runners, tickets):
    result = races.copy()
    picks = []
    for race_id, group in runners.groupby('race_id', sort=False):
        top = group.sort_values('score', ascending=False, kind='stable').iloc[0]
        picks.append(dict(race_id=race_id, pick_hit=int(top.y)))
    result = result.merge(pd.DataFrame(picks), on='race_id', how='left', validate='one_to_one')
    ticket_hits = tickets.groupby('race_id', sort=False).hit.max().rename('six_combo_hit_recomputed')
    result = result.merge(ticket_hits, on='race_id', how='left', validate='one_to_one')
    if 'six_combo_hit' in result:
        assert result.six_combo_hit.astype(int).equals(result.six_combo_hit_recomputed.astype(int))
        result = result.drop(columns='six_combo_hit_recomputed')
    else:
        result = result.rename(columns={'six_combo_hit_recomputed': 'six_combo_hit'})
    return result


def safe_context_join(predictions, features, columns):
    right = features[['api_record_id'] + columns].copy()
    overlaps = [column for column in columns if column in predictions.columns]
    if overlaps:
        left = predictions.set_index('api_record_id')
        other = right.set_index('api_record_id')
        assert left.index.is_unique and other.index.is_unique
        aligned = left[overlaps].join(other[overlaps], how='left', lsuffix='_existing', rsuffix='_context', validate='one_to_one')
        for column in overlaps:
            a = aligned[f'{column}_existing']
            b = aligned[f'{column}_context']
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                assert np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=0, equal_nan=True), (
                    f'context overlap differs: {column}'
                )
            else:
                assert a.astype('string').fillna('<NA>').equals(b.astype('string').fillna('<NA>')), (
                    f'context overlap differs: {column}'
                )
        right = right.drop(columns=overlaps)
    result = predictions.merge(right, on='api_record_id', how='left', validate='one_to_one', sort=False)
    assert result.api_record_id.equals(predictions.api_record_id)
    return result


def support_tables(features, candidate_runners):
    rows = []
    feature_n = {
        's1f_position': 'hist_s1f_relpos_n',
        's1f_to_4c_change': 'hist_s1f_to_c4_pair_n',
        '4c_to_g1f_change': 'hist_c4_to_g1f_pair_n',
    }
    career = pd.cut(features.observed_starts, [-1, 0, 4, np.inf], labels=['0', '1_4', '5_plus'])
    for feature_name, n_column in feature_n.items():
        contexts = [
            ('all', 'all', features),
            *[('year', str(int(k)), v) for k, v in features.groupby('year', sort=True)],
            *[('distance_m', str(int(k)), v) for k, v in features.groupby('distance_m', sort=True)],
            *[('career_observed_starts', str(k), features.loc[career.astype('string').eq(k)])
              for k in ['0', '1_4', '5_plus']],
            ('history_availability', 'unknown_no_valid_history', features.loc[features[n_column].eq(0)]),
            ('history_availability', 'has_valid_history', features.loc[features[n_column].gt(0)]),
        ]
        for kind, value, subset in contexts:
            for n, one in subset.groupby(n_column, sort=True, dropna=False):
                rows.append(dict(concept=feature_name, group=kind, value=value,
                                 valid_n=int(n), runners=int(len(one)), races=int(one.race_id.nunique()),
                                 race_days=int(one.race_date.nunique())))
    support = pd.DataFrame(rows)
    # Keep support table independent of downstream model performance claims.
    assert set(support.concept) == set(feature_n)
    return support


def runner_bootstrap(group, metric):
    assert group.api_record_id.is_unique
    pair = group[['api_record_id', 'race_id', 'race_date', f'{metric}_candidate', f'{metric}_f1']].copy()
    pair['delta'] = pair[f'{metric}_candidate'] - pair[f'{metric}_f1']
    assert pair.delta.notna().all()
    daily = pair.groupby('race_date', sort=True).delta.agg(['sum', 'size'])
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(daily), size=(REPS, len(daily)))
    samples = daily['sum'].to_numpy()[indices].sum(axis=1) / daily['size'].to_numpy()[indices].sum(axis=1)
    return dict(delta_candidate_minus_f1=float(pair.delta.mean()),
                ci95_low=float(np.quantile(samples, .025)), ci95_high=float(np.quantile(samples, .975)),
                runner_rows=int(len(pair)), races=int(pair.race_id.nunique()),
                race_days=int(pair.race_date.nunique()), resamples=REPS, seed=SEED)


def conditional_runner_losses(candidate_runners, baseline_runners, features):
    keys = ['api_record_id', 'race_id', 'race_date', 'year', 'distance_m']
    c = candidate_runners[keys + ['log_loss', 'brier']].rename(
        columns={'log_loss': 'log_loss_candidate', 'brier': 'brier_candidate'})
    f = baseline_runners[keys + ['log_loss', 'brier']].rename(
        columns={'log_loss': 'log_loss_f1', 'brier': 'brier_f1'})
    pair = c.merge(f, on=keys, how='inner', validate='one_to_one')
    assert len(pair) == 17412 and pair.api_record_id.is_unique
    context_cols = ['api_record_id', 'observed_starts', 'hist_s1f_relpos_n',
                    'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n']
    context = features[context_cols]
    pair = pair.merge(context, on='api_record_id', how='left', validate='one_to_one')
    career = pd.cut(pair.observed_starts, [-1, 0, 4, np.inf], labels=['0', '1_4', '5_plus'])
    groups = [('all', 'all', pair)]
    for year, one in pair.groupby('year', sort=True):
        groups.append(('year', str(int(year)), one))
    for distance, one in pair.groupby('distance_m', sort=True):
        groups.append(('distance_m', str(int(distance)), one))
    for label in ['0', '1_4', '5_plus']:
        groups.append(('career_observed_starts', label, pair.loc[career.astype('string').eq(label)]))
    for name, column in [('s1f_position', 'hist_s1f_relpos_n'),
                         ('s1f_to_4c_change', 'hist_s1f_to_c4_pair_n'),
                         ('4c_to_g1f_change', 'hist_c4_to_g1f_pair_n')]:
        for n in range(6):
            groups.append((f'history_valid_n:{name}', str(n), pair.loc[pair[column].eq(n)]))
        groups.extend([
            (f'history_availability:{name}', 'unknown_no_valid_history', pair.loc[pair[column].eq(0)]),
            (f'history_availability:{name}', 'has_valid_history', pair.loc[pair[column].gt(0)]),
        ])
    rows = []
    for kind, value, group in groups:
        if group.empty:
            rows.append(dict(group=kind, value=value, metric='log_loss', runner_rows=0, races=0,
                             race_days=0, delta_candidate_minus_f1=np.nan,
                             ci95_low=np.nan, ci95_high=np.nan, resamples=REPS, seed=SEED))
            rows.append(dict(group=kind, value=value, metric='brier', runner_rows=0, races=0,
                             race_days=0, delta_candidate_minus_f1=np.nan,
                             ci95_low=np.nan, ci95_high=np.nan, resamples=REPS, seed=SEED))
            continue
        for metric in ['log_loss', 'brier']:
            rows.append(dict(group=kind, value=value, metric=metric,
                             **runner_bootstrap(group, metric)))
    return pd.DataFrame(rows)


def comparison_tables(candidate_races, baseline_races):
    merged = candidate_races.merge(
        baseline_races[['race_id', 'race_date', 'year', 'distance_m', *PRIMARY, *SECONDARY]],
        on='race_id', how='inner', suffixes=('_candidate', '_f1'), validate='one_to_one'
    )
    assert len(merged) == len(candidate_races) == len(baseline_races) == 1779
    rows = []
    groups = [('all', 'all', merged)]
    for year, group in merged.groupby('year_candidate', sort=True):
        groups.append(('year', str(int(year)), group))
    for distance, group in merged.groupby('distance_m_candidate', sort=True):
        groups.append(('distance_m', str(int(distance)), group))
    for kind, value, group in groups:
        for metric in PRIMARY + SECONDARY:
            left = group[['race_id', 'race_date_candidate', f'{metric}_candidate']].rename(
                columns={'race_date_candidate': 'race_date', f'{metric}_candidate': metric})
            right = group[['race_id', f'{metric}_f1']].rename(columns={f'{metric}_f1': metric})
            stat = race_bootstrap(left, right, metric)
            rows.append(dict(group=kind, value=value, metric=metric, **stat))
    diffs = pd.DataFrame(rows)
    overall = diffs.loc[diffs.group.eq('all') & diffs.metric.isin(PRIMARY)]
    point = {row.metric: row.delta_candidate_minus_f1 for row in overall.itertuples(index=False)}
    ci = {row.metric: row.ci95_high for row in overall.itertuples(index=False)}
    gate = bool(all(point[metric] < 0 for metric in PRIMARY)
                and any(ci[metric] < 0 for metric in PRIMARY))
    return diffs, dict(primary_gate_passed=gate,
                       required_both_point_estimates_improve=True,
                       at_least_one_primary_ci_upper_below_zero=True,
                       candidate_minus_f1=True,
                       negative_loss_difference_means_improvement=True,
                       primary_point_differences=point,
                       primary_ci95_upper=ci)


def race_bootstrap(left, right, metric):
    pair = left[['race_id', 'race_date', metric]].rename(columns={metric: 'candidate'}).merge(
        right[['race_id', metric]].rename(columns={metric: 'f1'}), on='race_id', how='inner', validate='one_to_one'
    )
    assert len(pair) == len(left) == len(right)
    pair['delta'] = pair.candidate - pair.f1
    daily = pair.groupby('race_date', sort=True).delta.agg(['sum', 'size'])
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(daily), size=(REPS, len(daily)))
    samples = daily['sum'].to_numpy()[idx].sum(axis=1) / daily['size'].to_numpy()[idx].sum(axis=1)
    return dict(delta_candidate_minus_f1=float(pair.delta.mean()),
                ci95_low=float(np.quantile(samples, .025)), ci95_high=float(np.quantile(samples, .975)),
                races=int(len(pair)), race_days=int(len(daily)), resamples=REPS, seed=SEED)


def operating_common_467(runners, races, tickets):
    op_dir = e.HERE.parent / '20261009_operating_model_comparison_v1' / 'outputs'
    op_races = pd.read_csv(op_dir / 'race_metrics.csv')
    op_runners = pd.read_parquet(op_dir / 'runner_predictions.parquet')
    op_tickets = pd.read_csv(op_dir / 'six_combinations.csv')
    hyd = op_races.loc[op_races.variant.eq('HY_R_FORM')].copy()
    race_ids = set(hyd.race_id.astype(str))
    assert len(race_ids) == 467
    rows = []
    candidate_runners = runners.loc[runners.year.eq(2026) & runners.race_id.astype(str).isin(race_ids)]
    op_horses = op_runners.loc[op_runners.variant.eq('HY_R_FORM')]
    for variant in ['F1', e.VARIANT]:
        one = candidate_runners.loc[candidate_runners.variant.eq(variant)].copy()
        compare = one.sort_values(['race_id', 'horse_id'], kind='stable').reset_index(drop=True)
        ref = op_horses.loc[op_horses.race_id.astype(str).isin(race_ids)].sort_values(
            ['race_id', 'horse_id'], kind='stable').reset_index(drop=True)
        assert len(compare) == len(ref) == 4475
        assert compare[['race_id', 'horse_id', 'y']].astype(str).equals(ref[['race_id', 'horse_id', 'y']].astype(str))
        race_set = races.loc[races.variant.eq(variant) & races.race_id.astype(str).isin(race_ids)].copy()
        assert race_set.race_id.nunique() == 467
        race_set['source'] = 'additive_canonical_six_set'
        rows.append(race_set)
    hyd['source'] = 'native_hy_r_form_pl'
    combined = pd.concat([hyd, *rows], ignore_index=True, sort=False)
    summaries = []
    diffs = []
    for variant, group in combined.groupby('variant', sort=True):
        summaries.append(dict(variant=variant, probability_semantics=group.source.iloc[0],
                              races=int(group.race_id.nunique()), race_days=int(group.race_date.nunique()),
                              log_loss=float(group.log_loss.mean()), brier=float(group.brier.mean()),
                              pick_hit=float(group.pick_hit.mean()), top5_capture=float(group.top5_capture.mean()),
                              six_combo_hit=float(group.six_combo_hit.mean())))
    base = combined.loc[combined.variant.eq('HY_R_FORM')]
    for variant in ['F1', e.VARIANT]:
        current = combined.loc[combined.variant.eq(variant)]
        for metric in ['log_loss', 'brier', 'pick_hit', 'top5_capture', 'six_combo_hit']:
            stat = race_bootstrap(
                current[['race_id', 'race_date', metric]], base[['race_id', metric]], metric)
            diffs.append(dict(comparison=f'{variant}-HY_R_FORM', metric=metric,
                              probability_semantics='HY native PL separate from additive six-set', **stat))
    return combined, pd.DataFrame(summaries), pd.DataFrame(diffs)


def create_report():
    completion, approval, lock = check_fit_artifacts()
    assert not REPORT_DIR.exists(), f'refusing to overwrite report: {REPORT_DIR}'
    REPORT_DIR.mkdir()
    features = pd.read_parquet(e.OUT / 'features.parquet')
    candidate_stage = pd.read_parquet(e.OUT / 'candidate_scores_fit_stage.parquet')
    baseline_runners = pd.read_parquet(e.OUT / 'f1_reproduced_runner_predictions.parquet')
    baseline_races = pd.read_csv(e.OUT / 'f1_reproduced_race_metrics.csv')
    baseline_tickets = pd.read_csv(e.OUT / 'f1_reproduced_six_combinations.csv')
    candidate_races, candidate_runners, candidate_tickets = [], [], []
    for year in e.YEARS:
        folder = e.OUT / f'{e.VARIANT}_{year}'
        meta = e.load_json(folder / 'meta.json')
        assert e.sha256(folder / 'top3.txt') == meta['model_sha256']
        assert meta['evaluation_year'] == year and meta['features'] == e.MODEL_COLUMNS
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        stored = candidate_stage.loc[candidate_stage.year.eq(year)].copy()
        assert stored.api_record_id.astype('int64').tolist() == test.api_record_id.astype('int64').tolist()
        assert stored.score.notna().all()
        race_result, runner_result, ticket_result = OLD.evaluate(
            test, stored.score.to_numpy(float), float(meta['tau']), e.VARIANT)
        candidate_races.append(race_result)
        candidate_runners.append(runner_result)
        candidate_tickets.append(ticket_result)
    c_races = add_pick_hit(pd.concat(candidate_races, ignore_index=True),
                           pd.concat(candidate_runners, ignore_index=True),
                           pd.concat(candidate_tickets, ignore_index=True))
    f_races = add_pick_hit(baseline_races, baseline_runners, baseline_tickets)
    c_runners = pd.concat(candidate_runners, ignore_index=True)
    c_tickets = pd.concat(candidate_tickets, ignore_index=True)
    f_runners = baseline_runners.copy()
    f_tickets = baseline_tickets.copy()
    assert len(c_runners) == len(f_runners) == 17412
    assert c_races.race_id.nunique() == f_races.race_id.nunique() == 1779
    assert len(c_tickets) == len(f_tickets) == 10674
    top6_mass = c_tickets.groupby('race_id').probability.sum().rename('top6_mass')
    candidate_mass = c_races.set_index('race_id').six_combo_mass
    top6_mass = top6_mass.reindex(candidate_mass.index)
    assert top6_mass.notna().all()
    assert np.allclose(top6_mass.to_numpy(float), candidate_mass.to_numpy(float), rtol=0, atol=1e-12)
    assert top6_mass.gt(0).all() and top6_mass.le(1 + 1e-12).all()
    c_runners = safe_context_join(c_runners, features, [
        'observed_starts', 'previous_result_status', 'previous_top3',
        'same_distance_last5_actual_n', 'same_distance_last5_normal_n',
        'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n',
    ])
    f_runners = safe_context_join(f_runners, features, [
        'observed_starts', 'previous_result_status', 'previous_top3',
        'same_distance_last5_actual_n', 'same_distance_last5_normal_n',
        'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n',
    ])
    all_runners = pd.concat([f_runners, c_runners], ignore_index=True, sort=False)
    all_races = pd.concat([f_races, c_races], ignore_index=True, sort=False)
    all_tickets = pd.concat([f_tickets, c_tickets], ignore_index=True, sort=False)
    paired, gate = comparison_tables(c_races, f_races)
    support = support_tables(features, c_runners)
    conditional = conditional_runner_losses(c_runners, f_runners, features)
    op_races, op_summary, op_diffs = operating_common_467(all_runners, all_races, all_tickets)

    write_frame(REPORT_DIR / 'race_metrics.parquet', all_races, parquet=True)
    write_frame(REPORT_DIR / 'runner_predictions.parquet', all_runners, parquet=True)
    write_frame(REPORT_DIR / 'canonical_six_combinations.csv', all_tickets)
    write_frame(REPORT_DIR / 'paired_date_bootstrap.csv', paired)
    write_frame(REPORT_DIR / 'history_support.csv', support)
    write_frame(REPORT_DIR / 'conditional_runner_losses.csv', conditional)
    write_frame(REPORT_DIR / 'operating_common_467_race_metrics.csv', op_races)
    write_frame(REPORT_DIR / 'operating_common_467_summary.csv', op_summary)
    write_frame(REPORT_DIR / 'operating_common_467_paired_differences.csv', op_diffs)
    report = dict(
        passed=True,
        candidate=e.VARIANT,
        baseline='saved F1 exact replay',
        cohort_rows=17412,
        races=1779,
        race_days=int(c_races.race_date.nunique()),
        canonical_six_combination_rows=10674,
        primary_gate=gate,
        primary_metrics=PRIMARY,
        secondary_metrics=SECONDARY,
        paired_direction='candidate_minus_F1',
        negative_log_loss_or_brier_difference_means_improvement=True,
        bootstrap_resamples=REPS,
        bootstrap_seed_reset_per_metric=SEED,
        candidate_training_completion_sha256=e.sha256(e.OUT / 'candidate_training_completion.json'),
        root_fit_approval_sha256=e.sha256(e.OUT / 'root_fit_approval.json'),
        prepared_lock_sha256=e.sha256(e.OUT / 'prepared_lock.json'),
        report_artifacts={path.name: e.sha256(path) for path in REPORT_DIR.iterdir() if path.is_file()},
        operating_common_races=467,
        interpretation_scope=(
            'The six columns are a joint position-level, transition-change, and availability package. '
            'An improvement does not identify an independent effect of position change or tactical style. '
            'On identical valid slots, S1F mean minus the two mean changes can reconstruct mean G1F relative position; '
            'the bundle therefore remains entangled with recent G1F position level.'
        ),
        pure_tactical_effect_claim_permitted=False,
        operating_probability_semantics='HY_R_FORM native PL; F1 and F1_STYLE6 additive canonical six-set probabilities',
        outcome_scope='retrospective development; no independent future validation or causal inference',
        no_refit_after_report=True,
    )
    write_json(REPORT_DIR / 'report_receipt.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'report':
        raise SystemExit('usage: report.py report (requires saved candidate training outputs)')
    create_report()
