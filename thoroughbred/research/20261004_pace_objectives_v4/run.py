"""DB-only, chronological pace objective and trial ablation. No steward data."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logsumexp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PARENT = HERE.parent / '20261003_pace_jockey_v3'
SPEC = importlib.util.spec_from_file_location('pace_v4_parent', PARENT / 'run.py')
V3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V3)
BASE, PACE, KEY = V3.BASE, V3.PACE, V3.KEY


def cfg():
    return json.loads((HERE / 'config.json').read_text())


def json_records(frame):
    # Direct classifiers have no regression-position MAE: encode missing as null.
    return frame.astype(object).where(pd.notna(frame), None).to_dict('records')


def read_trials(db):
    # Both view names and query are fixed local code; original database is read-only.
    with duckdb.connect(str(db), read_only=True) as conn:
        t = conn.execute("""
          SELECT v.participant_row_id, v.trial_session_id,
            try_cast(v.trial_date AS DATE) source_date,
            cast(v.source_meet_query AS INT) source_meet,
            v.physical_venue, v.venue_review_status,
            e.resolved_horse_id horse_id, e.horse_identity_resolution,
            try_cast(v.api_rcTimeS1f AS DOUBLE) s1f_time,
            try_cast(v.api_s1f AS DOUBLE) s1f_rank,
            try_cast(v.api_rcTime AS DOUBLE) completed_time,
            v.api_passFlag pass_flag
          FROM trial_participants_venue_reviewed v
          JOIN trial_participants_entity_reviewed e USING(participant_row_id)
          WHERE v.source_meet_query IN ('1','3')
        """).fetchdf()
    if t.participant_row_id.duplicated().any():
        raise ValueError('Trial identity join duplicates observations')
    t['source_date'] = pd.to_datetime(t.source_date)
    t['meet'] = t.source_meet.astype('int64')
    override = t.physical_venue.notna()
    if not t.loc[override, 'physical_venue'].isin(['서울', '부산경남']).all():
        raise ValueError('Unhandled physical trial venue')
    t.loc[override, 'meet'] = t.loc[override, 'physical_venue'].map({'서울': 1, '부산경남': 3}).astype('int64')
    t['completed'] = t.completed_time.gt(0) & ~t.pass_flag.fillna('').str.contains('취소|제외', regex=True)
    t['identity_ok'] = t.horse_id.notna() & t.horse_id.ne('') & t.horse_identity_resolution.isin(
        ['api_direct', 'crosschecked_link', 'user_confirmed_link'])
    t['usable'] = t.completed & t.identity_ok & t.source_date.notna()
    t['time_valid'] = t.s1f_time.between(10, 30) & t.source_date.ge('2017-01-01')
    t['trial_s1f'] = t.s1f_time.where(t.usable & t.time_valid)
    t['trial_pass'] = t.pass_flag.eq('합격').astype(float).where(t.usable)
    t['trial_fraction'] = np.nan
    t['trial_session_delta'] = np.nan
    for _, idx in t[t.completed].groupby('trial_session_id', sort=False).groups.items():
        one = t.loc[idx]
        n = len(one)
        rank = one.s1f_rank
        if n >= 2 and rank.notna().all() and set(rank) == set(range(1, n + 1)):
            t.loc[idx, 'trial_fraction'] = (rank - 1) / (n - 1)
        times = one.trial_s1f
        if times.notna().sum() >= 3:
            t.loc[idx, 'trial_session_delta'] = times - times.median()
    return t


def add_trials(f, trials, lag):
    h = trials[trials.usable].sort_values(['horse_id', 'meet', 'source_date', 'participant_row_id']).copy()
    # If a horse has multiple trials on one date, retain a deterministic final row
    # for asof history; no same-day event is queried by a race.
    h = h.drop_duplicates(['horse_id', 'meet', 'source_date'], keep='last')
    group = h.groupby(['horse_id', 'meet'], sort=False)
    states = h[['horse_id', 'meet', 'source_date']].copy()
    states['trial_count'] = group.cumcount() + 1
    cols = ['trial_count']
    for source, stem in [('trial_s1f', 'time'), ('trial_fraction', 'fraction'),
                         ('trial_session_delta', 'session_delta'), ('trial_pass', 'pass')]:
        states['trial_previous_' + stem] = h[source]
        states['trial_last3_' + stem] = group[source].rolling(3, min_periods=1).mean().reset_index(level=[0, 1], drop=True)
        states['trial_last3_' + stem + '_count'] = group[source].rolling(3, min_periods=1).count().reset_index(level=[0, 1], drop=True)
        cols += ['trial_previous_' + stem, 'trial_last3_' + stem, 'trial_last3_' + stem + '_count']
    states['available_date'] = states.source_date + pd.Timedelta(days=lag)
    states['meet'] = states.meet.astype(f.meet.dtype)
    states['available_date'] = states.available_date.astype(f.race_date.dtype)
    value = V3.lookup(f, states, ['horse_id', 'meet'])
    out = f.copy()
    for col in cols:
        out[col] = value[col]
    out['trial_source_date'] = value.source_date
    out['trial_count'] = out.trial_count.fillna(0)
    out['trial_days_since'] = (out.race_date - out.trial_source_date).dt.days
    out['trial_time_minus_race'] = out.trial_last3_time - out.pace_last3_historical_start_time
    out['trial_has_time'] = out.trial_last3_time.notna().astype(float)
    cols += ['trial_days_since', 'trial_time_minus_race', 'trial_has_time']
    for col in ['trial_last3_time', 'trial_last3_fraction', 'trial_last3_session_delta']:
        name = 'relative_' + col
        out[name] = out[col] - out.groupby('race_key')[col].transform('mean')
        cols.append(name)
    out['trial_field_unknown_count'] = out.trial_last3_time.isna().groupby(out.race_key).transform('sum')
    cols.append('trial_field_unknown_count')
    return out, cols, h


def add_risk_labels(f, history, c):
    h = history.sort_values(['horse_id', 'race_date']).copy()
    group = h.groupby('horse_id', sort=False)
    # Last three actual starts, without skipping any missing or pre-2017 time.
    previous = group.historical_start_time.transform(lambda s: s.shift(1).rolling(3, min_periods=3).mean())
    known = previous.notna() & h.historical_start_time.notna()
    h['slow_label'] = (h.historical_start_time - previous).gt(c['slow_seconds'] + 1e-9).astype(float).where(known)
    states = h[['horse_id', 'race_date']].rename(columns={'race_date': 'source_date'})
    states['risk_past3_time'] = group.historical_start_time.transform(lambda s: s.rolling(3, min_periods=3).mean())
    group = h.groupby('horse_id', sort=False)
    cols = ['risk_past3_time']
    for n in [5, 10]:
        for stat in ['mean', 'count']:
            col = f'risk_last{n}_slow_{stat}'
            states[col] = getattr(group.slow_label.rolling(n, min_periods=1), stat)().reset_index(level=0, drop=True)
            cols.append(col)
    states['available_date'] = states.source_date + pd.Timedelta(days=c['history_lag_days'])
    value = V3.lookup(f, states, ['horse_id'])
    out = f.copy()
    for col in cols:
        out[col] = value[col]
    out['risk_source_date'] = value.source_date
    current = h[KEY + ['historical_start_time']]
    out = out.merge(current, on=KEY, validate='one_to_one')
    known = out.risk_past3_time.notna() & out.historical_start_time.notna()
    out['slow_label'] = (out.historical_start_time - out.risk_past3_time).gt(c['slow_seconds'] + 1e-9).astype(float).where(known)
    out['risk_eligible'] = known
    return out, cols, h


def prepare():
    c = cfg()
    if OUT.exists():
        raise FileExistsError('Refusing to replace existing experiment')
    V3.check_inputs()
    source = ROOT / c['source_db']
    paths = [source, ROOT / 'config/prediction_model_registry.json', HERE / 'run.py', HERE / 'config.json', HERE / 'PLAN.md',
             PARENT / 'run.py', V3.V2_PATH / 'run.py', V3.V2.PACE_PATH / 'run.py', PACE.BASE_PATH / 'run.py']
    paths += [PARENT / 'outputs' / name for name in ['features.parquet', 'labels.parquet', 'history.parquet',
              'feature_contract.json', 'runner_predictions.parquet', 'point_metrics.csv']]
    hashes = {str(p.relative_to(ROOT)): BASE.sha(p) for p in paths}
    f = pd.read_parquet(PARENT / 'outputs/features.parquet')
    labels = pd.read_parquet(PARENT / 'outputs/labels.parquet')
    contract = json.loads((PARENT / 'outputs/feature_contract.json').read_text())
    trials = read_trials(source)
    f, trial_cols, trial_history = add_trials(f, trials, c['history_lag_days'])
    history = pd.read_parquet(PARENT / 'outputs/history.parquet')
    f, risk_cols, history = add_risk_labels(f, history, c)
    for col in ['trial_source_date', 'risk_source_date']:
        if not (f[col].isna() | f[col].le(f.race_date - pd.Timedelta(days=c['history_lag_days']))).all():
            raise ValueError('T-2 failure ' + col)
    OUT.mkdir()
    for name, data in [('features', f), ('labels', labels), ('trials', trials), ('trial_history', trial_history), ('history', history)]:
        data.to_parquet(OUT / (name + '.parquet'), index=False)
    columns = contract['runner'] + contract['groups']['jockey']
    BASE.save_json(OUT / 'feature_contract.json', {'base': columns, 'trial': trial_cols,
        'risk': risk_cols + contract['groups']['stability'], 'forbidden': ['slow_label', 'historical_start_time', 'S1F_rank', 'G3F_rank']})
    f.groupby(['meet', 'year']).agg(runners=('horse_id', 'size'), trial_known=('trial_count', lambda x: int(x.gt(0).sum())),
        trial_time_known=('trial_has_time', 'sum'), risk_known=('risk_eligible', 'sum')).to_csv(OUT / 'coverage.csv')
    f[f.year.isin(c['evaluation_years'])].assign(experience=lambda d: np.where(d.history_count.eq(0), 'zero',
        np.where(d.history_count.lt(5), 'one_to_four', 'five_plus'))).groupby(['meet', 'experience']).agg(
        runners=('horse_id', 'size'), trial_time_known=('trial_has_time', 'sum')).to_csv(OUT / 'trial_experience_coverage.csv')
    BASE.save_json(OUT / 'data_audit.json', {'inputs': hashes, 'prepared_hashes':
        {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}, 'runners': len(f),
        'trial_rows': len(trials), 'trial_usable': int(trials.usable.sum()), 'production_changed': False})
    print('Prepared runners=' + str(len(f)) + ' trials=' + str(len(trials)), flush=True)


def check_inputs():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    for name, digest in audit['inputs'].items():
        if BASE.sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    for name, digest in audit['prepared_hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Prepared data changed: ' + name)
    return audit


def fit_binary(f, columns, target, eligible, year, c, path):
    first = f.year.between(c['training_start_year'], year - 3) & eligible
    valid = f.year.eq(year - 2) & eligible
    final = first | valid
    x, vocabulary = BASE.category_encode(f, first, columns)
    params = c['training'].copy()
    rounds, early = params.pop('max_rounds'), params.pop('early_stopping_rounds')
    params.update(objective='binary', metric='binary_logloss', seed=c['seed'])
    def dataset(mask):
        return lgb.Dataset(x[mask], label=f.loc[mask, target], weight=1 / f.loc[mask, 'field_size'], free_raw_data=False)
    model = lgb.train(params, dataset(first), num_boost_round=rounds, valid_sets=[dataset(valid)],
        callbacks=[lgb.early_stopping(early, verbose=False)])
    chosen = model.best_iteration
    model = lgb.train(params, dataset(final), num_boost_round=chosen)
    model.save_model(str(path))
    needed = f.year.isin([year - 1, year])
    scores = np.full(len(f), np.nan)
    scores[needed] = model.predict(x[needed], raw_score=True)
    meta = {'file': path.name, 'sha256': BASE.sha(path), 'columns': columns, 'vocabulary': vocabulary,
        'target': target, 'trees': chosen, 'training_year_end': year - 2, 'calibration_year': year - 1,
        'evaluation_year': year, 'training_rows': int(final.sum()),
        'feature_gain': dict(sorted(zip(columns, map(float, model.feature_importance(importance_type='gain'))), key=lambda a: -a[1]))}
    return scores, meta


def fit_risk(f, cols, year, c, dest):
    scores, meta = fit_binary(f, cols, 'slow_label', f.risk_eligible, year, c, dest / 'risk.txt')
    cal = f.year.eq(year - 1) & f.risk_eligible
    # Regularized monotone sigmoid calibration on the preceding year only.
    model = LogisticRegression(C=1., solver='lbfgs', random_state=c['seed'])
    model.fit(scores[cal, None], f.loc[cal, 'slow_label'], sample_weight=1 / f.loc[cal, 'field_size'])
    coef = max(0., float(model.coef_[0, 0]))
    intercept = float(model.intercept_[0])
    risk = expit(coef * scores + intercept)
    # A horse without three past times cannot receive this particular risk label.
    risk[f.risk_past3_time.isna()] = np.nan
    prior = float(np.average(f.loc[cal, 'slow_label'], weights=1 / f.loc[cal, 'field_size']))
    meta.update(calibration={'slope': coef, 'intercept': intercept, 'prior': prior, 'year': year - 1})
    return risk, scores, meta


def probability_evaluation(f, point, scores, year, variant, temps, raw_fraction=None):
    test = f.year.eq(year) & f[point + '_complete']
    runner, race = [], []
    for key, one in f[test].groupby('race_key', sort=False):
        idx = one.index.to_numpy()
        n = len(one)
        target = one[point + '_rank'].to_numpy(int)
        ix, joint, p = BASE.joint(np.repeat(scores[idx, None], 3, axis=1), temps)
        actual = [int(np.flatnonzero(target == k)[0]) for k in (1, 2, 3)]
        ranks = np.argsort(np.argsort(-scores[idx], kind='stable'), kind='stable') + 1
        front = np.argsort(-p[:, 2], kind='stable')[:3]
        y3 = target <= 3
        brier, ll = BASE.binary_metrics(p[:, 2], y3.astype(int))
        expected = 1 + np.clip(raw_fraction[idx], 0, 1) * (n - 1) if raw_fraction is not None else np.full(n, np.nan)
        row = {'race_key': key, 'meet': int(one.meet.iloc[0]), 'year': year,
            'race_date': str(one.race_date.iloc[0].date()), 'point': point, 'variant': variant,
            'rank_position_mae': float(np.mean(abs(ranks - target))),
            'rank_large_error_rate': float(np.mean(abs(ranks - target) >= 3)),
            'position_mae': float(np.mean(abs(expected - target))) if raw_fraction is not None else np.nan,
            'leader_hit': int(np.argmax(p[:, 0]) == actual[0]),
            'top3_exact_hit': int(set(front) == set(actual)), 'front_recall': len(set(front) & set(actual)) / 3,
            'top3_brier': brier, 'top3_logloss': ll, 'leader_nll': float(-np.log(max(p[actual[0], 0], 1e-300))),
            'ordered_top3_nll': float(-np.log(max(joint[np.all(ix == actual, axis=1)].sum(), 1e-300))),
            'probability_sum_error': float(np.max(abs(p.sum(axis=0) - [1, 2, 3])))}
        race.append(row)
        for loc, (_, entry) in enumerate(one.iterrows()):
            runner.append({**{k: entry[k] for k in KEY}, 'meet': int(entry.meet), 'year': year,
                'race_date': entry.race_date, 'point': point, 'variant': variant,
                'score': float(scores[idx[loc]]), 'expected_position': float(expected[loc]),
                'ranked_position': int(ranks[loc]), 'prob_lead': float(p[loc, 0]), 'prob_front3': float(p[loc, 2]),
                'actual_rank': int(target[loc])})
    return pd.DataFrame(runner), pd.DataFrame(race)


def temperatures(f, point, scores, year, c):
    cal = f.year.eq(year - 1) & f[point + '_complete']
    frame = f.assign(outcome=f[point + '_rank'])
    repeated = np.repeat(scores[:, None], 3, axis=1)
    return [BASE.temperature_fit(frame[cal], repeated, k, c['temperature_bounds']) for k in range(3)]


def risk_adjustment(f, scores, risk, year, c):
    cal = f.year.eq(year - 1) & f.S1F_complete
    log_survival = np.log1p(-np.clip(np.nan_to_num(risk, nan=0.), 0, 1 - 1e-8))
    parts = []
    for _, one in f[cal].groupby('race_key', sort=False):
        idx = one.index.to_numpy()
        target = int(np.flatnonzero(one.S1F_rank.to_numpy() == 1)[0])
        parts.append((scores[idx], log_survival[idx], target))
    width = max(len(s) for s, _, _ in parts)
    s = np.full((len(parts), width), -np.inf)
    r = np.zeros((len(parts), width))
    y = np.empty(len(parts), int)
    for i, (a, b, target) in enumerate(parts):
        s[i, :len(a)], r[i, :len(a)], y[i] = a, b, target
    def loss(par):
        x = s / np.exp(par[0]) + par[1] * r
        return float(np.mean(logsumexp(x, axis=1) - x[np.arange(len(y)), y]))
    lo, hi = c['temperature_bounds']
    fit = minimize(loss, [0., 0.], method='L-BFGS-B', bounds=[(np.log(lo), np.log(hi)), (0., 2.)])
    if not fit.success:
        raise ValueError('Risk weight calibration failed')
    temp, alpha = float(np.exp(fit.x[0])), float(fit.x[1])
    adjusted = scores / temp + alpha * log_survival
    temps = temperatures(f, 'S1F', adjusted, year, c)
    # Stage1 has already been jointly fitted with alpha; preserve that optimum.
    temps[0] = 1.
    return adjusted, temps, {'score_temperature': temp, 'alpha': alpha, 'calibration_year': year - 1,
        'calibration_leader_nll': float(fit.fun), 'unknown_risk_adjustment': 0.}


def inherit_predictions(f, year, point):
    p = pd.read_parquet(PARENT / 'outputs/runner_predictions.parquet')
    p = p[p.variant.eq('jockey') & p.year.eq(year) & p.point.eq(point) & p.meet.eq(int(f.meet.iloc[0]))].copy()
    join = f[KEY].merge(p[KEY + ['predicted_fraction']], on=KEY, how='left', validate='one_to_one')
    raw = join.predicted_fraction.to_numpy(float)
    # Evaluate using the frozen v3 temperatures, not a newly tuned baseline.
    meet = int(f.meet.iloc[0])
    metadata = json.loads((PARENT / 'outputs/models' / f'{meet}_{year}_jockey/metadata.json').read_text())
    rp, rm = probability_evaluation(f, point, -raw, year, 'jockey', metadata['point_temperatures'][point], raw)
    paired = rp.merge(p, on=KEY, suffixes=('_new', '_old'), validate='one_to_one')
    if len(paired) != len(p) or not np.allclose(paired.prob_lead_new, paired.prob_lead_old, atol=1e-10):
        raise ValueError('Frozen baseline probability reproduction failed')
    return rp, rm


def risk_metrics(p):
    rows = []
    for (meet, year), one in p.groupby(['meet', 'year']):
        known = one[one.slow_label.notna() & one.risk.notna()].copy()
        y, risk = known.slow_label.to_numpy(int), known.risk.to_numpy(float)
        brier, ll = BASE.binary_metrics(risk, y)
        pb, pl = BASE.binary_metrics(known.prior.to_numpy(float), y)
        selected = known.sort_values(['risk', 'race_key', 'program_no'], ascending=[False, True, True]).head(int(np.ceil(.1 * len(known))))
        rows.append({'meet': int(meet), 'year': int(year), 'runners': len(known), 'prevalence': float(y.mean()),
            'brier': brier, 'logloss': ll, 'prior_brier': pb, 'prior_logloss': pl,
            'auc': float(roc_auc_score(y, risk)), 'alert_n': len(selected),
            'alert_slow_rate': float(selected.slow_label.mean()),
            'alert_event_recall': float(selected.slow_label.sum() / y.sum())})
    return pd.DataFrame(rows)


def paired_differences(metrics, c):
    rng = np.random.default_rng(c['seed'])
    rows = []
    for (meet, point), one in metrics.groupby(['meet', 'point']):
        for variant in one.variant.unique():
            if variant == 'jockey':
                continue
            pair = one[one.variant.eq('jockey')].merge(one[one.variant.eq(variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
            for metric in ['leader_hit', 'top3_exact_hit', 'rank_position_mae', 'rank_large_error_rate', 'top3_brier', 'leader_nll']:
                delta = pair[metric + '_new'] - pair[metric + '_base']
                daily = pd.DataFrame({'day': pair.race_date_base, 'd': delta}).groupby('day').d.agg(['sum', 'size']).to_numpy()
                draw = daily[rng.integers(0, len(daily), (c['bootstrap_draws'], len(daily)))]
                bounds = np.quantile(draw[:, :, 0].sum(axis=1) / draw[:, :, 1].sum(axis=1), [.025, .975])
                rows.append({'meet': int(meet), 'point': point, 'variant': variant, 'metric': metric,
                    'races': len(pair), 'delta': float(delta.mean()), 'ci95': bounds.tolist()})
    return rows


def train():
    c = cfg()
    check_inputs()
    if (OUT / 'summary.json').exists():
        raise FileExistsError('Completed experiment exists')
    f = pd.read_parquet(OUT / 'features.parquet').merge(pd.read_parquet(OUT / 'labels.parquet'), on=KEY, validate='one_to_one')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    (OUT / 'models').mkdir(exist_ok=True)
    runners, metrics, risks, bundles = [], [], [], []
    for meet in c['venues']:
        one = f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            dest = OUT / 'models' / f'{meet}_{year}'
            completed = dest / 'metadata.json'
            if completed.exists():
                bundle = json.loads(completed.read_text())
                for name, digest in bundle['hashes'].items():
                    if BASE.sha(dest / name) != digest:
                        raise ValueError('Completed bundle changed')
                print(f'Reusing meet={meet} year={year}', flush=True)
            else:
                if dest.exists() and any(dest.iterdir()):
                    raise FileExistsError('Incomplete bundle: ' + str(dest))
                dest.mkdir(exist_ok=True)
                print(f'Training meet={meet} year={year}', flush=True)
                bundle = {'meet': meet, 'year': year, 'models': [], 'temperatures': {}, 'calibration_year': year - 1}
                rr, mm = [], []
                for point in ['S1F', 'G3F']:
                    rp, rm = inherit_predictions(one, year, point)
                    rr.append(rp); mm.append(rm)
                    pred, meta = PACE.fit_regression(one, contract['base'] + contract['trial'], point + '_fraction',
                        one[point + '_complete'], year, c, dest / (point + '_trial.txt'), race_weight=True)
                    bundle['models'].append(meta)
                    scores = -pred
                    regression_config = {**c, 'temperature_bounds': [0.02, 1.0]}
                    temps = temperatures(one, point, scores, year, regression_config)
                    bundle['temperatures'][point + '_trial'] = temps
                    rp, rm = probability_evaluation(one, point, scores, year, 'trial', temps, pred)
                    rr.append(rp); mm.append(rm)
                risk, risk_score, meta = fit_risk(one, contract['base'] + contract['trial'] + contract['risk'], year, c, dest)
                bundle['models'].append(meta)
                mask = one.year.eq(year) & one.S1F_complete
                risk_frame = one.loc[mask, KEY + ['meet', 'year', 'race_date', 'slow_label', 'risk_past3_time', 'historical_start_time']].copy()
                risk_frame['risk'], risk_frame['raw_score'], risk_frame['prior'] = risk[mask], risk_score[mask], meta['calibration']['prior']
                for variant, use_trials, front in [('leader', False, False), ('leader_trial', True, False), ('front3_trial', True, True)]:
                    # Unknown ranks occur outside the point-complete cohort and
                    # must never become training labels or block nullable casts.
                    one['direct_target'] = (one.S1F_rank.le(3) if front else one.S1F_rank.eq(1)).fillna(False).astype(int)
                    columns = contract['base'] + (contract['trial'] if use_trials else [])
                    scores, meta = fit_binary(one, columns, 'direct_target', one.S1F_complete, year, c, dest / (variant + '.txt'))
                    meta['direct_kind'] = 'front3' if front else 'leader'
                    bundle['models'].append(meta)
                    temps = temperatures(one, 'S1F', scores, year, c)
                    bundle['temperatures']['S1F_' + variant] = temps
                    rp, rm = probability_evaluation(one, 'S1F', scores, year, variant, temps)
                    rr.append(rp); mm.append(rm)
                    if variant == 'leader_trial':
                        adjusted, risk_temps, adjustment = risk_adjustment(one, scores, risk, year, c)
                        bundle['risk_adjustment'] = adjustment
                        bundle['temperatures']['S1F_leader_risk'] = risk_temps
                        rp, rm = probability_evaluation(one, 'S1F', adjusted, year, 'leader_risk', risk_temps)
                        rr.append(rp); mm.append(rm)
                pd.concat(rr, ignore_index=True).to_parquet(dest / 'runners.parquet', index=False)
                pd.concat(mm, ignore_index=True).to_csv(dest / 'points.csv', index=False)
                risk_frame.to_parquet(dest / 'risk_predictions.parquet', index=False)
                bundle['hashes'] = {p.name: BASE.sha(p) for p in dest.iterdir() if p.is_file()}
                BASE.save_json(completed, bundle)
                print(f'Evaluated meet={meet} year={year}', flush=True)
            runners.append(pd.read_parquet(dest / 'runners.parquet'))
            metrics.append(pd.read_csv(dest / 'points.csv'))
            risks.append(pd.read_parquet(dest / 'risk_predictions.parquet'))
            bundles.append(bundle)
    rp, rm, risk = pd.concat(runners, ignore_index=True), pd.concat(metrics, ignore_index=True), pd.concat(risks, ignore_index=True)
    rp.to_parquet(OUT / 'runner_predictions.parquet', index=False)
    rm.to_csv(OUT / 'point_metrics.csv', index=False)
    risk.to_parquet(OUT / 'risk_predictions.parquet', index=False)
    summary = []
    for (meet, point, variant), group in rm.groupby(['meet', 'point', 'variant']):
        for period, sample in [('all', group), *[(str(y), a) for y, a in group.groupby('year')]]:
            summary.append({'meet': int(meet), 'point': point, 'variant': variant, 'period': period, 'races': len(sample),
                **{col: float(sample[col].mean()) for col in ['rank_position_mae', 'rank_large_error_rate', 'position_mae',
                  'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier', 'top3_logloss', 'leader_nll', 'ordered_top3_nll']}})
    s = pd.DataFrame(summary)
    s.to_csv(OUT / 'metrics.csv', index=False)
    risk_summary = risk_metrics(risk)
    risk_summary.to_csv(OUT / 'risk_metrics.csv', index=False)
    differences = paired_differences(rm, c)
    BASE.save_json(OUT / 'paired_differences.json', differences)
    context = f[KEY + ['history_count', 'trial_has_time']].copy()
    context['experience'] = np.where(context.history_count.eq(0), 'zero', np.where(context.history_count.lt(5), 'one_to_four', 'five_plus'))
    joined = rp.merge(context, on=KEY, validate='many_to_one')
    joined['rank_error'] = abs(joined.ranked_position - joined.actual_rank)
    joined['large_error'] = joined.rank_error.ge(3)
    joined.groupby(['meet', 'point', 'variant', 'experience']).agg(runners=('horse_id', 'size'),
        rank_mae=('rank_error', 'mean'), large_error=('large_error', 'mean')).to_csv(OUT / 'experience_sensitivity.csv')
    scenarios(rp, risk)
    report(s, risk_summary, bundles, differences)
    BASE.save_json(OUT / 'summary.json', {'experiment': c['experiment'], 'models': bundles,
        'metrics': json_records(s), 'production_changed': False, 'final_finish_model_changed': False,
        'result_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}})
    print('Completed ' + str(OUT / 'REPORT.md'), flush=True)


def scenarios(predictions, risks):
    a = predictions[predictions.point.eq('S1F') & predictions.variant.eq('leader_trial')].copy()
    a = a.merge(risks[KEY + ['risk']], on=KEY, validate='one_to_one')
    b = predictions[predictions.point.eq('S1F') & predictions.variant.eq('leader_risk')]
    a = a.merge(b[KEY + ['prob_lead']], on=KEY, suffixes=('', '_risk_adjusted'), validate='one_to_one')
    rows = []
    for key, one in a.groupby('race_key', sort=False):
        order = one.sort_values(['prob_lead', 'program_no'], ascending=[False, True])
        lead, alternate = order.iloc[0], order.iloc[1]
        new_lead = one.sort_values(['prob_lead_risk_adjusted', 'program_no'], ascending=[False, True]).iloc[0]
        rows.append({'race_key': key, 'meet': int(lead.meet), 'year': int(lead.year),
            'leader_program': int(lead.program_no), 'leader_probability': float(lead.prob_lead),
            'leader_slow_risk': float(lead.risk), 'alternative_program': int(alternate.program_no),
            'alternative_probability': float(alternate.prob_lead), 'risk_adjusted_leader': int(new_lead.program_no),
            'changed': bool(new_lead.program_no != lead.program_no)})
    pd.DataFrame(rows).to_csv(OUT / 'leader_risk_scenarios.csv', index=False)


def report(s, risk, bundles, differences):
    names = {'jockey': '기존 기수 v3', 'trial': '+주행심사 회귀', 'leader': '선두 직접',
        'leader_trial': '선두 직접+심사', 'front3_trial': '앞선3두 직접+심사', 'leader_risk': '선두 직접+심사+위험'}
    lines = ['# 전개 v4 — 보유 자료로 목표·주행심사·초반 부진 위험 비교', '',
        '심판기록·외부수집 없이 원천 DB의 기록만 사용. 학습2017+, 이력T−2, 서울/부산 별도. 평가2024–2026-09-20은 기존 연구와 같은 후향 기간이며 독립 미래 검증이 아니다.', '',
        '| 장소 | 지점 | 후보 | 경주 | 선두 적중 | 앞선3두 정확 | 앞선 재현 | Brier ↓ | 점수순위 MAE ↓ |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for row in s[s.period.eq('all')].itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.point} | {names[row.variant]} | {row.races:,} | {row.leader_hit:.2%} | {row.top3_exact_hit:.2%} | {row.front_recall:.2%} | {row.top3_brier:.5f} | {row.rank_position_mae:.4f} |')
    lines += ['', '## 회귀 위치 오차', '', '직접 분류 점수를 평균 위치로 간주하지 않는다. 모든 후보의 점수순위 MAE는 정렬한 순번의 오차이며 기존 평균 예상위치 MAE와 다른 지표다.', '',
        '| 장소 | 지점 | 후보 | 평균 위치 MAE |', '|---|---|---|---:|']
    for row in s[s.period.eq('all') & s.variant.isin(['jockey', 'trial'])].itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.point} | {names[row.variant]} | {row.position_mae:.4f}두 |')
    lines += ['', '## 초반 부진 위험', '', '최근 실제출전3전 모두 초반시간이 있을 때 평균보다0.4초 초과 느린200m 기록. 출발 사고/발주대 반응 정답이 아니며 이력 부족은 미상이다.', '',
        '| 장소 | 연도 | 말 | 발생률 | Brier/상수 | Logloss/상수 | AUC | 상위10% 발생률 |', '|---|---:|---:|---:|---|---|---:|---:|']
    for row in risk.itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.year} | {row.runners:,} | {row.prevalence:.2%} | {row.brier:.5f}/{row.prior_brier:.5f} | {row.logloss:.5f}/{row.prior_logloss:.5f} | {row.auc:.4f} | {row.alert_slow_rate:.2%} |')
    lines += ['', '## 선행 후보의 위험 보정', '', '선두 직접+심사 점수의 온도와 log(1−위험) 가중치를 이전 연도 선두 NLL로 맞춘다. 평가 결과로 가중치를 선택하지 않는다. 미상 위험은 보정0. 대안 후보는 같은 사전 점수의 차순위이며 인과적 경합 시나리오 또는 실제 늦발 조건부 확률이 아니다.', '',
        '| 장소 | 평가연도 | 이전연도에서 맞춘 위험 가중치 |', '|---|---:|---:|']
    for bundle in bundles:
        lines.append(f'| { {1:"서울",3:"부산"}[bundle["meet"]]} | {bundle["year"]} | {bundle["risk_adjustment"]["alpha"]:.4f} |')
    lines += ['', '## 동일 경주 차이', '', '후보−기준. 날짜 단위95% bootstrap은 후보 반복 탐색을 보정하지 않는다.', '',
        '| 장소 | 지점 | 후보 | 지표 | 차이 | 95% 구간 |', '|---|---|---|---|---:|---|']
    for d in differences:
        if d['metric'] in ['leader_hit', 'top3_exact_hit', 'top3_brier']:
            lo, hi = d['ci95']
            lines.append(f'| { {1:"서울",3:"부산"}[d["meet"]]} | {d["point"]} | {names[d["variant"]]} | {d["metric"]} | {d["delta"]:+.5f} | {lo:+.5f}~{hi:+.5f} |')
    lines += ['', '## 범위와 보존', '',
        '주행심사 자료는 검토된 공식 말ID로 연결하고 기존 물리지역 예외를 반영했다. 세션 상대시간에는 연습 강도 차이가 남는다. 전체 주파시간은 미확인 거리 차이를 피하기 위해 입력하지 않았다. 세션 순위는 실제 완료자의 완전 순열만 사용한다.', '',
        '현재 출전 편성·기수·게이트는 기존 결과표 기반 대리값이며 당시 사전 공개 시점이 확인된 운영 검증은 아니다. 현재 결과·시간은 정답에만 쓰며 특징은 과거 관측이다. 원천 DB와 운영 등록부, 기존 실험을 보존한다.', '',
        '이번 결과는 통과위치·초반 부진 위험의 검증이다. 최종 입상이나 삼복승 적중률/수익률 개선을 주장하지 않는다. 연도별 결과와 신마 민감도, 주행심사/위험 관측률, 검증 결과를 함께 본다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'train'])
    args = parser.parse_args()
    {'prepare': prepare, 'train': train}[args.mode]()
