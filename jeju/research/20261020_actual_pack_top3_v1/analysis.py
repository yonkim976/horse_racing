"""Observed passing packs, with race-complete denominators and separate rate meanings."""
from pathlib import Path
import json,hashlib,importlib.util
import numpy as np
import pandas as pd
from scipy.stats import t
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PRE=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2'
RESULTS=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv'
POINTS=ROOT/'jeju/research/20261008_passing_group_running_style_v1/run01/race_point_audit.csv'
PARSER=ROOT/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py'
DISTANCES=[800,900,1000,1110,1200,1300,1400,1610];NAMES={0:'첫 묶음 선두',1:'두 번째 묶음',2:'세 번째 이후 뒤쪽'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(a):return a.astype(object).where(pd.notna(a),None).to_dict('records')
def load():
 cols=['api_record_id','race_id','race_date','race_number','year','horse_id','horse_name','race_distance_m','field_n','horse_number','y_s1f_pack3','y_c4_pack3']
 a=pd.read_csv(PRE/'features01/features_and_targets.csv',usecols=cols,dtype={'horse_id':str},low_memory=False)
 r=pd.read_csv(RESULTS,usecols=['api_record_id','horse_id','race_id','finish_position','top3'],dtype={'horse_id':str},low_memory=False)
 return a.merge(r,on=['api_record_id','horse_id','race_id'],validate='one_to_one'),pd.read_csv(POINTS,low_memory=False)
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def interval(g):
 if not len(g):return {'rate_pp':None,'date_low':None,'date_high':None,'horse_low':None,'horse_high':None}
 y=100*g.top3.astype(float);point=float(y.mean());r={'rate_pp':point}
 for label,key in [('date','race_date'),('horse','horse_id')]:
  scores=(y-point).groupby(g[key]).sum();G=len(scores);half=float(t.ppf(.975,G-1)*np.sqrt(float(scores@scores)/len(g)**2*G/(G-1))) if G>1 else None
  r.update({label+'_low':point-half if half is not None else None,label+'_high':point+half if half is not None else None})
 return r
def main():
 out=HERE/'run01';out.mkdir(exist_ok=False)
 manifest=json.loads((PRE/'features01/source_manifest.json').read_text())
 for r in manifest['files']:
  if r['path'] in [str(RESULTS.relative_to(ROOT)),str(POINTS.relative_to(ROOT)),str(PARSER.relative_to(ROOT))]:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 frozen=json.loads((ROOT/'jeju/research/20261009_style_leader_density_v1/features01/source_manifest.json').read_text())
 expected=next(r for r in frozen['files'] if r['path']==str((PRE/'features01/features_and_targets.csv').relative_to(ROOT)));assert sha(ROOT/expected['path'])==expected['sha256']
 sources=[HERE/'PLAN.md',PRE/'features01/features_and_targets.csv',PRE/'features01/source_manifest.json',PRE/'verification01/verification.json',RESULTS,POINTS,PARSER]
 save(HERE/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'data_upper':'2026-09-19','database_opened':False,'observed_postrace_positions_used_as_groups':True})
 sp=importlib.util.spec_from_file_location('frozen_group_parser',PARSER);parser=importlib.util.module_from_spec(sp);sp.loader.exec_module(parser)
 a,points=load();assert len(a)==52155 and a.race_id.nunique()==5206 and a.horse_id.nunique()==2813 and not a.horse_id.eq('3005648').any();assert np.array_equal(a.top3,a.finish_position.le(3))
 px=points.set_index(['race_id','point']);detail=[];race_rows=[];census=[]
 for point in ['s1f','c4']:
  for race,g in a.groupby('race_id',sort=True):
   assert len(g)==g.field_n.iloc[0] and int(g.top3.sum())==3 and int(g.finish_position.eq(1).sum())==1
   r=px.loc[(race,point)];reason='usable';groups=None
   if r.parse_status!='usable_group_interval':reason='source_quality_or_notation_unavailable'
   elif g['y_'+point+'_pack3'].isna().any():reason='frozen_target_unavailable'
   else:
    groups=parser.parse_groups(r.group_value)
    if not groups:reason='unparsed'
    elif len([n for group in groups for n in group])!=len(g) or set(n for group in groups for n in group)!=set(g.horse_number):reason='roster_mismatch'
   base={'race_id':race,'race_date':g.race_date.iloc[0],'race_number':int(g.race_number.iloc[0]),'year':int(g.year.iloc[0]),'race_distance_m':int(g.race_distance_m.iloc[0]),'field_n':len(g),'point':point,'group_value':r.group_value if pd.notna(r.group_value) else None,'quality_status':r.quality_status,'usable':reason=='usable','reason':reason}
   census.append(base)
   if reason!='usable':continue
   mapping={n:min(i,2) for i,group in enumerate(groups) for n in group};d=g.copy();d['point']=point;d['group_code']=d.horse_number.map(mapping).astype(int);assert np.array_equal(d.group_code,d['y_'+point+'_pack3'].astype(int));d['group_name']=d.group_code.map(NAMES);detail.append(d)
   for code in [0,1,2]:
    z=d[d.group_code.eq(code)];nr=len(z);top=z[z.top3];wins=z[z.finish_position.eq(1)]
    race_rows.append({**base,'group_code':code,'group_name':NAMES[code],'entries':nr,'top3_count':len(top),'winner_count':len(wins),'rate_pp':100*len(top)/nr if nr else None,'present':nr>0,'has_top3':len(top)>0,'program_numbers':','.join(map(str,sorted(z.horse_number))),'top3_program_numbers':','.join(map(str,top.sort_values('finish_position').horse_number)),'winner_program_numbers':','.join(map(str,wins.horse_number))})
 d=pd.concat(detail,ignore_index=True);rr=pd.DataFrame(race_rows);cc=pd.DataFrame(census);d.to_csv(out/'runner_groups.csv',index=False,encoding='utf-8-sig');rr.to_csv(out/'race_groups.csv',index=False,encoding='utf-8-sig');cc.to_csv(out/'race_census.csv',index=False,encoding='utf-8-sig');rates=[];coverage=[]
 for point in ['s1f','c4']:
  for period,g in periods(d[d.point.eq(point)]).items():
   for distance in ['all']+DISTANCES:
    z=g if distance=='all' else g[g.race_distance_m.eq(distance)];races=z.race_id.unique();sub=rr[rr.point.eq(point)&rr.race_id.isin(races)];cr=cc[cc.point.eq(point)]
    if period=='2024_2025':cr=cr[cr.year.between(2024,2025)]
    elif period=='2026':cr=cr[cr.year.eq(2026)]
    if distance!='all':cr=cr[cr.race_distance_m.eq(distance)]
    base={'point':point,'period':period,'distance':str(distance),'eligible_races':len(races),'eligible_starts':len(z),'first_date':z.race_date.min() if len(z) else None,'last_date':z.race_date.max() if len(z) else None}
    coverage.append({**base,'source_races':len(cr),'excluded_races':int((~cr.usable).sum()),'source_starts':int(cr.field_n.sum())})
    for code in [0,1,2]:
     h=z[z.group_code.eq(code)];rs=sub[sub.group_code.eq(code)];present=rs[rs.present]
     rates.append({**base,'group_code':code,'group_name':NAMES[code],'starts':len(h),'top3':int(h.top3.sum()),'wins':int(h.finish_position.eq(1).sum()),'horses':h.horse_id.nunique(),'races_with_group':len(present),'dates':h.race_date.nunique(),'mean_group_size':float(rs.entries.mean()) if len(rs) else None,'top3_share_pp':100*int(h.top3.sum())/(3*len(races)) if len(races) else None,'win_rate_pp':100*h.finish_position.eq(1).mean() if len(h) else None,'race_any_top3_pp':100*present.has_top3.mean() if len(present) else None,'equal_race_mean_rate_pp':present.rate_pp.mean() if len(present) else None,'low_support':len(h)<100 or len(present)<30 or h.race_date.nunique()<20,**interval(h)})
 rates=pd.DataFrame(rates);rates.to_csv(out/'rates.csv',index=False,encoding='utf-8-sig');pd.DataFrame(coverage).to_csv(out/'coverage.csv',index=False,encoding='utf-8-sig')
 print('Overall observed packs',flush=True);print(rates.query("distance=='all'")[['point','period','eligible_races','group_name','starts','top3','rate_pp','top3_share_pp','race_any_top3_pp']].round(4).to_string(index=False),flush=True)
 print('S1F distance rates',flush=True);print(rates[(rates.point=='s1f')&(rates.period=='all')&(rates.distance!='all')][['distance','eligible_races','group_code','starts','top3','rate_pp']].round(4).to_string(index=False),flush=True)
if __name__=='__main__':main()
