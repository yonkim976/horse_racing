"""Separate feature calculations, boundary cases and saved-model replay."""
import argparse
import json
import math
from datetime import date, timedelta
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
import run as experiment

HERE=experiment.HERE
OUT=experiment.OUT


def close(a,b):
    if pd.isna(a) or pd.isna(b):return bool(pd.isna(a) and pd.isna(b))
    if isinstance(a,(str,bool)) or isinstance(b,(str,bool)):return a==b
    return bool(np.isclose(float(a),float(b),atol=1e-10,rtol=0))


def independent_card(row,history):
    cutoff=(date.fromisoformat(row.race_date)-timedelta(days=2)).isoformat()
    past=history[(history.race_date<=cutoff)&(history.finish_position.between(1,89)|history.finish_position.isin([91,92]))]
    same=past[past.race_distance_m.eq(row.distance_m)]
    # Read actual source outcome directly, rather than trusting saved validity flags.
    def usable(q):return q.finish_position.between(1,89)&q.finish_time_seconds.gt(0)
    window=same.tail(6)
    values=[float(q.finish_time_seconds) if 1<=q.finish_position<=89 and q.finish_time_seconds>0 else None for q in window.itertuples()]
    finite=lambda xs:[x for x in xs if x is not None]
    avg=lambda xs:sum(xs)/len(xs) if xs else np.nan
    five=finite(values[-5:]);three=finite(values[-3:]);prior=finite(values[:-3])
    last=past.iloc[-1] if len(past) else None
    age=pd.to_numeric(last.age_at_race_raw,errors='coerce') if last is not None else np.nan
    if pd.isna(age) or age<=0:age=np.nan
    sex=last.sex_at_race_raw if last is not None else None
    if sex in ['', '-', '0']:sex=None
    gap=lambda q:(date.fromisoformat(row.race_date)-date.fromisoformat(q.race_date)).days if q is not None else np.nan
    f=dict(observed_starts=len(past),days_since_start=gap(last),previous_age=age,previous_sex=sex,
        same_starts=len(same),same_valid_times=int(usable(same).sum()),days_since_same=gap(same.iloc[-1] if len(same) else None),
        last_time_s=values[-1] if values and values[-1] is not None else np.nan,
        mean5_s=avg(five),valid_n5=len(five),mean3_s=avg(three),valid_n3=len(three),best5_s=min(five) if five else np.nan,
        fast2mean5_s=avg(sorted(five)[:2]) if len(five)>=2 else np.nan,
        std5_s=math.sqrt(sum((x-avg(five))**2 for x in five)/(len(five)-1)) if len(five)>=3 else np.nan,
        previous3_mean_s=avg(prior),previous3_valid_n=len(prior),trend_s=avg(three)-avg(prior) if min(len(three),len(prior))>=2 else np.nan)
    return f,window.api_record_id.astype(int).tolist(),past


def synthetic():
    def row(i,dt,pos,time,horse='A'):
        return dict(api_record_id=i,race_date=dt,race_number=1,horse_number=1,race_id=dt+'_2_1',horse_id=horse,
            horse_name=horse,year=2026,race_distance_m=1000,rank_class_raw='제5등급',finish_position=pos,
            finish_time_seconds=time,age_at_race_raw=3,sex_at_race_raw='암',started=pos in [1,91,92],valid_time=pos==1 and time>0)
    target=row(100,'2026-01-10',1,83.)
    # T−2 must be retained, T−1 excluded, invalid last start must not be skipped.
    d=pd.DataFrame([row(1,'2026-01-05',1,81.),row(2,'2026-01-08',91,0.),row(3,'2026-01-09',1,70.),target])
    ledger=pd.DataFrame([dict(race_id=target['race_id'],included=True)])
    f=experiment.build_features(d,ledger).iloc[0]
    assert f.observed_starts==2 and f.same_starts==2 and f.last6_same_source_ids==[1,2]
    assert pd.isna(f.last_time_s) and f.mean5_s==81 and f.valid_n5==1 and pd.isna(f.std5_s)
    d.loc[d.api_record_id.eq(100),['finish_time_seconds','age_at_race_raw','sex_at_race_raw']]=[20.,88,'수']
    changed=experiment.build_features(d,ledger).iloc[0]
    for c in experiment.BASE+experiment.EXTRA:
        assert close(f[c],changed[c]),c
    d.loc[d.api_record_id.eq(100),'horse_id']='B'
    cold=experiment.build_features(d,ledger).iloc[0]
    assert cold.observed_starts==0 and cold.same_starts==0 and cold.valid_n5==0
    assert pd.isna(cold.mean5_s) and pd.isna(cold.last_time_s) and pd.isna(cold.previous_age)
    # Six actual slots with invalid positions retain a 3-versus-3 trend window.
    past=[row(i,'2026-01-01',1 if i not in [2,5] else 91,80.+i) for i in range(1,7)]
    card,_,_=experiment.card(target,past,past)
    assert card['valid_n3']==2 and card['previous3_valid_n']==2
    assert card['trend_s']==3. and card['valid_n5']==3
    return ['inclusive_T_minus_2','excluded_T_minus_1','invalid_start_keeps_slot','unknown_time_stays_NULL',
            'current_outcome_and_age_sex_not_in_card','cold_start_kept','trend_two_nonempty_windows']


def preflight():
    experiment.check_prepared()
    d=pd.read_parquet(OUT/'source_snapshot.parquet')
    f=pd.read_parquet(OUT/'features.parquet')
    by_h={h:g for h,g in d.groupby('horse_id',sort=False)}
    source=d.set_index('api_record_id')
    # Every lineage, not only the displayed examples, must obey both key and cutoff.
    for r in f.itertuples():
        ids=list(r.last6_same_source_ids)
        if ids:
            q=source.loc[ids]
            assert q.horse_id.eq(r.horse_id).all() and q.race_distance_m.eq(r.distance_m).all()
            assert q.race_date.le(r.history_cutoff).all() and q.started.all()
        assert list(r.last5_same_source_ids)==ids[-5:]
    # Stratified + seeded separate arithmetic: include all examples and invalid windows.
    candidates=set(f.sample(150,random_state=experiment.SEED).api_record_id)
    candidates.update(x['api_record_id'] for x in json.loads((OUT/'example_scorecards.json').read_text()))
    candidates.update(f[f.last_time_s.isna() & f.same_starts.gt(0)].head(30).api_record_id)
    candidates.update(f[f.observed_starts.eq(0)].head(15).api_record_id)
    checked=0
    for r in f[f.api_record_id.isin(candidates)].itertuples():
        calc,ids,past=independent_card(r,by_h[r.horse_id])
        for col,val in calc.items():assert close(val,getattr(r,col)),(r.api_record_id,col,val,getattr(r,col))
        assert ids==list(r.last6_same_source_ids)
        assert close(int(past.api_record_id.iloc[-1]) if len(past) else np.nan,r.previous_start_id)
        checked+=1
    checks=synthetic()
    ledger=pd.read_csv(OUT/'race_inclusion_ledger.csv')
    assert set(f.race_id)==set(ledger.loc[ledger.included,'race_id'])
    assert f.groupby('race_id').finish_position.apply(lambda s:sorted(s)==list(range(1,len(s)+1))).all()
    assert f.groupby('race_id').horse_id.nunique().eq(f.groupby('race_id').size()).all()
    assert f[f.observed_starts.eq(0)].mean5_s.isna().all()
    experiment.save(OUT/'preflight_verification.json',dict(passed=True,lineage_rows=len(f),independent_card_rows=checked,
        synthetic_checks=checks,verifier_sha256=experiment.sha(HERE/'verify.py'),label_population_matches_ledger=True))
    print('Preflight passed',len(f),'lineages and',checked,'separate cards',flush=True)


def final():
    lock=experiment.check_prepared();experiment.check_protected(lock['protected'])
    pre=json.loads((OUT/'preflight_verification.json').read_text())
    assert experiment.sha(HERE/'verify.py')==pre['verifier_sha256']
    f=pd.read_parquet(OUT/'features.parquet')
    predictions=pd.read_parquet(OUT/'runner_predictions.parquet')
    race=pd.read_csv(OUT/'race_metrics.csv');tickets=pd.read_csv(OUT/'six_combinations.csv')
    count=0
    for year in [2024,2025,2026]:
        mask=f.year.eq(year);one=f[mask].reset_index(drop=True)
        for v,cols in experiment.CONTRACTS.items():
            folder=OUT/f'{v}_{year}';meta=json.loads((folder/'model_meta.json').read_text())
            assert experiment.sha(folder/'top3.txt')==meta['model_sha256']
            assert meta['refit_max']<meta['calibration_min']<=meta['calibration_max']<meta['evaluation_min']
            model=lgb.Booster(model_file=str(folder/'top3.txt'));x=one[cols].copy()
            for c in experiment.CATS:x[c]=pd.Categorical(x[c],categories=meta['vocabulary'][c])
            z=model.predict(x,raw_score=True,num_threads=4)
            old=predictions[predictions.variant.eq(v)&predictions.year.eq(year)]
            assert np.array_equal(old.api_record_id.to_numpy(),one.api_record_id.to_numpy())
            assert np.allclose(z,old.score,rtol=0,atol=1e-12)
            cal=f[f.year.eq(year-1)].reset_index(drop=True);cx=cal[cols].copy()
            for c in experiment.CATS:cx[c]=pd.Categorical(cx[c],categories=meta['vocabulary'][c])
            saved=json.loads((folder/'calibration_scores.json').read_text())
            cz=model.predict(cx,raw_score=True,num_threads=4)
            assert np.allclose(cz,saved['score'],rtol=0,atol=1e-12)
            assert np.isclose(experiment.temperature(cal,cz),meta['tau'],atol=1e-10)
            count+=1
    # Separate enumeration and metric calculation using stored scalar scores.
    for (v,rid),g in predictions.groupby(['variant','race_id'],sort=False):
        n=len(g);trips=list(__import__('itertools').combinations(range(n),3))
        terms=[sorted(g.score.iloc[list(c)].tolist()) for c in trips]
        energies=np.array([(t[0]+t[1])+t[2] for t in terms])
        tau=1 if v=='uniform' else json.loads((OUT/f'{v}_{int(g.year.iloc[0])}'/'model_meta.json').read_text())['tau']
        logq=energies/tau-logsumexp(energies/tau);q=np.exp(logq)
        p=np.array([sum(q[j] for j,c in enumerate(trips) if i in c) for i in range(n)])
        assert np.allclose(p,g.p_top3,atol=1e-12,rtol=0) and abs(p.sum()-3)<1e-10
        y=g.y.to_numpy();cp=np.clip(p,1e-12,1-1e-12)
        ll=-y*np.log(cp)-(1-y)*np.log1p(-cp)
        assert np.allclose(ll,g.log_loss,atol=1e-12)
        rr=race[race.variant.eq(v)&race.race_id.eq(rid)].iloc[0]
        assert np.isclose(ll.mean(),rr.log_loss) and np.isclose(((p-y)**2).mean(),rr.brier)
        chosen=np.argsort(-energies,kind='stable')[:6];truth=tuple(np.flatnonzero(y))
        target=trips.index(truth);t=tickets[tickets.variant.eq(v)&tickets.race_id.eq(rid)]
        assert len(t)==6 and t.numbers.nunique()==6
        assert int(target in chosen)==int(rr.six_combo_hit)==int(t.hit.sum())
        assert np.allclose(q[chosen],t.probability,atol=1e-12)
        assert t.numbers.tolist()==[','.join(map(str,g.horse_number.iloc[list(trips[j])].astype(int))) for j in chosen]
        order=np.argsort(-g.score.to_numpy(),kind='stable')
        for k in [3,4,5,6]:
            assert np.isclose(len(set(order[:k])&set(truth))/3,rr[f'top{k}_capture'])
            assert int(set(truth)<=set(order[:k]))==rr[f'top{k}_all3']
    metrics=pd.read_csv(OUT/'metrics_by_group.csv')
    for row in metrics[metrics.group.eq('all')].itertuples():
        one=race[race.variant.eq(row.variant)]
        for col in experiment.METRICS:assert np.isclose(one[col].mean(),getattr(row,col))
    differences=pd.read_csv(OUT/'paired_differences.csv')
    for row in differences[differences.group.isin(['all','year'])].itertuples():
        one=race if row.group=='all' else race[race.year.eq(int(row.value))]
        va,vb=row.comparison.split('-');calc=experiment.bootstrap(one[one.variant.eq(va)],one[one.variant.eq(vb)],row.metric)
        for col in ['delta','lo','hi']:assert np.isclose(calc[col],getattr(row,col),rtol=0,atol=1e-12)
    experiment.save(OUT/'final_verification.json',dict(passed=True,reloaded_models=count,
        probability_metric_ticket_recalculated_races=len(race),runner_rows=len(predictions),
        chronological_splits_checked=True,bootstrap_main_and_year_recalculated=True,
        protected_hashes_unchanged=True,production_changed=False,
        verifier_v2_sha256=experiment.sha(HERE/'verify_v2.py'),
        energy_summation='sorted three terms with left-associated IEEE addition matching frozen model contract'))
    print('Final verification passed',count,'models',len(race),'variant-races',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['preflight','final']);args=p.parse_args()
    (preflight if args.phase=='preflight' else final)()
