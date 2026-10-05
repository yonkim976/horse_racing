"""Read artifacts independently; brute-force sampled joints and historical counts."""
import hashlib
import itertools
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def main():
    audit = json.loads((OUT / "data_audit.json").read_text())
    summary = json.loads((OUT / "summary.json").read_text())
    cfg = json.loads((HERE / "config.json").read_text())
    checks = []
    def check(name, condition):
        checks.append({"check":name,"passed":bool(condition)})
        if not condition: raise AssertionError(name)
    check("source DB preserved", sha(ROOT / cfg["source_db"])==audit["source_sha256"])
    check("source manifest preserved", sha(Path(audit["source_db"]).parent / "manifest.json")==audit["source_manifest_sha256"])
    check("production registry preserved", sha(ROOT / "config/prediction_model_registry.json")==audit["production_registry_sha256"])
    for file,digest in summary["result_hashes"].items(): check("result hash "+file,sha(OUT/file)==digest)
    check("code frozen",sha(HERE / "run.py")==summary["code_sha256"]==audit["code_sha256"])
    check("config frozen",sha(HERE / "config.json")==summary["config_sha256"]==audit["config_sha256"])
    f = pd.read_parquet(OUT / "features.parquet")
    labels = pd.read_parquet(OUT / "labels.parquet")
    p = pd.read_parquet(OUT / "runner_predictions.parquet")
    r = pd.read_csv(OUT / "race_metrics.csv")
    split = pd.read_csv(OUT / "split_ledger.csv")
    check("no warm-up labels",f.race_date.ge("2017-01-01").all())
    for col in ["history_source_date","distance_source_date"]:
        check("T-2 cutoff "+col,(f[col].isna() | (f[col]<=f.race_date-pd.Timedelta(days=2))).all())
    check("all target runner keys unique",not labels.duplicated(["race_key","program_no","horse_id"]).any())
    check("all prediction keys unique",not p.duplicated(["race_key","program_no","horse_id","variant"]).any())
    check("3 probabilities ordered",((p.prob_win>=0)&(p.prob_win<=p.prob_top2+1e-12)&(p.prob_top2<=p.prob_top3+1e-12)&(p.prob_top3<=1+1e-12)).all())
    sums = p.groupby(["race_key","variant"])[["prob_win","prob_top2","prob_top3"]].sum().to_numpy()
    check("marginal sums 1,2,3",np.max(np.abs(sums-[1,2,3]))<1e-10)
    target_eval = f[f.year.isin(cfg["evaluation_years"])]
    expected_keys = set(zip(target_eval.race_key,target_eval.horse_id))
    for variant in ["uniform",*cfg["variants"]]:
        one = p[p.variant.eq(variant)]
        check("complete evaluation keyset "+variant,set(zip(one.race_key,one.horse_id))==expected_keys)
        check("race count "+variant,len(r[r.variant.eq(variant)])==target_eval.race_key.nunique())
    for year,one in split.groupby("evaluation_year"):
        dates = pd.to_datetime(one.race_date)
        limits = {"initial_train":(2017,year-3),"validation":(year-2,year-2),"calibration":(year-1,year-1),"evaluation":(year,year)}
        for role,(lo,hi) in limits.items(): check(f"split {year} {role}",dates[one.role.eq(role)].dt.year.between(lo,hi).all())
        check(f"disjoint races {year}",not one.duplicated("race_key").any())
    sample = f.sample(100,random_state=cfg["seed"])[["horse_id","race_date","history_count"]]
    with duckdb.connect(audit["source_db"],read_only=True) as c:
        c.register("sample",sample)
        expected = c.execute("""
          SELECT s.horse_id,s.race_date,s.history_count,count(r.horse_id_raw) counted
          FROM sample s LEFT JOIN confirmed_runners r
            ON r.horse_id_raw=s.horse_id AND r.source_meet IN ('1','3')
             AND strptime(r.result_date,'%Y%m%d')::DATE <= s.race_date-interval 2 day
             AND (try_cast(r.result_rank_raw as int) BETWEEN 1 AND 20 OR try_cast(r.result_rank_raw as int) IN (91,92))
          GROUP BY ALL
        """).fetchdf()
    check("100 history counts independently match source",np.array_equal(expected.history_count,expected.counted))
    maximum_error = 0.
    for model in summary["models"]:
        path = OUT / "models" / f"{model['meet']}_{model['evaluation_year']}_{model['variant']}"
        for file,digest in model["model_hashes"].items(): check("model hash "+str(path.name)+"/"+file,sha(path/file)==digest)
        check("model chronology "+path.name,model["final_training_year_end"] < model["calibration_year"] < model["evaluation_year"])
        one = p[(p.meet==model["meet"])&(p.evaluation_year==model["evaluation_year"])&p.variant.eq(model["variant"])]
        selected = one.race_key.drop_duplicates().sample(2,random_state=cfg["seed"])
        for race in selected:
            racep = one[one.race_key.eq(race)].sort_values("program_no")
            features = f[f.race_key.eq(race)].sort_values("program_no")[model["features"]].copy()
            for col,vocab in model["category_vocabulary"].items(): features[col]=pd.Categorical(features[col],categories=vocab)
            scores = np.stack([lgb.Booster(model_file=str(path/f"position_{k}.txt")).predict(features,raw_score=True) for k in (1,2,3)],axis=1)
            check("saved score replay "+race+"/"+model["variant"],np.allclose(scores,racep[["score_win","score_second","score_third"]],rtol=0,atol=1e-10))
            s = scores/np.array(model["temperatures"])
            margins = np.zeros((len(scores),3))
            joint_sum = 0.
            # Independent implementation: explicit remaining candidate sets at every step.
            for i,j,k in itertools.permutations(range(len(scores)),3):
                left2 = [x for x in range(len(scores)) if x!=i]
                left3 = [x for x in range(len(scores)) if x not in (i,j)]
                q = softmax(s[:,0])[i]*softmax(s[left2,1])[left2.index(j)]*softmax(s[left3,2])[left3.index(k)]
                joint_sum += q
                margins[i,0] += q
                margins[[i,j],1] += q
                margins[[i,j,k],2] += q
            maximum_error = max(maximum_error,float(np.max(np.abs(margins-racep[["prob_win","prob_top2","prob_top3"]].to_numpy()))))
            check("independent joint sum "+race+"/"+model["variant"],abs(joint_sum-1)<1e-10)
    check("independent sampled marginal replay",maximum_error<1e-10)
    result = {"passed":len(checks),"failed":0,"max_sampled_probability_error":maximum_error,"checks":checks,"production_changed":False}
    (OUT / "verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ["passed","failed","max_sampled_probability_error"]}))


if __name__=="__main__": main()
