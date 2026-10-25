"""Top-five descriptive selection and separate all-starter top-five outcome models."""
from pathlib import Path
import hashlib,json
import numpy as np,pandas as pd
import model as m
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]

def descriptives(d):
 rows=[]
 for cohort,v in [('all',d),('top5',d[d.top5.eq(1)])]:
  for scope,keys in [('venue',['meet','sex']),('group',['meet','distance_group','sex']),('distance',['meet','distance_m','sex'])]:
   for k,g in v.groupby(keys):
    k=(k,) if not isinstance(k,tuple) else k
    a=dict(cohort=cohort,scope=scope,**dict(zip(keys,k)),n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique(),days=g.day_key.nunique(),top5_rate=g.top5.mean(),field_size_mean=g.field_size.mean())
    for c in ['body_weight','weight','finish','early','late','seconds_per_1000m']:
     a.update({c+'_mean':g[c].mean(),c+'_median':g[c].median(),c+'_p20':g[c].quantile(.2),c+'_p80':g[c].quantile(.8)})
    a['body_weight_horse_equal_mean']=g.groupby('horse_id').body_weight.mean().mean();rows.append(a)
 pd.DataFrame(rows).to_csv(O/'descriptives.csv',index=False)
 ledger=d.groupby(['meet','distance_group','sex']).agg(n=('sex','size'),selected_top5=('top5','sum'),races=('source_key','nunique')).reset_index()
 ledger['selected_fraction']=ledger.selected_top5/ledger.n;ledger.to_csv(O/'selection_ledger.csv',index=False)

def common_top5(v,a,b):
 q=v[v.sex.isin([a,b])];t=q[q.top5.eq(1)]
 keys=pd.MultiIndex.from_frame(t[t.groupby(m.FE,dropna=False).sex.transform('nunique').eq(2)][m.FE].drop_duplicates())
 return v[pd.MultiIndex.from_frame(v[m.FE]).isin(keys)]

def main():
 d=m.load();d['rank']=pd.to_numeric(d.rank_raw,errors='raise');d['top5']=d['rank'].between(1,5).astype(float)
 assert (d.win==d['rank'].eq(1)).all() and (d.top3==d['rank'].le(3)).all()
 assert d.groupby('source_key').top5.sum().le(5).all();descriptives(d)
 for meet,v in d.groupby('meet'):
  for a,b in m.PAIRS:
   for cohort,g in [('all',v),('top5',v[v.top5.eq(1)])]:
    for spec,keys in [('raw',[]),('grade',m.FE)]:
     m.run(g,a,b,keys,[],['body_weight','weight'],dict(scope='weight',meet=meet,cohort=cohort,specification=spec,window='all'))
 windows=[('all',d),('complete_2024_2025',d[d.year.isin([2024,2025])]),('field_size_10plus',d[d.field_size.ge(10)])]
 for window,df in windows:
  df=df[df.distance_group.ne('long')]
  for meet,v in df.groupby('meet'):
   for a,b in m.PAIRS:
    cohorts=[('all',v),('top5',v[v.top5.eq(1)])]
    if window=='all':cohorts.append(('all_in_top5_common_cells',common_top5(v,a,b)))
    for cohort,g in cohorts:
     for spec,cols in [('grade',[]),('full',m.LOAD+m.FORM)]:
      m.run(g,a,b,m.FE,cols,['finish','seconds_per_1000m','early','late'],dict(scope='time',meet=meet,cohort=cohort,specification=spec,window=window),joint=True)
    mixed=v[v.mixed_actual&v.complete_retained_race&~v.original_nonstandard&~v.sex_condition.eq('암')]
    for spec,cols in [('race',[]),('race_full',['age','age_squared']+m.LOAD+m.FORM)]:
     m.run(mixed,a,b,['source_key'],cols,['top5','top3','win'],dict(scope='race_outcome',meet=meet,cohort='all',specification=spec,window=window),joint=True)
     m.run(mixed[mixed.top5.eq(1)],a,b,['source_key'],cols,['finish','early','late'],dict(scope='race_selected_time',meet=meet,cohort='top5',specification=spec,window=window),joint=True)
 pd.DataFrame(m.RESULT).to_csv(O/'contrasts.csv',index=False)
 missing_keys=d.groupby('source_key').top5.sum().loc[lambda x:x.lt(5)].index
 ledger=pd.read_parquet(m.SOURCE/'outputs/selection_ledger.parquet')
 missing=ledger[ledger.source_key.isin(missing_keys)&ledger['rank'].between(1,5)&~ledger.selected]
 assert len(missing)==1 and missing.selection_reason.eq('section_quality_or_distance_parent').all()
 inputs=[m.SOURCE/'outputs/selection_ledger.parquet',m.SOURCE/'outputs/population.parquet',m.SOURCE/'outputs/source_audit.json',H.parent/'20261007_sex_weight_distance_followup/analyze.py',H.parent/'20261007_sex_weight_distance_followup/outputs/joint_contrasts.csv']
 audit=dict(input_n=len(d),top5_n=int(d.top5.sum()),races=d.source_key.nunique(),horses=d.horse_id.nunique(),inputs_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},date_start=d.groupby('meet').date.min().astype(str).to_dict(),date_end=d.groupby('meet').date.max().astype(str).to_dict(),missing_selected_top5=missing[['row_key','sex_raw','rank','selection_reason']].to_dict('records'),source_sex='at race',selection='rank_raw numeric 1..5',top5_outcome_uses_all_starters_in_retained_complete_mixed_races=True,model_code='model.py copied from prior followup before main(), top5 outcome scaled to percentage points',uncertainty='max(two-way horse/date, horse-only,date-only); FE degrees and t correction; pointwise 95%',no_new_source_requests=True,no_existing_research_or_operational_changes=True,limitations=['post-outcome selection changes the question and can shrink gaps','one outing not permanent elite classification','exact overlap differs across selected/unselected cohorts','top5 is not constant percentile across field sizes','selected normal-finish cohort','long-distance females sparse','recent analyses use overlapping data'])
 (O/'source_and_method.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
 print('top5',int(d.top5.sum()),'saved',len(m.RESULT),'contrasts')
if __name__=='__main__':main()
