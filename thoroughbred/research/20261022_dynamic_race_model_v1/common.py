"""Local research paths and immutable comparison contracts."""
from pathlib import Path
import json, hashlib, sys
from datetime import datetime, timezone
# Load Torch's OpenMP runtime before LightGBM on this macOS host.
import torch
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESEARCH = HERE.parent
OUT = HERE / 'outputs'
BASE = RESEARCH / '20261022_probability_comparison_v1'
HISTORY = RESEARCH / '20261009_section_style_finish_v1/outputs/history_observations.parquet'
DB = ROOT / 'thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb'
sys.path.insert(0, str(BASE))
import run as base
import probability as prob
import evaluate as scorer
KEY = base.KEY

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''):h.update(b)
    return h.hexdigest()

def save(p,v):
    p=Path(p)
    assert p.resolve().is_relative_to(HERE),p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def freeze():
    paths=[HERE/'PLAN.md',*sorted(HERE.glob('*.py')),HISTORY,DB,
           base.SOURCE/'features.parquet',base.SOURCE/'feature_contract.json',
           base.ABILITY/'research_baseline_selection.json',BASE/'config.json',
           BASE/'run.py',BASE/'probability.py',BASE/'evaluate.py',
           BASE/'outputs/race_metrics.parquet',BASE/'outputs/population_flags.parquet',
           ROOT/'config/prediction_model_registry.json']
    data={str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths}
    target=OUT/'input_manifest.json'
    if target.exists():assert json.loads(target.read_text())==data
    else:save(target,data)
    save(OUT/'protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'evaluation_started':False,'variants':['strong89','state_gbm','state_joint']})

def check_inputs():
    for name,v in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/name)==v['sha256'],name

def frame():
    f=base.load_frame()
    s=pd.read_parquet(OUT/'state_features.parquet')
    assert (s.row_number.to_numpy()==f.row_number.to_numpy()).all()
    return pd.concat([f,s.drop(columns='row_number')],axis=1)

def features():
    state=json.loads((OUT/'state_contract.json').read_text())['features']
    old=base.contracts()['additive89']
    return {'strong89':old,'state_gbm':old+state,'state_joint':old+state}

def storage_check():
    total=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert total+53_756_748<300_000_000,total
    return total
