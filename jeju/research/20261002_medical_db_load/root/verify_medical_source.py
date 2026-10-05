"""Independent archived API16 -> normalized SQLite comparison, read only."""
import argparse
import collections
import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

FIELDS = {'clinicDate':'clinic_date_raw', 'meet':'meet_raw', 'hrName':'hr_name_raw',
          'hrNo':'hr_no_raw', 'hospiName':'hospi_name_raw', 'illName1':'ill_name1_raw',
          'illName2':'ill_name2_raw', 'part':'part_raw'}
SOURCE = 'jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(path.read_text())


def items(data):
    value = data['response']['body'].get('items') or {}
    if isinstance(value, dict):
        value = value.get('item') or []
    assert isinstance(value, (dict,list))
    return [value] if isinstance(value, dict) else value


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--project-root', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    c = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    profiles = {r['horse_id']: dict(r) for r in c.execute('SELECT * FROM horse_profile_latest')}
    ids = {k for k,v in profiles.items() if v['breed_label_raw']=='제주마'}
    exclusions = read(args.project_root/'jeju/data/horse_exclusions.json')['horses']
    excluded = {k for k,v in exclusions.items() if v.get('reimport_allowed') is False}
    ids -= excluded
    base = args.project_root/SOURCE
    manifest = read(base/'run_manifest.json')
    expected = {}
    page_hashes = {}
    pages_checked = 0
    all_rows = 0
    for year, entry in manifest['datasets']['clinic']['years'].items():
        for page in entry['pages']:
            path = (base/page['response_file']).resolve()
            assert path.is_relative_to(base.resolve())
            blob = path.read_bytes()
            assert sha(blob)==page['response_sha256']
            page_hashes[path.relative_to(args.project_root).as_posix()] = sha(blob)
            data = json.loads(blob)
            assert data['response']['header']['resultCode']=='00'
            rows = items(data)
            assert len(rows)==page['actual_page_rows']
            pages_checked += 1
            all_rows += len(rows)
            for position, raw in enumerate(rows,1):
                if str(raw.get('hrNo')) in ids:
                    expected[(path.relative_to(args.project_root).as_posix(),position)] = raw
    loaded = {(r['raw_relative_path'],r['source_row_no']):dict(r) for r in c.execute('''
        SELECT m.*, a.payload_json, a.payload_sha256, a.record_index,
               a.source_artifact_id AS record_artifact_id, s.raw_relative_path, s.sha256 AS artifact_sha256
        FROM medical_api_rows m JOIN api_records a USING(api_record_id)
        JOIN source_artifacts s ON s.source_artifact_id=m.source_artifact_id''')}
    assert set(loaded)==set(expected), ('source_positions_mismatch',len(loaded),len(expected))
    raw_counts = collections.Counter()
    phrase_counts = collections.Counter()
    for key, raw in expected.items():
        row = loaded[key]
        parsed = json.loads(row['payload_json'])
        assert json.dumps(parsed, sort_keys=True, separators=(',', ':'))==json.dumps(raw, sort_keys=True, separators=(',', ':'))
        assert sha(row['payload_json'].encode())==row['payload_sha256']
        assert row['source_artifact_id']==row['record_artifact_id']
        assert row['source_row_no']==row['record_index']==key[1]
        assert page_hashes[key[0]]==row['artifact_sha256']
        for field,column in FIELDS.items():
            assert row[column]==(None if raw.get(field) is None else str(raw[field])), (key,field)
        assert set(json.loads(row['raw_key_presence_json']))==set(raw).intersection(FIELDS)
        assert set(json.loads(row['raw_key_absence_json']))==set(FIELDS).difference(raw)
        kinds = {k:('null' if v is None else 'boolean' if isinstance(v,bool) else
                    'integer' if isinstance(v,int) else 'number' if isinstance(v,float) else
                    'string' if isinstance(v,str) else 'array' if isinstance(v,list) else 'object') for k,v in raw.items()}
        assert json.loads(row['raw_field_types_json'])==kinds
        assert row['horse_id']==str(raw['hrNo'])
        day = str(raw['clinicDate'])
        assert row['clinic_date']==date(int(day[:4]),int(day[4:6]),int(day[6:])).isoformat()
        raw_counts[json.dumps(raw,sort_keys=True,ensure_ascii=False)]+=1
        for key2 in ['illName1','illName2']:
            if raw.get(key2) not in (None,'','-'):
                phrase_counts[raw[key2]]+=1
    slots={(r['api_record_id'],r['source_slot_ordinal']):dict(r) for r in c.execute('SELECT * FROM medical_api_diagnosis_slots')}
    assert len(slots)==2*len(expected)
    for position,raw in expected.items():
        parent=loaded[position]
        for ordinal,kind in enumerate(['illName1','illName2'],1):
            slot=slots[(parent['api_record_id'],ordinal)]
            value=None if raw.get(kind) is None else str(raw[kind])
            assert slot['raw_diagnosis_text']==value
            assert slot['source_slot_kind']==kind
            assert slot['normalized_diagnosis_text']==(None if value in (None,'','-') else value)
            assert slot['raw_text_sha256']==(None if value is None else sha(value.encode()))
            for field in ['medical_api_row_id','source_artifact_id','source_row_no','horse_id','clinic_date']:
                assert slot[field]==parent[field]
    analysis = [dict(r) for r in c.execute('SELECT * FROM medical_api_rows_analysis_2026')]
    capped = [r for r in loaded.values() if r['clinic_date']<='2026-09-19']
    assert len(analysis)==len(capped)
    assert {r['api_record_id'] for r in analysis}=={r['api_record_id'] for r in capped}
    for row in analysis:
        profile = profiles[row['horse_id']]
        assert row['current_horse_name']==profile['horse_name_raw']
        birth = profile['birth_date_raw']
        age = 2026-int(birth[:4]) if birth and birth[:4].isdigit() else None
        assert row['current_horse_age_2026']==age
    assert not excluded.intersection(row['horse_id'] for row in loaded.values())
    repeats = [n for n in raw_counts.values() if n>1]
    report = {'all_passed':True,'source_pages_checked':pages_checked,'all_location_raw_rows':all_rows,
              'loaded_rows':len(loaded),'loaded_horses':len({r['horse_id'] for r in loaded.values()}),
              'analysis_rows':len(analysis),'analysis_horses':len({r['horse_id'] for r in analysis}),
              'raw_rows_after_cutoff':len(loaded)-len(analysis),
              'nonblank_phrases':len(phrase_counts),'nonblank_slots':sum(phrase_counts.values()),
              'exact_repeat_groups':len(repeats),'exact_repeat_group_rows':sum(repeats),
              'all_source_positions_and_raw_fields_equal':True,'all_diagnosis_slots_raw_equal':True,'latest_name_and_fixed_age_equal':True}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
