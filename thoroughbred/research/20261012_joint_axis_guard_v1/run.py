"""Frozen, outcome-blind joint-evidence confirmation of 103->122 axis changes."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
P=R/'20261012_full103_retention_v1/outputs'
B=R/'20261009_gate_front_late_v1/outputs'
KEY=['race_key','program_no','horse_id']
METRICS=['axis_top3','axis_top2','axis_win','quinella_one','axis_next3']
VARIANTS=['frozen103','frozen122','joint_only','joint_supported','joint_recent','recent_only']
INPUTS=['keep_fast_g3','keep_fast_g1','keep_fast_n','profile_count3','moist_last3_record_index_mean']


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p,value):
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'run.py',HERE/'PLAN.md',P/'features.parquet',P/'runner_predictions.parquet',
           P/'race_diagnostics.csv',P/'verification.json',P/'feature_contract.json',
           R/'20261012_full103_gain_loss_v1/outputs/summary.csv',
           ROOT/'config/prediction_model_registry.json',
           R/'20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
           R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    for parent,stem in [(P,'combined122'),(B,'full103')]:
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                paths += [parent/'models'/f'{stem}_{meet}_{year}'/name for name in ['metadata.json','model.txt']]
    manifest={str(p.relative_to(ROOT)):sha(p)for p in paths}
    target=OUT/'input_manifest.json'
    if target.exists(): assert json.loads(target.read_text())==manifest
    else: save(target,manifest)
    before=OUT/'publication_before.json'
    if not before.exists():
        files=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p))for p in files})
        snap=OUT/'publication_before';snap.mkdir()
        for p in files:(snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())
    save(OUT/'policy_contract.json',dict(primary='joint_recent',reference='frozen122',fallback='frozen103_anchor',
        features=INPUTS,joint_min=0,support_min=2,recent_count_min=2,recent_new_minus_old_min=0,
        comparison_scope='Only when frozen103 and frozen122 anchors differ',
        remaining_order='Preserve frozen122 order after moving selected anchor to first',
        probability_changed=False,model_training=False,threshold_fit=False,
        retrospective=True,zero_support_not_imputed=True,variants=VARIANTS))


def check():
    for path,digest in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/path)==digest,path


def load():
    f=pd.read_parquet(P/'features.parquet',columns=KEY+['race_date','year','meet','distance_m','grade','field_size']+INPUTS)
    p=pd.read_parquet(P/'runner_predictions.parquet')
    p=p[p.target.eq(3)&p.variant.isin(['baseline103','combined122'])].copy()
    p['race_date']=pd.to_datetime(p.race_date)
    p=p.sort_values(['variant','race_key','raw_score','program_no'],ascending=[True,True,False,True])
    p['model_rank']=p.groupby(['variant','race_key']).cumcount()+1
    assert not p.duplicated(['variant']+KEY).any()
    assert len(p)==101508
    return f,p


def decide(f,p):
    """Accept identifiers, frozen scores/ranks and PIT history only; no labels."""
    forbidden={'outcome','actual_early','actual_last600','actual_late'}
    assert not forbidden.intersection(f.columns) and not forbidden.intersection(p.columns)
    assert not any(c.startswith('actual_')for c in f.columns)
    anchors=[]
    for variant,side in [('baseline103','old'),('combined122','new')]:
        a=p[p.variant.eq(variant)&p.model_rank.eq(1)][KEY+['target_probability']]
        a=a.merge(f,on=KEY,validate='one_to_one').set_index('race_key').add_prefix(side+'_')
        anchors.append(a)
    d=anchors[0].join(anchors[1],validate='one_to_one').reset_index()
    for col in ['race_date','year','meet','distance_m','grade','field_size']:
        assert d['old_'+col].equals(d['new_'+col]);d[col]=d['old_'+col]
    d['proposed_switch']=d.old_horse_id.ne(d.new_horse_id)
    d['joint_pass']=d.new_keep_fast_g3.ge(0)&d.new_keep_fast_g1.ge(0)
    d['support_pass']=d.new_keep_fast_n.ge(2)
    d['recent_count_pass']=d.old_profile_count3.ge(2)&d.new_profile_count3.ge(2)
    d['recent_record_pass']=d.new_moist_last3_record_index_mean.ge(d.old_moist_last3_record_index_mean)
    d['recent_pass']=d.recent_count_pass&d.recent_record_pass
    d['joint_only_accept']=d.joint_pass
    d['joint_supported_accept']=d.joint_pass&d.support_pass
    d['joint_recent_accept']=d.joint_pass&d.support_pass&d.recent_pass
    d['recent_only_accept']=d.recent_pass
    for v in VARIANTS[2:]:
        accept=~d.proposed_switch|d[v+'_accept']
        d[v+'_axis_program_no']=np.where(accept,d.new_program_no,d.old_program_no)
        d[v+'_axis_horse_id']=np.where(accept,d.new_horse_id,d.old_horse_id)
        d[v+'_blocked']=d.proposed_switch&~d[v+'_accept']
    return d


def evaluate(d,p):
    races=[];rankings=[]
    piv=d.set_index('race_key')
    for variant in VARIANTS:
        source='baseline103'if variant=='frozen103'else'combined122'
        for rid,g in p[p.variant.eq(source)].groupby('race_key',sort=False):
            g=g.sort_values('model_rank');row=piv.loc[rid]
            if variant.startswith('frozen'):
                axis=int(g.program_no.iloc[0])
            else:
                axis=int(row[variant+'_axis_program_no'])
                g=pd.concat([g[g.program_no.eq(axis)],g[g.program_no.ne(axis)]])
            assert len(g)==row.field_size and g.program_no.iloc[0]==axis
            outcomes=g.outcome.to_numpy()
            winners=set(g.loc[g.outcome.between(1,2),'program_no'])
            assert len(winners)==2 and g.outcome.between(1,3).sum()==3
            race=dict(race_key=rid,race_date=row.race_date,year=int(row.year),meet=int(row.meet),
                distance_m=float(row.distance_m),grade=row.grade,field_size=int(row.field_size),
                variant=variant,axis_program_no=axis,axis_horse_id=g.horse_id.iloc[0],
                axis_outcome=int(outcomes[0]),proposed_switch=bool(row.proposed_switch),
                blocked=False if variant.startswith('frozen')else bool(row[variant+'_blocked']),
                axis_top3=int(1<=outcomes[0]<=3),axis_top2=int(1<=outcomes[0]<=2),axis_win=int(outcomes[0]==1),
                quinella_one=int(winners==set(g.program_no.iloc[:2])),
                axis_next3=int(axis in winners and winners<=set(g.program_no.iloc[:4])))
            races.append(race)
            for rank,r in enumerate(g.itertuples(),1):
                rankings.append(dict(variant=variant,race_key=rid,program_no=int(r.program_no),
                                     horse_id=r.horse_id,selection_rank=rank,frozen_model_rank=int(r.model_rank)))
    rr=pd.DataFrame(races);rk=pd.DataFrame(rankings)
    rr.to_parquet(OUT/'race_metrics.parquet',index=False)
    rk.to_parquet(OUT/'selection_rankings.parquet',index=False)
    return rr


def windows(z):
    yield 'all',z
    for year in [2024,2025,2026]:
        a=z[z.year.eq(year)];yield str(year),a
        yield f'{year}_to0920',a[a.race_date.dt.strftime('%m-%d').le('09-20')]


def analyse(rr,d):
    rows=[]
    for variant,z in rr.groupby('variant'):
        for period,g in windows(z):
            rows.append(dict(variant=variant,period=period,races=len(g),blocked=int(g.blocked.sum()),
                **{k:float(g[k].mean())for k in METRICS}))
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    rows=[]
    for variant in VARIANTS[2:]:
        for reference in ['frozen122','frozen103']:
            z=rr[rr.variant.eq(variant)].merge(rr[rr.variant.eq(reference)][['race_key','axis_program_no']+METRICS],
                on='race_key',validate='one_to_one',suffixes=('','_ref'))
            for period,g in windows(z):
                for metric in METRICS:
                    delta=g[metric]-g[metric+'_ref'];temp=g[['race_date']].copy();temp['delta']=delta
                    day=temp.groupby('race_date').delta.agg(['sum','size'])
                    rng=np.random.default_rng(20261012);idx=rng.integers(len(day),size=(2000,len(day)))
                    samples=day['sum'].to_numpy()[idx].sum(axis=1)/day['size'].to_numpy()[idx].sum(axis=1)
                    lo,hi=np.quantile(samples,[.025,.975])
                    rows.append(dict(variant=variant,reference=reference,period=period,metric=metric,n=len(g),
                        changed_axes=int(g.axis_program_no.ne(g.axis_program_no_ref).sum()),
                        gain=int(delta.eq(1).sum()),loss=int(delta.eq(-1).sum()),net=int(delta.sum()),
                        difference_pp=float(delta.mean()*100),lo_pp=float(lo*100),hi_pp=float(hi*100)))
    pd.DataFrame(rows).to_csv(OUT/'paired_differences.csv',index=False)
    truth=rr[rr.variant.eq('frozen122')][['race_key','axis_top3']].rename(columns={'axis_top3':'new_hit'})
    truth=truth.merge(rr[rr.variant.eq('frozen103')][['race_key','axis_top3']].rename(columns={'axis_top3':'old_hit'}),on='race_key',validate='one_to_one')
    dd=d.merge(truth,on='race_key',validate='one_to_one')
    dd['original_switch_net']=dd.new_hit-dd.old_hit
    dd['distance_band']=np.select([dd.distance_m.le(1300),dd.distance_m.le(1600)],['short','middle'],default='long')
    dd.to_parquet(OUT/'decisions.parquet',index=False)
    dd[dd.proposed_switch].to_csv(OUT/'proposed_switches.csv',index=False)
    rows=[]
    for period,z in windows(dd):
        for variant in VARIANTS[2:]:
            for blocked in [True,False]:
                g=z[z.proposed_switch&z[variant+'_blocked'].eq(blocked)]
                n=g.original_switch_net
                rows.append(dict(period=period,variant=variant,blocked=blocked,races=len(g),
                    original_new_gain=int(n.eq(1).sum()),original_new_loss=int(n.eq(-1).sum()),
                    original_both_hit=int((g.old_hit.eq(1)&g.new_hit.eq(1)).sum()),
                    original_both_miss=int((g.old_hit.eq(0)&g.new_hit.eq(0)).sum()),
                    net_original_gain=int(n.sum())))
    pd.DataFrame(rows).to_csv(OUT/'blocked_transitions.csv',index=False)
    rows=[];main=rr[rr.variant.eq('joint_recent')].merge(rr[rr.variant.eq('frozen122')][['race_key']+METRICS],on='race_key',suffixes=('','_ref'),validate='one_to_one')
    main['distance_band']=np.select([main.distance_m.le(1300),main.distance_m.le(1600)],['short','middle'],default='long')
    for period,z in windows(main):
        for condition in ['meet','grade','distance_band']:
            for value,g in z.groupby(condition,dropna=False,observed=True):
                for metric in METRICS:
                    delta=g[metric]-g[metric+'_ref']
                    rows.append(dict(period=period,condition=condition,value=str(value),metric=metric,n=len(g),
                        blocked=int(g.blocked.sum()),gain=int(delta.eq(1).sum()),loss=int(delta.eq(-1).sum()),
                        net=int(delta.sum()),difference_pp=float(delta.mean()*100)))
    pd.DataFrame(rows).to_csv(OUT/'conditions.csv',index=False)


def main():
    freeze();f,p=load();d=decide(f,p.drop(columns='outcome'));rr=evaluate(d,p);analyse(rr,d);check()
    m=pd.read_csv(OUT/'metrics.csv');print(m[m.period.isin(['2024','2025','2026','all'])].to_string(index=False))


if __name__=='__main__':main()
