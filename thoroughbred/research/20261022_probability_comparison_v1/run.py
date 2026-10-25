"""Bounded local research. Read existing sources; write only this experiment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE / "outputs"
SOURCE = R / "20261009_gate_front_late_v1/outputs"
ABILITY = R / "20261008_profile_carried_weight_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]


def cfg():
    return json.loads((HERE / "config.json").read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    assert path.resolve().is_relative_to(HERE), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def storage_check():
    sizes = [(p, p.stat().st_size) for p in HERE.rglob("*") if p.is_file()]
    assert all(n < cfg()["max_single_file_bytes"] for p, n in sizes)
    assert sum(n for p, n in sizes) < cfg()["max_new_bytes"]
    return sum(n for p, n in sizes)


def contracts():
    full = json.loads((SOURCE / "feature_contract.json").read_text())["full103"]
    ability = json.loads((ABILITY / "research_baseline_selection.json").read_text())["features"]
    shared = ["section_previous_distance", "section_same_distance_n5"]
    early = [c for c in full if c.startswith("section_early_") or c.startswith("dirgate_")]
    early += [c for c in full if c.startswith("style_role") or c in ["style_solo_mean5", "style_group_mean_relative_mean5"]]
    late = [c for c in full if c.startswith(("section_last600_", "section_late_", "rolelate_"))]
    late += [c for c in full if c.startswith(("style_middle_", "style_gain", "style_recovery_", "style_fade_"))]
    sets = {"ability22": ability, "early47": ability + shared + early,
            "late66": ability + shared + late, "additive89": ability + shared + early + late,
            "full103": full}
    for name, cols in sets.items():
        assert len(cols) == int("".join(c for c in name if c.isdigit())), (name, len(cols))
        assert len(cols) == len(set(cols))
        assert not any(any(s in c for s in ["jockey", "trainer", "aux_", "outcome", "label"]) for c in cols)
    assert set(sets["additive89"]) < set(full)
    return sets


def frozen_paths():
    paths = [HERE / "PLAN.md", HERE / "config.json", SOURCE / "features.parquet",
             SOURCE / "feature_contract.json", SOURCE / "runner_predictions.parquet",
             ABILITY / "research_baseline_selection.json", ROOT / "config/prediction_model_registry.json"]
    for venue in cfg()["venues"]:
        for year in cfg()["evaluation_years"]:
            for name in ["ability22", "full103"]:
                folder, filename = source_model(name, venue, year)
                paths += [folder / filename, folder / "metadata.json"]
    return paths


def source_model(variant, venue, year):
    if variant == "ability22":
        return ABILITY / "models" / f"{venue}_{year}_month_gate_weight22", "top3.txt"
    return SOURCE / "models" / f"full103_{venue}_{year}", "model.txt"


def freeze():
    OUT.mkdir(exist_ok=True)
    manifest = {str(p.relative_to(ROOT)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in frozen_paths()}
    target = OUT / "input_manifest.json"
    if target.exists():
        assert json.loads(target.read_text()) == manifest, "Frozen source/plan changed"
    else:
        save(target, manifest)
        save(OUT / "protocol_frozen.json", {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "plan_sha256": sha(HERE / "PLAN.md"), "config_sha256": sha(HERE / "config.json"),
            "new_evaluation_started": False, "initial_run_code_sha256": sha(HERE / "run.py")})
    save(OUT / "feature_contract.json", contracts())
    print("Frozen protocol and inputs", flush=True)


def check_inputs():
    for name, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / name) == expected["sha256"], name


def load_frame():
    cols = list(dict.fromkeys(KEY + ["meet", "race_date", "year", "grade_raw", "outcome",
        "cutoff_date", "history_source_date", "profile_source_date", "weight_source_date"] + contracts()["full103"]))
    f = pd.read_parquet(SOURCE / "features.parquet", columns=cols)
    assert len(f) == 178497 and not f.duplicated(KEY).any()
    assert f.meet.isin([1, 3]).all() and f.year.ge(2017).all()
    f = f.sort_values(["meet", "race_date", "race_key", "program_no"]).reset_index(drop=True)
    f["row_number"] = np.arange(len(f))
    for col in ["history_source_date", "profile_source_date", "weight_source_date"]:
        assert (f[col].isna() | f[col].le(f.cutoff_date)).all(), col
    g = f.groupby("race_key", sort=False)
    assert g.year.nunique().eq(1).all()
    assert g.size().eq(g.field_size.first()).all()
    for pos in [1, 2, 3]:
        assert f.outcome.eq(pos).groupby(f.race_key).sum().eq(1).all(), "Nonunique podium label"
    return f


def encode(f, cols, mask=None, vocabulary=None):
    x = f[cols].copy()
    vocab = {} if vocabulary is None else vocabulary.copy()
    for col in cols:
        if not pd.api.types.is_numeric_dtype(x[col]):
            if vocabulary is None:
                vocab[col] = sorted(f.loc[mask, col].dropna().unique().tolist())
            x[col] = pd.Categorical(x[col], categories=vocab[col])
    return x, vocab


@lru_cache(maxsize=32)
def triples(n):
    return np.array(list(itertools.combinations(range(n), 3)), dtype=int)


def set_temperature(frame, score):
    rows, truth = [], []
    for ix in frame.groupby("race_key", sort=False).indices.values():
        g = frame.iloc[ix]
        sets = triples(len(g))
        rows.append(np.sort(score[ix][sets], axis=1).sum(axis=1))
        truth.append(score[ix][g.outcome.between(1, 3).to_numpy()].sum())
    matrix = np.full((len(rows), max(map(len, rows))), -np.inf)
    for i, row in enumerate(rows):
        matrix[i, :len(row)] = row
    truth = np.array(truth)
    opt = minimize_scalar(lambda t: float(np.mean(logsumexp(matrix / t, axis=1) - truth / t)),
                          bounds=cfg()["temperature_bounds"], method="bounded")
    assert opt.success
    return float(opt.x)


def train():
    check_inputs()
    f = load_frame()
    fingerprint = sha(OUT / "input_manifest.json")
    for venue in cfg()["venues"]:
        one = f[f.meet.eq(venue)].reset_index(drop=True)
        for year in cfg()["evaluation_years"]:
            train_mask = one.year.between(2017, year - 3)
            valid = one.year.eq(year - 2)
            cal = one.year.eq(year - 1)
            test = one.year.eq(year)
            for variant, cols in contracts().items():
                folder = OUT / "models" / f"{variant}_{venue}_{year}"
                pred_path = folder / "scores.parquet"
                if pred_path.exists():
                    meta = json.loads((folder / "metadata.json").read_text())
                    assert meta["input_fingerprint"] == fingerprint
                    print("Reuse completed", folder.name, flush=True)
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                if variant in ["ability22", "full103"]:
                    old, filename = source_model(variant, venue, year)
                    oldmeta = json.loads((old / "metadata.json").read_text())
                    assert oldmeta["features"] == cols
                    x, vocab = encode(one, cols, vocabulary=oldmeta["category_vocabulary"])
                    model_path = old / filename
                    model = lgb.Booster(model_file=str(model_path))
                    meta = {k: oldmeta[k] for k in ["trees", "train_end", "temperature"]}
                    meta["reused"] = True
                else:
                    x, vocab = encode(one, cols, mask=train_mask)
                    params = cfg()["training"].copy()
                    rounds = params.pop("max_rounds")
                    early = params.pop("early_stopping_rounds")
                    params["seed"] = cfg()["training_seed"]
                    labels = one.outcome.between(1, 3).astype(int)
                    def dataset(mask):
                        return lgb.Dataset(x.loc[mask], label=labels[mask],
                                           weight=1 / one.loc[mask, "field_size"], free_raw_data=False)
                    initial = lgb.train(params, dataset(train_mask), num_boost_round=rounds,
                        valid_sets=[dataset(valid)], callbacks=[lgb.early_stopping(early, verbose=False)])
                    model = lgb.train(params, dataset(train_mask | valid), num_boost_round=initial.best_iteration)
                    model_path = folder / "model.txt"
                    model.save_model(str(model_path))
                    meta = {"trees": int(initial.best_iteration), "reused": False,
                            "train_end": str(one.loc[train_mask | valid, "race_date"].max().date())}
                cs = model.predict(x.loc[cal], raw_score=True, num_threads=4)
                ts = model.predict(x.loc[test], raw_score=True, num_threads=4)
                temp = set_temperature(one.loc[cal].reset_index(drop=True), cs)
                if meta["reused"]:
                    assert abs(temp - meta["temperature"]) < 1e-6, (variant, temp, meta["temperature"])
                else:
                    meta["temperature"] = temp
                meta.update({"variant": variant, "venue": venue, "evaluation_year": year,
                    "validation_year": year - 2, "calibration_year": year - 1,
                    "training_min": "2017-01-01", "features": cols, "category_vocabulary": vocab,
                    "model_path": str(model_path.relative_to(ROOT)), "model_sha256": sha(model_path),
                    "input_fingerprint": fingerprint, "training_code_sha256": sha(HERE / "run.py"),
                    "rows": {"initial": int(train_mask.sum()), "validation": int(valid.sum()),
                             "calibration": int(cal.sum()), "evaluation": int(test.sum())}})
                scores = pd.concat([pd.DataFrame({"row_number": one.loc[cal, "row_number"], "score": cs, "phase": "calibration"}),
                                    pd.DataFrame({"row_number": one.loc[test, "row_number"], "score": ts, "phase": "evaluation"})], ignore_index=True)
                save(folder / "metadata.json", meta)
                scores.to_parquet(pred_path, index=False, compression="zstd")
                print("Ready", folder.name, "trees", meta["trees"], "temperature", meta["temperature"], flush=True)
                storage_check()
    save(OUT / "training_complete.json", {"new_final_models": len(list((OUT / "models").glob("*/model.txt"))),
         "reused_models": 12, "folds": len(list((OUT / "models").glob("*/scores.parquet"))),
         "source_rows": len(f), "evaluation_races": int(f[f.year.ge(2024)].race_key.nunique()),
         "training_code_sha256": sha(HERE / "run.py")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "train"])
    args = parser.parse_args()
    {"freeze": freeze, "train": train}[args.command]()
