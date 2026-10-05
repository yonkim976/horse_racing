"""Independent annual chronology, model replay, joint math and cohort checks."""
import importlib.util
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_finish_stack', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT, KEY = RUN.OUT, RUN.KEY


def independent_joint(scores, temperatures):
    n = len(scores)
    ix = np.array(list(itertools.permutations(range(n), 3)))
    exp = np.exp(scores / np.asarray(temperatures) - np.max(scores / np.asarray(temperatures), axis=0))
    a, b, c = ix.T
    # Sum remaining terms directly: subtraction loses precision for a nearly
    # certain early leader, especially in the earliest sparse-data models.
    ids = np.arange(n)
    second_denominator = np.array([exp[ids != i, 1].sum() for i in range(n)])
    third_denominator = {(i, j): exp[(ids != i) & (ids != j), 2].sum()
                         for i, j in itertools.permutations(range(n), 2)}
    q = (exp[a, 0] / exp[:, 0].sum()) * (exp[b, 1] / second_denominator[a])
    q *= exp[c, 2] / np.array([third_denominator[(i, j)] for i, j in zip(a, b)])
    margins = np.stack([np.bincount(ix[:, k], weights=q, minlength=n) for k in range(3)], axis=1).cumsum(axis=1)
    combinations = list(itertools.combinations(range(n), 3))
    trios = np.array([q[np.all(np.sort(ix, axis=1) == t, axis=1)].sum() for t in combinations])
    return ix, q, margins, combinations, trios


def encode(f, cols, vocab):
    x = f[cols].copy()
    for col, values in vocab.items():
        x[col] = pd.Categorical(x[col], categories=values)
    return x


def main():
    RUN.check_stack()
    RUN.V5.check_inputs()  # Also checks the inherited frozen config/plan contract.
    c = RUN.cfg()
    checks = []
    maximum = 0.
    def check(name, value):
        checks.append({'check': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    def close(name, a, b, atol=1e-10):
        nonlocal maximum
        a, b = np.asarray(a, float), np.asarray(b, float)
        error = np.nanmax(abs(a - b)) if a.size and np.isfinite(a - b).any() else 0.
        maximum = max(maximum, float(error))
        check(name, np.allclose(a, b, atol=atol, rtol=1e-10, equal_nan=True))
    summary = json.loads((OUT / 'summary.json').read_text())
    for name, digest in summary['result_hashes'].items():
        check('result hash ' + name, RUN.BASE.sha(OUT / name) == digest)
    raw = pd.read_parquet(OUT / 'raw_features.parquet')
    f = pd.read_parquet(OUT / 'features.parquet')
    labels = pd.read_parquet(OUT / 'labels.parquet')
    point_labels = pd.read_parquet(RUN.PARENT / 'outputs/labels.parquet')
    pred = pd.read_parquet(OUT / 'external_pace_predictions.parquet')
    rp = pd.read_parquet(OUT / 'runner_predictions.parquet')
    rm = pd.read_csv(OUT / 'race_metrics.csv')
    rec = pd.read_parquet(OUT / 'recommendations.parquet')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    pd.testing.assert_frame_equal(f[raw.columns], raw, check_exact=True)
    pd.testing.assert_frame_equal(raw, pd.read_parquet(RUN.PARENT / 'outputs/features.parquet'), check_exact=True)
    pd.testing.assert_frame_equal(labels, pd.read_parquet(RUN.BASE_PATH / 'outputs/labels.parquet'), check_exact=True)
    check('raw parent features and podium labels identical', True)
    for variant, cols in contract.items():
        check('no current outcomes or identities ' + variant, not set(cols) & RUN.forbidden_columns())
        check('unique input columns ' + variant, len(cols) == len(set(cols)))
    early = f.year.lt(c['pace_prediction_start_year'])
    check('early years pace availability zero', f.loc[early, 'stack_pace_available'].eq(0).all())
    check('early years direct availability zero', f.loc[early, 'stack_direct_available'].eq(0).all())
    check('early years no substitute actual passing labels', f.loc[early, RUN.prediction_columns()[1:] + RUN.leader_columns()[1:]].isna().all().all())
    check('2020+ all runners covered', f.loc[~early, 'stack_pace_available'].eq(1).all())
    check('external pace keyset', set(map(tuple, pred[KEY].to_numpy())) == set(map(tuple, f.loc[~early, KEY].to_numpy())))
    check('external unique runner keys', not pred.duplicated(KEY).any())
    check('Seoul direct absent', f.loc[f.meet.eq(1), RUN.leader_columns()[1:]].isna().all().all())
    check('Busan direct available when external', f.loc[f.meet.eq(3) & ~early, 'stack_direct_available'].eq(1).all())
    for point in ['S1F', 'G3F']:
        p = pred[['stack_' + point + '_lead', 'stack_' + point + '_front3']]
        check('pace probabilities in range ' + point, p.ge(0).all().all() and p.le(1 + 1e-12).all().all())
        close('pace sum1/3 ' + point, p.groupby(pred.race_key).sum(), np.tile([1, 3], (pred.race_key.nunique(), 1)))
    close('derived advance', f.stack_advance, f.stack_S1F_fraction - f.stack_G3F_fraction)
    ledger = json.loads((OUT / 'pace_model_ledger.json').read_text())
    complete = raw.merge(point_labels, on=KEY, validate='one_to_one')
    for item in ledger:
        name = f"{item['meet']}/{item['prediction_year']}/{item['kind']}"
        year = item['prediction_year']
        path = RUN.ROOT / item['path']
        bundle = json.loads((path / 'metadata.json').read_text())
        meta = next(m for m in bundle['models'] if m['file'] == item['model_file'])
        one = complete[complete.meet.eq(item['meet'])].reset_index(drop=True)
        test = one[one.year.eq(year)].reset_index(drop=True)
        pp = pred[pred.meet.eq(item['meet']) & pred.year.eq(year)]
        pp = test[KEY].merge(pp, on=KEY, validate='one_to_one')
        kind = item['kind']
        point = 'S1F' if kind == 'leader' else kind
        check('upstream years external ' + name, meta['training_year_end'] == year - 2 and meta['calibration_year'] == year - 1)
        check('upstream T-2 ' + name, pd.Timestamp(item['calibration_max_date']) <= test.race_date.min() - pd.Timedelta(days=2))
        check('upstream max dates honest ' + name,
            str(one.loc[one.year.eq(year - 1), 'race_date'].max().date()) == item['calibration_max_date'] and
            str(one.loc[one.year.between(2017, year - 2), 'race_date'].max().date()) == item['training_max_date'])
        expected_rows = (one.year.between(2017, year - 2) & one[point + '_complete']).sum()
        check('upstream train row count ' + name, expected_rows == meta['training_rows'])
        check('upstream frozen whitelist ' + name, not set(meta['columns']) & RUN.forbidden_columns())
        check('upstream temperature bounds ' + name, all(.02 <= t <= (8 if kind == 'leader' else 1) for t in item['temperatures']))
        temperatures = bundle['temperatures'][kind]
        # The display ledger uses pandas JSON's ten-decimal formatting; the
        # hashed model metadata is the authoritative full-precision contract.
        check('ledger temperature display precision ' + name,
              np.allclose(item['temperatures'], temperatures, atol=5.1e-11, rtol=0))
        model = lgb.Booster(model_file=str(path / item['model_file']))
        check('upstream model column order ' + name, model.feature_name() == meta['columns'])
        rawp = model.predict(encode(test, meta['columns'], meta['vocabulary']), raw_score=kind == 'leader', num_threads=4)
        if kind != 'leader':
            close('all upstream fractions ' + name, pp['stack_' + kind + '_fraction'], np.clip(rawp, 0, 1))
            close('all upstream positions ' + name, pp['stack_' + kind + '_position'], 1 + np.clip(rawp, 0, 1) * (test.field_size - 1))
        selected = test.race_key.drop_duplicates().sample(3, random_state=c['seed']).tolist()
        for race in selected:
            idx = np.flatnonzero(test.race_key.eq(race))
            score = rawp[idx] if kind == 'leader' else -rawp[idx]
            _, q, margins, _, _ = independent_joint(np.repeat(score[:, None], 3, axis=1), temperatures)
            p = pp.iloc[idx]
            prefix = 'stack_direct_' if kind == 'leader' else 'stack_' + kind + '_'
            close('independent upstream lead ' + name + race, p[prefix + 'lead'], margins[:, 0])
            if kind != 'leader':
                close('independent upstream front3 ' + name + race, p[prefix + 'front3'], margins[:, 2])
            entropy = -np.sum(margins[:, 0] * np.log(margins[:, 0])) / np.log(len(idx))
            close('independent upstream entropy ' + name + race, p[prefix + ('entropy' if kind == 'leader' else 'lead_entropy')], entropy)
            other = [max(np.delete(margins[:, 0], k)) for k in range(len(idx))]
            close('independent upstream margin ' + name + race, p[prefix + ('margin' if kind == 'leader' else 'lead_margin')], margins[:, 0] - other)
            close('independent upstream joint sum ' + name + race, q.sum(), 1)
    check('35 external model heads', len(ledger) == 35)
    old_rp = pd.read_parquet(RUN.BASE_PATH / 'outputs/runner_predictions.parquet')
    old_rm = pd.read_csv(RUN.BASE_PATH / 'outputs/race_metrics.csv')
    frozen_p = old_rp[old_rp.variant.eq('history_records')].assign(variant='records').sort_values(KEY).reset_index(drop=True)
    actual_p = rp[rp.variant.eq('records')][frozen_p.columns].sort_values(KEY).reset_index(drop=True)
    pd.testing.assert_frame_equal(frozen_p, actual_p, check_exact=True)
    frozen_m = old_rm[old_rm.variant.eq('history_records')].assign(variant='records').sort_values('race_key').reset_index(drop=True)
    actual_m = rm[rm.variant.eq('records')][frozen_m.columns].sort_values('race_key').reset_index(drop=True)
    error_columns = ['joint_sum_error', 'marginal_sum_error']
    pd.testing.assert_frame_equal(frozen_m.drop(columns=error_columns), actual_m.drop(columns=error_columns), check_exact=True)
    close('records tiny diagnostic CSV roundtrip errors', frozen_m[error_columns], actual_m[error_columns], atol=1e-30)
    check('records baseline predictions and metrics identical', True)
    check('unique finish runner keys', not rp.duplicated(KEY + ['variant']).any())
    check('unique finish race keys', not rm.duplicated(['race_key', 'variant']).any())
    check('unique selected combinations', not rec.duplicated(['race_key', 'variant', 'horse_ids']).any())
    check('six combinations every race', rec.groupby(['race_key', 'variant']).size().eq(6).all())
    check('finish probability nesting', (rp.prob_win.le(rp.prob_top2 + 1e-12) & rp.prob_top2.le(rp.prob_top3 + 1e-12) & rp.prob_win.ge(0) & rp.prob_top3.le(1 + 1e-12)).all())
    close('finish marginal mass', rp.groupby(['race_key', 'variant'])[['prob_win', 'prob_top2', 'prob_top3']].sum(), np.tile([1, 2, 3], (len(rm), 1)))
    for meet in c['venues']:
        expected = f[f.meet.eq(meet) & f.year.isin(c['evaluation_years'])]
        for variant in RUN.variants(meet, c):
            pr = rp[rp.meet.eq(meet) & rp.variant.eq(variant)]
            check(f'complete finish keyset {meet}/{variant}', set(map(tuple, pr[KEY].to_numpy())) == set(map(tuple, expected[KEY].to_numpy())))
    full = f.merge(labels, on=KEY, validate='one_to_one')
    for meta in summary['models']:
        name = f"{meta['meet']}/{meta['evaluation_year']}/{meta['variant']}"
        path = RUN.ROOT / meta['path']
        year = meta['evaluation_year']
        check('finish columns match contract ' + name, meta['features'] == contract[meta['variant']])
        check('finish annual chronology ' + name, meta['final_training_year_end'] == year - 2 and meta['calibration_year'] == year - 1)
        one = full[full.meet.eq(meta['meet'])].reset_index(drop=True)
        test = one[one.year.eq(year)].reset_index(drop=True)
        check('finish calibration T-2 ' + name, one.loc[one.year.eq(year - 1), 'race_date'].max() <= test.race_date.min() - pd.Timedelta(days=2))
        stored = rp[rp.meet.eq(meta['meet']) & rp.evaluation_year.eq(year) & rp.variant.eq(meta['variant'])]
        stored = test[KEY].merge(stored, on=KEY, validate='one_to_one')
        x = encode(test, meta['features'], meta['category_vocabulary'])
        scores = np.empty((len(test), 3))
        for stage in range(3):
            model_path = path / f'position_{stage + 1}.txt'
            check('finish model hash ' + name + str(stage), RUN.BASE.sha(model_path) == meta['model_hashes'][model_path.name])
            model = lgb.Booster(model_file=str(model_path))
            check('finish model column order ' + name + str(stage), model.feature_name() == meta['features'])
            count = (one.year.between(2017, year - 2) & (one.outcome.gt(stage) if stage else True)).sum()
            check('finish training count ' + name + str(stage), count == meta['stages'][stage]['train_runners'])
            scores[:, stage] = model.predict(x, raw_score=True, num_threads=4)
            close('all finish scores ' + name + str(stage), scores[:, stage], stored[['score_win', 'score_second', 'score_third'][stage]])
        for race in test.race_key.drop_duplicates().sample(3, random_state=c['seed']):
            idx = np.flatnonzero(test.race_key.eq(race))
            target = test.iloc[idx].outcome.to_numpy()
            ix, q, margins, combos, probabilities = independent_joint(scores[idx], meta['temperatures'])
            close('sample finish mass ' + name + race, q.sum(), 1)
            close('sample finish marginals ' + name + race, stored.iloc[idx][['prob_win', 'prob_top2', 'prob_top3']], margins)
            truth = [int(np.flatnonzero(target == k)[0]) for k in [1, 2, 3]]
            truth_trio = sorted(truth)
            actual = probabilities[combos.index(tuple(truth_trio))]
            row = rm[rm.race_key.eq(race) & rm.variant.eq(meta['variant'])].iloc[0]
            close('sample ordered NLL ' + name + race, row.ordered_top3_nll, -np.log(q[np.all(ix == truth, axis=1)].sum()))
            close('sample trio NLL ' + name + race, row.trio_nll, -np.log(actual))
            chosen = np.argsort(-probabilities, kind='stable')[:6]
            selection = rec[rec.race_key.eq(race) & rec.variant.eq(meta['variant'])].sort_values('selection_rank')
            programs = test.iloc[idx].program_no.to_numpy(int)
            expected_programs = [','.join(map(str, sorted(programs[list(combos[k])]))) for k in chosen]
            check('sample six selections ' + name + race, expected_programs == selection.programs.tolist())
            close('sample six probabilities ' + name + race, selection.probability, probabilities[chosen])
            close('sample top6 probability ' + name + race, row.top6_trio_probability, probabilities[chosen].sum())
            check('sample top6 hit ' + name + race, row.top6_trio_hit == int(tuple(truth_trio) in [combos[k] for k in chosen]))
            top = np.argsort(-margins[:, 2], kind='stable')
            fixed = [tuple(sorted((top[0], a, b))) for a, b in itertools.combinations(top[1:5], 2)]
            check('sample fixed6 hit ' + name + race, row.fixed_axis6_trio_hit == int(tuple(truth_trio) in fixed))
    selection_groups = rec.groupby(['race_key', 'variant']).agg(hit=('hit', 'sum'), probability=('probability', 'sum')).reset_index()
    joined = rm.merge(selection_groups, on=['race_key', 'variant'], validate='one_to_one')
    close('all six hit sums', joined.top6_trio_hit, joined.hit)
    close('all six probability sums', joined.top6_trio_probability, joined.probability)
    metrics = pd.read_csv(OUT / 'metrics.csv')
    metric_names = [col for col in rm if col.endswith(('_nll', '_brier', '_logloss', '_hit')) or col == 'top5_contains_podium']
    for r in metrics.itertuples():
        group = rm[rm.meet.eq(r.meet) & rm.variant.eq(r.variant)]
        if r.period != 'all':
            group = group[group.evaluation_year.eq(int(r.period))]
        check(f'summary count {r.meet}/{r.variant}/{r.period}', len(group) == r.races)
        close(f'summary values {r.meet}/{r.variant}/{r.period}', [getattr(r, col) for col in metric_names], group[metric_names].mean())
    for item in json.loads((OUT / 'paired_differences.json').read_text()):
        a = rm[rm.meet.eq(item['meet']) & rm.variant.eq(item['base'])].set_index('race_key')
        b = rm[rm.meet.eq(item['meet']) & rm.variant.eq(item['candidate'])].set_index('race_key').reindex(a.index)
        close('paired point difference ' + str(item), item['difference'], (b[item['metric']] - a[item['metric']]).mean())
    outcome = {'passed': len(checks), 'failed': 0, 'max_numeric_error': maximum, 'checks': checks}
    RUN.BASE.save_json(OUT / 'verification.json', outcome)
    print(json.dumps({k: outcome[k] for k in ['passed', 'failed', 'max_numeric_error']}), flush=True)


if __name__ == '__main__':
    main()
