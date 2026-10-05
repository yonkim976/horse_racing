"""Read-only equipment gap review; bounded, sequential official-source requests.

Only audit artifacts are written. No application ingestion or database mutation.
API credentials are used only for the fixed official HTTPS endpoint, never logged.
Successful responses are reused on rerun with hashes checked before parsing.
"""
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import duckdb
import httpx
from horse_racing.config import get_settings

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'thoroughbred/research/20261001_equipment_storage_audit_v1/matched_operational_api78_missing_2017plus.csv'
KST=ZoneInfo('Asia/Seoul')
NUMBER=re.compile(r'\d+')
HORSE_LINK=re.compile(r"goHorse\(['\"](\d{7})['\"]")

def name_key(value):
    return ''.join(re.sub(r'^\[[^]]+\]','',value.strip()).removeprefix('★').split())

def save_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def now():return datetime.now(KST).isoformat(timespec='milliseconds')

def request(client,url,params,stem,kind):
    raw=OUT/'official'/f'{stem}.{kind}'
    meta=OUT/'official'/f'{stem}.metadata.json'
    if raw.is_file() and meta.is_file():
        record=json.loads(meta.read_text())
        content=raw.read_bytes()
        if record.get('http_status')==200 and hashlib.sha256(content).hexdigest()==record['sha256']:
            return content,record
    # One request at a time; no automatic retry or redirect on a failed call.
    time.sleep(1.0)
    record={'source_url':url,'requested_at_kst':now(),'artifact':str(raw.relative_to(ROOT))}
    try:
        response=client.get(url,params=params)
        record['retrieved_at_kst']=now()
        record['retrieved_at_basis']='timestamp_recorded_after_http_response'
        record['http_status']=response.status_code
        if response.status_code!=200:
            record['error']='non_200_response'
            save_json(meta,record)
            return None,record
        content=response.content
        record['sha256']=hashlib.sha256(content).hexdigest()
        raw.write_bytes(content)
        save_json(meta,record)
        return content,record
    except httpx.HTTPError as exc:
        record['error']=type(exc).__name__
        save_json(meta,record)
        return None,record

def api_items(content):
    payload=json.loads(content)
    header=payload['response']['header']
    if str(header.get('resultCode')) not in ('00','0000'):
        raise ValueError('api_result_not_success')
    body=payload['response']['body']
    items=body.get('items') or {}
    items=items.get('item',[]) if isinstance(items,dict) else []
    items=[items] if isinstance(items,dict) else items
    if not isinstance(items,list):raise ValueError('invalid_item_shape')
    if int(body['totalCount'])!=len(items):raise ValueError('incomplete_api_page')
    return items

def card_table(content):
    soup=BeautifulSoup(content.decode('cp949'),'html.parser')
    selected=None
    for table in soup.find_all('table'):
        headers=[x.get_text(' ',strip=True) for x in table.select('thead th')]
        if any('장구현황' in x for x in headers) and any('마명' in x for x in headers):
            selected=(table,headers)
            break
    if selected is None:raise ValueError('card_equipment_table_absent')
    table,headers=selected
    name_pos=next(i for i,x in enumerate(headers) if '마명' in x)
    equip_pos=next(i for i,x in enumerate(headers) if '장구현황' in x)
    rows={}
    for tr in table.select('tbody tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=len(headers):continue
        number=cells[0].get_text(' ',strip=True)
        if not number.isdigit():continue
        link=HORSE_LINK.search(str(cells[name_pos]))
        rows[int(number)]={'name':cells[name_pos].get_text(' ',strip=True),
            'horse_id':link.group(1) if link else None,'equipment_raw':cells[equip_pos].get_text(' ',strip=True)}
    return rows

def score_table(content):
    soup=BeautifulSoup(content.decode('cp949'),'html.parser')
    caption=next((x for x in soup.find_all('caption') if '경주상세성적' in x.get_text(' ',strip=True)),None)
    if caption is None:raise ValueError('score_table_absent')
    table=caption.find_parent('table')
    headers=[x.get_text(' ',strip=True) for x in table.select('thead th')]
    positions={label:next((i for i,x in enumerate(headers) if label in x),None) for label in ('순위','마번','마명','장구현황')}
    if any(v is None for v in positions.values()):raise ValueError('score_equipment_columns_absent')
    rows={}
    for tr in table.select('tbody tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=len(headers):continue
        number=cells[positions['마번']].get_text(' ',strip=True)
        if not number.isdigit():continue
        n=cells[positions['마명']]
        link=HORSE_LINK.search(str(n))
        rows[int(number)]={'name':n.get_text(' ',strip=True),'horse_id':link.group(1) if link else None,
            'rank':cells[positions['순위']].get_text(' ',strip=True),
            'equipment_raw':cells[positions['장구현황']].get_text(' ',strip=True)}
    return rows

def main():
    (OUT/'official').mkdir(parents=True,exist_ok=True)
    targets=list(csv.DictReader(SOURCE.open(encoding='utf-8')))
    assert len(targets)==104
    db=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
    core={(int(m),str(d),int(r),int(n),str(h)):str(rank) for m,d,r,n,h,rank in db.execute('SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_id_raw,result_rank_raw FROM confirmed_runners').fetchall()}
    historical=db.execute("""SELECT source_meet,left(result_date,4) season_year,min(result_date) first_date
        FROM confirmed_runners WHERE source_meet IN ('1','3') AND result_date BETWEEN '20100101' AND '20161231'
        GROUP BY source_meet,left(result_date,4) ORDER BY season_year,source_meet""").fetchall()
    feb=db.execute("""SELECT source_meet,'2016_feb' season_year,min(result_date) first_date
        FROM confirmed_runners WHERE source_meet IN ('1','3') AND result_date BETWEEN '20160201' AND '20160229'
        GROUP BY source_meet ORDER BY source_meet""").fetchall()
    db.close()
    api_dates=sorted({(r['date'].replace('-',''),int(r['meet'])) for r in targets})
    hist_dates=[(str(d),int(m)) for m,_,d in historical+feb]
    settings=get_settings()
    secret=settings.data_go_kr_service_key
    results={'targets':targets,'live_api78':[],'historical_api78_samples':[],'official_score':[],'official_card_samples':[]}
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        if secret is not None:
            key=unquote(secret.get_secret_value())
            for index,(day,meet) in enumerate(api_dates+hist_dates,1):
                params={'serviceKey':key,'rccrs_cd':meet,'race_dt':day,'_type':'json','pageNo':1,'numOfRows':1000}
                content,meta=request(client,'https://apis.data.go.kr/B551015/API78/chulmainfo',params,f'api78_{meet}_{day}','json')
                record={'date':day,'meet':meet,'metadata':meta}
                try:
                    if content is None:raise ValueError('fetch_failed')
                    items=api_items(content)
                    row_dates={re.sub(r'\D','',str(x.get('raceDt','')))[:8] for x in items}
                    if row_dates and row_dates!={day}:raise ValueError('api_row_date_mismatch')
                    record['item_count']=len(items)
                    record['equipment_nonblank_rows']=sum(bool(str(x.get('equipCrs') or '').strip()) for x in items)
                    record['signed_rows']=sum('+' in str(x.get('equipCrs') or '') or '-' in str(x.get('equipCrs') or '') for x in items)
                    wanted=[r for r in targets if r['date'].replace('-','')==day and int(r['meet'])==meet]
                    record['target_checks']=[]
                    for r in wanted:
                        matches=[x for x in items if int(NUMBER.search(str(x['raceNo'])).group())==int(r['race_no']) and int(x['gtno'])==int(r['horse_no'])]
                        record['target_checks'].append({'horse_id':r['horse_id'],'horse_name':r['horse_name'],'race_no':r['race_no'],'horse_no':r['horse_no'],
                            'matching_rows':[{'hrnm':x.get('hrnm'),'equipCrs':x.get('equipCrs'),'name_match':name_key(str(x.get('hrnm','')))==name_key(r['horse_name'])} for x in matches]})
                except (ValueError,KeyError,TypeError,AttributeError) as exc:
                    record['parse_error']=type(exc).__name__
                bucket='live_api78' if index<=len(api_dates) else 'historical_api78_samples'
                results[bucket].append(record)
                save_json(OUT/'official_checks.json',results)
                if index%16==0:print(f'API78 sequential checks {index}/{len(api_dates)+len(hist_dates)}',flush=True)
                if meta.get('http_status') in (403,429):break
        else:results['api_credentials_available']=False
        races=sorted({(r['date'].replace('-',''),int(r['meet']),int(r['race_no'])) for r in targets})
        for index,(day,meet,race) in enumerate(races,1):
            params={'Act':'04','Sub':'1','meet':meet,'realRcDate':day,'realRcNo':race}
            content,meta=request(client,'https://race.kra.co.kr/raceScore/ScoretableDetailList.do',params,f'score_{meet}_{day}_{race}','html')
            record={'date':day,'meet':meet,'race':race,'metadata':meta,'target_checks':[]}
            try:
                if content is None:raise ValueError('fetch_failed')
                rows=score_table(content)
                for r in targets:
                    if (r['date'].replace('-',''),int(r['meet']),int(r['race_no']))!=(day,meet,race):continue
                    row=rows.get(int(r['horse_no']))
                    core_rank=core[(meet,day,race,int(r['horse_no']),r['horse_id'])]
                    check={**r,'core_rank':core_rank,'official_row':row}
                    if row:
                        check.update(name_match=name_key(row['name'])==name_key(r['horse_name']),horse_id_match=row['horse_id']==r['horse_id'],rank_match=row['rank']==core_rank)
                    record['target_checks'].append(check)
            except (ValueError,KeyError,TypeError,UnicodeError) as exc:record['parse_error']=type(exc).__name__
            results['official_score'].append(record)
            save_json(OUT/'official_checks.json',results)
            if index%16==0:print(f'Official score sequential checks {index}/{len(races)}',flush=True)
            if meta.get('http_status') in (403,429):break
        representatives={}
        for r in sorted(targets,key=lambda x:x['date']):representatives.setdefault(r['horse_id'],r)
        for r in representatives.values():
            day=r['date'].replace('-','');meet=int(r['meet']);race=int(r['race_no'])
            params={'Act':'02','Sub':'1','meet':meet,'rcDate':day,'rcNo':race}
            content,meta=request(client,'https://race.kra.co.kr/chulmainfo/chulmaDetailInfoChulmapyo.do',params,f'card_{meet}_{day}_{race}','html')
            record={**r,'metadata':meta}
            try:
                if content is None:raise ValueError('fetch_failed')
                row=card_table(content).get(int(r['horse_no']))
                record['official_row']=row
                if row:record.update(name_match=name_key(row['name'])==name_key(r['horse_name']),horse_id_match=row['horse_id']==r['horse_id'])
            except (ValueError,KeyError,TypeError,UnicodeError) as exc:record['parse_error']=type(exc).__name__
            results['official_card_samples'].append(record)
            save_json(OUT/'official_checks.json',results)
            if meta.get('http_status') in (403,429):break
    print(json.dumps({'live_api78_dates':len(results['live_api78']),'historical_samples':len(results['historical_api78_samples']),'score_pages':len(results['official_score']),'card_samples':len(results['official_card_samples'])},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
