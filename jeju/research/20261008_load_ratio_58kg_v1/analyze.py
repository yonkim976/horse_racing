"""Same 58kg, different body mass: descriptive support and conditional load-cost contrasts."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.stats import t

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2'
sp=importlib.util.spec_from_file_location('weight_reuse',PRE/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
PLAN=json.loads((H/'PLAN.json').read_text());sha=a.sha
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,d):
    with (H/name).open('x',encoding='utf-8') as f:d.to_csv(f,index=False)
def pair_fit(g):
    numeric=['body_change10','previous_burden_kg','log_gap','age','previous_relative_time','previous_finish_fraction','previous_hist_mean','field_change','mean_body10','mean_body_squared']
    numeric += [c for c in g.columns if c.startswith(('band=','gate='))]+['sin1','cos1','sin2','cos2']
    nx,s=a.standardized_nuisance(g,numeric,['year_grade']);targets=['increase_kg','decrease_kg','increase_by_body','decrease_by_body'];columns=targets+['intercept']+s['nuisance_columns']
    x=np.column_stack([g[targets].to_numpy(),np.ones(len(g)),nx]);y=g[['time_delta','log_time_delta100']].to_numpy()
    fits=a.core_fit(x,y,g,columns,4,fe=False)
    for m in fits:m['design']=s
    return fits
def evaluate(m,body,family):
    slope='burden' if family=='row' else 'increase_kg';interaction='burden_body' if family=='row' else 'increase_by_body'
    return 3*(a.get_vector(m,slope)+a.get_vector(m,interaction,(body-278)/10))
def main():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'analyze.py',PRE/'source_lineage.csv',PRE/'pair_lineage.csv',PRE/'models.json',PRE/'verification.json',ROOT/'jeju/data/horse_exclusions.json']
    sources=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',sources)
    dbsha=sha(a.old.DB);assert dbsha==json.loads((PRE/'verification.json').read_text())['database_sha256']
    q=pd.read_csv(PRE/'source_lineage.csv',dtype={'horse_id':str});assert len(q)==52155 and q.api_record_id.is_unique and q.race_date.max()=='2026-09-19'
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses'];assert not(set(q.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']})
    q['relative_time']=q.time-q.groupby('race_id').time.transform('median');q['body_bin']=pd.cut(q.body_kg,[0,260,280,300,np.inf],right=False,labels=['under260','260to279','280to299','300plus'])
    q58=q[q.carried_weight_kg.eq(58)].copy();csv('exact58_source_lineage.csv',q58)
    raw=q58.groupby(['race_distance_m','body_bin'],observed=True).agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),races=('race_id','nunique'),body_mean_kg=('body_kg','mean'),load_mean_pct=('load_pct_body','mean'),relative_time_mean_s=('relative_time','mean'),relative_time_median_s=('relative_time','median')).reset_index();csv('exact58_body_groups.csv',raw)
    csv('ratio_examples.csv',pd.DataFrame([{'body_kg':body,'burden_kg':58,'load_pct_body':5800/body} for body in PLAN['examples_body_kg']]))
    supports=[]
    for distance,g in q.groupby('race_distance_m'):
        for body,lo,hi in [(250,240,260),(300,290,310)]:
            z=g[g.body_kg.between(lo,hi)];counts={kg:int(z.carried_weight_kg.eq(kg).sum()) for kg in [55,58]};h55=set(z[z.carried_weight_kg.eq(55)].horse_id);h58=set(z[z.carried_weight_kg.eq(58)].horse_id)
            supports.append({'distance':int(distance),'example_body_kg':body,'body_lo':lo,'body_hi':hi,'starts55':counts[55],'starts58':counts[58],'horses_at_both55_and58_in_body_window':len(h55&h58)})
    csv('example_load_support.csv',pd.DataFrame(supports))
    oldmodels=json.loads((PRE/'models.json').read_text());models=[]
    for item in oldmodels:
        if item['family']=='row' and item['period']=='full' and item['variant']=='interaction':models.append(item|{'origin':'preserved_v2_interaction_model'})
    pairs=pd.read_csv(PRE/'pair_lineage.csv',dtype={'horse_id':str});pairs['mean_body10']=((pairs.body_kg+pairs.previous_body_kg)/2-278)/10;pairs['mean_body_squared']=pairs.mean_body10**2;pairs['increase_by_body']=pairs.increase_kg*pairs.mean_body10;pairs['decrease_by_body']=pairs.decrease_kg*pairs.mean_body10
    support=[]
    for period,(lo,hi) in PLAN['pair_periods'].items():
        for distance,g in pairs[pairs.year.between(lo,hi)].groupby('distance'):
            for variant in (['primary','stable_conditions'] if period=='full' else ['primary']):
                z=g[g.stable_conditions] if variant=='stable_conditions' else g;s=a.support(z,True);entry={'family':'pair','period':period,'variant':variant,'distance':int(distance)}|s
                if not s['supported']:support.append(entry|{'estimated':False});continue
                try:fits=pair_fit(z)
                except AssertionError as exc:support.append(entry|{'estimated':False,'reason':str(exc)});continue
                support.append(entry|{'estimated':True})
                for m in fits:models.append(entry|{'model':m,'origin':'new_size_modifier_model'})
                print(period,distance,variant,len(z),flush=True)
    effects=[];difference=[]
    for item in models:
        m=item['model'];base={k:item[k] for k in ['family','period','variant','distance','rows','races','horses','dates']};base['target']=m['target']
        for body in [250,278,280,300]:effects.append(base|{'body_kg':body}|a.infer(m,evaluate(m,body,item['family'])))
        v=evaluate(m,250,item['family'])-evaluate(m,300,item['family']);difference.append(base|a.infer(m,v))
    ef=pd.DataFrame(effects);diff=pd.DataFrame(difference)
    for _,g in diff.groupby(['family','period','variant']):diff.loc[g.index,'q_BH']=a.old.bh(g.p)
    csv('conditional_55_to58_costs.csv',ef);csv('small_minus_large_cost.csv',diff);csv('pair_modifier_support.csv',pd.DataFrame(support));save('models.json',models)
    # Independent algebra: contrast must equal -15 times size-interaction coefficient.
    max_error=0.
    for item in models:
        m=item['model'];col='burden_body' if item['family']=='row' else 'increase_by_body';idx=m['columns'].index(col);b=np.asarray(m['beta']);c=np.asarray(m['cov']);pt=-15*b[idx];se=15*np.sqrt(c[idx,idx]);crit=t.ppf(.975,m['critical_df'])
        r=diff[(diff.family==item['family'])&diff.period.eq(item['period'])&diff.variant.eq(item['variant'])&diff.distance.eq(item['distance'])&diff.target.eq(m['target'])].iloc[0]
        error=float(max(abs(np.array([pt,pt-crit*se,pt+crit*se])-np.array([r.effect,r.ci_lo,r.ci_hi]))));max_error=max(max_error,error);assert error<1e-9
    assert np.isclose(5800/250,23.2) and np.isclose(5800/300,19.333333333333332)
    assert all(sha(Path(s['path']))==s['sha256'] for s in sources) and sha(a.old.DB)==dbsha
    save('verification.json',{'status':'passed','prior_sources_and_database_unchanged':True,'database_sha256':dbsha,'source_rows':len(q),'exact58_starts':len(q58),'original_pairs':len(pairs),'model_outcomes':len(models),'independent_small_minus_large_algebra_max_error':max_error,'same_impact_equivalence_test_performed':False,'fixed_correction_adopted':False,'operational_change':False})
    print('RAW58',raw.to_string(index=False),flush=True);print('DIFFERENCE',diff[diff.target.eq('time_s')].to_string(index=False),flush=True)
if __name__=='__main__':main()
