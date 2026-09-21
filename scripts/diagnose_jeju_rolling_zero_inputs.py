"""Descriptive input/TreeSHAP audit; no additional fit or candidate selection."""
import pickle
import numpy as np
import polars as pl
from scipy.special import logit
from scripts.run_jeju_rolling_zero import OUT, DATA, OLD, ANN, load_frame, save


def main():
    scores = pl.read_parquet(OUT / 'frozen_probabilities.parquet')
    h = pl.read_parquet(OUT / 'horse_predictions.parquet').filter(pl.col('model') == 'BASE').select('entry_id', 'y', 'boundary_tie')
    features = load_frame().select('entry_id', 'global_elo_pre', 'distance_elo_pre', 'elo_uncertainty_pre', 'rival_global_elo_gap', 'trial_count_pre', 'trial_observed_any', 'trial_coverage_unknown', 'trial_last_valid_time_ms_pre')
    d = scores.join(features, on='entry_id', validate='1:1').join(h, on='entry_id', validate='1:1')
    experienced = d.filter(pl.col('starts_pre') > 0).group_by('race_id').agg(pl.col('global_elo_pre').mean().alias('experienced_elo_mean'))
    d = d.join(experienced, on='race_id', validate='m:1').with_columns((pl.col('global_elo_pre')-pl.col('experienced_elo_mean')).alias('gap_to_experienced_mean'))
    d.write_parquet(OUT / 'input_diagnostic_rows.parquet')
    groups, defaults, shap, use = [], [], [], []
    for year in [2024, 2025, 2026, 'ALL']:
        f = d if year == 'ALL' else d.filter(pl.col('year') == year)
        z = f.filter(pl.col('starts_pre') == 0)
        valid = z.filter(~pl.col('boundary_tie'))
        defaults.append(dict(year=year, rows=len(z), global_elo_values=z['global_elo_pre'].unique().to_list(), distance_elo_values=z['distance_elo_pre'].unique().to_list(), uncertainty_values=z['elo_uncertainty_pre'].unique().to_list(), rival_elo_gap_mean=z['rival_global_elo_gap'].mean(), rival_elo_gap_median=z['rival_global_elo_gap'].median(), positive_rival_gap=int((z['rival_global_elo_gap'] > 0).sum()), trial_observed=int(z['trial_observed_any'].sum()), valid_trial_time=int(z['trial_last_valid_time_ms_pre'].is_not_null().sum()), trial_coverage_unknown=int(z['trial_coverage_unknown'].sum())))
        defaults[-1].update(gap_to_experienced_mean=z['gap_to_experienced_mean'].mean(), above_experienced_mean=int((z['gap_to_experienced_mean'] > 0).sum()))
        for observed in [False, True]:
            sub = valid.filter(pl.col('trial_last_valid_time_ms_pre').is_not_null() == observed)
            if len(sub):
                groups.append(dict(year=year, valid_trial_time=observed, rows=len(sub), actual=sub['y'].mean(), base=sub['p_BASE'].mean(), q4_zero=sub['p_Q4_ZERO'].mean(), oof_zero=sub['p_OOF_ZERO'].mean(), trial_time_min=sub['trial_last_valid_time_ms_pre'].min(), trial_time_max=sub['trial_last_valid_time_ms_pre'].max()))
    frame = load_frame()
    for year in [2024, 2025, 2026]:
        bundle = pickle.loads((OLD / 'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())['rank_bundle'] if year == 2026 else pickle.loads((ANN / f'bundles/{year}__BASE.pkl').read_bytes())
        races = scores.filter((pl.col('year') == year) & (pl.col('starts_pre') == 0)).select('race_id').unique()
        f = frame.join(races, on='race_id', how='semi').sort('race_id', 'horse_id')
        pre, models = bundle['preprocessor'], bundle['models']
        x = pre.transform(f)
        contrib = np.mean([m.predict(x, pred_contrib=True) for m in models], axis=0)
        raw = np.mean([m.predict(x, raw_score=True) for m in models], axis=0)
        np.testing.assert_allclose(contrib.sum(axis=1), raw, atol=1e-10)
        family = {'own_elo': [n for n in pre.names if n.split('__')[0] in ['global_elo_pre', 'distance_elo_pre', 'elo_uncertainty_pre']], 'rival_elo': [n for n in pre.names if 'rival_' in n and 'elo' in n], 'trial': [n for n in pre.names if n.startswith('trial_')]}
        z = f['starts_pre'].to_numpy() == 0
        for name, names in family.items():
            ix = [pre.names.index(n) for n in names]
            vals = contrib[:, ix].sum(axis=1)
            for iszero in [False, True]:
                a = vals[z == iszero]
                shap.append(dict(year=year, family=name, zero=iszero, rows=len(a), mean_signed_raw_score=float(a.mean()), mean_absolute_raw_score=float(np.abs(a).mean()), features=names))
        splits = sum(m.booster_.feature_importance(importance_type='split') for m in models)
        gains = sum(m.booster_.feature_importance(importance_type='gain') for m in models)
        for i, name in enumerate(pre.names):
            if name.startswith('trial_'):
                source = name.split('__')[0]
                use.append(dict(year=year, feature=name, splits=int(splits[i]), gain=float(gains[i]), fitted_median=float(pre.medians[pre.numeric.index(source)])))
    save('input_diagnostics.json', dict(defaults=defaults, trial_groups=groups, tree_contribution=shap, trial_model_use=use, interpretation='Associations and model explanations, not causal effects. Tree contributions are on raw ranking score, not probability. Only races containing a zero-history runner are used for contributions.'))
    # Post-result diagnostic of the already-frozen penalty; no refit or tuning.
    pool = pl.read_parquet(OUT / 'frozen_oof_probabilities.parquet').join(pl.read_parquet(DATA / 'labels.parquet').select('entry_id', 'label_top3'), on='entry_id', validate='1:1').join(pl.read_parquet(DATA / 'races.parquet').select('race_id', 'boundary_tie'), on='race_id', validate='m:1').filter(~pl.col('boundary_tie'))
    shrinkage = []
    for year in [2024, 2025, 2026]:
        f = pool.filter(pl.col('event_date').dt.year() == year-1)
        c = pickle.loads((OUT / f'bundles/{year}__CAL.pkl').read_bytes())['zero_cal']
        z, y, w = f['starts_pre'].to_numpy() == 0, f['label_top3'].to_numpy(), 1/f['field_size'].to_numpy()
        p = c.predict(logit(np.clip(f['p'].to_numpy(), 1e-8, 1-1e-8)), z.astype(int))
        share = w[z].sum()/w.sum()
        residual = np.average(p[z]-y[z], weights=w[z])
        implied = -.01*c.params_[2]/share
        assert abs(residual-implied) < 1e-6
        shrinkage.append(dict(year=year, zero_weight_share=float(share), weighted_zero_prediction=float(np.average(p[z], weights=w[z])), weighted_zero_actual=float(np.average(y[z], weights=w[z])), weighted_zero_bias=float(residual), penalty_implied_bias=float(implied)))
    save('calibration_shrinkage_diagnostic.json', shrinkage)
    print(defaults, flush=True)
    print(groups, flush=True)


if __name__ == '__main__':
    main()
