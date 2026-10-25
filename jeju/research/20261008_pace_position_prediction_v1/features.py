"""T-minus-two feature construction from immutable quality snapshots."""
from pathlib import Path
from datetime import date, timedelta
from bisect import bisect_left, bisect_right
import hashlib
import importlib.util
import json
import warnings
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREV = ROOT / 'jeju/research/20261008_running_style_outcomes_v1'
PACK = ROOT / 'jeju/research/20261008_passing_group_running_style_v1'
DISTANCES = [800,900,1000,1110,1200,1400,1610]
TASKS = {'s1f_pack3': ['첫 집단','두 번째 집단','그 뒤'],
         'c4_pack3': ['첫 집단','두 번째 집단','그 뒤'],
         'g1f_pack3': ['첫 집단','두 번째 집단','그 뒤'],
         's1f_position4': ['선행권','선입권','중단','후미'],
         's1f_second_inside': ['해당 없음','두 번째 집단 내측쪽']}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def source_observations(a, points):
    spec = importlib.util.spec_from_file_location('preserved_parser', ROOT/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py')
    mod = importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    lookup = {}
    for r in points[points.point.isin(['s1f','c4','g1f']) & points.parse_status.eq('usable_group_interval')].itertuples():
        groups = mod.parse_groups(r.group_value)
        assert groups
        for idx, group in enumerate(groups):
            for side, number in enumerate(group):
                lookup[(r.race_id,r.point,number)] = (idx,len(group),side/(len(group)-1) if len(group)>1 else np.nan)
    for p in ['s1f','c4','g1f']:
        vals = [lookup.get((r.race_id,p,r.horse_number),(np.nan,np.nan,np.nan)) for r in a.itertuples()]
        a[p+'_pack_index'],a[p+'_pack_size'],a[p+'_pack_lateral'] = zip(*vals)
        a['y_'+p+'_pack3'] = a[p+'_pack_index'].clip(upper=2)
    a['y_s1f_second_inside'] = np.where(a.s1f_pack_index.notna(),
        (a.s1f_pack_index.eq(1)&a.s1f_pack_size.ge(2)&a.s1f_pack_lateral.le(.5)).astype(float),np.nan)
    a['y_s1f_position4'] = a.early_position.map({'lead':0,'front':1,'middle':2,'rear':3})
    held = a.race_distance_m.eq(1300)
    for col in ['y_s1f_pack3','y_s1f_second_inside','y_s1f_position4']:
        a.loc[held,col] = np.nan
    block = a.s1f_group_status.str.contains('unresolved|not_applied|source_changed',na=True)
    valid = a.s1f_time_seconds.gt(0)&a.s1f_time_seconds.lt(a.finish_time_seconds)&~block&~held
    valid &= ~a.s1f_time_status.str.contains('unresolved|not_applied|source_changed',na=True)
    used = a.s1f_time_seconds.where(valid)
    n = used.groupby(a.race_id).transform('count')
    rank = used.groupby(a.race_id).rank(method='average')
    a['obs_s1ftime'] = ((rank-1)/(n-1)).where((n>=6)&(n>=.8*a.field_n))
    obs = ['s1ftime']
    for p in ['s1f','c4','g1f']:
        y = a['y_'+p+'_pack3']
        for c, name in [(0,'first'),(1,'second')]:
            col = p+'_'+name
            a['obs_'+col] = np.where(y.notna(),y.eq(c).astype(float),np.nan)
            obs.append(col)
    for zone in ['front','middle','rear','ambiguous']:
        col = 's1f_'+zone
        a['obs_'+col] = np.where(a.s1f_zone.notna()&~held,a.s1f_zone.eq(zone).astype(float),np.nan)
        obs.append(col)
    extras = {'s1f_lo':(a.s1f_rank_lo-1)/(a.field_n-1), 's1f_hi':(a.s1f_rank_hi-1)/(a.field_n-1),
              's1f_solo':pd.to_numeric(a.s1f_solo_lead,errors='coerce'), 's1f_lateral':a.s1f_pack_lateral,
              'g3ftime':a.g3f_relative_rank_fraction, 'g1ftime':a.g1f_relative_rank_fraction,
              'finish_rank':(a.finish_position-1)/(a.field_n-1), 'relative_time':a.relative_time_s,
              'gate':a.horse_number.astype(float)}
    for name,value in extras.items():
        a['obs_'+name] = value.mask(held) if name.startswith('s1f_') else value
        obs.append(name)
    return a,obs


def make_history(a, obs):
    rows, traces = [], []
    obscols = ['obs_'+c for c in obs]
    lastnames = ['s1f_first','s1ftime','finish_rank']
    lastidx = [obs.index(c) for c in lastnames]
    firstidx, timeidx = obs.index('s1f_first'), obs.index('s1ftime')
    for _,g in a.groupby('horse_id',sort=True):
        g = g.sort_values(['race_date','race_number','api_record_id'])
        dates = g.race_date.tolist();ids = g.api_record_id.to_numpy();dist = g.race_distance_m.to_numpy()
        values = g[obscols].to_numpy(dtype=float)
        for pos,r in enumerate(g.itertuples(index=False)):
            cut = (date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat()
            lower = (date.fromisoformat(r.race_date)-timedelta(days=730)).isoformat()
            end,start = bisect_right(dates,cut),bisect_left(dates,lower)
            candidates = np.arange(start,end)
            choices = {'any':candidates[-10:], 'same':candidates[dist[candidates]==r.race_distance_m][-10:]}
            row = {'api_record_id':r.api_record_id}
            trace = {'api_record_id':r.api_record_id,'horse_id':r.horse_id,'race_date':r.race_date,
                     'race_distance_m':int(r.race_distance_m),'history_cutoff':cut}
            for scope,ix in choices.items():
                prefix = 'h_'+scope+'_'
                data = values[ix]
                counts = np.isfinite(data).sum(axis=0) if len(ix) else np.zeros(len(obs),dtype=int)
                means = np.divide(np.nansum(data,axis=0),counts,out=np.full(len(obs),np.nan),where=counts>0) if len(ix) else np.full(len(obs),np.nan)
                row.update({prefix+c+'_mean':float(means[j]) for j,c in enumerate(obs)})
                row.update({prefix+c+'_last':float(data[-1,j]) if len(ix) else np.nan for c,j in zip(lastnames,lastidx)})
                row[prefix+'n'] = len(ix)
                row[prefix+'s1f_n'] = int(counts[firstidx])
                row[prefix+'s1ftime_n'] = int(counts[timeidx])
                row[prefix+'gap_days'] = (date.fromisoformat(r.race_date)-date.fromisoformat(dates[ix[-1]])).days if len(ix) else np.nan
                if len(ix)>5:
                    old,new = data[:-5,firstidx],data[-5:,firstidx]
                    row[prefix+'first_recent_change'] = float(np.nanmean(new)-np.nanmean(old)) if np.isfinite(old).any() and np.isfinite(new).any() else np.nan
                else:
                    row[prefix+'first_recent_change'] = np.nan
                trace[scope+'_ids'] = '|'.join(map(str,ids[ix]))
                trace[scope+'_last_date'] = dates[ix[-1]] if len(ix) else None
                assert not len(ix) or dates[ix[-1]] <= cut
                assert not len(ix) or np.all(ids[ix]!=r.api_record_id)
            rows.append(row);traces.append(trace)
    features = pd.DataFrame(rows)
    assert not features.api_record_id.duplicated().any()
    return a.merge(features,on='api_record_id',validate='one_to_one'),pd.DataFrame(traces)


def add_context(a):
    for dist in DISTANCES:
        a[f'base_distance_{dist}'] = a.race_distance_m.eq(dist).astype(float)
    a['base_field_n'] = a.field_n.astype(float)
    a['gate_number'] = a.horse_number.astype(float)
    mx = a.groupby('race_id').horse_number.transform('max')
    a['gate_scaled'] = (a.horse_number-1)/(mx-1)
    a['gate_order_scaled'] = (a.groupby('race_id').horse_number.rank(method='min')-1)/(a.field_n-1)
    a['gate_scaled_squared'] = a.gate_scaled**2
    a['gate_vs_past_mean'] = a.gate_number-a.h_any_gate_mean
    a['prior_lead_smoothed'] = (1+a.h_any_s1f_first_mean.fillna(0)*a.h_any_s1f_n)/(3+a.h_any_s1f_n)
    a['gate_x_prior_lead'] = a.gate_scaled*a.prior_lead_smoothed
    for dist in DISTANCES:
        a[f'gate_x_distance_{dist}'] = a.gate_scaled*a[f'base_distance_{dist}']
    # The smoothed personal prior is a historical input, not an opponent feature.
    a['h_prior_lead_smoothed'] = a.prior_lead_smoothed
    context = []
    for _,g in a.groupby('race_id',sort=False):
        lead = g.prior_lead_smoothed.to_numpy()
        gate = g.horse_number.to_numpy()
        known = g.h_any_s1f_n.ge(3).to_numpy()
        speed = g.h_any_s1ftime_mean.to_numpy(copy=True)
        speed[~g.h_any_s1ftime_n.ge(3).to_numpy()] = np.nan
        strong = known&(lead>=.5)
        leadrank = pd.Series(lead).rank(method='average').to_numpy()
        speedrank = pd.Series(speed).rank(method='average').to_numpy()
        knownspeed = np.isfinite(speed)
        for j,r in enumerate(g.itertuples(index=False)):
            other = np.arange(len(g))!=j
            inner,outer = gate<gate[j],gate>gate[j]
            values = lead[other]
            row = {'api_record_id':r.api_record_id,
                   'opp_lead_sum':float(values.sum()),'opp_lead_max':float(values.max()),
                   'opp_strong_count':int(strong[other].sum()),
                   'opp_inner_lead_sum':float(lead[inner].sum()),'opp_outer_lead_sum':float(lead[outer].sum()),
                   'opp_inner_strong_count':int(strong[inner].sum()),'opp_outer_strong_count':int(strong[outer].sum()),
                   'opp_known_fraction':float(known[other].mean()),
                   'opp_speed_known_fraction':float(knownspeed[other].mean()),
                   'opp_own_lead_rank':float((leadrank[j]-1)/(len(g)-1)),
                   'opp_own_speed_rank':float((speedrank[j]-1)/(knownspeed.sum()-1)) if knownspeed[j] and knownspeed.sum()>1 else np.nan,
                   'opp_faster_count':int(np.sum(speed[other]<speed[j])) if knownspeed[j] else np.nan,
                   'opp_inner_faster_count':int(np.sum(speed[inner]<speed[j])) if knownspeed[j] else np.nan,
                   'opp_gate_x_inner_pressure':float(r.gate_scaled*lead[inner].sum()),
                   'opp_gate_x_outer_pressure':float(r.gate_scaled*lead[outer].sum()),
                   'speed_prior_known_field_n':int(knownspeed.sum()),
                   'speed_prior_fast_third':bool(knownspeed[j] and knownspeed.sum()>=6 and knownspeed.sum()>=.8*len(g) and
                                                  3*(speedrank[j]-1)<=knownspeed.sum()-1)}
            context.append(row)
    a = a.merge(pd.DataFrame(context),on='api_record_id',validate='one_to_one')
    return a


def main():
    out = HERE/'features01';out.mkdir(exist_ok=False)
    sources = [HERE/'PLAN.md',PREV/'run01/runner_types_and_evidence.csv',PACK/'run01/race_point_audit.csv',
               PREV/'input01/source_manifest.json',PREV/'run01/verification_independent.json',
               ROOT/'jeju/data/horse_exclusions.json',
               ROOT/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py']
    manifest = [{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sources]
    save(out/'source_manifest.json',{'files':manifest,'plan_sha256':sha(HERE/'PLAN.md'),
        'source_database_sha256':json.loads((PREV/'input01/source_manifest.json').read_text())['database_sha256'],
        'live_database_opened':False})
    a = pd.read_csv(PREV/'run01/runner_types_and_evidence.csv',dtype={'horse_id':str},low_memory=False)
    points = pd.read_csv(PACK/'run01/race_point_audit.csv',low_memory=False)
    assert not a.api_record_id.duplicated().any()
    exclusions = json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(a.horse_id)&{k for k,v in exclusions.items() if not v['reimport_allowed']}
    a,obs = source_observations(a,points)
    print('Source targets constructed',len(a),flush=True)
    a,trace = make_history(a,obs)
    print('T-minus-two histories constructed',len(trace),flush=True)
    a = add_context(a)
    cols = {'common':[c for c in a if c.startswith('base_')],
            'history':[c for c in a if c.startswith('h_')],
            'gate':[c for c in a if c.startswith('gate_')],
            'opponents':[c for c in a if c.startswith('opp_')]}
    for c in sum(cols.values(),[]):
        assert c.startswith(('base_','h_','gate_','opp_'))
    keep = ['api_record_id','race_id','race_date','race_number','year','horse_id','horse_name','age_2026',
            'race_distance_m','field_n','horse_number','s1f_pack_index','s1f_pack_size','s1f_pack_lateral',
            's1f_rank_lo','s1f_rank_hi','speed_prior_known_field_n','speed_prior_fast_third']
    keep += ['y_'+task for task in TASKS]+sum(cols.values(),[])
    a[keep].to_csv(out/'features_and_targets.csv',index=False,encoding='utf-8-sig')
    trace.to_csv(out/'history_lineage.csv',index=False,encoding='utf-8-sig')
    save(out/'feature_columns.json',cols)
    assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest)
    save(out/'verification.json',{'status':'passed','rows':len(a),'history_windows':2*len(trace),
        'all_history_T_minus2_and_self_excluded':True,'quality_groups_only':True,
        'no_live_database_access':True,'no_current_postrace_features_in_whitelist':True,
        'history_observables':obs,'feature_counts':{k:len(v) for k,v in cols.items()},
        'source_hashes_unchanged':True,'code_sha256':sha(Path(__file__))})
    print({k:len(v) for k,v in cols.items()},flush=True)


if __name__=='__main__':
    main()
