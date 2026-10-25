"""Exploratory condition distributions, complete denominators and forecast residuals."""
from pathlib import Path
from itertools import product
import hashlib
import json
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=HERE.parent/'20261008_horse_profile_baseline_v1/outputs_v2'
REL=HERE.parent/'20261009_field_relative_ability_v1/outputs'
COMP=HERE.parent/'20261009_operating_model_comparison_v1/outputs'
OUT=HERE/'outputs'
MISSING='unknown'
SEED=20261009


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def bucket(x,bins,labels):
    return pd.cut(x,bins,labels=labels,right=False).astype('string').fillna(MISSING)


def derive(f,source):
    """Historical fields come only from the sealed previous / same-distance IDs."""
    f=f.copy()
    source=source.set_index('api_record_id',drop=False)
    current=source.loc[f.api_record_id].reset_index(drop=True)
    # Current burden is a retrospective declaration assumption, not availability proof.
    f['current_burden_kg']=current.carried_weight_kg.where(current.carried_weight_kg.gt(0)).to_numpy()
    previous=source.reindex(f.previous_start_id)
    f['previous_finish']=previous.finish_position.to_numpy()
    f['previous_burden_kg']=previous.carried_weight_kg.where(previous.carried_weight_kg.gt(0)).to_numpy()
    f['burden_delta_kg']=f.current_burden_kg-f.previous_burden_kg
    f['distance_delta_m']=f.distance_m-previous.race_distance_m.to_numpy()
    same_rate=[]
    for row in f.itertuples():
        ids=list(row.last5_same_source_ids)
        q=source.loc[ids] if ids else source.iloc[:0]
        assert q.horse_id.eq(row.horse_id).all()
        assert q.race_date.le(row.history_cutoff).all()
        assert q.race_distance_m.eq(row.distance_m).all()
        assert q.started.all()
        same_rate.append(float(q.finish_position.between(1,3).mean()) if len(q) else np.nan)
    f['same_recent5_top3_rate']=same_rate
    has=f.previous_start_id.notna().to_numpy()
    assert np.array_equal(previous.loc[has,'horse_id'].to_numpy(),f.loc[has,'horse_id'].to_numpy())
    assert (previous.loc[has,'race_date'].to_numpy()<=f.loc[has,'history_cutoff'].to_numpy()).all()
    assert f.horse_id.ne('3005648').all()
    for c in ['api_record_id','horse_id','horse_number','finish_position']:
        assert np.array_equal(current[c].to_numpy(),f[c].to_numpy()),c
    f['y']=f.finish_position.between(1,3).astype(int)
    f['uniform_p']=3/f.field_n
    f['period']=np.select([f.year.le(2023),f.year.le(2025)],['2017_2023','2024_2025'],default='2026')
    c={}
    c['career']=bucket(f.observed_starts,[-np.inf,1,5,20,np.inf],['0','1_4','5_19','20_plus'])
    c['same_valid_times']=bucket(f.same_valid_times,[-np.inf,1,3,5,np.inf],['0','1_2','3_4','5_plus'])
    c['gap_days']=bucket(f.days_since_start,[-np.inf,15,29,57,91,np.inf],['le14','15_28','29_56','57_90','91_plus'])
    c['previous_age']=bucket(f.previous_age,[-np.inf,3,4,5,7,np.inf],['le2','3','4','5_6','7_plus'])
    c['previous_sex']=f.previous_sex.astype('string').fillna(MISSING)
    x=f.previous_finish
    c['previous_finish']=pd.Series(np.select([x.between(1,3),x.between(4,6),x.between(7,89),x.ge(90)],['top3','4_6','7_plus','non_normal'],default=MISSING),index=f.index,dtype='string')
    x=f.same_recent5_top3_rate
    c['same_recent_top3']=pd.Series(np.select([x.eq(0),x.gt(0)&x.lt(.4),x.ge(.4)&x.lt(.8),x.ge(.8)],['zero','gt0_lt40','40_lt80','80_plus'],default=MISSING),index=f.index,dtype='string')
    c['relative_rank']=bucket(f.mean5_rank_fraction,[-np.inf,.25,.5,.75,np.inf],['best_quarter','second_quarter','third_quarter','last_quarter'])
    c['relative_seconds']=bucket(f.mean5_minus_opp_median_s,[-np.inf,-1,0,1,np.inf],['faster_gt1s','faster_le1s','slower_lt1s','slower_ge1s'])
    x=f.trend_s
    c['trend']=pd.Series(np.select([x.le(-.5),x.gt(-.5)&x.lt(.5),x.ge(.5)],['faster','stable','slower'],default=MISSING),index=f.index,dtype='string')
    x=f.std5_s
    c['variability']=pd.Series(np.select([x.le(1),x.gt(1)&x.le(2),x.gt(2)],['le1s','gt1_le2s','gt2s'],default=MISSING),index=f.index,dtype='string')
    x=f.current_burden_kg
    c['burden']=pd.Series(np.select([x.le(54),x.gt(54)&x.le(57),x.gt(57)&x.le(60),x.gt(60)],['le54','gt54_le57','gt57_le60','gt60'],default=MISSING),index=f.index,dtype='string')
    x=f.burden_delta_kg
    c['burden_change']=pd.Series(np.select([x.le(-2),x.gt(-2)&x.lt(0),x.eq(0),x.gt(0)&x.lt(3),x.ge(3)],['down_ge2','down_lt2','same','up_lt3','up_ge3'],default=MISSING),index=f.index,dtype='string')
    x=f.distance_delta_m
    c['distance_change']=pd.Series(np.select([x.lt(0),x.eq(0),x.gt(0)],['shorter','same','longer'],default=MISSING),index=f.index,dtype='string')
    c['distance']=f.distance_m.astype(int).astype('string')
    c['grade_raw']=f.grade_raw.astype('string').fillna(MISSING)
    eligible=f.groupby('race_id').horse_number.transform(lambda x:len(x)==10 and set(x)==set(range(1,11))).astype(bool)
    gate=pd.Series(np.select([f.horse_number.le(3),f.horse_number.between(4,7),f.horse_number.between(8,10)],['inner1_3','middle4_7','outer8_10'],default=MISSING),index=f.index,dtype='string')
    c['distance_gate_10']=f.distance_m.astype(int).astype('string')+'|'+gate
    c['distance_gate_10']=c['distance_gate_10'].where(eligible,pd.NA)
    for k in ['previous_finish','burden_change','trend','same_valid_times']:
        c['relative_rank_x_'+k]=c['relative_rank']+'|'+c[k]
    for k,v in c.items():f['C_'+k]=v
    return f,list(c)


def summary(g,family,condition,period,base,ci=True):
    y=g.y.to_numpy(float);u=g.uniform_p.to_numpy(float)
    n=len(g);winners=int(y.sum())
    mixed=g.groupby('race_id').agg(n=('y','size'),hit=('y','sum'),field_n=('field_n','first'))
    mixed=mixed[mixed.n.lt(mixed.field_n)]
    contrast=(mixed.hit/mixed.n-(3-mixed.hit)/(mixed.field_n-mixed.n)).mean() if len(mixed) else np.nan
    r=dict(family=family,condition=condition,period=period,rows=n,top3=winners,non_top3=n-winners,
        horses=g.horse_id.nunique(),races=g.race_id.nunique(),days=g.race_date.nunique(),
        first_date=g.race_date.min(),last_date=g.race_date.max(),condition_share=n/len(base),
        share_among_top3=winners/int(base.y.sum()),top3_rate=float(y.mean()),uniform_p=float(u.mean()),
        excess_uniform=float((y-u).mean()),within_race_risk_difference=float(contrast),
        within_race_comparable_races=len(mixed),low_support=n<100 or g.race_id.nunique()<50)
    for name,col in [('R1','p_R1'),('HY','p_HY')]:
        known=g[col].notna();q=g[known]
        r[name+'_rows']=len(q)
        r[name+'_predicted']=float(q[col].mean()) if len(q) else np.nan
        r[name+'_actual']=float(q.y.mean()) if len(q) else np.nan
        r[name+'_residual']=float((q.y-q[col]).mean()) if len(q) else np.nan
    if ci:
        for name,col in [('uniform','uniform_p'),('R1','p_R1')]:
            q=g[g[col].notna()].copy()
            if q.empty:continue
            q['delta']=q.y-q[col]
            d=q.groupby('race_date').delta.agg(['sum','size'])
            rng=np.random.default_rng(SEED)
            ix=rng.integers(0,len(d),size=(2000,len(d)))
            boot=d['sum'].to_numpy()[ix].sum(axis=1)/d['size'].to_numpy()[ix].sum(axis=1)
            r[name+'_lo'],r[name+'_hi']=map(float,np.quantile(boot,[.025,.975]))
    return r


def main():
    OUT.mkdir(exist_ok=False)
    sources=[REL/'features.parquet',REL/'runner_predictions.parquet',COMP/'runner_predictions.parquet',
        OLD/'source_snapshot.parquet',HERE/'CONTRACT.md',HERE/'analyze.py',ROOT/'jeju/AGENTS.md']
    protected=[ROOT/'jeju/data/jeju_native_core.sqlite3',ROOT/'jeju/models/current/HY_R_FORM.pkl',ROOT/'config/prediction_model_registry.json']
    lock={str(p.relative_to(ROOT)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in sources+protected}
    save(OUT/'source_lock.json',lock)
    original=pd.read_parquet(REL/'features.parquet')
    source=pd.read_parquet(OLD/'source_snapshot.parquet')
    f,families=derive(original,source)
    assert len(f)==52155 and f.race_id.nunique()==5206
    assert f.groupby('race_id').y.sum().eq(3).all()
    assert not f.duplicated(['race_id','horse_id']).any()
    r1=pd.read_parquet(REL/'runner_predictions.parquet');r1=r1[r1.variant.eq('R1')]
    f=f.merge(r1[['api_record_id','p_top3']].rename(columns={'p_top3':'p_R1'}),on='api_record_id',how='left',validate='one_to_one')
    hy=pd.read_parquet(COMP/'runner_predictions.parquet');hy=hy[hy.variant.eq('HY_R_FORM')]
    f=f.merge(hy[['race_id','horse_id','p_top3']].rename(columns={'p_top3':'p_HY'}),on=['race_id','horse_id'],how='left',validate='one_to_one')
    assert f.p_R1.notna().sum()==17412 and f.p_HY.notna().sum()==4475
    f.to_parquet(OUT/'condition_features.parquet',index=False)
    totals=f.groupby('period').agg(rows=('y','size'),top3=('y','sum'),races=('race_id','nunique'),horses=('horse_id','nunique'),days=('race_date','nunique'))
    totals.to_csv(OUT/'period_totals.csv')
    tables=[]
    for period,base in [('all',f)]+list(f.groupby('period')):
        for family in families:
            population=base[base['C_'+family].notna()]
            for condition,g in population.groupby('C_'+family,sort=True):
                tables.append(summary(g,family,str(condition),period,population,ci=period in ['2024_2025','2026']))
            assert sum(len(g) for _,g in population.groupby('C_'+family))==len(population)
        print('computed',period,flush=True)
    table=pd.DataFrame(tables);table.to_csv(OUT/'condition_statistics.csv',index=False)
    # Keep R1 and production residuals on exactly the same common 2026 subset.
    common=f[f.p_HY.notna()]
    compare=[]
    for family in families:
        population=common[common['C_'+family].notna()]
        for condition,g in population.groupby('C_'+family):
            row=summary(g,family,str(condition),'2026_operating_common467',population,ci=False)
            assert row['R1_rows']==row['HY_rows']
            compare.append(row)
    pd.DataFrame(compare).to_csv(OUT/'common_model_residuals.csv',index=False)
    # Distance-stratified primary conditions, preserving full raw counts; no ranking/selection.
    dist=[]
    for (period,distance),base in f.groupby(['period','distance_m']):
        for family in families:
            if '_x_' in family or family in ['distance','distance_gate_10']:continue
            for condition,g in base.groupby('C_'+family):
                row=summary(g,family,str(condition),period,base,ci=False)
                row['distance_m']=int(distance);dist.append(row)
    pd.DataFrame(dist).to_csv(OUT/'distance_condition_statistics.csv',index=False)
    # Point-estimate repeat candidates are exploratory, never a promotion criterion.
    recent=table[table.period.eq('2026')]
    prior=table[table.period.eq('2024_2025')]
    repeat=prior.merge(recent,on=['family','condition'],suffixes=('_2024_2025','_2026'),validate='one_to_one')
    repeat['adequate_both']=~repeat.low_support_2024_2025&~repeat.low_support_2026
    repeat['positive_uniform_both']=repeat.excess_uniform_2024_2025.gt(0)&repeat.excess_uniform_2026.gt(0)
    repeat['positive_R1_residual_both']=repeat.R1_residual_2024_2025.gt(0)&repeat.R1_residual_2026.gt(0)
    repeat.to_csv(OUT/'period_repetition.csv',index=False)
    for path,info in lock.items():assert sha(ROOT/path)==info['sha256'],path
    save(OUT/'analysis_verification.json',dict(passed=True,rows=len(f),races=f.race_id.nunique(),
        top3=int(f.y.sum()),non_top3=int((1-f.y).sum()),families=len(families),
        condition_period_rows=len(table),R1_prediction_rows=int(f.p_R1.notna().sum()),
        operating_common_rows=len(common),operating_common_races=common.race_id.nunique(),
        source_ids_and_history_T_minus_2_verified=True,all_condition_denominators_reconciled=True,
        protected_unchanged=True,fits=0,independent_validation=False))
    print(totals.to_string())
    cols=['family','condition','rows','top3_rate','R1_predicted','R1_residual','R1_lo','R1_hi']
    print(table[table.period.eq('2026')&table.family.isin(['relative_rank','previous_finish','same_recent_top3','burden_change','trend','gap_days'])][cols].to_string(index=False))


if __name__=='__main__':main()
