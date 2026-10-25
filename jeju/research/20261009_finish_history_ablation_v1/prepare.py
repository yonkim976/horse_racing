"""Prepare fixed F1/F2 inputs from the immutable R1 and source snapshots."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R1_DIR = HERE.parent / '20261009_field_relative_ability_v1'
R1_OUT = R1_DIR / 'outputs'
BASE_DIR = HERE.parent / '20261008_horse_profile_baseline_v1'
BASE_OUT = BASE_DIR / 'outputs_v2'
SOURCE_PATH = BASE_OUT / 'source_snapshot.parquet'
R1_FEATURES_PATH = R1_OUT / 'features.parquet'
OUT = HERE / 'outputs'
SEED = 20261008

spec = importlib.util.spec_from_file_location(
    'jeju_finish_history_r1_reference', BASE_DIR / 'run.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
R1_COLUMNS = list(base.BASE) + [
    'opp_mean5_valid_n', 'opp_mean5_valid_fraction', 'opp_mean5_median_s',
    'mean5_minus_opp_mean_s', 'mean5_minus_opp_median_s',
    'mean5_minus_opp_fast2mean_s', 'opp_mean5_faster_n', 'mean5_rank_fraction',
]
F1_EXTRA = [
    'previous_finish_relative_rank', 'previous_top3', 'previous_result_status',
]
F2_EXTRA = [
    'same_distance_last5_top3_rate', 'same_distance_last5_actual_n',
    'same_distance_last5_normal_n',
]
CONTRACTS = {
    'R1': R1_COLUMNS,
    'F1': R1_COLUMNS + F1_EXTRA,
    'F2': R1_COLUMNS + F1_EXTRA + F2_EXTRA,
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, payload):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write('\n')


def csv_new(path, frame):
    with Path(path).open('x', encoding='utf-8') as stream:
        frame.to_csv(stream, index=False)


def is_finite(value):
    try:
        return bool(np.isfinite(value))
    except TypeError:
        return False


def normalize_id_list(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise AssertionError(f'Expected saved history ID list, got {type(value)!r}')
    return [int(item) for item in value]


def race_quality(source):
    """Summarize the complete starter cohort, keeping raw status meanings opaque."""
    starter_by_race = {key: group for key, group in source[source.started].groupby('race_id', sort=False)}
    records = []
    for race_id, full in source.groupby('race_id', sort=False):
        starts = starter_by_race.get(race_id)
        if starts is None:
            starts = full.iloc[:0]
        n = len(starts)
        positions = pd.to_numeric(starts.finish_position, errors='coerce').to_numpy(float)
        integer_positions = (np.isfinite(positions) & (positions == np.floor(positions)))
        ranks = positions[integer_positions].astype(int).tolist()
        duplicate_horses = bool(starts.horse_id.duplicated().any())
        duplicate_ranks = len(ranks) != len(set(ranks))
        sequence_complete = (n >= 2 and not duplicate_horses and not duplicate_ranks
                             and len(ranks) == n and sorted(ranks) == list(range(1, n + 1)))
        reasons = []
        if n < 2:
            reasons.append('starter_count_below_2')
        if duplicate_horses:
            reasons.append('duplicate_horse_id')
        if duplicate_ranks:
            reasons.append('duplicate_rank')
        if len(ranks) != n or (n and sorted(ranks) != list(range(1, n + 1))):
            reasons.append('rank_sequence_incomplete_or_out_of_range')
        records.append(dict(
            race_id=race_id,
            race_date=str(full.race_date.iloc[0]),
            source_row_n=int(len(full)),
            started_n=int(n),
            started_horse_n=int(starts.horse_id.nunique()),
            finish_rank_unique_n=int(len(set(ranks))),
            finish_rank_observed_n=int(len(ranks)),
            rank_sequence_complete=bool(sequence_complete),
            reason='|'.join(reasons),
        ))
    return pd.DataFrame(records)


def valid_individual_rank(source_row, starter_n, duplicate_horse=False):
    if not bool(source_row.started) or duplicate_horse or starter_n < 1:
        return None
    raw = source_row.finish_position
    if not is_finite(raw):
        return None
    rank = int(raw)
    if float(raw) != rank or rank < 1 or rank > int(starter_n):
        return None
    return rank


def build_history_features(features, source, quality):
    src = source.set_index('api_record_id', drop=False)
    q = quality.set_index('race_id', drop=False)
    starter_n = q.started_n.to_dict()
    race_complete = q.rank_sequence_complete.to_dict()
    duplicate_horse_counts = source.loc[source.started].groupby(['race_id', 'horse_id']).size().to_dict()
    result_rows = []
    lineage = []

    for row in features.itertuples(index=False):
        prior_id = None if not is_finite(row.previous_start_id) else int(row.previous_start_id)
        prior_rank = None
        prior_top3 = np.nan
        prior_status = 'unobserved'
        if prior_id is not None:
            assert prior_id in src.index, f'missing previous_start_id: {prior_id}'
            past = src.loc[prior_id]
            assert isinstance(past, pd.Series)
            assert str(past.horse_id) == str(row.horse_id)
            assert bool(past.started)
            assert str(past.race_date) <= str(row.history_cutoff)
            assert past.race_id in q.index
            n = int(starter_n[past.race_id])
            duplicate_horse = duplicate_horse_counts.get((past.race_id, past.horse_id), 0) > 1
            rank = valid_individual_rank(past, n, duplicate_horse)
            complete = bool(race_complete[past.race_id])
            prior_status = 'normal' if complete else 'non_normal_or_incomplete'
            if complete and rank is not None:
                prior_rank = (rank - 1) / (n - 1)
            if rank is not None:
                prior_top3 = float(rank <= 3)
            lineage.append(dict(
                target_api_record_id=int(row.api_record_id),
                history_kind='previous_start',
                slot_oldest_to_newest=None,
                source_api_record_id=prior_id,
                source_race_id=str(past.race_id),
                source_race_date=str(past.race_date),
                target_cutoff=str(row.history_cutoff),
                target_horse_id=str(row.horse_id),
                source_horse_id=str(past.horse_id),
                target_distance_m=int(row.distance_m),
                source_distance_m=(None if not is_finite(past.race_distance_m) else int(past.race_distance_m)),
                source_started=bool(past.started),
                starter_n=n,
                event_rank_sequence_complete=complete,
                duplicate_horse_in_source_event=bool(duplicate_horse),
                raw_finish_position=int(past.finish_position),
                valid_individual_rank=rank,
                individual_top3=(None if rank is None else bool(rank <= 3)),
            ))

        ids = normalize_id_list(row.last5_same_source_ids)
        assert len(ids) <= 5
        assert len(ids) == len(set(ids)), f'duplicate same-distance history IDs for {row.api_record_id}'
        valid_ranks = []
        for slot_no, source_id in enumerate(ids, start=1):
            assert source_id in src.index, f'missing last5_same_source_id: {source_id}'
            past = src.loc[source_id]
            assert isinstance(past, pd.Series)
            assert str(past.horse_id) == str(row.horse_id)
            assert bool(past.started)
            assert is_finite(past.race_distance_m) and int(past.race_distance_m) == int(row.distance_m)
            assert str(past.race_date) <= str(row.history_cutoff)
            assert past.race_id in q.index
            n = int(starter_n[past.race_id])
            duplicate_horse = duplicate_horse_counts.get((past.race_id, past.horse_id), 0) > 1
            rank = valid_individual_rank(past, n, duplicate_horse)
            if rank is not None:
                valid_ranks.append(rank)
            lineage.append(dict(
                target_api_record_id=int(row.api_record_id),
                history_kind='last5_same_distance_start',
                slot_oldest_to_newest=int(slot_no),
                source_api_record_id=source_id,
                source_race_id=str(past.race_id),
                source_race_date=str(past.race_date),
                target_cutoff=str(row.history_cutoff),
                target_horse_id=str(row.horse_id),
                source_horse_id=str(past.horse_id),
                target_distance_m=int(row.distance_m),
                source_distance_m=int(past.race_distance_m),
                source_started=bool(past.started),
                starter_n=n,
                event_rank_sequence_complete=bool(race_complete[past.race_id]),
                duplicate_horse_in_source_event=bool(duplicate_horse),
                raw_finish_position=int(past.finish_position),
                valid_individual_rank=rank,
                individual_top3=(None if rank is None else bool(rank <= 3)),
            ))
        actual_n = len(ids)
        normal_n = len(valid_ranks)
        top3_rate = (sum(rank <= 3 for rank in valid_ranks) / normal_n
                     if normal_n else np.nan)
        result_rows.append(dict(
            api_record_id=int(row.api_record_id),
            previous_finish_relative_rank=prior_rank,
            previous_top3=prior_top3,
            previous_result_status=prior_status,
            same_distance_last5_top3_rate=top3_rate,
            same_distance_last5_actual_n=actual_n,
            same_distance_last5_normal_n=normal_n,
        ))

    added = pd.DataFrame(result_rows).set_index('api_record_id')
    out = features.copy().set_index('api_record_id', drop=False)
    for column in added.columns:
        out[column] = added[column]
    out = out.reset_index(drop=True)
    # Strings remain strings in the artifact; each model learns its vocabulary on train rows.
    out['previous_result_status'] = out.previous_result_status.astype('string')
    return out, pd.DataFrame(lineage)


def input_paths():
    paths = [
        HERE / 'CONTRACT.md', HERE / 'IMPLEMENTATION_PLAN.md', HERE / 'prepare.py',
        HERE / 'run.py', HERE / 'verify.py',
        R1_DIR / 'CONTRACT.md', R1_DIR / 'run.py', R1_DIR / 'verify.py',
        R1_OUT / 'prepared_lock.json', R1_OUT / 'features.parquet',
        R1_OUT / 'runner_predictions.parquet',
        R1_OUT / 'race_metrics.csv', R1_OUT / 'six_combinations.csv',
        R1_OUT / 'final_verification.json', BASE_DIR / 'run.py',
        BASE_OUT / 'prepared_lock.json', BASE_OUT / 'features.parquet',
        SOURCE_PATH, ROOT / 'jeju/AGENTS.md', ROOT / 'jeju/docs/RESTART_PLAN_20260928.md',
        ROOT / 'jeju/research/RESEARCH_PUBLICATION_POLICY.md',
        ROOT / 'jeju/data/horse_exclusions.json',
    ]
    for year in (2024, 2025, 2026):
        paths.extend([
            R1_OUT / f'R1_{year}/top3.txt', R1_OUT / f'R1_{year}/meta.json',
            R1_OUT / f'R1_{year}/calibration_scores.parquet',
            BASE_OUT / f'J0_{year}/top3.txt', BASE_OUT / f'J0_{year}/model_meta.json',
        ])
    op = HERE.parent / '20261009_operating_model_comparison_v1'
    paths.extend([
        op / 'compare.py', op / 'README.md', op / 'outputs/race_metrics.csv',
        op / 'outputs/runner_predictions.parquet', op / 'outputs/six_combinations.csv',
        op / 'outputs/race_alignment.csv', op / 'outputs/source_lock.json',
        op / 'outputs/verification.json',
    ])
    return paths


def protected_paths():
    return [
        ROOT / 'jeju/data/jeju_native_core.sqlite3',
        ROOT / 'config/prediction_model_registry.json',
        ROOT / 'jeju/models/current/metadata.json',
        ROOT / 'jeju/models/current/HY_R_FORM.pkl',
    ]


def prepare():
    OUT.mkdir(exist_ok=False)
    r1_lock = json.loads((R1_OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    for relative, expected in r1_lock['references'].items():
        assert sha(ROOT / relative) == expected, f'R1 reference changed: {relative}'
    for name, expected in r1_lock['artifacts'].items():
        assert sha(R1_OUT / name) == expected, f'R1 artifact changed: {name}'
    assert json.loads((R1_OUT / 'final_verification.json').read_text(encoding='utf-8'))['passed']
    base_lock = json.loads((BASE_OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    for relative, expected in base_lock['references'].items():
        assert sha(ROOT / relative) == expected, f'baseline reference changed: {relative}'
    for name, expected in base_lock['artifacts'].items():
        assert sha(BASE_OUT / name) == expected, f'baseline artifact changed: {name}'

    protected = {
        str(path.relative_to(ROOT)): dict(sha256=sha(path), bytes=path.stat().st_size)
        for path in protected_paths()
    }
    references = {
        str(path.relative_to(ROOT)): sha(path)
        for path in input_paths()
    }

    features = pd.read_parquet(R1_FEATURES_PATH)
    source = pd.read_parquet(SOURCE_PATH)
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert len(features.loc[features.year.ge(2024)]) == 17412
    assert features.loc[features.year.ge(2024), 'race_id'].nunique() == 1779
    assert features.api_record_id.is_unique and not features.duplicated(['race_id', 'horse_id']).any()
    assert source.api_record_id.is_unique and source.race_id.notna().all()
    expected_started = (source.finish_position.between(1, 89) | source.finish_position.isin([91, 92]))
    assert expected_started.equals(source.started.rename(expected_started.name))
    quality = race_quality(source)
    enriched, lineage = build_history_features(features, source, quality)
    assert list(features[R1_COLUMNS].columns) == R1_COLUMNS
    assert list(enriched[R1_COLUMNS].columns) == R1_COLUMNS
    assert not enriched.duplicated(['race_id', 'horse_id']).any()
    assert len(enriched) == len(features)
    assert set(enriched.columns) >= set(CONTRACTS['F2'])
    assert len(CONTRACTS['R1']) == 21 and len(CONTRACTS['F1']) == 24 and len(CONTRACTS['F2']) == 27
    assert enriched.api_record_id.equals(features.api_record_id)

    enriched.to_parquet(OUT / 'features.parquet', index=False)
    lineage.to_parquet(OUT / 'historical_lineage.parquet', index=False)
    quality.to_parquet(OUT / 'source_race_quality.parquet', index=False)
    csv_new(OUT / 'feature_contract.csv', pd.DataFrame([
        dict(variant=variant, column=column, ordinal=index + 1)
        for variant, columns in CONTRACTS.items()
        for index, column in enumerate(columns)
    ]))
    csv_new(OUT / 'feature_missingness.csv', pd.DataFrame([
        dict(variant=variant, feature=column, rows=len(enriched),
             missing=int(enriched[column].isna().sum()),
             missing_fraction=float(enriched[column].isna().mean()))
        for variant, columns in CONTRACTS.items()
        for column in columns
    ]))
    support = enriched.groupby(['year', 'distance_m']).agg(
        rows=('api_record_id', 'size'), races=('race_id', 'nunique'), days=('race_date', 'nunique'),
        no_previous=('previous_start_id', lambda values: int(values.isna().sum())),
        previous_status_normal=('previous_result_status', lambda values: int(values.eq('normal').sum())),
        previous_status_incomplete=('previous_result_status', lambda values: int(values.eq('non_normal_or_incomplete').sum())),
        no_same_distance_actual=('same_distance_last5_actual_n', lambda values: int(values.eq(0).sum())),
        no_same_distance_normal=('same_distance_last5_normal_n', lambda values: int(values.eq(0).sum())),
    ).reset_index()
    csv_new(OUT / 'support_by_year_distance.csv', support)
    quality_summary = dict(
        source_rows=int(len(source)), source_races=int(source.race_id.nunique()),
        source_started_rows=int(source.started.sum()),
        source_started_races=int(quality.started_n.gt(0).sum()),
        source_normal_complete_races=int(quality.rank_sequence_complete.sum()),
        source_incomplete_started_races=int(((quality.started_n.gt(0)) & (~quality.rank_sequence_complete)).sum()),
        source_zero_started_races=int(quality.started_n.eq(0).sum()),
        source_n1_races=int(quality.started_n.eq(1).sum()),
        previous_reference_rows=int(enriched.previous_start_id.notna().sum()),
        previous_distinct_races=int(source.set_index('api_record_id').loc[
            enriched.previous_start_id.dropna().astype('int64'), 'race_id'].nunique()),
        previous_incomplete_reference_rows=int(enriched.previous_result_status.eq('non_normal_or_incomplete').sum()),
        previous_incomplete_distinct_races=int(source.set_index('api_record_id').loc[
            enriched.loc[enriched.previous_result_status.eq('non_normal_or_incomplete'), 'previous_start_id'].astype('int64'), 'race_id'].nunique()),
        last5_reference_rows=int(lineage.history_kind.eq('last5_same_distance_start').sum()),
        last5_distinct_source_ids=int(lineage.loc[
            lineage.history_kind.eq('last5_same_distance_start'), 'source_api_record_id'].nunique()),
        previous_status_counts={str(k): int(v) for k, v in enriched.previous_result_status.value_counts(dropna=False).items()},
        source_snapshot_raw_finish_position_counts={
            str(k): int(v) for k, v in source.finish_position.value_counts(dropna=False).sort_index().items()
        },
        source_snapshot_started_false_raw_finish_position_counts={
            str(k): int(v) for k, v in source.loc[~source.started, 'finish_position'].value_counts(dropna=False).sort_index().items()
        },
        features_rows=int(len(enriched)), races=int(enriched.race_id.nunique()),
        evaluation_rows=int(enriched.year.ge(2024).sum()),
        evaluation_races=int(enriched.loc[enriched.year.ge(2024), 'race_id'].nunique()),
    )
    save_json(OUT / 'source_audit_summary.json', quality_summary)
    save_json(OUT / 'feature_contract.json', {
        variant: dict(columns=columns, retained=R1_COLUMNS, added=(F1_EXTRA + F2_EXTRA if variant == 'F2' else F1_EXTRA if variant == 'F1' else []), removed=[])
        for variant, columns in CONTRACTS.items()
    })

    artifacts = {
        path.name: sha(path) for path in OUT.iterdir()
        if path.is_file() and path.name != 'prepared_lock.json'
    }
    lock = dict(
        references=references, protected=protected, artifacts=artifacts,
        seed=SEED, parameters=base.PARAMS,
        versions={module.__name__: module.__version__ for module in [np, pd]},
        feature_columns={key: value for key, value in CONTRACTS.items()},
        audit=quality_summary,
    )
    save_json(OUT / 'prepared_lock.json', lock)
    print(json.dumps(quality_summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    prepare()
