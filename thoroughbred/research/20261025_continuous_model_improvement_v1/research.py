"""Bounded local ablations against the frozen personal_t2 recipe; no DB writes."""

from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sys
import time
import warnings
import torch  # noqa: F401 -- choose macOS OpenMP before LightGBM
import duckdb
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE / "outputs"
PREVIOUS = R / "20261024_training_state_v1"
sys.path.insert(0, str(PREVIOUS))
import study_common as previous

KEY = previous.KEY
CORE = previous.CORE
DB = previous.old.DB
HISTORY = previous.old.HISTORY
REGISTRY = ROOT / "config/prediction_model_registry.json"
PREVIOUS_BYTES = 204_224_091
REPORT_TERMS = {
    "contact": r"부딪|충돌|접촉|진로|방해|제한",
    "start": r"출발|진입|출발대",
    "behavior": r"기대|기댐|사행|머리|주행불량",
    "vet": r"마체|절음|출혈|파행|부상|다리",
}
SANCTION_TERMS = {
    "start": r"출발심사|진입|출발불량|출발자세",
    "running": r"주행심사|주행불량|능력미달|경주부적격",
    "vet": r"마체|출혈|절음|파행|부상|다리",
}
REPORT_COLS = [
    "report_support3",
    "report_mentions_last",
    "report_contact_last",
    "report_start_last",
    "report_behavior_last",
    "report_vet_last",
    "report_mentions_mean3",
    "sanctions90",
    "sanction_start90",
    "sanction_running90",
    "sanction_vet90",
    "sanction_gap365",
]
BODY_COLS = [
    "body_previous_kg",
    "body_mean3_kg",
    "body_previous_vs_prior3_kg",
    "body_sd5_kg",
    "body_n5",
    "burden_pct_previous_body",
]
VARIANTS = {"report_context": REPORT_COLS, "past_bodymass": BODY_COLS, "axis_rank": []}


def require(condition, message="Research invariant failed"):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    require(path.resolve().is_relative_to(HERE), "Output escapes study")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def storage():
    total = sum(
        p.stat().st_size for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    require(total + PREVIOUS_BYTES < 300_000_000, "Session storage ceiling")
    return total


def base_frame():
    return previous.frame(2)


def feature_columns():
    return previous.old.features()["state_gbm"] + previous.BASIC + previous.PERSONAL


def freeze():
    require(not (OUT / "input_manifest.json").exists(), "Already frozen")
    assets = [
        HERE / "PLAN.md",
        HERE / "research.py",
        HERE / "verify.py",
        CORE,
        DB,
        HISTORY,
        PREVIOUS / "study_common.py",
        PREVIOUS / "train_models.py",
        PREVIOUS / "outputs/feature_delta_t2.parquet",
        PREVIOUS / "outputs/runner_probabilities.parquet",
        PREVIOUS / "outputs/race_metrics.parquet",
        previous.old.base.SOURCE / "features.parquet",
        previous.old.base.SOURCE / "feature_contract.json",
        previous.old.PREV / "outputs/state_features.parquet"
        if hasattr(previous.old, "PREV")
        else R / "20261022_dynamic_race_model_v1/outputs/state_features.parquet",
        R / "20261022_dynamic_race_model_v1/common.py",
        R / "20261022_dynamic_race_model_v1/outputs/state_contract.json",
        previous.old.BASE / "run.py",
        previous.old.BASE / "probability.py",
        previous.old.BASE / "config.json",
        REGISTRY,
    ]
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            folder = PREVIOUS / "outputs/models" / f"personal_t2_{meet}_{year}"
            assets += [folder / x for x in ["model.txt", "metadata.json", "scores.parquet"]]
    save(
        OUT / "input_manifest.json",
        {str(p.relative_to(ROOT)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in assets},
    )
    save(
        OUT / "feature_contract.json",
        {
            "base": feature_columns(),
            "report_context": REPORT_COLS,
            "past_bodymass": BODY_COLS,
            "patterns": {
                "paragraph_context": REPORT_TERMS,
                "official_horse_sanctions": SANCTION_TERMS,
            },
            "lag_days": 2,
            "report_field": "judgement",
            "body_valid_kg": [300, 650],
            "historical_publication_time_verified": False,
            "paragraphs_assign_victim_or_blame": False,
        },
    )
    save(
        OUT / "protocol_frozen.json",
        {
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "main_metric": "axis_top3_2026_all1288",
            "stability_scope": "2024_2026_all4799",
            "variants": list(VARIANTS),
            "seed": 20261004,
            "max_rounds": 800,
            "early_stopping": 25,
            "initial_fits": 18,
            "final_models": 18,
            "evaluation_started": False,
            "bootstrap_draws": 2000,
            "bootstrap_seed": 20261025,
            "familywise_interval_level": 1 - 0.05 / 3,
            "rank_params": {
                "objective": "lambdarank",
                "metric": "ndcg",
                "ndcg_eval_at": [1, 3],
                "lambdarank_truncation_level": 3,
                "label_gain": [0, 1],
                "first_metric_only": True,
            },
            "new_independent_test": False,
            "production_changed": False,
        },
    )
    print("Frozen", flush=True)


def check():
    for name, item in json.loads((OUT / "input_manifest.json").read_text()).items():
        require(sha(ROOT / name) == item["sha256"], "Frozen input changed: " + name)


def event_key(meet, date, race):
    return (
        meet.astype(int).astype(str)
        + ":"
        + pd.to_datetime(date).dt.strftime("%Y%m%d")
        + ":"
        + race.astype(int).astype(str)
    )


def sources():
    h = pd.read_parquet(HISTORY, columns=KEY + ["race_date"])
    with duckdb.connect(str(DB), read_only=True) as db:
        weight = db.execute("""SELECT cast(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||cast(race_no AS VARCHAR) race_key,
             chul_no program_no,hr_no horse_id,horse_weight_kg body_weight
             FROM entry_result WHERE canonical_meet IN (1,3)""").df()
    require(not weight.duplicated(KEY).any(), "Duplicate weight identity")
    h = h.merge(weight, on=KEY, how="left", validate="one_to_one")
    h.body_weight = h.body_weight.where(h.body_weight.between(300, 650))
    with duckdb.connect(str(CORE), read_only=True) as db:
        cov = db.execute(
            "SELECT actual_meet_code,event_date,race_no,report_observation_count FROM steward_report_event_coverage WHERE actual_meet_code IN (1,3)"
        ).df()
        mentions = db.execute("""SELECT horse_id,event_date,actual_meet_code,race_no,paragraph_raw
             FROM horse_steward_history WHERE actual_meet_code IN (1,3)
             AND source_report_text_field='judgement' AND parent_report_event_date=event_date""").df()
        sanctions = db.execute("""SELECT s.linked_horse_id_raw horse_id,s.event_date,o.kind,o.reason
             FROM steward_horse_sanctions s JOIN steward_sanction_observations o
             ON s.sanction_observation_locator=o.observation_locator
             WHERE s.actual_meet_code IN (1,3) AND s.target_event_entry_link_verified""").df()
    cov["race_key"] = event_key(cov.actual_meet_code, cov.event_date, cov.race_no)
    require(not cov.race_key.duplicated().any(), "Duplicate report coverage")
    cov["report_available"] = cov.report_observation_count.gt(0).astype(float)
    mentions["race_key"] = event_key(
        mentions.actual_meet_code, mentions.event_date, mentions.race_no
    )
    mentions = mentions.drop_duplicates(["horse_id", "race_key", "paragraph_raw"])
    for name, pattern in REPORT_TERMS.items():
        mentions[name] = mentions.paragraph_raw.str.contains(pattern, regex=True).astype(float)
    annotated = (
        mentions.groupby(["race_key", "horse_id"], sort=False)
        .agg(mentions=("paragraph_raw", "size"), **{k: (k, "max") for k in REPORT_TERMS})
        .reset_index()
    )
    h = h.merge(
        cov[["race_key", "report_available"]], on="race_key", how="left", validate="many_to_one"
    )
    h = h.merge(annotated, on=["race_key", "horse_id"], how="left", validate="one_to_one")
    for col in ["mentions", *REPORT_TERMS]:
        h[col] = h[col].fillna(0).where(h.report_available.eq(1))
    h["race_date"] = pd.to_datetime(h.race_date)
    h = h.sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    require(not h.duplicated(["horse_id", "race_date"]).any(), "Duplicate historical start")
    sanctions = sanctions.drop_duplicates(["horse_id", "event_date", "kind", "reason"]).copy()
    sanctions["race_date"] = pd.to_datetime(sanctions.event_date)
    sanctions["count"] = 1.0
    text = sanctions.kind.fillna("") + " " + sanctions.reason.fillna("")
    for name, pattern in SANCTION_TERMS.items():
        sanctions[name] = text.str.contains(pattern, regex=True).astype(float)
    sanctions = (
        sanctions.groupby(["horse_id", "race_date"], sort=True)[["count", *SANCTION_TERMS]]
        .sum()
        .reset_index()
    )
    return h, sanctions


def slots(f, h, k=5):
    out = np.full((len(f), k), -1, dtype=int)
    lookup = h.groupby("horse_id", sort=False).indices
    for horse, ix in f.groupby("horse_id", sort=False).indices.items():
        hi = lookup.get(horse)
        if hi is None:
            continue
        dates = h.race_date.to_numpy()[hi]
        pos = (
            np.searchsorted(dates, f.cutoff_date.to_numpy()[ix], side="right")[:, None]
            - 1
            - np.arange(k)
        )
        valid = pos >= 0
        out[ix] = np.where(valid, hi[np.maximum(pos, 0)], -1)
    return out


def construct(f, h, sanctions):
    ix = slots(f, h)

    def values(col):
        return np.where(ix >= 0, h[col].to_numpy(float)[np.maximum(ix, 0)], np.nan)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        body = values("body_weight")
        b = pd.DataFrame(
            {
                "row_number": f.row_number.to_numpy(),
                "body_previous_kg": body[:, 0],
                "body_mean3_kg": np.nanmean(body[:, :3], axis=1),
                "body_previous_vs_prior3_kg": body[:, 0] - np.nanmean(body[:, 1:4], axis=1),
                "body_sd5_kg": np.nanstd(body, axis=1),
                "body_n5": np.isfinite(body).sum(1),
                "burden_pct_previous_body": 100 * f.current_carried_weight.to_numpy() / body[:, 0],
            }
        )
        b["body_sd5_kg"] = b.body_sd5_kg.where(b.body_n5 >= 2)
        avail = values("report_available")[:, :3]
        denominator = (ix[:, :3] >= 0).sum(1)
        b["report_support3"] = np.where(
            denominator > 0, (avail == 1).sum(1) / np.maximum(denominator, 1), np.nan
        )
        b["report_mentions_last"] = values("mentions")[:, 0]
        b["report_mentions_mean3"] = np.nanmean(values("mentions")[:, :3], axis=1)
        for name in REPORT_TERMS:
            b["report_" + name + "_last"] = values(name)[:, 0]
    b["sanction_gap365"] = np.nan
    for name in ["sanctions90", "sanction_start90", "sanction_running90", "sanction_vet90"]:
        b[name] = 0.0
    lookup = sanctions.groupby("horse_id", sort=False).indices
    for horse, rows in f.groupby("horse_id", sort=False).indices.items():
        si = lookup.get(horse)
        if si is None:
            continue
        dates = sanctions.race_date.to_numpy()[si]
        cutoff = f.cutoff_date.to_numpy()[rows]
        end = np.searchsorted(dates, cutoff, side="right")
        begin = np.searchsorted(dates, cutoff - np.timedelta64(90, "D"), side="right")
        for source, target in [
            ("count", "sanctions90"),
            ("start", "sanction_start90"),
            ("running", "sanction_running90"),
            ("vet", "sanction_vet90"),
        ]:
            sums = np.r_[0.0, np.cumsum(sanctions[source].to_numpy()[si])]
            b.loc[rows, target] = sums[end] - sums[begin]
        gap = (f.race_date.to_numpy()[rows] - dates[np.maximum(end - 1, 0)]) / np.timedelta64(
            1, "D"
        )
        b.loc[rows, "sanction_gap365"] = np.where((end > 0) & (gap <= 367), gap, np.nan)
    return b[["row_number"] + REPORT_COLS + BODY_COLS]


def build():
    check()
    require(not (OUT / "feature_delta.parquet").exists(), "Features already built")
    f = base_frame()
    h, sanctions = sources()
    delta = construct(f, h, sanctions)
    delta.to_parquet(OUT / "feature_delta.parquet", index=False, compression="zstd")
    evaluation = f.year.ge(2024)
    save(
        OUT / "source_audit.json",
        {
            "historical_starts": len(h),
            "sanction_days": len(sanctions),
            "source_meets": [1, 3],
            "evaluation_runners": int(evaluation.sum()),
            "evaluation_races": int(f.loc[evaluation, "race_key"].nunique()),
            "evaluation_feature_support": {
                col: {
                    "finite": int(delta.loc[evaluation, col].notna().sum()),
                    "nonzero": int(delta.loc[evaluation, col].fillna(0).ne(0).sum()),
                }
                for col in REPORT_COLS + BODY_COLS
            },
            "historical_publication_time_verified": False,
            "new_collection": False,
            "feature_sha256": sha(OUT / "feature_delta.parquet"),
        },
    )
    print("Built features", len(delta), storage(), flush=True)


def frame():
    f = base_frame()
    extra = pd.read_parquet(OUT / "feature_delta.parquet")
    require(np.array_equal(f.row_number, extra.row_number))
    return pd.concat([f, extra.drop(columns="row_number")], axis=1)


def train():
    check()
    require(
        json.loads((OUT / "feature_verification.json").read_text())["status"] == "passed",
        "Feature verification required",
    )
    f = frame()
    for variant, extra in VARIANTS.items():
        cols = feature_columns() + extra
        for meet in [1, 3]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024, 2025, 2026]:
                folder = OUT / "models" / f"{variant}_{meet}_{year}"
                if (folder / "metadata.json").exists():
                    m = json.loads((folder / "metadata.json").read_text())
                    require(sha(folder / "model.txt") == m["model_sha256"])
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                started = time.time()
                train_mask = one.year.between(2017, year - 3)
                valid, cal, test = [one.year.eq(year - d) for d in [2, 1, 0]]
                x, vocab = previous.old.base.encode(one, cols, mask=train_mask)
                labels = one.outcome.between(1, 3).astype(int)
                params = previous.old.base.cfg()["training"].copy()
                params.pop("max_rounds")
                early = params.pop("early_stopping_rounds")
                params["seed"] = 20261004
                if variant == "axis_rank":
                    params.update(
                        objective="lambdarank",
                        metric="ndcg",
                        ndcg_eval_at=[1, 3],
                        lambdarank_truncation_level=3,
                        label_gain=[0, 1],
                    )

                def data(mask):
                    kwargs = (
                        {"group": one.loc[mask].groupby("race_key", sort=False).size().to_numpy()}
                        if variant == "axis_rank"
                        else {}
                    )
                    return lgb.Dataset(
                        x.loc[mask],
                        label=labels[mask],
                        weight=1 / one.loc[mask, "field_size"],
                        **kwargs,
                    )

                history = {}
                print("Train", folder.name, flush=True)
                initial = lgb.train(
                    params,
                    data(train_mask),
                    num_boost_round=800,
                    valid_sets=[data(valid)],
                    callbacks=[
                        lgb.early_stopping(early, first_metric_only=True, verbose=False),
                        lgb.record_evaluation(history),
                    ],
                )
                model = lgb.train(
                    params, data(train_mask | valid), num_boost_round=initial.best_iteration
                )
                path = folder / "model.txt"
                model.save_model(str(path))
                cs = model.predict(x.loc[cal], raw_score=True, num_threads=4)
                ts = model.predict(x.loc[test], raw_score=True, num_threads=4)
                cf = one.loc[cal].reset_index(drop=True)
                temperature = previous.old.base.set_temperature(cf, cs)
                records = [
                    (cs[ix], cf.iloc[ix].outcome.to_numpy())
                    for ix in cf.groupby("race_key", sort=False).indices.values()
                ]
                order_temperature = previous.old.prob.fit_order_temperature(
                    records, bounds=(0.35, 4.0)
                )
                pd.concat(
                    [
                        pd.DataFrame(
                            {
                                "row_number": one.loc[cal, "row_number"],
                                "score": cs,
                                "phase": "calibration",
                            }
                        ),
                        pd.DataFrame(
                            {
                                "row_number": one.loc[test, "row_number"],
                                "score": ts,
                                "phase": "evaluation",
                            }
                        ),
                    ],
                    ignore_index=True,
                ).to_parquet(folder / "scores.parquet", index=False, compression="zstd")
                save(folder / "learning_curve.json", history)
                save(
                    folder / "metadata.json",
                    {
                        "variant": variant,
                        "meet": meet,
                        "year": year,
                        "features": cols,
                        "category_vocabulary": vocab,
                        "trees": int(initial.best_iteration),
                        "params": params,
                        "temperature": temperature,
                        "order_temperature": order_temperature,
                        "model_sha256": sha(path),
                        "feature_sha256": sha(OUT / "feature_delta.parquet"),
                        "protocol_sha256": sha(OUT / "protocol_frozen.json"),
                        "elapsed_s": time.time() - started,
                        "gain": dict(
                            zip(cols, model.feature_importance(importance_type="gain").tolist())
                        ),
                        "initial_train_races": int(one.loc[train_mask, "race_key"].nunique()),
                        "validation_races": int(one.loc[valid, "race_key"].nunique()),
                        "calibration_races": int(cf.race_key.nunique()),
                        "evaluation_races": int(one.loc[test, "race_key"].nunique()),
                    },
                )
                print(
                    "Ready",
                    folder.name,
                    "trees",
                    initial.best_iteration,
                    "seconds",
                    round(time.time() - started, 1),
                    "bytes",
                    storage(),
                    flush=True,
                )
    save(
        OUT / "training_complete.json",
        {"status": "complete", "initial_fits": 18, "final_models": 18, "lightgbm": lgb.__version__},
    )


def evaluate():
    check()
    require((OUT / "training_complete.json").exists())
    require(not (OUT / "evaluation_complete.json").exists(), "Evaluation already completed")
    save(
        OUT / "evaluation_started.json",
        {
            "protocol_sha256": sha(OUT / "protocol_frozen.json"),
            "model_metadata": {
                str(p.relative_to(ROOT)): sha(p)
                for p in sorted((OUT / "models").glob("*/metadata.json"))
            },
        },
    )
    f = base_frame()
    f = f[f.year.ge(2024)].copy()
    flags = pd.read_parquet(previous.old.BASE / "outputs/population_flags.parquet")
    f = f.merge(flags[KEY + ["normal_finisher", "ambiguous_flag"]], on=KEY, validate="one_to_one")
    require(len(f) == 50754 and f.race_key.nunique() == 4799)
    rows, runners, tickets = [], [], []
    for variant in VARIANTS:
        for meet in [1, 3]:
            for year in [2024, 2025, 2026]:
                folder = OUT / "models" / f"{variant}_{meet}_{year}"
                m = json.loads((folder / "metadata.json").read_text())
                scores = (
                    pd.read_parquet(folder / "scores.parquet")
                    .query("phase=='evaluation'")
                    .set_index("row_number")
                    .score
                )
                one = f[f.meet.eq(meet) & f.year.eq(year)].copy()
                one["score"] = one.row_number.map(scores)
                require(one.score.notna().all())
                for _, g in one.groupby("race_key", sort=False):
                    score = g.score.to_numpy(float)
                    q = previous.old.prob.trio_distribution(score, m["temperature"])
                    orders, mass = previous.old.prob.ordered_distribution(
                        score, q, m["order_temperature"]
                    )
                    row, tt, rr = previous.old.scorer.score_race(
                        g, score, orders, mass, variant, "all_starters"
                    )
                    sets = np.sort(orders, axis=1)
                    unique, inv = np.unique(sets, axis=0, return_inverse=True)
                    set_mass = np.bincount(inv, weights=mass)
                    choice = np.argsort(-np.round(set_mass, 12), kind="stable")[:6]
                    truth = g.outcome.between(1, 3).to_numpy()
                    row["trio_six"] = int(any(truth[unique[j]].all() for j in choice))
                    rows.append(row)
                    tickets.extend(tt)
                    runners.append(rr)
                print("Evaluated", variant, meet, year, flush=True)
    pd.DataFrame(rows).to_parquet(OUT / "race_metrics.parquet", index=False, compression="zstd")
    pd.concat(runners, ignore_index=True).to_parquet(
        OUT / "runner_probabilities.parquet", index=False, compression="zstd"
    )
    pd.DataFrame(tickets).to_parquet(OUT / "tickets.parquet", index=False, compression="zstd")
    save(
        OUT / "evaluation_complete.json",
        {
            "status": "complete",
            "races_per_variant": 4799,
            "race_rows": len(rows),
            "runner_rows": sum(map(len, runners)),
            "ticket_rows": len(tickets),
            "new_independent_test": False,
            "max_probability_error": max(x["coherence_max_error"] for x in rows),
        },
    )
    storage()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["freeze", "build", "train", "evaluate"])
    args = parser.parse_args()
    globals()[args.stage]()
