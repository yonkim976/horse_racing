"""Frozen personal_t2 ticket gain/loss diagnostics; no training or policy search."""
from pathlib import Path
from itertools import combinations
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / 'outputs'
PRIOR = R / '20261025_personal_t2_trio_top6_v1/outputs'
DYN = R / '20261024_training_state_v1/outputs'
FEATURES = R / '20261009_gate_front_late_v1/outputs/features.parquet'
GROUPS = R / '20261008_passing_group_style/outputs/observations.parquet'
OBS = R / '20261008_running_style_foundation/outputs/observed_styles.parquet'
DIV = R / '20261025_trio_six_ten_returns_v1/outputs/winning_dividends.parquet'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(name, value):
    p = OUT / name
    assert p.resolve().is_relative_to(OUT)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def freeze():
    paths = [FEATURES, GROUPS, OBS, DIV, DYN/'runner_probabilities.parquet',
             PRIOR/'race_results.parquet', PRIOR/'selected_tickets.parquet',
             PRIOR/'verification.json', PRIOR/'summary.csv', PRIOR/'gain_loss_summary.csv',
             PRIOR/'paired_differences.csv', HERE/'PLAN.md', HERE/'analyze.py',
             R/'20261025_trio_gain_loss_diagnosis_v1/analyze.py']
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            folder = DYN/'models'/f'personal_t2_{meet}_{year}'
            paths += [folder/'scores.parquet', folder/'metadata.json']
    manifest = {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in paths}
    p = OUT/'input_manifest.json'
    if p.exists():
        assert json.loads(p.read_text()) == manifest
    else:
        save('input_manifest.json', manifest)


def record(g, dimension, value, period):
    ga = g[g.transition.eq('gained')]
    lo = g[g.transition.eq('lost')]
    old = int(g.old_return.sum())
    new = int(g.new_return.sum())
    return dict(period=period, dimension=dimension, value=str(value), races=len(g),
                gained=len(ga), lost=len(lo), old_hits=int(g.axis_six_hit.sum()),
                new_hits=int(g.joint_top6_hit.sum()),
                gained_mean=ga.dividend.mean(), lost_mean=lo.dividend.mean(),
                gained_median=ga.dividend.median(), lost_median=lo.dividend.median(),
                gained_return=int(ga.payout.sum()), lost_return=int(lo.payout.sum()),
                old_return=old, new_return=new, delta_return=new-old,
                old_roi=old/(len(g)*6000)-1, new_roi=new/(len(g)*6000)-1,
                delta_roi_pp=(new-old)/(len(g)*6000)*100)


def main():
    freeze()
    races = pd.read_parquet(PRIOR/'race_results.parquet')
    races = races[races.previous_4133].copy().set_index('race_key')
    assert len(races) == 4133 and races.index.is_unique
    races['transition'] = np.select([~races.axis_six_hit & races.joint_top6_hit,
                                     races.axis_six_hit & ~races.joint_top6_hit,
                                     races.axis_six_hit & races.joint_top6_hit],
                                    ['gained', 'lost', 'both'], default='neither')
    races['payout'] = np.rint(races.dividend*1000).astype('int64')
    races['old_return'] = races.payout * races.axis_six_hit
    races['new_return'] = races.payout * races.joint_top6_hit
    races['delta_return'] = races.new_return - races.old_return
    cols = ['race_key', 'program_no', 'horse_id', 'meet', 'race_date', 'year',
            'grade_raw', 'grade', 'grade_kind', 'distance_m', 'history_count',
            'field_size', 'cutoff_date', 'history_source_date', 'profile_source_date',
            'front_gate_probability', 'front_prediction_supported',
            'section_early_mean3', 'section_last600_mean3', 'section_late_mean3',
            'section_early_n5', 'section_last600_n5', 'section_late_n5',
            'profile_top2mean5', 'profile_trend', 'moist_last3_record_index_mean',
            'last3_record_index_mean', 'outcome']
    f = pd.read_parquet(FEATURES, columns=cols)
    f = f.sort_values(['meet', 'race_date', 'race_key', 'program_no']).reset_index(drop=True)
    f['row_number'] = np.arange(len(f))
    scores = []
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            folder = DYN/'models'/f'personal_t2_{meet}_{year}'
            m = json.loads((folder/'metadata.json').read_text())
            assert m['train_end_year'] < year and m['calibration_year'] < year
            s = pd.read_parquet(folder/'scores.parquet')
            s = s[s.phase.eq('evaluation')].copy()
            s['energy'] = s.score / m['temperature']
            scores.append(s[['row_number', 'energy']])
    f = f[f.race_key.isin(races.index)].merge(pd.concat(scores), on='row_number', validate='one_to_one')
    p = pd.read_parquet(DYN/'runner_probabilities.parquet')
    p = p[p.variant.eq('personal_t2')][['race_key', 'program_no', 'top3']]
    f = f.merge(p, on=['race_key', 'program_no'], validate='one_to_one')
    f['model_rank'] = f.groupby('race_key').energy.rank(method='first', ascending=False).astype(int)
    # All current outcomes/actual passage information below are diagnostic labels only.
    o = pd.read_parquet(GROUPS, columns=['source_key','gate','horse_id','first_group',
                                       'first_group_size','group_observed','leader_conflict_race','group_index'])
    o['race_key'] = o.source_key.str.replace('서울:', '1:', regex=False).str.replace('부산:', '3:', regex=False)
    o = o[o.race_key.isin(races.index)].rename(columns={'gate':'program_no'})
    oc = pd.read_parquet(OBS, columns=['source_key', 'gate', 'g3f', 'g1f', 's1f', 's1f_time'])
    o = o.merge(oc, left_on=['source_key','program_no'], right_on=['source_key','gate'], validate='one_to_one')
    observations = {key:g for key,g in o.groupby('race_key')}
    values = []
    for key, g in f.groupby('race_key', sort=True):
        g = g.sort_values('program_no')
        ranked = g.sort_values(['energy','program_no'], ascending=[False,True])
        axis = ranked.iloc[0]
        assert int(axis.program_no) == int(races.loc[key, 'axis'])
        truth = tuple(sorted(g.loc[g.outcome.between(1,3),'program_no'].astype(int)))
        assert len(truth)==3 and len(g)==races.loc[key, 'field_size']
        ts = list(combinations(g.program_no.astype(int),3))
        energy = dict(zip(g.program_no,g.energy))
        energies = [sum(energy[x] for x in t) for t in ts]
        order = sorted(range(len(ts)), key=lambda i:(-energies[i],ts[i]))
        actual_rank = next(i+1 for i,j in enumerate(order) if ts[j]==truth)
        winner = g[g.outcome.between(1,3)].sort_values('model_rank')
        support = bool(g.front_gate_probability.notna().all() and g.front_prediction_supported.all())
        mass = float(g.front_gate_probability.sum()) if support else np.nan
        d = dict(race_key=key, distance=int(g.distance_m.iloc[0]),
                 grade_label='other' if pd.isna(g.grade.iloc[0]) else str(int(g.grade.iloc[0])),
                 grade_raw=g.grade_raw.iloc[0], grade_kind=g.grade_kind.iloc[0],
                 venue='서울' if int(g.meet.iloc[0])==1 else '부산',
                 predicted_front_mass=mass,
                 predicted_pace='unknown' if not support else '<2' if mass<2 else '2-<3' if mass<3 else '3+',
                 field_history_mean=float(g.history_count.mean()),
                 sparse_horses=int(g.history_count.lt(3).sum()),
                 axis_probability=float(axis.top3), axis_front_probability=float(axis.front_gate_probability),
                 fifth_probability=float(ranked.iloc[4].top3), sixth_probability=float(ranked.iloc[5].top3),
                 fifth_sixth_gap=float(ranked.iloc[4].top3-ranked.iloc[5].top3),
                 actual=','.join(map(str,truth)), actual_joint_rank=actual_rank,
                 podium_model_ranks=','.join(map(str,winner.model_rank)),
                 podium_worst_rank=int(winner.model_rank.max()),
                 podium_outside5=int(winner.model_rank.gt(5).sum()),
                 actual_axis_in_podium=bool(int(axis.program_no) in truth),
                 podium_fifth=bool(winner.model_rank.eq(5).any()),
                 min_history_date_ok=bool((g.history_source_date.isna() | g.history_source_date.le(g.cutoff_date)).all()),
                 observed_pace='unknown', observed_front_count=np.nan,
                 observed_front_podium=np.nan, observed_nonfront_podium=np.nan,
                 observed_axis_front=np.nan, observed_notation_coverage=False,
                 observed_status='missing_race')
        z = observations.get(key)
        if z is not None:
            roster = dict(zip(g.program_no,g.horse_id.astype(str)))
            obs_roster = dict(zip(z.program_no,z.horse_id.astype(str)))
            valid = roster==obs_roster and z.group_observed.all() and not z.leader_conflict_race.any()
            d['observed_status'] = 'valid' if valid else 'roster_mismatch' if roster!=obs_roster else 'missing_or_conflicted_group'
            if valid:
                front = set(z.loc[z.first_group.eq(True),'program_no'].astype(int))
                assert len(front)==int(z.first_group_size.iloc[0])
                d.update(observed_pace='1' if len(front)==1 else '2' if len(front)==2 else '3+',
                         observed_front_count=len(front), observed_front_podium=len(front&set(truth)),
                         observed_nonfront_podium=len(set(truth)-front),
                         observed_axis_front=int(axis.program_no) in front,
                         observed_notation_coverage=True)
        values.append(d)
    meta = pd.DataFrame(values).set_index('race_key')
    assert races.actual.eq(meta.loc[races.index, 'actual']).all()
    races = races.drop(columns=races.columns.intersection(meta.columns)).join(meta, validate='one_to_one').reset_index()
    for col in ['distance','grade_label']:
        races['venue_'+col] = races.venue + ':' + races[col].astype(str)
    races['venue_distance_grade'] = races.venue_distance+':'+races.grade_label
    races['observed_front_podium_label'] = races.observed_front_podium.map(lambda x:'unknown' if pd.isna(x) else str(int(x)))
    races.to_parquet(OUT/'race_diagnostics.parquet', index=False)
    cases = races[races.transition.isin(['gained','lost'])].copy()
    assert cases.transition.value_counts().to_dict() == {'gained':225,'lost':144}
    f[f.race_key.isin(cases.race_key)].to_parquet(OUT/'changed_runner_context.parquet', index=False)
    cases.to_csv(OUT/'changed_cases.csv', index=False, encoding='utf-8-sig')
    summaries=[]
    dims=['venue','distance','grade_label','grade_raw','venue_distance','venue_grade_label',
          'venue_distance_grade','predicted_pace','observed_pace','observed_front_podium_label',
          'observed_status','podium_model_ranks']
    for period in ['all',2024,2025,2026]:
        z=races if period=='all' else races[races.year.eq(period)]
        summaries.append(record(z,'all','all',period))
        for dim in dims:
            for value,g in z.groupby(dim,dropna=False):
                summaries.append(record(g,dim,value,period))
    pd.DataFrame(summaries).to_csv(OUT/'condition_summary.csv', index=False, encoding='utf-8-sig')
    # Payout tail diagnosis is symmetric and descriptive, never a purchase filter.
    payout=[];descriptive=[];sensitivity=[];concentration=[]
    numeric=['dividend','field_size','predicted_front_mass','field_history_mean','sparse_horses',
             'axis_probability','axis_front_probability','fifth_probability','sixth_probability',
             'fifth_sixth_gap','actual_joint_rank','podium_worst_rank','podium_outside5',
             'observed_front_count','observed_front_podium','observed_nonfront_podium']
    for period in ['all',2024,2025,2026]:
        z=cases if period=='all' else cases[cases.year.eq(period)]
        for transition,g in z.groupby('transition'):
            payout.append(dict(period=period,transition=transition,n=len(g),mean=g.dividend.mean(),
                               median=g.dividend.median(),p25=g.dividend.quantile(.25),p75=g.dividend.quantile(.75),
                               p90=g.dividend.quantile(.9),max=g.dividend.max(),
                               ge50=int(g.dividend.ge(50).sum()),ge100=int(g.dividend.ge(100).sum())))
            for col in numeric:
                descriptive.append(dict(period=period,transition=transition,variable=col,
                                        n=int(g[col].notna().sum()),mean=g[col].mean(),median=g[col].median()))
            for k in [1,3,5,10]:
                top=g.nlargest(k,'payout')
                concentration.append(dict(period=period,transition=transition,k=k,payout=int(top.payout.sum()),
                                           share=float(top.payout.sum()/g.payout.sum())))
        allz=races if period=='all' else races[races.year.eq(period)]
        for limit in [30,50,100,200]:
            for kind in ['cap','exclude']:
                pay=np.minimum(z.payout,limit*1000) if kind=='cap' else z.payout.where(z.dividend.le(limit),0)
                diff=int((pay*np.where(z.transition.eq('gained'),1,-1)).sum())
                sensitivity.append(dict(period=period,kind=kind,limit=limit,delta_return=diff,
                                        delta_pp=diff/(len(allz)*6000)*100))
    pd.DataFrame(payout).to_csv(OUT/'payout_distribution.csv',index=False)
    pd.DataFrame(descriptive).to_csv(OUT/'case_condition_comparison.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(OUT/'payout_sensitivity.csv',index=False)
    pd.DataFrame(concentration).to_csv(OUT/'payout_concentration.csv',index=False)
    standard=[]
    for period in ['all',2024,2025,2026]:
        z=cases if period=='all' else cases[cases.year.eq(period)]
        for dimension in ['venue','distance','grade_label','predicted_pace','venue_distance_grade']:
            cell=['year',dimension] if period=='all' else [dimension]
            groups=[]
            for key,g in z.groupby(cell):
                counts=g.transition.value_counts()
                if counts.get('gained',0)>=5 and counts.get('lost',0)>=5:
                    groups.append((len(g),g[g.transition.eq('gained')].dividend.mean(),
                                   g[g.transition.eq('lost')].dividend.mean()))
            n=sum(t[0] for t in groups)
            standard.append(dict(period=period,dimension=dimension,common_cells=len(groups),supported_cases=n,
                                  gained_standard_mean=sum(t[0]*t[1] for t in groups)/n if n else np.nan,
                                  lost_standard_mean=sum(t[0]*t[2] for t in groups)/n if n else np.nan))
    pd.DataFrame(standard).to_csv(OUT/'common_cell_standardization.csv',index=False)
    cases[cases.transition.eq('lost')].sort_values('payout',ascending=False).head(15).to_csv(OUT/'largest_lost.csv',index=False,encoding='utf-8-sig')
    cases[cases.transition.eq('gained')].sort_values('payout',ascending=False).head(15).to_csv(OUT/'largest_gained.csv',index=False,encoding='utf-8-sig')
    save('summary.json', dict(races=len(races),gained=int(cases.transition.eq('gained').sum()),
                             lost=int(cases.transition.eq('lost').sum()),delta_return=int(races.delta_return.sum()),
                             actual_pace_coverage=int(races.observed_notation_coverage.sum()),
                             missing_status=races.observed_status.value_counts().to_dict(),
                             source_history_ok=bool(races.min_history_date_ok.all()),new_fits=0))
    print(pd.read_csv(OUT/'condition_summary.csv').query("dimension=='all'").to_string(index=False))
    print(pd.read_csv(OUT/'payout_distribution.csv').to_string(index=False))


if __name__=='__main__':
    main()
