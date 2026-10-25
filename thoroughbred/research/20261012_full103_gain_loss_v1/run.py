"""Post-hoc diagnostics of frozen anchor switches; no fitting or promotion."""
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
P = R / '20261012_full103_retention_v1/outputs'
B = R / '20261009_gate_front_late_v1/outputs'
H = R / '20261012_inner_front_retention_v1/outputs/history_events.parquet'
OBS = R / '20261008_field_pace_prediction/outputs/observations.parquet'
KEY = ['race_key', 'program_no', 'horse_id']
KINDS = ['gain', 'loss', 'both_hit', 'both_miss', 'unchanged']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [HERE/'PLAN.md', HERE/'run.py', P/'features.parquet', P/'runner_predictions.parquet',
             P/'race_diagnostics.csv', P/'feature_contract.json', P/'verification.json', H, OBS,
             ROOT/'config/prediction_model_registry.json',
             R/'20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
             R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    for variant, parent, stem in [('combined122', P, 'combined122'), ('baseline103', B, 'full103')]:
        for meet in [1, 3]:
            for year in [2024, 2025, 2026]:
                folder = parent/'models'/f'{stem}_{meet}_{year}'
                paths += [folder/'model.txt', folder/'metadata.json']
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    m = OUT/'input_manifest.json'
    if m.exists():
        assert json.loads(m.read_text()) == manifest
    else:
        save(m, manifest)
    before = OUT/'publication_before.json'
    if not before.exists():
        shared = [R/n for n in ['README.md', 'ARTIFACT_SIZE_LOG.md', 'conclusions/README.md',
                                'conclusions/SOURCES.md', 'conclusions/source_manifest.json']]
        save(before, {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in shared})
        snap = OUT/'publication_before'; snap.mkdir()
        for p in shared:
            (snap/str(p.relative_to(R)).replace('/', '__')).write_bytes(p.read_bytes())


def check():
    for path, expected in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/path) == expected, path


def windows(d):
    yield 'all', d
    for year in [2024, 2025, 2026]:
        z = d[d.year.eq(year)]
        yield str(year), z
        yield f'{year}_to0920', z[z.race_date.dt.strftime('%m-%d').le('09-20')]


def cluster_ci(z):
    g = z.groupby('race_date').net.agg(['sum', 'size'])
    rng = np.random.default_rng(20261012)
    idx = rng.integers(len(g), size=(2000, len(g)))
    v = g['sum'].to_numpy()[idx].sum(axis=1) / g['size'].to_numpy()[idx].sum(axis=1)
    return np.quantile(v, [.025, .975]).tolist()


def summary(z):
    counts = z.kind.value_counts()
    return dict(races=len(z), switches=int(z.switched.sum()),
                old_hits=int(z.old_hit.sum()), new_hits=int(z.new_hit.sum()),
                old_rate=float(z.old_hit.mean()), new_rate=float(z.new_hit.mean()),
                gain=int(counts.get('gain', 0)), loss=int(counts.get('loss', 0)),
                both_hit=int(counts.get('both_hit', 0)), both_miss=int(counts.get('both_miss', 0)),
                net=int(z.net.sum()), delta=float(z.net.mean()), switch_rate=float(z.switched.mean()))


def prepare():
    f = pd.read_parquet(P/'features.parquet')
    pred = pd.read_parquet(P/'runner_predictions.parquet')
    pred['race_date'] = pd.to_datetime(pred.race_date)
    pred = pred[pred.variant.isin(['baseline103', 'combined122']) & pred.target.eq(3)].copy()
    pred = pred.sort_values(['variant', 'race_key', 'raw_score', 'program_no'], ascending=[True, True, False, True])
    pred['rank'] = pred.groupby(['variant', 'race_key']).cumcount() + 1
    assert not pred.duplicated(['variant']+KEY).any()
    a = pred[pred.variant.eq('baseline103')].drop(columns='variant')
    b = pred[pred.variant.eq('combined122')].drop(columns='variant')
    p = a.merge(b[KEY+['raw_score', 'target_probability', 'rank']], on=KEY, validate='one_to_one', suffixes=('_old', '_new'))
    p = p.merge(f, on=KEY+['race_date', 'meet', 'year', 'outcome'], validate='one_to_one')
    p['gate_fraction'] = p.dirgate_inner_n/(p.field_size-1)
    p['inner_pressure'] = (p.dirgate_inner_faster_n/p.dirgate_inner_early_n).where(p.dirgate_inner_early_n.gt(0))
    p['record_field_rank'] = p.groupby('race_key').moist_last3_record_index_mean.rank(ascending=False, method='min')
    p['record_field_adv'] = p.moist_last3_record_index_mean - p.groupby('race_key').moist_last3_record_index_mean.transform('mean')
    p['front_mass'] = p.groupby('race_key').front_gate_probability.transform('sum')
    hist = pd.read_parquet(H, columns=KEY+['early_peer_adv', 'last600_peer_adv', 'late_peer_adv', 'role4', 'role_valid', 'normal_outcome'])
    hist = hist.rename(columns={c: 'actual_'+c for c in hist.columns if c not in KEY})
    p = p.merge(hist, on=KEY, how='left', validate='one_to_one')
    names = pd.read_parquet(OBS, columns=['source_key', 'gate', 'horse_id', 'horse_name'])
    names['race_key'] = names.source_key.str.replace('서울:', '1:', regex=False).str.replace('부산:', '3:', regex=False)
    names['program_no'] = names.gate
    p = p.merge(names[KEY+['horse_name']], on=KEY, how='left', validate='one_to_one')
    selected = {}
    for side in ['old', 'new']:
        selected[side] = p[p['rank_'+side].eq(1)].set_index('race_key').add_prefix(side+'_')
    d = selected['old'].join(selected['new'], validate='one_to_one').reset_index()
    for c in ['year', 'meet', 'race_date', 'distance_m', 'grade', 'grade_kind', 'field_size']:
        assert d['old_'+c].equals(d['new_'+c])
        d[c] = d['old_'+c]
    d['minimum_history'] = d.race_key.map(p.groupby('race_key').history_count.min())
    d['old_margin'] = d.old_target_probability_old - d.race_key.map(p[p.rank_old.eq(2)].set_index('race_key').target_probability_old)
    d['new_margin'] = d.new_target_probability_new - d.race_key.map(p[p.rank_new.eq(2)].set_index('race_key').target_probability_new)
    d['old_hit'] = d.old_outcome.between(1, 3)
    d['new_hit'] = d.new_outcome.between(1, 3)
    d['switched'] = d.old_horse_id.ne(d.new_horse_id)
    d['net'] = d.new_hit.astype(int)-d.old_hit.astype(int)
    d['kind'] = np.select([~d.switched, d.net.eq(1), d.net.eq(-1), d.old_hit], ['unchanged', 'gain', 'loss', 'both_hit'], default='both_miss')
    d['distance_band'] = np.select([d.distance_m.le(1300), d.distance_m.le(1600)], ['short', 'middle'], default='long')
    d['field_band'] = np.select([d.field_size.le(9), d.field_size.le(11)], ['<=9', '10-11'], default='12+')
    d['newhorse_field'] = d.minimum_history.eq(0)
    d['old_probability_band'] = pd.cut(d.old_target_probability_old, [-np.inf, .6, .7, np.inf], right=False).astype(str)
    d['old_margin_band'] = pd.cut(d.old_margin, [-np.inf, .03, .08, np.inf], right=False).astype(str)
    d['promoted_old_rank'] = d.new_rank_old.clip(upper=5).astype(int).astype(str)
    for side in ['old', 'new']:
        d[side+'_gate_band'] = np.select([d[side+'_gate_fraction'].lt(1/3), d[side+'_gate_fraction'].lt(2/3)], ['inner', 'middle'], default='outer')
        d[side+'_front_band'] = pd.cut(d[side+'_front_gate_probability'], [-np.inf, .3, .6, np.inf], right=False).astype(str)
        d[side+'_history_band'] = np.select([d[side+'_history_count'].le(2), d[side+'_history_count'].le(5)], ['<=2', '3-5'], default='6+')
        for event in ['front', 'fast', 'outerfast']:
            n = d[f'{side}_keep_{event}_n']
            d[f'{side}_{event}_support'] = np.select([n.eq(0), n.eq(1)], ['0', '1'], default='2+')
            good = (d[f'{side}_keep_{event}_g3'].ge(0) & d[f'{side}_keep_{event}_g1'].ge(0))
            d[f'{side}_{event}_late'] = np.select([n.eq(0), good], ['no_history', 'both_nonnegative'], default='one_or_both_negative')
    d['new_vs_old_recent'] = np.where(d.new_moist_last3_record_index_mean.ge(d.old_moist_last3_record_index_mean), 'not_worse', 'worse')
    d.loc[d[['new_moist_last3_record_index_mean', 'old_moist_last3_record_index_mean']].isna().any(axis=1), 'new_vs_old_recent'] = 'missing'
    d.to_parquet(OUT/'races.parquet', index=False)
    p.to_parquet(OUT/'runners.parquet', index=False)
    checks = pd.read_csv(P/'race_diagnostics.csv')
    for variant, col in [('baseline103', 'old_hit'), ('combined122', 'new_hit')]:
        c = checks[checks.variant.eq(variant)].set_index('race_key').axis_top3
        np.testing.assert_array_equal(d.set_index('race_key')[col].reindex(c.index).astype(int), c)
    assert len(d)==4799 and len(p)==50754
    check()
    return d, p


def tables(d):
    rows = []
    for period, z in windows(d):
        lo, hi = cluster_ci(z)
        rows.append(dict(period=period, **summary(z), ci_low=lo, ci_high=hi))
    pd.DataFrame(rows).to_csv(OUT/'summary.csv', index=False)
    groupcols = ['meet', 'distance_m', 'distance_band', 'grade', 'grade_kind', 'field_band', 'newhorse_field',
                 'old_probability_band', 'old_margin_band', 'promoted_old_rank', 'new_vs_old_recent']
    groupcols += [s+'_'+c for s in ['old', 'new'] for c in ['gate_band', 'front_band', 'history_band',
                             'front_support', 'fast_support', 'outerfast_support', 'front_late', 'fast_late', 'outerfast_late']]
    rows = []
    for period, z in windows(d):
        for col in groupcols:
            for value, g in z.groupby(col, dropna=False, observed=True):
                rows.append(dict(period=period, condition=col, value=str(value), **summary(g)))
    pd.DataFrame(rows).to_csv(OUT/'conditions.csv', index=False)
    numeric = ['history_count', 'days_since_last', 'current_carried_weight', 'current_vs_previous_carried_weight',
               'moist_last3_record_index_mean', 'moist_last_record_index', 'profile_trend', 'profile_std5',
               'record_field_rank', 'record_field_adv', 'section_early_mean3', 'front_gate_probability',
               'gate_fraction', 'inner_inner_fastest_gap', 'inner_same_inner_fastest_gap', 'inner_pressure',
               'keep_front_g3', 'keep_front_g1', 'keep_front_n', 'keep_front_keep',
               'keep_fast_g3', 'keep_fast_g1', 'keep_fast_n', 'keep_fast_keep',
               'keep_outerfast_g3', 'keep_outerfast_g1', 'keep_outerfast_n',
               'actual_early_peer_adv', 'actual_last600_peer_adv', 'actual_late_peer_adv']
    rows = []
    for period, z in windows(d):
        for kind, g in z[z.switched].groupby('kind'):
            for c in numeric:
                a,b = g['old_'+c],g['new_'+c]; dif=b-a
                rows.append(dict(period=period, kind=kind, feature=c, n=len(g), old_count=int(a.notna().sum()),
                                 new_count=int(b.notna().sum()), paired_count=int(dif.notna().sum()),
                                 old_mean=a.mean(), new_mean=b.mean(), old_median=a.median(), new_median=b.median(),
                                 paired_delta_mean=dif.mean(), paired_delta_median=dif.median()))
    pd.DataFrame(rows).to_csv(OUT/'features_by_switch.csv', index=False)
    # Exact additive net-rate decomposition, using all races and fixed strata.
    rows = []
    for matched in [False, True]:
        z = d[d.year.isin([2025, 2026])]
        if matched:
            z=z[z.race_date.dt.strftime('%m-%d').le('09-20')]
        for cols in [['meet'], ['distance_band'], ['grade'], ['meet', 'distance_band'], ['meet', 'grade']]:
            t = z.groupby(['year']+cols, dropna=False).net.agg(['sum','size'])
            u,v=t.loc[2025],t.loc[2026];ix=u.index.union(v.index)
            u,v=u.reindex(ix).fillna(0),v.reindex(ix).fillna(0)
            pu,pv=u['size']/u['size'].sum(),v['size']/v['size'].sum()
            ru=(u['sum']/u['size']).fillna(0);rv=(v['sum']/v['size']).fillna(0)
            # Symmetric Kitagawa decomposition. Absent strata displayed, not hidden.
            mix=(pv-pu)*(rv+ru)/2; within=(rv-ru)*(pv+pu)/2
            for i, cell in enumerate(ix):
                rows.append(dict(matched=matched, strata='+'.join(cols), cell=str(cell),
                                 n2025=int(u['size'].iloc[i]), n2026=int(v['size'].iloc[i]),
                                 net2025=int(u['sum'].iloc[i]), net2026=int(v['sum'].iloc[i]),
                                 rate2025=ru.iloc[i], rate2026=rv.iloc[i],
                                 mix_contribution=mix.iloc[i], within_contribution=within.iloc[i],
                                 common_support=bool(u['size'].iloc[i]>0 and v['size'].iloc[i]>0)))
            assert np.isclose((mix+within).sum(), z[z.year.eq(2026)].net.mean()-z[z.year.eq(2025)].net.mean())
    pd.DataFrame(rows).to_csv(OUT/'year_decomposition.csv', index=False)
    # No cherry-picking: export every switch, with names and before-race data plus clearly prefixed actuals.
    d[d.switched].to_csv(OUT/'switched_races.csv', index=False)


def attribution_group(c):
    if c.startswith('inner_'): return 'new_inner_early'
    if c.startswith('keep_'): return 'new_paired_late'
    if c.startswith('combine_'): return 'new_interactions'
    if c.startswith('dirgate_'): return 'existing_gate'
    if c.startswith(('rolelate_', 'relate_')): return 'existing_role_late'
    if c.startswith('style_'): return 'existing_style'
    if c.startswith('section_'): return 'existing_sections'
    if c.startswith(('moist_', 'profile_')): return 'existing_record_profile'
    if c.startswith('front_'): return 'existing_front_probability'
    return 'existing_conditions'


def explain(p, d):
    rows=[]; errors=[]; feature_rows=[]
    for variant, parent, stem, suffix in [('baseline103', B, 'full103', 'old'), ('combined122', P, 'combined122', 'new')]:
        for (meet,year), z in p.groupby(['meet','year']):
            folder=parent/'models'/f'{stem}_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text()); cols=meta['features']
            x=z[cols].copy()
            for c, vocab in meta['category_vocabulary'].items():
                x[c]=pd.Categorical(x[c],categories=vocab)
            model=lgb.Booster(model_file=str(folder/'model.txt'))
            score=model.predict(x, raw_score=True, num_threads=1)
            err=float(np.abs(score-z['raw_score_'+suffix].to_numpy()).max());assert err<1e-10
            errors.append(dict(variant=variant,meet=int(meet),year=int(year),runners=len(z),max_error=err))
            pairs=d[d.switched & d.meet.eq(meet) & d.year.eq(year)]
            wanted=set(zip(pairs.race_key,pairs.old_program_no)) | set(zip(pairs.race_key,pairs.new_program_no))
            chosen=np.array([(r,g) in wanted for r,g in zip(z.race_key,z.program_no)])
            contrib=model.predict(x.loc[chosen], pred_contrib=True, num_threads=1)
            np.testing.assert_allclose(contrib.sum(axis=1), score[chosen],atol=1e-10,rtol=0)
            grouped=pd.DataFrame(index=z.loc[chosen].index)
            for group in sorted(set(map(attribution_group,cols))):
                grouped[group]=contrib[:,[i for i,c in enumerate(cols) if attribution_group(c)==group]].sum(axis=1)
            grouped['race_key']=z.loc[chosen,'race_key'];grouped['program_no']=z.loc[chosen,'program_no']
            grouped=grouped.set_index(['race_key','program_no'])
            detailed=pd.DataFrame(contrib[:,:-1],columns=cols)
            detailed['race_key']=z.loc[chosen,'race_key'].to_numpy()
            detailed['program_no']=z.loc[chosen,'program_no'].to_numpy()
            detailed=detailed.set_index(['race_key','program_no'])
            for row in pairs.itertuples():
                delta=grouped.loc[(row.race_key,row.new_program_no)]-grouped.loc[(row.race_key,row.old_program_no)]
                fd=detailed.loc[(row.race_key,row.new_program_no)]-detailed.loc[(row.race_key,row.old_program_no)]
                for feature, val in fd.items():
                    feature_rows.append(dict(year=int(year),meet=int(meet),kind=row.kind,variant=variant,
                                             feature=feature,contribution=float(val)))
                rawdelta=float(z.loc[(z.race_key.eq(row.race_key)) & z.program_no.eq(row.new_program_no),'raw_score_'+suffix].iloc[0]-z.loc[(z.race_key.eq(row.race_key)) & z.program_no.eq(row.old_program_no),'raw_score_'+suffix].iloc[0])
                assert np.isclose(delta.sum(),rawdelta,atol=1e-10)
                for group,val in delta.items():
                    rows.append(dict(race_key=row.race_key,year=int(year),meet=int(meet),kind=row.kind,
                                     variant=variant,group=group,contribution=float(val),pair_score_delta=rawdelta))
    t=pd.DataFrame(rows);t.to_csv(OUT/'pair_attributions.csv', index=False)
    t.groupby(['year','kind','variant','group']).contribution.agg(['count','mean','median']).reset_index().to_csv(OUT/'attribution_summary.csv',index=False)
    pd.DataFrame(feature_rows).groupby(['year','meet','kind','variant','feature']).contribution.agg(['count','mean','median']).reset_index().to_csv(OUT/'feature_attribution_summary.csv',index=False)
    save(OUT/'model_replay.json',dict(models=errors,all_scores_replayed=True,attribution_sum_verified=True,new_models=0))


def main():
    freeze();d,p=prepare();tables(d);explain(p,d);check()
    print(pd.read_csv(OUT/'summary.csv').to_string(index=False))


if __name__=='__main__': main()
