"""Resolve only held new/recent passing points with bounded, recorded public RPT reads."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import httpx,duckdb
from common import ROOT,canonical,digest,sha,save_json,now
from passing_rpt import resolve_passing_points
from horse_racing.collectors.kra_text import KraTextClient
class RecordingTransport(httpx.BaseTransport):
 def __init__(self,folder,max_calls=48):
  self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.native=httpx.HTTPTransport(retries=0);self.calls=0;self.max_calls=max_calls;self.sources={};self.receipts=[]
 def handle_request(self,request):
  if request.url.host!='race.kra.co.kr' or request.url.path not in {'/dbdata/textDataList.do','/dbdata/fileDownLoad.do'}:raise RuntimeError('rpt_route_not_allowed')
  key=digest(canonical([request.method,str(request.url),request.content.decode('ascii')]).encode());meta=self.folder/(key+'.json')
  if meta.exists():
   receipt=json.loads(meta.read_text());path=ROOT/receipt['source_file']
   if receipt['status']==200 and sha(path)==receipt['source_sha256']:
    self.sources[receipt['source_file']]=receipt['source_sha256'];self.receipts.append(receipt)
    return httpx.Response(receipt['status'],headers={'content-type':receipt['content_type']},content=path.read_bytes(),request=request)
  if self.calls>=self.max_calls:raise RuntimeError('rpt_call_budget')
  self.calls+=1;time.sleep(.7)
  response=self.native.handle_request(request);data=response.read();response.close();h=digest(data)
  path=self.folder/(h+('.rpt' if request.url.path.endswith('fileDownLoad.do') else '.html'));path.write_bytes(data)
  receipt={'source_file':str(path.relative_to(ROOT)),'source_sha256':h,'status':response.status_code,'content_type':response.headers.get('content-type','application/octet-stream'),'url':str(request.url),'captured_at_utc':now(),'bytes':len(data),'request_method':request.method,'public_request_body':request.content.decode('ascii')}
  save_json(meta,receipt);self.sources[receipt['source_file']]=h;self.receipts.append(receipt)
  return httpx.Response(response.status_code,headers={'content-type':receipt['content_type']},content=data,request=request)
 def close(self):self.native.close()
def resolve_prepared(prepared,run):
 holds=[]
 for values in prepared['event_rows']:
  if values[1]!='passing_groups' or values[17]!='accepted':continue
  fields=json.loads(values[8])
  for h in fields.get('passing_point_holds',[]):
   if h['mapping_status']!='ambiguous_repeated_notation':continue
   holds.append({'record_id':values[0],'event_date':values[3],'meet':values[4],'race_no':values[6],'canonical_point_candidate':h['canonical_point'],'notation_raw':h['notation'],'source_field':h['source_field'],'hold_status':h['mapping_status'],'source_file':values[11],'source_sha256':values[12],'source_row_no':values[13]})
 core=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb';c=duckdb.connect(str(core),read_only=True)
 if c.execute("select count(*) from information_schema.tables where table_name='research_current_passing_point_holds'").fetchone()[0]:
  cur=c.execute("select * from research_current_passing_point_holds where event_date between ? and ? and hold_status='ambiguous_repeated_notation'",[prepared['start'],prepared['end']]);cols=[r[0] for r in cur.description]
  for row in cur.fetchall():
   r=dict(zip(cols,row));r['record_id']=r['record_id'].split('#passing-hold:')[0];r['event_date']=str(r['event_date']);holds.append(r)
 c.close()
 unique={canonical([r['record_id'],r['source_field'],r['canonical_point_candidate']]):r for r in holds};holds=list(unique.values())
 prepared['passing_resolution_rows']=[]
 if not holds:prepared['passing_rpt_summary']={'requested_points':0,'resolved_points':0,'official_calls':0};return prepared
 signature=digest(canonical(sorted(unique)).encode());report_path=run/'passing_rpt_resolution.json';transport=RecordingTransport(run/'rpt_http')
 if report_path.exists() and json.loads(report_path.read_text()).get('target_signature')==signature:
  report=json.loads(report_path.read_text())
  if not all((ROOT/p).is_file() and sha(ROOT/p)==h for p,h in report.get('recorded_sources',{}).items()):raise ValueError('RPT_saved_source_hash_mismatch')
 else:
  with KraTextClient(timeout_seconds=20,transport=transport) as client:report=resolve_passing_points(holds,client=client,max_race_days=20)
  report.update(target_signature=signature,recorded_sources=transport.sources,recorded_http_receipts=transport.receipts,official_calls=transport.calls,resolved_at_utc=now());save_json(report_path,report)
 bysha={h:p for p,h in report.get('recorded_sources',{}).items()}
 for r in report['resolutions']:
  if r['resolution_status']!='resolved_exact_rpt_label_value_match':continue
  file=r['rpt_file'];source=bysha.get(file['source_sha256'])
  if source is None:raise ValueError('RPT_resolution_has_no_saved_raw')
  record_id=r['api_record_id'].split('#passing-hold:')[0]
  prepared['passing_resolution_rows'].append([record_id,r['source_field'],r['canonical_point'],r['api_notation_raw'],source,file['source_sha256'],r['rpt_line_no'],r['rpt_byte_offset'],r['rpt_raw_line'],r['resolution_status'],report['resolved_at_utc'],prepared['run_id']])
 for p,h in report.get('recorded_sources',{}).items():prepared['sources'][p]=h
 prepared['sources'][str(report_path.relative_to(ROOT))]=sha(report_path)
 prepared['passing_rpt_summary']={'requested_points':len(holds),'resolved_points':len(prepared['passing_resolution_rows']),'official_calls':report.get('official_calls',0),'unresolved_points':len(holds)-len(prepared['passing_resolution_rows'])}
 save_json(run/'prepared.json',prepared);return prepared
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();assert a.run_id.replace('_','').isalnum()
 run=ROOT/'thoroughbred/refresh/runs'/a.run_id;prepared=json.loads((run/'prepared.json').read_text());result=resolve_prepared(prepared,run);print(canonical(result['passing_rpt_summary']))
