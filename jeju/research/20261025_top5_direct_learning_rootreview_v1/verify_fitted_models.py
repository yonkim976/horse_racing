"""Independent reconstruction of train-only preprocessing and final head gradients.

Imports no implementation from the trained selector and performs no model fits.
"""
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
STUDY = HERE.parent / '20261025_top5_direct_learning_v1'
FEATURES = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
COUNTS = ['observed_starts', 'same_starts', 'same_valid_times',
          'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n']
MEANS = ['hist_s1f_relpos_mean5', 'hist_s1f_to_c4_forward_mean5', 'hist_c4_to_g1f_forward_mean5']
FEATURE_NAMES = ['log_observed_starts', 'log_same_starts', 'log_same_valid_times',
                 'mean5_rank_fraction', 'mean5_rank_fraction_missing',
                 'hist_s1f_relpos_mean5', 'log_hist_s1f_relpos_n',
                 'hist_s1f_to_c4_forward_mean5', 'log_hist_s1f_to_c4_pair_n',
                 'hist_c4_to_g1f_forward_mean5', 'log_hist_c4_to_g1f_pair_n']


def h(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def raw_inputs(f):
    logs = {n: np.log1p(f[n].to_numpy(float)) for n in COUNTS}
    rank = f.mean5_rank_fraction.to_numpy(float)
    return np.column_stack([logs[COUNTS[0]], logs[COUNTS[1]], logs[COUNTS[2]],
                            rank, np.isnan(rank).astype(float),
                            f[MEANS[0]], logs[COUNTS[3]], f[MEANS[1]], logs[COUNTS[4]],
                            f[MEANS[2]], logs[COUNTS[5]]]).astype(float)


def main():
    audit = json.loads((HERE / 'ROOT_SOURCE_AUDIT.json').read_text())
    fit_receipt = json.loads((STUDY / 'outputs/FIT_RECEIPT.json').read_text())
    assert fit_receipt['fit_count'] == 3
    assert h(FEATURES) == audit['features_sha256']
    results = []
    for year in [2024, 2025, 2026]:
        model_path = STUDY / 'outputs' / f'model_{year}.json'
        model = json.loads(model_path.read_text())
        assert h(model_path) == fit_receipt['model_artifacts'][model_path.name]['sha256']
        assert model['evaluation_year'] == year and model['feature_names'] == FEATURE_NAMES
        assert model['lambda'] == 1 and model['training_label_max_year'] == year - 1
        cols = ['api_record_id', 'race_id', 'race_date', 'year', 'horse_id', 'horse_number',
                'field_n', 'finish_position', 'mean5_rank_fraction'] + COUNTS + MEANS
        train = pd.read_parquet(FEATURES, columns=cols,
                                filters=[('year', '>=', 2019), ('year', '<', year)])
        assert train.year.min() == 2019 and train.year.max() == year - 1
        providers = [p for p in audit['training_score_providers'] if p['year'] < year]
        scores = []
        for p in providers:
            path = ROOT / p['score_path']
            assert h(path) == p['score_sha256']
            scores.append(pd.read_parquet(path, columns=['api_record_id', 'score']))
        train = train.merge(pd.concat(scores, ignore_index=True), on='api_record_id', validate='one_to_one')
        assert len(train) == model['training_rows']
        assert train.race_id.nunique() == model['training_races'] == audit['fold_training_races'][str(year)]
        raw = raw_inputs(train)
        mu = np.nanmean(raw, axis=0)
        sd = np.nanstd(raw, axis=0, ddof=0)
        sd[sd == 0] = 1
        max_mean_error = float(np.max(np.abs(mu - model['feature_means'])))
        max_scale_error = float(np.max(np.abs(sd - model['feature_scales'])))
        assert max_mean_error < 1e-11 and max_scale_error < 1e-11
        # Use independently computed statistics for the gradient reconstruction.
        x = np.where(np.isfinite(raw), (raw - mu) / sd, 0)
        beta = np.array(model['beta'])
        loss = initial_loss = 0.0
        grad = np.zeros(11)
        positive_count = candidate_count = races = 0
        for _, group in train.groupby('race_id', sort=True):
            rows = group.sort_values('horse_number')
            n = len(rows)
            assert n == int(rows.field_n.iloc[0])
            assert len(set(rows.horse_id)) == n
            positions = rows.finish_position.to_numpy(int)
            assert np.array_equal(np.sort(positions), np.arange(1, n + 1))
            combo = np.array(list(combinations(range(n), 5)))
            good = (positions[combo] <= 3).sum(axis=1) == 3
            assert good.sum() == math.comb(n - 3, 2)
            score = rows.score.to_numpy(float)
            z = np.zeros(n) if score.std(ddof=0) == 0 else (score - score.mean()) / score.std(ddof=0)
            prior = z[combo].sum(axis=1)
            phi = x[rows.index.to_numpy()][combo].sum(axis=1)
            energy = prior + phi @ beta
            za, zg = logsumexp(energy), logsumexp(energy[good])
            loss += za - zg
            initial_loss += logsumexp(prior) - logsumexp(prior[good])
            grad += np.exp(energy - za) @ phi - np.exp(energy[good] - zg) @ phi[good]
            races += 1; candidate_count += len(combo); positive_count += int(good.sum())
        loss = loss / races + beta @ beta / 2
        initial_loss /= races
        grad = grad / races + beta
        assert np.isfinite(beta).all() and np.isfinite(grad).all()
        assert np.max(np.abs(grad)) <= 1e-6
        assert abs(loss - model['fit_diagnostics']['objective_value']) < 1e-10
        assert loss <= initial_loss + 1e-12
        assert candidate_count == model['candidate_sets'] and positive_count == model['positive_sets']
        results.append(dict(year=year, rows=len(train), races=races, model_sha256=h(model_path),
                            training_max_date=str(train.race_date.max()),
                            max_mean_error=max_mean_error, max_scale_error=max_scale_error,
                            independent_objective=float(loss), initial_objective=float(initial_loss),
                            independent_gradient_max_abs=float(np.max(np.abs(grad))),
                            objective_error=abs(float(loss) - model['fit_diagnostics']['objective_value']),
                            candidate_sets=candidate_count, positive_sets=positive_count))
    result = dict(passed=True, new_fit_calls=0, independent_code=True,
                  target_fold_evaluation_labels_read=False,
                  earlier_year_labels_read_only_as_later_fold_training=True,
                  fit_receipt_sha256=h(STUDY / 'outputs/FIT_RECEIPT.json'), folds=results)
    with (HERE / 'ROOT_FITTED_MODEL_AUDIT.json').open('x') as f:
        json.dump(result, f, indent=2); f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
