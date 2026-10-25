"""Busan chronological joint S1F-pack forecasts and finish-score ablations."""
from pathlib import Path
import hashlib
import json
import math
import warnings
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control

warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
O = HERE/'outputs'
M = O/'models'
OLD = R/'20261021_busan_all_distance_profiles/outputs'
PACE = R/'20261008_field_pace_prediction/outputs'
SEED = 20261021
YEARS = [2024,2025,2026]
AUX_PARAMS = dict(learning_rate=.04,num_leaves=15,min_data_in_leaf=100,
                  lambda_l2=10.,verbosity=-1,num_threads=4,seed=SEED,
                  deterministic=True,force_col_wise=True)
MAIN_PARAMS = AUX_PARAMS | dict(min_data_in_leaf=80,lambda_l2=2.,max_bin=63)
MODELS = ['B','D','I','J']
STACK_COLS = ['front','solo','count1','count2','count3p','member1','member2','member3p',
              'expected_count','other_expected_count','top3_mixture','lead_top3_mass',
              'nonlead_top3_mass','late600_front_interaction','late200_front_interaction',
              'late600_other_front_adv','late200_other_front_adv']


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(name,value):
    (O/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for name,expected in json.loads((O/'input_manifest.json').read_text()).items():
        path=ROOT/name
        assert path.stat().st_size==expected['bytes'] and sha(path)==expected['sha256'],name


def lead_histories(q):
    """Prior five actual slots; conditioning uses only the past race's first pack."""
    assert not q.duplicated(['horse_id','date']).any()
    q=q.sort_values(['horse_id','date']).reset_index(drop=True)
    vals={}
    led=q.group_observed & q.role4.eq(0)
    normal=q.normal_outcome
    for key,source in [('g3f_peer','last600_peer_adv'),('g1f_peer','late_peer_adv'),
                        ('g3f_raw','last600'),('g1f_raw','late')]:
        vals[key]=np.where(led & normal,q[source],np.nan)
    vals['top3']=np.where(led,q.raw_finish_rank.between(1,3).astype(float),np.nan)
    a=np.column_stack(list(vals.values()))
    dates=q.date.to_numpy('datetime64[D]').astype('int64');horses=q.horse_id.to_numpy()
    idx=np.arange(len(q));sums=np.zeros_like(a);counts=np.zeros_like(a)
    for lag in range(1,6):
        prev=np.maximum(0,idx-lag)
        days=dates-dates[prev]
        good=(idx>=lag)&(horses==horses[prev])&(days>=2)&(days<=730)
        observed=np.isfinite(a[prev])&good[:,None]
        sums+=np.where(observed,a[prev],0);counts+=observed
    result={}
    for j,key in enumerate(vals):
        result['lead_hist_'+key+'_mean5']=np.divide(sums[:,j],counts[:,j],
                  out=np.full(len(q),np.nan),where=counts[:,j]>0)
        result['lead_hist_'+key+'_n5']=counts[:,j]
    return q,pd.DataFrame(result)


def prepare():
    allq=pd.read_parquet(PACE/'feature_context.parquet')
    allq,add=lead_histories(allq)
    source_x=pd.read_parquet(PACE/'feature_frame.parquet')
    # Stored frame is keyed by the saved context order; check before reindexing.
    original=pd.read_parquet(PACE/'feature_context.parquet',columns=['row_key'])
    source_x.index=original.row_key
    cols=[c for c in json.loads((PACE/'feature_groups.json').read_text())['F']
          if c!='jockey_changed']
    assert not any('jockey' in c or 'trainer' in c for c in cols)
    x=source_x.loc[allq.row_key,cols].reset_index(drop=True)
    x=pd.concat([x,add],axis=1)
    busan=allq.meet.eq('부산').to_numpy()
    q=allq.loc[busan].reset_index(drop=True)
    x=x.loc[busan].reset_index(drop=True)
    assert len(q)==66240 and q.row_key.is_unique
    assert (q.history_last.isna() | (q.date-q.history_last).dt.days.ge(2)).all()
    races=q.groupby('source_key',sort=True).agg(date=('date','first'),year=('year','first'),
           distance=('distance_m','first'),field_size=('field_size','first'),
           group_complete=('group_observed','all'),normal_complete=('normal_outcome','all'))
    count_features={}
    for col in ['distance_m','field_size','grade_num','month_sin','month_cos']:
        count_features[col]=x.groupby(q.source_key)[col].first()
    summaries=['early_mean5','early_adv_mean5','lead_prior5','solo_rate_mean5',
               'group_mean_relative_mean5','valid_position5','early_n5','past_total',
               'last600_peer_adv_mean5','late_peer_adv_mean5']
    for col in summaries:
        for stat in ['mean','min','max','std']:
            count_features[col+'_'+stat]=x.groupby(q.source_key)[col].agg(stat)
    rx=pd.DataFrame(count_features).reindex(races.index).astype(float)
    outcomes=pd.read_csv(R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv')
    outcome=outcomes.set_index('source_key')
    assert set(outcome.index)==set(races.index[races.group_complete])
    races['actual_count']=outcome.leader_count.reindex(races.index)
    races['count_class']=np.where(races.actual_count.eq(1),0,
                           np.where(races.actual_count.eq(2),1,2))
    races.loc[~races.group_complete,'count_class']=-1
    q['actual_count']=q.source_key.map(races.actual_count)
    q['count_class']=q.source_key.map(races.count_class).astype(int)
    add.loc[busan].reset_index(drop=True).to_parquet(O/'lead_history_additions.parquet',index=False)
    rx.to_parquet(O/'race_inputs.parquet')
    return q,x,races,rx


def fit(name,x,y,weights,params,rounds,train_dates):
    path=M/(name+'.txt')
    if path.exists():
        model=lgb.Booster(model_file=str(path))
        assert model.feature_name()==list(x.columns)
        return model
    model=lgb.train(params,lgb.Dataset(x,label=y,weight=weights),num_boost_round=rounds)
    model.save_model(str(path))
    save('models/'+name+'.json',dict(name=name,features=list(x.columns),n=len(x),
         train_start=str(pd.Series(train_dates).min().date()),
         train_end=str(pd.Series(train_dates).max().date()),params=params,rounds=rounds,
         model_sha256=sha(path)))
    print('Fitted',name,'rows',len(x),'features',x.shape[1],flush=True)
    return model


def polynomial(prob):
    out=np.array([1.])
    for p in prob:
        nxt=np.zeros(len(out)+1);nxt[:-1]+=(1-p)*out;nxt[1:]+=p*out;out=nxt
    return out


def joint(prob,desired=None):
    """Cardinality-bin reweighting of a nonempty Bernoulli subset distribution."""
    p=np.clip(np.asarray(prob,float),1e-6,1-1e-6)
    pmf=polynomial(p)
    bins=np.array([pmf[1],pmf[2],pmf[3:].sum()])
    pi=bins/bins.sum() if desired is None else np.asarray(desired,float)
    pi=pi/pi.sum()
    scale=pi/bins
    n=len(p);marginal=np.zeros((n,3));expected=0.
    for k in range(1,n+1):expected+=k*pmf[k]*scale[min(k-1,2)]
    for i in range(n):
        leave=polynomial(np.delete(p,i))
        marginal[i,0]=p[i]*leave[0]*scale[0]
        marginal[i,1]=p[i]*leave[1]*scale[1]
        marginal[i,2]=p[i]*leave[2:].sum()*scale[2]
    np.testing.assert_allclose(marginal.sum(),expected,atol=1e-9)
    np.testing.assert_allclose(marginal[:,0].sum(),pi[0],atol=1e-9)
    return marginal,pi,float(expected)


def stack_features(p,desired,conditional,late600,late200):
    mass,pi,expected=joint(p,desired)
    front=mass.sum(axis=1)
    top3_lead=(mass*conditional[:,1,:]).sum(axis=1)
    top3_nonlead=((pi[None,:]-mass)*conditional[:,0,:]).sum(axis=1)
    arrays=[front,mass[:,0],np.full(len(p),pi[0]),np.full(len(p),pi[1]),
            np.full(len(p),pi[2]),mass[:,0],mass[:,1],mass[:,2],
            np.full(len(p),expected),expected-front,top3_lead+top3_nonlead,
            top3_lead,top3_nonlead,front*late600,front*late200]
    for late in [late600,late200]:
        ok=np.isfinite(late);num=np.sum(front*np.nan_to_num(late));den=np.sum(front*ok)
        arrays.append(np.divide(num-front*np.nan_to_num(late),den-front*ok,
                      out=np.full(len(p),np.nan),where=(den-front*ok)>1e-9))
    return np.column_stack(arrays),pi


def auxiliary(q,x,races,rx):
    saved=O/'aux_predictions.parquet'
    race_saved=O/'count_predictions.parquet'
    if saved.exists():return pd.read_parquet(saved),pd.read_parquet(race_saved)
    parts=[];race_parts=[]
    for year in range(2020,2027):
        tr=q.year.lt(year)&q.group_observed
        te=q.year.eq(year)
        xr=x.loc[tr];target=q.loc[tr,'role4'].eq(0).astype(int)
        assert q.loc[tr,'date'].max()<q.loc[te,'date'].min()
        lead=fit(f'{year}_lead',xr,target,1/q.loc[tr,'field_size'],
                 AUX_PARAMS|dict(objective='binary'),180,q.loc[tr,'date'])
        rt=races.year.lt(year)&races.group_complete
        rv=races.year.eq(year)
        count=fit(f'{year}_count',rx.loc[rt],races.loc[rt,'count_class'].astype(int),None,
                  AUX_PARAMS|dict(objective='multiclass',num_class=3),180,races.loc[rt,'date'])
        cx=x.loc[tr].copy();cx['scenario_lead']=target.to_numpy()
        cx['scenario_count']=q.loc[tr,'count_class'].to_numpy()
        retention=fit(f'{year}_retention',cx,q.loc[tr,'raw_finish_rank'].between(1,3).astype(int),
                  1/q.loc[tr,'field_size'],AUX_PARAMS|dict(objective='binary'),180,q.loc[tr,'date'])
        pred=lead.predict(x.loc[te],num_threads=4)
        countpred=count.predict(rx.loc[rv],num_threads=4)
        qq=q.loc[te].copy().reset_index(drop=True);xx=x.loc[te].copy().reset_index(drop=True)
        conditional=np.empty((len(qq),2,3))
        for member in range(2):
            for n in range(3):
                scenario=xx.copy();scenario['scenario_lead']=member;scenario['scenario_count']=n
                conditional[:,member,n]=retention.predict(scenario,num_threads=4)
        pi_by_key=pd.DataFrame(countpred,index=rx.index[rv],columns=['p1','p2','p3p'])
        rr=races.loc[rv].copy().join(pi_by_key)
        race_parts.append(rr.reset_index())
        out=qq[['row_key','source_key','horse_id','date','year','distance_m','gate',
                'field_size','role4','group_observed','raw_finish_rank','actual_count']].copy()
        out['raw_lead']=pred
        for member in range(2):
            for n in range(3):out[f'ret_m{member}_n{n}']=conditional[:,member,n]
        independent=np.full((len(qq),len(STACK_COLS)),np.nan)
        structured=independent.copy()
        for key,ix in qq.groupby('source_key',sort=False).groups.items():
            ix=np.asarray(ix)
            args=(conditional[ix],qq.loc[ix,'last600_peer_adv_mean5'].to_numpy(float),
                   qq.loc[ix,'late_peer_adv_mean5'].to_numpy(float))
            independent[ix],_=stack_features(pred[ix],None,*args)
            desired=pi_by_key.loc[key].to_numpy(float)
            structured[ix],_=stack_features(pred[ix],desired,*args)
        for j,name in enumerate(STACK_COLS):
            out['I_'+name]=independent[:,j];out['J_'+name]=structured[:,j]
        parts.append(out)
    allp=pd.concat(parts,ignore_index=True)
    allr=pd.concat(race_parts,ignore_index=True)
    allp.to_parquet(saved,index=False);allr.to_parquet(race_saved,index=False)
    return allp,allr


def main_inputs(q,x,races,rx,aux):
    p=pd.read_parquet(OLD/'profiles.parquet')
    b=pd.read_parquet(OLD/'features.parquet')
    cols=json.loads((OLD/'feature_sets.json').read_text())['B3']
    keys='부산:'+p.date+':'+p.race_no.astype(str)+':'+p.horse_id
    direct=b[cols].copy()
    qx=x.copy();qx.index=q.row_key
    ctx=qx.reindex(keys).reset_index(drop=True).add_prefix('ctx_')
    racekeys='부산:'+p.date+':'+p.race_no.astype(str)
    race_x=rx.reindex(racekeys).reset_index(drop=True).add_prefix('race_')
    direct=pd.concat([direct,ctx,race_x],axis=1)
    assert direct.columns.is_unique
    extras={}
    for name in ['I','J']:
        aa=aux.set_index('row_key')[[name+'_'+c for c in STACK_COLS]].reindex(keys)
        aa.columns=['forecast_'+c for c in STACK_COLS]
        extras[name]=aa.reset_index(drop=True)
    return p,b[cols],direct,extras


def finish_models(q,x,races,rx,aux):
    path=O/'finish_predictions.parquet'
    if path.exists():return pd.read_parquet(path)
    p,b,d,extra=main_inputs(q,x,races,rx,aux)
    cols={name:list(d.columns)+(['forecast_'+c for c in STACK_COLS] if name in ['I','J'] else [])
          for name in ['D','I','J']}
    save('feature_contract.json',dict(auxiliary_horse=list(x.columns),auxiliary_race=list(rx.columns),
          base=list(b.columns),direct=list(d.columns),stack=STACK_COLS,
          downstream_counts={k:len(v) for k,v in cols.items()},jockey_trainer_features=False,
          early_training_start=2018,finish_training_start=2017,early_external_years=list(range(2020,2027))))
    parts=[]
    for year in YEARS:
        tr=p.year.between(2017,year-1)&p.normal_n.ge(6)
        te=p.year.eq(year)&p.normal_n.ge(6)
        out=p.loc[te,['row_id','date','race_no','horse_id','program_no','year','distance',
                      'grade','finish_rank','performance','normal_n']].copy()
        out['source_key']='부산:'+out.date+':'+out.race_no.astype(str)
        base=lgb.Booster(model_file=str(OLD/'models'/f'B3_{year}.txt'))
        out['score_B']=base.predict(b.loc[te],num_threads=4)
        for name in ['D','I','J']:
            xx=d if name=='D' else pd.concat([d,extra[name]],axis=1)
            fitted=fit(f'{year}_finish_{name}',xx.loc[tr],p.loc[tr,'performance'],
                    1/p.loc[tr,'normal_n'],MAIN_PARAMS|dict(objective='regression'),
                    120,pd.to_datetime(p.loc[tr,'date']))
            out['score_'+name]=fitted.predict(xx.loc[te],num_threads=4)
        parts.append(out)
    out=pd.concat(parts,ignore_index=True)
    frozen=pd.read_parquet(OLD/'predictions.parquet')[['row_id','raw_B3']]
    comp=out.merge(frozen,on='row_id',validate='one_to_one')
    np.testing.assert_allclose(comp.score_B,comp.raw_B3,atol=1e-12,rtol=0)
    assert len(out)==21452 and out.source_key.nunique()==1976
    out.to_parquet(path,index=False)
    return out


def quinella(r1,r2):
    """Original-rank settlement including first/second dead heats."""
    if r1==1 and r2==1:return True
    return (r1==1 and r2==2) or (r1==2 and r2==1)


def finish_metrics(pred):
    rows=[]
    for key,g in pred.groupby('source_key',sort=True):
        r=dict(source_key=key,date=str(g.date.iloc[0]),year=int(g.year.iloc[0]),
               distance=int(g.distance.iloc[0]),grade=str(g.grade.iloc[0]),n=len(g))
        target=g.performance.to_numpy()
        for name in MODELS:
            chosen=g.sort_values(['score_'+name,'program_no'],ascending=[False,True])
            ranks=chosen.finish_rank.to_numpy();score=g['score_'+name].to_numpy()
            r[name+'_axis_top3']=int(ranks[0]<=3)
            r[name+'_axis_top2']=int(ranks[0]<=2)
            r[name+'_win']=int(ranks[0]==1)
            r[name+'_quinella_one']=int(quinella(ranks[0],ranks[1]))
            r[name+'_axis_next3']=int(any(quinella(ranks[0],v) for v in ranks[1:4]))
            r[name+'_mae']=float(np.abs(score-np.median(score)-target).mean())
            r[name+'_axis_program']=int(chosen.program_no.iloc[0])
        rows.append(r)
    rr=pd.DataFrame(rows);rr.to_csv(O/'race_metrics.csv',index=False,encoding='utf-8-sig')
    summary=[]
    for window in ['all']+list(map(str,YEARS)):
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        for name in MODELS:
            row=dict(window=window,model=name,races=len(z))
            for metric in ['axis_top3','axis_top2','win','quinella_one','axis_next3','mae']:
                row[metric]=float(z[name+'_'+metric].mean())
                if metric!='mae':row[metric+'_hits']=int(z[name+'_'+metric].sum())
            summary.append(row)
    pd.DataFrame(summary).to_csv(O/'finish_metrics.csv',index=False)
    differences=[]
    for window in ['all']+list(map(str,YEARS)):
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        for new,old in [('I','D'),('J','I'),('J','D'),('D','B'),('J','B')]:
            for metric in ['axis_top3','quinella_one','axis_next3','win','mae']:
                delta=z[new+'_'+metric]-z[old+'_'+metric]
                days=z.assign(delta=delta).groupby('date').agg(s=('delta','sum'),n=('delta','size'))
                rng=np.random.default_rng(SEED)
                ix=rng.integers(0,len(days),size=(2000,len(days)))
                boot=days.s.to_numpy()[ix].sum(axis=1)/days.n.to_numpy()[ix].sum(axis=1)
                lo,hi=np.quantile(boot,[.025,.975])
                centered=boot-delta.mean()
                pval=(1+np.sum(np.abs(centered)>=abs(delta.mean())))/2001
                differences.append(dict(window=window,new=new,old=old,metric=metric,
                    n=len(z),difference=float(delta.mean()),lower=float(lo),upper=float(hi),
                    p_boot=float(pval),gained=int(((z[new+'_'+metric]>0)&(z[old+'_'+metric]==0)).sum()) if metric!='mae' else None,
                    lost=int(((z[new+'_'+metric]==0)&(z[old+'_'+metric]>0)).sum()) if metric!='mae' else None))
    dif=pd.DataFrame(differences)
    primary=dif.window.eq('all')&dif.metric.isin(['axis_top3','quinella_one'])&dif.old.isin(['D','I'])
    assert primary.sum()==6
    dif.loc[primary,'bh_q_primary6']=false_discovery_control(dif.loc[primary,'p_boot'])
    dif.to_csv(O/'paired_comparisons.csv',index=False)
    dist=[]
    for (year,distance),g in rr.groupby(['year','distance']):
        for name in MODELS:
            dist.append(dict(year=int(year),distance=int(distance),model=name,races=len(g),
                axis_top3=float(g[name+'_axis_top3'].mean()),quinella_one=float(g[name+'_quinella_one'].mean())))
    pd.DataFrame(dist).to_csv(O/'distance_metrics.csv',index=False)
    return rr


def aux_metrics(aux,races):
    rows=[];earlyr=[]
    for year in YEARS:
        z=aux[aux.year.eq(year)&aux.group_observed].copy()
        actual=z.role4.eq(0).to_numpy(float);top3=z.raw_finish_rank.between(1,3).to_numpy(float)
        for name in ['I','J']:
            p=z[name+'_front'].to_numpy()
            retain=z[name+'_top3_mixture'].to_numpy()
            rc=[]
            for key,g in z.groupby('source_key'):
                if len(g)!=g.field_size.iloc[0]:continue
                true=int(g.role4.eq(0).sum())
                pi=g[[name+'_count1',name+'_count2',name+'_count3p']].iloc[0].to_numpy(float)
                # Cardinality-only reweighting preserves the raw probability order.
                # Use that exact order to prevent floating point ties changing the chosen gate.
                cls=min(true-1,2);best=g.sort_values(['raw_lead','gate'],ascending=[False,True]).iloc[0]
                rr=dict(year=year,model=name,source_key=key,actual_count=true,
                        predicted_count=float(g[name+'_front'].sum()),
                        predicted_bin=int(pi.argmax()),actual_bin=cls,
                        top_in_first_group=int(best.role4==0),
                        count_brier=float(np.square(pi-np.eye(3)[cls]).sum()),
                        count_nll=float(-np.log(max(pi[cls],1e-15))))
                rc.append(rr);earlyr.append(rr)
            rc=pd.DataFrame(rc)
            rows.append(dict(year=year,model=name,starts=len(z),races=len(rc),
                front_brier=float(np.square(p-actual).mean()),
                front_logloss=float(np.mean(-actual*np.log(np.clip(p,1e-15,1))-(1-actual)*np.log(np.clip(1-p,1e-15,1)))),
                top_first_group_hit=float(rc.top_in_first_group.mean()),
                count_accuracy=float(rc.predicted_bin.eq(rc.actual_bin).mean()),
                count_mae=float(abs(rc.predicted_count-rc.actual_count).mean()),
                count_brier=float(rc.count_brier.mean()),count_nll=float(rc.count_nll.mean()),
                top3_mixture_brier=float(np.square(retain-top3).mean())))
    pd.DataFrame(rows).to_csv(O/'aux_metrics.csv',index=False)
    pd.DataFrame(earlyr).to_csv(O/'aux_race_metrics.csv',index=False)
    calibration=[]
    for year in YEARS:
        z=aux[aux.year.eq(year)&aux.group_observed]
        for name in ['I','J']:
            for field,target in [('front',z.role4.eq(0)),('top3_mixture',z.raw_finish_rank.between(1,3))]:
                pp=z[name+'_'+field];bins=np.minimum((pp*10).astype(int),9)
                zz=pd.DataFrame(dict(p=pp.to_numpy(),actual=target.to_numpy(),bin=bins.to_numpy()))
                for b,g in zz.groupby('bin'):
                    calibration.append(dict(year=year,model=name,target=field,bin=int(b),n=len(g),
                                           predicted=float(g.p.mean()),actual=float(g.actual.mean())))
    pd.DataFrame(calibration).to_csv(O/'calibration.csv',index=False)


def main():
    check()
    q,x,races,rx=prepare()
    aux,counts=auxiliary(q,x,races,rx)
    pred=finish_models(q,x,races,rx,aux)
    finish_metrics(pred);aux_metrics(aux,counts)
    save('run_summary.json',dict(venue='부산',evaluation_races=1976,evaluation_starts=21452,
         years=YEARS,aux_models=21,finish_models=9,reused_base_models=3,
         source_end='2026-09-18',training_labels_start=2017,aux_training_start=2018,
         prior_history_tminus2=True,current_actual_pace_passed_to_inference=False,
         jockey_trainer_used=False,new_database_access=False,operating_changed=False,
         future_independent_validation=False))
    check()
    print(pd.read_csv(O/'finish_metrics.csv').to_string(index=False),flush=True)
    print(pd.read_csv(O/'aux_metrics.csv').to_string(index=False),flush=True)


if __name__=='__main__':main()
