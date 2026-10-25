"""Fixed race-level selections, pair probabilities and date-cluster comparisons."""
import json
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control
import data as d
import train as tr


def boot(z,new,old,metric):
    delta=z[new+'_'+metric]-z[old+'_'+metric]
    dates=z.assign(delta=delta).groupby('date').agg(total=('delta','sum'),n=('delta','size'))
    rng=np.random.default_rng(d.SEED);ix=rng.integers(0,len(dates),size=(2000,len(dates)))
    estimates=dates.total.to_numpy()[ix].sum(axis=1)/dates.n.to_numpy()[ix].sum(axis=1)
    low,high=np.quantile(estimates,[.025,.975]);observed=float(delta.mean())
    p=(1+np.sum(abs(estimates-observed)>=abs(observed)))/2001
    return dict(difference=observed,lower=float(low),upper=float(high),p_boot=float(p),
        gained=int(((z[new+'_'+metric]>0)&(z[old+'_'+metric]==0)).sum()),
        lost=int(((z[new+'_'+metric]==0)&(z[old+'_'+metric]>0)).sum()))


def evaluate_races(scores,pairs):
    results=[]
    groups={key:g for key,g in pairs.groupby('source_key',sort=False)}
    for key,g in scores[scores.year.ge(2024)].groupby('source_key',sort=True):
        pp=groups[key].copy();g=g.copy()
        rank=dict(zip(g.program_no.astype(int),g.finish_rank.astype(int)))
        record=dict(source_key=key,date=str(g.date.iloc[0]),year=int(g.year.iloc[0]),
                    distance=int(g.distance.iloc[0]),grade=str(g.grade.iloc[0]),n=len(g))
        for name in ['B','J','H','S','PB','PF']:
            if name in ['PB','PF']:
                tag='base' if name=='PB' else 'full'
                score=pp['p_both_top3_'+tag]
                strength={number:0. for number in rank}
                for a,b,v in zip(pp.a_program,pp.b_program,score):
                    strength[int(a)]+=float(v);strength[int(b)]+=float(v)
                anchor=sorted(strength,key=lambda x:(-strength[x],x))[0]
                qn=pp.sort_values(['p_quinella_'+tag,'a_program','b_program'],ascending=[False,True,True]).head(3)
                qpl=pp.sort_values(['p_both_top3_'+tag,'a_program','b_program'],ascending=[False,True,True]).head(3)
            else:
                current=g.sort_values(['score_'+name,'program_no'],ascending=[False,True]);anchor=int(current.program_no.iloc[0])
                lookup=g.set_index('program_no')['score_'+name]
                pp['_sum']=pp.a_program.map(lookup)+pp.b_program.map(lookup)
                qn=pp.sort_values(['_sum','a_program','b_program'],ascending=[False,True,True]).head(3)
                qpl=qn
            record[name+'_axis_top3']=int(rank[anchor]<=3)
            record[name+'_axis_top2']=int(rank[anchor]<=2)
            record[name+'_axis_program']=anchor
            record[name+'_quinella_one']=int(qn.quinella.iloc[0])
            record[name+'_quinella_three']=int(qn.quinella.any())
            record[name+'_qpl_one']=int(qpl.both_top3.iloc[0])
            record[name+'_qpl_three_any']=int(qpl.both_top3.any())
            record[name+'_qpl_three_count']=int(qpl.both_top3.sum())
            record[name+'_qn_pair']=f'{int(qn.a_program.iloc[0])}-{int(qn.b_program.iloc[0])}'
            record[name+'_qpl_pair']=f'{int(qpl.a_program.iloc[0])}-{int(qpl.b_program.iloc[0])}'
        results.append(record)
    rr=pd.DataFrame(results);assert len(rr)==1976
    rr.to_csv(d.O/'race_metrics.csv',index=False,encoding='utf-8-sig')
    metrics=['axis_top3','axis_top2','quinella_one','quinella_three','qpl_one','qpl_three_any','qpl_three_count']
    summary=[]
    for window in ['all','2024','2025','2026']:
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        for name in ['B','J','H','S','PB','PF']:
            row=dict(window=window,model=name,races=len(z))
            for metric in metrics:
                row[metric]=float(z[name+'_'+metric].mean());row[metric+'_total']=int(z[name+'_'+metric].sum())
            summary.append(row)
    pd.DataFrame(summary).to_csv(d.O/'selection_metrics.csv',index=False)
    contrasts=[]
    for window in ['all','2024','2025','2026']:
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        for new,old in [('S','H'),('H','J'),('S','J'),('PF','PB'),('PF','S'),('S','B'),('PF','B')]:
            for metric in ['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three_any','qpl_three_count']:
                contrasts.append(dict(window=window,new=new,old=old,metric=metric,n=len(z))|boot(z,new,old,metric))
    dif=pd.DataFrame(contrasts)
    primary=dif.window.eq('all')&(((dif.new=='S')&(dif.old=='H')&dif.metric.isin(['axis_top3','quinella_one']))|
              ((dif.new=='PF')&(dif.old=='PB')&dif.metric.isin(['axis_top3','quinella_one','qpl_one'])))
    assert primary.sum()==5
    dif.loc[primary,'bh_q_primary5']=false_discovery_control(dif.loc[primary,'p_boot'])
    dif.to_csv(d.O/'paired_comparisons.csv',index=False)
    subgroups=[]
    for variable in ['distance','grade']:
        for (year,value),g in rr.groupby(['year',variable]):
            for name in ['J','H','S','PB','PF']:
                subgroups.append(dict(year=int(year),condition=variable,value=str(value),model=name,races=len(g),
                    axis_top3=float(g[name+'_axis_top3'].mean()),quinella_one=float(g[name+'_quinella_one'].mean()),
                    qpl_one=float(g[name+'_qpl_one'].mean())))
    pd.DataFrame(subgroups).to_csv(d.O/'subgroup_metrics.csv',index=False)
    changed=rr[(rr.S_axis_program!=rr.J_axis_program)|(rr.PF_axis_program!=rr.S_axis_program)]
    changed.to_csv(d.O/'changed_choices.csv',index=False,encoding='utf-8-sig')
    return rr


def probability_metrics(q,late,aux,pairs):
    z=late[late.year.ge(2024)].merge(aux[['row_key','J_top3_mixture']],on='row_key',validate='one_to_one')
    rows=[];cal=[]
    for year in [2024,2025,2026]:
        g=z[z.year.eq(year)]
        for target,col in [('g3front','chain_g3_front'),('g1front','chain_g1_front'),
                           ('top3','chain_top3'),('top3','J_top3_mixture')]:
            use=g[g[target].notna()];p=use[col].to_numpy();y=use[target].to_numpy()
            rows.append(dict(year=year,target=target,model=col,starts=len(use),
                 observed=float(y.mean()),predicted=float(p.mean()),brier=float(np.square(p-y).mean())))
            for b,h in use.assign(bin=np.minimum((use[col]*10).astype(int),9)).groupby('bin'):
                cal.append(dict(year=year,target=target,model=col,bin=int(b),n=len(h),
                                predicted=float(h[col].mean()),actual=float(h[target].mean())))
    pd.DataFrame(rows).to_csv(d.O/'late_probability_metrics.csv',index=False)
    pd.DataFrame(cal).to_csv(d.O/'late_calibration.csv',index=False)
    selection=[]
    for (year,normal,observed),g in z.assign(late_observed=z.g1front.notna()).groupby(['year','normal_outcome','late_observed']):
        selection.append(dict(year=int(year),normal=bool(normal),g1_observed=bool(observed),n=len(g),
             actual_top3=float(g.top3.mean()),chain_mean=float(g.chain_top3.mean()),
             prior_mean=float(g.J_top3_mixture.mean())))
    pd.DataFrame(selection).to_csv(d.O/'late_selection_calibration.csv',index=False)
    pair_quality=[];pair_cal=[]
    for year,g in pairs.groupby('year'):
        for target in ['both_top3','quinella']:
            for model in ['base','full']:
                col='p_'+target+'_'+model;p=np.clip(g[col].to_numpy(),1e-12,1-1e-12);y=g[target].to_numpy();w=g.race_weight.to_numpy()
                pair_quality.append(dict(year=int(year),target=target,model=model,pairs=len(g),
                    races=g.source_key.nunique(),brier=float(np.average((p-y)**2,weights=w)),
                    logloss=float(np.average(-y*np.log(p)-(1-y)*np.log1p(-p),weights=w)),
                    predicted=float(np.average(p,weights=w)),actual=float(np.average(y,weights=w))))
                bins=pd.cut(g[col],[0,.02,.05,.1,.2,.3,.5,1],include_lowest=True).astype(str)
                for b,h in g.assign(bin=bins).groupby('bin'):
                    pair_cal.append(dict(year=int(year),target=target,model=model,bin=b,n=len(h),
                        predicted=float(np.average(h[col],weights=h.race_weight)),
                        actual=float(np.average(h[target],weights=h.race_weight))))
    pd.DataFrame(pair_quality).to_csv(d.O/'pair_probability_metrics.csv',index=False)
    pd.DataFrame(pair_cal).to_csv(d.O/'pair_calibration.csv',index=False)


def main():
    d.check();q,h,x,races,aux,p,j=d.load()
    late=pd.read_parquet(d.O/'late_predictions.parquet')
    scores=pd.read_parquet(d.O/'external_scores.parquet')
    pairs=pd.read_parquet(d.O/'pair_predictions.parquet')
    rr=evaluate_races(scores,pairs);probability_metrics(q,late,aux,pairs)
    d.check()
    print(pd.read_csv(d.O/'selection_metrics.csv').to_string(index=False),flush=True)
    print(pd.read_csv(d.O/'paired_comparisons.csv').query("window == 'all' and bh_q_primary5 == bh_q_primary5").to_string(index=False),flush=True)


if __name__=='__main__':main()
