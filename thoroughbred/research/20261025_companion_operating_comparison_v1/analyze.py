"""Fixed matched-race comparison of axis companions; no fitting or DB access."""

from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE / "outputs"
PREVIOUS_BYTES = 227_004_940
COMPARISON = R / "20261025_operating_training_comparison_v1/outputs"
OLD_PRED = R / "20261004_close_contenders_v1/outputs/operating_runner_predictions.parquet"
NEW_PRED = R / "20261024_training_state_v1/outputs/runner_probabilities.parquet"
REGISTRY = ROOT / "config/prediction_model_registry.json"
BUNDLE = ROOT / "production_models/thoroughbred_training_state_20261025_v1"
KEY = ["race_key", "program_no", "horse_id"]
OLD_PROFILE = "thoroughbred-main-20260919-v1"
NEW_PROFILE = "thoroughbred-training-state-20261025-v1"
PRIMARY = "companion4_atleast2"
METRICS = [
    *[f"rank{i}_hit" for i in range(1, 6)],
    *[f"rank{i}_predicted" for i in range(2, 6)],
    "companion4_hits",
    "companion4_atleast2",
    "companion2_both",
    "companion3_atleast2",
    "top3_all3",
    "top4_all3",
    "top5_all3",
    "top3_hits",
    "top5_hits",
    "axis_trio6",
    *[f"actual{i}_top{k}" for i in [1, 2, 3] for k in [3, 5]],
]
POOLS = ["quinella_one", "quinella_three", "qpl_one", "qpl_three", "trio_one", "trio_six"]


def require(condition, message="Comparison invariant failed"):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    require(path.resolve().is_relative_to(HERE), "Output outside study")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def freeze():
    require(not (OUT / "input_manifest.json").exists(), "Already frozen")
    registry = json.loads(REGISTRY.read_text())
    require(registry["domains"]["thoroughbred"]["active_profile"] == NEW_PROFILE)
    old = json.loads((BUNDLE / "previous_registry.json").read_text())
    require(registry["profiles"][OLD_PROFILE] == old["profiles"][OLD_PROFILE])
    artifacts = registry["profiles"][NEW_PROFILE]["artifacts"]
    for item in artifacts.values():
        require(sha(ROOT / item["path"]) == item["sha256"], item["path"])
    old_manifest = json.loads((COMPARISON / "input_manifest.json").read_text())
    for p in [OLD_PRED, NEW_PRED]:
        require(sha(p) == old_manifest[str(p.relative_to(ROOT))]["sha256"])
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        HERE / "verify.py",
        REGISTRY,
        BUNDLE / "previous_registry.json",
        BUNDLE / "model_spec.json",
        BUNDLE / "asset_provenance.json",
        OLD_PRED,
        NEW_PRED,
        *[
            COMPARISON / x
            for x in [
                "cohort.parquet",
                "cohort_audit.json",
                "input_manifest.json",
                "verification.json",
                "race_metrics.parquet",
                "results.json",
            ]
        ],
    ]
    save(
        OUT / "input_manifest.json",
        {str(p.relative_to(ROOT)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in paths},
    )
    save(
        OUT / "protocol.json",
        {
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "primary": PRIMARY,
            "metrics": METRICS,
            "scope": "2026_matched1258",
            "ranking": "Top3 probability rounded12 descending, program ascending",
            "old_profile": OLD_PROFILE,
            "current_profile": NEW_PROFILE,
            "new_training": 0,
            "bootstrap_seed": 20261025,
            "bootstrap_draws": 2000,
            "new_independent_test": False,
            "production_changed": False,
        },
    )
    save(
        OUT / "model_identity.json",
        {
            "current_profile": NEW_PROFILE,
            "old_profile": OLD_PROFILE,
            "current_champion": registry["profiles"][NEW_PROFILE]["champion_id"],
            "old_champion": registry["profiles"][OLD_PROFILE]["champion_id"],
            "verified_current_artifacts": len(artifacts),
            "old_profile_preserved": True,
            "stored_prediction_hashes_match_verified_comparison": True,
        },
    )


def check():
    for name, value in json.loads((OUT / "input_manifest.json").read_text()).items():
        require(sha(ROOT / name) == value["sha256"], "Frozen source changed: " + name)


def aligned():
    cohort = pd.read_parquet(COMPARISON / "cohort.parquet")
    keys = set(cohort.race_key)
    old = pd.read_parquet(OLD_PRED)
    old["race_key"] = (
        old.race_key.str.replace("RACE:SEOUL:", "1:", regex=False)
        .str.replace("RACE:BUSAN:", "3:", regex=False)
        .str.replace(r":0([1-9])$", r":\1", regex=True)
    )
    old = old[old.race_key.isin(keys)].copy()
    new = pd.read_parquet(NEW_PRED)
    new = new[new.variant.eq("personal_t2") & new.race_key.isin(keys)].copy()
    for f in [old, new]:
        require(not f.duplicated(KEY).any())
        f["outcome"] = (
            pd.to_numeric(f.outcome, errors="coerce")
            .where(f.outcome.between(1, 20), 0)
            .fillna(0)
            .astype(int)
        )
    d = old[KEY + ["outcome", "prob_top3"]].merge(
        new[KEY + ["outcome", "top3"]], on=KEY, validate="one_to_one", suffixes=("_old", "_new")
    )
    require(len(d) == len(old) == len(new) == 13315, "Runner mismatch")
    require(d.outcome_old.eq(d.outcome_new).all(), "Outcome mismatch")
    d = d.rename(
        columns={"outcome_old": "outcome", "prob_top3": "old_prob", "top3": "current_prob"}
    ).drop(columns="outcome_new")
    d = d.merge(
        cohort[["race_key", "race_date", "meet", "starters"]], on="race_key", validate="many_to_one"
    )
    d = d.sort_values(["race_key", "program_no"]).reset_index(drop=True)
    require(d.groupby("race_key").size().eq(d.groupby("race_key").starters.first()).all())
    require(d.starters.min() >= 5 and d.race_key.nunique() == 1258)
    for col in ["old_prob", "current_prob"]:
        require(d[col].between(0, 1).all())
        require((d.groupby("race_key")[col].sum() - 3).abs().max() < 1e-9)
    for prefix in ["old", "current"]:
        d["_rounded"] = d[prefix + "_prob"].round(12)
        d[prefix + "_rank"] = (
            d.groupby("race_key")["_rounded"].rank(method="first", ascending=False).astype(int)
        )
    return d.drop(columns="_rounded")


def race_metrics(g, prefix):
    ranked = g.sort_values(prefix + "_rank")
    truth = ranked.outcome.between(1, 3).to_numpy()
    require(truth.sum() == 3)
    prob = ranked[prefix + "_prob"].to_numpy()
    c4 = int(truth[1:5].sum())
    row = {
        "race_key": g.race_key.iloc[0],
        "race_date": str(g.race_date.iloc[0]),
        "meet": int(g.meet.iloc[0]),
        "model": prefix,
        "axis": int(ranked.program_no.iloc[0]),
        "companion4_hits": c4,
        "companion4_atleast2": int(c4 >= 2),
        "companion2_both": int(truth[1:3].all()),
        "companion3_atleast2": int(truth[1:4].sum() >= 2),
        "axis_trio6": int(truth[0] and c4 >= 2),
    }
    for i in range(1, 6):
        row[f"rank{i}_hit"] = int(truth[i - 1])
        if i > 1:
            row[f"rank{i}_predicted"] = float(prob[i - 1])
    for k in [3, 4, 5]:
        row[f"top{k}_all3"] = int(truth[:k].sum() == 3)
        if k != 4:
            row[f"top{k}_hits"] = int(truth[:k].sum())
    for finish in [1, 2, 3]:
        rank = int(ranked.loc[ranked.outcome.eq(finish), prefix + "_rank"].iloc[0])
        for k in [3, 5]:
            row[f"actual{finish}_top{k}"] = int(rank <= k)
    return row


def summarize(wide, metrics):
    require(len(wide) > 0)
    dates, index = np.unique(wide.race_date_old.astype(str), return_inverse=True)
    counts = np.bincount(index)
    draws = np.random.default_rng(20261025).integers(0, len(dates), size=(2000, len(dates)))
    denominator = counts[draws].sum(1)
    result = {}
    for metric in metrics:
        b, a = [wide[metric + suffix].to_numpy(float) for suffix in ["_old", "_current"]]
        totals = np.bincount(index, weights=a - b)
        bootstrap = totals[draws].sum(1) / denominator
        result[metric] = {
            "old_total": float(b.sum()),
            "current_total": float(a.sum()),
            "old_mean": float(b.mean()),
            "current_mean": float(a.mean()),
            "difference": float((a - b).mean()),
            "ci95": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
            "gain_races": int((a > b).sum()),
            "loss_races": int((a < b).sum()),
        }
    return {"races": len(wide), "race_days": len(dates), "metrics": result}


def calculate():
    check()
    require(not (OUT / "results.json").exists(), "Already evaluated")
    d = aligned()
    rows = [
        race_metrics(g, prefix)
        for _, g in d.groupby("race_key", sort=False)
        for prefix in ["old", "current"]
    ]
    r = pd.DataFrame(rows)
    old, current = [r[r.model.eq(p)] for p in ["old", "current"]]
    wide = old.merge(current, on="race_key", suffixes=("_old", "_current"), validate="one_to_one")
    require(wide.rank1_hit_old.sum() == 800 and wide.rank1_hit_current.sum() == 830)
    prior = pd.read_parquet(COMPARISON / "race_metrics.parquet")
    for label, saved_label in [("old", "operating"), ("current", "personal_t2")]:
        saved = prior[prior.variant.eq(saved_label)].set_index("race_key")
        check_rows = r[r.model.eq(label)].set_index("race_key")
        require(check_rows.axis.eq(saved.loc[check_rows.index, "axis_program_no"]).all())
    same = wide.axis_old.eq(wide.axis_current)
    scopes = {
        "all_races": np.ones(len(wide), bool),
        "same_axis": same.to_numpy(),
        "same_axis_and_axis_hit": (same & wide.rank1_hit_old.eq(1)).to_numpy(),
    }
    groups = []
    for scope, mask in scopes.items():
        for meet in [0, 1, 3]:
            take = mask & (True if meet == 0 else wide.meet_old.eq(meet).to_numpy())
            row = summarize(wide.loc[take], METRICS)
            row.update(scope=scope, meet=meet)
            groups.append(row)
    old_native = prior[prior.variant.eq("operating")]
    new_native = prior[prior.variant.eq("personal_t2")]
    joined = old_native.merge(
        new_native, on="race_key", suffixes=("_old", "_current"), validate="one_to_one"
    )
    pools = []
    for meet in [0, 1, 3]:
        row = summarize(joined if meet == 0 else joined[joined.meet_old.eq(meet)], POOLS)
        row["meet"] = meet
        pools.append(row)
    d.to_parquet(OUT / "matched_ranks.parquet", index=False, compression="zstd")
    r.to_parquet(OUT / "race_metrics.parquet", index=False, compression="zstd")
    save(
        OUT / "results.json",
        {
            "primary": PRIMARY,
            "groups": groups,
            "native_pool_comparison": pools,
            "matched_races": 1258,
            "matched_starters": 13315,
            "new_fits": 0,
            "new_independent_test": False,
            "live_publications_compared": False,
            "production_changed": False,
            "scope_limits": "Common-axis-and-hit subset is retrospective diagnosis, not a race filtering policy.",
        },
    )
    require(
        sum(
            p.stat().st_size
            for p in HERE.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        + PREVIOUS_BYTES
        < 300_000_000
    )
    for row in groups:
        if row["scope"] == "all_races":
            print(
                json.dumps(
                    {
                        "scope": row["scope"],
                        "meet": row["meet"],
                        "races": row["races"],
                        "primary": row["metrics"][PRIMARY],
                        "axis_trio6": row["metrics"]["axis_trio6"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["freeze", "calculate"])
    globals()[p.parse_args().stage]()
