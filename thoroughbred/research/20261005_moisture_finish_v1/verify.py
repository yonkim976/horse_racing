"""Independent feature derivation, trained-head replay and trio calculations."""
from pathlib import Path
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_outsider_joint_v1';MOIST=HERE.parent/'20261003_pace_gate_moisture_v2'
KEY=['race_key','program_no','horse_id']
spec=importlib.util.spec_from_file_location('independent_joint_design',PARENT/'verify.py')
OLD=importlib.util.module_from_spec(spec);spec.loader.exec_module(OLD)
REPLACE=['last_record_index','last3_record_index_mean','last5_record_index_mean','last10_record_index_mean',
         'last5_record_index_best','last10_record_index_best','last5_record_index_count','last10_record_index_count',
         'last5_record_index_std','record_index_change','same_distance_last_finish','same_distance_last5_finish_mean',
         'relative_last3_record_index_mean']
DERIVED=['upside_best_gap','upside_best_relative','upside_best_rank','upside_last_rank',
         'upside_low_history_best','upside_growth','upside_grade_best']
SUPPORT=['moist_last_correction_seconds','moist_last5_supported_fraction','moist_last5_abs_correction_mean']
checks=0;maximum=0.

def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def check(ok,message=''):
    global checks
    checks+=1
    if not ok:raise AssertionError(f'{checks}: {message}')
def close(a,b,tolerance=2e-10):
    global maximum
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    check(a.shape==b.shape);check(np.array_equal(np.isnan(a),np.isnan(b)))
    valid=np.isfinite(a)&np.isfinite(b)
    error=float(np.max(np.abs(a[valid]-b[valid]))) if valid.any() else 0.
    maximum=max(maximum,error);check(error<tolerance,f'error {error}')

def derived(f):
    out={}
    out['upside_best_gap']=f.last5_record_index_best-f.last3_record_index_mean
    g=f.last5_record_index_best.groupby(f.race_key)
    n=g.transform('count');total=g.transform('sum')
    relative=f.last5_record_index_best-(total-f.last5_record_index_best.fillna(0))/(n-f.last5_record_index_best.notna()).replace(0,np.nan)
    out['upside_best_relative']=relative
    for source,dest in [('last5_record_index_best','upside_best_rank'),('last_record_index','upside_last_rank')]:
        group=f[source].groupby(f.race_key);count=group.transform('count')
        out[dest]=((count-group.rank(ascending=False,method='average'))/(count-1)).where(count.gt(1))
    out['upside_low_history_best']=relative/(1+f.history_count)
    young=pd.Series(np.where(f.previous_age.isna(),np.nan,np.where(f.previous_age.le(4),1.,0.)),index=f.index)
    out['upside_growth']=f.record_index_change*young
    out['upside_grade_best']=f.context_grade_change.clip(-2,2)*relative
    return out

def independently_check_support(raw,adjusted):
    records=pd.read_parquet(MOIST/'outputs/adjusted_records.parquet')
    groups=dict(tuple(records.sort_values(['horse_id','race_date']).groupby('horse_id',sort=False)))
    expected=np.full((len(raw),3),np.nan);dates=np.full(len(raw),np.datetime64('NaT'),dtype='datetime64[ns]')
    for horse,ids in raw.groupby('horse_id',sort=False).indices.items():
        h=groups[horse];times=h.race_date.to_numpy('datetime64[ns]')
        positions=np.searchsorted(times,(raw.race_date.iloc[ids]-pd.Timedelta(days=2)).to_numpy('datetime64[ns]'),side='right')-1
        known=positions>=0;query=ids[known];pos=positions[known]
        valid=h.original_finish_valid.notna().to_numpy()
        delta=h.correction_seconds.to_numpy(float)
        expected[query,0]=np.where(valid[pos],delta[pos],np.nan);dates[query]=times[pos]
        end=pos+1;start=np.maximum(0,pos-4)
        counts=np.r_[0,np.cumsum(valid)]
        denominator=counts[end]-counts[start]
        for column,values in [(1,h.supported.to_numpy(float)),(2,abs(delta))]:
            sums=np.r_[0.,np.cumsum(np.where(valid,values,0.))]
            expected[query,column]=np.divide(sums[end]-sums[start],denominator,
                out=np.full(len(pos),np.nan),where=denominator>0)
    close(adjusted[SUPPORT],expected,1e-8)
    check(np.array_equal(adjusted.moist_support_source_date.to_numpy('datetime64[ns]'),dates,equal_nan=True))
    check((adjusted.moist_support_source_date.isna()|adjusted.moist_support_source_date.le(raw.race_date-pd.Timedelta(days=2))).all())
    close(records.finish_valid,records.original_finish_valid+records.correction_seconds)
    close(records.loc[~records.supported,'correction_seconds'],np.zeros((~records.supported).sum()))
    effects=pd.read_parquet(MOIST/'outputs/effects.parquet');supported=effects[effects.supported]
    check(supported.environment_trained_through.lt(supported.year).all())
    check(supported.band_days.ge(20).all() and supported.dry_days.ge(20).all())
    close(supported.correction_seconds,-supported.effect_seconds*supported.meet.map({1:.8,3:.9}))

def assemble(raw,adjusted,candidate):
    result=raw.copy()
    if candidate=='replace':
        result[REPLACE+DERIVED]=adjusted[REPLACE+DERIVED]
    else:
        for col in REPLACE+DERIVED:result['moist_'+col]=adjusted[col]
        result[SUPPORT]=adjusted[SUPPORT]
    return result

def main():
    audit=json.loads((OUT/'audit.json').read_text());summary=json.loads((OUT/'summary.json').read_text())
    for p,h in audit['inputs'].items():check(sha(ROOT/p)==h,p)
    for p,h in summary['artifacts'].items():check(sha(OUT/p)==h,p)
    raw=pd.read_parquet(PARENT/'outputs/features.parquet');adj=pd.read_parquet(OUT/'adjusted_features.parquet')
    check(len(raw)==len(adj)==178497);check(raw[KEY].equals(adj[KEY]))
    source=raw[KEY].merge(pd.read_parquet(MOIST/'outputs/moisture_features.parquet')[KEY+REPLACE],on=KEY,validate='one_to_one')
    close(adj[REPLACE],source[REPLACE]);corrected=raw.copy();corrected[REPLACE]=source[REPLACE]
    for col,value in derived(corrected).items():close(adj[col],value)
    independently_check_support(raw,adj)
    contract=json.loads((OUT/'feature_contract.json').read_text());check(len(contract['replace'])==261);check(len(contract['augment'])==284)
    forbidden={'outcome','race_key','horse_id','program_no','race_date','S1F_rank','G3F_rank','moist_support_source_date'}
    for cols in contract.values():check(not set(cols)&forbidden);check(len(cols)==len(set(cols)))
    labels=pd.read_parquet(HERE.parent/'20261004_pace_finish_stack_v1/outputs/labels.parquet')
    races=pd.read_csv(OUT/'race_metrics.csv');runners=pd.read_parquet(OUT/'runner_predictions.parquet');rec=pd.read_parquet(OUT/'recommendations.parquet')
    check(races.groupby('variant').race_key.nunique().to_dict()=={v:4799 for v in ['raw','raw_joint','replace','replace_joint','augment','augment_joint']})
    original=pd.read_parquet(PARENT/'outputs/runner_predictions.parquet')
    for a,b in [('raw','upside'),('raw_joint','upside_joint')]:
        paired=runners[runners.variant.eq(a)].merge(original[original.variant.eq(b)],on=KEY,validate='one_to_one',suffixes=('_new','_old'))
        check(len(paired)==50754);close(paired.prob_top3_new,paired.prob_top3_old)
    rg=dict(tuple(runners.groupby(['variant','race_key'])));cg=dict(tuple(rec.groupby(['variant','race_key'])))
    eg=races.set_index(['variant','race_key'])
    baseline={rid:g.sort_values('program_no').prob_top3.to_numpy() for rid,g in runners[runners.variant.eq('raw')].groupby('race_key')}
    for meet in (1,3):
        mask=raw.meet.eq(meet)
        for candidate in ('replace','augment'):
            features=assemble(raw.loc[mask].reset_index(drop=True),adj.loc[mask].reset_index(drop=True),candidate)
            for col in ['last3_start_200_mean','last3_last_200_mean','last3_last_600_mean','pace_last3_S1F_fraction']:
                close(features[col],raw.loc[mask,col])
            for year in (2024,2025,2026):
                frame=features.merge(labels,on=KEY,validate='one_to_one')
                g=frame[frame.year.isin([year-1,year])].reset_index(drop=True)
                path=OUT/'models'/f'{meet}_{year}_{candidate}';meta=json.loads((path/'metadata.json').read_text());pair=json.loads((path/'joint.json').read_text())
                check(meta['features']==contract[candidate]);check(meta['calibration_year']==year-1)
                check(pd.Timestamp(meta['train_end'])<pd.Timestamp(year-1,1,1));check(meta['validation_year']==year-2)
                check(sha(path/'top3.txt')==meta['model_sha256']);check(pair['training_year']==year-1)
                check(pair['success']);check(max(abs(np.array(pair['coefficients'])))<=1+1e-12)
                x=g[meta['features']].copy()
                for col,v in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=v)
                model=lgb.Booster(model_file=str(path/'top3.txt'));check(model.num_trees()==meta['trees'])
                scores=model.predict(x,raw_score=True,num_threads=4)
                energies=[];targets=[];designs=[];calmass={candidate:[],candidate+'_joint':[]};pairnll=[]
                for rid,ids in g.groupby('race_key',sort=False).indices.items():
                    one=g.iloc[ids];n=len(one);sets,_,_=OLD.support(n)
                    incidence=np.stack([(sets==i).any(axis=1).astype(float) for i in range(n)],axis=1)
                    e=scores[ids][sets].sum(axis=1);design=OLD.design(one)
                    truth=set(np.flatnonzero(one.outcome.le(3)));target=next(i for i,s in enumerate(sets) if set(s)==truth)
                    for variant,joint in [(candidate,None),(candidate+'_joint',pair)]:
                        energy=e/(meta['temperature'] if joint is None else joint['temperature'])
                        if joint is not None:energy+=((design-joint['mean'])/joint['scale'])@np.array(joint['coefficients'])
                        q=np.exp(energy-logsumexp(energy));m=q@incidence;best=np.argsort(-q,kind='stable')[:6];mass=float(q[best].sum())
                        if int(one.year.iloc[0])==year-1:
                            calmass[variant].append(mass)
                            if joint is not None:pairnll.append(-np.log(q[target]))
                            continue
                        saved=rg[(variant,rid)].sort_values('program_no');r=eg.loc[(variant,rid)];cs=cg[(variant,rid)].sort_values('selection_rank')
                        check(np.array_equal(one.program_no,saved.program_no));close(saved.raw_top3_score,scores[ids]);close(saved.prob_top3,m)
                        close(m.sum(),3.);close(q.sum(),1.);close(r.trio_nll,-np.log(q[target]));close(r.trio6_probability,mass)
                        check(r.trio6_hit==int(target in best));check(r.selected==int(mass>=meta['thresholds'][variant]))
                        expected=[','.join(map(str,sorted(one.program_no.iloc[sets[j]].astype(int)))) for j in best]
                        check(cs.programs.tolist()==expected);close(cs.probability,q[best]);check(cs.hit.sum()==r.trio6_hit)
                        rank=np.argsort(-m,kind='stable')
                        for k in (3,5,6,7):check(r[f'top{k}_contains_podium']==int(truth<=set(rank[:k])))
                        close(r.top3_brier,np.mean((m-one.outcome.le(3).to_numpy())**2))
                        br=np.argsort(-baseline[rid],kind='stable');outside=truth-set(br[:5]);inside=truth&set(br[:5])
                        check(r.baseline_outsiders==len(outside));check(r.rescued_outsiders==len(outside&set(rank[:5])));check(r.lost_insiders==len(inside-set(rank[:5])))
                    if int(one.year.iloc[0])==year-1:energies.append(e);targets.append(target);designs.append(design)
                width=max(map(len,energies));matrix=np.full((len(energies),width),-np.inf)
                actual=np.array([e[t] for e,t in zip(energies,targets)])
                for i,e in enumerate(energies):matrix[i,:len(e)]=e
                fit=minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-actual/t)),bounds=(.35,4),method='bounded')
                check(fit.success);close(meta['temperature'],fit.x)
                mean=np.mean([x.mean(axis=0) for x in designs],axis=0)
                scale=np.maximum(np.sqrt(np.mean([((x-mean)**2).mean(axis=0) for x in designs],axis=0)),.05)
                close(pair['mean'],mean);close(pair['scale'],scale);close(pair['penalty'],50/len(designs))
                penalty=.5*pair['penalty']*np.sum(np.array(pair['coefficients'])**2)
                close(pair['loss'],np.mean(pairnll)+penalty)
                for v,masses in calmass.items():close(meta['thresholds'][v],np.median(masses))
    table=pd.read_csv(OUT/'metrics.csv')
    for row in table.itertuples():
        g=races[races.meet.eq(row.meet)&races.variant.eq(row.variant)]
        if row.period!='all':g=g[g.evaluation_year.eq(int(row.period))]
        check(len(g)==row.races);check(g.trio6_hit.sum()==row.hits);close(row.trio6_hit,g.trio6_hit.mean())
        for metric in ['trio_nll','top3_brier','top5_contains_podium','top7_contains_podium']:close(getattr(row,metric),g[metric].mean())
    for p,h in audit['inputs'].items():check(sha(ROOT/p)==h,p)
    result=dict(passed=True,checks=checks,max_numeric_error=maximum,new_head_replays=12,
                policies=6,evaluated_races_per_policy=4799,inputs_unchanged=True,
                support_history_independently_derived_rows=178497,
                inherited_parent_outsider_reference='context5; use aligned supplementary metrics for raw5 comparisons')
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
