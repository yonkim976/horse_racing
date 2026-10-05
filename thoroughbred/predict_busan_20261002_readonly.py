"""Read-only current card adapter, gated by frozen prepared-card feature parity."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, re, sqlite3, sys, importlib.util
import duckdb, numpy as np, pandas as pd

ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'data/research'
V2=R/'thoroughbred_win_research_20260918_v2'
V3=R/'thoroughbred_three_targets_20260918_v3'
V4=R/'thoroughbred_followup_20260918_v4/model'
V5=R/'thoroughbred_offline_20260918_v5'
SOURCE=R/'thoroughbred_unified_20260918/thoroughbred_unified.duckdb'
sys.path[:0]=[str(V2/'code'),str(V3/'code'),str(V4/'code')]
import shadow, features_v2, context_features, targets_core as tc
from run_v4_model import strict_features, NEW
from infer_targets import validate_frame

def read(p): return duckdb.connect().execute('select * from read_parquet(?) order by race_date,race_id,chul_no,hr_no',[str(p)]).fetchdf()
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def refresh_current(cards,hist,ctx,trials,historical,out):
    """Append confirmed operational results after the frozen source's last day."""
    c=sqlite3.connect('file:'+str(ROOT/'data/horse_racing.sqlite3')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    newer=[dict(x) for x in c.execute('''SELECT rc.kra_meet_code,r.race_date_local,r.race_number,r.distance_m,r.grade,r.track_condition,r.field_size,e.horse_number,h.kra_horse_id,e.carried_weight_kg,e.rating,e.body_weight_kg,j.kra_jockey_id,rr.finish_position,rr.finish_time_ms,rr.disqualified,e.scratched FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id LEFT JOIN jockeys j ON j.id=e.jockey_id LEFT JOIN race_results rr ON rr.race_entry_id=e.id WHERE r.race_date_local>? AND r.race_date_local<? AND r.status='completed' AND rc.kra_meet_code IN (1,3,4) ORDER BY r.race_date_local,r.race_number,e.horse_number''',(max(x['race_date'] for x in hist),'2026-10-02'))]
    newhist=[]
    for x in newer:
        v={1:'SEOUL',3:'BUSAN',4:'YEONGCHEON'}[x['kra_meet_code']];rank=x['finish_position'];valid=rank is not None and 0<rank<=x['field_size'] and not x['disqualified'] and not x['scratched']
        status='scratched' if x['scratched'] else 'disqualified' if x['disqualified'] else 'finished' if valid else 'did_not_finish'
        newhist.append(dict(race_id=f"RACE:{v}:{x['race_date_local'].replace('-','')}:{x['race_number']:02}",race_date=x['race_date_local'],race_no=x['race_number'],hr_no=str(x['kra_horse_id']),venue_code=v,distance_m=x['distance_m'],finish_order=rank if valid else None,result_status=status,is_rank_label=bool(valid),race_time_s=x['finish_time_ms']/1000 if x['finish_time_ms'] is not None else None,track_raw=x['track_condition'],chul_no=x['horse_number'],burden_weight_kg=x['carried_weight_kg'],rating_raw=x['rating'],race_class=x['grade'],field_size_full_card=x['field_size'],jockey_no=str(x['kra_jockey_id']) if x['kra_jockey_id'] else None,horse_weight_kg=x['body_weight_kg']))
    sizes=pd.DataFrame(newhist).groupby('race_id').size().to_dict()
    # Operational field_size is final starters; the frozen contract counts the full card.
    for x in newhist:x['field_size_full_card']=sizes[x['race_id']]
    fullhist=hist+newhist
    base=shadow._base38(newhist+cards,fullhist)
    v2=pd.DataFrame(features_v2.derive_features(fullhist,base))
    elo=v2.set_index(['race_id','hr_no']).research_elo_global.to_dict()
    newctx=[dict(x,baseline_elo=elo[(x['race_id'],x['hr_no'])],s1f_position=None) for x in newhist]
    # Unknown new S1F positions remain missing under the original verified-source contract.
    ctxrows=ctx.to_dict('records')+newctx
    extra_trials=[dict(x) for x in c.execute('''SELECT rt.id trial_id,rt.trial_date_local,rt.distance_m,h.kra_horse_id,rr.finish_time_ms FROM running_trials rt JOIN running_trial_results rr ON rr.running_trial_id=rt.id JOIN horses h ON h.id=rr.horse_id WHERE rt.meet_code IN (1,3,4) AND rt.trial_date_local>? AND rt.trial_date_local<? ORDER BY rt.trial_date_local,rt.id,rr.horse_number''',(str(trials.trial_date.max())[:10],'2026-10-02'))]
    c.close()
    dump(out/'history_append.json',dict(results=newhist,trials=extra_trials))
    trialrows=trials.to_dict('records')+[dict(trial_event_id='OPTRIAL:'+str(x['trial_id']),trial_date=x['trial_date_local'],hr_no=str(x['kra_horse_id']),distance_m=x['distance_m'],finish_time_ms=x['finish_time_ms']) for x in extra_trials]
    ctxfeatures=pd.DataFrame(context_features.derive_context_features(ctxrows,v2,trialrows))[['race_id','hr_no']+context_features.ALL_FEATURES]
    v2=v2.drop(columns=[x for x in context_features.ALL_FEATURES if x in v2]).merge(ctxfeatures,on=['race_id','hr_no'],validate='one_to_one')
    additions={col:np.nan for col in historical if col not in v2}
    v2=pd.concat([v2,pd.DataFrame(additions,index=v2.index)],axis=1).copy()
    v2['target_finish_order']=v2['finish_order'];v2['target_is_rank_label']=v2['is_rank_label'].fillna(False).astype(bool)
    combo=pd.concat([historical,v2[historical.columns]],ignore_index=True);combo['race_date']=pd.to_datetime(combo.race_date)
    strict=strict_features(combo)
    current=v2[v2.race_id.isin([x['race_id'] for x in cards])].copy()
    current=current.drop(columns=[x for x in NEW if x in current]).merge(strict[strict.race_id.isin(current.race_id)][['race_id','hr_no']+NEW],on=['race_id','hr_no'],validate='one_to_one')
    dump(out/'history_refresh.json',dict(frozen_history_max_date=max(x['race_date'] for x in hist),appended_result_rows=len(newhist),appended_races=len(sizes),history_max_date=max(x['race_date'] for x in fullhist),appended_trial_rows=len(extra_trials),trial_max_date=max(str(x['trial_date'])[:10] for x in trialrows),new_s1f_positions='missing; not verified against frozen source semantic contract',operational_db='data/horse_racing.sqlite3',all_target_day_results_excluded=True))
    return current,max(x['race_date'] for x in fullhist),max(str(x['trial_date'])[:10] for x in trialrows)
def main():
    reg=json.loads((ROOT/'config/prediction_model_registry.json').read_text())
    profile=reg['profiles'][reg['domains']['thoroughbred']['active_profile']]
    for name,x in profile['artifacts'].items():
        assert digest(ROOT/x['path'])==x['sha256'],name
    now=datetime.now(timezone.utc)
    out=ROOT/'thoroughbred/predictions'/('20261002_busan_3_9_readonly_'+now.strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False)
    raw=ROOT/'data/raw/kra/entry_sheet/2026/10/02/meet_3/run_19537/page_0001_1790838141261_6949e9158467.json'
    items=[x for x in json.loads(raw.read_text())['response']['body']['items']['item'] if 3<=int(x['rcNo'])<=9]
    assert len(items)==77
    cards=[]
    for x in items:
        rn=int(x['rcNo']); tm=re.search(r'(\d\d):(\d\d)',x['stTime'])
        scheduled=datetime.fromisoformat(f'2026-10-02T{tm[1]}:{tm[2]}:00+09:00').astimezone(timezone.utc).isoformat()
        cards.append(dict(race_id=f'RACE:BUSAN:20261002:{rn:02}',venue_code='BUSAN',canonical_meet=3,race_date='2026-10-02',race_no=rn,chul_no=int(x['chulNo']),hr_no=str(x['hrNo']),horse_name_normalized=x['hrName'],origin_raw=x['prd'],sex_raw=x['sex'],age_raw=x['age'],rating_raw=shadow._rating(x['rating']),jockey_no=str(x['jkNo']),trainer_no=str(x['trNo']),owner_no=str(x['owNo']),burden_weight_kg=float(x['wgBudam']),distance_m=int(x['rcDist']),race_type=x['rcName'],race_class=x['rank'],burden_type=x['budam'],rating_condition_raw=x['prizeCond'],field_size_full_card=int(x['dusu']),scheduled_start_at_utc=scheduled,source_observed_at_utc=shadow.observed_at_from_kra_path(raw).isoformat(),source_snapshot_id=digest(raw)))
    c=sqlite3.connect('file:'+str(ROOT/'data/horse_racing.sqlite3')+'?mode=ro',uri=True)
    db=pd.read_sql_query('''SELECT r.race_number race_no,e.horse_number chul_no,h.kra_horse_id hr_no,h.name_ko horse_name_normalized,e.id race_entry_id,e.carried_weight_kg burden_weight_kg,j.kra_jockey_id jockey_no FROM races r JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id JOIN jockeys j ON j.id=e.jockey_id WHERE r.race_date_local=? AND r.racecourse_id=(SELECT id FROM racecourses WHERE kra_meet_code=?) AND r.race_number BETWEEN 3 AND 9 AND e.scratched=0''',c,params=('2026-10-02',3));c.close()
    merged=pd.DataFrame(cards).merge(db,on=['race_no','chul_no'],suffixes=('','_db'),validate='one_to_one')
    assert len(merged)==77
    for k in ['hr_no','horse_name_normalized','burden_weight_kg','jockey_no']: assert merged[k].equals(merged[k+'_db']),k
    idmap=merged.set_index(['race_no','chul_no']).race_entry_id.to_dict()
    dump(out/'card.json',cards)
    old=read(V3/'prediction_input/future_20260919_20_context.parquet')
    oldv4=read(V4/'future_predictions_20260919_20/prepared_v4_features.parquet')
    old=old.merge(oldv4[['race_id','hr_no']+NEW],on=['race_id','hr_no'],validate='one_to_one')
    oldcards=old.to_dict('records')
    for x in oldcards:
        x['race_date']=str(x['race_date'])[:10]
        if pd.isna(x['rating_raw']):x['rating_raw']=None
    hist=shadow._history_rows(SOURCE,'2026-10-02')
    print('BASE',len(hist),len(cards),flush=True)
    base=shadow._base38(oldcards+cards,hist)
    enriched=features_v2.derive_features(hist,base)
    print('V2 complete',flush=True)
    frame=pd.DataFrame(enriched)
    # Frozen scheduled-card contract keeps unverified events and late information missing.
    for col in ['training_days_3d','training_days_7d','training_days_14d','training_days_28d','training_seconds_7d','training_seconds_28d','start_training_events_28d','race_day_weight_kg','race_day_weight_delta_kg','track_raw','weather_raw','track_moisture_percent']:
        if col not in frame:frame[col]=None
    source=duckdb.connect(str(SOURCE),read_only=True)
    ctx=source.execute('''WITH s1f AS (SELECT race_id,hr_no,try_cast(position_raw AS INTEGER) s1f_position FROM section WHERE section_code='S1F' AND venue_code IN ('SEOUL','YEONGCHEON') AND semantic_status IN ('verified_source_field','official_api_verified_first_meeting')) SELECT e.race_id,e.race_date,e.chul_no,e.hr_no,e.venue_code,r.distance_m,CASE WHEN e.finish_order IS NOT NULL THEN e.finish_order WHEN e.venue_code='YEONGCHEON' AND e.result_status='finished' THEN try_cast(e.finish_raw AS INTEGER) ELSE NULL END finish_order,e.result_status,CASE WHEN e.venue_code='YEONGCHEON' AND e.result_status='finished' AND try_cast(e.finish_raw AS INTEGER) IS NOT NULL THEN true ELSE e.is_rank_label END is_rank_label,e.jockey_no,e.burden_weight_kg,e.horse_weight_kg,s.s1f_position,b.research_elo_global baseline_elo FROM entry_result e JOIN race r USING(race_id) LEFT JOIN s1f s USING(race_id,hr_no) LEFT JOIN read_parquet(?) b USING(race_id,hr_no) WHERE r.official_result_state='confirmed' AND e.race_date>=DATE '2000-01-01' AND e.race_date<DATE '2026-10-02' ORDER BY e.race_date,e.race_id,e.chul_no,e.hr_no''',[str(V2/'prepared_v2.parquet')]).fetchdf()
    trials=source.execute("""SELECT trial_event_id,trial_date,hr_no,distance_m,finish_time_ms FROM trial_entry WHERE hr_no IS NOT NULL AND trial_date<DATE '2026-10-02' AND venue_resolution_status IN ('confirmed','confirmed_historical_text') AND ((horse_link_status='confirmed' AND venue_resolution_status='confirmed_historical_text') OR horse_link_status IN ('confirmed_official_id','linked_profile_signature','linked_race_age_corroborated','linked_training_date_corroborated','linked_training_disambiguated')) ORDER BY trial_date,trial_event_id,hr_no""").fetchdf();source.close()
    context=pd.DataFrame(context_features.derive_context_features(ctx,frame,trials))[['race_id','hr_no']+context_features.ALL_FEATURES]
    frame=frame.drop(columns=[x for x in context_features.ALL_FEATURES if x in frame]).merge(context,on=['race_id','hr_no'],validate='one_to_one')
    print('CONTEXT complete',flush=True)
    historical=read(V3/'prepared_context.parquet');historical=historical[pd.to_datetime(historical.race_date)<pd.Timestamp('2026-09-19')].copy()
    additions={col:False if col=='target_is_rank_label' else np.nan for col in historical if col not in frame}
    frame=pd.concat([frame,pd.DataFrame(additions,index=frame.index)],axis=1).copy()
    combined=pd.concat([historical,frame[historical.columns]],ignore_index=True)
    combined['race_date']=pd.to_datetime(combined.race_date)
    strict=strict_features(combined)
    frame=frame.drop(columns=[x for x in NEW if x in frame]).merge(strict[strict.race_id.isin(frame.race_id)][['race_id','hr_no']+NEW],on=['race_id','hr_no'],validate='one_to_one')
    bundles={'A':tc.load_bundle((ROOT/profile['artifacts']['A_model']['path']).parent),'BC':tc.load_bundle((ROOT/profile['artifacts']['BC_model']['path']).parent),'WIN':tc.load_v2_win_bundle((ROOT/profile['artifacts']['WIN_ORDER_model']['path']).parent)}
    features=set()
    for b in bundles.values():features.update(b.categorical_features+b.numeric_features)
    # Regeneration must reproduce every model input on the previously frozen 294-runner card.
    regenerated=frame[frame.race_id.isin(old.race_id)].set_index(['race_id','hr_no'],drop=False).sort_index();expected=old.set_index(['race_id','hr_no'],drop=False).sort_index()
    errors={}
    for col in sorted(features):
        if col in bundles['A'].categorical_features or col in bundles['BC'].categorical_features or col in bundles['WIN'].categorical_features:
            n=int((regenerated[col].astype('string').fillna('__NULL__')!=expected[col].astype('string').fillna('__NULL__')).sum())
        else:
            a=pd.to_numeric(regenerated[col],errors='coerce').to_numpy(float);b=pd.to_numeric(expected[col],errors='coerce').to_numpy(float)
            n=int((~np.isclose(a,b,atol=1e-9,rtol=1e-10,equal_nan=True)).sum())
        if n:errors[col]=n
    dump(out/'feature_parity.json',dict(passed=not errors,rows=len(expected),features=len(features),mismatches=errors))
    if errors:raise RuntimeError('Frozen feature parity failed: '+str(errors))
    frame,race_max,trial_max=refresh_current(cards,hist,ctx,trials,historical,out)
    frame=frame.sort_values(['race_no','chul_no']).reset_index(drop=True)
    frame=frame.drop(columns=[x for x in frame if x.startswith('target_') or x in ['finish_order','result_status','race_time_s','win_odds','place_odds']])
    validate_frame(frame,False); assert len(frame)==77
    frame.to_parquet(out/'prepared_features.parquet',index=False)
    scores={k:tc.raw_scores(b,frame) for k,b in bundles.items()}
    spec=importlib.util.spec_from_file_location('publisher_adapter',ROOT/'.agents/skills/horse-racing-prediction-publisher/scripts/build_20260919_publication_bundles.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
    b=bundles['A'];matrix=tc.prepare_matrix(frame,b.categorical_features,b.numeric_features,b.category_vocab)
    contrib=np.asarray(b.models['top3'].predict(matrix,pred_contrib=True,num_threads=4))
    assert np.allclose(contrib.sum(axis=1),scores['A']['top3'],atol=1e-8)
    runners=[];joints=[];explanations=[];checks=[]
    for rid,idx in frame.groupby('race_id',sort=False).indices.items():
        g=frame.iloc[idx];venue='BUSAN';wt=bundles['WIN'].metadata['temperature_by_venue'].get(venue,1.)
        at=bundles['A'].metadata['temperature_by_target_and_venue']['A'];bt=bundles['BC'].metadata['temperature_by_target_and_venue']
        a=tc.top3_set_joint(scores['A']['top3'][idx],scores['WIN']['win'][idx],at.get(venue,at['GLOBAL']),wt)
        w,p,t=pub.marginals(a) if hasattr(pub,'marginals') else (np.bincount(a.orders[:,0],weights=a.order_probability,minlength=len(g)),np.bincount(a.orders[:,:2].ravel(),weights=np.repeat(a.order_probability,2),minlength=len(g)),a.inclusion_probability)
        rank=np.argsort(np.argsort(-t,kind='stable'))+1
        for i,(_,row) in enumerate(g.iterrows()):
            global_i=int(idx[i]); eid=int(idmap[(int(row.race_no),int(row.chul_no))])
            runners.append(dict(race_id=rid,race_no=int(row.race_no),horse_number=int(row.chul_no),horse_name=row.horse_name_normalized,hr_no=row.hr_no,race_entry_id=eid,win_probability=float(w[i]),top2_probability=float(p[i]),top3_probability=float(t[i]),pred_rank=int(rank[i]),raw_A_score=float(scores['A']['top3'][global_i])))
            explanations+=pub.select_contributions(race_entry_id=eid,names=list(b.categorical_features+b.numeric_features),values=contrib[global_i,:-1],source=row.to_dict(),source_cutoff_at_ms=int(datetime.fromisoformat('2026-10-02T00:00:00+09:00').timestamp()*1000),component='A',method='lightgbm_pred_contrib_raw_a_score')
        checks.append(tc.probability_invariants(a))
        for target in 'BC':
            q=tc.top3_set_joint(scores['BC']['top3'][idx],scores['WIN']['win'][idx],bt[target].get(venue,bt[target]['GLOBAL']),wt);checks.append(tc.probability_invariants(q))
            prob=q.set_probability if target=='B' else q.order_probability;support=q.sets if target=='B' else q.orders
            for k,i in enumerate(np.argsort(-prob,kind='stable')[:10],1):joints.append(dict(race_id=rid,race_no=int(g.race_no.iloc[0]),target=target,rank=k,horse_numbers=[int(g.chul_no.iloc[j]) for j in support[i]],horse_names=[g.horse_name_normalized.iloc[j] for j in support[i]],probability=float(prob[i])))
    result=pd.DataFrame(runners);assert len(result)==77 and len(explanations)==462
    result.to_csv(out/'runner_probabilities.csv',index=False);result.to_parquet(out/'runner_probabilities.parquet',index=False)
    dump(out/'combination_predictions.json',joints);dump(out/'runner_explanations.json',explanations)
    maxerr=max(abs(float(v)) for x in checks for v in x.values());assert maxerr<1e-10
    dump(out/'metadata.json',dict(generated_at_utc=datetime.now(timezone.utc).isoformat(),model_profile=reg['domains']['thoroughbred']['active_profile'],prediction_stage='read_only_card_forecast',frozen_at_utc=now.isoformat(),card_hash=digest(out/'card.json'),race_history_max_date=race_max,trial_history_max_date=trial_max,history_cutoff='strictly_before_2026-10-02',races=7,runners=77,probability_error=maxerr,feature_parity_passed=True,warning='Scheduled-card features only; current body weight considered separately in human analysis. Verified new S1F positions unavailable; retained missing. Latest official changes checked separately.'))
    print('OUTPUT',out,flush=True);print(result.sort_values(['race_no','pred_rank']).groupby('race_no').head(5).to_string(index=False),flush=True)
if __name__=='__main__':main()
