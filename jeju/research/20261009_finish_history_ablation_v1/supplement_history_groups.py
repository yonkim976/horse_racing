"""Supplement subgroup tables for F2's fixed recent same-distance window."""
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
import run as pipeline
import prepare as prepared

OUT = prepared.OUT


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bins(series):
    values = pd.to_numeric(series, errors='coerce')
    labels = pd.Series(index=series.index, dtype='string')
    labels.loc[values.eq(0)] = '0'
    labels.loc[values.between(1, 2)] = '1_2'
    labels.loc[values.between(3, 5)] = '3_5'
    assert labels.notna().all()
    return labels


def main():
    completion_path = OUT / 'training_completion.json'
    completion = json.loads(completion_path.read_text(encoding='utf-8'))
    assert completion['passed'] and completion['final_candidate_models'] == 6
    for filename, expected in completion['outputs'].items():
        assert sha(OUT / filename) == expected, f'changed completion artifact: {filename}'
    runners = pd.read_parquet(OUT / 'runner_predictions.parquet')
    assert {'same_distance_last5_actual_n', 'same_distance_last5_normal_n'}.issubset(runners.columns)
    rows, diffs = [], []
    group_specs = [
        ('same_distance_last5_actual_n', bins(runners.same_distance_last5_actual_n)),
        ('same_distance_last5_normal_n', bins(runners.same_distance_last5_normal_n)),
    ]
    for column, labels in group_specs:
        for label in ['0', '1_2', '3_5']:
            subset = runners.loc[labels.eq(label)].copy()
            if subset.empty:
                continue
            for variant, one in subset.groupby('variant'):
                weight = 1 / one.field_n
                rows.append(dict(
                    group=column, value=label, variant=variant,
                    rows=len(one), races=one.race_id.nunique(), days=one.race_date.nunique(),
                    log_loss=float(one.log_loss.mean()), brier=float(one.brier.mean()),
                    weighted_log_loss=float(np.average(one.log_loss, weights=weight)),
                    weighted_brier=float(np.average(one.brier, weights=weight)),
                    predicted=float(np.average(one.p_top3, weights=weight)),
                    actual=float(np.average(one.y, weights=weight)),
                ))
            for left_variant, right_variant in [('F1', 'R1'), ('F2', 'F1'), ('F2', 'R1')]:
                left = subset.loc[subset.variant.eq(left_variant)]
                right = subset.loc[subset.variant.eq(right_variant)]
                for metric in ['log_loss', 'brier']:
                    diffs.append(dict(group=column, value=label,
                        comparison=f'{left_variant}-{right_variant}', metric=metric,
                        **pipeline.bootstrap_runner(left, right, metric)))
    metrics = pd.DataFrame(rows)
    differences = pd.DataFrame(diffs)
    metric_path = OUT / 'last5_history_group_metrics.csv'
    diff_path = OUT / 'last5_history_paired_differences.csv'
    receipt_path = OUT / 'last5_history_supplement_verification.json'
    for path in [metric_path, diff_path, receipt_path]:
        assert not path.exists(), f'refusing to overwrite: {path}'
    metrics.to_csv(metric_path, index=False)
    differences.to_csv(diff_path, index=False)
    receipt = dict(
        passed=True,
        source_completion_sha256=sha(completion_path),
        source_runner_predictions_sha256=sha(OUT / 'runner_predictions.parquet'),
        groups=['same_distance_last5_actual_n', 'same_distance_last5_normal_n'],
        bins=['0', '1_2', '3_5'],
        comparisons=['F1-R1', 'F2-F1', 'F2-R1'],
        bootstrap_repetitions=pipeline.BOOTSTRAP_REPS,
        bootstrap_seed=pipeline.BOOTSTRAP_SEED,
        protected_and_locked_outputs_unchanged=True,
        outputs={metric_path.name: sha(metric_path), diff_path.name: sha(diff_path)},
    )
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(metrics.to_string(index=False))
    print(differences.to_string(index=False))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
