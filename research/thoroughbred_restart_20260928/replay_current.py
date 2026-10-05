"""Read-only registered-model replay fixture. No model fitting or publication."""
from pathlib import Path
import json,sys,hashlib,argparse
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
V3=ROOT/'data/research/thoroughbred_three_targets_20260918_v3'
V4=ROOT/'data/research/thoroughbred_followup_20260918_v4/model'
V6=ROOT/'data/research/thoroughbred_boundary_20260918_v6'
sys.path.insert(0,str(V3/'code'))
import targets_core as tc

def main():
    phase=argparse.ArgumentParser();phase.add_argument('phase',choices=['before','after']);args=phase.parse_args()
    registry=json.loads((ROOT/'config/prediction_model_registry.json').read_text());active=registry['domains']['thoroughbred']['active_profile'];profile=registry['profiles'][active]
    def model_path(key):return ROOT/profile['artifacts'][key]['path']
    a=tc.load_bundle(model_path('A_model').parent);b=tc.load_bundle(model_path('BC_model').parent);w=tc.load_v2_win_bundle(model_path('WIN_ORDER_model').parent)
    if args.phase=='before':
        frame=pd.read_parquet(V3/'prediction_input/future_20260919_20_context.parquet');extra=pd.read_parquet(V4/'future_predictions_20260919_20/prepared_v4_features.parquet');keys=['race_id','hr_no','race_date']
        frame['race_date']=pd.to_datetime(frame.race_date);extra['race_date']=pd.to_datetime(extra.race_date)
        frame=frame.merge(extra[keys+[x for x in extra if x.startswith('research_v4_')]],on=keys,validate='one_to_one').sort_values(keys[:1]+['chul_no','hr_no']).reset_index(drop=True)
        frame.to_parquet(OUT/'retained_replay_input.parquet',index=False)
    else:frame=pd.read_parquet(OUT/'retained_replay_input.parquet')
    assert len(frame)==294 and frame.race_id.nunique()==27
    scores={'A':tc.raw_scores(a,frame)['top3'],'BC':tc.raw_scores(b,frame)['top3'],'order':tc.raw_scores(w,frame)['win']}
    at=a.metadata['temperature_by_target_and_venue'];bt=b.metadata['temperature_by_target_and_venue'];wt=w.metadata['temperature_by_venue']
    ar=[];jr=[];errors=[]
    for rid,idx in frame.groupby('race_id',sort=False).indices.items():
        card=frame.iloc[idx];venue=card.venue_code.iloc[0];horses=card.hr_no.astype(str).to_numpy()
        for target in 'ABC':
            ts=(at if target=='A' else bt)[target];joint=tc.top3_set_joint(scores['A' if target=='A' else 'BC'][idx],scores['order'][idx],ts.get(venue,ts['GLOBAL']),wt.get(venue,1.))
            errors.extend(tc.probability_invariants(joint).values())
            if target=='A':
                ar.extend({'race_id':rid,'hr_no':h,'probability':float(joint.inclusion_probability[i])} for i,h in enumerate(horses))
            else:
                prob=joint.set_probability if target=='B' else joint.order_probability;support=joint.sets if target=='B' else joint.orders
                for rank,i in enumerate(np.argsort(-prob,kind='stable')[:10],1):jr.append({'race_id':rid,'target':target,'prediction_rank':rank,'key':json.dumps(horses[support[i]].tolist()),'probability':float(prob[i])})
    ap=pd.DataFrame(ar);jp=pd.DataFrame(jr)
    olda=pd.read_parquet(V6/'future_predictions_20260919_20/A_predictions.parquet');oldj=pd.read_parquet(V6/'future_predictions_20260919_20/B_C_top10_predictions.parquet')
    ax=ap.merge(olda[['race_id','hr_no','A_slot_inclusion_probability']],on=['race_id','hr_no'],validate='one_to_one');jx=jp.merge(oldj[['race_id','target','prediction_rank','predicted_key','predicted_probability']],on=['race_id','target','prediction_rank'],validate='one_to_one')
    assert len(ax)==294 and len(jx)==540
    assert all(json.loads(x)==json.loads(y) for x,y in zip(jx.key,jx.predicted_key))
    da=float(abs(ax.probability-ax.A_slot_inclusion_probability).max());dj=float(abs(jx.probability-jx.predicted_probability).max())
    assert max(da,dj,*errors)<1e-10
    if args.phase=='before':
        np.savez(OUT/'retained_raw_scores.npz',**scores);ap.to_parquet(OUT/'retained_A_predictions.parquet',index=False);jp.to_parquet(OUT/'retained_BC_predictions.parquet',index=False)
    else:
        prior=np.load(OUT/'retained_raw_scores.npz');assert all(np.array_equal(prior[k],v) for k,v in scores.items())
        pd.testing.assert_frame_equal(ap,pd.read_parquet(OUT/'retained_A_predictions.parquet'),check_exact=True)
        pd.testing.assert_frame_equal(jp,pd.read_parquet(OUT/'retained_BC_predictions.parquet'),check_exact=True)
    result={'passed':True,'phase':args.phase,'active_profile':active,'races':27,'runners':294,'BC_top10_rows':540,'max_A_error_vs_saved':da,'max_BC_error_vs_saved':dj,'max_probability_invariant_error':max(errors),'before_after_exact_equal':args.phase=='after','registry_sha256':hashlib.sha256((ROOT/'config/prediction_model_registry.json').read_bytes()).hexdigest(),'DB_writes':0,'training':False}
    (OUT/f'replay_{args.phase}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
