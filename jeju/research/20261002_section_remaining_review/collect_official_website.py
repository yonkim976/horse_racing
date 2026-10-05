"""Archive KRA result tables for the fixed, audited remaining race keys."""
import hashlib,json,re,time
from datetime import UTC,datetime
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
OUT=Path(__file__).resolve().parent

def clean(cell):return re.sub(r'\s+',' ',cell.get_text(' ',strip=True)).strip()
def extract(body,key):
 soup=BeautifulSoup(body,'html.parser');tables=[];heading=None
 for t in soup.find_all('table'):
  rows=[[clean(c) for c in tr.find_all(['th','td'],recursive=False)] for tr in t.find_all('tr')]
  rows=[r for r in rows if r]
  joined=' '.join(x for r in rows for x in r)
  match=re.search(r'(\d{4})년\s+(\d{2})월\s+(\d{2})일.*?제(\d+)경주\s+제주',joined)
  if match:
   date=f'{match[1]}-{match[2]}-{match[3]}'
   if date==key['date'] and int(match[4])==key['race_no']:heading=rows
  if rows and (('순위' in rows[0] and '마번' in rows[0]) or '통과순위' in rows[0] or '펄롱타임' in rows[0]):
   tables.append({'caption':clean(t.find('caption')) if t.find('caption') else None,'rows':rows})
 return {'title':soup.title.get_text(strip=True) if soup.title else None,'heading':heading,'tables':tables,'identity_verified':heading is not None}

def main():
 keys=json.loads((OUT/'target_race_keys_initial.json').read_text())
 folder=OUT/'website_html';folder.mkdir(exist_ok=True)
 records=[]
 with httpx.Client(timeout=25,follow_redirects=False) as client:
  for i,key in enumerate(keys,1):
   day=key['date'].replace('-','');number=key['race_no']
   url=f'https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate={day}&realRcNo={number}'
   filename=f'{day}_{number}.html';path=folder/filename
   record={**key,'url':url,'retrieved_at_utc':datetime.now(UTC).isoformat(timespec='seconds')}
   try:
    if path.exists():
     blob=path.read_bytes();record['reused_existing_file']=True
    else:
     response=client.get(url);record['http_status']=response.status_code
     blob=response.content
     with path.open('xb') as f:f.write(blob)
    record.update({'raw_path':path.relative_to(OUT).as_posix(),'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),**extract(blob,key)})
   except Exception as e:record.update({'error_type':type(e).__name__,'identity_verified':False})
   records.append(record)
   if i%10==0:print(json.dumps({'checked':i,'targets':len(keys),'identity_verified':sum(x['identity_verified'] for x in records)}),flush=True)
   time.sleep(.15)
 (OUT/'website_evidence.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'total':len(records),'identity_verified':sum(x['identity_verified'] for x in records),'failed_keys':[{k:r[k] for k in ('date','race_no')} for r in records if not r['identity_verified']]}),flush=True)
if __name__=='__main__':main()
