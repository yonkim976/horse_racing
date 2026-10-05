"""Independent historical arithmetic, frozen baseline, metrics and model replay."""
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_v4_run', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    RUN.check_inputs()
    c = RUN.cfg()
    checks = []
    def check(name, ok):
        checks.append({'check': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    summary = json.loads((OUT / 'summary.json').read_text())
    if (OUT / 'serialization_repair.json').exists():
        repair = json.loads((OUT / 'serialization_repair.json').read_text())
        old_audit = json.loads((OUT / 'data_audit_before_serialization_fix.json').read_text())
        new_audit = json.loads((OUT / 'data_audit.json').read_text())
        runkey = str((HERE / 'run.py').relative_to(RUN.ROOT))
        check('serialization repair old definition', RUN.BASE.sha(OUT / 'frozen_run_before_serialization_fix.py') == repair['original_run_sha256'])
        check('serialization repair current definition', RUN.BASE.sha(HERE / 'run.py') == repair['repaired_run_sha256'])
        check('serialization repair data unchanged', old_audit['prepared_hashes'] == new_audit['prepared_hashes'])
        check('serialization repair source inputs unchanged', all(new_audit['inputs'][k] == v for k, v in old_audit['inputs'].items() if k != runkey))
        for name, digest in repair['model_metadata_sha256'].items():
            check('serialization repair model unchanged ' + name, RUN.BASE.sha(OUT / 'models' / name / 'metadata.json') == digest)
    for name, digest in summary['result_hashes'].items():
        check('result hash ' + name, RUN.BASE.sha(OUT / name) == digest)
    f = pd.read_parquet(OUT / 'features.parquet')
    labels = pd.read_parquet(OUT / 'labels.parquet')
    h = pd.read_parquet(OUT / 'history.parquet')
    trials = pd.read_parquet(OUT / 'trials.parquet')
    rp = pd.read_parquet(OUT / 'runner_predictions.parquet')
    rm = pd.read_csv(OUT / 'point_metrics.csv')
    risk = pd.read_parquet(OUT / 'risk_predictions.parquet')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    old_f = pd.read_parquet(RUN.PARENT / 'outputs/features.parquet')
    pd.testing.assert_frame_equal(f[old_f.columns], old_f, check_exact=True)
    check('base features identical', True)
    pd.testing.assert_frame_equal(labels, pd.read_parquet(RUN.PARENT / 'outputs/labels.parquet'), check_exact=True)
    check('labels identical', True)
    for col in ['trial_source_date', 'risk_source_date', 'pace_source_date', 'jockey_trait_source_date']:
        check('T-2 ' + col, (f[col].isna() | f[col].le(f.race_date - pd.Timedelta(days=2))).all())
    all_cols = contract['base'] + contract['trial'] + contract['risk']
    check('no current labels or time in feature contract', not set(all_cols) & set(contract['forbidden']))
    check('no repeated model features', len(all_cols) == len(set(all_cols)))
    check('pre2017 trial times excluded', trials.loc[trials.source_date.lt('2017-01-01'), 'trial_s1f'].isna().all())
    check('cancelled/excluded trials unusable', not trials.loc[trials.pass_flag.fillna('').str.contains('취소|제외'), 'usable'].any())
    check('reviewed identity only', trials.loc[trials.usable, 'horse_identity_resolution'].isin(
        ['api_direct', 'crosschecked_link', 'user_confirmed_link']).all())
    check('trial times valid or missing', (trials.trial_s1f.isna() | trials.trial_s1f.between(10, 30)).all())
    for key, one in trials[trials.completed].groupby('trial_session_id'):
        if one.trial_fraction.notna().any():
            check('trial point permutation ' + key, set(one.s1f_rank) == set(range(1, len(one) + 1)))
    for row in f.sample(120, random_state=c['seed']).itertuples():
        cutoff = row.race_date - pd.Timedelta(days=2)
        past = h[h.horse_id.eq(row.horse_id) & h.race_date.le(cutoff)].sort_values('race_date')
        last = past.tail(3).historical_start_time.to_numpy(float)
        mean = float(last.mean()) if len(last) == 3 and np.isfinite(last).all() else np.nan
        check('direct past3 ' + row.race_key + '/' + row.horse_id,
            np.isclose(mean, row.risk_past3_time, equal_nan=True))
        slow = float(row.historical_start_time - mean > .4 + 1e-9) if np.isfinite(mean) and np.isfinite(row.historical_start_time) else np.nan
        check('direct risk label ' + row.race_key + '/' + row.horse_id, np.isclose(slow, row.slow_label, equal_nan=True))
        past_t = trials[trials.horse_id.eq(row.horse_id) & trials.meet.eq(row.meet) & trials.usable & trials.source_date.le(cutoff)]
        past_t = past_t.sort_values(['source_date', 'participant_row_id']).drop_duplicates('source_date', keep='last')
        check('direct trial count ' + row.race_key + '/' + row.horse_id, len(past_t) == row.trial_count)
        times = past_t.tail(3).s1f_time.where(past_t.tail(3).source_date.ge('2017-01-01') & past_t.tail(3).s1f_time.between(10, 30))
        check('direct trial time ' + row.race_key + '/' + row.horse_id,
            np.isclose(times.mean(), row.trial_last3_time, equal_nan=True))
        if len(past_t):
            check('direct trial last date ' + row.race_key + '/' + row.horse_id, past_t.source_date.iloc[-1] == row.trial_source_date)
    check('prediction keys unique', not rp.duplicated(RUN.KEY + ['point', 'variant']).any())
    check('race metrics keys unique', not rm.duplicated(['race_key', 'point', 'variant']).any())
    for (meet, point), one in rp.groupby(['meet', 'point']):
        baseline = one[one.variant.eq('jockey')]
        keys = set(map(tuple, baseline[RUN.KEY].to_numpy()))
        for variant, p in one.groupby('variant'):
            check(f'identical evaluation keys {meet}/{point}/{variant}', set(map(tuple, p[RUN.KEY].to_numpy())) == keys)
            check(f'finite probabilities {meet}/{point}/{variant}', np.isfinite(p[['prob_lead', 'prob_front3']]).all().all())
            check(f'nested probabilities {meet}/{point}/{variant}', p.prob_front3.ge(p.prob_lead - 1e-12).all())
            check(f'probability bounds {meet}/{point}/{variant}', p.prob_lead.between(0, 1).all() & p.prob_front3.between(0, 1 + 1e-12).all())
            sums = p.groupby('race_key')[['prob_lead', 'prob_front3']].sum()
            check(f'probability sums {meet}/{point}/{variant}', np.allclose(sums.to_numpy(), [1, 3], atol=1e-10))
    old = pd.read_parquet(RUN.PARENT / 'outputs/runner_predictions.parquet')
    old = old[old.variant.eq('jockey')]
    pair = rp[rp.variant.eq('jockey')].merge(old, on=RUN.KEY + ['point'], suffixes=('_v4', '_v3'), validate='one_to_one')
    for name in ['prob_lead', 'prob_front3', 'expected_position', 'actual_rank']:
        check('exact baseline ' + name, len(pair) == len(old) and np.allclose(pair[name + '_v4'], pair[name + '_v3'], atol=1e-12))
    # Rebuild displayed race statistics from runner outputs.
    calculated = []
    for (key, point, variant), one in rp.groupby(['race_key', 'point', 'variant'], sort=False):
        leader = one.sort_values(['prob_lead', 'program_no'], ascending=[False, True]).iloc[0]
        front = one.sort_values(['prob_front3', 'program_no'], ascending=[False, True]).head(3)
        err = abs(one.ranked_position - one.actual_rank)
        y = one.actual_rank.le(3).to_numpy(int)
        if variant in ['jockey', 'trial']:
            estimate = 1 + np.clip(-one.score.to_numpy(), 0, 1) * (len(one) - 1)
            if not np.allclose(estimate, one.expected_position.to_numpy(), atol=1e-12):
                raise AssertionError('Regression position reconstruction ' + key)
        calculated.append({'race_key': key, 'point': point, 'variant': variant,
            'leader_hit': int(leader.actual_rank == 1), 'top3_exact_hit': int(front.actual_rank.le(3).all()),
            'front_recall': front.actual_rank.le(3).sum() / 3, 'rank_position_mae': err.mean(),
            'rank_large_error_rate': err.ge(3).mean(), 'top3_brier': np.mean((one.prob_front3.to_numpy() - y) ** 2),
            'position_mae': abs(one.expected_position - one.actual_rank).mean()})
    comparison = rm.merge(pd.DataFrame(calculated), on=['race_key', 'point', 'variant'], suffixes=('_saved', '_independent'), validate='one_to_one')
    for name in ['leader_hit', 'top3_exact_hit', 'front_recall', 'rank_position_mae', 'rank_large_error_rate', 'top3_brier', 'position_mae']:
        check('race metric ' + name, len(comparison) == len(rm) and np.allclose(comparison[name + '_saved'], comparison[name + '_independent'], atol=1e-12, equal_nan=True))
    saved_s = pd.read_csv(OUT / 'metrics.csv')
    names = ['rank_position_mae', 'rank_large_error_rate', 'position_mae', 'leader_hit', 'top3_exact_hit', 'top3_brier', 'leader_nll']
    for row in saved_s.itertuples():
        sample = rm[rm.meet.eq(row.meet) & rm.point.eq(row.point) & rm.variant.eq(row.variant)]
        if row.period != 'all':
            sample = sample[sample.year.eq(int(row.period))]
        check(f'summary {row.meet}/{row.point}/{row.variant}/{row.period}', len(sample) == row.races and all(
            np.isclose(sample[n].mean(), getattr(row, n), equal_nan=True) for n in names))
    risk_comparison = risk.merge(f[RUN.KEY + ['slow_label', 'risk_past3_time']], on=RUN.KEY, suffixes=('_saved', '_source'), validate='one_to_one')
    check('risk labels preserved', np.allclose(risk_comparison.slow_label_saved, risk_comparison.slow_label_source, equal_nan=True))
    check('unknown historical risk stays unknown', risk_comparison.loc[risk_comparison.risk_past3_time_source.isna(), 'risk'].isna().all())
    check('known historical risk predicted', risk_comparison.loc[risk_comparison.risk_past3_time_source.notna(), 'risk'].notna().all())
    saved_risk = pd.read_csv(OUT / 'risk_metrics.csv')
    for row in saved_risk.itertuples():
        sample = risk[risk.meet.eq(row.meet) & risk.year.eq(row.year) & risk.slow_label.notna() & risk.risk.notna()]
        y = sample.slow_label.to_numpy(float)
        probs = sample.risk.to_numpy(float)
        check(f'risk metric {row.meet}/{row.year}', len(sample) == row.runners and np.isclose(row.brier, np.mean((probs - y) ** 2))
            and np.isclose(row.prevalence, y.mean()))
    labeled = f.merge(labels, on=RUN.KEY, validate='one_to_one')
    max_error = 0.
    for bundle in summary['models']:
        dest = OUT / 'models' / f'{bundle["meet"]}_{bundle["year"]}'
        for name, digest in bundle['hashes'].items():
            check('bundle hash ' + dest.name + '/' + name, RUN.BASE.sha(dest / name) == digest)
        one = labeled[labeled.meet.eq(bundle['meet'])].reset_index(drop=True)
        test = one.year.eq(bundle['year'])
        for meta in bundle['models']:
            check('chronology ' + dest.name + '/' + meta['file'], meta['training_year_end'] == bundle['year'] - 2
                and meta['calibration_year'] == bundle['year'] - 1)
            x = one[meta['columns']].copy()
            for col, vocab in meta['vocabulary'].items():
                x[col] = pd.Categorical(x[col], categories=vocab)
            model = lgb.Booster(model_file=str(dest / meta['file']))
            binary = meta['file'] not in ['S1F_trial.txt', 'G3F_trial.txt']
            pred = model.predict(x[test], raw_score=binary)
            index = one.loc[test, RUN.KEY].copy()
            index['replayed'] = pred
            if meta['file'] == 'risk.txt':
                saved = risk[risk.meet.eq(bundle['meet']) & risk.year.eq(bundle['year'])]
                pair = saved.merge(index, on=RUN.KEY, validate='one_to_one')
                err = float(np.max(abs(pair.raw_score - pair.replayed)))
                p = expit(meta['calibration']['slope'] * pair.replayed + meta['calibration']['intercept'])
                check('risk calibration replay ' + dest.name, np.allclose(p[pair.risk.notna()], pair.loc[pair.risk.notna(), 'risk'], atol=1e-12))
            else:
                point = meta['file'][:3] if not binary else 'S1F'
                variant = 'trial' if not binary else meta['file'].removesuffix('.txt')
                saved = rp[rp.meet.eq(bundle['meet']) & rp.year.eq(bundle['year']) & rp.point.eq(point) & rp.variant.eq(variant)]
                pair = saved.merge(index, on=RUN.KEY, validate='one_to_one')
                compare = pair.replayed if binary else -pair.replayed
                err = float(np.max(abs(pair.score - compare)))
            max_error = max(max_error, err)
            check('model replay ' + dest.name + '/' + meta['file'], err < 1e-10)
        alpha = bundle['risk_adjustment']['alpha']
        check('risk alpha bounded ' + dest.name, 0 <= alpha <= 2 and bundle['risk_adjustment']['calibration_year'] == bundle['year'] - 1)
        leader = rp[rp.meet.eq(bundle['meet']) & rp.year.eq(bundle['year']) & rp.variant.eq('leader_trial') & rp.point.eq('S1F')]
        adjusted = rp[rp.meet.eq(bundle['meet']) & rp.year.eq(bundle['year']) & rp.variant.eq('leader_risk') & rp.point.eq('S1F')]
        z = leader.merge(adjusted, on=RUN.KEY, suffixes=('_base', '_new'), validate='one_to_one').merge(risk[RUN.KEY + ['risk']], on=RUN.KEY, validate='one_to_one')
        expected = z.score_base / bundle['risk_adjustment']['score_temperature'] + alpha * np.log1p(-np.clip(z.risk.fillna(0), 0, 1 - 1e-8))
        check('risk adjusted scores ' + dest.name, np.allclose(expected, z.score_new, atol=1e-12))
    deltas = json.loads((OUT / 'paired_differences.json').read_text())
    for d in deltas:
        one = rm[rm.meet.eq(d['meet']) & rm.point.eq(d['point'])]
        pair = one[one.variant.eq('jockey')].merge(one[one.variant.eq(d['variant'])], on='race_key', suffixes=('_old', '_new'), validate='one_to_one')
        check(f'paired delta {d["meet"]}/{d["point"]}/{d["variant"]}/{d["metric"]}', len(pair) == d['races']
            and np.isclose((pair[d['metric'] + '_new'] - pair[d['metric'] + '_old']).mean(), d['delta']))
    RUN.check_inputs()
    RUN.BASE.save_json(OUT / 'verification.json', {'passed': len(checks), 'failed': 0, 'max_replay_error': max_error,
        'checks': checks, 'production_changed': False})
    print(json.dumps({'passed': len(checks), 'failed': 0, 'max_replay_error': max_error}), flush=True)


if __name__ == '__main__':
    main()
