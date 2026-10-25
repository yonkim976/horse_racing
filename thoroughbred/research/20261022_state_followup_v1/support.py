"""Bounded, read-only reuse of the completed dynamic-state experiment."""
from pathlib import Path
from datetime import datetime,timezone
import importlib.util,json,sys,hashlib
import torch
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2];R=HERE.parent;OUT=HERE/'outputs'
PREV=R/'20261022_dynamic_race_model_v1'
sys.path.insert(0,str(PREV))
import common as old
import state as oldstate
spec=importlib.util.spec_from_file_location('state_prior_analysis',PREV/'analyze.py')
oldanalysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(oldanalysis)
base=old.base;prob=old.prob;scorer=old.scorer;KEY=old.KEY

def sha(path):return old.sha(path)
def save(path,value):
    path=Path(path);assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

RANK=['state_rank_mean','state_rank_sd','state_distance_slope','state_distance_sd','state_rank_current',
      'state_rank_current_sd','state_rank_n','state_rank_current_field_gap','state_rank_current_field_rank']
SIMPLE=['simple_last','simple_mean3','simple_mean5','simple_std5','simple_mean_all','simple_count_all',
        'simple_count5','simple_mean_all_field_gap','simple_mean_all_field_rank']

def contracts():
    full=old.features()['state_gbm'];oldcols=base.contracts()['additive89']
    return {'rank_only':oldcols+RANK,'no_rank':[x for x in full if x not in RANK],'simple_rank':oldcols+SIMPLE}

def frame():
    f=old.frame();s=pd.read_parquet(OUT/'simple_features.parquet')
    assert (s.row_number.to_numpy()==f.row_number.to_numpy()).all()
    return pd.concat([f,s.drop(columns='row_number')],axis=1)

def freeze():
    paths=[HERE/'PLAN.md',*sorted(HERE.glob('*.py')),old.DB,old.HISTORY,
        PREV/'PLAN.md',
        PREV/'outputs/state_features.parquet',PREV/'outputs/state_contract.json',
        PREV/'outputs/race_metrics.parquet',PREV/'outputs/tickets.parquet',
        old.BASE/'outputs/race_metrics.parquet',old.BASE/'outputs/population_flags.parquet',
        base.SOURCE/'features.parquet',base.SOURCE/'feature_contract.json',
        base.ABILITY/'research_baseline_selection.json',old.BASE/'config.json',
        old.BASE/'run.py',old.BASE/'probability.py',old.BASE/'evaluate.py',
        PREV/'common.py',PREV/'state.py',PREV/'train_models.py',PREV/'joint.py',PREV/'analyze.py',
        ROOT/'config/prediction_model_registry.json']
    for p in (PREV/'outputs/models').glob('state_gbm_*'):
        paths += [p/'metadata.json',p/'scores.parquet',p/'model.txt']
    manifest={str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths}
    p=OUT/'input_manifest.json'
    if p.exists():assert json.loads(p.read_text())==manifest
    else:save(p,manifest)
    save(OUT/'protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'evaluation_started':False,'model_variants':list(contracts()),'calibrator_family_count':1})
    save(OUT/'feature_contract.json',contracts())

def check():
    for name,v in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/name)==v['sha256'],name

def storage():
    total=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert total+103_392_015<300_000_000
    return total
