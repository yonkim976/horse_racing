"""Deduplicated augmentation of frozen full103; local retrospective research."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
OLD = R / '20261009_gate_front_late_v1'
NEW = R / '20261012_inner_front_retention_v1'

import importlib.util


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


N = module('retention_frozen', NEW / 'run.py')
G = module('gate_frozen', OLD / 'run.py')
S, T, save, sha = N.S, N.T, N.save, N.sha
BASE = json.loads((OLD / 'outputs/feature_contract.json').read_text())['full103']
GAPS = ['inner_inner_fastest_gap', 'inner_inner_mean_gap', 'inner_inner_close_n',
        'inner_same_early_mean5', 'inner_same_early_n5', 'inner_same_inner_fastest_gap',
        'inner_same_inner_early_n']
REMOVE = ['rolelate_front_g3f_adv_mean5', 'rolelate_front_g3f_adv_n5',
          'rolelate_front_g1f_adv_mean5', 'rolelate_front_g1f_adv_n5']
KEEP, INTER = N.KEEP, N.INTER
RELATIONS = [c for c in BASE if c.startswith('relate_')]
EXACT = dict(inner_early_mean3='section_early_mean3', inner_early_n5='section_early_n5',
             inner_inner_n='dirgate_inner_n', inner_inner_early_n='dirgate_inner_early_n',
             inner_inner_faster_n='dirgate_inner_faster_n', front_supported='front_prediction_supported')
COMBINED = [c for c in BASE if c not in REMOVE] + GAPS + KEEP + INTER
SWAPS = {'front_gate_probability': 'swap_front_probability'}
SWAPS.update({c: 'swap_' + c for c in RELATIONS + INTER})
CONTRACTS = dict(baseline103=BASE, gap110=BASE + GAPS, combined122=COMBINED,
                 swapped122=[SWAPS.get(c, c) for c in COMBINED])
METRICS = N.METRICS


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [HERE/'run.py', HERE/'PLAN.md', OLD/'run.py', NEW/'run.py',
             S.HERE/'run.py', S.HERE/'config.json', T.HERE/'run.py',
             ROOT/'config/prediction_model_registry.json', S.W/'research_baseline_selection.json',
             R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    for folder, names in [(OLD, ['features.parquet','feature_contract.json','race_metrics.csv','runner_predictions.parquet','verification.json']),
                          (NEW, ['features.parquet','history_events.parquet','feature_contract.json','verification.json']),
                          (S.HERE, ['history_slots.npy','history_observations.parquet'])]:
        paths += [folder/'outputs'/n for n in names]
    paths += sorted((OLD/'outputs/front_models').glob('gate_*/*'))
    paths += sorted((NEW/'outputs/front_models').glob('*/*'))
    paths += sorted((OLD/'outputs/models').glob('full103_*/*'))
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in paths if p.is_file()}
    target = OUT/'input_manifest.json'
    if target.exists():
        assert json.loads(target.read_text()) == manifest
    else:
        save(target, manifest)
    before = OUT/'publication_before.json'
    if not before.exists():
        shared = [R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before, {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
        snap = OUT/'publication_before'; snap.mkdir()
        for p in shared:
            (snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())


def check():
    for path, expected in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/path) == expected, path


def new_interactions(f, probability):
    p = probability.to_numpy(float)
    n = f.dirgate_inner_early_n.to_numpy(float)
    pressure = np.divide(f.dirgate_inner_faster_n.to_numpy(float), n,
                         out=np.full(len(f), np.nan), where=n>0)
    return pd.DataFrame(dict(combine_p_front_g3=p*f.keep_front_g3,
         combine_p_front_g1=p*f.keep_front_g1,
         combine_pressure_fast_g3=p*pressure*f.keep_fast_g3,
         combine_pressure_fast_g1=p*pressure*f.keep_fast_g1), index=f.index)[INTER]


def swapped_features(f):
    temp = f.copy()
    temp['front_gate_probability'] = temp.swap_front_probability
    relation = G.late_relations(temp)
    interaction = new_interactions(temp, temp.front_gate_probability)
    return pd.concat([relation, interaction],axis=1).add_prefix('swap_')


def build(a,b):
    assert a[S.KEY].equals(b[S.KEY])
    f = a.copy()
    duplicates = []
    for new, old in EXACT.items():
        np.testing.assert_allclose(b[new], a[old], atol=1e-12, rtol=0, equal_nan=True)
        duplicates.append(dict(new=new, existing=old, action='reuse_exact', different_rows=0))
    np.testing.assert_allclose(b.inner_gate_fraction, a.dirgate_inner_n/(a.field_size-1), atol=1e-12, rtol=0)
    duplicates.append(dict(new='inner_gate_fraction', existing='dirgate_inner_n/(field_size-1)', action='omit_deterministic',different_rows=0))
    for new,old in [('inner_front_rate5','style_role0_rate5'),('inner_front_n5','style_role_n5')]:
        diff = int((~np.isclose(b[new],a[old],equal_nan=True,atol=1e-12,rtol=0)).sum())
        duplicates.append(dict(new=new,existing=old,action='retain_existing_same_role_definition',different_rows=diff))
    duplicates.append(dict(new='front_probability',existing='front_gate_probability',action='existing_for_primary_replace_for_swap',different_rows=int((~np.isclose(a.front_gate_probability,b.front_probability,equal_nan=True,atol=1e-12,rtol=0)).sum())))
    for c in GAPS+KEEP:
        f[c] = b[c].to_numpy()
    f = pd.concat([f,new_interactions(f,f.front_gate_probability)],axis=1)
    f['swap_front_probability'] = b.front_probability.to_numpy()
    f = pd.concat([f,swapped_features(f)],axis=1)
    return f, duplicates


def prepare():
    a = pd.read_parquet(OLD/'outputs/features.parquet')
    b = pd.read_parquet(NEW/'outputs/features.parquet')
    f, duplicates = build(a,b)
    assert f[BASE].equals(a[BASE])
    assert [len(v) for v in CONTRACTS.values()] == [103,110,122,122]
    for name,cols in CONTRACTS.items():
        assert len(cols) == len(set(cols))
        assert not any(c.startswith(('aux_','outcome')) or c=='front_label' or 'jockey' in c or 'trainer' in c for c in cols)
    assert all(c not in CONTRACTS['swapped122'] for c in ['front_gate_probability']+RELATIONS+INTER)
    # Persist only identifiers, existing evaluation metadata, and needed input columns.
    cols = list(dict.fromkeys(S.KEY+['race_date','cutoff_date','year','meet','outcome','style_role_n5']+
                              sum(CONTRACTS.values(),[])))
    f[cols].to_parquet(OUT/'features.parquet', index=False)
    save(OUT/'feature_contract.json',CONTRACTS)
    save(OUT/'deduplication.json',dict(original_count=103,source_new_information_count=33,
         exact_duplicates=6,derived_omitted=1,role_history_omitted=2,probability_semantic_duplicate=1,
         original_removed=REMOVE,new_added=GAPS+KEEP+INTER,final_count=122,map=duplicates,
         primary_probability='frozen original65-input auxiliary',swap_probability='frozen new37-input auxiliary',
         replaced_front_adv_note='Four old relative-time/support inputs replaced by strict paired front G3/G1/shared count/keep rate. Absolute times and nonfront relations retained.'))
    check();print('Prepared',len(f),'inputs', {k:len(v) for k,v in CONTRACTS.items()},flush=True)


def train():
    check();f=pd.read_parquet(OUT/'features.parquet');rr=[];pp=[]
    for variant in ['gap110','combined122','swapped122']:
        for meet in [1,3]:
            one=f[f.meet==meet].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=OUT/'models'/f'{variant}_{meet}_{year}';folder.mkdir(parents=True,exist_ok=True)
                if (folder/'races.csv').exists():
                    r=pd.read_csv(folder/'races.csv');p=pd.read_parquet(folder/'runners.parquet')
                else:
                    r,p=S.fit(one,CONTRACTS[variant],year,3,variant,folder)
                    r.to_csv(folder/'races.csv',index=False);p.to_parquet(folder/'runners.parquet',index=False)
                rr.append(r);pp.append(p);print('Finish',variant,meet,year,flush=True)
    r=pd.read_csv(OLD/'outputs/race_metrics.csv');p=pd.read_parquet(OLD/'outputs/runner_predictions.parquet')
    r=r[(r.variant=='full103')&(r.target==3)].copy();p=p[(p.variant=='full103')&(p.target==3)].copy()
    r['variant']='baseline103';p['variant']='baseline103';rr.append(r);pp.append(p)
    pd.concat(rr,ignore_index=True).to_csv(OUT/'race_metrics.csv',index=False)
    pd.concat(pp,ignore_index=True).to_parquet(OUT/'runner_predictions.parquet',index=False)
    check()


def analyse():
    check();p=pd.read_parquet(OUT/'runner_predictions.parquet');r=T.add_coverage(pd.read_csv(OUT/'race_metrics.csv'),p)
    trio=[]
    for (variant,rid),g in p.groupby(['variant','race_key'],sort=False):
        g=g.sort_values('program_no');sets,_=S.support(len(g),3)
        energy=g.raw_score.to_numpy()[sets].sum(axis=1);best=np.argsort(-energy,kind='stable')[:6]
        truth=tuple(np.flatnonzero(g.outcome.between(1,3)))
        trio.append(dict(variant=variant,race_key=rid,trio6=int(any(tuple(sets[j])==truth for j in best))))
    r=r.merge(pd.DataFrame(trio),on=['variant','race_key'],validate='one_to_one');r.to_csv(OUT/'race_diagnostics.csv',index=False)
    summary=[];difference=[];gains=[]
    for variant,g in r.groupby('variant'):
        for period,z in [('all',g)]+[(str(y),g[g.year==y]) for y in [2024,2025,2026]]:
            summary.append(dict(variant=variant,period=period,n=len(z),**{m:float(z[m].mean()) for m in METRICS}))
    pd.DataFrame(summary).to_csv(OUT/'metrics.csv',index=False)
    pairs=[('gap110','baseline103'),('combined122','baseline103'),('swapped122','baseline103'),
           ('combined122','gap110'),('swapped122','combined122')]
    for variant,ref in pairs:
        for period,z in [('all',r)]+[(str(y),r[r.year==y]) for y in [2024,2025,2026]]:
            a=z[z.variant==variant];b=z[z.variant==ref]
            difference.extend(N.differences(a,b,variant,ref,period))
            a=a.set_index('race_key');b=b.set_index('race_key').reindex(a.index)
            for metric in ['axis_top3','axis_top2','quinella_one','axis_next3']:
                x=a[metric];y=b[metric]
                gains.append(dict(variant=variant,reference=ref,period=period,metric=metric,
                     new_hits=int(x.sum()),old_hits=int(y.sum()),gains=int(((x==1)&(y==0)).sum()),losses=int(((x==0)&(y==1)).sum())))
    pd.DataFrame(difference).to_csv(OUT/'paired_differences.csv',index=False)
    pd.DataFrame(gains).to_csv(OUT/'gain_loss.csv',index=False)
    check();print(pd.DataFrame(summary).query("period=='all'").to_string(index=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','train','analyse']);args=parser.parse_args()
    freeze();dict(prepare=prepare,train=train,analyse=analyse)[args.stage]()
