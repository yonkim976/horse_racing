"""Exact linear attribution of frozen 2026 grade6 axis-switch decisions."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import softmax

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
P=R/'20261013_axis_switch_learning_v1/outputs'
F=R/'20261012_full103_retention_v1/outputs/features.parquet'
OBS=R/'20261008_field_pace_prediction/outputs/observations.parquet'
MODEL=P/'selector_models/joint_logit_2026'
KEY=['race_key','program_no','horse_id']
EXTRA=['section_previous_distance','section_same_distance_n5','keep_front_n',
       'dirgate_inner_faster_n','inner_inner_fastest_gap','previous_age']
GROUPS=['blocked_gain','kept_gain','kept_both_hit','rescued_loss','kept_loss',
        'reverted_both_hit','reverted_both_miss','kept_both_miss']


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m);return m


E=module('switch_frozen_diagnosis',P.parent/'run.py')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'PLAN.md',HERE/'run.py',P.parent/'run.py',P/'pair_frame.parquet',P/'selector_predictions.parquet',
           P/'selector_diagnostics.parquet',P/'verification.json',P/'feature_contract.json',F,OBS,
           MODEL/'model.json',MODEL/'metadata.json',MODEL/'preprocess.json',
           ROOT/'config/prediction_model_registry.json',
           R/'20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
           R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
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
    for path,digest in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/path)==digest,path


def classify(d):
    return np.select([
        ~d.choose_new & d.switch_outcome.eq(1),d.choose_new & d.switch_outcome.eq(1),
        d.choose_new & d.old_outcome.between(1,3)&d.new_outcome.between(1,3),
        ~d.choose_new & d.switch_outcome.eq(-1),d.choose_new & d.switch_outcome.eq(-1),
        ~d.choose_new & d.old_outcome.between(1,3)&d.new_outcome.between(1,3),
        ~d.choose_new],GROUPS[:-1],default=GROUPS[-1])


def attribution_group(name):
    name=name.removeprefix('missing_')
    if '_g1_x_support'in name:return 'g1_support_interaction'
    if '_g3_x_support'in name:return 'g3_support_interaction'
    if '_g1_x_recent'in name:return 'g1_recent_interaction'
    if '_g3_x_recent'in name:return 'g3_recent_interaction'
    if 'keep_fast_g1'in name:return 'g1_level'
    if 'keep_fast_g3'in name:return 'g3_level'
    if 'keep_fast_n'in name or 'keep_fast_keep'in name:return 'observation_support'
    if any(c in name for c in ['moist_last3','profile_count3','profile_trend','record_field_adv']):return 'recent_records'
    if 'front_gate_probability'in name:return 'front_probability'
    if 'gate_fraction'in name:return 'gate_position'
    if 'history_count'in name or 'days_since_last'in name:return 'experience_interval'
    if any(c in name for c in ['target_probability','probability_margin','rank_old','rank_new']):return 'base_model_assessment'
    return 'race_context'


def prepare():
    allpairs=pd.read_parquet(P/'pair_frame.parquet')
    p=pd.read_parquet(P/'selector_predictions.parquet');p=p[p.variant.eq('joint_logit')]
    d=allpairs[allpairs.year.eq(2026)&allpairs.grade.eq(6)&allpairs.switched].copy()
    d=d.merge(p[['race_key','choose_new','p_loss','p_neutral','p_gain','expected_switch_gain']],on='race_key',validate='one_to_one')
    d['group']=classify(d);d['kept_hit']=d.choose_new&d.new_outcome.between(1,3)
    obs=pd.read_parquet(OBS,columns=['source_key','gate','horse_id','horse_name'])
    obs['race_key']=obs.source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    obs['program_no']=obs.gate
    extra=pd.read_parquet(F,columns=KEY+EXTRA)
    extra=extra.merge(obs[KEY+['horse_name']],on=KEY,how='left',validate='one_to_one').set_index(KEY)
    for side in ['old','new']:
        ix=pd.MultiIndex.from_arrays([d.race_key,d[side+'_program_no'],d[side+'_horse_id']])
        a=extra.loc[ix]
        for col in EXTRA+['horse_name']:d[side+'_'+col]=a[col].to_numpy()
        d[side+'_distance_change']=d.distance_m-d[side+'_section_previous_distance']
    for col in EXTRA+['distance_change']:d['delta_'+col]=d['new_'+col]-d['old_'+col]
    d['race_no']=d.race_key.str.rsplit(':',n=1).str[-1].astype(int)
    d=d.sort_values(['race_date','meet','race_no']).reset_index(drop=True)
    train=allpairs[allpairs.switched&allpairs.year.between(2020,2025)]
    pre=json.loads((MODEL/'preprocess.json').read_text());w=json.loads((MODEL/'model.json').read_text())
    x,names=E.transform(d,pre);tx,_=E.transform(train,pre)
    coef=np.array(w['coef']);intercept=np.array(w['intercept'])
    assert w['classes']==[-1,0,1] and names==w['features']
    logits=x@coef.T+intercept;prob=softmax(logits,axis=1)
    np.testing.assert_allclose(prob,d[['p_loss','p_neutral','p_gain']],atol=1e-12,rtol=0)
    beta=coef[2]-coef[0];reference=tx.mean(axis=0)
    baseline=float(intercept[2]-intercept[0]+reference@beta)
    contributions=(x-reference)*beta
    margin=logits[:,2]-logits[:,0]
    np.testing.assert_allclose(baseline+contributions.sum(axis=1),margin,atol=1e-12,rtol=0)
    np.testing.assert_allclose(margin,np.log(prob[:,2]/prob[:,0]),atol=1e-12,rtol=0)
    np.testing.assert_array_equal(margin>=0,d.choose_new)
    d['log_gain_loss_odds']=margin;d['reference_log_odds']=baseline
    rows=[]
    for i,row in d.iterrows():
        for j,name in enumerate(names):
            rows.append(dict(race_key=row.race_key,group=row.group,choose_new=bool(row.choose_new),
                feature=name,bundle=attribution_group(name),is_missing_indicator=name.startswith('missing_'),
                encoded_value=float(x[i,j]),training_reference=float(reference[j]),coefficient=float(beta[j]),
                contribution=float(contributions[i,j])))
    features=pd.DataFrame(rows);features.to_csv(OUT/'feature_contributions.csv',index=False)
    bundles=features.groupby(['race_key','group','choose_new','bundle'],sort=False).contribution.sum().reset_index()
    bundles.to_csv(OUT/'bundle_contributions.csv',index=False)
    # Summaries use all comparison types, not just successfully selected horses.
    summ=[]
    numeric=[c for c in E.HORSE if c in ['keep_fast_g3','keep_fast_g1','keep_fast_n','keep_fast_keep',
        'moist_last3_record_index_mean','profile_count3','profile_trend','record_field_adv',
        'front_gate_probability','gate_fraction','history_count','days_since_last']]+EXTRA+['distance_change']
    contexts=['distance_m','field_size','old_model_probability_margin','new_model_probability_margin','new_rank_old','old_rank_new','expected_switch_gain','log_gain_loss_odds']
    subsets={g:d[d.group.eq(g)]for g in GROUPS}
    subsets['kept_hit_all']=d[d.kept_hit];subsets['all_reverted']=d[~d.choose_new];subsets['all_kept']=d[d.choose_new]
    for label,g in subsets.items():
        for col in numeric:
            a,b=g['old_'+col],g['new_'+col];delta=b-a
            summ.append(dict(comparison_group=label,feature=col,races=len(g),
                old_n=int(a.notna().sum()),new_n=int(b.notna().sum()),paired_n=int(delta.notna().sum()),
                old_mean=a.mean(),new_mean=b.mean(),old_median=a.median(),new_median=b.median(),
                delta_mean=delta.mean(),delta_median=delta.median()))
        for col in contexts:
            a=g[col]
            summ.append(dict(comparison_group=label,feature=col,races=len(g),old_n=0,new_n=int(a.notna().sum()),paired_n=0,
                old_mean=np.nan,new_mean=a.mean(),old_median=np.nan,new_median=a.median(),delta_mean=np.nan,delta_median=np.nan))
    pd.DataFrame(summ).to_csv(OUT/'feature_comparisons.csv',index=False)
    rows=[]
    for label,g in subsets.items():
        ids=set(g.race_key);z=bundles[bundles.race_key.isin(ids)]
        for bundle,a in z.groupby('bundle'):
            rows.append(dict(comparison_group=label,bundle=bundle,n=len(a),mean=a.contribution.mean(),median=a.contribution.median()))
    pd.DataFrame(rows).to_csv(OUT/'bundle_comparisons.csv',index=False)
    rows=[]
    for label,g in subsets.items():
        for col in ['meet','distance_m']:
            for value,a in g.groupby(col):rows.append(dict(comparison_group=label,condition=col,value=str(value),n=len(a)))
        for col,mask in [('paired_under2',g.new_keep_fast_n.lt(2)),('paired_missing',g.new_keep_fast_g1.isna()),
                         ('recent_worse',g.delta_moist_last3_record_index_mean.lt(0)),
                         ('trend_missing',g.new_profile_trend.isna()),('distance_changed',g.new_distance_change.ne(0)&g.new_distance_change.notna())]:
            rows.append(dict(comparison_group=label,condition=col,value='true',n=int(mask.sum())))
    pd.DataFrame(rows).to_csv(OUT/'condition_counts.csv',index=False)
    d.to_parquet(OUT/'cases.parquet',index=False);d.to_csv(OUT/'all44_cases.csv',index=False)
    d[d.group.eq('blocked_gain')].to_csv(OUT/'missed11.csv',index=False)
    d[d.kept_hit].to_csv(OUT/'kept_hit14.csv',index=False)
    prior=allpairs[allpairs.switched&allpairs.grade.eq(6)]
    prior.groupby(['year','switch_outcome']).size().unstack(fill_value=0).to_csv(OUT/'grade6_prior_outcomes.csv')
    save(OUT/'decomposition_contract.json',dict(class_order=[-1,0,1],decision='log(Pgain/Ploss)>=0 chooses new',
        reference='Encoded feature mean of 1355 prior switch cases, 2020-2025',training_rows=len(train),
        encoded_features=len(names),reference_log_odds=baseline,centred_contributions=True,
        contribution_unit='log odds, not probability percentage points',causal=False,new_models=0,
        extras_not_used_by_selector=EXTRA+['distance_change','horse_name']))
    print(d.groupby('group').size().to_string(),flush=True)
    print('Reference log odds',baseline,flush=True)


def main():freeze();prepare();check()


if __name__=='__main__':main()
