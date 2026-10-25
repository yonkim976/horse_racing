"""Fixed all-race evaluation; calibration retains the original ticket policy."""
import json
from collections import defaultdict
import numpy as np
import pandas as pd
import support as s
import calibrate as cal

def fixed_score(g,scores,orders,mass,selected,variant):
    row,_,runners=s.scorer.score_race(g,scores,orders,mass,variant,'all_starters')
    m=s.prob.marginals(len(g),orders,mass);outcome=g.outcome.to_numpy(int)
    axis=selected['axis'];ar=g.iloc[axis]
    row.update(axis_program_no=int(ar.program_no),axis_history_count=float(ar.history_count),
        axis_front_probability=float(ar.front_gate_probability),axis_late600=float(ar.section_last600_mean3),
        axis_late200=float(ar.section_late_mean3),axis_top3=int(1<=outcome[axis]<=3),axis_probability=float(m['top3'][axis]))
    tickets=[]
    for pool in ['quinella','qpl']:
        selected_pairs=selected[pool];limit=2 if pool=='quinella' else 3
        prob=[];hits=[];event=np.zeros(len(mass),bool)
        for rank,(a,b) in enumerate(selected_pairs,1):
            probability=float(m[pool][a,b]);hit=int(1<=outcome[a]<=limit and 1<=outcome[b]<=limit)
            prob.append(probability);hits.append(hit)
            event|=(orders[:,:limit]==a).any(axis=1)&(orders[:,:limit]==b).any(axis=1)
            tickets.append({'race_key':ar.race_key,'variant':variant,'pool':pool,'rank':rank,
                'program_a':int(g.program_no.iloc[a]),'program_b':int(g.program_no.iloc[b]),'probability':probability,'hit':hit})
        prefix='qnl' if pool=='quinella' else 'qpl'
        row[pool+'_one']=hits[0];row[pool+'_three']=int(any(hits))
        row[prefix+'1_probability']=prob[0];row[prefix+'3_probability']=float(mass[event].sum())
        if pool=='qpl':row['qpl_count']=sum(hits);row['qpl_expected_count']=sum(prob)
    for prefix,outcome_key in [('axis','axis_top3'),('qnl1','quinella_one'),('qnl3','quinella_three'),('qpl1','qpl_one'),('qpl3','qpl_three')]:
        row[prefix+'_brier']=(row[prefix+'_probability']-row[outcome_key])**2
    return row,tickets,runners

def add_bins(acc,row):
    for label,pred,true in [('axis','axis_probability','axis_top3'),('qnl1','qnl1_probability','quinella_one'),
        ('qnl3','qnl3_probability','quinella_three'),('qpl1','qpl1_probability','qpl_one'),('qpl3','qpl3_probability','qpl_three')]:
        value=float(row[pred]);bin_id=min(9,int(value*10))
        v=acc[(row['variant'],row['meet'],row['year'],label,bin_id)]
        v[0]+=1;v[1]+=value;v[2]+=int(row[true])

def main():
    s.check();assert (s.OUT/'training_complete.json').exists() and (s.OUT/'calibration_complete.json').exists()
    assert not (s.OUT/'evaluation_complete.json').exists()
    f=s.frame();f=f[f.year.ge(2024)].copy()
    flags=pd.read_parquet(s.old.BASE/'outputs/population_flags.parquet')
    f=f.merge(flags[s.KEY+['normal_finisher','ambiguous_flag']],on=s.KEY,validate='one_to_one')
    metrics=[];tickets=[];runners=[];bins=defaultdict(lambda:[0,0.,0])
    for variant in [*s.contracts(),'calibration']:
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=(s.PREV/'outputs/models'/f'state_gbm_{meet}_{year}' if variant=='calibration' else s.OUT/'models'/f'{variant}_{meet}_{year}')
                meta=json.loads((folder/'metadata.json').read_text())
                scores=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
                one=f[f.meet.eq(meet)&f.year.eq(year)].copy();one['score']=one.row_number.map(scores)
                assert one.score.notna().all()
                if variant=='calibration':params=json.loads((s.OUT/'calibrators'/f'{meet}_{year}.json').read_text())
                for _,g in one.groupby('race_key',sort=False):
                    score=g.score.to_numpy(float);q=s.prob.trio_distribution(score,meta['temperature'])
                    orders,mass=s.prob.ordered_distribution(score,q,meta['order_temperature'])
                    if variant=='calibration':
                        for name,key in [('cal_candidate','beta'),('cal_selected','applied_beta')]:
                            new,_,_,select=cal.transform(orders,mass,np.array(params[key]))
                            row,tt,rr=fixed_score(g,score,orders,new,select,name)
                            metrics.append(row);tickets.extend(tt);runners.append(rr);add_bins(bins,row)
                    else:
                        row,tt,rr=s.scorer.score_race(g,score,orders,mass,variant,'all_starters')
                        metrics.append(row);tickets.extend(tt);runners.append(rr);add_bins(bins,row)
                print('Evaluated',variant,meet,year,flush=True)
    pd.DataFrame(metrics).to_parquet(s.OUT/'race_metrics.parquet',index=False,compression='zstd')
    pd.DataFrame(tickets).to_parquet(s.OUT/'tickets.parquet',index=False,compression='zstd')
    pd.concat(runners,ignore_index=True).to_parquet(s.OUT/'runner_probabilities.parquet',index=False,compression='zstd')
    s.save(s.OUT/'calibration_bins.json',[{'variant':v,'meet':m,'year':y,'target':t,'bin':b,'count':x[0],
        'probability_sum':x[1],'hits':x[2]} for (v,m,y,t,b),x in bins.items()])
    s.save(s.OUT/'evaluation_complete.json',{'new_variants':5,'race_rows':len(metrics),'tickets':len(tickets),
        'runner_rows':sum(map(len,runners)),'max_coherence_error':max(r['coherence_max_error'] for r in metrics),
        'recommendation_changes_from_calibration':0,'new_future_test':False})
    print('Evaluation done',s.storage(),flush=True)

if __name__=='__main__':main()
