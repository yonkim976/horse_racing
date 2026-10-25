"""Independently identify actual winning selections in latest complete API301 runs."""
from collections import defaultdict
from pathlib import Path
import hashlib
import itertools
import json
import math
import re
import sqlite3
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
POOLS={'WIN':1,'PLC':1,'QNL':2,'QPL':2,'EXA':2,'TLA':3,'TRI':3}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build():
 c=sqlite3.connect((ROOT/'data/horse_racing.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
 c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
 sql='''SELECT r.race_date_local,r.race_number,r.field_size,e.horse_number,e.scratched,z.finish_position,z.disqualified,h.kra_horse_id
 FROM races r JOIN racecourses c ON c.id=r.racecourse_id JOIN race_entries e ON e.race_id=r.id
 JOIN horses h ON h.id=e.horse_id LEFT JOIN race_results z ON z.race_entry_id=e.id
 WHERE c.kra_meet_code=? AND r.race_date_local BETWEEN ? AND ? AND r.status=?'''
 official=pd.read_sql_query(sql,c,params=(2,'2025-01-01','2026-09-19','completed'))
 docs=c.execute('SELECT id,local_path,sha256,request_params_json,retrieved_at_ms FROM source_documents WHERE endpoint=?',('/API301/Dividend_rate_total',)).fetchall();c.close()
 official['race_id']=official.race_date_local+'_2_'+official.race_number.astype(str)
 assert official.race_id.nunique()==1274
 targets=set(official.race_date_local);groups=defaultdict(dict);aliases=0
 for ident,location,digest,params,when in docs:
  params=json.loads(params);d=str(params.get('rc_date',''));day=f'{d[:4]}-{d[4:6]}-{d[6:8]}'
  if str(params.get('meet'))!='2' or day not in targets:continue
  page=int(params['pageNo']);size=int(params['numOfRows']);path=Path(location)
  if not path.is_absolute():path=ROOT/path
  path=path.resolve();assert path.is_relative_to(ROOT) and not path.is_symlink()
  match=re.search(r'(?:^|/)run_([^/]+)(?:/|$)',location)
  run=match.group(1) if match else 'verified-backfill'
  record={'id':ident,'path':path,'sha256':digest,'retrieved_at':when,'size':size}
  if page in groups[(day,run)]:
   old=groups[(day,run)][page];assert all(old[k]==record[k] for k in ['path','sha256','retrieved_at','size']);aliases+=1
  else:groups[(day,run)][page]=record
 latest={};read_cache={};complete_count=0
 for (day,run),pages in groups.items():
  totals=[];items=[];valid=True
  for page,record in sorted(pages.items()):
   path=record['path']
   if path not in read_cache:
    assert sha(path)==record['sha256'];payload=json.loads(path.read_bytes());body=payload['response'].get('body',{})
    rows=(body.get('items') or {}).get('item',[])
    if isinstance(rows,dict):rows=[rows]
    read_cache[path]=(body,rows)
   body,rows=read_cache[path];totals.append(int(body.get('totalCount') or 0))
   items.extend((row,record['sha256']) for row in rows)
  if not totals or len(set(totals))!=1 or len({r['size'] for r in pages.values()})!=1:continue
  total=totals[0];size=next(iter(pages.values()))['size']
  if set(pages)!=set(range(1,max(1,math.ceil(total/size))+1)) or len(items)!=total:continue
  allkeys=set();values={}
  for item,digest in items:
   rawday=str(item.get('rcDate',''));itemday=f'{rawday[:4]}-{rawday[4:6]}-{rawday[6:8]}'
   if item.get('meet')!='제주' or itemday!=day:continue
   pool=str(item.get('pool',''))
   if pool not in POOLS:continue
   numbers=[int(item[k]) for k in ['chulNo','chulNo2','chulNo3'][:POOLS[pool]]]
   if pool in ['QNL','QPL','TLA']:numbers.sort()
   key=(int(item['rcNo']),pool,'-'.join(map(str,numbers)))
   if key in allkeys:valid=False;break
   allkeys.add(key);values[key]=(item.get('odds'),digest)
  if not valid:continue
  complete_count+=1;order=(max(r['retrieved_at'] for r in pages.values()),run)
  if day not in latest or order>latest[day]['order']:latest[day]={'order':order,'values':values,'run':run,'pages':len(pages)}
 assert set(latest)==targets
 excluded_ids=set(json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses'])
 race_audit=[];winning=[]
 for rid,g in official.groupby('race_id',sort=True):
  active=g[g.scratched.eq(0)];n=len(active);assert n==g.field_size.iloc[0]
  clean=active[active.disqualified.eq(0)]
  ranks={rank:clean.loc[clean.finish_position.eq(rank),'horse_number'].astype(int).tolist() for rank in [1,2,3]}
  status='eligible';reason=''
  if g.kra_horse_id.astype(str).isin(excluded_ids).any():status='excluded';reason='excluded_horse'
  elif any(len(v)!=1 for v in ranks.values()):status='excluded';reason='nonunique_or_missing_podium'
  if status=='eligible':
   a,b,d=[ranks[k][0] for k in [1,2,3]];top=[a,b,d]
   keys={'WIN':[str(a)],'PLC':[str(v) for v in top[:3 if n>=8 else 2]],
    'QNL':['-'.join(map(str,sorted([a,b])))],'QPL':['-'.join(map(str,v)) for v in itertools.combinations(sorted(top),2)],
    'EXA':[f'{a}-{b}'],'TLA':['-'.join(map(str,sorted(top)))],'TRI':[f'{a}-{b}-{d}']}
   source=latest[g.race_date_local.iloc[0]];no=int(g.race_number.iloc[0]);rows=[]
   for pool,selections in keys.items():
    for selection in selections:
     quote=source['values'].get((no,pool,selection))
     try:odds=float(quote[0]) if quote else float('nan')
     except (ValueError,TypeError):odds=float('nan')
     if not math.isfinite(odds) or odds<1 or odds==9999.9:status='excluded';reason='winning_payout_missing_invalid_or_special';break
     rows.append({'race_id':rid,'race_date':g.race_date_local.iloc[0],'year':int(str(rid)[:4]),'pool':pool,
      'selection':selection,'odds':odds,'source_sha256':quote[1],'source_run_id':source['run']})
    if status!='eligible':break
   if status=='eligible':winning.extend(rows)
  race_audit.append({'race_id':rid,'race_date':g.race_date_local.iloc[0],'field_n':n,'status':status,'reason':reason})
 return pd.DataFrame(winning),pd.DataFrame(race_audit),{'candidate_races':1274,'target_dates':len(targets),'complete_runs':complete_count,
  'latest_complete_page_count':sum(v['pages'] for v in latest.values()),'registry_aliases':aliases,'raw_files_hash_checked':len(read_cache)}

def main():
 winning,audit,metadata=build()
 for name,frame in [('ROOT_WINNING_QUOTES.csv',winning),('ROOT_RACE_AUDIT.csv',audit)]:
  path=STUDY/name;assert not path.exists();frame.to_csv(path,index=False)
 metadata.update({'status':'PASS','histograms_or_frequency_percentages_computed':False,
  'eligible_races':int(audit.status.eq('eligible').sum()),'exclusion_counts':audit[audit.status.ne('eligible')].reason.value_counts().to_dict(),
  'winning_rows':len(winning),'winning_quote_sha256':sha(STUDY/'ROOT_WINNING_QUOTES.csv'),'race_audit_sha256':sha(STUDY/'ROOT_RACE_AUDIT.csv')})
 path=STUDY/'ROOT_SOURCE_REVIEW.json';assert not path.exists();path.write_text(json.dumps(metadata,indent=2)+'\n');print(json.dumps(metadata))

if __name__=='__main__':main()
