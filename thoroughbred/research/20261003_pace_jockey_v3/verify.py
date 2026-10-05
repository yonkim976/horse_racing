"""Independent history arithmetic, chronological expectations and model replay."""
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.linear_model import Ridge

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('jockey_verify', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    RUN.check_inputs()
    c = RUN.cfg()
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)
    summary = json.loads((OUT / 'summary.json').read_text())
    for name, digest in summary['result_hashes'].items():
        check('artifact ' + name, RUN.BASE.sha(OUT / name) == digest)
    f = pd.read_parquet(OUT / 'features.parquet')
    h = pd.read_parquet(OUT / 'history.parquet')
    expectations = pd.read_parquet(OUT / 'external_expectations.parquet')
    models = json.loads((OUT / 'expectation_models.json').read_text())
    original = pd.read_parquet(RUN.V2_PATH / 'outputs/raw_features.parquet')
    pd.testing.assert_frame_equal(f[original.columns], original)
    check('base input unchanged', True)
    reuse = json.loads((OUT / 'reuse_audit.json').read_text())
    archive = HERE / 'outputs_before_threshold_fix'
    check('archived original definition', RUN.BASE.sha(archive / 'frozen_run.py') == reuse['archived_definition_sha256'])
    before = pd.read_parquet(archive / 'features.parquet')
    before_race = pd.read_parquet(archive / 'race_features.parquet')
    current_race = pd.read_parquet(OUT / 'race_features.parquet')
    for name in ['labels.parquet', 'race_labels.parquet']:
        pd.testing.assert_frame_equal(pd.read_parquet(archive / name), pd.read_parquet(OUT / name), check_exact=True)
        check('reused labels identical ' + name, True)
    for item in reuse['reused_bundles']:
        meta = json.loads((OUT / 'models' / item['bundle'] / 'metadata.json').read_text())
        check('reused metadata identity ' + item['bundle'],
              RUN.BASE.sha(OUT / 'models' / item['bundle'] / 'metadata.json') == item['original_metadata_sha256'])
        for model in meta['models']:
            left, right = (before_race, current_race) if model['file'] == 'tempo.txt' else (before, f)
            pd.testing.assert_frame_equal(left[model['columns']], right[model['columns']], check_exact=True)
            check('reused full input identity ' + item['bundle'] + '/' + model['file'], True)
    del before, before_race, current_race
    check('external residual chronology', expectations.expectation_training_end.lt(expectations.year).all())
    check('residual model excludes warm-up targets', all(m['training_end'] >= 2017 for m in models))
    check('current label only used as residual target', np.allclose(expectations.early_residual,
        expectations.expected_early - expectations.S1F_fraction.astype(float), equal_nan=True))
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    forbidden = {'jockey_id', 'jockey_name', 'previous_jockey_id', 'outcome', 'S1F_rank', 'G3F_rank',
                 'S1F_fraction', 'G3F_fraction', 'advance', 'early_residual', 'advance_residual', 'moisture', 'tempo_time'}
    whitelist = contract['runner'] + contract['race'] + [v for group in contract['groups'].values() for v in group]
    whitelist += [v for group in contract['race_groups'].values() for v in group]
    check('no current outcome or identity in model inputs', not set(whitelist) & forbidden)
    for col in ['history_source_date', 'pace_source_date', 'previous_jockey_source_date',
                'jockey_trait_source_date', 'pair_trait_source_date', 'stability_source_date']:
        check('T-2 ' + col, (f[col].isna() | f[col].le(f.race_date - pd.Timedelta(days=c['history_lag_days']))).all())
    check('recent counts nonnegative', f.jockey_recent_count.ge(0).all())
    check('residual count does not exceed rides', f.jockey_early_count.le(f.jockey_history_count).all())
    check('new pair has zero shrunk trait', f.loc[f.pair_early_count.eq(0), 'pair_aggression'].eq(0).all())
    # Recompute source subsets rather than using the feature-builder's cumulative/asof helpers.
    for row in f.sample(100, random_state=c['seed']).itertuples():
        cutoff = row.race_date - pd.Timedelta(days=c['history_lag_days'])
        past = h[h.meet.eq(row.meet) & h.jockey_id.eq(row.jockey_id) & h.race_date.le(cutoff)]
        early = past.early_residual.dropna()
        recent = past[past.race_date.gt(row.race_date - pd.Timedelta(days=c['jockey_recent_days']))].early_residual.dropna()
        pair = past[past.horse_id.eq(row.horse_id)]
        pair_early = pair.early_residual.dropna()
        horse = h[h.horse_id.eq(row.horse_id) & h.race_date.le(cutoff)].sort_values('race_date')
        previous = horse.jockey_id.iloc[-1] if len(horse) else None
        label = row.race_key + '/' + row.horse_id
        check('independent jockey rides ' + label, len(past) == row.jockey_history_count)
        check('independent aggression ' + label, len(early) == row.jockey_early_count
              and np.isclose(early.sum() / (len(early) + c['jockey_prior_observations']), row.jockey_aggression))
        check('independent recent180 ' + label, len(recent) == row.jockey_recent_count
              and np.isclose(recent.sum() / (len(recent) + c['jockey_prior_observations']), row.jockey_recent_aggression))
        check('independent paired rides ' + label, len(pair) == row.pair_history_count
              and len(pair_early) == row.pair_early_count
              and np.isclose(pair_early.sum() / (len(pair_early) + c['pair_prior_observations']), row.pair_aggression))
        outer = past[past.gate_outer_proxy.eq(1)].early_residual.dropna()
        distance = past[past.distance_m.le(1400) if row.distance_m <= 1400 else past.distance_m.gt(1400)].early_residual.dropna()
        check('independent outer/distance trait ' + label,
              len(outer) == row.jockey_outer_count and len(distance) == row.jockey_distance_count
              and np.isclose(outer.sum() / (len(outer) + c['jockey_prior_observations']), row.jockey_outer_aggression)
              and np.isclose(distance.sum() / (len(distance) + c['jockey_prior_observations']), row.jockey_distance_aggression))
        check('independent previous jockey ' + label, previous == row.previous_jockey_id
              if previous is not None else pd.isna(row.previous_jockey_id))
        last = horse.tail(10).historical_start_time.astype(float)
        check('independent time dispersion ' + label, np.isclose(last.std(), row.stability_last10_time_std, equal_nan=True)
              and (np.isclose(last.count(), row.stability_last10_time_count) if len(horse) else pd.isna(row.stability_last10_time_count)))
        if len(horse):
            times = horse.historical_start_time.astype(float).to_numpy()
            slow = []
            for i in range(max(0, len(times) - 10), len(times)):
                previous_times = times[max(0, i - 3):i]
                known = previous_times[np.isfinite(previous_times)]
                if np.isfinite(times[i]) and len(known):
                    slow.append(float(times[i] - known.mean() > c['slow_start_seconds'] + 1e-9))
            check('independent slow-history rate ' + label,
                  len(slow) == row.stability_last10_slow_count and
                  np.isclose(np.mean(slow) if slow else np.nan, row.stability_last10_slow_rate, equal_nan=True))
    # Reconstruct design using saved preprocessing constants, not ridge_design().
    labeled = original.merge(pd.read_parquet(OUT / 'labels.parquet'), on=RUN.KEY, validate='one_to_one')
    labeled['advance'] = labeled.S1F_fraction - labeled.G3F_fraction
    for meta in models:
        check('expectation chronology ' + str((meta['meet'], meta['source_year'])), meta['training_end'] < meta['source_year'])
    for meet in c['venues']:
        meta = next(m for m in models if m['meet'] == meet and m['source_year'] == 2026)
        transform = meta['transform']
        one = labeled[labeled.meet.eq(meet)].reset_index(drop=True)
        numerical = one[transform['numeric']].apply(pd.to_numeric).astype(float).to_numpy()
        median = np.array(transform['median']); mean = np.array(transform['mean']); scale = np.array(transform['scale'])
        numerical = np.where(np.isnan(numerical), median, numerical)
        chunks = [(numerical - mean) / scale]
        for col, categories in transform['vocabulary'].items():
            values = one[col].fillna('__missing').astype(str)
            chunks += [values.eq(value).to_numpy(float)[:, None] for value in categories]
        x = np.concatenate(chunks, axis=1)
        selected = one.year.eq(2026)
        observed = expectations[expectations.meet.eq(meet) & expectations.year.eq(2026)]
        check('expectation row keys ' + str(meet), one.loc[selected, RUN.KEY].reset_index(drop=True).equals(observed[RUN.KEY].reset_index(drop=True)))
        for head in meta['heads']:
            target = head['target']
            train = one.year.between(2017, 2025) & one.S1F_complete & one[target].notna()
            independent = Ridge(alpha=c['expectation_alpha'])
            independent.fit(x[train], one.loc[train, target], sample_weight=1 / one.loc[train, 'field_size'])
            check('independent expectation coefficients ' + str((meet, target)),
                  np.max(abs(independent.coef_ - head['coefficient'])) < 1e-10 and abs(independent.intercept_ - head['intercept']) < 1e-10)
            name = 'expected_early' if target == 'S1F_fraction' else 'expected_advance'
            lo = 0 if target == 'S1F_fraction' else -1
            prediction = np.clip(x[selected] @ np.array(head['coefficient']) + head['intercept'], lo, 1)
            check('expectation replay ' + str((meet, target)), np.max(abs(prediction - observed[name].to_numpy())) < 1e-10)
    labels = pd.read_parquet(OUT / 'labels.parquet')
    frame = f.merge(labels, on=RUN.KEY, validate='one_to_one')
    predictions = pd.read_parquet(OUT / 'runner_predictions.parquet')
    metrics = pd.read_csv(OUT / 'point_metrics.csv')
    check('prediction keys unique', not predictions.duplicated(RUN.KEY + ['point', 'variant']).any())
    for point in c['points']:
        expected = frame[frame.year.isin(c['evaluation_years']) & frame[point + '_complete']]
        keyset = set(zip(expected.race_key, expected.horse_id))
        for variant in c['variants']:
            p = predictions[predictions.point.eq(point) & predictions.variant.eq(variant)]
            check('identical evaluation cohort ' + point + '/' + variant, set(zip(p.race_key, p.horse_id)) == keyset)
            check('point probability sums ' + point + '/' + variant,
                  np.max(abs(p.groupby('race_key')[['prob_lead', 'prob_front3']].sum().to_numpy() - [1, 3])) < 1e-10)
            check('point probability ranges ' + point + '/' + variant,
                  p.prob_lead.ge(0).all() and p.prob_front3.le(1 + 1e-12).all() and
                  (p.prob_lead <= p.prob_front3 + 1e-12).all())
    inherited = pd.read_parquet(RUN.V2_PATH / 'outputs/runner_predictions.parquet')
    inherited = inherited[inherited.variant.eq('gate')].reset_index(drop=True)
    pd.testing.assert_frame_equal(inherited, predictions[predictions.variant.eq('gate')].reset_index(drop=True))
    check('baseline predictions exact reuse', True)
    replay = predictions.assign(error=abs(predictions.expected_position - predictions.actual_rank))
    replay = replay.groupby(['race_key', 'point', 'variant']).error.mean().reset_index()
    paired = metrics.merge(replay, on=['race_key', 'point', 'variant'], validate='one_to_one')
    check('all race position MAEs', len(paired) == len(metrics) and np.max(abs(paired.error - paired.position_mae)) < 1e-10)
    aggregate = metrics.groupby(['meet', 'point', 'variant']).position_mae.agg(['size', 'mean'])
    for row in pd.read_csv(OUT / 'metrics.csv').query("period == 'all'").itertuples():
        observed = aggregate.loc[(row.meet, row.point, row.variant)]
        check('aggregate ' + str((row.meet, row.point, row.variant)), row.races == observed['size'] and abs(row.position_mae - observed['mean']) < 1e-10)
    race = pd.read_parquet(OUT / 'race_features.parquet').merge(pd.read_parquet(OUT / 'race_labels.parquet'), on='race_key', validate='one_to_one')
    tempo = pd.read_csv(OUT / 'tempo_predictions.csv')
    expected_tempo = set(race.loc[race.year.isin(c['evaluation_years']) & race.tempo_complete, 'race_key'])
    for variant in c['variants']:
        saved = tempo[tempo.variant.eq(variant)]
        check('tempo identical cohort ' + variant, not saved.race_key.duplicated().any() and set(saved.race_key) == expected_tempo)
        probs = saved[['prob_fast', 'prob_normal', 'prob_slow']].dropna()
        check('tempo class probabilities ' + variant, np.max(abs(probs.sum(axis=1) - 1)) < 1e-10 and (probs >= -1e-12).all().all())
    max_error = 0.
    for bundle in summary['models']:
        dest = OUT / 'models' / f"{bundle['meet']}_{bundle['year']}_{bundle['variant']}"
        for name, digest in bundle['artifact_hashes'].items():
            check('bundle hash ' + dest.name + '/' + name, RUN.BASE.sha(dest / name) == digest)
        for model in bundle['models']:
            name = dest.name + '/' + model['file']
            check('model chronology ' + name, model['training_year_end'] < model['calibration_year'] < model['evaluation_year'])
            point = model['file'].split('.')[0]
            target = race if point == 'tempo' else frame
            complete = target.tempo_complete if point == 'tempo' else target[point + '_complete']
            key = target[target.meet.eq(bundle['meet']) & target.year.eq(bundle['year']) & complete].race_key.drop_duplicates().sample(1, random_state=c['seed']).iloc[0]
            one = target[target.race_key.eq(key)]
            if point != 'tempo':
                one = one.sort_values('program_no')
            x = one[model['columns']].copy()
            for col, categories in model['vocabulary'].items():
                x[col] = pd.Categorical(x[col], categories=categories)
            pred = lgb.Booster(model_file=str(dest / model['file'])).predict(x)
            if point == 'tempo':
                saved = tempo[tempo.race_key.eq(key) & tempo.variant.eq(bundle['variant'])].iloc[0]
                err = abs(pred[0] + bundle['tempo']['bias'] - saved.predicted_time)
            else:
                saved = predictions[predictions.race_key.eq(key) & predictions.point.eq(point) & predictions.variant.eq(bundle['variant'])].sort_values('program_no')
                err = np.max(abs(pred - saved.predicted_fraction.to_numpy()))
                logits = -pred / bundle['point_temperatures'][point][0]
                lead = np.exp(logits - logsumexp(logits))
                check('independent lead softmax ' + name, np.max(abs(lead - saved.prob_lead.to_numpy())) < 1e-10)
            check('regressor replay ' + name, err < 1e-10)
            max_error = max(max_error, float(err))
    RUN.check_inputs()
    result = {'passed': len(checks), 'failed': 0, 'max_replay_error': max_error, 'checks': checks,
              'verify_sha256': RUN.BASE.sha(__file__), 'production_changed': False}
    RUN.BASE.save_json(OUT / 'verification.json', result)
    print(json.dumps({'passed': len(checks), 'failed': 0, 'max_replay_error': max_error}), flush=True)


if __name__ == '__main__':
    main()
