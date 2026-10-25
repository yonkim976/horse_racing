"""Independent fixed-bucket description; no fitting, DB access, or rule search."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
FEATURES=ROOT/"jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
PRED=ROOT/"jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
AXIS=ROOT/"jeju/research/20261020_model_axis_vs_win_favorite_rootreview_v1/ROOT_BASELINE_RACE_LEDGER.parquet"


def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def main():
    f=pd.read_parquet(FEATURES)
    pred=pd.read_parquet(PRED).sort_values(["race_id","score","horse_number"],ascending=[True,False,True],kind="stable")
    pred["prediction_rank"]=pred.groupby("race_id").cumcount()+1
    x=pd.read_parquet(AXIS)
    x=x.loc[x.favourite_tie_n.eq(1)].copy()
    assert len(x)==1477
    columns=["race_id","horse_id","api_record_id","prediction_rank","score","p_top3"]
    z=pred[columns].merge(f,on=["race_id","horse_id","api_record_id"],validate="one_to_one")
    keep=["api_record_id","prediction_rank","score","p_top3","observed_starts","valid_n5",
          "same_valid_times","days_since_start","days_since_same","last_time_s","mean5_s",
          "best5_s","std5_s","trend_s","previous3_valid_n","previous_top3","previous_result_status",
          "previous_finish_relative_rank","mean5_rank_fraction","mean5_minus_opp_mean_s",
          "mean5_minus_opp_fast2mean_s","opp_mean5_valid_fraction","hist_s1f_relpos_mean5",
          "hist_s1f_relpos_n","hist_s1f_to_c4_forward_mean5","hist_s1f_to_c4_pair_n",
          "hist_c4_to_g1f_forward_mean5","hist_c4_to_g1f_pair_n","history_cutoff","latest_history_date",
          "previous_age","previous_sex","grade_raw","field_n"]
    for prefix,key in [("m","model_horse_id"),("f","favourite_horse_id")]:
        local=z[["race_id","horse_id",*keep]].rename(columns={"horse_id":key,**{col:f"{prefix}_{col}" for col in keep}})
        x=x.merge(local,on=["race_id",key],how="left",validate="one_to_one")
        assert x[f"{prefix}_api_record_id"].notna().all()
        cutoff=(pd.to_datetime(x.race_date)-pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
        assert x[f"{prefix}_history_cutoff"].astype(str).equals(cutoff)
        valid=x[f"{prefix}_latest_history_date"].notna()
        assert x.loc[valid,f"{prefix}_latest_history_date"].astype(str).le(cutoff[valid]).all()
    assert x.m_grade_raw.equals(x.f_grade_raw) and x.m_field_n.equals(x.f_field_n)
    x["p_gap"]=x.model_probability-x.favourite_probability
    x["p_gap_bin"]=np.select([x.p_gap.lt(.05),x.p_gap.lt(.10)],["<.05",".05-.10"],default=">=.10")
    x["f_rank_bin"]=np.select([x.f_prediction_rank.eq(2),x.f_prediction_rank.eq(3)],["2","3"],default=">=4")
    for p in ["m","f"]:
        v=x[f"{p}_observed_starts"]
        x[f"{p}_career_bin"]=np.select([v.isna(),v.eq(0),v.lt(5)],["missing","0","1-4"],default=">=5")
        v=x[f"{p}_valid_n5"]
        x[f"{p}_n5_bin"]=np.select([v.isna(),v.eq(0),v.le(2)],["missing","0","1-2"],default="3-5")
        v=x[f"{p}_days_since_start"]
        x[f"{p}_gap_bin"]=np.select([v.isna(),v.le(14),v.le(28),v.le(56)],["missing","<=14","15-28","29-56"],default=">56")
    x["paired_mean5_direction"]=np.select(
        [x.m_mean5_s.isna()|x.f_mean5_s.isna(),x.m_mean5_s.le(x.f_mean5_s)],
        ["missing","model_no_slower"],default="model_slower")
    x["paired_previous_top3"]=np.where(x.m_previous_top3.isna()|x.f_previous_top3.isna(),"missing",
        x.m_previous_top3.fillna(-1).astype(int).astype(str)+"_"+x.f_previous_top3.fillna(-1).astype(int).astype(str))
    d=x.loc[~x.same_pick].copy()
    assert len(d)==678
    assert d.case.value_counts().to_dict()=={"favourite_only_hit":248,"both_hit":173,"neither_hit":131,"model_only_hit":126}
    conditions=["distance_m","year","m_grade_raw","m_field_n","p_gap_bin","f_rank_bin",
                "m_career_bin","f_career_bin","m_n5_bin","f_n5_bin","m_gap_bin","f_gap_bin",
                "paired_mean5_direction","paired_previous_top3"]
    rows=[]
    for condition in conditions:
        for value,g in d.groupby(condition,dropna=False,sort=True):
            for period,part in [("all",g),("2024-25",g.loc[g.year.le(2025)]),("2026",g.loc[g.year.eq(2026)])]:
                if not len(part):continue
                count=part.case.value_counts()
                rows.append(dict(condition=condition,level=str(value),period=period,n=len(part),
                                 model_only=int(count.get("model_only_hit",0)),market_only=int(count.get("favourite_only_hit",0)),
                                 both=int(count.get("both_hit",0)),neither=int(count.get("neither_hit",0)),
                                 model_hits=int(part.model_hit.sum()),market_hits=int(part.favourite_hit.sum()),
                                 model_hit_rate=float(part.model_hit.mean()),market_hit_rate=float(part.favourite_hit.mean()),
                                 delta=float((part.model_hit.astype(int)-part.favourite_hit.astype(int)).mean()),
                                 model_mean_p=float(part.model_probability.mean()),market_mean_p=float(part.favourite_probability.mean())))
    summary=pd.DataFrame(rows)
    with (HERE/"ROOT_PAIR_FEATURES.parquet").open("xb") as out:x.to_parquet(out,index=False)
    summary.to_csv(HERE/"ROOT_CONDITION_SUMMARY.csv",index=False,mode="x")
    receipt=dict(passed=True,unique_favourite_races=len(x),disagreement_races=len(d),exclusive_model_only=126,
                 exclusive_market_only=248,case_counts=d.case.value_counts().to_dict(),condition_summary_rows=len(summary),
                 sources={str(p.relative_to(ROOT)):sha(p) for p in [FEATURES,PRED,AXIS]},
                 database_opened=False,models_fitted=0)
    with (HERE/"ROOT_PRELIMINARY_REVIEW.json").open("x") as out:json.dump(receipt,out,ensure_ascii=False,indent=2)
    focus=summary.loc[summary.period.eq("all") & summary.condition.isin(["f_rank_bin","p_gap_bin","f_n5_bin","m_n5_bin","paired_mean5_direction","paired_previous_top3","distance_m","year"])]
    print(focus[["condition","level","n","model_only","market_only","both","neither","model_hit_rate","market_hit_rate"]].to_string(index=False))


if __name__=="__main__":main()
