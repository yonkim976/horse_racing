"""Recheck two race dates where stored API orders differ from the website."""
import hashlib,json
from pathlib import Path
from datetime import UTC,datetime
from urllib.parse import quote,quote_plus
from horse_racing.config import get_settings
from horse_racing.collectors.kra_api import KraApiClient,response_body
OUT=Path(__file__).resolve().parent

def main():
 settings=get_settings();secret=settings.data_go_kr_service_key
 if not secret:print('credential_unavailable');return
 key=secret.get_secret_value();run=OUT/'api4_retry'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S');run.mkdir(parents=True,exist_ok=False)
 reports=[]
 candidates=json.loads((OUT/'positive_order_website_correction_candidates.json').read_text())
 with KraApiClient(key,base_url='https://apis.data.go.kr/B551015',timeout_seconds=25) as client:
  for date,race in [('2025-10-17',7),('2026-03-06',8)]:
   params={'meet':2,'rc_date':date.replace('-',''),'pageNo':1,'numOfRows':1000,'_type':'json'}
   report={'date':date,'race_no':race,'public_params':params}
   try:
    page=client._fetch_json('/API4_3/raceResult_3','raceResult_3',params)
    if any(x.encode() in page.body for x in [key,quote(key,safe=''),quote_plus(key)]):raise RuntimeError('Secret echoed')
    filename=date.replace('-','')+'.json';(run/filename).write_bytes(page.body)
    body=response_body(page.payload);items=body.get('items') or {};rows=items.get('item',[]) if isinstance(items,dict) else [];rows=[rows] if isinstance(rows,dict) else rows
    assert len(rows)==int(body['totalCount']) and all(str(r['rcDate'])==date.replace('-','') for r in rows)
    target=[r for r in rows if int(r['rcNo'])==race];checks=[]
    for case in candidates:
     if (case['date'],case['race_no'])!=(date,race):continue
     row=next(r for r in target if str(r['hrNo'])==case['horse_id'] and int(r['chulNo'])==case['program_no'])
     field='sjS1fOrd' if case['point']=='S1F' else 'sjG1fOrd'
     checks.append({**case,'fresh_api_order':row[field],'fresh_matches_stored_api_order':row[field]==case['api_order'],'fresh_matches_website_order':row[field]==case['website_order']})
    report.update({'status':'complete','raw_file':filename,'sha256':hashlib.sha256(page.body).hexdigest(),'date_rows':len(rows),'target_race_rows':len(target),'order_checks':checks})
   except Exception as e:report.update({'status':'failed','error_type':type(e).__name__})
   reports.append(report);print(json.dumps({k:v for k,v in report.items() if k!='order_checks'},ensure_ascii=False),flush=True)
 (run/'manifest.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
 (OUT/'latest_api4_retry_pointer.json').write_text(json.dumps({'manifest':str((run/'manifest.json').relative_to(OUT))})+'\n')
if __name__=='__main__':main()
