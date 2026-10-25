"""Event-cutoff training features; no current or future race outcomes are inputs."""
import json
import duckdb
import numpy as np
import pandas as pd
import study_common as c

DAILY_SQL="""WITH selected AS (
 SELECT t.* FROM daily_training_raw t JOIN training_date_coverage v
 ON v.dataset=t.dataset AND v.meet=t.meet AND v.event_date=t.event_date
 AND v.selected_capture_id=t.capture_id
 WHERE v.coverage_status='complete_rows' AND NOT v.inventory_count_mismatch
 AND t.meet IN ('1','3') AND nullif(t.official_horse_id,'') IS NOT NULL
), keyed AS (
 SELECT meet,official_horse_id AS horse_id,event_date,started_at_raw,ended_at_raw,
 count(*) raw_rows,
 bool_and(qa_flags_json='[]' AND try_cast(duration_seconds_raw AS DOUBLE)>0
 AND try_cast(duration_seconds_raw AS DOUBLE)<=7200) AND count(DISTINCT duration_seconds_raw)=1 AS is_valid,
 max(try_cast(duration_seconds_raw AS DOUBLE))/60.0 AS duration_minutes
 FROM selected GROUP BY meet,horse_id,event_date,started_at_raw,ended_at_raw
)
SELECT cast(meet AS INTEGER) meet,horse_id,event_date,
 count(*) sessions,sum(raw_rows) raw_rows,
 bool_and(is_valid) AS is_valid,
 CASE WHEN bool_and(is_valid) THEN sum(duration_minutes) ELSE NULL END duration_minutes
FROM keyed GROUP BY meet,horse_id,event_date
"""

WINDOW_SQL="""
WITH w AS (
 SELECT a.anchor_id,
 count(t.event_date) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY) train_days7,
 count(t.event_date) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY) train_days14,
 count(t.event_date) train_days28,
 CASE WHEN bool_and(t.is_valid) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY)
 THEN sum(t.duration_minutes) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY) END train_minutes7,
 CASE WHEN bool_and(t.is_valid) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY)
 THEN sum(t.duration_minutes) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY) END train_minutes14,
 CASE WHEN bool_and(t.is_valid) THEN sum(t.duration_minutes) END train_minutes28,
 count(t.event_date) FILTER(WHERE NOT t.is_valid) train_qa_days28,
 max(t.event_date) training_source_max_date
 FROM anchors a LEFT JOIN study_daily t ON a.horse_id=t.horse_id AND a.meet=t.meet
 AND t.event_date BETWEEN a.cutoff-INTERVAL 27 DAY AND a.cutoff GROUP BY a.anchor_id
), coverage AS (
 SELECT a.anchor_id,count(v.event_date) FILTER(WHERE v.coverage_status IN ('complete_rows','complete_zero_rows')
 AND NOT v.inventory_count_mismatch)/28.0 train_coverage28
 FROM anchors a LEFT JOIN training_date_coverage v ON v.dataset='daily_training' AND cast(v.meet AS INTEGER)=a.meet
 AND v.event_date BETWEEN a.cutoff-INTERVAL 27 DAY AND a.cutoff GROUP BY a.anchor_id
) SELECT * FROM w JOIN coverage USING(anchor_id) ORDER BY anchor_id
"""

def source_anchors():
    con=duckdb.connect(str(c.old.DB),read_only=True)
    a=con.execute("""SELECT cast(canonical_meet AS INTEGER) meet,
      cast(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||cast(race_no AS VARCHAR) race_key,
      chul_no program_no,hr_no horse_id,race_date FROM entry_result
      WHERE canonical_meet IN (1,3) AND result_status IN ('finished','did_not_finish','disqualified','special_result')
      ORDER BY canonical_meet,hr_no,race_date,race_no,chul_no""").df();con.close()
    assert not a.duplicated(c.KEY).any();assert not a.duplicated(['meet','horse_id','race_date']).any()
    a['anchor_id']=np.arange(len(a));return a

def add_personal(a,z,lag):
    f=pd.concat([a.reset_index(drop=True),z.drop(columns='anchor_id').reset_index(drop=True)],axis=1)
    f['train_minutes_per_day14']=f.train_minutes14/f.train_days14.replace(0,np.nan)
    f['train_gap_days28']=(f.race_date-f.training_source_max_date).dt.days.astype(float)
    unsupported=f.train_coverage28.lt(1)
    f.loc[unsupported,[v for v in c.BASIC if v!='train_coverage28']]=np.nan
    values=f[c.PERSONAL_SOURCE].to_numpy(float);added=np.full((len(f),len(c.PERSONAL)),np.nan)
    previous_date=np.full(len(f),np.datetime64('NaT'),dtype='datetime64[ns]')
    for ix in f.groupby(['meet','horse_id'],sort=False).indices.values():
        days=f.iloc[ix].race_date.to_numpy(dtype='datetime64[D]')
        ends=np.searchsorted(days,days-np.timedelta64(lag,'D'),side='right')
        pos=ends[:,None]-np.arange(1,4)[None,:];exists=pos>=0
        past=values[ix][np.maximum(pos,0)].copy();past[~exists]=np.nan
        complete=np.isfinite(past).all(axis=2);n=complete.sum(1)
        past[~complete]=np.nan
        mean=np.nansum(past,axis=1)/np.maximum(n,1)[:,None]
        delta=values[ix]-mean;delta[n<2]=np.nan
        sd=np.sqrt(np.nansum((past[:,:,1]-mean[:,None,1])**2,axis=1)/np.maximum(n,1));sd[n<2]=np.nan
        added[ix,:6]=delta;added[ix,6]=n;added[ix,7]=sd
        has=ends>0;previous_date[ix[has]]=days[ends[has]-1]
    f[c.PERSONAL]=added;f['self_latest_race_date']=previous_date
    return f

def main():
    c.check();a=source_anchors();base=c.old.frame()
    con=duckdb.connect(str(c.CORE),read_only=True);con.execute('SET threads=4')
    # This temporary table belongs only to the connection and cannot alter the read-only DB.
    con.execute('CREATE TEMP TABLE study_daily AS '+DAILY_SQL)
    audit={'source_raw':con.sql("select meet,count(*) n,min(event_date) AS first_date,max(event_date) AS last_date,sum(historical_prerace_eligibility_verified::int) verified from daily_training_raw group by meet order by meet").df().astype(str).to_dict('records'),
        'daily':con.sql('select meet,count(*) AS observed_days,sum(sessions) AS sessions,sum(raw_rows) AS raw_rows,sum((NOT is_valid)::int) AS invalid_days from study_daily group by meet order by meet').df().to_dict('records'),
        'calendar':con.sql("select coverage_status,count(*) n from training_date_coverage where dataset='daily_training' group by 1").df().to_dict('records'),
        'anchors':len(a),'historical_prerace_availability_verified':False,'source_read_only':True}
    (c.OUT/'daily_query.sql').write_text(DAILY_SQL);(c.OUT/'window_query.sql').write_text(WINDOW_SQL)
    for lag in [2,7]:
        aa=a.copy();aa['cutoff']=aa.race_date-pd.Timedelta(days=lag);con.register('anchors',aa)
        z=con.execute(WINDOW_SQL).df();assert np.array_equal(z.anchor_id,a.anchor_id)
        f=add_personal(a,z,lag)
        cols=c.BASIC+c.PERSONAL+['training_source_max_date','self_latest_race_date']
        d=base[['row_number',*c.KEY]].merge(f[c.KEY+cols],on=c.KEY,how='left',validate='one_to_one').sort_values('row_number')
        assert len(d)==len(base) and d.train_coverage28.eq(1).all()
        cutoff=base.race_date-pd.Timedelta(days=lag)
        for col in ['training_source_max_date','self_latest_race_date']:assert (d[col].isna() | (d[col]<=cutoff)).all()
        d.to_parquet(c.OUT/f'feature_delta_t{lag}.parquet',index=False,compression='zstd')
        summary=base[['meet','year']].copy()
        summary['observed28']=d.train_days28.gt(0);summary['observed14']=d.train_days14.gt(0)
        summary['valid_minutes14']=d.train_minutes14.notna();summary['self_supported']=d.train_self_history_n.ge(2)
        summary['qa28']=d.train_qa_days28.gt(0);summary['n']=1
        audit[f't{lag}_coverage']=summary.groupby(['meet','year']).sum().reset_index().to_dict('records')
        audit[f't{lag}_missing_features']={k:int(d[k].isna().sum()) for k in c.BASIC+c.PERSONAL}
        print('Features ready',lag,len(d),'eval observed28',int(summary.loc[base.year>=2024,'observed28'].sum()),flush=True)
    con.close();c.save(c.OUT/'source_audit.json',audit)
    c.save(c.OUT/'feature_contract.json',{'basic':c.BASIC,'personal':c.PERSONAL,'personal_sources':c.PERSONAL_SOURCE,
        'cutoff_lags':[2,7],'model_names_are_current_study_only':True,'source_db_sha256':c.sha(c.CORE),
        'files':{str(p.relative_to(c.ROOT)):c.sha(p) for p in sorted(c.OUT.glob('feature_delta_*.parquet'))}})
    print('Storage',c.storage(),flush=True)
if __name__=='__main__':main()
