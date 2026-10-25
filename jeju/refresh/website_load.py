"""Append verified homepage training dates; API22 stays separate."""
import hashlib,json
from datetime import datetime,UTC
from pathlib import Path
from jeju.refresh.website import parse_training_html
from jeju.refresh.core import insert,CANON,hold,profile_relation

def apply_website(c,manifest_path,root,run_id):
    if not manifest_path:return {'status':'not_queried','rows_added':0}
    manifest_path=Path(manifest_path);d=json.loads(manifest_path.read_text());digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    profiles={r[0]:r[1] for r in c.execute("select horse_id,horse_profile_observation_id from "+profile_relation(c)+" where breed_label_raw='제주마'")}
    excluded={k for k,v in json.loads((root/'jeju/data/horse_exclusions.json').read_text())['horses'].items() if not v['reimport_allowed']}
    count={'status':d['collection_status'],'rows_added':0,'artifacts_added':0,'unchanged_dates':0,'held_dates':0}
    for e in d.get('dates',[]):
        if e.get('status')!='complete' or not e.get('html_path'):continue
        p=(manifest_path.parent/e['html_path']).resolve();p.relative_to(manifest_path.parent.resolve());raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==e['html_sha256']
        date=e['date'];parsed=parse_training_html(raw,date.replace('-',''));assert parsed # empty cannot replace old rows
        prior=c.execute("select html_sha256 from website_training_artifacts where training_date=? and status='complete'",(date,)).fetchall()
        if any(r[0]==e['html_sha256'] for r in prior):count['unchanged_dates']+=1;continue
        if prior:
            hold(c,run_id,'starting_training_website',date,{'html_sha256':e['html_sha256'],'rows':parsed},{'path':str(p.relative_to(root))},'changed_website_training_date_review_required');count['held_dates']+=1;continue
        aid=insert(c,'website_training_artifacts',dict(artifact_key='refresh:'+date+':'+e['html_sha256'],training_date=date,requested_at_utc=e.get('requested_at') or e.get('received_at') or datetime.now(UTC).isoformat(),collection_directory=str(manifest_path.parent.relative_to(root)),source_url=e.get('url') or e.get('source_url'),html_sha256=e['html_sha256'],status='complete',http_status=200,content_type=e.get('content_type','text/html'),html_relative_path=str(p.relative_to(root)),html_bytes=len(raw),manifest_sha256=digest,row_count=len(parsed),inserted_at_utc=datetime.now(UTC).isoformat()))
        for r in parsed:
            hid=r['horse_id_raw'];eligible=hid in profiles and hid not in excluded
            if not eligible:continue # only validated native IDs enter refreshed website rows
            vals=dict(website_artifact_id=aid,source_row_no=r['source_row_no'],**{k+'_raw':r.get(k) for k in ('affiliation','trainer_no','horse_name','rider','location','note')},horse_id_raw=hid,horse_id=hid,horse_profile_observation_id=profiles[hid],matching_status='verified_website_id_jeju',api_evidence_json=CANON({'status':'separate_website_observation','api22_event_equivalence':'not_asserted'}),raw_row_json=CANON(r['raw_row_json']))
            insert(c,'starting_training_website_rows',vals);count['rows_added']+=1
        count['artifacts_added']+=1
    return count
