"""Immutable inputs and bounded feature contracts for the training-state study."""
from pathlib import Path
from datetime import datetime, timezone
import sys, json
import torch  # Select the same OpenMP runtime as the referenced baseline.
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; R=HERE.parent; OUT=HERE/'outputs'
PREV=R/'20261022_dynamic_race_model_v1'
sys.path.insert(0,str(PREV))
import common as old
CORE=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
PREVIOUS_BYTES=162_395_776
BASIC=['train_days7','train_days14','train_days28','train_minutes7','train_minutes14','train_minutes28',
       'train_minutes_per_day14','train_gap_days28','train_qa_days28','train_coverage28']
PERSONAL_SOURCE=['train_days14','train_minutes14','train_minutes_per_day14','train_days28','train_minutes28','train_gap_days28']
PERSONAL=[x+'_delta_self3' for x in PERSONAL_SOURCE]+['train_self_history_n','train_minutes14_self_sd3']
VARIANTS={'quantity_t2':(2,BASIC),'personal_t2':(2,BASIC+PERSONAL),'personal_t7':(7,BASIC+PERSONAL)}
KEY=old.KEY
def sha(p):return old.sha(p)
def save(path,value):
    path=Path(path);assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def storage():
    n=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert PREVIOUS_BYTES+n<300_000_000
    return n
def frame(lag):
    f=old.frame();d=pd.read_parquet(OUT/f'feature_delta_t{lag}.parquet')
    assert np.array_equal(f.row_number,d.row_number)
    return pd.concat([f,d[BASIC+PERSONAL]],axis=1)
def freeze():
    assert not (OUT/'input_manifest.json').exists()
    paths=[HERE/'PLAN.md',*sorted(HERE.glob('*.py')),CORE,old.DB,old.HISTORY,
        old.base.SOURCE/'features.parquet',old.base.SOURCE/'feature_contract.json',old.base.ABILITY/'research_baseline_selection.json',
        old.BASE/'config.json',old.BASE/'run.py',old.BASE/'probability.py',old.BASE/'evaluate.py',
        old.BASE/'outputs/population_flags.parquet',PREV/'common.py',PREV/'outputs/state_features.parquet',PREV/'outputs/state_contract.json',
        PREV/'outputs/race_metrics.parquet',PREV/'outputs/runner_probabilities.parquet',PREV/'outputs/tickets.parquet',
        ROOT/'config/prediction_model_registry.json']
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            p=PREV/'outputs/models'/f'state_gbm_{meet}_{year}'
            paths += [p/'model.txt',p/'metadata.json',p/'scores.parquet']
    save(OUT/'input_manifest.json',{str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths})
    names=['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']
    save(OUT/'preexisting_files.json',{str((R/n).relative_to(ROOT)):{'sha256':sha(R/n),'bytes':(R/n).stat().st_size} for n in names})
    save(OUT/'protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'main_variant':'personal_t2',
        'variants':{k:{'lag':v[0],'features':old.features()['state_gbm']+v[1]} for k,v in VARIANTS.items()},
        'evaluation_started':False,'initial_fits':18,'final_models':18,'historical_availability_certified':False})
def check():
    for name,entry in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/name)==entry['sha256'],name
if __name__=='__main__':freeze()
