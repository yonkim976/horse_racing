"""Frozen local references and last-three label contracts. No database writes."""
from pathlib import Path
from datetime import datetime, timezone
import json, sys
import torch  # Initialize this OpenMP runtime before LightGBM on macOS.
import numpy as np
import pandas as pd
import duckdb
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE / 'outputs'
PREV = R / '20261022_dynamic_race_model_v1'
sys.path.insert(0, str(PREV))
import common as old

KEY = old.KEY
LAMBDAS = [0., .25, .5, 1.]
PREVIOUS_BYTES = 140_831_211

def sha(path): return old.sha(path)

def save(path, value):
    path = Path(path)
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def official():
    with duckdb.connect(str(old.DB), read_only=True) as con:
        return con.execute("""SELECT CAST(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||CAST(race_no AS VARCHAR) race_key,
            chul_no program_no, hr_no horse_id, finish_order, result_status, is_dead_heat
            FROM entry_result WHERE canonical_meet IN (1,3)""").df()

def add_labels(f):
    f = f.copy()
    f['normal'] = f.result_status.eq('finished')
    finish = f.finish_order.where(f.normal).astype(float)
    worst_rank = finish.groupby(f.race_key).rank(ascending=False, method='min')
    tied = f.groupby(['race_key', 'finish_order'], dropna=False).finish_order.transform('size')
    f['bottom_truth'] = ((4 - worst_rank) / tied).clip(0, 1).fillna(0.)
    f['boundary_tie'] = f.bottom_truth.between(0, 1, inclusive='neither').groupby(f.race_key).transform('any')
    assert f.groupby('race_key').normal.sum().ge(6).all()
    assert np.allclose(f.groupby('race_key').bottom_truth.sum(), 3.)
    assert not (f.bottom_truth.gt(0) & f.outcome.between(1,3)).any()
    assert f.loc[~f.normal, 'bottom_truth'].eq(0).all()
    return f

def frame():
    f = old.frame().merge(official(), on=KEY, how='left', validate='1:1')
    assert f.result_status.notna().all()
    assert np.array_equal(f.row_number, np.arange(len(f)))
    return add_labels(f)

def order(score): return old.scorer.probability_order(score)

def choose(base, bottom, lam): return int(order(base - lam * bottom)[0])

def exclude_axis(base, bottom):
    keep = np.ones(len(base), bool)
    keep[order(bottom)[:3]] = False
    ix = np.flatnonzero(keep)
    return int(ix[order(base[ix])[0]])

def temperature(f, scores):
    rows, truth = [], []
    for ix in f.groupby('race_key', sort=False).indices.values():
        g = f.iloc[ix]
        if g.boundary_tie.any(): continue
        s = scores[ix]
        rows.append(s[old.base.triples(len(g))].sum(axis=1))
        truth.append(float(s @ g.bottom_truth.to_numpy(float)))
    matrix = np.full((len(rows), max(map(len, rows))), -np.inf)
    for i, row in enumerate(rows): matrix[i, :len(row)] = row
    truth = np.array(truth)
    opt = minimize_scalar(lambda t: float(np.mean(logsumexp(matrix/t, axis=1)-truth/t)),
                          bounds=(.35, 4.), method='bounded')
    assert opt.success
    return float(opt.x)

def distribution(score, temp):
    sets = old.base.triples(len(score))
    logits = score[sets].sum(axis=1) / temp
    mass = np.exp(logits - logsumexp(logits))
    marginal = np.bincount(sets.ravel(), weights=np.repeat(mass, 3), minlength=len(score))
    assert abs(mass.sum()-1) < 1e-10 and abs(marginal.sum()-3) < 1e-10
    assert marginal.min() >= 0 and marginal.max() <= 1+1e-10
    return sets, mass, marginal

def policy_hits(f, base, bottom):
    hits = np.zeros(len(LAMBDAS), int)
    for ix in f.groupby('race_key', sort=False).indices.values():
        truth = f.iloc[ix].outcome.between(1,3).to_numpy()
        for j, lam in enumerate(LAMBDAS): hits[j] += int(truth[choose(base[ix], bottom[ix], lam)])
    return hits

def paired(f, before, after, scale=1.):
    b = f[before].to_numpy(float); a = f[after].to_numpy(float)
    dates, ix = np.unique(f.race_date, return_inverse=True)
    n = np.bincount(ix); diff = np.bincount(ix, weights=(a-b)/scale)
    draws = np.random.default_rng(20261026).integers(0, len(dates), size=(2000,len(dates)))
    boot = diff[draws].sum(1)/n[draws].sum(1)
    return {'races':len(f), 'dates':len(dates), 'baseline_total':float(b.sum()), 'candidate_total':float(a.sum()),
        'baseline_rate':float(b.mean()/scale), 'candidate_rate':float(a.mean()/scale),
        'difference':float((a-b).mean()/scale), 'difference_ci95':np.quantile(boot,[.025,.975]).tolist(),
        'relative_percent':float((a.mean()/b.mean()-1)*100) if b.mean() else None,
        'gained_races':int((a>b).sum()), 'lost_races':int((a<b).sum())}

def storage():
    n = sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert n + PREVIOUS_BYTES < 300_000_000
    return n

def freeze():
    paths = [HERE/'PLAN.md', *sorted(HERE.glob('*.py')), old.DB, old.HISTORY,
        old.base.SOURCE/'features.parquet', old.base.SOURCE/'feature_contract.json',
        old.base.ABILITY/'research_baseline_selection.json', old.BASE/'run.py', old.BASE/'probability.py',
        old.BASE/'evaluate.py', old.BASE/'config.json', PREV/'common.py', PREV/'state.py',
        PREV/'outputs/state_features.parquet', PREV/'outputs/state_contract.json',
        PREV/'outputs/race_metrics.parquet', PREV/'outputs/runner_probabilities.parquet', PREV/'outputs/tickets.parquet',
        ROOT/'config/prediction_model_registry.json']
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder = PREV/'outputs/models'/f'state_gbm_{meet}_{year}'
            paths += [folder/'metadata.json', folder/'model.txt', folder/'scores.parquet']
    assert not (OUT/'input_manifest.json').exists()
    save(OUT/'input_manifest.json', {str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths})
    save(OUT/'protocol_frozen.json', {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'evaluation_started':False,'new_model_families':1,'final_models':6,'initial_fits':6,
        'features':old.features()['state_gbm'],'lambdas':LAMBDAS,'repeated_development_data':True})
    names = ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']
    save(OUT/'preexisting_files.json', {str((R/n).relative_to(ROOT)):{'sha256':sha(R/n),'bytes':(R/n).stat().st_size} for n in names})
    f = frame(); audit = {}
    for name, g in [('all',f),('evaluation',f[f.year.ge(2024)])]:
        audit[name] = {'runners':len(g),'races':int(g.race_key.nunique()),
            'statuses':{str(k):int(v) for k,v in g.result_status.value_counts().items()},
            'boundary_tie_races':int(g.groupby('race_key').boundary_tie.first().sum()),
            'minimum_normal_finishers':int(g.groupby('race_key').normal.sum().min()),
            'truth_sum_max_error':float(abs(g.groupby('race_key').bottom_truth.sum()-3).max())}
    save(OUT/'label_audit.json', audit)
    print(json.dumps(audit,ensure_ascii=False),flush=True)

def check():
    for name, v in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/name) == v['sha256'], name

if __name__ == '__main__': freeze()
