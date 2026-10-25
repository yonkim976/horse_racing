"""Paired, race-weighted analysis of the frozen follow-up outputs."""
from __future__ import annotations
import json
from collections import defaultdict

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import common as c
import summarize as previous

HITS=["axis_top3","quinella_one","quinella_three","qpl_one","qpl_three"]
METRICS=HITS+["qpl_count","runner_brier","quinella_brier","qpl_brier","trio_logloss",
    "ordered_logloss","quinella_logloss","conditional_third_logloss",
    "axis_brier","qnl1_brier","qnl3_brier","qpl1_brier","qpl3_brier"]


def load_results():
    old=pd.read_parquet(c.BASE/"outputs/race_metrics.parquet")
    old=old[old.variant.isin(c.cfg()["baselines"])]
    extra=pd.read_parquet(c.OUT/"baseline_extra_metrics.parquet")
    old=old.merge(extra,on=["race_key","variant","scope"],validate="one_to_one")
    new=pd.read_parquet(c.OUT/"race_metrics.parquet")
    all_results=pd.concat([old,new],ignore_index=True)
    assert not all_results.duplicated(["scope","variant","race_key"]).any()
    assert all_results.groupby(["scope","variant"]).size().eq(4799).all()
    return all_results


def aggregate(frame):
    rows=[]
    for (scope,variant),g in frame.groupby(["scope","variant"],sort=True):
        for dimension,level,z in previous.strata(g):
            row=dict(scope=scope,variant=variant,dimension=dimension,level=level,
                races=len(z),starts=int(z.field_size.sum()),days=int(z.race_date.nunique()))
            row.update({m:float(z[m].mean()) for m in METRICS})
            row.update({m+"_hits":int(z[m].sum()) for m in HITS})
            row.update({f"qpl_count_{k}_races":int(z.qpl_count.eq(k).sum()) for k in range(4)})
            row["qpl_hits_total"]=int(z.qpl_count.sum())
            rows.append(row)
    return pd.DataFrame(rows)


def paired(frame):
    comparisons=[(v,b) for v in c.cfg()["new_variants"] for b in c.cfg()["baselines"]]
    comparisons += [("top2_89","top2_22"),("top2_89","crossF"),("top2_22","crossF")]
    rows=[]
    for scope,g in frame.groupby("scope",sort=True):
        periods=[("all",g)]+[(str(y),g[g.year.eq(y)]) for y in c.cfg()["evaluation_years"]]
        periods += [(f"venue{v}",g[g.meet.eq(v)]) for v in c.cfg()["venues"]]
        for period,z in periods:
            ref=z[z.variant.eq("full103")].sort_values("race_key")
            dates=sorted(ref.race_date.unique())
            rng=np.random.default_rng(c.cfg()["bootstrap_seed"])
            weights=rng.multinomial(len(dates),np.ones(len(dates))/len(dates),size=c.cfg()["bootstrap_draws"])
            for candidate,baseline in comparisons:
                a=z[z.variant.eq(candidate)].set_index("race_key").sort_index()
                b=z[z.variant.eq(baseline)].set_index("race_key").sort_index()
                assert a.index.equals(b.index) and a.race_date.equals(b.race_date)
                d=a[METRICS]-b[METRICS]
                totals=d.groupby(a.race_date).sum().reindex(dates).to_numpy()
                ns=a.groupby("race_date").size().reindex(dates).to_numpy()
                boot=(weights@totals)/(weights@ns)[:,None]
                lo99,lo,hi,hi99=np.quantile(boot,[.005,.025,.975,.995],axis=0)
                for j,m in enumerate(METRICS):
                    rows.append(dict(scope=scope,period=period,candidate=candidate,baseline=baseline,metric=m,
                        races=len(a),days=len(dates),candidate_mean=float(a[m].mean()),baseline_mean=float(b[m].mean()),
                        difference=float(d[m].mean()),ci_low=float(lo[j]),ci_high=float(hi[j]),
                        ci_99_low=float(lo99[j]),ci_99_high=float(hi99[j]),
                        gains=int((d[m]>0).sum()) if m in HITS else None,
                        losses=int((d[m]<0).sum()) if m in HITS else None))
    return pd.DataFrame(rows)


def gain_loss(frame):
    g=frame[frame.scope.eq("all_starters")]
    details=[];groups=[]
    for candidate in c.cfg()["new_variants"]:
        a=g[g.variant.eq(candidate)].set_index("race_key").sort_index()
        for baseline in c.cfg()["baselines"]:
            b=g[g.variant.eq(baseline)].set_index("race_key").loc[a.index]
            d=a[["race_date","year","meet","distance_m","grade","field_size","minimum_history",
                 "axis_program_no","axis_front_probability","axis_late600","axis_late200"]].copy()
            d["candidate"]=candidate;d["baseline"]=baseline;d["baseline_axis_program_no"]=b.axis_program_no
            d["history_band"]=np.where(d.minimum_history.eq(0),"any_no_history","all_have_history")
            for m in HITS+["qpl_count"]:
                d[m+"_candidate"]=a[m];d[m+"_baseline"]=b[m];d[m+"_difference"]=a[m]-b[m]
            details.append(d.reset_index())
            strata=list(previous.strata(d))+[("history_band",str(k),z) for k,z in d.groupby("history_band")]
            for dimension,level,z in strata:
                for m in HITS:
                    groups.append(dict(candidate=candidate,baseline=baseline,dimension=dimension,level=level,
                        metric=m,races=len(z),gains=int(z[m+"_difference"].eq(1).sum()),
                        losses=int(z[m+"_difference"].eq(-1).sum()),net=int(z[m+"_difference"].sum())))
    pd.concat(details,ignore_index=True).to_parquet(c.OUT/"gain_loss_races.parquet",index=False,compression="zstd")
    pd.DataFrame(groups).to_csv(c.OUT/"gain_loss_conditions.csv",index=False)


def calibration():
    old=pd.read_csv(c.BASE/"outputs/calibration_bins.csv")
    old=old[old.variant.isin(c.cfg()["baselines"])]
    bins=pd.concat([old,pd.read_csv(c.OUT/"calibration_bins.csv")],ignore_index=True)
    all_bins=bins.groupby(["variant","target","bin"],as_index=False)[["observations","race_weight","probability_sum","hit_sum"]].sum()
    all_bins["predicted"]=all_bins.probability_sum/all_bins.race_weight
    all_bins["observed"]=all_bins.hit_sum/all_bins.race_weight
    all_bins.to_csv(c.OUT/"calibration_overall.csv",index=False)
    rows=[]
    for (variant,target),z in all_bins.groupby(["variant","target"]):
        rows.append(dict(variant=variant,target=target,ece=float(np.average(abs(z.predicted-z.observed),weights=z.race_weight)),
            predicted=float(z.probability_sum.sum()/z.race_weight.sum()),observed=float(z.hit_sum.sum()/z.race_weight.sum()),
            observations=int(z.observations.sum()),race_weight=float(z.race_weight.sum())))
    pd.DataFrame(rows).to_csv(c.OUT/"calibration_summary.csv",index=False)


def decision(frame,differences):
    main=frame[frame.scope.eq("all_starters")]
    rows=[]
    for variant in c.cfg()["new_variants"]:
        a=main[main.variant.eq(variant)].set_index("race_key").sort_index()
        f=main[main.variant.eq("full103")].set_index("race_key").loc[a.index]
        el=main[main.variant.eq("additive89")].set_index("race_key").loc[a.index]
        d=differences[(differences.scope=="all_starters")&(differences.period=="all")&(differences.candidate==variant)]
        axis=d[(d.baseline=="full103")&(d.metric=="axis_top3")].iloc[0]
        qnl=d[(d.baseline=="additive89")&(d.metric=="quinella_three")].iloc[0]
        pair_ok=all((a[m]-f[m]).mean()>=-1e-12 for m in HITS[1:]+["qpl_count"])
        brier_ok=all((a[m]-f[m]).mean()<=1e-12 for m in ["runner_brier","quinella_brier","qpl_brier"])
        yearly={str(y):float((a[a.year.eq(y)].axis_top3-f[f.year.eq(y)].axis_top3).mean()) for y in c.cfg()["evaluation_years"]}
        protected=all((a[m]-el[m]).mean()>=-1e-12 for m in ["axis_top3","qpl_one","qpl_three","qpl_count","quinella_one"])
        qnl_proper=all((a[m]-el[m]).mean()<=1e-12 for m in ["quinella_brier","quinella_logloss"])
        rows.append(dict(variant=variant,general_improvement_vs_f=bool(axis.ci_low>0 and min(yearly.values())>=-1e-12 and pair_ok and brier_ok),
            axis_95_low_vs_f=float(axis.ci_low),annual_axis_vs_f=yearly,pair_hit_nonworse_vs_f=bool(pair_ok),
            brier_nonworse_vs_f=bool(brier_ok),quinella_specialization_vs_el=bool(protected and qnl_proper and qnl.ci_99_low>0),
            quinella_three_99_low_vs_el=float(qnl.ci_99_low),protected_hits_nonworse_vs_el=bool(protected),
            quinella_proper_scores_nonworse_vs_el=bool(qnl_proper)))
    c.save(c.OUT/"decision.json",{"candidates":rows,"new_independent_test_data":False,
        "further_search_stopped":True,"production_changed":False,
        "family_interval":"99% CI used for the five predeclared QNL3-vs-EL primary comparisons"})


def main():
    c.check_inputs()
    frame=load_results()
    metrics=aggregate(frame);metrics.to_csv(c.OUT/"metrics.csv",index=False)
    with threadpool_limits(limits=2):
        differences=paired(frame)
    differences.to_csv(c.OUT/"paired_differences.csv",index=False)
    gain_loss(frame);calibration();decision(frame,differences)
    aggregate(frame[~frame.ambiguous_race]).to_csv(c.OUT/"unambiguous_metrics.csv",index=False)
    print(metrics[(metrics.scope=="all_starters")&(metrics.dimension=="overall")][["variant","races",*HITS,"qpl_count","quinella_brier","quinella_logloss"]].to_string(index=False))
    c.storage_check()


if __name__=="__main__":
    main()
