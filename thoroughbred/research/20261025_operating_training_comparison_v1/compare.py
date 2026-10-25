"""Read-only, matched-race comparison with the exact registered operational ABC."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib
import torch
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];R=HERE.parent;OUT=HERE/'outputs'
PREV=R/'20261024_training_state_v1';STATE=R/'20261022_dynamic_race_model_v1'
OPS=R/'20261004_close_contenders_v1/outputs'
sys.path.insert(0,str(STATE));import common as ref
sys.path.insert(0,str(ROOT/'data/research/thoroughbred_three_targets_20260918_v3/code'));import targets_core as tc
KEY=['race_key','program_no','horse_id'];VARIANTS=['operating','state_gbm','personal_t2'];PREVIOUS_BYTES=195_899_998
HITS=['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three','trio_one','trio_six','ordered_one','ordered_six']
LOSSES=['runner_brier','native_trio_logloss','native_ordered_logloss','axis_brier']
def sha(p):return ref.sha(p)
def save(p,v):
    p=Path(p);assert p.resolve().is_relative_to(HERE);p.parent.mkdir(exist_ok=True,parents=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def bridge(s):return s.str.replace('RACE:SEOUL:','1:',regex=False).str.replace('RACE:BUSAN:','3:',regex=False).str.replace(r':0([1-9])$',r':\1',regex=True)
def signature(g):return frozenset(zip(g.program_no,g.horse_id,pd.to_numeric(g.outcome,errors='coerce').where(g.outcome.between(1,20),0).fillna(0).astype(int)))
def folder(v,m):return (STATE if v=='state_gbm' else PREV)/'outputs/models'/f'{v}_{m}_2026'
def freeze():
    assert not (OUT/'input_manifest.json').exists()
    registry=json.loads((ROOT/'config/prediction_model_registry.json').read_text());profile=registry['domains']['thoroughbred']['active_profile']
    assert profile=='thoroughbred-main-20260919-v1';p=registry['profiles'][profile]
    paths=[HERE/'PLAN.md',HERE/'compare.py',OPS/'operating_runner_predictions.parquet',OPS/'operating_trio6.parquet',OPS/'audit.json',OPS/'verification.json',
        R/'20261006_moisture_no_jockey_v1/outputs/operating_comparison.json',ROOT/'config/prediction_model_registry.json',
        ROOT/'data/research/thoroughbred_three_targets_20260918_v3/code/targets_core.py',
        STATE/'common.py',ref.BASE/'probability.py',ref.BASE/'evaluate.py',ref.BASE/'outputs/population_flags.parquet']
    for name in ['A_model','A_metadata','BC_model','BC_metadata','WIN_ORDER_model','WIN_ORDER_metadata']:
        x=p['artifacts'][name];assert sha(ROOT/x['path'])==x['sha256'];paths.append(ROOT/x['path'])
    for parent in [STATE,PREV]:
        paths.extend(parent/'outputs'/name for name in ['race_metrics.parquet','runner_probabilities.parquet'])
    for v in ['state_gbm','personal_t2']:
        for m in [1,3]:paths.extend(folder(v,m)/name for name in ['model.txt','metadata.json','scores.parquet'])
    paths+= [ref.base.SOURCE/'features.parquet',ref.base.SOURCE/'feature_contract.json',STATE/'outputs/state_features.parquet']
    old=json.loads((R/'20261006_moisture_no_jockey_v1/outputs/operating_comparison.json').read_text())
    expected=old['inputs'][str(OPS/'operating_runner_predictions.parquet')]
    assert sha(OPS/'operating_runner_predictions.parquet')==expected
    assert json.loads((OPS/'verification.json').read_text())['passed']
    save(OUT/'input_manifest.json',{str(x.relative_to(ROOT)):{'sha256':sha(x),'bytes':x.stat().st_size} for x in paths})
    save(OUT/'protocol.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'primary_variant':'personal_t2',
        'control':'state_gbm','operating_profile':profile,'champion':p['champion_id'],'no_fitting':True,
        'evaluation_year':2026,'pair_policy':'derive from A joint, same fixed1/3 pairs; not a live-ticket ledger',
        'native_trio_policy':'operating B / research set distribution,1/6','native_order_policy':'operating C / research ordered distribution,1/6'})
def check():
    for n,v in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/n)==v['sha256'],n
def operational_metadata():
    p=json.loads((ROOT/'config/prediction_model_registry.json').read_text())['profiles']['thoroughbred-main-20260919-v1']
    return {k:json.loads((ROOT/p['artifacts'][k+'_metadata']['path']).read_text()) for k in ['A','BC','WIN_ORDER']}
def ops_joints(g,metadata):
    venue='SEOUL' if int(g.meet.iloc[0])==1 else 'BUSAN'
    ta=metadata['A']['temperature_by_target_and_venue']['A'][venue]
    tb=metadata['BC']['temperature_by_target_and_venue']['B'][venue]
    tc_temp=metadata['BC']['temperature_by_target_and_venue']['C'][venue]
    tw=metadata['WIN_ORDER']['temperature_by_venue'][venue]
    w=g.raw_win_score.to_numpy(float);a=g.raw_a_score.to_numpy(float);b=g.raw_bc_score.to_numpy(float)
    return [tc.top3_set_joint(s,w,t,tw) for s,t in [(a,ta),(b,tb),(b,tc_temp)]]
def native(g,sets,q,orders,mass):
    y=g.outcome.to_numpy(int);truth=np.flatnonzero((y>=1)&(y<=3));ordered=np.array([np.flatnonzero(y==k)[0] for k in [1,2,3]])
    true_set=np.isin(sets,truth).all(1);true_order=(orders==ordered).all(1);assert true_set.sum()==true_order.sum()==1
    bs=ref.scorer.probability_order(q)[:6]
    # Canonical ascending program order resolves any exact/rounded probability ties.
    ix=np.lexsort((orders[:,2],orders[:,1],orders[:,0],-np.round(mass,12)))[:6]
    return {'trio_one':int(true_set[bs[0]]),'trio_six':int(true_set[bs].any()),
        'ordered_one':int(true_order[ix[0]]),'ordered_six':int(true_order[ix].any()),
        'native_trio_logloss':float(-np.log(q[true_set][0])),
        'native_ordered_logloss':float(-np.log(mass[true_order][0]))}
def cohort(op,f):
    op=op.copy();op['bridge']=bridge(op.race_key)
    og={k:g for k,g in op.groupby('bridge',sort=False)};fg={k:g for k,g in f.groupby('race_key',sort=False)}
    matched=[];excluded=[]
    for key,g in og.items():
        reason='absent_from_research_evaluation' if key not in fg else 'runner_or_rank_mismatch' if signature(g)!=signature(fg[key]) else None
        if reason:excluded.append({'race_key':key,'operating_race_key':g.race_key.iloc[0],'reason':reason,'operating_runners':len(g)})
        else:matched.append(key)
    assert len(matched)==1258 and len(excluded)==7
    save(OUT/'cohort_audit.json',{'operating_races':len(og),'research_2026_races':len(fg),'matched_races':len(matched),
        'matched_starters':sum(len(og[k]) for k in matched),'excluded_operating_races':excluded,
        'numeric_rank_normalization_for_matching_only':True,'all_common_races_had_identical_runner_and_rank_sets':True})
    pd.DataFrame([{'race_key':k,'operating_race_key':og[k].race_key.iloc[0],'race_date':str(pd.Timestamp(og[k].race_date.iloc[0]).date()),
        'meet':int(og[k].meet.iloc[0]),'starters':len(og[k])} for k in matched]).to_parquet(OUT/'cohort.parquet',index=False,compression='zstd')
    return og,fg,matched
def calculate():
    check();assert not (OUT/'race_metrics.parquet').exists()
    op=pd.read_parquet(OPS/'operating_runner_predictions.parquet');f=ref.frame();f=f[f.year.eq(2026)].copy()
    flags=pd.read_parquet(ref.BASE/'outputs/population_flags.parquet')
    f=f.merge(flags[KEY+['normal_finisher','ambiguous_flag']],on=KEY,validate='one_to_one')
    og,fg,matched=cohort(op,f);met=operational_metadata();rows=[];errors=[];native_checks=0;axes=[]
    old_trio=pd.read_parquet(OPS/'operating_trio6.parquet').groupby('race_key')
    stored={v:pd.read_parquet((STATE if v=='state_gbm' else PREV)/'outputs/runner_probabilities.parquet').query('variant==@v').set_index(KEY)
        for v in ['state_gbm','personal_t2']}
    saved_metrics={v:pd.read_parquet((STATE if v=='state_gbm' else PREV)/'outputs/race_metrics.parquet').query('variant==@v').set_index('race_key')
        for v in ['state_gbm','personal_t2']}
    bundles={(v,m):(json.loads((folder(v,m)/'metadata.json').read_text()),pd.read_parquet(folder(v,m)/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score)
        for v in ['state_gbm','personal_t2'] for m in [1,3]}
    for key in matched:
        g=fg[key].sort_values('program_no').reset_index(drop=True)
        oo=og[key].sort_values('program_no').reset_index(drop=True)
        assert np.array_equal(g.program_no,oo.program_no) and np.array_equal(g.horse_id,oo.horse_id)
        ja,jb,jc=ops_joints(oo,met)
        row,_,rr=ref.scorer.score_race(g,oo.raw_a_score.to_numpy(),ja.orders,ja.order_probability,'operating','matched_2026')
        native_a=native(g,jb.sets,jb.set_probability,jc.orders,jc.order_probability);row.update(native_a);rows.append(row)
        errors.append(float(np.max(np.abs(rr[['win','top2','top3']].to_numpy()-oo[['prob_win','prob_top2','prob_top3']].to_numpy()))))
        saved=old_trio.get_group(oo.race_key.iloc[0]).sort_values('selection_rank')
        pick=ref.scorer.probability_order(jb.set_probability)[:6]
        expected=[','.join(map(str,sorted(g.iloc[jb.sets[t]].program_no.astype(int)))) for t in pick]
        assert expected==saved.programs.tolist();assert np.max(np.abs(jb.set_probability[pick]-saved.probability.to_numpy()))<1e-12
        native_checks+=6
        chosen={'race_key':key,'race_date':row['race_date'],'meet':row['meet'],'operating_axis':row['axis_program_no'],'operating_hit':row['axis_top3']}
        for variant in ['state_gbm','personal_t2']:
            meta,scores=bundles[variant,int(g.meet.iloc[0])];s=g.row_number.map(scores).to_numpy(float)
            assert np.isfinite(s).all();q=ref.prob.trio_distribution(s,meta['temperature']);orders,mass=ref.prob.ordered_distribution(s,q,meta['order_temperature'])
            r,_,p=ref.scorer.score_race(g,s,orders,mass,variant,'matched_2026');r.update(native(g,ref.base.triples(len(g)),q,orders,mass));rows.append(r)
            pp=stored[variant].loc[pd.MultiIndex.from_frame(g[KEY]),['win','top2','top3']]
            errors.append(float(np.max(np.abs(p[['win','top2','top3']].to_numpy()-pp.to_numpy()))))
            for name in ['axis_top3','axis_program_no','quinella_one','quinella_three','qpl_one','qpl_three']:
                assert r[name]==saved_metrics[variant].loc[key,name],(variant,key,name)
            chosen[variant+'_axis']=r['axis_program_no'];chosen[variant+'_hit']=r['axis_top3']
        axes.append(chosen)
    assert max(errors)<1e-12
    pd.DataFrame(rows).to_parquet(OUT/'race_metrics.parquet',index=False,compression='zstd')
    pd.DataFrame(axes).to_parquet(OUT/'axis_comparison.parquet',index=False,compression='zstd')
    save(OUT/'replay_checks.json',{'status':'passed','operating_and_research_races_replayed':len(rows),
        'original_operating_B_tickets_checked':native_checks,'max_saved_runner_probability_error':max(errors),
        'native_ABC_not_mixed':True,'same_population':True})
def paired(g,metric):
    a=g[metric+'_new'].to_numpy(float);b=g[metric+'_op'].to_numpy(float)
    dates,ix=np.unique(g.race_date_new,return_inverse=True);n=np.bincount(ix);s=np.bincount(ix,weights=a-b)
    draws=np.random.default_rng(20261025).integers(0,len(dates),size=(2000,len(dates)))
    boot=s[draws].sum(1)/n[draws].sum(1)
    return {'races':len(g),'operating_total':float(b.sum()),'candidate_total':float(a.sum()),'operating_mean':float(b.mean()),'candidate_mean':float(a.mean()),
        'difference':float((a-b).mean()),'ci95':np.quantile(boot,[.025,.975]).tolist(),
        'gains':int(((a>b) if metric in HITS else (a<b)).sum()),'losses':int(((a<b) if metric in HITS else (a>b)).sum())}
def summarize():
    r=pd.read_parquet(OUT/'race_metrics.parquet');op=r[r.variant.eq('operating')];groups=[]
    for variant in ['state_gbm','personal_t2']:
        g=r[r.variant.eq(variant)].merge(op,on='race_key',suffixes=('_new','_op'),validate='one_to_one')
        for meet in [0,1,3]:
            one=g if meet==0 else g[g.meet_new.eq(meet)]
            groups.append({'variant':variant,'meet':meet,'races':len(one),'metrics':{m:paired(one,m) for m in HITS+LOSSES}})
    a=r[r.variant.eq('personal_t2')].merge(r[r.variant.eq('state_gbm')],on='race_key',suffixes=('_new','_op'),validate='one_to_one')
    extra={'comparison':'personal_t2_minus_state_gbm_on_same_operating_cohort','metrics':{m:paired(a,m) for m in HITS+LOSSES}}
    save(OUT/'results.json',{'groups':groups,'training_increment':extra,'bootstrap_seed':20261025,'bootstrap_draws':2000,
        'independent_future_validation':False,'no_refitting_or_selection':True,'production_changed':False})
    for x in groups:
        if x['variant']=='personal_t2':print(x['meet'],json.dumps(x['metrics'],ensure_ascii=False),flush=True)
if __name__=='__main__':
    freeze();calculate();summarize();check()
