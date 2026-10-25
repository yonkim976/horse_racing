"""Independently check the diagnostic for changed maximum-probability tickets."""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
from math_reference import aggregate, reference_distribution

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE.parent / 'experiment/outputs'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'


def main():
    summary = json.loads((OUT / 'choice_change_diagnostic.json').read_text())
    path = OUT / 'choice_change_diagnostic.parquet'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary['diagnostic_sha256']
    changes = pd.read_parquet(path)
    assert len(changes) == 61
    feature = pd.read_parquet(STYLE / 'features.parquet', columns=[
        'api_record_id', 'race_id', 'year', 'horse_number'])
    frames = []
    for year in (2024, 2025, 2026):
        scores = pd.read_parquet(STYLE / f'F1_STYLE6_{year}/evaluation_scores.parquet')
        frames.append(feature.loc[feature.year.eq(year)].merge(scores, on='api_record_id', validate='one_to_one'))
    data = pd.concat(frames).set_index('race_id')
    temperature = json.loads((OUT / 'fit_receipt.json').read_text())['fit']['temperature']
    max_gap = max_saved_error = 0.0
    for row in changes.itertuples():
        race = data.loc[row.race_id].sort_values('horse_number')
        numbers = list(race.horse_number)
        scores = race.score.to_numpy()
        first = tuple(numbers.index(n) for n in json.loads(row.ticket_t1_json))
        second = tuple(numbers.index(n) for n in json.loads(row.ticket_temp_json))
        first_scores, second_scores = [scores[i] for i in first], [scores[i] for i in second]
        assert sorted(first_scores) == sorted(second_scores)
        if row.pool in ('EXA', 'TRI'):
            assert first_scores == second_scores
        for arm, temp in [('t1', 1.0), ('temp', temperature)]:
            q = reference_distribution(scores, temp)
            pools, _ = aggregate(q, len(scores), 3 if len(scores) >= 8 else None)
            p, p2 = pools[row.pool][first], pools[row.pool][second]
            max_gap = max(max_gap, abs(p - p2))
            max_saved_error = max(max_saved_error,
                                  abs(p - getattr(row, 'p_t1_ticket_at_' + arm)),
                                  abs(p2 - getattr(row, 'p_temp_ticket_at_' + arm)))
    assert max_gap < 1e-12 and max_saved_error < 2e-14
    result = dict(passed=True, changed_ticket_cases=len(changes),
                  all_raw_ticket_score_ties=True, ordered_pool_score_sequences_equal=True,
                  max_independent_probability_gap=max_gap,
                  max_saved_probability_difference=max_saved_error,
                  experiment_code_imported=False, model_refit_performed=False,
                  interpretation='Selection differences are numerical ties, not predictive ranking improvements.')
    with (HERE / 'CHOICE_REVIEW.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
