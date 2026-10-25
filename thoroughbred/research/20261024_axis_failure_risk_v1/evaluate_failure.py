"""Frozen axis-failure probability and all-race, one-horse policy evaluation."""
import json
import failure_common as c
import numpy as np
import pandas as pd

RISKS=['base_risk','control_risk','model_risk']

def summarize(f):
    groups={'all':f,'seoul':f[f.meet.eq(1)],'busan':f[f.meet.eq(3)]}
    for year in [2024,2025,2026]:groups[str(year)]=f[f.year.eq(year)]
    for meet in [1,3]:
        for year in [2024,2025,2026]:groups[f'{meet}_{year}']=f[f.meet.eq(meet)&f.year.eq(year)]
    target=f.meet.eq(3)&f.grade_raw.eq('국5등급')&f.distance_m.isin([1300,1600])
    groups['busan_grade5_1300_1600']=f[target]
    groups['busan_grade5_1300_1600_2026']=f[target&f.year.eq(2026)]
    result={}
    for name,g in groups.items():
        z={'races':len(g),'failures':int(g.failure.sum()),'probability':{},'brier_comparisons':{},'axis_policies':{},'warning':{},'same_count_top20':{}}
        for risk in RISKS:
            z['probability'][risk]=c.probability_metrics(g.failure,g[risk])
            flagged=g[g[risk+'_warning']]
            z['warning'][risk]={'races':len(flagged),'coverage':len(flagged)/len(g),
                'failures':int(flagged.failure.sum()),'false_warnings':int(flagged.axis_hit.sum()),
                'precision':float(flagged.failure.mean()) if len(flagged) else None,
                'failure_recall':float(flagged.failure.sum()/g.failure.sum())}
            k=int(np.ceil(.2*len(g)));ix=np.argsort(-g[risk].to_numpy(float),kind='stable')[:k];top=g.iloc[ix]
            z['same_count_top20'][risk]={'races':k,'failures':int(top.failure.sum()),'precision':float(top.failure.mean()),
                'failure_recall':float(top.failure.sum()/g.failure.sum()),'retrospective_ranking_only':True}
        for baseline in ['base_risk','control_risk']:
            z['brier_comparisons'][baseline]=c.paired(g,baseline+'_brier','model_risk_brier')
        for policy in ['control','raw','selected']:
            z['axis_policies'][policy]=c.paired(g,'axis_hit',policy+'_hit')
            z['axis_policies'][policy]['switches']=int(g[policy+'_program_no'].ne(g.axis_program_no).sum())
            z['axis_policies'][policy]['relative_percent']=float((g[policy+'_hit'].mean()/g.axis_hit.mean()-1)*100)
        result[name]=z
    return result

def main():
    c.check();f=pd.read_parquet(c.OUT/'axis_examples.parquet')
    rr=pd.read_parquet(c.OUT/'conditional_runners.parquet')
    rg={k:g.sort_values('program_no') for k,g in rr.groupby('race_key',sort=False)}
    records=[];calibration=[]
    c.save(c.OUT/'evaluation_started.json',{'protocol_sha256':c.sha(c.OUT/'protocol_frozen.json'),
        'evaluate_code_sha256':c.sha(c.HERE/'evaluate_failure.py')})
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=c.OUT/'risk_models'/f'axis_failure_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
            pred=pd.read_parquet(folder/'predictions.parquet');pred=pred[pred.phase.eq('evaluation')]
            g=f[f.meet.eq(meet)&f.year.eq(year)].merge(pred[['race_key','model_raw_score','control_risk','model_risk']],on='race_key',validate='1:1')
            for row in g.itertuples():
                runners=rg[row.race_key]
                out={k:getattr(row,k) for k in ['race_key','race_date','meet','year','grade_raw','distance_m','field_size',
                    'axis_program_no','axis_horse_id','axis_outcome','axis_hit','failure','base_axis_probability',*RISKS]}
                out['policy_lambda']=meta['policy_lambda']
                for risk in RISKS:
                    out[risk+'_brier']=(out[risk]-row.failure)**2
                    out[risk+'_warning']=out[risk]>=meta['warning_thresholds'][risk]
                for policy,risk,lam in [('control',row.control_risk,1.),('raw',row.model_risk,1.),('selected',row.model_risk,meta['policy_lambda'])]:
                    program,hit,prob=c.pick(runners,risk,lam)
                    out[policy+'_program_no']=program;out[policy+'_hit']=hit;out[policy+'_probability']=prob
                records.append(out)
            print('Evaluated risk',meet,year,flush=True)
    m=pd.DataFrame(records);assert len(m)==4799 and not m.race_key.duplicated().any()
    for risk in RISKS:
        bucket=pd.cut(m[risk],bins=[0,.2,.3,.4,.5,.6,1],include_lowest=True,right=False)
        for bin_,g in m.groupby(bucket,observed=True):
            calibration.append({'risk':risk,'bin':str(bin_),'races':len(g),'failures':int(g.failure.sum()),
                'mean_probability':float(g[risk].mean()),'actual_failure_rate':float(g.failure.mean())})
    m.to_parquet(c.OUT/'race_predictions.parquet',index=False,compression='zstd')
    results=summarize(m);c.save(c.OUT/'results.json',results);c.save(c.OUT/'calibration_bins.json',calibration)
    a=results['all'];recent=results['2026']
    risk_pass=all(a['brier_comparisons'][b]['difference_ci95'][1]<0 and
        a['probability']['model_risk']['logloss']<=a['probability'][b]['logloss'] and
        recent['probability']['model_risk']['brier']<recent['probability'][b]['brier'] for b in ['base_risk','control_risk'])
    axis_pass=a['axis_policies']['selected']['difference_ci95'][0]>0 and recent['axis_policies']['selected']['difference']>=0
    c.save(c.OUT/'decision.json',{'risk_improvement_criterion_passed':bool(risk_pass),'axis_improvement_criterion_passed':bool(axis_pass),
        'ten_percent_relative_axis_improvement_achieved':a['axis_policies']['selected']['relative_percent']>=10,
        'production_changed':False,'independent_future_validation':False})
    print(json.dumps(a,ensure_ascii=False),flush=True);c.storage()

if __name__=='__main__':main()
