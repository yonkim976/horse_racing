"""Race-weighted summaries, paired date bootstrap, and gain/loss ledgers."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit
from threadpoolctl import threadpool_limits

import run as r

HITS=["axis_top3","quinella_one","quinella_three","qpl_one","qpl_three"]
METRICS=HITS+["qpl_count","runner_brier","quinella_brier","qpl_brier","trio_logloss",
    "axis_brier","qnl1_brier","qnl3_brier","qpl1_brier","qpl3_brier"]
COMPARISONS=[("early47","ability22"),("late66","ability22"),("additive89","early47"),
    ("additive89","late66"),("full103","additive89"),("full103_pair","full103"),
    ("ability22","full103"),("early47","full103"),("late66","full103"),("additive89","full103")]


def strata(g):
    yield "overall","all",g
    for cols in [["year"],["meet"],["distance_m"],["grade"],["year","meet"],
                 ["meet","distance_m"],["year","distance_m"],["year","grade"]]:
        for key,v in g.groupby(cols,dropna=False,sort=True):
            parts=key if isinstance(key,tuple) else (key,)
            yield "+".join(cols),"/".join(str(z) for z in parts),v


def aggregate(frame):
    rows=[]
    for (scope,variant),g in frame.groupby(["scope","variant"],sort=True):
        for dimension,level,z in strata(g):
            row=dict(scope=scope,variant=variant,dimension=dimension,level=level,
                races=len(z),starts=int(z.field_size.sum()),days=int(z.race_date.nunique()))
            row.update({c:float(z[c].mean()) for c in METRICS})
            row.update({c+"_hits":int(z[c].sum()) for c in HITS})
            row.update({f"qpl_count_{i}_races":int(z.qpl_count.eq(i).sum()) for i in range(4)})
            row["qpl_hits_total"]=int(z.qpl_count.sum())
            row["legacy_quinella_one"]=float(z.legacy_quinella_one.mean())
            row["legacy_quinella_three"]=float(z.legacy_quinella_three.mean())
            rows.append(row)
    return pd.DataFrame(rows)


def paired(frame):
    records=[]
    for scope,g in frame.groupby("scope",sort=True):
        slices=[("all",g)]+[(str(y),g[g.year.eq(y)]) for y in [2024,2025,2026]]
        slices += [("venue"+str(v),g[g.meet.eq(v)]) for v in [1,3]]
        for period,z in slices:
            reference=z[z.variant.eq("full103")].sort_values("race_key")
            dates=sorted(reference.race_date.unique())
            rng=np.random.default_rng(r.cfg()["bootstrap_seed"])
            weights=rng.multinomial(len(dates),np.ones(len(dates))/len(dates),size=r.cfg()["bootstrap_draws"])
            for new,old in COMPARISONS:
                a=z[z.variant.eq(new)].set_index("race_key").sort_index()
                b=z[z.variant.eq(old)].set_index("race_key").sort_index()
                assert a.index.equals(b.index) and a.race_date.equals(b.race_date)
                d=a[METRICS]-b[METRICS]
                bydate=d.groupby(a.race_date).sum().reindex(dates)
                ns=a.groupby("race_date").size().reindex(dates).to_numpy()
                samples=(weights@bydate.to_numpy())/(weights@ns)[:,None]
                lo,hi=np.quantile(samples,[.025,.975],axis=0)
                for j,c in enumerate(METRICS):
                    records.append(dict(scope=scope,period=period,candidate=new,baseline=old,metric=c,
                        races=len(a),days=len(dates),baseline_mean=float(b[c].mean()),candidate_mean=float(a[c].mean()),
                        difference=float(d[c].mean()),ci_low=float(lo[j]),ci_high=float(hi[j]),
                        gains=int(((a[c]>b[c])&(c in HITS)).sum()),losses=int(((a[c]<b[c])&(c in HITS)).sum())))
    return pd.DataFrame(records)


def gain_loss(frame):
    g=frame[frame.scope.eq("all_starters")]
    base=g[g.variant.eq("full103")].set_index("race_key")
    details=[];summaries=[]
    for variant in [v for v in r.cfg()["variants"] if v!="full103"]:
        a=g[g.variant.eq(variant)].set_index("race_key").loc[base.index]
        d=a[["race_date","year","meet","distance_m","grade","field_size","minimum_history",
             "axis_program_no","axis_history_count","axis_front_probability","axis_late600","axis_late200"]].copy()
        d["variant"]=variant
        d["baseline_axis"]=base.axis_program_no
        d["axis_changed"]=a.axis_program_no.ne(base.axis_program_no)
        d["baseline_axis_front_probability"]=base.axis_front_probability
        d["baseline_axis_late600"]=base.axis_late600
        d["baseline_axis_late200"]=base.axis_late200
        d["history_band"]=np.where(d.minimum_history.eq(0),"any_no_history","all_have_history")
        d["field_band"]=np.where(d.field_size.le(8),"up_to_8","9_plus")
        for c in HITS+["qpl_count"]:
            d[c+"_baseline"]=base[c];d[c+"_candidate"]=a[c];d[c+"_difference"]=a[c]-base[c]
        details.append(d.reset_index())
        groups=list(strata(d))
        for col in ["history_band","field_band"]:
            groups += [(col,str(key),z) for key,z in d.groupby(col)]
        for dimension,level,z in groups:
            for c in HITS:
                summaries.append(dict(candidate=variant,baseline="full103",dimension=dimension,level=level,
                    metric=c,races=len(z),gains=int(z[c+"_difference"].eq(1).sum()),
                    losses=int(z[c+"_difference"].eq(-1).sum()),net=int(z[c+"_difference"].sum())))
    pd.concat(details,ignore_index=True).to_parquet(r.OUT/"gain_loss_races.parquet",index=False,compression="zstd")
    pd.DataFrame(summaries).to_csv(r.OUT/"gain_loss_conditions.csv",index=False)


def calibration_diagnostics(frame):
    bins=pd.read_csv(r.OUT/"calibration_bins.csv")
    overall=bins.groupby(["variant","target","bin"],as_index=False)[["observations","race_weight","probability_sum","hit_sum"]].sum()
    overall["predicted"]=overall.probability_sum/overall.race_weight
    overall["observed"]=overall.hit_sum/overall.race_weight
    overall.to_csv(r.OUT/"calibration_overall.csv",index=False)
    rows=[]
    for (variant,target),z in overall.groupby(["variant","target"]):
        rows.append(dict(variant=variant,target=target,
            ece=float(np.average(np.abs(z.predicted-z.observed),weights=z.race_weight)),
            predicted=float(z.probability_sum.sum()/z.race_weight.sum()),
            observed=float(z.hit_sum.sum()/z.race_weight.sum()),
            observations=int(z.observations.sum()),race_weight=float(z.race_weight.sum())))
    pd.DataFrame(rows).to_csv(r.OUT/"calibration_summary.csv",index=False)
    # Diagnostic fit on evaluation predictions only; never fed back into inference.
    fits=[]
    main=frame[frame.scope.eq("all_starters")]
    for variant,g in main.groupby("variant"):
        for target,pc,yc in [("axis","axis_probability","axis_top3"),("qnl1","qnl1_probability","quinella_one"),
            ("qnl3","qnl3_probability","quinella_three"),("qpl1","qpl1_probability","qpl_one"),
            ("qpl3","qpl3_probability","qpl_three")]:
            x=logit(np.clip(g[pc].to_numpy(),1e-8,1-1e-8));y=g[yc].to_numpy()
            def objective(b):
                v=b[0]+b[1]*x
                loss=np.mean(np.logaddexp(0,v)-y*v)
                delta=expit(v)-y
                return loss,np.array([delta.mean(),np.mean(delta*x)])
            fit=minimize(objective,np.array([0.,1.]),jac=True,method="BFGS")
            fits.append(dict(variant=variant,target=target,intercept=float(fit.x[0]),slope=float(fit.x[1]),
                success=bool(fit.success),note="Evaluation diagnostic only; not applied"))
    pd.DataFrame(fits).to_csv(r.OUT/"calibration_diagnostic_slopes.csv",index=False)


def policy_comparison(frame):
    """The predeclared old fixed-axis vs all-pair selection control, same model."""
    main=frame[(frame.scope=="all_starters")&(frame.variant=="full103")]
    rows=[]
    for period,g in [("all",main)]+[(str(y),main[main.year.eq(y)]) for y in [2024,2025,2026]]:
        dates=sorted(g.race_date.unique())
        rng=np.random.default_rng(r.cfg()["bootstrap_seed"])
        weights=rng.multinomial(len(dates),np.ones(len(dates))/len(dates),size=r.cfg()["bootstrap_draws"])
        ns=g.groupby("race_date").size().reindex(dates).to_numpy()
        for metric in ["quinella_one","quinella_three"]:
            d=g[metric]-g["legacy_"+metric]
            total=d.groupby(g.race_date).sum().reindex(dates).to_numpy()
            samples=(weights@total)/(weights@ns)
            lo,hi=np.quantile(samples,[.025,.975])
            rows.append(dict(period=period,metric=metric,races=len(g),old_hits=int(g["legacy_"+metric].sum()),
                new_hits=int(g[metric].sum()),gains=int(d.eq(1).sum()),losses=int(d.eq(-1).sum()),
                difference=float(d.mean()),ci_low=float(lo),ci_high=float(hi)))
    pd.DataFrame(rows).to_csv(r.OUT/"policy_comparison.csv",index=False)


def main():
    frame=pd.read_parquet(r.OUT/"race_metrics.parquet")
    assert frame.groupby(["scope","variant"]).size().eq(4799).all()
    assert not frame.duplicated(["scope","variant","race_key"]).any()
    agg=aggregate(frame);agg.to_csv(r.OUT/"metrics.csv",index=False)
    with threadpool_limits(limits=2):
        diffs=paired(frame)
    diffs.to_csv(r.OUT/"paired_differences.csv",index=False)
    gain_loss(frame)
    calibration_diagnostics(frame)
    policy_comparison(frame)
    clean=frame[~frame.ambiguous_race]
    aggregate(clean).to_csv(r.OUT/"unambiguous_metrics.csv",index=False)
    baseline=frame[(frame.scope=="all_starters")&(frame.variant=="full103")]
    decisions=[]
    for variant in [v for v in r.cfg()["variants"] if v!="full103"]:
        g=frame[(frame.scope=="all_starters")&(frame.variant==variant)].set_index("race_key").loc[baseline.race_key]
        ci=diffs[(diffs.scope=="all_starters")&(diffs.period=="all")&(diffs.candidate==variant)&(diffs.baseline=="full103")]
        axis=ci[ci.metric=="axis_top3"].iloc[0]
        annual={str(y):float(g[g.year.eq(y)].axis_top3.mean()-baseline[baseline.year.eq(y)].axis_top3.mean()) for y in [2024,2025,2026]}
        counts_ok=all(float(g[c].mean()-baseline[c].mean())>=-1e-12 for c in HITS[1:]+["qpl_count"])
        brier_ok=all(float(g[c].mean()-baseline[c].mean())<=1e-12 for c in ["runner_brier","quinella_brier","qpl_brier"])
        passed=bool(axis.ci_low>0 and min(annual.values())>=-1e-12 and counts_ok and brier_ok)
        decisions.append(dict(variant=variant,improvement_gate_passed=passed,axis_ci_lower=float(axis.ci_low),
            annual_axis_differences=annual,all_pair_hit_metrics_nonworse=counts_ok,all_brier_nonworse=brier_ok))
    r.save(r.OUT/"decision.json",dict(general_improvement_confirmed=any(x["improvement_gate_passed"] for x in decisions),
        candidates=decisions,new_test_data=False,production_comparison=False,no_more_search=True))
    print(agg[(agg.scope=="all_starters")&(agg.dimension=="overall")][["variant","races",*HITS,"qpl_count","runner_brier","quinella_brier","qpl_brier"]].to_string(index=False))
    r.storage_check()


if __name__=="__main__":
    main()
