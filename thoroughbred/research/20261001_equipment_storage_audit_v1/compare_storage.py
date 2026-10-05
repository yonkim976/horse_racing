"""Read-only equipment inventory and strong-key coverage against the new API core."""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import duckdb

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
OP = ROOT / 'data/horse_racing.sqlite3'

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()

def day(value):
    value=str(value)
    return value if '-' in value else value[:4]+'-'+value[4:6]+'-'+value[6:8]

def normalize(value):
    return ''.join((value or '').split())

def csv_file(name, data, fields):
    with (OUT/name).open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)

def main():
    before=sha(CORE)
    d=duckdb.connect(str(CORE),read_only=True)
    fields=d.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='main' AND (column_name ILIKE '%equip%' OR column_name ILIKE '%장구%') ORDER BY 1,2").fetchall()
    core_rows=d.execute('SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_id_raw,horse_name_raw FROM confirmed_runners').fetchall()
    core={}
    for meet,date_,race,no,horse,name in core_rows:
        key=(int(meet),day(date_),int(race),int(no))
        assert key not in core
        core[key]={'horse_id':str(horse),'horse_name':name}
    d.close()
    s=sqlite3.connect(OP.as_uri()+'?mode=ro',uri=True)
    s.row_factory=sqlite3.Row
    s.execute('PRAGMA query_only=ON')
    s.execute('BEGIN')
    scope=( '2010-01-01','2026-09-29')
    entries=s.execute('''SELECT rc.kra_meet_code meet,r.race_date_local day,r.race_number race,
        e.horse_number no,h.kra_horse_id horse_id,h.name_ko horse_name,e.id entry_id,
        e.equipment,e.equipment_card_raw,e.equipment_card_observed_at_ms
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id JOIN horses h ON h.id=e.horse_id
        WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local BETWEEN ? AND ?''',scope).fetchall()
    equipment=s.execute('''SELECT q.meet_code meet,q.race_date_local day,q.race_number race,
        q.horse_number no,h.kra_horse_id horse_id,q.equipment_raw,q.observed_at_ms,
        q.bleeding_count,q.illness_note FROM entry_equipment q
        LEFT JOIN horses h ON h.id=q.horse_id
        WHERE q.meet_code IN (1,3,4) AND q.race_date_local BETWEEN ? AND ?''',scope).fetchall()
    changes=s.execute('''SELECT c.race_entry_id,c.position,c.equipment_name_raw,c.change_type,c.observed_at_ms
        FROM entry_equipment_changes c JOIN race_entries e ON e.id=c.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local BETWEEN ? AND ?''',scope).fetchall()
    def keyed(rows):
        result={}
        for row in rows:
            key=(int(row['meet']),str(row['day']),int(row['race']),int(row['no']))
            assert key not in result
            result[key]=row
        return result
    op=keyed(entries)
    equipment_event=keyed(equipment)
    by_entry=Counter(row['race_entry_id'] for row in changes)
    per_year=Counter()
    eq24_conflicts=[]
    entry_conflicts=[]
    missing_equipment_event=[]
    missing_cards=[]
    card_state=[]
    for key,runner in core.items():
        op_row=op.get(key)
        eq_row=equipment_event.get(key)
        prefix=(key[0],key[1][:4])
        per_year[prefix+('core_runners',)]+=1
        if op_row and op_row['horse_id']!=runner['horse_id']:
            entry_conflicts.append({'meet':key[0],'date':key[1],'race_no':key[2],'horse_no':key[3], 'core_horse_id':runner['horse_id'],'operational_horse_id':op_row['horse_id'],'core_name':runner['horse_name'],'operational_name':op_row['horse_name']})
        if eq_row and eq_row['horse_id']!=runner['horse_id']:
            eq24_conflicts.append({'meet':key[0],'date':key[1],'race_no':key[2],'horse_no':key[3], 'core_horse_id':runner['horse_id'],'equipment_event_horse_id':eq_row['horse_id'],'core_name':runner['horse_name']})
        op_ok=op_row is not None and op_row['horse_id']==runner['horse_id']
        eq_ok=eq_row is not None and eq_row['horse_id']==runner['horse_id']
        if not eq_ok:
            missing_equipment_event.append({'meet':key[0],'date':key[1],'race_no':key[2],'horse_no':key[3],'horse_id':runner['horse_id'],'horse_name':runner['horse_name'],'state':'identity_conflict' if eq_row else 'no_event_for_race_horse_number'})
        if op_ok:
            per_year[prefix+('operational_entry_matched',)]+=1
            per_year[prefix+('operational_equipment_nonblank',)]+=bool(normalize(op_row['equipment']))
            if op_row['equipment_card_observed_at_ms'] is not None:
                per_year[prefix+('api78_observation_matched',)]+=1
                per_year[prefix+('api78_raw_nonblank',)]+=bool(normalize(op_row['equipment_card_raw']))
                per_year[prefix+('api78_change_rows',)]+=by_entry[op_row['entry_id']]
                if len(card_state)<10 and ('+' in (op_row['equipment_card_raw'] or '') or '-' in (op_row['equipment_card_raw'] or '')):
                    card_state.append({'meet':key[0],'date':key[1],'race_no':key[2],'horse_no':key[3],'horse_id':runner['horse_id'],'horse_name':runner['horse_name'],'equipment':op_row['equipment'],'entry_equipment_raw':eq_row['equipment_raw'] if eq_ok else None,'api78_equipment_card_raw':op_row['equipment_card_raw'],'api78_observed_at_ms':op_row['equipment_card_observed_at_ms']})
            elif key[1]>='2017-01-01':
                missing_cards.append({'meet':key[0],'date':key[1],'race_no':key[2],'horse_no':key[3],'horse_id':runner['horse_id'],'horse_name':runner['horse_name'],'operational_entry_id':op_row['entry_id']})
        if eq_ok:
            per_year[prefix+('equipment_event_event_matched',)]+=1
            per_year[prefix+('equipment_event_equipment_nonblank',)]+=bool(normalize(eq_row['equipment_raw']))
    metrics=['core_runners','operational_entry_matched','operational_equipment_nonblank','equipment_event_event_matched','equipment_event_equipment_nonblank','api78_observation_matched','api78_raw_nonblank','api78_change_rows']
    years=sorted({key[:2] for key in per_year})
    annual=[{'meet':meet,'year':year,**{metric:per_year[(meet,year,metric)] for metric in metrics}} for meet,year in years]
    totals={metric:sum(row[metric] for row in annual) for metric in metrics}
    csv_file('coverage_by_meet_year.csv',annual,['meet','year',*metrics])
    csv_file('entry_identity_conflicts.csv',entry_conflicts,['meet','date','race_no','horse_no','core_horse_id','operational_horse_id','core_name','operational_name'])
    csv_file('equipment_event_identity_conflicts.csv',eq24_conflicts,['meet','date','race_no','horse_no','core_horse_id','equipment_event_horse_id','core_name'])
    csv_file('core_missing_equipment_event.csv',missing_equipment_event,['meet','date','race_no','horse_no','horse_id','horse_name','state'])
    csv_file('matched_operational_api78_missing_2017plus.csv',missing_cards,['meet','date','race_no','horse_no','horse_id','horse_name','operational_entry_id'])
    by_meet={}
    for meet in (1,3,4):
        er=[r for r in entries if r['meet']==meet]
        ar=[r for r in equipment if r['meet']==meet]
        erids={r['entry_id'] for r in er}
        cr=[r for r in changes if r['race_entry_id'] in erids]
        by_meet[str(meet)]={'operational_entries':len(er),'equipment_nonblank':sum(bool(normalize(r['equipment'])) for r in er),'api78_observed_entries':sum(r['equipment_card_observed_at_ms'] is not None for r in er),'equipment_event_events':len(ar),'equipment_event_nonblank':sum(bool(normalize(r['equipment_raw'])) for r in ar),'change_marks':dict(Counter(r['change_type'] for r in cr)),'equipment_event_first_date':min((r['day'] for r in ar),default=None),'equipment_event_last_date':max((r['day'] for r in ar),default=None)}
    s.rollback()
    s.close()
    after=sha(CORE)
    assert before==after
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'2010-01-01..2026-09-29; Seoul1 Busan3 Yeongcheon4','core_database_sha256_before':before,'core_database_sha256_after':after,'core_equipment_columns':fields,'core_runner_rows':len(core_rows),'core_key_unique':True,'operational_scope_by_meet':by_meet,'core_strong_key_coverage':totals,'operational_entry_identity_conflict_rows':len(entry_conflicts),'equipment_event_identity_conflict_rows':len(eq24_conflicts),'api78_missing_for_matched_2017plus_entries':len(missing_cards),'samples':card_state,'read_only':{'duckdb_read_only':True,'sqlite_mode_ro':True,'sqlite_query_only':True,'sqlite_read_transaction':True},'notes':['No operational or research database was modified.','API78 observation coverage includes explicit empty strings; nonblank equipment is counted separately.','Strong-key linkage requires meet/date/race/horse-number and equal official horse ID.','No equipment values are imported into the new core in this audit.','entry_equipment is mixed-origin; event coverage is not proof of parsed equipment coverage.']}
    (OUT/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
