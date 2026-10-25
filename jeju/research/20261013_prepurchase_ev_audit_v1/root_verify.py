"""Independent read-only audit; never imports the worker's calculation helpers."""
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PRED = ROOT / 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def connect(path):
    c = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    return c


def main():
    assert sha(PRED.read_bytes()) == '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6'
    full = pd.read_parquet(PRED)
    fixed = full.loc[full.selected_jockey_id_candidate.eq(1)].set_index('race_id')
    selected = fixed.loc[fixed.evaluation_year.isin([2025, 2026])]
    assert len(fixed) == 1779 and fixed.index.is_unique and len(selected) == 1142
    c = connect(ROOT / 'data/horse_racing.sqlite3')
    audit = pd.read_csv(STUDY / 'selected_pair_time_audit.csv').set_index('race_id')
    required = pd.read_csv(STUDY / 'selected_pair_required_odds.csv').set_index('race_id')
    assert len(audit) == len(required) == 1142
    assert audit.index.is_unique and required.index.is_unique
    assert set(audit.index) == set(required.index) == set(selected.index)
    races = {}
    for r in c.execute('''SELECT r.id,r.race_date_local,r.race_number,r.scheduled_at_ms,r.actual_start_at_ms
        FROM races r JOIN racecourses t ON t.id=r.racecourse_id
        WHERE t.kra_meet_code=? AND r.race_date_local BETWEEN ? AND ?''',
        (2, '2025-01-01', '2026-09-19')):
        key = f"{r['race_date_local']}_2_{r['race_number']}"
        if key in selected.index:
            races[key] = r
    assert len(races) == 1142
    pairs = {}; probs = {}; cutoffs = {}
    for rid, p in selected.iterrows():
        pair = '-'.join(map(str, sorted([int(p.horse_i), int(p.horse_j)])))
        probability = float(p.jockey_id_candidate_calibrated_probability)
        pairs[rid] = pair; probs[rid] = probability
        r, a, q = races[rid], audit.loc[rid], required.loc[rid]
        cutoff = r['scheduled_at_ms'] - 300000
        cutoffs[rid] = cutoff
        assert a.pair == q.selected_pair == pair
        assert abs(a.p_pair_top3 - probability) < 1e-14
        assert a.cutoff_ms == cutoff and a.scheduled_at_ms == r['scheduled_at_ms']
        assert r['actual_start_at_ms'] is None and pd.isna(a.actual_start_at_ms)
        quotes = c.execute('''SELECT observed_at_ms FROM odds_snapshots
            WHERE race_id=? AND bet_type=? AND selection_key=?''', (r['id'], 'QPL', pair)).fetchall()
        assert len(quotes) == int(a.shared_qpl_rows_exact_pair) == 1
        assert sum(x[0] < cutoff for x in quotes) == a.shared_qpl_exact_pair_rows_before_cutoff == 0
        assert pd.isna(a.pre_cutoff_odds) and pd.isna(a.pre_cutoff_ev)
        assert pd.isna(q.actual_pre_purchase_quote) and pd.isna(q.actual_ev)
        assert abs(q.p_pair_top3 - probability) <= 5.1e-9
        for suffix, ev in [('0', 0), ('0_05', .05), ('0_10', .10), ('0_20', .20)]:
            assert abs(q[f'required_qpl_display_odds_ev_ge_{suffix}'] - (1 + ev)/probability) <= 5.1e-7
    # Read registry independently; do not output URLs or unfiltered request parameters.
    documents = {}
    days = {rid.split('_')[0] for rid in selected.index}
    for r in c.execute('''SELECT id,ingestion_run_id,local_path,sha256,requested_at_ms,retrieved_at_ms,
        request_params_json FROM source_documents WHERE endpoint=?''', ('/API301/Dividend_rate_total',)):
        params = json.loads(r['request_params_json'] or '{}')
        day = str(params.get('rc_date', ''))
        if len(day) == 8:
            day = day[:4] + '-' + day[4:6] + '-' + day[6:]
        if day in days and str(params.get('meet')) in ('2', '제주'):
            documents[r['id']] = (dict(r), day)
    index = json.loads((STUDY / 'SOURCE_PAGE_INDEX.json').read_text())
    assert len(index) == len(documents) == 889
    assert {x['document_id'] for x in index} == set(documents)
    candidates = {}; all_versions = defaultdict(list); raw_cache = {}
    for entry in index:
        r, day = documents[entry['document_id']]
        path = Path(r['local_path'])
        if not path.is_absolute():
            path = ROOT / path
        assert path.resolve().is_relative_to(ROOT.resolve())
        if path not in raw_cache:
            data = path.read_bytes()
            raw_cache[path] = (sha(data), json.loads(data))
        digest, payload = raw_cache[path]
        assert digest == r['sha256'] == entry['expected_sha256'] == entry['actual_sha256']
        assert entry['hash_verified'] and entry['requested_at_ms'] == r['requested_at_ms']
        assert entry['retrieved_at_ms'] == r['retrieved_at_ms']
        items = payload['response'].get('body', {}).get('items') or {}
        items = items.get('item', []) if isinstance(items, dict) else []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if item.get('pool') != 'QPL' or str(item.get('meet')) not in ('제주', '2'):
                continue
            raw_day = str(item['rcDate'])
            item_day = raw_day[:4] + '-' + raw_day[4:6] + '-' + raw_day[6:]
            if item_day != day:
                continue
            rid = f"{day}_2_{int(item['rcNo'])}"
            if rid not in selected.index:
                continue
            pair = '-'.join(map(str, sorted([int(item['chulNo']), int(item['chulNo2'])])))
            if pair != pairs[rid]:
                continue
            price = float(item['odds'])
            all_versions[rid].append((r['requested_at_ms'], r['retrieved_at_ms'], price))
            if r['requested_at_ms'] < cutoffs[rid] and r['retrieved_at_ms'] < cutoffs[rid]:
                key = (rid, r['id'])
                assert key not in candidates
                candidates[key] = (r, price, digest)
    got = pd.read_csv(STUDY / 'RAW_PRESTART_API301_CANDIDATES.csv')
    assert len(got) == len(candidates) == 4
    assert Counter(x[1] for x in candidates.values()) == {1.0: 2, 9999.9: 2}
    for row in got.itertuples():
        r, price, digest = candidates[(row.race_id, row.document_id)]
        assert row.pair == pairs[row.race_id]
        assert abs(row.probability - probs[row.race_id]) < 1e-14
        assert row.source_api301_value == price and row.source_hash == digest
        assert row.requested_at_ms == r['requested_at_ms'] and row.retrieved_at_ms == r['retrieved_at_ms']
        assert row.cutoff_ms == cutoffs[row.race_id]
        later = [x for x in all_versions[row.race_id] if x[1] >= cutoffs[row.race_id]]
        assert len(later) == row.after_cutoff_exact_pair_source_versions == 2
        assert any(x[2] != price for x in later) and row.after_cutoff_source_value_differs
        if price == 1:
            assert math.isclose(row.conditional_ev_proxy, probs[row.race_id] - 1, abs_tol=1e-14)
        else:
            assert pd.isna(row.conditional_ev_proxy) and row.exceptional_value_excluded_from_ev
        assert not any(getattr(row, x) for x in ['proxy_pass_ev_ge_0', 'proxy_pass_ev_ge_0_05',
            'proxy_pass_ev_ge_0_10', 'proxy_pass_ev_ge_0_20'])
    for rid in selected.index:
        count = sum(k[0] == rid for k in candidates)
        assert audit.loc[rid].raw_api301_exact_pair_items_requested_and_retrieved_before_cutoff == count
    exception = c.execute('''SELECT r.race_date_local,r.race_number,o.selection_key
        FROM odds_snapshots o JOIN races r ON r.id=o.race_id
        JOIN racecourses t ON t.id=r.racecourse_id
        WHERE t.kra_meet_code=? AND o.bet_type=? AND o.observed_at_ms<r.scheduled_at_ms-?''',
        (2, 'QPL', 300000)).fetchall()
    assert len(exception) == 7
    for r in exception:
        assert r['race_date_local'] == '2026-09-05' and r['race_number'] == 7
        assert '7' in r['selection_key'].split('-') and '2026-09-05_2_7' not in fixed.index
    scratch = c.execute('''SELECT e.scratched FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses t ON t.id=r.racecourse_id WHERE t.kra_meet_code=?
        AND r.race_date_local=? AND r.race_number=? AND e.horse_number=?''', (2, '2026-09-05', 7, 7)).fetchone()
    assert scratch[0] == 1
    probe = connect(ROOT / 'data/research/api301_snapshot_probe_20261009/snapshots.sqlite3')
    pre = probe.execute('''SELECT count(*),sum(positive_rows),sum(status='empty') FROM observations
        WHERE meet=? AND received_ms<start_ms''', (2,)).fetchone()
    assert tuple(pre) == (38, 0, 38)
    report = json.loads((STUDY / 'REPORT.json').read_text())
    assert report['decision']['raw_pre_cutoff_exact_pair_candidates'] == 4
    assert report['decision']['verified_pre_purchase_selected_pair_quotes'] == 0
    assert not report['decision']['ev_threshold_backtest_created']
    assert not report['decision']['roi_or_confidence_interval_created']
    review = {'status': 'PASS', 'review_scope': 'Data availability and conditional price arithmetic only; no profitability validation',
        'selected_prediction_rows_verified': 1142, 'theoretical_required_odds_rows_verified': 1142,
        'source_registry_pages_independently_hash_verified': 889,
        'raw_pre_cutoff_candidates_independently_reconstructed': 4,
        'ordinary_1_0_negative_proxy_candidates': 2, 'unknown_9999_9_excluded_candidates': 2,
        'all_four_later_source_values_changed': True, 'shared_current_selected_quotes_before_cutoff': 0,
        'actual_start_missing': 1142, 'independent_public_bettability_or_clock_evidence_found': False,
        'out_of_cohort_scratched_pair_rows_verified': 7, 'separate_probe_pre_positive': 0,
        'qnl_ev_computed_using_top3_probability': False, 'roi_or_ci_estimated': False,
        'models_refit_or_operational_registry_changed': False, 'database_access': 'mode=ro; query_only=ON',
        'report_sha256': sha((STUDY / 'REPORT.json').read_bytes()),
        'reviewed_output_sha256': {p.name: sha(p.read_bytes()) for p in STUDY.iterdir()
            if p.is_file() and p.name != 'ROOT_REVIEW.json'}}
    (STUDY / 'ROOT_REVIEW.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in review.items() if k != 'reviewed_output_sha256'}))


if __name__ == '__main__':
    main()
