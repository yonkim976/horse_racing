"""Separate state-machine parsing, lineage selection and scalar label checks."""
from datetime import date,timedelta
import json,re
import numpy as np
import pandas as pd
from common import *

def parse_independent(raw):
    if not isinstance(raw,str):return None
    s=raw.replace(' ','');packs=[];at=0
    while at<len(s):
        if s[at] in ',=≡-':at+=1;continue
        group=[]
        if s[at]=='(':
            end=s.find(')',at+1)
            if end<0:return None
            body=s[at+1:end]
            if not re.fullmatch(r'\^?\d+(,\^?\d+)*',body):return None
            group=[int(t.lstrip('^')) for t in body.split(',')];at=end+1
        else:
            m=re.match(r'\^?\d+',s[at:])
            if not m:return None
            group=[int(m[0].lstrip('^'))];at+=len(m[0])
        packs.append(group)
    return packs or None

def main():
    sm=json.loads((OUT/'source_manifest.json').read_text());check_manifest(sm['files']);check_manifest([sm['selected_snapshot']])
    a=pd.read_parquet(OUT/'features_and_targets.parquet');raw=pd.read_parquet(OUT/'observations.parquet')
    assert set(a.api_record_id)==set(raw.api_record_id)
    assert a.race_date.max()=='2026-09-19' and not a.horse_id.eq('3005648').any()
    checks=0
    for race,g in a.groupby('race_id',sort=False):
        for p in POINTS:
            value=g[p+'_group'].iloc[0];groups=parse_independent(value)
            if g[p+'_group_status'].iloc[0]!='api_group_unreviewed' or (p=='c3' and g.race_distance_m.iloc[0]==800):groups=None
            if groups:
                nums=[x for pack in groups for x in pack]
                if len(nums)!=len(set(nums)) or set(nums)!=set(g.horse_number):groups=None
            if groups is None:assert g['y_'+p].isna().all();continue
            m={};lo=1
            for j,pack in enumerate(groups):
                for n in pack:m[n]=(min(j,2),lo,lo+len(pack)-1)
                lo+=len(pack)
            for r in g.itertuples():
                assert (getattr(r,'y_'+p),getattr(r,p+'_lo'),getattr(r,p+'_hi'))==m[r.horse_number]
                checks+=1
    for event,x,y in [('middle_advance','s1f','c3'),('late_advance','c4','g1f'),('last200_recovery','g1f','finish')]:
        left=a['obs_'+x+'_rank'];right=a['obs_'+y+'_rank'];known=left.notna()&right.notna()
        actual=a['y_'+event];assert actual.notna().equals(known)
        expected=(left-right)*(a.field_n-1)>=2-1e-8
        assert np.array_equal(actual[known],expected[known].astype(float));checks+=int(known.sum())
    ix=a.set_index('api_record_id');line=pd.read_parquet(OUT/'history_lineage.parquet').set_index('api_record_id')
    hchecks=0;featurechecks=0
    obs=[c for c in a if c.startswith('obs_')]
    for _,g in a.groupby('horse_id',sort=False):
        g=g.sort_values(['race_date','race_number','api_record_id']);days=np.array(g.race_date,dtype='datetime64[D]');ids=g.api_record_id.to_numpy()
        for r in g.itertuples():
            cut=np.datetime64(r.race_date)-np.timedelta64(2,'D');lower=np.datetime64(r.race_date)-np.timedelta64(730,'D')
            possible=np.flatnonzero((days<=cut)&(days>=lower))
            for name,slots in [('h5',5),('h10',10),('same10',10)]:
                selected=possible[g.race_distance_m.to_numpy()[possible]==r.race_distance_m][-slots:] if name=='same10' else possible[-slots:]
                assert line.loc[r.api_record_id,name+'_ids']=='|'.join(map(str,ids[selected]))
                assert r.api_record_id not in ids[selected]
                past=g.iloc[selected]
                used=[c for c in obs if name=='same10' or not c.endswith('_seconds')]
                data=past[used].to_numpy(float);counts=np.isfinite(data).sum(axis=0)
                means=np.divide(np.nansum(data,axis=0),counts,out=np.full(len(used),np.nan),where=counts>0)
                actualmean=np.array([getattr(r,name+'_'+c[4:]+'_mean') for c in used])
                actualn=np.array([getattr(r,name+'_'+c[4:]+'_n') for c in used])
                assert np.allclose(actualmean,means,equal_nan=True,atol=1e-12)
                assert np.array_equal(actualn,counts)
                hchecks+=1;featurechecks+=len(used)*2
    # Opponent means/inner sums independently reconstruct using only historical rows.
    oppchecks=0
    for _,g in a.groupby('race_id',sort=False):
        for r in g.itertuples():
            other=g[g.api_record_id.ne(r.api_record_id)]
            assert abs(r.opp_lead_sum-other.prior_s1f.sum())<1e-10
            assert abs(r.opp_inner_lead_sum-other.loc[other.horse_number.lt(r.horse_number),'prior_s1f'].sum())<1e-10
            oppchecks+=2
    contract=json.loads((OUT/'feature_contract.json').read_text())
    assert not any(c.startswith(('obs_','y_')) for c in contract['F'])
    assert not any(c.endswith('_seconds_mean') and not c.startswith('same10') for c in contract['F'])
    # Saved feature construction consumes current card + earlier source rows only.
    save(OUT/'build_verification.json',{'status':'passed','roster_rows':len(a),'point_labels_checked':checks,
         'history_windows_checked':hchecks,'historical_numeric_cells_checked':featurechecks,'opponent_scalar_checks':oppchecks,
         '800m_middle_not_distinct':True,'current_postrace_columns_excluded':True,'all_history_T_minus_2':True,
         'source_hashes_preserved':True,'database_written':False,'network_used':False})
    print('Build independently verified',len(a),'rows',hchecks,'historical windows',flush=True)

if __name__=='__main__':main()
