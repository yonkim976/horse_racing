"""Read-only snapshot followup under the user-corrected1300m sequence."""
from pathlib import Path
import importlib.util
import hashlib
import json
import math
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def main():
    out=HERE/'run01';out.mkdir(exist_ok=False)
    inputs=[HERE/'PLAN.json',HERE/'analyze.py',ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv',
        ROOT/'jeju/research/20261008_passing_group_running_style_v1/run01/race_point_audit.csv',
        ROOT/'jeju/research/20261008_gate_top3_period_moisture_v1/raw_gate.csv',
        ROOT/'jeju/research/20261008_gate_top3_period_moisture_v1/adjusted_contrasts.csv',
        ROOT/'jeju/research/20261008_gate_record_seconds_v1/lateral_seconds.csv',
        ROOT/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py',ROOT/'jeju/data/horse_exclusions.json']
    manifest=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in inputs]
    save(out/'source_manifest.json',{'files':manifest,'no_live_database_access':True})
    a=pd.read_csv(inputs[2],dtype={'horse_id':str},low_memory=False);a=a[a.race_distance_m.eq(1300)].copy()
    assert len(a)==606 and a.race_id.nunique()==63
    excluded=json.loads(inputs[-1].read_text())['horses']
    assert not set(a.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']}
    a['gate_band']=np.select([a.horse_number.le(3),a.horse_number.ge(8)],['inner','outer'],default='middle')
    points=pd.read_csv(inputs[3],low_memory=False);points=points[points.race_distance_m.eq(1300)&points.point.isin(['c2','s1f'])]
    spec=importlib.util.spec_from_file_location('preserved_parser',inputs[7]);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    observations=[]
    for r in points.itertuples():
        assert r.parse_status=='usable_group_interval'
        assert not any(t in str(r.quality_status) for t in ['unresolved','not_applied','source_changed'])
        packs=mod.parse_groups(r.group_value);assert packs
        roster=a[a.race_id.eq(r.race_id)]
        numbers=[n for g in packs for n in g]
        assert len(numbers)==len(set(numbers))==len(roster) and set(numbers)==set(roster.horse_number)
        before=0
        for ix,g in enumerate(packs):
            for n in g:
                observations.append({'race_id':r.race_id,'point':r.point,'horse_number':n,'pack_index':ix,
                    'pack_size':len(g),'rank_lo':before+1,'rank_hi':before+len(g),
                    'firstpack':int(ix==0),'first2packs':int(ix<2),'api303_api_record_id':r.api303_api_record_id})
            before+=len(g)
    obs=pd.DataFrame(observations)
    full=a.merge(obs,on=['race_id','horse_number'],validate='one_to_many')
    exact=a.groupby('race_id').horse_number.agg(lambda x:len(x)==10 and set(x)==set(range(1,11)))
    v=full[full.race_id.isin(exact[exact].index)].copy()
    assert v.api_record_id.nunique()==470 and v.race_id.nunique()==47
    full.to_csv(out/'all1300_quality_pack_observations.csv',index=False,encoding='utf-8-sig')
    v.to_csv(out/'exact10_observations.csv',index=False,encoding='utf-8-sig')
    counts=[]
    for period,g in [('all',v)]+[(str(y),v[v.year.eq(y)]) for y in sorted(v.year.unique())]:
        for (point,band),z in g.groupby(['point','gate_band']):
            counts.append({'period':period,'point':point,'gate_band':band,'races':z.race_id.nunique(),'starts':len(z),
                'firstpack':int(z.firstpack.sum()),'first2packs':int(z.first2packs.sum()),
                'firstpack_rate':z.firstpack.mean(),'first2packs_rate':z.first2packs.mean()})
    pd.DataFrame(counts).to_csv(out/'early_gate_counts.csv',index=False)
    rng=np.random.default_rng(20261008);contrasts=[]
    for point in ['c2','s1f']:
        for event in ['firstpack','first2packs']:
            z=v[v.point.eq(point)&v.gate_band.ne('middle')].groupby(['race_id','race_date','gate_band'])[event].mean().unstack('gate_band').reset_index()
            z['delta']=z.inner-z.outer
            dates=z.groupby('race_date').delta.agg(['sum','count'])
            n=len(dates);draws=rng.integers(n,size=(10000,n))
            num,den=dates['sum'].to_numpy(),dates['count'].to_numpy();mean=num.sum()/den.sum()
            boot=num[draws].sum(axis=1)/den[draws].sum(axis=1)
            lo,hi=np.quantile(boot,[.025,.975]);se=np.sqrt(n/(n-1)*np.square(num-mean*den).sum())/den.sum()
            p=math.erfc(abs(mean/se)/np.sqrt(2)) if se else float(not mean)
            contrasts.append({'point':point,'event':event,'races':len(z),'days':n,'inner_rate':z.inner.mean(),'outer_rate':z.outer.mean(),
                'difference_pp':100*mean,'ci_lo_pp':100*lo,'ci_hi_pp':100*hi,'p':p,'exploratory_not_ability_adjusted':True})
    contrasts=pd.DataFrame(contrasts);order=contrasts.sort_values('p')
    q=np.minimum.accumulate((order.p.to_numpy()*4/np.arange(1,5))[::-1])[::-1]
    contrasts.loc[order.index,'BH_q']=np.minimum(q,1)
    contrasts.to_csv(out/'early_gate_contrasts.csv',index=False)
    # Reproduce final outcome numerators from the same selected source runners.
    runners=v[v.point.eq('s1f')].copy()
    top=runners.groupby('horse_number').agg(starts=('api_record_id','size'),top3=('top3','sum')).reset_index()
    raw=pd.read_csv(inputs[4]);raw=raw[raw.race_distance_m.eq(1300)]
    chk=top.merge(raw,on='horse_number',suffixes=('_new','_saved'),validate='one_to_one')
    assert (chk.starts_new==chk.starts_saved).all() and (chk.top3_new==chk.top3_saved).all()
    top.to_csv(out/'top3_gate_reproduced.csv',index=False)
    annual=[]
    for period,g in [('all',runners)]+[(str(y),runners[runners.year.eq(y)]) for y in sorted(runners.year.unique())]:
        for band,z in g.groupby('gate_band'):
            annual.append({'period':period,'gate_band':band,'races':z.race_id.nunique(),'starts':len(z),'top3':int(z.top3.sum()),'top3_rate':z.top3.mean()})
    pd.DataFrame(annual).to_csv(out/'top3_group_counts.csv',index=False)
    adjusted=pd.read_csv(inputs[5]);adjusted=adjusted[(adjusted.distance==1300)&(adjusted.kind=='overall')&(adjusted.variant=='primary')]
    adjusted.to_csv(out/'previous_adjusted_top3.csv',index=False)
    seconds=pd.read_csv(inputs[6]);seconds=seconds[(seconds.distance==1300)&(seconds.period=='full')&(seconds.variant=='primary')&(seconds.contrast=='inner_minus_outer')]
    seconds.to_csv(out/'previous_adjusted_seconds.csv',index=False)
    # Independent rank-range membership checks do not read the event columns.
    assert (v.firstpack==v.rank_lo.eq(1).astype(int)).all()
    firstsizes=v[v.rank_lo.eq(1)].groupby(['race_id','point']).pack_size.first()
    boundaries=[firstsizes.loc[(r.race_id,r.point)]+1 for r in v.itertuples()]
    assert (v.first2packs==v.rank_lo.le(boundaries).astype(int)).all()
    assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest)
    save(out/'verification.json',{'status':'passed','all1300_races':63,'all1300_starts':606,'exact10_races':47,'exact10_starts':470,
        'actual_first_date':runners.race_date.min(),'actual_last_date':runners.race_date.max(),
        'quality_rosters_checked':len(points),'independent_event_checks':2*len(v),'top3_gate_counts_reproduced':10,
        'source_hashes_unchanged':True,'user_sequence_contract_applied':True,'official_specification_independently_verified':False,
        'prior_model_results_unchanged_and_still_exclude1300':True,'no_causal_effect_or_fixed_correction_adopted':True})
    print(contrasts.to_string(index=False),flush=True)
    print(pd.DataFrame(annual).to_string(index=False),flush=True)

if __name__=='__main__':main()
