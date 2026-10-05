"""Read current annual API6/303 responses for missing/legacy verification only."""
import hashlib,json,math
from datetime import UTC,datetime
from pathlib import Path
from urllib.parse import quote,quote_plus
from horse_racing.config import get_settings
from horse_racing.collectors.kra_api import KraApiClient,response_body
OUT=Path(__file__).resolve().parent
TARGETS=[('API6_1','raceDetailSectionRecord_1',2025),('API6_1','raceDetailSectionRecord_1',2026),('API6_1','raceDetailSectionRecord_1',2002),('API303','corner_rank',2002)]

def main():
 settings=get_settings();secret=settings.data_go_kr_service_key
 if not secret or not secret.get_secret_value().strip():
  print(json.dumps({'status':'credential_unavailable'}));return
 key=secret.get_secret_value();run=OUT/'api_retry'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S');run.mkdir(parents=True,exist_ok=False)
 records=[]
 with KraApiClient(key,base_url='https://apis.data.go.kr/B551015',timeout_seconds=25) as client:
  for service,operation,year in TARGETS:
   meta={'service':service,'operation':operation,'year':year,'pages':[],'rows':[]}
   page=1
   try:
    while True:
     params={'meet':2,'rc_year':str(year),'pageNo':page,'numOfRows':1000,'_type':'json'}
     result=client._fetch_json('/'+service+'/'+operation,operation,params)
     variants=[key,quote(key,safe=''),quote_plus(key)]
     if any(x.encode() in result.body for x in variants):raise RuntimeError('Secret echoed in response')
     filename=f'{service}_{year}_page{page}.json';(run/filename).write_bytes(result.body)
     body=response_body(result.payload);items=body.get('items') or {};rows=items.get('item',[]) if isinstance(items,dict) else [];rows=[rows] if isinstance(rows,dict) else rows
     total=int(body.get('totalCount') or 0);per=int(body.get('numOfRows') or 1000)
     meta['pages'].append({'file':filename,'sha256':hashlib.sha256(result.body).hexdigest(),'http_status':result.status_code,'public_params':params,'total_count':total,'rows':len(rows)})
     meta['rows'].extend(rows)
     if page>=max(1,math.ceil(total/per)):break
     page+=1
    meta['status']='complete';meta['total_count']=total;meta['returned_rows']=len(meta['rows'])
   except Exception as e:meta.update({'status':'failed','error_type':type(e).__name__})
   records.append(meta);print(json.dumps({k:v for k,v in meta.items() if k not in ('pages','rows')}),flush=True)
 (run/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
 (OUT/'latest_api_retry_pointer.json').write_text(json.dumps({'manifest':str((run/'manifest.json').relative_to(OUT))})+'\n')
if __name__=='__main__':main()
