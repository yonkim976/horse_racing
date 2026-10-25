"""Independently reconstruct fixed-stake QPL returns from stored selections."""
import hashlib
import json
import math
import sqlite3
from decimal import Decimal
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PAIR = ROOT / 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet'
SELECTORS = ['selected_jockey_id_candidate', 'selected_jockey_basic_candidate',
    'selected_expanded_candidate', 'selected_old_direct', 'selected_raw_top2',
    'selected_saved_f1_top2', 'selected_candidate_joint_marginal_top2',
    'selected_candidate_joint_maxpair', 'selected_matched_joint_maxpair']
NAMES = ['jockey_id_candidate', 'jockey_basic_candidate', 'expanded_candidate',
    'old_direct', 'raw_top2', 'saved_f1_top2', 'joint_marginal_top2',
    'candidate_joint_maxpair', 'matched_joint_maxpair']


def calculate():
    digest = hashlib.sha256(PAIR.read_bytes()).hexdigest()
    assert digest == '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6'
    p = pd.read_parquet(PAIR)
    p = p.loc[p.evaluation_year.isin([2025, 2026])]
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    quotes = c.execute('''SELECT r.race_date_local,r.race_number,o.selection_key,o.odds
        FROM odds_snapshots o JOIN races r ON r.id=o.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ? AND o.bet_type=?''',
        ('2025-01-01', '2026-09-19', 'QPL')).fetchall()
    ranks = c.execute('''SELECT r.race_date_local,r.race_number,e.horse_number,s.finish_position
        FROM race_entries e JOIN race_results s ON s.race_entry_id=e.id
        JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ?''',
        ('2025-01-01', '2026-09-19')).fetchall()
    c.close()
    odds = {}
    for day, number, key, value in quotes:
        k = (f'{day}_2_{number}', key)
        assert k not in odds
        odds[k] = Decimal(str(value))
    podiums = {}
    for day, number, horse, rank in ranks:
        if rank is not None and 1 <= rank <= 3:
            podiums.setdefault(f'{day}_2_{number}', set()).add(horse)
    results, long_rows = {}, []
    for selector in SELECTORS:
        rows = p.loc[p[selector].eq(1)]
        assert len(rows) == 1142 and rows.race_id.is_unique
        pays = []
        for r in rows.itertuples():
            pair = (int(r.horse_i), int(r.horse_j))
            assert pair[0] < pair[1]
            assert len(podiums[r.race_id]) == 3
            assert (set(pair) <= podiums[r.race_id]) == bool(r.y_pair)
            key = '-'.join(map(str, pair))
            assert (r.race_id, key) in odds, 'Missing final QPL quote'
            value = odds[(r.race_id, key)] if r.y_pair else Decimal(0)
            assert value >= 0
            pays.append((int(r.evaluation_year), value, int(r.y_pair)))
            long_rows.append({'selector': selector, 'race_id': r.race_id, 'pair': key,
                'year': int(r.evaluation_year), 'hit': int(r.y_pair),
                'return_multiple': float(value), 'return_krw': int(value * 10000)})
        result = {}
        for label, subset in [('combined', pays), ('2025', [x for x in pays if x[0] == 2025]),
                              ('2026_partial', [x for x in pays if x[0] == 2026])]:
            n = len(subset)
            total = sum((x[1] for x in subset), Decimal(0))
            hits = sum(x[2] for x in subset)
            result[label] = {'races': n, 'hits': hits, 'return_sum_multiple': str(total),
                'hit_rate_pct': hits / n * 100,
                'mean_hit_odds': float(total / hits),
                'recovery_pct': float(total / n * 100),
                'roi_pct': float((total / n - 1) * 100),
                'stake_krw': n * 10000, 'return_krw': int(total * 10000),
                'net_profit_krw': int((total - n) * 10000)}
        results[selector] = result
    return digest, results, pd.DataFrame(long_rows)


def main():
    digest, results, rows = calculate()
    report = {'method': 'Independent DB QPL quotes and official podiums; Decimal arithmetic',
              'prediction_sha256': digest, 'stake_per_race_krw': 10000, 'selectors': results}
    (STUDY / 'ROOT_REFERENCE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if not (STUDY / 'race_returns.csv').exists():
        print(json.dumps({s: r['combined'] for s, r in results.items()}))
        return
    names = dict(zip(SELECTORS, NAMES))
    rows['selector'] = rows.selector.map(names)
    expected = rows.set_index(['selector', 'race_id']).sort_index()
    actual = pd.read_csv(STUDY / 'race_returns.csv').set_index(['selector', 'race_id']).sort_index()
    assert actual.index.is_unique and expected.index.equals(actual.index)
    assert actual.selected_pair.equals(expected.pair.rename('selected_pair'))
    for actual_col, expected_col in [('year', 'year'), ('hit', 'hit'),
                                   ('paid_qpl_odds', 'return_multiple'), ('return_krw', 'return_krw')]:
        assert np.allclose(actual[actual_col], expected[expected_col], rtol=0, atol=1e-9)
    assert actual.stake_krw.eq(10000).all()
    assert (actual.return_krw - actual.stake_krw).equals(actual.net_krw)
    summary = pd.read_csv(STUDY / 'summary.csv').set_index(['selector', 'period'])
    mapping = {'races': 'races', 'hits': 'hits', 'hit_rate_pct': 'hit_rate_pct',
        'mean_paid_qpl_odds_on_hits': 'mean_hit_odds', 'sum_paid_qpl_odds': 'return_sum_multiple',
        'stake_krw': 'stake_krw', 'return_krw': 'return_krw', 'net_profit_krw': 'net_profit_krw',
        'recovery_rate_pct': 'recovery_pct', 'roi_pct': 'roi_pct'}
    for selector, periods in results.items():
        for period, values in periods.items():
            label = '2025-2026' if period == 'combined' else period
            got = summary.loc[(names[selector], label)]
            for col, key in mapping.items():
                assert math.isclose(float(got[col]), float(values[key]), rel_tol=0, abs_tol=1e-9)
    published = json.loads((STUDY / 'REPORT.json').read_text())
    for rec in published['same_denominator_summary'] + published['year_summary']:
        got = summary.loc[(rec['selector'], rec['period'])]
        for col in mapping:
            assert math.isclose(float(rec[col]), float(got[col]), rel_tol=0, abs_tol=1e-9)
    for rec in published['comparison_diagnostics']:
        a = expected.loc['jockey_id_candidate']
        b = expected.loc[rec['comparator']]
        changed = a.pair.ne(b.pair)
        delta = a.return_krw - b.return_krw
        assert rec['changed_races'] == int(changed.sum())
        assert rec['current_minus_comparator_net_krw'] == int(delta.sum())
        ranked = sorted(delta.loc[changed].items(), key=lambda kv: (-abs(kv[1]), kv[0]))[:3]
        for index, (race_id, difference) in enumerate(ranked, 1):
            assert rec[f'top{index}_race_id'] == race_id
            assert rec[f'top{index}_delta_return_krw'] == difference
    used = set(actual.loc[actual.hit.eq(1), 'qpl_source_page_sha256'])
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    docs = c.execute('SELECT id,local_path,sha256 FROM source_documents WHERE endpoint=?',
        ('/API301/Dividend_rate_total',)).fetchall()
    c.close()
    source_index, source_prices, seen = [], {}, set()
    for doc_id, local_path, page_hash in docs:
        if page_hash not in used or page_hash in seen:
            continue
        path = (ROOT / local_path).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == page_hash
        source_index.append({'source_document_id': doc_id, 'path': path.relative_to(ROOT).as_posix(),
                             'sha256': page_hash, 'bytes': len(content)})
        items = json.loads(content)['response']['body']['items']['item']
        for item in items:
            if item['pool'] != 'QPL' or str(item['meet']) not in ('제주', '2'):
                continue
            date = str(item['rcDate'])
            race_id = f'{date[:4]}-{date[4:6]}-{date[6:8]}_2_{int(item["rcNo"])}'
            pair = '-'.join(map(str, sorted([int(item['chulNo']), int(item['chulNo2'])])))
            key = (page_hash, race_id, pair)
            value = Decimal(str(item['odds']))
            if key in source_prices:
                assert source_prices[key] == value
            source_prices[key] = value
        seen.add(page_hash)
    assert seen == used
    for r in actual.reset_index().loc[lambda x: x.hit.eq(1)].itertuples():
        assert source_prices[(r.qpl_source_page_sha256, r.race_id, r.selected_pair)] == Decimal(str(r.paid_qpl_odds))
    (STUDY / 'SOURCE_PAGE_INDEX.json').write_text(json.dumps(source_index, indent=2) + '\n')
    result = {'status': 'PASS', 'selectors': 9, 'races_per_selector': 1142,
        'row_level_returns_verified': len(actual), 'summary_rows_verified': len(summary),
        'raw_qpl_pages_independently_hashed_and_parsed': len(used),
        'all_winning_prices_match_raw_api301': True, 'all_comparison_diagnostics_match': True,
        'prediction_sha256': digest,
        'report_sha256': hashlib.sha256((STUDY / 'REPORT.json').read_bytes()).hexdigest()}
    (STUDY / 'ROOT_REVIEW.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
