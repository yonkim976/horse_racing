"""Frozen joint-distribution evaluation; never tune using evaluation outcomes."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

import run as r
import probability as p


def probability_order(probabilities):
    """Resolve numerical equality by the supplied ascending program/pair order."""
    return np.argsort(-np.round(np.asarray(probabilities), 12), kind="stable")


def calibration_add(acc, variant, year, venue, name, probability, truth):
    probability = np.atleast_1d(probability).astype(float)
    truth = np.atleast_1d(truth).astype(float)
    bins = np.minimum(9, (probability * 10).astype(int))
    weight = 1.0 / len(truth)
    for b in np.unique(bins):
        take = bins == b
        key = (variant, year, venue, name, int(b))
        a = acc[key]
        a[0] += int(take.sum())
        a[1] += float(take.sum() * weight)
        a[2] += float(probability[take].sum() * weight)
        a[3] += float(truth[take].sum() * weight)


def score_race(g, scores, orders, mass, variant, scope, active=None, calibration=None):
    n = len(g)
    assert g.program_no.is_monotonic_increasing
    if active is None:
        active = np.ones(n, dtype=bool)
    if not active.all():
        keep = active[orders].all(axis=1)
        mass = np.where(keep, mass, 0)
        mass = mass / mass.sum()
    m = p.marginals(n, orders, mass)
    ii, jj = np.triu_indices(n, 1)
    eligible = active[ii] & active[jj]
    ii, jj = ii[eligible], jj[eligible]
    outcome = g.outcome.to_numpy(int)
    top3 = (outcome >= 1) & (outcome <= 3)
    top2 = (outcome >= 1) & (outcome <= 2)
    yq = (top2[ii] & top2[jj]).astype(int)
    yw = (top3[ii] & top3[jj]).astype(int)
    qp, wp = m["quinella"][ii, jj], m["qpl"][ii, jj]
    qs = probability_order(qp)[:3]
    ws = probability_order(wp)[:3]
    axis = int(probability_order(m["top3"])[0])
    qnl_union = float(qp[qs].sum())
    hits_in_order = np.zeros(len(orders), dtype=int)
    for t in ws:
        hits_in_order += ((orders == ii[t]).any(axis=1) & (orders == jj[t]).any(axis=1))
    qpl_union = float(mass[hits_in_order > 0].sum())
    true_order = np.array([np.flatnonzero(outcome == k)[0] for k in [1, 2, 3]])
    actual_set = top3[orders].all(axis=1)
    true_order_mask = (orders == true_order).all(axis=1)
    assert true_order_mask.sum() == 1
    qpl_count = int(yw[ws].sum())
    checks = [abs(mass.sum() - 1), abs(m["win"].sum() - 1), abs(m["top2"].sum() - 2),
        abs(m["top3"].sum() - 3), abs(qp.sum() - 1), abs(wp.sum() - 3),
        np.max(np.abs(m["qpl"].sum(axis=1) - 2*m["top3"])),
        np.max(np.abs(m["quinella"].sum(axis=1) - m["top2"])),
        float(np.maximum(0, qp-wp).max()), float(np.maximum(0,m["win"]-m["top2"]).max()),
        float(np.maximum(0,m["top2"]-m["top3"]).max()),
        float(np.maximum(0,wp-np.minimum(m["top3"][ii],m["top3"][jj])).max())]
    err = float(max(checks))
    assert err < 1e-9, (g.race_key.iloc[0], checks)
    base = dict(race_key=g.race_key.iloc[0], race_date=str(g.race_date.iloc[0].date()),
        meet=int(g.meet.iloc[0]), year=int(g.year.iloc[0]), distance_m=int(g.distance_m.iloc[0]),
        grade=str(g.grade_raw.iloc[0]), variant=variant, scope=scope,
        field_size=int(active.sum()), original_field_size=n,
        nonfinishers=int((~g.normal_finisher.to_numpy(bool)).sum()),
        ambiguous_race=bool(g.ambiguous_flag.any()), minimum_history=float(g.history_count.min()),
        axis_program_no=int(g.program_no.iloc[axis]), axis_history_count=float(g.history_count.iloc[axis]),
        axis_front_probability=float(g.front_gate_probability.iloc[axis]),
        axis_late600=float(g.section_last600_mean3.iloc[axis]),
        axis_late200=float(g.section_late_mean3.iloc[axis]),
        axis_top3=int(top3[axis]), axis_probability=float(m["top3"][axis]),
        quinella_one=int(yq[qs[0]]), quinella_three=int(yq[qs].sum() > 0),
        qpl_one=int(yw[ws[0]]), qpl_three=int(qpl_count > 0), qpl_count=qpl_count,
        qpl_expected_count=float(wp[ws].sum()), qnl1_probability=float(qp[qs[0]]),
        qnl3_probability=qnl_union, qpl1_probability=float(wp[ws[0]]), qpl3_probability=qpl_union,
        runner_brier=float(np.mean((m["top3"][active]-top3[active])**2)),
        quinella_brier=float(np.mean((qp-yq)**2)), qpl_brier=float(np.mean((wp-yw)**2)),
        trio_logloss=float(-np.log(max(mass[actual_set].sum(),1e-300))),
        ordered_logloss=float(-np.log(max(mass[true_order_mask].sum(),1e-300))),
        coherence_max_error=err)
    for label, pred, y in [("axis",base["axis_probability"],base["axis_top3"]),
                          ("qnl1",base["qnl1_probability"],base["quinella_one"]),
                          ("qnl3",qnl_union,base["quinella_three"]),
                          ("qpl1",base["qpl1_probability"],base["qpl_one"]),
                          ("qpl3",qpl_union,base["qpl_three"])]:
        base[label+"_brier"] = float((pred-y)**2)
    # The incumbent's old fixed-axis quinella policy is a recommendation-score control.
    ranking = np.flatnonzero(active)[np.argsort(-scores[active], kind="stable")]
    legacy = [(ranking[0], ranking[k]) for k in [1,2,3] if len(ranking)>k]
    base["legacy_quinella_one"] = int(top2[legacy[0][0]] and top2[legacy[0][1]])
    base["legacy_quinella_three"] = int(any(top2[a] and top2[b] for a,b in legacy))
    tickets=[]
    for pool, select, prob, truth in [("quinella",qs,qp,yq),("qpl",ws,wp,yw)]:
        for rank,t in enumerate(select,1):
            tickets.append(dict(race_key=base["race_key"],variant=variant,pool=pool,rank=rank,
                program_a=int(g.program_no.iloc[ii[t]]),program_b=int(g.program_no.iloc[jj[t]]),
                probability=float(prob[t]),hit=int(truth[t])))
    runners = pd.DataFrame({"race_key":g.race_key.to_numpy(),"program_no":g.program_no.to_numpy(),
        "horse_id":g.horse_id.to_numpy(),"variant":variant,"outcome":outcome,
        "win":m["win"],"top2":m["top2"],"top3":m["top3"]})
    if calibration is not None:
        for name,prob,truth in [("runner_top3",m["top3"],top3), ("quinella_all_pairs",qp,yq),
            ("qpl_all_pairs",wp,yw),("axis",base["axis_probability"],base["axis_top3"]),
            ("quinella_one",base["qnl1_probability"],base["quinella_one"]),
            ("quinella_three_union",qnl_union,base["quinella_three"]),
            ("qpl_one",base["qpl1_probability"],base["qpl_one"]),
            ("qpl_three_union",qpl_union,base["qpl_three"])]:
            calibration_add(calibration,variant,base["year"],base["meet"],name,prob,truth)
    return base,tickets,runners


def main():
    r.check_inputs()
    assert (r.OUT/"training_complete.json").exists()
    f = r.load_frame()
    flags = pd.read_parquet(r.OUT/"population_flags.parquet")
    assert not flags.duplicated(r.KEY).any()
    for col in ["normal_finisher","ambiguous_flag"]:
        assert flags[col].notna().all() and pd.api.types.is_bool_dtype(flags[col]), col
    expected = set(map(tuple, f[f.year.ge(2024)][r.KEY].to_numpy()))
    assert expected == set(map(tuple,flags[r.KEY].to_numpy()))
    f = f.merge(flags[r.KEY+["normal_finisher","ambiguous_flag"]],on=r.KEY,how="left",validate="one_to_one")
    f.index=f.row_number
    metrics=[];tickets=[];runners=[];calibration=defaultdict(lambda:np.zeros(4))
    fit_meta=[]
    r.save(r.OUT/"evaluation_started.json",{"protocol_sha256":r.sha(r.OUT/"protocol_frozen.json"),
        "evaluation_code_sha256":r.sha(Path(__file__)),"probability_code_sha256":r.sha(r.HERE/"probability.py"),
        "population_flags_sha256":r.sha(r.OUT/"population_flags.parquet")})
    for venue in r.cfg()["venues"]:
        for year in r.cfg()["evaluation_years"]:
            for variant in r.cfg()["variants"]:
                parent="full103" if variant=="full103_pair" else variant
                folder=r.OUT/"models"/f"{parent}_{venue}_{year}"
                meta=json.loads((folder/"metadata.json").read_text())
                s=pd.read_parquet(folder/"scores.parquet")
                calibration_scores=s[s.phase.eq("calibration")].set_index("row_number").score
                cal=f.loc[calibration_scores.index].copy()
                order_records=[];pair_records=[]
                for ix in cal.groupby("race_key",sort=False).indices.values():
                    g=cal.iloc[ix]
                    score=calibration_scores.loc[g.row_number].to_numpy(float)
                    order_records.append((score,g.outcome.to_numpy(int)))
                    if variant=="full103_pair":
                        pair_records.append((score,meta["temperature"],g.outcome.to_numpy(int),p.pair_features(g)))
                cal_path=r.OUT/"calibration"/f"{variant}_{venue}_{year}.json"
                if cal_path.exists():
                    cm=json.loads(cal_path.read_text())
                    assert cm["source_metadata_sha256"]==r.sha(folder/"metadata.json")
                    assert cm["probability_code_sha256"]==r.sha(r.HERE/"probability.py")
                    assert cm["config_sha256"]==r.sha(r.HERE/"config.json")
                    assert cm["variant"]==variant and cm["meet"]==venue
                    assert cm["calibration_year"]==year-1 and cm["evaluation_year"]==year
                    assert cm["set_temperature"]==meta["temperature"]
                    order_temp=cm["order_temperature"];beta=np.array(cm["beta"])
                    assert beta.shape==(3,) and np.isfinite(beta).all()
                    assert np.max(np.abs(beta))<=r.cfg()["pair_bound"]
                    assert r.cfg()["temperature_bounds"][0]<=order_temp<=r.cfg()["temperature_bounds"][1]
                    assert cm["optimizer"]["success"]
                else:
                    order_temp=p.fit_order_temperature(order_records,bounds=tuple(r.cfg()["temperature_bounds"]))
                    beta=np.zeros(3);diagnostic={"success":True,"note":"No pair coefficients"}
                    if variant=="full103_pair":
                        beta,diagnostic=p.fit_pair_beta(pair_records,ridge=r.cfg()["pair_ridge"],
                            bound=r.cfg()["pair_bound"],maxiter=r.cfg()["pair_maxiter"])
                        assert diagnostic["success"], diagnostic
                    cm=dict(variant=variant,meet=venue,evaluation_year=year,calibration_year=year-1,
                        calibration_start=str(cal.race_date.min().date()),calibration_end=str(cal.race_date.max().date()),
                        races=int(cal.race_key.nunique()),set_temperature=meta["temperature"],
                        order_temperature=order_temp,beta=beta.tolist(),optimizer=diagnostic,
                        source_metadata_sha256=r.sha(folder/"metadata.json"),
                        probability_code_sha256=r.sha(r.HERE/"probability.py"),
                        config_sha256=r.sha(r.HERE/"config.json"))
                    r.save(cal_path,cm)
                fit_meta.append(cm)
                tests=s[s.phase.eq("evaluation")].set_index("row_number").score
                test=f.loc[tests.index]
                for ix in test.groupby("race_key",sort=False).indices.values():
                    g=test.iloc[ix].reset_index(drop=True)
                    scores=tests.loc[g.row_number].to_numpy(float)
                    X=p.pair_features(g) if variant=="full103_pair" else None
                    q=p.trio_distribution(scores,meta["temperature"],X,beta if X is not None else None)
                    orders,mass=p.ordered_distribution(scores,q,order_temp)
                    row,tix,rp=score_race(g,scores,orders,mass,variant,"all_starters",calibration=calibration)
                    metrics.append(row);tickets.extend(tix);runners.append(rp)
                    active=g.normal_finisher.to_numpy(bool)
                    assert active[g.outcome.between(1,3)].all()
                    if active.all():
                        normal=row|{"scope":"normal_finishers_conditioned"}
                    else:
                        normal,_,_=score_race(g,scores,orders,mass,variant,"normal_finishers_conditioned",active=active)
                    metrics.append(normal)
                print("Evaluated frozen fold",variant,venue,year,"races",test.race_key.nunique(),flush=True)
    pd.DataFrame(metrics).to_parquet(r.OUT/"race_metrics.parquet",index=False,compression="zstd")
    pd.DataFrame(tickets).to_parquet(r.OUT/"tickets.parquet",index=False,compression="zstd")
    pd.concat(runners,ignore_index=True).to_parquet(r.OUT/"runner_probabilities.parquet",index=False,compression="zstd")
    records=[]
    for (variant,year,venue,name,b),v in calibration.items():
        records.append(dict(variant=variant,year=year,meet=venue,target=name,bin=b,observations=int(v[0]),
            race_weight=v[1],probability_sum=v[2],hit_sum=v[3],predicted=v[2]/v[1],observed=v[3]/v[1]))
    pd.DataFrame(records).to_csv(r.OUT/"calibration_bins.csv",index=False)
    r.save(r.OUT/"calibration_parameters.json",fit_meta)
    r.save(r.OUT/"evaluation_complete.json",dict(race_rows=len(metrics),runner_rows=sum(len(g) for g in runners),
        ticket_rows=len(tickets),max_coherence_error=max(x["coherence_max_error"] for x in metrics),
        evaluation_code_sha256=r.sha(Path(__file__)),probability_code_sha256=r.sha(r.HERE/"probability.py")))
    r.storage_check()


if __name__=="__main__":
    main()
