"""Fixed local paths and safe serialization for the phase-prediction study."""
from pathlib import Path
import hashlib
import json
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
DISTANCES = [800,900,1000,1110,1200,1300,1400,1610]
POINTS = ['s1f','c3','c4','g1f']
EVENTS = ['middle_advance','late_advance','last200_recovery','front_fade']
TASKS = POINTS + EVENTS
SNAPSHOT = ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
DB = ROOT/'jeju/data/jeju_native_core.sqlite3'
PARSER = ROOT/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def save(path,value):
    def cast(x):
        if isinstance(x,np.integer):return int(x)
        if isinstance(x,np.floating):return float(x)
        if isinstance(x,np.bool_):return bool(x)
        raise TypeError(type(x))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=cast)+'\n')

def manifest(paths):
    return [{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in paths]

def check_manifest(rows):
    for r in rows:
        p=(ROOT/r['path']).resolve()
        assert p.is_relative_to(ROOT) and sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],p
