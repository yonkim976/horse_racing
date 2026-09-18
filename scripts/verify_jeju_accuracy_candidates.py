"""Replay annual candidates and independently check subgroup membership and labels."""
import json,pickle
from collections import defaultdict
import numpy as np
import polars as pl
from scripts.run_jeju_accuracy_candidates import ROOT,OUT,DATA,ANN,OLD,FEAT,PLAN,sha,GROWTH
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_annual_revalidation import annual_parts
from scripts.run_jeju_context_experiment import rank_scores,order_scores

SUB=ROOT/'data/research/jeju_debut_diagnosis_20260919'
def read(p):return json.loads(p.read_text())
def main():
    checked=0
    for n,h in read(OUT/'manifest.json')['files'].items():assert sha(OUT/n)==h;checked+=1
    for key,base in [('inputs',ROOT),('outputs',SUB)]:
        for n,h in read(SUB/'manifest.json')[key].items():assert sha(base/n)==h;checked+=1
    assert read(OUT/'protocol.json')['plan_sha256']==sha(PLAN)
    assert len(read(OUT/'fit_ledger.json'))==12
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    assert sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')=='f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706'
    frame,_,_=data_frame()
    frame=frame.join(pl.read_parquet(DATA/'races.parquet').filter(pl.col('target_eligible')).select('race_id'),on='race_id',how='semi').join(pl.read_parquet(FEAT/'features.parquet'),on='entry_id',validate='1:1')
    scores=pl.read_parquet(OUT/'frozen_scores.parquet');replayed=0
    for year in [2024,2025,2026]:
        parts=annual_parts(frame,year);ev=parts['evaluation'];assert ev['finish_position'].null_count()==len(ev)
        for a,b in [('fit','tune'),('tune','calibration'),('calibration','evaluation')]:assert parts[a]['event_date'].max()<parts[b]['event_date'].min()
        ob=old['order_bundle'] if year==2026 else pickle.loads((ANN/f'bundles/{year}__ORDER.pkl').read_bytes())
        order=order_scores(ob,ev)
        for name in ['BASE','PACE','NO_GROWTH']:
            if name=='BASE':bundle=old['rank_bundle'] if year==2026 else pickle.loads((ANN/f'bundles/{year}__BASE.pkl').read_bytes())
            else:bundle=pickle.loads((OUT/f'bundles/{year}__{name}.pkl').read_bytes())
            if name=='NO_GROWTH':assert not set(GROWTH)&set(bundle['features'])
            s=scores.filter((pl.col('year')==year)&(pl.col('model')==name)).sort('race_id','horse_id')
            assert s['entry_id'].to_list()==ev['entry_id'].to_list()
            np.testing.assert_allclose(rank_scores(bundle,ev),s['score'].to_numpy(),atol=1e-12,rtol=0)
            np.testing.assert_allclose(order,s['order_score'].to_numpy(),atol=1e-12,rtol=0)
            replayed+=len(s)
            if name=='BASE':
                ref=pl.read_parquet((ROOT/'data/research/jeju_steward_pace_v2_pilot_20260918' if year==2026 else ANN)/'frozen_scores.parquet').filter((pl.col('model')=='BASE') & (pl.col('event_date').dt.year()==year)).sort('race_id','horse_id')
                np.testing.assert_allclose(s['score'].to_numpy(),ref['score'].to_numpy(),atol=1e-12,rtol=0)
                np.testing.assert_allclose(s['order_score'].to_numpy(),ref['order_score'].to_numpy(),atol=1e-12,rtol=0)
    accepted=defaultdict(list)
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():accepted[r['race_id']].append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    labels={(r['race_id'],r['horse_id']):r['label_top3'] for r in pl.read_parquet(DATA/'labels.parquet').to_dicts()}
    pred=pl.read_parquet(OUT/'race_predictions.parquet').to_dicts()
    for r in pred:
        t=accepted[r['race_id']];s=set(r['predicted_set'])
        assert r['pick_hit']==bool(labels[(r['race_id'],r['pick_horse_id'])])
        assert r['set_hit']==any(s==set(x) for x in t)
        assert r['order_hit']==(tuple(r['predicted_order']) in t)
        assert r['compatible_max_overlap']==max(len(s&set(x)) for x in t)
    for s in read(OUT/'summary.json'):
        rows=[r for r in pred if r['year']==s['year'] and r['model']==s['model']]
        assert len(rows)==s['races']
        for key in ['pick_hit','set_hit','order_hit']:assert sum(r[key] for r in rows)==s[key]
    history=pl.read_parquet(DATA/'horse_states.parquet');byrace=defaultdict(list)
    for r in history.to_dicts():byrace[r['race_id']].append(r)
    meta={r['race_id']:r for r in read(SUB/'race_classification.json')}
    assert len(meta)==1920
    for rid,r in meta.items():
        g=byrace[rid];zero=sum(h['starts_pre']==0 for h in g)
        assert r['zero_history_count']==zero and r['all_zero_history']==(zero==len(g))
        assert r['history_group']==('has_zero_history' if zero else 'all_have_history')
        assert r['grade_group']==('grade6' if r['grade']=='제6등급' else 'other_grade')
    for r in pl.read_parquet(OUT/'horse_predictions.parquet').to_dicts():assert r['y']==labels[(r['race_id'],r['horse_id'])]
    for s in read(SUB/'subgroup_summary.json'):
        rows=[]
        for r in pred:
            if r['model']!=s['model'] or (s['year']!='ALL' and r['year']!=s['year']):continue
            m=meta[r['race_id']]
            if s['axis']=='cross':value=m['grade_group']+'__'+m['history_group']
            elif s['axis']=='pick_history_group':
                h=next(h for h in byrace[r['race_id']] if h['horse_id']==r['pick_horse_id']);value='zero' if h['starts_pre']==0 else 'experienced'
            else:value=m[s['axis']]
            if value==s['group']:rows.append(r)
        assert len(rows)==s['races']
        for k in ['pick_hit','set_hit','order_hit']:assert sum(r[k] for r in rows)==s[k]
    result=dict(passed=True,hashes_checked=checked,score_rows_replayed=replayed,race_predictions_label_checked=len(pred),
       classified_races=len(meta),subgroup_summaries_checked=len(read(SUB/'subgroup_summary.json')),
       time_boundaries=True,baseline_and_order_preserved=True,model_fits=12,operating_model_unchanged=True)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
