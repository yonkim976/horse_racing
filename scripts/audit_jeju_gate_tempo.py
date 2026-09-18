"""Retrospective gate-position and official tempo association audit."""
import json
import re
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl
from scripts.analyze_jeju_conditions_questions import adjusted,records

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_gate_tempo_audit_20260917'
FEAT=ROOT/'data/research/jeju_tempo_pace_features_20260917'

def main():
    OUT.mkdir(exist_ok=False)
    original=pl.read_parquet(ROOT/'data/research/jeju_conditions_questions_20260917/race_entries.parquet')
    obs=pl.read_parquet(FEAT/'observations.parquet')
    keep=['entry_id','c3_rank','c4_rank','c3_seconds','c4_seconds','tempo','corner_4',
          'pace_c3_gap','pace_c4_gap','pace_pack_size','pace_pack_inner','event_number']
    d=pd.DataFrame(original.join(obs.select(keep),on='entry_id',validate='1:1').to_dicts())
    d['gate_group']=np.where(d.horse_number<=2,'inside12','other')
    d['gate3']=np.where(d.horse_number<=2,'1to2',np.where(d.horse_number<=5,'3to5','6plus'))
    result={};tables=[]
    for corner in ['c3','c4']:
        rank=corner+'_rank'
        d['improved_'+corner]=d.outcome_status.eq('normal_completed') & (d.finish_position<d[rank])
        d['gain_'+corner]=(d[rank]-d.finish_position).where(d.outcome_status.eq('normal_completed'))
        for lower in [3,4]:
            sub=d[d[rank]>=lower].copy()
            raw=records(sub.groupby('gate3').agg(entries=('entry_id','size'),races=('race_id','nunique'),
                improved=('improved_'+corner,'mean'),top3=('top3','mean'),gain=('gain_'+corner,'mean')).reset_index())
            result[corner+'_rank_ge'+str(lower)]=raw
            result[corner+'_rank_ge'+str(lower)+'_adjusted']=adjusted(sub,'gate_group','improved_'+corner,
                ['year_grade','distance_m','sex',rank],['elo_gap','field_size','age','burden_kg','pace_'+corner+'_gap'],'other')
            tables.append(sub[['entry_id','race_id','horse_id','event_date','gate_group',rank,'improved_'+corner,'top3']].assign(checkpoint=corner,minimum_rank=lower).rename(columns={rank:'corner_rank','improved_'+corner:'improved'}))
        result[corner+'_exact_rank']=records(d[d[rank]>=3].groupby([rank,'gate_group']).agg(
            entries=('entry_id','size'),improved=('improved_'+corner,'mean'),top3=('top3','mean')).reset_index())
        result[corner+'_by_distance']=records(d[d[rank]>=3].groupby(['distance_m','gate_group']).agg(
            entries=('entry_id','size'),improved=('improved_'+corner,'mean'),top3=('top3','mean')).reset_index())
    # Observed lateral location, not starting gate. Only explicit >=3-horse groups.
    pack=d[(d.c4_rank>=3)&d.pace_pack_size.ge(3)].copy()
    result['observed_pack']=records(pack.groupby('pace_pack_inner').agg(entries=('entry_id','size'),
         races=('race_id','nunique'),improved=('improved_c4','mean'),top3=('top3','mean')).reset_index())
    # Official tempo vs observed median race times (same outcome can enter official index).
    race=pd.DataFrame(pl.read_parquet(ROOT/'data/research/jeju_conditions_questions_20260917/race_track_summary.parquet').to_dicts())
    tempo=d.groupby('race_id').tempo.first().reset_index()
    race=race.merge(tempo,on='race_id',validate='one_to_one').dropna(subset=['tempo'])
    race['tempo_group']=race.tempo.astype(int).astype(str)
    result['tempo_by_distance']=records(race.groupby(['distance_m','tempo_group']).agg(
         races=('race_id','size'),days=('event_date','nunique'),seconds=('median_seconds','mean')).reset_index())
    result['tempo_adjusted']={str(dist):adjusted(g,'tempo_group','median_seconds',
        ['year_grade','month','track'],['mean_elo','mean_age','mean_burden','field_size'],'1')
        for dist,g in race.groupby('distance_m') if len(g)>=100}
    result['tempo_vs_moisture']=records(d.drop_duplicates('race_id').groupby(['tempo','track']).size().reset_index(name='races'))
    result['tempo_matched_races']=len(race)
    result['tempo_missing_races']=d[d.tempo.isna()].race_id.nunique()
    # Candidate evidence for human reading. Keyword matches are NOT event labels.
    c=sqlite3.connect('file:'+str(ROOT/'data/horse_racing.sqlite3')+'?mode=ro',uri=True)
    reports={(str(a).replace('-',''),b):str(t or '')+' '+str(u or '') for a,b,t,u in c.execute(
       "SELECT race_date_local,race_number,judgement,additional_judgement FROM race_steward_reports WHERE meet_code=2")}
    c.close();evidence=[]
    for row in d[(d.horse_number<=2)&(d.c4_rank>=3)&(~d.improved_c4)&(d.year.astype(int)>=2025)].itertuples():
        key=(row.event_date.strftime('%Y%m%d'),row.event_number)
        text=reports.get(key,'');marker='①②'[int(row.horse_number)-1]
        for bullet in text.split('●'):
            if marker in bullet and re.search('진로.{0,20}여의치|앞이 막|진로가 막|갇',bullet):
                evidence.append(dict(entry_id=row.entry_id,race_id=row.race_id,horse_id=row.horse_id,horse_number=row.horse_number,
                    date=key[0],race_number=row.event_number,c4_rank=row.c4_rank,finish=row.finish_position,
                    corner4=row.corner_4,raw_bullet=bullet.strip(),status='keyword_candidate_not_confirmed'))
    (OUT/'report_candidates.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=int))
    frame=pd.concat(tables,ignore_index=True).astype(object)
    pl.from_dicts(frame.where(pd.notna(frame),None).to_dict('records'),infer_schema_length=None).write_parquet(OUT/'gate_comparisons.parquet')
    print(json.dumps({k:v for k,v in result.items() if 'adjusted' in k or k in ['c3_rank_ge3','c4_rank_ge3','observed_pack','tempo_matched_races','tempo_missing_races']},ensure_ascii=False,default=int))
    print('report candidates',len(evidence))

if __name__=='__main__':main()
