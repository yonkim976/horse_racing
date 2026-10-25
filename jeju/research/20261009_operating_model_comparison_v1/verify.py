"""Independently replay legacy probabilities with the original hybrid routine."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import json
import hashlib
import numpy as np
import pandas as pd
from horse_racing.analysis.jeju_hybrid_evaluation import distribution

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
legacy = pd.read_parquet(ROOT/'data/research/jeju_native_transition_holdout_v13_20260916/horse_predictions.parquet')
legacy = legacy[legacy.model.eq('HY_R_FORM')]
race_map = pd.read_parquet(ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2/races.parquet').set_index('race_id')
legacy['key'] = [f'{d}_2_{int(race_map.loc[r,"event_number"])}' for d,r in zip(legacy.event_date,legacy.race_id)]
pred = pd.read_parquet(OUT/'runner_predictions.parquet')
tickets = pd.read_csv(OUT/'six_combinations.csv')
entries = pd.read_parquet(ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2/entries.parquet').set_index('entry_id')
common = set(pred.race_id)
for key, g in legacy[legacy.key.isin(common)].groupby('key'):
    g = g.sort_values('horse_id',kind='stable')
    sets, _, logs, _, p = distribution(g.score.to_numpy(),g.order_score.to_numpy(),float(g.beta.iloc[0]),float(g.beta_order.iloc[0]))
    saved = pred[pred.race_id.eq(key)&pred.variant.eq('HY_R_FORM')].set_index('horse_id').loc[g.horse_id]
    assert np.allclose(p,saved.p_top3,atol=1e-12,rtol=0)
    best = np.argsort(-logs,kind='stable')[:6]
    actual = tickets[tickets.race_id.eq(key)&tickets.variant.eq('HY_R_FORM')].sort_values('selection_rank')
    assert np.allclose(np.exp(logs[best]),actual.probability,atol=1e-12,rtol=0)
    numbers = entries.loc[g.entry_id,'horse_number'].to_numpy(int)
    expected = [','.join(map(str,sorted(numbers[sets[j]]))) for j in best]
    assert expected == actual.numbers.tolist()
for _, t in tickets.groupby(['race_id','variant']):
    assert len(t)<=6 and not t.numbers.duplicated().any()
    assert t.probability.between(0,1).all() and t.probability.sum()<=1+1e-12
lock = json.loads((OUT/'source_lock.json').read_text())
for path, info in lock.items():
    h=hashlib.sha256()
    with (ROOT/path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    assert h.hexdigest()==info['sha256'],path
result = dict(passed=True,independent_original_hybrid_replay_races=len(common),
              compared_runner_probabilities=int(len(pred)//3),all_six_ticket_probabilities_and_sets_match=True,
              sources_and_database_registry_model_unchanged=True,
              reference_code='src/horse_racing/analysis/jeju_hybrid_evaluation.py',
              reference_sha256=hashlib.sha256((ROOT/'src/horse_racing/analysis/jeju_hybrid_evaluation.py').read_bytes()).hexdigest())
(OUT/'independent_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
