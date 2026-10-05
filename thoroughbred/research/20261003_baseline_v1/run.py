"""Read-only source, frozen chronological runner and joint probability baselines."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from functools import lru_cache
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
KEY = ["race_key", "program_no", "horse_id"]
HISTORY_MEASURES = ["win", "top3", "rank_fraction", "nonfinish"]
RECORD_MEASURES = ["record_index", "start_200", "last_200", "last_600"]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def config():
    return json.loads((HERE / "config.json").read_text())


def read_source(db, history_start="2010-01-01"):
    with duckdb.connect(str(db), read_only=True) as c:
        rows = c.execute("""
          SELECT cast(r.source_meet as int) meet,
                 strptime(r.result_date, '%Y%m%d')::DATE race_date,
                 cast(r.result_race_no as int) race_no,
                 cast(r.horse_program_no_raw as int) program_no,
                 r.horse_id_raw horse_id, r.horse_name_raw horse_name,
                 try_cast(r.result_rank_raw as int) outcome,
                 try_cast(r.finish_time_seconds_raw as double) finish,
                 try_cast(r.race_distance_m_raw as int) result_distance,
                 try_cast(e.scheduled_distance_m as int) distance_m,
                 e.scheduled_grade_raw grade_raw,
                 try_cast(r.horse_age_raw as double) age,
                 try_cast(r.carried_weight_raw as double) carried_weight,
                 try_cast(regexp_extract(r.horse_weight_raw, '^([0-9]+)', 1) as double) body_weight,
                 r.horse_sex_raw sex
          FROM confirmed_runners r JOIN confirmed_races e
            ON r.source_meet=e.source_meet AND r.result_date=e.result_date_key
             AND r.result_race_no=e.result_race_no_key
          WHERE r.source_meet IN ('1','3')
            AND strptime(r.result_date, '%Y%m%d')::DATE >= cast(? as date)
          ORDER BY race_date, meet, race_no, program_no
        """, [history_start]).fetchdf()
        section = c.execute("""
          SELECT meet, strptime(race_date, '%Y%m%d')::DATE race_date,
                 race_no, horse_id,
                 max(time_ms)/1000.0 AS measurement_value,
                 point_code, measure_kind
          FROM section_measurements_api
          WHERE meet IN (1,3) AND point_code IN ('S1F','G1F','G3F','1F_G','3F_G')
            AND measure_kind IN ('cumulative_time','closing_time')
          GROUP BY meet,race_date,race_no,horse_id,point_code,measure_kind
        """).fetchdf()
        conflicts = c.execute("""
          SELECT count(*) FROM (
            SELECT meet,race_date,race_no,horse_id,point_code,measure_kind
            FROM section_measurements_api
            WHERE meet IN (1,3) AND point_code IN ('S1F','G1F','G3F','1F_G','3F_G')
              AND measure_kind IN ('cumulative_time','closing_time')
            GROUP BY ALL HAVING count(distinct time_ms)>1)
        """).fetchone()[0]
        objects = c.execute("select count(*) from information_schema.tables").fetchone()[0]
    if conflicts:
        raise ValueError("Conflicting selected section measurements")
    rows["race_date"] = pd.to_datetime(rows.race_date)
    rows["race_key"] = rows.meet.astype(str) + ":" + rows.race_date.dt.strftime("%Y%m%d") + ":" + rows.race_no.astype(str)
    for keys in [KEY, ["race_key", "horse_id"]]:
        if rows.duplicated(keys).any():
            raise ValueError("Duplicate runner key")
    if rows.horse_id.isna().any() or rows.horse_id.eq("").any():
        raise ValueError("Missing horse identity")
    section["race_date"] = pd.to_datetime(section.race_date)
    p = section.pivot(index=["meet", "race_date", "race_no", "horse_id"],
                      columns=["point_code", "measure_kind"], values="measurement_value")
    p.columns = [f"{point}_{kind}" for point, kind in p.columns]
    rows = rows.merge(p.reset_index(), how="left", on=["meet", "race_date", "race_no", "horse_id"], validate="one_to_one")
    return rows, objects


def prepare_records(rows):
    """Past outcomes never become current inputs; invalid times become null only."""
    a = rows.copy()
    normal = a.outcome.between(1, 20)
    starters = normal | a.outcome.isin([91, 92])
    a["historical_field_size"] = starters.groupby(a.race_key).transform("sum")
    a["win"] = a.outcome.eq(1).astype(float)
    a["top3"] = a.outcome.between(1, 3).astype(float)
    a["rank_fraction"] = ((a.outcome - 1) / (a.historical_field_size - 1)).where(normal, 1.0)
    a["nonfinish"] = a.outcome.isin([91, 92]).astype(float)
    # Warm-up outcomes/state remain useful; old raw track times are not pooled.
    full_ok = normal & a.race_date.ge("2017-01-01") & a.finish.gt(0) & (a.result_distance / a.finish).between(10, 20)
    a["finish_valid"] = a.finish.where(full_ok)
    a["start_200"] = a["S1F_cumulative_time"]
    a["last_200"] = a["1F_G_closing_time"].combine_first(a.finish - a["G1F_cumulative_time"])
    a["last_600"] = a["3F_G_closing_time"].combine_first(a.finish - a["G3F_cumulative_time"])
    invalid = {}
    for col, lo, hi in [("start_200", 10, 30), ("last_200", 8, 30), ("last_600", 28, 90)]:
        ok = full_ok & a[col].between(lo, hi) & a[col].lt(a.finish)
        if col == "last_600":
            ok &= a.last_200.isna() | a[col].ge(a.last_200 + 10)
        invalid[col] = int((a[col].notna() & ~ok).sum())
        a[col] = a[col].where(ok)
    a["year"] = a.race_date.dt.year
    a["record_index"] = np.nan
    reference = []
    for year in sorted(a.year.unique()):
        prior = a[a.year.lt(year) & a.finish_valid.notna()]
        stats = prior.groupby(["meet", "result_distance"]).finish_valid.agg(["count", "median"])
        mad = prior.groupby(["meet", "result_distance"]).finish_valid.agg(lambda x: np.median(np.abs(x - np.median(x))))
        stats["scale"] = np.maximum(0.5, 1.4826 * mad)
        stats = stats[stats["count"].ge(50)]
        if stats.empty:
            continue
        current = a[a.year.eq(year)].merge(stats, left_on=["meet", "result_distance"], right_index=True, how="left")
        a.loc[current.index, "record_index"] = ((current["median"] - current.finish_valid) / current.scale).clip(-10, 10)
        ref = stats.reset_index()
        ref["source_year"], ref["trained_through"] = year, year - 1
        reference.extend(ref.to_dict("records"))
    a["body_weight"] = a.body_weight.where(a.body_weight.between(300, 650))
    a["carried_weight"] = a.carried_weight.where(a.carried_weight.between(40, 70))
    a["age"] = a.age.where(a.age.between(1, 20))
    return a[starters].copy(), invalid, reference


def build_features(starters, lag):
    if starters.duplicated(["horse_id", "race_date"]).any():
        raise ValueError("Multiple starts of a horse on one date")
    h = starters.sort_values(["horse_id", "race_date"]).copy()
    g = h.groupby("horse_id", sort=False)
    post = h[["horse_id", "race_date"]].rename(columns={"race_date": "history_source_date"})
    post["available_date"] = post.history_source_date + pd.Timedelta(days=lag)
    post["history_count"] = g.cumcount() + 1
    for col in ["win", "top3", "nonfinish"]:
        post[f"career_{col}_rate"] = g[col].cumsum() / post.history_count
    for col in ["result_distance", "age", "sex", "carried_weight", "body_weight"]:
        post[f"previous_{col}"] = h[col]
    for col in HISTORY_MEASURES + RECORD_MEASURES:
        post[f"last_{col}"] = h[col]
        for k in (3, 5, 10):
            post[f"last{k}_{col}_mean"] = g[col].rolling(k, min_periods=1).mean().reset_index(level=0, drop=True)
    for k in (5, 10):
        post[f"last{k}_record_index_best"] = g.record_index.rolling(k, min_periods=1).max().reset_index(level=0, drop=True)
        post[f"last{k}_record_index_count"] = g.record_index.rolling(k, min_periods=1).count().reset_index(level=0, drop=True)
    post["last5_record_index_std"] = g.record_index.rolling(5, min_periods=2).std().reset_index(level=0, drop=True)
    post["record_index_change"] = h.record_index - g.record_index.shift(1)
    post["body_weight_change"] = h.body_weight - g.body_weight.shift(1)
    post["carried_weight_change"] = h.carried_weight - g.carried_weight.shift(1)
    left = starters[[*KEY, "meet", "race_date", "race_no", "distance_m", "grade_raw", "outcome", "horse_name"]].copy()
    frame = pd.merge_asof(left.sort_values("race_date"), post.sort_values("available_date"),
                          left_on="race_date", right_on="available_date", by="horse_id", direction="backward")
    same = h[["horse_id", "race_date", "result_distance"]].rename(columns={"result_distance": "distance_m", "race_date": "distance_source_date"})
    same["distance_available_date"] = same.distance_source_date + pd.Timedelta(days=lag)
    gd = h.groupby(["horse_id", "result_distance"], sort=False)
    same["same_distance_history_count"] = gd.cumcount() + 1
    same["same_distance_top3_rate"] = gd.top3.cumsum() / same.same_distance_history_count
    same["same_distance_last_finish"] = h.finish_valid
    same["same_distance_last5_finish_mean"] = gd.finish_valid.rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    # Nullable distances are held from the target cohort; keep missing rows out of this join.
    valid = frame.distance_m.notna()
    frame["distance_m"] = frame.distance_m.astype(float)
    same["distance_m"] = same.distance_m.astype(float)
    joined = pd.merge_asof(frame[valid].sort_values("race_date"), same[same.distance_m.notna()].sort_values("distance_available_date"),
                           left_on="race_date", right_on="distance_available_date", by=["horse_id", "distance_m"], direction="backward")
    frame = pd.concat([joined, frame[~valid]], ignore_index=True)
    frame["history_count"] = frame.history_count.fillna(0)
    frame["same_distance_history_count"] = frame.same_distance_history_count.fillna(0)
    frame["days_since_last"] = (frame.race_date - frame.history_source_date).dt.days
    frame["distance_change"] = frame.distance_m - frame.previous_result_distance
    frame["month"] = frame.race_date.dt.month
    frame["year"] = frame.race_date.dt.year
    frame["grade"] = pd.to_numeric(frame.grade_raw.str.extract(r"([1-6])", expand=False), errors="coerce")
    frame["grade_kind"] = frame.grade_raw.str.extract(r"^(국|혼)", expand=False).fillna("other")
    frame["field_size"] = frame.groupby("race_key").horse_id.transform("size")
    feature_names = [c for c in post.columns if c not in {"horse_id", "history_source_date", "available_date"}]
    feature_names += [c for c in same.columns if c not in {"horse_id", "distance_m", "distance_source_date", "distance_available_date"}]
    feature_names += ["distance_m", "grade", "grade_kind", "month", "field_size", "days_since_last", "distance_change"]
    record_features = [c for c in feature_names if any(s in c for s in ("record_index", "start_200", "last_200", "last_600", "finish")) and "nonfinish" not in c]
    # Within-field contrasts use pre-race values only; actual starters condition the roster.
    relative = ["career_top3_rate", "last3_rank_fraction_mean", "days_since_last", "last3_record_index_mean", "last3_start_200_mean", "last3_last_600_mean"]
    for col in relative:
        frame[f"relative_{col}"] = frame[col] - frame.groupby("race_key")[col].transform("mean")
        feature_names.append(f"relative_{col}")
        if col in record_features:
            record_features.append(f"relative_{col}")
    basic = [c for c in feature_names if c not in record_features]
    for col in ["history_source_date", "distance_source_date"]:
        if not (frame[col].isna() | frame[col].le(frame.race_date - pd.Timedelta(days=lag))).all():
            raise ValueError("History cutoff violation")
    return frame.sort_values(["race_date", "meet", "race_no", "program_no"]).reset_index(drop=True), {"history": basic, "history_records": feature_names}


def cohort_ledger(rows, starters, minimum):
    ledger = rows.groupby("race_key").agg(meet=("meet", "first"), race_date=("race_date", "first"), original_card_rows=("outcome", "size"))
    ledger["nonstarters"] = rows.outcome.isin([93, 94, 95]).groupby(rows.race_key).sum()
    ledger["unknown_outcomes"] = (~(rows.outcome.between(1, 20) | rows.outcome.isin([91, 92, 93, 94, 95]))).groupby(rows.race_key).sum()
    ledger["starters"] = starters.groupby("race_key").size()
    for pos in (1, 2, 3):
        ledger[f"rank{pos}_count"] = rows.outcome.eq(pos).groupby(rows.race_key).sum()
    ledger["missing_distance"] = rows.distance_m.isna().groupby(rows.race_key).any()
    ledger["distance_conflict"] = rows.distance_m.ne(rows.result_distance).groupby(rows.race_key).any()
    def reason(r):
        flags = []
        if r.unknown_outcomes: flags.append("unknown_outcome")
        if r.starters < minimum: flags.append("too_few_starters")
        if any(r[f"rank{k}_count"] != 1 for k in (1, 2, 3)): flags.append("nonunique_or_missing_top3")
        if r.missing_distance or r.distance_conflict: flags.append("invalid_plan_distance")
        return "|".join(flags) or "eligible"
    ledger["status"] = ledger.apply(reason, axis=1)
    return ledger.reset_index()


def prepare():
    cfg = config()
    OUT.mkdir(exist_ok=False)
    db = ROOT / cfg["source_db"]
    before = sha(db)
    rows, objects = read_source(db, cfg["history_start"])
    starters, invalid, references = prepare_records(rows)
    frame, features = build_features(starters, cfg["history_lag_days"])
    ledger = cohort_ledger(rows, starters, cfg["minimum_starters"])
    eligible = set(ledger.loc[ledger.status.eq("eligible"), "race_key"])
    frame = frame[frame.race_key.isin(eligible) & frame.year.ge(cfg["training_start_year"])].copy()
    labels = frame[KEY + ["outcome"]].copy()
    frame = frame.drop(columns="outcome")
    for columns in features.values():
        if set(columns) & {"outcome", "finish", "horse_id", "program_no", "year", "race_date"}:
            raise ValueError("Forbidden model feature")
    frame.to_parquet(OUT / "features.parquet", index=False)
    labels.to_parquet(OUT / "labels.parquet", index=False)
    ledger.to_csv(OUT / "cohort_ledger.csv", index=False)
    pd.DataFrame(references).to_csv(OUT / "record_references.csv", index=False)
    coverage = frame.groupby(["meet", "year"]).agg(runners=("horse_id", "size"), races=("race_key", "nunique"), no_history=("history_count", lambda x: int(x.eq(0).sum())))
    coverage.to_csv(OUT / "coverage.csv")
    missing = frame.groupby(["meet", "year"])[features["history_records"]].agg(lambda x: x.isna().mean())
    missing.to_csv(OUT / "feature_missingness.csv")
    splits = []
    for year in cfg["evaluation_years"]:
        for role, mask in [("initial_train", frame.year.between(cfg["training_start_year"], year-3)),
                           ("validation", frame.year.eq(year-2)), ("calibration", frame.year.eq(year-1)), ("evaluation", frame.year.eq(year))]:
            one = frame[mask].drop_duplicates("race_key")
            splits.append(one[["race_key", "meet", "race_date"]].assign(evaluation_year=year, role=role))
    pd.concat(splits).to_csv(OUT / "split_ledger.csv", index=False)
    save_json(OUT / "feature_contract.json", features)
    after = sha(db)
    if before != after:
        raise ValueError("Source DB changed during extraction")
    summary = {"source_db": str(db), "source_sha256": before, "source_manifest_sha256": sha(db.parent / "manifest.json"),
               "objects_observed": objects, "config_sha256": sha(HERE / "config.json"), "code_sha256": sha(__file__),
               "source_rows": len(rows), "source_races": rows.race_key.nunique(), "source_date_end": str(rows.race_date.max().date()),
               "nonstarter_rows": int(rows.outcome.isin([93,94,95]).sum()), "started_nonfinish_rows": int(starters.nonfinish.sum()),
               "cohort_status_counts": ledger.status.value_counts().to_dict(), "feature_rows": len(frame), "feature_races": frame.race_key.nunique(),
               "invalid_section_features": invalid, "feature_counts": {k: len(v) for k,v in features.items()},
               "publication_timestamps_verified": False, "production_changed": False,
               "production_registry_sha256": sha(ROOT / "config/prediction_model_registry.json"),
               "input_hashes": {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}}
    save_json(OUT / "data_audit.json", summary)
    print(json.dumps({"prepared": len(frame), "races": frame.race_key.nunique(), "cohort": summary["cohort_status_counts"]}), flush=True)


@lru_cache(maxsize=32)
def permutation_indices(n):
    return np.array(list(itertools.permutations(range(n), 3)), dtype=int)


def joint(scores, temperatures):
    n = len(scores)
    if n < 3 or not np.isfinite(scores).all() or np.any(np.array(temperatures) <= 0):
        raise ValueError("Invalid joint input")
    s = np.asarray(scores, dtype=float) / np.asarray(temperatures)
    ix = permutation_indices(n)
    second = np.broadcast_to(s[:, 1], (n, n)).copy()
    np.fill_diagonal(second, -np.inf)
    pairs = np.array(list(itertools.permutations(range(n), 2)))
    third = np.broadcast_to(s[:, 2], (len(pairs), n)).copy()
    third[np.arange(len(pairs)), pairs[:, 0]] = -np.inf
    third[np.arange(len(pairs)), pairs[:, 1]] = -np.inf
    denom3 = np.full((n, n), np.nan)
    denom3[pairs[:, 0], pairs[:, 1]] = logsumexp(third, axis=1)
    lp = s[ix[:, 0], 0] - logsumexp(s[:, 0])
    lp += s[ix[:, 1], 1] - logsumexp(second, axis=1)[ix[:, 0]]
    lp += s[ix[:, 2], 2] - denom3[ix[:, 0], ix[:, 1]]
    q = np.exp(lp)
    if not np.isclose(q.sum(), 1, atol=1e-10):
        raise ValueError("Joint normalization failure")
    positions = np.stack([np.bincount(ix[:, k], weights=q, minlength=n) for k in range(3)], axis=1)
    return ix, q, positions.cumsum(axis=1)


def pool_probabilities(ix, q, n):
    pair_index = np.array(list(itertools.combinations(range(n), 2)))
    trio_index = np.array(list(itertools.combinations(range(n), 3)))
    pair_lookup = np.full((n, n), -1, dtype=int)
    for t, (a,b) in enumerate(pair_index): pair_lookup[a,b] = pair_lookup[b,a] = t
    qnl = np.bincount(pair_lookup[ix[:,0], ix[:,1]], weights=q, minlength=len(pair_index))
    qpl = sum(np.bincount(pair_lookup[ix[:,a],ix[:,b]],weights=q,minlength=len(pair_index)) for a,b in [(0,1),(0,2),(1,2)])
    trio_lookup = {tuple(t): k for k,t in enumerate(trio_index)}
    keys = np.sort(ix, axis=1)
    tla = np.bincount([trio_lookup[tuple(t)] for t in keys], weights=q, minlength=len(trio_index))
    return pair_index, trio_index, qnl, qpl, tla


def category_encode(frame, train, cols):
    x = frame[cols].copy()
    cats = [c for c in cols if not pd.api.types.is_numeric_dtype(x[c])]
    vocabulary = {}
    for c in cats:
        values = sorted(frame.loc[train,c].dropna().unique().tolist())
        vocabulary[c] = values
        x[c] = pd.Categorical(x[c], categories=values)
    return x, vocabulary


def temperature_fit(frame, scores, stage, bounds):
    parts = []
    for _, one in frame.groupby("race_key", sort=False):
        eligible = (one.outcome > stage) if stage else pd.Series(True, index=one.index)
        ids = one.index[eligible].to_numpy()
        values = scores[ids, stage]
        truth = np.flatnonzero(one.loc[ids, "outcome"].to_numpy() == stage+1)
        if len(truth) != 1: raise ValueError("Temperature target unavailable")
        parts.append((values, int(truth[0])))
    # Pad once; scalar searches do not repeatedly iterate over DataFrames.
    padded = np.full((len(parts), max(len(v) for v,_ in parts)), -np.inf)
    actual = np.empty(len(parts))
    for i,(v,t) in enumerate(parts): padded[i,:len(v)], actual[i] = v, v[t]
    result = minimize_scalar(lambda t: float(np.mean(logsumexp(padded/t, axis=1)-actual/t)), bounds=bounds, method="bounded")
    if not result.success: raise ValueError("Temperature optimizer failed")
    return float(result.x)


def train_bundle(frame, columns, year, cfg, dest):
    train = frame.year.between(cfg["training_start_year"],year-3)
    valid, cal, test = frame.year.eq(year-2), frame.year.eq(year-1), frame.year.eq(year)
    if not all(mask.any() for mask in [train,valid,cal,test]): raise ValueError("Empty chronological split")
    x, vocab = category_encode(frame, train, columns)
    dest.mkdir(parents=True, exist_ok=False)
    scores = np.zeros((len(frame),3))
    info = []
    params = cfg["training"].copy()
    rounds, early = params.pop("max_rounds"), params.pop("early_stopping_rounds")
    params["seed"] = cfg["seed"]
    for stage in range(3):
        risk = frame.outcome.gt(stage) if stage else pd.Series(True,index=frame.index)
        y = frame.outcome.eq(stage+1).astype(int)
        weights = 1 / risk.groupby(frame.race_key).transform("sum")
        def dataset(mask): return lgb.Dataset(x[mask & risk], label=y[mask & risk], weight=weights[mask & risk], free_raw_data=False)
        initial = lgb.train(params, dataset(train), num_boost_round=rounds, valid_sets=[dataset(valid)],
                            callbacks=[lgb.early_stopping(early, verbose=False)])
        chosen = initial.best_iteration
        model = lgb.train(params, dataset(train | valid), num_boost_round=chosen)
        model.save_model(str(dest / f"position_{stage+1}.txt"))
        for mask in [cal,test]: scores[mask,stage] = model.predict(x[mask],raw_score=True)
        gain = model.feature_importance(importance_type="gain")
        info.append({"stage":stage+1,"trees":chosen,"train_runners":int(((train|valid)&risk).sum()),
                     "feature_gain":dict(sorted(zip(columns,map(float,gain)), key=lambda p:-p[1]))})
    temperatures = [temperature_fit(frame[cal],scores,stage,cfg["temperature_bounds"]) for stage in range(3)]
    metadata = {"evaluation_year":year,"final_training_year_end":year-2,"early_stopping_year":year-2,
                "calibration_year":year-1,"features":columns,"category_vocabulary":vocab,"temperatures":temperatures,"stages":info,
                "model_hashes":{p.name:sha(p) for p in dest.glob("*.txt")}}
    save_json(dest / "metadata.json",metadata)
    return scores, test, metadata


def binary_metrics(p,y):
    p = np.clip(p,1e-12,1-1e-12)
    return float(np.mean((p-y)**2)), float(np.mean(-(y*np.log(p)+(1-y)*np.log1p(-p))))


def evaluate(frame, scores, temps, name, year):
    runner_rows, race_rows = [], []
    for key, one in frame.groupby("race_key",sort=False):
        ids = one.index.to_numpy()
        ix, q, margins = joint(scores[ids], temps)
        pair_ix,trio_ix,qnl,qpl,tla = pool_probabilities(ix,q,len(one))
        outcome = one.outcome.to_numpy()
        truth = [int(np.flatnonzero(outcome==k)[0]) for k in (1,2,3)]
        sorted_truth = tuple(sorted(truth))
        actual = np.all(ix==truth,axis=1)
        pair_actual = np.all(pair_ix==sorted(truth[:2]),axis=1)
        qpl_y = np.array([all(t in truth for t in pair) for pair in pair_ix],dtype=int)
        trio_actual = np.all(trio_ix==sorted_truth,axis=1)
        order3 = np.argsort(-margins[:,2],kind="stable")
        axis = int(np.argmax(margins[:,0]))
        fixed6 = {tuple(sorted([order3[0],a,b])) for a,b in itertools.combinations(order3[1:5],2)}
        trios6 = set(map(tuple,trio_ix[np.argsort(-tla,kind="stable")[:6]]))
        r = {"race_key":key,"meet":int(one.meet.iloc[0]),"race_date":str(one.race_date.iloc[0].date()),
             "evaluation_year":year,"variant":name,"field_size":len(one),"grade":None if pd.isna(one.grade.iloc[0]) else int(one.grade.iloc[0]),
             "zero_observed_history_present":bool(one.history_count.eq(0).any()),"ordered_top3_nll":float(-np.log(q[actual].sum())),
             "trio_nll":float(-np.log(tla[trio_actual].sum())),"qnl_nll":float(-np.log(qnl[pair_actual].sum())),
             "axis_win_hit":int(axis==truth[0]),"top3_first_hit":int(order3[0] in truth),
             "top5_contains_podium":int(set(truth).issubset(order3[:5])),"top6_trio_hit":int(sorted_truth in trios6),
             "fixed_axis6_trio_hit":int(sorted_truth in fixed6),
             "qnl_first_hit":int(pair_actual[int(np.argmax(qnl))]),"qpl_first_hit":int(qpl_y[int(np.argmax(qpl))]),
             "top6_trio_probability":float(np.sort(tla)[-6:].sum()),"joint_sum_error":float(abs(q.sum()-1)),
             "marginal_sum_error":float(np.max(np.abs(margins.sum(axis=0)-[1,2,3])))}
        r["qpl_brier"],r["qpl_logloss"] = binary_metrics(qpl,qpl_y)
        for k,target in enumerate([outcome==1,outcome<=2,outcome<=3]):
            r[f"top{k+1}_brier"],r[f"top{k+1}_logloss"] = binary_metrics(margins[:,k],target.astype(int))
        race_rows.append(r)
        for loc, (_,entry) in enumerate(one.iterrows()):
            runner_rows.append({**{c:entry[c] for c in KEY},"meet":int(entry.meet),"race_date":entry.race_date,
                "evaluation_year":year,"variant":name,"outcome":int(entry.outcome),"field_size":len(one),
                "score_win":float(scores[ids[loc],0]),"score_second":float(scores[ids[loc],1]),"score_third":float(scores[ids[loc],2]),
                "prob_win":float(margins[loc,0]),"prob_top2":float(margins[loc,1]),"prob_top3":float(margins[loc,2])})
    return runner_rows,race_rows


def summaries(races, runners, cfg):
    metrics = [c for c in races.columns if c.endswith(("_nll","_brier","_logloss","_hit")) or c=="top5_contains_podium"]
    rows = []
    for (meet,variant),all_years in races.groupby(["meet","variant"]):
        for period,one in [("all",all_years), *[(str(y),g) for y,g in all_years.groupby("evaluation_year")]]:
            row = {"meet":int(meet),"variant":variant,"period":period,"races":len(one)}
            row.update({m:float(one[m].mean()) for m in metrics})
            rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "metrics.csv",index=False)
    calibration = []
    for (meet,name,year),one in runners.groupby(["meet","variant","evaluation_year"]):
        for k,col in enumerate(["prob_win","prob_top2","prob_top3"],1):
            bins = np.minimum((one[col]*10).astype(int),9)
            for b,cell in one.groupby(bins):
                calibration.append({"meet":int(meet),"variant":name,"year":int(year),"target":k,"bin":int(b),"runners":len(cell),
                                    "mean_probability":float(cell[col].mean()),"hit_rate":float(cell.outcome.le(k).mean())})
    pd.DataFrame(calibration).to_csv(OUT / "calibration.csv",index=False)
    condition = races.groupby(["meet","variant","evaluation_year","zero_observed_history_present"],dropna=False)[metrics].mean()
    condition["races"] = races.groupby(["meet","variant","evaluation_year","zero_observed_history_present"]).size()
    condition.to_csv(OUT / "experience_metrics.csv")
    differences = []
    rng = np.random.default_rng(cfg["seed"])
    for meet in cfg["venues"]:
        a = races[(races.meet==meet)&races.variant.eq("history")]
        b = races[(races.meet==meet)&races.variant.eq("history_records")]
        paired = a.merge(b,on="race_key",validate="one_to_one",suffixes=("_base","_record"))
        for metric in ["ordered_top3_nll","top1_brier","top2_brier","top3_brier","top6_trio_hit","top5_contains_podium"]:
            delta = paired[f"{metric}_record"] - paired[f"{metric}_base"]
            groups = pd.DataFrame({"day":paired.race_date_base,"delta":delta}).groupby("day").delta.agg(["sum","size"]).to_numpy()
            picks = rng.integers(0,len(groups),size=(cfg["bootstrap_draws"],len(groups)))
            draws = groups[picks]
            intervals = np.quantile(draws[:,:,0].sum(axis=1)/draws[:,:,1].sum(axis=1),[.025,.975])
            differences.append({"meet":meet,"metric":metric,"record_minus_history":float(delta.mean()),"day_cluster_95_ci":intervals.tolist(),"races":len(paired)})
    save_json(OUT / "paired_differences.json",differences)
    return summary, differences


def train():
    cfg = config()
    audit = json.loads((OUT / "data_audit.json").read_text())
    if audit["config_sha256"] != sha(HERE / "config.json") or audit["code_sha256"] != sha(__file__):
        raise ValueError("Frozen code/config changed after prepare")
    for file,digest in audit["input_hashes"].items():
        if sha(OUT/file)!=digest: raise ValueError("Prepared input changed: "+file)
    (OUT / "models").mkdir(exist_ok=False)
    frame = pd.read_parquet(OUT / "features.parquet").merge(pd.read_parquet(OUT / "labels.parquet"),on=KEY,validate="one_to_one")
    cols = json.loads((OUT / "feature_contract.json").read_text())
    all_runner, all_race, fits = [], [], []
    for meet in cfg["venues"]:
        one = frame[frame.meet.eq(meet)].reset_index(drop=True)
        for year in cfg["evaluation_years"]:
            test = one.year.eq(year)
            r,e = evaluate(one[test],np.zeros((len(one),3)),[1,1,1],"uniform",year)
            all_runner.extend(r); all_race.extend(e)
            for variant in cfg["variants"]:
                print(f"Training meet={meet} year={year} variant={variant}",flush=True)
                dest = OUT / "models" / f"{meet}_{year}_{variant}"
                scores,test,meta = train_bundle(one,cols[variant],year,cfg,dest)
                fits.append({"meet":meet,"variant":variant,**meta})
                r,e = evaluate(one[test],scores,meta["temperatures"],variant,year)
                all_runner.extend(r); all_race.extend(e)
                print(f"Evaluated {len(e)} races; temperatures={meta['temperatures']}",flush=True)
    runners,races = pd.DataFrame(all_runner),pd.DataFrame(all_race)
    runners.to_parquet(OUT / "runner_predictions.parquet",index=False)
    races.to_csv(OUT / "race_metrics.csv",index=False)
    summary, differences = summaries(races,runners,cfg)
    import importlib.metadata as packages
    result = {"experiment":cfg["experiment"],"data_audit_sha256":sha(OUT / "data_audit.json"),"config_sha256":sha(HERE / "config.json"),
              "code_sha256":sha(__file__),"production_registry_sha256":sha(ROOT / "config/prediction_model_registry.json"),
              "packages":{p:packages.version(p) for p in ["duckdb","lightgbm","pandas","numpy","scipy","pyarrow"]},
              "models":fits,"metrics":summary.to_dict("records"),"paired_differences":differences,
              "independent_future_test":False,"production_changed":False,
              "result_hashes":{p.name:sha(p) for p in OUT.iterdir() if p.is_file()}}
    save_json(OUT / "summary.json",result)
    write_report(audit,summary,differences)
    print("Completed: "+str(OUT / "REPORT.md"),flush=True)


def write_report(audit,summary,differences):
    lines = ["# 더러브렛 기준모델 v1 — 시간순 후향 평가", "", "서울·부산 각각의 과거 성적 기준선과 원시 기록 추가 기준선을 비교했다. 운영·제주 모델 변경 없음.",
             "",f"- 원천: {audit['source_races']:,}경주·{audit['source_rows']:,}행, 최신 {audit['source_date_end']}",
             f"- 2017년 이후 학습/검증/보정/평가 프레임: {audit['feature_races']:,}경주·{audit['feature_rows']:,}출발마",
             "- 2024·2025·2026년을 매년 이전 자료만으로 학습·보정해 평가. 2026년은 9월까지 일부 기간.",
             "- 출발마 명단을 결과에서 재구성했으므로 사전 실전 성능으로 표시하지 않는다. 상위 동착 등 제외 원장은 cohort_ledger.csv 참조.",
             "- history=과거 성적/상태, history_records=완주 기록 지수·과거 구간 기록 추가. 함수율 보정·기수·예상 전개는 미추가.","",
             "## 전체 기간", "", "| 경마장 | 모델 | 경주 | 우승축 | 입상 1순위 | 상위5두 포함 | 삼복6조합 | 복승1조합 | 복연1조합 | 착순 NLL ↓ | Top3 Brier ↓ |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _,r in summary[summary.period.eq("all")].iterrows():
        lines.append(f"| { {1:'서울',3:'부산'}[r.meet]} | {r.variant} | {r.races:,} | {r.axis_win_hit:.1%} | {r.top3_first_hit:.1%} | {r.top5_contains_podium:.1%} | {r.top6_trio_hit:.1%} | {r.qnl_first_hit:.1%} | {r.qpl_first_hit:.1%} | {r.ordered_top3_nll:.4f} | {r.top3_brier:.4f} |")
    lines += ["", "## 연도별", "", "| 경마장 | 연도 | 모델 | 경주 | 착순 NLL ↓ | 우승축 | 상위5두 포함 | 삼복6조합 |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for _,r in summary[summary.period.ne("all")].iterrows():
        lines.append(f"| { {1:'서울',3:'부산'}[r.meet]} | {r.period} | {r.variant} | {r.races:,} | {r.ordered_top3_nll:.4f} | {r.axis_win_hit:.1%} | {r.top5_contains_podium:.1%} | {r.top6_trio_hit:.1%} |")
    lines += ["", "## 기록 추가 효과", "", "차이는 history_records−history다. NLL/Brier는 음수가 개선, 적중률은 양수가 개선이다. 경주일 묶음 bootstrap 95% 구간으로 단일 경주 독립 가정을 줄였다.", "",
              "| 경마장 | 지표 | 변화 | 95% 구간 |", "|---|---|---:|---:|"]
    for r in differences:
        lo,hi = r['day_cluster_95_ci']
        lines.append(f"| { {1:'서울',3:'부산'}[r['meet']]} | {r['metric']} | {r['record_minus_history']:+.5f} | {lo:+.5f} ~ {hi:+.5f} |")
    lines += ["", "## 해석과 다음 단계", "", "확률과 동일 비용 선택 성능을 구분한다. 균등 기준 대비 개선은 예측 신호의 존재를 뜻하며 현행 운영 모델 대비 우위나 수익을 뜻하지 않는다. 균등 분포의 동률은 마번 순서로 결정되므로 균등 기준의 선택 적중률은 정보 없는 동률 규칙의 결과다.",
              "", "확률 보정표(calibration.csv)와 관측 국내 출발이력 0회 말 포함 여부(experience_metrics.csv)를 함께 확인한다. 관측 이력 0회는 공식 신마/해외 경력 0회를 뜻하지 않는다. 이미 관찰한 과거 연도이고 후보를 앞으로 반복 비교할 예정이므로 독립적인 미래 성능 확정이 아니다.",
              "", "다음 실험은 동일 표본에서 함수율 환산 유무 비교, 기록 상승·거리 적성 보완, 과거 초반능력으로 예상한 편성 경쟁을 순차 추가한다. 현행 모델과의 직접 비교는 같은 경주·입력·시점을 복원한 뒤 진행한다. 사전 공개시각을 입증한 출마표와 신규 예측을 저장하는 미래 평가가 필요하다."]
    (OUT / "REPORT.md").write_text("\n".join(lines)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare","train"])
    args = parser.parse_args()
    {"prepare":prepare,"train":train}[args.mode]()
