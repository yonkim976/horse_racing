"""Local retrospective diagnostic; no production predictions or DB writes."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import lsqr

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / 'outputs'
OBS = R / '20261008_field_pace_prediction/outputs/observations.parquet'
HIST = R / '20261009_section_style_finish_v1/outputs/history_observations.parquet'
FROZEN = [OBS, HIST, ROOT / 'config/prediction_model_registry.json',
          R / '20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
          R / '20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
PARTS = ['early', 'last600', 'late']
SHARED = ['README.md', 'ARTIFACT_SIZE_LOG.md', 'conclusions/README.md',
          'conclusions/SOURCES.md', 'conclusions/source_manifest.json']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def check():
    for key, value in json.loads((OUT / 'input_manifest.json').read_text()).items():
        assert sha(ROOT / key) == value, key


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    m = {str(p.relative_to(ROOT)): sha(p) for p in FROZEN + [HERE / 'PLAN.md', HERE / 'run.py']}
    f = OUT / 'input_manifest.json'
    if f.exists():
        assert json.loads(f.read_text()) == m
    else:
        save(f, m)
    b = OUT / 'publication_before.json'
    if not b.exists():
        paths = [R / s for s in SHARED]
        save(b, {str(p.relative_to(ROOT)): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in paths})
        snap = OUT / 'publication_before'
        snap.mkdir()
        for p in paths:
            (snap / str(p.relative_to(R)).replace('/', '__')).write_bytes(p.read_bytes())


def contexts():
    d = pd.read_parquet(OBS)
    d['race_key'] = d.source_key.str.replace('서울:', '1:', regex=False).str.replace('부산:', '3:', regex=False)
    assert not d.duplicated(['race_key', 'gate', 'horse_id']).any()
    assert (d.groupby('race_key').size() == d.groupby('race_key').field_size.first()).all()
    d['gate_fraction'] = (d.groupby('race_key').gate.rank(method='first') - 1) / (d.field_size - 1)
    d['gate_band'] = np.select([d.gate_fraction <= 1/3, d.gate_fraction >= 2/3], ['inner', 'outer'], default='middle')
    d['role_ok'] = d.group_observed & ~d.leader_conflict_race & d.role4.between(0, 3)
    # Only normal outcomes with measured sections enter time comparisons.
    for part in PARTS:
        d[part] = d[part].where(d.normal_outcome)
        val = d[part].where(d.normal_outcome)
        sums = val.groupby(d.race_key).transform('sum')
        ns = val.groupby(d.race_key).transform('count')
        eligible = val.notna() & ((ns - 1) >= 5) & (ns / d.field_size >= .8)
        d[part + '_adv'] = ((sums - val) / (ns - 1) - val).where(eligible)
    h = pd.read_parquet(HIST)[['race_key', 'program_no', 'horse_id', 'race_date', 'result_distance']]
    h = h.merge(d[['race_key', 'gate', 'horse_id'] + PARTS + [p+'_adv' for p in PARTS]],
                left_on=['race_key', 'program_no', 'horse_id'], right_on=['race_key', 'gate', 'horse_id'], how='left', validate='one_to_one')
    h = h.sort_values(['horse_id', 'race_date', 'race_key']).reset_index(drop=True)
    byhorse = h.groupby('horse_id', sort=False).indices
    fields = ['prior_early'] + ['prior_' + p + '_adv' for p in PARTS]
    vals = np.full((len(d), len(fields)), np.nan)
    counts = np.zeros((len(d), len(fields)), dtype=np.int16)
    slots = np.full((len(d), 5), -1, dtype=np.int32)
    latest = np.full(len(d), np.datetime64('NaT'), dtype='datetime64[ns]')
    hdates = h.race_date.to_numpy(dtype='datetime64[ns]')
    hdist = h.result_distance.to_numpy()
    ddates = d.date.to_numpy(dtype='datetime64[ns]')
    ddist = d.distance_m.to_numpy()
    hvalues = h[['early'] + [p+'_adv' for p in PARTS]].to_numpy(float)
    for horse, ids in d.groupby('horse_id', sort=False).indices.items():
        hx = byhorse.get(horse, np.array([], int))
        dates = hdates[hx]
        for j in ids:
            cutoff = ddates[j] - np.timedelta64(2, 'D')
            stop = np.searchsorted(dates, cutoff, side='right')
            ix = hx[max(0, stop-5):stop][::-1]
            ix = ix[hdates[ix] >= cutoff - np.timedelta64(730, 'D')]
            slots[j, :len(ix)] = ix
            if len(ix):
                latest[j] = hdates[ix[0]]
            same = ix[hdist[ix] == ddist[j]]
            for k, col in enumerate(['early'] + [p+'_adv' for p in PARTS]):
                v = hvalues[same, k]
                v = v[np.isfinite(v)]
                counts[j, k] = len(v)
                if len(v) >= 2:
                    vals[j, k] = v.mean()
    for k, name in enumerate(fields):
        d[name] = vals[:, k]
        d[name + '_n'] = counts[:, k]
    d['prior_latest'] = latest
    d['early_gain'] = (d.early_adv - d.prior_early_adv).round(10)
    d['last600_worsen'] = d.prior_last600_adv - d.last600_adv
    d['late_worsen'] = d.prior_late_adv - d.late_adv
    d['usual_band'] = np.select([d.early_gain >= .2, d.early_gain <= -.2, d.early_gain.notna()], ['faster', 'slower', 'similar'], default='unknown')
    for prefix, col in [('actual', 'early'), ('prior', 'prior_early')]:
        gap = np.full(len(d), np.nan)
        count = np.zeros(len(d), dtype=int)
        coverage = np.full(len(d), np.nan)
        for ix in d.groupby('race_key', sort=False).indices.values():
            gate = d.gate.to_numpy()[ix]
            v = d[col].to_numpy()[ix]
            for j, idx in enumerate(ix):
                inside = gate < gate[j]
                ok = inside & np.isfinite(v)
                count[idx] = ok.sum()
                coverage[idx] = ok.sum() / inside.sum() if inside.any() else np.nan
                if ok.sum() >= 3 and coverage[idx] >= .8 and np.isfinite(v[j]):
                    gap[idx] = np.round(v[ok].min() - v[j], 10)
        d[prefix+'_inner_gap'] = gap
        d[prefix+'_inner_n'] = count
        d[prefix+'_inner_coverage'] = coverage
        d[prefix+'_gap_band'] = np.select([gap >= .2, gap > 0, gap >= -.2, np.isfinite(gap)],
                                         ['faster_ge_0.2', 'faster_0_to_0.2', 'tie_or_slower_le_0.2', 'slower_gt_0.2'], default='unknown')
    h.to_parquet(OUT / 'history_context.parquet', index=False)
    np.save(OUT / 'history_slots.npy', slots)
    return d


def ci_mean(d, col, seed=20261011):
    a = d[['date', col]].dropna()
    if a.empty:
        return dict(n=0, dates=0, mean=None, lo=None, hi=None)
    g = a.groupby('date')[col].agg(['sum', 'count']).to_numpy()
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(20):
        draw = rng.integers(0, len(g), size=(100, len(g)))
        means.extend((g[draw, 0].sum(axis=1) / g[draw, 1].sum(axis=1)).tolist())
    lo, hi = np.quantile(means, [.025, .975])
    return dict(n=len(a), dates=len(g), mean=float(a[col].mean()), lo=float(lo), hi=float(hi))


def demean(a, groups):
    n = len(a)
    nh = groups[0].max()+1
    nr = groups[1].max()+1
    design = coo_matrix((np.ones(2*n), (np.tile(np.arange(n),2),
                       np.concatenate([groups[0],nh+groups[1]]))), shape=(n,nh+nr)).tocsr()
    residual = np.zeros_like(a)
    iterations = []
    for k in range(a.shape[1]):
        fit = lsqr(design,a[:,k],atol=1e-11,btol=1e-11,iter_lim=20000)
        assert fit[1] in [1,2], fit[1]
        residual[:,k] = a[:,k] - design@fit[0]
        assert np.max(np.abs(design.T@residual[:,k]))<1e-6
        iterations.append(int(fit[2]))
    graph = coo_matrix((np.ones(2*n), (np.concatenate([groups[0],nh+groups[1]]),
                       np.concatenate([nh+groups[1],groups[0]]))),shape=(nh+nr,nh+nr)).tocsr()
    components = connected_components(graph,directed=False,return_labels=False)
    return residual, iterations, int(nh+nr-components)


def fixed_effects(d, part):
    a = d[(d.gate_band != 'middle') & d.role_ok & (d.role4 == 0)].copy()
    a = a.dropna(subset=['early_gain', part+'_adv'])
    before_trim = len(a)
    while True:
        keep = (a.groupby('horse_id').horse_id.transform('size')>=2) & (a.groupby('race_key').race_key.transform('size')>=2)
        if keep.all():
            break
        a = a[keep].copy()
    a['outer'] = (a.gate_band == 'outer').astype(float)
    a['outer_gain'] = a.outer * a.early_gain
    names = ['outer', 'early_gain', 'outer_gain']
    # Race FE absorbs distance, grade, moisture, date, venue, and field-wide pace.
    codes = [pd.factorize(a[x])[0] for x in ['horse_id', 'race_key']]
    matrix, iters, fe_rank = demean(a[names + [part+'_adv']].to_numpy(float), codes)
    x, y = matrix[:, :3], -matrix[:, 3]  # positive seconds = slower finish
    bread = np.linalg.pinv(x.T @ x)
    beta = bread @ (x.T @ y)
    residual = y - x @ beta
    dates = pd.factorize(a.date)[0]
    score = np.zeros((dates.max()+1, 3))
    np.add.at(score, dates, x * residual[:, None])
    cov = bread @ (score.T @ score) @ bread
    residual_df = len(a)-fe_rank-np.linalg.matrix_rank(x)
    assert residual_df > 0
    cov *= len(score) / (len(score)-1) * (len(a)-1)/residual_df
    se = np.sqrt(np.maximum(0, np.diag(cov)))
    return dict(n=len(a), before_singleton_trim=before_trim, residual_df=int(residual_df), races=a.race_key.nunique(), horses=a.horse_id.nunique(), dates=len(score), iterations=iters,
                matrix_rank=int(np.linalg.matrix_rank(x)), coefficients=[dict(term=name, beta=float(b), se=float(s), lo=float(b-1.96*s), hi=float(b+1.96*s)) for name,b,s in zip(names,beta,se)])


def analyse(d):
    a = d[d.year.between(2024,2026)].copy()
    a.to_parquet(OUT / 'runner_diagnostics.parquet', index=False)
    groups = [('all', a)] + [(str(y), a[a.year == y]) for y in [2024,2025,2026]]
    role_rows, finish_rows, pair_rows, fe = [], [], [], []
    for scope, z in groups + [(f'{m}_{dist}', g) for (m,dist),g in a.groupby(['meet','distance_m'])]:
        for prefix in ['actual','prior']:
            b = z[(z.gate_band == 'outer') & z.role_ok & (z[prefix+'_gap_band'] != 'unknown')]
            for band, g in b.groupby(prefix+'_gap_band'):
                row = dict(scope=scope, basis=prefix, gap_band=band, n=len(g), races=g.race_key.nunique(), mean_gap=g[prefix+'_inner_gap'].mean())
                for role, name in enumerate(['front','stalk','middle','rear']):
                    row[name+'_n'] = int((g.role4 == role).sum())
                    row[name+'_rate'] = float((g.role4 == role).mean())
                role_rows.append(row)
        front = z[z.role_ok & (z.role4 == 0) & (z.gate_band != 'middle') & (z.usual_band != 'unknown')]
        for (gate, band), g in front.groupby(['gate_band','usual_band']):
            row = dict(scope=scope, gate_band=gate, usual_band=band, n=len(g), early_gain=g.early_gain.mean())
            for col in ['last600_worsen','late_worsen']:
                row.update({col+'_'+k:v for k,v in ci_mean(g,col).items()})
            finish_rows.append(row)
        # One equal-weight outer-minus-inner contrast per race with both in first group.
        for part in ['last600','late']:
            eligible = z[z.role_ok & (z.role4 == 0) & z.normal_outcome & (z.gate_band != 'middle')].dropna(subset=[part])
            t = eligible.groupby(['race_key','gate_band'])[part].mean().unstack()
            if {'outer','inner'} <= set(t.columns):
                p = (t.outer-t.inner).dropna().rename('difference').reset_index().merge(z[['race_key','date']].drop_duplicates(),on='race_key',validate='one_to_one')
                pair_rows.append(dict(scope=scope, section=part, **ci_mean(p,'difference')))
        if scope in ['all','2024','2025','2026']:
            for part in ['last600','late']:
                fe.append(dict(scope=scope, section=part, **fixed_effects(z,part)))
    pd.DataFrame(role_rows).to_csv(OUT / 'outer_roles.csv', index=False)
    pd.DataFrame(finish_rows).to_csv(OUT / 'front_finish_changes.csv', index=False)
    pd.DataFrame(pair_rows).to_csv(OUT / 'same_race_front_pairs.csv', index=False)
    save(OUT / 'fixed_effects.json', fe)
    save(OUT / 'coverage.json', dict(runners=len(a),races=a.race_key.nunique(), dates=a.date.nunique(), end=str(a.date.max().date()),
         role_valid=int(a.role_ok.sum()),outer=int((a.gate_band=='outer').sum()),
         outer_prior_comparable=int(((a.gate_band=='outer') & a.role_ok & a.prior_inner_gap.notna()).sum()),
         yearly={str(y):dict(runners=len(g),races=g.race_key.nunique()) for y,g in a.groupby('year')}))


if __name__ == '__main__':
    freeze()
    d = contexts()
    print('Contexts prepared', len(d), flush=True)
    analyse(d)
    check()
    print('Diagnostics complete', flush=True)
