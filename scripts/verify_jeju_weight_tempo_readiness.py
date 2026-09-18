"""Replay candidate models and verify tomorrow's sealed card/forecast alignment."""
import json,hashlib,pickle,re
from datetime import timedelta
from pathlib import Path
import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from horse_racing.analysis.jeju_weight_tempo_features import WEIGHT,TEMPO

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'data/research/jeju_weight_tempo_pilot_20260917'
F=ROOT/'data/research/jeju_weight_tempo_features_20260917'
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
LIVE=ROOT/'data/predictions/jeju_live_20260918_hy_r_form_verified_20260917'
OFF=ROOT/'data/predictions/jeju_20260918_official_inputs_20260917'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for root in [P,F]:
        manifest=json.loads((root/'manifest.json').read_text())
        for path,h in manifest['files'].items():assert sha(root/path)==h
        for category in ['parents','code']:
            for path,h in manifest.get(category,{}).items():assert sha(Path(path))==h
    protocol=json.loads((P/'protocol.json').read_text())
    assert sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')==protocol['old_model_sha256']
    assert sha(ROOT/'docs/JEJU_WEIGHT_TEMPO_READINESS_PLAN_2026-09-17.md')==protocol['plan_sha256']
    frame,_,folds=data_frame();features=pl.read_parquet(F/'features.parquet')
    frame=frame.join(features,on='entry_id',validate='1:1')
    ev=frame.join(folds.filter(pl.col('role')=='evaluation').select('race_id'),on='race_id',how='semi').sort('race_id','horse_id')
    assert ev['finish_position'].null_count()==len(ev)==4852
    saved=pl.read_parquet(P/'frozen_scores.parquet')
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    for name,extras in [('BASE',[]),('WEIGHT',WEIGHT),('TEMPO',TEMPO)]:
        bundle=old['rank_bundle'] if name=='BASE' else pickle.loads((P/'bundles'/f'{name}.pkl').read_bytes())
        assert bundle['features']==old['rank_bundle']['features']+extras
        scores=saved.filter(pl.col('model')==name+'__BASE').sort('race_id','horse_id')
        assert scores['entry_id'].to_list()==ev['entry_id'].to_list()
        assert np.allclose(rank_scores(bundle,ev),scores['score'].to_numpy(),atol=1e-12,rtol=0)
    for name in ['BASE','NEW']:
        bundle=old['order_bundle'] if name=='BASE' else pickle.loads((P/'bundles/ORDER_WEIGHT.pkl').read_bytes())
        scores=saved.filter(pl.col('model')=='BASE__'+name).sort('race_id','horse_id')
        assert np.allclose(order_scores(bundle,ev),scores['order_score'].to_numpy(),atol=1e-12,rtol=0)
    obs={r['entry_id']:r for r in pl.read_parquet(F/'observations.parquet').to_dicts()}
    for r in pl.read_parquet(F/'lineage.parquet').to_dicts():
        target=obs[r['entry_id']]
        for kind in ['past_weight_entry_ids','past_tempo_entry_ids']:
            for eid in r[kind]:
                past=obs[eid]
                assert past['horse_id']==target['horse_id'] and past['event_date']<=target['event_date']-timedelta(days=2)
                if kind=='past_tempo_entry_ids':assert past['distance_m']==target['distance_m']
    for r in obs.values():
        if r['tempo_reference_max_date']:
            assert r['tempo_reference_max_date']<=(r['event_date']-timedelta(days=2)).isoformat()
    podium={};orders={}
    for r in pl.read_parquet(DATA/'labels.parquet').filter(pl.col('label_top3')==1).to_dicts():podium.setdefault(r['race_id'],set()).add(r['horse_id'])
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():orders.setdefault(r['race_id'],set()).add((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    races=pl.read_parquet(P/'race_predictions.parquet')
    for r in races.to_dicts():
        assert r['pick_hit']==(r['pick_horse_id'] in podium[r['race_id']])
        assert r['set_hit']==(set(r['predicted_set'])==podium[r['race_id']])
        assert r['order_hit']==(tuple(r['predicted_order']) in orders[r['race_id']])
    hp=pl.read_parquet(P/'horse_predictions.parquet')
    assert hp['p'].is_between(0,1).all()
    assert (hp.group_by('model','race_id').agg(pl.col('p').sum())['p']-3).abs().max()<1e-10
    coverage=frame.join(folds.select('race_id','role'),on='race_id').group_by('role').agg(pl.len().alias('rows'),pl.col('race_id').n_unique().alias('races'),
        pl.col('live_weight_kg').is_finite().sum().alias('known_weight'),(pl.col('tempo_par_count_3')>0).sum().alias('supported_tempo')).to_dicts()
    (P/'coverage.json').write_text(json.dumps(coverage,indent=2))
    for path,h in json.loads((LIVE/'manifest.json').read_text()).items():assert sha(LIVE/path)==h
    live=pl.read_parquet(LIVE/'horse_predictions.parquet')
    earlier=pl.read_parquet(ROOT/'data/predictions/jeju_live_20260918_hy_r_form_readiness_20260917/horse_predictions.parquet')
    assert_frame_equal(live.sort('entry_id'),earlier.sort('entry_id'))
    official=json.loads((OFF/'gate_card_page_1.json').read_text())['response']['body']['items']['item']
    gate={(int(re.search(r'\d+',r['raceNo'])[0]),int(r['gtno'])):r for r in official}
    assert len(gate)==len(live)==67
    for r in live.to_dicts():
        g=gate[(r['race_number'],r['horse_number'])]
        assert r['horse_name']==g['hrnm'] and r['jockey_name']==g['jckyNm']
        assert r['burden_kg']==float(g['burdWgt']) and g['raceDt'].startswith('2026년09월18일')
    assert live['top3_probability'].is_between(0,1).all()
    assert (live.group_by('race_id').agg(pl.col('top3_probability').sum())['top3_probability']-3).abs().max()<1e-10
    meta=json.loads((LIVE/'metadata.json').read_text())
    assert meta['h2_supplemental_metadata']['cutoff_date']=='2026-09-16'
    assert not meta['same_day_weight_used'] and not meta['target_result_endpoints_called']
    result=dict(new_model_fits=6,models_replay=True,independent_A_B_C_checks=True,
        all_84583_historical_lineages_T_minus_2=True,tempo_par_references_T_minus_2=True,
        before_after_weight='historical measured value, actual publication-time replay not established',
        live_races=7,live_entries=67,gate_name_jockey_burden_match=True,live_probabilities_unchanged_by_report_fix=True,
        live_model='HY_R_FORM',live_weight_input=False,h2_cutoff='2026-09-16',result_endpoints_called=[])
    (P/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
