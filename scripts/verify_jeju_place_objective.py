"""Replay locked binary/calibration outputs and independent one-horse outcomes."""
import json,pickle
from collections import defaultdict
import numpy as np
import polars as pl
from scipy.special import logit
from scripts.run_jeju_place_objective import ROOT,OUT,DATA,ANN,OLD,REF,PLAN,ARMS,load_frame,base_prob,sha
from scripts.run_jeju_annual_revalidation import annual_parts
from horse_racing.analysis.jeju_zero_history_calibration import objective_gradient

def read(p):return json.loads(p.read_text())
def main():
    checked=0
    for name,h in read(OUT/'manifest.json')['files'].items():assert sha(OUT/name)==h;checked+=1
    protocol=read(OUT/'protocol.json');assert sha(PLAN)==protocol['plan_sha256']
    assert sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')==protocol['reference_sha256']=='f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706'
    assert len(read(OUT/'fit_ledger.json'))==6 and len(read(OUT/'calibration_ledger.json'))==12
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes());frame=load_frame()
    scores=pl.read_parquet(OUT/'frozen_probabilities.parquet')
    boundary=pl.read_parquet(DATA/'races.parquet').filter(pl.col('boundary_tie'))['race_id'].to_list()
    replayed=0;gradients=[]
    for year in [2024,2025,2026]:
        parts=annual_parts(frame,year);ev=parts['evaluation'];cal=parts['calibration'].filter(~pl.col('race_id').is_in(boundary))
        for a,b in [('fit','tune'),('tune','calibration'),('calibration','evaluation')]:assert parts[a]['event_date'].max()<parts[b]['event_date'].min()
        assert ev['label_top3'].null_count()==len(ev)
        bundle=pickle.loads((OUT/f'bundles/{year}__P_FORM_CAL.pkl').read_bytes());assert bundle['features']==old['rank_bundle']['features']
        base=old['rank_bundle'] if year==2026 else pickle.loads((ANN/f'bundles/{year}__BASE.pkl').read_bytes())
        saved=scores.filter(pl.col('year')==year).sort('race_id','horse_id');assert saved['entry_id'].to_list()==ev['entry_id'].to_list()
        raw={};bp={}
        for role,part in [('evaluation',ev),('calibration',cal)]:
            x=bundle['preprocessor'].transform(part);raw[role]=np.mean([m.predict(x,raw_score=True) for m in bundle['models']],axis=0);bp[role]=base_prob(base,part)
        np.testing.assert_allclose(raw['evaluation'],saved['binary_score'].to_numpy(),rtol=0,atol=1e-12)
        np.testing.assert_allclose(bp['evaluation'],saved['p_BASE'].to_numpy(),rtol=0,atol=1e-12)
        for family in ['BASE','P_FORM']:
            x={k:logit(np.clip(p,1e-8,1-1e-8)) for k,p in bp.items()} if family=='BASE' else raw
            c=bundle['calibrators'][family];z=(ev['starts_pre'].to_numpy()==0).astype(int)
            name='BASE_GLOBAL' if family=='BASE' else family
            np.testing.assert_allclose(c['global_cal'].predict(x['evaluation']),saved['p_'+name].to_numpy(),atol=1e-12,rtol=0)
            np.testing.assert_allclose(c['zero_cal'].predict(x['evaluation'],z),saved['p_'+family+'_ZERO'].to_numpy(),atol=1e-12,rtol=0)
            loss,gradient=objective_gradient(c['zero_cal'].params_,x['calibration'],(cal['starts_pre'].to_numpy()==0).astype(int),cal['label_top3'].to_numpy(),1/cal['field_size'].to_numpy())
            assert abs(loss-c['zero_cal'].objective_)<1e-12
            assert np.max(np.abs(gradient))<1e-5
            gradients.append(dict(year=year,family=family,max_gradient=float(np.max(np.abs(gradient)))))
        replayed+=len(ev)*5
    y={(r['race_id'],r['horse_id']):int(r['label_top3']) for r in pl.read_parquet(DATA/'labels.parquet').to_dicts()}
    ref={r['race_id']:r for r in pl.read_parquet(REF/'race_predictions.parquet').filter(pl.col('model')=='BASE').to_dicts()}
    previous={(r['race_id'],r['horse_id']):r['p'] for r in pl.read_parquet(REF/'horse_predictions.parquet').filter(pl.col('model')=='BASE').to_dicts()}
    hp=pl.read_parquet(OUT/'horse_predictions.parquet').to_dicts();byrace=defaultdict(list)
    for h in hp:
        assert h['y']==y[(h['race_id'],h['horse_id'])] and 0<=h['p']<=1
        if h['model']=='BASE':assert abs(h['p']-previous[(h['race_id'],h['horse_id'])])<1e-12
        byrace[(h['model'],h['race_id'])].append(h)
    races=pl.read_parquet(OUT/'race_predictions.parquet').to_dicts()
    for r in races:
        g=sorted(byrace[(r['model'],r['race_id'])],key=lambda h:(-h['p'],h['horse_id']));h=g[0]
        assert h['horse_id']==r['pick_horse_id'] and bool(h['y'])==r['pick_hit']
        assert h['zero']==r['pick_zero']
        assert r['changed_from_BASE']==(h['horse_id']!=ref[r['race_id']]['pick_horse_id'])
        assert r['outside_BASE_set']==(h['horse_id'] not in ref[r['race_id']]['predicted_set'])
    for s in read(OUT/'summary.json'):
        g=[r for r in races if r['model']==s['model'] and (s['year']=='ALL' or s['year']==r['year'])]
        assert len(g)==s['races'] and sum(r['pick_hit'] for r in g)==s['hits']
        expected=sum(r['pick_hit']-ref[r['race_id']]['pick_hit'] for r in g)
        assert expected==s['changed_wins']-s['changed_losses']
    result=dict(passed=True,hashes_checked=checked,probabilities_replayed=replayed,horse_label_rows=len(hp),race_selections_checked=len(races),
        cal_objective_gradient_checks=gradients,baseline_probabilities_identical=True,monotonic_control_choices_identical=True,
        evaluation_excluded_from_fit_tune_cal=True,operating_model_unchanged=True)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
