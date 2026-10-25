"""Independent enumeration of operational ABC, ticket truth and matched decisions."""
from itertools import combinations,permutations
import json
import numpy as np
import pandas as pd
import compare as c

def independent(g,top3,win,temp,win_temp):
    n=len(g);sets=np.array(list(combinations(range(n),3)));orders=np.array(list(permutations(range(n),3)))
    energy=top3[sets].sum(1)/temp;q=np.exp(energy-energy.max());q/=q.sum()
    weights=np.exp((win-win.max())/win_temp);mapping={tuple(t):i for i,t in enumerate(sets)}
    raw=np.array([weights[i]/weights.sum()*weights[j]/(weights.sum()-weights[i])*
        weights[k]/(weights.sum()-weights[i]-weights[j]) for i,j,k in orders])
    si=np.array([mapping[tuple(sorted(t))] for t in orders]);den=np.bincount(si,weights=raw,minlength=len(sets))
    mass=raw/den[si]*q[si]
    return sets,q,orders,mass
def direct_metrics(g,sets,q,orders,mass):
    n=len(g);y=g.outcome.to_numpy(int);top3=(y>=1)&(y<=3);top2=(y>=1)&(y<=2)
    inc=np.array([mass[(orders==i).any(1)].sum() for i in range(n)])
    axis=int(np.argsort(-np.round(inc,12),kind='stable')[0]);ii,jj=np.triu_indices(n,1)
    qnl=np.array([mass[(np.sort(orders[:,:2],axis=1)==[i,j]).all(1)].sum() for i,j in zip(ii,jj)])
    qpl=np.array([mass[((orders==i).any(1))&((orders==j).any(1))].sum() for i,j in zip(ii,jj)])
    qs=np.argsort(-np.round(qnl,12),kind='stable')[:3];ws=np.argsort(-np.round(qpl,12),kind='stable')[:3]
    qy=top2[ii]&top2[jj];wy=top3[ii]&top3[jj]
    return {'axis_program_no':int(g.program_no.iloc[axis]),'axis_top3':int(top3[axis]),
        'quinella_one':int(qy[qs[0]]),'quinella_three':int(qy[qs].any()),
        'qpl_one':int(wy[ws[0]]),'qpl_three':int(wy[ws].any()),
        'runner_brier':float(np.mean((inc-top3)**2))},inc

def main():
    c.check();r=pd.read_parquet(c.OUT/'race_metrics.parquet').set_index(['variant','race_key'])
    op=pd.read_parquet(c.OPS/'operating_runner_predictions.parquet');op['bridge']=c.bridge(op.race_key)
    rr=pd.read_parquet(c.PREV/'outputs/runner_probabilities.parquet');rr=rr[rr.variant.eq('personal_t2')]
    gg={k:g for k,g in rr.groupby('race_key')};op_groups={k:g for k,g in op.groupby('bridge')}
    state=pd.read_parquet(c.STATE/'outputs/runner_probabilities.parquet').query("variant=='state_gbm'")
    source_groups={'personal_t2':gg,'state_gbm':{k:g for k,g in state.groupby('race_key')}}
    co=pd.read_parquet(c.OUT/'cohort.parquet');assert len(co)==1258 and co.race_key.is_unique
    excluded=json.loads((c.OUT/'cohort_audit.json').read_text())['excluded_operating_races']
    assert set(co.race_key)|{v['race_key'] for v in excluded}==set(op_groups)
    metadata=c.operational_metadata();max_error=0.;checks=0;native_checks=0
    for key in co.race_key:
        g=op_groups[key].sort_values('program_no').reset_index(drop=True);candidate=gg[key].sort_values('program_no')
        assert c.signature(g)==c.signature(candidate);assert g.race_date.nunique()==g.meet.nunique()==1
        # Preserve actual finite normal ranks; nonfinishers can never count as podium.
        assert candidate.outcome.between(1,3).sum()==3
        g['outcome']=candidate.outcome.to_numpy(int)
        venue='SEOUL' if int(g.meet.iloc[0])==1 else 'BUSAN';w=g.raw_win_score.to_numpy(float)
        aa=metadata['A']['temperature_by_target_and_venue']['A'][venue]
        bb=metadata['BC']['temperature_by_target_and_venue']['B'][venue]
        cc=metadata['BC']['temperature_by_target_and_venue']['C'][venue]
        wt=metadata['WIN_ORDER']['temperature_by_venue'][venue]
        sets,q,orders,mass=independent(g,g.raw_a_score.to_numpy(),w,aa,wt)
        m,inc=direct_metrics(g,sets,q,orders,mass)
        max_error=max(max_error,float(np.max(np.abs(inc-g.prob_top3.to_numpy()))))
        for name,value in m.items():
            actual=r.loc[('operating',key),name];assert abs(actual-value)<1e-10,(key,name,actual,value);checks+=1
        bsets,bq,_,_=independent(g,g.raw_bc_score.to_numpy(),w,bb,wt)
        _,_,corders,cmass=independent(g,g.raw_bc_score.to_numpy(),w,cc,wt)
        native=c.native(g,bsets,bq,corders,cmass)
        for name,value in native.items():
            error=abs(r.loc[('operating',key),name]-value);assert error<1e-10,(key,name,error);max_error=max(max_error,float(error));native_checks+=1
        for variant in ['personal_t2','state_gbm']:
            s=source_groups[variant][key].sort_values('program_no')
            assert c.signature(s)==c.signature(candidate)
            ix=int(np.argsort(-np.round(s.top3.to_numpy(),12),kind='stable')[0]);a=s.iloc[ix]
            assert r.loc[(variant,key),'axis_program_no']==a.program_no
            assert r.loc[(variant,key),'axis_top3']==int(1<=a.outcome<=3);checks+=2
    a=pd.read_parquet(c.OUT/'axis_comparison.parquet');res=json.loads((c.OUT/'results.json').read_text())
    for row in res['groups']:
        group=a if not row['meet'] else a[a.meet.eq(row['meet'])];n=row['variant']+'_hit'
        m=row['metrics']['axis_top3'];assert len(group)==m['races']
        assert group.operating_hit.sum()==m['operating_total'] and group[n].sum()==m['candidate_total']
        # Separate matrix multiplication implementation of the paired date bootstrap.
        dates=sorted(group.race_date.unique());daily=[]
        for date in dates:
            z=group[group.race_date.eq(date)];daily.append([len(z),int(z[n].sum()-z.operating_hit.sum())])
        daily=np.asarray(daily);draws=np.random.default_rng(20261025).integers(0,len(dates),size=(2000,len(dates)))
        weights=np.array([np.bincount(ix,minlength=len(dates)) for ix in draws]);sums=weights@daily
        interval=np.quantile(sums[:,1]/sums[:,0],[.025,.975]);assert np.max(np.abs(interval-m['ci95']))<1e-12
    c.check();assert max_error<1e-10
    c.save(c.OUT/'verification.json',{'status':'passed','matched_races':1258,'matched_starters':int(co.starters.sum()),
        'cohort_signature_checks':1258,'direct_operating_and_axis_checks':checks,'native_ABC_metric_checks':native_checks,
        'max_independent_numeric_error':max_error,'all_six_axis_bootstrap_intervals_reproduced':True,
        'operating_registry_models_inputs_unchanged':True,'no_refit':True,'actual_live_publications_compared':False,
        'verifier_sha256':c.sha(__file__)})
    print(json.dumps(json.loads((c.OUT/'verification.json').read_text())),flush=True)
if __name__=='__main__':main()
