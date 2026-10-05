"""Frozen, annual external pace predictions stacked into joint podium models."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PARENT = HERE.parent / '20261004_pace_context_v5'
SPEC = importlib.util.spec_from_file_location('finish_stack_pace_v5', PARENT / 'run.py')
V5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V5)
BASE, PACE, V4, KEY = V5.BASE, V5.PACE, V5.V4, V5.KEY
BASE_PATH = PACE.BASE_PATH


def cfg():
    return json.loads((HERE / 'config.json').read_text())


def variants(meet, c):
    return c['variants'] + ([c['busan_extra_variant']] if meet == 3 else [])


def prediction_columns():
    cols = ['stack_pace_available']
    for point in ['S1F', 'G3F']:
        cols += ['stack_' + point + '_' + stem for stem in
                 ['fraction', 'position', 'lead', 'front3', 'lead_entropy', 'lead_margin']]
    return cols + ['stack_advance']


def leader_columns():
    return ['stack_direct_available', 'stack_direct_lead', 'stack_direct_entropy', 'stack_direct_margin']


def forbidden_columns():
    return {'outcome', 'S1F_rank', 'G3F_rank', 'S1F_fraction', 'G3F_fraction', 'S1F_complete',
            'G3F_complete', 'tempo_complete', 'historical_start_time', 'slow_label', 'risk_eligible',
            'direct_target', 'horse_id', 'jockey_id', 'race_date', 'year', 'program_no', 'race_key'}


def prepare():
    c = cfg()
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite experiment')
    V5.check_inputs()
    paths = [ROOT / c['source_db'], ROOT / 'config/prediction_model_registry.json', HERE / 'run.py',
             HERE / 'config.json', HERE / 'PLAN.md']
    for folder in [PARENT, V5.PARENT, V4.PARENT, V5.V3.V2_PATH, PACE.HERE, BASE_PATH]:
        paths.append(folder / 'run.py')
    for folder, names in [(PARENT, ['features.parquet', 'labels.parquet', 'feature_contract.json', 'summary.json']),
                          (BASE_PATH, ['features.parquet', 'labels.parquet', 'feature_contract.json',
                                       'runner_predictions.parquet', 'race_metrics.csv', 'summary.json'])]:
        paths += [folder / 'outputs' / name for name in names]
    paths += list((PARENT / 'outputs/models').glob('*/metadata.json'))
    paths += list((PARENT / 'outputs/models').glob('*/*.txt'))
    paths += list((BASE_PATH / 'outputs/models').glob('*_history_records/metadata.json'))
    paths += list((BASE_PATH / 'outputs/models').glob('*_history_records/*.txt'))
    hashes = {str(p.relative_to(ROOT)): BASE.sha(p) for p in paths}
    f = pd.read_parquet(PARENT / 'outputs/features.parquet')
    base_f = pd.read_parquet(BASE_PATH / 'outputs/features.parquet')
    joined = f[KEY].merge(base_f, on=KEY, validate='one_to_one')
    pd.testing.assert_frame_equal(f[base_f.columns], joined[base_f.columns], check_exact=True)
    targets = pd.read_parquet(BASE_PATH / 'outputs/labels.parquet')
    if set(map(tuple, f[KEY].to_numpy())) != set(map(tuple, targets[KEY].to_numpy())):
        raise ValueError('Different podium keyset')
    contract = json.loads((PARENT / 'outputs/feature_contract.json').read_text())
    records = json.loads((BASE_PATH / 'outputs/feature_contract.json').read_text())['history_records']
    context = contract['base'] + contract['distance'] + contract['context']
    contracts = {'records': records, 'context': context, 'context_pace': context + prediction_columns(),
                 'context_pace_leader': context + prediction_columns() + leader_columns()}
    for cols in contracts.values():
        if set(cols) & forbidden_columns() or len(set(cols)) != len(cols):
            raise ValueError('Invalid feature contract')
    OUT.mkdir()
    f.to_parquet(OUT / 'raw_features.parquet', index=False)
    targets.to_parquet(OUT / 'labels.parquet', index=False)
    BASE.save_json(OUT / 'feature_contract.json', contracts)
    BASE.save_json(OUT / 'data_audit.json', {'inputs': hashes, 'rows': len(f), 'races': f.race_key.nunique(),
        'prepared_hashes': {p.name: BASE.sha(p) for p in OUT.iterdir() if p.is_file()},
        'production_changed': False, 'publication_timestamps_verified': False})
    print(f'Prepared {len(f):,} rows, {f.race_key.nunique():,} races', flush=True)


def check_inputs():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    for name, digest in audit['inputs'].items():
        if BASE.sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed ' + name)
    for name, digest in audit['prepared_hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Prepared input changed ' + name)
    return audit


def encoded(frame, model):
    x = frame[model['columns']].copy()
    for col, vocabulary in model['vocabulary'].items():
        x[col] = pd.Categorical(x[col], categories=vocabulary)
    return x


def chronology(frame, year, meta):
    train_end, cal_year = meta['training_year_end'], meta['calibration_year']
    if train_end != year - 2 or cal_year != year - 1:
        raise ValueError('Incorrect annual upstream split')
    train = frame[frame.year.between(2017, train_end)]
    cal = frame[frame.year.eq(cal_year)]
    test = frame[frame.year.eq(year)]
    if train.empty or cal.empty or test.empty:
        raise ValueError('Empty upstream split')
    if cal.race_date.max() > test.race_date.min() - pd.Timedelta(days=2):
        raise ValueError('Annual model unavailable at prediction cutoff')
    return {'training_max_date': str(train.race_date.max().date()),
            'calibration_max_date': str(cal.race_date.max().date()),
            'prediction_min_date': str(test.race_date.min().date())}


def race_probabilities(frame, raw, temperatures, prefix, regression):
    result = frame[KEY].copy()
    for stem in ['fraction', 'position', 'lead', 'front3', 'lead_entropy', 'lead_margin']:
        result[prefix + stem] = np.nan
    for _, idx in frame.groupby('race_key', sort=False).indices.items():
        n = len(idx)
        score = -raw[idx] if regression else raw[idx]
        _, _, margins = BASE.joint(np.repeat(score[:, None], 3, axis=1), temperatures)
        lead, front = margins[:, 0], margins[:, 2]
        entropy = -np.sum(lead * np.log(np.clip(lead, 1e-15, 1))) / np.log(n)
        other_best = np.array([np.max(np.delete(lead, k)) for k in range(n)])
        result.loc[idx, prefix + 'lead'] = lead
        result.loc[idx, prefix + 'front3'] = front
        result.loc[idx, prefix + 'lead_entropy'] = entropy
        result.loc[idx, prefix + 'lead_margin'] = lead - other_best
        if regression:
            result.loc[idx, prefix + 'fraction'] = np.clip(raw[idx], 0, 1)
            result.loc[idx, prefix + 'position'] = 1 + np.clip(raw[idx], 0, 1) * (n - 1)
    return result


def upstream_bundle(one, year, variant, c):
    pc = V5.cfg()
    contract = json.loads((PARENT / 'outputs/feature_contract.json').read_text())
    if year in pc['evaluation_years']:
        path = PARENT / 'outputs/models' / f'{int(one.meet.iloc[0])}_{year}_{variant}'
        bundle = json.loads((path / 'metadata.json').read_text())
        return path, bundle, True
    path = OUT / 'pace_models' / f'{int(one.meet.iloc[0])}_{year}_{variant}'
    if (path / 'metadata.json').exists():
        meta = json.loads((path / 'metadata.json').read_text())
        for name, digest in meta['model_hashes'].items():
            if BASE.sha(path / name) != digest:
                raise ValueError('Changed completed upstream bundle')
        return path, meta, False
    if path.exists():
        raise FileExistsError('Incomplete upstream bundle')
    path.mkdir(parents=True)
    cols = contract['base'] + contract['distance'] + (contract['context'] if variant == 'context' else [])
    bundle = {'meet': int(one.meet.iloc[0]), 'year': year, 'variant': variant, 'models': [], 'temperatures': {}}
    if variant == 'distance':
        for point in ['S1F', 'G3F']:
            raw, model = PACE.fit_regression(one, cols, point + '_fraction', one[point + '_complete'],
                                            year, pc, path / (point + '.txt'), race_weight=True)
            bundle['models'].append(model)
            bundle['temperatures'][point] = V4.temperatures(one, point, -raw, year,
                                                          {**pc, 'temperature_bounds': [.02, 1.]})
    else:
        work = one.assign(direct_target=one.S1F_rank.eq(1).fillna(False).astype(int))
        raw, model = V4.fit_binary(work, cols, 'direct_target', work.S1F_complete, year, pc, path / 'leader.txt')
        bundle['models'].append(model)
        bundle['temperatures']['leader'] = V4.temperatures(one, 'S1F', raw, year, pc)
    bundle['model_hashes'] = {p.name: BASE.sha(p) for p in path.glob('*.txt')}
    BASE.save_json(path / 'metadata.json', bundle)
    return path, bundle, False


def pace():
    c = cfg()
    check_inputs()
    if (OUT / 'stack_audit.json').exists():
        raise FileExistsError('Completed stack exists')
    f = pd.read_parquet(OUT / 'raw_features.parquet')
    labels = pd.read_parquet(PARENT / 'outputs/labels.parquet')
    work = f.merge(labels, on=KEY, validate='one_to_one')
    predictions, ledger = [], []
    for meet in c['venues']:
        one = work[work.meet.eq(meet)].reset_index(drop=True)
        for year in range(c['pace_prediction_start_year'], max(c['evaluation_years']) + 1):
            test = one[one.year.eq(year)].reset_index(drop=True)
            result = test[KEY + ['meet', 'race_date', 'year']].copy()
            print(f'External pace meet={meet}, year={year}', flush=True)
            for variant in ['distance'] + (['context'] if meet == 3 else []):
                path, bundle, reused = upstream_bundle(one, year, variant, c)
                for kind in (['S1F', 'G3F'] if variant == 'distance' else ['leader']):
                    meta = next(m for m in bundle['models'] if m['file'] == kind + '.txt')
                    dates = chronology(one, year, meta)
                    model = lgb.Booster(model_file=str(path / meta['file']))
                    raw = model.predict(encoded(test, meta), raw_score=kind == 'leader')
                    prefix = 'stack_' + kind + '_' if kind != 'leader' else 'stack_direct_'
                    prob = race_probabilities(test, raw, bundle['temperatures'][kind], prefix, kind != 'leader')
                    if kind == 'leader':
                        prob = prob.rename(columns={'stack_direct_lead_entropy': 'stack_direct_entropy',
                                                    'stack_direct_lead_margin': 'stack_direct_margin'})
                        prob = prob[KEY + leader_columns()[1:]]
                    result = result.merge(prob, on=KEY, validate='one_to_one')
                    ledger.append({'meet': meet, 'prediction_year': year, 'kind': kind, 'variant': variant,
                        'path': str(path.relative_to(ROOT)), 'model_file': meta['file'],
                        'model_sha256': BASE.sha(path / meta['file']), 'metadata_sha256': BASE.sha(path / 'metadata.json'),
                        'reused_v5': reused, 'training_year_end': meta['training_year_end'],
                        'calibration_year': meta['calibration_year'], 'temperatures': bundle['temperatures'][kind], **dates})
            result['stack_pace_available'] = 1.
            result['stack_direct_available'] = float(meet == 3)
            result['stack_advance'] = result.stack_S1F_fraction - result.stack_G3F_fraction
            predictions.append(result)
    pred = pd.concat(predictions, ignore_index=True)
    merged = f.merge(pred[KEY + prediction_columns() + leader_columns()], on=KEY, how='left', validate='one_to_one')
    for col in ['stack_pace_available', 'stack_direct_available']:
        merged[col] = merged[col].fillna(0.)
    merged.to_parquet(OUT / 'features.parquet', index=False)
    pred.to_parquet(OUT / 'external_pace_predictions.parquet', index=False)
    pd.DataFrame(ledger).to_json(OUT / 'pace_model_ledger.json', orient='records', indent=2)
    merged.groupby(['meet', 'year']).agg(runners=('horse_id', 'size'),
        pace_available=('stack_pace_available', 'sum'), direct_available=('stack_direct_available', 'sum')).to_csv(OUT / 'stack_coverage.csv')
    files = ['features.parquet', 'external_pace_predictions.parquet', 'pace_model_ledger.json', 'stack_coverage.csv']
    BASE.save_json(OUT / 'stack_audit.json', {'hashes': {name: BASE.sha(OUT / name) for name in files},
        'external_predictions': len(pred), 'models': len(ledger), 'early_missing_years': [2017, 2018, 2019]})
    print(f'External pace complete: {len(pred):,} rows, {len(ledger)} model heads', flush=True)


def check_stack():
    check_inputs()
    audit = json.loads((OUT / 'stack_audit.json').read_text())
    for name, digest in audit['hashes'].items():
        if BASE.sha(OUT / name) != digest:
            raise ValueError('Changed stacked input ' + name)
    for item in json.loads((OUT / 'pace_model_ledger.json').read_text()):
        path = ROOT / item['path']
        if BASE.sha(path / item['model_file']) != item['model_sha256'] or BASE.sha(path / 'metadata.json') != item['metadata_sha256']:
            raise ValueError('Changed upstream model')


def recommendations(frame, scores, temps, variant, year):
    rows = []
    for key, one in frame.groupby('race_key', sort=False):
        ix, q, margins = BASE.joint(scores[one.index], temps)
        _, trios, _, _, probabilities = BASE.pool_probabilities(ix, q, len(one))
        chosen = np.argsort(-probabilities, kind='stable')[:6]
        top = np.argsort(-margins[:, 2], kind='stable')
        truth = set(np.flatnonzero(one.outcome.le(3).to_numpy()))
        for rank, loc in enumerate(chosen, 1):
            combo = trios[loc]
            rows.append({'race_key': key, 'meet': int(one.meet.iloc[0]), 'evaluation_year': year,
                'variant': variant, 'selection_rank': rank,
                'programs': ','.join(map(str, sorted(one.program_no.iloc[combo].astype(int)))),
                'horse_ids': ','.join(sorted(one.horse_id.iloc[combo])), 'probability': float(probabilities[loc]),
                'hit': int(set(combo) == truth), 'axis_program': int(one.program_no.iloc[top[0]])})
    return pd.DataFrame(rows)


def train():
    c = cfg()
    check_stack()
    if (OUT / 'summary.json').exists():
        raise FileExistsError('Completed finish experiment')
    f = pd.read_parquet(OUT / 'features.parquet').merge(pd.read_parquet(OUT / 'labels.parquet'), on=KEY, validate='one_to_one')
    contract = json.loads((OUT / 'feature_contract.json').read_text())
    old_rp = pd.read_parquet(BASE_PATH / 'outputs/runner_predictions.parquet')
    old_rm = pd.read_csv(BASE_PATH / 'outputs/race_metrics.csv')
    runners = [old_rp[old_rp.variant.eq('history_records')].assign(variant='records')]
    races = [old_rm[old_rm.variant.eq('history_records')].assign(variant='records')]
    recs, fits = [], []
    for meet in c['venues']:
        one = f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            for variant in variants(meet, c):
                print(f'Finish meet={meet}, year={year}, variant={variant}', flush=True)
                if variant == 'records':
                    path = BASE_PATH / 'outputs/models' / f'{meet}_{year}_history_records'
                    meta = json.loads((path / 'metadata.json').read_text())
                    scores = np.zeros((len(one), 3))
                    test = one.year.eq(year)
                    x = one.loc[test, meta['features']].copy()
                    for col, vocab in meta['category_vocabulary'].items():
                        x[col] = pd.Categorical(x[col], categories=vocab)
                    for stage in range(3):
                        scores[test, stage] = lgb.Booster(model_file=str(path / f'position_{stage+1}.txt')).predict(x, raw_score=True)
                    meta = {**meta, 'variant': variant, 'meet': meet, 'path': str(path.relative_to(ROOT)), 'reused': True}
                else:
                    path = OUT / 'models' / f'{meet}_{year}_{variant}'
                    if (path / 'bundle.json').exists():
                        meta = json.loads((path / 'bundle.json').read_text())
                        for name, digest in meta['artifact_hashes'].items():
                            if BASE.sha(path / name) != digest:
                                raise ValueError('Changed finish bundle')
                        runners.append(pd.read_parquet(path / 'runners.parquet'))
                        races.append(pd.read_csv(path / 'races.csv'))
                        recs.append(pd.read_parquet(path / 'recommendations.parquet'))
                        fits.append(meta)
                        continue
                    scores, test, meta = BASE.train_bundle(one, contract[variant], year, c, path)
                    meta = {**meta, 'variant': variant, 'meet': meet, 'path': str(path.relative_to(ROOT)), 'reused': False}
                    rr, rm = BASE.evaluate(one[test], scores, meta['temperatures'], variant, year)
                    rp, race = pd.DataFrame(rr), pd.DataFrame(rm)
                    rp.to_parquet(path / 'runners.parquet', index=False)
                    race.to_csv(path / 'races.csv', index=False)
                    runners.append(rp); races.append(race)
                recommendation = recommendations(one[test], scores, meta['temperatures'], variant, year)
                recs.append(recommendation)
                if variant != 'records':
                    recommendation.to_parquet(path / 'recommendations.parquet', index=False)
                    meta['artifact_hashes'] = {p.name: BASE.sha(p) for p in path.iterdir() if p.is_file()}
                    BASE.save_json(path / 'bundle.json', meta)
                fits.append(meta)
    rp, rm = pd.concat(runners, ignore_index=True), pd.concat(races, ignore_index=True)
    rec = pd.concat(recs, ignore_index=True)
    attributes = f[['race_key', 'distance_m', 'distance_band', 'context_direction', 'history_count']]
    attrs = attributes.groupby('race_key').agg(distance_m=('distance_m', 'first'), distance_band=('distance_band', 'first'),
        extended_present=('context_direction', lambda x: bool(x.eq(1).any())),
        extended_count=('context_direction', lambda x: int(x.eq(1).sum())),
        low_history_present=('history_count', lambda x: bool(x.lt(5).any()))).reset_index()
    rm = rm.merge(attrs, on='race_key', validate='many_to_one')
    rp.to_parquet(OUT / 'runner_predictions.parquet', index=False)
    rm.to_csv(OUT / 'race_metrics.csv', index=False)
    rec.to_parquet(OUT / 'recommendations.parquet', index=False)
    summaries(rm, rp, c)
    files = [p for p in OUT.iterdir() if p.is_file() and p.name != 'summary.json']
    BASE.save_json(OUT / 'summary.json', {'experiment': c['experiment'], 'models': fits,
        'independent_future_test': False, 'production_changed': False,
        'result_hashes': {p.name: BASE.sha(p) for p in files}})
    print('Finish training and comparison complete', flush=True)


def summaries(races, runners, c):
    metrics = [col for col in races if col.endswith(('_nll', '_brier', '_logloss', '_hit')) or col == 'top5_contains_podium']
    rows = []
    for (meet, variant), one in races.groupby(['meet', 'variant']):
        for period, group in [('all', one)] + [(str(y), g) for y, g in one.groupby('evaluation_year')]:
            rows.append({'meet': int(meet), 'variant': variant, 'period': period, 'races': len(group),
                         **{m: float(group[m].mean()) for m in metrics}})
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / 'metrics.csv', index=False)
    for key in ['distance_band', 'grade', 'zero_observed_history_present', 'low_history_present', 'extended_present']:
        group = races.groupby(['meet', 'variant', key], dropna=False)
        result = group[metrics].mean()
        result['races'] = group.size()
        result.to_csv(OUT / (key + '_metrics.csv'))
    calibration = []
    for (meet, variant, year), one in runners.groupby(['meet', 'variant', 'evaluation_year']):
        for target, col in enumerate(['prob_win', 'prob_top2', 'prob_top3'], 1):
            bins = np.minimum((one[col] * 10).astype(int), 9)
            for b, cell in one.groupby(bins):
                calibration.append({'meet': int(meet), 'variant': variant, 'year': int(year), 'target': target,
                    'bin': int(b), 'runners': len(cell), 'mean_probability': float(cell[col].mean()),
                    'hit_rate': float(cell.outcome.le(target).mean())})
    pd.DataFrame(calibration).to_csv(OUT / 'calibration.csv', index=False)
    group = races.groupby(['meet', 'variant', 'evaluation_year'])
    calibration6 = group.agg(races=('race_key', 'size'), mean_probability=('top6_trio_probability', 'mean'),
                             hit_rate=('top6_trio_hit', 'mean'))
    calibration6.to_csv(OUT / 'trio6_calibration.csv')
    differences = []
    rng = np.random.default_rng(c['seed'])
    compare_metrics = ['ordered_top3_nll', 'trio_nll', 'top3_brier', 'top6_trio_hit', 'fixed_axis6_trio_hit',
                       'top3_first_hit', 'top5_contains_podium', 'qnl_first_hit', 'qpl_first_hit']
    for meet in c['venues']:
        pairs = [('records', 'context'), ('context', 'context_pace'), ('records', 'context_pace')]
        if meet == 3:
            pairs += [('context_pace', 'context_pace_leader'), ('records', 'context_pace_leader')]
        for base, candidate in pairs:
            a = races[races.meet.eq(meet) & races.variant.eq(base)]
            b = races[races.meet.eq(meet) & races.variant.eq(candidate)]
            pair = a.merge(b, on='race_key', validate='one_to_one', suffixes=('_base', '_candidate'))
            if len(pair) != len(a) or len(pair) != len(b):
                raise ValueError('Different paired cohort')
            for metric in compare_metrics:
                delta = pair[metric + '_candidate'] - pair[metric + '_base']
                daily = pd.DataFrame({'date': pair.race_date_base, 'delta': delta}).groupby('date').delta.agg(['sum', 'size']).to_numpy()
                picks = rng.integers(0, len(daily), size=(c['bootstrap_draws'], len(daily)))
                sampled = daily[picks]
                intervals = np.quantile(sampled[:, :, 0].sum(axis=1) / sampled[:, :, 1].sum(axis=1), [.025, .975])
                differences.append({'meet': meet, 'base': base, 'candidate': candidate, 'metric': metric,
                    'difference': float(delta.mean()), 'day_cluster_95_ci': intervals.tolist(), 'races': len(pair)})
    BASE.save_json(OUT / 'paired_differences.json', differences)
    names = {1: '서울', 3: '부산'}
    lines = ['# 전개 예측의 입상 연결 비교', '', '같은 입상 모델 구조·표본에서 raw 전개 입력과 시간순 외부 전개 예측의 추가 효과를 분리했다.', '',
        '| 지역 | 후보 | 경주 | 삼복 상위6 | 축 고정6 | 입상1순위 | 상위5두 포함 | 삼복 NLL↓ | Top3 Brier↓ |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in summary[summary.period.eq('all')].itertuples():
        lines.append(f'| {names[r.meet]} | {r.variant} | {r.races} | {r.top6_trio_hit:.2%} | {r.fixed_axis6_trio_hit:.2%} | {r.top3_first_hit:.2%} | {r.top5_contains_podium:.2%} | {r.trio_nll:.5f} | {r.top3_brier:.6f} |')
    lines += ['', '## 연도별', '', '| 지역 | 연도 | 후보 | 삼복6 | 삼복 NLL↓ |', '|---|---|---|---:|---:|']
    for r in summary[summary.period.ne('all')].itertuples():
        lines.append(f'| {names[r.meet]} | {r.period} | {r.variant} | {r.top6_trio_hit:.2%} | {r.trio_nll:.5f} |')
    lines += ['', '## 사전 지정 쌍차이', '', '| 지역 | 비교 | 지표 | 후보−기준 | 날짜 bootstrap95% 구간 |', '|---|---|---|---:|---|']
    for d in differences:
        if d['metric'] not in ['trio_nll', 'top6_trio_hit', 'top3_brier']:
            continue
        lo, hi = d['day_cluster_95_ci']
        lines.append(f"| {names[d['meet']]} | {d['base']}→{d['candidate']} | {d['metric']} | {d['difference']:+.6f} | {lo:+.6f}~{hi:+.6f} |")
    lines += ['', '2010–2016 warm-up, 정답2017+, T−2. 전개 외부 예측은2020+이고2017–2019는 결측/가용성0이다. 현재 통과 정답이 없는 평가 경주도 포함했다.',
        '전개 모델은 이전 연도까지만 학습/보정한다. 입력/운영 등록부는 보존하고 심판기록은 사용하지 않았다.',
        '결과표 기반 편성·기수·게이트 대리값과 반복 사용한2024–2026 연구 기간이다. 독립 미래/실전 사전 공개 검증 또는 배당 수익 평가가 아니다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'pace', 'train'])
    args = parser.parse_args()
    {'prepare': prepare, 'pace': pace, 'train': train}[args.mode]()
