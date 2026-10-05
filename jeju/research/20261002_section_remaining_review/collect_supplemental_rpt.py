"""Collect official TXT only after unresolved API/website comparison."""
import hashlib,json,re,time
from pathlib import Path
from datetime import UTC,datetime
from urllib.parse import urlencode
import httpx
OUT=Path(__file__).resolve().parent
TITLE=re.compile(r'^제목\s*:\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일[^\n]*?제\s*(\d+)경주',re.M)

def main():
 targets={}
 for r in json.loads((OUT/'remaining_website_internal_order_conflicts.json').read_text()):targets[(r['date'],int(r['race_no']))]='website_internal_order_conflict'
 import csv
 for r in csv.DictReader((OUT.parents[2]/'jeju/research/20261002_section_passing_audit/root_audit/completed_missing_source_keys.csv').open()):targets[(r['date'],int(r['race_no']))]='race_level_section_missing'
 for r in json.loads((OUT/'positive_order_website_correction_candidates.json').read_text()):targets[(r['date'],r['race_no'])]='api_website_order_disagreement'
 records=[];folder=OUT/'supplemental_rpt';folder.mkdir(exist_ok=True)
 with httpx.Client(timeout=25,follow_redirects=False) as client:
  for i,date in enumerate(sorted({d for d,n in targets}),1):
   compact=date.replace('-','');fn=f'chollian/jeju/jungbo/rcresult/{compact}dacom11.rpt';url='https://race.kra.co.kr/dbdata/fileDownLoad.do?'+urlencode({'fn':fn,'meet':2});file=folder/(compact+'dacom11.rpt')
   meta={'date':date,'url':url,'retrieved_at_utc':datetime.now(UTC).isoformat(timespec='seconds')}
   try:
    if file.exists():blob=file.read_bytes()
    else:
     r=client.get(url);meta['http_status']=r.status_code;blob=r.content
     with file.open('xb') as f:f.write(blob)
    text=blob.decode('cp949');matches=list(TITLE.finditer(text));blocks=[]
    for j,m in enumerate(matches):
     if (date,int(m[4])) not in targets:continue
     assert '-'.join(m.group(k) for k in (1,2,3))==date
     block=text[m.start():matches[j+1].start() if j+1<len(matches) else len(text)]
     name=compact+'_'+m[4]+'_block.txt';(folder/name).write_text(block,encoding='utf-8')
     relevant=[line for line in block.splitlines() if re.match(r'\s*(펄롱타임|통과거리|통과타임|통과순위|C1|C2|C3|C4|G-1F)\s*:',line)]
     blocks.append({'race_no':int(m[4]),'reason':targets[(date,int(m[4]))],'block_file':str((folder/name).relative_to(OUT)),'block_sha256':hashlib.sha256(block.encode()).hexdigest(),'race_level_lines':relevant})
    meta.update({'raw_file':str(file.relative_to(OUT)),'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'race_blocks':blocks,'matched_target_races':len(blocks),'status':'parsed' if blocks else 'no_target_title'})
   except Exception as e:meta.update({'status':'failed','error_type':type(e).__name__})
   records.append(meta)
   if i%5==0:print(json.dumps({'dates_checked':i,'dates':len({d for d,n in targets})}),flush=True)
   time.sleep(.15)
 (OUT/'supplemental_rpt_manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'dates':len(records),'target_races':len(targets),'matched':sum(r.get('matched_target_races',0) for r in records)}),flush=True)
if __name__=='__main__':main()
