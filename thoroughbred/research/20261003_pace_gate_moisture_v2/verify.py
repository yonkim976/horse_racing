"""Independent source/feature/coefficient/prediction replay of v2 artifacts."""
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('v2_check', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)
    audit = RUN.check_inputs()
    summary = json.loads((OUT / 'summary.json').read_text())
    c = RUN.cfg()
    for name, digest in summary['result_hashes'].items():
        check('result hash ' + name, RUN.BASE.sha(OUT / name) == digest)
    check('production unchanged', not summary['production_changed'] and not summary['final_finish_model_changed'])
    raw = pd.read_parquet(OUT / 'raw_features.parquet')
    moist = pd.read_parquet(OUT / 'moisture_features.parquet')
    old = pd.read_parquet(RUN.PACE_PATH / 'outputs/features.parquet')
    pd.testing.assert_frame_equal(raw[old.columns], old)
    check('all original v1 inputs preserved', True)
    pd.testing.assert_frame_equal(raw.drop(columns=RUN.MOISTURE_COLUMNS), moist.drop(columns=RUN.MOISTURE_COLUMNS))
    check('only approved whole-time features replaced', True)
    check('T-2 history cutoff', (raw.history_source_date.isna() | raw.history_source_date.le(raw.race_date - pd.Timedelta(days=2))).all())
    check('2017+ targets', raw.year.ge(2017).all())
    check('gate from full card without scratch renumber', np.allclose(raw.gate_fraction_proxy, (raw.program_no - 1) / (raw.card_max_number - 1)))
    labels = pd.read_parquet(OUT / 'labels.parquet')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    forbidden = {'outcome', 'S1F_rank', 'G3F_rank', 'S1F_fraction', 'G3F_fraction',
                 'moisture', 'band', 'finish_valid', 'tempo_time', 'actual_rank', 'year', 'program_no'}
    for name in ['runner', 'race', 'gate_runner', 'gate_race']:
        check('input whitelist ' + name, not set(contract[name]) & forbidden)
    effects = pd.read_parquet(OUT / 'effects.parquet')
    records = pd.read_parquet(OUT / 'adjusted_records.parquet')
    check('environment source chronology', (effects.environment_trained_through.dropna() < effects.loc[effects.environment_trained_through.notna(), 'year']).all())
    check('coefficient support', (effects.loc[effects.supported, ['band_days', 'dry_days']] >= c['minimum_moisture_reference_days']).all().all())
    check('unsupported coefficient does not alter raw time', effects.loc[~effects.supported, 'correction_seconds'].eq(0).all())
    for meet in c['venues']:
        one = effects[effects.meet.eq(meet)]
        check('allowed distances ' + str(meet), one.loc[one.supported, 'distance_m'].isin(c['moisture_distances'][str(meet)]).all())
        check('adopted sign and rate ' + str(meet), np.allclose(one.loc[one.supported, 'correction_seconds'],
              -c['moisture_rates'][str(meet)] * one.loc[one.supported, 'effect_seconds']))
    check('record time formula', np.allclose(records.finish_valid, records.original_finish_valid + records.correction_seconds, equal_nan=True))
    references = pd.read_csv(OUT / 'record_references.csv')
    check('record normalization is prior-year only', references.trained_through.lt(references.source_year).all())
    # Independently solve one environmental model per venue, with separately built transforms.
    residuals = pd.read_parquet(RUN.ROOT / c['race_residuals'])
    for (meet, year), observed in effects.groupby(['meet', 'year']):
        prior = residuals[residuals.meet.eq(meet) & residuals.part.eq('finish') & residuals.year.lt(year)]
        counts = prior.groupby(['distance_m', 'band']).day_key.nunique()
        expected_band = [int(counts.get((d, b), 0)) if len(prior) >= 100 else 0
                         for d, b in zip(observed.distance_m, observed.band)]
        expected_dry = [int(counts.get((d, '건조'), 0)) if len(prior) >= 100 else 0
                        for d in observed.distance_m]
        check('independent support day counts ' + str((meet, year)),
              np.array_equal(expected_band, observed.band_days) and np.array_equal(expected_dry, observed.dry_days))
    for row in records[records.finish_valid.notna()].sample(100, random_state=c['seed']).itertuples():
        past = records[(records.meet == row.meet) & (records.result_distance == row.result_distance)
                       & records.year.lt(row.year)].finish_valid.dropna().to_numpy(float)
        if len(past) < 50:
            expected = np.nan
        else:
            center = np.median(past)
            scale = max(.5, 1.4826 * np.median(abs(past - center)))
            expected = np.clip((center - row.finish_valid) / scale, -10, 10)
        check('independent prior record index ' + row.race_key + '/' + row.horse_id,
              np.isclose(expected, row.record_index, equal_nan=True))
    for meet in c['venues']:
        train = residuals[residuals.meet.eq(meet) & residuals.part.eq('finish') & residuals.year.lt(2026)].copy()
        actual = effects[effects.meet.eq(meet) & effects.year.eq(2026) & effects.band.notna()].copy()
        train['distance_band'] = train.distance_m.astype(str) + ':' + train.band.astype(str)
        actual['month'] = actual.race_date.dt.month
        actual['distance_band'] = actual.distance_m.astype(str) + ':' + actual.band.astype(str)
        dry = actual.assign(band='건조')
        dry['distance_band'] = dry.distance_m.astype(str) + ':건조'
        cats = ['distance_m', 'month', 'band', 'distance_band']
        prep = ColumnTransformer([('categories', OneHotEncoder(handle_unknown='ignore'), cats),
                                  ('numbers', StandardScaler(), ['year', 'race_no'])])
        model = Pipeline([('preprocess', prep), ('fit', Ridge(alpha=25))])
        model.fit(train, train.residual)
        diff = model.predict(actual) - model.predict(dry)
        check('independent environmental effects ' + str(meet), np.max(abs(diff - actual.effect_seconds)) < 1e-9)
    predictions = pd.read_parquet(OUT / 'runner_predictions.parquet')
    metrics = pd.read_csv(OUT / 'point_metrics.csv')
    check('prediction uniqueness', not predictions.duplicated(RUN.KEY + ['point', 'variant']).any())
    errors = predictions.assign(error=abs(predictions.expected_position - predictions.actual_rank))
    errors = errors.groupby(['race_key', 'point', 'variant']).error.mean().rename('replayed_error').reset_index()
    paired = metrics.merge(errors, on=['race_key', 'point', 'variant'], validate='one_to_one')
    check('all race position MAEs independently aggregated', len(paired) == len(metrics)
          and np.max(abs(paired.position_mae - paired.replayed_error)) < 1e-10)
    grouped = metrics.groupby(['meet', 'point', 'variant']).position_mae.agg(['size', 'mean'])
    report_metrics = pd.read_csv(OUT / 'metrics.csv')
    for row in report_metrics[report_metrics.period.eq('all')].itertuples():
        actual = grouped.loc[(row.meet, row.point, row.variant)]
        check('aggregate metrics ' + str((row.meet, row.point, row.variant)),
              int(actual['size']) == row.races and abs(actual['mean'] - row.position_mae) < 1e-10)
    frame = raw.merge(labels, on=RUN.KEY, validate='one_to_one')
    for point in c['points']:
        target = frame[frame.year.isin(c['evaluation_years']) & frame[point + '_complete']]
        expected = set(zip(target.race_key, target.horse_id))
        for variant in c['variants']:
            p = predictions[predictions.point.eq(point) & predictions.variant.eq(variant)]
            check('identical cohort ' + point + '/' + variant, set(zip(p.race_key, p.horse_id)) == expected)
            check('probability sums ' + point + '/' + variant, np.max(abs(p.groupby('race_key')[['prob_lead', 'prob_front3']].sum().to_numpy() - [1, 3])) < 1e-10)
    inherited = pd.read_parquet(RUN.PACE_PATH / 'outputs/runner_predictions.parquet')
    inherited = inherited[inherited.variant.eq('field_model')].assign(variant='raw').reset_index(drop=True)
    pd.testing.assert_frame_equal(inherited, predictions[predictions.variant.eq('raw')].reset_index(drop=True))
    check('baseline predictions exact reuse', True)
    rf = pd.read_parquet(OUT / 'race_features.parquet').merge(pd.read_parquet(OUT / 'race_labels.parquet'), on='race_key', validate='one_to_one')
    tp = pd.read_csv(OUT / 'tempo_predictions.csv')
    for a, b in [('raw', 'moisture'), ('gate', 'both')]:
        left = tp[tp.variant.eq(a)].drop(columns='variant').sort_values('race_key').reset_index(drop=True)
        right = tp[tp.variant.eq(b)].drop(columns='variant').sort_values('race_key').reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)
        check('tempo shared branch ' + a + '/' + b, True)
    frames = {'raw': frame, 'moisture': moist.merge(labels, on=RUN.KEY, validate='one_to_one')}
    max_error = 0.
    for bundle in summary['models']:
        dest = OUT / 'models' / f"{bundle['meet']}_{bundle['year']}_{bundle['variant']}"
        for meta in bundle['models']:
            name = dest.name + '/' + meta['file']
            check('model hash ' + name, RUN.BASE.sha(dest / meta['file']) == meta['sha256'])
            check('model chronology ' + name, meta['training_year_end'] < meta['calibration_year'] < meta['evaluation_year'])
            point = meta['file'].split('.')[0]
            f = rf if point == 'tempo' else frames['moisture' if bundle['variant'] in ['moisture', 'both'] else 'raw']
            complete = f.tempo_complete if point == 'tempo' else f[point + '_complete']
            key = f[f.meet.eq(bundle['meet']) & f.year.eq(bundle['year']) & complete].race_key.drop_duplicates().sample(1, random_state=c['seed']).iloc[0]
            one = f[f.race_key.eq(key)]
            if point != 'tempo':
                one = one.sort_values('program_no')
            x = one[meta['columns']].copy()
            for col, vocab in meta['vocabulary'].items():
                x[col] = pd.Categorical(x[col], categories=vocab)
            pred = lgb.Booster(model_file=str(dest / meta['file'])).predict(x)
            if point == 'tempo':
                saved = tp[tp.race_key.eq(key) & tp.variant.eq('gate')].iloc[0]
                err = abs(pred[0] + bundle['tempo']['bias'] - saved.predicted_time)
            else:
                saved = predictions[predictions.race_key.eq(key) & predictions.point.eq(point) & predictions.variant.eq(bundle['variant'])].sort_values('program_no')
                err = np.max(abs(pred - saved.predicted_fraction.to_numpy()))
                logits = -pred / bundle['point_temperatures'][point][0]
                lead = np.exp(logits - logsumexp(logits))
                check('independent lead replay ' + name, np.max(abs(lead - saved.prob_lead.to_numpy())) < 1e-10)
                error = np.mean(abs(1 + np.clip(pred, 0, 1) * (len(one) - 1) - one[point + '_rank']))
                observed = metrics[metrics.race_key.eq(key) & metrics.point.eq(point) & metrics.variant.eq(bundle['variant'])].iloc[0]
                check('independent position MAE ' + name, abs(error - observed.position_mae) < 1e-10)
            max_error = max(max_error, float(err))
            check('regressor replay ' + name, err < 1e-10)
    RUN.check_inputs()
    result = {'passed': len(checks), 'failed': 0, 'max_replay_error': max_error, 'checks': checks,
              'verify_sha256': RUN.BASE.sha(__file__), 'production_changed': False}
    RUN.BASE.save_json(OUT / 'verification.json', result)
    print(json.dumps({'passed': len(checks), 'failed': 0, 'max_replay_error': max_error}), flush=True)


if __name__ == '__main__':
    main()
