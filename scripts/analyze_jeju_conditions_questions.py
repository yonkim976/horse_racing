"""Descriptive retrospective answers; never alters prediction models or inputs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
HISTORY = ROOT / 'data/research/jeju_native_transition_features_v1_20260916/context_history.parquet'
OUT = ROOT / 'data/research/jeju_conditions_questions_20260917'


def records(df):
    return json.loads(df.to_json(orient='records', force_ascii=False))


def rates(df, keys):
    return records(df.groupby(keys, observed=True).agg(
        entries=('entry_id', 'size'), races=('race_id', 'nunique'),
        horses=('horse_id', 'nunique'), top3=('top3', 'sum'),
        top3_rate=('top3', 'mean'), win_rate=('win', 'mean'),
    ).reset_index())


def adjusted(df, treatment, outcome, categorical, numeric, baseline):
    """Exploratory OLS association with horse/day two-way cluster covariance.

    No causal identification; no out-of-time prediction claim. Day-only for
    race-level track summaries. Complete cases, explicit baseline.
    """
    cols = list(dict.fromkeys([treatment, outcome, 'event_date', *categorical, *numeric]))
    if 'horse_id' in df:
        cols.append('horse_id')
    d = df[cols].dropna().copy()
    levels = [baseline] + sorted(set(d[treatment].astype(str)) - {baseline})
    d[treatment] = pd.Categorical(d[treatment], categories=levels)
    cats = pd.get_dummies(d[[treatment, *categorical]].astype({c: 'category' for c in categorical}),
                          drop_first=True, dtype=float)
    nums = d[numeric].astype(float)
    nums = (nums - nums.mean()) / nums.std().replace(0, 1)
    design = pd.concat([pd.Series(1., index=d.index, name='intercept'), cats, nums], axis=1)
    x, y = design.to_numpy(), d[outcome].to_numpy(float)
    bread = np.linalg.pinv(x.T @ x)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    score = x * (y - x @ beta)[:, None]
    def meat(group):
        ix, names = pd.factorize(group)
        sums = np.zeros((len(names), x.shape[1]))
        np.add.at(sums, ix, score)
        g = len(names)
        return sums.T @ sums * g / max(g - 1, 1) * (len(d)-1) / max(len(d)-x.shape[1], 1)
    cov = meat(d.event_date.astype(str))
    if 'horse_id' in d:
        cov += meat(d.horse_id) - meat(d.horse_id.astype(str) + '/' + d.event_date.astype(str))
    cov = bread @ cov @ bread
    result = []
    for i, name in enumerate(design.columns):
        if name.startswith(treatment + '_'):
            se = np.sqrt(max(cov[i, i], 0))
            result.append(dict(term=name, estimate=float(beta[i]),
                               low95=float(beta[i]-1.96*se), high95=float(beta[i]+1.96*se)))
    return dict(n=len(d), days=d.event_date.nunique(), baseline=baseline,
                rank=int(np.linalg.matrix_rank(x)), columns=x.shape[1],
                controls=categorical+numeric, contrasts=result)


def main():
    OUT.mkdir(exist_ok=False)
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    src = pd.read_sql_query("""
      SELECT e.id entry_id, v.id race_id, v.event_date, v.event_type,
        v.distance_m, v.grade, e.hr_no horse_id, e.horse_name,
        e.finish_time_ms, e.finish_position, e.segment_quality,
        v.track_moisture_percent, e.record_status, e.identity_status,
        json_extract(s.normalized_json,'$.age') age,
        json_extract(s.normalized_json,'$.sj_4cOrd') corner4_rank,
        json_extract(s.normalized_json,'$.je_4cTime') corner4_seconds,
        json_extract(s.normalized_json,'$.jeS1fTime') s1f_seconds,
        json_extract(s.normalized_json,'$.sex') sex,
        json_extract(s.normalized_json,'$.trial_result.judgement') trial_judgement
      FROM entry e JOIN event v ON v.id=e.event_id
      JOIN source_row s ON s.id=e.source_row_id
      WHERE v.event_date<='20260912' AND e.hr_no IS NOT NULL
        AND e.breed_status='native_confirmed'
    """, c)
    sec = pd.read_sql_query("""SELECT entry_id, section_code, source_value_ms
          FROM section_checkpoint WHERE section_code in ('S1F','G1F')""", c)
    c.close()
    src['event_date'] = pd.to_datetime(src.event_date, format='%Y%m%d')
    h = pd.DataFrame(pl.read_parquet(HISTORY).to_dicts())
    h.event_date = pd.to_datetime(h.event_date)
    extra = ['entry_id','distance_m','grade','age','sex','corner4_rank','corner4_seconds','s1f_seconds','segment_quality']
    h = h.merge(src.loc[src.event_type.eq('race'), extra], on='entry_id', validate='one_to_one')
    h = h.sort_values(['horse_id','event_date','entry_id'])
    h['top3'] = h.outcome_status.eq('normal_completed') & h.finish_position.between(1,3)
    h['win'] = h.outcome_status.eq('normal_completed') & h.finish_position.eq(1)
    h['gap_days'] = h.groupby('horse_id').event_date.diff().dt.days
    h['previous_weight'] = h.groupby('horse_id').body_weight_kg.shift()
    h['weight_change'] = h.body_weight_kg - h.previous_weight
    h['year'] = h.event_date.dt.year.astype(str)
    h['month'] = h.event_date.dt.month.astype(str)
    h['year_grade'] = h.year + '/' + h.grade.fillna('unknown')
    h['elo_gap'] = h.global_elo_pre - h.rival_elo_mean
    h['track'] = pd.cut(h.track_moisture_percent, [0,5,9,14,19,100],
                         labels=['dry','good','moist','saturated','sloppy'])
    # Strictly prior successful weight in the SAME exact distance; no future best weight.
    reference = {}
    for _, g in h.groupby(['horse_id','distance_m'], sort=False):
        past=[]
        for row in g.itertuples():
            reference[row.entry_id] = np.median(past[-5:]) if len(past)>=3 else np.nan
            if row.top3 and pd.notna(row.body_weight_kg):
                past.append(row.body_weight_kg)
    h['prior_good_weight'] = h.entry_id.map(reference)
    h['weight_distance_pct'] = (h.body_weight_kg-h.prior_good_weight).abs()/h.prior_good_weight*100
    h['weight_proximity'] = pd.cut(h.weight_distance_pct, [-1,1,2,100],labels=['within1pct','1to2pct','over2pct'])
    # Recent era; the year/grade interaction keeps policy regimes separate.
    d = h[h.event_date.between('2023-01-01','2026-09-12') & h.distance_m.ge(800)].copy()
    d['interval'] = pd.cut(d.gap_days,[0,14,28,42,84,np.inf],labels=['1to14','15to28','29to42','43to84','85plus'])
    d['weight_bin'] = pd.cut(d.body_weight_kg,[0,260,280,300,320,1000],right=False,
                              labels=['under260','260to279','280to299','300to319','320plus'])
    for name in ['early_rank','corner4_rank','late_rank']:
        d[name] = pd.to_numeric(d[name],errors='coerce')
        d.loc[~d[name].between(1,d.field_size),name]=np.nan
        d[name+'_group'] = pd.cut(d[name],[0,1,3,5,100],labels=['1','2to3','4to5','6plus'])
    result = dict(period=['2023-01-01','2026-09-12'], entries=len(d),races=d.race_id.nunique(),
                  horses=d.horse_id.nunique(), days=d.event_date.nunique(),
                  body_weight_known=int(d.body_weight_kg.notna().sum()),
                  descriptive_not_causal=True, multiple_testing_adjusted=False)
    result['distance_counts']=rates(d,['distance_m'])
    for name in ['early_rank','corner4_rank','late_rank']:
        result[name]=rates(d.dropna(subset=[name]),['distance_m',name+'_group'])
    result['interval']=rates(d.dropna(subset=['interval']),['interval'])
    result['interval_by_year']=rates(d.dropna(subset=['interval']),['year','interval'])
    result['bodyweight_by_distance']=rates(d.dropna(subset=['weight_bin']),['distance_m','weight_bin'])
    result['good_weight_proximity']=rates(d.dropna(subset=['weight_proximity']),['weight_proximity'])
    result['interval_adjusted']=adjusted(d,'interval','top3',
       ['year_grade','month','distance_m','sex'],['elo_gap','field_size','age','burden_kg'],'15to28')
    result['good_weight_adjusted']=adjusted(d,'weight_proximity','top3',
       ['year_grade','month','distance_m','sex'],['elo_gap','field_size','age','burden_kg'],'within1pct')
    # Each race contributes one median, not N correlated runners; usable normal finishes.
    speed=d[d.outcome_status.eq('normal_completed') & d.segment_quality.eq('usable') & d.finish_time_ms.gt(0)].copy()
    speed['seconds']=speed.finish_time_ms/1000
    race=speed.groupby('race_id').agg(event_date=('event_date','first'),distance_m=('distance_m','first'),
       year_grade=('year_grade','first'),month=('month','first'),track=('track','first'),
       median_seconds=('seconds','median'),mean_elo=('global_elo_pre','mean'),
       mean_age=('age','mean'),mean_burden=('burden_kg','mean'),field_size=('field_size','first')).reset_index()
    result['track_by_distance']=records(race.groupby(['distance_m','track'],observed=True).agg(
       races=('race_id','size'),mean_race_median_seconds=('median_seconds','mean')).reset_index())
    result['track_adjusted']={str(dist):adjusted(g,'track','median_seconds',['year_grade','month'],
       ['mean_elo','mean_age','mean_burden','field_size'],'dry') for dist,g in race.groupby('distance_m') if len(g)>=100}
    # Only observed time-gap proxies, NOT proof of sustained contest or physical spacing.
    gaps={}
    for rid,g in d.groupby('race_id'):
        x=g.loc[g.corner4_seconds.gt(0),'corner4_seconds'].sort_values()
        gaps[rid]=float(x.iloc[1]-x.iloc[0]) if len(x)>=2 else np.nan
    d['corner4_lead_seconds']=d.race_id.map(gaps)
    leaders=d[d.early_rank.eq(1)&d.corner4_rank.eq(1)&d.corner4_lead_seconds.notna()].copy()
    leaders['lead_gap_group']=pd.cut(leaders.corner4_lead_seconds,[-.01,.2,.5,np.inf],
                                    labels=['at_most_0.2s','over0.2_to0.5s','over0.5s'])
    result['lead_gap_proxy']=rates(leaders,['lead_gap_group'])
    # Trial -> FIRST subsequent race, <=90d. Exactly one row per race, latest preceding trial.
    trials=src[src.event_type.eq('trial') & src.finish_time_ms.gt(0)].copy()
    races=src[src.event_type.eq('race')].copy()
    follow=[]
    racegroups={k:g.sort_values('event_date') for k,g in races.groupby('horse_id')}
    for horse,g in trials.groupby('horse_id'):
        rr=racegroups.get(horse)
        if rr is None: continue
        for row in g.itertuples():
            pos=rr.event_date.searchsorted(row.event_date,side='right')
            if pos>=len(rr): continue
            nxt=rr.iloc[pos]
            gap=(nxt.event_date-row.event_date).days
            if gap>90 or gap<2 or nxt.event_date<pd.Timestamp('2023-01-01'): continue
            if not (0<nxt.finish_position<90 and nxt.finish_time_ms>0 and nxt.segment_quality=='usable'): continue
            follow.append(dict(trial_entry_id=row.entry_id,race_entry_id=int(nxt.entry_id),horse_id=horse,
               trial_date=row.event_date,race_date=nxt.event_date,gap_days=gap,
               trial_distance=row.distance_m,race_distance=nxt.distance_m,judgement=row.trial_judgement,
               trial_seconds=row.finish_time_ms/1000,race_seconds=nxt.finish_time_ms/1000,
               trial_moisture=row.track_moisture_percent,race_moisture=nxt.track_moisture_percent))
    p=pd.DataFrame(follow).sort_values('trial_date').drop_duplicates('race_entry_id',keep='last')
    assert not sec.duplicated(['entry_id','section_code']).any()
    sections=sec.pivot(index='entry_id',columns='section_code',values='source_value_ms')/1000
    for label,key in [('trial','trial_entry_id'),('race','race_entry_id')]:
        p=p.merge(sections.add_prefix(label+'_'),left_on=key,right_index=True,how='left',validate='many_to_one')
    p['total_delta_seconds']=p.race_seconds-p.trial_seconds
    p['early_delta_seconds']=p.race_S1F-p.trial_S1F
    p['closing_delta_seconds']=p.race_G1F-p.trial_G1F
    same=p[p.trial_distance.eq(p.race_distance)].copy()
    result['trial_pair_counts']=dict(all_pairs=len(p),same_distance=len(same),horses=same.horse_id.nunique())
    result['trial_vs_race']=records(same.groupby(['trial_distance','judgement'],dropna=False).agg(
       pairs=('race_entry_id','size'),trial_mean=('trial_seconds','mean'),race_mean=('race_seconds','mean'),
       mean_delta=('total_delta_seconds','mean'),median_delta=('total_delta_seconds','median'),
       delta_q25=('total_delta_seconds',lambda s:s.quantile(.25)),delta_q75=('total_delta_seconds',lambda s:s.quantile(.75)),
       early_mean_delta=('early_delta_seconds','mean'),closing_mean_delta=('closing_delta_seconds','mean')).reset_index())
    result['trial_800_to_race900_sections']=records(p[p.trial_distance.eq(800)&p.race_distance.eq(900)].groupby('judgement').agg(
       pairs=('race_entry_id','size'),early_mean_delta=('early_delta_seconds','mean'),
       closing_mean_delta=('closing_delta_seconds','mean')).reset_index())
    # Reproducibility checks: no future label in reference; one unique target per trial pair table.
    assert h.entry_id.is_unique and d.entry_id.is_unique and p.race_entry_id.is_unique
    assert p.gap_days.between(2,90).all() and (p.trial_date<p.race_date).all()
    assert d.event_date.max()<=pd.Timestamp('2026-09-12')
    assert d.top3.sum()==((d.finish_position<=3)&d.outcome_status.eq('normal_completed')).sum()
    for frame,name in [(d,'race_entries'),(race,'race_track_summary'),(p,'trial_next_race_pairs')]:
        clean=frame.astype(object).where(pd.notna(frame),None)
        pl.from_dicts(clean.to_dict('records'), infer_schema_length=None).write_parquet(OUT/(name+'.parquet'))
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=lambda x:int(x)),encoding='utf-8')
    sources=[DB,HISTORY,Path(__file__)]
    sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
    manifest=dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in sources},
                  outputs={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
                  checks='unique keys, chronological pairs, 90d limit, end date, top3 reconciliation passed')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['bodyweight_by_distance','early_rank','corner4_rank','late_rank','interval_by_year','track_by_distance']},ensure_ascii=False,default=lambda x:int(x)))


if __name__=='__main__':
    main()
