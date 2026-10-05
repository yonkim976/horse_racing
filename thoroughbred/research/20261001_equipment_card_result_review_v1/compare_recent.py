"""Read-only recent card/result comparison; aliases are diagnostic, not canonical."""
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sqlite3
import duckdb

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ALIASES = {
    '계란형큰':'계란형큰고리재갈', '반가지큰':'반가지큰고리재갈',
    '망사':'망사가면', '망사눈':'망사눈가면', '눈가면':'눈가면',
    '혀끈':'혀보정끈', '자극판':'구각자극판', '양털코':'양털코굴레',
    '양털뺨':'양털뺨굴레', 'Triabit':'Triabit러깅재갈',
    'JR러깅':'JR러깅재갈', '가지':'가지재갈', '반가지':'반가지재갈',
    '고무가지':'고무가지재갈', '나비':'나비재갈',
    '혀보정':'혀보정재갈', '혀보정큰':'혀보정큰고리재갈',
    '코넬컬러':'CornellCollar', '승인편자':'승인편자',
}
MARK = re.compile(r'^(.+?)\s*([+-])?\s*$')

def norm(value):
    return ''.join((value or '').split())

def card_items(value):
    tokens = []
    for position, part in enumerate((value or '').split(','), 1):
        if not part.strip():
            continue
        match = MARK.fullmatch(part.strip())
        name = match.group(1).strip()
        tokens.append((position, norm(name), match.group(2) or 'unmarked'))
    return tokens

def full_family(value):
    value = norm(value)
    if any(term in value for term in ('편자', 'HoofPad', 'HoofRimPad')):
        return '승인편자'
    return re.sub(r'\((오른쪽|왼쪽)\)$', '', value)

def main():
    core = duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
    valid = set()
    for m,d,r,n,h in core.execute('SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_id_raw FROM confirmed_runners').fetchall():
        d = str(d)
        d = d if '-' in d else d[:4]+'-'+d[4:6]+'-'+d[6:8]
        valid.add((int(m),d,int(r),int(n),str(h)))
    core.close()
    db = sqlite3.connect((ROOT/'data/horse_racing.sqlite3').as_uri()+'?mode=ro',uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    rows = db.execute('''SELECT rc.kra_meet_code meet,r.race_date_local date,r.race_number race,
        e.horse_number no,h.kra_horse_id horse_id,h.name_ko horse_name,
        e.equipment_card_raw card_raw,e.equipment_card_observed_at_ms card_observed_at_ms,
        q.equipment_raw event_raw,q.observed_at_ms event_observed_at_ms,
        qh.kra_horse_id event_horse_id,e.equipment wide_raw
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id JOIN horses h ON h.id=e.horse_id
        LEFT JOIN entry_equipment q ON q.meet_code=rc.kra_meet_code
          AND q.race_date_local=r.race_date_local AND q.race_number=r.race_number
          AND q.horse_number=e.horse_number
        LEFT JOIN horses qh ON qh.id=q.horse_id
        WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local BETWEEN ? AND ?
          AND e.equipment_card_observed_at_ms IS NOT NULL''',('2025-01-01','2026-09-29')).fetchall()
    counts=Counter()
    gaps=[]
    dual=[]
    token_counts=Counter()
    removed_present=Counter()
    for row in rows:
        key=(row['meet'],row['date'],row['race'],row['no'],row['horse_id'])
        counts['operational_card_rows']+=1
        if key not in valid:
            counts['outside_confirmed_core']+=1
            continue
        counts['matched_core_rows']+=1
        if row['event_horse_id']!=row['horse_id']:
            counts['missing_or_identity_conflicting_event']+=1
            continue
        tokens=card_items(row['card_raw'])
        for _,name,mark in tokens:
            token_counts[(name,mark)]+=1
        active_names={name for _,name,mark in tokens if mark!='-'}
        removed_names={name for _,name,mark in tokens if mark=='-'}
        if active_names & removed_names:
            dual.append({**dict(row),'same_label_active_and_removed':','.join(sorted(active_names & removed_names))})
        if not norm(row['card_raw']):
            counts['observed_blank_card']+=1
        if not norm(row['event_raw']):
            counts['blank_event']+=1
        if not norm(row['card_raw']) or not norm(row['event_raw']):
            continue
        counts['both_nonblank']+=1
        full={full_family(t) for t in row['event_raw'].split(',') if t.strip()}
        unresolved=active_names-ALIASES.keys()
        projected={ALIASES[t] for t in active_names if t in ALIASES}
        if unresolved:
            counts['unknown_card_names']+=1
        absent=projected-full
        if absent:
            counts['active_card_family_absent_in_event']+=1
            gaps.append({**dict(row),'diagnostic_absent_names':','.join(sorted(absent))})
        else:
            counts['active_card_families_all_in_event']+=1
        for name in removed_names-active_names:
            if name in ALIASES and ALIASES[name] in full:
                removed_present[name]+=1
    db.close()
    fields=['meet','date','race','no','horse_id','horse_name','card_raw','card_observed_at_ms','event_raw','event_observed_at_ms','event_horse_id','wide_raw']
    for filename,data,extra in [('diagnostic_active_absent.csv',gaps,'diagnostic_absent_names'),('same_label_active_and_removed.csv',dual,'same_label_active_and_removed')]:
        with (OUT/filename).open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields+[extra]);writer.writeheader();writer.writerows(data)
    result={'scope':'2025-01-01..2026-09-29, meets1/3/4, confirmed core match with official horse ID',
        'read_only':True,'counts':dict(counts),'dual_label_rows':len(dual),
        'diagnostic_aliases':ALIASES,
        'alias_status':'diagnostic_only_unverified_for_canonical_use; shoe categories and laterality coarsened',
        'removed_without_active_label_but_in_event':dict(removed_present),
        'tokens':[{'name':n,'mark':m,'count':c} for (n,m),c in sorted(token_counts.items())],
        'interpretation':'event raw remains mixed-origin table, not certified actual wear or certified API24 source per row; diagnostic mismatches are not confirmed day-of changes'}
    (OUT/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('tokens','diagnostic_aliases')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
