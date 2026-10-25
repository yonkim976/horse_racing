"""Prior-only gain/loss learning over every possible alternative anchor."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PRIOR = R / '20261013_axis_switch_learning_v1'
FEATURES = R / '20261012_full103_retention_v1/outputs/features.parquet'
KEY = ['race_key', 'program_no', 'horse_id']
METRICS = ['axis_top3', 'axis_top2', 'axis_win', 'quinella_one', 'axis_next3']
HORSE = ['keep_fast_g3', 'keep_fast_g1', 'keep_fast_n', 'keep_fast_keep',
         'moist_last3_record_index_mean', 'profile_count3', 'profile_trend',
         'record_field_adv', 'front_gate_probability', 'gate_fraction',
         'history_count', 'days_since_last']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


S = module('frozen_switch_preprocess', PRIOR / 'run.py')


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = {ROOT / p for p in json.loads((PRIOR / 'outputs/input_manifest.json').read_text())}
    paths.update([HERE / 'PLAN.md', HERE / 'run.py', PRIOR / 'run.py',
                  PRIOR / 'outputs/input_manifest.json', PRIOR / 'outputs/verification.json',
                  PRIOR / 'outputs/base_predictions.parquet', PRIOR / 'outputs/race_metrics.parquet',
                  PRIOR / 'outputs/selector_predictions.parquet', FEATURES])
    for folder in ['past_models', 'selector_models']:
        paths.update(p for p in (PRIOR / 'outputs' / folder).rglob('*')
                     if p.is_file() and p.suffix in ['.json', '.txt'])
    target = OUT / 'input_manifest.json'
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    if target.exists():
        assert json.loads(target.read_text()) == manifest
    else:
        save(target, manifest)
    before = OUT / 'publication_before.json'
    if not before.exists():
        files = [R / p for p in ['README.md', 'ARTIFACT_SIZE_LOG.md',
                 'conclusions/README.md', 'conclusions/SOURCES.md', 'conclusions/source_manifest.json']]
        save(before, {str(p.relative_to(ROOT)): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files})
        snap = OUT / 'publication_before'
        snap.mkdir()
        for p in files:
            (snap / str(p.relative_to(R)).replace('/', '__')).write_bytes(p.read_bytes())


def check():
    for path, digest in json.loads((OUT / 'input_manifest.json').read_text()).items():
        assert sha(ROOT / path) == digest, path


def load_features():
    columns = KEY + ['race_date', 'year', 'meet', 'distance_m', 'grade', 'grade_kind',
                    'field_size', 'dirgate_inner_n'] + [c for c in HORSE if c not in ['gate_fraction', 'record_field_adv']]
    f = pd.read_parquet(FEATURES, columns=columns)
    f['gate_fraction'] = f.dirgate_inner_n / (f.field_size - 1)
    f['record_field_adv'] = (f.moist_last3_record_index_mean
                            - f.groupby('race_key').moist_last3_record_index_mean.transform('mean'))
    return f


def build_candidates(f, p):
    """Serving-safe; no current outcome may enter the builder."""
    assert not {'outcome', 'switch_outcome', 'ref_outcome', 'candidate_outcome'}.intersection(f.columns)
    assert 'outcome' not in p and not any(c.startswith('actual_') for c in f)
    q = p[p.variant.eq('combined122')].merge(f, on=KEY, validate='one_to_one',
           suffixes=('_base', ''))
    for c in ['race_date', 'year', 'meet']:
        np.testing.assert_array_equal(q[c].to_numpy(), q[c + '_base'].to_numpy())
        q = q.drop(columns=c + '_base')
    a = p[p.variant.eq('baseline103')][KEY + ['model_rank', 'target_probability']]
    q = q.merge(a, on=KEY, suffixes=('_122', '_103'), validate='one_to_one')
    refs = q[q.model_rank_122.eq(1)].copy()
    axis103 = p[p.variant.eq('baseline103') & p.model_rank.eq(1)].set_index('race_key').horse_id
    q['axis103_horse_id'] = q.race_key.map(axis103)
    q['axis122_horse_id'] = q.race_key.map(refs.set_index('race_key').horse_id)
    refcols = HORSE + ['program_no', 'horse_id', 'target_probability_103',
                      'target_probability_122', 'model_rank_103', 'model_rank_122']
    d = q.merge(refs[['race_key'] + refcols].rename(columns={c: 'ref_' + c for c in refcols}),
                on='race_key', validate='many_to_one')
    d = d[d.horse_id.ne(d.ref_horse_id)].copy()
    numeric = []
    for c in HORSE:
        d['candidate_' + c] = d[c]
        d['delta_' + c] = d[c] - d['ref_' + c]
        numeric += ['ref_' + c, 'candidate_' + c, 'delta_' + c]
    numeric += ['distance_m', 'grade', 'field_size']
    for model in ['103', '122']:
        name = 'target_probability_' + model
        d['candidate_' + name] = d[name]
        d['delta_' + name] = d[name] - d['ref_' + name]
        numeric += ['ref_' + name, 'candidate_' + name, 'delta_' + name]
        rank = 'model_rank_' + model
        d['candidate_' + rank] = d[rank]
        numeric += ['ref_' + rank, 'candidate_' + rank]
    for section in ['g3', 'g1']:
        for context in ['support', 'recent']:
            name = section + '_x_' + context
            for side in ['ref', 'candidate']:
                multiplier = d[side + '_keep_fast_n'] / 5 if context == 'support' else d[side + '_record_field_adv']
                d[side + '_' + name] = d[side + '_keep_fast_' + section] * multiplier
            d['delta_' + name] = d['candidate_' + name] - d['ref_' + name]
            numeric += ['ref_' + name, 'candidate_' + name, 'delta_' + name]
    categorical = ['meet', 'grade_kind']
    assert len(numeric) == 61 and len(set(numeric + categorical)) == 63
    d['is_third'] = ~d.horse_id.eq(d.axis103_horse_id)
    d['case_weight'] = 1 / d.groupby('race_key').horse_id.transform('size')
    keep = KEY + ['race_date', 'year', 'ref_program_no', 'ref_horse_id', 'axis103_horse_id',
                  'axis122_horse_id', 'is_third', 'case_weight'] + numeric + categorical
    return d[list(dict.fromkeys(keep))].sort_values(KEY).reset_index(drop=True), dict(numeric=numeric, categorical=categorical)


def prepare():
    p = pd.read_parquet(PRIOR / 'outputs/base_predictions.parquet')
    d, contract = build_candidates(load_features(), p.drop(columns='outcome'))
    labels = p[p.variant.eq('combined122')].set_index(KEY).outcome
    d['candidate_outcome'] = labels.reindex(pd.MultiIndex.from_frame(d[KEY])).to_numpy()
    index = pd.MultiIndex.from_arrays([d.race_key, d.ref_program_no, d.ref_horse_id])
    d['ref_outcome'] = labels.reindex(index).to_numpy()
    d['switch_outcome'] = (d.candidate_outcome.between(1, 3).astype(int)
                           - d.ref_outcome.between(1, 3).astype(int))
    assert d[['candidate_outcome', 'ref_outcome']].notna().all().all()
    assert np.allclose(d.groupby('race_key').case_weight.sum(), 1)
    d.to_parquet(OUT / 'candidate_frame.parquet', index=False)
    save(OUT / 'feature_contract.json', contract)
    d.groupby(['year', 'switch_outcome']).agg(cases=('horse_id', 'size'),
            race_weight=('case_weight', 'sum')).to_csv(OUT / 'candidate_label_counts.csv')
    print('Candidate frame', d.shape, flush=True)


def predict(d, folder, model_kind):
    forbidden = {'candidate_outcome', 'ref_outcome', 'switch_outcome', 'outcome'}
    assert not forbidden.intersection(d.columns)
    pre = json.loads((folder / 'preprocess.json').read_text())
    x, _ = S.transform(d, pre)
    if model_kind == 'gain_logit':
        model = json.loads((folder / 'model.json').read_text())
        assert model['classes'] == [-1, 0, 1]
        return softmax(x @ np.array(model['coef']).T + np.array(model['intercept']), axis=1)
    return lgb.Booster(model_file=str(folder / 'model.txt')).predict(x, num_threads=1)


def choose(scores, p, scope):
    """Choose without labels; reference gain is zero, never inferred."""
    assert not {'candidate_outcome', 'ref_outcome', 'switch_outcome', 'outcome'}.intersection(scores.columns)
    assert 'outcome' not in p
    candidates = scores.copy()
    if scope == 'two':
        candidates = candidates[~candidates.is_third]
    refs = p[p.variant.eq('combined122') & p.model_rank.eq(1)][KEY + ['race_date', 'year']].copy()
    refs['expected_gain'] = 0.0
    refs['is_reference'] = True
    refs['is_third'] = False
    refs['candidate_model_rank_122'] = 1
    candidates['is_reference'] = False
    a = pd.concat([refs, candidates], ignore_index=True)
    a = a.sort_values(['race_key', 'expected_gain', 'is_reference', 'candidate_model_rank_122', 'program_no'],
                     ascending=[True, False, False, True, True])
    best = a.drop_duplicates('race_key').copy()
    assert len(best) == len(refs)
    return best[KEY + ['race_date', 'year', 'expected_gain', 'is_reference', 'is_third']].reset_index(drop=True)


def learn():
    d = pd.read_parquet(OUT / 'candidate_frame.parquet')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    p = pd.read_parquet(PRIOR / 'outputs/base_predictions.parquet').drop(columns='outcome')
    scores, selections, counts = [], [], []
    forbidden = ['candidate_outcome', 'ref_outcome', 'switch_outcome']
    for year in [2024, 2025, 2026]:
        train = d[d.year.between(2020, year - 1)].copy()
        test = d[d.year.eq(year)].drop(columns=forbidden)
        pre = S.fit_preprocess(train, contract)
        x, names = S.transform(train, pre)
        counts.append(dict(year=year, training_races=train.race_key.nunique(), training_pairs=len(train),
                           training_weight=float(train.case_weight.sum()), training_max=str(train.race_date.max().date())))
        for kind in ['gain_logit', 'gain_tree']:
            folder = OUT / 'models' / f'{kind}_{year}'
            folder.mkdir(parents=True, exist_ok=True)
            save(folder / 'preprocess.json', pre)
            if kind == 'gain_logit':
                model = LogisticRegression(C=.1, solver='lbfgs', max_iter=2000)
                model.fit(x, train.switch_outcome.to_numpy(), sample_weight=train.case_weight.to_numpy())
                assert model.n_iter_.max() < 2000
                save(folder / 'model.json', dict(coef=model.coef_.tolist(), intercept=model.intercept_.tolist(),
                     classes=model.classes_.tolist(), C=.1, features=names, iterations=model.n_iter_.tolist()))
                importance = pd.DataFrame(dict(feature=names, gain_minus_loss_coefficient=model.coef_[2] - model.coef_[0]))
            else:
                params = dict(objective='multiclass', num_class=3, learning_rate=.03, num_leaves=4,
                              min_data_in_leaf=150, lambda_l2=20, seed=20261014, num_threads=1,
                              deterministic=True, force_col_wise=True, verbosity=-1)
                model = lgb.train(params, lgb.Dataset(x, label=train.switch_outcome.to_numpy() + 1,
                           weight=train.case_weight.to_numpy(), feature_name=[str(i) for i in range(len(names))]),
                           num_boost_round=80)
                model.save_model(str(folder / 'model.txt'))
                importance = pd.DataFrame(dict(feature=names, gain=model.feature_importance(importance_type='gain')))
            importance.to_csv(folder / 'importance.csv', index=False)
            probabilities = predict(test, folder, kind)
            q = test[KEY + ['race_date', 'year', 'ref_program_no', 'ref_horse_id', 'is_third', 'candidate_model_rank_122']].copy()
            q['model_kind'] = kind
            q['p_loss'], q['p_neutral'], q['p_gain'] = probabilities.T
            q['expected_gain'] = probabilities[:, 2] - probabilities[:, 0]
            scores.append(q)
            for scope in ['two', 'all']:
                selection = choose(q, p[p.year.eq(year)], scope)
                selection['variant'] = kind + '_' + scope
                selections.append(selection)
            save(folder / 'metadata.json', dict(model_kind=kind, evaluation_year=year,
                 training_years=[2020, year - 1], training_max=pre['training_max'], training_pairs=len(train),
                 training_races=int(train.race_key.nunique()), case_weight='1/(field alternatives), sum1 per race',
                 raw_features=63, encoded_features=len(names), test_labels_used=False,
                 probability_scope='conditional gain/neutral/loss versus frozen122 anchor; not horse probability',
                 model_sha256=sha(folder / ('model.json' if kind == 'gain_logit' else 'model.txt')),
                 preprocess_sha256=sha(folder / 'preprocess.json')))
            print('Trained', kind, year, 'pairs', len(train), 'races', train.race_key.nunique(), flush=True)
    pd.concat(scores, ignore_index=True).to_parquet(OUT / 'candidate_predictions.parquet', index=False)
    pd.concat(selections, ignore_index=True).to_parquet(OUT / 'selected_axes.parquet', index=False)
    pd.DataFrame(counts).to_csv(OUT / 'training_counts.csv', index=False)


def windows(d):
    yield 'all', d
    for year in [2024, 2025, 2026]:
        z = d[d.year.eq(year)]
        yield str(year), z
        yield f'{year}_to0920', z[z.race_date.dt.strftime('%m-%d').le('09-20')]


def evaluate():
    p = pd.read_parquet(PRIOR / 'outputs/base_predictions.parquet')
    selections = pd.read_parquet(OUT / 'selected_axes.parquet')
    original = pd.read_parquet(PRIOR / 'outputs/race_metrics.parquet')
    original = original[original.variant.isin(['frozen103', 'frozen122', 'joint_logit'])].copy()
    rows = []
    base = {rid: g.sort_values('model_rank') for rid, g in p[p.variant.eq('combined122') & p.year.ge(2024)].groupby('race_key')}
    context = load_features().drop_duplicates('race_key').set_index('race_key')
    for s in selections.itertuples():
        g = base[s.race_key]
        g = pd.concat([g[g.horse_id.eq(s.horse_id)], g[g.horse_id.ne(s.horse_id)]])
        truth = g.outcome.to_numpy()
        winners = set(g.loc[g.outcome.between(1, 2), 'program_no'])
        assert len(winners) == 2 and g.outcome.between(1, 3).sum() == 3
        c = context.loc[s.race_key]
        rows.append(dict(variant=s.variant, race_key=s.race_key, race_date=s.race_date, year=s.year,
             meet=int(c.meet), distance_m=float(c.distance_m), grade=c.grade, field_size=int(c.field_size),
             axis_program_no=s.program_no, axis_horse_id=s.horse_id, axis_outcome=int(truth[0]),
             axis_top3=int(1 <= truth[0] <= 3), axis_top2=int(1 <= truth[0] <= 2), axis_win=int(truth[0] == 1),
             quinella_one=int(set(g.program_no.iloc[:2]) == winners),
             axis_next3=int(s.program_no in winners and winners <= set(g.program_no.iloc[:4]))))
    rr = pd.concat([original, pd.DataFrame(rows)], ignore_index=True)
    rr.to_parquet(OUT / 'race_metrics.parquet', index=False)
    metrics = []
    for variant, z in rr.groupby('variant'):
        for period, g in windows(z):
            metrics.append(dict(variant=variant, period=period, n=len(g), **{m: float(g[m].mean()) for m in METRICS}))
    pd.DataFrame(metrics).to_csv(OUT / 'metrics.csv', index=False)
    pairs = []
    for variant in ['gain_logit_all', 'gain_tree_all']:
        for reference in ['joint_logit', 'frozen122', 'frozen103', variant.replace('_all', '_two')]:
            z = rr[rr.variant.eq(variant)].merge(rr[rr.variant.eq(reference)][['race_key'] + METRICS],
                    on='race_key', suffixes=('', '_ref'), validate='one_to_one')
            for period, g in windows(z):
                for metric in METRICS:
                    delta = g[metric] - g[metric + '_ref']
                    day = g[['race_date']].assign(delta=delta).groupby('race_date').delta.agg(['sum', 'size'])
                    rng = np.random.default_rng(20261014)
                    idx = rng.integers(len(day), size=(2000, len(day)))
                    values = day['sum'].to_numpy()[idx].sum(axis=1) / day['size'].to_numpy()[idx].sum(axis=1)
                    lo, hi = np.quantile(values, [.025, .975])
                    pairs.append(dict(variant=variant, reference=reference, period=period, metric=metric, n=len(g),
                         gain=int(delta.eq(1).sum()), loss=int(delta.eq(-1).sum()), net=int(delta.sum()),
                         difference_pp=float(delta.mean() * 100), lo_pp=float(lo * 100), hi_pp=float(hi * 100)))
    pd.DataFrame(pairs).to_csv(OUT / 'paired_differences.csv', index=False)
    axes = original.pivot(index='race_key', columns='variant', values='axis_horse_id')
    hits = original.pivot(index='race_key', columns='variant', values='axis_top3')
    details = []
    for variant, z in rr[rr.variant.str.endswith('_all')].groupby('variant'):
        z = z.copy()
        z['old103_horse_id'] = z.race_key.map(axes.frozen103)
        z['old122_horse_id'] = z.race_key.map(axes.frozen122)
        z['prior_selected_horse_id'] = z.race_key.map(axes.joint_logit)
        z['is_third'] = ~z.axis_horse_id.eq(z.old103_horse_id) & ~z.axis_horse_id.eq(z.old122_horse_id)
        z['both_original_miss'] = z.race_key.map(hits.frozen103).eq(0) & z.race_key.map(hits.frozen122).eq(0)
        z['prior_hit'] = z.race_key.map(hits.joint_logit)
        z['gain_vs_prior'] = z.axis_top3.eq(1) & z.prior_hit.eq(0)
        z['loss_vs_prior'] = z.axis_top3.eq(0) & z.prior_hit.eq(1)
        details.append(z)
    details = pd.concat(details, ignore_index=True)
    details.to_parquet(OUT / 'selection_diagnostics.parquet', index=False)
    details[details.is_third].to_csv(OUT / 'third_axis_cases.csv', index=False)
    third = []
    slices = []
    for variant, z in details.groupby('variant'):
        z = z.copy()
        z['distance_band'] = np.select([z.distance_m.le(1300), z.distance_m.le(1600)], ['short', 'middle'], default='long')
        for period, g in windows(z):
            t = g[g.is_third]
            third.append(dict(variant=variant, period=period, n=len(g), third_selected=len(t),
                 third_top3=int(t.axis_top3.sum()), third_top2=int(t.axis_top2.sum()),
                 both_original_miss=int(g.both_original_miss.sum()),
                 both_miss_rescued=int((g.both_original_miss & g.axis_top3.eq(1)).sum()),
                 third_gain_vs_prior=int(t.gain_vs_prior.sum()), third_loss_vs_prior=int(t.loss_vs_prior.sum())))
            for col in ['meet', 'grade', 'distance_band']:
                for value, a in g.groupby(col, dropna=False):
                    slices.append(dict(variant=variant, period=period, condition=col, value=str(value), n=len(a),
                         third_selected=int(a.is_third.sum()), gains=int(a.gain_vs_prior.sum()),
                         losses=int(a.loss_vs_prior.sum()), net=int(a.gain_vs_prior.sum() - a.loss_vs_prior.sum())))
    pd.DataFrame(third).to_csv(OUT / 'third_axis_summary.csv', index=False)
    pd.DataFrame(slices).to_csv(OUT / 'slices.csv', index=False)
    print(pd.DataFrame(metrics).query("period in ['all','2024','2025','2026']").to_string(index=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'learn', 'analyse'])
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        freeze()
        check()
        {'prepare': prepare, 'learn': learn, 'analyse': evaluate}[args.stage]()
        check()


if __name__ == '__main__':
    main()
