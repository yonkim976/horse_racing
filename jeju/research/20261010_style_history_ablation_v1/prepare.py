"""Build the fixed F1_STYLE6 input from the audited, immutable history cache."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_DIR = HERE.parent / '20261009_finish_history_ablation_v1'
BASE_OUT = BASE_DIR / 'outputs'
PROFILE_DIR = HERE.parent / '20261008_horse_profile_baseline_v1'
SOURCE_AUDIT_DIR = HERE.parent / '20261010_style_history_source_audit_v1'
SOURCE_AUDIT_PATH = SOURCE_AUDIT_DIR / 'source_audit.json'
FULL_POINT_CACHE_PATH = SOURCE_AUDIT_DIR / 'api4_full_started_point_quality_cache.parquet'
SLOT_CACHE_PATH = SOURCE_AUDIT_DIR / 'actual_slot_point_eligibility.parquet'
OUT = HERE / 'outputs'
FEATURES_PATH = BASE_OUT / 'features.parquet'
SOURCE_SNAPSHOT_PATH = PROFILE_DIR / 'outputs_v2' / 'source_snapshot.parquet'
SEED = 20261008
VARIANT = 'F1_STYLE6'
YEARS = [2024, 2025, 2026]

STYLE_FEATURES = [
    'hist_s1f_relpos_mean5',
    'hist_s1f_relpos_n',
    'hist_s1f_to_c4_forward_mean5',
    'hist_s1f_to_c4_pair_n',
    'hist_c4_to_g1f_forward_mean5',
    'hist_c4_to_g1f_pair_n',
]
STYLE_MAPPING = {
    'hist_s1f_relpos_mean5': 'mean of slot-cache s1f_r over s1f_final_point_eligible slots',
    'hist_s1f_relpos_n': 'count of those same source slots; 0..5; mean NULL at n=0',
    'hist_s1f_to_c4_forward_mean5': 'mean of s1f_r - c4_r over s1f_to_c4_pair_eligible slots',
    'hist_s1f_to_c4_pair_n': 'count of those same-slot eligible S1F/4C pairs; 0..5; mean NULL at n=0',
    'hist_c4_to_g1f_forward_mean5': 'mean of c4_r - g1f_r over c4_to_g1f_pair_eligible slots',
    'hist_c4_to_g1f_pair_n': 'count of those same-slot eligible 4C/G1F pairs; 0..5; mean NULL at n=0',
}
SLOT_FEATURE_SPECS = {
    'hist_s1f_relpos_mean5': ('s1f_final_point_eligible', 's1f_r'),
    'hist_s1f_to_c4_forward_mean5': ('s1f_to_c4_pair_eligible', 's1f_to_c4_forward_change'),
    'hist_c4_to_g1f_forward_mean5': ('c4_to_g1f_pair_eligible', 'c4_to_g1f_forward_change'),
}
SLOT_N_FEATURES = {
    'hist_s1f_relpos_n': 's1f_final_point_eligible',
    'hist_s1f_to_c4_pair_n': 's1f_to_c4_pair_eligible',
    'hist_c4_to_g1f_pair_n': 'c4_to_g1f_pair_eligible',
}


def load_reference_module():
    path = BASE_DIR / 'prepare.py'
    spec = importlib.util.spec_from_file_location('style_f1_history_reference_prepare', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load fixed F1 input contract: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F1 = load_reference_module()
BASE_COLUMNS = list(F1.CONTRACTS['F1'])
MODEL_COLUMNS = BASE_COLUMNS + STYLE_FEATURES
assert len(BASE_COLUMNS) == 24 and len(MODEL_COLUMNS) == 30


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_json_new(path, payload):
    path = Path(path)
    assert not path.exists(), f'refusing to overwrite existing result: {path}'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write('\n')


def save_json_replace(path, payload):
    """Atomically refresh this experiment's lock/receipt metadata only."""
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_frame_new(path, frame, parquet=False):
    path = Path(path)
    assert not path.exists(), f'refusing to overwrite existing result: {path}'
    if parquet:
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def is_finite(value):
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def as_bool(value):
    if pd.isna(value):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value in (0, 1):
        return bool(value)
    raise AssertionError(f'expected an audited boolean value, got {value!r}')


def normalize_ids(value):
    return F1.normalize_id_list(value)


def verify_reference_lock(lock_path):
    lock = load_json(lock_path)
    for relative, expected in lock['references'].items():
        path = ROOT / relative
        assert path.is_file() and sha256(path) == expected, f'F1 reference changed: {relative}'
    for relative, info in lock['protected'].items():
        path = ROOT / relative
        assert path.is_file() and sha256(path) == info['sha256'], f'F1 protected source changed: {relative}'
        assert path.stat().st_size == int(info['bytes']), f'F1 protected byte count changed: {relative}'
    for name, expected in lock['artifacts'].items():
        path = BASE_OUT / name
        assert path.is_file() and sha256(path) == expected, f'F1 artifact changed: {name}'
    return lock


def verify_audit_receipt(audit):
    assert audit.get('passed') is True, 'independent full-roster source audit has not passed'
    assert audit.get('fit_or_prediction_work') is False
    reconciliation = audit.get('f1_population', {}).get('full_roster_reconciliation', {})
    assert reconciliation.get('snapshot_common_rows_exactly_match_full_base') is True
    assert reconciliation.get('races_where_snapshot_started_n_differs_from_full') == 0
    assert reconciliation.get('full_started_null_api_id') == 0
    assert reconciliation.get('full_started_null_horse_id') == 0
    assert reconciliation.get('full_started_null_horse_number') == 0
    assert reconciliation.get('full_started_duplicate_api_id_rows') == 0
    assert reconciliation.get('full_started_duplicate_horse_id_rows') == 0
    assert reconciliation.get('full_started_duplicate_horse_number_rows') == 0
    status_policy = audit.get('source_status_policy', {})
    assert status_policy.get('api4_order_allowed') == [
        'api_positive_unreviewed', 'website_corrected'
    ]
    assert status_policy.get('api303_group_status_allowed') == [
        'api_group_unreviewed', 'api_group_unavailable'
    ]
    assert status_policy.get('api303_parser_is_diagnostic_only') is True
    unknown_domain = audit.get('source_slot_quality', {}).get('unknown_status_domain', {})
    assert unknown_domain.get('api4_order') == []
    assert unknown_domain.get('api303_group') == []
    assert audit.get('chronology_and_distance', {}).get('time_consistency_not_feature_or_source_gate') is True
    mapping = audit.get('candidate_6_field_definition', {}).get('feature_mapping')
    assert isinstance(mapping, dict)
    assert set(mapping) == set(STYLE_FEATURES), 'source audit feature mapping differs from contract'
    artifacts = audit.get('artifacts')
    assert isinstance(artifacts, dict)
    allowed_audit_artifacts = {
        'api4_full_started_point_quality_cache.parquet',
        'actual_slot_point_eligibility.parquet',
        'support_by_distance_year.csv',
        'point_support_by_distance.csv',
        'api303_group_support_by_distance.csv',
        'cross_source_interval_examples.csv',
        'full_roster_reconciliation_by_race.csv',
        'race_point_quality_support.csv',
        'point_time_chronology_by_distance.csv',
    }
    assert set(artifacts) == allowed_audit_artifacts, 'source audit artifact set differs from reviewed contract'
    for name, entry in artifacts.items():
        assert Path(name).name == name, f'unsafe source audit artifact name: {name}'
        path = SOURCE_AUDIT_DIR / name
        assert isinstance(entry, dict) and path.is_file()
        assert entry.get('sha256') == sha256(path) and int(entry.get('bytes', -1)) == path.stat().st_size
    for path in (FULL_POINT_CACHE_PATH, SLOT_CACHE_PATH):
        entry = artifacts.get(path.name)
        assert isinstance(entry, dict) and entry.get('sha256') == sha256(path), (
            f'source cache hash does not match locked audit receipt: {path.name}'
        )
        assert int(entry.get('bytes', -1)) == path.stat().st_size
    for feature, expected in STYLE_MAPPING.items():
        assert mapping[feature] == expected, f'source feature mapping differs: {feature}'
    return audit


def _validate_cache_shape(full_cache, slot_cache):
    full_required = {
        'race_id', 'race_date', 'race_distance_m', 'api_record_id', 'horse_id', 'horse_number',
        'point', 'full_started_n', 'quality_order_value', 'quality_order_status',
        'local_rank_ok', 'point_permutation_valid', 'api4_order_permutation_valid',
        'race_point_eligible', 'normalized_rank',
        'api303_group_status', 'api303_group_gate_supported',
    }
    slot_required = {
        'target_api_record_id', 'source_api_record_id', 'slot_oldest_to_newest',
        'slot_position', 'source_horse_id', 'source_distance_m',
        'source_race_id', 'source_race_date', 'target_cutoff', 'target_horse_id',
        'target_distance_m', 'source_snapshot_valid_time', 'full_started_n',
        's1f_r', 's1f_final_point_eligible', 's1f_order', 's1f_order_status',
        's1f_individual_order_valid', 's1f_full_point_permutation_valid',
        's1f_race_point_eligible',
        's1f_api303_group_status', 's1f_group_status_gate',
        's1f_group_interval_parse_pass_diagnostic_only',
        'c4_r', 'c4_final_point_eligible', 'c4_order', 'c4_order_status',
        'c4_individual_order_valid', 'c4_full_point_permutation_valid',
        'c4_race_point_eligible',
        'c4_api303_group_status', 'c4_group_status_gate',
        'c4_group_interval_parse_pass_diagnostic_only',
        'g1f_r', 'g1f_final_point_eligible', 'g1f_order', 'g1f_order_status',
        'g1f_individual_order_valid', 'g1f_full_point_permutation_valid',
        'g1f_race_point_eligible',
        'g1f_api303_group_status', 'g1f_group_status_gate',
        'g1f_group_interval_parse_pass_diagnostic_only',
        's1f_to_c4_pair_eligible', 's1f_to_c4_forward_change',
        'c4_to_g1f_pair_eligible', 'c4_to_g1f_forward_change',
    }
    assert full_required.issubset(full_cache.columns), f'missing full-cache fields: {full_required - set(full_cache.columns)}'
    assert slot_required.issubset(slot_cache.columns), f'missing slot-cache fields: {slot_required - set(slot_cache.columns)}'
    assert set(full_cache.point.dropna().astype(str)) == {'S1F', '4C', 'G1F'}
    assert not full_cache.duplicated(['api_record_id', 'point']).any()
    assert not slot_cache.duplicated(['target_api_record_id', 'slot_oldest_to_newest']).any()
    assert slot_cache.slot_position.astype('int64').equals(slot_cache.slot_oldest_to_newest.astype('int64'))
    assert slot_cache.source_horse_id.astype(str).equals(slot_cache.target_horse_id.astype(str))
    assert slot_cache.source_distance_m.astype('int64').equals(slot_cache.target_distance_m.astype('int64'))
    if 'started_n' in full_cache:
        assert full_cache.started_n.astype('int64').equals(full_cache.full_started_n.astype('int64'))
    if 'complete_unique_1_to_n_permutation' in full_cache:
        assert full_cache.complete_unique_1_to_n_permutation.map(as_bool).equals(
            full_cache.point_permutation_valid.map(as_bool)
        )
    if 'api303_group_status_gate' in full_cache:
        assert full_cache.api303_group_status_gate.map(as_bool).equals(
            full_cache.api303_group_gate_supported.map(as_bool)
        )
    assert full_cache.api4_order_permutation_valid.map(as_bool).equals(
        full_cache.point_permutation_valid.map(as_bool)
    )
    assert full_cache.race_point_eligible.map(as_bool).equals(
        full_cache.point_permutation_valid.map(as_bool) & full_cache.api303_group_gate_supported.map(as_bool)
    )
    for prefix in ('s1f', 'c4', 'g1f'):
        if f'{prefix}_api303_group_status_gate' in slot_cache:
            assert slot_cache[f'{prefix}_api303_group_status_gate'].map(as_bool).equals(
                slot_cache[f'{prefix}_group_status_gate'].map(as_bool)
            )
    assert slot_cache.source_api_record_id.notna().all()


def _validate_full_point_permutations(full_cache, source_snapshot, slot_cache):
    checks = 0
    slot_races = set(slot_cache.source_race_id.astype(str))
    expected_keys = {(race_id, point) for race_id in slot_races for point in ('S1F', '4C', 'G1F')}
    actual_keys = set(zip(full_cache.race_id.astype(str), full_cache.point.astype(str)))
    assert actual_keys == expected_keys, 'full cache must have every referenced source race and point exactly once'
    started_snapshot = source_snapshot.loc[source_snapshot.started.astype(bool)].copy()
    snapshot_by_race = {
        str(race_id): group for race_id, group in started_snapshot.groupby('race_id', sort=False)
    }
    for (race_id, point), group in full_cache.groupby(['race_id', 'point'], sort=False, dropna=False):
        n_values = pd.to_numeric(group.full_started_n, errors='coerce').dropna().unique()
        assert len(n_values) == 1, f'inconsistent actual starter N: {race_id}/{point}'
        n = int(n_values[0])
        assert n == len(group), f'full starter rows do not cover roster: {race_id}/{point}'
        assert group.horse_id.astype(str).nunique() == n, f'duplicate/missing horse IDs: {race_id}/{point}'
        assert group.horse_number.astype(str).nunique() == n, f'duplicate/missing horse numbers: {race_id}/{point}'
        assert group.api_record_id.nunique() == n, f'duplicate/missing record IDs: {race_id}/{point}'
        assert str(race_id) in snapshot_by_race, f'full point race absent from source snapshot: {race_id}'
        snapshot_group = snapshot_by_race[str(race_id)]
        assert len(snapshot_group) == n, f'snapshot/full starter N mismatch: {race_id}/{point}'
        assert set(group.api_record_id.astype('int64')) == set(snapshot_group.api_record_id.astype('int64'))
        assert set(group.horse_id.astype(str)) == set(snapshot_group.horse_id.astype(str))
        assert set(group.horse_number.astype('int64')) == set(snapshot_group.horse_number.astype('int64'))
        expected_field = {'S1F': 'sjS1fOrd', '4C': 'sj_4cOrd', 'G1F': 'sjG1fOrd'}[str(point)]
        assert group.field_name.astype(str).eq(expected_field).all()
        permutation = group.point_permutation_valid.map(as_bool)
        assert permutation.nunique(dropna=False) == 1, (
            f'permutation validity must be race-point consistent: {race_id}/{point}'
        )
        group_status = group.api303_group_status.astype('string')
        allowed_group = group_status.isin(['api_group_unreviewed', 'api_group_unavailable'])
        assert group.api303_group_status.astype('string').nunique(dropna=False) == 1, (
            f'group status must be race-point consistent: {race_id}/{point}'
        )
        group_gate = group.api303_group_gate_supported.map(as_bool)
        assert group_gate.eq(allowed_group).all(), f'API303 point gate/status mismatch: {race_id}/{point}'
        assert group_gate.nunique(dropna=False) == 1, f'API303 gate must be race-point consistent: {race_id}/{point}'
        race_point_eligible = bool(permutation.iloc[0] and group_gate.iloc[0])
        if 'race_point_eligible' in group:
            assert group.race_point_eligible.map(as_bool).eq(race_point_eligible).all(), (
                f'race-point eligibility must equal permutation AND group gate: {race_id}/{point}'
            )
        assert group.api4_order_permutation_valid.map(as_bool).equals(permutation), (
            f'API4 permutation alias mismatch: {race_id}/{point}'
        )
        assert group.race_point_eligible.map(as_bool).eq(race_point_eligible).all(), (
            f'race-point eligibility must equal permutation AND group gate: {race_id}/{point}'
        )
        if bool(permutation.all()):
            assert group.local_rank_ok.map(as_bool).all(), f'permutation includes invalid local rank: {race_id}/{point}'
            ranks = pd.to_numeric(group.quality_order_value, errors='coerce').to_numpy(float)
            assert np.array_equal(np.sort(ranks), np.arange(1, n + 1, dtype=float)), (
                f'not a complete 1..N permutation: {race_id}/{point}'
            )
            assert group.quality_order_status.astype(str).isin(
                ['api_positive_unreviewed', 'website_corrected']
            ).all(), f'unapproved API4 quality order status: {race_id}/{point}'
            norm = (ranks - 1.0) / (n - 1.0) if n >= 2 else np.full(n, np.nan)
            stored = pd.to_numeric(group.normalized_rank, errors='coerce').to_numpy(float)
            if bool(group_gate.all()):
                assert np.allclose(stored, norm, rtol=0, atol=1e-12, equal_nan=True)
            else:
                assert not np.isfinite(stored).any(), f'group-held rank must be NULL: {race_id}/{point}'
        else:
            assert not group.normalized_rank.notna().any(), f'failed permutation must fail closed: {race_id}/{point}'
        checks += 1
    return checks


def build_style_features(features, source_snapshot, slot_cache):
    assert features.api_record_id.is_unique
    assert features.race_id.notna().all()
    assert source_snapshot.api_record_id.is_unique
    source = source_snapshot.set_index('api_record_id', drop=False)
    slot_groups = {int(key): group.sort_values('slot_oldest_to_newest', kind='stable')
                   for key, group in slot_cache.groupby('target_api_record_id', sort=False)}
    rows = []
    lineage_rows = []
    for row in features.itertuples(index=False):
        target_id = int(row.api_record_id)
        ids = normalize_ids(row.last5_same_source_ids)
        assert len(ids) <= 5 and len(ids) == len(set(ids))
        slots = slot_groups.get(target_id)
        if slots is None:
            assert not ids, f'missing audited slot rows for target {target_id}'
            slots = slot_cache.iloc[:0]
        else:
            assert len(slots) == len(ids), f'audit slot count differs from F1 for {target_id}'
            assert slots.source_api_record_id.astype('int64').tolist() == ids, (
                f'audit slot ID/order differs from F1 for {target_id}'
            )
            assert slots.slot_oldest_to_newest.astype(int).tolist() == list(range(1, len(ids) + 1))

        values_by_feature = {feature: [] for feature in SLOT_FEATURE_SPECS}
        for slot in slots.itertuples(index=False):
            source_id = int(slot.source_api_record_id)
            assert source_id in source.index, f'historical actual slot missing from F1 source snapshot: {source_id}'
            past = source.loc[source_id]
            assert isinstance(past, pd.Series)
            assert str(past.horse_id) == str(row.horse_id)
            assert str(slot.target_horse_id) == str(row.horse_id)
            assert bool(past.started)
            assert str(past.race_id) == str(slot.source_race_id)
            assert str(past.race_date) == str(slot.source_race_date)
            assert str(past.race_date) <= str(row.history_cutoff) == str(slot.target_cutoff)
            assert is_finite(past.race_distance_m) and int(past.race_distance_m) == int(row.distance_m)
            assert int(slot.target_distance_m) == int(row.distance_m)
            assert int(past.race_distance_m) == int(row.distance_m)
            source_valid_time = bool(past.valid_time)
            assert as_bool(slot.source_snapshot_valid_time) == source_valid_time
            assert int(slot.full_started_n) >= 1
            for prefix in ('s1f', 'c4', 'g1f'):
                order_valid = as_bool(getattr(slot, f'{prefix}_individual_order_valid'))
                perm_valid = as_bool(getattr(slot, f'{prefix}_full_point_permutation_valid'))
                group_status = getattr(slot, f'{prefix}_api303_group_status')
                group_gate = as_bool(getattr(slot, f'{prefix}_group_status_gate'))
                allowed_group_status = (not pd.isna(group_status) and
                                        str(group_status) in ('api_group_unreviewed', 'api_group_unavailable'))
                assert group_gate == allowed_group_status
                rank_value = getattr(slot, f'{prefix}_r')
                order_value = getattr(slot, f'{prefix}_order')
                order_status = getattr(slot, f'{prefix}_order_status')
                rank_usable = perm_valid and group_gate
                if perm_valid:
                    n_source = int(slot.full_started_n)
                    assert n_source >= 2 and order_valid
                    assert order_status in ('api_positive_unreviewed', 'website_corrected')
                    assert is_finite(order_value) and float(order_value).is_integer()
                    expected_rank = (int(order_value) - 1) / (n_source - 1)
                    if rank_usable:
                        assert is_finite(rank_value) and np.isclose(
                            float(rank_value), expected_rank, rtol=0, atol=1e-12
                        )
                    else:
                        assert not is_finite(rank_value), f'group-held point rank must be NULL: {source_id}/{prefix}'
                else:
                    assert not is_finite(rank_value), f'failed point permutation must be NULL: {source_id}/{prefix}'
                final_eligible = as_bool(getattr(slot, f'{prefix}_final_point_eligible'))
                assert as_bool(getattr(slot, f'{prefix}_race_point_eligible')) == rank_usable
                assert final_eligible == (source_valid_time and rank_usable and is_finite(rank_value))

            expected_s1f_c4_pair = (
                as_bool(slot.s1f_final_point_eligible) and as_bool(slot.c4_final_point_eligible)
            )
            expected_c4_g1f_pair = (
                as_bool(slot.c4_final_point_eligible) and as_bool(slot.g1f_final_point_eligible)
            )
            assert as_bool(slot.s1f_to_c4_pair_eligible) == expected_s1f_c4_pair
            assert as_bool(slot.c4_to_g1f_pair_eligible) == expected_c4_g1f_pair
            for prefix in ('s1f', 'c4', 'g1f'):
                if hasattr(slot, f'{prefix}_race_point_eligible'):
                    expected_race_point = (
                        as_bool(getattr(slot, f'{prefix}_full_point_permutation_valid'))
                        and as_bool(getattr(slot, f'{prefix}_group_status_gate'))
                    )
                    assert as_bool(getattr(slot, f'{prefix}_race_point_eligible')) == expected_race_point
            if expected_s1f_c4_pair:
                expected_change = float(slot.s1f_r) - float(slot.c4_r)
                assert is_finite(slot.s1f_to_c4_forward_change)
                assert np.isclose(float(slot.s1f_to_c4_forward_change), expected_change, rtol=0, atol=1e-12)
            else:
                assert not is_finite(slot.s1f_to_c4_forward_change)
            if expected_c4_g1f_pair:
                expected_change = float(slot.c4_r) - float(slot.g1f_r)
                assert is_finite(slot.c4_to_g1f_forward_change)
                assert np.isclose(float(slot.c4_to_g1f_forward_change), expected_change, rtol=0, atol=1e-12)
            else:
                assert not is_finite(slot.c4_to_g1f_forward_change)
            lineage = dict(
                target_api_record_id=target_id,
                target_race_id=str(row.race_id),
                target_horse_id=str(row.horse_id),
                target_distance_m=int(row.distance_m),
                target_cutoff=str(row.history_cutoff),
                source_api_record_id=source_id,
                source_race_id=str(past.race_id),
                source_race_date=str(past.race_date),
                source_horse_id=str(past.horse_id),
                source_distance_m=int(past.race_distance_m),
                slot_position=int(slot.slot_oldest_to_newest),
                source_snapshot_valid_time=source_valid_time,
                full_started_n=int(slot.full_started_n),
            )
            for prefix in ('s1f', 'c4', 'g1f'):
                for suffix in ('order', 'order_status', 'r', 'individual_order_valid',
                               'full_point_permutation_valid', 'api303_group_status',
                               'group_status_gate', 'group_interval_parse_pass_diagnostic_only',
                               'final_point_eligible'):
                    value = getattr(slot, f'{prefix}_{suffix}')
                    if suffix in ('order', 'r') and not is_finite(value):
                        value = None
                    elif suffix in ('individual_order_valid', 'full_point_permutation_valid',
                                    'group_status_gate', 'group_interval_parse_pass_diagnostic_only',
                                    'final_point_eligible'):
                        value = as_bool(value)
                    lineage[f'{prefix}_{suffix}'] = value
                point_eligible = as_bool(getattr(slot, f'{prefix}_final_point_eligible'))
                reasons = []
                if not source_valid_time:
                    reasons.append('source_snapshot_valid_time_false')
                if not perm_valid:
                    reasons.append('api4_full_roster_permutation_failed')
                if not group_gate:
                    reasons.append('api303_group_status_hold')
                if perm_valid and group_gate and not is_finite(getattr(slot, f'{prefix}_r')):
                    reasons.append('normalized_rank_unavailable')
                lineage[f'{prefix}_exclusion_reason'] = '|'.join(reasons) if reasons else 'valid'
            for feature, (eligible_column, value_column) in SLOT_FEATURE_SPECS.items():
                eligible = as_bool(getattr(slot, eligible_column))
                value = getattr(slot, value_column)
                if eligible:
                    assert source_valid_time, f'valid_time=False slot contributed to {feature}: {source_id}'
                    assert is_finite(value), f'eligible slot has no numeric value: {feature}/{source_id}'
                    values_by_feature[feature].append(float(value))
                lineage[f'{feature}_eligible'] = eligible
                # Preserve the source rank/transition above as a diagnostic, but
                # a feature contribution is NULL whenever its final gate fails.
                lineage[f'{feature}_value'] = float(value) if eligible else None
            for count_feature, eligibility_column in SLOT_N_FEATURES.items():
                lineage[f'{count_feature}_eligible'] = as_bool(getattr(slot, eligibility_column))
            lineage_rows.append(lineage)

        record = {'api_record_id': target_id}
        for count_feature, eligible_column in SLOT_N_FEATURES.items():
            if len(slots):
                count = int(slots[eligible_column].map(as_bool).sum())
            else:
                count = 0
            assert 0 <= count <= len(ids) <= 5
            record[count_feature] = count
        for mean_feature, values in values_by_feature.items():
            count_feature = {
                'hist_s1f_relpos_mean5': 'hist_s1f_relpos_n',
                'hist_s1f_to_c4_forward_mean5': 'hist_s1f_to_c4_pair_n',
                'hist_c4_to_g1f_forward_mean5': 'hist_c4_to_g1f_pair_n',
            }[mean_feature]
            assert len(values) == record[count_feature]
            record[mean_feature] = float(np.mean(values)) if values else np.nan
        rows.append(record)

    added = pd.DataFrame(rows)
    assert added.api_record_id.is_unique and len(added) == len(features)
    out = features.copy().merge(added, on='api_record_id', how='left', validate='one_to_one', sort=False)
    assert out.api_record_id.equals(features.api_record_id)
    for name in BASE_COLUMNS:
        left = features[name]
        right = out[name]
        if pd.api.types.is_numeric_dtype(left):
            assert np.allclose(left.to_numpy(dtype=float), right.to_numpy(dtype=float), rtol=0,
                               atol=0, equal_nan=True), f'baseline input changed: {name}'
        else:
            assert left.astype('string').equals(right.astype('string')), f'baseline input changed: {name}'
    assert all(name in out.columns for name in MODEL_COLUMNS)
    return out, pd.DataFrame(lineage_rows)


def summarize_support(features):
    n_features = ['hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n']
    rows = []
    for (year, distance), group in features.groupby(['year', 'distance_m'], sort=True):
        for name in n_features:
            for n, one in group.groupby(name, dropna=False, sort=True):
                rows.append(dict(year=int(year), distance_m=int(distance), feature=name,
                                 valid_n=int(n), runners=len(one), races=one.race_id.nunique(),
                                 race_days=one.race_date.nunique()))
    return pd.DataFrame(rows)


def feature_missingness(features):
    rows = []
    for feature in STYLE_FEATURES:
        overall = features[feature]
        rows.append(dict(feature=feature, scope='all', value='all', rows=len(features),
                         missing=int(overall.isna().sum()), valid=int(overall.notna().sum())))
        for year, group in features.groupby('year', sort=True):
            series = group[feature]
            rows.append(dict(feature=feature, scope='year', value=str(int(year)), rows=len(group),
                             missing=int(series.isna().sum()), valid=int(series.notna().sum())))
        for distance, group in features.groupby('distance_m', sort=True):
            series = group[feature]
            rows.append(dict(feature=feature, scope='distance_m', value=str(int(distance)), rows=len(group),
                             missing=int(series.isna().sum()), valid=int(series.notna().sum())))
    return pd.DataFrame(rows)


def build_lock(audit, f1_lock, artifacts):
    reference_paths = [
        HERE / 'CONTRACT.md', HERE / 'IMPLEMENTATION_PLAN.md', HERE / 'prepare.py',
        HERE / 'run.py', HERE / 'report.py', HERE / 'verify.py', HERE / 'README.md',
        BASE_DIR / 'CONTRACT.md', BASE_DIR / 'IMPLEMENTATION_PLAN.md',
        BASE_DIR / 'prepare.py', BASE_DIR / 'run.py', BASE_DIR / 'verify.py',
        BASE_OUT / 'prepared_lock.json', BASE_OUT / 'features.parquet',
        BASE_OUT / 'source_race_quality.parquet', BASE_OUT / 'historical_lineage.parquet',
        BASE_OUT / 'feature_contract.json', BASE_OUT / 'preflight_verification.json',
        BASE_OUT / 'r1_replay_verification.json', BASE_OUT / 'final_verification.json',
        SOURCE_SNAPSHOT_PATH, SOURCE_AUDIT_PATH, FULL_POINT_CACHE_PATH, SLOT_CACHE_PATH,
        ROOT / 'jeju/AGENTS.md', ROOT / 'jeju/docs/RESTART_PLAN_20260928.md',
        ROOT / 'jeju/review_documents/README.md', ROOT / 'jeju/research/RESEARCH_PUBLICATION_POLICY.md',
        ROOT / 'jeju/data/horse_exclusions.json',
        OUT / 'f1_replay_verification.json',
        OUT / 'f1_reproduced_runner_predictions.parquet',
        OUT / 'f1_reproduced_race_metrics.csv',
        OUT / 'f1_reproduced_six_combinations.csv',
        SOURCE_AUDIT_DIR / 'audit_source_definitions.py',
        SOURCE_AUDIT_DIR / 'support_by_distance_year.csv',
        SOURCE_AUDIT_DIR / 'point_support_by_distance.csv',
        SOURCE_AUDIT_DIR / 'api303_group_support_by_distance.csv',
        SOURCE_AUDIT_DIR / 'cross_source_interval_examples.csv',
        SOURCE_AUDIT_DIR / 'full_roster_reconciliation_by_race.csv',
        SOURCE_AUDIT_DIR / 'race_point_quality_support.csv',
        SOURCE_AUDIT_DIR / 'point_time_chronology_by_distance.csv',
    ]
    for year in YEARS:
        reference_paths.extend([
            BASE_OUT / f'F1_{year}/top3.txt', BASE_OUT / f'F1_{year}/meta.json',
            BASE_OUT / f'F1_{year}/calibration_scores.parquet',
        ])
    operating = HERE.parent / '20261009_operating_model_comparison_v1'
    reference_paths.extend([
        operating / 'README.md', operating / 'compare.py',
        operating / 'outputs/race_metrics.csv', operating / 'outputs/runner_predictions.parquet',
        operating / 'outputs/six_combinations.csv', operating / 'outputs/race_alignment.csv',
        operating / 'outputs/source_lock.json', operating / 'outputs/verification.json',
    ])
    references = {}
    for path in reference_paths:
        assert path.is_file(), f'missing scoped reference: {path}'
        relative = str(path.relative_to(ROOT))
        references[relative] = sha256(path)
    protected_paths = [
        ROOT / 'jeju/data/jeju_native_core.sqlite3',
        ROOT / 'config/prediction_model_registry.json',
        ROOT / 'jeju/models/current/metadata.json',
        ROOT / 'jeju/models/current/HY_R_FORM.pkl',
    ]
    protected = {str(path.relative_to(ROOT)): dict(sha256=sha256(path), bytes=path.stat().st_size)
                 for path in protected_paths}
    return dict(
        variant=VARIANT,
        input_features=MODEL_COLUMNS,
        f1_features=BASE_COLUMNS,
        source_audit_passed=bool(audit['passed']),
        source_cache_hashes={path.name: sha256(path) for path in (FULL_POINT_CACHE_PATH, SLOT_CACHE_PATH, SOURCE_AUDIT_PATH)},
        artifacts=artifacts,
        references=references,
        protected=protected,
        f1_protected_at_source={key: value for key, value in f1_lock['protected'].items()},
        seed=SEED,
    )


def prepare():
    prepared_paths = [
        OUT / 'features.parquet', OUT / 'style_history_lineage.parquet',
        OUT / 'support_by_year_distance.csv', OUT / 'feature_missingness.csv',
    ]
    if all(path.is_file() for path in prepared_paths):
        return finish_preflight_from_existing(prepared_paths)

    f1_lock = verify_reference_lock(BASE_OUT / 'prepared_lock.json')
    assert load_json(BASE_OUT / 'preflight_verification.json').get('passed') is True
    assert load_json(BASE_OUT / 'final_verification.json').get('passed') is True
    replay = load_json(OUT / 'f1_replay_verification.json')
    assert replay.get('passed') is True and replay.get('baseline_models_reloaded') == 3
    audit = verify_audit_receipt(load_json(SOURCE_AUDIT_PATH))
    features = pd.read_parquet(FEATURES_PATH)
    source_snapshot = pd.read_parquet(SOURCE_SNAPSHOT_PATH)
    full_cache = pd.read_parquet(FULL_POINT_CACHE_PATH)
    slot_cache = pd.read_parquet(SLOT_CACHE_PATH)
    _validate_cache_shape(full_cache, slot_cache)
    point_checks = _validate_full_point_permutations(full_cache, source_snapshot, slot_cache)
    assert int(audit.get('f1_population', {}).get('actual_same_distance_last5_slots', -1)) == 178459
    assert len(slot_cache) == 178459
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert len(features.loc[features.year.ge(2024)]) == 17412
    assert features.loc[features.year.ge(2024), 'race_id'].nunique() == 1779
    assert features.api_record_id.is_unique and not features.duplicated(['race_id', 'horse_id']).any()
    assert source_snapshot.api_record_id.is_unique
    expected_started = (source_snapshot.finish_position.between(1, 89)
                        | source_snapshot.finish_position.isin([91, 92]))
    assert expected_started.equals(source_snapshot.started.rename(expected_started.name))
    enriched, lineage = build_style_features(features, source_snapshot, slot_cache)
    assert len(enriched) == 52155 and enriched.race_id.nunique() == 5206
    assert len(MODEL_COLUMNS) == 30 and len(BASE_COLUMNS) == 24
    assert enriched.api_record_id.equals(features.api_record_id)
    support = summarize_support(enriched)
    missingness = feature_missingness(enriched)
    save_frame_new(OUT / 'features.parquet', enriched, parquet=True)
    save_frame_new(OUT / 'style_history_lineage.parquet', lineage, parquet=True)
    save_frame_new(OUT / 'support_by_year_distance.csv', support)
    save_frame_new(OUT / 'feature_missingness.csv', missingness)
    save_json_new(OUT / 'source_audit_reference.json', {
        'source_audit_path': str(SOURCE_AUDIT_PATH.relative_to(ROOT)),
        'source_audit_sha256': sha256(SOURCE_AUDIT_PATH),
        'full_point_cache_sha256': sha256(FULL_POINT_CACHE_PATH),
        'slot_cache_sha256': sha256(SLOT_CACHE_PATH),
        'full_point_race_point_groups_validated': point_checks,
        'actual_slot_rows': len(slot_cache),
        'feature_mapping': STYLE_MAPPING,
        'api4_order_status_allowlist': audit['source_status_policy']['api4_order_allowed'],
        'api303_group_status_allowlist': audit['source_status_policy']['api303_group_status_allowed'],
        'full_roster_reconciliation': audit['f1_population']['full_roster_reconciliation'],
        'source_cache_rows': audit['cache_rows'],
        'api4_permutation_races_by_point': audit['source_slot_quality']['api4_order_permutation_valid_races_by_point'],
        'race_point_eligible_races_by_point': audit['source_slot_quality']['race_point_eligible_races_by_point'],
        'chronology_source_path': str((SOURCE_AUDIT_DIR / 'point_time_chronology_by_distance.csv').relative_to(ROOT)),
        'chronology_source_sha256': sha256(SOURCE_AUDIT_DIR / 'point_time_chronology_by_distance.csv'),
    })
    prepared_artifacts = {
        name: sha256(OUT / name) for name in (
            'features.parquet', 'style_history_lineage.parquet',
            'support_by_year_distance.csv', 'feature_missingness.csv',
            'source_audit_reference.json',
        )
    }
    lock = build_lock(audit, f1_lock, prepared_artifacts)
    save_json_new(OUT / 'prepared_lock.json', lock)
    preflight = dict(
        passed=True,
        variant=VARIANT,
        baseline_features=len(BASE_COLUMNS),
        added_features=len(STYLE_FEATURES),
        candidate_features=len(MODEL_COLUMNS),
        source_rows=int(len(source_snapshot)),
        source_candidate_races=int(source_snapshot.race_id.nunique()),
        target_rows=int(len(enriched)),
        target_races=int(enriched.race_id.nunique()),
        evaluation_rows=int(enriched.year.ge(2024).sum()),
        evaluation_races=int(enriched.loc[enriched.year.ge(2024), 'race_id'].nunique()),
        actual_same_distance_slot_rows=int(len(lineage)),
        feature_mapping=STYLE_MAPPING,
        full_point_race_point_groups_validated=int(point_checks),
        source_audit_sha256=sha256(SOURCE_AUDIT_PATH),
        f1_replay_passed=True,
        candidate_fit_models=0,
        candidate_temperature_optimizations=0,
        candidate_outcome_metrics_computed=False,
        database_changed=False,
        production_changed=False,
        code_sha256={name: sha256(HERE / name) for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')},
    )
    save_json_new(OUT / 'preflight_verification.json', preflight)
    print(json.dumps(preflight, ensure_ascii=False, indent=2), flush=True)


def finish_preflight_from_existing(prepared_paths):
    """Lock already-built prepared artifacts without recalculating or overwriting them."""
    prior_lock_path = OUT / 'prepared_lock.json'
    prior_preflight_path = OUT / 'preflight_verification.json'
    prior_lock_sha = sha256(prior_lock_path) if prior_lock_path.is_file() else None
    prior_preflight = load_json(prior_preflight_path) if prior_preflight_path.is_file() else {}
    f1_lock = verify_reference_lock(BASE_OUT / 'prepared_lock.json')
    assert load_json(BASE_OUT / 'preflight_verification.json').get('passed') is True
    assert load_json(BASE_OUT / 'final_verification.json').get('passed') is True
    replay = load_json(OUT / 'f1_replay_verification.json')
    assert replay.get('passed') is True and replay.get('baseline_models_reloaded') == 3
    audit = verify_audit_receipt(load_json(SOURCE_AUDIT_PATH))

    features = pd.read_parquet(OUT / 'features.parquet')
    baseline_features = pd.read_parquet(FEATURES_PATH)
    lineage = pd.read_parquet(OUT / 'style_history_lineage.parquet')
    support = pd.read_csv(OUT / 'support_by_year_distance.csv')
    missingness = pd.read_csv(OUT / 'feature_missingness.csv')
    assert len(features) == len(baseline_features) == 52155
    assert features.race_id.nunique() == baseline_features.race_id.nunique() == 5206
    assert features.api_record_id.equals(baseline_features.api_record_id)
    assert features.api_record_id.is_unique and features.race_id.notna().all()
    assert features.year.ge(2024).sum() == 17412
    assert features.loc[features.year.ge(2024), 'race_id'].nunique() == 1779
    pd.testing.assert_frame_equal(features[BASE_COLUMNS], baseline_features[BASE_COLUMNS], check_exact=True)
    assert len(BASE_COLUMNS) == 24 and len(MODEL_COLUMNS) == 30
    assert all(name in features.columns for name in MODEL_COLUMNS)
    assert len(lineage) == 178459
    assert not lineage.duplicated(['target_api_record_id', 'slot_position']).any()
    assert lineage.slot_position.between(1, 5).all()
    assert len(support) and len(missingness)
    for path in prepared_paths:
        assert path.is_file()

    source_reference = {
        'source_audit_path': str(SOURCE_AUDIT_PATH.relative_to(ROOT)),
        'source_audit_sha256': sha256(SOURCE_AUDIT_PATH),
        'full_point_cache_sha256': sha256(FULL_POINT_CACHE_PATH),
        'slot_cache_sha256': sha256(SLOT_CACHE_PATH),
        'actual_slot_rows': int(audit['cache_rows']['actual_slot_eligibility']),
        'feature_mapping': STYLE_MAPPING,
        'api4_order_status_allowlist': audit['source_status_policy']['api4_order_allowed'],
        'api303_group_status_allowlist': audit['source_status_policy']['api303_group_status_allowed'],
        'full_roster_reconciliation': audit['f1_population']['full_roster_reconciliation'],
        'source_cache_rows': audit['cache_rows'],
        'api4_permutation_races_by_point': audit['source_slot_quality']['api4_order_permutation_valid_races_by_point'],
        'race_point_eligible_races_by_point': audit['source_slot_quality']['race_point_eligible_races_by_point'],
        'chronology_source_path': str((SOURCE_AUDIT_DIR / 'point_time_chronology_by_distance.csv').relative_to(ROOT)),
        'chronology_source_sha256': sha256(SOURCE_AUDIT_DIR / 'point_time_chronology_by_distance.csv'),
        'prepared_artifacts_reused_without_recalculation': True,
    }
    source_reference_path = OUT / 'source_audit_reference.json'
    if source_reference_path.exists():
        assert load_json(source_reference_path) == source_reference
    else:
        save_json_new(source_reference_path, source_reference)
    artifacts = {
        name: sha256(OUT / name) for name in (
            'features.parquet', 'style_history_lineage.parquet',
            'support_by_year_distance.csv', 'feature_missingness.csv',
            'source_audit_reference.json',
        )
    }
    lock = build_lock(audit, f1_lock, artifacts)
    lock_path = OUT / 'prepared_lock.json'
    if lock_path.exists():
        if load_json(lock_path) != lock:
            save_json_replace(lock_path, lock)
    else:
        save_json_new(lock_path, lock)
    result = dict(
        passed=True,
        variant=VARIANT,
        baseline_features=len(BASE_COLUMNS),
        added_features=len(STYLE_FEATURES),
        candidate_features=len(MODEL_COLUMNS),
        source_candidate_races=6269,
        source_started_rows=62248,
        target_rows=len(features),
        target_races=int(features.race_id.nunique()),
        evaluation_rows=int(features.year.ge(2024).sum()),
        evaluation_races=int(features.loc[features.year.ge(2024), 'race_id'].nunique()),
        actual_same_distance_slot_rows=len(lineage),
        feature_mapping=STYLE_MAPPING,
        source_support_by_point=audit['source_slot_quality']['race_point_eligible_races_by_point'],
        final_eligible_slot_counts={
            'S1F': 177688, 'S1F_to_4C': 177450, '4C_to_G1F': 177498,
        },
        f1_replay_passed=True,
        prepared_artifacts_reused_without_recalculation=True,
        candidate_fit_models=0,
        candidate_temperature_optimizations=0,
        candidate_outcome_metrics_computed=False,
        database_changed=False,
        production_changed=False,
        prepared_lock_sha256=sha256(OUT / 'prepared_lock.json'),
        artifact_sha256=artifacts,
        code_sha256={name: sha256(HERE / name) for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')},
    )
    result['metadata_refresh'] = prior_preflight.get('metadata_refresh') or dict(
        previous_prepared_lock_sha256=prior_lock_sha,
        previous_preflight_sha256=(sha256(prior_preflight_path) if prior_preflight_path.is_file() else None),
        previous_code_sha256=prior_preflight.get('code_sha256'),
        reason=(
            'Verifier-only correction: lineage already stores API4 permutation and API303 group gate '
            'separately, so race_point_eligible is derived as their conjunction. Prepared feature, '
            'lineage, support, and missingness artifacts were reused unchanged.'
        ),
        prepared_artifacts_changed=False,
        feature_recalculation_performed=False,
    )
    preflight_path = OUT / 'preflight_verification.json'
    if preflight_path.exists():
        if load_json(preflight_path) != result:
            save_json_replace(preflight_path, result)
    else:
        save_json_new(preflight_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


if __name__ == '__main__':
    prepare()
