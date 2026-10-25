"""Independent, outcome-free reconstruction of frozen relationship probabilities."""
from pathlib import Path
from itertools import combinations
import hashlib
import json
import math

import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet'
FEATURES = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
OLD = ROOT / 'jeju/research/20261010_joint_relationship_v1/outputs'
EXPECTED = {
    BASE: 'c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1',
    FEATURES: '036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f',
    OLD / 'fit_parameters.json': 'ff96e32cc4e0c991ac1326ef111a785b0e4f11b49daedc9f584be00dfe72eaeb',
    OLD / 'report/all_triples.parquet': '13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c',
}
STYLE = ['hist_s1f_relpos_mean5', 'hist_s1f_relpos_n',
         'hist_s1f_to_c4_forward_mean5', 'hist_s1f_to_c4_pair_n',
         'hist_c4_to_g1f_forward_mean5', 'hist_c4_to_g1f_pair_n']
COLS = ['score'] + STYLE
MEAN_INDICES = [1, 3, 5]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def check_sources():
    for path, expected in EXPECTED.items():
        assert digest(path) == expected, str(path)


def reconstruct(group, fold):
    n = len(group)
    raw = group[COLS].to_numpy(float)
    valid = np.isfinite(raw)
    for k in MEAN_INDICES:
        valid[:, k] &= raw[:, k + 1] > 0
    z = np.zeros_like(raw)
    for k, name in enumerate(COLS):
        stat = fold['runner_scaler'][name]
        if not stat['degenerate']:
            z[valid[:, k], k] = (raw[valid[:, k], k] - stat['mean']) / stat['sd']
    pairs = list(combinations(range(n), 2))
    phi = np.zeros((len(pairs), 11))
    for p, (i, j) in enumerate(pairs):
        phi[p, 0] = z[i, 0] * z[j, 0]
        for k in range(7):
            if k not in MEAN_INDICES or (valid[i, k] and valid[j, k]):
                phi[p, 1 + k] = abs(z[i, k] - z[j, k])
        for k, c in enumerate(MEAN_INDICES):
            phi[p, 8 + k] = float(not (valid[i, c] and valid[j, c]))
    degree = np.zeros((n, 11))
    for p, (i, j) in enumerate(pairs):
        degree[i] += phi[p]
        degree[j] += phi[p]
    unary = (degree - phi.sum(axis=0) / (n - 1)) / (n - 2)
    residual = np.array([phi[p] - unary[i] - unary[j] for p, (i, j) in enumerate(pairs)])
    rho = np.array(fold['pair_rms'])
    normalized = np.zeros_like(residual)
    active = rho > 1e-12
    normalized[:, active] = residual[:, active] / rho[active]
    normalized[:, np.max(np.abs(normalized), axis=0) <= 1e-12] = 0
    pair_lookup = {pair: normalized[p] for p, pair in enumerate(pairs)}
    triples = list(combinations(range(n), 3))
    # Match the saved energy's stated floating-point summation contract.
    energy = np.sort(raw[:, 0][np.array(triples)], axis=1).sum(axis=1)
    x = np.array([pair_lookup[(i, j)] + pair_lookup[(i, k)] + pair_lookup[(j, k)]
                  for i, j, k in triples])
    relation = x @ np.array(fold['beta'])
    probabilities = {}
    for arm, e, tau in [('candidate', energy + relation, fold['candidate_tau']['tau']),
                        ('matched_baseline', energy, fold['baseline_tau']['tau'])]:
        scaled = e / tau
        probabilities[arm] = np.exp(scaled - logsumexp(scaled))
    numbers = group.horse_number.to_numpy(int)
    keys = [','.join(str(numbers[i]) for i in t) for t in triples]
    return keys, probabilities


def main():
    check_sources()
    base = pd.read_parquet(BASE, columns=['api_record_id', 'race_id', 'year', 'horse_number', 'score'])
    features = pd.read_parquet(FEATURES, columns=['api_record_id'] + STYLE)
    frame = base.merge(features, on='api_record_id', validate='one_to_one')
    assert len(frame) == 17412 and frame.race_id.nunique() == 1779
    params = json.loads((OLD / 'fit_parameters.json').read_text())
    folds = {f['evaluation_year']: f for f in params['folds']}
    for f in folds.values():
        d = {k: pd.Timestamp(v) for k, v in f['dates'].items()}
        gap = pd.Timedelta(days=2)
        assert d['refit_max'] <= d['h1_min'] - gap
        assert d['h1_max'] <= d['h2_min'] - gap
        assert d['h2_max'] <= d['evaluation_min'] - gap
    saved = pd.read_parquet(OLD / 'report/all_triples.parquet',
                            columns=['race_id', 'arm', 'triple_numbers', 'probability'])
    saved_groups = {(r, a): g.set_index('triple_numbers').probability
                    for (r, a), g in saved.groupby(['race_id', 'arm'], sort=False)}
    max_error = {'candidate': 0.0, 'matched_baseline': 0.0}
    max_mass_error = 0.0
    counts = {a: 0 for a in max_error}
    for race_id, g in frame.groupby('race_id', sort=True):
        g = g.sort_values('horse_number')
        keys, probs = reconstruct(g, folds[int(g.year.iloc[0])])
        for arm, q in probs.items():
            old = saved_groups[(race_id, arm)]
            assert len(old) == len(keys) == len(set(keys))
            assert set(old.index) == set(keys)
            diff = float(np.max(np.abs(q - old.loc[keys].to_numpy())))
            max_error[arm] = max(max_error[arm], diff)
            max_mass_error = max(max_mass_error, abs(math.fsum(q) - 1))
            counts[arm] += len(q)
    assert max(max_error.values()) < 1e-12
    assert max_mass_error < 1e-12
    check_sources()
    result = dict(passed=True, outcome_labels_read=False, independent_formula=True,
                  new_fits=0, races=1779, probabilities_checked=counts,
                  max_abs_q_error=max_error, max_mass_error=max_mass_error,
                  temporal_gap_checks_passed=True,
                  sources={str(p.relative_to(ROOT)): h for p, h in EXPECTED.items()})
    with (HERE / 'ROOT_Q_RECONSTRUCTION.json').open('x') as f:
        json.dump(result, f, indent=2); f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
