"""Chronological jockey, start consistency and field-pressure pace ablation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
V2_PATH = HERE.parent / '20261003_pace_gate_moisture_v2'
# Fixed local source, no caller-controlled imports.
import importlib.util
SPEC = importlib.util.spec_from_file_location('v3_parent', V2_PATH / 'run.py')
V2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V2)
PACE, BASE, KEY = V2.PACE, V2.BASE, V2.KEY


def cfg():
    return json.loads((HERE / 'config.json').read_text())


def read_jockey(db):
    with duckdb.connect(str(db), read_only=True) as conn:
        f = conn.execute("""
          SELECT cast(source_meet as int) meet,
            strptime(result_date,'%Y%m%d')::DATE race_date,
            cast(result_race_no as int) race_no,
            cast(horse_program_no_raw as int) program_no,
            horse_id_raw horse_id,jockey_id_raw jockey_id,jockey_name_raw jockey_name
          FROM confirmed_runners WHERE source_meet IN ('1','3')
           AND (try_cast(result_rank_raw as int) BETWEEN 1 AND 20 OR try_cast(result_rank_raw as int) IN (91,92))
        """).fetchdf()
    f['race_date'] = pd.to_datetime(f.race_date)
    f['race_key'] = f.meet.astype(str) + ':' + f.race_date.dt.strftime('%Y%m%d') + ':' + f.race_no.astype(str)
    if f.duplicated(KEY).any() or f.jockey_id.isna().any() or f.jockey_id.eq('').any():
        raise ValueError('Unusable jockey identity')
    return f


def ridge_design(f, columns, train):
    cats = ['previous_sex', 'grade_kind']
    nums = [col for col in columns if col not in cats]
    numeric = f[nums].apply(pd.to_numeric, errors='raise').astype(float)
    center = numeric[train].median().fillna(0)
    numeric = numeric.fillna(center)
    mean, scale = numeric[train].mean(), numeric[train].std(ddof=0)
    scale = scale.where(scale.gt(1e-8), 1.)
    numeric = (numeric - mean) / scale
    chunks = [numeric.to_numpy(float)]
    vocab = {}
    names = list(nums)
    for col in cats:
        values = f[col].fillna('__missing').astype(str)
        vocab[col] = sorted(values[train].unique().tolist())
        for value in vocab[col]:
            chunks.append(values.eq(value).to_numpy(float)[:, None])
            names.append(col + '=' + value)
    return np.concatenate(chunks, axis=1), {'numeric': nums, 'median': center.tolist(),
        'mean': mean.tolist(), 'scale': scale.tolist(), 'vocabulary': vocab, 'names': names}


def external_expectations(f, contract, c):
    predictions, fits = [], []
    columns = contract['runner'] + contract['gate_runner']
    for meet in c['venues']:
        one = f[f.meet.eq(meet)].reset_index(drop=True)
        for year in range(c['expectation_start_year'], int(one.year.max()) + 1):
            prior = one.year.between(c['training_start_year'], year - 1)
            train = prior & one.S1F_complete
            test = one.year.eq(year)
            if train.sum() < 100 or not test.any():
                continue
            x, transform = ridge_design(one, columns, train)
            result = one.loc[test, KEY + ['meet', 'race_date', 'year', 'S1F_fraction', 'advance']].copy()
            info = {'meet': meet, 'source_year': year, 'training_end': year - 1,
                    'transform': transform, 'heads': []}
            for target, name, lo, hi in [('S1F_fraction', 'expected_early', 0, 1), ('advance', 'expected_advance', -1, 1)]:
                available = train & one[target].notna()
                model = Ridge(alpha=c['expectation_alpha'])
                model.fit(x[available], one.loc[available, target], sample_weight=1 / one.loc[available, 'field_size'])
                result[name] = np.clip(model.predict(x[test]), lo, hi)
                info['heads'].append({'target': target, 'rows': int(available.sum()),
                    'coefficient': model.coef_.tolist(), 'intercept': float(model.intercept_)})
            result['early_residual'] = result.expected_early - result.S1F_fraction
            result['advance_residual'] = result.advance - result.expected_advance
            result['expectation_training_end'] = year - 1
            predictions.append(result)
            fits.append(info)
            print(f'External expectations meet={meet} year={year}', flush=True)
    return pd.concat(predictions, ignore_index=True), fits


def lookup(query, states, by, shift_days=0):
    q = query[by + ['race_date']].copy()
    q['_row'] = np.arange(len(q))
    q['_query_date'] = q.race_date - pd.Timedelta(days=shift_days)
    q = q.drop(columns='race_date')
    result = pd.merge_asof(q.sort_values('_query_date'), states.sort_values('available_date'),
        left_on='_query_date', right_on='available_date', by=by, direction='backward')
    return result.sort_values('_row').reset_index(drop=True)


def daily_states(h, by, lag):
    d = h.copy()
    d['rides'] = 1
    measures = {'early': d.early_residual, 'advance': d.advance_residual,
                'outer': d.early_residual.where(d.gate_outer_proxy.eq(1)),
                'short': d.early_residual.where(d.distance_m.le(1400)),
                'route': d.early_residual.where(d.distance_m.gt(1400))}
    agg = {'rides': 'sum'}
    for name, values in measures.items():
        d[name + '_sum'] = values.fillna(0)
        d[name + '_count'] = values.notna().astype(int)
        agg[name + '_sum'] = 'sum'; agg[name + '_count'] = 'sum'
    daily = d.groupby(by + ['race_date'], sort=True).agg(agg).reset_index()
    columns = list(agg)
    daily[columns] = daily.groupby(by, sort=False)[columns].cumsum()
    daily['source_date'] = daily.race_date
    daily['available_date'] = daily.race_date + pd.Timedelta(days=lag)
    return daily.drop(columns='race_date')


def add_jockey(frame, h, c):
    f = frame.copy()
    previous = h[['horse_id', 'race_date', 'jockey_id']].rename(columns={'jockey_id': 'previous_jockey_id', 'race_date': 'source_date'})
    previous['available_date'] = previous.source_date + pd.Timedelta(days=c['history_lag_days'])
    prev = lookup(f, previous, ['horse_id'])
    f['previous_jockey_id'] = prev.previous_jockey_id
    f['previous_jockey_source_date'] = prev.source_date
    f['jockey_changed'] = f.jockey_id.ne(f.previous_jockey_id).astype(float).where(f.previous_jockey_id.notna())
    states = daily_states(h, ['meet', 'jockey_id'], c['history_lag_days'])
    current = lookup(f, states, ['meet', 'jockey_id'])
    lower = lookup(f, states, ['meet', 'jockey_id'], c['jockey_recent_days'] - c['history_lag_days'])
    cols = ['jockey_changed', 'jockey_history_count', 'jockey_early_count', 'jockey_aggression',
            'jockey_recent_count', 'jockey_recent_aggression', 'jockey_outer_count', 'jockey_outer_aggression',
            'jockey_distance_count', 'jockey_distance_aggression', 'jockey_advance_count', 'jockey_advance_residual',
            'pair_history_count', 'pair_early_count', 'pair_aggression', 'jockey_switch_aggression_difference',
            'jockey_switch_prior_count', 'jockey_gate_interaction', 'jockey_horse_style_interaction', 'jockey_relative_aggression']
    current = current.fillna({name: 0 for name in current if name.endswith(('_count', '_sum')) or name == 'rides'})
    f['jockey_trait_source_date'] = current.source_date
    prior = c['jockey_prior_observations']
    f['jockey_history_count'] = current.rides
    f['jockey_early_count'] = current.early_count
    f['jockey_aggression'] = current.early_sum / (current.early_count + prior)
    recent_count = current.early_count - lower.early_count.fillna(0)
    f['jockey_recent_count'] = recent_count
    f['jockey_recent_aggression'] = (current.early_sum - lower.early_sum.fillna(0)) / (recent_count + prior)
    for measure, stem in [('outer', 'outer'), ('advance', 'advance')]:
        f['jockey_' + stem + '_count'] = current[measure + '_count']
        f['jockey_' + stem + ('_residual' if stem == 'advance' else '_aggression')] = current[measure + '_sum'] / (current[measure + '_count'] + prior)
    count = np.where(f.distance_m.le(1400), current.short_count, current.route_count)
    total = np.where(f.distance_m.le(1400), current.short_sum, current.route_sum)
    f['jockey_distance_count'], f['jockey_distance_aggression'] = count, total / (count + prior)
    pair_states = daily_states(h, ['meet', 'horse_id', 'jockey_id'], c['history_lag_days'])
    pair = lookup(f, pair_states, ['meet', 'horse_id', 'jockey_id'])
    f['pair_trait_source_date'] = pair.source_date
    f['pair_history_count'], f['pair_early_count'] = pair.rides.fillna(0), pair.early_count.fillna(0)
    f['pair_aggression'] = pair.early_sum.fillna(0) / (f.pair_early_count + c['pair_prior_observations'])
    query = f.copy()
    query['jockey_id'] = query.previous_jockey_id.fillna('__unknown')
    former = lookup(query, states, ['meet', 'jockey_id'])
    f['jockey_switch_prior_count'] = former.early_count.fillna(0)
    previous_trait = former.early_sum.fillna(0) / (former.early_count.fillna(0) + prior)
    f['jockey_switch_aggression_difference'] = (f.jockey_aggression - previous_trait).where(f.previous_jockey_id.notna())
    f['jockey_gate_interaction'] = f.jockey_aggression * f.gate_fraction_proxy
    f['jockey_horse_style_interaction'] = f.jockey_aggression * f.pace_last3_S1F_fraction
    f['jockey_relative_aggression'] = f.jockey_aggression - f.groupby('race_key').jockey_aggression.transform('mean')
    return f, cols, states, pair_states


def add_stability(frame, h, c):
    h = h.sort_values(['horse_id', 'race_date']).copy()
    g = h.groupby('horse_id', sort=False)
    past_mean = g.historical_start_time.transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
    # Times have millisecond resolution; tolerate sub-nanosecond float roundoff
    # so an exact0.4s difference is not accidentally classified as >0.4s.
    h['slow_start'] = (h.historical_start_time - past_mean).gt(c['slow_start_seconds'] + 1e-9).astype(float).where(h.historical_start_time.notna() & past_mean.notna())
    g = h.groupby('horse_id', sort=False)
    states = h[['horse_id', 'race_date']].rename(columns={'race_date': 'source_date'})
    cols = []
    for measure, name, k in [('S1F_fraction', 'stability_last5_position_std', 5),
                              ('S1F_fraction', 'stability_last10_position_std', 10),
                              ('historical_start_time', 'stability_last10_time_std', 10)]:
        states[name] = g[measure].rolling(k, min_periods=2).std().reset_index(level=0, drop=True)
        cols.append(name)
    for stat in ['min', 'max', 'count']:
        name = 'stability_last10_time_' + stat
        states[name] = getattr(g.historical_start_time.rolling(10, min_periods=1), stat)().reset_index(level=0, drop=True)
        cols.append(name)
    states['stability_last10_time_range'] = states.stability_last10_time_max - states.stability_last10_time_min
    states['stability_last10_slow_rate'] = g.slow_start.rolling(10, min_periods=1).mean().reset_index(level=0, drop=True)
    states['stability_last10_slow_count'] = g.slow_start.rolling(10, min_periods=1).count().reset_index(level=0, drop=True)
    cols += ['stability_last10_time_range', 'stability_last10_slow_rate', 'stability_last10_slow_count']
    states['available_date'] = states.source_date + pd.Timedelta(days=c['history_lag_days'])
    value = lookup(frame, states, ['horse_id'])
    f = frame.copy()
    for col in cols:
        f[col] = value[col]
    f['stability_source_date'] = value.source_date
    return f, cols


def add_competition(frame, c):
    f = frame.copy()
    cols = ['competition_faster_inner', 'competition_close_inner', 'competition_faster_outer',
            'competition_near_gate_leaders', 'competition_inner_forward', 'competition_outer_forward',
            'competition_fastest_gap', 'competition_fast3_std']
    values = np.full((len(f), len(cols)), np.nan)
    for _, idx in f.groupby('race_key', sort=False).indices.items():
        one = f.iloc[idx]
        time = one.pace_last3_historical_start_time.to_numpy(float)
        gate = one.gate_number_proxy.to_numpy(float)
        forward = one.pace_last3_S1F_front.ge(.5).to_numpy()
        habitual = one.pace_last5_S1F_lead.ge(.25).to_numpy()
        diff = time[None, :] - time[:, None]
        inner = gate[None, :] < gate[:, None]
        outer = gate[None, :] > gate[:, None]
        known = np.isfinite(time)
        values[idx, 0] = np.where(known, ((diff < -c['competition_time_margin_seconds']) & inner).sum(axis=1), np.nan)
        values[idx, 1] = np.where(known, ((abs(diff) <= c['competition_time_margin_seconds']) & inner).sum(axis=1), np.nan)
        values[idx, 2] = np.where(known, ((diff < -c['competition_time_margin_seconds']) & outer).sum(axis=1), np.nan)
        near = (abs(gate[None, :] - gate[:, None]) <= 2) & (gate[None, :] != gate[:, None])
        values[idx, 3] = (near & habitual[None, :]).sum(axis=1)
        values[idx, 4], values[idx, 5] = (inner & forward[None, :]).sum(axis=1), (outer & forward[None, :]).sum(axis=1)
        fastest = np.sort(time[known])[:3]
        values[idx, 6] = fastest[1] - fastest[0] if len(fastest) >= 2 else np.nan
        values[idx, 7] = np.std(fastest) if len(fastest) >= 3 else np.nan
    f[cols] = values
    return f, cols


def race_extra(frame, base_race):
    group = frame.groupby('race_key', sort=False)
    choices = {'jockey': ['jockey_aggression', 'jockey_recent_aggression', 'jockey_distance_aggression',
                           'jockey_advance_residual', 'jockey_changed', 'pair_early_count'],
               'stability': ['stability_last10_time_std', 'stability_last10_slow_rate', 'stability_last5_position_std'],
               'competition': ['competition_close_inner', 'competition_near_gate_leaders', 'competition_fastest_gap', 'competition_fast3_std']}
    r = base_race.set_index('race_key').copy()
    contract = {}
    for kind, features in choices.items():
        contract[kind] = []
        for col in features:
            for stat in ['mean', 'max', 'std']:
                name = 'field_' + col + '_' + stat
                r[name] = getattr(group[col], stat)()
                contract[kind].append(name)
    return r.reset_index(), contract


def inputs(c):
    return [ROOT / c['source_db'], ROOT / 'config/prediction_model_registry.json',
        HERE / 'run.py', HERE / 'config.json', HERE / 'PLAN.md', V2_PATH / 'run.py',
        V2.PACE_PATH / 'run.py', PACE.BASE_PATH / 'run.py',
        *[V2_PATH / 'outputs' / n for n in ['raw_features.parquet', 'labels.parquet', 'feature_contract.json',
          'race_features.parquet', 'race_labels.parquet', 'runner_predictions.parquet', 'point_metrics.csv', 'tempo_predictions.csv']]]


def prepare():
    c = cfg()
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite output directory')
    hashes = {str(p.relative_to(ROOT)): BASE.sha(p) for p in inputs(c)}
    V2.check_inputs()
    OUT.mkdir()
    f = pd.read_parquet(V2_PATH / 'outputs/raw_features.parquet')
    labels = pd.read_parquet(V2_PATH / 'outputs/labels.parquet')
    contract = json.loads((V2_PATH / 'outputs/feature_contract.json').read_text())
    labeled = f.merge(labels, on=KEY, validate='one_to_one')
    labeled['advance'] = labeled.S1F_fraction - labeled.G3F_fraction
    expectations, fits = external_expectations(labeled, contract, c)
    h = PACE.read_points(ROOT / c['source_db'])
    jockey = read_jockey(ROOT / c['source_db'])
    h = h.merge(jockey[KEY + ['jockey_id']], on=KEY, validate='one_to_one')
    context = V2.read_context(ROOT / c['source_db'])
    h = h.merge(context[['race_key', 'card_max_number']], on='race_key', validate='many_to_one')
    h['gate_outer_proxy'] = ((h.program_no - 1) / (h.card_max_number - 1)).ge(2 / 3).astype(float)
    distance = f[['race_key', 'distance_m']].drop_duplicates('race_key')
    # Warm-up distance only distinguishes context of residuals, which start2018.
    h = h.merge(distance, on='race_key', how='left', validate='many_to_one')
    h = h.merge(expectations[KEY + ['early_residual', 'advance_residual', 'expectation_training_end']], on=KEY, how='left', validate='one_to_one')
    f = f.merge(jockey[KEY + ['jockey_id', 'jockey_name']], on=KEY, validate='one_to_one')
    f, jcols, states, pairs = add_jockey(f, h, c)
    f, scols = add_stability(f, h, c)
    f, ccols = add_competition(f, c)
    race, race_groups = race_extra(f, pd.read_parquet(V2_PATH / 'outputs/race_features.parquet'))
    groups = {'jockey': jcols, 'stability': scols, 'competition': ccols}
    for name, table in [('features', f), ('labels', labels), ('race_features', race),
        ('race_labels', pd.read_parquet(V2_PATH / 'outputs/race_labels.parquet')),
        ('external_expectations', expectations), ('history', h), ('jockey_states', states), ('pair_states', pairs)]:
        table.to_parquet(OUT / (name + '.parquet'), index=False)
    BASE.save_json(OUT / 'expectation_models.json', fits)
    BASE.save_json(OUT / 'feature_contract.json', {'runner': contract['runner'] + contract['gate_runner'],
        'race': contract['race'] + contract['gate_race'], 'groups': groups, 'race_groups': race_groups})
    f.groupby(['meet', 'year']).agg(runners=('horse_id', 'size'),
        jockey_residual_known=('jockey_early_count', lambda x: int(x.gt(0).sum())),
        paired_residual_known=('pair_early_count', lambda x: int(x.gt(0).sum())),
        switched=('jockey_changed', 'sum'), prior_jockey_unknown=('previous_jockey_id', lambda x: int(x.isna().sum()))).to_csv(OUT / 'coverage.csv')
    for col in ['previous_jockey_source_date', 'jockey_trait_source_date', 'pair_trait_source_date', 'stability_source_date']:
        if not (f[col].isna() | f[col].le(f.race_date - pd.Timedelta(days=c['history_lag_days']))).all():
            raise ValueError('Historical cutoff failure ' + col)
    audit = {'inputs': hashes, 'runners': len(f), 'races': int(f.race_key.nunique()),
        'source_db': str(ROOT / c['source_db']), 'production_changed': False,
        'prepared_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}}
    BASE.save_json(OUT / 'data_audit.json', audit)
    print(json.dumps({'runners': len(f), 'races': audit['races'], 'expectation_models': len(fits)}), flush=True)


def check_inputs():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    for name, digest in audit['inputs'].items():
        if BASE.sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    for name, digest in audit['prepared_hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Prepared data changed: ' + name)
    return audit


def train():
    c = cfg(); check_inputs()
    if (OUT / 'summary.json').exists():
        raise FileExistsError('Completed experiment already exists')
    (OUT / 'models').mkdir(exist_ok=True)
    f = pd.read_parquet(OUT / 'features.parquet').merge(pd.read_parquet(OUT / 'labels.parquet'), on=KEY, validate='one_to_one')
    r = pd.read_parquet(OUT / 'race_features.parquet').merge(pd.read_parquet(OUT / 'race_labels.parquet'), on='race_key', validate='one_to_one')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    def inherit(name):
        frame = pd.read_parquet(V2_PATH / 'outputs' / name) if name.endswith('.parquet') else pd.read_csv(V2_PATH / 'outputs' / name)
        return frame[frame.variant.eq('gate')]
    runners, metrics, tempos = [inherit('runner_predictions.parquet')], [inherit('point_metrics.csv')], [inherit('tempo_predictions.csv')]
    bundles = []
    for meet in c['venues']:
        one, races = f[f.meet.eq(meet)].reset_index(drop=True), r[r.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            for variant in c['variants'][1:]:
                dest = OUT / 'models' / f'{meet}_{year}_{variant}'
                complete = dest / 'metadata.json'
                if complete.exists():
                    bundle = json.loads(complete.read_text())
                    for name, digest in bundle['artifact_hashes'].items():
                        if BASE.sha(dest / name) != digest:
                            raise ValueError('Completed bundle changed')
                else:
                    if dest.exists() and any(dest.iterdir()):
                        raise FileExistsError('Incomplete bundle needs explicit recovery: ' + str(dest))
                    dest.mkdir(exist_ok=True)
                    groups = list(contract['groups']) if variant == 'all' else [variant]
                    cols = contract['runner'] + [col for group in groups for col in contract['groups'][group]]
                    rcols = contract['race'] + [col for group in groups for col in contract['race_groups'][group]]
                    bundle = {'meet': meet, 'year': year, 'variant': variant, 'models': [], 'point_temperatures': {}}
                    print(f'Training meet={meet} year={year} variant={variant}', flush=True)
                    arows, brows = [], []
                    for point in c['points']:
                        pred, meta = PACE.fit_regression(one, cols, point + '_fraction', one[point + '_complete'], year, c, dest / (point + '.txt'), race_weight=True)
                        a, b, t = PACE.point_evaluation(one, point, pred, year, variant, c)
                        arows.extend(a); brows.extend(b)
                        bundle['models'].append(meta); bundle['point_temperatures'][point] = t
                    pred, meta = PACE.fit_regression(races, rcols, 'tempo_time', races.tempo_complete, year, c, dest / 'tempo.txt')
                    rows, calibration = PACE.tempo_evaluation(races, pred, year, variant, c)
                    bundle['models'].append(meta); bundle['tempo'] = calibration
                    pd.DataFrame(arows).to_parquet(dest / 'runners.parquet', index=False)
                    pd.DataFrame(brows).to_csv(dest / 'points.csv', index=False)
                    pd.DataFrame(rows).to_csv(dest / 'tempo.csv', index=False)
                    bundle['artifact_hashes'] = {p.name: BASE.sha(p) for p in dest.iterdir() if p.is_file()}
                    BASE.save_json(complete, bundle)
                    print(f'Evaluated meet={meet} year={year} variant={variant}', flush=True)
                runners.append(pd.read_parquet(dest / 'runners.parquet'))
                metrics.append(pd.read_csv(dest / 'points.csv')); tempos.append(pd.read_csv(dest / 'tempo.csv'))
                bundles.append(bundle)
    rp, rm, tp = pd.concat(runners, ignore_index=True), pd.concat(metrics, ignore_index=True), pd.concat(tempos, ignore_index=True)
    rp.to_parquet(OUT / 'runner_predictions.parquet', index=False)
    rm.to_csv(OUT / 'point_metrics.csv', index=False); tp.to_csv(OUT / 'tempo_predictions.csv', index=False)
    metric_names = ['fraction_mae', 'position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier', 'leader_nll', 'ordered_top3_nll']
    rows = []
    for (meet, point, variant), one in rm.groupby(['meet', 'point', 'variant']):
        for period, sample in [('all', one), *[(str(y), group) for y, group in one.groupby('year')]]:
            rows.append({'meet': int(meet), 'point': point, 'variant': variant, 'period': period,
                         'races': len(sample), **{m: float(sample[m].mean()) for m in metric_names}})
    s = pd.DataFrame(rows); s.to_csv(OUT / 'metrics.csv', index=False)
    ts = tp.groupby(['meet', 'year', 'variant']).agg(races=('race_key', 'size'),
        time_mae=('absolute_error', 'mean'), class_hit=('class_hit', 'mean'), classified_races=('class_hit', 'count')).reset_index()
    ts.to_csv(OUT / 'tempo_metrics.csv', index=False)
    paired = differences(rm, c)
    BASE.save_json(OUT / 'paired_differences.json', paired)
    sensitivity(rp, f)
    report(s, ts, paired)
    BASE.save_json(OUT / 'summary.json', {'experiment': c['experiment'], 'models': bundles,
        'metrics': s.to_dict('records'), 'tempo_metrics': ts.to_dict('records'),
        'production_changed': False, 'final_finish_model_changed': False,
        'result_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}})
    print('Completed ' + str(OUT / 'REPORT.md'), flush=True)


def differences(rm, c):
    rng, rows = np.random.default_rng(c['seed']), []
    comparisons = [('gate', v) for v in c['variants'][1:]] + [('jockey', 'all')]
    for (meet, point), one in rm.groupby(['meet', 'point']):
        for base, variant in comparisons:
            pair = one[one.variant.eq(base)].merge(one[one.variant.eq(variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
            for metric in ['fraction_mae', 'position_mae', 'leader_hit', 'top3_brier']:
                delta = pair[metric + '_new'] - pair[metric + '_base']
                groups = pd.DataFrame({'day': pair.race_date_base, 'd': delta}).groupby('day').d.agg(['sum', 'size']).to_numpy()
                sample = groups[rng.integers(0, len(groups), (c['bootstrap_draws'], len(groups)))]
                bounds = np.quantile(sample[:, :, 0].sum(axis=1) / sample[:, :, 1].sum(axis=1), [.025, .975])
                rows.append({'meet': int(meet), 'point': point, 'base': base, 'variant': variant, 'metric': metric,
                             'delta': float(delta.mean()), 'ci95': bounds.tolist(), 'races': len(pair)})
    return rows


def sensitivity(predictions, frame):
    context = frame[KEY + ['jockey_changed', 'history_count', 'gate_zone_proxy', 'distance_m']].copy()
    context['experience'] = np.where(context.history_count.eq(0), 'zero', np.where(context.history_count.lt(5), 'one_to_four', 'five_plus'))
    context['jockey_status'] = np.where(context.jockey_changed.isna(), 'unknown', np.where(context.jockey_changed.eq(1), 'changed', 'same'))
    p = predictions.merge(context, on=KEY, validate='many_to_one')
    p['position_error'] = abs(p.expected_position - p.actual_rank)
    for name in ['experience', 'jockey_status', 'gate_zone_proxy', 'distance_m']:
        p.groupby(['meet', 'point', 'variant', 'year', name]).agg(runners=('horse_id', 'size'),
            position_mae=('position_error', 'mean')).to_csv(OUT / (name + '_sensitivity.csv'))


def report(s, ts, paired):
    names = {'gate': '게이트 v2', 'jockey': '+기수', 'stability': '+초반 안정성', 'competition': '+게이트별 경쟁', 'all': '+전체'}
    lines = ['# 전개 v3 — 기수 성향·초반 안정성·게이트별 경쟁', '',
        '동일 경주·정답·분할의 후향 비교. 2010–2016 이력 준비, 학습2017+, 평가2024–2026 보존자료. 기수는 결과표의 현재 기수 대리값이며 사전 공개 시점을 확인한 실시간 예측이 아니다.', '',
        '| 장소 | 지점 | 후보 | 경주 | 순위 MAE ↓ | 통과1위 | 상위3두 | Brier ↓ |', '|---|---|---|---:|---:|---:|---:|---:|']
    for row in s[s.period.eq('all')].itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.point} | {names[row.variant]} | {row.races:,} | {row.position_mae:.4f}두 | {row.leader_hit:.2%} | {row.top3_exact_hit:.2%} | {row.top3_brier:.5f} |')
    lines += ['', '## 동일 경주 차이', '', '변경−기준. 오차는 음수, 적중은 양수가 개선. 날짜 구간은 다중비교·계수오차·장기 날짜 의존성을 완전히 반영하지 않는다.', '',
        '| 장소 | 지점 | 비교 | 지표 | 차이 | 95% 구간 |', '|---|---|---|---|---:|---|']
    for d in paired:
        if d['metric'] not in ['position_mae', 'leader_hit']:
            continue
        lo, hi = d['ci95']
        lines.append(f'| { {1:"서울",3:"부산"}[d["meet"]]} | {d["point"]} | {names[d["variant"]]}−{names[d["base"]]} | {d["metric"]} | {d["delta"]:+.5f} | {lo:+.5f}~{hi:+.5f} |')
    lines += ['', '## 초반시간', '', '| 장소 | 연도 | 후보 | 시간 MAE | 분류 적중 |', '|---|---:|---|---:|---:|']
    for row in ts.itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.year} | {names[row.variant]} | {row.time_mae:.4f}초 | {row.class_hit:.2%} |')
    lines += ['', '## 해석 범위', '',
        '기수의 초반 적극성은 이전연도 기대모델 대비 앞선 위치의 잔차이며 기수 전체30·말×기수10 관측만큼0으로 완화한다. 신규 조합은 값0과 관측 수를 함께 입력한다. 최근값은 현재일 이전180일 중 T−2까지의 관측이다. 당일 앞 경주도 제외한다. 인과효과나 기수 의도를 확정한 값이 아니다.', '',
        '초반시간 표준편차·느린 초반시간 비율에는 환경·편성 변화가 섞인다. 출발사고를 직접 측정하지 않았다. 경쟁 피처는 과거 성향과 게이트 배치 대리변수이며 실제 경합 정답을 사용하지 않았다.', '',
        '이번 연구는 최종 착순·삼복승 적중 개선을 측정하지 않는다. 주행심사·당일 부담중량·횡방향 위치는 별도 후보로 남긴다. 원천 DB·v1/v2·운영 등록부는 보존했다. 연도별 metrics.csv, 표본 coverage.csv, 교체/경력/게이트/거리 민감도, verification.json을 함께 확인한다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'train'])
    args = parser.parse_args()
    {'prepare': prepare, 'train': train}[args.mode]()
