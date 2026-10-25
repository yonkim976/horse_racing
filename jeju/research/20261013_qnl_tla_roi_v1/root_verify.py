"""Independent saved-ticket and winning-dividend accounting."""
import ast
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
JOINT = ROOT / 'jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/report/canonical_six_combinations.csv'
SELECTORS = ['selected_jockey_id_candidate', 'selected_jockey_basic_candidate',
    'selected_expanded_candidate', 'selected_old_direct', 'selected_raw_top2',
    'selected_saved_f1_top2', 'selected_candidate_joint_marginal_top2',
    'selected_candidate_joint_maxpair', 'selected_matched_joint_maxpair']


def canonical(value):
    return tuple(sorted(int(v) for v in value.split(',')))


def calculate():
    assert hashlib.sha256(PAIR.read_bytes()).hexdigest() == '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6'
    p = pd.read_parquet(PAIR)
    p = p.loc[p.evaluation_year.isin([2025, 2026])]
    cohort = set(p.race_id)
    assert len(cohort) == 1142
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    ranks = c.execute('''SELECT r.race_date_local,r.race_number,e.horse_number,s.finish_position
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id JOIN race_results s ON s.race_entry_id=e.id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ?''',
        ('2025-01-01', '2026-09-19')).fetchall()
    quotes = c.execute('''SELECT r.race_date_local,r.race_number,o.bet_type,o.selection_key,o.odds
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        JOIN odds_snapshots o ON o.race_id=r.id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN ? AND ? AND o.bet_type IN ('QNL','TLA')''',
        ('2025-01-01', '2026-09-19')).fetchall()
    c.close()
    podium = {pool: {} for pool in ['QNL', 'TLA']}
    for day, no, horse, rank in ranks:
        rid = f'{day}_2_{no}'
        if rid not in cohort or rank is None:
            continue
        for pool, limit in [('QNL', 2), ('TLA', 3)]:
            if 1 <= rank <= limit:
                podium[pool].setdefault(rid, []).append(horse)
    odds = {}
    for day, no, pool, key, value in quotes:
        k = (f'{day}_2_{no}', pool, tuple(map(int, key.split('-'))))
        assert k not in odds
        odds[k] = Decimal(str(value))
    for pool, groups in podium.items():
        for rid, horses in groups.items():
            groups[rid] = tuple(sorted(horses))
            assert len(horses) == (2 if pool == 'QNL' else 3)
    strategies = []
    for selector in SELECTORS:
        selected = p.loc[p[selector].eq(1)]
        assert len(selected) == 1142 and selected.race_id.is_unique
        tickets = {r.race_id: [(int(r.horse_i), int(r.horse_j))] for r in selected.itertuples()}
        strategies.append(('QNL', selector, 1, tickets))
    j = pd.read_csv(JOINT)
    j = j.loc[j.race_id.isin(cohort)]
    sixes = {}
    for name, col in [('joint_candidate', 'candidate_six_tickets'), ('matched_baseline', 'baseline_six_tickets')]:
        sixes[name] = {r.race_id: [canonical(t) for t in ast.literal_eval(getattr(r, col))] for r in j.itertuples()}
    f = pd.read_csv(STYLE)
    f = f.loc[f.race_id.isin(cohort)]
    for variant in ['F1', 'F1_STYLE6']:
        sixes[variant] = {rid: [canonical(t) for t in g.sort_values('selection_rank').numbers]
            for rid, g in f.loc[f.variant.eq(variant)].groupby('race_id')}
    for name, six in sixes.items():
        assert set(six) == cohort
        assert all(len(t) == len(set(t)) == 6 for t in six.values())
        for count in [1, 6]:
            strategies.append(('TLA', name, count, {rid: t[:count] for rid, t in six.items()}))
    rows = []
    for pool, name, count, selections in strategies:
        for rid, tickets in selections.items():
            winner = podium[pool][rid]
            assert len(tickets) == len(set(tickets)) == count
            hit = int(winner in tickets)
            winning_odds = odds[(rid, pool, winner)]
            payout = winning_odds * (6000 // count) if hit else Decimal(0)
            assert payout == payout.to_integral_value()
            rows.append({'pool': pool, 'strategy': name, 'ticket_count': count, 'race_id': rid,
                'year': int(rid[:4]), 'tickets': tickets, 'winner': winner, 'hit': hit,
                'winning_odds': float(winning_odds), 'stake_krw': 6000,
                'return_krw': int(payout), 'net_krw': int(payout) - 6000})
    data = pd.DataFrame(rows)
    summary = []
    for (pool, strategy, count), g in data.groupby(['pool', 'strategy', 'ticket_count']):
        for label, part in [('combined', g), ('2025', g.loc[g.year.eq(2025)]), ('2026_partial', g.loc[g.year.eq(2026)])]:
            stake = int(part.stake_krw.sum())
            returned = int(part.return_krw.sum())
            summary.append({'pool': pool, 'strategy': strategy, 'ticket_count': count,
                'period': label, 'races': len(part), 'hits': int(part.hit.sum()),
                'stake_krw': stake, 'return_krw': returned, 'net_krw': returned - stake,
                'roi_pct': (returned - stake) / stake * 100})
    return data, summary


def main():
    independent, summary = calculate()
    payload = {'method': 'Independent source tickets, DB winning keys, and Decimal payouts',
        'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [PAIR, JOINT, STYLE]}, 'summary': summary}
    (STUDY / 'ROOT_REFERENCE.json').write_text(json.dumps(payload, indent=2) + '\n')
    if not (STUDY / 'race_returns.csv').exists():
        print(json.dumps([r for r in summary if r['period'] == 'combined']))
        return
    names = dict(zip(SELECTORS, ['jockey_id_candidate', 'jockey_basic_candidate',
        'expanded_candidate', 'old_direct', 'raw_top2', 'saved_f1_top2',
        'joint_marginal_top2', 'candidate_joint_maxpair', 'matched_joint_maxpair']))
    expected_rows = []
    for r in independent.itertuples():
        selector = names[r.strategy] if r.pool == 'QNL' else (
            ('joint_matched_baseline' if r.strategy == 'matched_baseline' else r.strategy)
            + ('_rank1' if r.ticket_count == 1 else '_six'))
        for rank, ticket in enumerate(r.tickets, 1):
            hit = int(ticket == r.winner)
            stake = 6000 // r.ticket_count
            paid = r.winning_odds if hit else 0
            returned = Decimal(str(paid)) * stake
            expected_rows.append({'pool': r.pool, 'selector': selector, 'race_id': r.race_id,
                'year': r.year, 'ticket_rank': rank, 'ticket': ','.join(map(str, ticket)),
                'exact_hit': hit, 'stake_krw': stake, 'paid_dividend_odds': paid,
                'return_krw': int(returned), 'net_krw': int(returned) - stake})
    qpl_path = ROOT / 'jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv'
    qpl = pd.read_csv(qpl_path)
    for r in qpl.loc[qpl.selector.eq('jockey_id_candidate')].itertuples():
        returned = Decimal(str(r.paid_qpl_odds)) * 6000
        expected_rows.append({'pool': 'QPL', 'selector': 'QPL_jockey_id_candidate_reference',
            'race_id': r.race_id, 'year': r.year, 'ticket_rank': 1,
            'ticket': r.selected_pair.replace('-', ','), 'exact_hit': r.hit,
            'stake_krw': 6000, 'paid_dividend_odds': r.paid_qpl_odds,
            'return_krw': int(returned), 'net_krw': int(returned) - 6000})
    keys = ['pool', 'selector', 'race_id', 'ticket_rank']
    expected = pd.DataFrame(expected_rows).set_index(keys).sort_index()
    actual = pd.read_csv(STUDY / 'race_returns.csv').set_index(keys).sort_index()
    assert expected.index.equals(actual.index) and actual.index.is_unique
    assert expected.ticket.equals(actual.ticket)
    for col in ['year', 'exact_hit', 'stake_krw', 'paid_dividend_odds', 'return_krw', 'net_krw']:
        assert np.allclose(expected[col], actual[col], rtol=0, atol=1e-8), col
    got = pd.read_csv(STUDY / 'summary.csv').set_index(['pool', 'selector', 'period'])
    for (pool, selector), g in expected.reset_index().groupby(['pool', 'selector']):
        assert g.groupby('race_id').stake_krw.sum().eq(6000).all()
        for label, part in [('2025-2026', g), ('2025', g.loc[g.year.eq(2025)]),
                            ('2026_partial', g.loc[g.year.eq(2026)])]:
            row = got.loc[(pool, selector, label)]
            stake, returned = int(part.stake_krw.sum()), int(part.return_krw.sum())
            hits = int(part.exact_hit.sum())
            races = int(part.race_id.nunique())
            values = {'races': races, 'ticket_count': len(part), 'ticket_hits': hits,
                'hit_races': part.loc[part.exact_hit.eq(1)].race_id.nunique(),
                'stake_krw': stake, 'return_krw': returned, 'net_profit_krw': returned - stake,
                'roi_pct': (returned - stake) / stake * 100, 'recovery_rate_pct': returned / stake * 100,
                'ticket_hit_rate_pct': hits / len(part) * 100, 'race_hit_rate_pct': hits / races * 100,
                'mean_paid_dividend_odds_on_hits': part.loc[part.exact_hit.eq(1)].paid_dividend_odds.mean()}
            for col, value in values.items():
                assert math.isclose(float(row[col]), float(value), rel_tol=0, abs_tol=1e-8)
    report = json.loads((STUDY / 'REPORT.json').read_text())
    for r in report['summary']:
        row = got.loc[(r['pool'], r['selector'], r['period'])]
        for col, value in row.items():
            assert math.isclose(float(r[col]), float(value), rel_tol=0, abs_tol=1e-8)
    hashes = json.loads((STUDY / 'SOURCE_HASHES.json').read_text())['source_sha256']
    for path, value in hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == value
    used = set(actual.loc[actual.exact_hit.eq(1), 'winning_api301_page_sha256'])
    c = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    docs = c.execute('SELECT id,local_path,sha256 FROM source_documents WHERE endpoint=?',
        ('/API301/Dividend_rate_total',)).fetchall()
    c.close()
    pages, source_values, seen = [], {}, set()
    for doc_id, local_path, page_hash in docs:
        if page_hash not in used or page_hash in seen:
            continue
        path = (ROOT / local_path).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == page_hash
        pages.append({'source_document_id': doc_id, 'path': path.relative_to(ROOT).as_posix(),
                      'sha256': page_hash, 'bytes': len(content)})
        for item in json.loads(content)['response']['body']['items']['item']:
            pool = item['pool']
            if pool not in ('QNL', 'TLA', 'QPL') or str(item['meet']) not in ('제주', '2'):
                continue
            day = str(item['rcDate'])
            rid = f'{day[:4]}-{day[4:6]}-{day[6:8]}_2_{int(item["rcNo"])}'
            ns = [int(item['chulNo']), int(item['chulNo2'])]
            if pool == 'TLA':
                ns.append(int(item['chulNo3']))
            ticket = ','.join(map(str, sorted(ns)))
            source_values[(page_hash, pool, rid, ticket)] = Decimal(str(item['odds']))
        seen.add(page_hash)
    assert used == seen
    for r in actual.reset_index().loc[lambda x: x.exact_hit.eq(1)].itertuples():
        assert source_values[(r.winning_api301_page_sha256, r.pool, r.race_id, r.ticket)] == Decimal(str(r.paid_dividend_odds))
    (STUDY / 'SOURCE_PAGE_INDEX.json').write_text(json.dumps(pages, indent=2) + '\n')
    receipt = {'status': 'PASS', 'independent_ticket_rows_verified': len(actual),
        'methods': 18, 'summary_rows_verified': len(got), 'races_per_method': 1142,
        'race_budget_krw': 6000, 'winning_api301_pages_hashed_and_parsed': len(used),
        'all_source_hashes_match': True, 'all_winning_payments_match_raw_api301': True,
        'report_sha256': hashlib.sha256((STUDY / 'REPORT.json').read_bytes()).hexdigest()}
    (STUDY / 'ROOT_REVIEW.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
