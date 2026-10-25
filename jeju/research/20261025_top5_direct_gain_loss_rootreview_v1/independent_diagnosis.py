"""Independent fixed-cohort condition tables and additive-head energy audit.

This is post-outcome description. No new model or selection policy is fitted.
"""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / 'jeju/research'
SOURCE = RESEARCH / '20261025_top5_direct_learning_v1'
FEATURES = RESEARCH / '20261010_style_history_ablation_v1/outputs/features.parquet'
BASE = RESEARCH / '20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet'
STYLE = ['hist_s1f_relpos_mean5', 'hist_s1f_to_c4_forward_mean5', 'hist_c4_to_g1f_forward_mean5']
COUNTS = ['observed_starts', 'same_starts', 'same_valid_times',
          'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n']
PROFILES = ['observed_starts', 'same_starts', 'same_valid_times', 'valid_n5',
            'mean5_rank_fraction', 'days_since_start', *STYLE, *COUNTS[3:]]
GROUPS = {'career': [0], 'same_distance_support': [1, 2], 'relative_rank': [3, 4],
          'style_means': [5, 7, 9], 'style_support': [6, 8, 10]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(g):
    rank = g.mean5_rank_fraction.to_numpy(float)
    log = {c: np.log1p(g[c].to_numpy(float)) for c in COUNTS}
    return np.column_stack([log[COUNTS[0]], log[COUNTS[1]], log[COUNTS[2]],
                            rank, np.isnan(rank).astype(float), g[STYLE[0]], log[COUNTS[3]],
                            g[STYLE[1]], log[COUNTS[4]], g[STYLE[2]], log[COUNTS[5]]]).astype(float)


def finite_mean(values):
    a = np.asarray(values, dtype=float)
    return float(np.mean(a[np.isfinite(a)])) if np.isfinite(a).any() else None


def main():
    plan = json.loads((HERE / 'ROOT_PLAN_REVIEW.json').read_text())
    assert sha(ROOT / plan['plan_path']) == plan['plan_sha256']
    audit = json.loads((HERE / 'ROOT_COHORT_AUDIT.json').read_text())
    for name, expected in audit['source_hashes'].items():
        assert sha(ROOT / name) == expected
    feature_cols = ['api_record_id', 'race_id', 'race_date', 'year', 'horse_id', 'horse_number',
                    'distance_m', 'grade_raw', 'field_n', 'history_cutoff', 'latest_history_date',
                    'valid_n5', 'days_since_start', 'mean5_rank_fraction', *COUNTS, *STYLE]
    features = pd.read_parquet(FEATURES, columns=feature_cols, filters=[('year', '>=', 2024)])
    base = pd.read_parquet(BASE, columns=['api_record_id', 'score', 'y'])
    frame = features.merge(base, on='api_record_id', validate='one_to_one')
    assert len(frame) == 17412 and frame.race_id.nunique() == 1779
    choices = {r['race_id']: r for r in map(json.loads, (SOURCE / 'outputs/candidate_choices.jsonl').read_text().splitlines())}
    models = {y: json.loads((SOURCE / 'outputs' / f'model_{y}.json').read_text()) for y in [2024, 2025, 2026]}
    records = []
    swapped = []
    max_energy_replay_error = max_decomposition_error = 0.0
    for race_id, raw in frame.groupby('race_id', sort=True):
        g = raw.sort_values('horse_number').reset_index(drop=True)
        c = choices[race_id]
        year = int(g.year.iloc[0]); m = models[year]
        score = g.score.to_numpy(float); sd = score.std(ddof=0)
        z = np.zeros(len(g)) if sd == 0 else (score - score.mean()) / sd
        raw_x = inputs(g)
        x = np.where(np.isfinite(raw_x), (raw_x - m['feature_means']) / m['feature_scales'], 0)
        beta = np.array(m['beta']); u = z + x @ beta
        ids = g.horse_id.astype(str).to_numpy()
        old = np.isin(ids, c['baseline_top5_horse_ids'])
        new = np.isin(ids, c['selector_top5_horse_ids'])
        added = new & ~old; removed = old & ~new
        truth = g.y.to_numpy(int).astype(bool)
        assert old.sum() == new.sum() == 5 and truth.sum() == 3
        old_cap, new_cap = int(truth[old].sum()), int(truth[new].sum())
        case = 'both_hit' if old_cap == new_cap == 3 else 'caught' if new_cap == 3 else 'lost' if old_cap == 3 else 'both_miss'
        ordered = sorted(range(len(g)), key=lambda i: (-score[i], int(g.horse_number.iloc[i])))
        assert set(ids[ordered[:5]]) == set(ids[old])
        rank = np.empty(len(g), dtype=int); rank[ordered] = np.arange(1, len(g) + 1)
        edge = g.iloc[ordered[4]]
        gap_raw = float(score[ordered[4]] - score[ordered[5]])
        gap_z = gap_raw / sd if sd != 0 else 0.0
        career = int(edge.observed_starts); valid = int(edge.valid_n5); same = int(edge.same_valid_times)
        days = float(edge.days_since_start)
        nswap = int(added.sum()); assert nswap == removed.sum()
        delta = int(new_cap == 3) - int(old_cap == 3)
        rec = dict(race_id=race_id, race_date=str(edge.race_date), year=year,
                   distance=int(edge.distance_m), grade=str(edge.grade_raw), field_n=int(edge.field_n),
                   case=case, delta=delta, changed=nswap > 0, swaps=nswap,
                   gap_z=gap_z, gap_raw=gap_raw,
                   gap_bin='<=0.10' if gap_z <= .1 else '(0.10,0.25]' if gap_z <= .25 else '>0.25',
                   career_bin='0' if career == 0 else '1-4' if career <= 4 else '5+',
                   valid_bin='0' if valid == 0 else '1-2' if valid <= 2 else '3-5',
                   same_bin='0' if same == 0 else '1' if same == 1 else '2+',
                   days_bin='missing' if not np.isfinite(days) else '<15' if days < 15 else '15-28' if days <= 28 else '29-60' if days <= 60 else '61+',
                   swap_bin='unchanged' if nswap == 0 else '1' if nswap == 1 else '2+',
                   baseline_captured=old_cap, selector_captured=new_cap)
        records.append(rec)
        if not nswap:
            continue
        contributions = (x[new].sum(axis=0) - x[old].sum(axis=0)) * beta
        prior_delta = float(z[new].sum() - z[old].sum())
        energy_delta = float(u[new].sum() - u[old].sum())
        replay_error = max(abs(float(u[new].sum()) - c['selector_energy']),
                           abs(float(z[old].sum()) - c['baseline_energy']))
        max_energy_replay_error = max(max_energy_replay_error, replay_error)
        max_decomposition_error = max(max_decomposition_error, abs(prior_delta + contributions.sum() - energy_delta))
        assert energy_delta >= -1e-12 and prior_delta <= 1e-12
        added_true, removed_true = int(truth[added].sum()), int(truth[removed].sum())
        assert new_cap - old_cap == added_true - removed_true
        r = dict(race_id=race_id, year=year, distance=rec['distance'], case=case, swaps=nswap,
                 added_ranks=[int(v) for v in rank[added]], removed_ranks=[int(v) for v in rank[removed]],
                 added_true=added_true, removed_true=removed_true,
                 retained_true=int(truth[new & old].sum()), outside_both=int(truth[~(new | old)].sum()),
                 old_captured=old_cap, new_captured=new_cap, gap_z=gap_z,
                 prior_delta=prior_delta, energy_delta=energy_delta,
                 feature_contributions=contributions.tolist(),
                 grouped_contributions={k: float(contributions[idx].sum()) for k, idx in GROUPS.items()},
                 added_profile={p: finite_mean(g.loc[added, p]) for p in PROFILES},
                 removed_profile={p: finite_mean(g.loc[removed, p]) for p in PROFILES})
        swapped.append(r)
    assert max_energy_replay_error < 1e-12 and max_decomposition_error < 1e-12
    races = pd.DataFrame(records)
    primary = races[races.distance.isin([900, 1000, 1110, 1200])].copy()
    assert len(primary) == 1503 and primary.changed.sum() == 254
    dates = sorted(races.race_date.unique())
    assert hashlib.sha256('\n'.join(dates).encode()).hexdigest() == 'e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84'
    schedule_path = RESEARCH / '20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
    assert sha(schedule_path) == 'd141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
    schedule = np.load(schedule_path, allow_pickle=False)

    def table_row(g):
        daily = g.groupby('race_date').delta.agg(['sum', 'size']).reindex(dates, fill_value=0)
        numer = daily['sum'].to_numpy()[schedule].sum(axis=1)
        denom = daily['size'].to_numpy()[schedule].sum(axis=1)
        defined = denom > 0
        ci = np.quantile(numer[defined] / denom[defined], [.025, .975], method='linear')
        return dict(races=len(g), changed=int(g.changed.sum()), caught=int(g.case.eq('caught').sum()),
                    lost=int(g.case.eq('lost').sum()), both_hit=int(g.case.eq('both_hit').sum()),
                    both_miss=int(g.case.eq('both_miss').sum()), net=int(g.delta.sum()),
                    delta_pp=float(100*g.delta.mean()), ci95_pp=(ci*100).tolist(),
                    valid_bootstrap_draws=int(defined.sum()), sparse=len(g) < 30)

    conditions = {}
    for column in ['year', 'distance', 'grade', 'field_n', 'gap_bin', 'career_bin', 'valid_bin', 'same_bin', 'days_bin', 'swap_bin']:
        conditions[column] = {str(k): table_row(g) for k, g in primary.groupby(column, sort=True)}
    conditions['year_by_distance'] = {f'{y}:{d}': table_row(g) for (y, d), g in primary.groupby(['year', 'distance'], sort=True)}
    primary_swaps = [r for r in swapped if r['distance'] in [900, 1000, 1110, 1200]]
    case_profiles = {}
    for case in ['caught', 'lost', 'both_hit', 'both_miss']:
        group = [r for r in primary_swaps if r['case'] == case]
        case_profiles[case] = dict(races=len(group), mean_gap_z=finite_mean([r['gap_z'] for r in group]),
             mean_prior_delta=finite_mean([r['prior_delta'] for r in group]),
             mean_energy_delta=finite_mean([r['energy_delta'] for r in group]),
             grouped_contributions={k: finite_mean([r['grouped_contributions'][k] for r in group]) for k in GROUPS},
             added_profiles={p: finite_mean([r['added_profile'][p] for r in group]) for p in PROFILES},
             removed_profiles={p: finite_mean([r['removed_profile'][p] for r in group]) for p in PROFILES},
             added_true=sum(r['added_true'] for r in group), removed_true=sum(r['removed_true'] for r in group),
             outside_both_races=sum(r['outside_both'] > 0 for r in group))
    result = dict(passed=True, new_fit_calls=0, primary_races=1503, changed_primary=254,
                  counts=primary.case.value_counts().to_dict(),
                  max_energy_replay_error=max_energy_replay_error,
                  max_decomposition_error=max_decomposition_error,
                  conditions=conditions, changed_case_profiles=case_profiles,
                  changed_primary_records=primary_swaps,
                  caveat='All condition findings are retrospective; conditional contrasts and arithmetic score contributions are not causal or validated rules.')
    with (HERE / 'ROOT_INDEPENDENT_DIAGNOSIS.json').open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps({k: result[k] for k in ['passed', 'primary_races', 'changed_primary', 'counts', 'max_energy_replay_error', 'max_decomposition_error']}, indent=2))
    print(json.dumps({k: conditions[k] for k in ['gap_bin', 'career_bin', 'valid_bin', 'days_bin']}, indent=2))
    print(json.dumps(case_profiles, indent=2))


if __name__ == '__main__':
    main()
