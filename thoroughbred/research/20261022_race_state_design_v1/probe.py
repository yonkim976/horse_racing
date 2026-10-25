"""One frozen policy comparison; no fitting, network, or database writes."""
from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / '20261022_probability_comparison_v1'
OUT = HERE / 'outputs'
FEATURES = HERE.parent / '20261009_gate_front_late_v1/outputs/features.parquet'
DOCS = ['thoroughbred/research/README.md', 'thoroughbred/research/conclusions/README.md',
        'thoroughbred/research/conclusions/SOURCES.md', 'thoroughbred/research/conclusions/source_manifest.json',
        'thoroughbred/research/ARTIFACT_SIZE_LOG.md']

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def save(name, value):
    p = (OUT / name).resolve()
    assert p.is_relative_to(OUT.resolve())
    OUT.mkdir(exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def freeze():
    assert not (OUT / 'results.json').exists()
    paths = [HERE/'PLAN.md', HERE/'probe.py', FEATURES, BASE/'outputs/race_metrics.parquet']
    for v in [1,3]:
        for y in [2024,2025,2026]:
            d = BASE/'outputs/models'/f'additive89_{v}_{y}'
            paths += [d/'metadata.json',d/'scores.parquet']
    manifest = {str(p.relative_to(ROOT)): {'sha256':sha(p),'bytes':p.stat().st_size} for p in paths}
    if (OUT/'input_manifest.json').exists():
        assert json.loads((OUT/'input_manifest.json').read_text()) == manifest
    else:
        save('input_manifest.json',manifest)
        save('protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
            'new_policy_count':1,'new_trained_models':0,'new_independent_test':False})
        save('preexisting_files.json',{s:{'bytes':(ROOT/s).stat().st_size,'sha256':sha(ROOT/s)} for s in DOCS})

def inputs_check():
    for s,v in json.loads((OUT/'input_manifest.json').read_text()).items():
        p = (ROOT/s).resolve()
        assert p.is_relative_to(ROOT) and p.stat().st_size==v['bytes'] and sha(p)==v['sha256'],s

@lru_cache(maxsize=20)
def support(n):
    pairs = np.array(list(combinations(range(n),2)),dtype=np.int16)
    triples = np.array(list(combinations(range(n),3)),dtype=np.int16)
    choices = np.array(list(combinations(range(len(pairs)),3)),dtype=np.int32)
    incidence = np.array([[set(p).issubset(t) for p in pairs] for t in triples],dtype=bool)
    lookup = {tuple(t):i for i,t in enumerate(triples)}
    m = len(pairs); sentinel = len(triples)
    overlap = np.full((m,m),sentinel,dtype=np.int32)
    for a,b in combinations(range(m),2):
        union = sorted(set(pairs[a])|set(pairs[b]))
        if len(union)==3:
            overlap[a,b] = overlap[b,a] = lookup[tuple(union)]
    a,b,d = choices.T
    correction = np.column_stack([overlap[a,b],overlap[a,d],overlap[b,d]])
    triangle = np.where((correction[:,0]==correction[:,1])&(correction[:,1]==correction[:,2]),
                        correction[:,0],sentinel)
    return pairs,triples,choices,incidence,correction,triangle

def objective(q,n):
    pairs,triples,choices,incidence,correction,triangle = support(n)
    marginal = q @ incidence
    extended = np.append(q,0.)
    union = marginal[choices].sum(axis=1)-extended[correction].sum(axis=1)+extended[triangle]
    return marginal,union

def direct(q,incidence,selected):
    return float(q[incidence[:,selected].any(axis=1)].sum())

def verify_formula():
    rng = np.random.default_rng(20261022)
    comparisons = 0; error = 0.
    for n in [3,4,5,6,7]:
        pairs,triples,choices,incidence,_,_ = support(n)
        for _ in range(2):
            q = rng.dirichlet(np.ones(len(triples)))
            _,fast = objective(q,n)
            literal = np.array([direct(q,incidence,x) for x in choices])
            error = max(error,float(np.max(abs(fast-literal))))
            assert np.allclose(fast,literal,atol=1e-12,rtol=0)
            comparisons += len(choices)
    return {'literal_all_choice_checks':comparisons,'max_error':error}

def bootstrap(g):
    cols=['old_hit','new_hit','old_count','new_count','old_brier','new_brier']
    by = g.groupby('race_date')[cols].sum()
    ns = g.groupby('race_date').size()
    rng = np.random.default_rng(20261022)
    w = rng.multinomial(len(by),np.ones(len(by))/len(by),size=2000)
    b = (w@by.to_numpy())/(w@ns.to_numpy())[:,None]
    out = {'n':len(g),'days':len(by),'old_hits':int(g.old_hit.sum()),'new_hits':int(g.new_hit.sum()),
        'old_hit_rate':float(g.old_hit.mean()),'new_hit_rate':float(g.new_hit.mean()),
        'difference':float((g.new_hit-g.old_hit).mean()),
        'relative_gain':float(g.new_hit.sum()/g.old_hit.sum()-1),
        'difference_ci95':np.quantile(b[:,1]-b[:,0],[.025,.975]).tolist(),
        'relative_gain_ci95':np.quantile(b[:,1]/b[:,0]-1,[.025,.975]).tolist(),
        'gains':int(((g.old_hit==0)&(g.new_hit==1)).sum()),
        'losses':int(((g.old_hit==1)&(g.new_hit==0)).sum()),
        'old_mean_count':float(g.old_count.mean()),'new_mean_count':float(g.new_count.mean()),
        'count_difference_ci95':np.quantile(b[:,3]-b[:,2],[.025,.975]).tolist(),
        'old_expected_count':float(g.old_expected_count.mean()),'new_expected_count':float(g.new_expected_count.mean()),
        'old_predicted_union':float(g.old_union.mean()),'new_predicted_union':float(g.new_union.mean()),
        'old_brier':float(g.old_brier.mean()),'new_brier':float(g.new_brier.mean()),
        'brier_difference_ci95':np.quantile(b[:,5]-b[:,4],[.025,.975]).tolist(),
        'old_count_distribution':{str(k):int(g.old_count.eq(k).sum()) for k in range(4)},
        'new_count_distribution':{str(k):int(g.new_count.eq(k).sum()) for k in range(4)},
        'changed_ticket_sets':int((~g.same_selection).sum()),
        'standalone_top_pair_included':int(g.top_pair_included.sum())}
    return out

def evaluate():
    inputs_check()
    assert not (OUT/'results.json').exists(),'Bounded probe already completed'
    verification = verify_formula()
    cols = ['race_key','program_no','horse_id','meet','race_date','year','outcome','field_size','distance_m','grade_raw']
    f = pd.read_parquet(FEATURES,columns=cols)
    assert len(f)==178497 and not f.duplicated(['race_key','program_no','horse_id']).any()
    f = f.sort_values(['meet','race_date','race_key','program_no']).reset_index(drop=True)
    f['row_number'] = np.arange(len(f))
    f = f[f.year.isin([2024,2025,2026])]
    assert len(f)==50754 and f.race_key.nunique()==4799
    old = pd.read_parquet(BASE/'outputs/race_metrics.parquet')
    old = old[(old.variant=='additive89')&(old.scope=='all_starters')].set_index('race_key')
    records=[];max_old_error=0.;max_literal_error=0.;max_choices=0
    for venue in [1,3]:
        for year in [2024,2025,2026]:
            folder=BASE/'outputs/models'/f'additive89_{venue}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            scores=pd.read_parquet(folder/'scores.parquet').set_index('row_number')['score']
            for key,g in f[(f.meet==venue)&(f.year==year)].groupby('race_key',sort=True):
                n=len(g);pairs,triples,choices,incidence,_,_=support(n)
                s=scores.loc[g.row_number].to_numpy()
                energy=s[triples].sum(axis=1)/meta['temperature']
                q=np.exp(energy-energy.max());q/=q.sum()
                marginal,unions=objective(q,n)
                old_selected=np.argsort(-np.round(marginal,12),kind='stable')[:3]
                new_selected=choices[np.argmax(np.round(unions,12))]
                old_union=direct(q,incidence,old_selected);new_union=direct(q,incidence,new_selected)
                max_literal_error=max(max_literal_error,abs(new_union-float(unions.max())))
                assert new_union>=old_union-2e-12
                assert max_literal_error<2e-12
                # Actual outcomes are used only after the recommendation is fixed.
                podium=g.outcome.between(1,3).to_numpy()
                actual_pairs=podium[pairs].all(axis=1)
                old_count=int(actual_pairs[old_selected].sum());new_count=int(actual_pairs[new_selected].sum())
                ref=old.loc[key]
                max_old_error=max(max_old_error,abs(old_union-ref.qpl3_probability),
                    abs(marginal[old_selected].sum()-ref.qpl_expected_count))
                assert max_old_error<2e-12 and old_count==ref.qpl_count and int(old_count>0)==ref.qpl_three
                assert np.isclose(marginal.sum(),3,atol=1e-12)
                max_choices=max(max_choices,len(choices))
                old_hit=int(old_count>0);new_hit=int(new_count>0)
                programs=g.program_no.to_numpy()
                rec={'race_key':key,'race_date':str(ref.race_date),'meet':venue,'year':year,'n':n,
                    'distance_m':int(ref.distance_m),'grade':str(ref.grade),
                    'old_hit':old_hit,'new_hit':new_hit,'old_count':old_count,'new_count':new_count,
                    'old_union':old_union,'new_union':new_union,
                    'old_expected_count':float(marginal[old_selected].sum()),
                    'new_expected_count':float(marginal[new_selected].sum()),
                    'old_brier':(old_union-old_hit)**2,'new_brier':(new_union-new_hit)**2,
                    'same_selection':set(old_selected)==set(new_selected),
                    'top_pair_included':int(old_selected[0] in new_selected)}
                for name,selected in [('old',old_selected),('new',new_selected)]:
                    rec[name+'_tickets']=';'.join(f'{programs[a]}-{programs[b]}' for a,b in pairs[selected])
                records.append(rec)
            print(f'completed {venue}/{year}',flush=True)
    result=pd.DataFrame(records)
    result.to_parquet(OUT/'race_comparison.parquet',index=False,compression='zstd')
    summary={'status':'completed','policy_count':1,'new_trained_models':0,'overall':bootstrap(result),
        'years':{str(y):bootstrap(g) for y,g in result.groupby('year')},
        'venues':{str(v):bootstrap(g) for v,g in result.groupby('meet')},
        'new_independent_test':False,'probability_model_changed':False,'production_changed':False}
    save('results.json',summary)
    save('verification.json',{'status':'passed',**verification,'baseline_races_reproduced':len(result),
        'baseline_max_error':max_old_error,'all_recommendations_literal_event_sum_checked':True,
        'maximum_candidates_per_race':max_choices,'maximum_optimization_numeric_error':max_literal_error,
        'all_source_hashes_match':True,'recalibration_or_training':False})
    inputs_check()
    print(json.dumps(summary['overall'],ensure_ascii=False,indent=2))

if __name__=='__main__':
    {'freeze':freeze,'evaluate':evaluate}[sys.argv[1]]()
