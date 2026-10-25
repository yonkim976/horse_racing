"""Frozen recent weekly risk sets and raw-label medical families; read-only DuckDB input."""
from pathlib import Path
from collections import defaultdict
import json,re,hashlib
import numpy as np
import pandas as pd
import duckdb

H=Path(__file__).resolve().parent; ROOT=H.parents[2]; O=H/'outputs'
END=pd.Timestamp('2026-09-18')

# These are explicit lexical research groups, not clinical severity categories.
RULES=[
 ('post_arthroscopy','술후처치_관절경','술후처치.*관절경'),
 ('post_castration','술후처치_거세','술후처치.*거세'),
 ('post_other','술후처치_기타','술후처치'),
 ('fatigue','피로회복처치','피로회복'),
 ('vaccination','예방접종','예방접종'),
 ('dental','정치_발치','^(정치|발치)$'),
 ('sedation','진정처치','진정'),
 ('physical_therapy','물리치료_침치료','물리치료|침치료'),
 ('examination','마체검사_검진','마체검사|검진|혈액검사|방사선검사|초음파검사'),
 ('administrative','재료판매_진단서','재료판매|진단서'),
 ('myoglobinuria','마비성근색소뇨증','근색소뇨증'),
 ('corneal_abrasion','각막찰과상','각막찰과상'),
 ('keratitis','각막염','각막염'),
 ('interference','교돌상','교돌상'),
 ('lameness','파행','파행'),
 ('muscle_pain','근육통','근육통'),
 ('back_pain','요배통','요배통'),
 ('periostitis','골막염','골막염'),
 ('tendon_ligament','건_인대_건초문구','건염|인대염|건초염|계인대|건단열|건좌상|인대손상|인대파열'),
 ('sprain','염좌문구','염좌'),
 ('fetlock','구절염','구절염'),
 ('swelling','부종','부종'),
 ('cold','감기','^감기$'),
 ('bronchitis','기관지염','기관지염'),
 ('appetite','식욕부진','식욕부진'),
 ('skin','피부병_피부염','피부병|피부염|피부사상균'),
 ('abrasion_other','찰과상_각막제외','찰과상'),
 ('stomatitis','구내염','구내염'),
 ('colic','산통','산통'),
 ('bleeding','출혈문구','출혈'),
 ('fracture','골절문구','골절'),
 ('hoof','발굽관련문구','제엽염|제차부란|제염|제저|제구염'),
]
def family(s):
 for k,label,pattern in RULES:
  if re.search(pattern,s):return k
 return 'other'

def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 c=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
 # Exact raw slots, no comma splitting, inferred horse IDs, or archive/text union.
 med=c.execute('''select distinct linked_horse_official_id horse_id, event_date,
  meet_code, ill_name1_raw,ill_name2_raw from medical_current_api_records
  where linked_horse_official_id is not null''').df()
 rr=c.execute('''select * from runner_results where execution_status='executed_plan_and_result'
  and result_date>='20170101' ''').df();c.close()
 med['date']=pd.to_datetime(med.event_date)
 slots=pd.concat([med[['horse_id','date','meet_code']].assign(raw=med[f'ill_name{i}_raw']) for i in [1,2]],ignore_index=True)
 slots=slots[slots.raw.notna()&~slots.raw.isin(['','-'])].drop_duplicates(['horse_id','date','raw'])
 slots['family']=slots.raw.map(family)
 maprows=slots.groupby(['raw','family']).agg(observed_horse_days=('horse_id','size'),horses=('horse_id','nunique')).reset_index()
 maprows.to_csv(O/'raw_phrase_family_mapping.csv',index=False)
 fams=slots[['horse_id','date','family']].drop_duplicates().sort_values(['horse_id','family','date'])
 gap=fams.groupby(['horse_id','family']).date.diff().dt.days
 for gapdays in [7,14]:fams['new'+str(gapdays)]=gap.isna()|gap.gt(gapdays)
 fams.to_parquet(O/'medical_family_days.parquet',index=False)
 # Invalid/missing diagnosis days remain observation evidence and are a separate exposure.
 all_days=med[['horse_id','date']].drop_duplicates().sort_values(['horse_id','date'])
 r=rr.rename(columns={'horse_id_raw':'horse_id','horse_name_raw':'horse_name','source_meet':'meet'})
 r['date']=pd.to_datetime(r.result_date,format='%Y%m%d');r['rank']=pd.to_numeric(r.result_rank_raw,errors='coerce')
 r['race_key']=r.meet+':'+r.result_date+':'+r.result_race_no
 assert not r.duplicated(['horse_id','race_key']).any()
 r['normal']=r['rank'].between(1,89);r['started']=r.normal|r['rank'].isin([91,92])
 r['field']=r.started.groupby(r.race_key).transform('sum')
 r=r[r.started].copy().sort_values(['horse_id','date','race_key']).reset_index(drop=True)
 assert not r.duplicated(['horse_id','date']).any()
 r['top3']=r['rank'].le(3).astype(float)
 r['rank_badness']=np.where(r.normal,(r['rank']-1)/(r.field-1).replace(0,np.nan),1.)
 r['distance']=pd.to_numeric(r.race_distance_m_raw,errors='coerce')
 r['raw_time']=pd.to_numeric(r.finish_time_seconds_raw,errors='coerce')
 r['quality_time']=r.normal&r.raw_time.gt(0)&(r.distance/r.raw_time).between(8,22)
 r['time_good']=r.raw_time.where(r.quality_time)
 median=r.groupby('race_key').time_good.transform('median')
 r['time_loss']=(r.time_good-median)*1000/r.distance
 for source,dest in [('horse_age_raw','age'),('horse_rating_raw','rating'),('carried_weight_raw','weight'),('horse_program_no_raw','gate')]:
  r[dest]=pd.to_numeric(r[source],errors='coerce')
 r['body_weight']=pd.to_numeric(r.horse_weight_raw.str.extract(r'^(\d+(?:\.\d+)?)')[0],errors='coerce')
 r['grade']=pd.to_numeric(r.grade_raw.str.extract(r'(\d+)')[0],errors='coerce')
 r['previous_gap']=r.groupby('horse_id').date.diff().dt.days
 for target in ['rank_badness','top3','time_loss']:
  # At index, the most recent race and rolling means are already past information.
  r['mean5_'+target]=r.groupby('horse_id')[target].transform(lambda x:x.rolling(5,min_periods=1).mean())
 r['starts']=r.groupby('horse_id').cumcount()+1
 # Prior-calendar-year jockey/trainer levels contain no index-year future results.
 r['year']=r.date.dt.year
 for entity in ['jockey','trainer']:
  idcol=entity+'_id_raw';a=r.groupby(['meet','year',idcol]).agg(n=('top3','size'),s=('top3','sum')).reset_index()
  a['level']=(a.s+20*.25)/(a.n+20);a['year']+=1
  r=r.merge(a[['meet','year',idcol,'level']].rename(columns={'level':entity+'_prior_level'}),on=['meet','year',idcol],how='left',validate='many_to_one')
 r=r.sort_values(['horse_id','date','race_key']).reset_index(drop=True)
 r.to_parquet(O/'race_history.parquet',index=False)
 byhorse={k:g.reset_index(drop=True) for k,g in r.groupby('horse_id',sort=False)}
 md={k:g.date.to_numpy('datetime64[D]') for k,g in all_days.groupby('horse_id')}
 histories=defaultdict(dict)
 for (hid,fam),g in fams.groupby(['horse_id','family'],sort=False):
  histories[hid][fam]=(g.date.to_numpy('datetime64[D]'),g.new14.to_numpy(),g.new7.to_numpy())
 weeks=pd.date_range('2024-01-01','2026-03-16',freq='W-MON').to_numpy('datetime64[D]')
 records=[];families=[x[0] for x in RULES]+['other']
 for hid,ds in md.items():
  if hid not in byhorse:continue
  g=byhorse[hid];dates=g.date.to_numpy('datetime64[D]')
  for day in weeks:
   mi=np.searchsorted(ds,day-np.timedelta64(7,'D'))-1
   if mi<0 or (day-ds[mi]).astype(int)>365:continue
   j=np.searchsorted(dates,day)-1
   if j<0:continue
   elapsed=int((day-dates[j]).astype(int))
   if not 8<=elapsed<=180:continue
   # Any start exactly at index day belongs to follow-up, not pre-index controls.
   p=g.iloc[j];d={'horse_id':hid,'horse_name':p.horse_name,'index_date':pd.Timestamp(day),'year':pd.Timestamp(day).year,'meet':p.meet,
    'index_week':p.meet+':'+str(day),'prior_race_key':p.race_key,'prior_date':p.date,'elapsed':elapsed,
    'prev_rank':p.rank_badness,'prev_top3':p.top3,'prev_time':p.time_loss,
    'mean5_rank':p.mean5_rank_badness,'mean5_top3':p.mean5_top3,'mean5_time':p.mean5_time_loss,
    'prior_age':p.age,'prior_rating':p.rating,'prior_weight':p.weight,'prior_body_weight':p.body_weight,
    'prior_grade':p.grade,'prior_distance':p.distance,'prior_gap':p.previous_gap,'prior_starts':p.starts,
    'prior_trainer_level':p.trainer_prior_level,'prior_jockey_level':p.jockey_prior_level,
    'observed_history_days':int((day-ds[0]).astype(int))}
   hist=histories[hid]
   anyfamily=False
   for fam in families:
    a=hist.get(fam)
    for gapdays in [14,7]:d['new'+str(gapdays)+'_'+fam]=0
    d['ongoing14_'+fam]=d['ongoing7_'+fam]=0
    if a is None:continue
    dd,nn14,nn7=a;lo=np.searchsorted(dd,day-np.timedelta64(7,'D'));hi=np.searchsorted(dd,day)
    if hi<=lo:continue
    anyfamily=True
    for gapdays,nn in [(14,nn14),(7,nn7)]:
     onset=bool(nn[lo:hi].any());d['new'+str(gapdays)+'_'+fam]=int(onset);d['ongoing'+str(gapdays)+'_'+fam]=int(not onset)
   ml=np.searchsorted(ds,day-np.timedelta64(7,'D'));mh=np.searchsorted(ds,day)
   d['missing_diagnosis_week']=int(mh>ml and not anyfamily)
   nextj=j+1;wait=(dates[nextj]-day).astype(int) if nextj<len(dates) else 99999
   d['restricted_wait_180']=min(int(wait),180)
   for lim in [30,60,90,180]:d['no_start_'+str(lim)]=int(wait>lim)
   for h in [1,2,3]:
    qj=j+h
    if qj<len(g) and int((dates[qj]-day).astype(int))<=180:
     q=g.iloc[qj];d['date'+str(h)]=q.date;d['race'+str(h)]=q.race_key;d['top3_'+str(h)]=q.top3
     d['rank_'+str(h)]=q.rank_badness;d['time_'+str(h)]=q.time_loss
     d['interval_'+str(h)]=int((dates[qj]-day).astype(int));d['weight_'+str(h)]=q.weight
     d['body_'+str(h)]=q.body_weight;d['gate_'+str(h)]=q.gate/max(q.field,1)
     d['distance_change_'+str(h)]=q.distance-p.distance;d['grade_change_'+str(h)]=q.grade-p.grade
     d['jockey_level_'+str(h)]=q.jockey_prior_level;d['trainer_level_'+str(h)]=q.trainer_prior_level
    else:
     for key in ['date','race','top3_','rank_','time_','interval_','weight_','body_','gate_','distance_change_','grade_change_','jockey_level_','trainer_level_']:
      d[key+str(h)]=np.nan if key not in ['date','race'] else None
    d['no_top3_at_'+str(h)+'_by180']=int(not (d['top3_'+str(h)]==1))
   records.append(d)
 d=pd.DataFrame(records);d['row_id']=np.arange(len(d));d.to_parquet(O/'landmark_rows.parquet',index=False)
 labels={k:v for k,v,_ in RULES};labels['other']='기타원문';dump(O/'family_definitions.json',{'labels':labels,'rules':RULES,'one_raw_phrase_one_family':True,'clinical_severity_inferred':False})
 counts=[]
 for period,z in [('2024_2025',d[d.year.le(2025)]),('2024',d[d.year.eq(2024)]),('2025',d[d.year.eq(2025)]),('2026_partial',d[d.year.eq(2026)])]:
  for fam in families:
   a=z[z['new14_'+fam].eq(1)];counts.append(dict(period=period,family=fam,label=labels[fam],new_rows=len(a),new_horses=a.horse_id.nunique(),ongoing_rows=int(z['ongoing14_'+fam].sum())))
 pd.DataFrame(counts).to_csv(O/'exposure_counts.csv',index=False)
 audit=dict(medical_exact_tuples=len(med),medical_nonempty_horse_date_slots=len(slots),medical_family_days=len(fams),medical_horses=len(md),
  race_rows=len(r),race_quality_time=int(r.quality_time.sum()),special_started=int((~r.normal).sum()),landmark_rows=len(d),landmark_horses=d.horse_id.nunique(),
  periods=d.groupby('year').agg(rows=('horse_id','size'),horses=('horse_id','nunique')).reset_index().to_dict('records'),
  landmark_end=str(d.index_date.max().date()),common_race_cutoff=str(END.date()),
  same_day_medical_race_not_used=True,first_followup_at_or_after_index=True,
  any_180d_followup_cut_short=bool((d.index_date+pd.Timedelta(days=180)>END).any()))
 assert not audit['any_180d_followup_cut_short']
 dump(O/'source_audit.json',audit);print(json.dumps(audit,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
