"""Compare independent prediction math and paired-date bootstrap to worker outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EVAL=ROOT/"jeju/research/20261019_distance_section_relative_evaluation_v1/outputs"
BASE=ROOT/"jeju/research/20261010_style_history_ablation_v1/outputs"
DISTANCES=[900,1000,1110,1200]


def main():
    candidate={name:pd.read_parquet(HERE/f"candidate_independent_{name}.parquet")
               for name in ["runner","race","ticket"]}
    errs={}
    for name,keys,cols in [
        ("runner",["api_record_id"],["score","p_top3","log_loss","brier"]),
        ("race",["race_id"],["log_loss","brier","trio_nll","six_combo_mass"]),
        ("ticket",["race_id","selection_rank"],["probability"]),
    ]:
        worker_name={"runner":"candidate_runner_predictions.parquet",
                     "race":"candidate_race_metrics.parquet",
                     "ticket":"candidate_canonical_max6.parquet"}[name]
        actual=candidate[name].set_index(keys).sort_index()
        expected=pd.read_parquet(EVAL/worker_name).set_index(keys).sort_index()
        assert actual.index.equals(expected.index)
        for col in cols:
            err=float(np.max(np.abs(actual[col].to_numpy()-expected[col].to_numpy())))
            assert err<2e-12,(name,col,err)
            errs[f"{name}.{col}"]=err
        if name=="ticket":
            assert actual[["numbers","hit"]].equals(expected[["numbers","hit"]])
        if name=="race":
            assert actual.six_combo_hit.equals(expected.six_combo_hit)
    base=pd.read_parquet(BASE/"report/race_metrics.parquet")
    base=base.loc[base.variant.eq("F1_STYLE6")].set_index("race_id").sort_index()
    cand=candidate["race"].set_index("race_id").sort_index()
    assert base.index.equals(cand.index)
    dates=sorted(base.race_date.astype(str).unique())
    assert len(dates)==269
    schedule=np.load(ROOT/"jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy",allow_pickle=False)
    assert schedule.shape==(2000,269)
    primary=base.distance_m.isin(DISTANCES)
    assert int(primary.sum())==1503
    draws_saved=pd.read_parquet(EVAL/"primary_bootstrap_draws.parquet")
    scopes=pd.read_parquet(EVAL/"scope_comparisons.parquet")
    results={}
    for metric in ["log_loss","brier"]:
        delta=cand.loc[primary,metric]-base.loc[primary,metric]
        daily=pd.DataFrame({"race_date":base.loc[primary,"race_date"].astype(str),"delta":delta})
        grouped=daily.groupby("race_date").delta.agg(["sum","count"]).reindex(dates,fill_value=0)
        sums=grouped["sum"].to_numpy()[schedule].sum(axis=1)
        n=grouped["count"].to_numpy()[schedule].sum(axis=1)
        assert (n>0).all()
        draws=sums/n
        saved=draws_saved.loc[draws_saved.metric.eq(metric)].sort_values("draw")
        err=float(np.max(np.abs(draws-saved.candidate_minus_baseline.to_numpy())))
        assert len(saved)==2000 and err<2e-12
        interval=np.quantile(draws,[.025,.975])
        summary=scopes.loc[scopes.scope.eq("primary_distance_cohort")&scopes.metric.eq(metric)].iloc[0]
        for got,expected in [
            (float(delta.mean()),float(summary.candidate_minus_baseline)),
            (float(interval[0]),float(summary.paired_date_ci95_low)),
            (float(interval[1]),float(summary.paired_date_ci95_high)),
        ]:
            assert abs(got-expected)<2e-12
        results[metric]=dict(baseline=float(base.loc[primary,metric].mean()),
                             candidate=float(cand.loc[primary,metric].mean()),
                             delta=float(delta.mean()),ci95=interval.tolist(),
                             bootstrap_max_abs_error=err)
    gate=all(x["delta"]<0 for x in results.values()) and any(x["ci95"][1]<0 for x in results.values())
    worker_summary=json.loads((EVAL/"evaluation_summary.json").read_text())
    assert gate==worker_summary["primary"]["primary_gate_passed"]
    distances={}
    for distance in DISTANCES:
        mask=base.distance_m.eq(distance)
        distances[str(distance)]=dict(races=int(mask.sum()),
            baseline_six_hits=int(base.loc[mask,"six_combo_hit"].sum()),
            candidate_six_hits=int(cand.loc[mask,"six_combo_hit"].sum()),
            log_loss_delta=float((cand.loc[mask,"log_loss"]-base.loc[mask,"log_loss"]).mean()),
            brier_delta=float((cand.loc[mask,"brier"]-base.loc[mask,"brier"]).mean()))
    receipt=dict(passed=True,runner_rows_checked=17412,race_rows_checked=1779,
                 canonical_max6_rows_checked=10674,prediction_errors=errs,
                 primary_bootstrap_draws_checked=4000,primary=results,
                 primary_gate_passed=bool(gate),by_distance=distances,
                 primary_baseline_six_hits=int(base.loc[primary,"six_combo_hit"].sum()),
                 primary_candidate_six_hits=int(cand.loc[primary,"six_combo_hit"].sum()),
                 database_opened=False,models_fitted=0)
    with (HERE/"ROOT_EVALUATION_REVIEW.json").open("x") as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
