"""Read-only proof of older official daily-detail rider labels and exact events."""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib
import importlib.util
import json
import re
import sqlite3
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('rider_types',ROOT/'jeju/research/20261015_training_rider_types/classify_riders.py')
types=importlib.util.module_from_spec(spec);spec.loader.exec_module(types)
c=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
names=set()
for meet in (1,2,3):
    body=json.loads((ROOT/f'data/research/jockey_roster_20261008/api_{meet}.json').read_text())['response']['body']
    items=body['items']['item'];items=[items] if isinstance(items,dict) else items
    assert len(items)==int(body['totalCount'])
    names.update(r['jkName'] for r in items if r.get('jkName') not in (None,'','-'))
results=[];evidence=[];unresolved=[]
for folder in ['daily_all_2007','daily_all_2010','daily_all_2012','daily_all_2022','daily_all_2024','daily_all_april']:
    record=json.loads((HERE/'homepage'/folder/'manifest.json').read_text())[0]
    path=ROOT/record['source_path'];raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==record['sha256'] and record['http_status']==200
    soup=BeautifulSoup(raw.decode('euc-kr'),'html.parser')
    expected=record['form_fields']['trDate']
    assert soup.find('input',attrs={'name':'trDate'})['value']==expected
    assert soup.find('input',attrs={'name':'meet'})['value']=='2'
    text=soup.get_text(' ',strip=True)
    assert '관:주로조교' in text and '전체 일별상세조교현황' in text
    date=expected.replace('/','-');index=defaultdict(list);rows=[]
    for rowno,tr in enumerate(soup.find_all('tr'),1):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=9 or not cells[0].get_text(strip=True).isdigit():continue
        link=cells[3].find('a');match=re.search(r"goPage4\(\s*['\"](\d+)['\"]\s*\)",str(link))
        assert match,'Missing official horse ID link'
        values=[x.get_text(' ',strip=True) for x in cells]
        label=values[4];kind,jockey=types.parse_label(label,names)
        minutes=re.fullmatch(r'(\d+)분',values[8]);duration=int(minutes.group(1))*60 if minutes else None
        r={'horse_id':match.group(1),'website_name':values[3],'label':label,'start':values[6],'end':values[7],
           'duration_seconds':duration,'candidate_type':kind,'jockey_name':jockey,'html_row':rowno}
        index[r['horse_id']].append(r);rows.append(r)
    source=c.execute("""SELECT d.*,a.rider_type,a.type_status FROM daily_training_api_rows d
          JOIN daily_training_rider_type_assignments a USING(daily_training_api_row_id)
          WHERE d.training_date=? AND a.rider_type='미분류'""",(date,)).fetchall()
    counts=Counter();unknown_labels=Counter();matched=0;no_clock=0;ambiguous=0
    for d in source:
        full=[]
        for r in index.get(d['horse_id'],[]):
            if d['start_time_local'] and d['end_time_local'] and d['duration_seconds']:
                if (d['start_time_local'][11:],d['end_time_local'][11:],d['duration_seconds'])==(r['start']+':00',r['end']+':00',r['duration_seconds']):full.append(r)
        if len(full)!=1:
            if len(full)>1:ambiguous+=1
            elif not d['start_time_local'] or not d['duration_seconds']:no_clock+=bool(index.get(d['horse_id']))
            continue
        r=full[0];matched+=1
        obs={'row_id':d['daily_training_api_row_id'],'horse_id':d['horse_id'],'date':date,
             'employee_number':d['prNo_raw'],'api_category':d['prGubun_raw'],'api_name':d['hrName_raw'],
             **r,'source_path':record['source_path'],'source_sha256':record['sha256'],'url':record['url'],
             'form_fields':record['form_fields'],'method':'exact_horse_date_start_end_duration'}
        if r['candidate_type']=='미분류':unknown_labels[r['label']]+=1;unresolved.append(obs)
        else:counts[r['candidate_type']]+=1;evidence.append(obs)
    results.append({'date':date,'website_all_horse_rows':len(rows),'stored_unknown_rows_on_date':len(source),
                    'exact_matched_unknown_rows':matched,'classifiable_counts':dict(counts),'classifiable_rows':sum(counts.values()),
                    'unresolved_exact_label_counts':dict(unknown_labels),'source_missing_timing_horse_date_matches':no_clock,
                    'ambiguous_keys':ambiguous,'all_page_label_counts':dict(Counter(r['label'] for r in rows)),
                    'source_path':record['source_path'],'sha256':record['sha256']})
c.close()
report={'database_modified':False,'method':'Official dated daily detail: exact linked horse ID/date/start/end/duration; explicit role or verified full jockey name only',
        'samples':results,'total_new_classifiable_samples':len(evidence),'candidate_type_counts':dict(Counter(r['candidate_type'] for r in evidence)),
        'evidence':evidence,'exact_unresolved_labels':unresolved}
(HERE/'daily_sample_matches.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('evidence','exact_unresolved_labels','samples')},ensure_ascii=False))
for r in results:print(json.dumps({k:v for k,v in r.items() if k not in ('all_page_label_counts','source_path','sha256')},ensure_ascii=False))
