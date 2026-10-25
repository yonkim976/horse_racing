"""Chronological OOF learning of axis-switch gain/loss; no promotion."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
P=R/'20261012_full103_retention_v1/outputs'
B=R/'20261009_gate_front_late_v1/outputs'
KEY=['race_key','program_no','horse_id']
METRICS=['axis_top3','axis_top2','axis_win','quinella_one','axis_next3']
HORSE=['keep_fast_g3','keep_fast_g1','keep_fast_n','keep_fast_keep',
       'moist_last3_record_index_mean','profile_count3','profile_trend','record_field_adv',
       'front_gate_probability','gate_fraction','history_count','days_since_last']
BASECOLS=json.loads((P/'feature_contract.json').read_text())


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


S=module('axis_section_frozen',R/'20261009_section_style_finish_v1/run.py')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p,value):
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'PLAN.md',HERE/'run.py',P/'features.parquet',P/'runner_predictions.parquet',
           P/'race_diagnostics.csv',P/'feature_contract.json',P/'verification.json',
           S.HERE/'run.py',S.HERE/'config.json',
           R/'20261012_joint_axis_guard_v1/outputs/metrics.csv',
           ROOT/'config/prediction_model_registry.json',
           R/'20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
           R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    for parent,stem in [(P,'combined122'),(B,'full103')]:
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                paths += [parent/'models'/f'{stem}_{meet}_{year}'/n for n in ['model.txt','metadata.json']]
    manifest={str(p.relative_to(ROOT)):sha(p)for p in paths};target=OUT/'input_manifest.json'
    if target.exists():assert json.loads(target.read_text())==manifest
    else:save(target,manifest)
    before=OUT/'publication_before.json'
    if not before.exists():
        files=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p))for p in files})
        snap=OUT/'publication_before';snap.mkdir()
        for p in files:(snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())


def check():
    for path,digest in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/path)==digest,path


def past():
    check();f=pd.read_parquet(P/'features.parquet')
    for variant in ['baseline103','combined122']:
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2020,2021,2022,2023]:
                folder=OUT/'past_models'/f'{variant}_{meet}_{year}';folder.mkdir(parents=True,exist_ok=True)
                if not(folder/'runners.parquet').exists():
                    races,runners=S.fit(one,BASECOLS[variant],year,3,'switch_oof_'+variant,folder)
                    runners['variant']=variant;races['variant']=variant
                    runners.to_parquet(folder/'runners.parquet',index=False);races.to_csv(folder/'races.csv',index=False)
                print('Prior-only ability predictions',variant,meet,year,flush=True)
    check()


def load_predictions():
    allp=[pd.read_parquet(p)for p in sorted((OUT/'past_models').glob('*/runners.parquet'))]
    assert len(allp)==16
    p=pd.read_parquet(P/'runner_predictions.parquet')
    allp.append(p[p.variant.isin(['baseline103','combined122'])&p.target.eq(3)])
    p=pd.concat(allp,ignore_index=True);p['race_date']=pd.to_datetime(p.race_date)
    p=p.sort_values(['variant','race_key','raw_score','program_no'],ascending=[True,True,False,True])
    p['model_rank']=p.groupby(['variant','race_key']).cumcount()+1
    assert not p.duplicated(['variant']+KEY).any()
    return p


def build_pairs(f,p):
    """No current outcome or actual-section fields enter this function."""
    assert 'outcome'not in f and 'outcome'not in p
    assert not any(c.startswith('actual_')for c in f)
    f=f.copy();f['gate_fraction']=f.dirgate_inner_n/(f.field_size-1)
    f['record_field_adv']=f.moist_last3_record_index_mean-f.groupby('race_key').moist_last3_record_index_mean.transform('mean')
    sides=[]
    for variant,side in [('baseline103','old'),('combined122','new')]:
        a=p[p.variant.eq(variant)&p.model_rank.eq(1)][KEY+['target_probability']].merge(f,on=KEY,validate='one_to_one')
        sides.append(a.set_index('race_key').add_prefix(side+'_'))
    d=sides[0].join(sides[1],validate='one_to_one').reset_index()
    for c in ['year','meet','race_date','distance_m','grade','grade_kind','field_size']:
        assert d['old_'+c].equals(d['new_'+c]);d[c]=d['old_'+c]
    d['switched']=d.old_horse_id.ne(d.new_horse_id)
    numerical=[];categorical=['meet','grade_kind']
    for c in HORSE:
        d['delta_'+c]=d['new_'+c]-d['old_'+c]
        numerical += ['old_'+c,'new_'+c,'delta_'+c]
    numerical+=['distance_m','grade','field_size']
    lookup=p.set_index(['variant']+KEY)
    old_index=pd.MultiIndex.from_arrays([np.repeat('baseline103',len(d)),d.race_key,d.new_program_no,d.new_horse_id])
    new_index=pd.MultiIndex.from_arrays([np.repeat('combined122',len(d)),d.race_key,d.old_program_no,d.old_horse_id])
    d['new_rank_old']=lookup.model_rank.reindex(old_index).to_numpy()
    d['old_rank_new']=lookup.model_rank.reindex(new_index).to_numpy()
    d['old_model_probability_margin']=d.old_target_probability-lookup.target_probability.reindex(old_index).to_numpy()
    d['new_model_probability_margin']=d.new_target_probability-lookup.target_probability.reindex(new_index).to_numpy()
    numerical+=['old_target_probability','new_target_probability','old_model_probability_margin',
                'new_model_probability_margin','new_rank_old','old_rank_new']
    for section in ['g3','g1']:
        for context in ['support','recent']:
            name=section+'_x_'+context
            for side in ['old','new']:
                multiplier=d[side+'_keep_fast_n']/5 if context=='support'else d[side+'_record_field_adv']
                d[side+'_'+name]=d[side+'_keep_fast_'+section]*multiplier
            d['delta_'+name]=d['new_'+name]-d['old_'+name]
            numerical+=['old_'+name,'new_'+name,'delta_'+name]
    assert len(numerical)==57 and len(categorical)==2
    assert len(set(numerical+categorical))==59
    keep=['race_key','race_date','year','switched','old_program_no','old_horse_id','new_program_no','new_horse_id']+numerical+categorical
    return d[list(dict.fromkeys(keep))],dict(numeric=numerical,categorical=categorical)


def prepare():
    check();p=load_predictions();p.to_parquet(OUT/'base_predictions.parquet',index=False)
    columns=KEY+['race_date','year','meet','distance_m','grade','grade_kind','field_size','dirgate_inner_n']+[c for c in HORSE if c not in ['gate_fraction','record_field_adv']]
    f=pd.read_parquet(P/'features.parquet',columns=columns)
    d,contract=build_pairs(f,p.drop(columns='outcome'))
    label=p.set_index(['variant']+KEY).outcome
    for variant,side in [('baseline103','old'),('combined122','new')]:
        ix=pd.MultiIndex.from_arrays([np.repeat(variant,len(d)),d.race_key,d[side+'_program_no'],d[side+'_horse_id']])
        d[side+'_outcome']=label.reindex(ix).to_numpy()
    d['switch_outcome']=d.new_outcome.between(1,3).astype(int)-d.old_outcome.between(1,3).astype(int)
    assert d.loc[~d.switched,'switch_outcome'].eq(0).all()
    d.to_parquet(OUT/'pair_frame.parquet',index=False);save(OUT/'feature_contract.json',contract)
    count=d[d.switched].groupby(['year','switch_outcome']).size().unstack(fill_value=0)
    count.to_csv(OUT/'switch_training_counts.csv');check();print(count.to_string(),flush=True)


def fit_preprocess(d,contract):
    nums=contract['numeric'];a=d[nums].replace([np.inf,-np.inf],np.nan)
    median=a.median().fillna(0);filled=a.fillna(median);mean=filled.mean();scale=filled.std(ddof=0).replace(0,1)
    return dict(numeric=nums,median=median.tolist(),mean=mean.tolist(),scale=scale.tolist(),
        categories={c:sorted(d[c].dropna().astype(str).unique().tolist())for c in contract['categorical']},
        training_min=str(d.race_date.min().date()),training_max=str(d.race_date.max().date()),training_rows=len(d))


def transform(d,pre):
    a=d[pre['numeric']].replace([np.inf,-np.inf],np.nan).to_numpy(float)
    miss=np.isnan(a);filled=np.where(miss,np.array(pre['median']),a)
    x=[(filled-np.array(pre['mean']))/np.array(pre['scale']),miss.astype(float)]
    names=pre['numeric']+['missing_'+c for c in pre['numeric']]
    for col,values in pre['categories'].items():
        x.append(np.array([(d[col].astype(str)==v).to_numpy(float)for v in values]).T)
        names += [col+'='+v for v in values]
    matrix=np.column_stack(x);assert np.isfinite(matrix).all()
    return matrix,names


def selector_predict(d,folder,variant):
    assert not {'switch_outcome','old_outcome','new_outcome'}.intersection(d.columns)
    pre=json.loads((folder/'preprocess.json').read_text());x,names=transform(d,pre)
    if variant=='joint_logit':
        weights=json.loads((folder/'model.json').read_text())
        logits=x@np.array(weights['coef']).T+np.array(weights['intercept'])
        prob=softmax(logits,axis=1);assert weights['classes']==[-1,0,1]
    else:
        model=lgb.Booster(model_file=str(folder/'model.txt'));prob=model.predict(x,num_threads=1)
    assert prob.shape==(len(d),3)
    return prob


def learn():
    check();d=pd.read_parquet(OUT/'pair_frame.parquet');contract=json.loads((OUT/'feature_contract.json').read_text());pred=[]
    for year in [2024,2025,2026]:
        train=d[d.switched&d.year.between(2020,year-1)].copy()
        test=d[d.year.eq(year)].copy()
        assert train.year.max()<year and set(train.switch_outcome.unique())=={-1,0,1}
        pre=fit_preprocess(train,contract);x,names=transform(train,pre)
        for variant in ['joint_logit','joint_tree']:
            folder=OUT/'selector_models'/f'{variant}_{year}';folder.mkdir(parents=True,exist_ok=True)
            save(folder/'preprocess.json',pre)
            if variant=='joint_logit':
                model=LogisticRegression(C=.1,solver='lbfgs',max_iter=2000)
                model.fit(x,train.switch_outcome.to_numpy())
                assert int(model.n_iter_.max())<2000
                save(folder/'model.json',dict(coef=model.coef_.tolist(),intercept=model.intercept_.tolist(),
                     classes=model.classes_.tolist(),C=.1,features=names,iterations=model.n_iter_.tolist()))
                importance=pd.DataFrame(dict(feature=names,gain_minus_loss_coefficient=model.coef_[2]-model.coef_[0]))
            else:
                params=dict(objective='multiclass',num_class=3,learning_rate=.03,num_leaves=4,
                    min_data_in_leaf=60,lambda_l2=20,seed=20261013,num_threads=4,deterministic=True,
                    force_col_wise=True,verbosity=-1)
                model=lgb.train(params,lgb.Dataset(x,label=train.switch_outcome.to_numpy()+1,feature_name=[str(i)for i in range(len(names))]),num_boost_round=80)
                model.save_model(str(folder/'model.txt'))
                importance=pd.DataFrame(dict(feature=names,gain=model.feature_importance(importance_type='gain')))
            importance.to_csv(folder/'importance.csv',index=False)
            prob=selector_predict(test.drop(columns=['old_outcome','new_outcome','switch_outcome']),folder,variant);expected=prob[:,2]-prob[:,0]
            choose_new=~test.switched.to_numpy()|(expected>=0)
            out=test[['race_key','race_date','year','switched','old_program_no','old_horse_id','new_program_no','new_horse_id']].copy()
            out['variant']=variant;out['p_loss']=prob[:,0];out['p_neutral']=prob[:,1];out['p_gain']=prob[:,2]
            out['expected_switch_gain']=expected;out['choose_new']=choose_new
            out['axis_program_no']=np.where(choose_new,test.new_program_no,test.old_program_no)
            out['axis_horse_id']=np.where(choose_new,test.new_horse_id,test.old_horse_id)
            pred.append(out)
            save(folder/'metadata.json',dict(variant=variant,evaluation_year=year,training_years=[2020,year-1],
                training_max_date=str(train.race_date.max().date()),training_rows=len(train),
                outcome_counts={str(int(k)):int(v)for k,v in train.switch_outcome.value_counts().items()},
                features=names,raw_feature_count=59,encoded_feature_count=len(names),class_order=[-1,0,1],
                rule='P(gain)-P(loss)>=0 selects new122 anchor; no input eligibility filters',
                probability_scope='Conditional axis-switch outcome, not horse placing probability',
                test_labels_used=False,preprocess_sha256=sha(folder/'preprocess.json'),
                model_sha256=sha(folder/('model.json'if variant=='joint_logit'else'model.txt'))))
            print('Switch learner',variant,year,'prior cases',len(train),'fallback',int((test.switched.to_numpy()&~choose_new).sum()),flush=True)
    pd.concat(pred,ignore_index=True).to_parquet(OUT/'selector_predictions.parquet',index=False);check()


def windows(d):
    yield'all',d
    for year in [2024,2025,2026]:
        z=d[d.year.eq(year)];yield str(year),z
        yield f'{year}_to0920',z[z.race_date.dt.strftime('%m-%d').le('09-20')]


def evaluate(p,pred,d):
    rows=[];rankings=[];lookup=d.set_index('race_key')
    for variant in ['frozen103','frozen122','joint_logit','joint_tree']:
        source='baseline103'if variant=='frozen103'else'combined122'
        sel=None if variant.startswith('frozen')else pred[pred.variant.eq(variant)].set_index('race_key')
        for rid,g in p[p.variant.eq(source)&p.year.ge(2024)].groupby('race_key',sort=False):
            g=g.sort_values('model_rank');row=lookup.loc[rid]
            axis=int(g.program_no.iloc[0]if sel is None else sel.loc[rid,'axis_program_no'])
            g=pd.concat([g[g.program_no.eq(axis)],g[g.program_no.ne(axis)]])
            truth=g.outcome.to_numpy();winners=set(g.loc[g.outcome.between(1,2),'program_no'])
            assert len(winners)==2 and g.outcome.between(1,3).sum()==3
            rows.append(dict(variant=variant,race_key=rid,race_date=row.race_date,year=int(row.year),meet=int(row.meet),
                distance_m=float(row.distance_m),grade=row.grade,field_size=int(row.field_size),
                axis_program_no=axis,axis_horse_id=g.horse_id.iloc[0],axis_outcome=int(truth[0]),
                switched=bool(row.switched),fallback=bool(axis!=row.new_program_no),
                axis_top3=int(1<=truth[0]<=3),axis_top2=int(1<=truth[0]<=2),axis_win=int(truth[0]==1),
                quinella_one=int(set(g.program_no.iloc[:2])==winners),
                axis_next3=int(axis in winners and winners<=set(g.program_no.iloc[:4]))))
            for n,r in enumerate(g.itertuples(),1):
                rankings.append(dict(variant=variant,race_key=rid,program_no=int(r.program_no),horse_id=r.horse_id,selection_rank=n))
    rr=pd.DataFrame(rows);rr.to_parquet(OUT/'race_metrics.parquet',index=False)
    pd.DataFrame(rankings).to_parquet(OUT/'selection_rankings.parquet',index=False)
    return rr


def analyse():
    check();p=pd.read_parquet(OUT/'base_predictions.parquet');pred=pd.read_parquet(OUT/'selector_predictions.parquet');d=pd.read_parquet(OUT/'pair_frame.parquet')
    rr=evaluate(p,pred,d);rows=[]
    for variant,z in rr.groupby('variant'):
        for period,g in windows(z):
            rows.append(dict(variant=variant,period=period,n=len(g),fallback=int(g.fallback.sum()),
                             **{m:float(g[m].mean())for m in METRICS}))
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False);pairs=[]
    for variant in ['joint_logit','joint_tree']:
        for reference in ['frozen122','frozen103']:
            z=rr[rr.variant.eq(variant)].merge(rr[rr.variant.eq(reference)][['race_key']+METRICS],on='race_key',suffixes=('','_ref'),validate='one_to_one')
            for period,g in windows(z):
                for metric in METRICS:
                    delta=g[metric]-g[metric+'_ref'];tmp=g[['race_date']].copy();tmp['delta']=delta
                    day=tmp.groupby('race_date').delta.agg(['sum','size']);rng=np.random.default_rng(20261013)
                    idx=rng.integers(len(day),size=(2000,len(day)))
                    values=day['sum'].to_numpy()[idx].sum(axis=1)/day['size'].to_numpy()[idx].sum(axis=1)
                    lo,hi=np.quantile(values,[.025,.975])
                    pairs.append(dict(variant=variant,reference=reference,period=period,metric=metric,n=len(g),
                        gain=int(delta.eq(1).sum()),loss=int(delta.eq(-1).sum()),net=int(delta.sum()),
                        difference_pp=float(delta.mean()*100),lo_pp=float(lo*100),hi_pp=float(hi*100)))
    pd.DataFrame(pairs).to_csv(OUT/'paired_differences.csv',index=False)
    details=pred.merge(d[['race_key','old_outcome','new_outcome','switch_outcome','meet','grade','distance_m','field_size']],on='race_key',validate='many_to_one')
    details['distance_band']=np.select([details.distance_m.le(1300),details.distance_m.le(1600)],['short','middle'],default='long')
    details.to_parquet(OUT/'selector_diagnostics.parquet',index=False);details[details.switched].to_csv(OUT/'switched_races.csv',index=False)
    transitions=[];conditions=[]
    for variant,z in details.groupby('variant'):
        for period,g in windows(z):
            for selected_new,a in g[g.switched].groupby('choose_new'):
                label=a.switch_outcome
                transitions.append(dict(variant=variant,period=period,choose_new=bool(selected_new),n=len(a),
                    original_gain=int(label.eq(1).sum()),original_loss=int(label.eq(-1).sum()),
                    both_hit=int((a.old_outcome.between(1,3)&a.new_outcome.between(1,3)).sum()),
                    both_miss=int((~a.old_outcome.between(1,3)&~a.new_outcome.between(1,3)).sum()),
                    change_net_vs122=0 if selected_new else int(-label.sum())))
            for col in ['meet','grade','distance_band']:
                for value,a in g.groupby(col,dropna=False,observed=True):
                    changed=a[a.switched&~a.choose_new];label=changed.switch_outcome
                    conditions.append(dict(variant=variant,period=period,condition=col,value=str(value),n=len(a),
                        fallback=len(changed),recovered=int(label.eq(-1).sum()),sacrificed=int(label.eq(1).sum()),net=int(-label.sum())))
    pd.DataFrame(transitions).to_csv(OUT/'switch_transitions.csv',index=False)
    pd.DataFrame(conditions).to_csv(OUT/'conditions.csv',index=False)
    check();print(pd.DataFrame(rows).query("period in ['all','2024','2025','2026']").to_string(index=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['past','prepare','learn','analyse']);args=parser.parse_args()
    with threadpool_limits(limits=1):
        freeze();dict(past=past,prepare=prepare,learn=learn,analyse=analyse)[args.stage]()


if __name__=='__main__':main()
