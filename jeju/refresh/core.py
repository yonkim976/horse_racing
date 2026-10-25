"""Incremental append-only Jeju core loading. Caller owns transaction."""
from __future__ import annotations
import hashlib,json,re,sqlite3
from pathlib import Path
from datetime import datetime,UTC
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from collections import Counter

CANON=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
DIGEST=lambda x:hashlib.sha256(CANON(x).encode()).hexdigest()
FAMILY={'race_result':('15058305','한국마사회 경주기록 정보','raceResult_3','race_result_entry'), 'running_trial':('15056974','한국마사회 주행심사 상세결과','ridingTestResult_1','running_trial_entry'),'corner_rank':('15119851','한국마사회_경마코너별통과순위_주로빠르기','corner_rank','api303_corner_rank'), 'section_records':(None,'한국마사회 구간별 기록','raceDetailSectionRecord_1','refresh_section_records'), 'starting_training_api':('15059043','한국마사회 출발훈련 정보','startingTranning_1','refresh_starting_training_api'),'horse_profile':('15057985','한국마사회 마필종합 상세정보','totalHorseInfo_1','horse_profile')}
API_PATHS={'race_result':'/API4_3/raceResult_3','running_trial':'/API20_1/ridingTestResult_1','corner_rank':'/API303/corner_rank','section_records':'/API6_1/raceDetailSectionRecord_1','starting_training_api':'/API22_1/startingTranning_1','horse_profile':'/API42_1/totalHorseInfo_1'}
DDL='''CREATE TABLE IF NOT EXISTS research_refresh_runs(run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL,completed_at_utc TEXT, start_date TEXT NOT NULL,end_date TEXT NOT NULL,manifest_path TEXT,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_refresh_observations(observation_id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,family TEXT NOT NULL,natural_key TEXT NOT NULL,source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),source_row_no INTEGER NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,event_date TEXT,decision TEXT NOT NULL,notes TEXT,UNIQUE(source_artifact_id,source_row_no));
CREATE INDEX IF NOT EXISTS ix_refresh_family_key ON research_refresh_observations(family,natural_key);
CREATE TABLE IF NOT EXISTS research_refresh_holds(hold_id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,family TEXT NOT NULL,natural_key TEXT NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,source_path TEXT NOT NULL,reason TEXT NOT NULL,UNIQUE(family,natural_key,payload_sha256,reason));
CREATE TABLE IF NOT EXISTS refresh_section_records(api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),race_date TEXT NOT NULL,meet_code INTEGER NOT NULL,race_number INTEGER NOT NULL,UNIQUE(race_date,meet_code,race_number));
CREATE TABLE IF NOT EXISTS refresh_starting_training_api(api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),training_date TEXT NOT NULL,horse_id TEXT NOT NULL,source_row_no INTEGER NOT NULL,source_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS refresh_section_website_evidence(race_date TEXT NOT NULL,race_number INTEGER NOT NULL,horse_id TEXT NOT NULL,api_payload_sha256 TEXT NOT NULL,website_path TEXT NOT NULL,website_sha256 TEXT NOT NULL,review_json TEXT NOT NULL,PRIMARY KEY(race_date,race_number,horse_id,api_payload_sha256));
'''
def schema(c):
    # No executescript: keep caller's encompassing transaction intact.
    for stmt in DDL.split(';'):
        if stmt.strip():c.execute(stmt)
def text(x):return None if x is None else str(x)
def num(x):
    try:return float(x) if x is not None else None
    except (TypeError,ValueError):return None
def integer(x):
    return int(str(x)) if x is not None and str(x).isdigit() else None
def day(x):
    s=re.sub(r'\D','',str(x or ''));return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s)==8 else None
def safe_path(root,p):
    path=(root/p).resolve();path.relative_to((root/'jeju').resolve());return path
def page_items(root,p):
    raw=safe_path(root,p['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==p['sha256']
    d=json.loads(raw);assert str(d['response']['header']['resultCode'])=='00'
    body=d['response']['body'];vals=(body.get('items') or {})
    vals=vals.get('item',[]) if isinstance(vals,dict) else []
    if isinstance(vals,dict):vals=[vals]
    assert isinstance(vals,list) and all(isinstance(r,dict) for r in vals)
    return raw,vals

def artifact(c,p,raw,run_id):
    row=c.execute('select source_artifact_id from source_artifacts where raw_relative_path=? and sha256=?',(p['path'],p['sha256'])).fetchone()
    if row:return row[0]
    f=p['family'];ds,name,op,_=FAMILY[f];url=p.get('source_url_without_key') or 'https://apis.data.go.kr/B551015'+API_PATHS[f]+'?'+urlencode(p.get('params',{}))
    assert 'servicekey=' not in url.lower()
    params=p.get('params',{});assert not any(k.lower() in ('servicekey','service_key') for k in params)
    return c.execute('''insert into source_artifacts(source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,attempt_id,request_params_json,source_url_without_key,collected_at_utc,http_status_code,content_type,raw_relative_path,response_bytes,sha256,parser_version,created_at_utc) values('kra_openapi','primary',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(ds,name,url.split('?')[0],p.get('operation',op),run_id,CANON(params),url,p['collected_at_utc'],200,'application/json',p['path'],len(raw),p['sha256'],'jeju-research-refresh-v1',datetime.now(UTC).isoformat())).lastrowid

def insert(c,table,values):
    # Only internal literal identifiers; values are always bound.
    assert re.fullmatch(r'[a-z_0-9]+',table) and all(re.fullmatch(r'[a-zA-Z_0-9]+',k) for k in values)
    cols=list(values)
    return c.execute('INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(values[k] for k in cols)).lastrowid

def hold(c,run_id,f,key,row,p,reason):
    c.execute('insert or ignore into research_refresh_holds(run_id,family,natural_key,payload_sha256,payload_json,source_path,reason) values(?,?,?,?,?,?,?)',(run_id,f,key,DIGEST(row),CANON(row),p['path'],reason))

def profile_relation(c):
    """Same latest-profile semantics with a bounded, key-directed join order."""
    if c.execute("select 1 from sqlite_master where name='horse_profile_refresh_current'").fetchone():
        return 'horse_profile_refresh_current'
    sql=c.execute("select sql from sqlite_master where name='horse_profile_latest'").fetchone()[0]
    body=re.split(r'\bAS\b',sql,maxsplit=1,flags=re.I)[1].replace('JOIN api_records','CROSS JOIN api_records').replace('JOIN source_artifacts','CROSS JOIN source_artifacts')
    return '('+body+')'

def apply_core(c,pages,root,run_id,start,end):
    schema(c);count=Counter();stats={}
    excluded={k for k,v in json.loads((root/'jeju/data/horse_exclusions.json').read_text())['horses'].items() if not v['reimport_allowed']}
    profiles={r[0]:r[1] for r in c.execute('select horse_id,breed_label_raw from '+profile_relation(c))}
    ordered=sorted((p for p in pages if p['family'] in FAMILY and p.get('path') and p.get('sha256') and p.get('pagination_complete',True)),key=lambda p:(p['family']!='horse_profile',p['family'],p['path']))
    for p in ordered:
        f=p['family'];fc=Counter();raw,rows=page_items(root,p);aid=artifact(c,p,raw,run_id)
        # Preserve legitimate repeated source items without counting a later capture twice.
        occurrences=Counter()
        for idx,r in enumerate(rows,1):
            fc['raw_rows']+=1;hid=text(r.get('hrNo'));event=day(r.get({'race_result':'rcDate','running_trial':'trainDate','corner_rank':'rcDate','section_records':'rcDate','starting_training_api':'trDate'}.get(f,'')))
            if f!='horse_profile' and (not event or not start<=event<=end):fc['outside_window']+=1;continue
            if hid in excluded:fc['excluded']+=1;continue
            if f=='race_result' and event in {'2026-07-07','2026-08-25','2026-08-26'}:fc['excluded_replay']+=1;continue
            if f not in ('corner_rank','section_records','horse_profile') and profiles.get(hid)!='제주마':
                key=f'{event}|{hid}';hold(c,run_id,f,key,r,p,'official_profile_breed_unconfirmed');fc['held']+=1;continue
            if f=='horse_profile':
                key=hid
                if not hid or not re.fullmatch(r'\d{7}',hid):fc['invalid']+=1;continue
                if r.get('breed')!='제주마':hold(c,run_id,f,key,r,p,'profile_non_native_or_unknown');fc['held']+=1;continue
            else:
                if str(r.get('meet')) not in ('제주','2'):raise ValueError('Unexpected meet')
                rn=integer(r.get('rcNo' if f!='running_trial' else 'trainNo'))
                key=f'{event}|2|{rn}'
                if f in ('race_result','running_trial'):key+=f"|{integer(r.get('chulNo'))}|{hid}"
                elif f=='starting_training_api':key=f'{event}|{hid}|{DIGEST(r)}'
            digest=DIGEST(r);occurrences[(key,digest)]+=1
            if c.execute('select 1 from research_refresh_observations where source_artifact_id=? and source_row_no=?',(aid,idx)).fetchone():fc['replay_skipped']+=1;continue
            record_type=FAMILY[f][3]
            existing=[]
            if f in ('race_result','running_trial','horse_profile','corner_rank'):
                if f=='corner_rank':existing=c.execute('select a.payload_sha256,a.api_record_id from api303_corner_rank_rows x join api_records a using(api_record_id) where x.race_date=? and x.meet_code=2 and x.race_number=?',(event,integer(r.get('rcNo')))).fetchall()
                elif f=='horse_profile':existing=c.execute('select a.payload_sha256,a.api_record_id from horse_profile_observations x join api_records a using(api_record_id) where horse_id=? order by observed_at_utc desc limit 1',(hid,)).fetchall()
                else:existing=c.execute('select payload_sha256,api_record_id from api_records where record_type=? and natural_key=?',(record_type,key)).fetchall()
            elif f=='section_records':existing=c.execute('select a.payload_sha256,a.api_record_id from refresh_section_records x join api_records a using(api_record_id) where race_date=? and meet_code=2 and race_number=?',(event,integer(r.get('rcNo')))).fetchall()
            else:
                prior=c.execute('select count(*) from research_refresh_observations where family=? and natural_key=? and payload_sha256=? and decision=?',(f,key,digest,'inserted')).fetchone()[0]
                if prior>=occurrences[(key,digest)]:existing=[(digest,None)]
            decision='inserted'
            if any(x[0]==digest for x in existing):decision='unchanged';fc['unchanged']+=1
            elif existing and f!='horse_profile':decision='held';hold(c,run_id,f,key,r,p,'changed_official_payload_review_required');fc['held']+=1
            elif f=='running_trial' and r.get('majong')!='제주':decision='held';hold(c,run_id,f,key,r,p,'trial_breed_label_conflict');fc['held']+=1
            if decision=='inserted':
                rec=insert(c,'api_records',dict(source_artifact_id=aid,record_index=idx,record_type=record_type,natural_key=key,payload_json=CANON(r),payload_sha256=digest))
                if f=='race_result':
                    vals=dict(api_record_id=rec,race_date=event,meet_code=2,race_number=integer(r.get('rcNo')),horse_number=integer(r.get('chulNo')),horse_id=hid,horse_name=text(r.get('hrName')),race_distance_m=integer(r.get('rcDist')),rank_class_raw=text(r.get('rank')),race_name_raw=text(r.get('rcName')),finish_position=integer(r.get('ord')),finish_status_raw=text(r.get('ord')),finish_time_seconds=num(r.get('rcTime')),carried_weight_kg=num(r.get('wgBudam')),body_weight_raw=text(r.get('wgHr')),jockey_id=text(r.get('jkNo')),jockey_name=text(r.get('jkName')),trainer_id=text(r.get('trNo')),trainer_name=text(r.get('trName')),owner_id=text(r.get('owNo')),owner_name=text(r.get('owName')),track_raw=text(r.get('track')),weather_raw=text(r.get('weather')),breed_label_raw=None,breed_assessment='api_cross_reference_candidate',breed_assessment_note='Official API42 current 제주마 profile matched by horse ID; retrieval-time breed evidence is not historical effective date.')
                    insert(c,'race_result_rows',vals)
                elif f=='running_trial':
                    vals=dict(api_record_id=rec,trial_date=event,meet_code=2,trial_number=integer(r.get('trainNo')),horse_number=integer(r.get('chulNo')),horse_id=hid,horse_name=text(r.get('hrName')),finish_position=integer(r.get('ord')),finish_status_raw=text(r.get('ord')),finish_time_seconds=num(r.get('rcTime')),body_weight_kg=num(r.get('wgHr')),carried_weight_base_kg=num(r.get('wgBudam')),jockey_overweight_kg=num(r.get('wgJkAdd')),jockey_id=text(r.get('jkNo')),jockey_name=text(r.get('jkName')),trainer_id=text(r.get('trNo')),trainer_name=text(r.get('trName')),pass_flag_raw=text(r.get('passFlag')),failure_reason_raw=text(r.get('nopassReason')),inspection_reason_raw=text(r.get('inspeReason')),section_times_json=CANON({k:v for k,v in r.items() if k.startswith(('s1f','g1f','g2f','g3f','g4f','g6f','g8f','rcTime','passtime'))}),breed_label_raw=text(r.get('majong')),breed_assessment='api_native_label',breed_assessment_note="API20 majong='제주'; official current API42 profile matched separately.")
                    insert(c,'running_trial_rows',vals)
                elif f=='corner_rank':
                    vals=dict(api_record_id=rec,race_date=event,meet_code=2,race_number=integer(r.get('rcNo')),api_meet_raw=text(r.get('meet')),**{k+'_raw':text(r.get(k)) for k in [*(f'corner_{i}' for i in range(1,10)),'passtime_3f','passtime_4f','tempo']});insert(c,'api303_corner_rank_rows',vals)
                elif f=='section_records':insert(c,'refresh_section_records',dict(api_record_id=rec,race_date=event,meet_code=2,race_number=integer(r.get('rcNo'))))
                elif f=='starting_training_api':insert(c,'refresh_starting_training_api',dict(api_record_id=rec,training_date=event,horse_id=hid,source_row_no=idx,source_status='separate_api22_not_website_equivalent'))
                elif f=='horse_profile':
                    obs=p['collected_at_utc'];dt=datetime.fromisoformat(obs.replace('Z','+00:00'));birth=text(r.get('birthDt')) or (str(r.get('birthYr'))+'-01-01' if r.get('birthYr') else None)
                    if r.get('birthDt') is None and birth:birth=str(r['birthYr']) # retain year precision
                    insert(c,'horse_profile_observations',dict(api_record_id=rec,horse_id=hid,observed_at_utc=obs,observed_kst_date=dt.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat(),horse_name_raw=text(r.get('hrNm')),birth_date_raw=birth,age_raw=text(r.get('age')),breed_label_raw=text(r.get('breed')),sex_raw=text(r.get('sex')),color_raw=text(r.get('color')),production_country_raw=text(r.get('prdCty'))))
                    insert(c,'breed_evidence',dict(horse_id=hid,observed_event_date=None,breed_label_raw=r['breed'],evidence_kind='API42_1 current profile breed',source_artifact_id=aid,api_record_id=rec,timing_basis='profile_retrieval_time',notes='Refresh retrieval-time evidence; historical effective breed date not asserted.'))
                    profiles[hid]=r['breed']
                fc['inserted']+=1
            insert(c,'research_refresh_observations',dict(run_id=run_id,family=f,natural_key=key,source_artifact_id=aid,source_row_no=idx,payload_sha256=digest,payload_json=CANON(r),event_date=event,decision=decision,notes=None))
        stats.setdefault(f,Counter()).update(fc)
    return {f:dict(v) for f,v in stats.items()}

def add_website_evidence(c,root):
    src=root/'jeju/predictions/refresh_20261017_full_20261016/reviewed_new_sections.json'
    if not src.exists():return 0
    n=0; original={}
    archive=root/'jeju/predictions/refresh_20261017_history_20261016/official'
    archived_manifest=json.loads((archive/'manifest.json').read_text())
    for dataset in archived_manifest['datasets']:
        if not dataset['name'].startswith('results_'):continue
        for pg in dataset['pages']:
            body=(archive/pg['path']).read_bytes();assert hashlib.sha256(body).hexdigest()==pg['sha256']
            doc=json.loads(body)['response']['body'];rawitems=(doc.get('items') or {});rawitems=rawitems.get('item',[]) if isinstance(rawitems,dict) else [];rawitems=[rawitems] if isinstance(rawitems,dict) else rawitems
            for item in rawitems:original[(day(item['rcDate']),integer(item['rcNo']),str(item['hrNo']))]=DIGEST(item)
    for r in json.loads(src.read_text()):
        p=safe_path(root,r['website_source_path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==r['website_source_sha256']
        match=c.execute('select a.payload_sha256 from race_result_rows x join api_records a using(api_record_id) where race_date=? and meet_code=2 and race_number=? and horse_id=?',(r['event_date'],r['race_no'],r['horse_id'])).fetchall()
        if len(match)!=1:continue
        if original.get((r['event_date'],r['race_no'],r['horse_id']))!=match[0][0]:continue # historical review may only witness its original API payload
        n+=c.execute('insert or ignore into refresh_section_website_evidence values(?,?,?,?,?,?,?)',(r['event_date'],r['race_no'],r['horse_id'],match[0][0],r['website_source_path'],r['website_source_sha256'],CANON(r))).rowcount
    return n
