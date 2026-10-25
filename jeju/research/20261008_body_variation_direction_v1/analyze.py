"""Retrospective personal body-change magnitude versus record direction."""
from pathlib import Path
import importlib.util
import json
import bisect
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2'
sp=importlib.util.spec_from_file_location('body_prior',H.parent/'20261008_body_change_optimum_sex_v2/analyze.py');b=importlib.util.module_from_spec(sp);sp.loader.exec_module(b);a=b.a
PLAN=json.loads((H/'PLAN.json').read_text())
GROUPS=['gain_within','gain_above','loss_within','loss_above']
def save(name,value):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(b.clean(value),f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,df):
    with (H/name).open('x',encoding='utf-8') as f:df.to_csv(f,index=False)
def info(g):return {'rows':len(g),'races':g.race_id.nunique(),'dates':g.race_date.nunique(),'horses':g.horse_id.nunique()}
def group(delta,threshold):
    return np.select([delta.eq(0),(delta>0)&(delta<=threshold),(delta>0)&(delta>threshold),(delta<0)&(-delta<=threshold),(delta<0)&(-delta>threshold)],['zero']+GROUPS,default='unavailable')
def load():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'pair_lineage.csv',PRE/'source_lineage.csv',PRE/'input_audit.json',PRE/'analyze.py',H.parent/'20261008_body_change_optimum_sex_v2/analyze.py',ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/AGENTS.md',H.parent/'RESEARCH_PUBLICATION_POLICY.md']
    save('source_manifest.json',[{'path':str(p),'bytes':p.stat().st_size,'sha256':a.sha(p)} for p in refs]);dbsha=a.sha(a.old.DB);assert dbsha==json.loads((PRE/'input_audit.json').read_text())['database_sha256']
    p=pd.read_csv(PRE/'pair_lineage.csv',dtype={'horse_id':str});p=p.sort_values(['horse_id','race_date','pair_id']).reset_index(drop=True)
    assert len(p)==27230 and p.pair_id.is_unique and not p.horse_id.eq('3005648').any()
    histories=[]
    for mode,keys in [('personal',['horse_id']),('same_distance',['horse_id','distance'])]:
        stats=[]
        for _,g in p.groupby(keys,sort=False):
            dates=g.race_date.to_numpy();ids=g.pair_id.to_numpy();values=g.body_change_kg.abs().to_numpy()
            for r in g.itertuples():
                cutoff=(pd.Timestamp(r.race_date)-pd.Timedelta(days=2)).strftime('%Y-%m-%d');end=bisect.bisect_right(dates,cutoff);start=max(0,end-10);v=values[start:end]
                history_ids=ids[start:end].astype(int).tolist();assert r.pair_id not in history_ids
                stats.append({'pair_id':r.pair_id,mode+'_mean':v.mean() if len(v)>=5 else np.nan,mode+'_sd':v.std(ddof=1) if len(v)>=5 else np.nan,mode+'_n':len(v)})
                histories.append({'mode':mode,'pair_id':r.pair_id,'horse_id':r.horse_id,'distance':r.distance,'cutoff':cutoff,'history_pair_ids':history_ids})
        p=p.merge(pd.DataFrame(stats),on='pair_id',validate='one_to_one')
    p['previous_body10']=(p.previous_body_kg-278)/10;p['previous_body2']=p.previous_body10**2
    p['group']=group(p.body_change_kg,p.personal_mean);p['large_group']=group(p.body_change_kg,p.personal_mean+p.personal_sd);p['same_distance_group']=group(p.body_change_kg,p.same_distance_mean)
    csv('pair_features.csv',p);save('history_lineage.json',histories)
    save('input_audit.json',{'source_pairs':len(p),'personal_history_supported_pairs':p.personal_mean.notna().sum(),'same_distance_history_supported_pairs':p.same_distance_mean.notna().sum(),'personal_history_missing_by_year':p.assign(missing=p.personal_mean.isna()).groupby('year').missing.sum().to_dict(),'database_sha256':dbsha,'last_date':p.race_date.max(),'current_body_is_retrospective':True})
    return p,dbsha
def summarize(p):
    typical=[];raw=[]
    for period,(lo,hi) in PLAN['periods'].items():
        pp=p[p.year.between(lo,hi)]
        for distance,g in [(0,pp)]+list(pp.groupby('distance')):
            v=g.body_change_kg;ab=v.abs();typical.append({'period':period,'distance':distance,**info(g),'signed_mean_kg':v.mean(),'absolute_mean_kg':ab.mean(),'absolute_median_kg':ab.median(),'absolute_p75_kg':ab.quantile(.75),'absolute_p90_kg':ab.quantile(.90),'absolute_p95_kg':ab.quantile(.95),'gain_mean_kg':v[v>0].mean(),'loss_magnitude_mean_kg':-v[v<0].mean(),'zero_fraction':v.eq(0).mean(),'personal_baseline_median_kg':g.personal_mean.median()})
        for variant in (['primary','large_threshold','same_distance_baseline','stable_conditions'] if period=='full' else ['primary']):
            pp1=select(pp,variant)
            for (dist,label),g in pp1.groupby(['distance','selected_group']):
                r={'period':period,'variant':variant,'distance':dist,'group':label,**info(g),'body_delta_mean_kg':g.body_change_kg.mean(),'absolute_body_delta_mean_kg':g.body_change_kg.abs().mean(),'threshold_mean_kg':g.threshold.mean(),'time_delta_mean_s':g.time_delta.mean(),'time_delta_median_s':g.time_delta.median(),'relative_delta_mean_s':g.relative_time_delta.mean()}
                for outcome,col in [('raw','time_delta'),('relative','relative_time_delta')]:
                    v=g[col];r[outcome+'_exact_equal_count']=int(v.eq(0).sum())
                    for margin in [.5,1.]:
                        key=outcome+('_half' if margin==.5 else '_one')
                        for label,mask in [('improved',v.lt(-margin)),('similar',v.abs().le(margin)),('worsened',v.gt(margin))]:r[key+'_'+label+'_count']=int(mask.sum());r[key+'_'+label+'_rate']=mask.mean()
                raw.append(r)
    csv('typical_change_summary.csv',pd.DataFrame(typical));csv('raw_direction_groups.csv',pd.DataFrame(raw))
def select(p,variant):
    p=p.copy();name='same_distance' if variant=='same_distance_baseline' else 'personal';p=p[p[name+'_mean'].notna()].copy();p['threshold']=p[name+'_mean']+(p[name+'_sd'] if variant=='large_threshold' else 0);p['selected_group']=group(p.body_change_kg,p.threshold);p['baseline_mean']=p[name+'_mean'];p['baseline_sd']=p[name+'_sd'];p['baseline_n']=p[name+'_n']
    if variant=='stable_conditions':p=p[p.month.eq(p.previous_month)&p.band.eq(p.previous_band)&p.burden_change.abs().le(1)]
    return p
def fit(g):
    numeric=['increase_kg','decrease_kg','previous_burden_kg','previous_body10','previous_body2','log_gap','age','previous_relative_time','previous_finish_fraction','previous_hist_mean','field_change','baseline_mean','baseline_sd','baseline_n']+[c for c in g if c.startswith(('band=','gate='))]+['sin1','cos1','sin2','cos2']
    nx,s=a.standardized_nuisance(g,numeric,['year_grade']);columns=GROUPS+['intercept']+s['nuisance_columns'];x=np.column_stack([g.selected_group.eq(c).to_numpy(float) for c in GROUPS]+[np.ones(len(g)),nx]);y=g[['time_delta','relative_time_delta']].to_numpy();ms=a.core_fit(x,y,g,columns,4,fe=False)
    for m,label in zip(ms,['raw_delta_s','relative_delta_s']):m['target']=label;m['design']=s
    return ms
def main():
    p,dbsha=load();summarize(p);models=[];rows=[];support=[]
    for period,(lo,hi) in PLAN['periods'].items():
        for variant in (['primary','large_threshold','same_distance_baseline','stable_conditions'] if period=='full' else ['primary']):
            pp=select(p[p.year.between(lo,hi)],variant)
            for dist,g in pp.groupby('distance'):
                count=g.selected_group.value_counts();can=a.support(g,pairs=True)['supported'] and all(count.get(k,0)>=30 for k in ['zero']+GROUPS);entry={'period':period,'variant':variant,'distance':int(dist),**info(g)};support.append(entry|{'estimated':can,'group_counts':json.dumps(count.to_dict())})
                if not can:continue
                for m in fit(g):
                    models.append(entry|{'model':m})
                    for sign in ['gain','loss']:
                        for contrast,v in [(sign+'_above_minus_within',a.get_vector(m,sign+'_above')-a.get_vector(m,sign+'_within')),(sign+'_above_minus_zero',a.get_vector(m,sign+'_above'))]:
                            z=a.infer(m,v);rows.append(entry|{'target':m['target'],'contrast':contrast,**z,'mean_difference_within_half_second_supported':z['ci_lo']>-.5 and z['ci_hi']<.5})
                print(period,variant,dist,len(g),flush=True)
    effects=pd.DataFrame(rows)
    for _,g in effects.groupby(['period','variant','contrast']):effects.loc[g.index,'q_BH']=a.old.bh(g.p.to_numpy())
    csv('effects.csv',effects);csv('support.csv',pd.DataFrame(support));save('models.json',models)
    assert a.sha(a.old.DB)==dbsha
    for r in json.loads((H/'source_manifest.json').read_text()):assert a.sha(Path(r['path']))==r['sha256']
    save('verification.json',{'status':'passed','database_and_sources_unchanged':True,'history_endpoints':sum(len(r['history_pair_ids']) for r in json.loads((H/'history_lineage.json').read_text())),'models':len(models),'target_labels_are_raw_and_relative_seconds':True,'operational_change':False})
    print(effects[effects.variant.eq('primary')&effects.contrast.str.endswith('within')].to_string(index=False),flush=True)
if __name__=='__main__':main()
