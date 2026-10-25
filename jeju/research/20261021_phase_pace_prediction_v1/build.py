"""Freeze quality-selected observations and construct strictly historical inputs."""
from datetime import date,timedelta
from bisect import bisect_left,bisect_right
import importlib.util
import json
import sqlite3
import numpy as np
import pandas as pd
from common import *

def freeze_source():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'observations.parquet').exists(), 'do not overwrite a frozen source'
    # The roster remains the immutable pre-existing cohort, including DNF/DQ.
    roster=pd.read_parquet(SNAPSHOT)
    a=roster[roster.race_date.between('2017-01-01','2026-09-19') & roster.meet_code.eq(2)
             & roster.race_distance_m.isin(DISTANCES) & roster.started].copy()
    assert a.api_record_id.is_unique and a.race_id.nunique()>5000
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(a.horse_id.astype(str)) & {k for k,v in excluded.items() if not v['reimport_allowed']}
    columns=['api_record_id','horse_id','horse_name','age_2026','race_date','race_number',
             'race_distance_m','horse_number','finish_position','finish_time_seconds',
             'api4_3_payload_sha256','api303_payload_sha256']
    for p in POINTS:columns += [p+'_group',p+'_group_status',p+'_order',p+'_order_status']
    for p in ['s1f','g3f','g1f']:columns += [p+'_time_seconds',p+'_time_status']
    c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
    c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
    v=c.execute('PRAGMA data_version').fetchone()[0]
    sql=c.execute('SELECT sql FROM sqlite_master WHERE name=?',('jeju_race_postrace_sections_quality_2026',)).fetchone()[0]
    # Column list and IN values are internal constants; dates are bound data.
    q='SELECT '+','.join(columns)+' FROM jeju_race_postrace_sections_quality_2026 WHERE race_date BETWEEN ? AND ? AND race_distance_m IN (800,900,1000,1110,1200,1300,1400,1610) ORDER BY api_record_id'
    b=pd.read_sql_query(q,c,params=['2017-01-01','2026-09-19'])
    assert c.execute('PRAGMA query_only').fetchone()[0]==1
    assert c.execute('PRAGMA data_version').fetchone()[0]==v
    c.close()
    b=b[b.api_record_id.isin(a.api_record_id)].copy()
    assert set(b.api_record_id)==set(a.api_record_id) and b.api_record_id.is_unique
    z=a[['api_record_id','race_id','year','started','valid_time','carried_weight_kg']].merge(b,on='api_record_id',validate='one_to_one')
    old=a.set_index('api_record_id');new=z.set_index('api_record_id')
    for col in ['horse_id','race_date','horse_number','race_distance_m','finish_position','api4_3_payload_sha256']:
        left=old[col].sort_index();right=new[col].sort_index()
        if col in ['horse_number','race_distance_m','finish_position']:
            assert np.array_equal(left.to_numpy(float),right.to_numpy(float)),col
        else:
            assert left.astype(str).equals(right.astype(str)),col
    z['horse_id']=z.horse_id.astype(str)
    z['field_n']=z.groupby('race_id').api_record_id.transform('size')
    z['race_distance_m']=z.race_distance_m.astype(int)
    z=z.sort_values(['race_date','race_number','horse_number']).reset_index(drop=True)
    assert not z.duplicated(['race_id','horse_number']).any()
    z.to_parquet(OUT/'observations.parquet',index=False)
    sources=[SNAPSHOT,PARSER,HERE/'PLAN.md',ROOT/'jeju/AGENTS.md',ROOT/'jeju/data/horse_exclusions.json',
             ROOT/'jeju/research/20261019_section_layout_by_distance_v1/README.md',
             ROOT/'thoroughbred/research/20261008_field_pace_prediction/PLAN.md',
             ROOT/'thoroughbred/research/20261021_busan_joint_pace_stack/PLAN.md']
    save(OUT/'source_manifest.json',{'files':manifest(sources),'selected_snapshot':manifest([OUT/'observations.parquet'])[0],
        'query':q,'bound_parameters':['2017-01-01','2026-09-19'],'view_sql_sha256':__import__('hashlib').sha256(sql.encode()).hexdigest(),
        'sqlite_mode':'ro','query_only':True,'data_version_unchanged':True,'whole_database_hash_claimed':False,
        'roster_rows':len(z),'roster_races':z.race_id.nunique(),'normal_complete_filter':False})
    return z

def targets(a):
    a=a.copy()
    sp=importlib.util.spec_from_file_location('preserved_pack_parser',PARSER)
    parser=importlib.util.module_from_spec(sp);sp.loader.exec_module(parser)
    census=[]
    for p in POINTS:
        a['y_'+p]=np.nan;a[p+'_lo']=np.nan;a[p+'_hi']=np.nan
        for race,g in a.groupby('race_id',sort=False):
            value=g[p+'_group'].iloc[0];status=g[p+'_group_status'].iloc[0]
            assert g[p+'_group'].nunique(dropna=False)==1
            reason='usable';groups=None
            if status!='api_group_unreviewed':reason='quality_unavailable_or_held'
            elif not isinstance(value,str) or not (groups:=parser.parse_groups(value)):reason='notation_unparsed'
            else:
                numbers=[n for pack in groups for n in pack]
                if len(numbers)!=len(set(numbers)) or set(numbers)!=set(g.horse_number):reason='roster_mismatch'
            if p=='c3' and g.race_distance_m.iloc[0]==800:reason='800m_alias_of_s1f'
            census.append({'race_id':race,'point':p,'year':int(g.year.iloc[0]),'distance':int(g.race_distance_m.iloc[0]),
                           'rows':len(g),'reason':reason,'source_group':value,'status':status})
            if reason!='usable':continue
            d={};lo=1
            for i,pack in enumerate(groups):
                for n in pack:d[n]=(min(i,2),lo,lo+len(pack)-1)
                lo+=len(pack)
            a.loc[g.index,'y_'+p]=[d[n][0] for n in g.horse_number]
            a.loc[g.index,p+'_lo']=[d[n][1] for n in g.horse_number]
            a.loc[g.index,p+'_hi']=[d[n][2] for n in g.horse_number]
        # Reviewed official ranks are distinct from pack-internal ordering.
        o=pd.to_numeric(a[p+'_order'],errors='coerce')
        valid=o.between(1,a.field_n) & ~a[p+'_order_status'].str.contains('conflict|unresolved|not_applied|source_changed',na=True)
        # A held point cannot re-enter via another field of the same point.
        valid &= a['y_'+p].notna()
        a['obs_'+p+'_rank']=((o-1)/(a.field_n-1)).where(valid)
        for k in [0,1,2]:a[f'obs_{p}_{k}']=np.where(a['y_'+p].notna(),a['y_'+p].eq(k).astype(float),np.nan)
        a['obs_'+p+'_solo']=np.where(a['y_'+p].notna(),(a['y_'+p].eq(0)&a[p+'_hi'].eq(1)).astype(float),np.nan)
    normal=a.finish_position.between(1,89)
    a['obs_finish_rank']=((a.finish_position-1)/(a.field_n-1)).where(normal)
    a['obs_top3']=a.finish_position.le(3).astype(float).where(normal)
    # Complete point masks and official ranks define the phase movements.
    for event,before,after in [('middle_advance','s1f','c3'),('late_advance','c4','g1f'),('last200_recovery','g1f','finish')]:
        x=a['obs_'+before+'_rank'];y=a['obs_'+after+'_rank']
        a['y_'+event]=((x-y)*(a.field_n-1)>=2-1e-8).astype(float).where(x.notna()&y.notna())
    a['y_front_fade']=(a.y_s1f.eq(0)&((a.finish_position-a.s1f_lo)>=3)).astype(float).where(a.y_s1f.notna()&normal)
    for event in EVENTS:a['obs_'+event]=a['y_'+event]
    a['y_count']=a.y_s1f.eq(0).groupby(a.race_id).transform('sum').clip(upper=3)-1
    a['y_count']=a.y_count.where(a.y_s1f.notna())
    for p in ['s1f','g3f','g1f']:
        value=a[p+'_time_seconds'];status=a[p+'_time_status']
        ok=value.gt(0)&value.lt(a.finish_time_seconds)&normal
        ok &= status.isin(['api_positive_unreviewed','website_corrected'])
        # Group conflicts block time-derived inputs from the associated point.
        mask=a['y_'+('c3' if p=='g3f' else p)].notna()
        if p=='g3f':mask |= a.race_distance_m.eq(800)&a.y_s1f.notna()
        ok &= mask
        a['obs_'+p+'_seconds']=value.where(ok)
        v=value.where(ok);n=v.groupby(a.race_id).transform('count')
        a['obs_'+p+'_speedrank']=((v.groupby(a.race_id).rank(method='average')-1)/(n-1)).where(n.ge(6)&n.ge(.8*a.field_n))
    ft=a.finish_time_seconds.where(a.valid_time&normal)
    a['obs_finish_relative']=(ft-ft.groupby(a.race_id).transform('median'))*1000/a.race_distance_m
    a['obs_first_g1f_speedrank']=a.obs_g1f_speedrank.where(a.y_s1f.eq(0))
    a['obs_first_top3']=a.obs_top3.where(a.y_s1f.eq(0))
    a['obs_gate']=a.horse_number.astype(float)
    pd.DataFrame(census).to_parquet(OUT/'target_census.parquet',index=False)
    return a

def histories(a):
    obs=[c for c in a if c.startswith('obs_')]
    # Raw seconds are only in exact-distance history, never pooled 200/210m.
    pools={'h5':5,'h10':10,'same10':10}
    rows=[];traces=[]
    for horse,g in a.groupby('horse_id',sort=True):
        g=g.sort_values(['race_date','race_number','api_record_id'])
        dates=g.race_date.tolist();ids=g.api_record_id.to_numpy();dist=g.race_distance_m.to_numpy()
        vals=g[obs].to_numpy(dtype=float)
        for r in g.itertuples():
            cutoff=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat()
            lower=(date.fromisoformat(r.race_date)-timedelta(days=730)).isoformat()
            ix=np.arange(bisect_left(dates,lower),bisect_right(dates,cutoff))
            row={'api_record_id':r.api_record_id};trace={'api_record_id':r.api_record_id,'cutoff':cutoff,'lower':lower}
            for name,slots in pools.items():
                selected=ix[dist[ix]==r.race_distance_m][-slots:] if name=='same10' else ix[-slots:]
                trace[name+'_ids']='|'.join(map(str,ids[selected]))
                data=vals[selected];counts=np.isfinite(data).sum(axis=0)
                means=np.divide(np.nansum(data,axis=0),counts,out=np.full(len(obs),np.nan),where=counts>0)
                row[name+'_slots']=len(selected)
                for j,c in enumerate(obs):
                    if c.endswith('_seconds') and name!='same10':continue
                    stem=name+'_'+c[4:]
                    row[stem+'_mean']=means[j];row[stem+'_n']=int(counts[j])
                row[name+'_gap']=(date.fromisoformat(r.race_date)-date.fromisoformat(dates[selected[-1]])).days if len(selected) else np.nan
            rows.append(row);traces.append(trace)
    features=pd.DataFrame(rows)
    b=a.merge(features,on='api_record_id',validate='one_to_one')
    pd.DataFrame(traces).to_parquet(OUT/'history_lineage.parquet',index=False)
    return b

def context(a):
    a=a.copy();a['base_distance']=a.race_distance_m.astype(float);a['base_field_n']=a.field_n.astype(float)
    a['base_month']=pd.to_datetime(a.race_date).dt.month
    a['gate_number']=a.horse_number.astype(float)
    a['gate_scaled']=(a.horse_number-1)/(a.groupby('race_id').horse_number.transform('max')-1)
    for p in POINTS:
        a['prior_'+p]=(a['h10_'+p+'_0_mean'].fillna(0)*a['h10_'+p+'_0_n']+1)/(a['h10_'+p+'_0_n']+3)
    rows=[]
    compare=['prior_s1f','prior_c3','prior_c4','prior_g1f','h10_s1f_speedrank_mean','h10_g1f_speedrank_mean',
             'h10_finish_rank_mean','h10_first_g1f_speedrank_mean']
    for _,g in a.groupby('race_id',sort=False):
        gate=g.horse_number.to_numpy();z=g[compare].to_numpy(float)
        for j,r in enumerate(g.itertuples()):
            other=np.arange(len(g))!=j;inner=gate<gate[j];outer=gate>gate[j]
            row={'api_record_id':r.api_record_id}
            for k,c in enumerate(compare):
                vals=z[other,k];known=np.isfinite(vals)
                row['opp_'+c+'_mean']=float(vals[known].mean()) if known.any() else np.nan
                row['opp_'+c+'_known']=float(known.mean())
                row['opp_'+c+'_gap']=z[j,k]-row['opp_'+c+'_mean']
                row['opp_'+c+'_percentile']=float(np.mean(vals[known]<=z[j,k])) if known.any() and np.isfinite(z[j,k]) else np.nan
            lead=z[:,0];known=g.h10_s1f_0_n.to_numpy()>=3;strong=known&(lead>=.5)
            row.update(opp_lead_sum=float(lead[other].sum()),opp_inner_lead_sum=float(lead[inner].sum()),
                       opp_outer_lead_sum=float(lead[outer].sum()),opp_strong_count=int(strong[other].sum()),
                       opp_inner_strong=int(strong[inner].sum()),opp_outer_strong=int(strong[outer].sum()))
            rows.append(row)
    return a.merge(pd.DataFrame(rows),on='api_record_id',validate='one_to_one')

def main():
    a=freeze_source();print('Frozen starter roster',len(a),a.race_id.nunique(),flush=True)
    a=targets(a);print('Quality targets constructed',flush=True)
    a=histories(a);print('Historical windows constructed',flush=True)
    a=context(a)
    own=[c for c in a if c.startswith(('h5_','h10_','same10_','base_'))]
    field=[c for c in a if c.startswith(('gate_','opp_','prior_'))]
    save(OUT/'feature_contract.json',{'P':own,'F':own+field,'tasks':TASKS,'primary_points':POINTS,
         'historical_slots':[5,10],'days_back':730,'cutoff_lag_days':2,'publication_times_verified':False,
         'current_postrace_inputs':[],'800m_c3_alias':True,'rider_trainer_features':False})
    a.to_parquet(OUT/'features_and_targets.parquet',index=False)
    save(OUT/'build_receipt.json',{'status':'built_pending_independent_verification','rows':len(a),'races':a.race_id.nunique(),
        'horses':a.horse_id.nunique(),'start':a.race_date.min(),'end':a.race_date.max(),
        'P_columns':len(own),'F_columns':len(own+field),'normal_rows':int(a.finish_position.between(1,89).sum()),
        'dnf_dq_rows':int(a.finish_position.isin([91,92]).sum())})
    print('Feature matrix saved',a.shape,'P/F',len(own),len(own+field),flush=True)

if __name__=='__main__':main()
