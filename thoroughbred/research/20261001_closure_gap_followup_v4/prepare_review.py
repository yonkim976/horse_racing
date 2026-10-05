"""Normalize reviewed evidence while leaving original API and previous reviews intact."""
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))

def write(path, fields, rows):
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def union(sources, destination):
    data, fields = [], ['evidence_package']
    for source in sources:
        for row in read(source):
            data.append({'evidence_package':str(source.relative_to(ROOT)),**row})
            for field in row:
                if field not in fields:
                    fields.append(field)
    write(destination,fields,data)
    return len(data)

def main():
    approved=HERE/'root_approved'
    review=HERE/'core_review'
    approved.mkdir(exist_ok=True)
    review.mkdir(exist_ok=True)
    daily=read(ROOT/'thoroughbred/research/20260929_calendar_api_v1/daily_calendar.csv')
    calendar={(r['meet'],r['date']):r for r in daily}
    candidates=[]
    verification=[]
    for package in ('early_2010_2013','years_2014_2015'):
        source=HERE/package/'interval_candidates.csv'
        for original in read(source):
            meet=original.get('meet_code',original.get('meet'))
            left,right=date.fromisoformat(original['start_date']),date.fromisoformat(original['end_date'])
            assert meet in ('1','3') and left<=right
            dates=[left+timedelta(days=n) for n in range((right-left).days+1)]
            executed=sum(int(calendar[(meet,d.isoformat())]['executed_race_count']) for d in dates)
            scheduled=sum(int(calendar[(meet,d.isoformat())]['scheduled_race_count']) for d in dates)
            if 'api_executed_races' in original:
                assert int(original['api_executed_races'])==executed
            if 'api_scheduled_races' in original:
                assert int(original['api_scheduled_races'])==scheduled
            evidence=json.loads(original.get('source_evidence','[]'))
            for item in evidence:
                assert sha(ROOT/item['raw_file'])==item['sha256']
            if original.get('capture_path'):
                assert sha(ROOT/original['capture_path'])==original['capture_sha256']
            candidate={
                'candidate_id':package+'_'+original['candidate_id'],
                'meet_code':meet,'venue':original['venue'],
                'start_date':original['start_date'],'end_date':original['end_date'],
                'reason':original['reason'],
                'evidence_kind':original.get('evidence_kind',original.get('review_class','')),
                'source_url':original.get('source_url',';'.join(item['url'] for item in evidence)),
                'status':original.get('status',original.get('integration_status','')),
                'api_scheduled_races':scheduled,'api_executed_races':executed,
                'evidence_package':str(source.relative_to(ROOT)),
                'original_record_json':json.dumps(original,ensure_ascii=False),
            }
            candidates.append(candidate)
            verification.append({k:candidate[k] for k in ('candidate_id','meet_code','start_date','end_date','api_scheduled_races','api_executed_races')})
    assert len({r['candidate_id'] for r in candidates})==len(candidates)
    write(approved/'closure_gap_review_candidates.csv',list(candidates[0]),candidates)
    amendments=[HERE/'early_2010_2013/plan_amendments.csv',HERE/'years_2014_2015/plan_amendments.csv']
    amendment_count=union(amendments,approved/'closure_plan_amendment_review.csv')
    questions=[HERE/package/'user_review_items.csv' for package in ('early_2010_2013','years_2014_2015','year_2021')]
    question_count=union(questions,approved/'closure_review_questions.csv')
    additions=read(HERE/'year_2021/interval_candidates.csv')
    assert len(additions)==4
    for r in additions:
        assert r['evidence_kind']=='kra_authored_plan_user_supplied'
        left,right=date.fromisoformat(r['start_date']),date.fromisoformat(r['end_date'])
        assert r['meet_code'] in ('1','3')
        assert (r['start_date'],r['end_date']) in (('2021-01-01','2021-01-03'),('2021-02-12','2021-02-14'))
        assert all(int(calendar[(r['meet_code'],(left+timedelta(days=i)).isoformat())]['executed_race_count'])==0 for i in range((right-left).days+1))
    coverage=read(ROOT/'thoroughbred/research/20261001_remaining_closure_cancel_v3/core_review/reviewed_year_coverage.csv')
    for r in coverage:
        if r['year']=='2021':
            r.update(coverage_status='annual_table_user_supplied_q3_corroborated',notes='KRA-authored annual closure table visually reviewed from user PDF; Jan/Feb 4 intervals added. Q3 dates match prior sourced table; Q1 Friday plan and API weekday transition reconcile February gap. Exhaustive amendment history is not established.')
        elif int(r['year'])<=2015:
            r['notes']='Selected reported exact-date candidates and conflicting earlier plans catalogued in v4; full primary annual/amendment coverage not established. Secondary leads are not promoted to official closures.'
    write(review/'reviewed_year_coverage.csv',list(coverage[0]),coverage)
    validation={'candidate_count':len(candidates),'amendment_count':amendment_count,'review_item_count':question_count,'primary_additions':4,'primary_new_venue_days':12,'api_candidate_reconciliation':verification,'candidate_capture_hashes_verified':True}
    (review/'source_package_verification.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
    config=json.loads((ROOT/'thoroughbred/research/20261001_remaining_closure_cancel_v3/core_review/approved_inputs.json').read_text())
    config['closure_paths'].append(str((HERE/'year_2021/interval_candidates.csv').relative_to(ROOT)))
    config['closure_coverage_status']='partial; 81 sourced intervals / 552 venue-days including 4 user-supplied KRA-authored annual-plan intervals and 2 official-start/API-end intervals; secondary historical leads and amendment gaps retained'
    config['closure_source_coverage_path']=str((review/'reviewed_year_coverage.csv').relative_to(ROOT))
    config['closure_coverage_gaps']=[
        {'years':'2010–2015','gap':'Selected secondary reports provide exact dates; full official annual and amended closure schedules remain incomplete. Conflicting original plans are retained as superseded or unclassified, not API errors.'},
        {'years':'2020','gap':'Sep1 start is official; Oct15 end is API-derived. Explicit official end notice not recovered.'},
        {'years':'2021','gap':'Annual closure table now reviewed from user PDF; original hosting URL and official Feb19 weekday-change notice not recovered. Exhaustive amendments not established.'},
        {'years':'2016–2026','gap':'Reviewed source tables do not establish exhaustive amendment coverage.'},
    ]
    for name in ('closure_gap_review_candidates','closure_plan_amendment_review','closure_review_questions'):
        config['extra_csv_exports'][name+'.csv']=str((approved/(name+'.csv')).relative_to(ROOT))
    pins={r['path']:r for r in config['pinned_files']}
    for path in sorted(HERE.rglob('*')):
        if not path.is_file() or path.name in ('approved_inputs.json','root_verification.json','independent_db_verification.json'):
            continue
        if path.parent==review and path.name not in ('verify_db_preservation.py','reviewed_year_coverage.csv','source_package_verification.json'):
            continue
        relative=str(path.relative_to(ROOT))
        pins[relative]={'path':relative,'sha256':sha(path)}
    config['pinned_files']=list(pins.values())
    assert all(sha(ROOT/r['path'])==r['sha256'] for r in config['pinned_files'])
    (review/'approved_inputs.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({**{k:v for k,v in validation.items() if k!='api_candidate_reconciliation'},'pinned_files':len(pins)},ensure_ascii=False))

if __name__=='__main__':
    main()
