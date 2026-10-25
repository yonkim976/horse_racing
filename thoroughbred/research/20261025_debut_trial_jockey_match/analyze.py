"""Official trial/debut rider matching, frozen-model diagnostics and fixed additions."""

import json
import math
import time

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import linalg,stats
from scipy.special import logit
from sklearn.linear_model import LogisticRegression

from common import DB,HERE,IDENTITY,MODELS,OUT,PREVIOUS,QUALITY,ROOT,dump,independent_paths,parent,sha


def prepare():
    OUT.mkdir(exist_ok=True);MODELS.mkdir(exist_ok=True)
    audit=json.loads((PREVIOUS/'outputs/source_audit.json').read_text())
    assert sha(DB)==audit['inputs'][0]['sha256'],'Current source differs from parent; investigate before reuse'
    protected=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in independent_paths()]
    dump(OUT/'protected_inputs.json',protected)
    d=pd.read_parquet(PREVIOUS/'outputs/debut_cohort.parquet')
    d=d[d.primary_eligible].reset_index(drop=True)
    c=duckdb.connect(str(DB),read_only=True)
    c.register('r',d[['row_key','horse_id','date','cutoff','selected_trial_id','selected_trial_date','jockey_id_raw']])
    query="""SELECT r.row_key,t.jockey_id_for_completed_trial AS trial_jockey_id,
      t.jockey_name_with_review AS trial_jockey_name,t.api_jkNo AS trial_jockey_raw_id,
      t.jockey_id_review_status_with_official_web AS trial_jockey_identity_status,
      t.source_file AS identity_source_file,t.source_item_index AS identity_source_item_index,
      t.api_rcTime AS identity_source_time
      FROM r JOIN trial_participants_entity_reviewed t ON r.selected_trial_id=t.participant_row_id"""
    (OUT/'identity_query.sql').write_text(query+'\n')
    ident=c.execute(query).df();d=d.merge(ident,on='row_key',validate='one_to_one')
    known=d.trial_jockey_id.fillna('').str.fullmatch('[0-9A-Z]{6}')&d.jockey_id_raw.fillna('').str.fullmatch('[0-9A-Z]{6}')
    d['last_same']=np.where(known,d.trial_jockey_id.eq(d.jockey_id_raw).astype(float),np.nan)
    d['rider_group']=np.select([~known,d.last_same.eq(1)],['unknown','same'],default='different')
    assert pd.to_numeric(d.identity_source_time).gt(0).all()
    query="""SELECT r.row_key,
      count(t.participant_row_id) FILTER(WHERE t.jockey_id_for_completed_trial=r.jockey_id_raw) AS any_same_completed_count,
      max(cast(t.trial_date AS DATE)) FILTER(WHERE t.jockey_id_for_completed_trial=r.jockey_id_raw) AS last_same_completed_date,
      arg_max(t.jockey_id_for_completed_trial,struct_pack(d:=cast(t.trial_date AS DATE),n:=try_cast(t.trial_no AS INTEGER),k:=t.participant_row_id)) AS last_completed_jockey_id,
      max(cast(t.trial_date AS DATE)) AS last_completed_date
      FROM r LEFT JOIN trial_participants_entity_reviewed t ON lpad(t.resolved_horse_id,7,'0')=r.horse_id
      AND cast(t.trial_date AS DATE)<=r.cutoff AND cast(t.trial_date AS DATE)>=r.date-INTERVAL 365 DAY
      AND try_cast(t.api_rcTime AS DOUBLE)>0 AND t.jockey_id_for_completed_trial IS NOT NULL
      GROUP BY r.row_key"""
    (OUT/'any_completed_query.sql').write_text(query+'\n')
    d=d.merge(c.execute(query).df(),on='row_key',validate='one_to_one')
    d['any_same_completed']=d.any_same_completed_count.gt(0)
    d['latest_completed_same']=d.last_completed_jockey_id.eq(d.jockey_id_raw)
    d['continuity_group']=np.select([d.rider_group.eq('unknown'),d.last_same.eq(1),d.any_same_completed],
        ['unknown','last_same','last_different_but_seen_same'],default='last_different_no_seen_same')
    assert (~d.last_same.eq(1)|d.any_same_completed).all()
    assert d.last_completed_date.le(d.cutoff).all()
    windows=[]
    for name,anchor in [('at_trial','selected_trial_date'),('at_debut','date')]:
        w=d[['row_key','trial_jockey_id',anchor]].rename(columns={anchor:'anchor'}).copy()
        w['window']=name;w['history_cutoff']=w.anchor-pd.Timedelta(days=2);windows.append(w)
    w=pd.concat(windows,ignore_index=True);c.register('w',w)
    query="""SELECT w.row_key,w.window,count(p.horse_id_raw) AS history_n,
      (coalesce(sum(CASE WHEN p.result_rank_raw='1' THEN 1 ELSE 0 END),0)+2)/(count(p.horse_id_raw)+20.0) AS prior_win,
      (coalesce(sum(CASE WHEN try_cast(p.result_rank_raw AS INTEGER) BETWEEN 1 AND 3 THEN 1 ELSE 0 END),0)+5)/(count(p.horse_id_raw)+20.0) AS prior_top3,
      max(p.result_date) AS history_last
      FROM w LEFT JOIN confirmed_runners p ON p.jockey_id_raw=w.trial_jockey_id
      AND p.result_date<=strftime(w.history_cutoff,'%Y%m%d')
      AND p.result_date>=strftime(w.anchor-INTERVAL 365 DAY,'%Y%m%d')
      AND (try_cast(p.result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR p.result_rank_raw IN ('91','92'))
      GROUP BY w.row_key,w.window"""
    (OUT/'jockey_quality_query.sql').write_text(query+'\n')
    quality=c.execute(query).df();c.close()
    for name in ['at_trial','at_debut']:
        f=quality[quality.window.eq(name)].drop(columns='window')
        f=f.rename(columns={k:'trial_j_'+name+'_'+k for k in ['history_n','prior_win','prior_top3','history_last']})
        d=d.merge(f,on='row_key',validate='one_to_one')
        d['trial_j_'+name+'_history_last']=pd.to_datetime(d['trial_j_'+name+'_history_last'],format='%Y%m%d')
        anchor=d.selected_trial_date if name=='at_trial' else d.date
        last=d['trial_j_'+name+'_history_last']
        assert (last.isna()|last.le(anchor-pd.Timedelta(days=2))).all()
    d['jockey_win_gap']=d.jockey_prior_win-d.trial_j_at_debut_prior_win
    d['jockey_top3_gap']=d.jockey_prior_top3-d.trial_j_at_debut_prior_top3
    same=d[d.last_same.eq(1)]
    assert np.allclose(same.jockey_prior_win,same.trial_j_at_debut_prior_win)
    assert np.allclose(same.jockey_prior_top3,same.trial_j_at_debut_prior_top3)
    assert same.jockey_history_n.eq(same.trial_j_at_debut_history_n).all()
    d.to_parquet(OUT/'rider_features.parquet',index=False)
    d.groupby(['meet','year','rider_group','trial_jockey_identity_status'],dropna=False).size().rename('n').reset_index().to_csv(OUT/'identity_coverage.csv',index=False)
    dump(OUT/'source_audit.json',dict(inputs=audit['inputs'],rows=len(d),selected_trial_identity_rows=len(ident),unknown_match_rows=int((~known).sum()),
        source_end_by_meet=audit['starts_end_by_meet'],completed_trial_id_only=True,names_used_for_match=False,
        historical_entry_jockey_availability_certified=False,parent_files_protected=len(protected),production_changed=False))
    print('IDENTITY',len(d),d.rider_group.value_counts().to_dict(),flush=True)
    return d


def group_metrics(g,probability=None,target='top3'):
    result=dict(n=len(g),wins=int(g.win.sum()),top3_events=int(g.top3.sum()),win_rate=float(g.win.mean()),top3_rate=float(g.top3.mean()),
        mean_trial_finish=float(g.finish.mean()),mean_gap_days=float(g.trial_gap_days.mean()),
        current_jockey_top3=float(g.jockey_prior_top3.mean()),trial_jockey_top3=float(g.trial_j_at_debut_prior_top3.mean()))
    if probability is not None:
        z=g.copy();z['p']=z[probability];z['target']=target
        result.update(parent.score(z));result['residual_mean']=float((z[target]-z.p).mean())
    return result


def cluster(g,influence,estimate):
    s=pd.Series(influence,index=g.index).groupby(g.date).sum().to_numpy()
    n=len(s);se=math.sqrt(float(s@s)*n/max(n-1,1));crit=stats.t.ppf(.975,max(n-1,1))
    return dict(estimate=float(estimate),se=se,ci_low=float(estimate-crit*se),ci_high=float(estimate+crit*se),dates=n)


def gaps(g,value):
    a=g[g.rider_group.eq('same')];b=g[g.rider_group.eq('different')]
    ma=a[value].mean();mb=b[value].mean()
    influence=np.where(g.rider_group.eq('same'),(g[value]-ma)/len(a),-(g[value]-mb)/len(b))
    return cluster(g,influence,ma-mb)


def association(g,target):
    z=g[g.rider_group.isin(['same','different'])].copy();p=np.clip(z.p,1e-6,1-1e-6)
    controls=pd.DataFrame(dict(logit=logit(p),logit_sq=logit(p)**2,log_gap=np.log1p(z.trial_gap_days),
        current_top3=z.jockey_prior_top3,current_win=z.jockey_prior_win,current_n=np.log1p(z.jockey_history_n),
        trial_pre_top3=z.trial_j_at_trial_prior_top3,trial_pre_win=z.trial_j_at_trial_prior_win,
        trial_now_top3=z.trial_j_at_debut_prior_top3,trial_now_win=z.trial_j_at_debut_prior_win,
        trial_n=np.log1p(z.trial_j_at_debut_history_n)),index=z.index)
    scale=controls.std(ddof=0);controls=controls.loc[:,scale.gt(1e-10)]/scale[scale.gt(1e-10)]
    results=[]
    mixed=z.groupby('race_key').rider_group.nunique().eq(2)
    for fixed in ['venue_year','race']:
        fe=z.meet+':'+z.year.astype(str) if fixed=='venue_year' else z.race_key
        a=pd.concat([z.last_same.rename('same'),controls,z[target].rename('outcome')],axis=1)
        a=a-a.groupby(fe).transform('mean')
        x=a.iloc[:,:-1].to_numpy(float);y=a.outcome.to_numpy(float)
        beta,_,rank,_=linalg.lstsq(x,y,cond=1e-10);inverse=linalg.pinv(x,rtol=1e-10)
        projector=inverse@x;assert np.max(abs(projector[0]-np.eye(x.shape[1])[0]))<1e-6
        residual=y-x@beta;df=len(z)-fe.nunique()-rank;assert df>0
        ci=cluster(z,inverse[0]*residual*math.sqrt(len(z)/df),beta[0])
        results.append(dict(target=target,fixed_effect=fixed,n=len(z),residual_df=int(df),mixed_races=int(mixed.sum()),
            mixed_race_runners=int(z.race_key.isin(mixed[mixed].index).sum()),**ci))
    return results


def frozen_analysis(d):
    p=pd.read_parquet(PREVIOUS/'outputs/predictions.parquet')
    p=p[p.model.isin(['total','sections'])].copy()
    extra=d[['row_key','rider_group','continuity_group','last_same','latest_completed_same','any_same_completed',
        'jockey_prior_top3','trial_j_at_debut_prior_top3','jockey_prior_win','jockey_history_n',
        'trial_j_at_trial_prior_top3','trial_j_at_trial_prior_win','trial_j_at_debut_prior_win','trial_j_at_debut_history_n']]
    p=p.merge(extra,on='row_key',validate='many_to_one')
    p.to_parquet(OUT/'frozen_predictions_grouped.parquet',index=False)
    raw=[];scores=[];differences=[];adjusted=[]
    for period,z in [('2018_2023',d[d.year.le(2023)]),('2024_2025',d[d.year.between(2024,2025)]),('2026_partial',d[d.year.eq(2026)]),('2024_2026',d[d.year.ge(2024)])]:
        for meet,g in [('all',z)]+list(z.groupby('meet')):
            for classification in ['rider_group','continuity_group']:
                for group,s in g.groupby(classification):
                    raw.append(dict(period=period,meet=meet,classification=classification,group=group,**group_metrics(s)))
    for algorithm,pp in p.groupby('algorithm'):
        subsets=[('all',pp)]+[(str(y),pp[pp.year.eq(y)]) for y in [2024,2025,2026]]+[(m,pp[pp.meet.eq(m)]) for m in ['서울','부산']]
        for subset,z in subsets:
            for (model,target),g in z.groupby(['model','target']):
                for group,s in g.groupby('rider_group'):
                    scores.append(dict(algorithm=algorithm,subset=subset,model=model,target=target,group=group,**group_metrics(s,'p',target)))
                known=g[g.rider_group.ne('unknown')].copy();known['residual']=known[target]-known.p
                for value in [target,'residual']:
                    differences.append(dict(algorithm=algorithm,subset=subset,model=model,target=target,
                        quantity='raw_gap' if value==target else 'actual_minus_expected_gap',**gaps(known,value)))
        if algorithm=='lightgbm':
            for target in ['top3','win']:
                g=pp[pp.model.eq('sections')&pp.target.eq(target)]
                adjusted.extend(association(g,target))
    pd.DataFrame(raw).to_csv(OUT/'raw_performance.csv',index=False)
    pd.DataFrame(scores).to_csv(OUT/'frozen_group_metrics.csv',index=False)
    pd.DataFrame(differences).to_csv(OUT/'performance_gaps.csv',index=False)
    pd.DataFrame(adjusted).to_csv(OUT/'adjusted_associations.csv',index=False)
    return p


def train(d):
    results=[];manifest=[]
    specs=[('lightgbm','sections','identity'),('lightgbm','sections','quality'),('lightgbm','sections','quality_identity'),
           ('lightgbm','total','identity'),('logistic','sections','identity')]
    for year in [2024,2025,2026]:
        ref=pd.read_parquet(PREVIOUS/f'outputs/reference_features_{year}.parquet')
        z=d.merge(ref,on='row_key',validate='one_to_one')
        tr=z[z.year<=year-2];ca=z[z.year.eq(year-1)];te=z[z.year.eq(year)]
        assert tr.date.max()<ca.date.min() and ca.date.max()<te.date.min()
        for algorithm,base,addition in specs:
            num,cat=parent.GROUPS[base]
            features=num+(IDENTITY if 'identity' in addition else [])+(QUALITY if 'quality' in addition else [])
            schema=parent.fit_schema(tr,features,cat)
            name=f'{algorithm}_{base}_{addition}_{year}'
            dump(MODELS/f'{name}_schema.json',schema)
            matrices=[parent.encode(x,schema) for x in [tr,ca,te]]
            print('FIT',year,algorithm,base,addition,'n',len(tr),len(ca),len(te),flush=True)
            for target in ['top3','win']:
                if algorithm=='lightgbm':
                    clf=lgb.LGBMClassifier(n_estimators=200,learning_rate=.04,num_leaves=7,min_child_samples=80,
                        reg_lambda=10,n_jobs=1,random_state=20261025,verbosity=-1)
                else:clf=LogisticRegression(C=.3,max_iter=3000,solver='lbfgs')
                clf.fit(matrices[0],tr[target])
                raw_cal=np.clip(clf.predict_proba(matrices[1])[:,1],1e-6,1-1e-6)
                raw_test=np.clip(clf.predict_proba(matrices[2])[:,1],1e-6,1-1e-6)
                cal=LogisticRegression(C=100,max_iter=2000).fit(logit(raw_cal).reshape(-1,1),ca[target])
                probability=cal.predict_proba(logit(raw_test).reshape(-1,1))[:,1]
                threshold=float(np.quantile(cal.predict_proba(logit(raw_cal).reshape(-1,1))[:,1],.8))
                out=te[['row_key','horse_id','race_key','meet','date','year','top3','win','rider_group']].copy()
                out['algorithm']=algorithm;out['base']=base;out['addition']=addition;out['target']=target
                out['p']=probability;out['p_raw']=raw_test;out['high_threshold']=threshold;out['high_group']=probability>=threshold
                results.append(out)
                path=MODELS/f'{name}_{target}.txt'
                if algorithm=='lightgbm':clf.booster_.save_model(str(path))
                else:
                    path=MODELS/f'{name}_{target}_coef.json';dump(path,dict(coef=clf.coef_[0].tolist(),intercept=float(clf.intercept_[0])))
                manifest.append(dict(algorithm=algorithm,base=base,addition=addition,year=year,target=target,
                    train_n=len(tr),cal_n=len(ca),test_n=len(te),train_end=str(tr.date.max().date()),cal_end=str(ca.date.max().date()),
                    model_file=str(path.relative_to(HERE)),schema_file=str((MODELS/f'{name}_schema.json').relative_to(HERE)),model_sha256=sha(path),
                    platt_coef=float(cal.coef_[0,0]),platt_intercept=float(cal.intercept_[0]),high_threshold=threshold))
    p=pd.concat(results,ignore_index=True);p.to_parquet(OUT/'extended_predictions.parquet',index=False)
    dump(OUT/'model_manifest.json',manifest)
    return p


def evaluate(new,frozen):
    base=frozen.rename(columns={'model':'base'}).copy();base['addition']='base'
    keys=['row_key','horse_id','race_key','meet','date','year','top3','win','rider_group','algorithm','base','addition','target','p']
    p=pd.concat([base[keys],new[keys]],ignore_index=True)
    metrics=[];intervals=[]
    subsets=[('all',p)]+[(str(y),p[p.year.eq(y)]) for y in [2024,2025,2026]]+[(m,p[p.meet.eq(m)]) for m in ['서울','부산']]+[(g,p[p.rider_group.eq(g)]) for g in ['same','different']]
    for subset,z in subsets:
        for (algorithm,model,addition,target),g in z.groupby(['algorithm','base','addition','target']):
            metrics.append(dict(subset=subset,algorithm=algorithm,base=model,addition=addition,target=target,**parent.score(g)))
        for (algorithm,model,target),g in z.groupby(['algorithm','base','target']):
            wide=g.pivot(index='row_key',columns='addition',values='p')
            context=g[g.addition.eq('base')][['row_key','date',target]].merge(wide,on='row_key',validate='one_to_one')
            if len(context)==0:continue
            pairs=[(x,'base') for x in wide.columns if x!='base']
            if 'quality_identity' in wide:pairs.append(('quality_identity','quality'))
            counts=context.groupby('date').size().to_numpy()
            rng=np.random.default_rng(20261025);weights=rng.multinomial(len(counts),np.full(len(counts),1/len(counts)),size=2000)
            denominator=weights@counts;y=context[target].to_numpy(float)
            for loss in ['brier','logloss']:
                losses={}
                for col in wide:
                    prob=np.clip(context[col].to_numpy(float),1e-12,1-1e-12)
                    losses[col]=(prob-y)**2 if loss=='brier' else -y*np.log(prob)-(1-y)*np.log1p(-prob)
                for extended,reference in pairs:
                    delta=losses[extended]-losses[reference]
                    daily=pd.Series(delta,index=context.index).groupby(context.date).sum().to_numpy()
                    sampled=weights@daily/denominator
                    intervals.append(dict(subset=subset,algorithm=algorithm,base=model,target=target,extended=extended,reference=reference,loss=loss,
                        n=len(context),dates=len(counts),estimate=float(delta.mean()),ci_low=float(np.quantile(sampled,.025)),ci_high=float(np.quantile(sampled,.975))))
    pd.DataFrame(metrics).to_csv(OUT/'extended_metrics.csv',index=False)
    pd.DataFrame(intervals).to_csv(OUT/'paired_loss_intervals.csv',index=False)


if __name__=='__main__':
    begin=time.time();data=prepare();fixed=frozen_analysis(data);new=train(data);evaluate(new,fixed)
    print('COMPLETE seconds',round(time.time()-begin,1),flush=True)
