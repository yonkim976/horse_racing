"""Independently check case membership, native probabilities and attribution sums."""
import ast
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    d=pd.read_parquet(e.OUT/'cases.parquet');source=pd.read_parquet(e.P/'selector_diagnostics.parquet')
    a=source[source.variant.eq('joint_logit')&source.year.eq(2026)&source.grade.eq(6)&source.switched].set_index('race_key').sort_index()
    b=d.set_index('race_key').sort_index();assert len(a)==len(b)==44
    for c in ['old_outcome','new_outcome','choose_new','p_loss','p_gain','expected_switch_gain']:
        np.testing.assert_array_equal(a[c],b[c])
    missed=(~d.choose_new)&(~d.old_outcome.between(1,3))&d.new_outcome.between(1,3)
    kept_gain=d.choose_new&(~d.old_outcome.between(1,3))&d.new_outcome.between(1,3)
    kept_hit=d.choose_new&d.new_outcome.between(1,3)
    assert missed.sum()==11 and kept_gain.sum()==10 and kept_hit.sum()==14
    np.testing.assert_array_equal(missed,d.group.eq('blocked_gain'))
    np.testing.assert_array_equal(kept_gain,d.group.eq('kept_gain'))
    assert d.group.eq('rescued_loss').sum()==1 and d.group.eq('kept_loss').sum()==4
    assert d.old_horse_name.notna().all()and d.new_horse_name.notna().all()
    assert d.old_program_no.ne(d.new_program_no).all()
    final_hit=d.new_outcome.between(1,3).where(d.choose_new,d.old_outcome.between(1,3))
    net=int((final_hit.astype(int)-d.new_outcome.between(1,3).astype(int)).sum());assert net==-10
    assert len(pd.read_csv(e.OUT/'missed11.csv'))==11 and len(pd.read_csv(e.OUT/'kept_hit14.csv'))==14
    pre=json.loads((e.MODEL/'preprocess.json').read_text());w=json.loads((e.MODEL/'model.json').read_text())
    x,names=e.E.transform(d,pre);native=LogisticRegression(C=.1)
    native.classes_=np.array(w['classes']);native.coef_=np.array(w['coef']);native.intercept_=np.array(w['intercept']);native.n_features_in_=x.shape[1]
    prob=native.predict_proba(x)
    np.testing.assert_allclose(prob,d[['p_loss','p_neutral','p_gain']],atol=1e-12,rtol=0)
    np.testing.assert_array_equal(prob[:,2]>=prob[:,0],d.choose_new)
    changed=d.copy();changed['old_outcome']=99;changed['new_outcome']=1;changed['switch_outcome']=-99
    x2,names2=e.E.transform(changed,pre);np.testing.assert_array_equal(x,x2)
    c=pd.read_csv(e.OUT/'feature_contributions.csv');bundle=pd.read_csv(e.OUT/'bundle_contributions.csv')
    assert len(c)==44*119 and c.feature.nunique()==119
    assert not c.feature.str.contains('outcome').any()
    np.testing.assert_allclose(c.contribution,c.coefficient*(c.encoded_value-c.training_reference),atol=1e-12,rtol=0)
    sums=c.groupby('race_key').contribution.sum().reindex(d.race_key).to_numpy()
    np.testing.assert_allclose(sums+d.reference_log_odds,np.log(prob[:,2]/prob[:,0]),atol=1e-12,rtol=0)
    sums2=bundle.groupby('race_key').contribution.sum().reindex(d.race_key).to_numpy()
    np.testing.assert_allclose(sums,sums2,atol=1e-12,rtol=0)
    grouped=c.groupby(['race_key','bundle']).contribution.sum().sort_index()
    np.testing.assert_allclose(grouped,bundle.set_index(['race_key','bundle']).contribution.sort_index(),atol=1e-12,rtol=0)
    pairs=pd.read_parquet(e.P/'pair_frame.parquet');train=pairs[pairs.switched&pairs.year.between(2020,2025)]
    assert len(train)==1355 and train.year.max()==2025
    tx,_=e.E.transform(train,pre);beta=np.array(w['coef'])[2]-np.array(w['coef'])[0]
    reference=float(w['intercept'][2]-w['intercept'][0]+tx.mean(axis=0)@beta)
    np.testing.assert_allclose(d.reference_log_odds,reference,atol=1e-12,rtol=0)
    expected={g:int(d.group.eq(g).sum())for g in e.GROUPS}
    e.save(e.OUT/'verification.json',dict(status='verified',cases=44,groups=expected,missed=11,kept_new_hits=14,
        strict_kept_gain_comparator=10,model_replay_max_error=float(np.abs(prob-d[['p_loss','p_neutral','p_gain']].to_numpy()).max()),
        encoded_feature_contributions=44*119,feature_sum_verified=True,bundle_sum_verified=True,
        outcome_mutation_invariant=True,prior_reference_rows=1355,net_vs122=-10,
        source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),new_models=0,
        production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':main()
