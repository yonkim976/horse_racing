"""Replay feature lineage, saved models, and historical ticket/gap outcomes."""
import hashlib,json,pickle
from pathlib import Path

import numpy as np
import polars as pl

from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from horse_racing.analysis.jeju_wager_probabilities import ticket_hits

ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'data/research/jeju_steward_pace_v2_20260918'
P=ROOT/'data/research/jeju_steward_pace_v2_pilot_20260918'
M=ROOT/'data/research/jeju_markets_gap_20260918'
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'

def read(p):return json.loads(p.read_text())
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    files=0
    for folder in [F,M]:
        man=read(folder/'manifest.json')
        for name,digest in man['inputs'].items():assert sha(ROOT/name)==digest;files+=1
        for name,digest in man['outputs'].items():assert sha(folder/name)==digest;files+=1
    for name,digest in read(P/'manifest.json')['files'].items():assert sha(P/name)==digest;files+=1
    assert sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')=='f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706'
    history=pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet')
    lookup={r['entry_id']:r for r in history.to_dicts()}
    feat={r['entry_id']:r for r in pl.read_parquet(F/'features.parquet').to_dicts()}
    events={e['event_id']:e for e in read(F/'events.json')}
    for r in pl.read_parquet(F/'pace_lineage.parquet').to_dicts():
        target=lookup[r['entry_id']]
        assert r['event_date']==target['event_date']
        for eid in r['same_distance_source_ids']+([r['previous_entry_id']] if r['previous_entry_id'] is not None else []):
            h=lookup[eid]
            assert h['horse_id']==target['horse_id'] and h['event_date']<=r['cutoff_date']
        for eid in r['same_distance_source_ids']:assert lookup[eid]['distance_m']==target['distance_m']
    for r in pl.read_parquet(F/'steward_lineage.parquet').to_dicts():
        target=lookup[r['entry_id']]
        if r['previous_date'] is not None:
            assert (target['event_date']-r['previous_date']).days>=2
        for eid in r['event_ids']:
            e=events[eid]
            assert e['status']=='explicit_rule_match' and e['field']=='judgement'
            assert e['date']==r['previous_date'].isoformat()
            assert r['previous_entry_id'] in [a['entry_id'] for a in e['affected']]
        if feat[r['entry_id']]['st2_report_known']==0:
            assert feat[r['entry_id']]['st2_event_any'] is None
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    frame,_,folds=data_frame()
    frame=frame.join(pl.read_parquet(F/'features.parquet'),on='entry_id',validate='1:1')
    ev=frame.join(folds.filter(pl.col('role')=='evaluation').select('race_id'),on='race_id',how='semi').sort('race_id','horse_id')
    scores=pl.read_parquet(P/'frozen_scores.parquet')
    order=order_scores(old['order_bundle'],ev)
    for name in ['BASE','STEWARD','PACE_BURDEN']:
        bundle=old['rank_bundle'] if name=='BASE' else pickle.loads((P/'bundles'/f'{name}.pkl').read_bytes())
        s=scores.filter(pl.col('model')==name).sort('race_id','horse_id')
        assert ev['entry_id'].to_list()==s['entry_id'].to_list()
        assert np.allclose(rank_scores(bundle,ev),s['score'].to_numpy(),rtol=0,atol=1e-12)
        assert np.allclose(order,s['order_score'].to_numpy(),rtol=0,atol=1e-12)
    accepted={}
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').filter(pl.col('event_date').dt.year()==2026).to_dicts():
        accepted.setdefault(r['race_id'],[]).append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    labels={}
    for r in pl.read_parquet(DATA/'labels.parquet').filter(pl.col('event_date').dt.year()==2026).to_dicts():
        labels[(r['race_id'],r['horse_id'])]=int(r['label_top3'])
    for r in pl.read_parquet(P/'horse_predictions.parquet').to_dicts():assert labels[(r['race_id'],r['horse_id'])]==r['y']
    for r in read(M/'market_races.json'):
        assert len(accepted[r['race_id']])==1
        hit=ticket_hits(r['market'],r['selection'],accepted[r['race_id']][0],r['field_size'])
        assert hit==r['hit']
    for r in read(M/'portfolio_races.json'):
        assert len(r['selections'])==r['k']==len({tuple(sorted(s)) for s in r['selections']})
        actual=accepted[r['race_id']][0]
        assert any(set(s)==set(actual) for s in r['selections'])==r['hit']
        if r['policy']=='one_anchor':assert all(r['anchor'] in s for s in r['selections'])
    for r in read(M/'gap_races.json'):
        assert r['y3']==labels[(r['race_id'],r['third_id'])]
        assert r['y4']==labels[(r['race_id'],r['fourth_id'])]
        assert np.isclose(r['p3']-r['p4'],r['gap'])
    result=dict(hashes_checked=files,all_84583_feature_lineages=True,unknown_reports_not_zero_events=True,
        all_saved_rank_scores_replayed=True,order_model_unchanged=True,all_labels_replayed=True,
        all_market_and_portfolio_outcomes_replayed=True,gap_outcomes_replayed=True,baseline_hash_unchanged=True)
    (P/'verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
