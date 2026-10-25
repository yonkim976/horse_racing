"""Independent read-only selected-point audit for the fresh target history slots."""
import sqlite3
import json
import numpy as np
import pandas as pd
from independent_build import ROOT,HERE,RAW,POINTS,dump_new

def main():
    old=pd.read_parquet(RAW);fresh=pd.read_parquet(HERE/'ROOT_RAW_NEW_ROWS.parquet')
    source=pd.concat([old,fresh[old.columns]],ignore_index=True).sort_values(['race_date','race_number','horse_number','api_record_id'])
    targets=[];held=[]
    for rid,g in fresh.groupby('race_id',sort=True):
        n=len(g)
        okay=(n>=6 and g.race_distance_m.isin([800,900,1000,1110,1200,1300,1400,1610]).all()
              and g.valid_time.all() and sorted(g.finish_position.dropna())==list(range(1,n+1))
              and g.horse_id.nunique()==n and g.horse_number.notna().all() and g.horse_number.gt(0).all()
              and g.horse_number.nunique()==n
              and all(g[c].nunique(dropna=False)==1 for c in ['race_distance_m','rank_class_raw']))
        if okay:targets.append(g)
        else:held.append(rid)
    target=pd.concat(targets,ignore_index=True).sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
    target['distance_m']=target.race_distance_m;target['grade_raw']=target.rank_class_raw
    target['field_n']=target.groupby('race_id').api_record_id.transform('size')
    target.to_parquet(HERE/'ROOT_TARGET_ROSTER.parquet',index=False)
    histories={h:g for h,g in source[source.started].groupby('horse_id',sort=False)}
    slots=[]
    for r in target.itertuples(index=False):
        cutoff=(pd.Timestamp(r.race_date)-pd.Timedelta(days=2)).date().isoformat()
        g=histories.get(r.horse_id,source.iloc[:0]);same=g[(g.race_date<=cutoff)&g.race_distance_m.eq(r.distance_m)].tail(5)
        for s in same.itertuples(index=False):slots.append(dict(target_api_record_id=int(r.api_record_id),source_api_record_id=int(s.api_record_id),source_race_id=s.race_id))
    ids=set(r['source_api_record_id'] for r in slots);cache=pd.read_parquet(POINTS)
    missing=ids-set(cache.api_record_id);keys=source[source.api_record_id.isin(missing)][['race_date','meet_code','race_number']].drop_duplicates().sort_values(['race_date','race_number'])
    con=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True)
    con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
    binds=','.join('(?,?,?)' for _ in range(len(keys)));params=[v.item() if isinstance(v,np.generic) else v for row in keys.itertuples(index=False,name=None) for v in row]
    full=pd.read_sql_query('SELECT * FROM race_result_rows WHERE (race_date,meet_code,race_number) IN (VALUES '+binds+')',con,params=params)
    full=full[full.finish_position.between(1,89)|full.finish_position.isin([91,92])].copy()
    full['horse_id']=full.horse_id.astype(str);full['race_id']=full.race_date+'_2_'+full.race_number.astype(str)
    assert missing<=set(full.api_record_id)
    mark=','.join('?' for _ in range(len(full)))
    orders=pd.read_sql_query('SELECT api_record_id,field_name,quality_order_value,quality_order_status FROM jeju_race_section_order_quality_values WHERE api_record_id IN ('+mark+") AND field_name IN ('sjS1fOrd','sj_4cOrd','sjG1fOrd')",con,params=full.api_record_id.astype(int).tolist())
    groups=pd.read_sql_query("SELECT api_record_id,race_date,meet_code,race_number,point,group_value,group_status FROM jeju_race_section_group_quality_values WHERE (race_date,meet_code,race_number) IN (VALUES "+binds+") AND point IN ('S1F','4C','G1F')",con,params=params)
    con.close();groups['race_id']=groups.race_date+'_2_'+groups.race_number.astype(str)
    assert not orders.duplicated(['api_record_id','field_name']).any()
    assert not groups.duplicated(['race_id','point']).any()
    orderlookup=orders.set_index(['api_record_id','field_name']).to_dict('index')
    grouplookup=groups.set_index(['race_id','point']).group_status.to_dict()
    out=[];quality=[]
    for rid,g in full.groupby('race_id',sort=True):
        n=len(g)
        for point,field in [('S1F','sjS1fOrd'),('4C','sj_4cOrd'),('G1F','sjG1fOrd')]:
            rows=[orderlookup.get((int(a),field),{}) for a in g.api_record_id]
            vals=[r.get('quality_order_value',np.nan) for r in rows]
            statuses=[r.get('quality_order_status') for r in rows]
            integer=lambda x:pd.notna(x) and np.isfinite(x) and int(x)==x and 1<=x<=n
            local=[statuses[i] in {'api_positive_unreviewed','website_corrected'} and integer(v) for i,v in enumerate(vals)]
            permutation=(n>=2 and all(local) and len(set(vals))==n and g.horse_id.nunique()==n)
            groupstatus=grouplookup.get((rid,point));eligible=permutation and groupstatus in {'api_group_unreviewed','api_group_unavailable'}
            quality.append(dict(race_id=rid,point=point,started_n=n,group_status=groupstatus,permutation=bool(permutation),eligible=bool(eligible)))
            for i,r in enumerate(g.itertuples(index=False)):
                out.append(dict(api_record_id=int(r.api_record_id),race_id=rid,race_date=r.race_date,race_distance_m=r.race_distance_m,
                                horse_id=r.horse_id,horse_number=int(r.horse_number),point=point,field_name=field,full_started_n=n,
                                quality_order_value=vals[i],quality_order_status=statuses[i],local_rank_ok=bool(local[i]),
                                api303_group_status=groupstatus,race_point_eligible=bool(eligible),
                                normalized_rank=float((vals[i]-1)/(n-1)) if eligible else np.nan))
    frame=pd.DataFrame(out);frame.to_parquet(HERE/'ROOT_EXTRA_FULL_POINT_CACHE.parquet',index=False)
    orders.to_parquet(HERE/'ROOT_EXTRA_SELECTED_ORDERS.parquet',index=False)
    groups.to_parquet(HERE/'ROOT_EXTRA_SELECTED_GROUPS.parquet',index=False)
    pd.DataFrame(slots).to_parquet(HERE/'ROOT_TARGET_STYLE_SLOTS.parquet',index=False)
    pd.DataFrame(quality).to_csv(HERE/'ROOT_EXTRA_RACE_POINT_QUALITY.csv',index=False)
    dump_new('ROOT_EXTRA_POINT_SOURCE.json',dict(status='PASS',target_rows=len(target),target_races=target.race_id.nunique(),
             held_target_races=held,style_slots=len(slots),unique_slot_source_ids=len(ids),missing_old_cache_ids=len(missing),
             missing_old_cache_races=len(keys),queried_full_started_rows=len(full),extra_point_rows=len(frame),
             missing_group_status_points=int(sum(r['group_status'] is None for r in quality)),
             eligible_points=int(sum(r['eligible'] for r in quality)),all_slots_explicitly_covered=True,model_predictions=0))
    print(json.dumps(dict(status='PASS',targets=len(target),races=target.race_id.nunique(),missing_cache_ids=len(missing),full_extra_races=len(keys),new_eligible_points=sum(r['eligible'] for r in quality))))

if __name__=='__main__':main()
