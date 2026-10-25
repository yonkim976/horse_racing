"""Read operational identity keys without changing persistent data."""
import json
from pathlib import Path

import duckdb
import psycopg
from sqlalchemy.engine import make_url

from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / '20261013_steward_horse_phrases_v1/outputs/horse_steward_phrases.duckdb'


def connect():
    u = make_url(get_settings().database_url)
    assert u.host == 'aws-0-ap-northeast-2.pooler.supabase.com'
    assert u.username == 'postgres.xkykmhhkjtosptoibduo'
    return psycopg.connect(host=u.host, port=u.port, dbname=u.database,
                          user=u.username, password=u.password, sslmode='require',
                          connect_timeout=20)


def main():
    with duckdb.connect(str(SOURCE), read_only=True) as d:
        source = d.execute('select horse_id,event_meet,event_date,event_race,historical_program '
                           'from horse_steward_phrases').fetchall()
    with connect() as c:
        # Only transient staging is written. All operational tables remain read-only.
        c.execute('set statement_timeout = 60000')
        c.execute('create temporary table phrase_keys (kra_horse_id text, meet_code integer, '
                  'race_date_local date, race_number integer, historical_program integer) on commit drop')
        with c.cursor().copy('copy phrase_keys from stdin') as cp:
            for row in source:
                cp.write_row(row)
        c.execute('analyze phrase_keys')
        query = '''
          select k.*,h.id horse_id,r.id race_id,e.id race_entry_id,
                 e.horse_number operational_program,s.id report_id,
                 case when h.id is null then 'horse_missing'
                      when r.id is null then 'race_missing'
                      when e.id is null then 'entry_missing'
                      when e.horse_number <> k.historical_program then 'program_mismatch'
                      else 'matched' end status
          from phrase_keys k
          left join public.horses h on h.kra_horse_id=k.kra_horse_id
          left join public.racecourses rc on rc.kra_meet_code=k.meet_code
          left join public.races r on r.racecourse_id=rc.id
             and r.race_date_local=k.race_date_local and r.race_number=k.race_number
          left join public.race_entries e on e.race_id=r.id and e.horse_id=h.id
          left join public.race_steward_reports s on s.meet_code=k.meet_code
             and s.race_date_local=k.race_date_local and s.race_number=k.race_number
        '''
        cur=c.execute(query)
        keys=[x.name for x in cur.description]
        rows=[dict(zip(keys,r)) for r in cur.fetchall()]
        counts={}
        for row in rows:
            counts[row['status']]=counts.get(row['status'],0)+1
        result={'project_id':'xkykmhhkjtosptoibduo','source_rows':len(source),
                'status_counts':counts,'with_race_report':sum(r['report_id'] is not None for r in rows),
                'unmatched_examples':[r for r in rows if r['status']!='matched'][:25]}
        (ROOT/'preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
        (ROOT/'identity_matches.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,default=str)+'\n' for r in rows))
        print(json.dumps(result,ensure_ascii=False,default=str))
        c.rollback()


if __name__=='__main__':
    main()
