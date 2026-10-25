"""Build a first-start cohort and features with a strict event-date T-2 cutoff."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
DB=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def main():
    OUT.mkdir(exist_ok=True)
    dbhash=sha(DB)
    c=duckdb.connect(str(DB),read_only=True)
    raw=c.execute('SELECT * FROM confirmed_runners').df()
    rank=pd.to_numeric(raw.result_rank_raw,errors='coerce')
    started=rank.between(1,89)|rank.isin([91,92])
    starts=raw[started].copy()
    starts['rank']=rank[started].astype(int)
    starts['date']=pd.to_datetime(starts.result_date,format='%Y%m%d')
    starts['horse_id']=starts.horse_id_raw.str.zfill(7)
    starts['meet']=starts.source_meet.map({'1':'서울','3':'부산','4':'영천'})
    starts['race_key']=starts.source_meet+':'+starts.result_date+':'+starts.result_race_no
    starts['row_key']=starts.race_key+':'+starts.horse_id
    assert starts.row_key.is_unique and starts.meet.notna().all()
    assert not starts[['horse_id','date']].duplicated().any()
    starts['win']=starts['rank'].eq(1).astype(int)
    starts['top3']=starts['rank'].between(1,3).astype(int)
    starts['field_size']=starts.groupby('race_key').horse_id.transform('size')
    starts['finish_p']=np.where(starts['rank'].between(1,89),(starts['rank']-1)/(starts.field_size-1).clip(lower=1),1.)
    starts=starts.sort_values(['horse_id','date']).reset_index(drop=True)
    first=starts.groupby('horse_id',sort=False).head(1).copy()
    starts['first_date']=starts.horse_id.map(first.set_index('horse_id').date)
    # Other domestic venues still disqualify a later Seoul/Busan start from being a debut.
    first=first[first.date.ge('2018-01-01')&first.source_meet.isin(['1','3'])].copy()
    first['year']=first.date.dt.year;first['month']=first.date.dt.month.astype(str)
    first['cutoff']=first.date-pd.Timedelta(days=2)
    first['domestic']=first.horse_origin_raw.eq('한국')
    first['age']=pd.to_numeric(first.horse_age_raw,errors='coerce')
    first['sex']=first.horse_sex_raw.fillna('미상')
    first['origin']=first.horse_origin_raw.fillna('미상')
    first['distance']=pd.to_numeric(first.race_distance_m_raw,errors='coerce')
    first['grade']=first.grade_raw.fillna('미상')
    first['gate']=pd.to_numeric(first.horse_program_no_raw,errors='coerce')
    first['gate_relative']=(first.gate-1)/(first.field_size-1).clip(lower=1)
    # Fixed SQL contains no interpolated request data.
    q="""SELECT e.participant_row_id,e.trial_session_id,e.trial_date,e.trial_no,
      e.source_meet_query,e.resolved_horse_id,e.resolved_horse_name,e.horse_identity_resolution,
      e.source_file,e.source_item_index,e.source_file_sha256,e.api_age,e.api_sex,
      e.api_reason,e.api_passFlag,e.api_track,e.api_wgBudam,e.api_wgHr,
      e.api_rcTime,e.api_rcTimeS1f,e.api_rcTimeG3f,e.api_rcTimeG1f,e.api_rcTimeG400,
      e.api_ord,e.api_s1f,e.api_g1f,e.api_g3f_4c,e.jockey_id_for_completed_trial,
      v.physical_venue,v.reviewed_distance_m
      FROM trial_participants_entity_reviewed e JOIN trial_participants_venue_reviewed v
      USING(participant_row_id)"""
    (OUT/'trial_query.sql').write_text(q+'\n')
    t=c.execute(q).df()
    assert t.participant_row_id.is_unique
    t['date']=pd.to_datetime(t.trial_date)
    t['horse_id']=t.resolved_horse_id.str.zfill(7)
    t['trial_meet']=t.source_meet_query.map({'1':'서울','3':'부산'})
    t['trial_month']=t.date.dt.month.astype(str)
    t['trial_age']=pd.to_numeric(t.api_age,errors='coerce')
    t['trial_sex']=t.api_sex.fillna('미상')
    t['trial_no_num']=pd.to_numeric(t.trial_no,errors='raise')
    t['trial_moisture']=pd.to_numeric(t.api_track.str.extract(r'(\d+(?:\.\d+)?)\s*%')[0],errors='coerce')
    t['trial_moisture_band']=pd.cut(t.trial_moisture,[0,5,9,14,19,np.inf],labels=['건조','양호','다습','포화','불량']).astype('string').fillna('미상')
    for col,field in [('trial_weight','api_wgBudam'),('trial_body_weight','api_wgHr'),('finish','api_rcTime'),
                      ('early','api_rcTimeS1f'),('last600','api_rcTimeG3f'),('late','api_rcTimeG1f'),('last400','api_rcTimeG400'),
                      ('trial_rank','api_ord'),('trial_early_rank','api_s1f'),('trial_late_rank','api_g1f')]:
        t[col]=pd.to_numeric(t[field],errors='coerce')
    t['middle1']=t.finish-t.early-t.last600
    t['middle2']=t.last600-t.late
    t['valid_finish']=t.finish.between(50,100)
    t['valid_sections']=t.valid_finish&t.early.between(10,30)&t.last600.between(25,60)&t.late.between(8,25)&t.middle1.between(8,30)&t.middle2.between(16,50)
    t['last400']=t.last400.where(t.last400.between(8,50)&t.last400.gt(t.late)&t.last400.lt(t.last600))
    t.loc[~t.valid_sections,['early','middle1','middle2','late','last600','last400']]=np.nan
    t['finish']=t.finish.where(t.valid_finish)
    t['fs200']=20*t.finish/t.late
    t['fs600']=60*t.finish/t.last600
    t['trial_position_gain']=t.trial_early_rank-t.trial_late_rank
    t['passed']=t.api_passFlag.eq('합격')
    t['new_reason']=t.api_reason.eq('주행미합(신)')
    t['failed']=t.api_passFlag.eq('불합격')
    t['practice']=t.api_passFlag.isin(['연습주행','주행연습'])
    session_valid=t[t.valid_finish].copy()
    sess=session_valid.groupby('trial_session_id').finish.agg(['min','count'])
    t['trial_session_n']=t.trial_session_id.map(sess['count'])
    t['trial_gap_to_fastest']=t.finish-t.trial_session_id.map(sess['min'])
    t['trial_time_pct']=t.groupby('trial_session_id').finish.rank(method='average',pct=True)
    t['trial_rank_relative']=(t.trial_rank-1)/(t.trial_session_n-1).clip(lower=1)
    t['trial_rank_relative']=t.trial_rank_relative.where(t.trial_rank.between(1,30))
    c.register('r',first[['row_key','horse_id','date','cutoff']])
    c.register('t',t)
    links_query="""WITH joined AS (
      SELECT r.row_key,t.* FROM r LEFT JOIN t ON t.horse_id=r.horse_id
        AND t.date<=r.cutoff AND t.date>=r.date-INTERVAL 365 DAY
    ) SELECT row_key,count(participant_row_id) AS trial_attempts,
      count(participant_row_id) FILTER(WHERE failed) AS trial_failures,
      count(participant_row_id) FILTER(WHERE practice) AS trial_practices,
      count(participant_row_id) FILTER(WHERE new_reason AND passed) AS new_passes,
      count(participant_row_id) FILTER(WHERE passed) AS trial_passes,
      arg_max(participant_row_id,struct_pack(d:=date,n:=trial_no_num,k:=participant_row_id)) FILTER(WHERE passed) AS selected_trial_id,
      min(finish) FILTER(WHERE passed) AS best_finish,
      arg_min(finish,struct_pack(d:=date,n:=trial_no_num,k:=participant_row_id)) FILTER(WHERE passed AND valid_finish) AS first_pass_finish,
      max(date) AS last_any_trial_date
      FROM joined GROUP BY row_key"""
    (OUT/'link_query.sql').write_text(links_query+'\n')
    links=c.execute(links_query).df()
    first=first.merge(links,on='row_key',validate='one_to_one')
    fields=['participant_row_id','date','trial_session_id','trial_meet','trial_month','trial_moisture','trial_moisture_band',
        'trial_age','trial_sex','trial_weight','trial_body_weight','valid_finish','valid_sections','finish','early','middle1','middle2',
        'last600','late','last400','fs200','fs600','trial_position_gain','trial_session_n','trial_gap_to_fastest','trial_time_pct',
        'trial_rank_relative','api_reason','source_file','source_item_index','source_file_sha256']
    selected=t[fields].rename(columns={'participant_row_id':'selected_trial_id','date':'selected_trial_date',
        'source_file':'trial_source_file','source_item_index':'trial_source_item_index','source_file_sha256':'trial_source_sha256','api_reason':'selected_trial_reason'})
    first=first.merge(selected,on='selected_trial_id',how='left',validate='many_to_one')
    first['trial_gap_days']=(first.date-first.selected_trial_date).dt.days
    first['trial_finish_change']=first.finish-first.first_pass_finish
    first['cross_venue_trial']=first.meet.ne(first.trial_meet).where(first.trial_meet.notna()).astype(float)
    first['primary_eligible']=first.domestic&first.new_passes.gt(0)&first.valid_finish.eq(True)
    assert (first.selected_trial_date.isna()|first.selected_trial_date.le(first.cutoff)).all()
    assert first.loc[first.primary_eligible,'trial_gap_days'].between(2,365).all()
    # Use only roster rows from races containing at least one first-start horse.
    field=starts[starts.race_key.isin(first.race_key)].copy()
    field['cutoff']=field.date-pd.Timedelta(days=2)
    c.register('all_starts',starts[['row_key','horse_id','date','race_key','win','top3','finish_p','jockey_id_raw','trainer_id_raw']])
    c.register('field',field[['row_key','horse_id','date','cutoff']])
    history_query="""WITH p AS (
      SELECT f.row_key,s.date AS prior_date,s.top3,s.finish_p,
        row_number() OVER(PARTITION BY f.row_key ORDER BY s.date DESC) AS slot
      FROM field f LEFT JOIN all_starts s ON s.horse_id=f.horse_id AND s.date<=f.cutoff
        AND s.date>=f.date-INTERVAL 730 DAY
    ) SELECT row_key,count(prior_date) AS prior_n5,avg(top3) AS prior_top3_mean5,
      avg(finish_p) AS prior_finish_p5,max(prior_date) AS history_last
      FROM p WHERE slot<=5 GROUP BY row_key"""
    (OUT/'history_query.sql').write_text(history_query+'\n')
    history=c.execute(history_query).df()
    field=field.merge(history,on='row_key',validate='one_to_one')
    field['has_previous_start']=field.first_date.le(field.cutoff).astype(int)
    field['prior_top3_mean5']=field.prior_top3_mean5.fillna(.25)
    field['prior_finish_p5']=field.prior_finish_p5.fillna(.5)
    field['debut_count']=field.groupby('race_key').has_previous_start.transform('size')-field.groupby('race_key').has_previous_start.transform('sum')
    field['field_experienced_other']=field.groupby('race_key').has_previous_start.transform('sum')-field.has_previous_start
    for col in ['prior_top3_mean5','prior_finish_p5']:
        field['other_'+col]=(field.groupby('race_key')[col].transform('sum')-field[col])/(field.field_size-1).clip(lower=1)
    field['other_best_top3']=field.groupby('race_key').prior_top3_mean5.transform('max')
    # Debutants have no previous record; exclude self exactly for the maximum as well.
    for _,ix in field.groupby('race_key').groups.items():
        values=field.loc[ix,'prior_top3_mean5'].to_numpy();index=np.array(list(ix))
        for j,idx in enumerate(index):field.loc[idx,'other_best_top3']=np.max(np.delete(values,j)) if len(values)>1 else np.nan
    assert (field.history_last.isna()|field.history_last.le(field.cutoff)).all()
    field_cols=['row_key','race_key','horse_id','date','history_last','prior_n5','prior_top3_mean5','prior_finish_p5',
        'debut_count','field_experienced_other','other_prior_top3_mean5','other_prior_finish_p5','other_best_top3']
    field[field_cols].to_parquet(OUT/'field_history_audit.parquet',index=False)
    first=first.merge(field[field_cols].drop(columns=['race_key','horse_id','date']),on='row_key',validate='one_to_one')
    assert first.loc[first.primary_eligible,'prior_n5'].eq(0).all()
    c.register('r',first[['row_key','date','cutoff','jockey_id_raw','trainer_id_raw']])
    people_query="""SELECT r.row_key,count(p.row_key) AS history_n,
      (coalesce(sum(p.win),0)+2)/(count(p.row_key)+20.0) AS prior_win,
      (coalesce(sum(p.top3),0)+5)/(count(p.row_key)+20.0) AS prior_top3,max(p.date) AS history_last
      FROM r LEFT JOIN all_starts p ON p.jockey_id_raw=r.jockey_id_raw
      AND r.jockey_id_raw!='' AND p.date<=r.cutoff AND p.date>=r.date-INTERVAL 365 DAY
      GROUP BY r.row_key"""
    (OUT/'people_query.sql').write_text(people_query+'\n')
    for role in ['jockey','trainer']:
        query=people_query if role=='jockey' else people_query.replace('jockey_id_raw','trainer_id_raw')
        person=c.execute(query).df().rename(columns={x:role+'_'+x for x in ['history_n','prior_win','prior_top3','history_last']})
        first=first.merge(person,on='row_key',validate='one_to_one')
        assert (first[role+'_history_last'].isna()|first[role+'_history_last'].le(first.cutoff)).all()
    c.close()
    first['coverage_status']=np.select([~first.domestic,first.trial_attempts.eq(0),first.new_passes.eq(0),~first.valid_finish.eq(True)],
        ['non_domestic_first_KRA_start','no_trial_in_window','no_new_horse_pass','latest_pass_time_invalid'],default='primary')
    coverage=first.groupby(['meet','year','coverage_status'],dropna=False).agg(n=('row_key','size'),wins=('win','sum'),top3=('top3','sum')).reset_index()
    coverage.to_csv(OUT/'coverage.csv',index=False)
    first.to_parquet(OUT/'debut_cohort.parquet',index=False)
    # Only modest trial feature inputs are duplicated; raw JSON remains in the frozen source DB.
    trial_cols=['participant_row_id','date','trial_meet','trial_month','trial_age','trial_sex','trial_weight',
        'trial_moisture_band','finish','early','middle1','middle2','late','valid_sections','passed','new_reason']
    t[trial_cols].to_parquet(OUT/'trial_reference_inputs.parquet',index=False)
    assert sha(DB)==dbhash
    dump(OUT/'source_audit.json',dict(inputs=[dict(path=str(DB.relative_to(ROOT)),bytes=DB.stat().st_size,sha256=dbhash)],
        raw_runner_rows=len(raw),actual_starts=len(starts),all_first_starts_2018plus=len(first),
        primary_rows=int(first.primary_eligible.sum()),trials=len(t),
        starts_end_by_meet={k:str(v.date()) for k,v in starts.groupby('meet').date.max().items()},
        role_codes=dict(started=[91,92],not_started=[0,93,94,95]),
        publication_time_certified=False,final_result_roster_is_entry_proxy=True,
        read_only=True,production_changed=False))
    print('COHORT',len(first),'PRIMARY',int(first.primary_eligible.sum()),flush=True)
    print(coverage.groupby(['meet','coverage_status']).n.sum().to_string(),flush=True)


if __name__=='__main__':main()
