"""Predeclared five-arm follow-up; at most six new binary Top2 models."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import common as c
import heads


def freeze():
    paths = [c.HERE / n for n in ["PLAN.md", "config.json", "common.py", "heads.py", "study.py"]]
    previous = json.loads((c.BASE / "outputs/input_manifest.json").read_text())
    paths += [c.ROOT / name for name in previous]
    paths += [c.BASE / n for n in ["run.py", "probability.py", "evaluate.py", "summarize.py",
        "outputs/population_flags.parquet", "outputs/race_metrics.parquet", "outputs/calibration_bins.csv",
        "outputs/evaluation_complete.json", "outputs/verification.json", "outputs/feature_contract.json"]]
    for venue in c.cfg()["venues"]:
        for year in c.cfg()["evaluation_years"]:
            for variant in ["full103", "additive89"]:
                folder = c.BASE / "outputs/models" / f"{variant}_{venue}_{year}"
                meta = json.loads((folder / "metadata.json").read_text())
                paths += [folder / "metadata.json", folder / "scores.parquet", c.ROOT / meta["model_path"],
                    c.BASE / "outputs/calibration" / f"{variant}_{venue}_{year}.json"]
            paths += [c.source_top2(venue, year) / name for name in ["model.txt", "metadata.json"]]
    manifest = {str(p.relative_to(c.ROOT)): {"bytes": p.stat().st_size, "sha256": c.sha(p)} for p in sorted(set(paths))}
    output = c.OUT / "input_manifest.json"
    if output.exists():
        assert json.loads(output.read_text()) == manifest, "Frozen protocol/input changed"
    else:
        c.save(output, manifest)
        c.save(c.OUT / "protocol_frozen.json", {"time_utc": datetime.now(timezone.utc).isoformat(),
            "plan_sha256": c.sha(c.HERE / "PLAN.md"), "config_sha256": c.sha(c.HERE / "config.json"),
            "new_evaluation_started": False, "preexisting_evaluation_period_reused": True,
            "new_final_model_cap": 6, "lightgbm_call_cap": 12, "new_prediction_variants": 5})
    c.save(c.OUT / "feature_contract.json", {"top2_22": c.base.contracts()["ability22"],
        "top2_89": c.base.contracts()["additive89"]})
    print("Frozen", len(manifest), "input/code files", flush=True)


def train():
    c.check_inputs()
    f = c.load_frame()
    fingerprint = c.sha(c.OUT / "input_manifest.json")
    for venue in c.cfg()["venues"]:
        one = f[f.meet.eq(venue)].reset_index(drop=True)
        for year in c.cfg()["evaluation_years"]:
            initial = one.year.between(2017, year - 3)
            valid = one.year.eq(year - 2)
            cal = one.year.eq(year - 1)
            test = one.year.eq(year)
            for variant in ["top2_22", "top2_89"]:
                folder = c.OUT / "models" / f"{variant}_{venue}_{year}"
                if (folder / "scores.parquet").exists():
                    meta = json.loads((folder / "metadata.json").read_text())
                    assert meta["input_fingerprint"] == fingerprint
                    assert c.sha(c.ROOT / meta["model_path"]) == meta["model_sha256"]
                    print("Reuse", folder.name, flush=True)
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                if variant == "top2_22":
                    old = c.source_top2(venue, year)
                    meta_old = json.loads((old / "metadata.json").read_text())
                    cols = meta_old["features"]
                    assert cols == c.base.contracts()["ability22"]
                    assert meta_old["target"] == 2 and meta_old["evaluation_year"] == year
                    assert meta_old["calibration_year"] == year - 1 and meta_old["validation_year"] == year - 2
                    assert meta_old["train_end"] < f"{year-1}-01-01"
                    x, vocab = c.base.encode(one, cols, vocabulary=meta_old["category_vocabulary"])
                    model_path = old / "model.txt"
                    model = lgb.Booster(model_file=str(model_path))
                    assert c.sha(model_path) == meta_old["model_sha256"]
                    trees = meta_old["trees"]
                    validation_log = {"note": "Frozen existing Top2 control; not retrained"}
                else:
                    cols = c.base.contracts()["additive89"]
                    x, vocab = c.base.encode(one, cols, mask=initial)
                    params = c.cfg()["training"].copy()
                    rounds = params.pop("max_rounds")
                    early = params.pop("early_stopping_rounds")
                    params["seed"] = c.cfg()["training_seed"]
                    y = one.outcome.between(1, 2).astype(int)
                    def dataset(mask):
                        return lgb.Dataset(x.loc[mask], label=y[mask], weight=1/one.loc[mask,"field_size"], free_raw_data=False)
                    validation_log = {}
                    first = lgb.train(params, dataset(initial), num_boost_round=rounds, valid_sets=[dataset(valid)],
                        valid_names=["validation"], callbacks=[lgb.early_stopping(early, verbose=False),
                                                              lgb.record_evaluation(validation_log)])
                    trees = int(first.best_iteration)
                    model = lgb.train(params, dataset(initial | valid), num_boost_round=trees)
                    model_path = folder / "model.txt"
                    model.save_model(str(model_path))
                scores = pd.concat([pd.DataFrame({"row_number": one.loc[mask,"row_number"],
                    "score": model.predict(x.loc[mask], raw_score=True, num_threads=4), "phase": phase})
                    for phase, mask in [("calibration", cal), ("evaluation", test)]], ignore_index=True)
                meta = {"variant": variant, "target": 2, "meet": venue, "evaluation_year": year,
                    "validation_year": year-2, "calibration_year": year-1, "training_min": "2017-01-01",
                    "train_end": str(one.loc[initial | valid,"race_date"].max().date()),
                    "features": cols, "category_vocabulary": vocab, "trees": trees,
                    "reused": variant == "top2_22", "model_path": str(model_path.relative_to(c.ROOT)),
                    "model_sha256": c.sha(model_path), "input_fingerprint": fingerprint,
                    "rows": {label:int(mask.sum()) for label,mask in [("initial",initial),("validation",valid),("calibration",cal),("evaluation",test)]},
                    "validation_history": validation_log}
                c.save(folder / "metadata.json", meta)
                scores.to_parquet(folder / "scores.parquet", index=False, compression="zstd")
                print("Ready", folder.name, "trees", trees, flush=True)
                c.storage_check()
    c.save(c.OUT / "training_complete.json", {"new_final_models": len(list((c.OUT/"models").glob("*/model.txt"))),
        "reused_top2_models": 6, "reused_top3_models": 12, "model_score_folds": 12,
        "training_code_sha256": c.sha(Path(__file__)), "input_fingerprint": fingerprint})


def fold_scores(variant, venue, year, phase):
    root = c.OUT if variant.startswith("top2_") else c.BASE / "outputs"
    folder = root / "models" / f"{variant}_{venue}_{year}"
    meta = json.loads((folder / "metadata.json").read_text())
    data = pd.read_parquet(folder / "scores.parquet")
    data = data[data.phase.eq(phase)].set_index("row_number").score
    assert data.index.is_unique
    return meta, data


def base_distributions(g, scores, meta, calibration):
    answer = {}
    orders = None
    for variant in ["additive89", "full103"]:
        s = scores[variant].loc[g.row_number].to_numpy(float)
        q = c.prob.trio_distribution(s, meta[variant]["temperature"])
        ix, mass = c.prob.ordered_distribution(s, q, calibration[variant]["order_temperature"])
        if orders is not None:
            assert np.array_equal(ix, orders)
        orders = ix
        answer[variant] = {"score": s, "q": q, "mass": mass}
    return orders, answer


def calibrate(f, venue, year, meta, calibration):
    path = c.OUT / "calibration" / f"{venue}_{year}.json"
    if path.exists():
        cm = json.loads(path.read_text())
        assert cm["input_fingerprint"] == c.sha(c.OUT / "input_manifest.json")
        assert cm["heads_sha256"] == c.sha(c.HERE / "heads.py")
        return cm
    scores={v:fold_scores(v,venue,year,"calibration")[1] for v in ["additive89","full103","top2_22","top2_89"]}
    indexes = scores["additive89"].index
    assert all(s.index.equals(indexes) for s in scores.values())
    frame=f.loc[indexes]
    assert frame.year.eq(year-1).all()
    records={v:[] for v in ["full103","top2_22","top2_89"]}
    actual={v:[] for v in ["additive89","full103"]}
    for ix in frame.groupby("race_key",sort=False).indices.values():
        g=frame.iloc[ix]
        order, distributions=base_distributions(g,scores,meta,calibration)
        y=g.outcome.to_numpy(int)
        actual_order=np.array(heads.actual_indices(y,len(g)))
        mask=(order==actual_order).all(axis=1)
        assert mask.sum()==1
        for v in actual:
            actual[v].append(float(distributions[v]["mass"][mask][0]))
        for v in records:
            records[v].append((scores[v].loc[g.row_number].to_numpy(float),y))
    weight, diagnostic=heads.fit_mixture_weight(actual["additive89"],actual["full103"])
    bounds=tuple(c.cfg()["temperature_bounds"])
    third={v:heads.fit_third_temperature(records[v],bounds) for v in ["top2_22","top2_89"]}
    first=heads.fit_first_temperature(records["full103"],bounds)
    cm={"meet":venue,"evaluation_year":year,"calibration_year":year-1,
        "calibration_start":str(frame.race_date.min().date()),"calibration_end":str(frame.race_date.max().date()),
        "calibration_races":int(frame.race_key.nunique()),"mix_weight_el":weight,"mix_fit":diagnostic,
        "third_temperatures":third,"first_temperature":first,
        "input_fingerprint":c.sha(c.OUT/"input_manifest.json"),"heads_sha256":c.sha(c.HERE/"heads.py")}
    # Proper-score diagnostic only; no gate, grid, or retry based on these values.
    cm["conditional_third_calibration_nll"]={}
    for v in third:
        selected=heads.selected_scores(records[v]);t=third[v]
        from scipy.special import logsumexp
        cm["conditional_third_calibration_nll"][v]=float(np.mean(logsumexp(-selected/t,axis=1)+selected[:,2]/t))
    c.save(path,cm)
    return cm


def evaluate():
    c.check_inputs()
    assert json.loads((c.OUT/"training_complete.json").read_text())["new_final_models"]==6
    f=c.load_frame()
    metrics=[];tickets=[];runners=[];fits=[];baseline_extras=[]
    calibration_acc=defaultdict(lambda:np.zeros(4))
    c.save(c.OUT/"evaluation_started.json",{"time_utc":datetime.now(timezone.utc).isoformat(),
        "input_fingerprint":c.sha(c.OUT/"input_manifest.json"),"study_sha256":c.sha(Path(__file__)),
        "heads_sha256":c.sha(c.HERE/"heads.py")})
    max_preservation=0.0
    for venue in c.cfg()["venues"]:
        for year in c.cfg()["evaluation_years"]:
            meta={};scores={};base_cal={}
            for v in ["additive89","full103","top2_22","top2_89"]:
                meta[v],scores[v]=fold_scores(v,venue,year,"evaluation")
                if not v.startswith("top2_"):
                    base_cal[v]=json.loads((c.BASE/"outputs/calibration"/f"{v}_{venue}_{year}.json").read_text())
            cm=calibrate(f,venue,year,meta,base_cal);fits.append(cm)
            indexes=scores["additive89"].index
            assert all(s.index.equals(indexes) for s in scores.values())
            test=f.loc[indexes]
            assert test.year.eq(year).all()
            for ix in test.groupby("race_key",sort=False).indices.values():
                g=test.iloc[ix].reset_index(drop=True)
                orders,d=base_distributions(g,scores,meta,base_cal)
                mass={"mix50":heads.mixed(d["additive89"]["mass"],d["full103"]["mass"],.5),
                    "mixcal":heads.mixed(d["additive89"]["mass"],d["full103"]["mass"],cm["mix_weight_el"]),
                    "crossF":c.prob.ordered_distribution(d["full103"]["score"],d["additive89"]["q"],base_cal["full103"]["order_temperature"])[1]}
                for v in ["top2_22","top2_89"]:
                    oo,mass[v]=heads.top2_ordered(scores[v].loc[g.row_number].to_numpy(float),d["full103"]["score"],
                        d["additive89"]["q"],cm["third_temperatures"][v],cm["first_temperature"])
                    assert np.array_equal(oo,orders)
                y=g.outcome.to_numpy(int)
                top2=(y>=1)&(y<=2)
                actual_trio=np.isin(y[orders],[1,2,3]).all(axis=1)
                actual_third=orders[:,2]==np.flatnonzero(y==3)[0]
                true_pair=top2[orders[:,:2]].all(axis=1)
                active=g.normal_finisher.to_numpy(bool)
                for base_variant in ["additive89","full103"]:
                    for scope in ["all_starters","normal_finishers_conditioned"]:
                        bm=d[base_variant]["mass"].copy()
                        if scope=="normal_finishers_conditioned" and not active.all():
                            bm=np.where(active[orders].all(axis=1),bm,0);bm/=bm.sum()
                        baseline_extras.append(dict(race_key=g.race_key.iloc[0],variant=base_variant,scope=scope,
                            quinella_logloss=float(-np.log(max(float(bm[true_pair].sum()),1e-300))),
                            conditional_third_logloss=float(-np.log(max(float(bm[actual_trio&actual_third].sum()/bm[actual_trio].sum()),1e-300)))))
                for v in c.cfg()["new_variants"]:
                    row,tix,rp=c.score.score_race(g,d["additive89"]["score"],orders,mass[v],v,"all_starters",calibration=calibration_acc)
                    row["quinella_logloss"]=-np.log(max(float(mass[v][true_pair].sum()),1e-300))
                    row["conditional_third_logloss"]=-np.log(max(float(mass[v][actual_trio & actual_third].sum()/mass[v][actual_trio].sum()),1e-300))
                    metrics.append(row);tickets.extend(tix);runners.append(rp)
                    if active.all():
                        normal=row|{"scope":"normal_finishers_conditioned"}
                    else:
                        normal,_,_=c.score.score_race(g,d["additive89"]["score"],orders,mass[v],v,"normal_finishers_conditioned",active=active)
                        conditioned=np.where(active[orders].all(axis=1),mass[v],0);conditioned/=conditioned.sum()
                        normal["quinella_logloss"]=-np.log(max(float(conditioned[true_pair].sum()),1e-300))
                        normal["conditional_third_logloss"]=-np.log(max(float(conditioned[actual_trio&actual_third].sum()/conditioned[actual_trio].sum()),1e-300))
                    metrics.append(normal)
                    if v in ["crossF","top2_22","top2_89"]:
                        err=float(np.max(np.abs(mass[v].reshape(-1,6).sum(axis=1)-d["additive89"]["q"])))
                        max_preservation=max(max_preservation,err)
                        assert err<1e-12
            print("Evaluated five variants",venue,year,"races",test.race_key.nunique(),flush=True)
    pd.DataFrame(metrics).to_parquet(c.OUT/"race_metrics.parquet",index=False,compression="zstd")
    pd.DataFrame(baseline_extras).to_parquet(c.OUT/"baseline_extra_metrics.parquet",index=False,compression="zstd")
    pd.DataFrame(tickets).to_parquet(c.OUT/"tickets.parquet",index=False,compression="zstd")
    pd.concat(runners,ignore_index=True).to_parquet(c.OUT/"runner_probabilities.parquet",index=False,compression="zstd")
    bins=[]
    for (variant,year,venue,target,b),a in calibration_acc.items():
        bins.append(dict(variant=variant,year=year,meet=venue,target=target,bin=b,observations=int(a[0]),
            race_weight=a[1],probability_sum=a[2],hit_sum=a[3],predicted=a[2]/a[1],observed=a[3]/a[1]))
    pd.DataFrame(bins).to_csv(c.OUT/"calibration_bins.csv",index=False)
    c.save(c.OUT/"calibration_parameters.json",fits)
    c.save(c.OUT/"evaluation_complete.json",{"race_rows":len(metrics),"runner_rows":sum(len(z) for z in runners),
        "ticket_rows":len(tickets),"coherence_max_error":max(z["coherence_max_error"] for z in metrics),
        "trio_preservation_max_error":max_preservation,"study_sha256":c.sha(Path(__file__)),"heads_sha256":c.sha(c.HERE/"heads.py")})
    c.storage_check()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["freeze","train","evaluate"])
    args=parser.parse_args()
    {"freeze":freeze,"train":train,"evaluate":evaluate}[args.command]()
