"""Compare exact website result rows and point labels with retained API observations."""
import csv,hashlib,json,re,sqlite3,collections
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
AUDIT=ROOT/'jeju/research/20261002_section_passing_audit/root_audit'
BASE=ROOT/'jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/20260929T143902.196014Z'
MAP={'S1F':('corner_7','passrankS1f','sjS1fOrd',3,'jeS1fTime'), '1C':('corner_1','passrankG8f_1c','sj_1cOrd',4,'je_1cTime'),'2C':('corner_2','passrankG6f_2c','sj_2cOrd',5,'je_2cTime'),'3C':('corner_3','passrankG4f_3c','sj_3cOrd',6,'je_3cTime'),'4C':('corner_4','passrankG3f_4c','sj_4cOrd',7,'je_4cTime'),'G1F':('corner_8','passrankG1f','sjG1fOrd',9,'jeG1fTime')}
LABEL={'S-1F':'S1F','1코너':'1C','2코너':'2C','3코너':'3C','4코너':'4C','G-1F':'G1F'}
def norm(v):
 v='' if v is None else re.sub(r'\s+','',str(v));return None if v in ('','-','X','0') else v

def rows(f):return list(csv.DictReader((AUDIT/f).open()))
def seconds(v):
 if not v:return None
 if ':' in str(v):
  m,s=v.split(':');value=int(m)*60+float(s)
 else:value=float(v)
 return value if value>0 else None

def table(web,header):return next(t['rows'] for t in web['tables'] if header in t['rows'][0])
def website_groups(web):
 out={}
 for row in table(web,'통과순위'):
  for cell in row:
   for label,point in LABEL.items():
    if cell.startswith(label+':'):out[point]=cell.split(':',1)[1].strip()
 return out

def write(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def main():
 websites=json.loads((OUT/'website_evidence.json').read_text());webs={(w['date'],w['race_no']):w for w in websites}
 for w in websites:
  path=OUT/w['raw_path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==w['sha256'];assert w['identity_verified']
 groups={k:website_groups(w) for k,w in webs.items()}
 api6={}
 manifest=json.loads((BASE/'run_manifest.json').read_text())
 for y in manifest['datasets']['detail_section']['yearly']:
  for page in y['pages']:
   payload=json.loads((BASE/page['response_file']).read_bytes())
   items=payload['response']['body']['items']['item'];items=items if isinstance(items,list) else [items]
   for r in items:
    d=str(r['rcDate']);key=(f'{d[:4]}-{d[4:6]}-{d[6:]}',int(r['rcNo']));api6[key]=r
 c=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 corner={}
 for r in c.execute('SELECT race_date,race_number,a.payload_json FROM api303_corner_rank_rows r JOIN api_records a USING(api_record_id)'):
  corner[(r[0],r[1])]=json.loads(r[2])
 days=sorted({k[0] for k in webs});marks=','.join('?' for _ in days)
 runners={}
 for r in c.execute('''SELECT r.*,a.payload_json FROM race_result_rows r JOIN api_records a USING(api_record_id) WHERE r.race_date IN ('''+marks+')',days):
  key=(r['race_date'],r['race_number'])
  if key in webs:
   runners[(key,r['horse_number'])]={'row':dict(r),'raw':json.loads(r['payload_json'])}
 runner_comparisons=[];source_groups=[];mismatches=[];checked_rosters=[];extra_times=[]
 for key,w in webs.items():
  main=table(w,'마명');tm=table(w,'S-1F');trows={int(r[1]):r for r in tm[1:]}
  html=BeautifulSoup((OUT/w['raw_path']).read_bytes(),'html.parser')
  ids={}
  for a in html.find_all('a',href=True):
   match=re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)",a['href'])
   if match:ids[a.get_text(strip=True)]=match[1]
  checked=0
  for row in main[1:]:
   try:num=int(row[1])
   except (ValueError,IndexError):continue
   data=runners.get((key,num));t=trows.get(num)
   if not data or not t:continue
   r=data['row'];raw=data['raw'];hid=ids.get(row[2])
   identity=hid==r['horse_id']
   name_equal=row[2].removeprefix('★')==r['horse_name']
   checked_rosters.append({'date':key[0],'race_no':key[1],'program_no':num,'horse_id':r['horse_id'],'website_horse_id':hid,'website_name':row[2],'api_name':r['horse_name'],'identity_equal':identity,'name_equal_ignoring_leading_star_marker':name_equal})
   assert identity,(key,num,'identity mismatch')
   ranks=[x.strip() for x in t[2].split('-')]
   # KRA renders a final unavailable G1F as an additional dash placeholder.
   if len(ranks)==7 and ranks[-1]=='':ranks.pop()
   assert len(ranks)==6,(key,num,ranks)
   for index,(point,(cf,sf,of,ti,tf)) in enumerate(MAP.items()):
    website_order=int(ranks[index]) if ranks[index] else None;api_order=raw.get(of);api_order=api_order if isinstance(api_order,(int,float)) and api_order>0 else None
    api_time=seconds(raw.get(tf));website_time=seconds(t[ti])
    obs={'date':key[0],'race_no':key[1],'program_no':num,'horse_id':r['horse_id'],'horse_name':row[2],'point':point,'api_order':api_order,'website_order':website_order,'api_time':api_time,'website_time':website_time,'orders_equal':api_order==website_order,'times_equal':api_time==website_time}
    runner_comparisons.append(obs)
    if not obs['orders_equal'] or not obs['times_equal']:mismatches.append(obs)
   for field,idx in [('jeG3fTime',8),('rcTime',10)]:
    at=seconds(raw.get(field));wt=seconds(t[idx]);extra_times.append({'date':key[0],'race_no':key[1],'program_no':num,'horse_id':r['horse_id'],'field':field,'api_time':at,'website_time':wt,'times_equal':at==wt})
   checked+=1
  for point,(cf,sf,of,ti,tf) in MAP.items():
   web=groups[key].get(point);cv=corner.get(key,{}).get(cf);sv=api6.get(key,{}).get(sf)
   source_groups.append({'date':key[0],'race_no':key[1],'point':point,'website_raw':web,'api303_field':cf,'api303_raw':cv,'api6_field':sf,'api6_raw':sv,'api303_equal_website':norm(cv)==norm(web),'api6_equal_website':norm(sv)==norm(web),'api6_present':key in api6,'api303_present':key in corner,'api303_value_matching_website_points':[p for p,v in groups[key].items() if norm(v) is not None and norm(cv)==norm(v)],'api6_value_matching_website_points':[p for p,v in groups[key].items() if norm(v) is not None and norm(sv)==norm(v)]})
 orders=[]
 for r in rows('api4_group_order_disagreements.csv'):
  key=(r['date'],int(r['race_no']));p=r['point'];num=int(r['program_no']);o=next(x for x in runner_comparisons if (x['date'],x['race_no'],x['program_no'],x['point'])==(*key,num,p));g=next(x for x in source_groups if (x['date'],x['race_no'],x['point'])==(*key,p))
  orders.append({**r,'website_order':o['website_order'],'api4_order_matches_website':o['orders_equal'],'website_group_raw':g['website_raw'],'api303_matches_website_group':g['api303_equal_website'],'api6_matches_website_group':g['api6_equal_website']})
 differences=[]
 for r in rows('api6_api303_raw_differences.csv'):
  key=(r['date'],int(r['race_no']),r['point']);g=next(x for x in source_groups if (x['date'],x['race_no'],x['point'])==key);differences.append({**r,**g})
 summary={'website_pages':len(websites),'page_hashes_and_event_identity_verified':True,'horse_rows_with_api_source':len(checked_rosters),'horse_ids_equal':all(x['identity_equal'] for x in checked_rosters),'horse_names_equal_ignoring_star_marker':all(x['name_equal_ignoring_leading_star_marker'] for x in checked_rosters),'horse_point_comparisons':len(runner_comparisons),'order_disagreements':sum(not x['orders_equal'] for x in runner_comparisons),'time_comparisons_including_g3f_finish':len(runner_comparisons)+len(extra_times),'time_disagreements':sum(not x['times_equal'] for x in runner_comparisons)+sum(not x['times_equal'] for x in extra_times),'flagged_order_observations':len(orders),'flagged_order_api_matches_website':sum(x['api4_order_matches_website'] for x in orders),'flagged_order_api303_group_matches_website':sum(x['api303_matches_website_group'] for x in orders),'flagged_order_api6_group_matches_website':sum(x['api6_matches_website_group'] for x in orders),'api6_api303_discrepant_points':len(differences),'discrepant_points_api6_equals_website':sum(x['api6_equal_website'] for x in differences),'discrepant_points_api303_equals_website':sum(x['api303_equal_website'] for x in differences),'all_group_api303_website_disagreements':sum(not x['api303_equal_website'] for x in source_groups),'all_group_api6_website_disagreements_when_present':sum(x['api6_present'] and not x['api6_equal_website'] for x in source_groups)}
 for file,data in [('website_comparison_summary.json',summary),('runner_website_comparisons.json',runner_comparisons),('runner_website_disagreements.json',mismatches),('g3f_finish_website_comparisons.json',extra_times),('group_website_comparisons.json',source_groups),('order_flag_website_review.json',orders),('legacy_difference_website_review.json',differences),('website_horse_identity_verification.json',checked_rosters)]:write(file,data)
 print(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(mismatches[:12],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
