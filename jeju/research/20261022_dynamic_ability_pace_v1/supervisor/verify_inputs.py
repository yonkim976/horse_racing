"""Independent reconstruction of a fixed sample of all four history channels.

No input-builder import, fitted model, database connection, or source write.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtri

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
HISTORY = ROOT/'jeju/research/20261021_phase_pace_prediction_v1/outputs'
BASE = ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2'
CHANNELS = ('rank', 'margin', 'early', 'recovery')
SUFFIXES = ('all_mean', 'exact_distance_deviation', 'all_weight_sum',
            'exact_distance_weight_sum', 'all_weighted_variance', 'days_since_last_valid')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def run():
    inputs = pd.read_parquet(STUDY/'inputs/model_inputs.parquet')
    races = pd.read_parquet(STUDY/'inputs/race_inputs.parquet')
    lineage = pd.read_parquet(STUDY/'inputs/history_lineage.parquet')
    meta = pd.read_parquet(BASE/'features.parquet', columns=['api_record_id', 'race_id', 'race_date', 'horse_id', 'horse_number', 'finish_position', 'field_n', 'distance_m'])
    raw = pd.read_parquet(BASE/'source_snapshot.parquet', columns=['api_record_id', 'horse_id', 'race_id', 'race_date', 'race_distance_m', 'finish_position', 'finish_time_seconds'])
    obs = pd.read_parquet(HISTORY/'observations.parquet', columns=['api_record_id', 'horse_id', 'race_id', 'race_date', 'race_distance_m'])
    labels = pd.read_parquet(HISTORY/'features_and_targets.parquet', columns=['api_record_id', 'y_s1f', 'y_last200_recovery', 'y_count'])
    assert inputs.api_record_id.is_unique and races.race_id.is_unique
    assert set(inputs.api_record_id) == set(meta.api_record_id)
    assert len(inputs) == 52155 and len(races) == 5206 and len(lineage) == 4*len(inputs)
    for col in ('race_id', 'race_date', 'horse_id', 'horse_number', 'finish_position', 'field_n'):
        a = inputs.set_index('api_record_id')[col].sort_index().astype(str)
        b = meta.set_index('api_record_id')[col].sort_index().astype(str)
        if col in ('horse_number', 'finish_position', 'field_n'):
            assert np.array_equal(pd.to_numeric(a), pd.to_numeric(b)), col
        else: assert a.equals(b), col
    history = obs.merge(labels, on='api_record_id', validate='one_to_one')
    history['early'] = np.where(history.y_s1f.notna(), (history.y_s1f == 0).astype(float), np.nan)
    history['recovery'] = history.y_last200_recovery
    strict = raw.loc[raw.api_record_id.isin(set(meta.api_record_id))].copy()
    n = strict.groupby('race_id').api_record_id.transform('size')
    strict['rank'] = ndtri(1-(strict.finish_position-.5)/n)
    median = strict.groupby('race_id').finish_time_seconds.transform('median')
    assert np.isfinite(strict.finish_time_seconds).all() and (strict.finish_time_seconds > 0).all()
    strict['margin'] = np.log(median/strict.finish_time_seconds)
    history = history.merge(strict[['api_record_id', 'rank', 'margin']], on='api_record_id', how='left', validate='one_to_one')
    history['day'] = pd.to_datetime(history.race_date)
    history['horse_id'] = history.horse_id.astype(str)
    history = history.loc[history.day >= pd.Timestamp('2017-01-01')]
    by_horse = {str(h): frame for h, frame in history.groupby('horse_id')}
    # Fixed seed/year strata selected without inspecting model outcomes.
    rng = np.random.default_rng(2026102204)
    sampled = []
    for _, frame in inputs.groupby('year'):
        sampled.extend(rng.choice(frame.index, size=min(128, len(frame)), replace=False).tolist())
    max_error = 0.; comparisons = 0
    for target in inputs.loc[sorted(sampled)].itertuples():
        day = pd.Timestamp(target.race_date)
        h = by_horse[str(target.horse_id)]
        h = h.loc[h.day.between(day-pd.Timedelta(days=730), day-pd.Timedelta(days=2))]
        for ch in CHANNELS:
            v = h.loc[h[ch].notna()]
            prior = 0. if ch in ('rank', 'margin') else .5
            if len(v) == 0:
                expected = [np.nan, np.nan, 0., 0., np.nan, np.nan]
            else:
                age = (day-v.day).dt.days.to_numpy(float)
                w = np.exp2(-age/365.)
                x = v[ch].to_numpy(float)
                sw = math.fsum(w); sx = math.fsum(w*x)
                mean = (3*prior+sx)/(3+sw)
                exact = v.race_distance_m.to_numpy() == target.race_distance_m
                ew = math.fsum(w[exact]); ex = math.fsum((w*x)[exact])
                deviation = (3*mean+ex)/(3+ew)-mean
                var = math.fsum(w*(x-sx/sw)**2)/sw if len(v) >= 2 else np.nan
                expected = [mean, deviation, sw, ew, var, float(min(age))]
            actual = [getattr(target, ch+'_'+suffix) for suffix in SUFFIXES]
            assert np.array_equal(np.isnan(actual), np.isnan(expected)), (target.api_record_id, ch)
            err = np.nanmax(np.abs(np.asarray(actual)-np.asarray(expected)))
            max_error = max(max_error, float(err))
            assert err < 1e-11, (target.api_record_id, ch, err)
            comparisons += 6
    link = lineage.merge(inputs[['api_record_id', 'race_date']], on='api_record_id', validate='many_to_one')
    latest = pd.to_datetime(link.latest_history_date)
    cutoff = pd.to_datetime(link.race_date)-pd.Timedelta(days=2)
    lower = pd.to_datetime(link.race_date)-pd.Timedelta(days=730)
    assert ((latest <= cutoff) | latest.isna()).all()
    assert ((latest >= lower) | latest.isna()).all()
    assert (pd.to_datetime(link.history_cutoff_inclusive) == cutoff).all()
    assert (link.no_valid_history == (link.valid_observations_all_n == 0)).all()
    joined = inputs[['api_record_id', 'label_early', 'label_recovery']].merge(labels, on='api_record_id', validate='one_to_one')
    for name, truth in [('label_early', np.where(joined.y_s1f.notna(), joined.y_s1f.eq(0), np.nan)), ('label_recovery', joined.y_last200_recovery)]:
        assert np.allclose(joined[name], truth, equal_nan=True)
    for ch in ('early', 'recovery'):
        g = inputs.groupby('race_id')[ch+'_all_mean']
        for suffix, expected in [('mean', g.transform('mean')), ('max', g.transform('max')), ('known_count', g.transform('count'))]:
            assert np.allclose(inputs[ch+'_mean_race_'+suffix], expected, equal_nan=True)
        assert np.allclose(inputs[ch+'_mean_race_centered'], inputs[ch+'_all_mean']-g.transform('mean'), equal_nan=True)
    assert np.allclose(inputs.gate_scaled, (inputs.horse_number-1)/(inputs.field_n-1))
    ev = inputs.loc[inputs.year >= 2024]
    assert ev.race_id.nunique() == 1779 and len(ev) == 17412 and ev.race_date.nunique() == 269
    assert ev.race_date.min() == '2024-01-05' and ev.race_date.max() == '2026-09-19'
    assert ev.loc[ev.field_n >= 8].race_id.nunique() == 1743
    return dict(passed=True, sample_rows=len(sampled), feature_cell_comparisons=comparisons,
                max_feature_error=max_error, all_lineage_rows_checked=len(lineage),
                all_target_keys_and_phase_labels_match=True, all_field_summaries_match=True,
                publication_timestamp_available=False, evaluation_races=1779, plc_races=1743,
                input_manifest_sha256=sha(STUDY/'inputs/input_manifest.json'))


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
