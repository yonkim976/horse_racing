"""Refit current Jeju distances using pooled 2017-2026 observational data."""
import sys,json,hashlib,bisect
from pathlib import Path
from datetime import date,timedelta
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'20261007_environment_correction_pilot_v1'
sys.path.insert(0,str(OLD))
import numpy as np
import pandas as pd
from scipy.stats import norm
from modeling import load,features,NUM,CAT,interval,design,contrast
# Avoid importing old analyze.py under this script's own name.
import importlib.util
loader=importlib.util.spec_from_file_location('preserved_gate_analyze',OLD/'analyze.py');mod=importlib.util.module_from_spec(loader);loader.loader.exec_module(mod)
gatefit=mod.gatefit;gate_vector=mod.gate_vector
DB=HERE.parents[2]/'jeju/data/jeju_native_core.sqlite3'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def save(name,x):
    with (HERE/name).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,x):
    with (HERE/name).open('x',encoding='utf-8') as f:x.to_csv(f,index=False)
def bh(p):
    p=np.asarray(p);ix=np.argsort(p);n=len(p);out=np.empty(n);out[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*n/np.arange(1,n+1))[::-1])[::-1]);return out

def all_features(d,h):
    q=d[d.year>=2017].copy();time=d.finish_time_seconds
    means=[];last=[]
    for rid in q.index:
        ids=h[str(rid)][-5:];v=time.loc[ids].to_numpy() if ids else []
        means.append(float(np.mean(v)) if len(v) else np.nan);last.append(float(v[-1]) if len(v) else np.nan)
    q['hist_mean']=means;q['hist_last']=last
    for dest,src in [('log_same_count','same_count'),('log_starts','observed_starts'),('log_gap','days_since_start'),('log_same_gap','days_since_same')]:q[dest]=np.log1p(q[src])
    age=pd.to_numeric(q.age_at_race_raw,errors='coerce');q['event_age']=age.where(age>0);q['age_squared']=q.event_age**2;q['weight']=q.carried_weight_kg.where(q.carried_weight_kg>0)
    q['grade']=q.rank_class_raw.fillna('unknown');q['sex']=q.sex_at_race_raw.fillna('unknown');q['era']=np.where(q.year<=2018,'2017_2018','2019_plus')
    for c in ['mean','last']:q['relative_'+c]=q['hist_'+c]-q.groupby('race_id')['hist_'+c].transform('median')
    q['relative_rank']=(q.groupby('race_id').hist_mean.rank(method='average')-1)/(q.field_n-1)
    q['lateral']=np.select([q.horse_number<=3,q.horse_number<=7],['inner','middle'],default='outer')
    return q

def main():
    refs=[HERE/'PLAN.json',OLD/'audit/source_rows.csv',OLD/'audit/history_ids.json',OLD/'audit/summary.json',OLD/'audit/reference_manifest.json',OLD/'modeling.py',OLD/'analyze.py',OLD/'audit.py',OLD/'analysis_02/number_coefficients.csv',OLD/'RESEARCH_CONTRACT.md',HERE.parent/'20261008_gate_all_distances_v1/analyze.py',HERE.parent/'20261008_gate_all_distances_v1/lateral_contrasts.csv',HERE.parent/'20261008_gate_distance_scope_v2/scope_decision.json',HERE.parents[2]/'jeju/AGENTS.md']
    manifest=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',manifest)
    before=DB.stat();dbsha=sha(DB);assert dbsha==json.loads((OLD/'audit/summary.json').read_text())['database_sha256']
    d,h=load();q=all_features(d,h);original=features(d,h);assert q.loc[original.index,NUM+CAT].equals(original[NUM+CAT])
    q=q[q.race_distance_m.isin([800,900,1000,1110,1200,1300,1400,1610])].copy()
    assert q.race_date.max()=='2026-09-19'
    allrace=q[q.strict].drop_duplicates('race_id');periods=json.loads((HERE/'PLAN.json').read_text())['periods']
    support=[];rows=[];numbers=[];models=[];lineage=[];raw=[];max_error=0.;histchecked=0
    stored=pd.read_csv(OLD/'analysis_02/number_coefficients.csv');stored=stored[stored.record_year==2026]
    q=q[q.strict&(q.field_n==10)].copy()
    assert q.groupby('race_id').horse_number.apply(lambda v:sorted(v)==list(range(1,11))).all()
    groups={'inner':[1,2,3],'middle':[4,5,6,7],'outer':[8,9,10]}
    for period,years in periods.items():
        for dist in sorted(allrace.race_distance_m.unique()):
            g=q[q.year.isin(years)&(q.race_distance_m==dist)].sort_values(['race_date','race_number','horse_number'])
            candidate=allrace[allrace.year.isin(years)&(allrace.race_distance_m==dist)]
            n=int(g.race_id.nunique());days=int(g.race_date.nunique());ny=int(g.year.nunique());canfit=n>=30 and days>=20
            status='not_estimated_insufficient_support' if not canfit else 'historical_only_limited' if period.startswith('historical') else 'partial_year_exploratory' if period=='2026_partial' else 'basic_support' if n>=100 and days>=40 and ny>=2 else 'limited_sample'
            entry={'period':period,'distance':int(dist),'all_field_races':len(candidate),'ten_runner_races':n,'days':days,'years':ny,'rows':len(g),'history_available_rows':int((g.same_count>0).sum()),'status':status,'estimated':canfit,'first_date':g.race_date.min() if len(g) else None,'last_date':g.race_date.max() if len(g) else None};support.append(entry)
            if not canfit:
                for target in ['time','top3']:
                    for name in ['inner','middle','outer','inner_minus_middle','outer_minus_middle','inner_minus_outer']:rows.append({**entry,'target':target,'contrast':name,'effect':np.nan,'ci_lo':np.nan,'ci_hi':np.nan,'horse_ci_lo':np.nan,'horse_ci_hi':np.nan,'p':np.nan,'unit':'seconds' if target=='time' else 'percentage_points'})
                continue
            for rid in g.index:
                r=g.loc[rid];ids=h[str(rid)];cut=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat()
                assert all(d.loc[i,'horse_id']==r.horse_id and d.loc[i,'race_distance_m']==dist and d.loc[i,'race_date']<=cut for i in ids);histchecked+=1
            lineage.append(g[['api_record_id','race_id','horse_id','race_date','race_distance_m','horse_number','history_cutoff','api4_3_payload_sha256']].assign(period=period))
            for lateral,a in g.groupby('lateral'):
                raw.append({**entry,'lateral':lateral,'starts':len(a),'top3_rate':float((a.finish_position<=3).mean()),'mean_time_s':float(a.finish_time_seconds.mean())})
            for target in ['time','top3']:
                b,s,c,hc=gatefit(g,target);scale=1 if target=='time' else 100
                models.append({'period':period,'distance':int(dist),'target':target,'beta':b.tolist(),'design':s,'date_cluster_cov':c.tolist(),'horse_cluster_cov':hc.tolist()})
                vectors={name:np.mean([gate_vector(s,k) for k in ks],axis=0) for name,ks in groups.items()}
                for k in range(1,11):
                    v=gate_vector(s,k);pt,lo,hi=interval(v,b,c);_,hlo,hhi=interval(v,b,hc);se=(hi-lo)/3.92
                    numbers.append({**entry,'target':target,'number':k,'effect':pt*scale,'ci_lo':lo*scale,'ci_hi':hi*scale,'horse_ci_lo':hlo*scale,'horse_ci_hi':hhi*scale,'p':float(2*norm.sf(abs(pt/se))) if se>0 else 1.,'unit':'seconds' if target=='time' else 'percentage_points'})
                    if period=='2019_2025' and dist in [1000,1110]:
                        prev=stored[(stored.distance==dist)&(stored.target==target)&(stored.number==k)].effect.iloc[0];max_error=max(max_error,abs(pt*scale-prev))
                for name,v in list(vectors.items())+[(a+'_minus_'+z,vectors[a]-vectors[z]) for a,z in [('inner','middle'),('outer','middle'),('inner','outer')]]:
                    pt,lo,hi=interval(v,b,c);_,hlo,hhi=interval(v,b,hc);se=(hi-lo)/3.92
                    rows.append({**entry,'target':target,'contrast':name,'effect':pt*scale,'ci_lo':lo*scale,'ci_hi':hi*scale,'horse_ci_lo':hlo*scale,'horse_ci_hi':hhi*scale,'p':float(2*norm.sf(abs(pt/se))) if se>0 else 1.,'unit':'seconds' if target=='time' else 'percentage_points'})
            print(period,int(dist),n,status,flush=True)
    results=pd.DataFrame(rows);num=pd.DataFrame(numbers);families=[]
    for period in periods:
        mask=(results.period==period)&results.contrast.str.contains('_minus_')&results.p.notna();n=int(mask.sum())
        if n:results.loc[mask,'q_BH']=bh(results.loc[mask,'p'].to_numpy())
        families.append({'period':period,'family':'group_contrasts_all_distances_both_targets','comparisons':n})
        mask=(num.period==period)&num.p.notna();n=int(mask.sum())
        if n:num.loc[mask,'q_BH']=bh(num.loc[mask,'p'].to_numpy())
        families.append({'period':period,'family':'individual_numbers_all_distances_both_targets','comparisons':n})
    assert max_error<1e-10
    assert np.allclose(num.groupby(['period','distance','target']).effect.mean(),0,atol=1e-10)
    checks=[]
    for (period,dist,target),g in results[results.estimated].groupby(['period','distance','target']):
        a=g.set_index('contrast').effect;assert np.isclose(a['inner_minus_outer'],a['inner']-a['outer'])
        rawnum=num[(num.period==period)&(num.distance==dist)&(num.target==target)].set_index('number').effect
        for name,ks in groups.items():assert np.isclose(a[name],rawnum.loc[ks].mean())
    csv('support.csv',pd.DataFrame(support));csv('lateral_contrasts.csv',results);csv('number_effects.csv',num);csv('raw_lateral_rates.csv',pd.DataFrame(raw));csv('source_lineage.csv',pd.concat(lineage,ignore_index=True))
    csv('all_field_support.csv',allrace.groupby(['year','race_distance_m','field_n']).size().reset_index(name='races'));save('models.json',models);save('multiplicity_families.json',families)
    assert all(sha(Path(r['path']))==r['sha256'] for r in manifest);assert sha(DB)==dbsha and (DB.stat().st_size,DB.stat().st_mtime_ns)==(before.st_size,before.st_mtime_ns)
    save('verification.json',{'status':'passed','features_match_preserved_1000_1110':True,'existing_coefficients_max_error':max_error,'history_rows_checked_including_period_reuse':histchecked,'all_history_keys_distances_T_minus_2_valid':True,'group_contrast_arithmetic_verified':True,'all_sources_unchanged':True,'database_unchanged':True,'database_sha256':dbsha,'all_fits_ten_runners_numbers_1_through_10':True,'unsupported_effects_NULL':bool(results[~results.estimated].effect.isna().all()),'code_sha256':sha(Path(__file__))})
    print(results[(results.contrast=='inner_minus_outer')&(results.target=='top3')][['period','distance','ten_runner_races','days','effect','ci_lo','ci_hi','q_BH','status']].to_string(index=False),flush=True)
if __name__=='__main__':main()
