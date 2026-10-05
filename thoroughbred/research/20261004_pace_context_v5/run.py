"""Chronological, distance-conditioned horse style and field context ablation."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PARENT = HERE.parent / '20261004_pace_objectives_v4'
SPEC = importlib.util.spec_from_file_location('context_v5_parent', PARENT / 'run.py')
V4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V4)
BASE, PACE, KEY, V3 = V4.BASE, V4.PACE, V4.KEY, V4.V3
MEASURES = ['S1F_fraction', 'S1F_lead', 'S1F_front', 'G3F_fraction', 'G3F_front', 'advance', 'historical_start_time']


def cfg():
    return json.loads((HERE / 'config.json').read_text())


def band(values, breaks):
    conditions = [values.le(breaks[0]), values.le(breaks[1]), values.notna()]
    return np.select([a.fillna(False).to_numpy(bool) for a in conditions], [0, 1, 2], default=3).astype('int64')


def direction(values):
    conditions = [values.gt(0), values.lt(0), values.eq(0)]
    return np.select([a.fillna(False).to_numpy(bool) for a in conditions], [1, -1, 0], default=3).astype('int64')


def enrich_history(h, db, c):
    with duckdb.connect(str(db), read_only=True) as conn:
        context = conn.execute("""
          SELECT cast(source_meet as INT) meet,
            strptime(result_date,'%Y%m%d')::DATE race_date,
            cast(result_race_no as INT) race_no,
            cast(horse_program_no_raw as INT) program_no, horse_id_raw horse_id,
            try_cast(race_distance_m_raw as DOUBLE) source_distance, grade_raw source_grade
          FROM confirmed_runners WHERE source_meet IN ('1','3')
           AND (try_cast(result_rank_raw as INT) BETWEEN 1 AND 20 OR try_cast(result_rank_raw as INT) IN (91,92))
        """).fetchdf()
    context.race_date = pd.to_datetime(context.race_date)
    context['race_key'] = context.meet.astype(str) + ':' + context.race_date.dt.strftime('%Y%m%d') + ':' + context.race_no.astype(str)
    if context.duplicated(KEY).any():
        raise ValueError('Duplicate historical context')
    out = h.drop(columns='distance_m').merge(context[KEY + ['source_distance', 'source_grade']], on=KEY, validate='one_to_one')
    out = out.rename(columns={'source_distance': 'distance_m'})
    if len(out) != len(h):
        raise ValueError('Historical distance context incomplete')
    # Ten Busan warm-up records on2010-03-12 have no distance. Preserve them
    # as unknown rather than inventing a distance or dropping other history.
    out['distance_m'] = out.distance_m.where(out.distance_m.between(800, 3000))
    out['distance_band'] = band(out.distance_m, c['distance_breaks'])
    out['grade_number'] = pd.to_numeric(out.source_grade.str.extract(r'([1-6])', expand=False), errors='coerce')
    return out


def lookup(query, states, by):
    states = states.copy()
    for col in by:
        states[col] = states[col].astype(query[col].dtype)
    states['available_date'] = states.available_date.astype(query.race_date.dtype)
    return V3.lookup(query, states, by)


def rolling_states(h, by, measures, prefix, c):
    h = h.sort_values(by + ['race_date']).copy()
    group = h.groupby(by, sort=False)
    state = h[by + ['race_date']].rename(columns={'race_date': 'source_date'})
    state[prefix + '_history_count'] = group.cumcount() + 1
    columns = [prefix + '_history_count']
    for measure in measures:
        mean, count = prefix + '_' + measure + '_mean', prefix + '_' + measure + '_count'
        rolling = group[measure].rolling(5, min_periods=1)
        state[mean] = rolling.mean().reset_index(level=list(range(len(by))), drop=True)
        state[count] = rolling.count().reset_index(level=list(range(len(by))), drop=True)
        columns += [mean, count]
    state['available_date'] = state.source_date + pd.Timedelta(days=c['history_lag_days'])
    return state, columns


def add_distance(f, h, c):
    out = f.copy()
    out['distance_band'] = band(out.distance_m, c['distance_breaks'])
    columns = ['distance_band']
    for by, prefix in [(['horse_id', 'meet', 'distance_band'], 'band_style'),
                       (['horse_id', 'meet', 'distance_m'], 'exact_style')]:
        state, cols = rolling_states(h[h.distance_m.notna()], by, MEASURES, prefix, c)
        value = lookup(out, state, by)
        for col in cols:
            out[col] = value[col]
            if col.endswith('_count'):
                out[col] = out[col].fillna(0)
        out[prefix + '_source_date'] = value.source_date
        out[prefix + '_days_since'] = (out.race_date - value.source_date).dt.days
        columns += cols + [prefix + '_days_since']
    prior = c['distance_prior_observations']
    for measure in MEASURES:
        mixed = out['pace_last5_' + measure].astype(float)
        band_mean = out['band_style_' + measure + '_mean'].astype(float)
        band_n = out['band_style_' + measure + '_count'].astype(float)
        # Unknown mixed history cannot dilute a known regional/band history.
        weight = band_n / (band_n + prior)
        smooth = weight * band_mean + (1 - weight) * mixed
        smooth = smooth.where(mixed.notna(), band_mean).where(band_mean.notna(), mixed)
        name = 'conditioned_band_' + measure
        out[name] = smooth
        exact = out['exact_style_' + measure + '_mean'].astype(float)
        exact_n = out['exact_style_' + measure + '_count'].astype(float)
        ew = exact_n / (exact_n + prior)
        exact_smooth = ew * exact + (1 - ew) * smooth
        exact_smooth = exact_smooth.where(smooth.notna(), exact).where(exact.notna(), smooth)
        out['conditioned_exact_' + measure] = exact_smooth
        out['conditioned_difference_' + measure] = exact_smooth - mixed
        columns += [name, 'conditioned_exact_' + measure, 'conditioned_difference_' + measure]
    relative = ['S1F_fraction', 'S1F_front', 'G3F_fraction', 'advance', 'historical_start_time']
    for measure in relative:
        source, name = 'conditioned_exact_' + measure, 'field_relative_conditioned_' + measure
        out[name] = out[source] - out.groupby('race_key')[source].transform('mean')
        columns.append(name)
    faster, close = np.full(len(out), np.nan), np.full(len(out), np.nan)
    for _, idx in out.groupby('race_key', sort=False).indices.items():
        time = out.iloc[idx].conditioned_exact_historical_start_time.to_numpy(float)
        known = np.isfinite(time)
        difference = time[None, :] - time[:, None]
        mask = ~np.eye(len(time), dtype=bool)
        faster[idx] = np.where(known, ((difference < -c['competition_time_margin_seconds']) & mask).sum(axis=1), np.nan)
        close[idx] = np.where(known, ((abs(difference) <= c['competition_time_margin_seconds']) & mask).sum(axis=1), np.nan)
    out['conditioned_faster_competitors'], out['conditioned_close_competitors'] = faster, close
    out['conditioned_unknown_count'] = out.conditioned_exact_S1F_fraction.isna().groupby(out.race_key).transform('sum')
    out['conditioned_gate_style'] = out.gate_fraction_proxy * out.conditioned_exact_S1F_front
    columns += ['conditioned_faster_competitors', 'conditioned_close_competitors', 'conditioned_unknown_count', 'conditioned_gate_style']
    return out, columns


def transition_history(h, c):
    previous = h[['horse_id', 'race_date', 'distance_m', 'grade_number', 'S1F_fraction', 'S1F_rank', 'advance']].rename(
        columns={'race_date': 'source_date', 'distance_m': 'previous_distance', 'grade_number': 'previous_grade',
                 'S1F_fraction': 'previous_fraction', 'S1F_rank': 'previous_rank', 'advance': 'previous_advance'})
    previous['available_date'] = previous.source_date + pd.Timedelta(days=c['history_lag_days'])
    value = lookup(h, previous, ['horse_id'])
    out = h.copy()
    out['transition_previous_date'] = value.source_date
    out['transition_previous_distance'] = value.previous_distance
    out['transition_direction'] = direction(out.distance_m - value.previous_distance)
    out['transition_fraction_delta'] = out.S1F_fraction - value.previous_fraction
    out['transition_advance_delta'] = out.advance - value.previous_advance
    valid = out.S1F_fraction.notna() & value.previous_fraction.notna()
    out['transition_front_lost'] = out.S1F_rank.gt(3).fillna(False).astype(float).where(valid & value.previous_rank.le(3).fillna(False))
    out['transition_lead_lost'] = out.S1F_rank.ne(1).fillna(False).astype(float).where(valid & value.previous_rank.eq(1).fillna(False))
    return out, previous


def add_context(f, h, previous, c):
    out = f.copy()
    value = lookup(out, previous, ['horse_id'])
    out['context_previous_grade'] = value.previous_grade
    out['context_grade_change'] = out.grade - value.previous_grade
    out['context_grade_history_known'] = value.previous_grade.notna().astype(float)
    out['context_previous_source_date'] = value.source_date
    out['context_direction'] = direction(out.distance_m - value.previous_distance)
    cols = ['context_previous_grade', 'context_grade_change', 'context_grade_history_known', 'context_direction']
    measures = ['transition_fraction_delta', 'transition_advance_delta', 'transition_front_lost', 'transition_lead_lost']
    qualified = h[h.transition_direction.ne(3)].copy()
    state, names = rolling_states(qualified, ['horse_id', 'meet', 'transition_direction'], measures, 'transition_style', c)
    query = out.copy()
    query['transition_direction'] = query.context_direction
    value = lookup(query, state, ['horse_id', 'meet', 'transition_direction'])
    for name in names:
        out[name] = value[name]
        if name.endswith('_count'):
            out[name] = out[name].fillna(0)
    out['transition_style_source_date'] = value.source_date
    out['transition_style_days_since'] = (out.race_date - value.source_date).dt.days
    cols += names + ['transition_style_days_since']
    # Use the already chronological v3 residuals, never current rider outcomes.
    by = ['meet', 'jockey_id', 'distance_band']
    daily = h.groupby(by + ['race_date'], sort=True).agg(early_sum=('early_residual', 'sum'),
        early_count=('early_residual', 'count'), advance_sum=('advance_residual', 'sum'),
        advance_count=('advance_residual', 'count')).reset_index()
    values = ['early_sum', 'early_count', 'advance_sum', 'advance_count']
    daily[values] = daily.groupby(by, sort=False)[values].cumsum()
    daily['source_date'] = daily.race_date
    daily['available_date'] = daily.race_date + pd.Timedelta(days=c['history_lag_days'])
    daily = daily.drop(columns='race_date')
    jockey = lookup(out, daily, by)
    for measure in ['early', 'advance']:
        name = 'context_jockey_' + measure
        count = jockey[measure + '_count'].fillna(0)
        out[name + '_count'] = count
        out[name] = jockey[measure + '_sum'].fillna(0) / (count + c['jockey_prior_observations'])
        cols += [name, name + '_count']
    out['context_jockey_source_date'] = jockey.source_date
    out['context_jockey_relative_early'] = out.context_jockey_early - out.groupby('race_key').context_jockey_early.transform('mean')
    out['context_jockey_style_interaction'] = out.context_jockey_early * out.conditioned_exact_S1F_fraction
    cols += ['context_jockey_relative_early', 'context_jockey_style_interaction']
    return out, cols


def prepare():
    c = cfg()
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite experiment')
    V4.check_inputs()
    paths = [ROOT / c['source_db'], ROOT / 'config/prediction_model_registry.json', HERE / 'run.py', HERE / 'config.json', HERE / 'PLAN.md',
        PARENT / 'run.py', V4.PARENT / 'run.py', V3.V2_PATH / 'run.py', V3.V2.PACE_PATH / 'run.py', PACE.BASE_PATH / 'run.py']
    paths += [PARENT / 'outputs' / name for name in ['features.parquet', 'history.parquet', 'labels.parquet',
        'feature_contract.json', 'runner_predictions.parquet', 'point_metrics.csv']]
    hashes = {str(p.relative_to(ROOT)): BASE.sha(p) for p in paths}
    f = pd.read_parquet(PARENT / 'outputs/features.parquet')
    h = enrich_history(pd.read_parquet(PARENT / 'outputs/history.parquet'), ROOT / c['source_db'], c)
    h, previous = transition_history(h, c)
    f, distance_cols = add_distance(f, h, c)
    print('Prepared distance-conditioned histories', flush=True)
    f, context_cols = add_context(f, h, previous, c)
    for col in ['band_style_source_date', 'exact_style_source_date', 'context_previous_source_date', 'transition_style_source_date', 'context_jockey_source_date']:
        if not (f[col].isna() | f[col].le(f.race_date - pd.Timedelta(days=c['history_lag_days']))).all():
            raise ValueError('Historical cutoff failure ' + col)
    old_contract = json.loads((PARENT / 'outputs/feature_contract.json').read_text())
    base_cols = old_contract['base'] + old_contract['trial']
    if len(set(base_cols + distance_cols + context_cols)) != len(base_cols + distance_cols + context_cols):
        raise ValueError('Duplicate feature definition')
    OUT.mkdir()
    f.to_parquet(OUT / 'features.parquet', index=False)
    h.to_parquet(OUT / 'history.parquet', index=False)
    pd.read_parquet(PARENT / 'outputs/labels.parquet').to_parquet(OUT / 'labels.parquet', index=False)
    BASE.save_json(OUT / 'feature_contract.json', {'base': base_cols, 'distance': distance_cols, 'context': context_cols})
    f.groupby(['meet', 'year', 'distance_band']).agg(runners=('horse_id', 'size'),
        band_known=('band_style_S1F_fraction_count', lambda x: int(x.gt(0).sum())),
        exact_known=('exact_style_S1F_fraction_count', lambda x: int(x.gt(0).sum())),
        transition_known=('transition_style_transition_fraction_delta_count', lambda x: int(x.gt(0).sum())),
        jockey_band_known=('context_jockey_early_count', lambda x: int(x.gt(0).sum()))).to_csv(OUT / 'coverage.csv')
    BASE.save_json(OUT / 'data_audit.json', {'inputs': hashes, 'prepared_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()},
        'runners': len(f), 'history_rows': len(h), 'production_changed': False})
    print(f'Prepared {len(f)} runners, {len(distance_cols)} distance and {len(context_cols)} context inputs', flush=True)


def check_inputs():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    for name, digest in audit['inputs'].items():
        if BASE.sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed ' + name)
    for name, digest in audit['prepared_hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Prepared data changed ' + name)
    return audit


def train():
    c = cfg()
    check_inputs()
    if (OUT / 'summary.json').exists():
        raise FileExistsError('Completed experiment exists')
    f = pd.read_parquet(OUT / 'features.parquet').merge(pd.read_parquet(OUT / 'labels.parquet'), on=KEY, validate='one_to_one')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    inherited_runners = pd.read_parquet(PARENT / 'outputs/runner_predictions.parquet')
    inherited_metrics = pd.read_csv(PARENT / 'outputs/point_metrics.csv')
    use = inherited_runners.variant.isin(['trial', 'leader_trial'])
    runners = [inherited_runners[use]]
    metrics = [inherited_metrics[inherited_metrics.variant.isin(['trial', 'leader_trial'])]]
    bundles = []
    (OUT / 'models').mkdir(exist_ok=True)
    for meet in c['venues']:
        one = f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            for variant in ['distance', 'context']:
                dest = OUT / 'models' / f'{meet}_{year}_{variant}'
                complete = dest / 'metadata.json'
                if complete.exists():
                    bundle = json.loads(complete.read_text())
                    for name, digest in bundle['artifact_hashes'].items():
                        if BASE.sha(dest / name) != digest:
                            raise ValueError('Completed bundle changed')
                else:
                    if dest.exists() and any(dest.iterdir()):
                        raise FileExistsError('Incomplete bundle: ' + str(dest))
                    dest.mkdir(exist_ok=True)
                    print(f'Training meet={meet} year={year} variant={variant}', flush=True)
                    columns = contract['base'] + contract['distance'] + (contract['context'] if variant == 'context' else [])
                    bundle = {'meet': meet, 'year': year, 'variant': variant, 'models': [], 'temperatures': {}}
                    rr, mm = [], []
                    for point in ['S1F', 'G3F']:
                        prediction, model = PACE.fit_regression(one, columns, point + '_fraction', one[point + '_complete'], year, c,
                            dest / (point + '.txt'), race_weight=True)
                        temps = V4.temperatures(one, point, -prediction, year, {**c, 'temperature_bounds': [.02, 1.]})
                        rp, rm = V4.probability_evaluation(one, point, -prediction, year, variant, temps, prediction)
                        rr.append(rp); mm.append(rm)
                        bundle['models'].append(model); bundle['temperatures'][point] = temps
                    one['direct_target'] = one.S1F_rank.eq(1).fillna(False).astype(int)
                    scores, model = V4.fit_binary(one, columns, 'direct_target', one.S1F_complete, year, c, dest / 'leader.txt')
                    model['direct_kind'] = 'leader'
                    temps = V4.temperatures(one, 'S1F', scores, year, c)
                    rp, rm = V4.probability_evaluation(one, 'S1F', scores, year, 'leader_' + variant, temps)
                    rr.append(rp); mm.append(rm)
                    bundle['models'].append(model); bundle['temperatures']['leader'] = temps
                    pd.concat(rr, ignore_index=True).to_parquet(dest / 'runners.parquet', index=False)
                    pd.concat(mm, ignore_index=True).to_csv(dest / 'points.csv', index=False)
                    bundle['artifact_hashes'] = {p.name: BASE.sha(p) for p in dest.iterdir() if p.is_file()}
                    BASE.save_json(complete, bundle)
                    print(f'Evaluated meet={meet} year={year} variant={variant}', flush=True)
                runners.append(pd.read_parquet(dest / 'runners.parquet'))
                metrics.append(pd.read_csv(dest / 'points.csv'))
                bundles.append(bundle)
    rp, rm = pd.concat(runners, ignore_index=True), pd.concat(metrics, ignore_index=True)
    rp.to_parquet(OUT / 'runner_predictions.parquet', index=False)
    rm.to_csv(OUT / 'point_metrics.csv', index=False)
    names = ['position_mae', 'rank_position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier', 'leader_nll', 'rank_large_error_rate']
    rows = []
    for (meet, point, variant), sample in rm.groupby(['meet', 'point', 'variant']):
        for period, part in [('all', sample), *[(str(y), a) for y, a in sample.groupby('year')]]:
            rows.append({'meet': int(meet), 'point': point, 'variant': variant, 'period': period, 'races': len(part),
                **{name: float(part[name].mean()) for name in names}})
    s = pd.DataFrame(rows)
    s.to_csv(OUT / 'metrics.csv', index=False)
    differences = paired_differences(rm, c)
    BASE.save_json(OUT / 'paired_differences.json', differences)
    sensitivity(rp, rm, f)
    report(s, differences)
    BASE.save_json(OUT / 'summary.json', {'experiment': c['experiment'], 'models': bundles,
        'metrics': V4.json_records(s), 'production_changed': False, 'final_finish_model_changed': False,
        'result_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}})
    print('Completed ' + str(OUT / 'REPORT.md'), flush=True)


def paired_differences(metrics, c):
    rng, results = np.random.default_rng(c['seed']), []
    for (meet, point), one in metrics.groupby(['meet', 'point']):
        comparisons = [('trial', 'distance'), ('trial', 'context'), ('distance', 'context')]
        if point == 'S1F':
            comparisons += [('leader_trial', 'leader_distance'), ('leader_trial', 'leader_context')]
        for baseline, variant in comparisons:
            paired = one[one.variant.eq(baseline)].merge(one[one.variant.eq(variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
            metrics_to_compare = ['leader_hit', 'top3_exact_hit', 'top3_brier', 'leader_nll']
            if not variant.startswith('leader_'):
                metrics_to_compare += ['position_mae']
            for metric in metrics_to_compare:
                delta = paired[metric + '_new'] - paired[metric + '_base']
                daily = pd.DataFrame({'day': paired.race_date_base, 'd': delta}).groupby('day').d.agg(['sum', 'size']).to_numpy()
                sample = daily[rng.integers(0, len(daily), (c['bootstrap_draws'], len(daily)))]
                bounds = np.quantile(sample[:, :, 0].sum(axis=1) / sample[:, :, 1].sum(axis=1), [.025, .975])
                results.append({'meet': int(meet), 'point': point, 'base': baseline, 'variant': variant, 'metric': metric,
                    'races': len(paired), 'delta': float(delta.mean()), 'ci95': bounds.tolist()})
    return results


def sensitivity(rp, rm, f):
    context = f[KEY + ['distance_band', 'grade', 'grade_kind', 'history_count', 'context_direction', 'band_style_S1F_fraction_count']].copy()
    context['experience'] = np.where(context.history_count.eq(0), 'zero', np.where(context.history_count.lt(5), 'one_to_four', 'five_plus'))
    context['band_history'] = np.where(context.band_style_S1F_fraction_count.eq(0), 'unknown',
        np.where(context.band_style_S1F_fraction_count.lt(3), 'one_to_two', 'three_plus'))
    one = rp.merge(context, on=KEY, validate='many_to_one')
    one['position_error'] = abs(one.expected_position - one.actual_rank)
    one['large_error'] = one.position_error.ge(3).where(one.position_error.notna())
    one['rank_error'] = abs(one.ranked_position - one.actual_rank)
    for name in ['distance_band', 'experience', 'context_direction', 'band_history']:
        one.groupby(['meet', 'point', 'variant', name], dropna=False).agg(runners=('horse_id', 'size'),
            position_mae=('position_error', 'mean'), large_error=('large_error', 'mean'), rank_mae=('rank_error', 'mean')).to_csv(OUT / (name + '_runner_metrics.csv'))
    races = f[['race_key', 'distance_band', 'grade', 'grade_kind']].drop_duplicates('race_key')
    race = rm.merge(races, on='race_key', validate='many_to_one')
    for name in ['distance_band', 'grade']:
        race.groupby(['meet', 'point', 'variant', name], dropna=False).agg(races=('race_key', 'size'),
            position_mae=('position_mae', 'mean'), leader_hit=('leader_hit', 'mean'),
            top3_exact_hit=('top3_exact_hit', 'mean'), top3_brier=('top3_brier', 'mean')).to_csv(OUT / (name + '_race_metrics.csv'))


def report(s, differences):
    names = {'trial': 'v4 주행심사 회귀', 'distance': '+거리별 이력·편성', 'context': '+거리변경·기수·등급',
        'leader_trial': 'v4 선두 직접+심사', 'leader_distance': '선두+거리별 이력', 'leader_context': '선두+전체 문맥'}
    lines = ['# 전개 v5 — 이번 거리·편성에 맞춘 전개 이력', '',
        '2010–2016 이력 준비, 학습2017+, 원시시간2017+, 이력T−2. 서울·부산 별도. 같은2024–2026-09-20 후향 평가이며 독립 미래 검증이 아니다. 심판기록은 사용하지 않았다.', '',
        '| 장소 | 지점 | 후보 | 경주 | 위치 MAE ↓ | 선두 | 앞선3두 정확 | Brier ↓ |', '|---|---|---|---:|---:|---:|---:|---:|']
    for row in s[s.period.eq('all')].itertuples():
        error = f'{row.position_mae:.4f}두' if pd.notna(row.position_mae) else '해당 없음'
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {row.point} | {names[row.variant]} | {row.races:,} | {error} | {row.leader_hit:.2%} | {row.top3_exact_hit:.2%} | {row.top3_brier:.5f} |')
    lines += ['', '## 동일 경주 차이', '', '후보−기준. 날짜bootstrap95% 구간은 반복된 후보 탐색을 보정하지 않는다.', '',
        '| 장소 | 지점 | 비교 | 지표 | 차이 | 95% 구간 |', '|---|---|---|---|---:|---|']
    for d in differences:
        if d['metric'] not in ['position_mae', 'leader_hit', 'top3_exact_hit']:
            continue
        lo, hi = d['ci95']
        lines.append(f'| { {1:"서울",3:"부산"}[d["meet"]]} | {d["point"]} | {names[d["variant"]]}−{names[d["base"]]} | {d["metric"]} | {d["delta"]:+.5f} | {lo:+.5f}~{hi:+.5f} |')
    lines += ['', '## 해석 범위', '',
        '같은 거리 및 거리 구간의 과거 기록을3관측의 가중치로 혼합 이력에 완화하고 이번 편성 안에서 비교한다. 기수의 의도·고정 각질·실제 진로를 직접 관측한 모델은 아니다.', '',
        '신마나 같은 거리 경험이 없는 말은 혼합 이력·관측 수·주행심사 정보를 유지한다. 거리 변경 방향별 이력도 표본 수와 함께 입력하며 적은 사례로 고정된 전략을 단정하지 않는다.', '',
        '거리/등급/경력/연장·단축별 결과를CSV에 보존했다. 원천 DB·운영 등록부·v4 입력·정답을 유지한다. 현재 출전표·기수·게이트는 결과표 기반 대리값이며 사전 공개 시점 검증은 아직이다. 최종 입상·삼복승 개선은 별도로 검증해야 한다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'train'])
    args = parser.parse_args()
    {'prepare': prepare, 'train': train}[args.mode]()
