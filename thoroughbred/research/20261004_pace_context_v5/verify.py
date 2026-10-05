"""Independent context arithmetic, frozen baseline and complete model replay."""
import importlib.util
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_context_v5', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def close(a, b):
    if pd.isna(a) or pd.isna(b):
        return bool(pd.isna(a) and pd.isna(b))
    return bool(np.isclose(float(a), float(b)))


def scalar_smooth(value, count, fallback, prior):
    if pd.isna(value):
        return fallback
    if pd.isna(fallback):
        return value
    return (count * value + prior * fallback) / (count + prior)


def historical_transitions(horse, lag):
    dates = (horse.race_date + pd.Timedelta(days=lag)).to_numpy()
    rows = []
    for current in horse.itertuples():
        pos = np.searchsorted(dates, current.race_date.to_datetime64(), side='right') - 1
        if pos < 0:
            continue
        prev = horse.iloc[pos]
        if pd.isna(current.distance_m) or pd.isna(prev.distance_m):
            continue
        direction = int(np.sign(current.distance_m - prev.distance_m))
        frac = current.S1F_fraction - prev.S1F_fraction
        advance = current.advance - prev.advance
        valid = pd.notna(current.S1F_fraction) and pd.notna(prev.S1F_fraction)
        front = float(current.S1F_rank > 3) if valid and prev.S1F_rank <= 3 else np.nan
        lead = float(current.S1F_rank != 1) if valid and prev.S1F_rank == 1 else np.nan
        rows.append({'race_date': current.race_date, 'meet': current.meet, 'direction': direction,
            'transition_fraction_delta': frac, 'transition_advance_delta': advance,
            'transition_front_lost': front, 'transition_lead_lost': lead})
    return pd.DataFrame(rows)


def main():
    RUN.check_inputs()
    c = RUN.cfg()
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)
    s = json.loads((OUT / 'summary.json').read_text())
    for name, digest in s['result_hashes'].items():
        check('artifact ' + name, RUN.BASE.sha(OUT / name) == digest)
    f = pd.read_parquet(OUT / 'features.parquet')
    h = pd.read_parquet(OUT / 'history.parquet')
    labels = pd.read_parquet(OUT / 'labels.parquet')
    rp = pd.read_parquet(OUT / 'runner_predictions.parquet')
    rm = pd.read_csv(OUT / 'point_metrics.csv')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    old = pd.read_parquet(RUN.PARENT / 'outputs/features.parquet')
    pd.testing.assert_frame_equal(f[old.columns], old, check_exact=True)
    check('old features identical', True)
    pd.testing.assert_frame_equal(labels, pd.read_parquet(RUN.PARENT / 'outputs/labels.parquet'), check_exact=True)
    check('labels identical', True)
    old_h = pd.read_parquet(RUN.PARENT / 'outputs/history.parquet')
    columns = [name for name in old_h if name != 'distance_m']
    pd.testing.assert_frame_equal(h[columns], old_h[columns], check_exact=True)
    check('old history outcomes and raw times identical', True)
    with duckdb.connect(str(RUN.ROOT / c['source_db']), read_only=True) as conn:
        source = conn.execute("""
          SELECT cast(source_meet as INT) meet, result_date, cast(result_race_no as INT) race_no,
            cast(horse_program_no_raw as INT) program_no, horse_id_raw horse_id,
            try_cast(race_distance_m_raw as DOUBLE) source_distance, grade_raw source_grade
          FROM confirmed_runners WHERE source_meet IN ('1','3')
           AND (try_cast(result_rank_raw as INT) BETWEEN 1 AND 20 OR try_cast(result_rank_raw as INT) IN (91,92))
        """).fetchdf()
    source['race_key'] = source.meet.astype(str) + ':' + source.result_date + ':' + source.race_no.astype(str)
    source = h[RUN.KEY + ['distance_m', 'source_grade']].merge(source, on=RUN.KEY, suffixes=('_saved', '_source'), validate='one_to_one')
    check('all historical distances directly from DB', len(source) == len(h) and np.allclose(source.distance_m,
        source.source_distance.where(source.source_distance.between(800, 3000)), equal_nan=True))
    check('historical grade raw identity', source.source_grade_saved.fillna('__unknown').eq(source.source_grade_source.fillna('__unknown')).all())
    check('unknown warm-up distances remain missing', h.distance_m.isna().sum() == 10 and h.loc[h.distance_m.isna(), 'race_date'].eq('2010-03-12').all())
    for name in ['band_style_source_date', 'exact_style_source_date', 'context_previous_source_date', 'transition_style_source_date', 'context_jockey_source_date']:
        check('T-2 ' + name, (f[name].isna() | f[name].le(f.race_date - pd.Timedelta(days=2))).all())
    check('historical transition cutoff', (h.transition_previous_date.isna() | h.transition_previous_date.le(h.race_date - pd.Timedelta(days=2))).all())
    allowed = contract['base'] + contract['distance'] + contract['context']
    forbidden = {'S1F_rank', 'G3F_rank', 'S1F_fraction', 'G3F_fraction', 'historical_start_time', 'slow_label', 'direct_target',
        'S1F_complete', 'G3F_complete', 'outcome', 'jockey_id', 'horse_id'}
    check('no outcome/current time/identity model features', not set(allowed) & forbidden)
    check('pre2017 raw200m absent', h.loc[h.race_date.lt('2017-01-01'), 'historical_start_time'].isna().all())
    horse_groups = {key: group.sort_values('race_date') for key, group in h.groupby('horse_id', sort=False)}
    jockey_groups = {key: group for key, group in h.groupby(['meet', 'jockey_id', 'distance_band'], sort=False)}
    for row in f.sample(140, random_state=c['seed']).itertuples():
        cutoff = row.race_date - pd.Timedelta(days=2)
        horse = horse_groups.get(row.horse_id, h.iloc[:0])
        past = horse[horse.race_date.le(cutoff)]
        regional = past[past.meet.eq(row.meet) & past.distance_m.notna()]
        samples = {'band_style': regional[regional.distance_band.eq(row.distance_band)],
                   'exact_style': regional[regional.distance_m.eq(row.distance_m)]}
        for prefix, sample in samples.items():
            check('direct count ' + prefix + '/' + row.race_key + '/' + row.horse_id,
                len(sample) == getattr(row, prefix + '_history_count'))
            last = sample.tail(5)
            for measure in RUN.MEASURES:
                count, mean = last[measure].count(), last[measure].mean()
                check('direct value ' + prefix + '/' + measure + '/' + row.race_key + '/' + row.horse_id,
                    count == getattr(row, prefix + '_' + measure + '_count')
                    and close(mean, getattr(row, prefix + '_' + measure + '_mean')))
        for measure in RUN.MEASURES:
            mixed = getattr(row, 'pace_last5_' + measure)
            bw = samples['band_style'].tail(5)[measure]
            expected_band = scalar_smooth(bw.mean(), bw.count(), mixed, c['distance_prior_observations'])
            ew = samples['exact_style'].tail(5)[measure]
            expected_exact = scalar_smooth(ew.mean(), ew.count(), expected_band, c['distance_prior_observations'])
            check('smoothing ' + measure + '/' + row.race_key + '/' + row.horse_id,
                close(expected_band, getattr(row, 'conditioned_band_' + measure))
                and close(expected_exact, getattr(row, 'conditioned_exact_' + measure)))
        if len(past):
            prev = past.iloc[-1]
            check('previous grade ' + row.race_key + '/' + row.horse_id,
                close(prev.grade_number, row.context_previous_grade))
        transitions = historical_transitions(past, 2)
        if len(transitions):
            transitions = transitions[transitions.meet.eq(row.meet) & transitions.direction.eq(row.context_direction)].sort_values('race_date')
        check('transition count ' + row.race_key + '/' + row.horse_id,
            len(transitions) == row.transition_style_history_count)
        for measure in ['transition_fraction_delta', 'transition_advance_delta', 'transition_front_lost', 'transition_lead_lost']:
            values = transitions.tail(5)[measure] if len(transitions) else pd.Series([], dtype=float)
            check('transition value ' + measure + '/' + row.race_key + '/' + row.horse_id,
                values.count() == getattr(row, 'transition_style_' + measure + '_count')
                and close(values.mean(), getattr(row, 'transition_style_' + measure + '_mean')))
        jockey = jockey_groups.get((row.meet, row.jockey_id, row.distance_band), h.iloc[:0])
        jockey = jockey[jockey.race_date.le(cutoff)]
        for measure, residual in [('early', 'early_residual'), ('advance', 'advance_residual')]:
            values = jockey[residual].dropna()
            check('jockey band ' + measure + '/' + row.race_key + '/' + row.horse_id,
                len(values) == getattr(row, 'context_jockey_' + measure + '_count')
                and np.isclose(values.sum() / (len(values) + c['jockey_prior_observations']), getattr(row, 'context_jockey_' + measure)))
    for measure in ['S1F_fraction', 'S1F_front', 'G3F_fraction', 'advance', 'historical_start_time']:
        values = f['conditioned_exact_' + measure]
        expected = values - values.groupby(f.race_key).transform('mean')
        check('field relative ' + measure, np.allclose(expected, f['field_relative_conditioned_' + measure], equal_nan=True))
    for key in f.race_key.drop_duplicates().sample(100, random_state=7):
        one = f[f.race_key.eq(key)]
        times = one.conditioned_exact_historical_start_time.to_numpy(float)
        for pos, row in enumerate(one.itertuples()):
            if not np.isfinite(times[pos]):
                check('unknown competitors ' + key + '/' + row.horse_id, pd.isna(row.conditioned_faster_competitors))
            else:
                other = np.delete(times, pos)
                fast = np.sum(other < times[pos] - .2)
                close_count = np.sum(abs(other - times[pos]) <= .2)
                check('self excluded competition ' + key + '/' + row.horse_id,
                    fast == row.conditioned_faster_competitors and close_count == row.conditioned_close_competitors)
    original = pd.read_parquet(RUN.PARENT / 'outputs/runner_predictions.parquet')
    original = original[original.variant.isin(['trial', 'leader_trial'])]
    inherited = rp[rp.variant.isin(['trial', 'leader_trial'])]
    keys = RUN.KEY + ['point', 'variant']
    pd.testing.assert_frame_equal(original.sort_values(keys).reset_index(drop=True),
        inherited[original.columns].sort_values(keys).reset_index(drop=True), check_exact=True)
    check('baseline predictions exactly identical', True)
    check('unique prediction keys', not rp.duplicated(keys).any())
    for (meet, point), one in rp.groupby(['meet', 'point']):
        keyset = set(map(tuple, one[one.variant.eq('trial')][RUN.KEY].to_numpy()))
        for variant, part in one.groupby('variant'):
            check(f'evaluation keyset {meet}/{point}/{variant}', set(map(tuple, part[RUN.KEY].to_numpy())) == keyset)
            check(f'probability sums {meet}/{point}/{variant}', np.allclose(part.groupby('race_key')[['prob_lead', 'prob_front3']].sum(), [1, 3], atol=1e-10))
            check(f'probability range {meet}/{point}/{variant}', part.prob_lead.between(0, 1).all()
                and part.prob_front3.between(0, 1 + 1e-12).all() and part.prob_front3.ge(part.prob_lead - 1e-12).all())
    calculated = []
    for (key, point, variant), one in rp.groupby(['race_key', 'point', 'variant'], sort=False):
        leader = one.loc[one.prob_lead.idxmax()]
        front = one.nlargest(3, 'prob_front3')
        calculated.append({'race_key': key, 'point': point, 'variant': variant,
            'position_mae': abs(one.expected_position - one.actual_rank).mean(),
            'leader_hit': int(leader.actual_rank == 1), 'top3_exact_hit': int(front.actual_rank.le(3).all()),
            'front_recall': front.actual_rank.le(3).mean(),
            'top3_brier': ((one.prob_front3 - one.actual_rank.le(3).astype(int)) ** 2).mean()})
    pair = rm.merge(pd.DataFrame(calculated), on=['race_key', 'point', 'variant'], suffixes=('_saved', '_direct'), validate='one_to_one')
    for name in ['position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier']:
        check('race metric ' + name, len(pair) == len(rm) and np.allclose(pair[name + '_saved'], pair[name + '_direct'], equal_nan=True, atol=1e-12))
    saved = pd.read_csv(OUT / 'metrics.csv')
    for row in saved.itertuples():
        sample = rm[rm.meet.eq(row.meet) & rm.point.eq(row.point) & rm.variant.eq(row.variant)]
        if row.period != 'all':
            sample = sample[sample.year.eq(int(row.period))]
        check(f'summary {row.meet}/{row.point}/{row.variant}/{row.period}', len(sample) == row.races and all(
            np.isclose(sample[name].mean(), getattr(row, name), equal_nan=True) for name in ['position_mae', 'leader_hit', 'top3_exact_hit', 'top3_brier']))
    max_error = 0.
    labeled = f.merge(labels, on=RUN.KEY, validate='one_to_one')
    for bundle in s['models']:
        dest = OUT / 'models' / f'{bundle["meet"]}_{bundle["year"]}_{bundle["variant"]}'
        for name, digest in bundle['artifact_hashes'].items():
            check('bundle hash ' + dest.name + '/' + name, RUN.BASE.sha(dest / name) == digest)
        one = labeled[labeled.meet.eq(bundle['meet'])].reset_index(drop=True)
        needed = one.year.isin([bundle['year'] - 1, bundle['year']])
        for model in bundle['models']:
            check('model chronology ' + dest.name + '/' + model['file'], model['training_year_end'] == bundle['year'] - 2
                and model['calibration_year'] == bundle['year'] - 1 and model['evaluation_year'] == bundle['year'])
            check('model input whitelist ' + dest.name + '/' + model['file'], set(model['columns']).issubset(allowed) and not set(model['columns']) & forbidden)
            x = one[model['columns']].copy()
            for name, vocabulary in model['vocabulary'].items():
                x[name] = pd.Categorical(x[name], categories=vocabulary)
            classifier = model['file'] == 'leader.txt'
            booster = lgb.Booster(model_file=str(dest / model['file']))
            pred = np.full(len(one), np.nan)
            pred[needed] = booster.predict(x[needed], raw_score=classifier)
            point = 'S1F' if classifier else model['file'][:3]
            variant = 'leader_' + bundle['variant'] if classifier else bundle['variant']
            scores = pred if classifier else -pred
            output = rp[rp.meet.eq(bundle['meet']) & rp.year.eq(bundle['year']) & rp.point.eq(point) & rp.variant.eq(variant)]
            lookup = one[RUN.KEY].copy(); lookup['replayed'] = scores
            pair = output.merge(lookup, on=RUN.KEY, validate='one_to_one')
            err = float(np.max(abs(pair.score - pair.replayed)))
            max_error = max(max_error, err)
            check('model replay ' + dest.name + '/' + model['file'], err < 1e-10)
            temperatures = bundle['temperatures']['leader' if classifier else point]
            for key in output.race_key.drop_duplicates().sample(5, random_state=5):
                race = output[output.race_key.eq(key)]
                expected = softmax(race.score.to_numpy() / temperatures[0])
                check('leader softmax replay ' + dest.name + '/' + model['file'] + '/' + key,
                    np.allclose(expected, race.prob_lead, atol=1e-12))
    for item in json.loads((OUT / 'paired_differences.json').read_text()):
        one = rm[rm.meet.eq(item['meet']) & rm.point.eq(item['point'])]
        pair = one[one.variant.eq(item['base'])].merge(one[one.variant.eq(item['variant'])], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
        check('paired delta ' + '/'.join(map(str, [item['meet'], item['point'], item['base'], item['variant'], item['metric']])),
            len(pair) == item['races'] and np.isclose((pair[item['metric'] + '_new'] - pair[item['metric'] + '_base']).mean(), item['delta']))
    RUN.check_inputs()
    RUN.BASE.save_json(OUT / 'verification.json', {'passed': len(checks), 'failed': 0, 'max_replay_error': max_error,
        'checks': checks, 'production_changed': False})
    print(json.dumps({'passed': len(checks), 'failed': 0, 'max_replay_error': max_error}), flush=True)


if __name__ == '__main__':
    main()
