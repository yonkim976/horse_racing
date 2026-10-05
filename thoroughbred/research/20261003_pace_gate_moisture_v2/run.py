"""Frozen four-way retrospective pace comparison; no production writes."""
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
PACE_PATH = HERE.parent / '20261003_pace_v1'
ENV_PATH = HERE.parent / '20261002_moisture_distance_retrain'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PACE = module('pace_v2_parent', PACE_PATH / 'run.py')
BASE = PACE.BASE
ENV = module('pace_v2_environment', ENV_PATH / 'analyze.py')
KEY = BASE.KEY
GATE_COLUMNS = ['gate_number_proxy', 'gate_fraction_proxy', 'gate_inner_proxy',
                'gate_outer_proxy', 'gate_style_interaction']
GATE_RACE_COLUMNS = ['gate_fast3_mean', 'gate_time_covariance',
                     'gate_forward_inner_count', 'gate_forward_outer_count']
MOISTURE_COLUMNS = ['last_record_index', 'last3_record_index_mean',
                    'last5_record_index_mean', 'last10_record_index_mean',
                    'last5_record_index_best', 'last10_record_index_best',
                    'last5_record_index_count', 'last10_record_index_count',
                    'last5_record_index_std', 'record_index_change',
                    'same_distance_last_finish', 'same_distance_last5_finish_mean',
                    'relative_last3_record_index_mean']


def cfg():
    return json.loads((HERE / 'config.json').read_text())


def read_context(db):
    with duckdb.connect(str(db), read_only=True) as conn:
        context = conn.execute("""
          SELECT cast(source_meet as int) meet,
            strptime(result_date_key,'%Y%m%d')::DATE race_date,
            cast(result_race_no_key as int) race_no,
            try_cast(regexp_extract(actual_track_condition_raw,
              '([0-9]+)\\s*%',1) as double) moisture
          FROM confirmed_races WHERE source_meet IN ('1','3')
        """).fetchdf()
        card = conn.execute("""
          SELECT cast(source_meet as int) meet,
            strptime(result_date,'%Y%m%d')::DATE race_date,
            cast(result_race_no as int) race_no,
            max(try_cast(horse_program_no_raw as int)) card_max_number
          FROM confirmed_runners WHERE source_meet IN ('1','3') GROUP BY ALL
        """).fetchdf()
    context['race_date'] = pd.to_datetime(context.race_date)
    card['race_date'] = pd.to_datetime(card.race_date)
    context = context.merge(card, on=['meet', 'race_date', 'race_no'], validate='one_to_one')
    context['race_key'] = (context.meet.astype(str) + ':' + context.race_date.dt.strftime('%Y%m%d')
                           + ':' + context.race_no.astype(str))
    context['year'], context['month'] = context.race_date.dt.year, context.race_date.dt.month
    context['day_key'] = context.meet.astype(str) + ':' + context.race_date.dt.strftime('%Y%m%d')
    context['band'] = pd.cut(context.moisture, [0, 5, 9, 14, 19, np.inf],
                             labels=['건조', '양호', '다습', '포화', '불량']).astype('object')
    return context


def add_gate(frame, context):
    f = frame.merge(context[['race_key', 'card_max_number']], on='race_key', validate='many_to_one')
    f['gate_number_proxy'] = f.program_no.astype(float)
    f['gate_fraction_proxy'] = (f.program_no - 1) / (f.card_max_number - 1)
    if not f.gate_fraction_proxy.between(0, 1).all():
        raise ValueError('Invalid gate proxy')
    f['gate_inner_proxy'] = f.gate_fraction_proxy.lt(1 / 3).astype(float)
    f['gate_outer_proxy'] = f.gate_fraction_proxy.ge(2 / 3).astype(float)
    f['gate_style_interaction'] = f.gate_fraction_proxy * f.pace_last3_S1F_fraction
    f['gate_zone_proxy'] = np.where(f.gate_inner_proxy.eq(1), 'inner',
                                   np.where(f.gate_outer_proxy.eq(1), 'outer', 'middle'))
    return f


def add_race_gate(r, f):
    rows = []
    for key, one in f.groupby('race_key', sort=False):
        valid = one[one.pace_last3_historical_start_time.notna()]
        time = valid.pace_last3_historical_start_time.to_numpy(float)
        gate = valid.gate_fraction_proxy.to_numpy(float)
        covariance = np.mean((time - time.mean()) * (gate - gate.mean())) if len(time) > 1 else np.nan
        fastest = valid.nsmallest(3, 'pace_last3_historical_start_time')
        rows.append({'race_key': key,
                     'gate_fast3_mean': float(fastest.gate_fraction_proxy.mean()) if len(valid) >= 3 else np.nan,
                     'gate_time_covariance': covariance,
                     'gate_forward_inner_count': int((one.gate_inner_proxy.eq(1) & one.pace_last3_S1F_front.ge(.5)).sum()),
                     'gate_forward_outer_count': int((one.gate_outer_proxy.eq(1) & one.pace_last3_S1F_front.ge(.5)).sum())})
    return r.merge(pd.DataFrame(rows), on='race_key', validate='one_to_one')


def estimate_effects(starters, context, residuals, c):
    """Only years before each observed record supply coefficients and support."""
    events = starters.drop_duplicates('race_key')[['race_key', 'meet', 'race_date', 'result_distance']]
    events = events.merge(context[['race_key', 'year', 'month', 'race_no', 'day_key', 'band']],
                          on='race_key', validate='one_to_one').rename(columns={'result_distance': 'distance_m'})
    residuals = residuals[residuals.part.eq('finish')].copy()
    rows, fits = [], []
    for (meet, year), one in events.groupby(['meet', 'year'], sort=True):
        train = residuals[residuals.meet.eq(meet) & residuals.year.lt(year)].copy()
        one = one.copy()
        one['effect_seconds'] = np.nan
        one['environment_trained_through'] = np.nan
        one['band_days'] = 0
        one['dry_days'] = 0
        if len(train) >= 100:
            if train.year.max() >= year:
                raise ValueError('Environment future leakage')
            cells = train.groupby(['distance_m', 'band']).day_key.nunique()
            actual = one[one.band.notna()].copy()
            if not actual.empty:
                model = ENV.environment_model(ENV.interaction(train), 'distance')
                dry = actual.assign(band='건조')
                delta = model.predict(ENV.interaction(actual)) - model.predict(ENV.interaction(dry))
                one.loc[actual.index, 'effect_seconds'] = delta
                one.loc[actual.index, 'environment_trained_through'] = int(train.year.max())
            one['band_days'] = [int(cells.get((d, b), 0)) for d, b in zip(one.distance_m, one.band)]
            one['dry_days'] = [int(cells.get((d, '건조'), 0)) for d in one.distance_m]
            fits.append({'meet': int(meet), 'source_year': int(year), 'training_end': int(train.year.max()),
                         'training_races': len(train), 'training_days': int(train.day_key.nunique())})
        one['supported'] = (one.effect_seconds.notna() & one.distance_m.isin(c['moisture_distances'][str(meet)])
                             & one.band_days.ge(c['minimum_moisture_reference_days'])
                             & one.dry_days.ge(c['minimum_moisture_reference_days']))
        one['correction_seconds'] = -c['moisture_rates'][str(meet)] * one.effect_seconds.where(one.supported, 0)
        rows.append(one)
    return pd.concat(rows, ignore_index=True), fits


def correct_records(starters, effects):
    s = starters.merge(effects[['race_key', 'correction_seconds', 'supported']], on='race_key', validate='many_to_one')
    s['original_finish_valid'] = s.finish_valid
    s['finish_valid'] = s.finish_valid + s.correction_seconds
    s['record_index'] = np.nan
    references = []
    for year in sorted(s.year.unique()):
        prior = s[s.year.lt(year) & s.finish_valid.notna()]
        stats = prior.groupby(['meet', 'result_distance']).finish_valid.agg(['count', 'median'])
        mad = prior.groupby(['meet', 'result_distance']).finish_valid.agg(lambda x: np.median(np.abs(x - np.median(x))))
        stats['scale'] = np.maximum(.5, 1.4826 * mad)
        stats = stats[stats['count'].ge(50)]
        current = s[s.year.eq(year)].merge(stats, left_on=['meet', 'result_distance'], right_index=True, how='left')
        s.loc[current.index, 'record_index'] = ((current['median'] - current.finish_valid) / current.scale).clip(-10, 10)
        references.append(stats.reset_index().assign(source_year=year, trained_through=year - 1))
    return s, pd.concat(references, ignore_index=True)


def input_paths(c):
    return [ROOT / c['source_db'], ROOT / 'config/prediction_model_registry.json',
            ROOT / c['race_residuals'], HERE / 'PLAN.md', HERE / 'config.json', HERE / 'run.py',
            PACE_PATH / 'run.py', PACE.BASE_PATH / 'run.py', ENV_PATH / 'analyze.py', ENV.BASE.HERE / 'analyze.py',
            *[PACE_PATH / 'outputs' / n for n in ['features.parquet', 'labels.parquet', 'feature_contract.json',
                'race_features.parquet', 'race_labels.parquet', 'runner_predictions.parquet', 'point_metrics.csv',
                'tempo_predictions.csv', 'summary.json']]]


def prepare():
    c = cfg()
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite outputs')
    inputs = {str(p.relative_to(ROOT)): BASE.sha(p) for p in input_paths(c)}
    old = json.loads((PACE_PATH / 'outputs/data_audit.json').read_text())
    if inputs[c['source_db']] != old['source_sha256']:
        raise ValueError('Source differs from v1')
    OUT.mkdir()
    raw = pd.read_parquet(PACE_PATH / 'outputs/features.parquet')
    context = read_context(ROOT / c['source_db'])
    raw = add_gate(raw, context)
    source, _ = BASE.read_source(ROOT / c['source_db'])
    starters, _, _ = BASE.prepare_records(source)
    effects, fits = estimate_effects(starters, context, pd.read_parquet(ROOT / c['race_residuals']), c)
    adjusted, references = correct_records(starters, effects)
    corrected, _ = BASE.build_features(adjusted, c['history_lag_days'])
    corrected = raw[KEY].merge(corrected[KEY + MOISTURE_COLUMNS], on=KEY, validate='one_to_one')
    moisture = raw.copy()
    for col in MOISTURE_COLUMNS:
        moisture[col] = corrected[col]
    labels = pd.read_parquet(PACE_PATH / 'outputs/labels.parquet')
    rf = add_race_gate(pd.read_parquet(PACE_PATH / 'outputs/race_features.parquet'), raw)
    rl = pd.read_parquet(PACE_PATH / 'outputs/race_labels.parquet')
    for name, frame in [('raw_features', raw), ('moisture_features', moisture), ('labels', labels),
                         ('race_features', rf), ('race_labels', rl), ('effects', effects),
                         ('adjusted_records', adjusted[KEY + ['meet', 'race_date', 'year', 'result_distance',
                             'original_finish_valid', 'finish_valid', 'record_index', 'supported', 'correction_seconds']])]:
        frame.to_parquet(OUT / (name + '.parquet'), index=False)
    references.to_csv(OUT / 'record_references.csv', index=False)
    effects.groupby(['meet', 'year', 'band'], dropna=False).agg(
        races=('race_key', 'size'), supported=('supported', 'sum'), mean_correction=('correction_seconds', 'mean')).to_csv(OUT / 'correction_coverage.csv')
    changes = []
    for col in MOISTURE_COLUMNS:
        different = ~np.isclose(raw[col].to_numpy(float), moisture[col].to_numpy(float), equal_nan=True)
        for (meet, year), idx in raw.groupby(['meet', 'year']).indices.items():
            changes.append({'column': col, 'meet': int(meet), 'year': int(year),
                            'runners': len(idx), 'changed': int(different[idx].sum())})
    pd.DataFrame(changes).to_csv(OUT / 'feature_changes.csv', index=False)
    contract = json.loads((PACE_PATH / 'outputs/feature_contract.json').read_text())
    BASE.save_json(OUT / 'feature_contract.json', {'runner': contract['runner'], 'race': contract['race'],
                                                   'gate_runner': GATE_COLUMNS, 'gate_race': GATE_RACE_COLUMNS,
                                                   'moisture_replaced': MOISTURE_COLUMNS})
    BASE.save_json(OUT / 'environment_fits.json', fits)
    audit = {'inputs': inputs, 'source_db': str(ROOT / c['source_db']), 'runners': len(raw),
             'races': raw.race_key.nunique(), 'code_sha256': BASE.sha(__file__),
             'prepared_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()},
             'production_changed': False, 'final_finish_model_changed': False}
    BASE.save_json(OUT / 'data_audit.json', audit)
    print(json.dumps({'runners': len(raw), 'races': audit['races'], 'environment_fits': len(fits)}), flush=True)


def check_inputs():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    for name, digest in audit['inputs'].items():
        if BASE.sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    for name, digest in audit['prepared_hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Prepared input changed: ' + name)
    return audit


def train():
    c = cfg()
    check_inputs()
    (OUT / 'models').mkdir(exist_ok=False)
    labels = pd.read_parquet(OUT / 'labels.parquet')
    frames = {name: pd.read_parquet(OUT / (name + '_features.parquet')).merge(labels, on=KEY, validate='one_to_one')
              for name in ['raw', 'moisture']}
    rf = pd.read_parquet(OUT / 'race_features.parquet').merge(pd.read_parquet(OUT / 'race_labels.parquet'), on='race_key', validate='one_to_one')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    def inherited(file):
        frame = pd.read_parquet(PACE_PATH / 'outputs' / file) if file.endswith('.parquet') else pd.read_csv(PACE_PATH / 'outputs' / file)
        return frame[frame.variant.eq('field_model')].assign(variant='raw')
    runners = [inherited('runner_predictions.parquet')]
    points = [inherited('point_metrics.csv')]
    base_tempo = inherited('tempo_predictions.csv')
    tempos = [base_tempo, base_tempo.assign(variant='moisture')]
    bundles = []
    for meet in c['venues']:
        for year in c['evaluation_years']:
            for variant in ['gate', 'moisture', 'both']:
                one = frames['moisture' if variant in ['moisture', 'both'] else 'raw']
                one = one[one.meet.eq(meet)].reset_index(drop=True)
                columns = contract['runner'] + (contract['gate_runner'] if variant in ['gate', 'both'] else [])
                dest = OUT / 'models' / f'{meet}_{year}_{variant}'
                dest.mkdir()
                bundle = {'meet': meet, 'year': year, 'variant': variant, 'models': [], 'point_temperatures': {}}
                print(f'Training meet={meet} year={year} variant={variant}', flush=True)
                for point in c['points']:
                    predictions, meta = PACE.fit_regression(one, columns, point + '_fraction',
                        one[point + '_complete'], year, c, dest / (point + '.txt'), race_weight=True)
                    a, b, temperatures = PACE.point_evaluation(one, point, predictions, year, variant, c)
                    runners.append(pd.DataFrame(a)); points.append(pd.DataFrame(b))
                    bundle['models'].append(meta); bundle['point_temperatures'][point] = temperatures
                if variant == 'gate':
                    races = rf[rf.meet.eq(meet)].reset_index(drop=True)
                    predictions, meta = PACE.fit_regression(races, contract['race'] + contract['gate_race'],
                        'tempo_time', races.tempo_complete, year, c, dest / 'tempo.txt')
                    rows, calibration = PACE.tempo_evaluation(races, predictions, year, variant, c)
                    tempo = pd.DataFrame(rows)
                    tempos.extend([tempo, tempo.assign(variant='both')])
                    bundle['models'].append(meta); bundle['tempo'] = calibration
                BASE.save_json(dest / 'metadata.json', bundle)
                bundles.append(bundle)
                print(f'Evaluated meet={meet} year={year} variant={variant}', flush=True)
    rp, rm, tp = pd.concat(runners, ignore_index=True), pd.concat(points, ignore_index=True), pd.concat(tempos, ignore_index=True)
    rp.to_parquet(OUT / 'runner_predictions.parquet', index=False)
    rm.to_csv(OUT / 'point_metrics.csv', index=False)
    tp.to_csv(OUT / 'tempo_predictions.csv', index=False)
    metrics = ['fraction_mae', 'position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'leader_nll', 'ordered_top3_nll', 'top3_brier']
    rows = []
    for (meet, point, variant), one in rm.groupby(['meet', 'point', 'variant']):
        for period, sample in [('all', one), *[(str(y), group) for y, group in one.groupby('year')]]:
            rows.append({'meet': int(meet), 'point': point, 'variant': variant, 'period': period,
                         'races': len(sample), **{m: float(sample[m].mean()) for m in metrics}})
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / 'metrics.csv', index=False)
    tempo_summary = tp.groupby(['meet', 'year', 'variant']).agg(races=('race_key', 'size'),
        time_mae=('absolute_error', 'mean'), class_hit=('class_hit', 'mean'), classified_races=('class_hit', 'count')).reset_index()
    tempo_summary.to_csv(OUT / 'tempo_metrics.csv', index=False)
    sensitivity(rp, frames['raw'], rm, c)
    differences = paired_differences(rm, c)
    BASE.save_json(OUT / 'paired_differences.json', differences)
    BASE.save_json(OUT / 'summary.json', {'experiment': c['experiment'], 'models': bundles,
        'metrics': summary.to_dict('records'), 'tempo_metrics': tempo_summary.to_dict('records'),
        'production_changed': False, 'final_finish_model_changed': False,
        'result_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()}})
    report(summary, tempo_summary, differences)
    print('Completed ' + str(OUT / 'REPORT.md'), flush=True)


def paired_differences(metrics, c):
    rng = np.random.default_rng(c['seed'])
    rows = []
    for (meet, point), one in metrics.groupby(['meet', 'point']):
        for base, variant in [('raw', 'gate'), ('raw', 'moisture'), ('raw', 'both'), ('gate', 'both')]:
            pair = one[one.variant.eq(base)].merge(one[one.variant.eq(variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
            for metric in ['fraction_mae', 'position_mae', 'leader_hit', 'top3_brier']:
                delta = pair[metric + '_new'] - pair[metric + '_base']
                groups = pd.DataFrame({'day': pair.race_date_base, 'delta': delta}).groupby('day').delta.agg(['sum', 'size']).to_numpy()
                draws = groups[rng.integers(0, len(groups), (c['bootstrap_draws'], len(groups)))]
                bounds = np.quantile(draws[:, :, 0].sum(axis=1) / draws[:, :, 1].sum(axis=1), [.025, .975])
                rows.append({'meet': int(meet), 'point': point, 'base': base, 'variant': variant, 'metric': metric,
                             'races': len(pair), 'delta': float(delta.mean()), 'ci95': bounds.tolist()})
    return rows


def sensitivity(predictions, frame, metrics, c):
    contextual = frame[KEY + ['distance_m', 'gate_zone_proxy']]
    p = predictions.merge(contextual, on=KEY, validate='many_to_one')
    p['position_error'] = abs(p.expected_position - p.actual_rank)
    for name in ['distance_m', 'gate_zone_proxy']:
        p.groupby(['meet', 'year', 'point', 'variant', name]).agg(
            runners=('horse_id', 'size'), position_mae=('position_error', 'mean')).to_csv(OUT / (name + '_sensitivity.csv'))
    # Error conditional on a horse's start draw; not race-level leader hit per zone.


def report(summary, tempo, differences):
    names = {'raw': '기존 v1', 'gate': '게이트 추가', 'moisture': '전체기록 함수율 보정', 'both': '둘 다'}
    lines = ['# 전개 v2 — 게이트·함수율 동일 경주 비교', '',
        '2010–2016 warm-up, 학습2017+, 평가2024–2026. 이미 관찰한 자료의 시간순 후향 비교다. 게이트는 출발 마번 대리변수이며 실제 주행 내외측 위치는 입력하지 않았다. 함수율은 과거 전체 주파기록만 건조 기준으로 환산했다.', '',
        '| 장소 | 지점 | 입력 | 경주 | 순위 MAE ↓ | 통과1위 선택 | 상위3두 전부 | Brier ↓ |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for _, r in summary[summary.period.eq('all')].sort_values(['meet', 'point', 'variant']).iterrows():
        lines.append(f'| { {1:"서울",3:"부산"}[r.meet]} | {r.point} | {names[r.variant]} | {r.races:,} | {r.position_mae:.4f}두 | {r.leader_hit:.2%} | {r.top3_exact_hit:.2%} | {r.top3_brier:.5f} |')
    lines += ['', '## 같은 경주일 비교', '',
        '아래는 변경−기준. 오차/Brier는 음수, 통과1위 적중은 양수가 개선이다. 날짜 bootstrap 구간은 계수 추정오차·장기 날짜 의존성·여러 비교의 다중성을 완전히 반영하지 않는 보조 구간이다.', '',
        '| 장소 | 지점 | 비교 | 지표 | 차이 | 95% 구간 |', '|---|---|---|---|---:|---|']
    for d in differences:
        if d['metric'] not in ['position_mae', 'leader_hit']:
            continue
        lo, hi = d['ci95']
        lines.append(f'| { {1:"서울",3:"부산"}[d["meet"]]} | {d["point"]} | {names[d["variant"]]}−{names[d["base"]]} | {d["metric"]} | {d["delta"]:+.5f} | {lo:+.5f} ~ {hi:+.5f} |')
    lines += ['', '## 초반시간', '', '전체기록 보정은 초반시간 branch의 입력을 바꾸지 않으므로 기존=함수율, 게이트=둘 다가 동일하다. 빠름/보통/느림은 이전 보정연도의 거리별 분위수 기준이며 현재 함수율을 알았다고 가정하지 않는다.', '',
        '| 장소 | 연도 | 입력 | 경주 | 시간 MAE | 분류 적중 |', '|---|---:|---|---:|---:|---:|']
    for _, r in tempo[tempo.variant.isin(['raw', 'gate'])].iterrows():
        lines.append(f'| { {1:"서울",3:"부산"}[r.meet]} | {r.year} | {names[r.variant]} | {r.races:,} | {r.time_mae:.4f}초 | {r.class_hit:.2%} |')
    lines += ['', '## 해석과 한계', '',
        '함수율 계수는 기존 말별 극단잔차 제외 자산을 재사용해 매 관측연도 이전 자료로 적합했다. 자산 시작2020, 최초계수2021. 서울80%·부산90%, 합의 거리 및 거리별 조건/건조 각각20일 지원을 적용했다. 부족하거나 없는 계수는 원기록을 유지했으며 0효과로 판정하지 않는다. 지원 범위는 correction_coverage.csv, 실제 피처 변경은 feature_changes.csv에서 확인한다.', '',
        '출발/막판 구간은 원기록이며, 환산된 전체시간에서 구간을 역산하지 않았다. 현재 실제 통과순위·횡방향 위치·함수율은 입력하지 않았다. 당일 취소 시점/실제 발주대/사전 공개시점은 증명되지 않아 결과 편성 조건부 연구다.', '',
        '삼복승 적중 개선은 아직 측정한 결과가 아니다. 연결하려면 학습자료에도 이전 날짜만으로 만든 전개 예측을 생성하고 입상모델을 재학습해 같은6조합 기준으로 검증해야 한다. 운영 등록부·기존 모델은 그대로다.', '',
        '연도별 metrics.csv, 거리/게이트 구간 민감도, paired_differences.json, environment_fits.json, 독립검증 verification.json을 함께 보존한다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'train'])
    args = parser.parse_args()
    {'prepare': prepare, 'train': train}[args.mode]()
