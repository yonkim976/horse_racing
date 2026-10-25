"""Prespecified-model diagnostics; no refit or model selection."""
import numpy as np
import pandas as pd
import experiment as a


def main():
    aux=pd.read_parquet(a.O/'aux_predictions.parquet')
    old=pd.read_parquet(a.PACE/'feature_context.parquet',columns=['row_key','lead_prior5'])
    aux=aux.merge(old,on='row_key',validate='one_to_one')
    reference=[];numerical_ties=[]
    for year,g in aux[aux.year.ge(2024)&aux.group_observed].groupby('year'):
        for key,z in g.groupby('source_key'):
            assert len(z)==z.field_size.iloc[0]
            record=dict(year=int(year),source_key=key,date=z.date.iloc[0].strftime('%Y-%m-%d'))
            canonical=z.sort_values(['raw_lead','gate'],ascending=[False,True]).iloc[0]
            for name in ['I','J']:
                floating=z.sort_values([name+'_front','gate'],ascending=[False,True]).iloc[0]
                if floating.gate!=canonical.gate:
                    assert abs(floating.raw_lead-canonical.raw_lead)<1e-12
                    numerical_ties.append(dict(source_key=key,model=name,
                        previous_gate=int(floating.gate),canonical_gate=int(canonical.gate),
                        raw_probability_difference=float(floating.raw_lead-canonical.raw_lead)))
            for name,col in [('H','lead_prior5'),('I','raw_lead'),('J','raw_lead')]:
                best=z.sort_values([col,'gate'],ascending=[False,True]).iloc[0]
                record[name+'_hit']=int(best.role4==0)
                record[name+'_gate']=int(best.gate)
            reference.append(record)
    rr=pd.DataFrame(reference)
    assert rr.I_gate.eq(rr.J_gate).all()
    a.save('numerical_tie_audit.json',dict(reason='Cardinality-only reweighting preserves horse order; raw-head order resolves floating ties.',
        cases=numerical_ties,finish_scores_changed=False,refits=0))
    rr.to_csv(a.O/'early_reference_races.csv',index=False)
    rows=[]
    for window in ['all','2024','2025','2026']:
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        for name in ['H','I','J']:
            rows.append(dict(window=window,model=name,races=len(z),
                             hits=int(z[name+'_hit'].sum()),hit_rate=float(z[name+'_hit'].mean())))
    pd.DataFrame(rows).to_csv(a.O/'early_reference_metrics.csv',index=False)
    contrasts=[]
    for window in ['all','2024','2025','2026']:
        z=rr if window=='all' else rr[rr.year.eq(int(window))]
        days=z.assign(delta=z.I_hit-z.H_hit).groupby('date').agg(total=('delta','sum'),n=('delta','size'))
        rng=np.random.default_rng(a.SEED)
        ix=rng.integers(0,len(days),size=(2000,len(days)))
        boots=days.total.to_numpy()[ix].sum(axis=1)/days.n.to_numpy()[ix].sum(axis=1)
        lo,hi=np.quantile(boots,[.025,.975])
        contrasts.append(dict(window=window,difference=float((z.I_hit-z.H_hit).mean()),
                              lower=float(lo),upper=float(hi)))
    pd.DataFrame(contrasts).to_csv(a.O/'early_reference_contrasts.csv',index=False)
    metrics=pd.read_csv(a.O/'race_metrics.csv')
    changed=metrics[metrics[['B_axis_program','D_axis_program','I_axis_program','J_axis_program']].nunique(axis=1)>1]
    changed.to_csv(a.O/'changed_axis_races.csv',index=False,encoding='utf-8-sig')
    calibration=[]
    for (year,model),g in pd.read_csv(a.O/'aux_race_metrics.csv').groupby(['year','model']):
        calibration.append(dict(year=int(year),model=model,actual_count_mean=float(g.actual_count.mean()),
                                 predicted_count_mean=float(g.predicted_count.mean())))
    pd.DataFrame(calibration).to_csv(a.O/'count_mean_diagnostics.csv',index=False)
    source=pd.read_csv(a.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv')
    count_reference=[]
    for year in a.YEARS:
        tr=source[source.year.lt(year)];te=source[source.year.eq(year)]
        tc=np.minimum(tr.leader_count.to_numpy()-1,2)
        yc=np.minimum(te.leader_count.to_numpy()-1,2)
        prior=(np.bincount(tc,minlength=3)+1)/(len(tr)+3)
        count_reference.append(dict(year=year,train_races=len(tr),test_races=len(te),
          training_mode_class=int(prior.argmax()),accuracy=float((yc==prior.argmax()).mean()),
          count_brier=float(np.square(prior-np.eye(3)[yc]).sum(axis=1).mean()),
          count_nll=float(-np.log(prior[yc]).mean()),
          expected_count=float(tr.leader_count.mean()),
          count_mae=float(abs(te.leader_count-tr.leader_count.mean()).mean())))
    pd.DataFrame(count_reference).to_csv(a.O/'count_reference_metrics.csv',index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__=='__main__':main()
