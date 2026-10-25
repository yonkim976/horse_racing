"""Read-only, source-verified S1F/1C timing audit for every Seoul1800 row."""
import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
DB=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
KEY=['date_key','race_no','horse_id']
FIELDS={'S1F':'seS1fAccTime','1C':'se_1cAccTime','2C':'se_2cAccTime','3C':'se_3cAccTime','G3F':'seG3fAccTime','4C':'se_4cAccTime','G1F':'seG1fAccTime'}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def load():
    with duckdb.connect(str(DB),read_only=True) as c:
        d=c.execute("""select result_date date_key,try_cast(result_race_no as int) race_no,
            horse_id_raw horse_id,horse_name_raw horse_name,try_cast(horse_program_no_raw as int) program_no,
            result_rank_raw rank_raw,try_cast(result_rank_raw as int) finish_rank,
            try_cast(finish_time_seconds_raw as double) finish_seconds,execution_status,
            grade_raw,track_condition_raw,weather_raw,source_file,try_cast(source_item_index as int) source_item_index
            from confirmed_runners where source_meet='1' and try_cast(race_distance_m_raw as int)=1800""").df()
        q=c.execute("""select race_date date_key,try_cast(race_no as int) race_no,horse_id,
            point_code,measure_kind,time_ms,passing_order,source_field,source_file,source_item_index
            from section_measurements_api where meet=1""").df()
        plans=c.execute("""select result_date_key date_key,try_cast(result_race_no_key as int) race_no,
            scheduled_start_raw,plan_source_file from confirmed_races where source_meet='1'""").df()
    assert not d.duplicated(KEY).any() and not plans.duplicated(KEY[:2]).any()
    q=q.merge(d[KEY],on=KEY,validate='many_to_one')
    for kind,col in [('cumulative_time','time_ms'),('passing_order','passing_order')]:
        sub=q[q.measure_kind.eq(kind)]
        assert not sub.duplicated(KEY+['point_code']).any()
        w=sub.pivot(index=KEY,columns='point_code',values=col)
        w.columns=[str(p)+('_ms' if kind=='cumulative_time' else '_order') for p in w.columns]
        d=d.merge(w,on=KEY,how='left',validate='one_to_one')
    for name in d.columns:
        if name.endswith(('_ms','_order')):d[name]=d[name].to_numpy(dtype=float,na_value=np.nan)
    return d.merge(plans,on=KEY[:2],how='left',validate='many_to_one'),q


def check():
    for path,digest in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/path)==digest,path


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    d,q=load()
    sources=sorted(d.source_file.unique())
    paths=[HERE/'PLAN.md',HERE/'run.py',DB,DB.parent/'manifest.json',
           R/'20261017_section_layout_by_distance_v1/outputs/distance_layouts.csv',
           ROOT/'config/prediction_model_registry.json']+[ROOT/p for p in sources]
    frozen={str(p.relative_to(ROOT)):sha(p) for p in paths}
    mf=OUT/'input_manifest.json'
    if mf.exists():assert json.loads(mf.read_text())==frozen
    else:save(mf,frozen)
    before=OUT/'publication_before.json'
    if not before.exists():
        shared=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
        snap=OUT/'publication_before';snap.mkdir()
        for p in shared:(snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())
    raw=[];cells=0
    for source,g in d.groupby('source_file'):
        p=(ROOT/source).resolve()
        assert p.is_relative_to(ROOT/'thoroughbred/research/20260929_calendar_api_v1/raw')
        with gzip.open(p,'rt',encoding='utf-8') as f:items=json.load(f)['response']['body']['items']['item']
        for row in g.itertuples():
            x=items[row.source_item_index]
            assert (str(x['rcDate']),int(x['rcNo']),str(x['hrNo']).zfill(7))==(row.date_key,row.race_no,row.horse_id)
            assert int(x['rcDist'])==1800 and x['meet']=='서울'
            record={k:getattr(row,k) for k in KEY}
            for point,field in FIELDS.items():
                value=float(x[field]);actual=d.at[row.Index,point+'_ms']
                assert (pd.isna(actual) and value<=0) or abs(actual-value*1000)<1e-8
                record[field]=value;cells+=1
            for point,field in [('S1F','sjS1fOrd'),('1C','sj_1cOrd')]:
                record[field]=int(x[field]);actual=d.at[row.Index,point+'_order']
                if pd.isna(actual):assert not 1<=record[field]<=30
                else:assert actual==record[field]
                cells+=1
            raw.append(record)
        print('raw verified',source,len(g),flush=True)
    pd.DataFrame(raw).to_parquet(OUT/'raw_fields.parquet',index=False)
    a,b=d.S1F_ms,d['1C_ms'];both=a.gt(0)&b.gt(0)
    d['comparison']=np.select([~both,b.eq(a),b.gt(a)],['missing','equal','later'],default='earlier')
    d['delta_seconds']=(b-a)/1000
    d['normal_finish']=d.finish_rank.between(1,30)&d.finish_seconds.gt(0)
    d['year']=d.date_key.str[:4].astype(int);d['month']=d.date_key.str[4:6].astype(int)
    start=d.scheduled_start_raw.fillna('').astype(str).str.strip()
    valid=start.str.fullmatch(r'\d{4}') & pd.to_numeric(start.str[2:],errors='coerce').lt(60)
    d['scheduled_night']=pd.Series(pd.NA,index=d.index,dtype='boolean')
    d.loc[valid,'scheduled_night']=pd.to_numeric(start[valid]).ge(1801).to_numpy()
    d.sort_values(KEY).to_parquet(OUT/'runner_audit.parquet',index=False)
    yearly=[]
    for scope,g in [('all',d),('normal',d[d.normal_finish])]:
        for year,h in g.groupby('year'):
            n=h.comparison.value_counts();yearly.append(dict(scope=scope,year=int(year),rows=len(h),
                **{s:int(n.get(s,0)) for s in ['equal','later','earlier','missing']},
                first_equal=h.loc[h.comparison.eq('equal'),'date_key'].min() if n.get('equal',0) else '',
                last_equal=h.loc[h.comparison.eq('equal'),'date_key'].max() if n.get('equal',0) else ''))
    pd.DataFrame(yearly).to_csv(OUT/'yearly_counts.csv',index=False)
    d.groupby(['year','month','comparison'],dropna=False).size().rename('rows').reset_index().to_csv(OUT/'monthly_counts.csv',index=False)
    race=[]
    for (date,no),g in d.groupby(KEY[:2]):
        n=g.comparison.value_counts()
        race.append(dict(date_key=date,race_no=int(no),rows=len(g),**{s:int(n.get(s,0)) for s in ['equal','later','earlier','missing']},
            scheduled_start_raw=g.scheduled_start_raw.iloc[0],scheduled_night=g.scheduled_night.iloc[0],
            normal_rows=int(g.normal_finish.sum()),normal_equal=int((g.normal_finish&g.comparison.eq('equal')).sum()),
            delta_median=g.delta_seconds.median(),track=g.track_condition_raw.iloc[0],grade=g.grade_raw.iloc[0]))
    races=pd.DataFrame(race).sort_values(KEY[:2]);races.to_csv(OUT/'race_counts.csv',index=False)
    eq=races[races.equal.gt(0)];eq.to_csv(OUT/'equal_races.csv',index=False)
    d[d.comparison.eq('earlier')].to_csv(OUT/'earlier_records.csv',index=False)
    d[d.comparison.eq('equal')&~d.normal_finish].to_csv(OUT/'non_normal_equal.csv',index=False)
    controls=races[races.date_key.isin(eq.date_key)];controls.to_csv(OUT/'same_day_controls.csv',index=False)
    races.groupby(['scheduled_night'],dropna=False)[['rows','equal','later','earlier','missing']].sum().to_csv(OUT/'scheduled_night_counts.csv')
    counts=d.comparison.value_counts().to_dict();normal=d[d.normal_finish].comparison.value_counts().to_dict()
    save(OUT/'summary.json',dict(rows=len(d),races=len(races),first_date=d.date_key.min(),last_date=d.date_key.max(),
        all_counts=counts,normal_rows=int(d.normal_finish.sum()),normal_counts=normal,equal_races=len(eq),
        equal_first=eq.date_key.min(),equal_last=eq.date_key.max(),equal_months=sorted(d.loc[d.comparison.eq('equal'),'month'].unique().astype(int).tolist()),
        equal_races_with_later=int(eq.later.gt(0).sum()),equal_races_all_scheduled_night=bool(eq.scheduled_night.fillna(False).all()),
        equal_order_matches=int((d.comparison.eq('equal')&d.S1F_order.eq(d['1C_order'])).sum()),
        raw_rows_checked=len(d),raw_cells_checked=cells,raw_files=len(sources),max_raw_error=0,
        ordinary_delta_median=float(d.loc[d.comparison.eq('later'),'delta_seconds'].median()),
        database_access='read_only',models_changed=False,actual_route_changes_individually_verified=False))
    save(OUT/'official_sources.json',dict(checked_on='2026-10-19',sources=[
        dict(url='https://race.kra.co.kr/down/raceplan_2019.pdf',page_zero_based=15,
             fact='Seoul adverse weather or night:1800 start may move to1700 start;join outer course at2C;total1800 unchanged;planned after18:00 is night'),
        dict(url='https://race.kra.co.kr/down/raceplan_2023.pdf',page_zero_based=13,
             fact='Same optional start/course change rule;night after18:00 per monthly plan'),
        dict(url='https://race.kra.co.kr/globalEn/resultsRaceDetailSeoul.do?rcDate=20190720&rcNo=9',status='web_tool_inaccessible; used preserved raw API, not live scorecard')]))
    check();print((OUT/'summary.json').read_text())


if __name__=='__main__':main()
