"""No-fit verifier for locked inputs, prepared features, saved models, and report."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd

import prepare as e
import report as reporting
import run as fit_runner


def close(left, right, atol=1e-12):
    return np.allclose(np.asarray(left, dtype=float), np.asarray(right, dtype=float),
                       rtol=0, atol=atol, equal_nan=True)


def assert_numeric_frame(left, right, keys, numeric, atol=1e-12):
    a = left.sort_values(keys, kind='stable').reset_index(drop=True)
    b = right.sort_values(keys, kind='stable').reset_index(drop=True)
    assert len(a) == len(b)
    for key in keys:
        assert a[key].astype('string').fillna('<NA>').equals(b[key].astype('string').fillna('<NA>')), key
    for column in numeric:
        assert close(a[column], b[column], atol=atol), column


def verify_prepared():
    lock = e.load_json(e.OUT / 'prepared_lock.json')
    fit_runner.verify_locked_inputs(lock)
    preflight = e.load_json(e.OUT / 'preflight_verification.json')
    replay = e.load_json(e.OUT / 'f1_replay_verification.json')
    assert preflight.get('passed') is True and preflight.get('candidate_fit_models') == 0
    assert preflight.get('candidate_outcome_metrics_computed') is False
    assert replay.get('passed') is True and replay.get('baseline_models_reloaded') == 3
    features = pd.read_parquet(e.OUT / 'features.parquet')
    original = pd.read_parquet(e.FEATURES_PATH)
    lineage = pd.read_parquet(e.OUT / 'style_history_lineage.parquet')
    assert len(features) == len(original) == 52155
    assert features.api_record_id.equals(original.api_record_id)
    assert features.race_id.nunique() == original.race_id.nunique() == 5206
    assert len(features.loc[features.year.ge(2024)]) == 17412
    assert features.loc[features.year.ge(2024), 'race_id'].nunique() == 1779
    assert len(e.BASE_COLUMNS) == 24 and e.MODEL_COLUMNS == e.BASE_COLUMNS + e.STYLE_FEATURES
    assert len(e.MODEL_COLUMNS) == 30
    pd.testing.assert_frame_equal(features[e.BASE_COLUMNS], original[e.BASE_COLUMNS], check_exact=True)
    assert len(lineage) == 178459
    assert lineage.source_api_record_id.notna().all()
    assert lineage.source_horse_id.astype(str).equals(lineage.target_horse_id.astype(str))
    assert lineage.source_distance_m.astype('int64').equals(lineage.target_distance_m.astype('int64'))
    assert lineage.source_race_date.astype(str).le(lineage.target_cutoff.astype(str)).all()
    assert lineage.slot_position.between(1, 5).all()

    features_by_id = features.set_index('api_record_id')
    for target_id, group in lineage.groupby('target_api_record_id', sort=False):
        row = features_by_id.loc[target_id]
        ids = e.normalize_ids(row.last5_same_source_ids)
        ordered = group.sort_values('slot_position', kind='stable')
        assert ordered.source_api_record_id.astype('int64').tolist() == ids
        assert ordered.slot_position.astype(int).tolist() == list(range(1, len(ids) + 1))
        for prefix in ('s1f', 'c4', 'g1f'):
            valid_time = ordered.source_snapshot_valid_time.map(e.as_bool)
            permutation = ordered[f'{prefix}_full_point_permutation_valid'].map(e.as_bool)
            group_gate = ordered[f'{prefix}_group_status_gate'].map(e.as_bool)
            allowed_group = ordered[f'{prefix}_api303_group_status'].map(
                lambda value: not pd.isna(value) and str(value) in ('api_group_unreviewed', 'api_group_unavailable')
            )
            assert group_gate.equals(allowed_group)
            # The lineage stores the two independent source gates. Their
            # conjunction is the cache's race_point_eligible value; derive it
            # here rather than requiring a duplicated lineage column.
            race_point = permutation & group_gate
            eligible = ordered[f'{prefix}_final_point_eligible'].map(e.as_bool)
            expected_eligible = valid_time & race_point & ordered[f'{prefix}_r'].notna()
            assert eligible.equals(expected_eligible)
            for item in ordered.itertuples(index=False):
                n = int(item.full_started_n)
                rank = getattr(item, f'{prefix}_r')
                api4_permutation = bool(getattr(item, f'{prefix}_full_point_permutation_valid'))
                api303_allowed = bool(getattr(item, f'{prefix}_group_status_gate'))
                if api4_permutation and api303_allowed:
                    assert n >= 2 and bool(getattr(item, f'{prefix}_individual_order_valid'))
                    value = getattr(item, f'{prefix}_order')
                    assert str(getattr(item, f'{prefix}_order_status')) in (
                        'api_positive_unreviewed', 'website_corrected'
                    )
                    assert e.is_finite(value) and float(value).is_integer()
                    assert close([rank], [(int(value) - 1) / (n - 1)])
                else:
                    assert not e.is_finite(rank)

        expected_s1f_c4 = (
            ordered.s1f_final_point_eligible.map(e.as_bool)
            & ordered.c4_final_point_eligible.map(e.as_bool)
        )
        expected_c4_g1f = (
            ordered.c4_final_point_eligible.map(e.as_bool)
            & ordered.g1f_final_point_eligible.map(e.as_bool)
        )
        assert ordered.hist_s1f_to_c4_forward_mean5_eligible.map(e.as_bool).equals(expected_s1f_c4)
        assert ordered.hist_c4_to_g1f_forward_mean5_eligible.map(e.as_bool).equals(expected_c4_g1f)
        for row_slot in ordered.itertuples(index=False):
            s1f_c4_value = (float(row_slot.s1f_r) - float(row_slot.c4_r)
                            if e.is_finite(row_slot.s1f_r) and e.is_finite(row_slot.c4_r) else np.nan)
            c4_g1f_value = (float(row_slot.c4_r) - float(row_slot.g1f_r)
                            if e.is_finite(row_slot.c4_r) and e.is_finite(row_slot.g1f_r) else np.nan)
            for feature, eligibility, expected_value in [
                ('hist_s1f_relpos_mean5', 'hist_s1f_relpos_mean5_eligible', row_slot.s1f_r),
                ('hist_s1f_to_c4_forward_mean5', 'hist_s1f_to_c4_forward_mean5_eligible',
                 s1f_c4_value),
                ('hist_c4_to_g1f_forward_mean5', 'hist_c4_to_g1f_forward_mean5_eligible',
                 c4_g1f_value),
            ]:
                contribution = getattr(row_slot, f'{feature}_value')
                if bool(getattr(row_slot, eligibility)):
                    assert close([contribution], [expected_value])
                else:
                    assert not e.is_finite(contribution)
            assert bool(row_slot.hist_s1f_relpos_n_eligible) == bool(row_slot.s1f_final_point_eligible)
            assert bool(row_slot.hist_s1f_to_c4_pair_n_eligible) == bool(row_slot.hist_s1f_to_c4_forward_mean5_eligible)
            assert bool(row_slot.hist_c4_to_g1f_pair_n_eligible) == bool(row_slot.hist_c4_to_g1f_forward_mean5_eligible)

    aggregate_specs = {
        'hist_s1f_relpos_mean5': ('hist_s1f_relpos_mean5_eligible', 'hist_s1f_relpos_mean5_value'),
        'hist_s1f_relpos_n': ('hist_s1f_relpos_n_eligible', None),
        'hist_s1f_to_c4_forward_mean5': ('hist_s1f_to_c4_forward_mean5_eligible', 'hist_s1f_to_c4_forward_mean5_value'),
        'hist_s1f_to_c4_pair_n': ('hist_s1f_to_c4_pair_n_eligible', None),
        'hist_c4_to_g1f_forward_mean5': ('hist_c4_to_g1f_forward_mean5_eligible', 'hist_c4_to_g1f_forward_mean5_value'),
        'hist_c4_to_g1f_pair_n': ('hist_c4_to_g1f_pair_n_eligible', None),
    }
    lineage_groups = {int(key): group for key, group in lineage.groupby('target_api_record_id', sort=False)}
    for row in features.itertuples(index=False):
        slots = lineage_groups.get(int(row.api_record_id), lineage.iloc[:0])
        for feature, (eligible_col, value_col) in aggregate_specs.items():
            eligible = slots[eligible_col].map(e.as_bool) if len(slots) else pd.Series(dtype=bool)
            count = int(eligible.sum())
            if feature.endswith('_n') or feature.endswith('_pair_n'):
                assert int(getattr(row, feature)) == count
            else:
                values = pd.to_numeric(slots.loc[eligible, value_col], errors='coerce').to_numpy(float)
                expected = float(np.mean(values)) if len(values) else np.nan
                assert close([getattr(row, feature)], [expected])
                assert (count > 0) == e.is_finite(getattr(row, feature))
    return dict(rows=len(features), races=int(features.race_id.nunique()),
                history_slot_rows=len(lineage), baseline_features=len(e.BASE_COLUMNS),
                candidate_features=len(e.MODEL_COLUMNS), reference_f1_replay=True)


def _compare_report_outputs(features, candidate_scores, baseline_scores):
    candidate_races, candidate_runners, candidate_tickets = [], [], []
    baseline_races, baseline_runners, baseline_tickets = [], [], []
    for year in e.YEARS:
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        candidate_score = candidate_scores.loc[candidate_scores.year.eq(year)].copy()
        assert candidate_score.api_record_id.astype('int64').tolist() == test.api_record_id.astype('int64').tolist()
        c_meta = e.load_json(e.OUT / f'{e.VARIANT}_{year}' / 'meta.json')
        cr, cu, ct = reporting.OLD.evaluate(test, candidate_score.score.to_numpy(float),
                                             float(c_meta['tau']), e.VARIANT)
        candidate_races.append(cr)
        candidate_runners.append(cu)
        candidate_tickets.append(ct)

        f_rows = baseline_scores.loc[baseline_scores.year.eq(year)].copy()
        assert f_rows.api_record_id.astype('int64').tolist() == test.api_record_id.astype('int64').tolist()
        f_meta = e.load_json(e.BASE_OUT / f'F1_{year}' / 'meta.json')
        fr, fu, ft = reporting.OLD.evaluate(test, f_rows.score.to_numpy(float),
                                             float(f_meta['tau']), 'F1')
        baseline_races.append(fr)
        baseline_runners.append(fu)
        baseline_tickets.append(ft)
    c_races = reporting.add_pick_hit(pd.concat(candidate_races, ignore_index=True),
                                     pd.concat(candidate_runners, ignore_index=True),
                                     pd.concat(candidate_tickets, ignore_index=True))
    f_races = reporting.add_pick_hit(pd.concat(baseline_races, ignore_index=True),
                                     pd.concat(baseline_runners, ignore_index=True),
                                     pd.concat(baseline_tickets, ignore_index=True))
    c_runners = pd.concat(candidate_runners, ignore_index=True)
    f_runners = pd.concat(baseline_runners, ignore_index=True)
    c_tickets = pd.concat(candidate_tickets, ignore_index=True)
    f_tickets = pd.concat(baseline_tickets, ignore_index=True)
    report_dir = reporting.REPORT_DIR
    saved_races = pd.read_parquet(report_dir / 'race_metrics.parquet')
    saved_runners = pd.read_parquet(report_dir / 'runner_predictions.parquet')
    saved_tickets = pd.read_csv(report_dir / 'canonical_six_combinations.csv')
    for variant, calculated in [('F1', f_races), (e.VARIANT, c_races)]:
        selected = saved_races.loc[saved_races.variant.eq(variant)]
        assert_numeric_frame(selected, calculated, ['race_id'],
                             ['log_loss', 'brier', 'top5_capture', 'top5_all3', 'six_combo_hit',
                              'six_combo_mass', 'pick_hit'])
    for variant, calculated in [('F1', f_runners), (e.VARIANT, c_runners)]:
        selected = saved_runners.loc[saved_runners.variant.eq(variant)]
        assert_numeric_frame(selected, calculated, ['api_record_id'],
                             ['score', 'p_top3', 'log_loss', 'brier', 'y'])
    for variant, calculated in [('F1', f_tickets), (e.VARIANT, c_tickets)]:
        selected = saved_tickets.loc[saved_tickets.variant.eq(variant)]
        assert_numeric_frame(selected, calculated, ['race_id', 'selection_rank'], ['probability', 'hit'])
        a = selected.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
        b = calculated.sort_values(['race_id', 'selection_rank'], kind='stable').reset_index(drop=True)
        assert a[['numbers']].astype(str).equals(b[['numbers']].astype(str))

    paired, gate = reporting.comparison_tables(c_races, f_races)
    saved_paired = pd.read_csv(report_dir / 'paired_date_bootstrap.csv')
    assert_numeric_frame(saved_paired, paired, ['group', 'value', 'metric'],
                         ['delta_candidate_minus_f1', 'ci95_low', 'ci95_high', 'races',
                          'race_days', 'resamples', 'seed'])
    assert reporting.e.load_json(report_dir / 'report_receipt.json')['primary_gate'] == gate
    support = reporting.support_tables(features, c_runners)
    saved_support = pd.read_csv(report_dir / 'history_support.csv')
    assert_numeric_frame(saved_support, support, ['concept', 'group', 'value', 'valid_n'],
                         ['runners', 'races', 'race_days'])
    conditional = reporting.conditional_runner_losses(c_runners, f_runners, features)
    saved_conditional = pd.read_csv(report_dir / 'conditional_runner_losses.csv')
    assert_numeric_frame(saved_conditional, conditional, ['group', 'value', 'metric'],
                         ['runner_rows', 'races', 'race_days', 'delta_candidate_minus_f1',
                          'ci95_low', 'ci95_high', 'resamples', 'seed'])
    return dict(report_race_metrics=True, runner_metrics=True, canonical_six_sets=True,
                date_paired_primary_secondary=True, conditional_runner_losses=True,
                primary_gate=gate['primary_gate_passed'])


def verify_saved_fit_and_report():
    approval = e.load_json(e.OUT / 'root_fit_approval.json')
    completion = e.load_json(e.OUT / 'candidate_training_completion.json')
    lock_path = e.OUT / 'prepared_lock.json'
    lock = e.load_json(lock_path)
    fit_runner.verify_locked_inputs(lock)
    assert approval.get('approved') is True and approval.get('approved_by') == 'root'
    assert approval.get('code_review_passed') is True
    assert completion.get('passed') is True
    assert completion.get('candidate_models') == 3
    assert completion.get('lightgbm_train_calls') == 6
    assert completion.get('temperature_optimizations') == 3
    assert completion.get('candidate_score_rows') == 17412
    assert completion.get('candidate_outcome_metrics_computed') is False
    assert completion.get('prepared_lock_sha256') == e.sha256(lock_path)
    expected_code_hashes = {
        name: e.sha256(e.HERE / name) for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')
    }
    assert completion.get('code_sha256') == expected_code_hashes
    features = pd.read_parquet(e.OUT / 'features.parquet')
    stage = pd.read_parquet(e.OUT / 'candidate_scores_fit_stage.parquet')
    baseline = pd.read_parquet(e.OUT / 'f1_reproduced_runner_predictions.parquet')
    all_scores = []
    model_hashes = {}
    model_records = {int(row['year']): row for row in completion.get('model_years', [])}
    assert set(model_records) == set(e.YEARS)
    for year in e.YEARS:
        folder = e.OUT / f'{e.VARIANT}_{year}'
        meta = e.load_json(folder / 'meta.json')
        model_path = folder / 'top3.txt'
        assert e.sha256(model_path) == meta['model_sha256']
        assert meta['features'] == e.MODEL_COLUMNS
        assert meta['feature_count'] == 30
        assert meta['variant'] == e.VARIANT and meta['evaluation_year'] == year
        assert meta['parameters'] == reporting.OLD.PARAMS
        assert meta['seed'] == reporting.OLD.SEED
        assert meta['lightgbm_train_calls'] == 2 and meta['temperature_optimizations'] == 1
        assert 0.35 <= float(meta['tau']) <= 4.0
        assert model_records[year]['model_sha256'] == meta['model_sha256']
        assert model_records[year]['tau'] == meta['tau']
        assert e.sha256(folder / 'calibration_scores.parquet') == meta['calibration_scores_sha256']
        assert e.sha256(folder / 'evaluation_scores.parquet') == meta['evaluation_scores_sha256']
        model = lgb.Booster(model_file=str(model_path))
        assert model.current_iteration() == int(meta['trees'])
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        x = fit_runner.transform(test, e.MODEL_COLUMNS, meta['vocabulary'])
        scores = model.predict(x, raw_score=True, num_threads=4)
        calibration = features.loc[features.year.eq(year - 1)].reset_index(drop=True)
        calibration_x = fit_runner.transform(calibration, e.MODEL_COLUMNS, meta['vocabulary'])
        calibration_scores = model.predict(calibration_x, raw_score=True, num_threads=4)
        saved_calibration = pd.read_parquet(folder / 'calibration_scores.parquet')
        assert saved_calibration.api_record_id.astype('int64').tolist() == calibration.api_record_id.astype('int64').tolist()
        assert close(calibration_scores, saved_calibration.score)
        saved = pd.read_parquet(folder / 'evaluation_scores.parquet')
        assert saved.api_record_id.astype('int64').tolist() == test.api_record_id.astype('int64').tolist()
        assert close(scores, saved.score)
        stage_year = stage.loc[stage.year.eq(year)]
        assert stage_year.api_record_id.astype('int64').tolist() == test.api_record_id.astype('int64').tolist()
        assert close(scores, stage_year.score)
        all_scores.append(stage_year)
        model_hashes[str(year)] = e.sha256(model_path)
    candidate_scores = pd.concat(all_scores, ignore_index=True)
    assert len(candidate_scores) == 17412 and candidate_scores.api_record_id.is_unique
    assert baseline.api_record_id.astype('int64').tolist() == candidate_scores.api_record_id.astype('int64').tolist()
    report_receipt_path = reporting.REPORT_DIR / 'report_receipt.json'
    report_receipt = e.load_json(report_receipt_path)
    assert report_receipt.get('passed') is True
    assert report_receipt.get('candidate_training_completion_sha256') == e.sha256(e.OUT / 'candidate_training_completion.json')
    assert report_receipt.get('prepared_lock_sha256') == e.sha256(lock_path)
    for name, expected in report_receipt['report_artifacts'].items():
        path = reporting.REPORT_DIR / name
        assert path.is_file() and e.sha256(path) == expected
    report_checks = _compare_report_outputs(features, candidate_scores, baseline)
    return dict(models_reloaded=3, refit_models=0, retrained_models=0,
                candidate_model_sha256=model_hashes,
                calibration_raw_scores_reloaded_and_matched=True,
                tau_reoptimized=0,
                evaluation_score_rows=int(len(candidate_scores)), report_checks=report_checks,
                probability_sums_rechecked_by_f1_evaluator=True,
                no_refit_finalizer=True)


def verify_all():
    prepared = verify_prepared()
    fitted = verify_saved_fit_and_report()
    result = dict(
        passed=True,
        candidate=e.VARIANT,
        prepared=prepared,
        fitted=fitted,
        candidate_outcome_metrics_verified=True,
        candidate_models_fit=3,
        lightgbm_train_calls=6,
        temperature_optimizations=3,
        finalizer_fit_calls=0,
        primary_gate_is_descriptive_not_promotion=True,
        operating_database_changed=False,
        production_or_registry_changed=False,
        final_protected_sha256={key: value['sha256'] for key, value in lock_protection().items()},
        code_sha256={name: e.sha256(e.HERE / name)
                     for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')},
    )
    e.save_json_new(e.OUT / 'final_verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


def lock_protection():
    lock = e.load_json(e.OUT / 'prepared_lock.json')
    fit_runner.verify_locked_inputs(lock)
    return lock['protected']


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'final':
        raise SystemExit('usage: verify.py final (reloads saved outputs; never fits or recalibrates)')
    verify_all()
