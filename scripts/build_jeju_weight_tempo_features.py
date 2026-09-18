import json,hashlib
from pathlib import Path
import polars as pl
from horse_racing.analysis.jeju_weight_tempo_features import build
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_weight_tempo_features_20260917'
def main():
    OUT.mkdir(exist_ok=False)
    source=ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet'
    features,lineage,obs=build(pl.read_parquet(source).to_dicts())
    for name,rows in [('features',features),('lineage',lineage),('observations',obs)]:
        pl.from_dicts(rows,infer_schema_length=None).write_parquet(OUT/(name+'.parquet'))
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(dict(files={p.name:sha(p) for p in OUT.iterdir()},
      parents={str(source):sha(source)},code={str(ROOT/'src/horse_racing/analysis/jeju_weight_tempo_features.py'):sha(ROOT/'src/horse_racing/analysis/jeju_weight_tempo_features.py')}),indent=2))
    print('built',len(features),flush=True)
if __name__=='__main__':main()
