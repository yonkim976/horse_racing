"""Fit only the root-approved F1_STYLE6 candidate and save scores before reports."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd

import prepare as e

HERE = e.HERE
ROOT = e.ROOT
OUT = e.OUT
OLD = e.F1.base
YEARS = e.YEARS
MODEL_CATS = list(OLD.CATS) + ['previous_result_status']


def sha256(path):
    return e.sha256(path)


def save_json_new(path, payload):
    e.save_json_new(path, payload)


def write_frame_new(path, frame, parquet=False):
    e.save_frame_new(path, frame, parquet=parquet)


def verify_locked_inputs(lock):
    for relative, expected in lock['references'].items():
        path = ROOT / relative
        assert path.is_file() and sha256(path) == expected, f'locked reference changed: {relative}'
    for relative, info in lock['protected'].items():
        path = ROOT / relative
        assert path.is_file() and sha256(path) == info['sha256'], f'protected source changed: {relative}'
        assert path.stat().st_size == int(info['bytes']), f'protected bytes changed: {relative}'
    for name, expected in lock['artifacts'].items():
        path = OUT / name
        assert path.is_file() and sha256(path) == expected, f'prepared artifact changed: {name}'
    for name, expected in lock['source_cache_hashes'].items():
        if name == e.SOURCE_AUDIT_PATH.name:
            path = e.SOURCE_AUDIT_PATH
        elif name == e.FULL_POINT_CACHE_PATH.name:
            path = e.FULL_POINT_CACHE_PATH
        elif name == e.SLOT_CACHE_PATH.name:
            path = e.SLOT_CACHE_PATH
        else:
            raise AssertionError(f'unknown source cache artifact: {name}')
        assert sha256(path) == expected, f'audited source cache changed: {name}'


def require_fit_authorization(lock):
    preflight_path = OUT / 'preflight_verification.json'
    replay_path = OUT / 'f1_replay_verification.json'
    approval_path = OUT / 'root_fit_approval.json'
    assert preflight_path.is_file() and replay_path.is_file() and approval_path.is_file(), (
        'fit requires passing input preflight, exact F1 replay, and explicit root approval'
    )
    preflight = json.loads(preflight_path.read_text(encoding='utf-8'))
    replay = json.loads(replay_path.read_text(encoding='utf-8'))
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    assert preflight.get('passed') is True
    assert preflight.get('candidate_fit_models') == 0
    assert preflight.get('candidate_outcome_metrics_computed') is False
    assert replay.get('passed') is True and replay.get('baseline_models_reloaded') == 3
    assert replay.get('runner_rows_reproduced') == 17412
    assert replay.get('distinct_races_reproduced') == 1779
    assert replay.get('canonical_six_combination_rows_reproduced') == 10674
    assert approval.get('approved') is True
    assert approval.get('candidate') == e.VARIANT
    assert approval.get('candidate_models') == 3
    assert approval.get('lightgbm_train_calls') == 6
    assert approval.get('temperature_optimizations') == 3
    assert approval.get('contract_sha256') == sha256(HERE / 'CONTRACT.md')
    assert approval.get('prepared_lock_sha256') == sha256(OUT / 'prepared_lock.json')
    assert approval.get('preflight_sha256') == sha256(preflight_path)
    assert approval.get('approved_by') == 'root'
    assert approval.get('code_review_passed') is True
    verify_locked_inputs(lock)
    return approval


def transform(data, columns, vocabulary):
    x = data[columns].copy()
    for column in MODEL_CATS:
        if column in columns:
            x[column] = pd.Categorical(x[column].astype('string'), categories=vocabulary[column])
    return x


def fit_one_year(features, year):
    columns = e.MODEL_COLUMNS
    x = features[columns].copy()
    train = features.year.between(2017, year - 3)
    valid = features.year.eq(year - 2)
    calibration = features.year.eq(year - 1)
    test = features.year.eq(year)
    assert all(mask.any() for mask in (train, valid, calibration, test))
    vocabulary = {}
    for column in MODEL_CATS:
        if column in columns:
            vocabulary[column] = sorted(features.loc[train, column].dropna().astype(str).unique().tolist())
            x[column] = pd.Categorical(x[column].astype('string'), categories=vocabulary[column])
    target = features.finish_position.le(3).astype(int)
    weight = 1 / features.field_n

    def dataset(mask):
        return lgb.Dataset(x.loc[mask], label=target.loc[mask], weight=weight.loc[mask],
                           free_raw_data=False)

    initial = lgb.train(
        OLD.PARAMS, dataset(train), num_boost_round=200, valid_sets=[dataset(valid)],
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )
    model = lgb.train(OLD.PARAMS, dataset(train | valid),
                      num_boost_round=int(initial.best_iteration))

    folder = OUT / f'{e.VARIANT}_{year}'
    folder.mkdir(exist_ok=False)
    model_path = folder / 'top3.txt'
    model.save_model(str(model_path))

    calibration_data = features.loc[calibration].reset_index(drop=True)
    evaluation_data = features.loc[test].reset_index(drop=True)
    calibration_scores = model.predict(x.loc[calibration], raw_score=True, num_threads=4)
    evaluation_scores = model.predict(x.loc[test], raw_score=True, num_threads=4)
    tau = OLD.temperature(calibration_data, calibration_scores)
    assert 0.35 <= float(tau) <= 4.0

    write_frame_new(folder / 'calibration_scores.parquet', pd.DataFrame({
        'api_record_id': calibration_data.api_record_id.to_numpy(),
        'score': calibration_scores,
    }), parquet=True)
    write_frame_new(folder / 'evaluation_scores.parquet', pd.DataFrame({
        'api_record_id': evaluation_data.api_record_id.to_numpy(),
        'score': evaluation_scores,
    }), parquet=True)
    meta = dict(
        variant=e.VARIANT,
        evaluation_year=int(year),
        features=columns,
        feature_count=len(columns),
        vocabulary=vocabulary,
        trees=int(initial.best_iteration),
        tau=float(tau),
        seed=int(OLD.SEED),
        parameters=OLD.PARAMS,
        lightgbm_train_calls=2,
        temperature_optimizations=1,
        training_min=str(features.loc[train, 'race_date'].min()),
        initial_training_max=str(features.loc[train, 'race_date'].max()),
        early_stopping_min=str(features.loc[valid, 'race_date'].min()),
        refit_max=str(features.loc[valid, 'race_date'].max()),
        calibration_min=str(features.loc[calibration, 'race_date'].min()),
        calibration_max=str(features.loc[calibration, 'race_date'].max()),
        evaluation_min=str(features.loc[test, 'race_date'].min()),
        evaluation_max=str(features.loc[test, 'race_date'].max()),
        train_rows=int((train | valid).sum()),
        train_races=int(features.loc[train | valid, 'race_id'].nunique()),
        calibration_rows=int(calibration.sum()),
        calibration_races=int(features.loc[calibration, 'race_id'].nunique()),
        evaluation_rows=int(test.sum()),
        evaluation_races=int(features.loc[test, 'race_id'].nunique()),
        model_sha256=sha256(model_path),
        calibration_scores_sha256=sha256(folder / 'calibration_scores.parquet'),
        evaluation_scores_sha256=sha256(folder / 'evaluation_scores.parquet'),
        gain=dict(zip(columns, map(float, model.feature_importance(importance_type='gain')))),
        outcome_metrics_computed=False,
    )
    save_json_new(folder / 'meta.json', meta)
    return dict(
        year=int(year), model_sha256=meta['model_sha256'], trees=meta['trees'],
        tau=meta['tau'], calibration_rows=meta['calibration_rows'],
        evaluation_rows=meta['evaluation_rows'],
    )


def fit():
    lock = json.loads((OUT / 'prepared_lock.json').read_text(encoding='utf-8'))
    approval = require_fit_authorization(lock)
    assert len(e.MODEL_COLUMNS) == 30 and len(e.STYLE_FEATURES) == 6
    assert not any((OUT / f'{e.VARIANT}_{year}').exists() for year in YEARS), (
        'candidate artifacts already exist; this runner refuses a refit or overwrite'
    )
    features_path = OUT / 'features.parquet'
    features = pd.read_parquet(features_path)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert set(e.MODEL_COLUMNS).issubset(features.columns)

    fitted = [fit_one_year(features, year) for year in YEARS]
    score_frames = []
    for year in YEARS:
        evaluation = pd.read_parquet(OUT / f'{e.VARIANT}_{year}/evaluation_scores.parquet')
        evaluation['year'] = year
        score_frames.append(evaluation)
    stage_scores = pd.concat(score_frames, ignore_index=True)
    assert len(stage_scores) == 17412 and stage_scores.api_record_id.is_unique
    write_frame_new(OUT / 'candidate_scores_fit_stage.parquet', stage_scores, parquet=True)

    verify_locked_inputs(lock)
    completion = dict(
        passed=True,
        fit_approval_sha256=sha256(OUT / 'root_fit_approval.json'),
        candidate=e.VARIANT,
        candidate_models=len(fitted),
        lightgbm_train_calls=sum(2 for _ in fitted),
        temperature_optimizations=len(fitted),
        model_years=fitted,
        candidate_score_rows=int(len(stage_scores)),
        candidate_outcome_metrics_computed=False,
        report_phase_required=True,
        no_refit_after_this_point=True,
        production_changed=False,
        database_changed=False,
        prepared_lock_sha256=sha256(OUT / 'prepared_lock.json'),
        code_sha256={name: sha256(HERE / name) for name in ('prepare.py', 'run.py', 'report.py', 'verify.py')},
    )
    save_json_new(OUT / 'candidate_training_completion.json', completion)
    print(json.dumps(completion, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'fit':
        raise SystemExit('usage: run.py fit (requires root_fit_approval.json)')
    fit()
