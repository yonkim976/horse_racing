"""Independent raw-declaration and SQL/as-of input audit, read-only sources."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
AUDIT = HERE.parent / 'audit'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''): h.update(b)
    return h.hexdigest()


def main():
    path = AUDIT / 'entry_condition_inputs.parquet'
    f = pd.read_parquet(path).sort_values('api_record_id').reset_index(drop=True)
    base = pd.read_parquet(ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet')
    base['race_date'] = pd.to_datetime(base.race_date).dt.strftime('%Y-%m-%d')
    keys = ['api_record_id', 'race_id', 'race_date', 'horse_id', 'horse_number', 'field_n']
    base = base.sort_values('api_record_id').reset_index(drop=True)
    pd.testing.assert_frame_equal(f[keys], base[keys], check_dtype=False)
    assert len(f) == 52155 and f.race_id.nunique() == 5206
    known = f.current_declared_burden_kg.notna()
    assert known.sum() == 51917
    docs = {int(x['id']): x for x in json.loads((ROOT / 'data/research/jeju_native_h3_features_v1_20260916/source_documents.json').read_text())}
    cache = {}; raw_checked = 0; repaired = 0
    for row in f.loc[known].itertuples(index=False):
        doc = docs[int(row.source_document_id)]
        source = (ROOT / doc['path']).resolve(strict=True)
        assert source.is_relative_to(ROOT)
        if row.source_document_id not in cache:
            assert sha(source) == doc['sha256']
            cache[row.source_document_id] = source.read_bytes().decode('cp949', errors='replace').splitlines()
        line = cache[row.source_document_id][int(row.source_line_number)-1]
        assert hashlib.sha256(line.encode('utf-8')).hexdigest() == row.source_line_sha256
        tokens = line.split()
        assert tokens[2] == '제' and tokens[3] in ('수', '암', '거')
        assert int(tokens[0]) == row.horse_number == row.declared_horse_number
        assert float(tokens[5]) == row.current_declared_burden_kg
        assert tokens[1] == row.source_raw_horse_name
        if tokens[1] != row.target_horse_name:
            assert tokens[1] == '★' + row.target_horse_name
            assert row.current_source_status == 'dacom01_direct_single_star_marker_match'
            repaired += 1
        assert row.source_document_sha256 == doc['sha256']
        assert pd.Timestamp(row.source_file_date) <= pd.Timestamp(row.race_date) - pd.Timedelta(days=2)
        raw_checked += 1
    assert repaired == 135
    complete = f.groupby('race_id').current_declared_burden_kg.apply(lambda x: x.notna().all())
    assert int(complete.sum()) == 5181
    observed = f.loc[f.race_id.isin(complete.index[complete])]
    maxima = observed.groupby('race_id').horse_number.transform('max').to_numpy(float)
    np.testing.assert_array_equal(observed.max_declared_horse_number, maxima)
    np.testing.assert_allclose(observed.horse_number_fraction, (observed.horse_number.to_numpy(float)-1)/(maxima-1), atol=0, rtol=0)
    assert f.loc[~known, ['current_declared_burden_kg', 'horse_number_fraction', 'burden_change_vs_last_valid_kg']].isna().all().all()

    db = ROOT / 'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
    expected = '0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f'
    assert sha(db) == expected
    conn = sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    sql = '''SELECT e.hr_no AS horse_id, v.event_date, v.event_number,
                    e.finish_position, e.finish_time_ms, e.record_status,
                    s.id AS source_row_id, s.row_sha256,
                    json_extract(s.normalized_json,'$.wgBudam') AS weight,
                    json_extract(s.normalized_json,'$.rcTime') AS raw_time,
                    json_extract(s.normalized_json,'$.ord') AS raw_ord
             FROM entry e JOIN event v ON e.event_id=v.id
             JOIN source_row s ON s.id=e.source_row_id
             WHERE v.event_type='race' AND v.meet=2
               AND v.population_status='confirmed_native_normal_race'
               AND e.identity_status='official_race_ids_linked' '''
    h = pd.read_sql_query(sql, conn); conn.close()
    h['horse_id'] = h.horse_id.astype(str)
    h = h.loc[h.horse_id.isin(f.horse_id)].copy()
    for c in ['weight', 'raw_time', 'raw_ord', 'finish_position', 'finish_time_ms']:
        h[c] = pd.to_numeric(h[c], errors='coerce')
    assert h.loc[h.finish_position.notna(), 'finish_position'].eq(h.loc[h.finish_position.notna(), 'raw_ord']).all()
    basic = h.weight.between(30, 100) & h.finish_time_ms.gt(0)
    normal = h.finish_position.between(1, 89) & h.record_status.eq('normal_completed')
    special = h.finish_position.isin([91, 92]) & h.raw_time.gt(0)
    h = h.loc[basic & (normal | special)].copy()
    h['history_date'] = pd.to_datetime(h.event_date.astype(str), format='%Y%m%d')
    assert not h.duplicated(['horse_id', 'history_date']).any()
    left = f[['api_record_id', 'horse_id', 'race_date']].copy()
    left['cutoff'] = pd.to_datetime(left.race_date)-pd.Timedelta(days=2)
    joined = pd.merge_asof(left.sort_values('cutoff'), h.sort_values('history_date'),
                          by='horse_id', left_on='cutoff', right_on='history_date',
                          direction='backward', allow_exact_matches=True).sort_values('api_record_id').reset_index(drop=True)
    np.testing.assert_allclose(joined.weight, f.latest_prior_burden_kg, atol=0, rtol=0, equal_nan=True)
    np.testing.assert_allclose(joined.source_row_id, f.latest_prior_source_row_id, atol=0, rtol=0, equal_nan=True)
    present = joined.source_row_id.notna()
    assert joined.loc[present, 'row_sha256'].eq(f.loc[present, 'latest_prior_source_row_sha256']).all()
    dates = joined.history_date.dt.strftime('%Y-%m-%d')
    assert dates.loc[present].eq(f.loc[present, 'latest_prior_race_date']).all()
    expected_race = dates + '_2_' + joined.event_number.astype('Int64').astype(str)
    assert expected_race.loc[present].eq(f.loc[present, 'latest_prior_race_id']).all()
    np.testing.assert_allclose(f.current_declared_burden_kg-joined.weight, f.burden_change_vs_last_valid_kg,
                               atol=0, rtol=0, equal_nan=True)
    tail = left.cutoff.gt(pd.Timestamp('2026-09-12'))
    assert np.array_equal(~tail, f.prior_source_snapshot_complete)
    assert f.loc[tail, 'burden_change_vs_last_valid_kg'].isna().all()
    result = {'passed': True, 'target_rows': len(f), 'target_races': f.race_id.nunique(),
              'declaration_rows_directly_checked': raw_checked, 'declaration_documents_hashed': len(cache),
              'single_star_exact_matches_checked': repaired, 'full_roster_fraction_races_checked': int(complete.sum()),
              'prior_asof_rows_checked': len(joined), 'prior_observed_rows': int(present.sum()),
              'prior_eligible_source_rows': len(h), 'source_truncated_target_rows': int(tail.sum()),
              'database_sha256': expected, 'feature_sha256': sha(path), 'verifier_sha256': sha(Path(__file__)),
              'source_build_module_imported': False, 'database_mode': 'ro/query_only',
              'first_publication_time_verified': False}
    with (HERE / 'INPUT_VERIFICATION.json').open('x') as out: json.dump(result, out, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
