"""Independently verify saved official equipment evidence; no network or DB writes."""
import csv
import hashlib
import json
from pathlib import Path
import re
from collections import Counter
from bs4 import BeautifulSoup
from check_official import api_items,name_key,score_table,card_table

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
HEADER=re.compile(r'(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일.*?제(\d+)경주',re.S)
MARK=re.compile(r'^(.+?)\s*([+-])\s*$')

def verified_content(record):
    meta=record['metadata']
    path=(ROOT/meta['artifact']).resolve()
    assert path.is_relative_to(OUT/'official')
    assert meta['http_status']==200
    content=path.read_bytes()
    assert hashlib.sha256(content).hexdigest()==meta['sha256']
    return content

def verify_header(record,content):
    soup=BeautifulSoup(content.decode('cp949'),'html.parser')
    headings=[]
    for cell in soup.select('th.bgnone,td.bgnone'):
        text=cell.get_text(' ',strip=True)
        m=HEADER.search(text)
        if m:headings.append((''.join((m.group(1),m.group(2).zfill(2),m.group(3).zfill(2))),int(m.group(4)),text))
    wanted_date=record.get('date','').replace('-','')
    wanted_race=int(record.get('race',record.get('race_no')))
    hits=[x for x in headings if x[0]==wanted_date and x[1]==wanted_race]
    assert len(hits)==1,(wanted_date,wanted_race,headings)
    label='서울' if int(record['meet'])==1 else '부경'
    assert label in hits[0][2]
    return hits[0][2]

def main():
    a=json.loads((OUT/'official_checks.json').read_text())
    assert len(a['targets'])==104
    assert len(a['live_api78'])==96
    assert len(a['official_score'])==103
    assert len(a['official_card_samples'])==8
    checks=Counter();live=[];historic=[];candidates=[];tokens=[]
    for record in a['live_api78']+a['historical_api78_samples']:
        content=verified_content(record);items=api_items(content)
        assert len(items)==record['item_count']
        row_dates={re.sub(r'\D','',str(x.get('raceDt','')))[:8] for x in items}
        assert not row_dates or row_dates=={record['date']}
        checks['api_pages_hash_and_complete']+=1
        for c in record.get('target_checks',[]):
            hits=[x for x in items if int(re.search(r'\d+',str(x['raceNo'])).group())==int(c['race_no']) and int(x['gtno'])==int(c['horse_no'])]
            same_name=[x for x in items if name_key(str(x.get('hrnm','')))==name_key(c['horse_name'])]
            assert hits==[] and c['matching_rows']==[]
            live.append({'date':record['date'],'meet':record['meet'],'race_no':c['race_no'],'horse_no':c['horse_no'],'horse_id':c['horse_id'],'horse_name':c['horse_name'],
                'exact_race_number_missing':True,'same_name_any_race_rows':len(same_name)})
            checks['live_target_exact_key_absent']+=1
            checks['live_target_name_absent_entire_day']+=int(not same_name)
        if not record.get('target_checks'):
            historic.append({'date':record['date'],'meet':record['meet'],'rows':len(items),
                'equipment_blank':sum(not str(x.get('equipCrs') or '').strip() for x in items),
                'equipment_nonblank':sum(bool(str(x.get('equipCrs') or '').strip()) for x in items),
                'signed_rows':sum('+' in str(x.get('equipCrs') or '') or '-' in str(x.get('equipCrs') or '') for x in items)})
    for record in a['official_score']:
        content=verified_content(record);heading=verify_header(record,content);rows=score_table(content)
        checks['score_page_hash_and_date_race_meet']+=1
        for c in record['target_checks']:
            row=rows[int(c['horse_no'])]
            assert row==c['official_row']
            assert row['horse_id']==c['horse_id']
            assert name_key(row['name'])==name_key(c['horse_name'])
            assert row['rank']==c['core_rank'] and 1<=int(row['rank'])<=30
            assert row['equipment_raw'].strip()
            checks['score_target_id_name_rank_equipment_verified']+=1
            source_url='https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet='+str(record['meet'])+'&realRcDate='+record['date']+'&realRcNo='+str(record['race'])
            candidate={'meet':record['meet'],'date':c['date'],'race_no':c['race_no'],'horse_no':c['horse_no'],'horse_id':c['horse_id'],'horse_name':c['horse_name'],
                'equipment_raw':row['equipment_raw'],'source':'KRA_official_score_html','source_url':source_url,'retrieved_at_kst':record['metadata']['retrieved_at_kst'],
                'retrieved_at_basis':record['metadata'].get('retrieved_at_basis','not_recorded'),
                'raw_path':record['metadata']['artifact'],'sha256':record['metadata']['sha256'],'availability_status':'retrospective_score_observation_not_verified_pre_race',
                'api78_status':'row_not_provided_in_requeried_api','candidate_only_not_loaded':True}
            candidates.append(candidate)
            for position,token in enumerate(row['equipment_raw'].split(','),1):
                token=token.strip()
                if not token:continue
                mark=MARK.fullmatch(token)
                status='new' if mark and mark.group(2)=='+' else 'removed' if mark else 'unmarked'
                name=mark.group(1).strip() if mark else token
                tokens.append({**candidate,'position':position,'equipment_name_raw':name,'mark':status,'token_raw':token})
                checks['tokens_'+status]+=1
    for record in a['official_card_samples']:
        content=verified_content(record);verify_header(record,content);rows=card_table(content)
        assert int(record['horse_no']) not in rows
        assert all(name_key(x['name'])!=name_key(record['horse_name']) for x in rows.values())
        checks['representative_website_card_target_absent']+=1
    assert len({(c['meet'],c['date'],c['race_no'],c['horse_no'],c['horse_id']) for c in candidates})==104
    for filename,data in [('score_supplement_candidates.csv',candidates),('score_supplement_tokens.csv',tokens)]:
        with (OUT/filename).open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    result={'passed':True,'scope':'104 currently unobserved API78 runners; no DB load',
        'checks':dict(checks),'live_api78_targets':live,'historical_samples':historic,
        'horse_rows':[{'horse_name':n,'horse_id':h,'rows':count} for (n,h),count in Counter((c['horse_name'],c['horse_id']) for c in candidates).most_common()],
        'signed_score_rows':sum('+' in c['equipment_raw'] or '-' in c['equipment_raw'] for c in candidates)}
    (OUT/'root_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('live_api78_targets','historical_samples')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
