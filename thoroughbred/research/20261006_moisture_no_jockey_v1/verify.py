"""Rider-free feature contract, perturbation invariance and independent trio replay."""
from pathlib import Path
import hashlib
import importlib.util
import json
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261005_moisture_finish_v1/outputs'
RAW=HERE.parent/'20261004_outsider_joint_v1/outputs'
KEY=['race_key','program_no','horse_id']
spec=importlib.util.spec_from_file_location('independent_no_jockey_joint',RAW.parent/'verify.py')
OLD=importlib.util.module_from_spec(spec);spec.loader.exec_module(OLD)
checks=0;maximum=0.

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def check(ok,message=''):
    global checks
    checks+=1
    if not ok:raise AssertionError(f'{checks}: {message}')
def close(a,b):
    global maximum
    a=np.asarray(a,float);b=np.asarray(b,float);check(a.shape==b.shape)
    check(np.array_equal(np.isnan(a),np.isnan(b)))
    valid=np.isfinite(a)&np.isfinite(b)
    e=float(abs(a[valid]-b[valid]).max()) if valid.any() else 0.
    maximum=max(maximum,e);check(e<2e-10,str(e))

def assemble(raw,adj,cols):
    result=raw[['race_key','program_no','horse_id','meet','race_date','year']].copy()
    for col in cols:
        if col.startswith('moist_'):
            result[col]=adj[col] if col in adj else adj[col.removeprefix('moist_')]
        else:result[col]=raw[col]
    return result

def main():
    audit=json.loads((OUT/'audit.json').read_text());summary=json.loads((OUT/'summary.json').read_text())
    for p,h in audit['inputs'].items():check(sha(ROOT/p)==h,p)
    for p,h in summary['artifacts'].items():check(sha(OUT/p)==h,p)
    contract=json.loads((OUT/'feature_contract.json').read_text());cols=contract['no_jockey']
    oldcols=json.loads((PARENT/'feature_contract.json').read_text())['augment']
    removed=[c for c in oldcols if 'jockey' in c or c in ['pair_history_count','pair_early_count','pair_aggression']]
    check(contract['removed']==removed);check(len(removed)==26);check(cols==[c for c in oldcols if c not in removed]);check(len(cols)==258)
    check(not any('jockey' in c for c in cols));check(not set(cols)&{'horse_id','program_no','outcome','S1F_rank','G3F_rank'})
    gates=['gate_number_proxy','gate_fraction_proxy','gate_inner_proxy','gate_outer_proxy','gate_style_interaction','conditioned_gate_style']
    check(set(gates)<=set(cols));check('jockey_gate_interaction' not in cols);check(not any(c.startswith('stack_') for c in cols))
    raw=pd.read_parquet(RAW/'features.parquet');adj=pd.read_parquet(PARENT/'adjusted_features.parquet')
    check(raw[KEY].equals(adj[KEY]))
    assembled=assemble(raw,adj,cols)
    changed=raw.copy()
    for c in removed:
        if c in changed:changed[c]=10000.
    for c in ['jockey_id','jockey_name','previous_jockey_id']:
        if c in changed:changed[c]='perturbed'
    perturbed=assemble(changed,adj,cols)
    pd.testing.assert_frame_equal(assembled,perturbed,check_exact=True);check(True)
    labels=pd.read_parquet(HERE.parent/'20261004_pace_finish_stack_v1/outputs/labels.parquet')
    assembled=assembled.merge(labels,on=KEY,validate='one_to_one');perturbed=perturbed.merge(labels,on=KEY,validate='one_to_one')
    races=pd.read_csv(OUT/'race_metrics.csv',low_memory=False);runners=pd.read_parquet(OUT/'runner_predictions.parquet');rec=pd.read_parquet(OUT/'recommendations.parquet')
    check(races.groupby('variant').race_key.nunique().to_dict()=={v:4799 for v in ['with_jockey','with_jockey_joint','no_jockey','no_jockey_joint']})
    previous=pd.read_parquet(PARENT/'runner_predictions.parquet')
    for a,b in [('with_jockey','augment'),('with_jockey_joint','augment_joint')]:
        p=runners[runners.variant.eq(a)].merge(previous[previous.variant.eq(b)],on=KEY,validate='one_to_one',suffixes=('_new','_old'))
        check(len(p)==50754);close(p.prob_top3_new,p.prob_top3_old)
    rg=dict(tuple(runners.groupby(['variant','race_key'])));cg=dict(tuple(rec.groupby(['variant','race_key'])))
    eg=races.set_index(['variant','race_key'])
    for meet in (1,3):
        for year in (2024,2025,2026):
            mask=assembled.meet.eq(meet)&assembled.year.isin([year-1,year])
            g=assembled[mask].reset_index(drop=True);gp=perturbed[mask].reset_index(drop=True)
            path=OUT/'models'/f'{meet}_{year}_no_jockey';meta=json.loads((path/'metadata.json').read_text());pair=json.loads((path/'joint.json').read_text())
            check(meta['features']==cols);check(not meta['explicit_rider_features']);check(meta['validation_year']==year-2)
            check(pd.Timestamp(meta['train_end'])<pd.Timestamp(year-1,1,1));check(meta['calibration_year']==year-1)
            check(sha(path/'top3.txt')==meta['model_sha256']);check(pair['training_year']==year-1);check(pair['success'])
            model=lgb.Booster(model_file=str(path/'top3.txt'));check(model.feature_name()==cols);check(model.num_trees()==meta['trees'])
            def x(frame):
                f=frame[cols].copy()
                for c,v in meta['category_vocabulary'].items():f[c]=pd.Categorical(f[c],categories=v)
                return f
            scores=model.predict(x(g),raw_score=True,num_threads=4)
            close(scores,model.predict(x(gp),raw_score=True,num_threads=4))
            energies=[];truths=[];designs=[];calm={v:[] for v in ['no_jockey','no_jockey_joint']};cal_joint_nll=[]
            for rid,ids in g.groupby('race_key',sort=False).indices.items():
                one=g.iloc[ids];n=len(one);sets,_,_=OLD.support(n)
                inc=np.stack([(sets==i).any(axis=1).astype(float) for i in range(n)],axis=1)
                energy=scores[ids][sets].sum(axis=1);design=OLD.design(one)
                truth=set(np.flatnonzero(one.outcome.le(3)));target=next(i for i,s in enumerate(sets) if set(s)==truth)
                for variant,joint in [('no_jockey',None),('no_jockey_joint',pair)]:
                    e=energy/(meta['temperature'] if joint is None else joint['temperature'])
                    if joint is not None:e+=((design-joint['mean'])/joint['scale'])@np.array(joint['coefficients'])
                    q=np.exp(e-logsumexp(e));m=q@inc;best=np.argsort(-q,kind='stable')[:6];mass=float(q[best].sum())
                    if int(one.year.iloc[0])==year-1:
                        calm[variant].append(mass)
                        if joint is not None:cal_joint_nll.append(-np.log(q[target]))
                        continue
                    saved=rg[(variant,rid)].sort_values('program_no');r=eg.loc[(variant,rid)];cs=cg[(variant,rid)].sort_values('selection_rank')
                    check(np.array_equal(saved.program_no,one.program_no));close(saved.prob_top3,m);close(saved.raw_top3_score,scores[ids])
                    close(q.sum(),1.);close(m.sum(),3.);close(r.trio_nll,-np.log(q[target]));close(r.top3_brier,np.mean((m-one.outcome.le(3).to_numpy())**2))
                    close(r.trio6_probability,mass);check(r.trio6_hit==int(target in best));check(r.selected==int(mass>=meta['thresholds'][variant]))
                    expected=[','.join(map(str,sorted(one.program_no.iloc[sets[j]].astype(int)))) for j in best]
                    check(cs.programs.tolist()==expected);close(cs.probability,q[best]);check(cs.hit.sum()==r.trio6_hit)
                    rank=np.argsort(-m,kind='stable')
                    for k in (3,5,6,7):check(r[f'top{k}_contains_podium']==int(truth<=set(rank[:k])))
                if int(one.year.iloc[0])==year-1:energies.append(energy);truths.append(target);designs.append(design)
            width=max(map(len,energies));matrix=np.full((len(energies),width),-np.inf)
            actual=np.array([e[t] for e,t in zip(energies,truths)])
            for i,e in enumerate(energies):matrix[i,:len(e)]=e
            fit=minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-actual/t)),bounds=(.35,4),method='bounded')
            check(fit.success);close(meta['temperature'],fit.x)
            mean=np.mean([z.mean(axis=0) for z in designs],axis=0)
            scale=np.maximum(np.sqrt(np.mean([((z-mean)**2).mean(axis=0) for z in designs],axis=0)),.05)
            close(pair['mean'],mean);close(pair['scale'],scale);close(pair['penalty'],50/len(designs))
            close(pair['loss'],np.mean(cal_joint_nll)+.5*pair['penalty']*sum(np.array(pair['coefficients'])**2))
            for v,masses in calm.items():close(meta['thresholds'][v],np.median(masses))
    for row in pd.read_csv(OUT/'metrics.csv').itertuples():
        group=races[races.meet.eq(row.meet)&races.variant.eq(row.variant)]
        if row.period!='all':group=group[group.evaluation_year.eq(int(row.period))]
        check(len(group)==row.races);check(group.trio6_hit.sum()==row.hits)
        for col in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium','top7_contains_podium']:close(getattr(row,col),group[col].mean())
    for p,h in audit['inputs'].items():check(sha(ROOT/p)==h,p)
    result=dict(passed=True,checks=checks,max_numeric_error=maximum,new_head_replays=6,
                policies=4,evaluated_races_per_policy=4799,removed_rider_features=26,retained_features=258,
                rider_input_perturbation_invariant=True,inputs_unchanged=True)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
