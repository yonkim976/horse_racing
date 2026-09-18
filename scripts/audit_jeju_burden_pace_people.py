"""Retrospective hypothesis audit; no fitting or production prediction changes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from analyze_jeju_conditions_questions import adjusted, records

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/jeju_burden_pace_people_audit_20260918'
DB = ROOT / 'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
OBS = ROOT / 'data/research/jeju_tempo_pace_features_20260917/observations.parquet'
COND = ROOT / 'data/research/jeju_conditions_questions_20260917/race_entries.parquet'
STATE = ROOT / 'data/research/jeju_native_top3_dataset_v1_20260915_r2/horse_states.parquet'
PRED = ROOT / 'data/research/jeju_tempo_pace_pilot_20260917/horse_predictions.parquet'
STEWARD = ROOT / 'data/research/jeju_steward_2024_events_20260917/features_2024_2026.parquet'


def read(path):
    return pd.DataFrame(pl.read_parquet(path).to_dicts())


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                                      allow_nan=False, default=str))


def describe(d, group):
    return records(d.groupby(group, observed=True, dropna=False).agg(
        starts=('entry_id', 'size'), horses=('horse_id', 'nunique'),
        top3=('top3', 'sum'), top3_rate=('top3', 'mean'),
        prior_top3_rate=('previous_top3', 'mean'),
        mean_elo_gap=('elo_gap', 'mean'),
        relative_seconds_per100=('relative_seconds_per100', 'mean'),
    ).reset_index())


def residual_summary(d):
    """Day clustered exploratory intervals, fixed seed; multiplicity unadjusted."""
    if d.empty:
        return dict(starts=0)
    sums = d.assign(residual=d.y-d.p).groupby('event_date').agg(
        n=('entry_id', 'size'), residual=('residual', 'sum'))
    a = sums.to_numpy()
    ix = np.random.default_rng(17).integers(0, len(a), (5000, len(a)))
    b = a[ix].sum(axis=1)
    ci = np.quantile(b[:, 1]/b[:, 0], [.025, .975])
    return dict(starts=len(d), horses=d.horse_id.nunique(), days=len(sums),
                top3=int(d.y.sum()), actual_rate=float(d.y.mean()),
                predicted_rate=float(d.p.mean()), residual=float((d.y-d.p).mean()),
                residual_ci95=ci.tolist())


def main():
    OUT.mkdir(exist_ok=False)
    save('protocol.json', dict(
        purpose='Exploratory data audit, no model training or promotion',
        cutoff='2026-09-12', recent_from='2023-01-01',
        fade_definition='Valid normal splits; start-to-600m-left at least 0.3s faster '
                        'than own race median; last200 at least 0.5s slower than own race '
                        'median AND at least 0.5s slower than preceding400 per200 equivalent.',
        burden_groups='decrease<=-1kg; stable (-1,+1); increase>=+1kg',
        prospective_use='Only lagged observed profiles through T-2; current splits forbidden',
        inference='Association, not physiological energy or causal effects; unadjusted multiplicity',
        reused_evaluation=True))
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    extra = pd.read_sql_query("""SELECT e.id entry_id,e.horse_name,e.tr_no trainer_id,
        json_extract(s.normalized_json,'$.trName') trainer_name,
        json_extract(s.normalized_json,'$.jeG3fTime') g3f_seconds
        FROM entry e JOIN source_row s ON s.id=e.source_row_id
        JOIN event v ON v.id=e.event_id
        WHERE v.event_type='race' AND v.event_date<='20260912'""", c)
    sections = dict(c.execute('SELECT section_code,count(*) FROM section_checkpoint GROUP BY section_code'))
    training = {}
    for t in ['daily_training_record', 'analysis_start_training_distinct']:
        training[t] = records(pd.read_sql_query(f"""SELECT substr(event_date,1,4) year,
            count(*) records,count(distinct hr_no) horses,min(event_date) first_date,
            max(event_date) last_date FROM {t} WHERE event_date<='20260912'
            GROUP BY substr(event_date,1,4)""", c))
    c.close()
    h = read(OBS).merge(extra, on='entry_id', validate='one_to_one')
    h.event_date = pd.to_datetime(h.event_date)
    assert h.event_date.max() <= pd.Timestamp('2026-09-12')
    assert h.entry_id.is_unique
    h['g3f_seconds'] = pd.to_numeric(h.g3f_seconds, errors='coerce')
    h['top3'] = h.outcome_status.eq('normal_completed') & h.finish_position.between(1, 3)
    valid = (h.outcome_status.eq('normal_completed') & h.segment_quality.eq('usable') &
             h.distance_m.ge(900) & h.g1f_seconds.gt(0) & h.g3f_seconds.gt(h.g1f_seconds) &
             h.total_seconds.gt(h.g3f_seconds) & h.s1f_seconds.gt(0) &
             (h.total_seconds-h.g3f_seconds).gt(h.s1f_seconds))
    h['split_valid'] = valid
    for name, values in {
        'pre600_seconds': h.total_seconds-h.g3f_seconds,
        'between600_200_seconds': h.g3f_seconds-h.g1f_seconds,
        'last200_seconds': h.g1f_seconds,
    }.items():
        h[name] = values.where(valid)
        h[name+'_race_relative'] = h[name]-h.groupby('race_id')[name].transform('median')
    h['late200_slowdown_seconds'] = h.last200_seconds-h.between600_200_seconds/2
    h['fast_then_fade'] = np.where(valid,
        (h.pre600_seconds_race_relative.le(-.3) & h.last200_seconds_race_relative.ge(.5) &
         h.late200_slowdown_seconds.ge(.5)).astype(float), np.nan)
    h = h.sort_values(['horse_id', 'event_date', 'entry_id'])
    lagcols = ['entry_id', 'event_date', 'distance_m', 'grade', 'burden_kg', 'top3',
               'finish_position', 'fast_then_fade', 'pre600_seconds_race_relative',
               'last200_seconds_race_relative']
    for col in lagcols:
        h['previous_'+col] = h.groupby('horse_id')[col].shift()
    days = (h.event_date-h.previous_event_date).dt.days
    # Use no prior row less than two days old, even for this retrospective audit.
    h.loc[days.lt(2), ['previous_'+x for x in lagcols]] = np.nan
    h['burden_delta'] = h.burden_kg-h.previous_burden_kg
    h['burden_group'] = pd.Series(pd.NA, index=h.index, dtype='string')
    h.loc[h.burden_delta.notna(), 'burden_group'] = 'stable'
    h.loc[h.burden_delta.le(-1), 'burden_group'] = 'decrease'
    h.loc[h.burden_delta.ge(1), 'burden_group'] = 'increase'
    h['relative_seconds_per100'] = (h.time_minus_race_median_ms/h.distance_m/10).where(
        h.segment_quality.eq('usable') & h.outcome_status.eq('normal_completed'))
    h['elo_gap'] = h.global_elo_pre-h.rival_elo_mean
    d = h[h.event_date.ge('2023-01-01') & h.distance_m.ge(800)].copy()
    conditions = read(COND)[['entry_id', 'age', 'sex', 'year_grade', 'month', 'track', 'gap_days']]
    d = d.merge(conditions, on='entry_id', validate='one_to_one')
    state = read(STATE)[['entry_id', 'training_28d_count', 'training_28d_duration_seconds',
                        'training_28d_gallop_count', 'training_28d_coverage_unknown',
                        'training_28d_observed_any', 'start_training_28d_count']]
    d = d.merge(state, on='entry_id', validate='one_to_one')
    assert len(d) == len(conditions) == 25529
    summary = dict(starts=len(d), races=d.race_id.nunique(), horses=d.horse_id.nunique(),
                   section_counts_all_history=sections, training_inventory=training,
                   final400_available=False, valid_splits=int(d.split_valid.sum()),
                   fast_then_fade=int(d.fast_then_fade.eq(1).sum()))
    summary['burden_groups'] = describe(d.dropna(subset=['burden_group']), ['burden_group'])
    # Stable distance/grade and same policy year; prior outcome and ability remain confounder controls.
    stable = d[d.distance_m.eq(d.previous_distance_m) & d.grade.eq(d.previous_grade) &
               d.event_date.dt.year.eq(d.previous_event_date.dt.year)].copy()
    numeric = ['elo_gap', 'field_size', 'age', 'previous_burden_kg', 'previous_finish_position', 'gap_days']
    cats = ['year_grade', 'month', 'distance_m', 'sex', 'track']
    summary['burden_adjusted_top3'] = adjusted(stable, 'burden_group', 'top3', cats, numeric, 'stable')
    summary['burden_adjusted_relative_time'] = adjusted(stable, 'burden_group', 'relative_seconds_per100', cats, numeric, 'stable')
    for k in ['burden_adjusted_top3', 'burden_adjusted_relative_time']:
        assert summary[k]['rank'] == summary[k]['columns'], (k, summary[k])
    d['style_observed'] = pd.cut(d.early_rank.where(d.early_rank.between(1,d.field_size)),
        [0, 1, 3, 5, 100], labels=['lead', 'stalk2to3', 'mid4to5', 'back6plus'])
    d['late_gain_observed'] = (d.c4_rank-d.finish_position).where(
        d.outcome_status.eq('normal_completed') & d.c4_rank.between(1,d.field_size))
    style = d.dropna(subset=['jockey_id', 'style_observed']).groupby(
        ['jockey_id', 'jockey_name', 'style_observed'], observed=True).agg(
        starts=('entry_id', 'size'), horses=('horse_id', 'nunique'),
        top3_rate=('top3', 'mean'), mean_elo_gap=('elo_gap', 'mean'),
        mean_c4_finish_gain=('late_gain_observed', 'mean')).reset_index()
    save('jockey_style_descriptive.json', records(style))
    people = d.dropna(subset=['jockey_id']).groupby(['jockey_id', 'jockey_name']).agg(
        starts=('entry_id', 'size'), horses=('horse_id', 'nunique'),
        known_early=('early_rank', lambda x: x.between(1, 20).sum()),
        leads=('early_rank', lambda x: x.eq(1).sum()),
        top3_rate=('top3', 'mean'), mean_elo_gap=('elo_gap', 'mean')).reset_index()
    people['lead_rate'] = people.leads/people.known_early
    save('jockey_summary.json', records(people.sort_values('starts', ascending=False)))
    trainer = d.dropna(subset=['trainer_id']).groupby(['trainer_id', 'trainer_name']).agg(
        starts=('entry_id', 'size'), horses=('horse_id', 'nunique'),
        top3_rate=('top3', 'mean'), mean_elo_gap=('elo_gap', 'mean'),
        training_observed_rate=('training_28d_observed_any', 'mean'),
        training_coverage_unknown_rate=('training_28d_coverage_unknown', 'mean'),
        training_count_mean=('training_28d_count', 'mean')).reset_index()
    save('trainer_summary.json', records(trainer.sort_values('starts', ascending=False)))
    summary['coverage_year'] = records(d.assign(year=d.event_date.dt.year).groupby('year').agg(
        starts=('entry_id', 'size'), trainer_known=('trainer_id', 'count'),
        jockey_known=('jockey_id', 'count'), split_valid=('split_valid', 'sum'),
        training_observed=('training_28d_observed_any', 'sum'),
        training_coverage_unknown=('training_28d_coverage_unknown', 'sum')).reset_index())
    pred = read(PRED).query("model == 'BASE__BASE'")
    ev = d.merge(pred, on=['race_id', 'horse_id'], validate='one_to_one')
    assert len(ev) == 4852 and (ev.top3.astype(int) == ev.y).all()
    steward = read(STEWARD)[['entry_id', 'previous_report_known', 'previous_explicit_event']]
    ev = ev.merge(steward, on='entry_id', validate='one_to_one')
    cases = {}
    for name, mask in {
        'all': pd.Series(True, index=ev.index),
        'previous_fade': ev.previous_fast_then_fade.eq(1),
        'previous_fade_nonpodium': ev.previous_fast_then_fade.eq(1) & ev.previous_top3.eq(False),
        'previous_fade_nonpodium_burden_decrease': ev.previous_fast_then_fade.eq(1) & ev.previous_top3.eq(False) & ev.burden_group.eq('decrease'),
        'previous_fade_nonpodium_burden_stable': ev.previous_fast_then_fade.eq(1) & ev.previous_top3.eq(False) & ev.burden_group.eq('stable'),
        'previous_fade_nonpodium_burden_increase': ev.previous_fast_then_fade.eq(1) & ev.previous_top3.eq(False) & ev.burden_group.eq('increase'),
        'previous_steward_event_burden_decrease': ev.previous_explicit_event.eq(True) & ev.burden_group.eq('decrease'),
    }.items():
        cases[name] = residual_summary(ev[mask.fillna(False)])
    for name in ['decrease', 'stable', 'increase']:
        cases['burden_'+name] = residual_summary(ev[ev.burden_group.eq(name).fillna(False)])
    save('next_start_associations.json', cases)
    save('summary.json', summary)
    keep = ['entry_id', 'race_id', 'horse_id', 'horse_name', 'event_date', 'previous_entry_id',
            'previous_event_date', 'burden_delta', 'burden_group', 'previous_fast_then_fade',
            'previous_top3', 'previous_report_known', 'previous_explicit_event', 'p', 'y']
    save('evaluation_lineage.json', records(ev[keep]))
    save('verification.json', dict(unique_entry_ids=True, recent_starts=len(d), evaluation_starts=len(ev),
        labels_equal_saved_predictions=True, model_fits=0,
        regression_full_rank=True,
        lagged_sources_through_T_minus_2=bool((ev.event_date-ev.previous_event_date).dropna().dt.days.ge(2).all()),
        record_cutoff=str(d.event_date.max().date())))
    def sha(path):
        with path.open('rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest()
    save('manifest.json', dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in [OBS, COND, STATE, PRED, STEWARD, DB]},
         script_sha256=sha(Path(__file__)), outputs={p.name:sha(p) for p in OUT.iterdir()}))
    print(json.dumps(summary, ensure_ascii=False, default=str))
    print(json.dumps(cases, ensure_ascii=False))


if __name__ == '__main__':
    main()
