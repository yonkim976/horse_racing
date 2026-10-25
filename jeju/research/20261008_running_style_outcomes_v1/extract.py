"""Capture selected quality times read-only; preserve earlier group intervals."""
from pathlib import Path
import hashlib
import json
import sqlite3
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
PREV = ROOT / 'jeju/research/20261008_passing_group_running_style_v1'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    out = HERE / 'input01'
    out.mkdir(exist_ok=False)
    sources = [PREV / 'run01/runner_position_intervals.csv', PREV / 'run01/source_lineage.csv',
               PREV / 'run01/verification.json', PREV / 'PLAN.md', HERE / 'PLAN.md',
               ROOT / 'jeju/data/horse_exclusions.json',
               ROOT / 'jeju/research/20261003_unresolved_section_review/README.md']
    manifest = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in sources]
    before, digest = DB.stat(), sha(DB)
    expected = json.loads((PREV / 'run01/source_manifest.json').read_text())['database']['sha256']
    assert digest == expected
    save(out / 'source_manifest.json', {'files': manifest, 'database_sha256': digest,
                                       'database_bytes': before.st_size, 'quality_view': 'jeju_race_postrace_sections_quality_2026'})
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as con:
        con.execute('PRAGMA query_only=ON')
        d = pd.read_sql_query('''SELECT api_record_id,horse_id,race_date,race_distance_m,finish_position,
            finish_time_seconds,rank_class_raw,track_raw,carried_weight_kg,api4_3_payload_sha256,
            api303_payload_sha256,s1f_time_seconds,s1f_time_status,c4_time_seconds,c4_time_status,
            g3f_time_seconds,g3f_time_status,g1f_time_seconds,g1f_time_status,
            s1f_group_status,c4_group_status,g1f_group_status,c4_order_status,g1f_order_status
            FROM jeju_race_postrace_sections_quality_2026 WHERE race_date BETWEEN ? AND ?''',
            con, params=('2017-01-01', '2026-09-19'))
    lineage = pd.read_csv(PREV / 'run01/source_lineage.csv', usecols=['api_record_id', 'api4_3_payload_sha256', 'api303_payload_sha256'])
    d = d[d.api_record_id.isin(lineage.api_record_id)].copy()
    assert len(d) == len(lineage) == 52155 and not d.api_record_id.duplicated().any()
    m = d.merge(lineage, on='api_record_id', validate='one_to_one', suffixes=('_new', '_old'))
    for col in ['api4_3_payload_sha256', 'api303_payload_sha256']:
        assert m[col + '_new'].equals(m[col + '_old'])
    d.to_csv(out / 'selected_quality_times.csv', index=False, encoding='utf-8-sig')
    assert sha(DB) == digest and (DB.stat().st_mtime_ns, DB.stat().st_size) == (before.st_mtime_ns, before.st_size)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in manifest)
    save(out / 'verification.json', {'status': 'passed', 'rows': len(d), 'unique_entry_ids': True,
                                     'earlier_payload_hashes_match': True, 'database_unchanged': True,
                                     'database_sha256': digest, 'sources_unchanged': True,
                                     'code_sha256': sha(Path(__file__))})
    print('Read-only quality snapshot:', len(d), flush=True)


if __name__ == '__main__':
    main()
