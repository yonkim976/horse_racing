"""Remove all explicit rider inputs while retaining calibrated moisture history."""
from pathlib import Path
import importlib.util
import argparse
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261005_moisture_finish_v1'
spec=importlib.util.spec_from_file_location('no_rider_moisture_parent',PARENT/'run.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
PRE=M.PRE;BASE=M.BASE;KEY=M.KEY

def cfg():return json.loads((HERE/'config.json').read_text())
def dump(p,v):BASE.save_json(p,v)

def rider_columns(columns):
    return [col for col in columns if 'jockey' in col or col in {'pair_history_count','pair_early_count','pair_aggression'}]

def features():
    raw=pd.read_parquet(M.PARENT/'outputs/features.parquet')
    adjusted=pd.read_parquet(PARENT/'outputs/adjusted_features.parquet')
    frame=M.construct(raw,adjusted,'augment')
    return frame.drop(columns=rider_columns(frame.columns))

def prepare():
    if OUT.exists():raise FileExistsError('Existing experiment')
    paths=[HERE/'run.py',HERE/'PLAN.md',HERE/'config.json',PARENT/'run.py',M.PARENT/'run.py',BASE.HERE/'run.py',
           ROOT/'config/prediction_model_registry.json',ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb',
           M.PARENT/'outputs/features.parquet',M.STACK/'outputs/labels.parquet']
    paths += [PARENT/'outputs'/n for n in ['adjusted_features.parquet','feature_contract.json','aligned_race_metrics.csv',
        'runner_predictions.parquet','recommendations.parquet','verification.json','report_verification.json']]
    for meet in (1,3):
        for year in (2024,2025,2026):
            paths += [PARENT/'outputs/models'/f'{meet}_{year}_augment'/n for n in ['top3.txt','metadata.json','joint.json']]
    hashes={str(p.relative_to(ROOT)):BASE.sha(p) for p in paths}
    original=json.loads((PARENT/'outputs/feature_contract.json').read_text())['augment']
    removed=rider_columns(original);contract=[col for col in original if col not in removed]
    if len(removed)!=26 or len(contract)!=258:raise ValueError('Unexpected rider contract')
    frame=features()
    if any(col not in frame for col in contract):raise ValueError('Missing retained input')
    if rider_columns(contract):raise ValueError('Rider input remains')
    OUT.mkdir();dump(OUT/'feature_contract.json',dict(no_jockey=contract,removed=removed))
    dump(OUT/'audit.json',dict(inputs=hashes,feature_contract_sha256=BASE.sha(OUT/'feature_contract.json'),
                             rows=len(frame),production_changed=False))
    print('Prepared',len(frame),'rows;',len(removed),'removed;',len(contract),'retained',flush=True)

def check_inputs():
    audit=json.loads((OUT/'audit.json').read_text())
    for p,h in audit['inputs'].items():
        if BASE.sha(ROOT/p)!=h:raise ValueError('Changed input: '+p)
    if BASE.sha(OUT/'feature_contract.json')!=audit['feature_contract_sha256']:raise ValueError('Changed contract')

def train():
    check_inputs();c=cfg()
    if (OUT/'summary.json').exists():raise FileExistsError('Completed experiment')
    frame=features().merge(pd.read_parquet(M.STACK/'outputs/labels.parquet'),on=KEY,validate='one_to_one')
    contract=json.loads((OUT/'feature_contract.json').read_text())['no_jockey']
    r=pd.read_csv(PARENT/'outputs/aligned_race_metrics.csv',low_memory=False)
    p=pd.read_parquet(PARENT/'outputs/runner_predictions.parquet');t=pd.read_parquet(PARENT/'outputs/recommendations.parquet')
    def inherited(f):
        f=f[f.variant.isin(['augment','augment_joint'])].copy()
        f['variant']=f.variant.replace({'augment':'with_jockey','augment_joint':'with_jockey_joint'})
        return f
    rows=[inherited(r)];runners=[inherited(p)];tickets=[inherited(t)]
    rawpred=p[p.variant.eq('raw')].sort_values(KEY).set_index(['race_key','program_no']).prob_top3
    for meet in c['venues']:
        f=frame[frame.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            print('Train',meet,year,'no_jockey',flush=True)
            path=OUT/'models'/f'{meet}_{year}_no_jockey'
            score,meta=PRE.direct_train(f,contract,year,c,path)
            cal=f.year.eq(year-1);test=f.year.eq(year)
            parts=M.race_parts(f[cal].reset_index(drop=True),score[cal]);temp=PRE.temperature(parts,c)
            pair=PRE.residual_fit(parts,temp,c);pair.update(training_year=year-1,evaluation_year=year)
            thresholds={v:M.calibration_mass(parts,temp,j) for v,j in [('no_jockey',None),('no_jockey_joint',pair)]}
            meta.update(temperature=temp,thresholds=thresholds,explicit_rider_features=False)
            dump(path/'metadata.json',meta);dump(path/'joint.json',pair)
            for v,j in [('no_jockey',None),('no_jockey_joint',pair)]:
                one,runner,combo=M.evaluate(f[test].reset_index(drop=True),score[test],temp,j,v,thresholds[v],rawpred)
                rows.append(one);runners.append(runner);tickets.append(combo)
            print('Evaluated',meet,year,flush=True)
    r=pd.concat(rows,ignore_index=True);p=pd.concat(runners,ignore_index=True);t=pd.concat(tickets,ignore_index=True)
    r.to_csv(OUT/'race_metrics.csv',index=False);p.to_parquet(OUT/'runner_predictions.parquet',index=False);t.to_parquet(OUT/'recommendations.parquet',index=False)
    summarize(r,c);check_inputs()
    dump(OUT/'summary.json',dict(new_heads=6,new_pair_models=6,retained_features=258,removed_rider_features=26,
         production_changed=False,independent_future_test=False,
         artifacts={str(p.relative_to(OUT)):BASE.sha(p) for p in OUT.rglob('*') if p.is_file()}))
    print('Completed',flush=True)

def summarize(r,c):
    rows=[]
    for (meet,variant),g in r.groupby(['meet','variant']):
        for period,s in [('all',g)]+[(str(y),z) for y,z in g.groupby('evaluation_year')]:
            keep=s[s.selected.eq(1)]
            row=dict(meet=int(meet),variant=variant,period=period,races=len(s),hits=int(s.trio6_hit.sum()),
                     selected=len(keep),selected_hits=int(keep.trio6_hit.sum()),selected_hit=float(keep.trio6_hit.mean()))
            for col in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium','top7_contains_podium',
                        'rescued_outsiders','lost_insiders','trio6_probability']:row[col]=float(s[col].mean())
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    rng=np.random.default_rng(c['bootstrap_seed']);differences=[]
    for meet in (0,1,3):
        for a,b in [('with_jockey','no_jockey'),('with_jockey_joint','no_jockey_joint')]:
            mask=r.meet.eq(meet) if meet else np.ones(len(r),bool)
            paired=r[mask&r.variant.eq(a)].merge(r[mask&r.variant.eq(b)],on='race_key',suffixes=('_a','_b'),validate='one_to_one')
            for metric in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium','rescued_outsiders']:
                delta=paired[metric+'_b']-paired[metric+'_a']
                daily=pd.DataFrame({'date':paired.race_date_a,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
                draws=daily[rng.integers(0,len(daily),size=(2000,len(daily)))].sum(axis=1)
                differences.append(dict(meet=meet,base=a,candidate=b,metric=metric,races=len(paired),difference=float(delta.mean()),
                                        date_bootstrap_95_interval=np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist()))
    dump(OUT/'paired_differences.json',differences)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','train']);args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
