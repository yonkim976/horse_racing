"""Independent comparison of saved pair predictions; no training or DB access."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
OLD = ROOT / 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet'
OLD_SHA = '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert digest(OLD) == OLD_SHA
    path = STUDY / 'outputs/evaluation_pair_predictions.parquet'
    current_hash = digest(path)
    old = pd.read_parquet(OLD)
    new = pd.read_parquet(path)
    keys = ['race_id', 'horse_i', 'horse_j']
    for frame in (old, new):
        frame['race_id'] = frame.race_id.astype(str)
        assert not frame.duplicated(keys).any()
    old = old.set_index(keys).sort_index()
    new = new.set_index(keys).sort_index()
    assert old.index.equals(new.index) and len(new) == 76848
    assert old.index.get_level_values('race_id').nunique() == 1779
    for col in old:
        if pd.api.types.is_numeric_dtype(old[col]):
            assert np.allclose(old[col], new[col], rtol=0, atol=0, equal_nan=True), col
        else:
            assert old[col].astype(str).equals(new[col].astype(str)), col
    receipt = json.loads((STUDY / 'outputs/PREDICTION_RECEIPT.json').read_text())
    pcol = receipt.get('candidate_probability_column')
    scol = receipt.get('candidate_selector_column')
    if not pcol:
        candidates = [c for c in new if c.endswith('_calibrated_probability') and c not in old]
        assert len(candidates) == 1
        pcol = candidates[0]
    if not scol:
        candidates = [c for c in new if c.startswith('selected_') and c not in old]
        assert len(candidates) == 1
        scol = candidates[0]
    refcol = 'jockey_id_candidate_calibrated_probability'
    assert new[pcol].between(0, 1, inclusive='neither').all()
    assert new[scol].isin([0, 1]).all()
    frame = new.reset_index()
    assert frame.groupby('race_id')[scol].sum().eq(1).all()
    assert frame.groupby('race_id').y_pair.sum().eq(3).all()
    # Select on logits to preserve the contract even if sigmoid rounds two
    # distinct logits to the same floating-point probability.
    eta_col = pcol.replace('_calibrated_probability', '_eta')
    assert eta_col in frame and np.isfinite(frame[eta_col]).all()
    fit_path = STUDY / 'outputs/FIT.json'
    fit = json.loads(fit_path.read_text())
    assert fit['h1_fit_count'] == 3 and fit['h2_candidate_map_count'] == 3
    map_errors = {}
    for fold in fit['folds']:
        part = frame[frame.evaluation_year.eq(fold['evaluation_year'])]
        coef = np.asarray(fold['coefficients'], dtype=float)
        assert len(coef) == 69 and np.isfinite(coef).all()
        assert fold['optimizer']['success'] and fold['optimizer']['gradient_inf_norm'] <= 1e-6
        cal = fold['h2_candidate_platt']
        assert cal['success'] and cal['B'] > 0 and cal['projected_gradient_inf_norm'] <= 1e-6
        eta = part[eta_col].to_numpy(float)
        raw = 1 / (1 + np.exp(-eta))
        calibrated = 1 / (1 + np.exp(-(cal['A'] + cal['B'] * eta)))
        err = max(np.max(np.abs(raw - part[pcol.replace('calibrated', 'raw')])),
                  np.max(np.abs(calibrated - part[pcol])))
        assert err < 1e-14
        map_errors[str(fold['evaluation_year'])] = float(err)
    expected = frame.sort_values(['race_id', eta_col, 'horse_i', 'horse_j'],
                                 ascending=[True, False, True, True]).groupby('race_id').head(1)
    selected = frame[frame[scol].eq(1)]
    assert set(map(tuple, expected[keys].to_numpy())) == set(map(tuple, selected[keys].to_numpy()))
    base = frame[frame.selected_jockey_id_candidate.eq(1)].set_index('race_id').sort_index()
    chosen = selected.set_index('race_id').loc[base.index]
    races = base[['race_date', 'evaluation_year', 'distance_m']].copy()
    races['old_hit'] = base.y_pair
    races['new_hit'] = chosen.y_pair
    races['hit_delta'] = chosen.y_pair - base.y_pair
    races['changed'] = (chosen.horse_i != base.horse_i) | (chosen.horse_j != base.horse_j)
    for metric in ('brier', 'logloss'):
        def loss(p, y):
            return (p-y)**2 if metric == 'brier' else -(y*np.log(p)+(1-y)*np.log1p(-p))
        races['fixed_'+metric+'_delta'] = loss(base[pcol], base.y_pair) - loss(base[refcol], base.y_pair)
        all_delta = loss(frame[pcol], frame.y_pair) - loss(frame[refcol], frame.y_pair)
        races['all_'+metric+'_delta'] = all_delta.groupby(frame.race_id).mean().loc[races.index]
    dates = sorted(pd.to_datetime(frame.race_date).dt.strftime('%Y-%m-%d').unique())
    assert len(dates) == 269
    schedule = np.load(ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy', allow_pickle=False)
    assert schedule.shape == (2000, 269)
    weights = np.stack([np.bincount(draw, minlength=269) for draw in schedule])
    lookup = {d: i for i, d in enumerate(dates)}
    date_i = pd.to_datetime(races.race_date).dt.strftime('%Y-%m-%d').map(lookup).to_numpy()
    counts = np.bincount(date_i, minlength=269)
    cis = {}
    for col in ['hit_delta', 'fixed_brier_delta', 'fixed_logloss_delta', 'all_brier_delta', 'all_logloss_delta']:
        totals = np.bincount(date_i, weights=races[col], minlength=269)
        draws = (weights @ totals) / (weights @ counts)
        cis[col] = {'estimate': float(races[col].mean()), 'ci95': np.quantile(draws, [.025, .975]).tolist()}
    assert int(races.old_hit.sum()) == 438
    by_year = []
    for year, group in races.groupby('evaluation_year'):
        by_year.append({'year': int(year), 'races': len(group), 'old_hits': int(group.old_hit.sum()), 'new_hits': int(group.new_hit.sum())})
    result = {'status': 'PASS', 'scope': 'Independent saved-prediction calculation, not improvement confirmation',
              'races': len(races), 'pair_rows': len(frame), 'old_hits': int(races.old_hit.sum()),
              'new_hits': int(races.new_hit.sum()), 'changed': int(races.changed.sum()),
              'gains': int(races.hit_delta.eq(1).sum()), 'losses': int(races.hit_delta.eq(-1).sum()),
              'changed_ties': int((races.changed & races.hit_delta.eq(0)).sum()),
              'by_year': by_year, 'independent_date_bootstrap': cis,
              'all_old_columns_unchanged': True, 'stable_argmax_verified': True,
              'baseline_sha256': OLD_SHA, 'candidate_sha256': current_hash,
              'fit_sha256': digest(fit_path), 'probability_map_max_errors': map_errors,
              'recorded_h1_fits': fit['h1_fit_count'], 'recorded_h2_fits': fit['h2_candidate_map_count'],
              'training_runs': 0, 'database_access': False}
    assert digest(path) == current_hash and digest(OLD) == OLD_SHA
    output = STUDY / 'ROOT_METRICS_REVIEW.json'
    with output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
