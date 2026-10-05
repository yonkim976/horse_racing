"""Post-event association, not a start reaction or causal error model."""
from pathlib import Path
import json
import hashlib

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / '20261003_pace_jockey_v3/outputs'
OUT = HERE / 'outputs'
KEY = ['race_key', 'program_no', 'horse_id']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite outputs')
    inputs = [SOURCE / (n + '.parquet') for n in ['features', 'history', 'runner_predictions']]
    inputs += [HERE / 'analyze.py', HERE / 'PLAN.md']
    hashes = {str(p): sha(p) for p in inputs}
    f, h, p = [pd.read_parquet(path) for path in inputs[:3]]
    p = p[p.variant.eq('jockey') & p.point.eq('S1F')].copy()
    p['signed_error'] = p.actual_rank - p.expected_position
    p['absolute_error'] = abs(p.signed_error)
    p['error_group'] = np.where(p.signed_error.ge(3), 'behind_by3plus',
                               np.where(p.signed_error.le(-3), 'ahead_by3plus', 'within3'))
    current = h[KEY + ['start_time']].rename(columns={'start_time': 'actual_start_time'})
    p = p.merge(current, on=KEY, validate='one_to_one').merge(
        f[KEY + ['history_count', 'distance_m', 'previous_result_distance', 'horse_name', 'gate_zone_proxy']],
        on=KEY, validate='one_to_one')
    h = h.sort_values(['horse_id', 'race_date']).copy()
    group = h.groupby('horse_id', sort=False)
    states = h[['horse_id', 'race_date']].rename(columns={'race_date': 'source_date'})
    states['available_date'] = states.source_date + pd.Timedelta(days=2)
    for name, col in [('time', 'historical_start_time'), ('meet', 'meet'), ('distance', 'distance_m')]:
        roll = group[col].rolling(3, min_periods=1)
        states['last3_' + name + '_count'] = roll.count().reset_index(level=0, drop=True)
        states['last3_' + name + '_mean'] = roll.mean().reset_index(level=0, drop=True)
        states['last3_' + name + '_min'] = roll.min().reset_index(level=0, drop=True)
        states['last3_' + name + '_max'] = roll.max().reset_index(level=0, drop=True)
    p = pd.merge_asof(p.sort_values('race_date'), states.sort_values('available_date'),
        left_on='race_date', right_on='available_date', by='horse_id', direction='backward')
    p['time_known'] = p.last3_time_count.eq(3) & p.actual_start_time.between(10, 30)
    p['time_change'] = (p.actual_start_time - p.last3_time_mean).where(p.time_known)
    available_count = p.groupby('race_key').time_known.transform('sum')
    common = p.groupby('race_key').time_change.transform('median')
    p['race_centered_change'] = (p.time_change - common).where(available_count.ge(5))
    p['same_context'] = (p.time_known & p.last3_meet_count.eq(3) & p.last3_distance_count.eq(3)
        & p.last3_meet_min.eq(p.meet) & p.last3_meet_max.eq(p.meet)
        & p.last3_distance_min.eq(p.distance_m) & p.last3_distance_max.eq(p.distance_m))
    OUT.mkdir()
    p.to_parquet(OUT / 'runner_diagnostic.parquet', index=False)
    coverage = p.groupby(['meet', 'year', 'error_group']).agg(runners=('horse_id', 'size'),
        time_known=('time_known', 'sum'), mean_absolute_error=('absolute_error', 'mean'))
    coverage.to_csv(OUT / 'coverage.csv')
    rows = []
    for threshold in [.3, .4, .5]:
        for context in ['all_known', 'same_context']:
            for measure in ['time_change', 'race_centered_change']:
                sample = p[p.time_known] if context == 'all_known' else p[p.same_context]
                sample = sample[sample[measure].notna()]
                for (meet, error), cell in sample.groupby(['meet', 'error_group']):
                    for period, one in [('all', cell), *[(str(y), part) for y, part in cell.groupby('year')]]:
                        value = one[measure].astype(float)
                        rows.append({'meet': int(meet), 'error_group': error, 'context': context,
                            'measure': measure, 'threshold': threshold, 'period': period, 'runners': len(one),
                            'slow': int(value.gt(threshold + 1e-9).sum()), 'fast': int(value.lt(-threshold - 1e-9).sum()),
                            'normal': int(value.between(-threshold - 1e-9, threshold + 1e-9).sum()),
                            'mean_change': float(value.mean()), 'median_change': float(value.median())})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / 'time_error_groups.csv', index=False)
    chosen = p.sort_values(['race_key', 'prob_lead', 'program_no'], ascending=[True, False, True]).drop_duplicates('race_key')
    selected = []
    for (meet, hit), one in chosen.groupby(['meet', chosen.actual_rank.eq(1)]):
        known = one[one.time_known]
        selected.append({'meet': int(meet), 'leader_hit': bool(hit), 'races': len(one), 'known_time_races': len(known),
            'slow': int(known.time_change.gt(.4 + 1e-9).sum()), 'fast': int(known.time_change.lt(-.4 - 1e-9).sum()),
            'normal': int(known.time_change.between(-.4 - 1e-9, .4 + 1e-9).sum())})
    pd.DataFrame(selected).to_csv(OUT / 'leader_selection.csv', index=False)
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)
    check('unique runners', not p.duplicated(KEY).any())
    check('historical cutoff', (p.source_date.isna() | p.source_date.le(p.race_date - pd.Timedelta(days=2))).all())
    check('all classification counts', (metrics[['slow', 'fast', 'normal']].sum(axis=1) == metrics.runners).all())
    check('cohort preserved', len(p) == len(f[f.race_key.isin(p.race_key.unique())]))
    check('one lead choice per race', chosen.race_key.nunique() == len(chosen) == p.race_key.nunique())
    for row in p[p.time_known].sample(100, random_state=20261003).itertuples():
        past = h[h.horse_id.eq(row.horse_id) & h.race_date.le(row.race_date - pd.Timedelta(days=2))].tail(3)
        values = past.historical_start_time.astype(float)
        check('independent last3 ' + row.race_key + '/' + row.horse_id,
              len(past) == values.notna().sum() == 3 and np.isclose(values.mean(), row.last3_time_mean)
              and np.isclose(row.actual_start_time - values.mean(), row.time_change))
    for path in inputs:
        check('input unchanged ' + path.name, sha(path) == hashes[str(path)])
    summary = {'passed': len(checks), 'failed': 0, 'checks': checks, 'inputs': hashes,
               'runners': len(p), 'races': int(p.race_key.nunique()), 'cause_identified': False,
               'production_changed': False}
    (OUT / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    report(p, metrics, pd.DataFrame(selected), summary)
    print(json.dumps({'passed': len(checks), 'runners': len(p), 'races': summary['races']}), flush=True)


def report(p, metrics, selected, summary):
    names = {'behind_by3plus': '예상보다3두 이상 뒤', 'ahead_by3plus': '예상보다3두 이상 앞', 'within3': '오차3두 미만'}
    lines = ['# 전개 오차와 출발200m 기록 — 사후 진단', '',
        'S1F 통과순위 오차를 살폈다. 발주대 반응시간·첫발 속도·출발 사고를 직접 측정한 분석이 아니다. 동일200m의 시간과 순위는 구조적으로 관련되므로 인과 해석을 하지 않는다.', '',
        '최근3전 유효S1F 모두 있는 말 기준. 느림=평소 평균보다0.4초 초과, 빠름=0.4초 초과 단축. 기록이 없는 말은 비교에서 제외하고 coverage.csv에 남겼다.', '',
        '| 장소 | 오차 방향 | 비교 두수 | 느림 | 보통 | 빠름 |', '|---|---|---:|---:|---:|---:|']
    mask = metrics.period.eq('all') & metrics.context.eq('all_known') & metrics.measure.eq('time_change') & metrics.threshold.eq(.4)
    for r in metrics[mask].itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[r.meet]} | {names[r.error_group]} | {r.runners:,} | {r.slow/r.runners:.1%} | {r.normal/r.runners:.1%} | {r.fast/r.runners:.1%} |')
    lines += ['', '## 선두 선택 실패', '', '| 장소 | 선택 결과 | 경주 | 최근3전 비교 가능 | 그중 느림 |', '|---|---|---:|---:|---:|']
    for r in selected.itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[r.meet]} | {"적중" if r.leader_hit else "실패"} | {r.races:,} | {r.known_time_races:,} | {r.slow/r.known_time_races:.1%} |')
    lines += ['', '## 한계와 검증', '',
        '기록 변화에는 함수율·거리·편성·가속·기수 조절·진로·말 상태가 섞일 수 있다. 경주 내 중앙 변화 제거와 동일거리/지역 제한,0.3·0.5초 민감도는 time_error_groups.csv에 남겼다. 경주 중앙 제거는 현재 정답을 사용한 보조 사후 통계이며 예측 입력이 아니다.', '',
        f'검증{summary["passed"]}개 통과. 기존 입력 해시·과거3전100개 직접 재현·시점·키·분류 합계를 확인했다. model/DB/운영 등록부 변경 없음.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
