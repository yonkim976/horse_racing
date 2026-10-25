"""Read-only independent reconstruction of model-axis vs final WIN favourite."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PRED=ROOT/"jeju/research/20261019_distance_section_relative_evaluation_v1/outputs"
SOURCE=ROOT/"jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def compare(frame):
    by_race=[]
    for race_id,group in frame.groupby("race_id",sort=True):
        ordered=group.sort_values(["score","horse_number"],ascending=[False,True],kind="stable")
        model=ordered.iloc[0]
        lowest=group.loc[group.win_odds.eq(group.win_odds.min())].sort_values("horse_number",kind="stable")
        favourite=lowest.iloc[0]
        same=int(model.horse_number)==int(favourite.horse_number)
        mh=bool(model.y);fh=bool(favourite.y)
        group_case="same_hit" if same and mh else "same_miss" if same else (
            "both_hit" if mh and fh else "model_only_hit" if mh else "favourite_only_hit" if fh else "neither_hit")
        by_race.append(dict(race_id=race_id,race_date=str(model.race_date),year=int(model.year),
                           distance_m=int(model.distance_m),model_horse_number=int(model.horse_number),
                           model_horse_id=str(model.horse_id),model_probability=float(model.p_top3),
                           favourite_horse_number=int(favourite.horse_number),favourite_horse_id=str(favourite.horse_id),
                           favourite_probability=float(favourite.p_top3),favourite_odds=float(favourite.win_odds),
                           model_odds=float(model.win_odds),model_hit=mh,favourite_hit=fh,
                           same_pick=same,case=group_case,favourite_tie_n=len(lowest),
                           model_in_minimum_odds_set=bool(model.horse_number in lowest.horse_number.tolist())))
    ledger=pd.DataFrame(by_race)
    main=ledger.loc[ledger.favourite_tie_n.eq(1)].copy()
    assert len(ledger)==1503 and len(main)==1477
    def summarize(x):
        cases=x.case.value_counts().to_dict()
        same=x.loc[x.same_pick];different=x.loc[~x.same_pick]
        return dict(races=len(x),same_races=len(same),different_races=len(different),
                    same_fraction=float(x.same_pick.mean()),
                    model_hits=int(x.model_hit.sum()),favourite_hits=int(x.favourite_hit.sum()),
                    model_hit_rate=float(x.model_hit.mean()),favourite_hit_rate=float(x.favourite_hit.mean()),
                    model_mean_probability=float(x.model_probability.mean()),
                    favourite_mean_model_probability=float(x.favourite_probability.mean()),
                    same_hits=int(same.model_hit.sum()),same_hit_rate=float(same.model_hit.mean()),
                    same_mean_probability=float(same.model_probability.mean()),
                    different_model_hits=int(different.model_hit.sum()),
                    different_favourite_hits=int(different.favourite_hit.sum()),
                    different_model_hit_rate=float(different.model_hit.mean()),
                    different_favourite_hit_rate=float(different.favourite_hit.mean()),
                    cases={k:int(cases.get(k,0)) for k in
                           ["same_hit","same_miss","both_hit","model_only_hit","favourite_only_hit","neither_hit"]})
    summary=dict(unique_minimum_main=summarize(main),lower_number_tie_representative_sensitivity=summarize(ledger),
                 tied_minimum_races=int(ledger.favourite_tie_n.gt(1).sum()),
                 main_by_distance={str(d):summarize(g) for d,g in main.groupby("distance_m")},
                 main_by_year={str(y):summarize(g) for y,g in main.groupby("year")})
    return ledger,summary


def main():
    predictions={name:pd.read_parquet(PRED/f"{name}_runner_predictions.parquet") for name in ["baseline","candidate"]}
    predictions={name:f.loc[f.distance_m.isin([900,1000,1110,1200])].copy() for name,f in predictions.items()}
    base=predictions["baseline"]
    assert len(base)==14714 and base.race_id.nunique()==1503 and base.api_record_id.is_unique
    assert base.groupby("race_id").size().equals(base.groupby("race_id").field_n.first())
    ids=base.api_record_id.astype(int).tolist()
    connection=sqlite3.connect(f"file:{ROOT/'jeju/data/jeju_native_core.sqlite3'}?mode=ro",uri=True)
    connection.execute("PRAGMA query_only=ON");connection.execute("BEGIN")
    rows=[]
    for start in range(0,len(ids),450):
        chunk=ids[start:start+450]
        sql=("SELECT a.api_record_id,a.record_type,a.payload_sha256,a.source_artifact_id,"
             "json_extract(a.payload_json,'$.winOdds'),json_type(a.payload_json,'$.winOdds'),"
             "r.race_date,r.meet_code,r.race_number,r.horse_number,r.horse_id,r.finish_position "
             "FROM api_records a JOIN race_result_rows r USING(api_record_id) WHERE a.api_record_id IN ("
             +",".join("?" for _ in chunk)+")")
        rows.extend(connection.execute(sql,chunk).fetchall())
    full=pd.read_sql_query("SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,finish_position "
                           "FROM race_result_rows WHERE meet_code=2 AND race_date>=? AND race_date<=? "
                           "AND race_distance_m IN (900,1000,1110,1200)",connection,
                           params=["2024-01-01","2026-09-19"])
    connection.close()
    source=pd.DataFrame(rows,columns=["api_record_id","record_type","payload_sha256","source_artifact_id",
                                     "raw_win_odds","win_odds_json_type","source_race_date","source_meet",
                                     "source_race_number","source_horse_number","source_horse_id","finish_position"])
    assert source.api_record_id.is_unique and len(source)==14714
    source["win_odds"]=pd.to_numeric(source.raw_win_odds,errors="raise")
    assert np.isfinite(source.win_odds).all() and source.win_odds.gt(0).all()
    assert source.win_odds_json_type.isin(["integer","real"]).all()
    assert source.record_type.eq("race_result_entry").all()
    frozen=pd.read_parquet(SOURCE,columns=["api_record_id","api4_3_payload_sha256"])
    chk=source.merge(frozen,on="api_record_id",how="left",validate="one_to_one")
    assert chk.payload_sha256.eq(chk.api4_3_payload_sha256).all()
    full["race_id"]=full.race_date.astype(str)+"_"+full.meet_code.astype(int).astype(str)+"_"+full.race_number.astype(int).astype(str)
    started=full.finish_position.between(1,89)|full.finish_position.isin([91,92])
    full=full.loc[started&full.race_id.isin(set(base.race_id))]
    assert set(full.api_record_id.astype(int))==set(ids)
    summaries={}
    for name,f in predictions.items():
        joined=f.merge(source,on="api_record_id",how="left",validate="one_to_one")
        assert len(joined)==14714 and joined.win_odds.notna().all()
        assert joined.horse_number.astype(int).equals(joined.source_horse_number.astype(int))
        assert joined.horse_id.astype(str).equals(joined.source_horse_id.astype(str))
        assert joined.race_date.astype(str).equals(joined.source_race_date.astype(str))
        assert joined.y.astype(bool).equals(joined.finish_position.le(3))
        ledger,summary=compare(joined)
        assert int(ledger.model_hit.sum())==({"baseline":861,"candidate":866}[name])
        with (HERE/f"ROOT_{name.upper()}_RACE_LEDGER.parquet").open("xb") as stream:
            ledger.to_parquet(stream,index=False)
        summaries[name]=summary
    with (HERE/"ROOT_MARKET_SOURCE.parquet").open("xb") as stream:
        source.to_parquet(stream,index=False)
    receipt=dict(passed=True,scope_races=1503,scope_runners=14714,unique_favourite_races=1477,
                 displayed_minimum_odds_tie_races=26,full_current_starter_roster_matches_model=True,
                 raw_payload_matches_frozen_snapshot=True,database_read_only=True,
                 source_and_model_paths={"frozen_roster_sha256":sha(SOURCE),
                     **{f"{name}_predictions_sha256":sha(PRED/f"{name}_runner_predictions.parquet")
                        for name in ["baseline","candidate"]}},summaries=summaries)
    with (HERE/"ROOT_INDEPENDENT_SUMMARY.json").open("x") as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v["unique_minimum_main"] for k,v in summaries.items()},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
