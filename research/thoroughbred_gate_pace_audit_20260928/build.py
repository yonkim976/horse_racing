from collections import defaultdict,deque
import sqlite3
import numpy as np
import pandas as pd
from common import *

def main():
    with sqlite3.connect(f'file:{ROOT}/data/horse_racing.sqlite3?mode=ro',uri=True) as c:
        c.execute('pragma query_only=on')
        q='''SELECT r.id race_id,r.race_date_local race_date,r.race_number,r.distance_m,r.grade,r.track_condition,
        r.track_moisture_percent,r.field_size,r.scheduled_at_ms,r.actual_start_at_ms,
        rc.kra_meet_code meet,e.id entry_id,e.horse_id,h.kra_horse_id,h.name_ko horse_name,h.birth_date,
        e.horse_number,e.gate_number,e.carried_weight_kg,e.rating,e.scratched,
        rr.finish_position,rr.finish_time_ms,rr.disqualified,rr.rank_remark,
        s.position_raw s1f_position,s.elapsed_time_ms s1f_ms
        FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
        LEFT JOIN race_results rr ON rr.race_entry_id=e.id
        LEFT JOIN race_section_times s ON s.race_entry_id=e.id AND s.point_code='S1F' AND s.time_kind='cumulative'
        WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN '2015-01-01' AND '2026-09-20' '''
        f=pd.read_sql_query(q,c)
        p=pd.read_sql_query('''SELECT p.*,r.race_date_local race_date,r.race_number,rc.kra_meet_code meet FROM race_passing_groups p JOIN races r ON r.id=p.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN '2017-01-01' AND '2026-09-20' ''',c)
        batches=pd.read_sql_query('select * from race_point_source_batches where meet_code in (1,3) order by meet_code,race_year',c)
    assert not f.entry_id.duplicated().any()
    f.race_date=pd.to_datetime(f.race_date);f['venue']=f.meet.map({1:'SEOUL',3:'BUSAN'})
    f['age']=(f.race_date-pd.to_datetime(f.birth_date,errors='coerce')).dt.days/365.25
    f['valid_finish']=f.finish_position.between(1,20)&~f.disqualified.fillna(0).astype(bool)
    f['is_scratched']=f.scratched.fillna(0).astype(bool)|f.finish_position.isin([93,94,95])
    f['n_starters']=(~f.is_scratched).groupby(f.race_id).transform('sum')
    f['finish_pct']=(f.finish_position-1)/(f.n_starters-1)
    f['s1f_pct']=(f.s1f_position-1)/(f.n_starters-1)
    f.loc[~f.s1f_position.between(1,f.n_starters),'s1f_pct']=np.nan
    f.loc[~f.s1f_ms.between(10000,30000),'s1f_ms']=np.nan
    f['top3']=f.finish_position.le(3).astype(float);f['win']=f.finish_position.eq(1).astype(float)
    f=f.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
    state=defaultdict(lambda:{'form':deque(maxlen=5),'early':deque(maxlen=5),'starts':0,'last':None})
    prior=[]
    for date,g in f.groupby('race_date',sort=True):
        for row in g.itertuples(index=False):
            h=state[row.horse_id];prior.append((row.entry_id,np.mean([x[0] for x in h['form']]) if h['form'] else np.nan,np.mean([x[1] for x in h['form']]) if h['form'] else np.nan,np.mean(h['early']) if h['early'] else np.nan,h['starts'],(date-h['last']).days if h['last'] is not None else np.nan,h['last']))
        for row in g.itertuples(index=False):
            if row.is_scratched:continue
            h=state[row.horse_id];h['starts']+=1;h['last']=date
            if row.valid_finish:
                h['form'].append((row.finish_pct,row.top3))
                if pd.notna(row.s1f_pct):h['early'].append(row.s1f_pct)
    prior=pd.DataFrame(prior,columns=['entry_id','prior_finish5','prior_top3_5','prior_early5','prior_starts','days_since_last','last_history_date'])
    f=f.merge(prior,on='entry_id',validate='one_to_one');assert (f.last_history_date.isna()|f.last_history_date.lt(f.race_date)).all()
    eligible=[];excluded=[]
    for rid,g in f[f.race_date.ge('2017-01-01')].groupby('race_id',sort=False):
        g=g[~g.is_scratched];reason=None
        if len(g)<6:reason='fewer_than_6_starters'
        elif not g.valid_finish.all():reason='nonstandard_or_missing_result'
        elif sorted(g.finish_position.astype(int))!=list(range(1,len(g)+1)):reason='tie_or_incomplete_ranking'
        elif g.gate_number.isna().any() or g.gate_number.duplicated().any() or (g.gate_number<=0).any():reason='invalid_gate'
        if reason:excluded.append({'race_id':rid,'reason':reason})
        else:eligible.append(rid)
    d=f[f.race_id.isin(eligible)&~f.is_scratched].copy()
    d['n']=d.groupby('race_id').entry_id.transform('size')
    d['gate_pct']=(d.groupby('race_id').gate_number.rank(method='first')-.5)/d.n
    d['band']=np.where(d.gate_pct.le(1/3),'INNER',np.where(d.gate_pct.ge(2/3),'OUTER','MIDDLE'))
    d['s1f_ms_relative']=d.s1f_ms-d.groupby('race_id').s1f_ms.transform('median')
    d['year']=d.race_date.dt.year;d['month']=d.race_date.dt.month;d['quarter']=d.race_date.dt.to_period('Q').astype(str)
    d['condition']=d.track_condition.where(d.track_condition.isin(['건조','양호','다습','포화','불량']),'UNKNOWN')
    d['race_order_band']=np.where(d.race_number.le(3),'R1-3',np.where(d.race_number.le(6),'R4-6','R7+'))
    d['prior_style']=np.where(d.prior_early5.isna(),'UNKNOWN',np.where(d.prior_early5.lt(.35),'FRONT',np.where(d.prior_early5.gt(.65),'BACK','MIDDLE')))
    assert d.groupby('race_id').band.nunique().eq(3).all()
    d.to_parquet(OUT/'runners.parquet',index=False);p.to_parquet(OUT/'passing_raw.parquet',index=False)
    dump('source_batches.json',batches.to_dict('records'));dump('excluded_races.json',excluded)
    support=d.groupby('venue').agg(races=('race_id','nunique'),days=('race_date','nunique'),runners=('entry_id','size'),s1f_runners=('s1f_pct','count'),ratings=('rating','count')).reset_index()
    dump('quality.json',{'passed':True,'source_rows':len(f),'analysis':support.to_dict('records'),'excluded_races':len(excluded),'excluded_reasons':pd.Series([r['reason'] for r in excluded]).value_counts().to_dict(),'strict_prior_dates':True,'actual_start_nonmissing':int(d.actual_start_at_ms.notna().sum()),'scheduled_nonmissing':int(d.scheduled_at_ms.notna().sum()),'operational_db_read_only':True})
    print(support.to_string(index=False),flush=True)
if __name__=='__main__':main()
