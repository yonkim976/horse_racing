"""Read-only sex-group comparisons; fixed effects and horse/date clustered inference."""
from pathlib import Path
import gzip
import hashlib
import json
import re
import sys

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
SEASON = HERE.parent / '20261007_seasonal_same_moisture'
AUDIT = HERE.parent / '20261002_track_source_reconciliation/results/api_study_population.parquet'
HISTORY = HERE.parent / '20261002_gate_lateral_bias/outputs/runners.parquet'
SEXES = ['암', '수', '거']
PAIRS = [('암', '수'), ('거', '수'), ('암', '거')]
CORE = ['early', 'middle1', 'middle2', 'late']
PARTS = CORE + ['finish', 'last600', 'last400', 'early_relative_pct', 'late_relative_pct']
BASE = ['year', 'month', 'age', 'moisture']
LOAD = ['weight', 'body_weight', 'weight_squared', 'body_squared']
FORM = ['rating', 'rating_squared', 'prior_finish', 'prior_top3', 'prior_early', 'log_starts', 'log_gap']
RESULTS = []


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write_json(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def source_items(p):
    p = p.resolve()
    assert p.is_relative_to(ROOT / 'thoroughbred/research/20260929_calendar_api_v1/raw')
    with gzip.open(p, 'rt', encoding='utf-8') as f:
        x = json.load(f)['response']['body']['items']['item']
    return x if isinstance(x, list) else [x]


def prepare():
    d = pd.read_parquet(SEASON / 'outputs/population.parquet')
    ss = json.loads((SEASON / 'outputs/summary.json').read_text())
    inputs = {str((SEASON / 'outputs/population.parquet').relative_to(ROOT)): sha(SEASON / 'outputs/population.parquet')}
    pointers = []
    for name, expected in ss['inputs'].items():
        p = ROOT / name
        inputs[name] = sha(p)
        assert inputs[name] == expected
        x = pd.read_parquet(p)
        if 'population' in x:
            x = x[x.population.eq('실전1200')]
        pointers.append(x[['row_key', 'source_file', 'source_item_index']])
    ptr = pd.concat(pointers, ignore_index=True)
    assert not ptr.row_key.duplicated().any()
    d = d.merge(ptr, on='row_key', validate='one_to_one')
    d['source_item_index'] = pd.to_numeric(d.source_item_index).astype(int)
    assert len(d) == 151074 and d.source_key.nunique() == 13928
    d['horse_id'] = d.row_key.str.rsplit(':', n=1).str[-1]
    assert d.horse_id.str.fullmatch(r'\d{7}').all()
    a = pd.read_parquet(AUDIT)
    inputs[str(AUDIT.relative_to(ROOT))] = sha(AUDIT)
    a = a[a.meet.isin([1, 3]) & a.distance_m.isin(d.distance_m.unique())].copy()
    a['meet'] = a.meet.map({1: '서울', 3: '부산'})
    a['date'] = pd.to_datetime(a.date)
    a['source_key'] = a.meet + ':' + a.date.dt.strftime('%Y%m%d') + ':' + a.race_no.astype(str)
    a['row_key'] = a.source_key + ':' + a.horse_id
    assert not a.row_key.duplicated().any()
    # API audit cohort consists of validated keys; never treat arbitrary API-only rows as events.
    raw_records, sex_rosters = [], {}
    for file, g in a.groupby('source_file'):
        p = ROOT / file
        inputs[file] = sha(p)
        items = source_items(p)
        for r in g.itertuples():
            item = items[int(r.source_item_index)]
            assert str(item['hrNo']).zfill(7) == r.horse_id
            assert int(item['rcDate']) == int(r.date.strftime('%Y%m%d'))
            assert int(item['rcNo']) == r.race_no and int(item['rcDist']) == r.distance_m
            assert int(item['ord']) == r.rank
            # Five prior quality failures have a preserved null normalized time.
            assert pd.isna(r.finish) or np.isclose(float(item['rcTime']) * 1000, r.finish)
            body = re.fullmatch(r'\s*(\d+)(?:\([^)]*\))?\s*', str(item.get('wgHr', '')))
            body = float(body[1]) if body and float(body[1]) > 0 else np.nan
            raw_records.append(dict(row_key=r.row_key, sex_raw=str(item['sex']),
                                    sex_condition=str(item.get('sexCond', '')), body_weight=body,
                                    age_raw=float(item['age']), weight_raw=float(item['wgBudam']),
                                    rating_raw=float(item.get('rating', 0)), rank_raw=int(item['ord'])))
        # Entire original rosters for selected official race keys, including nonfinishers and scratches.
        wanted = set(g.source_key)
        for item in items:
            key = f"{g.meet.iloc[0]}:{int(item['rcDate'])}:{int(item['rcNo'])}"
            if key in wanted:
                sex_rosters.setdefault(key, []).append((str(item['sex']), int(item['ord'])))
    raw = pd.DataFrame(raw_records)
    a = a.merge(raw, on='row_key', validate='one_to_one')
    a['selected'] = a.row_key.isin(d.row_key)
    roster = {}
    for key, entries in sex_rosters.items():
        starters = [(s, k) for s, k in entries if k not in [93, 94, 95]]
        roster[key] = dict(field_size=len(starters), original_sex_count=len(set(s for s, k in starters)),
                           original_all_female=bool(starters) and all(s == '암' for s, k in starters),
                           original_nonstandard=any(not (1 <= k <= 20) for s, k in starters))
    rr = pd.DataFrame.from_dict(roster, orient='index').rename_axis('source_key').reset_index()
    a = a.merge(rr, on='source_key', validate='many_to_one')
    parent = pd.read_parquet(HISTORY)
    inputs[str(HISTORY.relative_to(ROOT))] = sha(HISTORY)
    parent['meet'] = parent.meet.map({1: '서울', 3: '부산'})
    parent['date'] = pd.to_datetime(parent.date)
    parent['row_key'] = parent.meet + ':' + parent.date.dt.strftime('%Y%m%d') + ':' + parent.race_no.astype(str) + ':' + parent.horse_id
    a['selection_reason'] = np.select([a.selected, ~a.row_key.isin(parent.row_key)],
                                     ['retained', 'outside_parent_normal_full_race'], default='section_quality_or_distance_parent')
    cols = ['row_key', 'sex_raw', 'sex_condition', 'body_weight', 'age_raw', 'weight_raw', 'rating_raw', 'rank_raw',
            'field_size', 'original_sex_count', 'original_all_female', 'original_nonstandard']
    d = d.merge(a[cols], on='row_key', validate='one_to_one')
    assert d.sex.eq(d.sex_raw).all() and set(d.sex) == set(SEXES)
    np.testing.assert_allclose(d.age, d.age_raw)
    np.testing.assert_allclose(d.weight, d.weight_raw)
    assert d.age.notna().all() and d.body_weight.notna().all()
    assert d.body_weight.between(200, 700).all()
    assert not d.row_key.duplicated().any()
    assert d.groupby('source_key')[['meet', 'distance_m', 'date', 'grade', 'moisture', 'sex_condition']].nunique().eq(1).all().all()
    d['win'] = d.rank_raw.eq(1).astype(float)
    d['top3'] = d.rank_raw.le(3).astype(float)
    d['rank_pct'] = (d.rank_raw - 1) / (d.field_size - 1)
    d['complete_retained_race'] = d.groupby('source_key').row_key.transform('size').eq(d.field_size)
    d['mixed_actual'] = d.original_sex_count.ge(2)
    d['age_group'] = d.age.map(lambda v: str(int(v)) if v < 5 else '5+')
    d['day_key'] = d.meet + ':' + d.date.dt.strftime('%Y%m%d')
    for col in ['weight', 'body_weight', 'rating']:
        name = {'weight': 'weight_squared', 'body_weight': 'body_squared', 'rating': 'rating_squared'}[col]
        d[name] = d[col] ** 2
    d['early_relative_pct'] = 100 * 200 * d.finish / (d.distance_m * d.early)
    d['late_relative_pct'] = 100 * 200 * d.finish / (d.distance_m * d.late)
    # Fixed common recent reference, pooled across sexes, not separate normalization.
    refs = {k: np.sort(g.finish.to_numpy()) for k, g in d[d.year.ge(2024)].groupby(['meet', 'distance_m', 'grade', 'band'])}
    score = np.full(len(d), np.nan)
    ref_n = np.zeros(len(d), dtype=int)
    for key, ids in d.groupby(['meet', 'distance_m', 'grade', 'band']).groups.items():
        if key not in refs:
            continue
        arr = refs[key]; v = d.loc[ids, 'finish'].to_numpy()
        score[ids] = 100 * (len(arr) - (np.searchsorted(arr, v, 'left') + np.searchsorted(arr, v, 'right')) / 2) / len(arr)
        ref_n[ids] = len(arr)
    d['common_recent_score'] = score
    d['common_reference_n'] = ref_n
    d.to_parquet(OUT / 'population.parquet', index=False)
    a[['row_key','source_key','meet','distance_m','date','horse_id','sex_raw','sex_condition','rank','finish','field_size','selected','selection_reason','body_weight','moisture','grade_normalized']].rename(columns={'finish':'finish_ms'}).to_parquet(OUT / 'selection_ledger.parquet', index=False)
    selections = a.groupby(['meet','distance_m','sex_raw','selection_reason']).agg(n=('row_key','size')).reset_index()
    totals = a.groupby(['meet','distance_m','sex_raw']).size().rename('source_n').reset_index()
    selections = selections.merge(totals, on=['meet','distance_m','sex_raw'])
    selections['share'] = selections.n / selections.source_n
    selections.to_csv(OUT / 'selection_by_sex.csv', index=False)
    a['day_key'] = a.meet + ':' + a.date.dt.strftime('%Y%m%d')
    a['sex'] = a.sex_raw
    a['finish'] /= 1000
    a['year'] = a.date.dt.year
    a['month'] = a.date.dt.month
    a['age'] = a.age_raw
    a['grade'] = a.grade_normalized
    a['win'] = a['rank'].eq(1).astype(float)
    a['top3'] = a['rank'].le(3).astype(float)
    # Temporal sex paths: observed records, not surgery dates or treatment effects.
    paths = []
    for hid, g in a.sort_values('date').groupby('horse_id'):
        changes = g.loc[g.sex.ne(g.sex.shift())]
        seq = changes.sex.tolist()
        if len(seq) > 1:
            paths.append(dict(horse_id=hid, sequence='>'.join(seq), first_date=str(g.date.min().date()),
                              last_date=str(g.date.max().date()), observed_rows=len(g),
                              reversal=any(s != '거' for s in seq[seq.index('거')+1:]) if '거' in seq else False,
                              female_switch=('암' in seq)))
    pd.DataFrame(paths).to_csv(OUT / 'observed_sex_transitions.csv', index=False)
    incoherent = set(x['horse_id'] for x in paths if x['reversal'] or x['female_switch'])
    write_json(OUT / 'source_audit.json', dict(inputs=inputs, input_rows=len(d), races=d.source_key.nunique(),
        horses=d.horse_id.nunique(), source_audit_rows=len(a), source_sex_counts=a.sex.value_counts().to_dict(),
        sex_counts=d.sex.value_counts().to_dict(), source_start={k:str(v.date()) for k,v in d.groupby('meet').date.min().items()},
        source_end={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},
        historical_missing_by_sex=d.groupby('sex')[['rating','prior_finish','prior_top3','prior_early','log_gap','body_weight']].agg(lambda x: int(x.isna().sum())).to_dict(),
        raw_identity_sex_checks=len(d), source_raw_rows_checked=len(a), raw_files=len(a.source_file.unique()),
        raw_sex_conditions=d.sex_condition.value_counts().to_dict(), complete_retained_rows=int(d.complete_retained_race.sum()),
        observed_sex_transition_horses=len(paths), transition_audit_population_rows=len(a),
        final_population_sex_transition_horses=int(d.groupby('horse_id').sex.nunique().gt(1).sum()),
        incoherent_transition_horses=sorted(incoherent),
        seasonal_reuse='identical final row keys/measurements; historical API sex independently rechecked; IDs reconstructed and checked against raw hrNo',
        additional_api_requests=0))
    return d, a, incoherent


def count_tables(d):
    for name, cols in [('venue_distance_sex',['meet','distance_m','sex']),
                       ('age_grade_counts',['meet','distance_m','sex','age','grade']),
                       ('restriction_counts',['meet','sex_condition','mixed_actual','sex']),
                       ('year_counts',['meet','year','sex'])]:
        tab = d.groupby(cols).agg(n=('row_key','size'),races=('source_key','nunique'),horses=('horse_id','nunique'),days=('date','nunique'),
            first_date=('date','min'),last_date=('date','max'),body_weight=('body_weight','mean'),carried_weight=('weight','mean'),
            win_rate=('win','mean'),top3_rate=('top3','mean'),rank_pct=('rank_pct','mean')).reset_index()
        tab.to_csv(OUT / f'{name}.csv', index=False)
    rows = []
    for scope, keys in [('distance',['meet','distance_m','sex']),('age',['meet','distance_m','age_group','sex']),('grade',['meet','distance_m','grade','sex'])]:
        for key, g in d.groupby(keys):
            meta = dict(zip(keys,key)) | dict(scope=scope, races=g.source_key.nunique(),horses=g.horse_id.nunique(),days=g.date.nunique())
            for col in PARTS + ['common_recent_score']:
                x = g[col].dropna()
                if len(x):
                    q=x.quantile([.1,.2,.5,.8,.9]); lo=x.le(q.loc[.2]); hi=x.ge(q.loc[.8])
                    if col in ['common_recent_score','early_relative_pct','late_relative_pct']:
                        lo,hi=x.ge(q.loc[.8]),x.le(q.loc[.2])
                    fq=g.finish.quantile([.2,.8])
                    ff=g.loc[g.finish.le(fq.loc[.2]),col].dropna()
                    fs=g.loc[g.finish.ge(fq.loc[.8]),col].dropna()
                    rows.append(meta | dict(part=col,n=len(x),mean=x.mean(),p10=q.loc[.1],p20=q.loc[.2],median=q.loc[.5],p80=q.loc[.8],p90=q.loc[.9],
                        fast20_n=int(lo.sum()),slow20_n=int(hi.sum()),fast20_mean=x[lo].mean(),slow20_mean=x[hi].mean(),
                        finish_fast20_n=len(ff),finish_slow20_n=len(fs),
                        finish_fast20_part_mean=ff.mean(),finish_slow20_part_mean=fs.mean()))
    pd.DataFrame(rows).to_csv(OUT / 'observed_distributions.csv',index=False)


def codes(frame, keys):
    return pd.factorize(pd.MultiIndex.from_frame(frame[keys]),sort=True)[0]


def demean(a, groups):
    a = np.asarray(a, dtype=float)
    count = np.bincount(groups)
    if a.ndim == 1:
        return a - (np.bincount(groups,weights=a) / count)[groups]
    means=np.column_stack([np.bincount(groups,weights=v)/count for v in a.T])
    return a-means[groups]


def controls(g, names):
    arr=[]; labels=[]
    for name in names:
        v=g[name].to_numpy(float); miss=~np.isfinite(v)
        if miss.all():
            continue
        v=np.where(miss,np.median(v[~miss]),v)
        sd=v.std()
        if sd > 1e-10:
            arr.append((v-v.mean())/sd);labels.append(name)
        if miss.any() and not miss.all():
            arr.append(miss.astype(float));labels.append(name+'_missing')
    return (np.column_stack(arr) if arr else np.empty((len(g),0))),labels


def cluster_variance(influence, group, correction):
    c=pd.factorize(group)[0]; m=c.max()+1
    sums=np.bincount(c,weights=influence)
    return float(sums@sums * correction * (m/(m-1) if m>1 else 1)),m


def solve(g, fe, names, outcomes, era=False):
    group=codes(g,fe) if fe else np.zeros(len(g),int)
    sx=g.is_target.to_numpy(float)
    c, labels=controls(g,names)
    if era:
        er=g.recent.to_numpy(float)
        x=np.column_stack([sx,sx*er,c*(1-er[:,None]),c*er[:,None]])
        labels=['target','target_x_recent']+[f'old:{x}' for x in labels]+[f'recent:{x}' for x in labels]
    else:
        x=np.column_stack([sx,c]);labels=['target']+labels
    y=g[outcomes].to_numpy(float)
    xd,yd=demean(x,group),demean(y,group)
    gram=xd.T@xd; inv=np.linalg.pinv(gram,rcond=1e-12)
    beta=inv@xd.T@yd
    residual=yd-xd@beta
    rank=np.linalg.matrix_rank(xd,tol=1e-8)
    projection=inv@gram
    dof=len(g)-len(np.unique(group))-rank
    corr=(len(g)-1)/max(dof,1)
    estimable=np.allclose(projection[0],np.eye(len(labels))[0],atol=1e-7)
    if era:
        estimable &= np.allclose(projection[1],np.eye(len(labels))[1],atol=1e-7)
    results=[]
    vectors=[('difference',np.eye(len(labels))[0])]
    if era:
        vectors=[('old_gap',np.eye(len(labels))[0]),('gap_change',np.eye(len(labels))[1]),('recent_gap',np.eye(len(labels))[0]+np.eye(len(labels))[1])]
    for j,col in enumerate(outcomes):
        for kind,v in vectors:
            influence=(xd@(inv@v))*residual[:,j]
            vh,nh=cluster_variance(influence,g.horse_id,corr)
            vd,nd=cluster_variance(influence,g.day_key,corr)
            vi,ni=cluster_variance(influence,g.horse_id+':'+g.day_key,corr)
            vt=vh+vd-vi
            se=np.sqrt(max(vt,vh,vd,0))
            diff=float(v@beta[:,j]) if estimable else np.nan
            p=2*student_t.sf(abs(diff)/se,min(nh,nd)-1) if se>0 and estimable else np.nan
            critical=student_t.ppf(.975,min(nh,nd)-1) if min(nh,nd)>1 else np.nan
            results.append(dict(part=col,contrast_kind=kind,difference=diff,se=se,
                lower_unrestricted=diff-critical*se,upper_unrestricted=diff+critical*se,p=p,
                horse_variance=vh,date_variance=vd,intersection_variance=vi,two_way_variance=vt,
                horse_clusters=nh,date_clusters=nd,estimable=bool(estimable),matrix_rank=rank,
                design_columns=len(labels),fe_groups=int(group.max()+1),residual_df=dof))
    return results,labels


def pair_sample(g,target,reference,fe):
    q=g[g.sex.isin([target,reference])].copy()
    q['is_target']=q.sex.eq(target).astype(float)
    if fe and len(q):
        q=q[q.groupby(fe,dropna=False).sex.transform('nunique').eq(2)].copy()
    return q


def run(g,target,reference,fe,names,outcomes,metadata,era=False):
    input_pair=g[g.sex.isin([target,reference])]
    q=pair_sample(g,target,reference,fe)
    if era and len(q):
        # Keep only covariate cells seen in both periods, then reapply within-year sex overlap.
        cross=[x for x in fe if x!='year']
        q=q[q.groupby(cross).recent.transform('nunique').eq(2)].copy()
        q=pair_sample(q,target,reference,fe)
    meta=metadata|dict(target=target,reference=reference,input_pair_n=len(input_pair),common_n=len(q),
                       excluded_fraction=1-len(q)/len(input_pair) if len(input_pair) else np.nan,
                       target_n=int(q.sex.eq(target).sum()),reference_n=int(q.sex.eq(reference).sum()),
                       common_races=q.source_key.nunique(),common_horses=q.horse_id.nunique(),common_days=q.day_key.nunique())
    support=bool(len(q)) and min(q.sex.value_counts().reindex([target,reference],fill_value=0))>=100
    for sex in [target,reference]:
        h=q[q.sex.eq(sex)]
        support &= h.horse_id.nunique()>=30 and h.day_key.nunique()>=20
    if fe and len(q):
        support &= len(q[fe].drop_duplicates())>=20
    if era:
        support &= all((q[q.recent.eq(e)].sex.value_counts().reindex([target,reference],fill_value=0)>=100).all() and q[q.recent.eq(e)].day_key.nunique()>=20 for e in [0,1])
    available=[x for x in outcomes if len(q) and q[x].notna().all()]
    if len(q)>3 and available:
        fits,labels=solve(q,fe,names,available,era=era)
        for r in fits:
            ok=support and r['estimable'] and r['residual_df']>0
            mult=100 if r['part'] in ['top3','win','rank_pct'] else 1
            for field in ['difference','se','lower_unrestricted','upper_unrestricted']:
                r[field]*=mult
            r['lower']=r['lower_unrestricted'] if ok else np.nan
            r['upper']=r['upper_unrestricted'] if ok else np.nan
            r['supported']=ok
            r['unit']='percentage_points' if r['part'] in ['top3','win','rank_pct','early_relative_pct','late_relative_pct'] else ('score_points' if r['part']=='common_recent_score' else 'seconds')
            r['controls']='|'.join(labels)
            RESULTS.append(meta|r)
    else:
        for part in outcomes:
            RESULTS.append(meta|dict(part=part,contrast_kind='gap_change' if era else 'difference',difference=np.nan,lower=np.nan,upper=np.nan,supported=False,estimable=False,unit='seconds'))
    return q


def main_models(d):
    # Four question levels. No prior sex-adjusted residuals are used.
    for (meet,dist),g in d.groupby(['meet','distance_m']):
        print('distance',meet,dist,len(g),flush=True)
        for target,reference in PAIRS:
            meta=dict(scope='distance',meet=meet,distance_m=int(dist),subgroup='all',window='all')
            for spec,fe,nums in [('raw',[],[]),('context',BASE,[]),('grade',BASE+['grade'],[]),
                                 ('load_body',BASE+['grade'],LOAD),('full',BASE+['grade'],LOAD+FORM)]:
                q=run(g,target,reference,fe,nums,[x for x in PARTS if x!='last400'],meta|dict(specification=spec))
                if spec=='grade':
                    run(q,target,reference,BASE,[],['finish'],meta|dict(specification='context_on_grade_common'))
                    run(q,target,reference,[],[],['finish'],meta|dict(specification='raw_on_grade_common'))
                if spec=='full' and dist in [1200,1400,1800]:
                    cc=q.dropna(subset=LOAD+FORM)
                    run(cc,target,reference,BASE+['grade'],LOAD+FORM,['finish'],meta|dict(specification='full_completecase'))
            if meet=='부산':
                z=g[g.last400.notna()]
                run(z,target,reference,BASE+['grade'],LOAD+FORM,['last400'],meta|dict(specification='full_observed400'))
            # Common pooled recent score; cells without recent reference remain missing.
            run(g[g.common_recent_score.notna()],target,reference,BASE+['grade'],[],['common_recent_score'],meta|dict(specification='common_recent_score'))
            # Within-race overlap-weighted comparison among complete original rosters.
            mixed=g[g.mixed_actual & g.complete_retained_race & ~g.original_nonstandard]
            for spec,nums in [('race',[]),('race_age',['age','age_squared']),('race_load_body',['age','age_squared']+LOAD),('race_full',['age','age_squared']+LOAD+FORM)]:
                run(mixed,target,reference,['source_key'],nums,['finish','top3','win','rank_pct'],meta|dict(scope='same_race',specification=spec))
    # Targeted pooled-within-distance age and grade panels: no explosion of all cross-products.
    for meet,venue in d.groupby('meet'):
        for scope,key in [('age','age_group'),('grade','grade')]:
            for level,g in venue.groupby(key):
                if len(g)<100:
                    continue
                for target,reference in PAIRS:
                    for spec,nums in [('grade',[]),('full',LOAD+FORM)]:
                        run(g,target,reference,['distance_m']+BASE+['grade'],nums,['finish'],dict(scope=scope,meet=meet,distance_m=0,subgroup=str(level),window='all',specification=spec))


def eras(d):
    for window,old,recent,months in [('jan_aug',list(range(2018,2024)),[2024,2025,2026],list(range(1,9))),
                                     ('complete_years',list(range(2018,2024)),[2024,2025],list(range(1,13))),
                                     ('near_complete',[2021,2022,2023],[2024,2025],list(range(1,13)))]:
        v=d[d.year.isin(old+recent)&d.month.isin(months)].copy()
        v['recent']=v.year.isin(recent).astype(float)
        for (meet,dist),g in v.groupby(['meet','distance_m']):
            for target,reference in PAIRS:
                for spec,nums in [('grade',[]),('full',LOAD+FORM)]:
                    run(g,target,reference,BASE+['grade'],nums,['finish'],dict(scope='era',meet=meet,distance_m=int(dist),subgroup='all',window=window,specification=spec),era=True)


def sensitivity(d,a,incoherent):
    for (meet,dist),g in a[a.sex.isin(SEXES) & a.finish.notna()].groupby(['meet','distance_m']):
        for target,reference in PAIRS:
            run(g,target,reference,BASE+['grade'],[],['finish'],dict(scope='sensitivity',meet=meet,distance_m=int(dist),subgroup='all',window='all',specification='broader_positive_finish'))
    for (meet,dist),g in d.groupby(['meet','distance_m']):
        for target,reference in PAIRS:
            for name,sub in [('unrestricted_sex_condition',g[~g.sex_condition.eq('암')]),
                             ('coherent_sex_paths',g[~g.horse_id.isin(incoherent)]),
                             ('history_observed',g[g.prior_finish.notna()])]:
                run(sub,target,reference,BASE+['grade'],LOAD+FORM,['finish'],dict(scope='sensitivity',meet=meet,distance_m=int(dist),subgroup='all',window='all',specification=name))
    # Balanced horse contribution by one reproducible middle observation per horse/sex/distance.
    # Different population, explicitly separate from primary repeat-runner analysis.
    z=d.sort_values(['date','row_key']).copy()
    z['j']=z.groupby(['meet','distance_m','horse_id','sex']).cumcount()
    z['mid']=z.groupby(['meet','distance_m','horse_id','sex']).row_key.transform('size')//2
    z=z[z.j.eq(z.mid)]
    for (meet,dist),g in z.groupby(['meet','distance_m']):
        for target,reference in PAIRS:
            run(g,target,reference,BASE+['grade'],[],['finish'],dict(scope='sensitivity',meet=meet,distance_m=int(dist),subgroup='all',window='all',specification='one_observation_per_horse_sex'))


def main():
    d,a,bad=prepare()
    d['age_squared']=d.age**2
    count_tables(d)
    main_models(d)
    eras(d)
    sensitivity(d,a,bad)
    results=pd.DataFrame(RESULTS)
    results['q_primary_distance_finish']=np.nan
    eligible=results.scope.eq('distance')&results.part.eq('finish')&results.specification.eq('grade')&results.supported.fillna(False)
    ids=results[eligible].sort_values('p').index.to_numpy()
    if len(ids):
        p=results.loc[ids,'p'].to_numpy();q=np.minimum.accumulate((p*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]
        results.loc[ids,'q_primary_distance_finish']=np.minimum(q,1)
    results.to_csv(OUT / 'contrasts.csv',index=False)
    write_json(OUT / 'model_definition.json',dict(version='sex_ability_gap_v1',question='observed runner group associations, not biological or causal ability',
        context_fixed_effects=BASE,grade_fixed_effects=BASE+['grade'],load_controls=LOAD,form_controls=FORM,
        primary_weight='one start one row; pairwise within-stratum OLS, harmonic overlap weights implicitly',
        uncertainty='horse + venue-date - intersection cluster score variance; max(two-way, horse-only, date-only), finite-sample FE degrees of freedom, t min(cluster counts)-1',
        support=dict(each_sex_rows=100,each_sex_horses=30,each_sex_days=20,common_strata=20),
        no_horse_fixed_effects=True,no_track_speed=True,no_prior_sex_model_residual=True,
        outcomes=PARTS,era='sex interaction with recent period; year FE retained; nuisance slopes allowed to differ by period',
        score='pooled-sex 2024+ venue/distance/grade/moisture-band empirical midrank; not moisture-adjusted or predictive; unsupported reference null',
        source_path='preserved official API4_3/raceResult_3 raw outputs; no fresh network data',
        software=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__)))
    print('saved',len(results),'contrasts',flush=True)


if __name__=='__main__':
    main()
