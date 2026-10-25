"""Independent review using DB winning keys, separate from API301 analysis."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PREDICTIONS = ROOT / 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet'


def main():
    source_hash = hashlib.sha256(PREDICTIONS.read_bytes()).hexdigest()
    assert source_hash == '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6'
    p = pd.read_parquet(PREDICTIONS)
    selected = p.loc[p.selected_jockey_id_candidate.eq(1)].copy()
    assert selected.race_id.is_unique and len(selected) == 1779 and selected.y_pair.sum() == 438
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    params = ('2024-01-01', '2026-09-19')
    races = pd.read_sql_query('''SELECT r.id db_id,r.race_date_local,r.race_number
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ?''', c, params=params)
    races['race_id'] = races.race_date_local + '_2_' + races.race_number.astype(str)
    entries = pd.read_sql_query('''SELECT e.race_id db_id,e.horse_number,s.finish_position
        FROM race_entries e JOIN race_results s ON s.race_entry_id=e.id
        JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ?''', c, params=params)
    odds = pd.read_sql_query('''SELECT o.race_id db_id,o.bet_type,o.selection_key,o.odds
        FROM odds_snapshots o JOIN races r ON r.id=o.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ?
        AND o.bet_type IN ('TLA','QNL','QPL')''', c, params=params)
    c.close()
    assert not odds.duplicated(['db_id', 'bet_type', 'selection_key']).any()
    quotes = odds.set_index(['db_id', 'bet_type', 'selection_key']).odds.to_dict()
    by_race = {i: g for i, g in entries.groupby('db_id')}
    independent = []
    dead_heat_races = 0
    for row in selected.merge(races, on='race_id', validate='one_to_one').itertuples():
        g = by_race[row.db_id]
        dead_heat_races += int(g.loc[g.finish_position.between(1, 3), 'finish_position'].duplicated().any())
        top3 = sorted(g.loc[g.finish_position.between(1, 3), 'horse_number'].astype(int))
        top2 = sorted(g.loc[g.finish_position.between(1, 2), 'horse_number'].astype(int))
        assert len(top3) == 3 and len(top2) == 2
        assert (set([row.horse_i, row.horse_j]) <= set(top3)) == bool(row.y_pair)
        out = {'race_id': row.race_id, 'pair_hit': int(row.y_pair)}
        for pool, numbers, col in [
            ('TLA', top3, 'tla_race_mean'), ('QNL', top2, 'qnl_race_mean'),
            ('QPL', sorted([row.horse_i, row.horse_j]), 'selected_qpl_dividend')]:
            key = '-'.join(map(str, numbers))
            out[col] = quotes.get((row.db_id, pool, key)) if pool != 'QPL' or row.y_pair else None
        independent.append(out)
    expected = pd.DataFrame(independent).set_index('race_id').sort_index()
    actual = pd.read_csv(STUDY / 'race_payouts.csv').set_index('race_id').sort_index()
    used_hashes = {h for value in actual.source_sha256s for h in json.loads(value)}
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    source_rows = c.execute('''SELECT id,local_path,sha256 FROM source_documents
        WHERE endpoint=?''', ('/API301/Dividend_rate_total',)).fetchall()
    c.close()
    page_index = []
    for doc_id, local_path, digest in source_rows:
        if digest not in used_hashes:
            continue
        path = (ROOT / local_path).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        page_index.append({'source_document_id': doc_id, 'path': path.relative_to(ROOT).as_posix(),
                           'sha256': digest, 'bytes': len(data)})
    assert {p['sha256'] for p in page_index} == used_hashes
    (STUDY / 'SOURCE_PAGE_INDEX.json').write_text(json.dumps(page_index, indent=2) + '\n')
    assert expected.index.equals(actual.index)
    assert np.array_equal(expected.pair_hit, actual.pair_hit)
    for col in ['tla_race_mean', 'qnl_race_mean', 'selected_qpl_dividend']:
        assert np.allclose(expected[col], actual[col], rtol=0, atol=1e-8, equal_nan=True), col
    covered = expected.loc[expected.tla_race_mean.notna()]
    assert len(covered) == 1142 and covered.pair_hit.sum() == 283
    report = json.loads((STUDY / 'REPORT.json').read_text())
    combined = {r['pair_outcome']: r for r in report['statistics'] if r['year'] == '2025-2026'}
    for name, flag in [('hit', 1), ('miss', 0)]:
        part = covered.loc[covered.pair_hit.eq(flag)]
        assert combined[name]['evaluation_races'] == len(part)
        for col in ['tla_race_mean', 'qnl_race_mean', 'selected_qpl_dividend']:
            data = part[col].dropna()
            stats = combined[name][col]
            assert stats['n'] == len(data)
            if len(data):
                assert abs(stats['mean'] - data.mean()) < 1e-10
                assert abs(stats['median'] - data.median()) < 1e-10
                assert abs(stats['p90'] - data.quantile(.9)) < 1e-10
    result = {'status': 'PASS', 'method': 'Independent shared-DB results and winning-key odds; row-level match to API301 audit',
              'evaluation_races': 1779, 'evaluation_hits': 438, 'covered_races': 1142,
              'covered_hits': 283, 'covered_misses': 859, 'missing_2024_races': 637,
              'all_selected_labels_match_official_results': True, 'row_level_payout_match': True,
              'top3_rank_ties_in_evaluation': dead_heat_races, 'prediction_sha256': source_hash,
              'used_source_page_hashes_verified': len(used_hashes),
              'report_sha256': hashlib.sha256((STUDY / 'REPORT.json').read_bytes()).hexdigest()}
    (STUDY / 'ROOT_REVIEW.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
