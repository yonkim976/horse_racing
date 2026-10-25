"""Append the frozen verified dataset; resolve IDs against the live database.

Schema is applied separately through a versioned Supabase migration. This loader
only inserts literal phrases. It never changes horses, races, entries or reports.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import duckdb

from preflight import ROOT, SOURCE, connect

EXPECTED_SHA = '396d7c3fb3ef8c272e154e18ee439c8a9acb8e0001e0e2fa339d2517dfb1a83a'
DATASET_PATH = SOURCE.relative_to(ROOT.parents[2]).as_posix()


def load_source():
    with SOURCE.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == EXPECTED_SHA
    with duckdb.connect(str(SOURCE), read_only=True) as d:
        obs = {r['website_phrase_id']: r for r in d.execute(
            'select * from website_phrase_observations').to_arrow_table().to_pylist()}
        rows = d.execute('select * from horse_steward_phrases '
                         'order by horse_id,event_meet,event_date,event_race,phrase_text').to_arrow_table().to_pylist()
    assert len(rows) == 48130
    assert len({r['horse_id'] for r in rows}) == 9196
    result=[]
    now=int(time.time()*1000)
    for r in rows:
        assert r['text_basis']=='official_website' and r['website_text_verified'] is True
        assert r['historical_publication_time_verified'] is False
        evidence=[]
        for oid in json.loads(r['provenance_ids_json']):
            o=obs[oid]
            assert (o['horse_id'],o['event_meet'],o['event_date'],o['event_race'],o['historical_program']) == (
                r['horse_id'],r['event_meet'],r['event_date'],r['event_race'],r['historical_program'])
            assert o['phrase_text']==r['phrase_text']
            assert o['website_text_raw'][o['span_start_codepoint']:o['span_end_codepoint']]==r['phrase_text']
            url=urlsplit(o['source_url'])
            assert url.scheme=='https' and url.hostname=='race.kra.co.kr'
            captured=int(datetime.fromisoformat(o['captured_at_utc'].replace('Z','+00:00')).timestamp()*1000)
            evidence.append({
                'observation_id':oid,'website_row_id':o['website_row_id'],
                'source_url':o['source_url'],'source_html_sha256':o['source_html_sha256'],
                'source_raw_file':o['source_raw_file'],'observed_at_ms':captured,
                'card_meet':o['card_meet'],'card_date':o['card_date'],'card_race':o['card_race'],
                'current_program':o['current_program'],'bullet_index':o['bullet_index'],
                'span_start_codepoint':o['span_start_codepoint'],'span_end_codepoint':o['span_end_codepoint'],
            })
        assert evidence
        result.append((r['horse_id'],r['event_meet'],r['event_date'],r['event_race'],r['historical_program'],
                       r['phrase_text'],hashlib.sha256(r['phrase_text'].encode()).hexdigest(),
                       json.dumps(evidence,ensure_ascii=False,separators=(',',':')),EXPECTED_SHA,DATASET_PATH,
                       min(e['observed_at_ms'] for e in evidence),max(e['observed_at_ms'] for e in evidence),now))
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--apply',action='store_true',help='Commit the validated append; default rolls back')
    args=p.parse_args()
    source=load_source()
    with connect() as c:
        c.execute("set local lock_timeout='5s'")
        c.execute("set local statement_timeout='120s'")
        c.execute('select pg_advisory_xact_lock(20261017,48130)')
        before=c.execute('select count(*) from public.horse_steward_phrases').fetchone()[0]
        c.execute('''create temporary table phrase_stage (
            kra_horse_id text,meet_code integer,race_date_local date,race_number integer,
            historical_program integer,phrase_text text,phrase_sha256 text,provenance_json text,
            source_dataset_sha256 text,source_dataset_path text,
            first_observed_at_ms bigint,last_observed_at_ms bigint,ingested_at_ms bigint
        ) on commit drop''')
        with c.cursor().copy('copy phrase_stage from stdin') as cp:
            for row in source:
                cp.write_row(row)
        c.execute('analyze phrase_stage')
        c.execute('''create temporary table resolved on commit drop as
            select h.id horse_id,r.id race_id,e.id race_entry_id,rs.id race_steward_report_id,
                   s.historical_program,s.phrase_text,s.phrase_sha256,
                   'official_website'::text text_basis,true website_text_verified,
                   case when e.id is null then 'entry_missing' else 'matched' end entry_link_status,
                   s.provenance_json,s.source_dataset_sha256,s.source_dataset_path,
                   s.first_observed_at_ms,s.last_observed_at_ms,null::bigint source_published_at_ms,
                   false historical_publication_time_verified,s.ingested_at_ms,
                   e.horse_number operational_program
            from phrase_stage s
            left join public.horses h on h.kra_horse_id=s.kra_horse_id
            left join public.racecourses rc on rc.kra_meet_code=s.meet_code
            left join public.races r on r.racecourse_id=rc.id and r.race_date_local=s.race_date_local
                 and r.race_number=s.race_number
            left join public.race_entries e on e.race_id=r.id and e.horse_id=h.id
            left join public.race_steward_reports rs on rs.meet_code=s.meet_code
                 and rs.race_date_local=s.race_date_local and rs.race_number=s.race_number''')
        bad=c.execute('''select count(*) from resolved where horse_id is null or race_id is null
                       or (race_entry_id is not null and operational_program<>historical_program)''').fetchone()[0]
        assert bad==0, f'Operational identity conflict: {bad}'
        columns='''horse_id,race_id,race_entry_id,race_steward_report_id,historical_program,
            phrase_text,phrase_sha256,text_basis,website_text_verified,entry_link_status,provenance_json,
            source_dataset_sha256,source_dataset_path,first_observed_at_ms,last_observed_at_ms,
            source_published_at_ms,historical_publication_time_verified,ingested_at_ms'''
        cur=c.execute('insert into public.horse_steward_phrases ('+columns+') select '+columns+
                      ' from resolved on conflict (horse_id,race_id,phrase_sha256) do nothing')
        inserted=cur.rowcount
        # A full row comparison, excluding ingestion time, also makes retries safe.
        checked=columns.replace(',ingested_at_ms','').replace(' ','').replace('\n','').split(',')
        target_row=','.join('t.'+col for col in checked)
        stage_row=','.join('s.'+col for col in checked)
        mismatches=c.execute('''select count(*) from resolved s left join public.horse_steward_phrases t
            on t.horse_id=s.horse_id and t.race_id=s.race_id and t.phrase_sha256=s.phrase_sha256
            where t.id is null or ('''+target_row+') is distinct from ('+stage_row+')').fetchone()[0]
        assert mismatches==0, f'Source/target mismatch: {mismatches}'
        hash_bad=c.execute('''select count(*) from public.horse_steward_phrases
            where source_dataset_sha256=%s and phrase_sha256<>encode(sha256(convert_to(phrase_text,'UTF8')),'hex')''',
                           (EXPECTED_SHA,)).fetchone()[0]
        assert hash_bad==0
        counts=dict(c.execute('select entry_link_status,count(*) from resolved group by 1').fetchall())
        after=c.execute('select count(*) from public.horse_steward_phrases').fetchone()[0]
        assert after-before==inserted
        receipt={'project_id':'xkykmhhkjtosptoibduo','table':'public.horse_steward_phrases',
                 'source_dataset_sha256':EXPECTED_SHA,'source_rows':len(source),
                 'distinct_horses':9196,'before_rows':before,'inserted_rows':inserted,'after_rows':after,
                 'entry_link_status':counts,'identity_conflicts':bad,'full_row_mismatches':mismatches,
                 'text_hash_mismatches':hash_bad,'historical_publication_times_unknown':True,
                 'commit_requested':args.apply,'finished_at_utc':datetime.now(timezone.utc).isoformat()}
        ids=c.execute('select t.id from public.horse_steward_phrases t join resolved s '
                      'on t.horse_id=s.horse_id and t.race_id=s.race_id and t.phrase_sha256=s.phrase_sha256 '
                      'order by t.id').fetchall()
        if args.apply:
            c.commit()
        else:
            c.rollback()
        receipt['committed']=args.apply
        name='publication' if args.apply else 'dry_run'
        (ROOT/(name+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        if args.apply:
            (ROOT/'published_ids.json').write_text(json.dumps([r[0] for r in ids])+'\n')
        print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':
    main()
