"""Replay annual scores and independently reconstruct payouts from official sources."""
import hashlib
import json
import pickle
import sqlite3
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl

from scripts.run_jeju_annual_revalidation import annual_parts
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores, order_scores

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT/'data/research/jeju_annual_revalidation_20260918'
OUT = ROOT/'data/research/jeju_annual_returns_20260918'
DATA = ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
DB = ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'

def read(path):
    return json.loads(path.read_text())

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def canonical(m, selection):
    return tuple(sorted(selection)) if m in {'QNL', 'QPL', 'TLA'} else tuple(selection)

def main():
    hashes = 0
    for name, digest in read(ANN/'manifest.json')['files'].items():
        assert sha(ANN/name) == digest
        hashes += 1
    man = read(OUT/'manifest.json')
    for base, section in [(ROOT, 'inputs'), (OUT, 'outputs')]:
        for name, digest in man[section].items():
            assert sha(base/name) == digest
            hashes += 1
    lock = read(OUT/'selection_lock.json')
    assert sha(OUT/'tickets_locked.json') == lock['tickets_sha256']
    assert lock['price_inputs_used_for_selection'] is False
    old = ROOT/'data/research/jeju_native_transition_holdout_v13_20260916/bundles/frozen_2026__HY_R_FORM.pkl'
    assert sha(old) == 'f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706'
    frame, _, _ = data_frame()
    frame = frame.join(pl.read_parquet(DATA/'races.parquet').filter(pl.col('target_eligible')).select('race_id'), on='race_id', how='semi')
    frame = frame.join(pl.read_parquet(ROOT/'data/research/jeju_steward_pace_v2_20260918/features.parquet'), on='entry_id', validate='1:1')
    saved = pl.read_parquet(ANN/'frozen_scores.parquet')
    replayed = 0
    for year in [2024, 2025]:
        parts = annual_parts(frame, year)
        for left, right in [('fit', 'tune'), ('tune', 'calibration'), ('calibration', 'evaluation')]:
            assert parts[left]['event_date'].max() < parts[right]['event_date'].min()
        ev = parts['evaluation']
        assert ev['label_top3'].null_count() == len(ev)
        ob = pickle.loads((ANN/f'bundles/{year}__ORDER.pkl').read_bytes())
        order = order_scores(ob, ev)
        for name in ['BASE', 'PACE_BURDEN'] + (['STEWARD'] if year == 2025 else []):
            bundle = pickle.loads((ANN/f'bundles/{year}__{name}.pkl').read_bytes())
            s = saved.filter((pl.col('year') == year) & (pl.col('model') == name)).sort('race_id', 'horse_id')
            assert s['entry_id'].to_list() == ev['entry_id'].to_list()
            np.testing.assert_allclose(rank_scores(bundle, ev), s['score'].to_numpy(), rtol=0, atol=1e-12)
            np.testing.assert_allclose(order, s['order_score'].to_numpy(), rtol=0, atol=1e-12)
            replayed += len(s)
        if year == 2024:
            assert parts['fit']['st2_report_known'].sum() == 0
    print('Annual score replay passed', replayed, flush=True)
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    nums = {int(e): int(n) for e, n in c.execute('SELECT id,horse_number FROM entry') if n is not None}
    source_rows = {int(i): json.loads(s) for i, s in c.execute('SELECT id,normalized_json FROM source_row')}
    c.close()
    obs = pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet')
    numbers = {(r['race_id'], r['horse_id']): nums[r['entry_id']] for r in obs.to_dicts()}
    accepted = defaultdict(list)
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():
        accepted[r['race_id']].append(tuple(numbers[(r['race_id'], r[k])] for k in ['first_horse_id','second_horse_id','third_horse_id']))
    cache = {}
    payouts = defaultdict(dict)
    for row in read(OUT/'settlement_sources.json'):
        src = row['source']; path = ROOT/src['path']
        if str(path) not in cache:
            assert sha(path) == src['sha256']
            hashes += 1
            if src['kind'] == 'official_final_dividend_cache':
                items = read(path)['response']['body']['items']['item']
                if isinstance(items, dict): items = [items]
                cache[str(path)] = {(str(i['rcDate']), int(i['rcNo']), i['pool'], canonical(i['pool'], [int(i[k]) for k in ['chulNo','chulNo2','chulNo3'] if i.get(k)])): float(i['odds']) for i in items}
            else:
                cache[str(path)] = None
        if src['kind'] == 'official_final_dividend_cache':
            value = cache[str(path)][(row['date'].replace('-', ''), row['race_number'], row['market'], tuple(row['selection']))]
        else:
            value = float(source_rows[src['source_row_id']]['winOdds' if row['market'] == 'WIN' else 'plcOdds'])
        assert value == row['odds']
        payouts[(row['race_id'], row['market'])][tuple(row['selection'])] = value
    tickets = read(OUT/'tickets_locked.json')
    settled = {(r['race_id'], r['policy']): r for r in read(OUT/'settled_races.json')}
    unknown = {(r['race_id'], r['market']) for r in read(OUT/'unsettled_race_markets.json')}
    for row in tickets:
        rid, m = row['race_id'], row['market']
        assert len(accepted[rid]) == 1
        a, b, d = accepted[rid][0]
        winners = {'WIN': {(a,)}, 'PLC': {(h,) for h in (a,b,d)[:2 if row['field_size'] <= 7 else 3]},
                   'QNL': {tuple(sorted((a,b)))}, 'EXA': {(a,b)},
                   'QPL': {tuple(sorted(pair)) for pair in combinations((a,b,d),2)},
                   'TLA': {tuple(sorted((a,b,d)))}, 'TRI': {(a,b,d)}}[m]
        assert len(row['tickets']) == row['k'] == len({canonical(m, t) for t in row['tickets']})
        assert row['total_stake'] == 1
        if (rid,m) in unknown:
            assert (rid,row['policy']) not in settled
            continue
        assert set(payouts[(rid,m)]) == winners
        value = sum(payouts[(rid,m)].get(canonical(m,t),0) for t in row['tickets']) / row['k']
        result = settled[(rid,row['policy'])]
        assert np.isclose(value, result['gross_return'])
        assert np.isclose(value - 1, result['net_return'])
        assert result['hit'] == any(canonical(m,t) in winners for t in row['tickets'])
    for s in read(OUT/'summary.json'):
        rows = [r for r in settled.values() if r['year'] == s['year'] and r['policy'] == s['policy']]
        assert len(rows) == s['settled_races']
        if rows:
            assert sum(r['hit'] for r in rows) == s['hits']
            assert np.isclose(sum(r['gross_return'] for r in rows)/len(rows), s['gross_recovery'])
    expected = [('WIN',[4],1.5),('PLC',[4],1.0),('PLC',[7],1.2),('PLC',[2],6.5),('QNL',[4,7],3.7),('EXA',[4,7],4.5),('QPL',[4,7],1.5),('QPL',[2,4],10.3),('QPL',[2,7],18.0),('TLA',[2,4,7],33.5),('TRI',[4,7,2],73.3)]
    check = {(r['market'], tuple(r['selection'])): r['odds'] for r in read(OUT/'settlement_sources.json') if r['date']=='2026-01-02' and r['race_number']==1}
    for m,t,p in expected: assert check[(m,tuple(t))] == p
    result = dict(hashes_checked=hashes, annual_score_rows_replayed=replayed, annual_time_boundaries=True,
                  tickets_rechecked=len(tickets), settlements_recomputed=len(settled), missing_payouts_excluded=True,
                  original_2026_bundle_unchanged=True, official_public_spotcheck=dict(
                      url='https://m.kra.co.kr/race/jeju/scoretableDailyList.do?rcDate=20260102', race=1, dividends=11),
                  limitation='Public page spotcheck is one race; full payout provenance is verified against cached official sources.')
    (OUT/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
