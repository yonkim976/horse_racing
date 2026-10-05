"""Independent profile API42 and frozen six-Parquet row comparison."""
import argparse
import collections
import hashlib
import json
import sqlite3
from pathlib import Path
import duckdb


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def canon(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--project-root',type=Path,required=True)
    p.add_argument('--profile-dir',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    c=sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    old=sqlite3.connect(args.baseline.resolve().as_uri()+'?mode=ro',uri=True)
    old_ids={r[0] for r in old.execute('SELECT horse_id FROM horse_profile_latest')}
    old.close()
    expected={}
    for line in (args.profile_dir/'validated_profile_rows.jsonl').read_text().splitlines():
        if not line.strip():continue
        item=json.loads(line);raw=item['raw_item'];hid=item['horse_id']
        assert hid==str(raw['hrNo']) and hid not in expected and hid not in old_ids
        assert raw['breed']=='제주마' and hid!='3005648'
        assert item['http_status']==200 and item['api_result_code']=='00' and item['api_total_count']==1
        path=(args.profile_dir/item['response_file']).resolve()
        assert path.is_relative_to(args.profile_dir.resolve())
        blob=path.read_bytes()
        assert sha(blob)==item['response_sha256'] and len(blob)==item['response_bytes']
        data=json.loads(blob)
        assert data['response']['header']['resultCode']=='00'
        body=data['response']['body'];assert int(body['totalCount'])==1
        rows=body['items']['item'];rows=rows if isinstance(rows,list) else [rows]
        assert len(rows)==1 and canon(rows[0])==canon(raw)
        expected[hid]=item
    now={r['horse_id']:dict(r) for r in c.execute('SELECT * FROM horse_profile_latest')}
    assert set(now)==old_ids|set(expected),('profile_id_population_mismatch',len(now),len(old_ids),len(expected))
    for hid,item in expected.items():
        row=now[hid];raw=item['raw_item']
        assert canon(json.loads(row['payload_json']))==canon(raw)
        assert sha(row['payload_json'].encode())==row['payload_sha256']
        assert row['observed_at_utc']==item['observed_at_utc']
        for key,column in [('hrNm','horse_name_raw'),('birthDt','birth_date_raw'),('age','age_raw'),
                           ('breed','breed_label_raw'),('sex','sex_raw'),('color','color_raw'),('prdCty','production_country_raw')]:
            assert row[column]==(None if raw.get(key) is None else str(raw[key])),(hid,key)
        a=dict(c.execute('SELECT * FROM source_artifacts WHERE source_artifact_id=?',(row['source_artifact_id'],)).fetchone())
        assert a['raw_relative_path']=='jeju/research/20261002_medical_db_load/profile_collection/'+item['response_file']
        assert a['sha256']==item['response_sha256'] and a['response_bytes']==item['response_bytes']
        assert a['operation']=='totalHorseInfo_1' and a['http_status_code']==200
        assert a['attempt_id']==Path(item['response_file']).parts[2]
        assert 'servicekey' not in a['request_params_json'].lower()
        rec=dict(c.execute('SELECT * FROM api_records WHERE api_record_id=?',(row['api_record_id'],)).fetchone())
        assert rec['record_index']==1 and rec['source_artifact_id']==row['source_artifact_id']
        evidence=c.execute('SELECT * FROM breed_evidence WHERE api_record_id=?',(row['api_record_id'],)).fetchall()
        assert len(evidence)==1 and evidence[0]['observed_event_date'] is None
        assert evidence[0]['breed_label_raw']=='제주마'
    package=args.project_root/'thoroughbred/research/20261002_medical_v1/dictionary'
    manifest=json.loads((package/'manifest.json').read_text())
    pins=json.loads((Path(__file__).parent/'root_dictionary_pins.json').read_text())
    assert sha((package/'manifest.json').read_bytes())==pins['source_manifest_sha256']
    files={'api33_source_rows.parquet':'medical_api33_source_rows','api33_terms.parquet':'medical_api33_terms',
           'phrase_decisions.parquet':'medical_phrase_decisions','phrase_components.parquet':'medical_phrase_components',
           'explanation_observations.parquet':'medical_explanation_observations','explanation_terms.parquet':'medical_explanation_terms'}
    d=duckdb.connect()
    checks={}
    for file,table in files.items():
        path=package/file;meta=manifest['output_files'][file]
        assert sha(path.read_bytes())==pins['file_sha256'][file]==meta['sha256']
        cur=d.execute('SELECT * FROM read_parquet(?)',[str(path)])
        columns=[x[0] for x in cur.description]
        assert table.isidentifier() and all(x.isidentifier() for x in columns)
        original=[tuple(int(x) if isinstance(x,bool) else x for x in row) for row in cur.fetchall()]
        col_sql=','.join('"'+x+'"' for x in columns)
        stored=[tuple(r) for r in c.execute(f'SELECT {col_sql} FROM "{table}"')]
        assert len(original)==len(stored)==meta['row_count']
        assert collections.Counter(original)==collections.Counter(stored),('dictionary_rows_changed',file)
        checks[file]={'rows':len(stored),'columns':len(columns),'sha256':meta['sha256'],'all_rows_equal':True}
    held=c.execute("SELECT count(*) FROM medical_phrase_decisions WHERE mapping_rule_scope='prior_rpt_parser_context_only' AND prefix_rule_reusable=0").fetchone()[0]
    assert held==356
    assert c.execute("SELECT count(*) FROM medical_api_diagnosis_components WHERE mapping_disposition<>'reviewed_exact_phrase_component_metadata_only'").fetchone()[0]==0
    assert c.execute("SELECT count(*) FROM medical_api33_source_rows WHERE ill_desc IS NOT '-'").fetchone()[0]==0
    result={'all_passed':True,'new_profiles_checked':len(expected),'profile_population':len(now),
            'six_dictionary_files':checks,'parser_prefix_rules_blocked':held,
            'safe_component_filter_verified':True,'api33_dash_not_description':True}
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'all_passed':True,'new_profiles_checked':len(expected),'profile_population':len(now),'dictionary_files_verified':len(checks)},ensure_ascii=False))


if __name__=='__main__':main()
