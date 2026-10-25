"""One-horse first packs versus shared first packs in frozen complete races."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from scipy.stats import t
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261020_actual_pack_top3_v1'
DISTANCES=[800,900,1000,1110,1200,1300,1400,1610]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(a):return a.astype(object).where(pd.notna(a),None).to_dict('records')
def inputs():
 a=pd.read_csv(OLD/'run01/runner_groups.csv',dtype={'horse_id':str});r=pd.read_csv(OLD/'run01/race_groups.csv');r=r[r.group_code.eq(0)].copy();return a,r
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def stats(g):
 out={}
 for name,col in [('top3',g.top3),('win',g.finish_position.eq(1))]:
  n=len(g);y=100*col.astype(float);point=float(y.mean()) if n else None;out[name+'_rate_pp']=point
  for label,key in [('date','race_date'),('horse','horse_id')]:
   G=g[key].nunique()
   if G<2:out[name+'_'+label+'_low']=None;out[name+'_'+label+'_high']=None;continue
   score=(y-point).groupby(g[key]).sum();half=float(t.ppf(.975,G-1)*np.sqrt(float(score@score)/n**2*G/(G-1)));out[name+'_'+label+'_low']=point-half;out[name+'_'+label+'_high']=point+half
 return out
def main():
 out=HERE/'run01';out.mkdir(exist_ok=False);sources=[HERE/'PLAN.md',OLD/'run01/runner_groups.csv',OLD/'run01/race_groups.csv',OLD/'run01/rates.csv',OLD/'verification01/verification.json',OLD/'artifact_manifest.json']
 assert json.loads((OLD/'verification01/verification.json').read_text())['status']=='passed';m=json.loads((OLD/'artifact_manifest.json').read_text())
 for p in sources[1:-1]:
  r=next(r for r in m['files'] if r['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 save(HERE/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'data_upper':'2026-09-19','database_opened':False})
 a,r=inputs();leaders=a[a.group_code.eq(0)].merge(r[['point','race_id','entries','group_value']],on=['point','race_id'],validate='many_to_one').rename(columns={'entries':'leader_pack_n'});assert leaders[leaders.point.eq('s1f')].shape[0]==10384
 assert leaders.groupby(['point','race_id']).size().eq(leaders.groupby(['point','race_id']).leader_pack_n.first()).all()
 leaders['size_group']=np.where(leaders.leader_pack_n.eq(1),'solo',np.where(leaders.leader_pack_n.eq(2),'pair','three_plus'));leaders.to_csv(out/'leaders.csv',index=False,encoding='utf-8-sig');leaders[leaders.leader_pack_n.eq(1)].to_csv(out/'solo_starts.csv',index=False,encoding='utf-8-sig');rows=[]
 for point in ['s1f','c4']:
  for period,g in periods(leaders[leaders.point.eq(point)]).items():
   for dist in ['all']+DISTANCES:
    z=g if dist=='all' else g[g.race_distance_m.eq(dist)]
    for category in ['solo','pair','three_plus','shared']:
     h=z[z.leader_pack_n.ge(2)] if category=='shared' else z[z.size_group.eq(category)]
     rows.append({'point':point,'period':period,'distance':str(dist),'category':category,'starts':len(h),'races':h.race_id.nunique(),'horses':h.horse_id.nunique(),'days':h.race_date.nunique(),'top3':int(h.top3.sum()),'wins':int(h.finish_position.eq(1).sum()),'first_date':h.race_date.min() if len(h) else None,'last_date':h.race_date.max() if len(h) else None,'low_support':len(h)<100 or h.race_id.nunique()<30 or h.race_date.nunique()<20,**stats(h)})
 rates=pd.DataFrame(rows);rates.to_csv(out/'rates.csv',index=False,encoding='utf-8-sig');print(rates[(rates.point=='s1f')&(rates.distance=='all')][['period','category','starts','races','top3','wins','top3_rate_pp','win_rate_pp']].round(4).to_string(index=False),flush=True);print('DISTANCE SOLO',flush=True);print(rates[(rates.point=='s1f')&(rates.period=='all')&(rates.category=='solo')&(rates.distance!='all')][['distance','starts','top3','wins','top3_rate_pp','win_rate_pp']].round(4).to_string(index=False),flush=True)
if __name__=='__main__':main()
