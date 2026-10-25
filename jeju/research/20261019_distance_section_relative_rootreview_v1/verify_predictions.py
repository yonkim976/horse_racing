"""Independent read-only model replay and triplet probability verification.

Uses trusted local study artifacts; writes a new root-review receipt only.
Does not import the worker's feature or evaluation implementation.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
NEW = ROOT / "jeju/research/20261019_distance_section_relative_ablation_v1/outputs"


def sha(path):
    return hashlib.file_digest(Path(path).open("rb"), "sha256").hexdigest()


def run(mode):
    assert mode in {"baseline", "candidate"}
    source = BASE if mode == "baseline" else NEW
    feature_path = BASE / "features.parquet"
    f = pd.read_parquet(feature_path)
    # Candidate schema/path are deliberately discovered only inside its fixed folder.
    if mode == "candidate":
        paths = list(NEW.glob("features*.parquet"))
        assert len(paths) == 1, paths
        feature_path = paths[0]
        f = pd.read_parquet(feature_path)
    assert len(f) == 52155 and f.race_id.nunique() == 5206
    saved_runners = pd.read_parquet(BASE / "report/runner_predictions.parquet")
    saved_runners = saved_runners.loc[saved_runners.variant.eq("F1_STYLE6")]
    saved_races = pd.read_parquet(BASE / "report/race_metrics.parquet")
    saved_races = saved_races.loc[saved_races.variant.eq("F1_STYLE6")]
    saved_tickets = pd.read_csv(BASE / "report/canonical_six_combinations.csv")
    saved_tickets = saved_tickets.loc[saved_tickets.variant.eq("F1_STYLE6")]
    years = []
    race_records = []
    runner_records = []
    ticket_records = []
    for year in [2024, 2025, 2026]:
        paths = [p for p in source.glob(f"*_{year}/meta.json")
                 if (mode != "baseline" or p.parent.name == f"F1_STYLE6_{year}")]
        assert len(paths) == 1, paths
        meta_path = paths[0]
        meta = json.loads(meta_path.read_text())
        model_path = meta_path.parent / "top3.txt"
        assert sha(model_path) == meta["model_sha256"]
        model = lgb.Booster(model_file=str(model_path))
        test = f.loc[f.year.eq(year)].reset_index(drop=True)
        x = test[meta["features"]].copy()
        for col, vocab in meta["vocabulary"].items():
            x[col] = pd.Categorical(x[col].astype("string"), categories=vocab)
        scores = np.asarray(model.predict(x, raw_score=True, num_threads=4))
        locked = pd.read_parquet(meta_path.parent / "evaluation_scores.parquet")
        assert locked.api_record_id.tolist() == test.api_record_id.tolist()
        assert np.array_equal(scores, locked.score.to_numpy())
        for rid, ids in test.groupby("race_id", sort=False).indices.items():
            one = test.iloc[ids]
            numbers = one.horse_number.to_numpy(dtype=int)
            assert np.all(numbers[:-1] < numbers[1:])
            c = np.array(list(itertools.combinations(range(len(one)), 3)), dtype=int)
            energies = np.sort(scores[ids][c], axis=1).sum(axis=1)
            logq = energies / float(meta["tau"])
            logq -= logsumexp(logq)
            q = np.exp(logq)
            p = np.bincount(c.ravel(), weights=np.repeat(q, 3), minlength=len(one))
            truth = (one.finish_position.to_numpy() <= 3).astype(int)
            assert truth.sum() == 3 and np.isclose(p.sum(), 3, atol=1e-12)
            pc = np.clip(p, 1e-12, 1 - 1e-12)
            ll = -truth * np.log(pc) - (1-truth) * np.log1p(-pc)
            bs = (p-truth)**2
            real = np.flatnonzero(truth)
            truth_idx = np.flatnonzero((c == real).all(axis=1)).item()
            best = np.argsort(-energies, kind="stable")[:6]
            record = dict(race_id=rid, race_date=str(one.race_date.iloc[0]),
                          year=year, distance_m=int(one.distance_m.iloc[0]),
                          log_loss=float(ll.mean()), brier=float(bs.mean()),
                          trio_nll=float(-logq[truth_idx]),
                          six_combo_hit=int(truth_idx in best),
                          six_combo_mass=float(q[best].sum()))
            race_records.append(record)
            for i, api in enumerate(one.api_record_id):
                runner_records.append(dict(api_record_id=int(api), score=float(scores[ids][i]),
                                           p_top3=float(p[i]), log_loss=float(ll[i]), brier=float(bs[i])))
            for rank, j in enumerate(best, 1):
                ticket_records.append(dict(race_id=rid, selection_rank=rank,
                                           numbers=",".join(map(str,numbers[c[j]])),
                                           hit=int(j==truth_idx), probability=float(q[j])))
        years.append(dict(year=year, rows=len(test), races=test.race_id.nunique(),
                          exact_raw_replay=True, model_sha256=sha(model_path), tau=meta["tau"]))
    runners = pd.DataFrame(runner_records).set_index("api_record_id").sort_index()
    races = pd.DataFrame(race_records).set_index("race_id").sort_index()
    tickets = pd.DataFrame(ticket_records).set_index(["race_id","selection_rank"]).sort_index()
    assert len(runners)==17412 and len(races)==1779 and len(tickets)==10674
    errs = {}
    if mode == "baseline":
        for label, actual, saved, keys, cols in [
            ("runner",runners,saved_runners,["api_record_id"],["score","p_top3","log_loss","brier"]),
            ("race",races,saved_races,["race_id"],["log_loss","brier","trio_nll","six_combo_mass"]),
            ("ticket",tickets,saved_tickets,["race_id","selection_rank"],["probability"]),
        ]:
            expected=saved.set_index(keys).sort_index()
            assert actual.index.equals(expected.index)
            for col in cols:
                err=float(np.max(np.abs(actual[col].to_numpy()-expected[col].to_numpy())))
                assert err < 2e-12, (label,col,err)
                errs[f"{label}.{col}"]=err
        expected=saved_tickets.set_index(["race_id","selection_rank"]).sort_index()
        assert tickets[["numbers","hit"]].equals(expected[["numbers","hit"]])
        assert races.six_combo_hit.equals(saved_races.set_index("race_id").sort_index().six_combo_hit)
    else:
        for name, frame in [("runner",runners),("race",races),("ticket",tickets)]:
            path=HERE / f"candidate_independent_{name}.parquet"
            with path.open("xb") as out:
                frame.reset_index().to_parquet(out,index=False)
    primary=races.loc[races.distance_m.isin([900,1000,1110,1200])]
    receipt=dict(passed=True,mode=mode,feature_sha256=sha(feature_path),folds=years,
                 runner_rows=len(runners),races=len(races),canonical_max6_rows=len(tickets),
                 primary_races=len(primary),primary_ll=float(primary.log_loss.mean()),
                 primary_brier=float(primary.brier.mean()),primary_six_hits=int(primary.six_combo_hit.sum()),
                 independent_numeric_errors=errs, database_opened=False, models_fitted=0)
    with (HERE/f"ROOT_{mode.upper()}_REPLAY.json").open("x") as out:
        json.dump(receipt,out,ensure_ascii=False,indent=2)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    run(sys.argv[1])
