"""Read-only Jeju scorecards and two predeclared chronological Top3 models."""
import argparse
import bisect
import hashlib
import itertools
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow
import scipy
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
OUT = HERE / 'outputs_v2'
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
SEED = 20261008
BASE = ['distance_m', 'grade_raw', 'field_n', 'observed_starts', 'days_since_start',
        'previous_age', 'previous_sex', 'same_starts', 'same_valid_times', 'days_since_same',
        'last_time_s', 'mean5_s', 'valid_n5']
EXTRA = ['mean3_s', 'valid_n3', 'best5_s', 'fast2mean5_s', 'std5_s',
         'previous3_mean_s', 'previous3_valid_n', 'trend_s']
CONTRACTS = {'J0': BASE, 'J1': BASE + EXTRA}
CATS = ['grade_raw', 'previous_sex']
PARAMS = dict(objective='binary', metric='binary_logloss', learning_rate=0.04,
              num_leaves=15, min_data_in_leaf=100, lambda_l2=5.0, num_threads=4,
              deterministic=True, force_col_wise=True, verbosity=-1, seed=SEED)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def save(path, obj):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda x: x.item() if isinstance(x, np.generic) else str(x))
        f.write('\n')


def write_csv(path, frame):
    with Path(path).open('x', encoding='utf-8') as f:
        frame.to_csv(f, index=False)


def read_source():
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    # Fixed identifiers; no user-provided SQL or table names.
    cache = HERE / 'outputs/source_snapshot.parquet'
    receipt = json.loads((HERE/'PREPARATION_RETRY.json').read_text())
    assert sha(DB) == receipt['database_reference_sha256']
    assert sha(cache) == receipt['snapshot_sha256']
    d = pd.read_parquet(cache)
    full = pd.read_sql_query('''SELECT race_date,meet_code,race_number,COUNT(*) AS full_n
        FROM race_result_rows GROUP BY race_date,meet_code,race_number''', con)
    con.close()
    for df in [d, full]:
        df['race_id'] = df.race_date + '_' + df.meet_code.astype(str) + '_' + df.race_number.astype(str)
    d['horse_id'] = d.horse_id.astype(str)
    assert not d.duplicated(['race_id', 'horse_id']).any()
    assert d.api_record_id.is_unique and d.race_date.max() == '2026-09-19'
    forbidden = json.loads((ROOT / 'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(d.horse_id) & {h for h, v in forbidden.items() if not v['reimport_allowed']}
    d = d.sort_values(['race_date', 'race_number', 'horse_number', 'api_record_id']).reset_index(drop=True)
    d['year'] = d.race_date.str[:4].astype(int)
    d['started'] = d.finish_position.between(1, 89) | d.finish_position.isin([91, 92])
    d['valid_time'] = d.finish_position.between(1, 89) & d.finish_time_seconds.gt(0)
    return d, dict(zip(full.race_id, full.full_n))


def population(d, full):
    ledger = []
    for rid, g in d[d.year.ge(2017)].groupby('race_id', sort=True):
        n = len(g)
        reasons = []
        if not g.race_distance_m.isin(DISTANCES).all(): reasons.append('outside_current_distances')
        if n < 6: reasons.append('fewer_than_6')
        if n != full.get(rid): reasons.append('partial_vs_stored_result')
        if not g.valid_time.all(): reasons.append('non_normal_or_nonpositive_time')
        if sorted(g.finish_position.dropna().tolist()) != list(range(1, n + 1)): reasons.append('ranks_not_complete_unique_1_to_N')
        if g.horse_id.nunique() != n: reasons.append('duplicate_horse')
        if g.horse_number.isna().any() or g.horse_number.le(0).any() or g.horse_number.nunique() != n: reasons.append('invalid_or_duplicate_number')
        if any(g[c].nunique(dropna=False) != 1 for c in ['race_distance_m', 'rank_class_raw']): reasons.append('within_race_condition_conflict')
        ledger.append(dict(race_id=rid, race_date=g.race_date.iloc[0], year=int(g.year.iloc[0]),
                           distance_m=int(g.race_distance_m.iloc[0]), field_n=n,
                           included=not reasons, reasons='|'.join(reasons),
                           result_codes='|'.join(map(str, sorted(g.finish_position.dropna().unique())))))
    return pd.DataFrame(ledger)


def mean_valid(a):
    return float(np.nanmean(a)) if np.isfinite(a).any() else np.nan


def card(r, past, same):
    """Receives already cut histories; actual start slots are preserved."""
    recent = same[-5:]
    six = same[-6:]
    a = np.array([x['finish_time_seconds'] if x['valid_time'] else np.nan for x in six], float)
    last5 = a[-5:]
    last3 = a[-3:]
    prior3 = a[:-3]
    n3 = int(np.isfinite(last3).sum()); np3 = int(np.isfinite(prior3).sum())
    known = last5[np.isfinite(last5)]
    prev = past[-1] if past else None
    latest = same[-1] if same else None
    gap = lambda row: (date.fromisoformat(r['race_date']) - date.fromisoformat(row['race_date'])).days if row else np.nan
    previous_age = pd.to_numeric(prev['age_at_race_raw'], errors='coerce') if prev else np.nan
    if not pd.notna(previous_age) or previous_age <= 0: previous_age = np.nan
    previous_sex = prev['sex_at_race_raw'] if prev else None
    if previous_sex in ['', '-', '0']: previous_sex = None
    result = dict(observed_starts=len(past), days_since_start=gap(prev), previous_age=previous_age,
                  previous_sex=previous_sex, same_starts=len(same),
                  same_valid_times=sum(x['valid_time'] for x in same), days_since_same=gap(latest),
                  last_time_s=a[-1] if len(a) else np.nan, mean5_s=mean_valid(last5), valid_n5=len(known),
                  mean3_s=mean_valid(last3), valid_n3=n3, best5_s=float(known.min()) if len(known) else np.nan,
                  fast2mean5_s=float(np.sort(known)[:2].mean()) if len(known) >= 2 else np.nan,
                  std5_s=float(known.std(ddof=1)) if len(known) >= 3 else np.nan,
                  previous3_mean_s=mean_valid(prior3), previous3_valid_n=np3,
                  trend_s=mean_valid(last3)-mean_valid(prior3) if min(n3, np3) >= 2 else np.nan)
    return result, [int(x['api_record_id']) for x in recent], [int(x['api_record_id']) for x in six]


def build_features(d, ledger):
    by_h = {k: g.to_dict('records') for k, g in d[d.started].groupby('horse_id', sort=False)}
    dates = {k: [x['race_date'] for x in v] for k, v in by_h.items()}
    by_hd = {k: g.to_dict('records') for k, g in d[d.started].groupby(['horse_id', 'race_distance_m'], sort=False)}
    sd = {k: [x['race_date'] for x in v] for k, v in by_hd.items()}
    included = set(ledger.loc[ledger.included, 'race_id'])
    records = []
    for r in d[d.race_id.isin(included)].to_dict('records'):
        cutoff = (date.fromisoformat(r['race_date']) - timedelta(days=2)).isoformat()
        h = r['horse_id']; hd = (h, r['race_distance_m'])
        past = by_h.get(h, [])[:bisect.bisect_right(dates.get(h, []), cutoff)]
        same = by_hd.get(hd, [])[:bisect.bisect_right(sd.get(hd, []), cutoff)]
        f, ids5, ids6 = card(r, past, same)
        assert not past or past[-1]['race_date'] <= cutoff
        records.append({**{k: r[k] for k in ['api_record_id', 'race_id', 'race_date', 'year', 'horse_id',
                                            'horse_name', 'horse_number', 'finish_position']},
                        'distance_m': r['race_distance_m'], 'grade_raw': r['rank_class_raw'],
                        'history_cutoff': cutoff, 'latest_history_date': past[-1]['race_date'] if past else None,
                        'previous_start_id': int(past[-1]['api_record_id']) if past else None,
                        'last6_same_source_ids': ids6, 'last5_same_source_ids': ids5, **f})
    f = pd.DataFrame(records)
    f['field_n'] = f.groupby('race_id').api_record_id.transform('size')
    return f.sort_values(['race_date', 'race_id', 'horse_number']).reset_index(drop=True)


def protect_paths():
    files = [DB, ROOT/'config/prediction_model_registry.json']
    files += [p for p in (ROOT/'jeju/models').rglob('*') if p.is_file()]
    return {str(p.relative_to(ROOT)): dict(sha256=sha(p), bytes=p.stat().st_size) for p in files if p.exists()}


def check_protected(lock):
    for p, info in lock.items():
        assert sha(ROOT/p) == info['sha256'], p
        assert (ROOT/p).stat().st_size == info['bytes'], p


def examples(f, d):
    ids = ['3107406','3107451','3107838','3103957','3103294','3014773']
    q = f[f.race_date.eq('2026-09-19') & f.horse_id.isin(ids)]
    source = d.set_index('api_record_id', drop=False)
    result = []
    for r in q.to_dict('records'):
        history = source.loc[r['last6_same_source_ids']].copy() if r['last6_same_source_ids'] else source.iloc[:0]
        context = ['api_record_id', 'race_date', 'horse_id', 'race_distance_m', 'finish_position',
                   'finish_time_seconds', 'valid_time', 'rank_class_raw', 'carried_weight_kg',
                   'track_raw', 'api4_3_payload_sha256']
        row = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in r.items()}
        row['recent_same_history'] = json.loads(history[context].to_json(orient='records', force_ascii=False))
        valid = history.iloc[-5:]; valid = valid[valid.valid_time]
        row['best5_context'] = json.loads(valid.nsmallest(1, 'finish_time_seconds')[context].to_json(orient='records', force_ascii=False))
        result.append(row)
    assert len(result) == 6
    return result


def prepare():
    OUT.mkdir(exist_ok=False)
    protected = protect_paths()
    d, full = read_source()
    ledger = population(d, full)
    f = build_features(d, ledger)
    assert all(not set(cols) & {'finish_position','horse_id','horse_name','horse_number','race_date','api_record_id'} for cols in CONTRACTS.values())
    assert len(BASE) == 13 and len(BASE+EXTRA) == 21
    assert not f.duplicated(['race_id','horse_id']).any()
    assert (f.latest_history_date.isna() | f.latest_history_date.le(f.history_cutoff)).all()
    d.to_parquet(OUT/'source_snapshot.parquet', index=False)
    f.to_parquet(OUT/'features.parquet', index=False)
    write_csv(OUT/'race_inclusion_ledger.csv', ledger)
    write_csv(OUT/'feature_missingness.csv', pd.DataFrame([dict(variant=v, feature=c, missing=int(f[c].isna().sum()), rows=len(f), fraction=float(f[c].isna().mean())) for v, cols in CONTRACTS.items() for c in cols]))
    write_csv(OUT/'population_support.csv', f.groupby(['year','distance_m']).agg(rows=('api_record_id','size'), races=('race_id','nunique'), days=('race_date','nunique'), no_observed_history=('observed_starts', lambda x:int(x.eq(0).sum())), no_same_valid_time=('same_valid_times',lambda x:int(x.eq(0).sum()))).reset_index())
    save(OUT/'feature_contract.json', {v:dict(retained=BASE,added=[] if v=='J0' else EXTRA,removed=[],inputs=cols) for v,cols in CONTRACTS.items()})
    save(OUT/'example_scorecards.json', examples(f,d))
    counts = dict(source_rows=len(d), source_races=d.race_id.nunique(), label_candidate_races=len(ledger),
                  included_rows=len(f), included_races=f.race_id.nunique(), excluded_races=int((~ledger.included).sum()),
                  exclusion_reasons=dict(Counter(reason for s in ledger.reasons for reason in s.split('|') if reason)),
                  evaluation_rows=int(f.year.ge(2024).sum()), evaluation_races=f.loc[f.year.ge(2024),'race_id'].nunique())
    save(OUT/'audit.json', counts)
    check_protected(protected)
    refs=[HERE/'run.py', HERE/'verify.py', HERE/'report.py', HERE/'PREPARATION_RETRY.json', HERE/'outputs/source_snapshot.parquet', HERE/'CONTRACT.md', ROOT/'jeju/AGENTS.md',
          ROOT/'jeju/research/20261007_foundation_v1/EXPERIMENT_PROTOCOL.md',
          ROOT/'jeju/research/20261007_environment_correction_pilot_v1/modeling.py',
          ROOT/'thoroughbred/research/20261008_horse_profile_model_v1/run.py',
          ROOT/'thoroughbred/research/20261008_horse_profile_model_v1/README.md',
          ROOT/'thoroughbred/research/20261008_profile_carried_weight_v1/README.md',
          ROOT/'jeju/research/20261008_research_synthesis_v1/README.md']
    save(OUT/'prepared_lock.json', dict(protected=protected, references={str(p.relative_to(ROOT)):sha(p) for p in refs},
         artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
         versions={m.__name__:m.__version__ for m in [lgb,np,pd,scipy,pyarrow]}, seed=SEED,
         model_parameters=PARAMS, evaluation_years=[2024,2025,2026]))
    print(json.dumps(counts,ensure_ascii=False),flush=True)


@lru_cache(maxsize=16)
def support(n):
    c = np.array(list(itertools.combinations(range(n),3)),int)
    incidence = np.zeros((len(c),n))
    for k, triple in enumerate(c): incidence[k,triple]=1
    return c,incidence


def parts(f, z):
    result=[]
    for rid, idx in f.groupby('race_id',sort=False).indices.items():
        one=f.iloc[idx]; c,_=support(len(idx))
        truth=np.flatnonzero(one.finish_position.to_numpy()<=3)
        assert len(truth)==3
        target=np.flatnonzero((c==truth).all(axis=1)).item()
        energy=np.sort(z[idx][c],axis=1).sum(axis=1)
        result.append((rid,idx,energy,target))
    return result


def temperature(f,z):
    ps=parts(f,z);width=max(len(p[2]) for p in ps)
    a=np.full((len(ps),width),-np.inf);truth=[]
    for i,(_,_,e,t) in enumerate(ps):a[i,:len(e)]=e;truth.append(e[t])
    result=minimize_scalar(lambda t:float(np.mean(logsumexp(a/t,axis=1)-np.array(truth)/t)),bounds=(.35,4),method='bounded')
    assert result.success
    return float(result.x)


def evaluate(f,z,tau,variant):
    races=[];runners=[];tickets=[]
    for rid,idx,e,target in parts(f,z):
        one=f.iloc[idx]; n=len(one);c,incidence=support(n)
        logq=e/tau-logsumexp(e/tau); q=np.exp(logq); p=q@incidence
        assert np.isclose(p.sum(),3,atol=1e-10) and np.isclose(q.sum(),1,atol=1e-12)
        assert one.horse_number.is_monotonic_increasing
        y=one.finish_position.le(3).to_numpy(float);pc=np.clip(p,1e-12,1-1e-12)
        ll=-y*np.log(pc)-(1-y)*np.log1p(-pc);brier=(p-y)**2
        order=np.argsort(-z[idx],kind='stable');best=np.argsort(-e,kind='stable')[:6]
        truth=set(c[target]); r=dict(race_id=rid,race_date=one.race_date.iloc[0],year=int(one.year.iloc[0]),variant=variant,
             distance_m=int(one.distance_m.iloc[0]),grade_raw=one.grade_raw.iloc[0],field_n=n,
             any_no_history=bool(one.observed_starts.eq(0).any()),any_low_history=bool(one.observed_starts.lt(5).any()),
             any_no_same_time=bool(one.same_valid_times.eq(0).any()),
             log_loss=float(ll.mean()),brier=float(brier.mean()),trio_nll=float(-logq[target]),
             six_combo_hit=int(target in best),six_combo_mass=float(q[best].sum()))
        for k in [3,4,5,6]:
            r[f'top{k}_capture']=len(truth&set(order[:k]))/3
            r[f'top{k}_all3']=int(truth<=set(order[:k]))
        races.append(r)
        for i,row in enumerate(one.to_dict('records')):
            runners.append({k:row[k] for k in ['api_record_id','race_id','race_date','year','distance_m','grade_raw','horse_id','horse_number','observed_starts','same_valid_times','field_n']} |
                  dict(variant=variant,score=float(z[idx][i]),p_top3=float(p[i]),y=int(y[i]),log_loss=float(ll[i]),brier=float(brier[i])))
        for rank,j in enumerate(best,1):
            tickets.append(dict(race_id=rid,variant=variant,selection_rank=rank,
               numbers=','.join(map(str,one.horse_number.iloc[c[j]].astype(int))),probability=float(q[j]),hit=int(j==target)))
    return pd.DataFrame(races),pd.DataFrame(runners),pd.DataFrame(tickets)


def fit(f,variant,year):
    cols=CONTRACTS[variant];x=f[cols].copy();vocab={}
    train=f.year.between(2017,year-3);valid=f.year.eq(year-2);cal=f.year.eq(year-1);test=f.year.eq(year)
    assert all(mask.any() for mask in [train,valid,cal,test])
    for c in CATS:
        vocab[c]=sorted(f.loc[train,c].dropna().unique().tolist())
        x[c]=pd.Categorical(x[c],categories=vocab[c])
    y=f.finish_position.le(3).astype(int);weight=1/f.field_n
    def ds(mask):return lgb.Dataset(x[mask],label=y[mask],weight=weight[mask],free_raw_data=False)
    initial=lgb.train(PARAMS,ds(train),num_boost_round=200,valid_sets=[ds(valid)],callbacks=[lgb.early_stopping(25,verbose=False)])
    model=lgb.train(PARAMS,ds(train|valid),num_boost_round=initial.best_iteration)
    folder=OUT/f'{variant}_{year}';folder.mkdir(exist_ok=False)
    model.save_model(str(folder/'top3.txt'))
    zc=model.predict(x[cal],raw_score=True);zt=model.predict(x[test],raw_score=True)
    tau=temperature(f[cal].reset_index(drop=True),zc)
    meta=dict(variant=variant,evaluation_year=year,features=cols,vocabulary=vocab,trees=int(initial.best_iteration),
              training_min=f.loc[train,'race_date'].min(),initial_training_max=f.loc[train,'race_date'].max(),
              early_stopping_min=f.loc[valid,'race_date'].min(),refit_max=f.loc[valid,'race_date'].max(),
              calibration_min=f.loc[cal,'race_date'].min(),calibration_max=f.loc[cal,'race_date'].max(),
              evaluation_min=f.loc[test,'race_date'].min(),evaluation_max=f.loc[test,'race_date'].max(),
              train_races=f.loc[train|valid,'race_id'].nunique(),calibration_races=f.loc[cal,'race_id'].nunique(),
              test_races=f.loc[test,'race_id'].nunique(),tau=tau,model_sha256=sha(folder/'top3.txt'),
              gain=dict(zip(cols,map(float,model.feature_importance(importance_type='gain')))))
    save(folder/'model_meta.json',meta)
    save(folder/'calibration_scores.json',dict(ids=f.loc[cal,'api_record_id'].astype(int).tolist(),score=zc.tolist()))
    print(variant,year,'trees',meta['trees'],'tau',round(tau,4),flush=True)
    return evaluate(f[test].reset_index(drop=True),zt,tau,variant)


def check_prepared():
    lock=json.loads((OUT/'prepared_lock.json').read_text())
    for p,h in lock['references'].items():assert sha(ROOT/p)==h,p
    for p,h in lock['artifacts'].items():assert sha(OUT/p)==h,p
    check_protected(lock['protected'])
    return lock


def bootstrap(a,b,col):
    q=a[['race_id','race_date',col]].merge(b[['race_id',col]],on='race_id',suffixes=('','_base'),validate='one_to_one')
    assert len(q)==len(a)==len(b)
    q['delta']=q[col]-q[col+'_base'];g=q.groupby('race_date').delta.agg(['sum','size'])
    rng=np.random.default_rng(SEED);idx=rng.integers(0,len(g),size=(2000,len(g)))
    boot=g['sum'].to_numpy()[idx].sum(axis=1)/g['size'].to_numpy()[idx].sum(axis=1)
    return dict(delta=float(q.delta.mean()),lo=float(np.quantile(boot,.025)),hi=float(np.quantile(boot,.975)),races=len(q),days=len(g))


METRICS=['log_loss','brier','trio_nll','top3_capture','top4_capture','top5_capture','top6_capture','top5_all3','six_combo_hit']


def summaries(r,runners):
    rows=[];pairs=[]
    groups=[('all','all',r)]+[('year',str(k),g) for k,g in r.groupby('year')]+[('distance',str(k),g) for k,g in r.groupby('distance_m')]+[('grade',str(k),g) for k,g in r.groupby('grade_raw',dropna=False)]
    for col in ['any_no_history','any_low_history','any_no_same_time']:
        groups += [(col,str(k),g) for k,g in r.groupby(col)]
    for kind,key,g in groups:
        for v,one in g.groupby('variant'):
            rows.append(dict(group=kind,value=key,variant=v,races=len(one),days=one.race_date.nunique(),**{m:float(one[m].mean()) for m in METRICS}))
        for va,vb in [('J1','J0'),('J0','uniform')]:
            a=g[g.variant.eq(va)];b=g[g.variant.eq(vb)]
            for m in METRICS:
                pairs.append(dict(group=kind,value=key,comparison=f'{va}-{vb}',metric=m,**bootstrap(a,b,m)))
    write_csv(OUT/'metrics_by_group.csv',pd.DataFrame(rows))
    write_csv(OUT/'paired_differences.csv',pd.DataFrame(pairs))
    runner_rows=[]
    for v,g in runners.groupby('variant'):
        for col in ['observed_starts','same_valid_times']:
            bins=pd.cut(g[col],[-1,0,4,np.inf],labels=['0','1_4','5_plus'])
            for key,one in g.groupby(bins,observed=True):
                runner_rows.append(dict(variant=v,group=col,value=str(key),rows=len(one),races=one.race_id.nunique(),
                      log_loss=float(one.log_loss.mean()),brier=float(one.brier.mean()),predicted=float(one.p_top3.mean()),actual=float(one.y.mean())))
        runner_rows.append(dict(variant=v,group='all',value='all',rows=len(g),races=g.race_id.nunique(),log_loss=float(g.log_loss.mean()),brier=float(g.brier.mean()),predicted=float(g.p_top3.mean()),actual=float(g.y.mean())))
    write_csv(OUT/'runner_metrics.csv',pd.DataFrame(runner_rows))
    bins=np.arange(0,1.0001,.1);cal=[]
    for v,g in runners.groupby('variant'):
        for key,one in g.groupby(pd.cut(g.p_top3,bins,include_lowest=True),observed=True):
            w=1/one.field_n
            cal.append(dict(variant=v,bin=str(key),rows=len(one),races=one.race_id.nunique(),
                predicted=float(np.average(one.p_top3,weights=w)),actual=float(np.average(one.y,weights=w))))
    write_csv(OUT/'calibration_bins.csv',pd.DataFrame(cal))


def train():
    lock=check_prepared()
    assert (OUT/'preflight_verification.json').exists(), 'Independent preflight required'
    assert json.loads((OUT/'preflight_verification.json').read_text())['passed']
    f=pd.read_parquet(OUT/'features.parquet')
    results=[]
    for y in [2024,2025,2026]:
        test=f[f.year.eq(y)].reset_index(drop=True)
        results.append(evaluate(test,np.zeros(len(test)),1.,'uniform'))
        for variant in CONTRACTS:results.append(fit(f,variant,y))
    races=pd.concat([x[0] for x in results],ignore_index=True)
    runners=pd.concat([x[1] for x in results],ignore_index=True)
    tickets=pd.concat([x[2] for x in results],ignore_index=True)
    write_csv(OUT/'race_metrics.csv',races)
    runners.to_parquet(OUT/'runner_predictions.parquet',index=False)
    write_csv(OUT/'six_combinations.csv',tickets)
    summaries(races,runners)
    check_protected(lock['protected'])
    save(OUT/'training_completion.json',dict(models=6,production_changed=False,database_changed=False,
         results_sha256={p.name:sha(p) for p in [OUT/'race_metrics.csv',OUT/'runner_predictions.parquet',OUT/'six_combinations.csv']},
         preflight_sha256=sha(OUT/'preflight_verification.json')))
    print(races.groupby('variant')[METRICS].mean().to_string(),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','train']);args=p.parse_args()
    (prepare if args.phase=='prepare' else train)()
