"""Independent five-interval source/mask/last-five aggregation audit; no fit."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
SOURCE=ROOT/'jeju/research/20261017_1000m_five_section_source_audit_v1'
BASE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
ORIGINAL=ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
MAIN=ROOT/'jeju/research/20261017_1000m_five_section_ablation_v1/outputs'
NAMES=['seg_0_200','seg_200_to_c3_approx400','seg_c3_approx400_to_c4_approx600','seg_c4_approx600_to_800','seg_800_to_1000']
FEATURES=['hist_0_200m','hist_200_approx400m','hist_approx400_approx600m','hist_approx600_800m','hist_800_1000m']
POINTS={'s1f':('sjS1fOrd','S1F'),'c3':('sj_3cOrd','3C'),'c4':('sj_4cOrd','4C'),'g1f':('sjG1fOrd','G1F')}

def main():
    base=pd.read_parquet(BASE);old=pd.read_parquet(ORIGINAL);q=pd.read_parquet(SOURCE/'api4_quality_source_snapshot.parquet');slots=pd.read_parquet(SOURCE/'target_last5_section_intervals.parquet')
    orders=pd.read_parquet(SOURCE/'source_point_order_status_evidence.parquet');groups=pd.read_parquet(SOURCE/'source_point_group_status_evidence.parquet');mask=pd.read_parquet(SOURCE/'source_race_point_quality_masks.parquet')
    assert len(slots)==53828 and slots.source_api_record_id.nunique()==14193
    qi=q.set_index('api_record_id');oldi=old.set_index('api_record_id');refer=qi.loc[slots.source_api_record_id].reset_index(drop=True)
    for col in ['horse_id','race_date','race_distance_m','horse_number','finish_time_seconds','api4_3_payload_sha256']:
        a=qi[col].reindex(q.api_record_id).reset_index(drop=True);b=oldi[col].reindex(q.api_record_id).reset_index(drop=True)
        if col in ['horse_id','race_date','api4_3_payload_sha256']:assert a.astype(str).equals(b.astype(str)),col
        else:assert np.allclose(a,b,atol=0,rtol=0,equal_nan=True),col
    expected=old[old.started.eq(True)].groupby('race_id').api_record_id.agg(set).to_dict()
    oq={k:g for k,g in orders.groupby(['race_id','field_name'])};gq={k:g for k,g in groups.groupby(['race_id','point'])}
    qgroups={k:g for k,g in q.groupby('race_id')};clear={};point_rows=[]
    good_order={'api_positive_unreviewed','website_corrected','api_unavailable_or_nonpositive_or_sentinel'};good_group={'api_group_unreviewed','api_group_unavailable'}
    for r in mask.itertuples(index=False):
        field,gpoint=POINTS[r.point];o=oq[(r.race_id,field)];o=o[o.api_record_id.isin(expected[r.race_id])]
        selected=qgroups[r.race_id].api303_api_record_id.dropna().unique();g=gq.get((r.race_id,gpoint),pd.DataFrame(columns=groups.columns))
        g=g[g.api_record_id.isin(selected)]
        same_ids=set(o.api_record_id)==expected[r.race_id]
        ok=same_ids and o.quality_order_status.isin(good_order).all() and len(selected)==1 and len(g)==1 and g.group_status.isin(good_group).all()
        assert bool(ok)==bool(r.point_clear_full_race),(r.race_id,r.point,ok,r.point_clear_full_race)
        clear[(r.race_id,r.point)]=bool(ok);point_rows.append((r.race_id,r.point,bool(ok)))
    nums={n:pd.to_numeric(refer[n+'_time_seconds'],errors='coerce').to_numpy(float) for n in ['s1f','c3','c4','g1f']};t=refer.finish_time_seconds.to_numpy(float)
    values=np.column_stack([nums['s1f'],nums['c3']-nums['s1f'],nums['c4']-nums['c3'],t-nums['g1f']-nums['c4'],nums['g1f']])
    endpoint={n:np.isfinite(nums[n])&(nums[n]>0)&refer[n+'_time_status'].isin(['api_positive_unreviewed','website_corrected']).to_numpy() for n in nums}
    good={n:np.array([clear[(str(r),n)] for r in slots.source_race_id]) for n in POINTS}
    source_valid=oldi.valid_time.reindex(slots.source_api_record_id).to_numpy(bool)
    eligible=np.column_stack([endpoint['s1f']&good['s1f'],endpoint['s1f']&endpoint['c3']&good['s1f']&good['c3'],endpoint['c3']&endpoint['c4']&good['c3']&good['c4'],endpoint['c4']&endpoint['g1f']&good['c4']&good['g1f']&np.isfinite(t)&(t>0),endpoint['g1f']&good['g1f']])
    eligible&=np.isfinite(values)&(values>0)&source_valid[:,None]
    for i,name in enumerate(NAMES):
        assert np.allclose(slots[name+'_raw_delta_seconds'],values[:,i],atol=1e-12,rtol=0,equal_nan=True)
        assert np.array_equal(slots[name+'_feature_eligible'].to_numpy(bool),eligible[:,i])
    assert slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
    target=base[base.distance_m.eq(1000)];assert len(target)==14457
    assert np.array_equal(pd.to_datetime(target.history_cutoff).to_numpy(),(pd.to_datetime(target.race_date)-pd.Timedelta(days=2)).to_numpy())
    target_index=target.set_index('api_record_id');actual={tid:g for tid,g in slots.groupby('target_api_record_id',sort=False)}
    assert not slots.duplicated(['target_api_record_id','source_api_record_id']).any()
    assert np.array_equal(target_index.horse_id.reindex(slots.target_api_record_id).astype(str).to_numpy(),refer.horse_id.astype(str).to_numpy())
    assert refer.race_distance_m.eq(1000).all() and refer.started.eq(True).all()
    for tid,row in target_index.iterrows():
        g=actual.get(tid);ids=[] if g is None else list(g.sort_values('slot_oldest_to_newest').source_api_record_id)
        assert ids==list(row['last5_same_source_ids'])
    candidate=pd.read_parquet(MAIN/'features_f1_style6_5section.parquet');pd.testing.assert_frame_equal(candidate[base.columns],base,check_exact=True)
    extra=pd.DataFrame({'api_record_id':target.api_record_id.to_numpy()});max_error=0.
    for i,stem in enumerate(FEATURES):
        v=pd.DataFrame({'id':slots.target_api_record_id,'v':np.where(eligible[:,i],values[:,i],np.nan)}).groupby('id').v.agg(['mean','count']).reindex(target.api_record_id)
        mean=v['mean'].to_numpy();n=v['count'].fillna(0).to_numpy(float);extra[stem+'_seconds_mean5']=mean;extra[stem+'_n']=n
        saved=candidate.set_index('api_record_id').loc[target.api_record_id]
        assert np.allclose(saved[stem+'_seconds_mean5'],mean,atol=1e-12,rtol=0,equal_nan=True),stem
        assert np.array_equal(saved[stem+'_n'].to_numpy(),n),stem
        finite=np.isfinite(mean);max_error=max(max_error,float(abs(saved[stem+'_seconds_mean5'].to_numpy()[finite]-mean[finite]).max()))
    columns=[col for col in extra.columns if col!='api_record_id'];assert candidate[candidate.distance_m.ne(1000)][columns].isna().all().all()
    extra.to_parquet(HERE/'ROOT_SECTION_FEATURE_REFERENCE.parquet',index=False)
    receipt={'status':'PASS','source_rows':len(q),'full_race_points':len(mask),'actual_slots':len(slots),'targets':len(target),'feature_columns':10,'max_mean_error':max_error,'valid_time_false_slots_preserved':int((~source_valid).sum()),'training_calls':0,'new_feature_sha256':hashlib.sha256((MAIN/'features_f1_style6_5section.parquet').read_bytes()).hexdigest()}
    (HERE/'ROOT_FEATURE_REVIEW.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
