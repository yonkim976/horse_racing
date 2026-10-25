"""Fixed-budget trio policy comparison with existing model distributions."""
from functools import lru_cache
import hashlib
import itertools
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.special import logsumexp
import torch  # Load OpenMP before the repository's LightGBM helpers.

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=R.parents[1]
OUT=HERE/'outputs'
DYN=R/'20261022_dynamic_race_model_v1'
OLD=R/'20261024_axis4_trio_comparison_v1/outputs'
RET=R/'20261025_trio_six_ten_returns_v1/outputs'
RISK=R/'20261024_axis_failure_risk_v1/outputs'
FULL=R/'20261009_gate_front_late_v1/outputs'
BASE=R/'20261022_probability_comparison_v1'
OP=ROOT/'data/research/thoroughbred_boundary_20260918_v6/A_horse_predictions.parquet'
sys.path.insert(0,str(DYN))
import common as c
import joint


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(p,obj):
    assert p.resolve().is_relative_to(HERE)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


@lru_cache(maxsize=32)
def support(n):
    triples=np.asarray(list(itertools.combinations(range(n),3)),dtype=int)
    inc=np.zeros((len(triples),n),float)
    inc[np.arange(len(triples))[:,None],triples]=1
    return triples,inc


def distribution(energy):
    triples,inc=support(len(energy))
    z=np.asarray(energy,float)[triples].sum(1)
    return np.exp(z-logsumexp(z))


def inverse_marginals(p,zero_start=False):
    """Invert the existing additive fixed-size exponential family, without labels."""
    p=np.asarray(p,float);n=len(p);triples,inc=support(n);b=inc[:,:-1]
    assert abs(p.sum()-3)<1e-9 and ((p>0)&(p<1)).all()
    if zero_start:x=np.zeros(n-1)
    else:
        initial=np.log(p)-np.log1p(-p);x=initial[:-1]-initial[-1]
    for iteration in range(80):
        z=b@x;q=np.exp(z-logsumexp(z));m=q@inc
        error=float(np.max(np.abs(m-p)))
        if error<5e-12:break
        grad=m[:-1]-p[:-1]
        h=(b.T*q)@b-np.outer(m[:-1],m[:-1])
        step=np.linalg.solve(h,grad)
        objective=float(logsumexp(z)-p[:-1]@x)
        scale=1.
        for _ in range(40):
            candidate=x-scale*step
            new=float(logsumexp(b@candidate)-p[:-1]@candidate)
            if new<=objective-1e-4*scale*float(grad@step)+1e-14:
                x=candidate;break
            scale*=.5
        else:raise AssertionError('Inverse line search failed')
    energy=np.r_[x,0.]
    q=distribution(energy);error=float(np.max(np.abs(q@inc-p)))
    assert error<2e-10,('inverse mismatch',error)
    return energy,q,error,iteration+1


def preflight():
    rng=np.random.default_rng(20261025);worst=0.
    for n in [6,10,16]:
        triples,inc=support(n)
        for scale in [.2,1.,3.]:
            energy=rng.normal(size=n)*scale;q=distribution(energy);p=q@inc
            for zero in [False,True]:
                recovered,got,error,it=inverse_marginals(p,zero)
                worst=max(worst,float(np.max(np.abs(got-q))))
                assert np.max(np.abs(got-q))<2e-10
    # Independent outcome/price data is absent from both selection and inversion.
    save(OUT/'preflight.json',dict(status='passed',synthetic_inverse_cases=18,max_joint_probability_error=worst))


def inputs():
    paths=[HERE/'PLAN.md',OP,OLD/'race_results.parquet',OLD/'verification.json',
        RET/'winning_dividends.parquet',RET/'return_summary.csv',RET/'verification.json',
        DYN/'outputs/runner_probabilities.parquet',DYN/'outputs/state_features.parquet',DYN/'joint.py',DYN/'common.py',
        FULL/'runner_predictions.parquet',FULL/'features.parquet',FULL/'feature_contract.json',
        BASE/'outputs/runner_probabilities.parquet',BASE/'outputs/calibration_parameters.json',
        BASE/'probability.py',BASE/'run.py',RISK/'race_predictions.parquet',
        ROOT/'config/prediction_model_registry.json',
        ROOT/'data/research/thoroughbred_three_targets_20260918_v3/code/targets_core.py']
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            for variant in ['state_gbm','state_joint']:
                folder=DYN/'outputs/models'/f'{variant}_{meet}_{year}'
                paths += [folder/'metadata.json',folder/('scores.parquet' if variant=='state_gbm' else 'encoding.json')]
                if variant=='state_joint':paths.append(folder/'model.safetensors')
    return list(dict.fromkeys(paths))


def select(g,q,previous,model):
    triples,inc=support(len(g));numbers=g.program_no.to_numpy(int)
    assert g.program_no.is_monotonic_increasing
    assert np.isfinite(q).all() and q.min()>=0 and abs(q.sum()-1)<1e-9
    marginal=q@inc
    expected=g.expected_probability.to_numpy(float)
    err=float(np.max(np.abs(marginal-expected)))
    assert err<2e-10,(model,g.race_key.iloc[0],err)
    axis=int(numbers[np.argsort(-np.round(marginal,12),kind='stable')[0]])
    assert axis==previous.axis,(model,g.race_key.iloc[0],axis,previous.axis)
    other=list(map(int,previous.companions.split(',')))
    fixed={tuple(sorted((axis,*p))) for p in itertools.combinations(other,2)}
    keys=[tuple(t) for t in numbers[triples]]
    lookup={k:i for i,k in enumerate(keys)}
    old_index=np.array([lookup[t] for t in sorted(fixed)],int)
    order=np.argsort(-np.round(q,12),kind='stable')
    free_index=order[:6]
    assert len(set(free_index))==6 and q[free_index].sum()>=q[old_index].sum()-1e-10
    truth=tuple(sorted(g.loc[g.outcome.between(1,3),'program_no'].astype(int)))
    assert truth==tuple(map(int,previous.actual.split(',')))
    old_hit=truth in fixed;free_keys={keys[i] for i in free_index};free_hit=truth in free_keys
    assert old_hit==previous.hit
    records=[]
    for policy,indices in [('axis_six',old_index),('joint_top6',free_index)]:
        for rank,ix in enumerate(indices,1):
            records.append(dict(race_key=previous.race_key,model=model,policy=policy,rank=rank,
                a=keys[ix][0],b=keys[ix][1],c=keys[ix][2],probability=float(q[ix]),hit=keys[ix]==truth))
    row=dict(race_key=previous.race_key,race_date=previous.race_date,year=int(previous.year),meet=int(previous.meet),
        model=model,axis=axis,field_size=len(g),axis_hit=bool(previous.axis_hit),
        axis_six_hit=old_hit,joint_top6_hit=free_hit,axis_six_probability=float(q[old_index].sum()),
        joint_top6_probability=float(q[free_index].sum()),changed_tickets=6-len(fixed&free_keys),
        joint_horses=len(set(x for t in free_keys for x in t)),
        joint_without_axis=sum(axis not in t for t in free_keys),marginal_max_error=err,
        boundary_gap=float(q[order[5]]-q[order[6]]) if len(q)>6 else None)
    return row,records


def evaluate():
    old=pd.read_parquet(OLD/'race_results.parquet').query("scope=='identical_roster'")
    assert old.groupby('model').size().eq(4133).all()
    keys=set(old.race_key);previous={(r.model,r.race_key):r for r in old.itertuples()}
    frame=c.frame();frame=frame[frame.race_key.isin(keys)].copy()
    assert frame.race_key.nunique()==4133
    probabilities=pd.read_parquet(DYN/'outputs/runner_probabilities.parquet')
    baseline=probabilities[probabilities.variant.eq('state_gbm')]
    combined=frame.merge(baseline[['race_key','program_no','horse_id','top3']],on=['race_key','program_no','horse_id'],validate='1:1')
    assert len(combined)==len(frame)
    frame=combined.rename(columns={'top3':'base_probability'})
    raw_full=pd.read_parquet(FULL/'runner_predictions.parquet').query("variant=='full103' and target==3")
    old_full=pd.read_parquet(BASE/'outputs/runner_probabilities.parquet').query("variant=='full103'")
    full_lookup=raw_full.set_index(['race_key','program_no']).raw_score
    full_p=old_full.set_index(['race_key','program_no']).top3
    cal=json.loads((BASE/'outputs/calibration_parameters.json').read_text())
    temps={(x['meet'],x['evaluation_year']):x['set_temperature'] for x in cal if x['variant']=='full103'}
    nn_p=probabilities[probabilities.variant.eq('state_joint')].set_index(['race_key','program_no']).top3
    risk=pd.read_parquet(RISK/'race_predictions.parquet').set_index('race_key')
    op=pd.read_parquet(OP)
    op=op[op.candidate.eq('current_A') & op.venue_code.isin(['SEOUL','BUSAN'])].copy()
    z=op.race_id.str.extract(r'RACE:(SEOUL|BUSAN):(\d{8}):(\d+)')
    op['race_key']=z[0].map({'SEOUL':'1','BUSAN':'3'})+':'+z[1]+':'+z[2].astype(int).astype(str)
    op_p=op.set_index(['race_key','hr_no']).probability
    rows=[];tickets=[];latent=[];inverse_errors=[]
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            one=frame[frame.meet.eq(meet)&frame.year.eq(year)].reset_index(drop=True)
            gf=DYN/'outputs/models'/f'state_gbm_{meet}_{year}'
            gm=json.loads((gf/'metadata.json').read_text())
            assert gm['calibration_year']==year-1 and gm['train_end_year']<year
            scores=pd.read_parquet(gf/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
            one['gbm_score']=one.row_number.map(scores)
            nf=DYN/'outputs/models'/f'state_joint_{meet}_{year}'
            nm=json.loads((nf/'metadata.json').read_text());encoding=json.loads((nf/'encoding.json').read_text())
            assert sha(ROOT/nm['model_path'])==nm['model_sha256'] and nm['calibration_year']==year-1 and nm['train_end_year']<year
            x,_=joint.encode(one,nm['features'],meta=encoding)
            model=joint.restore(ROOT/nm['model_path'],nm['inputs'])
            for ix in one.groupby('race_key',sort=False).indices.values():
                g=one.iloc[ix].copy();key=g.race_key.iloc[0];numbers=g.program_no.to_numpy(int)
                mi=pd.MultiIndex.from_arrays([g.race_key,numbers]);triples,inc=support(len(g))
                op_index=pd.MultiIndex.from_arrays([g.race_key,g.horse_id])
                target=op_p.loc[op_index].to_numpy(float)
                energy,oq,err,iterations=inverse_marginals(target)
                _,qzero,errzero,itzero=inverse_marginals(target,True)
                assert np.max(np.abs(oq-qzero))<2e-10
                assert np.array_equal(np.argsort(-np.round(oq,12),kind='stable')[:6],np.argsort(-np.round(qzero,12),kind='stable')[:6]),key
                inverse_errors.append(dict(race_key=key,error=err,second_start_error=errzero,
                    q_start_max_difference=float(np.max(np.abs(oq-qzero))),iterations=iterations,zero_iterations=itzero))
                for num,e,p in zip(numbers,energy,target):latent.append(dict(race_key=key,program_no=int(num),energy=float(e),original_probability=float(p)))
                fq=c.prob.trio_distribution(full_lookup.loc[mi].to_numpy(float),temps[(meet,year)])
                bq=c.prob.trio_distribution(g.gbm_score.to_numpy(float),gm['temperature'])
                ordered,mass=joint.distribution(model,x[ix],nm['temperature'])
                assert np.array_equal(np.sort(ordered.reshape(-1,6,3)[:,0,:],axis=1),triples)
                nq=mass.reshape(-1,6).sum(1)
                rr=risk.loc[key];base_axis=int(np.flatnonzero(numbers==rr.axis_program_no)[0])
                pi=float((bq@inc)[base_axis]);assert abs(pi-rr.base_axis_probability)<2e-10
                newp=(1-rr.policy_lambda)*pi+rr.policy_lambda*(1-rr.model_risk)
                event=(triples==base_axis).any(1)
                rq=bq*np.where(event,newp/pi,(1-newp)/(1-pi))
                bundles=[('operating_A_v5',oq,target),('full103',fq,full_p.loc[mi].to_numpy(float)),
                    ('state_gbm118',bq,g.base_probability.to_numpy(float)),('state_joint118',nq,nn_p.loc[mi].to_numpy(float)),
                    ('axis_failure_selected',rq,rq@inc)]
                for name,q,p in bundles:
                    h=g.copy();h['expected_probability']=p
                    row,t=select(h,q,previous[(name,key)],name);rows.append(row);tickets.extend(t)
            print('Replayed',meet,year,one.race_key.nunique(),flush=True)
    f=pd.DataFrame(rows);t=pd.DataFrame(tickets)
    payouts=pd.read_parquet(RET/'winning_dividends.parquet')
    f=f.merge(payouts[['race_key','status','dividend']],on='race_key',validate='m:1')
    assert len(f)==4133*5 and f.status.eq('valid').all()
    f.to_parquet(OUT/'race_results.parquet',compression='zstd',index=False)
    t.to_parquet(OUT/'selected_tickets.parquet',compression='zstd',index=False)
    pd.DataFrame(latent).to_parquet(OUT/'operating_energies.parquet',compression='zstd',index=False)
    pd.DataFrame(inverse_errors).to_csv(OUT/'operating_inverse_diagnostics.csv',index=False)
    return f


def aggregate(f):
    rows=[];contrasts=[]
    for name,g in [('all',f),*[(str(y),z) for y,z in f.groupby('year')],*[(('seoul' if m==1 else 'busan'),z) for m,z in f.groupby('meet')]]:
        for model,z in g.groupby('model'):
            for policy in ['axis_six','joint_top6']:
                hits=z[policy+'_hit'].astype(int);payout=z.dividend*hits*1000
                cost=len(z)*6000;best=float(payout.max())
                rows.append(dict(subgroup=name,model=model,policy=policy,races=len(z),hits=int(hits.sum()),
                    hit_rate=float(hits.mean()),stake_krw=cost,return_krw=round(float(payout.sum()),6),
                    net_krw=round(float(payout.sum()-cost),6),roi=float(payout.sum()/cost-1),
                    mean_prediction=float(z[policy+'_probability'].mean()),
                    roi_without_best_race=float((payout.sum()-best)/((len(z)-1)*6000)-1),
                    best_race_payout_share=best/float(payout.sum())))
            if name in ['all','2024','2025','2026']:
                daily=z.assign(hit_diff=z.joint_top6_hit.astype(int)-z.axis_six_hit.astype(int),
                    return_diff=z.dividend*(z.joint_top6_hit.astype(int)-z.axis_six_hit.astype(int))/6).groupby('race_date').agg(n=('race_key','size'),hit=('hit_diff','sum'),roi=('return_diff','sum'))
                n=len(daily);w=np.random.default_rng(20261025).multinomial(n,np.full(n,1/n),size=2000);den=w@daily.n.to_numpy()
                for metric in ['hit','roi']:
                    boot=(w@daily[metric].to_numpy())/den;ci=np.quantile(boot,[.025,.975])
                    contrasts.append(dict(subgroup=name,model=model,metric=metric,races=len(z),dates=n,
                        difference=float(daily[metric].sum()/len(z)),ci_low=float(ci[0]),ci_high=float(ci[1]),
                        gained=int((~z.axis_six_hit&z.joint_top6_hit).sum()),lost=int((z.axis_six_hit&~z.joint_top6_hit).sum()),
                        changed_races=int(z.changed_tickets.gt(0).sum()),mean_changed_tickets=float(z.changed_tickets.mean()),
                        mean_joint_horses=float(z.joint_horses.mean()),mean_joint_without_axis=float(z.joint_without_axis.mean())))
    return pd.DataFrame(rows),pd.DataFrame(contrasts)


def main():
    OUT.mkdir(exist_ok=True)
    manifest={str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in inputs()}
    save(OUT/'input_manifest.json',manifest)
    shared=[R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md',R/'conclusions/source_manifest.json',R/'ARTIFACT_SIZE_LOG.md']
    if not (OUT/'publication_before.json').exists():save(OUT/'publication_before.json',{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
    preflight();f=evaluate();s,p=aggregate(f)
    s.to_csv(OUT/'summary.csv',index=False);p.to_csv(OUT/'paired_differences.csv',index=False)
    print(s[s.subgroup.eq('all')].to_string(index=False))
    for path,m in manifest.items():assert sha(ROOT/path)==m['sha256'],path


if __name__=='__main__':main()
