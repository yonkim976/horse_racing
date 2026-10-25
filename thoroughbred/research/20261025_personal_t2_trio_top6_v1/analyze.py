"""Frozen personal_t2, equal six-ticket policies, without training or odds selection."""
from pathlib import Path
from itertools import combinations
from functools import lru_cache
from decimal import Decimal
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=R.parents[1]
OUT=HERE/'outputs'
TRAIN=R/'20261024_training_state_v1/outputs'
PREVIOUS=R/'20261025_trio_joint_top6_v1/outputs'
PROMOTION=R/'20261025_operating_training_comparison_v1/outputs'
PAYOUT=R/'20261025_trio_six_ten_returns_v1/outputs'
FEATURES=R/'20261009_gate_front_late_v1/outputs/features.parquet'
PRODUCTION=ROOT/'production_models/thoroughbred_training_state_20261025_v1'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def save(name,value):
    p=OUT/name
    assert p.resolve().is_relative_to(OUT)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def freeze():
    paths=[HERE/'PLAN.md',FEATURES,TRAIN/'runner_probabilities.parquet',TRAIN/'race_metrics.parquet',
        PREVIOUS/'race_results.parquet',PROMOTION/'cohort.parquet',PROMOTION/'race_metrics.parquet',
        PAYOUT/'winning_dividends.parquet',PAYOUT/'verification.json',ROOT/'config/prediction_model_registry.json']
    resolved=json.loads(Path('/private/tmp/personal_t2_policy_resolved_20261025.json').read_text())
    assert resolved['ok'] and resolved['active_profile']=='thoroughbred-training-state-20261025-v1'
    assert sha(ROOT/'config/prediction_model_registry.json')==resolved['registry_sha256']
    save('model_resolution.json',resolved)
    for item in resolved['verified_artifacts']:
        path=ROOT/item['path'];assert sha(path)==item['sha256'];paths.append(path)
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=TRAIN/'models'/f'personal_t2_{meet}_{year}'
            paths.extend([folder/'model.txt',folder/'metadata.json',folder/'scores.parquet'])
    manifest={str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in dict.fromkeys(paths)}
    path=OUT/'input_manifest.json'
    if path.exists():assert manifest==json.loads(path.read_text())
    else:save('input_manifest.json',manifest)


def frame():
    cols=['race_key','program_no','horse_id','meet','race_date','year','outcome','field_size',
          'distance_m','grade_raw','cutoff_date','history_source_date','profile_source_date']
    f=pd.read_parquet(FEATURES,columns=cols).sort_values(['meet','race_date','race_key','program_no']).reset_index(drop=True)
    f['row_number']=np.arange(len(f))
    for col in ['history_source_date','profile_source_date']:
        assert (f[col].isna()|f[col].le(f.cutoff_date)).all()
    f=f[f.year.ge(2024)].copy()
    assert len(f)==50754 and f.race_key.nunique()==4799
    probabilities=pd.read_parquet(TRAIN/'runner_probabilities.parquet').query("variant=='personal_t2'")
    f=f.merge(probabilities[['race_key','program_no','horse_id','outcome','top3']],
        on=['race_key','program_no','horse_id','outcome'],validate='one_to_one')
    assert len(f)==50754
    scores=[];models=[]
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=TRAIN/'models'/f'personal_t2_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            assert meta['train_end_year']==year-2 and meta['calibration_year']==year-1
            assert len(meta['features'])==136 and meta['variant']=='personal_t2'
            assert sha(folder/'model.txt')==meta['model_sha256']
            if year==2026:
                assert sha(PRODUCTION/f'meet_{meet}_model.txt')==meta['model_sha256']
                pmeta=json.loads((PRODUCTION/f'meet_{meet}_metadata.json').read_text())
                assert meta['temperature']==pmeta['temperature']
            s=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").copy()
            s['temperature']=meta['temperature'];scores.append(s)
            models.append(dict(meet=meet,year=year,train_end_year=meta['train_end_year'],
                calibration_year=meta['calibration_year'],temperature=meta['temperature'],
                model_sha256=meta['model_sha256'],current_production_weights=year==2026))
    f=f.merge(pd.concat(scores)[['row_number','score','temperature']],on='row_number',validate='one_to_one')
    assert len(f)==50754 and f.score.notna().all()
    save('year_models.json',models)
    return f


@lru_cache(maxsize=32)
def support(n):return np.asarray(list(combinations(range(n),3)),int)


def evaluate(f):
    previous=set(pd.read_parquet(PREVIOUS/'race_results.parquet',columns=['race_key']).race_key)
    promoted=set(pd.read_parquet(PROMOTION/'cohort.parquet').race_key)
    dividends=pd.read_parquet(PAYOUT/'winning_dividends.parquet').set_index('race_key')
    existing=pd.read_parquet(TRAIN/'race_metrics.parquet').query("variant=='personal_t2'").set_index('race_key')
    records=[];tickets=[];worst=0.
    for key,g in f.groupby('race_key',sort=True):
        g=g.sort_values('program_no');numbers=g.program_no.to_numpy(int);score=g.score.to_numpy(float)
        assert len(g)==g.field_size.iloc[0] and len(set(numbers))==len(g) and len(g)>=6
        ts=support(len(g));energy=score[ts].sum(axis=1)/float(g.temperature.iloc[0]);q=np.exp(energy-logsumexp(energy))
        marginal=np.bincount(ts.ravel(),weights=np.repeat(q,3),minlength=len(g))
        error=float(np.max(np.abs(marginal-g.top3.to_numpy(float))));assert error<2e-10
        worst=max(worst,error)
        order=np.argsort(-np.round(marginal,12),kind='stable')
        axis=int(numbers[order[0]]);others=numbers[order[1:5]]
        fixed={tuple(sorted((axis,int(x),int(y)))) for x,y in combinations(others,2)}
        keys=[tuple(t) for t in numbers[ts]];lookup={t:i for i,t in enumerate(keys)}
        ixold=[lookup[t] for t in sorted(fixed)]
        ixnew=np.argsort(-np.round(q,12),kind='stable')[:6]
        newset={keys[i] for i in ixnew}
        truth=tuple(sorted(g.loc[g.outcome.between(1,3),'program_no'].astype(int)))
        assert len(truth)==3 and truth==tuple(map(int,dividends.loc[key,'actual'].split(',')))
        assert axis==existing.loc[key,'axis_program_no']
        assert (axis in truth)==bool(existing.loc[key,'axis_top3'])
        assert q[ixnew].sum()>=q[ixold].sum()-1e-10
        oldhit=truth in fixed;newhit=truth in newset
        for policy,idx in [('axis_six',ixold),('joint_top6',ixnew)]:
            for rank,ix in enumerate(idx,1):
                t=keys[ix]
                tickets.append(dict(race_key=key,policy=policy,rank=rank,a=t[0],b=t[1],c=t[2],
                                    probability=float(q[ix]),hit=t==truth))
        dividend=float(dividends.loc[key,'dividend'])
        assert dividends.loc[key,'status']=='valid'
        pay=int(Decimal(str(dividend))*1000)
        records.append(dict(race_key=key,race_date=str(pd.Timestamp(g.race_date.iloc[0]).date()),
            year=int(g.year.iloc[0]),meet=int(g.meet.iloc[0]),field_size=len(g),distance=int(g.distance_m.iloc[0]),
            grade_raw=g.grade_raw.iloc[0],axis=axis,companions=','.join(map(str,others)),actual=','.join(map(str,truth)),
            axis_hit=axis in truth,axis_six_hit=oldhit,joint_top6_hit=newhit,
            axis_six_probability=float(q[ixold].sum()),joint_top6_probability=float(q[ixnew].sum()),
            changed_tickets=6-len(fixed&newset),joint_horses=len({n for t in newset for n in t}),
            joint_without_axis=sum(axis not in t for t in newset),dividend=dividend,payout=pay,
            axis_six_return=pay*oldhit,joint_top6_return=pay*newhit,
            transition='gained' if newhit and not oldhit else 'lost' if oldhit and not newhit else 'both' if oldhit else 'neither',
            previous_4133=key in previous,promoted_1258=key in promoted))
    r=pd.DataFrame(records);t=pd.DataFrame(tickets)
    assert r.previous_4133.sum()==4133 and r.promoted_1258.sum()==1258
    r.to_parquet(OUT/'race_results.parquet',index=False,compression='zstd')
    t.to_parquet(OUT/'selected_tickets.parquet',index=False,compression='zstd')
    r[r.transition.isin(['gained','lost'])].to_csv(OUT/'gain_loss_races.csv',index=False,encoding='utf-8-sig')
    save('reconstruction.json',dict(races=len(r),runner_rows=len(f),marginal_max_error=worst,
         current2026_weights_match=True,probability_order_target='top3_marginal',selection_uses_odds=False,new_fits=0))
    return r


def cohorts(r):
    return [('previous_4133',r[r.previous_4133]),('all_4799',r),('promoted_1258',r[r.promoted_1258])]


def aggregate(r):
    rows=[];contrasts=[];transitions=[]
    for scope,frame in cohorts(r):
        for subgroup,g in [('all',frame),*[(str(y),q) for y,q in frame.groupby('year')],
                           *[('seoul' if m==1 else 'busan',q) for m,q in frame.groupby('meet')]]:
            stake=len(g)*6000
            for policy in ['axis_six','joint_top6']:
                ret=int(g[policy+'_return'].sum());best=int(g[policy+'_return'].max())
                rows.append(dict(scope=scope,subgroup=subgroup,policy=policy,races=len(g),
                    hits=int(g[policy+'_hit'].sum()),hit_rate=float(g[policy+'_hit'].mean()),
                    stake_krw=stake,return_krw=ret,net_krw=ret-stake,roi=ret/stake-1,
                    mean_prediction=float(g[policy+'_probability'].mean()),
                    roi_without_best_race=(ret-best)/((len(g)-1)*6000)-1,best_payout_share=best/ret))
            gain=g[g.transition.eq('gained')];loss=g[g.transition.eq('lost')]
            transitions.append(dict(scope=scope,subgroup=subgroup,races=len(g),gained=len(gain),lost=len(loss),
                gained_mean=gain.dividend.mean(),lost_mean=loss.dividend.mean(),
                gained_return=int(gain.payout.sum()),lost_return=int(loss.payout.sum()),
                delta_return=int(gain.payout.sum()-loss.payout.sum()),
                changed_races=int(g.changed_tickets.gt(0).sum()),mean_changed_tickets=float(g.changed_tickets.mean()),
                mean_joint_horses=float(g.joint_horses.mean()),mean_joint_without_axis=float(g.joint_without_axis.mean())))
            if subgroup in ['all','2024','2025','2026']:
                daily=g.assign(hit_delta=g.joint_top6_hit.astype(int)-g.axis_six_hit.astype(int),
                    roi_delta=(g.joint_top6_return-g.axis_six_return)/6000).groupby('race_date').agg(
                        n=('race_key','size'),hit=('hit_delta','sum'),roi=('roi_delta','sum'))
                n=len(daily)
                w=np.random.default_rng(20261025).multinomial(n,np.full(n,1/n),size=2000)
                denom=w@daily.n.to_numpy()
                for metric in ['hit','roi']:
                    draw=(w@daily[metric].to_numpy())/denom
                    lo,hi=np.quantile(draw,[.025,.975])
                    contrasts.append(dict(scope=scope,subgroup=subgroup,metric=metric,races=len(g),dates=n,
                        difference=float(daily[metric].sum()/len(g)),ci_low=float(lo),ci_high=float(hi)))
    return pd.DataFrame(rows),pd.DataFrame(contrasts),pd.DataFrame(transitions)


def main():
    freeze();r=evaluate(frame());s,b,t=aggregate(r)
    s.to_csv(OUT/'summary.csv',index=False);b.to_csv(OUT/'paired_differences.csv',index=False)
    t.to_csv(OUT/'gain_loss_summary.csv',index=False)
    print(s[s.scope.eq('previous_4133')].to_string(index=False))
    print(t[t.scope.eq('previous_4133')].to_string(index=False))


if __name__=='__main__':main()
