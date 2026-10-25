"""Independent source, candidate, temporal, model and ticket checks."""
import ast
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

import run as e


def main():
    e.check()
    for path in e.HERE.glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
    p = pd.read_parquet(e.PRIOR / 'outputs/base_predictions.parquet')
    d = pd.read_parquet(e.OUT / 'candidate_frame.parquet')
    scores = pd.read_parquet(e.OUT / 'candidate_predictions.parquet')
    selected = pd.read_parquet(e.OUT / 'selected_axes.parquet')
    rr = pd.read_parquet(e.OUT / 'race_metrics.parquet')
    contract = json.loads((e.OUT / 'feature_contract.json').read_text())
    assert len(contract['numeric']) == 61 and len(contract['categorical']) == 2
    assert len(set(contract['numeric'] + contract['categorical'])) == 63
    assert not any('outcome' in c or 'actual_' in c for c in contract['numeric'] + contract['categorical'])
    assert d.race_key.nunique() == 10770 and len(d) == len(p) // 2 - 10770
    assert len(scores) == 2 * (50754 - 4799) and len(selected) == 4799 * 4
    assert len(rr) == 4799 * 7
    assert not d.duplicated(e.KEY).any()
    assert not scores.duplicated(['model_kind'] + e.KEY).any()
    base = p[p.variant.eq('combined122')]
    fieldcounts = base.groupby('race_key').size()
    actualcounts = d.groupby('race_key').size()
    np.testing.assert_array_equal(actualcounts.sort_index(), (fieldcounts - 1).sort_index())
    np.testing.assert_allclose(d.groupby('race_key').case_weight.sum(), 1, atol=1e-12, rtol=0)
    np.testing.assert_allclose(d.case_weight, 1 / (d.race_key.map(fieldcounts) - 1), atol=1e-12, rtol=0)
    labels = base.set_index(e.KEY).outcome
    candlabels = labels.reindex(pd.MultiIndex.from_frame(d[e.KEY]))
    reflabels = labels.reindex(pd.MultiIndex.from_arrays([d.race_key, d.ref_program_no, d.ref_horse_id]))
    np.testing.assert_array_equal(candlabels, d.candidate_outcome)
    np.testing.assert_array_equal(reflabels, d.ref_outcome)
    np.testing.assert_array_equal(candlabels.between(1, 3).to_numpy().astype(int)
                                 - reflabels.between(1, 3).to_numpy().astype(int), d.switch_outcome)
    f = e.load_features()
    index = f.set_index(e.KEY)
    for side in ['ref', 'candidate']:
        ix = pd.MultiIndex.from_arrays([d.race_key, d.ref_program_no, d.ref_horse_id]) if side == 'ref' else pd.MultiIndex.from_frame(d[e.KEY])
        source = index.loc[ix]
        for name in e.HORSE:
            np.testing.assert_allclose(d[side + '_' + name], source[name], atol=1e-12, rtol=0, equal_nan=True)
    for name in e.HORSE:
        np.testing.assert_allclose(d['delta_' + name], d['candidate_' + name] - d['ref_' + name],
                                   atol=1e-12, rtol=0, equal_nan=True)
    rebuilt, rebuilt_contract = e.build_candidates(f, p.drop(columns='outcome'))
    pd.testing.assert_frame_equal(rebuilt, d[rebuilt.columns])
    assert rebuilt_contract == contract
    dirty = p.copy()
    dirty['outcome'] = np.random.default_rng(53).permutation(dirty.outcome.to_numpy())
    changed, _ = e.build_candidates(f, dirty.drop(columns='outcome'))
    pd.testing.assert_frame_equal(rebuilt, changed)
    try:
        e.build_candidates(f, p)
    except AssertionError:
        pass
    else:
        raise AssertionError('candidate API accepted current outcomes')
    replays = []
    rawf = pd.read_parquet(e.FEATURES).set_index(e.KEY)
    # Recheck every reused base model against the underlying frozen runner inputs.
    for variant, stem, parent in [('baseline103', 'full103', e.S.B), ('combined122', 'combined122', e.S.P)]:
        for meet in [1, 3]:
            for year in range(2020, 2027):
                folder = (e.PRIOR / 'outputs/past_models' / f'{variant}_{meet}_{year}' if year < 2024
                          else parent / 'models' / f'{stem}_{meet}_{year}')
                meta = json.loads((folder / 'metadata.json').read_text())
                model = lgb.Booster(model_file=str(folder / 'model.txt'))
                z = p[p.variant.eq(variant) & p.meet.eq(meet) & p.year.eq(year)]
                x = rawf.loc[pd.MultiIndex.from_frame(z[e.KEY]), meta['features']].copy()
                for col, vocabulary in meta['category_vocabulary'].items():
                    x[col] = pd.Categorical(x[col], categories=vocabulary)
                prediction = model.predict(x, raw_score=True, num_threads=1)
                error = float(np.abs(prediction - z.raw_score.to_numpy()).max())
                assert error < 1e-10
                assert meta['validation_year'] == year - 2 and meta['calibration_year'] == year - 1
                assert pd.Timestamp(meta['train_end']) < pd.Timestamp(year=year-1, month=1, day=1)
                assert meta['training_min'] == '2017-01-01'
                assert e.sha(folder / 'model.txt') == meta['model_sha256']
                replays.append(dict(kind='frozen_ability', variant=variant, meet=meet, year=year, max_error=error))
    forbidden = ['candidate_outcome', 'ref_outcome', 'switch_outcome']
    encoded = []
    for year in [2024, 2025, 2026]:
        train = d[d.year.between(2020, year - 1)]
        test = d[d.year.eq(year)]
        clean = test.drop(columns=forbidden)
        for kind in ['gain_logit', 'gain_tree']:
            folder = e.OUT / 'models' / f'{kind}_{year}'
            pre = json.loads((folder / 'preprocess.json').read_text())
            meta = json.loads((folder / 'metadata.json').read_text())
            assert pre == e.S.fit_preprocess(train, contract)
            assert pd.Timestamp(pre['training_max']) < pd.Timestamp(year=year, month=1, day=1)
            assert len(train) == meta['training_pairs'] == pre['training_rows']
            assert train.race_key.nunique() == meta['training_races']
            assert e.sha(folder / 'preprocess.json') == meta['preprocess_sha256']
            assert e.sha(folder / ('model.json' if kind == 'gain_logit' else 'model.txt')) == meta['model_sha256']
            probability = e.predict(clean, folder, kind)
            stored = scores[scores.model_kind.eq(kind) & scores.year.eq(year)].set_index(e.KEY).loc[pd.MultiIndex.from_frame(test[e.KEY])]
            np.testing.assert_allclose(probability, stored[['p_loss', 'p_neutral', 'p_gain']], atol=1e-12, rtol=0)
            np.testing.assert_allclose(probability.sum(axis=1), 1, atol=1e-12, rtol=0)
            np.testing.assert_allclose(stored.expected_gain, probability[:, 2] - probability[:, 0], atol=1e-12, rtol=0)
            assert ((probability >= 0) & (probability <= 1)).all()
            try:
                e.predict(test, folder, kind)
            except AssertionError:
                pass
            else:
                raise AssertionError('prediction API accepted labels')
            if kind == 'gain_logit':
                w = json.loads((folder / 'model.json').read_text())
                x, names = e.S.transform(train, pre)
                native = LogisticRegression(C=.1, solver='lbfgs', max_iter=2000)
                native.fit(x, train.switch_outcome, sample_weight=train.case_weight)
                np.testing.assert_allclose(native.coef_, w['coef'], atol=1e-10, rtol=0)
                np.testing.assert_allclose(native.intercept_, w['intercept'], atol=1e-10, rtol=0)
                tx, _ = e.S.transform(clean, pre)
                np.testing.assert_allclose(native.predict_proba(tx), probability, atol=1e-12, rtol=0)
                encoded.append(len(names))
            replays.append(dict(kind='new_selector', variant=kind, year=year,
                                max_error=float(np.abs(probability - stored[['p_loss', 'p_neutral', 'p_gain']].to_numpy()).max())))
            for scope in ['two', 'all']:
                q = scores[scores.model_kind.eq(kind) & scores.year.eq(year)]
                chosen = e.choose(q, p[p.year.eq(year)].drop(columns='outcome'), scope)
                shuffled = e.choose(q.sample(frac=1, random_state=53), p[p.year.eq(year)].drop(columns='outcome'), scope)
                pd.testing.assert_frame_equal(chosen, shuffled)
                actual = selected[selected.variant.eq(kind + '_' + scope) & selected.year.eq(year)].drop(columns='variant')
                pd.testing.assert_frame_equal(chosen, actual.reset_index(drop=True))
                assert chosen.expected_gain.ge(0).all()
                if scope == 'two':
                    assert not chosen.is_third.any()
    # Independent enumeration of reference zero and every alternative's stored gain.
    all_lookup = {rid: g.sort_values(['raw_score', 'program_no'], ascending=[False, True])
                  for rid, g in base[base.year.ge(2024)].groupby('race_key')}
    checks = 0
    for kind in ['gain_logit', 'gain_tree']:
        lookup = {rid: g for rid, g in scores[scores.model_kind.eq(kind)].groupby('race_key')}
        for scope in ['two', 'all']:
            z = rr[rr.variant.eq(kind + '_' + scope)].set_index('race_key')
            for rid, g in all_lookup.items():
                alternatives = lookup[rid]
                if scope == 'two':
                    alternatives = alternatives[~alternatives.is_third]
                rank = {int(n): k for k, n in enumerate(g.program_no, 1)}
                refno = int(g.program_no.iloc[0])
                options = [(0.0, 1, 1, refno)] + [(float(x.expected_gain), 0, rank[int(x.program_no)], int(x.program_no)) for x in alternatives.itertuples()]
                axis = sorted(options, key=lambda x: (-x[0], -x[1], x[2], x[3]))[0][3]
                remaining = [int(n) for n in g.program_no if n != axis]
                truth = dict(zip(g.program_no, g.outcome))
                winner = {int(n) for n, k in truth.items() if 1 <= k <= 2}
                result = [int(1 <= truth[axis] <= 3), int(1 <= truth[axis] <= 2), int(truth[axis] == 1),
                          int(winner == {axis, remaining[0]}), int(any(winner == {axis, n} for n in remaining[:3]))]
                row = z.loc[rid]
                assert row.axis_program_no == axis
                np.testing.assert_array_equal(result, row[e.METRICS].to_numpy(dtype=int))
                checks += 1
    prior = pd.read_parquet(e.PRIOR / 'outputs/race_metrics.parquet')
    for v in ['frozen103', 'frozen122', 'joint_logit']:
        a = rr[rr.variant.eq(v)].set_index('race_key').sort_index()
        b = prior[prior.variant.eq(v)].set_index('race_key').sort_index()
        pd.testing.assert_frame_equal(a[b.columns], b, check_dtype=False)
    metrics = pd.read_csv(e.OUT / 'metrics.csv', dtype={'period': str})
    differences = pd.read_csv(e.OUT / 'paired_differences.csv', dtype={'period': str})
    for v, z in rr.groupby('variant'):
        for period, g in e.windows(z):
            row = metrics[metrics.variant.eq(v) & metrics.period.eq(period)].iloc[0]
            assert row.n == len(g)
            np.testing.assert_allclose(row[e.METRICS].to_numpy(float), g[e.METRICS].mean(), atol=1e-14, rtol=0)
    for row in differences.itertuples():
        a = rr[rr.variant.eq(row.variant)].set_index('race_key')
        b = rr[rr.variant.eq(row.reference)].set_index('race_key')
        g = dict(e.windows(a))[row.period]
        delta = g[row.metric] - b.loc[g.index, row.metric]
        assert row.net == delta.sum() and row.gain == delta.eq(1).sum() and row.loss == delta.eq(-1).sum()
        assert np.isclose(row.difference_pp, delta.mean() * 100)
        day = g[['race_date']].assign(delta=delta).groupby('race_date').delta.agg(['sum', 'size'])
        rng = np.random.default_rng(20261014)
        idx = rng.integers(len(day), size=(2000, len(day)))
        draws = day['sum'].to_numpy()[idx].sum(axis=1) / day['size'].to_numpy()[idx].sum(axis=1)
        np.testing.assert_allclose([row.lo_pp, row.hi_pp], np.quantile(draws, [.025, .975]) * 100, atol=1e-12, rtol=0)
    diagnostics = pd.read_parquet(e.OUT / 'selection_diagnostics.parquet')
    origins = prior[prior.variant.isin(['frozen103', 'frozen122'])].pivot(index='race_key', columns='variant', values='axis_horse_id')
    sourcehits = prior[prior.variant.isin(['frozen103', 'frozen122'])].pivot(index='race_key', columns='variant', values='axis_top3')
    third = (~diagnostics.axis_horse_id.eq(diagnostics.race_key.map(origins.frozen103))
             & ~diagnostics.axis_horse_id.eq(diagnostics.race_key.map(origins.frozen122)))
    np.testing.assert_array_equal(third, diagnostics.is_third)
    both = diagnostics.race_key.map(sourcehits.frozen103).eq(0) & diagnostics.race_key.map(sourcehits.frozen122).eq(0)
    np.testing.assert_array_equal(both, diagnostics.both_original_miss)
    e.save(e.OUT / 'model_replay.json', dict(models=replays, reused_ability=28, new_selector=6))
    e.save(e.OUT / 'verification.json', dict(status='verified', source_hashes=len(json.loads((e.OUT / 'input_manifest.json').read_text())),
         candidate_races=10770, candidate_pairs=len(d), evaluation_races=4799, evaluation_runners=50754,
         raw_features=63, encoded_features=encoded, all_candidates_included=True, equal_race_weight=True,
         new_selector_models=6, reused_ability_models=28, independent_race_checks=checks,
         model_max_error=max(x['max_error'] for x in replays), logistic_refit_exact=True,
         outcome_rejection_and_permutation_invariant=True, row_permutation_invariant=True,
         temporal_oof_and_preprocessing_verified=True, original_metrics_exact=True,
         all_paired_bootstraps_reproduced=True, horse_probabilities_changed=False,
         production_changed=False, selected22_changed=False, future_contract_changed=False,
         database_access=False, network_access=False, jeju_access=False))
    e.check()
    print((e.OUT / 'verification.json').read_text())


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
