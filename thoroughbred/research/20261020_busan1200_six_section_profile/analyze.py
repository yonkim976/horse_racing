"""Read-only Busan1200 six-section descriptive profiles. No prediction fitting."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
DB = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
KEY = ['date', 'race_no', 'horse_id']
POINTS = ['S1F', 'G4F', 'G3F', 'G2F', 'G1F']
PARTS = [f's{i}' for i in range(1, 7)]
LABELS = [f'{i*200}–{(i+1)*200}m' for i in range(6)]


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def check_inputs():
    for name, old in json.loads((OUT / 'input_manifest.json').read_text()).items():
        p = ROOT / name
        assert p.stat().st_size == old['bytes'] and sha(p) == old['sha256'], name


def load():
    with duckdb.connect(str(DB), read_only=True) as c:
        runners = c.execute('''SELECT result_date AS date,
            try_cast(result_race_no AS INT) AS race_no,horse_id_raw AS horse_id,
            try_cast(horse_program_no_raw AS INT) AS program_no,horse_name_raw AS horse_name,
            try_cast(result_rank_raw AS INT) AS finish_rank,
            try_cast(finish_time_seconds_raw AS DOUBLE) AS finish_seconds,
            grade_raw AS grade,track_condition_raw AS moisture,
            source_file,source_item_index
            FROM confirmed_runners WHERE source_meet=?
            AND try_cast(race_distance_m_raw AS INT)=?
            AND result_date BETWEEN ? AND ?
            AND try_cast(result_rank_raw AS INT) BETWEEN 1 AND 30
            AND try_cast(finish_time_seconds_raw AS DOUBLE)>0''',
            ['3', 1200, '20100101', '20260918']).df()
        sections = c.execute('''SELECT race_date AS date,race_no,horse_id,
            point_code,measure_kind,time_ms,passing_order
            FROM section_measurements_api WHERE meet=?
            AND race_date BETWEEN ? AND ?
            AND point_code IN ('S1F','G4F','G3F','G2F','G1F')
            AND measure_kind IN ('cumulative_time','passing_order')''',
            [3, '20100101', '20260918']).df()
    assert not runners.duplicated(KEY).any()
    q = sections[sections.measure_kind.eq('cumulative_time')]
    p = sections[sections.measure_kind.eq('passing_order')]
    assert not q.duplicated(KEY+['point_code']).any()
    assert not p.duplicated(KEY+['point_code']).any()
    a = q.pivot(index=KEY, columns='point_code', values='time_ms').div(1000).reset_index()
    b = p.pivot(index=KEY, columns='point_code', values='passing_order').add_prefix('order_').reset_index()
    d = runners.merge(a, on=KEY, how='left', validate='one_to_one').merge(b, on=KEY, how='left', validate='one_to_one')
    return d.sort_values(['horse_id', 'date', 'race_no']).reset_index(drop=True)


def main():
    check_inputs()
    d = load()
    assert len(d) == 34663
    matrix = np.column_stack([np.zeros(len(d)), d[POINTS].to_numpy(float), d.finish_seconds.to_numpy(float)])
    raw = np.diff(matrix, axis=1)
    pair_valid = np.isfinite(raw) & (raw > 0) & (matrix[:, :-1] >= 0) & (matrix[:, 1:] <= matrix[:, -1, None])
    d['complete_six'] = pair_valid.all(axis=1)
    assert int(d.complete_six.sum()) == 34660
    full = d.complete_six.to_numpy()
    np.testing.assert_allclose(raw[full].sum(axis=1), d.loc[full, 'finish_seconds'], rtol=0, atol=1e-10)
    for i, s in enumerate(PARTS):
        d[s+'_seconds'] = np.where(pair_valid[:, i], raw[:, i], np.nan)
        d[s+'_equivalent_seconds'] = 6*d[s+'_seconds']
        d[s+'_index'] = 100*d.finish_seconds/d[s+'_equivalent_seconds']
        d[s+'_delta'] = d[s+'_index'] - 100
        d[s+'_equivalent_advantage_seconds'] = d.finish_seconds - d[s+'_equivalent_seconds']
    race = ['date', 'race_no']
    d['normal_finishers'] = d.groupby(race).horse_id.transform('size')
    for point in POINTS:
        v = 'order_'+point
        d[v] = d[v].to_numpy(dtype=float, na_value=np.nan)
        d[v] = d[v].where(d[v].between(1, 30))
    # This denominator is observed among normal finishers, not a full-starter certificate.
    d['observed_order_max'] = d.groupby(race).order_S1F.transform('max')
    d['early_position_fraction'] = (d.order_S1F-1)/(d.observed_order_max-1).replace(0, np.nan)
    d['observed_early_position'] = np.select([
        d.order_S1F.isna(), d.order_S1F.eq(1), d.early_position_fraction.le(1/3),
        d.early_position_fraction.le(2/3)], ['미확인', '선행', '앞선', '중단'], default='후미')
    good = d[d.complete_six].copy()
    for s in PARTS:
        # Only complete normal finishers contribute to the descriptive field reference.
        median = good.groupby(race)[s+'_delta'].median().rename(s+'_field_median_delta')
        d = d.merge(median, on=race, how='left', validate='many_to_one')
        d[s+'_field_shape_delta'] = d[s+'_delta']-d[s+'_field_median_delta']
        d[s+'_time_rank_in_normal_field'] = d.groupby(race)[s+'_seconds'].rank(method='min')
    d['early_shape'] = d.s1_field_shape_delta
    d['late_shape'] = d[['s5_field_shape_delta','s6_field_shape_delta']].mean(axis=1, skipna=False)
    d['shape'] = np.select([
        ~d.complete_six,
        d.early_shape.ge(0) & d.late_shape.ge(0),
        d.early_shape.ge(0) & d.late_shape.lt(0),
        d.early_shape.lt(0) & d.late_shape.ge(0)],
        ['분할불완전', '초반비중↑·종반비중↑', '초반비중↑·종반비중↓', '초반비중↓·종반비중↑'],
        default='초반비중↓·종반비중↓')
    d['position_gain_last400'] = d.order_G2F - d.finish_rank
    # Every slot is a normal1200 start; an invalid timing slot still consumes its place.
    d = d.sort_values(['horse_id','date','race_no']).reset_index(drop=True)
    for s in PARTS:
        for name in ['index', 'seconds']:
            col = s+'_'+name
            d['past5_'+col+'_mean'] = d.groupby('horse_id')[col].transform(lambda x: x.shift().rolling(5,min_periods=1).mean())
        d['past5_'+s+'_n'] = d.groupby('horse_id')[s+'_index'].transform(lambda x: x.shift().rolling(5,min_periods=0).count()).astype(int)
    d['past5_last_date'] = d.groupby('horse_id').date.shift()
    d['past5_slots'] = d.groupby('horse_id').cumcount().clip(upper=5)
    has_past = d.past5_last_date.notna()
    assert (d.loc[has_past,'past5_last_date'] < d.loc[has_past,'date']).all()
    d['year'] = d.date.str[:4].astype(int)
    d.to_parquet(OUT/'runner_profiles.parquet', index=False)
    d.loc[~d.complete_six,KEY+['program_no','horse_name']+POINTS+['finish_seconds']].to_csv(OUT/'incomplete_records.csv',index=False)
    recent = d[d.year.ge(2024) & d.complete_six].copy()
    distribution=[]
    for s,label in zip(PARTS,LABELS):
        for scope,g in [('all_2010_2026',d[d.complete_six]),('recent_2024_2026',recent)]:
            distribution.append(dict(scope=scope,segment=label,n=len(g),seconds_mean=float(g[s+'_seconds'].mean()),
                index_mean=float(g[s+'_index'].mean()),index_median=float(g[s+'_index'].median()),
                index_p20=float(g[s+'_index'].quantile(.2)),index_p80=float(g[s+'_index'].quantile(.8))))
    pd.DataFrame(distribution).to_csv(OUT/'segment_distributions.csv',index=False)
    grouped=recent.groupby('shape').agg(n=('horse_id','size'),races=('race_no','size'),
        early_index=('s1_index','mean'),late_index=('s6_index','mean'),
        early_position_mean=('order_S1F','mean'),position_gain_last400_mean=('position_gain_last400','mean'),
        finish_seconds_mean=('finish_seconds','mean'))
    grouped['races'] = recent.groupby('shape').apply(lambda x:x[['date','race_no']].drop_duplicates().shape[0],include_groups=False)
    grouped.to_csv(OUT/'shape_groups.csv')
    pd.crosstab(recent['shape'],recent.observed_early_position).to_csv(OUT/'shape_vs_early_position.csv')
    observed=recent[recent.observed_early_position.ne('미확인')]
    rho = observed.s1_index.corr(-observed.early_position_fraction,method='spearman')
    late_rho = recent[['s5_index','s6_index']].mean(axis=1).corr(recent.position_gain_last400,method='spearman')
    # Descriptive same-horse adjacent-start stability; not an evaluated style predictor.
    temp=d[d.complete_six].sort_values(['horse_id','date','race_no']).copy()
    temp['previous_shape']=temp.groupby('horse_id')['shape'].shift()
    temp['previous_date']=temp.groupby('horse_id')['date'].shift()
    pairs=temp[temp.year.ge(2024)&temp.previous_shape.notna()]
    recent_races=recent.groupby(race).agg(rows=('horse_id','size'),field=('normal_finishers','first'))
    selected=recent_races[(recent_races.rows.eq(recent_races.field))&(recent_races.rows.ge(8))].tail(8).reset_index()[race]
    examples=d.merge(selected,on=race,how='inner').sort_values(race+['program_no'])
    examples.to_csv(OUT/'example_runners.csv',index=False)
    save('summary.json',dict(source_end='2026-09-18',normal1200_rows=len(d),complete_rows=int(full.sum()),
        incomplete_rows=int((~full).sum()),races=d[race].drop_duplicates().shape[0],
        recent_complete_rows=len(recent),recent_races=recent[race].drop_duplicates().shape[0],
        formula='I=100*T/(6*t); delta=I-100; equivalent_time=6*t',baseline='same horse same race mean speed',
        raw_early_index_vs_forward_position_spearman=float(rho),
        late_index_vs_last400_position_gain_spearman=float(late_rho),
        same_horse_next_complete_start_pairs=len(pairs),same_shape_fraction=float(pairs['shape'].eq(pairs.previous_shape).mean()),
        examples=selected.to_dict('records'),new_prediction_models=0,track_corrections_applied=False,
        descriptions_are_postrace=True,history_cutoff='strictly earlier date; source publication timestamps unverified',
        same_horse_stability_scope='consecutive complete1200 starts; may skip incomplete timing starts; not the past5 feature slot definition'))
    save('verification.json',dict(status='analyzed_pending_independent_verify',six_partition_sum_max_error=float(np.abs(raw[full].sum(axis=1)-d.loc[full,'finish_seconds'].to_numpy()).max()),
        protected_hashes=len(json.loads((OUT/'input_manifest.json').read_text())),database_mode='read_only',
        jeju_db_access=False,production_changed=False,web_app_changed=False,prediction_models_trained=0))
    print((OUT/'summary.json').read_text())


if __name__=='__main__':
    main()
