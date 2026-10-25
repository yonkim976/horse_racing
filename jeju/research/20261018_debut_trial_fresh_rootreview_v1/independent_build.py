"""Independent reconstruction of the saved 30-field assessment; never fits a model."""
from pathlib import Path
from bisect import bisect_right
import hashlib
import json
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'
RAW = ROOT / 'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
POINTS = ROOT / 'jeju/research/20261010_style_history_source_audit_v1/api4_full_started_point_quality_cache.parquet'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump_new(name, obj):
    with (HERE / name).open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

def protect():
    files = [OLD/'features.parquet', RAW, POINTS,
             ROOT/'config/prediction_model_registry.json',
             ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs/features_f1_style6_debut_trial4.parquet']
    for folder in [OLD/'F1_STYLE6_2026', ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs/F1_STYLE6_DEBUT_TRIAL4_2026']:
        files += [folder/name for name in ['top3.txt','meta.json','evaluation_scores.parquet','calibration_scores.parquet']]
    dump_new('ROOT_PROTECTED_BEFORE.json', {str(p.relative_to(ROOT)):sha(p) for p in files})

def rebuild(source, targets, point_rows):
    """Independent formulas, supplied immutable source; targets carry only key/conditions."""
    source = source.sort_values(['race_date','race_number','horse_number','api_record_id']).copy()
    assert source.api_record_id.is_unique
    source['horse_id'] = source.horse_id.astype(str)
    assert source.started.eq(source.finish_position.between(1,89) | source.finish_position.isin([91,92])).all()
    started = source[source.started]
    histories = {str(h):g.to_dict('records') for h,g in started.groupby('horse_id', sort=False)}
    dates = {h:[r['race_date'] for r in g] for h,g in histories.items()}
    byid = source.set_index('api_record_id',drop=False)
    quality = {}
    for rid,g in started.groupby('race_id',sort=False):
        n=len(g);ranks=g.finish_position.tolist()
        quality[rid]=(n, n>=2 and g.horse_id.nunique()==n and sorted(ranks)==list(range(1,n+1)))
    assert not point_rows.duplicated(['api_record_id','point']).any()
    point_values={}
    for p in point_rows.itertuples(index=False):
        good=bool(p.race_point_eligible and p.local_rank_ok)
        if good:
            assert p.quality_order_status in {'api_positive_unreviewed','website_corrected'}
            assert p.api303_group_status in {'api_group_unreviewed','api_group_unavailable'}
            value=(float(p.quality_order_value)-1)/(int(p.full_started_n)-1)
            assert np.isclose(value,p.normalized_rank,atol=0,rtol=0)
            point_values[(int(p.api_record_id),p.point)]=value
    rows=[];lineage=[]
    for t in targets.itertuples(index=False):
        cutoff=(pd.Timestamp(t.race_date)-pd.Timedelta(days=2)).date().isoformat()
        history=histories.get(str(t.horse_id),[])
        past=history[:bisect_right(dates.get(str(t.horse_id),[]),cutoff)]
        same=[r for r in past if r['race_distance_m']==t.distance_m]
        recent=same[-5:];prev=past[-1] if past else None
        values=np.array([r['finish_time_seconds'] if r['valid_time'] else np.nan for r in recent],float)
        known=values[np.isfinite(values)]
        age=pd.to_numeric(prev['age_at_race_raw'],errors='coerce') if prev else np.nan
        age=age if pd.notna(age) and age>0 else np.nan
        sex=prev['sex_at_race_raw'] if prev else None
        if sex in ('','-','0'):sex=None
        gap=lambda r:float((pd.Timestamp(t.race_date)-pd.Timestamp(r['race_date'])).days) if r else np.nan
        n,complete=quality[prev['race_id']] if prev else (0,False)
        rank=prev['finish_position'] if prev else np.nan
        duplicate=bool(prev is not None and len(started[(started.race_id==prev['race_id'])&(started.horse_id==prev['horse_id'])])>1)
        validrank=prev is not None and not duplicate and np.isfinite(rank) and int(rank)==rank and 1<=rank<=n
        row=dict(api_record_id=int(t.api_record_id),race_id=t.race_id,race_date=t.race_date,horse_id=str(t.horse_id),
                 distance_m=t.distance_m,grade_raw=t.grade_raw,field_n=int(t.field_n),observed_starts=len(past),
                 days_since_start=gap(prev),previous_age=age,previous_sex=sex,same_starts=len(same),
                 same_valid_times=sum(bool(r['valid_time']) for r in same),days_since_same=gap(same[-1] if same else None),
                 last_time_s=values[-1] if len(values) else np.nan,mean5_s=float(known.mean()) if len(known) else np.nan,
                 valid_n5=len(known),previous_finish_relative_rank=(rank-1)/(n-1) if complete and validrank else np.nan,
                 previous_top3=float(rank<=3) if validrank else np.nan,
                 previous_result_status=('normal' if complete else 'non_normal_or_incomplete') if prev else 'unobserved')
        a=[];b=[];c=[]
        for r in recent:
            vals={p:point_values.get((int(r['api_record_id']),p),np.nan) if r['valid_time'] else np.nan for p in ['S1F','4C','G1F']}
            if np.isfinite(vals['S1F']):a.append(vals['S1F'])
            if np.isfinite(vals['S1F']) and np.isfinite(vals['4C']):b.append(vals['S1F']-vals['4C'])
            if np.isfinite(vals['4C']) and np.isfinite(vals['G1F']):c.append(vals['4C']-vals['G1F'])
            lineage.append(dict(target_api_record_id=int(t.api_record_id),source_api_record_id=int(r['api_record_id']),
                                source_date=r['race_date'],cutoff=cutoff,source_valid_time=bool(r['valid_time']),**vals))
        for name,count,arr in [('hist_s1f_relpos_mean5','hist_s1f_relpos_n',a),
                               ('hist_s1f_to_c4_forward_mean5','hist_s1f_to_c4_pair_n',b),
                               ('hist_c4_to_g1f_forward_mean5','hist_c4_to_g1f_pair_n',c)]:
            row[name]=float(np.mean(arr)) if arr else np.nan;row[count]=len(arr)
        rows.append(row)
    result=pd.DataFrame(rows)
    for rid,indices in result.groupby('race_id',sort=False).indices.items():
        assert len(indices)==result.iloc[indices[0]].field_n
        times=result.iloc[indices].mean5_s.to_numpy(float)
        for offset,idx in enumerate(indices):
            others=np.delete(times,offset);known=others[np.isfinite(others)];n=len(known);own=times[offset]
            has=bool(n and np.isfinite(own))
            vals=dict(opp_mean5_valid_n=n,opp_mean5_valid_fraction=n/(len(indices)-1),
                      opp_mean5_median_s=float(np.median(known)) if n else np.nan,
                      mean5_minus_opp_mean_s=own-known.mean() if has else np.nan,
                      mean5_minus_opp_median_s=own-np.median(known) if has else np.nan,
                      mean5_minus_opp_fast2mean_s=own-np.sort(known)[:2].mean() if has and n>=2 else np.nan,
                      opp_mean5_faster_n=int((known<own).sum()) if has else np.nan,
                      mean5_rank_fraction=float(((known<own).sum()+.5*(known==own).sum())/n) if has else np.nan)
            for col,val in vals.items():result.loc[idx,col]=val
    return result,pd.DataFrame(lineage)

def compare(actual, expected, columns):
    expected=expected.set_index('api_record_id').loc[actual.api_record_id]
    errors={}
    for col in columns:
        a=actual[col].reset_index(drop=True);b=expected[col].reset_index(drop=True)
        if col in {'grade_raw','previous_sex','previous_result_status'}:
            assert a.astype('string').fillna('<NULL>').equals(b.astype('string').fillna('<NULL>')),col
            errors[col]=0.0
        else:
            aa=a.to_numpy(float);bb=b.to_numpy(float)
            assert np.allclose(aa,bb,atol=1e-12,rtol=0,equal_nan=True), (col,float(np.nanmax(np.abs(aa-bb))))
            errors[col]=float(np.nanmax(np.abs(aa-bb))) if np.isfinite(aa-bb).any() else 0.0
    return errors

def historical():
    target=pd.read_parquet(OLD/'features.parquet');target=target[target.year.eq(2026)].reset_index(drop=True)
    source=pd.read_parquet(RAW);points=pd.read_parquet(POINTS)
    rebuilt,lineage=rebuild(source,target,points)
    cols=json.loads((OLD/'F1_STYLE6_2026/meta.json').read_text())['features']
    errors=compare(rebuilt,target,cols)
    rebuilt.to_parquet(HERE/'ROOT_REBUILT_OLD_2026.parquet',index=False)
    dump_new('ROOT_HISTORICAL_REBUILD.json',dict(status='PASS',rows=len(target),races=target.race_id.nunique(),
             independently_reconstructed_from_source=True,field_errors=errors,model_fits=0))
    print(json.dumps(dict(status='PASS',historical_rebuilt_rows=len(target),max_error=max(errors.values()))))

if __name__=='__main__':
    if sys.argv[1:]==['protect']:protect()
    elif sys.argv[1:]==['historical']:historical()
    else:raise SystemExit('usage: independent_build.py protect|historical')
