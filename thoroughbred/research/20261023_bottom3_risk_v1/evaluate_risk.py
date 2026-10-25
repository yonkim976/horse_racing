"""Frozen comparison metrics and one-horse policies, evaluated on every held-out race."""
import json
import risk_common as c
import numpy as np
import pandas as pd

def score(g,base,bottom,meta):
    y=g.bottom_truth.to_numpy(float);out=g.outcome.to_numpy(int)
    programs=g.program_no.to_numpy(int);top=(out>=1)&(out<=3)
    row={'race_key':g.race_key.iloc[0],'race_date':str(g.race_date.iloc[0].date()),'meet':int(g.meet.iloc[0]),
        'year':int(g.year.iloc[0]),'distance_m':int(g.distance_m.iloc[0]),'grade':str(g.grade_raw.iloc[0]),
        'field_size':len(g),'boundary_tie':bool(g.boundary_tie.any()),'nonfinishers':int((~g.normal).sum()),
        'random_precision':3/len(g),'policy_lambda':meta['policy_lambda']}
    runners=g[['row_number',*c.KEY,'finish_order','result_status','bottom_truth']].copy()
    runners['base_score']=base;runners['bottom_score']=bottom
    for name,s,temp in [('baseline',-base,meta['baseline_bottom_temperature']),('model',bottom,meta['bottom_temperature'])]:
        ix=c.order(s)[:3];sets,mass,p=c.distribution(s,temp)
        hit=float(y[ix].sum())
        row.update({name+'_correct':hit,name+'_exact3':float(hit==3) if not row['boundary_tie'] else np.nan,
            name+'_atleast2':int(hit>=2),name+'_zero':int(hit==0),name+'_podium_excluded':int(top[ix].sum()),
            name+'_any_podium_excluded':int(top[ix].any()),name+'_winner_excluded':int((out[ix]==1).any()),
            name+'_nonfinishers_selected':int((~g.normal.to_numpy()[ix]).sum()),
            name+'_brier':float(np.mean((p-y)**2)),name+'_set_nll':float(-np.log(max(mass[(y[sets]==1).all(axis=1)].sum(),1e-300))) if not row['boundary_tie'] else np.nan})
        for i,idx in enumerate(ix,1):row[f'{name}_bottom_{i}']=int(programs[idx])
        runners[name+'_bottom_probability']=p
        runners[name+'_selected']=np.isin(np.arange(len(g)),ix)
    for name,ix in [('base',c.choose(base,bottom,0)),('exclude',c.exclude_axis(base,bottom)),
        ('selected',c.choose(base,bottom,meta['policy_lambda']))]:
        row[name+'_axis']=int(programs[ix]);row[name+'_axis_hit']=int(top[ix])
    return row,runners

def summarize(m):
    groups={'all':m,'seoul':m[m.meet.eq(1)],'busan':m[m.meet.eq(3)]}
    groups.update({str(y):m[m.year.eq(y)] for y in [2024,2025,2026]})
    target=m.meet.eq(3)&m.grade.eq('국5등급')&m.distance_m.isin([1300,1600])
    groups['busan_grade5_1300_1600']=m[target]
    groups['busan_grade5_1300_1600_2026']=m[target&m.year.eq(2026)]
    for meet in [1,3]:
        for year in [2024,2025,2026]:groups[f'{meet}_{year}']=m[m.meet.eq(meet)&m.year.eq(year)]
    result={}
    for name,g in groups.items():
        v={'races':len(g),'random_precision':float(g.random_precision.mean()),'nonfinishers':int(g.nonfinishers.sum()),
            'bottom_comparison':c.paired(g,'baseline_correct','model_correct',3.),
            'false_podium_comparison':c.paired(g,'baseline_podium_excluded','model_podium_excluded',3.),
            'exclude_axis_comparison':c.paired(g,'base_axis_hit','exclude_axis_hit'),
            'selected_axis_comparison':c.paired(g,'base_axis_hit','selected_axis_hit')}
        for model in ['baseline','model']:
            v[model]={'correct_horses':float(g[model+'_correct'].sum()),'precision':float(g[model+'_correct'].mean()/3),
                'exact3_races':int(g[model+'_exact3'].sum()),'exact3_denominator':int(g[model+'_exact3'].notna().sum()),
                'atleast2_races':int(g[model+'_atleast2'].sum()),'zero_races':int(g[model+'_zero'].sum()),
                'podium_horses_excluded':int(g[model+'_podium_excluded'].sum()),
                'races_any_podium_excluded':int(g[model+'_any_podium_excluded'].sum()),
                'winner_excluded_races':int(g[model+'_winner_excluded'].sum()),
                'nonfinishers_selected':int(g[model+'_nonfinishers_selected'].sum()),
                'race_mean_brier':float(g[model+'_brier'].mean()),'mean_set_nll':float(g[model+'_set_nll'].mean())}
        for policy in ['exclude','selected']:v[policy+'_switches']=int(g[policy+'_axis'].ne(g.base_axis).sum())
        result[name]=v
    return result

def main():
    c.check();f=c.frame();f.index=f.row_number
    c.save(c.OUT/'evaluation_started.json',{'protocol_sha256':c.sha(c.OUT/'protocol_frozen.json'),
        'evaluation_code_sha256':c.sha(c.HERE/'evaluate_risk.py')})
    rows=[];runners=[]
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=c.OUT/'models'/f'bottom3_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            bs=pd.read_parquet(c.PREV/'outputs/models'/f'state_gbm_{meet}_{year}'/'scores.parquet')
            bs=bs[bs.phase.eq('evaluation')].set_index('row_number').score
            ss=pd.read_parquet(folder/'scores.parquet')
            ss=ss[ss.phase.eq('evaluation')].set_index('row_number').score
            assert set(bs.index)==set(ss.index)
            one=f.loc[ss.index].copy().sort_values(['race_date','race_key','program_no'])
            for _,g in one.groupby('race_key',sort=False):
                assert g.program_no.is_monotonic_increasing
                row,rr=score(g,bs.loc[g.row_number].to_numpy(float),ss.loc[g.row_number].to_numpy(float),meta)
                rows.append(row);runners.append(rr)
            print('Scored',meet,year,flush=True)
    m=pd.DataFrame(rows);rr=pd.concat(runners,ignore_index=True)
    assert len(m)==4799 and len(rr)==50754 and not m.race_key.duplicated().any()
    ref=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet')
    ref=ref[ref.variant.eq('state_gbm')&ref.scope.eq('all_starters')]
    joined=m.merge(ref[['race_key','axis_program_no','axis_top3']],on='race_key',validate='1:1')
    assert len(joined)==4799
    assert joined.base_axis.eq(joined.axis_program_no).all() and joined.base_axis_hit.eq(joined.axis_top3).all()
    m.to_parquet(c.OUT/'race_metrics.parquet',index=False,compression='zstd')
    rr.to_parquet(c.OUT/'runner_predictions.parquet',index=False,compression='zstd')
    c.save(c.OUT/'results.json',summarize(m))
    c.storage()
    print(json.dumps(summarize(m)['all'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
