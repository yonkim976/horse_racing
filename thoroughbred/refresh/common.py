"""Bounded public KRA retrieval with complete-page receipts and no secret logging."""
from __future__ import annotations
import hashlib,json,math,time,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import unquote
import httpx
from horse_racing.config import get_settings
ROOT=Path(__file__).resolve().parents[2]
HOST='https://apis.data.go.kr/B551015'
ALLOWED={'/API72_2/racePlan_2','/API4_3/raceResult_3','/API303/corner_rank','/API20_1/ridingTestResult_1','/API78/chulmainfo','/API215/JudgeReport','/API180_1/sanctionHistory_1','/API18_1/dailyTraining_1','/API22_1/startingTranning_1','/API216/SwimTr','/API21_1/startingTestResult_1','/API16_1/raceHorseClinic_1','/API8_2/raceHorseInfo_2','/API307/jockeyInfo','/API308/trainerInfo','/API309/horseOwnerInfo','/API309/ownerInfo','/API307/jockeyInfo_1','/API308/trainerInfo_1','/API309/ownerInfo_1','/API25_1/entryHorseWeightInfo_1','/API26_2/entrySheet_2'}
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(data):return hashlib.sha256(data).hexdigest()
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
def save_json(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');temp.replace(path)
class CaptureError(Exception):pass
class Collector:
 def __init__(self,run_dir,max_calls=1200,interval=0.4):
  secret=get_settings().data_go_kr_service_key
  if secret is None:raise CaptureError('credential_unavailable')
  self.key=unquote(secret.get_secret_value());self.run_dir=Path(run_dir).resolve()
  assert self.run_dir.is_relative_to(ROOT/'thoroughbred')
  self.client=httpx.Client(timeout=60,follow_redirects=False)
  self.calls=0;self.max_calls=max_calls;self.interval=interval;self.stop=False
 def close(self):self.client.close()
 def bundle(self,request):
  endpoint=request['endpoint'];endpoint='/'+endpoint.lstrip('/')
  if endpoint not in ALLOWED:raise CaptureError('endpoint_not_allowlisted')
  public=dict(request['params']);public.pop('_type',None)
  if any('key' in str(k).lower() for k in public):raise CaptureError('secret_parameter_in_public_request')
  identifier=digest(canonical({'family':request['family'],'endpoint':endpoint,'params':public}).encode())[:20]
  folder=self.run_dir/'raw'/request['family']/identifier;folder.mkdir(parents=True,exist_ok=True)
  receipt=folder/'bundle.json'
  if receipt.exists():
   b=json.loads(receipt.read_text())
   if b.get('complete') and all(sha(ROOT/p['source_file'])==p['source_sha256'] for p in b['pages']):return b
  b={'family':request['family'],'endpoint':endpoint,'params':public,'meet':str(request.get('meet','')),'complete':False,'pages':[],'requested_at_utc':now()}
  total=None;page=1;received=0;seen_pages=set()
  try:
   while True:
    if self.stop or self.calls>=self.max_calls:raise CaptureError('call_budget_or_quota_stop')
    params={**public,'_type':'json','pageNo':page,'numOfRows':20000,request.get('service_key_parameter','ServiceKey'):self.key}
    path=folder/f'p{page:04d}.json'
    data=None
    for attempt in range(2):
     self.calls+=1;time.sleep(self.interval)
     try:
      response=self.client.get(HOST+endpoint,params=params)
      if response.status_code==429:self.stop=True;raise CaptureError('HTTP429_quota')
      if response.status_code!=200:raise CaptureError('HTTP_'+str(response.status_code))
      data=response.content
      if self.key.encode() in data:raise CaptureError('credential_reflected')
      payload=response.json();root=payload.get('response',payload);header=root.get('header',{});code=str(header.get('resultCode',''))
      if code not in {'00','0000'}:
       if code=='22':self.stop=True
       raise CaptureError('API_code_'+(code if re.fullmatch(r'[0-9]{2,4}',code) else 'unknown'))
      body=root.get('body',{});items=body.get('items') or []
      if isinstance(items,dict):items=items.get('item') or []
      if isinstance(items,dict):items=[items]
      if not isinstance(items,list) or not all(isinstance(r,dict) for r in items):raise CaptureError('invalid_items')
      new_total=int(body['totalCount']);actual_size=int(body.get('numOfRows') or 20000);actual_page=int(body.get('pageNo') or page)
      if total is not None and new_total!=total:raise CaptureError('changing_total')
      if actual_page!=page or actual_size<1 or len(items)!=min(actual_size,max(0,new_total-(page-1)*actual_size)):raise CaptureError('incomplete_or_wrong_page')
      total=new_total
      break
     except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
      if attempt==1:raise CaptureError('transport_or_response_'+type(exc).__name__) from None
    else:raise CaptureError('capture_failed')
    rawhash=digest(data)
    if rawhash in seen_pages and total>actual_size:raise CaptureError('repeated_page')
    seen_pages.add(rawhash);path.write_bytes(data)
    b['pages'].append({'source_file':path.relative_to(ROOT).as_posix(),'source_sha256':rawhash,'captured_at_utc':now(),'page_no':page,'item_count':len(items),'total_count':total,'page_size':actual_size,'bytes':len(data)})
    received+=len(items);save_json(receipt,b)
    if page>=max(1,math.ceil(total/actual_size)):break
    page+=1
   if received!=total:raise CaptureError('incomplete_bundle')
   b.update(complete=True,total_count=total,captured_at_utc=now(),receipt_file=receipt.relative_to(ROOT).as_posix())
  except CaptureError as exc:b.update(error=str(exc),captured_at_utc=now())
  save_json(receipt,b);return b
 def rows(self,bundle):
  if not bundle['complete']:raise CaptureError('incomplete_bundle_not_loadable')
  for meta in bundle['pages']:
   path=ROOT/meta['source_file']
   if sha(path)!=meta['source_sha256']:raise CaptureError('raw_hash_mismatch')
   root=json.loads(path.read_bytes());root=root.get('response',root);items=root['body'].get('items') or []
   if isinstance(items,dict):items=items.get('item') or []
   if isinstance(items,dict):items=[items]
   for i,item in enumerate(items,1):
    yield item,{**meta,'source_row_no':i,'meet':bundle['meet'],'request_params':bundle['params'],'requested_date':bundle['params'].get('race_dt') or bundle['params'].get('tr_date') or bundle['params'].get('rc_date') or bundle['params'].get('clinic_date')}

from contextlib import contextmanager
import fcntl
@contextmanager
def domain_lock():
 path=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/refresh.lock'
 with path.open('a+') as stream:
  try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise CaptureError('thoroughbred_refresh_already_running') from None
  try:yield
  finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
