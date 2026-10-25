"""Exact leader-pack sizes: individual rates and distinct group outcome events."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261020_actual_pack_top3_v1';DISTANCES=[800,900,1000,1110,1200,1300,1400,1610]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(g):return g.astype(object).where(pd.notna(g),None).to_dict('records')
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def source():
 a=pd.read_csv(OLD/'run01/race_groups.csv');return a[a.point.eq('s1f')&a.group_code.eq(0)].copy()
def main():
 out=HERE/'run01';out.mkdir(exist_ok=False);files=[HERE/'PLAN.md',OLD/'run01/race_groups.csv',OLD/'run01/runner_groups.csv',OLD/'run01/rates.csv',OLD/'verification01/verification.json',OLD/'artifact_manifest.json'];m=json.loads((OLD/'artifact_manifest.json').read_text());assert json.loads((OLD/'verification01/verification.json').read_text())['status']=='passed'
 for p in files[1:-1]:
  r=next(r for r in m['files'] if r['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 save(HERE/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'source_end':'2026-09-19','partial_2026':True,'database_opened':False})
 a=source();assert len(a)==5200 and a.race_id.nunique()==5200 and a.entries.sum()==10384 and a.top3_count.sum()==5007 and a.winner_count.sum()==2206 and a.entries.between(1,7).all();assert a.top3_count.between(0,3).all() and a.top3_count.le(a.entries).all()
 a['top3_category']=np.where(a.top3_count.eq(0),'0',np.where(a.top3_count.eq(1),'1','2+'));a.to_csv(out/'race_outcomes.csv',index=False,encoding='utf-8-sig');rows=[]
 for period,g in periods(a).items():
  for dist in ['all']+DISTANCES:
   z=g if dist=='all' else g[g.race_distance_m.eq(dist)]
   for n in range(1,8):
    h=z[z.entries.eq(n)];R=len(h);E=int(h.entries.sum());K=int(h.top3_count.sum());W=int(h.winner_count.sum());counts=[int(h.top3_count.eq(j).sum()) for j in range(4)];days=h.race_date.nunique()
    rows.append({'period':period,'distance':str(dist),'leader_count':n,'races':R,'leader_starts':E,'top3_horses':K,'winner_horses':W,'zero_top3_races':counts[0],'one_top3_races':counts[1],'two_top3_races':counts[2],'three_top3_races':counts[3],'two_plus_top3_races':counts[2]+counts[3],'any_top3_races':R-counts[0],'days':days,'individual_top3_pct':100*K/E if E else None,'individual_win_pct':100*W/E if E else None,'group_win_pct':100*W/R if R else None,'zero_top3_pct':100*counts[0]/R if R else None,'one_top3_pct':100*counts[1]/R if R else None,'two_top3_pct':100*counts[2]/R if R else None,'three_top3_pct':100*counts[3]/R if R else None,'two_plus_top3_pct':100*(counts[2]+counts[3])/R if R else None,'any_top3_pct':100*(R-counts[0])/R if R else None,'first_date':h.race_date.min() if R else None,'last_date':h.race_date.max() if R else None,'sample_status':'무표본' if not R else '소표본' if E<100 or R<30 or days<20 else '기준 충족'})
 rates=pd.DataFrame(rows);rates.to_csv(out/'rates.csv',index=False,encoding='utf-8-sig');save(out/'rates.json',clean(rates));print('OVERALL',flush=True);print(rates[(rates.period=='all')&(rates.distance=='all')][['leader_count','races','individual_top3_pct','individual_win_pct','group_win_pct','zero_top3_pct','one_top3_pct','two_plus_top3_pct','two_top3_races','three_top3_races']].round(3).to_string(index=False),flush=True)
 print('DISTANCES',flush=True);print(rates[(rates.period=='all')&(rates.distance!='all')&rates.races.gt(0)][['distance','leader_count','races','individual_top3_pct','individual_win_pct','group_win_pct','zero_top3_pct','one_top3_pct','two_plus_top3_pct']].round(2).to_string(index=False),flush=True)
if __name__=='__main__':main()
