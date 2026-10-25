"""Read-only spot check of missing API18 rider categories against official HTML."""
from pathlib import Path
import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

fetch = module('official_training_reader', 'jeju/research/20261015_training_rider_identity/source_review/collect_kra_training_html.py')
types = module('official_training_types', 'jeju/research/20261015_training_rider_types/classify_riders.py')
c = sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro', uri=True)
c.row_factory = sqlite3.Row
horses = [r[0] for r in c.execute("""SELECT horse_id FROM daily_training_rider_type_assignments
 WHERE rider_type='미분류' AND training_date>='2026-04-17'
 GROUP BY horse_id ORDER BY count(*) DESC,horse_id LIMIT 8""")]
names = set()
for meet in (1,2,3):
    source = ROOT/f'data/research/jockey_roster_20261008/api_{meet}.json'
    items = json.loads(source.read_text())['response']['body']['items']['item']
    for item in ([items] if isinstance(items,dict) else items):
        if item.get('jkName') not in (None,'','-'):
            names.add(item['jkName'])
rows = c.execute("""SELECT d.*,a.rider_type,a.type_status
 FROM daily_training_api_rows d JOIN daily_training_rider_type_assignments a
 ON a.daily_training_api_row_id=d.daily_training_api_row_id
 WHERE d.training_date>='2026-04-17'""").fetchall()
c.close()
bykey = {}
for r in rows:
    if r['horse_id'] not in horses or not r['start_time_local'] or not r['end_time_local'] or not r['duration_seconds']:
        continue
    key = (r['horse_id'],r['training_date'],r['start_time_local'][11:16],r['end_time_local'][11:16],r['duration_seconds'])
    bykey.setdefault(key,[]).append(dict(r))

def check(horse):
    try:
        page = fetch.fetch_page({'horse_id':horse,'url':fetch.profile_url(horse)})
        body = page.pop('body')
        path = OUT/'html'/f'{horse}.html'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        page['source_path'] = str(path.relative_to(ROOT))
        text = fetch.decode_html(body,page['content_type'])
        parsed = fetch.parse_page(body,page['content_type'],horse)
        if not parsed['profile_id_matches_url'] or not parsed['training_table_found']:
            raise ValueError('Official horse ID or training table not verified')
        soup = BeautifulSoup(text,'html.parser')
        page['profile_name'] = parsed['profile_name_raw']
        page['page_training_dates'] = {'first':min((x['date'] for x in parsed['training_rows']),default=None),'last':max((x['date'] for x in parsed['training_rows']),default=None)}
        page['six_month_notice'] = [s for s in soup.stripped_strings if '6개월' in s]
        page['legend_text'] = [s for s in soup.stripped_strings if any(x in s for x in ('주로조교','트랙라이더','기승자범례','교육생'))]
        page['form_fields'] = [{'name':x.get('name'),'type':x.get('type'),'value':x.get('value')} for x in soup.select('form input,form select')]
        observations=[]
        ambiguous=[]
        for w in parsed['training_rows']:
            if fetch.clock_minutes(w['end'])-fetch.clock_minutes(w['start'])!=w['duration_minutes']:
                continue
            key=(horse,w['date'],w['start'],w['end'],w['duration_minutes']*60)
            matches=bykey.get(key,[])
            if len(matches)>1:
                ambiguous.append({'key':key,'row_ids':[r['daily_training_api_row_id'] for r in matches]})
                continue
            if not matches:
                continue
            r=matches[0]
            if r['rider_type']!='미분류':
                continue
            kind,jockey=types.parse_label(w['website_name_raw'],names)
            observations.append({'row_id':r['daily_training_api_row_id'],'horse_id':horse,'horse_name':parsed['profile_name_raw'],'date':w['date'],'start':w['start'],'end':w['end'],'minutes':w['duration_minutes'],'api_category':r['prGubun_raw'],'employee_number':r['prNo_raw'],'website_label':w['website_name_raw'],'candidate_type':kind,'candidate_jockey_name':jockey,'source_sha256':page['sha256'],'source_path':page['source_path']})
        page['unclassified_exact_matches']=len(observations)
        page['candidate_type_counts']=dict(Counter(x['candidate_type'] for x in observations))
        return {'page':page,'observations':observations,'ambiguous':ambiguous}
    except Exception as e:
        return {'page':{'horse_id':horse,'error':str(e)},'observations':[],'ambiguous':[]}

with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(check,horses))
allobs=[o for r in results for o in r['observations']]
report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'db_modified':False,'sample_selection':'Top 8 horses by unclassified records from 2026-04-17; not a population estimate','pages':[r['page'] for r in results],'observations':allobs,'ambiguous':[a for r in results for a in r['ambiguous']],'candidate_type_counts':dict(Counter(o['candidate_type'] for o in allobs)),'matched_unclassified_rows':len(allobs)}
(OUT/'website_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('observations','pages')},ensure_ascii=False))
print(json.dumps([{'horse_id':r['page']['horse_id'],'error':r['page'].get('error'),'counts':r['page'].get('candidate_type_counts')} for r in results],ensure_ascii=False))
