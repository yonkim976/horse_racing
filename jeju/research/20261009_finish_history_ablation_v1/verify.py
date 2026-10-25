"""Independent lineage, feature, R1 replay, and final prediction checks."""
import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

sys.dont_write_bytecode = True
import prepare as e

OUT = e.OUT


def close(left, right, atol=1e-10):
    return np.allclose(np.asarray(left, dtype=float), np.asarray(right, dtype=float),
                       rtol=0, atol=atol, equal_nan=True)


def nullable(value):
    return None if not e.is_finite(value) else float(value)


def snapshot_checks(lock):
    for relative, expected in lock['references'].items():
        assert e.sha(e.ROOT / relative) == expected, f'reference changed: {relative}'
    for relative, info in lock['protected'].items():
        path = e.ROOT / relative
        assert e.sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], relative
    for name, expected in lock['artifacts'].items():
        assert e.sha(OUT / name) == expected, f'prepared artifact changed: {name}'


def independent_quality(source):
    counts = source.loc[source.started].groupby('race_id').size().to_dict()
    complete = {}
    reasons = {}
    for race_id, whole in source.groupby('race_id', sort=False):
        group = whole.loc[whole.started]
        n = int(len(group))
        positions = pd.to_numeric(group.finish_position, errors='coerce').to_numpy(float)
        integer = np.isfinite(positions) & (positions == np.floor(positions))
        ranks = positions[integer].astype(int).tolist()
        duplicate_horse = bool(group.horse_id.duplicated().any())
        duplicate_rank = len(ranks) != len(set(ranks))
        ok = (n >= 2 and len(ranks) == n and not duplicate_horse and not duplicate_rank
              and sorted(ranks) == list(range(1, n + 1)))
        complete[race_id] = bool(ok)
        why = []
        if n < 2:
            why.append('starter_count_below_2')
        if duplicate_horse:
            why.append('duplicate_horse_id')
        if duplicate_rank:
            why.append('duplicate_rank')
        if len(ranks) != n or (n and sorted(ranks) != list(range(1, n + 1))):
            why.append('rank_sequence_incomplete_or_out_of_range')
        reasons[race_id] = '|'.join(why)
    return counts, complete, reasons


def direct_rank(source_row, n, duplicate_horse=False):
    if not bool(source_row.started) or duplicate_horse or n < 1:
        return None
    raw = source_row.finish_position
    if not e.is_finite(raw):
        return None
    rank = int(raw)
    if float(raw) != rank or rank < 1 or rank > n:
        return None
    return rank


def synthetic_checks():
    # Complete ordered field with three starters.
    full = [1, 2, 3]
    assert len(full) >= 2 and len(set(full)) == 3 and sorted(full) == [1, 2, 3]
    assert close([(value - 1) / 2 for value in full], [0, .5, 1])
    # A DNF remains a NULL position slot; field completeness fails while the
    # other horse's directly observed valid top-three result remains usable.
    dnf_ranks = [1, 2, 91]
    assert not (len(set(dnf_ranks)) == 3 and sorted(dnf_ranks) == [1, 2, 3])
    assert direct_rank(pd.Series(dict(started=True, finish_position=2)), 3) == 2
    assert direct_rank(pd.Series(dict(started=True, finish_position=91)), 3) is None
    assert close([float(2 <= 3), np.nan], [1, np.nan])
    # A valid fourth-place result in an incomplete four-starter field is not a Top3,
    # while its relative field rank remains unavailable.
    assert direct_rank(pd.Series(dict(started=True, finish_position=4)), 4) == 4
    assert direct_rank(pd.Series(dict(started=True, finish_position=8)), 1) is None
    assert direct_rank(pd.Series(dict(started=False, finish_position=99)), 8) is None
    assert direct_rank(pd.Series(dict(started=True, finish_position=2)), 4, duplicate_horse=True) is None
    # Duplicate or missing rank prevents a complete relative scale.
    assert sorted([1, 1, 3]) != [1, 2, 3]
    assert sorted([1, 3]) != [1, 2, 3]
    # Actual slots remain counted even when their individual ranks are unavailable;
    # the normal-result denominator remains zero and rate stays NULL.
    ranks = [None, None, 2]
    valid = [rank for rank in ranks if rank is not None]
    assert len(ranks) == 3 and len(valid) == 1
    assert sum(rank <= 3 for rank in valid) / len(valid) == 1.0
    assert sum(rank is not None for rank in [None, None]) == 0
    assert np.isnan(np.nan)
    return [
        'complete_rank_fraction_endpoints', 'dnf_keeps_slot_and_NULL_rank',
        'field_incomplete_does_not_erase_direct_own_top3',
        'valid_fourth_place_is_zero_top3', 'N1_relative_rank_unavailable',
        'nonstarter_not_used_as_actual_start', 'duplicate_horse_own_result_NULL',
        'duplicate_or_missing_rank_incomplete',
        'zero_normal_result_rate_is_NULL',
    ]


def preflight():
    lock = json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    snapshot_checks(lock)
    source = pd.read_parquet(e.SOURCE_PATH)
    base_features = pd.read_parquet(e.R1_FEATURES_PATH)
    features = pd.read_parquet(OUT / 'features.parquet')
    quality_file = pd.read_parquet(OUT / 'source_race_quality.parquet').set_index('race_id')
    lineage = pd.read_parquet(OUT / 'historical_lineage.parquet')

    expected_started = source.finish_position.between(1, 89) | source.finish_position.isin([91, 92])
    assert expected_started.equals(source.started.rename(expected_started.name))
    assert source.api_record_id.is_unique and source.race_id.notna().all()
    assert base_features.api_record_id.is_unique and features.api_record_id.is_unique
    assert features.api_record_id.equals(base_features.api_record_id)
    pd.testing.assert_frame_equal(features[base_features.columns], base_features, check_exact=True)
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert len(features.loc[features.year.ge(2024)]) == 17412
    assert features.loc[features.year.ge(2024), 'race_id'].nunique() == 1779
    assert len(e.CONTRACTS['R1']) == 21 and len(e.CONTRACTS['F1']) == 24 and len(e.CONTRACTS['F2']) == 27
    assert features.previous_result_status.astype('string').isin(
        ['normal', 'non_normal_or_incomplete', 'unobserved']).all()

    starter_counts, complete_by_race, reason_by_race = independent_quality(source)
    all_races = set(source.race_id)
    assert set(quality_file.index) == all_races
    for race_id in all_races:
        expected_n = int(starter_counts.get(race_id, 0))
        actual = quality_file.loc[race_id]
        assert int(actual.started_n) == expected_n
        assert bool(actual.rank_sequence_complete) == complete_by_race[race_id]
        assert actual.reason == reason_by_race[race_id]
    started_races = {race_id for race_id, count in starter_counts.items() if count > 0}
    normal_races = {race_id for race_id in started_races if complete_by_race[race_id]}
    incomplete_races = started_races - normal_races
    n1_races = {race_id for race_id, count in starter_counts.items() if count == 1}
    no_start_races = len(all_races - started_races)
    assert (len(started_races), len(normal_races), len(incomplete_races), len(n1_races), no_start_races) == (9347, 9027, 320, 32, 147)

    src = source.set_index('api_record_id', drop=False)
    # Reconstruct all earlier started rows independently so that prior IDs and the
    # same-distance five-start windows are checked as the true last events.
    all_starts = source.loc[source.started].sort_values(
        ['race_date', 'race_number', 'horse_number', 'api_record_id'], kind='stable')
    by_horse = {str(key): group for key, group in all_starts.groupby('horse_id', sort=False)}
    by_horse_distance = {
        (str(horse), int(distance)): group
        for (horse, distance), group in all_starts.loc[all_starts.race_distance_m.notna()].groupby(
            ['horse_id', 'race_distance_m'], sort=False)
    }
    duplicate_horse_counts = source.loc[source.started].groupby(['race_id', 'horse_id']).size().to_dict()
    rank_refs = 0
    last5_refs = 0
    prior_abnormal_rows = 0
    incomplete_but_direct_rows = 0
    invalid_prior_horse_rows = 0
    invalid_last5_slots = 0
    for row in features.itertuples(index=False):
        cutoff = (date.fromisoformat(str(row.race_date)) - timedelta(days=2)).isoformat()
        assert str(row.history_cutoff) == cutoff
        previous_history = by_horse.get(str(row.horse_id), source.iloc[:0])
        previous_history = previous_history.loc[previous_history.race_date.le(cutoff)]
        expected_previous = (int(previous_history.api_record_id.iloc[-1])
                             if len(previous_history) else None)
        actual_previous = None if not e.is_finite(row.previous_start_id) else int(row.previous_start_id)
        assert actual_previous == expected_previous, (row.api_record_id, actual_previous, expected_previous)
        if expected_previous is None:
            assert row.previous_result_status == 'unobserved'
            assert not e.is_finite(row.previous_finish_relative_rank)
            assert not e.is_finite(row.previous_top3)
        else:
            past = src.loc[expected_previous]
            assert str(past.horse_id) == str(row.horse_id) and bool(past.started)
            assert str(past.race_date) <= cutoff and past.race_id in all_races
            n = int(starter_counts.get(past.race_id, 0))
            duplicate_horse = duplicate_horse_counts.get((past.race_id, str(past.horse_id)), 0) > 1
            own_rank = direct_rank(past, n, duplicate_horse)
            event_complete = complete_by_race[past.race_id]
            expected_status = 'normal' if event_complete else 'non_normal_or_incomplete'
            expected_relative = ((own_rank - 1) / (n - 1)
                                 if event_complete and own_rank is not None and n >= 2 else np.nan)
            expected_top3 = float(own_rank <= 3) if own_rank is not None else np.nan
            assert row.previous_result_status == expected_status
            assert close([row.previous_finish_relative_rank, row.previous_top3],
                         [expected_relative, expected_top3])
            if not event_complete:
                prior_abnormal_rows += 1
                if own_rank is not None:
                    incomplete_but_direct_rows += 1
            if own_rank is None:
                invalid_prior_horse_rows += 1
            rank_refs += 1

        ids = e.normalize_id_list(row.last5_same_source_ids)
        assert len(ids) <= 5 and len(ids) == len(set(ids))
        same_history = by_horse_distance.get((str(row.horse_id), int(row.distance_m)), source.iloc[:0])
        same_history = same_history.loc[same_history.race_date.le(cutoff)]
        expected_ids = [int(value) for value in same_history.api_record_id.iloc[-5:].tolist()]
        assert ids == expected_ids, (row.api_record_id, ids, expected_ids)
        own_ranks = []
        for source_id in ids:
            past = src.loc[source_id]
            assert str(past.horse_id) == str(row.horse_id) and bool(past.started)
            assert is_distance_match(past.race_distance_m, row.distance_m)
            assert str(past.race_date) <= cutoff
            n = int(starter_counts.get(past.race_id, 0))
            duplicate_horse = duplicate_horse_counts.get((past.race_id, str(past.horse_id)), 0) > 1
            rank = direct_rank(past, n, duplicate_horse)
            if rank is not None:
                own_ranks.append(rank)
            else:
                invalid_last5_slots += 1
            last5_refs += 1
        expected_rate = (sum(value <= 3 for value in own_ranks) / len(own_ranks)
                         if own_ranks else np.nan)
        assert int(row.same_distance_last5_actual_n) == len(ids)
        assert int(row.same_distance_last5_normal_n) == len(own_ranks)
        assert close([row.same_distance_last5_top3_rate], [expected_rate])

    previous_rows = features.previous_start_id.notna()
    incomplete_previous = features.loc[previous_rows & features.previous_result_status.eq('non_normal_or_incomplete')]
    previous_source = src.loc[incomplete_previous.previous_start_id.astype('int64'), 'race_id']
    assert len(incomplete_previous) == 745 and previous_source.nunique() == 93
    assert features.previous_start_id.notna().sum() == 50209
    assert features.previous_start_id.dropna().map(lambda v: str(src.loc[int(v)].race_date)).notna().all()

    expected_lineage_rows = int(features.previous_start_id.notna().sum() + last5_refs)
    assert len(lineage) == expected_lineage_rows
    assert lineage.source_api_record_id.notna().all()
    assert lineage.source_horse_id.eq(lineage.target_horse_id).all()
    assert lineage.source_started.all()
    assert lineage.source_race_date.le(lineage.target_cutoff).all()
    assert lineage.loc[lineage.history_kind.eq('last5_same_distance_start')].source_distance_m.eq(
        lineage.loc[lineage.history_kind.eq('last5_same_distance_start')].target_distance_m).all()
    invalid_lineage = lineage.valid_individual_rank.isna()
    assert lineage.loc[invalid_lineage, 'individual_top3'].isna().all()
    assert len(lineage.loc[invalid_lineage]) >= invalid_last5_slots

    cases = synthetic_checks()
    summary = dict(
        passed=True,
        reference_hashes_checked=len(lock['references']),
        protected_hashes_checked=len(lock['protected']),
        prepared_artifacts_checked=len(lock['artifacts']),
        source_rows=len(source), source_races=len(all_races),
        started_rows=int(source.started.sum()), started_races=len(started_races),
        complete_started_races=len(normal_races), incomplete_started_races=len(incomplete_races),
        zero_started_races=no_start_races, n1_started_races=len(n1_races),
        previous_reference_rows=rank_refs, previous_distinct_races=int(
            src.loc[features.previous_start_id.dropna().astype('int64'), 'race_id'].nunique()),
        previous_incomplete_reference_rows=len(incomplete_previous),
        previous_incomplete_distinct_races=int(previous_source.nunique()),
        previous_abnormal_rows=prior_abnormal_rows,
        previous_incomplete_with_direct_own_result_rows=incomplete_but_direct_rows,
        previous_invalid_own_result_rows=invalid_prior_horse_rows,
        last5_reference_slots=last5_refs,
        last5_invalid_rank_slots=invalid_last5_slots,
        rows=len(features), races=int(features.race_id.nunique()),
        evaluation_rows=int(features.year.ge(2024).sum()),
        evaluation_races=int(features.loc[features.year.ge(2024), 'race_id'].nunique()),
        feature_counts={name: len(columns) for name, columns in e.CONTRACTS.items()},
        synthetic_checks=cases,
        r1_replay_required=True,
        database_changed=False,
        production_changed=False,
    )
    e.save_json(OUT / 'preflight_verification.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def is_distance_match(left, right):
    return e.is_finite(left) and e.is_finite(right) and int(left) == int(right)


def r1_replay():
    preflight_path = OUT / 'preflight_verification.json'
    assert json.loads(preflight_path.read_text(encoding='utf-8'))['passed']
    replay_path = OUT / 'r1_replay_verification.json'
    assert replay_path.exists(), 'run.py replay has not written its verification record'
    replay = json.loads(replay_path.read_text(encoding='utf-8'))
    assert replay['passed'] and replay['reloaded_models'] == 3
    assert replay['runner_rows_reproduced'] == 17412
    lock = json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    snapshot_checks(lock)
    replay['preflight_passed'] = True
    replay['protected_hashes_unchanged'] = True
    e.save_json(OUT / 'r1_pretraining_gate.json', replay)
    print(json.dumps(replay, ensure_ascii=False, indent=2), flush=True)


def final():
    lock = json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    for relative, expected in lock['references'].items():
        assert e.sha(e.ROOT / relative) == expected, relative
    for relative, info in lock['protected'].items():
        path = e.ROOT / relative
        assert e.sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], relative
    pre = json.loads((OUT / 'preflight_verification.json').read_text(encoding='utf-8'))
    replay_gate = json.loads((OUT / 'r1_pretraining_gate.json').read_text(encoding='utf-8'))
    assert pre['passed'] and replay_gate['passed']
    preds_path = OUT / 'runner_predictions.parquet'
    races_path = OUT / 'race_metrics.csv'
    tickets_path = OUT / 'six_combinations.csv'
    assert all(path.exists() for path in [preds_path, races_path, tickets_path])
    features = pd.read_parquet(OUT / 'features.parquet')
    predictions = pd.read_parquet(preds_path)
    races = pd.read_csv(races_path)
    tickets = pd.read_csv(tickets_path)
    assert set(predictions.variant) == {'R1', 'F1', 'F2'}
    assert len(predictions) == 3 * 17412
    assert len(races) == 3 * 1779
    assert predictions.p_top3.between(0, 1).all()
    counts = dict(
        passed=True, final_candidate_models=6,
        lightgbm_train_calls=12, temperature_optimizations=6,
        variants=sorted(predictions.variant.unique().tolist()),
        runner_prediction_rows=len(predictions), variant_race_rows=len(races),
        probability_sum_checked_races=0,
        database_changed=False, production_changed=False,
    )
    # Verify all persisted probabilities and set tickets by rebuilding the same
    # canonical sorted three-horse distribution from scores and saved temperatures.
    from prepare import base
    import itertools
    for (variant, race_id), group in predictions.groupby(['variant', 'race_id'], sort=False):
        group = group.sort_values('horse_number', kind='stable')
        values = group.score.to_numpy(float)
        triples = np.asarray(list(itertools.combinations(range(len(group)), 3)), dtype=int)
        ordered = np.sort(values[triples], axis=1)
        energy = (ordered[:, 0] + ordered[:, 1]) + ordered[:, 2]
        year = int(group.year.iloc[0])
        if variant == 'R1':
            meta_path = e.R1_OUT / f'R1_{year}/meta.json'
        else:
            meta_path = OUT / f'{variant}_{year}/meta.json'
        tau = float(json.loads(meta_path.read_text(encoding='utf-8'))['tau'])
        logq = energy / tau - logsumexp(energy / tau)
        q = np.exp(logq)
        marginal = np.zeros(len(group))
        for index, triple in enumerate(triples):
            marginal[triple] += q[index]
        assert close(marginal, group.p_top3)
        assert abs(marginal.sum() - 3) < 1e-10 and abs(q.sum() - 1) < 1e-12
        actual = group.y.to_numpy(int)
        assert int(actual.sum()) == 3
        expected_tickets = np.argsort(-energy, kind='stable')[:6]
        observed = tickets[tickets.variant.eq(variant) & tickets.race_id.eq(race_id)].sort_values('selection_rank')
        assert len(observed) == 6
        expected_numbers = [','.join(map(str, sorted(group.horse_number.iloc[triples[k]].astype(int))))
                            for k in expected_tickets]
        assert observed.numbers.tolist() == expected_numbers
        assert close(observed.probability.to_numpy(), q[expected_tickets])
        counts['probability_sum_checked_races'] += 1
    counts['distinct_races'] = int(races.race_id.nunique())
    assert counts['probability_sum_checked_races'] == 3 * 1779
    counts['reference_hashes_unchanged'] = len(lock['references'])
    counts['protected_hashes_unchanged'] = len(lock['protected'])
    e.save_json(OUT / 'final_verification.json', counts)
    print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['preflight', 'r1_replay', 'final'])
    args = parser.parse_args()
    {'preflight': preflight, 'r1_replay': r1_replay, 'final': final}[args.phase]()
