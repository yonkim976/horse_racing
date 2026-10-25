"""Verify all API080626 observations against five captured official day pages."""
import hashlib,json,re
from collections import Counter,defaultdict
from pathlib import Path
import duckdb
from bs4 import BeautifulSoup
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(path):
 with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 captures={r['name']:r for r in map(json.loads,(HERE/'official_web/capture_manifest.jsonl').read_text().splitlines())}
 indexed=defaultdict(list)
 for name,r in captures.items():
  path=(HERE/r['file']).resolve()
  assert path.is_relative_to(HERE) and sha(path)==r['sha256']
  if not name.startswith('yeongnam_daily_'): continue
  soup=BeautifulSoup(path.read_bytes().decode('cp949'),'html.parser')
  date=r['request_form']['trDate']
  assert date in soup.get_text(' ',strip=True)
  tables=[t for t in soup.find_all('table') if t.find('caption') and '전체일별상세조교현황' in t.find('caption').get_text()]
  assert len(tables)==1
  for tr in tables[0].find_all('tr'):
   cells=tr.find_all('td',recursive=False)
   if not cells: continue
   assert len(cells)==13
   values=[c.get_text(' ',strip=True) for c in cells]
   horse=re.fullmatch(r"javascript:goPage4\('([0-9]+)'\)",cells[3].find('a')['href'])
   assert horse
   indexed[(date.replace('/','-'),'3',horse[1],values[7],values[8])].append({'web_values':values,'web_sha256':r['sha256'],'web_file':r['file'],'web_url':r['url'],'web_request_form':r['request_form']})
 con=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
 q=con.execute('SELECT observation_id,event_date,meet,official_horse_id,horse_name_raw,rider_type_raw,rider_id_raw,started_at_raw,ended_at_raw,raw_path,raw_sha256,source_page_no,source_row_no FROM daily_training_raw WHERE rider_id_raw=? ORDER BY event_date,started_at_raw',['080626'])
 columns=[c[0] for c in q.description]
 rows=[dict(zip(columns,r)) for r in q.fetchall()]
 roles=dict(con.execute('select rider_type_raw,count(*) from daily_training_raw group by 1 order by 2 desc').fetchall())
 con.close()
 evidence=[]; sources={}
 for row in rows:
  row['event_date']=str(row['event_date'])
  hhmm=lambda v: v[-6:-4]+':'+v[-4:-2]
  key=(row['event_date'],row['meet'],row['official_horse_id'],hhmm(row['started_at_raw']),hhmm(row['ended_at_raw']))
  matches=indexed[key]
  assert len(matches)==1,(key,len(matches))
  web=matches[0]
  assert web['web_values'][3]==row['horse_name_raw']
  path=(ROOT/row['raw_path']).resolve()
  assert path.is_relative_to(ROOT)
  if row['raw_path'] not in sources:
   assert sha(path)==row['raw_sha256']
   sources[row['raw_path']]=row['raw_sha256']
  evidence.append({**row,**web,'web_rider_name':web['web_values'][5],'official_profile_candidate_id':'080584','identity_note':'same-event displayed name verified; relationship between raw080626 and official080584 not established'})
 assert len(evidence)==31
 names=Counter(r['web_rider_name'] for r in evidence)
 assert names=={'다비드':31},names
 profile={}
 for number in ['080626','080584']:
  r=captures['yeongnam_jockey_profile_'+number]
  soup=BeautifulSoup((HERE/r['file']).read_bytes().decode('cp949'),'html.parser')
  hidden=soup.find('input',attrs={'name':'jkNo'})
  profile[number]={'hidden_jkNo':hidden.get('value') if hidden else None,'sha256':r['sha256'],'file':r['file'],'text_after_name':soup.get_text(' ',strip=True).split('인적사항 성명',1)[-1][:200]}
 assert profile['080626']['hidden_jkNo']==''
 assert profile['080584']['hidden_jkNo']=='080584' and '다비드' in profile['080584']['text_after_name']
 report={'status':'same_event_name_verified_id_relationship_unresolved','verified_rows':len(evidence),'dates':dict(Counter(r['event_date'] for r in evidence)),'web_names':dict(names),'profiles':profile,'API_raw_files_verified':sources,'API_rider_categories':roles,'matching_rule':'date+meet+official horse ID+entry minute+exit minute; unique candidate required; horse name checked; raw seconds retained','database_mode':'read_only','database_writes':False}
 (HERE/'080626_exact_event_evidence.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in evidence),encoding='utf-8')
 (HERE/'080626_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
