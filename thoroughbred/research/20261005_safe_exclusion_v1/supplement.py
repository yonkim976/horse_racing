"""Matched operating reference and date-cluster uncertainty; no policy fitting."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
OPERATING = HERE.parent / '20261004_close_contenders_v1/outputs'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def interval(delta, dates, rng):
    daily = pd.DataFrame({'date': dates, 'delta': delta}).groupby('date').delta.agg(['sum', 'size']).to_numpy()
    draws = daily[rng.integers(0, len(daily), size=(2000, len(daily)))].sum(axis=1)
    return np.quantile(draws[:, 0] / draws[:, 1], [.025, .975]).tolist()


def main():
    target = OUT / 'supplement_summary.json'
    if target.exists():
        raise FileExistsError('Completed supplementary evaluation')
    inputs = [OUT / 'race_metrics.csv', OUT / 'runner_predictions.parquet',
              OUT / 'full_distribution_metrics.csv', OPERATING / 'race_diagnostics.csv',
              OPERATING / 'operating_runner_predictions.parquet']
    hashes = {str(p): sha(p) for p in inputs}
    races = pd.read_csv(inputs[0])
    runners = pd.read_parquet(inputs[1])
    full = pd.read_csv(inputs[2])
    operating = pd.read_csv(inputs[3])
    operating = operating[operating.variant.eq('operating_exact_2026')].copy()
    op_runners = pd.read_parquet(inputs[4])
    for frame in [runners, op_runners]:
        frame['comparison_rank'] = frame.outcome.where(frame.outcome.between(1, 20), 0).astype(int)
    op_sets = op_runners.groupby('race_key').apply(
        lambda g: frozenset(zip(g.program_no, g.horse_id, g.comparison_rank)), include_groups=False)
    new_sets = runners.groupby('race_key').apply(
        lambda g: frozenset(zip(g.program_no, g.horse_id, g.comparison_rank)), include_groups=False)
    operating['bridge'] = (operating.race_key.str.replace('RACE:SEOUL:', '1:', regex=False)
                           .str.replace('RACE:BUSAN:', '3:', regex=False)
                           .str.replace(r':0([1-9])$', r':\1', regex=True))
    operating['matched'] = [row.bridge in new_sets.index and new_sets[row.bridge] == op_sets[row.race_key]
                            for row in operating.itertuples()]
    op = operating[operating.matched]
    rng = np.random.default_rng(20261005)
    comparisons = []
    for meet in [0, 1, 3]:
        for policy in sorted(races.policy.unique()):
            left = races[races.policy.eq(policy)]
            right = op
            if meet:
                left = left[left.meet.eq(meet)]
                right = right[right.meet.eq(meet)]
            paired = left.merge(right, left_on='race_key', right_on='bridge',
                                suffixes=('_new', '_operating'), validate='one_to_one')
            if len(paired) != len(right):
                raise ValueError('Matched operating races lost')
            delta = paired.trio6_hit_new - paired.trio6_hit_operating
            comparisons.append(dict(meet=meet, policy=policy, races=len(paired),
                                    new_rate=float(paired.trio6_hit_new.mean()),
                                    operating_rate=float(paired.trio6_hit_operating.mean()),
                                    difference=float(delta.mean()),
                                    date_bootstrap_95_interval=interval(delta, paired.race_date_new, rng)))
    probability = []
    for meet in [1, 3]:
        a = full[full.meet.eq(meet) & full.model.eq('parent')]
        b = full[full.meet.eq(meet) & full.model.eq('fusion')]
        p = a.merge(b, on='race_key', suffixes=('_a', '_b'), validate='one_to_one')
        for metric in ['trio_nll', 'top3_brier']:
            delta = p[metric + '_b'] - p[metric + '_a']
            probability.append(dict(meet=meet, metric=metric, difference=float(delta.mean()),
                                    date_bootstrap_95_interval=interval(delta, p.race_date_a, rng)))
    selection = []
    for (meet, policy), g in races.groupby(['meet', 'policy']):
        keep = g[g.selected.eq(1)]
        selection.append(dict(meet=int(meet), policy=policy, selected=len(keep), total=len(g),
                              selection_rate=len(keep)/len(g),
                              hit_rate=float(keep.trio6_hit.mean()),
                              hit_95_interval=interval(keep.trio6_hit, keep.race_date, rng),
                              hits_retained=int(keep.trio6_hit.sum()),
                              all_hits=int(g.trio6_hit.sum())))
    if any(sha(Path(path)) != digest for path, digest in hashes.items()):
        raise ValueError('Input changed during supplementary evaluation')
    result = dict(inputs=hashes, matched_operating_races=len(op),
                  unmatched_operating_races=operating.loc[~operating.matched, 'race_key'].tolist(),
                  match_fields=['program_no', 'horse_id', 'all_numeric_finishing_ranks'],
                  non_numeric_finish_normalization='NaN/91/92 -> 0 for matching only',
                  bootstrap_seed=20261005, bootstrap_draws=2000,
                  operating_comparisons=comparisons, probability_differences=probability,
                  selection=selection, no_policy_tuning=True)
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['matched_operating_races', 'probability_differences']}))
    print(json.dumps([x for x in comparisons if x['meet'] == 0 and x['policy'] in
                      ['parent_full', 'fusion_full', 'fusion_guarded_union7']]))


if __name__ == '__main__':
    main()
