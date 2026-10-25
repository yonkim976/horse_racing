"""Derive native F1_STYLE6 unordered Top3-set probabilities on the frozen cohort."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logsumexp


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
STYLE_OUT = STYLE / "outputs"
SOURCE_SCORES = STYLE_OUT / "F1_STYLE6_2026/evaluation_scores.parquet"
SOURCE_META = STYLE_OUT / "F1_STYLE6_2026/meta.json"
SOURCE_MODEL = STYLE_OUT / "F1_STYLE6_2026/top3.txt"
SOURCE_RUNNERS = STYLE_OUT / "report/runner_predictions.parquet"
SOURCE_TOP6 = STYLE_OUT / "report/canonical_six_combinations.csv"
COHORT = ROOT / "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv"
ORIGINAL_FORMULA = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"

TRIPLET_CSV = STUDY / "tla_set_probabilities.csv"
TRIPLET_PARQUET = STUDY / "tla_set_probabilities.parquet"
REPORT = STUDY / "REPORT.json"
MANIFEST = STUDY / "SOURCE_MANIFEST.json"
ATOL = 1e-12


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    require(path.resolve().parent == STUDY.resolve(), f"output escaped study folder: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    inputs = [SOURCE_SCORES, SOURCE_META, SOURCE_MODEL, SOURCE_RUNNERS, SOURCE_TOP6,
              COHORT, ORIGINAL_FORMULA]
    for path in inputs:
        require(path.is_file() and not path.is_symlink(), f"required regular source file missing: {path}")
        require(path.resolve().is_relative_to(ROOT), f"source outside workspace: {path}")
    for path in [TRIPLET_CSV, TRIPLET_PARQUET, REPORT, MANIFEST]:
        require(not path.exists() and not path.is_symlink(), f"refusing to overwrite output: {path}")

    meta = json.loads(SOURCE_META.read_text(encoding="utf-8"))
    require(meta.get("variant") == "F1_STYLE6" and meta.get("evaluation_year") == 2026,
            "saved score metadata is not the F1_STYLE6 2026 evaluation artifact")
    model_sha = sha256_file(SOURCE_MODEL)
    require(model_sha == meta.get("model_sha256"), "saved F1_STYLE6 model SHA differs from metadata")
    tau = float(meta["tau"])
    require(np.isfinite(tau) and tau > 0, "saved temperature is invalid")

    cohort = pd.read_csv(COHORT, dtype={"race_id": "string"})
    common = cohort.loc[cohort["reason"].eq("matched")].copy()
    common_ids = set(common["race_id"].astype(str))
    require(len(common) == 467 and len(common_ids) == 467, "frozen common cohort is not 467 unique races")
    require(common["race_date"].nunique() == 70, "frozen common cohort day count changed")

    runners = pd.read_parquet(SOURCE_RUNNERS)
    runners = runners.loc[
        runners["variant"].eq("F1_STYLE6") & runners["year"].eq(2026)
        & runners["race_id"].astype(str).isin(common_ids)
    ].copy()
    require(runners["race_id"].nunique() == 467, "saved F1_STYLE6 runner output misses a common race")
    require(not runners["api_record_id"].duplicated().any(), "saved runner IDs are not unique")

    saved_scores = pd.read_parquet(SOURCE_SCORES)
    require(not saved_scores["api_record_id"].duplicated().any(), "saved evaluation score IDs are not unique")
    score_merge = runners.merge(
        saved_scores, on="api_record_id", how="left", validate="one_to_one", suffixes=("_runner", "_source"),
        indicator=True,
    )
    require(score_merge["_merge"].eq("both").all(), "saved runner roster does not align to original scores")
    require(np.array_equal(score_merge["score_runner"].to_numpy(float),
                           score_merge["score_source"].to_numpy(float)),
            "runner score differs from original saved evaluation score")
    runners = score_merge.drop(columns=["_merge", "score_runner"]).rename(columns={"score_source": "score"})

    top6_saved = pd.read_csv(SOURCE_TOP6, dtype={"race_id": "string", "numbers": "string"})
    top6_saved = top6_saved.loc[
        top6_saved["variant"].eq("F1_STYLE6") & top6_saved["race_id"].astype(str).isin(common_ids)
    ].copy()
    require(len(top6_saved) == 467 * 6, "original native Top6 artifact does not cover all common races")

    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for race_id, group in runners.groupby("race_id", sort=True):
        one = group.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        n = len(one)
        require(n >= 3 and one["horse_number"].is_unique and one["horse_id"].is_unique,
                f"invalid triplet roster: {race_id}")
        require(one["horse_number"].is_monotonic_increasing, f"horse-number order is unstable: {race_id}")
        require(one["field_n"].astype(int).eq(n).all(), f"saved field size differs from roster: {race_id}")
        cohort_row = common.loc[common["race_id"].eq(str(race_id))]
        require(len(cohort_row) == 1 and int(cohort_row.iloc[0]["field_n"]) == n,
                f"common cohort field size differs from saved runners: {race_id}")

        number = one["horse_number"].to_numpy(dtype=int)
        horse_id = one["horse_id"].astype(str).to_numpy()
        score = one["score"].to_numpy(dtype=float)
        require(np.isfinite(score).all(), f"nonfinite saved score: {race_id}")
        triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=int)
        # This is the original F1/R1 energy: sort each triple's saved scores, then sum.
        energy = np.sort(score[triples], axis=1).sum(axis=1)
        log_probability = energy / tau - logsumexp(energy / tau)
        probability = np.exp(log_probability)
        require(np.isfinite(probability).all() and (probability >= 0).all(),
                f"invalid set probabilities: {race_id}")
        require(abs(float(probability.sum()) - 1.0) <= ATOL,
                f"all-triplet probability mass does not sum to one: {race_id}")

        marginal = np.zeros(n, dtype=float)
        for col in range(3):
            np.add.at(marginal, triples[:, col], probability)
        saved_marginal = one["p_top3"].to_numpy(dtype=float)
        marginal_error = float(np.max(np.abs(marginal - saved_marginal)))
        require(marginal_error <= ATOL, f"derived set marginal differs from saved p_top3: {race_id}")

        # Same stable order used by the native evaluator: itertools combinations are canonical.
        native_order = np.argsort(-energy, kind="stable")
        top6_rows = top6_saved.loc[top6_saved["race_id"].eq(str(race_id))].sort_values(
            "selection_rank", kind="mergesort")
        require(top6_rows["selection_rank"].astype(int).tolist() == list(range(1, 7)),
                f"original Top6 ranks are incomplete: {race_id}")
        for rank, (artifact_row, combo_index) in enumerate(
                zip(top6_rows.itertuples(index=False), native_order[:6]), start=1):
            combo = triples[combo_index]
            label = ",".join(str(int(number[ix])) for ix in combo)
            require(str(artifact_row.numbers) == label,
                    f"native Top6 horse set differs at rank {rank}: {race_id}")
            require(abs(float(artifact_row.probability) - float(probability[combo_index])) <= ATOL,
                    f"native Top6 probability differs at rank {rank}: {race_id}")
            expected_hit = int(bool(one.iloc[combo]["y"].astype(int).all()))
            require(int(artifact_row.hit) == expected_hit,
                    f"native Top6 outcome label differs at rank {rank}: {race_id}")

        energy_rank = np.empty(len(energy), dtype=int)
        energy_rank[native_order] = np.arange(1, len(energy) + 1)
        date = str(one["race_date"].iloc[0])
        distance = int(one["distance_m"].iloc[0])
        for ix, combo in enumerate(triples):
            rows.append({
                "race_id": str(race_id), "race_date": date, "distance_m": distance,
                "field_n": n, "horse_no_1": int(number[combo[0]]),
                "horse_no_2": int(number[combo[1]]), "horse_no_3": int(number[combo[2]]),
                "horse_id_1": str(horse_id[combo[0]]), "horse_id_2": str(horse_id[combo[1]]),
                "horse_id_3": str(horse_id[combo[2]]), "numbers": ",".join(
                    str(int(number[j])) for j in combo),
                "set_probability": float(probability[ix]), "native_energy_rank": int(energy_rank[ix]),
            })
        checks.append({
            "race_id": str(race_id), "race_date": date, "field_n": n,
            "triplet_n": int(len(triples)), "probability_sum": float(probability.sum()),
            "max_p_top3_marginal_abs_error": marginal_error,
            "native_top6_rows_reproduced": 6,
        })

    result = pd.DataFrame(rows)
    require(result["race_id"].nunique() == 467, "derived table race count changed")
    require(not result.duplicated(["race_id", "horse_no_1", "horse_no_2", "horse_no_3"]).any(),
            "duplicate exact Top3 set keys")
    require(len(result) == sum(int(len(group) * (len(group) - 1) * (len(group) - 2) / 6)
                               for _, group in runners.groupby("race_id")),
            "derived row count differs from sum of C(N,3)")

    # Write once, into this research folder only.
    result.to_csv(TRIPLET_CSV, index=False, float_format="%.17g")
    with TRIPLET_PARQUET.open("xb") as stream:
        result.to_parquet(stream, index=False)

    support = {
        "native_supported": [
            {"pool": "TLA", "event": "unordered exact Top3 set", "status": "supported",
             "probability_source": "F1_STYLE6 native all-C(N,3) set distribution"},
        ],
        "native_unsupported": [
            {"pool": "WIN", "event": "winner", "status": "unsupported",
             "reason": "the runner Top3 scorer and unordered Top3 set distribution contain no within-set order"},
            {"pool": "QNL", "event": "unordered exact Top2 set", "status": "unsupported",
             "reason": "Top3-set membership does not identify which two runners occupied first and second"},
            {"pool": "EXA", "event": "ordered first and second", "status": "unsupported",
             "reason": "no native first/second ordering distribution is saved"},
            {"pool": "TRI", "event": "ordered exact Top3", "status": "unsupported",
             "reason": "no native ordered Top3 distribution is saved"},
        ],
        "not_used_as_probability": [
            "runner score rank is not a calibrated Win probability",
            "p_top3 is not a WIN, QNL, EXA, or TRI probability",
            "pair-ID calibrated probabilities are standalone unordered pair events, not an ordered joint distribution",
        ],
    }
    report = {
        "status": "PASS",
        "scope": "saved F1_STYLE6 2026 scores on common operating/research cohort only",
        "cohort": {"races": 467, "race_days": 70, "date_min": str(common["race_date"].min()),
                   "date_max": str(common["race_date"].max()),
                   "field_size_min": int(result.groupby("race_id")["field_n"].first().min()),
                   "field_size_max": int(result.groupby("race_id")["field_n"].first().max()),
                   "races_with_complete_triplet_support": 467,
                   "tla_set_rows": int(len(result))},
        "model": {"variant": "F1_STYLE6", "evaluation_year": 2026,
                  "tau": tau, "model_sha256": model_sha,
                  "saved_scores": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet"},
        "native_formula": {
            "energy": "E({i,j,k}) = sum(sort(score_i, score_j, score_k))",
            "set_probability": "exp(E/tau) / sum over every unordered 3-runner set exp(E/tau))",
            "runner_top3_marginal": "sum of all exact set probabilities containing the runner",
            "implementation_reference": "jeju/research/20261008_horse_profile_baseline_v1/run.py:parts, temperature, evaluate",
        },
        "validation": {
            "saved_runner_scores_exactly_match_original_score_file": True,
            "per_race_all_set_probability_sum_abs_error_max": float(
                max(abs(check["probability_sum"] - 1.0) for check in checks)),
            "saved_p_top3_marginal_max_abs_error": float(
                max(check["max_p_top3_marginal_abs_error"] for check in checks)),
            "original_native_top6_set_keys_probabilities_and_hit_labels_reproduced": True,
            "original_native_top6_rows_checked": int(467 * 6),
            "normalization_tolerance": ATOL,
            "marginal_and_top6_probability_tolerance": ATOL,
        },
        "pool_support": support,
        "promotion_or_refit": False,
        "network_or_database_access": False,
    }
    write_json_once(REPORT, report)

    output_paths = [TRIPLET_CSV, TRIPLET_PARQUET, REPORT]
    manifest = {
        "status": "PASS",
        "created_by": "derive_tla.py",
        "inputs": {
            str(path.relative_to(ROOT)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in inputs
        },
        "outputs": {
            str(path.relative_to(ROOT)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in output_paths
        },
        "code_sha256": sha256_file(Path(__file__).resolve()),
        "row_count": int(len(result)),
        "race_count": int(result["race_id"].nunique()),
        "probability_column": "set_probability",
        "event_semantics": "unordered exact Top3 set (TLA)",
    }
    write_json_once(MANIFEST, manifest)
    print(json.dumps({"status": "PASS", "races": 467, "triplet_rows": len(result),
                      "tla_supported": True, "win_qnl_exa_tri_supported": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
