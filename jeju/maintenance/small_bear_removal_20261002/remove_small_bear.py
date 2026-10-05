"""Remove explicitly user-excluded horse from the local DB and active API21 candidate.

Raw source artifacts and historical audits remain as evidence; the local DB is
backed up before deletion. This script is intentionally limited to horse 3005648.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

JEJU = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DB = JEJU / 'data/jeju_native_core.sqlite3'
CANDIDATE = JEJU / 'research/20261001_starting_exam_api_collection/api21_verified_native_candidate_rows.jsonl'
REGISTRY = JEJU / 'data/horse_exclusions.json'
HORSE_ID = '3005648'
EXPECTED = {'race_result_rows': 0, 'running_trial_rows': 2, 'breed_evidence': 3,
            'horse_profile_observations': 1, 'starting_training_website_rows': 0,
            'daily_training_api_rows': 0}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path, data):
    temp = path.with_name(path.name + '.small_bear_removal.tmp')
    with temp.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def main():
    receipt_path = HERE / 'deletion_receipt.json'
    assert not receipt_path.exists(), 'Already applied; inspect receipt instead of repeating.'
    backup_path = HERE / 'before_deletion.sqlite3'
    assert not backup_path.exists(), 'Do not overwrite backup.'
    original = CANDIDATE.read_bytes()
    kept, removed = [], []
    for line in original.splitlines(keepends=True):
        row = json.loads(line)
        (removed if str(row['raw']['hrNo']) == HORSE_ID else kept).append(line)
    assert len(removed) == 2
    registry_original = REGISTRY.read_bytes() if REGISTRY.exists() else None
    registry = json.loads(registry_original) if registry_original else {'version': 1, 'horses': {}}
    assert HORSE_ID not in registry['horses']
    registry['horses'][HORSE_ID] = {'horse_name': '작은곰', 'decision_date_kst': '2026-10-02',
                                 'status': 'excluded_by_user', 'reason': '사용자 요청: 작은곰 데이터 삭제',
                                 'reimport_allowed': False,
                                 'receipt': 'maintenance/small_bear_removal_20261002/deletion_receipt.json'}
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('BEGIN IMMEDIATE')
    files_changed = False
    try:
        rows = {}
        totals_before = {}
        for table in EXPECTED:
            # Table identifiers are fixed constants, values are always bound.
            rows[table] = [dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE horse_id=?', (HORSE_ID,))]
            assert len(rows[table]) == EXPECTED[table], (table, len(rows[table]))
            totals_before[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        ids = sorted({r['api_record_id'] for rs in rows.values() for r in rs if 'api_record_id' in r})
        assert ids == [194894, 194937, 246104]
        rows['api_records'] = [dict(r) for r in conn.execute('SELECT * FROM api_records WHERE api_record_id IN (?,?,?)', ids)]
        assert len(rows['api_records']) == 3
        assert all(str(json.loads(r['payload_json'])['hrNo']) == HORSE_ID for r in rows['api_records'])
        all_stored_ids = [r[0] for r in conn.execute("SELECT api_record_id FROM api_records WHERE CAST(json_extract(payload_json,'$.hrNo') AS TEXT)=?", (HORSE_ID,))]
        assert sorted(all_stored_ids) == ids
        totals_before['api_records'] = conn.execute('SELECT COUNT(*) FROM api_records').fetchone()[0]
        (HERE / 'deleted_database_rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
        (HERE / 'candidate_before_deletion.jsonl').write_bytes(original)
        (HERE / 'deleted_api21_candidate_rows.jsonl').write_bytes(b''.join(removed))
        reader = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        backup = sqlite3.connect(backup_path)
        reader.backup(backup)
        assert backup.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        backup.close()
        reader.close()
        deleted = {}
        for table in ['starting_training_website_rows', 'daily_training_api_rows', 'breed_evidence',
                      'running_trial_rows', 'horse_profile_observations', 'race_result_rows']:
            deleted[table] = conn.execute(f'DELETE FROM {table} WHERE horse_id=?', (HORSE_ID,)).rowcount
        deleted['api_records'] = conn.execute('DELETE FROM api_records WHERE api_record_id IN (?,?,?)', ids).rowcount
        assert deleted == {**EXPECTED, 'api_records': 3}
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        totals_after = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in totals_before}
        assert all(totals_before[t] - totals_after[t] == deleted[t] for t in deleted)
        assert CANDIDATE.read_bytes() == original
        assert (REGISTRY.read_bytes() if REGISTRY.exists() else None) == registry_original
        files_changed = True
        atomic_write(CANDIDATE, b''.join(kept))
        atomic_write(REGISTRY, (json.dumps(registry, ensure_ascii=False, indent=2) + '\n').encode())
        conn.commit()
    except BaseException:
        conn.rollback()
        if files_changed:
            atomic_write(CANDIDATE, original)
            if registry_original is None:
                REGISTRY.unlink(missing_ok=True)
            else:
                atomic_write(REGISTRY, registry_original)
        raise
    finally:
        conn.close()
    active_rows = [json.loads(line) for line in CANDIDATE.read_text().splitlines()]
    assert all(str(r['raw']['hrNo']) != HORSE_ID for r in active_rows)
    receipt = {'decision_date_kst': '2026-10-02', 'horse_id': HORSE_ID, 'horse_name': '작은곰',
               'status': 'deleted_from_local_database_and_active_candidate', 'deleted_db_rows': deleted,
               'db_totals_before': totals_before, 'db_totals_after': totals_after,
               'candidate_rows_before': len(kept) + len(removed), 'candidate_rows_deleted': len(removed),
               'candidate_rows_after': len(active_rows),
               'candidate_horses_after': len({str(r['raw']['hrNo']) for r in active_rows}),
               'rider_absent_rows_after': sum('rider' not in r['raw'] for r in active_rows),
               'backup_file': backup_path.name, 'backup_sha256': digest(backup_path),
               'db_sha256_after': digest(DB), 'candidate_sha256_after': digest(CANDIDATE),
               'foreign_key_violations_after': 0, 'quick_check': 'ok',
               'raw_source_artifacts_deleted': False,
               'historical_audit_results_are_pre_deletion_snapshots': True,
               'reimport_exclusion_registry': 'data/horse_exclusions.json'}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ['status', 'deleted_db_rows', 'candidate_rows_after',
                                           'candidate_horses_after', 'rider_absent_rows_after', 'quick_check']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
