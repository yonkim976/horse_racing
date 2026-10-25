"""Independent arithmetic, window, database, and serialized-model checks."""
from pathlib import Path
import hashlib
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t

H = Path(__file__).resolve().parent
ROOT = H.parents[2]
PRE = H.parent / '20261008_weight_speed_v2'
FORM = H.parent / '20261008_recent_form_persistence_v1'

def sha(p):
    x = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            x.update(chunk)
    return x.hexdigest()

def close(x, y, tol=1e-8):
    assert np.allclose(x, y, atol=tol, rtol=tol, equal_nan=True)

tr = pd.read_csv(H / 'training_source_lineage.csv', dtype={'horse_id': str})
ft = pd.read_csv(H / 'training_features.csv').set_index('api_record_id')
tr_by_id = {int(r.daily_training_api_row_id): (r.horse_id, r.training_date, r.duration_seconds)
            for r in tr.itertuples()}
trace = json.loads((H / 'training_window_lineage.json').read_text())
endpoints = 0
for r in trace:
    dt = pd.Timestamp(r['race_date'])
    assert r['cutoff'] == (dt - pd.Timedelta(days=2)).strftime('%Y-%m-%d')
    for label, start, end in [('7', 8, 2), ('14', 15, 2), ('28', 29, 2), ('previous28', 57, 30)]:
        ids = r[label]
        assert len(ids) == len(set(ids))
        lo = (dt - pd.Timedelta(days=start)).strftime('%Y-%m-%d')
        hi = (dt - pd.Timedelta(days=end)).strftime('%Y-%m-%d')
        rows = [tr_by_id[i] for i in ids]
        assert all(h == r['horse_id'] and lo <= date <= hi for h, date, _ in rows)
        durations = [v for _, _, v in rows if np.isfinite(v)]
        close(ft.loc[r['api_record_id'], 'days' + label], len(rows) if rows else np.nan)
        close(ft.loc[r['api_record_id'], 'meanmin' + label], np.mean(durations) / 60 if durations else np.nan)
        endpoints += len(ids)
print('all training window endpoints checked', endpoints, flush=True)

db = ROOT / 'jeju/data/jeju_native_core.sqlite3'
con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
con.execute('PRAGMA query_only=ON')
sql_checks = []
for i in np.random.default_rng(20261008).choice(len(trace), 64, replace=False):
    r = trace[i]; dt = pd.Timestamp(r['race_date'])
    for label, start, end in [('7', 8, 2), ('14', 15, 2), ('28', 29, 2), ('previous28', 57, 30)]:
        lo = (dt - pd.Timedelta(days=start)).strftime('%Y-%m-%d')
        hi = (dt - pd.Timedelta(days=end)).strftime('%Y-%m-%d')
        rows = con.execute('SELECT daily_training_api_row_id,duration_seconds FROM daily_training_api_rows WHERE horse_id=? AND training_date BETWEEN ? AND ? ORDER BY training_date', (r['horse_id'], lo, hi)).fetchall()
        assert [z[0] for z in rows] == r[label]
        durations = [z[1] for z in rows if z[1] is not None]
        close(ft.loc[r['api_record_id'], 'meanmin' + label], np.mean(durations) / 60 if durations else np.nan)
        sql_checks.append({'api_record_id': r['api_record_id'], 'window': label, 'rows': len(rows)})
con.close()

pairs = pd.read_csv(PRE / 'pair_lineage.csv', dtype={'horse_id': str})
delta = pairs.burden_change
pairs['burden_group'] = np.where(delta <= -1, 'down1plus', np.where(delta < 1, 'stableUnder1', np.where(delta < 3, 'up1toUnder3', 'up3plus')))
pairs['raw_slow2'] = (pairs.time_delta >= 2).astype(float)
pairs['relative_slow1'] = (pairs.relative_time_delta >= 1).astype(float)
pairs['hinge3'] = np.maximum(delta - 3, 0)
pairs['gap_squared'] = pairs.gap ** 2
for key in ['days28', 'meanmin28']:
    pairs[key] = ft.loc[pairs.pair_id, key].to_numpy()
    pairs['previous_' + key] = ft.loc[pairs.previous_api_record_id, key].to_numpy()
pairs['training_days5'] = (pairs.days28 - pairs.previous_days28) / 5
pairs['training_mean5'] = (pairs.meanmin28 - pairs.previous_meanmin28) / 5

raw = pd.read_csv(H / 'burden_raw_risks.csv')
for r in raw[raw.period.eq('full')].itertuples():
    g = pairs[pairs.distance.eq(r.distance) & pairs.burden_group.eq(r.burden_group)]
    assert len(g) == r.rows
    close(g.raw_slow2.mean(), r.raw_slow2_rate)
    close(g.relative_slow1.mean(), r.relative_slow1_rate)

checks = []
models = json.loads((H / 'association_models.json').read_text())
for entry in models:
    if entry['period'] != 'full' or entry['variant'] != 'primary' or entry['distance'] not in [1000, 1110] or entry['family'] == 'training_row':
        continue
    g = pairs[pairs.distance.eq(entry['distance'])]
    m = entry['model']; spec = m['design']; cols = m['columns']
    if entry['family'] == 'burden_risk':
        targets = ['down1plus', 'up1toUnder3', 'up3plus']
        tv = np.column_stack([(g.burden_group == c).astype(float) for c in targets])
    else:
        targets = ['increase_kg', 'hinge3'] if entry['family'] == 'burden_spline' else ['training_days5', 'training_mean5']
        tv = g[targets].to_numpy()
    nuisance = []
    for name in spec['nuisance_columns']:
        if name.endswith('_missing'):
            z = g[name[:-8]].isna().to_numpy(float)
        elif name.startswith('year_grade='):
            z = (g.year_grade == name.split('=', 1)[1]).to_numpy(float)
        else:
            z = g[name].fillna(spec['nuisance_medians'][name]).to_numpy(float)
        nuisance.append(z)
    nx = (np.column_stack(nuisance) - spec['nuisance_means']) / spec['nuisance_sd']
    x = np.column_stack([tv, np.ones(len(g)), nx])
    ycol = m['target'] if entry['family'] == 'burden_risk' else 'time_delta' if m['target'] == 'time_s' else 'log_time_delta100'
    y = g[ycol].to_numpy(float)
    penalty = np.ones(x.shape[1]); penalty[:len(targets) + 1] = 0
    normal = x.T @ x + np.diag(penalty)
    beta = np.linalg.solve(normal, x.T @ y)
    close(beta, m['beta'], 1e-8)
    bread = np.linalg.solve(normal, np.eye(len(cols)))
    res = y - x @ beta; cov = np.zeros_like(bread)
    df = len(g) - np.linalg.matrix_rank(x, tol=1e-7)
    for key in ['race_date', 'horse_id']:
        codes, counts = pd.factorize(g[key])
        scores = np.zeros((len(counts), len(cols)))
        np.add.at(scores, codes, x * res[:, None])
        n = len(counts)
        cov += bread @ (scores.T @ scores) @ bread * n / (n - 1) * (len(g) - 1) / df
    close(cov, m['cov'], 1e-8)
    checks.append({'family': entry['family'], 'distance': entry['distance'], 'target': m['target'], 'maximum_beta_error': float(np.max(np.abs(beta - m['beta']))), 'maximum_cov_error': float(np.max(np.abs(cov - m['cov'])))})

f = pd.read_csv(FORM / 'features.csv', dtype={'horse_id': str}).merge(ft.reset_index(), on='api_record_id', validate='one_to_one')
pred = pd.read_csv(H / 'training_predictions.csv').set_index('api_record_id')
prediction_checks = []
for m in json.loads((H / 'training_prediction_models.json').read_text()):
    nums = m['numeric_columns']
    def transform(z):
        a = z[nums].to_numpy(float)
        mask = np.isnan(a)
        a = np.where(mask, m['imputer_median'], a)
        a = np.column_stack([a, mask[:, m['missing_indicators']].astype(float)])
        a = (a - m['scale_mean']) / m['scale_sd']
        cat = np.column_stack([(z[key].astype(str) == level).to_numpy(float) for key, levels in zip(['last_grade', 'last_sex'], m['categorical_levels']) for level in levels])
        return np.column_stack([a, cat])
    train = f[f.year.lt(m['year']) & f.distance.eq(m['distance'])]
    test = f[f.year.eq(m['year']) & f.distance.eq(m['distance'])]
    x = transform(test)
    close(x @ m['coefficient'] + m['intercept'], pred.loc[test.api_record_id, 'prediction_E'], 1e-9)
    if m['distance'] in [1000, 1110] and m['year'] in [2024, 2026]:
        x = transform(train); y = train.time.to_numpy(float)
        w = 1 / train.eligible_in_race.to_numpy(float); w = w / w.mean()
        xm = np.average(x, axis=0, weights=w); ym = np.average(y, weights=w)
        xc = x - xm; yc = y - ym
        beta = np.linalg.solve(xc.T @ (w[:, None] * xc) + 10 * np.eye(x.shape[1]), xc.T @ (w * yc))
        close(beta, m['coefficient'], 1e-8)
        close(ym - xm @ beta, m['intercept'], 1e-8)
        prediction_checks.append({'year': m['year'], 'distance': m['distance'], 'coefficient_max_error': float(np.max(np.abs(beta - m['coefficient'])))})

for filename, keys in [('burden_effects.csv', ['family','period','variant','target','exposure']), ('training_effects.csv', ['family','period','exposure']), ('training_prediction_improvements.csv', ['period','metric'])]:
    table = pd.read_csv(H / filename)
    for _, g in table.groupby(keys):
        p = g.p.to_numpy(); order = np.argsort(p); q = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1].clip(0, 1)
        close(g.q_BH.to_numpy()[order], q)

prior = json.loads((ROOT / 'jeju/research/conclusions/source_manifest.json').read_text())
for r in prior['files']:
    assert sha(ROOT / r['path']) == r['sha256'], r['path']
for r in json.loads((H / 'source_manifest.json').read_text()):
    assert sha(Path(r['path'])) == r['sha256'], r['path']
assert sha(db) == json.loads((H / 'input_audit.json').read_text())['database_sha256']
result = {'status': 'passed', 'window_rows': len(trace), 'window_endpoints': endpoints, 'database_window_samples': sql_checks, 'independent_association_coefficient_covariance_checks': checks, 'serialized_prediction_reproductions': 13, 'independent_weighted_ridge_checks': prediction_checks, 'BH_arithmetic_passed': True, 'prior_central_manifest_unchanged_files': len(prior['files']), 'database_and_prior_sources_unchanged': True}
with (H / 'independent_verification.json').open('x') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('passed independent checks', len(checks), len(prediction_checks), flush=True)
