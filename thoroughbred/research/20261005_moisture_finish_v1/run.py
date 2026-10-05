"""Fixed moisture-history ablation; no production writes or current going input."""
from pathlib import Path
from functools import lru_cache
import argparse
import importlib.util
import json
import itertools
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_outsider_joint_v1'
MOIST=HERE.parent/'20261003_pace_gate_moisture_v2'
STACK=HERE.parent/'20261004_pace_finish_stack_v1'
spec=importlib.util.spec_from_file_location('moisture_finish_parent',PARENT/'run.py')
PRE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PRE)
BASE=PRE.BASE;KEY=PRE.KEY
REPLACE=['last_record_index','last3_record_index_mean','last5_record_index_mean','last10_record_index_mean',
         'last5_record_index_best','last10_record_index_best','last5_record_index_count','last10_record_index_count',
         'last5_record_index_std','record_index_change','same_distance_last_finish','same_distance_last5_finish_mean',
         'relative_last3_record_index_mean']
DERIVED=['upside_best_gap','upside_best_relative','upside_best_rank','upside_last_rank',
         'upside_low_history_best','upside_growth','upside_grade_best']
SUPPORT=['moist_last_correction_seconds','moist_last5_supported_fraction','moist_last5_abs_correction_mean']

def cfg():return json.loads((HERE/'config.json').read_text())
def dump(p,v):BASE.save_json(p,v)

@lru_cache(maxsize=32)
def support(n):
    sets=np.array(list(itertools.combinations(range(n),3)),int)
    incidence=np.zeros((len(sets),n))
    for i,s in enumerate(sets):incidence[i,s]=1
    return sets,incidence

def history_support(f,records):
    h=records.sort_values(['horse_id','race_date']).copy()
    if h.duplicated(['horse_id','race_date']).any():raise ValueError('Ambiguous historical start')
    valid=h.original_finish_valid.notna()
    h['valid_support']=h.supported.astype(float).where(valid)
    h['valid_delta']=h.correction_seconds.where(valid)
    h['absolute_delta']=h.valid_delta.abs()
    groups=h.groupby('horse_id',sort=False)
    states=h[['horse_id','race_date']].rename(columns={'race_date':'moist_support_source_date'})
    states['moist_last_correction_seconds']=h.valid_delta
    for source,dest in [('valid_support',SUPPORT[1]),('absolute_delta',SUPPORT[2])]:
        states[dest]=groups[source].rolling(5,min_periods=1).mean().reset_index(level=0,drop=True)
    states['available_date']=states.moist_support_source_date+pd.Timedelta(days=2)
    query=f[KEY+['race_date']].copy();query['_row']=np.arange(len(f))
    joined=pd.merge_asof(query.sort_values('race_date'),states.sort_values('available_date'),
                         left_on='race_date',right_on='available_date',by='horse_id',direction='backward')
    joined=joined.sort_values('_row').reset_index(drop=True)
    if not (joined.moist_support_source_date.isna()|joined.moist_support_source_date.le(joined.race_date-pd.Timedelta(days=2))).all():
        raise ValueError('Correction support history leak')
    return joined[SUPPORT+['moist_support_source_date']]

def construct(raw,adjustment,variant):
    if not raw[KEY].equals(adjustment[KEY]):raise ValueError('Incorrect feature alignment')
    result=raw.copy()
    if variant=='replace':
        for col in REPLACE+DERIVED:result[col]=adjustment[col]
    elif variant=='augment':
        for col in REPLACE+DERIVED:result['moist_'+col]=adjustment[col]
        for col in SUPPORT:result[col]=adjustment[col]
    else:raise ValueError('Unknown candidate')
    return result

def prepare():
    if OUT.exists():raise FileExistsError('Completed/prepared experiment')
    sources=[HERE/'PLAN.md',HERE/'config.json',HERE/'run.py',PARENT/'run.py',MOIST/'run.py',BASE.HERE/'run.py',
             ROOT/'config/prediction_model_registry.json',ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb']
    sources += [PARENT/'outputs'/n for n in ['features.parquet','feature_contract.json','runner_predictions.parquet',
                'race_metrics.csv','recommendations.parquet','verification.json']]
    sources += [MOIST/'outputs'/n for n in ['moisture_features.parquet','adjusted_records.parquet','effects.parquet',
                'environment_fits.json','record_references.csv','verification.json','data_audit.json']]
    sources += [MOIST/'config.json',STACK/'outputs/labels.parquet']
    for meet in (1,3):
        for year in (2024,2025,2026):
            sources += [PARENT/'outputs/models'/f'{meet}_{year}_upside'/n for n in ['top3.txt','metadata.json','joint.json']]
    hashes={str(p.relative_to(ROOT)):BASE.sha(p) for p in sources}
    raw=pd.read_parquet(PARENT/'outputs/features.parquet')
    adjusted=pd.read_parquet(MOIST/'outputs/moisture_features.parquet')
    corrected=raw[KEY].merge(adjusted[KEY+REPLACE],on=KEY,validate='one_to_one')
    if len(corrected)!=len(raw):raise ValueError('Missing corrected records')
    temp=raw.copy()
    for col in REPLACE:temp[col]=corrected[col]
    temp,_=PRE.upside_features(temp)
    for col in DERIVED:corrected[col]=temp[col]
    for col in [c for c in raw if c.startswith('upside_') and c not in DERIVED]:
        pd.testing.assert_series_equal(raw[col],temp[col],check_exact=True)
    hist=history_support(raw,pd.read_parquet(MOIST/'outputs/adjusted_records.parquet'))
    corrected=pd.concat([corrected,hist],axis=1)
    contract=json.loads((PARENT/'outputs/feature_contract.json').read_text())['upside']
    contracts={'replace':contract,'augment':contract+['moist_'+col for col in REPLACE+DERIVED]+SUPPORT}
    forbidden={'outcome','race_key','program_no','horse_id','race_date','S1F_rank','G3F_rank','moist_support_source_date'}
    for cols in contracts.values():
        if len(set(cols))!=len(cols) or set(cols)&forbidden:raise ValueError('Invalid contract')
    OUT.mkdir();corrected.to_parquet(OUT/'adjusted_features.parquet',index=False)
    dump(OUT/'feature_contract.json',contracts)
    changes=[]
    for col in REPLACE+DERIVED:
        unequal=~np.isclose(raw[col].to_numpy(float),corrected[col].to_numpy(float),equal_nan=True)
        for (meet,year),idx in raw.groupby(['meet','year']).indices.items():
            changes.append(dict(meet=int(meet),year=int(year),column=col,runners=len(idx),changed=int(unequal[idx].sum())))
    pd.DataFrame(changes).to_csv(OUT/'feature_changes.csv',index=False)
    dump(OUT/'audit.json',dict(inputs=hashes,rows=len(raw),races=int(raw.race_key.nunique()),production_changed=False,
         prepared_hashes={p.name:BASE.sha(p) for p in OUT.iterdir() if p.is_file()}))
    print('Prepared',len(raw),'runners; features', {k:len(v) for k,v in contracts.items()},flush=True)

def check_inputs():
    audit=json.loads((OUT/'audit.json').read_text())
    for p,h in audit['inputs'].items():
        if BASE.sha(ROOT/p)!=h:raise ValueError('Changed source: '+p)
    for p,h in audit['prepared_hashes'].items():
        if BASE.sha(OUT/p)!=h:raise ValueError('Changed prepared artifact: '+p)

def race_parts(f,raw):
    result=[]
    for rid,idx in f.groupby('race_key',sort=False).indices.items():
        g=f.iloc[idx];sets,_=support(len(g));truth=set(np.flatnonzero(g.outcome.le(3)))
        target=next(i for i,s in enumerate(sets) if set(s)==truth)
        result.append(dict(race_key=rid,idx=idx,energy=raw[idx][sets].sum(axis=1),X=PRE.pair_design(g),target=target))
    return result

def evaluate(f,raw,temperature,pair,variant,threshold,baseline):
    rows=[];runners=[];tickets=[]
    for p in race_parts(f,raw):
        g=f.iloc[p['idx']];sets,incidence=support(len(g));n=len(g)
        energy=p['energy']/(temperature if pair is None else pair['temperature'])
        if pair is not None:energy+=((p['X']-pair['mean'])/pair['scale'])@np.array(pair['coefficients'])
        q=np.exp(energy-logsumexp(energy));m=q@incidence
        best=np.argsort(-q,kind='stable')[:6];mass=float(q[best].sum());truth=set(sets[p['target']])
        rank=np.argsort(-m,kind='stable');base_rank=np.argsort(-baseline.loc[p['race_key']].to_numpy(),kind='stable')
        outside=truth-set(base_rank[:5]);inside=truth&set(base_rank[:5])
        row=dict(race_key=p['race_key'],meet=int(g.meet.iloc[0]),evaluation_year=int(g.year.iloc[0]),race_date=str(g.race_date.iloc[0].date()),
                 variant=variant,field_size=n,distance_m=float(g.distance_m.iloc[0]),grade=float(g.grade.iloc[0]),
                 low_history_present=bool(g.history_count.lt(5).any()),trio_nll=float(-np.log(q[p['target']])),
                 top3_brier=float(np.mean((m-g.outcome.le(3).to_numpy())**2)),trio6_hit=int(p['target'] in best),
                 trio6_probability=mass,selected=int(mass>=threshold),baseline_outsiders=len(outside),
                 rescued_outsiders=len(outside&set(rank[:5])),lost_insiders=len(inside-set(rank[:5])),
                 top3_first_hit=int(rank[0] in truth),joint_error=float(abs(q.sum()-1)))
        for k in (3,5,6,7):row[f'top{k}_contains_podium']=int(truth<=set(rank[:k]))
        rows.append(row)
        for i,(_,entry) in enumerate(g.iterrows()):
            runners.append({**{key:entry[key] for key in KEY},'meet':int(entry.meet),'evaluation_year':int(entry.year),
                            'variant':variant,'outcome':int(entry.outcome),'raw_top3_score':float(raw[p['idx']][i]),'prob_top3':float(m[i])})
        for i,j in enumerate(best,1):
            tickets.append(dict(race_key=p['race_key'],meet=int(g.meet.iloc[0]),evaluation_year=int(g.year.iloc[0]),variant=variant,
                                selection_rank=i,programs=','.join(map(str,sorted(g.program_no.iloc[sets[j]].astype(int)))),
                                probability=float(q[j]),hit=int(j==p['target'])))
    return pd.DataFrame(rows),pd.DataFrame(runners),pd.DataFrame(tickets)

def calibration_mass(parts,temp,pair):
    masses=[]
    for p in parts:
        e=p['energy']/(temp if pair is None else pair['temperature'])
        if pair is not None:e+=((p['X']-pair['mean'])/pair['scale'])@np.array(pair['coefficients'])
        q=np.exp(e-logsumexp(e));masses.append(float(np.sort(q)[-6:].sum()))
    return float(np.median(masses))

def baseline_outputs():
    races=pd.read_csv(PARENT/'outputs/race_metrics.csv');rp=pd.read_parquet(PARENT/'outputs/runner_predictions.parquet')
    rec=pd.read_parquet(PARENT/'outputs/recommendations.parquet')
    races=races[races.variant.isin(['upside','upside_joint'])].copy()
    races=races.rename(columns={'top6_trio_hit':'trio6_hit','top6_trio_probability':'trio6_probability'})
    rp=rp[rp.variant.isin(['upside','upside_joint'])].copy();rec=rec[rec.variant.isin(['upside','upside_joint'])].copy()
    for frame in [races,rp,rec]:frame['variant']=frame.variant.replace({'upside':'raw','upside_joint':'raw_joint'})
    return races,rp,rec

def train():
    check_inputs();c=cfg()
    if (OUT/'summary.json').exists():raise FileExistsError('Completed experiment')
    raw=pd.read_parquet(PARENT/'outputs/features.parquet')
    adjustment=pd.read_parquet(OUT/'adjusted_features.parquet')
    labels=pd.read_parquet(STACK/'outputs/labels.parquet')
    contracts=json.loads((OUT/'feature_contract.json').read_text())
    oldr,oldp,oldc=baseline_outputs();races=[oldr];runners=[oldp];tickets=[oldc]
    rawpred=oldp[oldp.variant.eq('raw')].sort_values(KEY).set_index(['race_key','program_no']).prob_top3
    for meet in c['venues']:
        mask=raw.meet.eq(meet)
        for candidate in c['candidates']:
            f=construct(raw.loc[mask].reset_index(drop=True),adjustment.loc[mask].reset_index(drop=True),candidate)
            f=f.merge(labels,on=KEY,validate='one_to_one')
            for year in c['evaluation_years']:
                print('Train',meet,year,candidate,flush=True)
                path=OUT/'models'/f'{meet}_{year}_{candidate}'
                if (path/'metadata.json').exists():
                    meta=json.loads((path/'metadata.json').read_text())
                    if BASE.sha(path/'top3.txt')!=meta['model_sha256']:raise ValueError('Changed head')
                    x=f[meta['features']].copy()
                    for col,vocab in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=vocab)
                    score=np.full(len(f),np.nan);future=f.year.isin([year-1,year])
                    score[future]=lgb.Booster(model_file=str(path/'top3.txt')).predict(x[future],raw_score=True,num_threads=4)
                else:score,meta=PRE.direct_train(f,contracts[candidate],year,c,path)
                cal=f.year.eq(year-1);test=f.year.eq(year)
                parts=race_parts(f[cal].reset_index(drop=True),score[cal]);temp=PRE.temperature(parts,c)
                pair=PRE.residual_fit(parts,temp,c);pair.update(training_year=year-1,evaluation_year=year)
                thresholds={candidate:calibration_mass(parts,temp,None),candidate+'_joint':calibration_mass(parts,temp,pair)}
                meta.update(temperature=temp,thresholds=thresholds,calibration_year=year-1)
                dump(path/'metadata.json',meta);dump(path/'joint.json',pair)
                for variant,joint in [(candidate,None),(candidate+'_joint',pair)]:
                    r,p,t=evaluate(f[test].reset_index(drop=True),score[test],temp,joint,variant,thresholds[variant],rawpred)
                    races.append(r);runners.append(p);tickets.append(t)
                print('Evaluated',meet,year,candidate,flush=True)
    r=pd.concat(races,ignore_index=True);p=pd.concat(runners,ignore_index=True);t=pd.concat(tickets,ignore_index=True)
    r.to_csv(OUT/'race_metrics.csv',index=False);p.to_parquet(OUT/'runner_predictions.parquet',index=False);t.to_parquet(OUT/'recommendations.parquet',index=False)
    summarize(r,c);check_inputs()
    dump(OUT/'summary.json',dict(new_heads=12,new_pair_models=12,production_changed=False,independent_future_test=False,
         artifacts={str(p.relative_to(OUT)):BASE.sha(p) for p in OUT.rglob('*') if p.is_file()}))
    print('Completed',flush=True)

def summarize(r,c):
    rows=[]
    for (meet,variant),g in r.groupby(['meet','variant']):
        for period,s in [('all',g)]+[(str(y),z) for y,z in g.groupby('evaluation_year')]:
            keep=s[s.selected.eq(1)]
            row=dict(meet=int(meet),variant=variant,period=period,races=len(s),hits=int(s.trio6_hit.sum()),
                     selected=len(keep),selected_hits=int(keep.trio6_hit.sum()),selected_hit=float(keep.trio6_hit.mean()))
            for col in ['trio6_hit','trio_nll','top3_brier','top3_first_hit','top5_contains_podium','top7_contains_podium',
                        'trio6_probability','baseline_outsiders','rescued_outsiders','lost_insiders']:row[col]=float(s[col].mean())
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pairs=[('raw','replace'),('raw','augment'),('raw_joint','replace_joint'),('raw_joint','augment_joint'),
           ('replace','replace_joint'),('augment','augment_joint')]
    rng=np.random.default_rng(c['bootstrap_seed']);differences=[]
    for meet in (1,3):
        for a,b in pairs:
            p=r[r.meet.eq(meet)&r.variant.eq(a)].merge(r[r.meet.eq(meet)&r.variant.eq(b)],on='race_key',suffixes=('_a','_b'),validate='one_to_one')
            for metric in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium','rescued_outsiders']:
                delta=p[metric+'_b']-p[metric+'_a']
                daily=pd.DataFrame({'date':p.race_date_a,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
                samples=daily[rng.integers(0,len(daily),size=(c['bootstrap_draws'],len(daily)))].sum(axis=1)
                ci=np.quantile(samples[:,0]/samples[:,1],[.025,.975])
                differences.append(dict(meet=meet,base=a,candidate=b,metric=metric,difference=float(delta.mean()),date_bootstrap_95_interval=ci.tolist()))
    dump(OUT/'paired_differences.json',differences)
    calibration=[]
    for (meet,variant),g in r.groupby(['meet','variant']):
        for bin,s in g.groupby(np.minimum((g.trio6_probability*10).astype(int),9)):
            calibration.append(dict(meet=int(meet),variant=variant,bin=int(bin),races=len(s),predicted=float(s.trio6_probability.mean()),actual=float(s.trio6_hit.mean())))
    pd.DataFrame(calibration).to_csv(OUT/'trio6_calibration.csv',index=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','train']);args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
