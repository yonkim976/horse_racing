"""Post-hoc lateral contrasts of the preserved Jeju ten-number model."""
import sys,json,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'20261007_environment_correction_pilot_v1'
sys.path.insert(0,str(OLD))
import numpy as np
import pandas as pd
from scipy.stats import norm
from modeling import load,features,interval
from analyze import gatefit,gate_vector

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,data):
    with (HERE/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def csv(name,data):
    with (HERE/name).open('x',encoding='utf-8') as f:data.to_csv(f,index=False)
def bh(p):
    ix=np.argsort(p);n=len(p);out=np.empty(n);out[ix]=np.minimum(1,np.minimum.accumulate((np.asarray(p)[ix]*n/np.arange(1,n+1))[::-1])[::-1]);return out

def main():
    inputs=[HERE/'PLAN.md',OLD/'RESEARCH_CONTRACT.md',OLD/'modeling.py',OLD/'analyze.py',OLD/'audit.py',OLD/'audit/source_rows.csv',OLD/'audit/history_ids.json',OLD/'analysis_02/number_coefficients.csv']
    manifest=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in inputs]
    save('source_manifest.json',manifest)
    d,h=load();q=features(d,h);q=q[q.strict&(q.field_n==10)&q.horse_number.between(1,10)]
    stored=pd.read_csv(OLD/'analysis_02/number_coefficients.csv');stored=stored[stored.record_year==2026]
    groups={'inner':[1,2,3],'middle':[4,5,6,7],'outer':[8,9,10]};rows=[];numbers=[];max_error=0
    for period,years in [('2019_2025',range(2019,2026)),('2024_2025',[2024,2025])]:
        for dist in [1000,1110]:
            g=q[q.year.isin(years)&(q.race_distance_m==dist)].sort_values(['race_date','race_number','horse_number'])
            for target in ['time','top3']:
                b,s,c,hc=gatefit(g,target);scale=1 if target=='time' else 100
                vectors={name:np.mean([gate_vector(s,k) for k in ks],axis=0) for name,ks in groups.items()}
                for k in range(1,11):
                    pt,lo,hi=interval(gate_vector(s,k),b,c)
                    numbers.append({'period':period,'distance':dist,'target':target,'number':k,'effect':pt*scale,'lo':lo*scale,'hi':hi*scale})
                    if period=='2019_2025':
                        prev=stored[(stored.distance==dist)&(stored.target==target)&(stored.number==k)].effect.iloc[0];max_error=max(max_error,abs(pt*scale-prev))
                for name,v in list(vectors.items())+[(a+'_minus_'+z,vectors[a]-vectors[z]) for a,z in [('inner','middle'),('outer','middle'),('outer','inner')]]:
                    pt,lo,hi=interval(v,b,c);_,hlo,hhi=interval(v,b,hc);se=(hi-lo)/3.92
                    rows.append({'period':period,'distance':dist,'target':target,'contrast':name,'effect':pt*scale,'ci_lo':lo*scale,'ci_hi':hi*scale,'horse_ci_lo':hlo*scale,'horse_ci_hi':hhi*scale,'p':float(2*norm.sf(abs(pt/se))) if se>0 else 1.,'races':int(g.race_id.nunique()),'days':int(g.race_date.nunique()),'rows':len(g),'unit':'seconds' if target=='time' else 'percentage_points'})
    results=pd.DataFrame(rows);mask=results.contrast.str.contains('_minus_')
    for period in results.period.unique():
        ix=(results.period==period)&mask;results.loc[ix,'q_BH_12_contrasts']=bh(results.loc[ix,'p'].to_numpy())
    assert max_error<1e-10
    csv('lateral_contrasts.csv',results);csv('number_effects.csv',pd.DataFrame(numbers))
    assert all(sha(Path(r['path']))==r['sha256'] for r in manifest)
    save('verification.json',{'status':'passed','original_number_coefficients_max_difference':max_error,'all_source_hashes_unchanged':True,'group_mapping':groups,'posthoc_exploratory':True,'prediction_improvement_tested':False,'code_sha256':sha(Path(__file__))})
    print(results[mask].to_string(index=False))
if __name__=='__main__':main()
