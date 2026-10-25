"""Read-only official archive linkage; no absence-only inference of planned bookings."""
from pathlib import Path
import json,re,hashlib,importlib.util
import pandas as pd
import numpy as np
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def norm(x):return re.sub(r'\s+','',str(x)).strip()
def horse_norm(x):return re.sub(r'^\[(?:서울|부산경남|서|부)\]','',norm(x))
VEN={1:'서울',3:'부산경남'}
def rk(meet,date,no):return f'{meet}:{str(date).replace("-","").replace("/","")}:{int(no)}'
def reason_class(s):
 if re.search('부상|낙마|골절|염좌|좌상|타박',s):return 'injury_fall'
 if re.search('현기증|어지럼증|독감|일사병|수술|통증|복통|두통|감기|질병|인후|몸살|발열|구토|장염|설사|감염|불편|컨디션|건강|통|질환',s):return 'illness_pain'
 if re.search('중량|체중|증량|감량',s):return 'weight'
 return 'other' if s.strip() else 'unsupported'
def main():
 d=pd.read_parquet(R/'20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet'); actual_meets=set(d.meet);VEN[3]=next(m for m in actual_meets if m!='서울')
 sources=[];cards=[];notices=[];days=[];errors=[]
 for kind in ['dacom01','dacom13']:
  mp=ROOT/f'data/raw/kra_text/_manifests/{kind}/manifest.jsonl';sources.append(dict(path=str(mp.relative_to(ROOT)),bytes=mp.stat().st_size,sha256=sha(mp)))
  ms=[json.loads(x) for x in mp.read_text().splitlines()];selected={}
  for x in ms:
   if x.get('local_path') and x.get('sha256') and x['file_date']>='2018-01-01' and x['meet'] in VEN:
    selected.setdefault((x['meet'],x['file_date'],x['sha256']),x)
  for (meet,nominal,hash_),x in sorted(selected.items()):
   p=ROOT/x['local_path']; assert p.is_relative_to(ROOT/'data/raw/kra_text');assert sha(p)==hash_
   ref=dict(path=x['local_path'],bytes=p.stat().st_size,sha256=hash_,nominal_date=nominal,meet=VEN[meet],url=x['source_url'],retrieved_at_ms=x['retrieved_at_ms'])
   sources.append(ref);lines=p.read_bytes().decode('cp949').splitlines()
   if kind=='dacom01':
    race=None;table=False;started=False
    for lineno,line in enumerate(lines,1):
     title=re.search(r'제목\s*:\s*(?:[가-힣]+\s+)?(\d{2})\.(\d{2})\.(\d{2}).*?\s(\d+)경주',line)
     if title:
      yy,mm,dd,no=title.groups();date=f'20{yy}-{mm}-{dd}';race=rk(VEN[meet],date,no);table=False;started=False
     if '조교사' in line and '중량' in line and re.search(r'기\s*수',line):table=True;started=False;continue
     if not table or not race:continue
     if started and re.fullmatch(r'\s*-{10,}\s*',line):table=False;continue
     if not re.match(r'^\s*\d+\s',line):continue
     started=True
     m=re.match(r'^\s*(\d+)\s+(\S+)\s+(\S+?)\s*([암수거])\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(?:\(-\d+\))?(\S+)\s+(\S+)',line)
     if not m:errors.append(dict(kind='card_row',path=x['local_path'],line_no=lineno,line=line));continue
     gate,horse,origin,sex,age,weight,jockey,trainer=m.groups()
     cards.append(dict(source_key=race,gate=int(gate),card_horse=horse,scheduled_name=jockey,card_trainer=trainer,card_weight=float(weight),card_nominal_date=nominal,card_date=date,card_pre_race=nominal<date,source_path=x['local_path'],source_sha256=hash_,line_no=lineno,source_line=line))
   else:
    title=next((re.search(r'제목\s*:\s*(\d{4})년(\d{2})월(\d{2})일',line) for line in lines if '제목' in line),None)
    bodydate='-'.join(title.groups()) if title else ''
    section=False; explicit_zero=False;n=0;bad=0
    for lineno,line in enumerate(lines,1):
     if re.search(r'■\s*기수변경',line):section=True;continue
     if section and '■' in line:section=False
     if not section:continue
     if '기수변경이 없습니다' in line:explicit_zero=True
     if not re.match(r'^\s*\d{4}/',line):continue
     m=re.match(r'^\s*(\d{4}/\d{2}/\d{2})\s+(\d+)R\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+(?:\.\d+)?|null)\s*(.*)$',line)
     if not m:bad+=1;errors.append(dict(kind='notice_row',path=x['local_path'],line_no=lineno,line=line));continue
     date,no,gate,horse,before,after,weight,reason=m.groups();n+=1
     notices.append(dict(source_key=rk(VEN[meet],date,no),gate=int(gate),notice_horse=horse,before_name=before,after_name=after,after_weight=float(weight) if weight!='null' else np.nan,reason=reason,reason_class=reason_class(reason),notice_type='dacom13',notice_date=date.replace('/','-'),source_path=x['local_path'],source_sha256=hash_,line_no=lineno,source_line=line,before_id='',after_id=''))
    days.append(dict(meet=VEN[meet],date=nominal,body_date=bodydate,source_path=x['local_path'],source_sha256=hash_,explicit_zero=explicit_zero,parsed_notices=n,unparsed_rows=bad,supported=bodydate==nominal and bad==0 and (explicit_zero or n>0)))
 pd.DataFrame(errors,columns=['kind','path','line_no','line']).to_csv(O/'parse_exceptions.csv',index=False)
 c=pd.DataFrame(cards); n=pd.DataFrame(notices);day=pd.DataFrame(days)
 # All successful, complete daily API receipts are support, including explicit zero receipts.
 api_receipts=[];api_notices=[]
 for p in sorted((ROOT/'data/raw/kra/jockey_changes').rglob('*.json')):
  match=re.search(r'jockey_changes/(\d{4})/(\d{2})/(\d{2})/meet_([13])/',str(p))
  if not match:continue
  yy,mm,dd,meet=match.groups();meet=VEN[int(meet)];date=f'{yy}-{mm}-{dd}';raw=json.loads(p.read_text());a=raw.get('response',{});b=a.get('body',{});items=b.get('items',{});items=items.get('item',[]) if isinstance(items,dict) else [];items=items if isinstance(items,list) else [items];good=a.get('header',{}).get('resultCode')=='00' and int(b.get('totalCount',-1))==len(items) and int(b.get('pageNo',0))==1
  hash_=sha(p);sources.append(dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hash_));api_receipts.append(dict(meet=meet,date=date,n=len(items),supported=good,source_path=str(p.relative_to(ROOT)),sha256=hash_))
  if not good:continue
  for i,it in enumerate(items):
   if it['meet']!=meet:continue
   api_notices.append(dict(source_key=rk(meet,it['rcDate'],it['rcNo']),gate=int(it['chulNo']),notice_horse=it['hrName'],before_name=it['jkBefName'],after_name=it['jkAftName'],after_weight=float(it['aftBudam']),reason=it.get('reason',''),reason_class=reason_class(it.get('reason','')),notice_type='api10_1',notice_date=pd.to_datetime(str(it['rcDate'])).strftime('%Y-%m-%d'),source_path=str(p.relative_to(ROOT)),source_sha256=hash_,line_no=i,source_line=json.dumps(it,ensure_ascii=False),before_id=str(it['jkBef']),after_id=str(it['jkAft'])))
 if api_notices:n=pd.concat([n,pd.DataFrame(api_notices)],ignore_index=True)
 api=pd.DataFrame(api_receipts)
 # jkChange is genuinely unsupported (only '-'/'null' in the frozen data); never use it as a negative notice.
 sp=R/'20261002_steward_reports_v1/source/api_observations.parquet';s=pd.read_parquet(sp,columns=['dataset','race_key','jkChange']);s=s[s.dataset.eq('api215_judge_report')];use=s[~s.jkChange.fillna('').isin(['','-','null'])];assert len(use)==0,'Additional text requires explicit linkage before analysis'
 sources.append(dict(path=str(sp.relative_to(ROOT)),bytes=sp.stat().st_size,sha256=sha(sp)))
 # Historical name IDs; no live profiles or numeric-only ID filters.
 maps={}
 for typ in ['jockey','trainer']:
  maps[typ]=d[d[typ+'_id'].ne('')].assign(name=d[typ+'_name'].map(norm)).groupby(['meet','name'])[typ+'_id'].agg(lambda v:sorted(set(v))).to_dict()
 def lookup(meet,name,typ='jockey'):
  ids=maps[typ].get((meet,norm(name)),[])
  if not ids:ids=sorted({v for (m,k),vs in maps[typ].items() if k==norm(name) for v in vs})
  return ids[0] if len(ids)==1 else ''
 c['meet']=c.source_key.str.split(':').str[0];c['scheduled_id']=[lookup(m,j) for m,j in zip(c.meet,c.scheduled_name)];c['card_trainer_id']=[lookup(m,j,'trainer') for m,j in zip(c.meet,c.card_trainer)]
 for side in ['before','after']:
  n[side+'_id']=[old or lookup(key.split(':')[0],name) for old,key,name in zip(n[side+'_id'],n.source_key,n[side+'_name'])]
 c.to_parquet(O/'card_rows.parquet',index=False);n.to_parquet(O/'notice_rows.parquet',index=False);day.to_csv(O/'daily_bulletin_support.csv',index=False);api.to_csv(O/'api_receipt_support.csv',index=False)
 cdict={}
 for item in c.itertuples():cdict.setdefault((item.source_key,item.gate),[]).append(item)
 ndict={k:g for k,g in n.groupby(['source_key','gate'],sort=False)}
 support=set(zip(day.loc[day.supported,'meet'],day.loc[day.supported,'date']))|set(zip(api.loc[api.supported,'meet'],api.loc[api.supported,'date']))
 # A parse failure invalidates the whole relevant date, rather than treating failed rows as no changes.
 failed=set(zip(day.loc[~day.supported,'meet'],day.loc[~day.supported,'date']))-set(zip(api.loc[api.supported,'meet'],api.loc[api.supported,'date']))
 rec=[]
 for row in d.itertuples():
  key=(row.source_key,int(row.gate));cs=cdict.get(key);ns=ndict.get(key);date=row.date.strftime('%Y-%m-%d');supported=(row.meet,date) in support;scheduled='';status='unresolved';why='';planned_changed=None;reason='';reasoncat='unsupported';card_path='';card_line=0
  if cs is None:why='card_missing'
  else:
   relevant=[v for v in cs if v.card_pre_race];sig={(v.card_horse,v.scheduled_id,v.card_trainer_id) for v in relevant}
   if len(sig)!=1:why='card_conflict_or_not_pre_race'
   else:
    card=relevant[0];scheduled=card.scheduled_id;card_path=card.source_path;card_line=int(card.line_no)
    if horse_norm(card.card_horse)!=horse_norm(row.horse_name) or card.card_trainer_id!=row.trainer_id or not card.card_trainer_id:why='card_horse_trainer_mismatch'
    elif not scheduled:why='scheduled_id_ambiguous_or_missing'
    elif ns is None:
     if scheduled!=row.jockey_id:why='card_actual_mismatch_without_notice'
     elif not supported:why='change_support_missing'
     else:status='planned_as_card';why='card_actual_match_and_supported_notice_source'
    else:why='notice_requires_validation'
  if ns is not None:
   # Validate every edge; allow a documented chain for repeated changes. Different reasons do not invalidate same edge.
   matched=ns[ns.notice_horse.map(horse_norm).eq(horse_norm(row.horse_name))];edges=set(zip(matched.before_id,matched.after_id));valid=False
   if len(matched)==len(ns) and all(a and b for a,b in edges):
    starts=[scheduled] if scheduled else sorted({a for a,b in edges}-{b for a,b in edges})
    for start in starts:
     reached={start};used=set()
     for _ in range(len(edges)+1):
      new={(a,b) for a,b in edges if a in reached};used|=new;reached|={b for a,b in new}
     if row.jockey_id in reached and used==edges and row.jockey_id!=start:valid=True
   if valid and (not scheduled or why in ['notice_requires_validation','card_missing']):
    status='post_card_change';why='documented_card_to_actual_chain' if scheduled else 'documented_notice_to_actual_card_missing';reason=' | '.join(sorted({str(v).strip() for v in matched.reason}));reasoncat=reason_class(reason)
   else:status='unresolved';why='notice_card_actual_conflict_or_unresolved'
  if scheduled and row.previous_jockey_id:planned_changed=scheduled!=row.previous_jockey_id
  rec.append(dict(row_key=row.row_key,classification=status,classification_reason=why,scheduled_id=scheduled,scheduled_name=cs[0].scheduled_name if cs is not None else '',change_source_supported=supported,notice_count=0 if ns is None else len(ns),reason=reason,reason_class=reasoncat,scheduled_differs_previous=planned_changed,card_source_path=card_path,card_line_no=card_line))
 z=d.merge(pd.DataFrame(rec),on='row_key',validate='one_to_one');z['previous_classification']=z.previous_row_key.map(z.set_index('row_key').classification)
 z.to_parquet(O/'classified_starts.parquet',index=False)
 cov=z.groupby(['year','meet','classification','classification_reason'],dropna=False).size().rename('n').reset_index();cov.to_csv(O/'classification_coverage.csv',index=False)
 badids=c[c.scheduled_id.eq('')|c.card_trainer_id.eq('')][['meet','scheduled_name','card_trainer']].value_counts().reset_index(name='n');badids.to_csv(O/'unsupported_card_names.csv',index=False)
 audit=dict(source_files=len(sources),card_rows=len(c),notice_source_rows=len(n),parse_exceptions=len(errors),api215_races=len(s),api215_nonempty_jkChange=len(use),api215_not_a_negative_source=True,classification_counts=z.classification.value_counts().to_dict(),data_end_by_meet={m:str(g.date.max().date()) for m,g in z.groupby('meet')},supported_card_end_by_meet={m:str(g.card_date.max()) for m,g in c.groupby('meet')},nominal_initial_card_archive_not_certified_immutable_snapshot=True,source_inputs=sources)
 dump(O/'source_audit.json',audit);print(json.dumps({k:v for k,v in audit.items() if k!='source_inputs'},ensure_ascii=False,indent=2));print(cov[cov.year.ge(2024)].to_string(index=False))
if __name__=='__main__':main()
