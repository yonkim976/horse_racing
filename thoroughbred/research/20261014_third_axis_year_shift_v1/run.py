"""Frozen third-anchor gain/loss diagnostics and prior-model sensitivity."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import softmax
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PREV = R / '20261014_open_axis_candidates_v1'
P = PREV / 'outputs'
OBS = R / '20261008_field_pace_prediction/outputs/observations.parquet'
KEY = ['race_key', 'program_no', 'horse_id']
EXTRA = ['previous_age', 'section_previous_distance', 'section_same_distance_n5',
         'inner_inner_fastest_gap', 'section_early_mean3', 'section_last600_mean3',
         'section_late_mean3', 'profile_std5', 'current_carried_weight']


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


E = module('frozen_open_axis_diagnostic', PREV / 'run.py')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [HERE / 'PLAN.md', HERE / 'run.py', PREV / 'run.py',
             P / 'input_manifest.json', P / 'verification.json', P / 'candidate_frame.parquet',
             P / 'candidate_predictions.parquet', P / 'selected_axes.parquet',
             P / 'selection_diagnostics.parquet', P / 'race_metrics.parquet',
             E.PRIOR / 'outputs/base_predictions.parquet', E.FEATURES, OBS,
             ROOT / 'config/prediction_model_registry.json',
             R / '20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
             R / '20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    for year in [2025, 2026]:
        paths += [P / 'models' / f'gain_logit_{year}' / n for n in ['model.json', 'preprocess.json', 'metadata.json']]
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    target = OUT / 'input_manifest.json'
    if target.exists():
        assert json.loads(target.read_text()) == manifest
    else:
        save(target, manifest)
    before = OUT / 'publication_before.json'
    if not before.exists():
        files = [R / n for n in ['README.md', 'ARTIFACT_SIZE_LOG.md', 'conclusions/README.md',
                                'conclusions/SOURCES.md', 'conclusions/source_manifest.json']]
        save(before, {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in files})
        snap = OUT / 'publication_before'
        snap.mkdir()
        for p in files:
            (snap / str(p.relative_to(R)).replace('/', '__')).write_bytes(p.read_bytes())


def check():
    for path, digest in json.loads((OUT / 'input_manifest.json').read_text()).items():
        assert sha(ROOT / path) == digest, path


def periods(d):
    yield '2025_full', d[d.year.eq(2025)]
    yield '2025_to0920', d[d.year.eq(2025) & d.race_date.dt.strftime('%m-%d').le('09-20')]
    yield '2025_after0920', d[d.year.eq(2025) & d.race_date.dt.strftime('%m-%d').gt('09-20')]
    yield '2026_to0920', d[d.year.eq(2026)]


def bucket(name):
    name = name.removeprefix('missing_')
    for section in ['g1', 'g3']:
        for context in ['support', 'recent']:
            if '_' + section + '_x_' + context in name:
                return section + '_' + context
    if 'keep_fast_g1' in name:
        return 'g1_level'
    if 'keep_fast_g3' in name:
        return 'g3_level'
    if 'keep_fast_n' in name or 'keep_fast_keep' in name:
        return 'support_maintenance'
    if any(x in name for x in ['moist_last3', 'profile_count3', 'profile_trend', 'record_field_adv']):
        return 'recent_records'
    if 'front_gate_probability' in name:
        return 'front_probability'
    if 'gate_fraction' in name:
        return 'gate_position'
    if 'history_count' in name or 'days_since_last' in name:
        return 'experience_interval'
    if 'target_probability' in name or 'model_rank' in name:
        return 'base_assessment'
    return 'race_context'


def prepare():
    diagnostics = pd.read_parquet(P / 'selection_diagnostics.parquet')
    diagnostics = diagnostics[diagnostics.variant.eq('gain_logit_all') & diagnostics.year.isin([2025, 2026])].copy()
    source = pd.read_parquet(E.PRIOR / 'outputs/base_predictions.parquet')
    base = source[source.variant.eq('combined122')].set_index(['race_key', 'horse_id'])
    d = diagnostics[diagnostics.is_third].copy()
    d['program_no'], d['horse_id'] = d.axis_program_no, d.axis_horse_id
    d['group'] = np.select([d.gain_vs_prior, d.loss_vs_prior], ['gain', 'loss'], default='neutral')
    prior_index = pd.MultiIndex.from_arrays([d.race_key, d.prior_selected_horse_id])
    prior = base.loc[prior_index]
    d['prior_program_no'] = prior.program_no.to_numpy()
    d['prior_outcome'] = prior.outcome.to_numpy()
    d['race_no'] = d.race_key.str.rsplit(':', n=1).str[-1].astype(int)
    f = E.load_features()
    extra = pd.read_parquet(E.FEATURES, columns=KEY + EXTRA)
    f = f.merge(extra, on=KEY, validate='one_to_one')
    names = pd.read_parquet(OBS, columns=['source_key', 'gate', 'horse_id', 'horse_name'])
    names['race_key'] = names.source_key.str.replace('서울:', '1:', regex=False).str.replace('부산:', '3:', regex=False)
    names['program_no'] = names.gate
    f = f.merge(names[KEY + ['horse_name']], on=KEY, how='left', validate='one_to_one').set_index(KEY)
    features = E.HORSE + EXTRA
    for side, ix in [('third', pd.MultiIndex.from_frame(d[KEY])),
                     ('prior', pd.MultiIndex.from_arrays([d.race_key, d.prior_program_no, d.prior_selected_horse_id]))]:
        a = f.loc[ix]
        for col in features + ['horse_name']:
            d[side + '_' + col] = a[col].to_numpy()
        d[side + '_distance_change'] = d.distance_m - d[side + '_section_previous_distance']
    for col in features + ['distance_change']:
        d['difference_' + col] = d['third_' + col] - d['prior_' + col]
    d['distance_band'] = np.select([d.distance_m.le(1300), d.distance_m.le(1600)], ['short', 'middle'], default='long')
    d['grade_band'] = np.select([d.grade.eq(6), d.grade.eq(5), d.grade.between(1, 4)], ['grade6', 'grade5', 'grade1_4'], default='unknown')
    d['field_band'] = np.where(d.field_size.le(9), 'le9', 'ge10')
    d['history_band'] = np.where(d.third_history_count.le(2), 'le2', 'ge3')
    d['g1_missing'] = d.third_keep_fast_g1.isna().astype(str)
    d = d.sort_values(['race_date', 'meet', 'race_no']).reset_index(drop=True)
    d.to_parquet(OUT / 'cases.parquet', index=False)
    d.to_csv(OUT / 'all_third_cases.csv', index=False)
    for year in [2025, 2026]:
        for group in ['gain', 'loss']:
            d[d.year.eq(year) & d.group.eq(group)].to_csv(OUT / f'{year}_{group}_cases.csv', index=False)
    summaries = []
    for period, g in periods(diagnostics):
        for scope, a in [('all_races', g), ('third', g[g.is_third]), ('other', g[~g.is_third])]:
            summaries.append(dict(period=period, scope=scope, n=len(a), gains=int(a.gain_vs_prior.sum()),
                losses=int(a.loss_vs_prior.sum()), net=int(a.gain_vs_prior.sum() - a.loss_vs_prior.sum()),
                both_original_miss_rescued=int((a.both_original_miss & a.axis_top3.eq(1)).sum())))
    pd.DataFrame(summaries).to_csv(OUT / 'period_decomposition.csv', index=False)
    rows, conditions = [], []
    for period, a in periods(d):
        for group, g in [('all', a)] + list(a.groupby('group')):
            for col in features + ['distance_change']:
                values = []
                for side in ['third', 'prior', 'difference']:
                    x = g[side + '_' + col].dropna()
                    values += [int(len(x)), None if x.empty else float(x.mean()), None if x.empty else float(x.median())]
                rows.append(dict(period=period, group=group, feature=col, races=len(g),
                    **dict(zip(['third_n', 'third_mean', 'third_median', 'prior_n', 'prior_mean', 'prior_median',
                                'paired_n', 'difference_mean', 'difference_median'], values))))
        for col in ['meet', 'grade_band', 'distance_band', 'field_band', 'history_band', 'g1_missing']:
            for value, g in a.groupby(col, dropna=False):
                conditions.append(dict(period=period, condition=col, value=str(value), n=len(g),
                    gains=int(g.gain_vs_prior.sum()), losses=int(g.loss_vs_prior.sum()),
                    net=int(g.gain_vs_prior.sum() - g.loss_vs_prior.sum()), third_hit_rate=float(g.axis_top3.mean())))
    pd.DataFrame(rows).to_csv(OUT / 'feature_comparisons.csv', index=False)
    pd.DataFrame(conditions).to_csv(OUT / 'conditions.csv', index=False)
    decompose(d)
    attribute(d)
    sensitivity(source)
    print(pd.DataFrame(summaries).to_string(index=False), flush=True)


def decompose(d):
    rows, cells = [], []
    z = d[d.race_date.dt.strftime('%m-%d').le('09-20')].copy()
    z['net'] = z.gain_vs_prior.astype(int) - z.loss_vs_prior.astype(int)
    for columns in [['meet'], ['distance_band'], ['grade_band'], ['meet', 'distance_band', 'grade_band']]:
        name = '+'.join(columns)
        a = z[z.year.eq(2025)].groupby(columns).net.agg(['size', 'mean'])
        b = z[z.year.eq(2026)].groupby(columns).net.agg(['size', 'mean'])
        shared = a.join(b, how='inner', lsuffix='_25', rsuffix='_26')
        p25, p26 = shared.size_25 / shared.size_25.sum(), shared.size_26 / shared.size_26.sum()
        r25, r26 = shared.mean_25, shared.mean_26
        composition = float(((p26 - p25) * (r26 + r25) / 2).sum())
        within = float(((r26 - r25) * (p26 + p25) / 2).sum())
        total = float((p26 * r26).sum() - (p25 * r25).sum())
        assert np.isclose(composition + within, total)
        rows.append(dict(strata=name, cells=len(shared), included25=int(shared.size_25.sum()),
            included26=int(shared.size_26.sum()), excluded25=int((z.year.eq(2025)).sum()-shared.size_25.sum()),
            excluded26=int((z.year.eq(2026)).sum()-shared.size_26.sum()),
            netrate25=float((p25*r25).sum()), netrate26=float((p26*r26).sum()),
            change=total, composition=composition, within=within))
        for key, row in shared.iterrows():
            cells.append(dict(strata=name, cell=str(key), n25=int(row.size_25), n26=int(row.size_26),
                 rate25=float(row.mean_25), rate26=float(row.mean_26), sparse=min(row.size_25,row.size_26)<5))
    pd.DataFrame(rows).to_csv(OUT / 'composition_decomposition.csv', index=False)
    pd.DataFrame(cells).to_csv(OUT / 'composition_cells.csv', index=False)


def attribute(d):
    frame = pd.read_parquet(P / 'candidate_frame.parquet')
    stored = pd.read_parquet(P / 'candidate_predictions.parquet')
    selections = pd.read_parquet(P / 'selected_axes.parquet')
    feature_rows, bundle_rows, decision_rows, references = [], [], [], []
    for year in [2025, 2026]:
        g = d[d.year.eq(year)]
        a = frame.set_index(KEY).loc[pd.MultiIndex.from_frame(g[KEY])].reset_index()
        folder = P / 'models' / f'gain_logit_{year}'
        pre = json.loads((folder / 'preprocess.json').read_text())
        w = json.loads((folder / 'model.json').read_text())
        x, names = E.S.transform(a, pre)
        train = frame[frame.year.between(2020, year-1)]
        tx, _ = E.S.transform(train, pre)
        reference = np.average(tx, axis=0, weights=train.case_weight)
        beta = np.array(w['coef'])[2] - np.array(w['coef'])[0]
        intercept = np.array(w['intercept'])[2] - np.array(w['intercept'])[0]
        baseline = float(reference @ beta + intercept)
        contribution = (x-reference) * beta
        probability = softmax(x @ np.array(w['coef']).T + np.array(w['intercept']), axis=1)
        observed = stored[stored.model_kind.eq('gain_logit')].set_index(KEY).loc[pd.MultiIndex.from_frame(g[KEY])]
        np.testing.assert_allclose(probability, observed[['p_loss','p_neutral','p_gain']], atol=1e-12, rtol=0)
        margin = np.log(probability[:,2]/probability[:,0])
        np.testing.assert_allclose(baseline+contribution.sum(axis=1), margin, atol=1e-10, rtol=0)
        references.append(dict(year=year, reference_log_odds=baseline, training_races=train.race_key.nunique(),
                               definition='encoded means weighted so every prior race has total weight1'))
        buckets = [bucket(n) for n in names]
        index = stored[stored.model_kind.eq('gain_logit') & stored.year.eq(year)].set_index(['race_key','horse_id'])
        two = selections[selections.variant.eq('gain_logit_two') & selections.year.eq(year)].set_index('race_key')
        for i, row in enumerate(g.itertuples()):
            for j, name in enumerate(names):
                feature_rows.append(dict(race_key=row.race_key, year=year, group=row.group, feature=name,
                     bundle=buckets[j], encoded=float(x[i,j]), reference=float(reference[j]), coefficient=float(beta[j]),
                     contribution=float(contribution[i,j])))
            for name in sorted(set(buckets)):
                val = float(contribution[i,np.array(buckets)==name].sum())
                bundle_rows.append(dict(race_key=row.race_key, year=year, group=row.group, bundle=name, contribution=val))
            same = stored[stored.model_kind.eq('gain_logit') & stored.race_key.eq(row.race_key)]
            prior_score = 0.0 if row.prior_selected_horse_id==row.old122_horse_id else float(index.loc[(row.race_key,row.prior_selected_horse_id),'expected_gain'])
            two_score = float(two.loc[row.race_key,'expected_gain'])
            decision_rows.append(dict(race_key=row.race_key, year=year, group=row.group,
                selected_gain=float(probability[i,2]-probability[i,0]), prior_gain=prior_score, two_gain=two_score,
                advantage_over_two=float(probability[i,2]-probability[i,0]-two_score),
                p_loss=float(probability[i,0]),p_neutral=float(probability[i,1]),p_gain=float(probability[i,2]),
                selected_log_odds=float(margin[i]),reference_log_odds=baseline,
                best_other_gain=max(0.0,float(same[same.horse_id.ne(row.axis_horse_id)].expected_gain.max()))))
    pd.DataFrame(feature_rows).to_parquet(OUT / 'feature_contributions.parquet', index=False)
    bundles = pd.DataFrame(bundle_rows)
    bundles.to_csv(OUT / 'bundle_contributions.csv', index=False)
    pd.DataFrame(decision_rows).to_csv(OUT / 'decision_scores.csv', index=False)
    save(OUT / 'decomposition_contract.json',dict(references=references,unit='log(Pgain/Ploss)',
         comparison='selected third versus frozen122 reference only',
         selection_rule='global max(Pgain-Ploss), not max log ratio',causal=False))
    merged = bundles.merge(d[['race_key','race_date']],on='race_key',validate='many_to_one')
    out=[]
    for period,g in periods(merged):
        for (group,bundle),a in g.groupby(['group','bundle']):
            out.append(dict(period=period,group=group,bundle=bundle,n=len(a),mean=float(a.contribution.mean()),median=float(a.contribution.median())))
    pd.DataFrame(out).to_csv(OUT / 'bundle_comparisons.csv',index=False)


def sensitivity(source):
    d = pd.read_parquet(P / 'candidate_frame.parquet')
    test = d[d.year.eq(2026)].drop(columns=['candidate_outcome','ref_outcome','switch_outcome'])
    probability = E.predict(test, P / 'models/gain_logit_2025', 'gain_logit')
    q = test[KEY+['race_date','year','is_third','candidate_model_rank_122']].copy()
    q['p_loss'],q['p_neutral'],q['p_gain'] = probability.T
    q['expected_gain']=probability[:,2]-probability[:,0]
    q.to_parquet(OUT/'frozen2025_on2026_predictions.parquet',index=False)
    chosen = E.choose(q,source[source.year.eq(2026)].drop(columns='outcome'),'all')
    chosen.to_parquet(OUT/'frozen2025_on2026_axes.parquet',index=False)
    base=source[source.variant.eq('combined122')&source.year.eq(2026)]
    truth={rid:g.sort_values('model_rank')for rid,g in base.groupby('race_key')}
    rows=[]
    for row in chosen.itertuples():
        g=truth[row.race_key]
        seq=[row.horse_id]+[x for x in g.horse_id if x!=row.horse_id]
        outcomes=g.set_index('horse_id').outcome
        axis=int(outcomes.loc[row.horse_id]);winners=set(g.loc[g.outcome.between(1,2),'horse_id'])
        rows.append(dict(race_key=row.race_key,year=2026,race_date=row.race_date,axis_horse_id=row.horse_id,
             is_third=row.is_third,axis_top3=int(1<=axis<=3),axis_top2=int(1<=axis<=2),
             quinella_one=int(winners==set(seq[:2])),axis_next3=int(row.horse_id in winners and winners<=set(seq[:4]))))
    result=pd.DataFrame(rows)
    actual=pd.read_parquet(P/'race_metrics.parquet')
    actual=actual[actual.year.eq(2026)&actual.variant.isin(['joint_logit','gain_logit_all'])]
    prior=actual[actual.variant.eq('joint_logit')].set_index('race_key').axis_top3
    result['prior_hit']=result.race_key.map(prior)
    result['gain']=result.axis_top3.eq(1)&result.prior_hit.eq(0)
    result['loss']=result.axis_top3.eq(0)&result.prior_hit.eq(1)
    result.to_csv(OUT/'frozen2025_on2026_race_metrics.csv',index=False)
    summary=[]
    for variant,g in [('frozen2025_on2026',result)]+list(actual.groupby('variant')):
        summary.append(dict(variant=variant,n=len(g),**{k:float(g[k].mean())for k in ['axis_top3','axis_top2','quinella_one','axis_next3']}))
    pd.DataFrame(summary).to_csv(OUT/'model_update_sensitivity.csv',index=False)


if __name__=='__main__':
    with threadpool_limits(limits=1):
        freeze();check();prepare();check()
