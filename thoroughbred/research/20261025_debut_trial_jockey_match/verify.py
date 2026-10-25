"""Independent identity/date checks, source preservation and model replay."""

import importlib.util
import json

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import linalg
from scipy.special import expit,logit
from scipy.stats import rankdata

from common import DB,HERE,OUT,PREVIOUS,ROOT,dump,sha

spec=importlib.util.spec_from_file_location('debut_parent_replay',PREVIOUS/'verify.py')
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)


def weighted_auc(weights,y,p):
    order=np.argsort(p,kind='stable');labels=np.asarray(y)[order];scores=np.asarray(p)[order]
    starts=np.r_[0,np.flatnonzero(np.diff(scores)!=0)+1]
    wp=np.add.reduceat(weights[:,order]*labels[None,:],starts,axis=1)
    wn=np.add.reduceat(weights[:,order]*(1-labels)[None,:],starts,axis=1)
    den=wp.sum(axis=1)*wn.sum(axis=1)
    return np.sum(wp*(np.cumsum(wn,axis=1)-.5*wn),axis=1)/den


def auc(y,p):
    y=np.asarray(y);r=rankdata(p,method='average');n1=y.sum();n0=len(y)-n1
    return (r[y==1].sum()-n1*(n1+1)/2)/(n1*n0)


def main():
    d=pd.read_parquet(OUT/'rider_features.parquet');n=pd.read_parquet(OUT/'extended_predictions.parquet')
    f=pd.read_parquet(OUT/'frozen_predictions_grouped.parquet')
    audit=json.loads((OUT/'source_audit.json').read_text())
    assert sha(DB)==audit['inputs'][0]['sha256']
    protected=json.loads((OUT/'protected_inputs.json').read_text())
    for r in protected:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    assert d.horse_id.is_unique and len(d)==8884
    c=duckdb.connect(str(DB),read_only=True)
    c.register('r',d[['row_key','selected_trial_id','source_file','source_item_index']])
    source=c.execute("""SELECT r.row_key,t.jockey_id_for_completed_trial AS trial_id,p.jockey_id_raw AS race_id,
      t.api_rcTime AS trial_time FROM r JOIN trial_participants_entity_reviewed t
      ON t.participant_row_id=r.selected_trial_id JOIN confirmed_runners p
      ON p.source_file=r.source_file AND try_cast(p.source_item_index AS BIGINT)=try_cast(r.source_item_index AS BIGINT)""").df()
    check=d.merge(source,on='row_key',validate='one_to_one')
    assert len(check)==8884 and check.trial_jockey_id.eq(check.trial_id).all() and check.jockey_id_raw.eq(check.race_id).all()
    assert check.last_same.eq(check.trial_id.eq(check.race_id)).all()
    assert pd.to_numeric(check.trial_time).gt(0).all()
    for row in d.sample(40,random_state=20261025).itertuples():
        events=c.execute("""SELECT cast(trial_date AS DATE),try_cast(trial_no AS INTEGER),participant_row_id,
          jockey_id_for_completed_trial FROM trial_participants_entity_reviewed
          WHERE lpad(resolved_horse_id,7,'0')=? AND cast(trial_date AS DATE)<=?::DATE
          AND cast(trial_date AS DATE)>=?::DATE-INTERVAL 365 DAY AND try_cast(api_rcTime AS DOUBLE)>0
          AND jockey_id_for_completed_trial IS NOT NULL ORDER BY 1,2,3""",[row.horse_id,row.cutoff,row.date]).fetchall()
        same=[x for x in events if x[3]==row.jockey_id_raw]
        assert len(same)==row.any_same_completed_count
        assert events[-1][3]==row.last_completed_jockey_id
        for window,anchor in [('at_trial',row.selected_trial_date),('at_debut',row.date)]:
            t=c.execute("""SELECT count(*),sum(CASE WHEN result_rank_raw='1' THEN 1 ELSE 0 END),
              sum(CASE WHEN try_cast(result_rank_raw AS INTEGER) BETWEEN 1 AND 3 THEN 1 ELSE 0 END),max(result_date)
              FROM confirmed_runners WHERE jockey_id_raw=? AND result_date<=strftime(?::DATE-INTERVAL 2 DAY,'%Y%m%d')
              AND result_date>=strftime(?::DATE-INTERVAL 365 DAY,'%Y%m%d')
              AND (try_cast(result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR result_rank_raw IN ('91','92'))""",
              [row.trial_jockey_id,anchor,anchor]).fetchone()
            prefix='trial_j_'+window+'_'
            assert t[0]==getattr(row,prefix+'history_n')
            assert abs(((t[1] or 0)+2)/(t[0]+20)-getattr(row,prefix+'prior_win'))<1e-12
            assert abs(((t[2] or 0)+5)/(t[0]+20)-getattr(row,prefix+'prior_top3'))<1e-12
    c.close()
    original=pd.read_parquet(PREVIOUS/'outputs/predictions.parquet')
    for keys,g in f.groupby(['algorithm','model','target','year']):
        a=original
        for col,value in zip(['algorithm','model','target','year'],keys,strict=True):a=a[a[col].eq(value)]
        z=g.merge(a[['row_key','p']],on='row_key',suffixes=('_new','_old'),validate='one_to_one')
        assert len(z)==len(a) and np.array_equal(z.p_new,z.p_old)
    manifest=json.loads((OUT/'model_manifest.json').read_text());max_error=0.;predictions_checked=0;usage=[]
    for r in manifest:
        year=r['year'];ref=pd.read_parquet(PREVIOUS/f'outputs/reference_features_{year}.parquet')
        allrows=d.merge(ref,on='row_key',validate='one_to_one')
        train=allrows[allrows.year<=year-2];cal=allrows[allrows.year.eq(year-1)]
        assert len(train)==r['train_n'] and len(cal)==r['cal_n'] and train.date.max()<cal.date.min()
        assert train.date.max()==pd.Timestamp(r['train_end']) and cal.date.max()==pd.Timestamp(r['cal_end'])
        pred=n[n.algorithm.eq(r['algorithm'])&n.base.eq(r['base'])&n.addition.eq(r['addition'])&n.target.eq(r['target'])&n.year.eq(year)]
        assert len(pred)==r['test_n'] and pred.row_key.is_unique
        assert set(train.horse_id).isdisjoint(pred.horse_id) and cal.date.max()<pred.date.min()
        schema=json.loads((HERE/r['schema_file']).read_text());path=HERE/r['model_file'];assert sha(path)==r['model_sha256']
        assert not {'horse_id','trial_jockey_id','jockey_id_raw','trial_jockey_name','top3','win'}.intersection(schema['numeric']+schema['categorical'])
        rows=pred.sample(6,random_state=20261025);values=allrows.set_index('row_key').loc[rows.row_key]
        x=replay.independent_encode(values,schema);xcal=replay.independent_encode(cal,schema)
        if r['algorithm']=='lightgbm':
            booster=lgb.Booster(model_file=str(path));trees=booster.dump_model()['tree_info']
            raw=np.array([sum(replay.leaf(tree['tree_structure'],row) for tree in trees) for row in x])
            calraw=booster.predict(xcal,raw_score=True)
            if 'last_same' in schema['numeric']:
                ix=schema['numeric'].index('last_same')
                usage.append(dict(algorithm=r['algorithm'],base=r['base'],addition=r['addition'],year=year,target=r['target'],
                    identity_splits=int(booster.feature_importance('split')[ix]),identity_gain=float(booster.feature_importance('gain')[ix])))
        else:
            coef=json.loads(path.read_text());raw=x@np.array(coef['coef'])+coef['intercept'];calraw=xcal@np.array(coef['coef'])+coef['intercept']
            ix=schema['numeric'].index('last_same')
            usage.append(dict(algorithm=r['algorithm'],base=r['base'],addition=r['addition'],year=year,target=r['target'],
                identity_coef_per_match=float(coef['coef'][ix]/schema['scales'][ix])))
        probability=expit(r['platt_coef']*logit(np.clip(expit(raw),1e-6,1-1e-6))+r['platt_intercept'])
        error=float(np.max(np.abs(probability-rows.p.to_numpy())));assert error<1e-10
        expected_threshold=np.quantile(expit(r['platt_coef']*logit(np.clip(expit(calraw),1e-6,1-1e-6))+r['platt_intercept']),.8)
        assert abs(expected_threshold-r['high_threshold'])<1e-10
        assert pred.high_group.eq(pred.p.ge(expected_threshold)).all()
        max_error=max(max_error,error);predictions_checked+=len(rows)
    pd.DataFrame(usage).to_csv(OUT/'identity_feature_usage.csv',index=False)
    # Independent rank-based AUC and direct proper-score recomputation.
    full=f.rename(columns={'model':'base'}).copy();full['addition']='base'
    combined=pd.concat([full,n],ignore_index=True)
    metrics=pd.read_csv(OUT/'extended_metrics.csv')
    for row in metrics.itertuples():
        z=combined[combined.algorithm.eq(row.algorithm)&combined.base.eq(row.base)&combined.addition.eq(row.addition)&combined.target.eq(row.target)]
        if row.subset in ['same','different']:z=z[z.rider_group.eq(row.subset)]
        elif row.subset in ['서울','부산']:z=z[z.meet.eq(row.subset)]
        elif row.subset!='all':z=z[z.year.eq(int(row.subset))]
        y=z[row.target].to_numpy();p=z.p.to_numpy()
        assert len(z)==row.n and y.sum()==row.events
        assert abs(((p-y)**2).mean()-row.brier)<1e-12
        assert abs((-y*np.log(p)-(1-y)*np.log1p(-p)).mean()-row.logloss)<1e-12
        assert abs(auc(y,p)-row.auc)<1e-12
    # Auxiliary uncertainty for the two predeclared groups' frozen-model AUC.
    auc_rows=[]
    for target in ['top3','win']:
        z=f[f.algorithm.eq('lightgbm')&f.model.eq('sections')&f.target.eq(target)].reset_index(drop=True)
        code,dates=pd.factorize(z.date,sort=True);rng=np.random.default_rng(20261025)
        weight=rng.multinomial(len(dates),np.full(len(dates),1/len(dates)),size=2000)[:,code]
        distributions={};estimates={}
        for group in ['same','different']:
            mask=z.rider_group.eq(group).to_numpy()
            distributions[group]=weighted_auc(weight[:,mask],z.loc[mask,target].to_numpy(),z.loc[mask,'p'].to_numpy())
            estimates[group]=auc(z.loc[mask,target],z.loc[mask,'p'])
            auc_rows.append(dict(target=target,group=group,n=int(mask.sum()),estimate=estimates[group],
                ci_low=float(np.quantile(distributions[group],.025)),ci_high=float(np.quantile(distributions[group],.975))))
        diff=distributions['same']-distributions['different']
        auc_rows.append(dict(target=target,group='same_minus_different',n=len(z),estimate=estimates['same']-estimates['different'],
            ci_low=float(np.quantile(diff,.025)),ci_high=float(np.quantile(diff,.975))))
    pd.DataFrame(auc_rows).to_csv(OUT/'group_auc_intervals.csv',index=False)
    # Direct dummy least squares cross-check of the adjusted match coefficient.
    regression=pd.read_csv(OUT/'adjusted_associations.csv');reg_errors=[]
    for target in ['top3','win']:
        z=f[f.algorithm.eq('lightgbm')&f.model.eq('sections')&f.target.eq(target)].copy()
        v=logit(np.clip(z.p,1e-6,1-1e-6))
        control=pd.DataFrame(dict(logit=v,logit_sq=v*v,log_gap=np.log1p(z.trial_gap_days),current_top3=z.jockey_prior_top3,
            current_win=z.jockey_prior_win,current_n=np.log1p(z.jockey_history_n),trial_pre_top3=z.trial_j_at_trial_prior_top3,
            trial_pre_win=z.trial_j_at_trial_prior_win,trial_now_top3=z.trial_j_at_debut_prior_top3,
            trial_now_win=z.trial_j_at_debut_prior_win,trial_n=np.log1p(z.trial_j_at_debut_history_n)),index=z.index)
        scale=control.std(ddof=0);control=control.loc[:,scale.gt(1e-10)]/scale[scale.gt(1e-10)]
        for fixed in ['venue_year','race']:
            fe=z.meet+':'+z.year.astype(str) if fixed=='venue_year' else z.race_key
            x=np.column_stack([z.last_same,control,pd.get_dummies(fe,dtype=float)])
            coef=linalg.lstsq(x,z[target].to_numpy(float),cond=1e-10)[0][0]
            old=regression[regression.target.eq(target)&regression.fixed_effect.eq(fixed)].iloc[0].estimate
            error=abs(coef-old);assert error<1e-9;reg_errors.append(error)
    for r in protected:assert sha(ROOT/r['path'])==r['sha256']
    assert sha(DB)==audit['inputs'][0]['sha256']
    dump(OUT/'verification.json',dict(passed=True,official_identity_rows_checked=len(check),scalar_prior_windows=80,
        any_completed_source_windows=40,frozen_prediction_rows_preserved=len(f),models_replayed=len(manifest),
        scalar_new_predictions=predictions_checked,max_probability_replay_error=max_error,
        calibration_thresholds_checked=len(manifest),metric_groups_checked=len(metrics),
        independent_FE_regressions=4,max_FE_coefficient_error=max(reg_errors),auxiliary_group_auc_bootstrap=2000,
        parent_files_preserved=len(protected),source_DB_unchanged=True,names_not_used_for_identity=True,
        production_changed=False,prospective_validation=False))
    print('VERIFIED models',len(manifest),'probability error',max_error,flush=True)


if __name__=='__main__':main()
