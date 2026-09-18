"""Read-only replay and independent artifact checks for the fixed tempo pilot."""
import hashlib
import json
import pickle
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores, order_scores
from horse_racing.analysis.jeju_tempo_pace import PAR, PACE

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'data/research/jeju_tempo_pace_pilot_20260917'
F = ROOT / 'data/research/jeju_tempo_pace_features_20260917'
OLD = ROOT / 'data/research/jeju_native_transition_holdout_v13_20260916'
DATA = ROOT / 'data/research/jeju_native_top3_dataset_v1_20260915_r2'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    checks = {}
    for root in [F, P]:
        manifest = json.loads((root / 'manifest.json').read_text())
        for path, expected in manifest['files'].items():
            assert sha(root / path) == expected, path
        for category in ['parents', 'code']:
            for path, expected in manifest.get(category, {}).items():
                assert sha(Path(path)) == expected, path
        checks[root.name + '_hashes'] = True
    protocol = json.loads((P / 'protocol.json').read_text())
    assert sha(OLD / 'bundles/frozen_2026__HY_R_FORM.pkl') == protocol['old_model_sha256']
    assert sha(ROOT / 'docs/JEJU_NATIVE_TEMPO_PACE_PILOT_PLAN_2026-09-17.md') == protocol['plan_sha256']
    checks['baseline_and_plan_unchanged'] = True

    frame, _, folds = data_frame()
    frame = frame.join(pl.read_parquet(F / 'features.parquet'), on='entry_id', validate='1:1')
    ev = frame.join(folds.filter(pl.col('role') == 'evaluation').select('race_id'), on='race_id', how='semi').sort('race_id', 'horse_id')
    assert ev['finish_position'].null_count() == len(ev) == 4852
    scores = pl.read_parquet(P / 'frozen_scores.parquet')
    old = pickle.loads((OLD / 'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    for name in ['BASE', 'PAR', 'PACE', 'BOTH']:
        bundle = old['rank_bundle'] if name == 'BASE' else pickle.loads((P / 'bundles' / (name + '.pkl')).read_bytes())
        expected = [] if name == 'BASE' else PAR if name == 'PAR' else PACE if name == 'PACE' else PAR + PACE
        assert bundle['features'] == old['rank_bundle']['features'] + expected
        saved = scores.filter(pl.col('model') == name + '__BASE').sort('race_id', 'horse_id')
        assert saved['entry_id'].to_list() == ev['entry_id'].to_list()
        replay = rank_scores(bundle, ev)
        assert np.allclose(replay, saved['score'].to_numpy(), atol=1e-12, rtol=0)
    for name in ['BASE', 'NEW']:
        bundle = old['order_bundle'] if name == 'BASE' else pickle.loads((P / 'bundles/ORDER_BOTH.pkl').read_bytes())
        assert bundle['features'] == old['order_bundle']['features'] + ([] if name == 'BASE' else PAR + PACE)
        saved = scores.filter(pl.col('model') == 'BASE__' + name).sort('race_id', 'horse_id')
        assert np.allclose(order_scores(bundle, ev), saved['order_score'].to_numpy(), atol=1e-12, rtol=0)
    checks['all_saved_bundles_replay_exact'] = True

    labels = pl.read_parquet(DATA / 'labels.parquet').filter(pl.col('label_top3') == 1)
    podium = {}
    for row in labels.to_dicts():
        podium.setdefault(row['race_id'], set()).add(row['horse_id'])
    accepted = {}
    for row in pl.read_parquet(DATA / 'accepted_orders.parquet').to_dicts():
        accepted.setdefault(row['race_id'], set()).add((row['first_horse_id'], row['second_horse_id'], row['third_horse_id']))
    races = pl.read_parquet(P / 'race_predictions.parquet')
    for row in races.to_dicts():
        rid = row['race_id']
        assert row['pick_hit'] == (row['pick_horse_id'] in podium[rid])
        assert row['set_hit'] == (set(row['predicted_set']) == podium[rid])
        assert row['order_hit'] == (tuple(row['predicted_order']) in accepted[rid])
        assert set(row['predicted_order']) == set(row['predicted_set'])
        assert abs(row['set_probability_sum'] - 1) < 1e-10
        assert abs(row['order_probability_sum'] - 1) < 1e-10
    horses = pl.read_parquet(P / 'horse_predictions.parquet')
    assert horses['p'].is_between(0, 1).all()
    assert ((horses.group_by('model', 'race_id').agg(pl.col('p').sum())['p'] - 3).abs() < 1e-10).all()
    assert races.height == 8 * 510
    checks['independent_pick_set_order_and_probability_checks'] = True

    obs = {r['entry_id']: r for r in pl.read_parquet(F / 'observations.parquet').to_dicts()}
    lineage = pl.read_parquet(F / 'lineage.parquet').to_dicts()
    for row in lineage:
        target = obs[row['entry_id']]
        for key in row['source_entry_ids']:
            past = obs[key]
            assert past['horse_id'] == target['horse_id']
            assert past['distance_m'] == target['distance_m']
            assert past['event_date'] <= target['event_date'] - timedelta(days=2)
        assert len(row['source_entry_ids']) <= 3
    checks['all_84583_lineages_same_horse_distance_and_T_minus_2'] = True
    checks['evaluation_feature_support'] = ev.select(
        (pl.col('par_supported_count_3') > 0).mean().alias('any_par'),
        (pl.col('tempo_known_count_3') > 0).mean().alias('any_tempo'),
        (pl.col('pace_history_count_3') > 0).mean().alias('any_same_distance_history'),
    ).to_dicts()[0]
    checks['fit_count'] = len(json.loads((P / 'fit_ledger.json').read_text()))
    assert checks['fit_count'] == 8
    (P / 'verification.json').write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
