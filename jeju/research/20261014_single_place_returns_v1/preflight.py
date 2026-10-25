"""Label-free replay of the saved F1_STYLE6 Top3 marginals and single-axis rule."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logsumexp


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[2]
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
REPORT_RUNNERS = STYLE_OUT / "report/runner_predictions.parquet"
BASE_EVALUATOR = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"
OUTPUT_DIR = STUDY_DIR / "outputs"
ANCHOR_OUTPUT = OUTPUT_DIR / "selected_anchors_label_free.csv"
RECEIPT_OUTPUT = OUTPUT_DIR / "probability_preflight_receipt.json"

EXPECTED_SHA256 = {
    "report/runner_predictions.parquet":
        "706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56",
    "F1_STYLE6_2024/meta.json":
        "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726",
    "F1_STYLE6_2024/evaluation_scores.parquet":
        "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60",
    "F1_STYLE6_2025/meta.json":
        "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8",
    "F1_STYLE6_2025/evaluation_scores.parquet":
        "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    "F1_STYLE6_2026/meta.json":
        "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d",
    "F1_STYLE6_2026/evaluation_scores.parquet":
        "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
}
EXPECTED_EVALUATION_COUNTS = {
    2024: (6329, 637),
    2025: (6410, 654),
    2026: (4673, 488),
}
RUNNER_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id",
    "horse_number", "field_n", "variant", "score", "p_top3",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_output_path(path: Path) -> None:
    resolved = path.resolve()
    base = STUDY_DIR.resolve()
    if resolved != base and base not in resolved.parents:
        raise RuntimeError(f"output escaped the approved study folder: {path}")


def save_new_json(path: Path, value: dict[str, Any]) -> None:
    assert_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def verify_source_hashes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in EXPECTED_SHA256.items():
        path = STYLE_OUT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"locked source hash changed: {relative}")
        observed[str(path.relative_to(ROOT))] = actual
    evaluator_sha = sha256(BASE_EVALUATOR)
    expected_evaluator_sha = "40fcb2875c06beedd56044f8fe94cdedf6fc0e2c2db38a87a326234999255e68"
    if evaluator_sha != expected_evaluator_sha:
        raise RuntimeError("the frozen additive Top3 evaluator source changed")
    observed[str(BASE_EVALUATOR.relative_to(ROOT))] = evaluator_sha
    return observed


def replay_top3_marginal(scores: np.ndarray, tau: float) -> np.ndarray:
    """Match the frozen evaluate() definition: q @ incidence over all triples."""
    n = len(scores)
    if n < 3 or not np.all(np.isfinite(scores)):
        raise RuntimeError("race scores must be finite and contain at least three runners")
    if not math.isfinite(tau) or tau <= 0:
        raise RuntimeError("saved temperature must be positive and finite")

    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    energy = np.sort(scores[triples], axis=1).sum(axis=1)
    log_q = energy / tau - logsumexp(energy / tau)
    q = np.exp(log_q)
    incidence = np.zeros((len(triples), n), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    probabilities = q @ incidence
    if not np.all(np.isfinite(probabilities)):
        raise RuntimeError("replayed Top3 marginals are non-finite")
    if not np.isclose(float(q.sum()), 1.0, rtol=0.0, atol=1e-12):
        raise RuntimeError("exact-Top3 subset probabilities do not sum to one")
    if not np.isclose(float(probabilities.sum()), 3.0, rtol=0.0, atol=1e-12):
        raise RuntimeError("Top3 runner marginals do not sum to three")
    return probabilities


def load_label_free_runners() -> pd.DataFrame:
    # The selected parquet columns deliberately omit y, finish_position and all
    # other outcome fields. Payout files and databases are not opened here.
    runners = pd.read_parquet(REPORT_RUNNERS, columns=RUNNER_COLUMNS)
    runners = runners.loc[runners.variant.eq("F1_STYLE6")].copy()
    if len(runners) != 17412 or runners.api_record_id.nunique() != len(runners):
        raise RuntimeError("F1_STYLE6 saved runner rows or key uniqueness changed")
    if runners.race_id.isna().any() or runners.horse_id.isna().any():
        raise RuntimeError("runner identifiers must be present")
    if runners.race_date.isna().any() or runners.year.isna().any():
        raise RuntimeError("evaluation date/year must be present")
    if not np.all(np.isfinite(runners.score.to_numpy(dtype=float))):
        raise RuntimeError("saved runner scores must be finite")
    saved_p = runners.p_top3.to_numpy(dtype=float)
    if not np.all(np.isfinite(saved_p)) or np.any((saved_p < 0.0) | (saved_p > 1.0)):
        raise RuntimeError("saved Top3 marginals must be finite probabilities")
    if not runners.horse_number.gt(0).all():
        raise RuntimeError("horse numbers must be positive")
    return runners.sort_values(
        ["race_date", "race_id", "horse_number"], kind="stable"
    ).reset_index(drop=True)


def join_evaluation_scores(runners: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    pieces: list[pd.DataFrame] = []
    source_meta: dict[str, Any] = {}
    for year, (expected_rows, expected_races) in EXPECTED_EVALUATION_COUNTS.items():
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("variant") != "F1_STYLE6" or int(meta.get("evaluation_year", -1)) != year:
            raise RuntimeError(f"saved evaluation metadata mismatch for {year}")
        tau = float(meta["tau"])
        if not math.isfinite(tau) or tau <= 0:
            raise RuntimeError(f"invalid saved tau for {year}")
        if pd.Timestamp(meta["calibration_max"]) >= pd.Timestamp(meta["evaluation_min"]):
            raise RuntimeError(f"calibration window does not precede evaluation in {year}")

        scores = pd.read_parquet(
            folder / "evaluation_scores.parquet",
            columns=["api_record_id", "score"],
        )
        if scores.api_record_id.isna().any() or scores.api_record_id.duplicated().any():
            raise RuntimeError(f"duplicate or missing evaluation key in {year}")
        year_runners = runners.loc[runners.year.eq(year)].copy()
        if len(year_runners) != expected_rows or year_runners.race_id.nunique() != expected_races:
            raise RuntimeError(f"saved runner coverage mismatch for {year}")
        joined = year_runners.merge(
            scores.rename(columns={"score": "evaluation_score"}),
            on="api_record_id", how="left", validate="one_to_one", sort=False,
            indicator=True,
        )
        if not joined._merge.eq("both").all() or joined.evaluation_score.isna().any():
            raise RuntimeError(f"evaluation-score key coverage mismatch for {year}")
        if not np.array_equal(
            joined.score.to_numpy(dtype=np.float64),
            joined.evaluation_score.to_numpy(dtype=np.float64),
        ):
            raise RuntimeError(f"saved runner score does not match raw score parquet for {year}")
        joined = joined.drop(columns=["evaluation_score", "_merge"])
        pieces.append(joined)
        source_meta[str(year)] = {
            "tau": tau,
            "calibration_max": str(meta["calibration_max"]),
            "evaluation_min": str(meta["evaluation_min"]),
            "evaluation_max": str(meta["evaluation_max"]),
            "runner_rows": expected_rows,
            "races": expected_races,
        }

    combined = pd.concat(pieces, ignore_index=True)
    if len(combined) != 17412 or combined.api_record_id.nunique() != len(combined):
        raise RuntimeError("joined raw scores do not cover the fixed evaluation cohort")
    return combined, source_meta


def build_label_free_anchors(
    runners: pd.DataFrame, source_meta: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    max_abs_probability_error = 0.0
    race_day_counts: dict[str, int] = {}
    field_sizes: dict[str, int] = {}
    tied_score_races = 0

    for race_id, group in runners.groupby("race_id", sort=True, observed=True):
        group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
        sizes = group.field_n.drop_duplicates().tolist()
        years = group.year.drop_duplicates().tolist()
        dates = group.race_date.drop_duplicates().tolist()
        if len(sizes) != 1 or len(years) != 1 or len(dates) != 1:
            raise RuntimeError(f"race metadata is inconsistent: {race_id}")
        n = int(sizes[0])
        if len(group) != n or group.horse_id.nunique() != n or group.horse_number.nunique() != n:
            raise RuntimeError(f"race roster does not match its field size: {race_id}")
        if n < 6:
            raise RuntimeError(f"field size outside the locked F1 cohort: {race_id}")

        year = int(years[0])
        tau = float(source_meta[str(year)]["tau"])
        scores = group.score.to_numpy(dtype=np.float64)
        replayed_p = replay_top3_marginal(scores, tau)
        saved_p = group.p_top3.to_numpy(dtype=np.float64)
        if not np.allclose(replayed_p, saved_p, rtol=0.0, atol=1e-12):
            raise RuntimeError(f"saved p_top3 parity failed: {race_id}")
        error = float(np.max(np.abs(replayed_p - saved_p)))
        max_abs_probability_error = max(max_abs_probability_error, error)

        top_score = float(np.max(scores))
        candidate_positions = np.flatnonzero(scores == top_score)
        if len(candidate_positions) > 1:
            tied_score_races += 1
        # Runners are ordered by ascending horse number, so exact score ties
        # deterministically select the lowest number with no probability tolerance.
        selected_index = int(candidate_positions[0])
        selected = group.iloc[selected_index]
        place_probability = float(selected.p_top3) if n >= 8 else None
        anchors.append({
            "race_id": str(race_id),
            "race_date": str(pd.Timestamp(dates[0]).date()),
            "year": year,
            "horse_id": str(selected.horse_id),
            "horse_number": int(selected.horse_number),
            "api_record_id": int(selected.api_record_id),
            "field_n": n,
            "score": float(selected.score),
            "p_top3": float(selected.p_top3),
            "p_place": place_probability,
            "place_finish_cutoff": 3 if n >= 8 else 2,
        })
        race_day_counts[str(dates[0])] = race_day_counts.get(str(dates[0]), 0) + 1
        field_sizes[str(n)] = field_sizes.get(str(n), 0) + 1

    frame = pd.DataFrame(anchors).sort_values(
        ["race_date", "race_id"], kind="stable"
    ).reset_index(drop=True)
    if len(frame) != 1779 or frame.race_id.nunique() != 1779:
        raise RuntimeError("single-axis selection did not produce one row per race")
    top3_supported = int(frame.p_place.notna().sum())
    top2_unavailable = int(frame.p_place.isna().sum())
    if (top3_supported, top2_unavailable, frame.race_date.nunique()) != (1743, 36, 269):
        raise RuntimeError("Top2 support boundary or race-day inventory changed")

    year_counts = frame.groupby("year", sort=True).size().to_dict()
    small_fields_by_year = frame.loc[frame.field_n.le(7)].groupby("year", sort=True).size().to_dict()
    if year_counts != {2024: 637, 2025: 654, 2026: 488}:
        raise RuntimeError("evaluation-year race counts changed")
    if small_fields_by_year != {2025: 4, 2026: 32}:
        raise RuntimeError("Top2-unavailable race allocation changed")

    counts = {
        "races": int(len(frame)),
        "runner_rows": int(len(runners)),
        "race_days": int(frame.race_date.nunique()),
        "native_probability_supported_races": top3_supported,
        "Top2_probability_unavailable_races": top2_unavailable,
        "evaluation_races_by_year": {str(key): int(value) for key, value in year_counts.items()},
        "Top2_probability_unavailable_by_year": {
            str(key): int(value) for key, value in small_fields_by_year.items()
        },
        "field_size_races": field_sizes,
        "races_by_date": len(race_day_counts),
        "exact_score_tie_races": tied_score_races,
        "saved_p_top3_max_abs_replay_error": max_abs_probability_error,
    }
    return frame, counts


def main() -> None:
    if ANCHOR_OUTPUT.exists() or RECEIPT_OUTPUT.exists():
        raise FileExistsError("label-free preflight outputs already exist; refusing overwrite")
    source_hashes = verify_source_hashes()
    runners = load_label_free_runners()
    joined, source_meta = join_evaluation_scores(runners)
    anchors, counts = build_label_free_anchors(joined, source_meta)

    assert_output_path(ANCHOR_OUTPUT)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    anchors.to_csv(ANCHOR_OUTPUT, index=False, mode="x")
    receipt = {
        "status": "PASS",
        "target_labels_read": False,
        "payout_inputs_read": False,
        "fit_or_recalibration_runs": 0,
        "performance_metrics_computed": False,
        "selector": "maximum saved F1_STYLE6 raw score; exact score ties choose the lowest horse number",
        "probability_semantics": "saved additive unordered exact-Top3 subset marginal; p_place is null when field_n <= 7",
        "probability_replay": "all C(N,3), q(T)=softmax(sum(score_h)/saved_tau), p_top3=q@incidence",
        "probability_atol": 1e-12,
        "sources": source_hashes,
        "saved_model_metadata": source_meta,
        "counts": counts,
        "anchor_output": {
            "path": str(ANCHOR_OUTPUT.relative_to(ROOT)),
            "sha256": sha256(ANCHOR_OUTPUT),
            "rows": int(len(anchors)),
        },
        "code_sha256": sha256(Path(__file__)),
    }
    save_new_json(RECEIPT_OUTPUT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
