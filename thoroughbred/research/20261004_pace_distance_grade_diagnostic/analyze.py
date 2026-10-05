"""Post-evaluation distance/grade decomposition; no fitting or DB writes."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PARENT = HERE.parent / '20261004_pace_objectives_v4'
SPEC = importlib.util.spec_from_file_location('distance_diag_parent', PARENT / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def distance_band(d):
    return np.select([d.le(1300), d.le(1600)], ['≤1300m', '1400–1600m'], default='≥1700m')


def grade_band(f):
    return np.select([f.grade.eq(6), f.grade.eq(5), f.grade.eq(4), f.grade.eq(3), f.grade.isin([1, 2])],
        ['6등급', '5등급', '4등급', '3등급', '1–2등급'], default='OPEN')


def summarize(f, groups):
    metrics = ['position_mae', 'rank_position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier', 'leader_nll']
    result = f.groupby(['meet', 'point', 'variant'] + groups, dropna=False).agg(races=('race_key', 'size'),
        **{m: (m, 'mean') for m in metrics}).reset_index()
    result['small_sample'] = result.races.lt(50)
    return result


def main():
    if OUT.exists():
        raise FileExistsError('Refusing to overwrite diagnostic')
    RUN.check_inputs()
    names = ['features.parquet', 'labels.parquet', 'history.parquet', 'runner_predictions.parquet',
             'point_metrics.csv', 'risk_predictions.parquet', 'metrics.csv', 'feature_contract.json']
    hashes = {name: RUN.BASE.sha(PARENT / 'outputs' / name) for name in names}
    hashes.update({'analyze.py': RUN.BASE.sha(HERE / 'analyze.py'), 'PLAN.md': RUN.BASE.sha(HERE / 'PLAN.md')})
    f = pd.read_parquet(PARENT / 'outputs/features.parquet')
    h = pd.read_parquet(PARENT / 'outputs/history.parquet')
    labels = pd.read_parquet(PARENT / 'outputs/labels.parquet')
    m = pd.read_csv(PARENT / 'outputs/point_metrics.csv')
    p = pd.read_parquet(PARENT / 'outputs/runner_predictions.parquet')
    r = pd.read_parquet(PARENT / 'outputs/risk_predictions.parquet')
    f['distance_band'] = distance_band(f.distance_m)
    f['grade_band'] = grade_band(f)
    race = f[['race_key', 'distance_m', 'distance_band', 'grade_raw', 'grade_band', 'field_size']].drop_duplicates()
    if race.race_key.duplicated().any():
        raise ValueError('Conflicting race context')
    combined = m.merge(race, on='race_key', validate='many_to_one')
    OUT.mkdir()
    for name, groups in [('distance', ['distance_band']), ('exact_distance', ['distance_m']),
                          ('grade', ['grade_band']), ('exact_grade', ['grade_raw']),
                          ('distance_grade', ['distance_band', 'grade_band'])]:
        summarize(combined, groups).to_csv(OUT / (name + '_metrics.csv'), index=False)
    # Store sufficient race-level data for independent subgroup recomputation.
    combined.to_parquet(OUT / 'race_diagnostics.parquet', index=False)
    states = h[['horse_id', 'race_date', 'distance_m', 'S1F_rank', 'S1F_fraction', 'S1F_complete', 'n']].copy()
    states = states.rename(columns={'race_date': 'source_date', 'distance_m': 'previous_distance',
        'S1F_rank': 'previous_early_rank', 'S1F_fraction': 'previous_early_fraction',
        'S1F_complete': 'previous_complete', 'n': 'previous_field_size'})
    states['available_date'] = states.source_date + pd.Timedelta(days=2)
    previous = RUN.V3.lookup(f, states, ['horse_id'])
    current = f[RUN.KEY + ['meet', 'race_date', 'year', 'distance_m', 'distance_band', 'grade_band', 'history_count']].copy()
    for name in ['source_date', 'previous_distance', 'previous_early_rank', 'previous_early_fraction', 'previous_complete', 'previous_field_size']:
        current[name] = previous[name]
    current = current.merge(labels[RUN.KEY + ['S1F_rank', 'S1F_complete']], on=RUN.KEY, validate='one_to_one')
    current = current[current.year.ge(2024) & current.S1F_complete & current.previous_complete.fillna(False) & current.previous_distance.notna()].copy()
    current['distance_delta'] = current.distance_m - current.previous_distance
    current['distance_change_group'] = np.select([current.distance_delta.gt(0), current.distance_delta.lt(0)], ['extended', 'shortened'], default='same')
    current['previous_leader'] = current.previous_early_rank.eq(1)
    current['previous_front3'] = current.previous_early_rank.le(3)
    current['now_front3'] = current.S1F_rank.le(3)
    current['now_outside_front3'] = current.S1F_rank.gt(3)
    current['now_leader'] = current.S1F_rank.eq(1)
    current.to_parquet(OUT / 'runner_distance_changes.parquet', index=False)
    rows = []
    for condition, subset in [('previous_leader', current[current.previous_leader]), ('previous_front3', current[current.previous_front3])]:
        for groups in [['meet', 'distance_change_group'], ['meet', 'distance_band', 'distance_change_group']]:
            one = subset.groupby(groups).agg(runners=('horse_id', 'size'), now_front3=('now_front3', 'mean'),
                now_outside_front3=('now_outside_front3', 'mean'), now_leader=('now_leader', 'mean')).reset_index()
            one['prior_condition'] = condition
            rows.append(one)
    pd.concat(rows, ignore_index=True).to_csv(OUT / 'style_transition_rates.csv', index=False)
    r = r.merge(current[RUN.KEY + ['distance_change_group']], on=RUN.KEY, how='left', validate='one_to_one')
    r = r.merge(f[RUN.KEY + ['distance_band', 'grade_band']], on=RUN.KEY, validate='one_to_one')
    known = r[r.slow_label.notna() & r.risk.notna()]
    known.groupby(['meet', 'distance_change_group'], dropna=False).agg(runners=('horse_id', 'size'),
        slow_rate=('slow_label', 'mean'), predicted_risk=('risk', 'mean')).to_csv(OUT / 'risk_distance_changes.csv')
    # Compare candidates within the same subgroup, with a day-block uncertainty range.
    rng, comparisons = np.random.default_rng(20261004), []
    for dimension in ['distance_band', 'grade_band']:
        for (meet, point, group), one in combined.groupby(['meet', 'point', dimension]):
            for variant, metric in [('trial', 'position_mae'), ('trial', 'leader_hit'), ('trial', 'top3_exact_hit'), ('leader_trial', 'leader_hit')]:
                if point == 'G3F' and variant != 'trial':
                    continue
                paired = one[one.variant.eq('jockey')].merge(one[one.variant.eq(variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
                delta = paired[metric + '_new'] - paired[metric + '_base']
                daily = pd.DataFrame({'day': paired.race_date_base, 'd': delta}).groupby('day').d.agg(['sum', 'size']).to_numpy()
                sampled = daily[rng.integers(0, len(daily), (1000, len(daily)))]
                lo, hi = np.quantile(sampled[:, :, 0].sum(axis=1) / sampled[:, :, 1].sum(axis=1), [.025, .975])
                comparisons.append({'dimension': dimension, 'group': group, 'meet': int(meet), 'point': point,
                    'variant': variant, 'metric': metric, 'races': len(paired), 'delta': float(delta.mean()),
                    'ci95_low': float(lo), 'ci95_high': float(hi)})
    pd.DataFrame(comparisons).to_csv(OUT / 'paired_differences.csv', index=False)
    report()
    RUN.BASE.save_json(OUT / 'audit.json', {'inputs': hashes, 'source_audit_sha256': RUN.BASE.sha(PARENT / 'outputs/data_audit.json'),
        'outputs': {file.name: RUN.BASE.sha(file) for file in OUT.iterdir() if file.is_file()},
        'models_changed': False, 'post_evaluation_analysis': True})
    print('Completed ' + str(OUT / 'REPORT.md'), flush=True)


def report():
    lines = ['# 거리·등급별 전개 v4 사후 진단', '',
        '보존 예측의 같은 경주 분해. 후보 재학습/선택/운영 변경 없이 평가2024–2026-09-20을 나눴다. 거리·등급별 표본·신마·편성 차이는 인과적으로 통제하지 않았다.', '',
        '현재 입력에는 거리, 직전거리/증감, 등급/국·혼, 같은 거리의 과거 입상률·완주시간이 있다. 말의 S1F/G3F 전개 이력은 거리별로 따로 집계하지 않고 혼합한다. 기수 성향은1400m 이하/초과 분할이다. 따라서 거리별 각질 전환을 충분히 모델링했다고 주장하지 않는다.', '']
    for title, filename, dimension in [('거리 구간', 'distance_metrics.csv', 'distance_band'), ('등급 요약', 'grade_metrics.csv', 'grade_band')]:
        table = pd.read_csv(OUT / filename)
        lines += ['', '## ' + title, '', '| 장소 | 구분 | 경주 | 평균 위치 MAE 기존→심사 | 선두 기존→심사 | 선두 직접+심사 | 초반3두 기존→심사 |',
                  '|---|---|---:|---|---|---:|---|']
        base = table[table.point.eq('S1F') & table.variant.eq('jockey')]
        for row in base.itertuples():
            group = getattr(row, dimension)
            one = table[table.meet.eq(row.meet) & table.point.eq('S1F') & table[dimension].eq(group)].set_index('variant')
            trial, lead = one.loc['trial'], one.loc['leader_trial']
            label = str(group) + (' (소표본)' if row.races < 50 else '')
            lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | {label} | {row.races:,} | {row.position_mae:.3f}→{trial.position_mae:.3f} | {row.leader_hit:.2%}→{trial.leader_hit:.2%} | {lead.leader_hit:.2%} | {row.top3_exact_hit:.2%}→{trial.top3_exact_hit:.2%} |')
    t = pd.read_csv(OUT / 'style_transition_rates.csv')
    t = t[t.prior_condition.eq('previous_leader') & t.distance_band.isna()]
    lines += ['', '## 직전 초반 선두였던 말', '', '| 장소 | 거리 변경 | 말 | 이번 초반3위 밖 | 이번도 초반 선두 |', '|---|---|---:|---:|---:|']
    for row in t.itertuples():
        lines.append(f'| { {1:"서울",3:"부산"}[row.meet]} | { {"extended":"연장","shortened":"단축","same":"동일"}[row.distance_change_group]} | {row.runners:,} | {row.now_outside_front3:.2%} | {row.now_leader:.2%} |')
    lines += ['', '거리 변경은 T−2 이전 직전 실제출전과 비교했다. 앞선3위 밖으로 이동했다고 최종 추입 각질·기수 의도·거리의 인과효과로 판정하지 않는다. 같은 거리에서도 상대 편성·게이트·기수·상태가 달라질 수 있다.', '',
        '현재 부진 위험 라벨도 거리 혼합 과거3전의 원시200m 시간과 비교하므로 거리 연장에 따른 의도적 초반 조절이 섞일 수 있다. 등급별 효과는 거리·경험별 구성과 함께 봐야 한다. exact_distance_metrics.csv, exact_grade_metrics.csv, distance_grade_metrics.csv와 날짜bootstrap paired_differences.csv에 세부 결과를 남긴다. 소표본·반복 비교의 우연을 고려해야 한다.', '',
        '다음 설계 후보는 말×거리 구간/동일거리의 과거 통과순위·앞선 비율·S1F→G3F 위치 변화, 이번 거리에서의 편성 상대 비교, 거리 변경 시 전개 변화 이력이다. 1300m 경계는 사용자 관점의 진단 기준이며 고정된 최적 경계로 확인한 것은 아니다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
