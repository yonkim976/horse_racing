"""Persist event-specific rider types; never infer historical roles from names."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import argparse
import hashlib
import json
import re
import sqlite3
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
SOURCE = ROOT / 'jeju/research/20261015_training_rider_identity/source_review'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261015_add_training_rider_types.sql'
API_TYPES = {'기수', '조교사', '조교보', '조교승인', '기수후보생'}
TYPES = ('기수', '조교사', '조교보', '조교승인', '기수후보생', '주로조교', '교육생', '기수트랙라이더', '미분류')
FIELDS = ('daily_training_api_row_id', 'daily_training_api_artifact_id', 'prGubun_raw',
          'prNo_raw', 'horse_id', 'training_date', 'start_time_local', 'end_time_local',
          'duration_seconds', 'rider_type', 'type_status', 'website_type',
          'website_label_raw', 'website_jockey_name', 'website_source_path', 'website_sha256')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def parse_label(label, jockey_names):
    if label in ('', '-', '외', '경주일'):
        return '미분류', None
    for token, kind in (('조','조교사'), ('관','주로조교'), ('생','교육생'), ('트','기수트랙라이더')):
        if (label == token and token!='트') or label.endswith('(' + token + ')'):
            return kind, None
    if label in jockey_names:
        return '기수', label
    return '미분류', None


def same_event_web(c):
    ledger_path = SOURCE / 'http_collection_manifest.json'
    manifest = json.loads(ledger_path.read_text())
    pages = manifest['pages']
    jockey_names = set()
    roster_manifest = json.loads((ROOT/'data/research/jockey_roster_20261008/manifest.json').read_text())
    for meet in (1,2,3):
        p = ROOT / f'data/research/jockey_roster_20261008/api_{meet}.json'
        require({r['api_sha256'] for r in roster_manifest['rows'] if r['meet_code']==meet}=={sha(p)}, 'API307 archive SHA changed')
        body = json.loads(p.read_text())['response']['body']
        items = body['items']['item']
        items = [items] if isinstance(items, dict) else items
        require(len(items) == int(body['totalCount']), 'Incomplete API307 roster')
        jockey_names.update(r['jkName'] for r in items if r.get('jkName') not in (None,'','-'))
    selected_horses = {p['horse_id'] for p in pages}
    source_rows = c.execute('''SELECT daily_training_api_row_id,horse_id,training_date,
        start_time_local,end_time_local,duration_seconds FROM daily_training_api_rows
        WHERE training_date>='2026-04-15' AND start_time_local IS NOT NULL
          AND end_time_local IS NOT NULL AND duration_seconds>0''')
    by_key = {}
    for r in source_rows:
        if r['horse_id'] not in selected_horses:
            continue
        key = (r['horse_id'],r['training_date'],r['start_time_local'][11:16],
               r['end_time_local'][11:16],r['duration_seconds'])
        by_key.setdefault(key,[]).append(r['daily_training_api_row_id'])
    matches = {}
    for p in pages:
        require(p['http_status']==200, 'Failed source page')
        path = (ROOT/p['source_path']).resolve(strict=True)
        require(path.is_relative_to(SOURCE), 'Unsafe source path')
        require(sha(path)==p['sha256'], 'Website source SHA changed')
        parsed_url = urlsplit(p['url'])
        params = parse_qs(parsed_url.query)
        require(parsed_url.scheme=='https' and parsed_url.hostname=='race.kra.co.kr'
                and parsed_url.path=='/racehorse/profileTrainState.do'
                and params.get('meet')==['2'] and params.get('hrNo')==[p['horse_id']], 'Wrong official page')
        soup = BeautifulSoup(path.read_bytes().decode('euc-kr'),'html.parser')
        require(soup.find('input',attrs={'name':'hrNo'}).get('value')==p['horse_id'], 'Horse ID mismatch')
        require('기승자범례' in soup.get_text(), 'Website legend absent')
        for tr in soup.find_all('tr'):
            cells = [td.get_text(' ',strip=True) for td in tr.find_all('td')]
            if len(cells)!=7 or not re.match(r'^\d{4}/\d{2}/\d{2}',cells[1]):
                continue
            if not re.fullmatch(r'\d{2}:\d{2}',cells[3]) or not re.fullmatch(r'\d{2}:\d{2}',cells[4]):
                continue
            mins = re.fullmatch(r'(\d+)분',cells[5])
            if not mins:
                continue
            duration = int(mins.group(1))*60
            start = int(cells[3][:2])*60+int(cells[3][3:])
            end = int(cells[4][:2])*60+int(cells[4][3:])
            if (end-start)*60!=duration:
                continue
            key = (p['horse_id'], cells[1][:10].replace('/','-'),cells[3],cells[4],duration)
            ids = by_key.get(key,[])
            require(len(ids)<=1, 'Ambiguous API event key')
            if not ids:
                continue
            kind, name = parse_label(cells[2],jockey_names)
            row = {'website_type':kind, 'website_label_raw':cells[2],
                   'website_jockey_name':name, 'website_source_path':p['source_path'],
                   'website_sha256':p['sha256']}
            if ids[0] in matches:
                require(matches[ids[0]]==row,'Multiple website labels for event')
            matches[ids[0]] = row
    return matches, {'website_pages':len(pages),'same_event_matches':len(matches),
                     'web_type_counts':dict(Counter(x['website_type'] for x in matches.values())),
                     'website_manifest_sha256':sha(ledger_path)}


def classified_rows(c, web):
    for r in c.execute('''SELECT daily_training_api_row_id,daily_training_api_artifact_id,
        prGubun_raw,prNo_raw,horse_id,training_date,start_time_local,end_time_local,duration_seconds
        FROM daily_training_api_rows ORDER BY daily_training_api_row_id'''):
        result = dict(r)
        api = r['prGubun_raw'] if r['prGubun_raw'] in API_TYPES else None
        observed = web.get(r['daily_training_api_row_id'])
        wkind = observed['website_type'] if observed else None
        kind, status = '미분류', 'unclassified_api_category_missing'
        if api:
            kind, status = api, 'api_category_observed'
            if wkind and wkind != '미분류' and wkind != api:
                if api=='기수' and wkind=='기수트랙라이더':
                    kind,status = wkind,'website_track_rider_specialization'
                elif (api=='기수후보생' and wkind=='교육생') or (api in ('조교보','조교승인') and wkind=='주로조교'):
                    status = 'api_category_website_compatible'
                else:
                    kind,status = '미분류','api_website_type_conflict'
        elif wkind and wkind!='미분류':
            kind,status = wkind,'website_same_event_type'
        elif observed:
            status = 'unclassified_website_label'
        result.update({'rider_type':kind,'type_status':status})
        result.update(observed or {k:None for k in FIELDS[11:]})
        yield result


def statements(text):
    buf=''
    for line in text.splitlines(keepends=True):
        buf+=line
        if sqlite3.complete_statement(buf):
            yield buf
            buf=''
    require(not buf.strip(),'Incomplete migration')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=DB)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-db-sha256')
    args=parser.parse_args()
    db=args.db.resolve(strict=True); output=args.output.resolve()
    require(db==DB or db.is_relative_to(HERE),'Only local Jeju or staged database allowed')
    require(output.is_relative_to(HERE) and not output.exists(),'Use new output in work folder')
    web_path=output.with_suffix('.website_matches.json')
    require(not web_path.exists(),'Website matches sidecar already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(db.as_uri()+('?mode=rw' if args.apply else '?mode=ro'),uri=True)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    if not args.apply:c.execute('PRAGMA query_only=ON')
    require({r[0] for r in c.execute('SELECT DISTINCT prGubun_raw FROM daily_training_api_rows')}==API_TYPES|{'-'},
            'API category population changed; review the new source values first')
    web,summary=same_event_web(c)
    counts={scope:Counter({t:0 for t in TYPES}) for scope in ('all','analysis_2026','from_2017')}
    statuses=Counter();digest=hashlib.sha256()
    for row in classified_rows(c,web):
        digest.update((canonical(row)+'\n').encode())
        counts['all'][row['rider_type']]+=1
        if row['training_date']<='2026-09-19':counts['analysis_2026'][row['rider_type']]+=1
        if '2017-01-01'<=row['training_date']<='2026-09-19':counts['from_2017'][row['rider_type']]+=1
        statuses[row['type_status']]+=1
    require(sum(counts['all'].values())==908316,'Source population changed')
    summary.update({'rider_type_counts':counts,'status_counts':statuses,
                    'classification_sha256':digest.hexdigest(),'model_inputs_modified':False,
                    'database_modified':False})
    if args.apply:
        require(args.expected_db_sha256 and sha(db)==args.expected_db_sha256,'DB SHA mismatch')
        if db==DB:require((HERE/'before_types.sqlite3').exists(),'Production backup required')
        previous=dict((r['name'],r['sql']) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
        existing=c.execute("SELECT 1 FROM sqlite_master WHERE name='daily_training_rider_type_assignments'").fetchone()
        if existing and c.execute('SELECT COUNT(*) FROM daily_training_rider_type_assignments').fetchone()[0]:
            actual=hashlib.sha256()
            for r in c.execute('SELECT * FROM daily_training_rider_type_assignments ORDER BY daily_training_api_row_id'):
                actual.update((canonical(dict(r))+'\n').encode())
            require(actual.hexdigest()==digest.hexdigest(),'Existing classification differs')
            summary['status']='already_applied'
        else:
            c.execute('BEGIN IMMEDIATE')
            try:
                for sql in statements(MIGRATION.read_text()):c.execute(sql)
                c.executemany('INSERT INTO daily_training_rider_type_assignments ('+','.join(FIELDS)+') VALUES ('+','.join('?' for _ in FIELDS)+')',
                              (tuple(row[k] for k in FIELDS) for row in classified_rows(c,web)))
                after=dict((r['name'],r['sql']) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                require(all(after.get(k)==v for k,v in previous.items()),'Existing schema changed')
                require(not c.execute('PRAGMA foreign_key_check(daily_training_rider_type_assignments)').fetchall(),'FK failure')
                require(c.execute('SELECT COUNT(*) FROM daily_training_rider_types').fetchone()[0]==908316,'View count mismatch')
                c.commit()
            except BaseException:
                c.rollback();raise
            summary.update(status='applied',database_modified=True,applied_at_utc=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    web_path.write_text(json.dumps(web,ensure_ascii=False,indent=2)+'\n')
    c.close();print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
