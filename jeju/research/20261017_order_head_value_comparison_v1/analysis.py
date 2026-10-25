"""Fixed-policy postrace comparison for the conditional order head.

This script stops before reading probability/quote rows unless the separately
frozen main-study prediction receipt and root value-evaluation approval pin the
same ordered-joint artifact and this study's frozen plan.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
CONDITIONAL = ROOT / "jeju/research/20261017_conditional_order_head_v1"
PREVIOUS_OTHER = ROOT / "jeju/research/20261015_other_pools_postrace_value_v1"
PREVIOUS_COHORT = ROOT / "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv"
OFFICIAL = ROOT / "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv"
TLA_NATIVE = ROOT / "jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
BOOTSTRAP_DATES = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
PREFIT_LOCK = STUDY / "SOURCE_MANIFEST_PREFIT.json"
FIT_APPROVAL = CONDITIONAL / "outputs/ROOT_FIT_APPROVAL.json"
FIT_RECEIPT = CONDITIONAL / "outputs/FIT_RECEIPT.json"
FIT_ARTIFACTS = CONDITIONAL / "outputs/FIT_ARTIFACTS.json"
PREDICTION_RECEIPT = CONDITIONAL / "outputs/PREDICTION_RECEIPT.json"
ROOT_VALUE_APPROVAL = CONDITIONAL / "outputs/ROOT_VALUE_EVAL_APPROVAL.json"
ORDERED_JOINT = CONDITIONAL / "outputs/evaluation_ordered_joint.parquet"

PLAN_SHA256 = "43917a7440c80717214b152419be77afcc9c4303e290e7d8e0802d2c2de203a4"
STAKE = 1000.0
ORDERED_MODELS = ("HY_R_FORM", "F1_STYLE6_COND_ORDER_V1", "F1_STYLE6_FIXED_SCORE_PL_CONTROL")
TLA_MODELS = (
    "F1_STYLE6_NATIVE_TLA_Q",
    "F1_STYLE6_COND_ORDER_V1_TLA_Q",
    "F1_STYLE6_FIXED_SCORE_PL_CONTROL_TLA_Q",
)
ALL_POOLS = ("WIN", "QNL", "EXA", "TLA", "TRI")
ORDERED_POOLS = ("WIN", "QNL", "EXA", "TRI")
POOL_LABELS = {"WIN": "단승", "QNL": "복승", "EXA": "쌍승", "TLA": "삼복승", "TRI": "삼쌍승"}
POLICIES = [
    ("p_rank_1", "p rank 1"),
    ("p_rank_2", "p rank 2"),
    ("p_rank_3", "p rank 3"),
    ("p_rank_4", "p rank 4"),
    ("p_rank_5", "p rank 5"),
    ("p_rank_1_ev_positive", "p rank 1 EV > 0"),
    ("all_max_ev_positive", "all candidates max EV > 0"),
    ("top3_max_ev_positive", "p ranks 1-3 max EV > 0"),
    ("top5_max_ev_positive", "p ranks 1-5 max EV > 0"),
    ("top3_max_ev_gt_020", "p ranks 1-3 max EV > 0.20"),
]
EXPECTED_INPUT_HASHES = {
    "config/prediction_model_registry.json": "944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b",
    "jeju/models/current/HY_R_FORM.pkl": "f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706",
    "src/horse_racing/analysis/jeju_hybrid_evaluation.py": "61409385b5748d2df6a34fcd4eca5bd453669c0421c024f34e55aca216050aa7",
    "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv": "4f87d05e0f7e2db48f1029dbf1fc78c393ba3804eb20ccb8d28cf6e20e73983f",
    "jeju/research/20261015_other_pools_postrace_value_v1/candidate_rows.csv": "74f35fbf3fe18fb29a6942b89a8d06c89e5aa7a3f6ba69c5c8471ebba7068682",
    "jeju/research/20261015_other_pools_postrace_value_v1/candidate_quotes.csv": "96c6a2536520ca3ea33f6b255b04501972aef4f837c3ac694d1563a8148bce50",
    "jeju/research/20261015_other_pools_postrace_value_v1/SOURCE_PREFLIGHT.json": "c6b6b20cdb6bb4ae6f3cfac63402dc53a5b7262b53fa356618bffd83df89554f",
    "jeju/research/20261015_other_pools_postrace_value_v1/source_exclusions.csv": "cd48b73779a95f220db1408210f15d2dfce26060a9590bcd040ab7418bec0aee",
    "jeju/research/20261015_other_pools_postrace_value_v1/SOURCE_MANIFEST.json": "9531cc71a5abf429bc3a24fbe63b2eba4b08d91bc479be95267f22aafd153fe3",
    "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv": "4ae6133d9d537f9ca6b351ed909a945b88a428cb4babcdf15659e266a68f2df6",
    "jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet": "7c7bafcb315a9f9595e06aa1ee12ca0affbcf3abcc13426e90e079261d29b382",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json": "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet": "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6",
    "jeju/research/20261017_conditional_order_head_v1/PLAN.md": "b5aeebeaadfd73e73e2d8bf97eb79a6bcaa82e0e5492f78cf0fe1aa52da02a80",
    "jeju/research/20261017_conditional_order_head_v1/INPUT_CONTRACT.md": "4baf862c8a9c9a3f8643e76231f993174653fc48a29167c3b282558f0ca7276c",
    "jeju/research/20261017_conditional_order_head_v1/outputs/PREFIT_SOURCE_LOCK.json": "7285382f2731c59db3684f76dfa72682c0153663ece55426e3a1960c18c72d94",
    "jeju/research/20261017_conditional_order_head_v1/outputs/SOURCE_PREFLIGHT.json": "352980cf94b6d59825690418129d6bc0cc566aa4fc6841904a1fa4a9dd9d69fb",
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [json_safe(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def save_json(path: Path, value: Any) -> None:
    require(path.parent.resolve() == STUDY.resolve(), f"output escaped study directory: {path}")
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(frame: pd.DataFrame, filename: str) -> Path:
    path = (STUDY / filename).resolve()
    require(path.parent == STUDY.resolve(), f"output escaped study directory: {filename}")
    frame.to_csv(path, index=False, na_rep="")
    return path


def parse_event_key(value: Any) -> tuple[int, ...]:
    parts = str(value).split("-")
    require(all(part.isdigit() for part in parts), f"non-numeric event key: {value}")
    return tuple(int(part) for part in parts)


def key_text(values: tuple[int, ...]) -> str:
    return "-".join(str(int(value)) for value in values)


def key_tuple(row: pd.Series | Any, pool: str) -> tuple[int, ...]:
    size = {"WIN": 1, "QNL": 2, "EXA": 2, "TLA": 3, "TRI": 3}[pool]
    nums = tuple(int(getattr(row, f"horse_no_{index}")) for index in range(1, size + 1))
    if pool in {"QNL", "TLA"}:
        return tuple(sorted(nums))
    return nums


def output_tuple(values: tuple[int, ...]) -> tuple[Any, Any, Any]:
    padded = values + (None,) * (3 - len(values))
    return padded[0], padded[1], padded[2]


def verify_approvals_and_joint_hash() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Check all independent gates before loading any quote or probability rows."""
    require(sha256_file(STUDY / "PLAN.md") == PLAN_SHA256, "value-comparison PLAN hash changed")
    fit = safe_json(FIT_APPROVAL)
    require(fit.get("status") == "APPROVED", "main-study root fit approval is absent or not approved")
    require(fit.get("h1_fit_count") == 3 and fit.get("h2_calibration_count") == 3,
            "main-study root fit authorization scope changed")
    require(fit.get("production_changed") is False and fit.get("fitting_requires_no_odds") is True,
            "main-study fit authorization boundary changed")
    require(fit.get("plan_sha256") == "b5aeebeaadfd73e73e2d8bf97eb79a6bcaa82e0e5492f78cf0fe1aa52da02a80",
            "main-study root fit approval does not pin the frozen conditional-order plan")
    require(fit.get("prefit_source_lock_sha256") == sha256_file(CONDITIONAL / "outputs/PREFIT_SOURCE_LOCK.json")
            and fit.get("source_prefight_sha256") == sha256_file(CONDITIONAL / "outputs/SOURCE_PREFLIGHT.json"),
            "main-study root fit approval does not pin the frozen prefit sources")

    receipt = safe_json(PREDICTION_RECEIPT)
    require(receipt.get("status") == "PASS_FROZEN_BEFORE_EVALUATION_METRICS",
            "main ordered-joint prediction is not frozen before evaluation metrics")
    require(receipt.get("artifact_path") == "outputs/evaluation_ordered_joint.parquet",
            "prediction receipt points to an unexpected artifact")
    require(receipt.get("model_label") == "F1_STYLE6_COND_ORDER_V1",
            "prediction receipt model label changed")
    require((receipt.get("fit_count", receipt.get("h1_fit_count")) == 3)
            and (receipt.get("calibration_count", receipt.get("h2_calibration_count")) == 3),
            "prediction receipt does not certify three frozen H1/H2 fits")
    require(receipt.get("evaluation_metrics_computed") is False,
            "prediction receipt indicates outcomes were inspected before this comparison")
    require(receipt.get("root_fit_approval_sha256") == sha256_file(FIT_APPROVAL)
            and receipt.get("prefit_source_lock_sha256") == sha256_file(CONDITIONAL / "outputs/PREFIT_SOURCE_LOCK.json"),
            "frozen prediction receipt does not pin its root-approved fit and source lock")
    fit_receipt_sha = receipt.get("fit_receipt_sha256")
    fit_artifacts_sha = receipt.get("fit_artifacts_sha256")
    actual_fit_receipt_sha = sha256_file(FIT_RECEIPT)
    actual_fit_artifacts_sha = sha256_file(FIT_ARTIFACTS)
    frozen_fit_receipt = safe_json(FIT_RECEIPT)
    require(isinstance(fit_receipt_sha, str) and len(fit_receipt_sha) == 64
            and fit_receipt_sha == actual_fit_receipt_sha,
            "frozen prediction receipt does not pin the actual FIT_RECEIPT.json bytes")
    require(isinstance(fit_artifacts_sha, str) and len(fit_artifacts_sha) == 64
            and fit_artifacts_sha == actual_fit_artifacts_sha
            and frozen_fit_receipt.get("fit_artifacts_sha256") == actual_fit_artifacts_sha
            and frozen_fit_receipt.get("fit_artifact_path") == "outputs/FIT_ARTIFACTS.json"
            and frozen_fit_receipt.get("status") == "PASS_FIT_ARTIFACTS_FROZEN_BEFORE_EVALUATION_METRICS"
            and frozen_fit_receipt.get("h1_fit_count") == 3
            and frozen_fit_receipt.get("h2_calibration_count") == 3
            and frozen_fit_receipt.get("evaluation_predictions_generated") is False
            and frozen_fit_receipt.get("evaluation_metrics_computed") is False
            and frozen_fit_receipt.get("odds_or_market_sources_read") is False
            and frozen_fit_receipt.get("database_or_network_access") is False,
            "frozen prediction receipt does not pin the actual immutable FIT_ARTIFACTS.json file")
    joint_sha = sha256_file(ORDERED_JOINT)
    require(receipt.get("artifact_sha256") == joint_sha
            and receipt.get("ordered_joint_sha256") == joint_sha,
            "ordered-joint bytes do not match the frozen prediction receipt")

    approval = safe_json(ROOT_VALUE_APPROVAL)
    require(approval.get("status") == "APPROVED", "root postrace-value approval is absent or not approved")
    require(approval.get("comparison_plan_sha256") == PLAN_SHA256,
            "root value approval does not pin this comparison plan")
    require(approval.get("ordered_joint_sha256") == joint_sha,
            "root value approval does not pin these ordered-joint predictions")
    return fit, receipt, approval, joint_sha


def verify_prefit_sources() -> tuple[dict[str, Any], dict[str, str]]:
    lock = safe_json(PREFIT_LOCK)
    require(lock.get("status") == "FROZEN_PRE_SELECTION", "prefit source manifest is not frozen")
    require(lock.get("frozen_plan_sha256") == PLAN_SHA256, "prefit source manifest plan hash changed")
    require(lock.get("evaluator_code_sha256") == sha256_file(STUDY / "analysis.py"),
            "evaluator code hash differs from prefit source manifest")
    sealed_registry = lock.get("sealed_preexisting_references", {}).get("registry_resolution", {})
    require(sealed_registry.get("active_profile") == "jeju-hy-r-form-20260919-v1"
            and sealed_registry.get("champion_id") == "HY_R_FORM"
            and sealed_registry.get("registry_sha256") == EXPECTED_INPUT_HASHES["config/prediction_model_registry.json"]
            and sealed_registry.get("hy_model_sha256") == EXPECTED_INPUT_HASHES["jeju/models/current/HY_R_FORM.pkl"]
            and sealed_registry.get("hy_distribution_source_sha256") == EXPECTED_INPUT_HASHES[
                "src/horse_racing/analysis/jeju_hybrid_evaluation.py"],
            "current HY registry identity differs from prior sealed metadata")
    actual: dict[str, str] = {}
    for relative, expected in EXPECTED_INPUT_HASHES.items():
        path = ROOT / relative
        digest = sha256_file(path)
        require(digest == expected, f"pinned input hash changed: {relative}")
        actual[relative] = digest
    for section in ("pinned_inputs",):
        # The detailed JSON lock must agree with the independent, code-pinned hash map.
        for entry in lock.get(section, {}).values():
            if isinstance(entry, dict) and entry.get("path") in {
                "config/prediction_model_registry.json",
                "jeju/models/current/HY_R_FORM.pkl",
                "src/horse_racing/analysis/jeju_hybrid_evaluation.py",
                "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv",
                "jeju/research/20261015_other_pools_postrace_value_v1/candidate_rows.csv",
                "jeju/research/20261015_other_pools_postrace_value_v1/candidate_quotes.csv",
                "jeju/research/20261015_other_pools_postrace_value_v1/SOURCE_PREFLIGHT.json",
                "jeju/research/20261015_other_pools_postrace_value_v1/source_exclusions.csv",
                "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv",
                "jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet",
                "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy",
                "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json",
                "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet",
            }:
                require(entry.get("sha256") == actual[entry["path"]],
                        f"prefit lock disagrees with pinned input map: {entry['path']}")
    return lock, actual


def freeze_source_manifest(fit: dict[str, Any], prediction: dict[str, Any], approval: dict[str, Any],
                           joint_sha: str, input_hashes: dict[str, str]) -> dict[str, Any]:
    manifest = {
        "status": "PASS_FROZEN_BEFORE_QUOTE_SELECTION",
        "study": "20261017_order_head_value_comparison_v1",
        "plan_sha256": PLAN_SHA256,
        "analysis_code_sha256": sha256_file(STUDY / "analysis.py"),
        "prefit_manifest_sha256": sha256_file(PREFIT_LOCK),
        "ordered_joint_prediction_sha256": joint_sha,
        "fit_approval_sha256": sha256_file(FIT_APPROVAL),
        "prediction_receipt_sha256": sha256_file(PREDICTION_RECEIPT),
        "root_value_approval_sha256": sha256_file(ROOT_VALUE_APPROVAL),
        "fit_authorization": {
            "status": fit.get("status"),
            "h1_fit_count": fit.get("h1_fit_count"),
            "h2_calibration_count": fit.get("h2_calibration_count"),
            "production_changed": fit.get("production_changed"),
        },
        "frozen_prediction_receipt": prediction,
        "root_value_approval": approval,
        "input_sha256": input_hashes,
        "read_only": {"database": False, "network": False, "registry_write": False,
                       "training_or_calibration": False, "external_study_writes": False},
    }
    save_json(STUDY / "SOURCE_MANIFEST.json", manifest)
    return manifest


def expected_event_count(pool: str, n: int) -> int:
    return {
        "WIN": n,
        "QNL": n * (n - 1) // 2,
        "EXA": n * (n - 1),
        "TLA": n * (n - 1) * (n - 2) // 6,
        "TRI": n * (n - 1) * (n - 2),
    }[pool]


def expected_keys(pool: str, roster: tuple[int, ...]) -> set[tuple[int, ...]]:
    if pool == "WIN":
        return {(horse,) for horse in roster}
    if pool == "QNL":
        return set(itertools.combinations(roster, 2))
    if pool == "EXA":
        return set(itertools.permutations(roster, 2))
    if pool == "TLA":
        return set(itertools.combinations(roster, 3))
    if pool == "TRI":
        return set(itertools.permutations(roster, 3))
    raise RuntimeError(f"unknown pool {pool}")


def canonical_event_frame(records: list[dict[str, Any]], model: str, pool: str) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return pd.DataFrame(columns=["race_id", "race_date", "pool", "model", "event_key",
                                     "horse_no_1", "horse_no_2", "horse_no_3", "field_n", "p"])
    frame["pool"] = pool
    frame["model"] = model
    frame["event_key"] = frame.event_tuple.map(key_text)
    frame[["horse_no_1", "horse_no_2", "horse_no_3"]] = pd.DataFrame(
        frame.event_tuple.map(output_tuple).tolist(), index=frame.index
    )
    return frame.drop(columns="event_tuple")


def aggregate_joint(joint: pd.DataFrame, cohort: pd.DataFrame, roster_map: dict[str, tuple[int, ...]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    joint = joint.copy()
    joint["race_id"] = joint.race_id.astype(str)
    joint["race_date"] = pd.to_datetime(joint.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    for col in ("horse_no_1", "horse_no_2", "horse_no_3", "field_n"):
        joint[col] = pd.to_numeric(joint[col], errors="raise").astype(int)
    for col in ("q_top3_set", "p_ordered_joint", "control_p_ordered_joint"):
        joint[col] = pd.to_numeric(joint[col], errors="raise")
        require(np.isfinite(joint[col].to_numpy(float)).all(), f"non-finite joint probability: {col}")
        require(((joint[col] >= -1e-15) & (joint[col] <= 1 + 1e-15)).all(), f"probability outside [0,1]: {col}")
    require(joint.race_id.isin(set(cohort.race_id.astype(str))).all(), "joint table has unexpected common-cohort race")
    require(joint.race_id.nunique() == len(cohort) == 467, "joint table does not cover the exact common cohort")
    require(not joint.duplicated(["race_id", "horse_no_1", "horse_no_2", "horse_no_3"]).any(),
            "ordered joint contains duplicate triple keys")
    require((joint["horse_no_1"] != joint["horse_no_2"]).all()
            and (joint["horse_no_1"] != joint["horse_no_3"]).all()
            and (joint["horse_no_2"] != joint["horse_no_3"]).all(), "ordered triple repeats a horse")

    expected_cols = ["race_id", "race_date", "distance_m", "field_n", "horse_no_1", "horse_no_2", "horse_no_3",
                     "q_top3_set", "p_ordered_joint", "control_p_ordered_joint"]
    require(set(expected_cols).issubset(joint.columns), "ordered joint schema missing a required field")
    cohort_dates = cohort.set_index("race_id").race_date.astype(str).to_dict()
    require(all(cohort_dates[rid] == date for rid, date in zip(joint.race_id, joint.race_date)),
            "ordered joint dates differ from fixed cohort")
    cohort_field = cohort.set_index("race_id").field_n.astype(int).to_dict()

    mass_rows: list[dict[str, Any]] = []
    for race_id, rows in joint.groupby("race_id", sort=True):
        roster = roster_map[race_id]
        require(rows.field_n.nunique() == 1 and int(rows.field_n.iloc[0]) == len(roster) == cohort_field[race_id],
                f"ordered-joint field size differs from fixed runner roster: {race_id}")
        actual_roster = tuple(sorted(set(rows.horse_no_1) | set(rows.horse_no_2) | set(rows.horse_no_3)))
        require(actual_roster == roster, f"ordered-joint runner roster differs from HY common roster: {race_id}")
        count = expected_event_count("TRI", len(roster))
        require(len(rows) == count, f"ordered triple cardinality changed: {race_id}")
        for col in ("p_ordered_joint", "control_p_ordered_joint"):
            mass = float(rows[col].sum())
            require(np.isclose(mass, 1.0, rtol=0, atol=1e-12), f"ordered mass != 1: {race_id} {col}")
        set_key = rows[["horse_no_1", "horse_no_2", "horse_no_3"]].to_numpy(int)
        canonical_set = np.sort(set_key, axis=1)
        set_frame = pd.DataFrame({"a": canonical_set[:, 0], "b": canonical_set[:, 1], "c": canonical_set[:, 2],
                                  "q": rows.q_top3_set.to_numpy(float),
                                  "p": rows.p_ordered_joint.to_numpy(float),
                                  "control": rows.control_p_ordered_joint.to_numpy(float)})
        set_mass = set_frame.groupby(["a", "b", "c"], sort=True).agg(
            q_min=("q", "min"), q_max=("q", "max"), p_set=("p", "sum"), control_set=("control", "sum")
        ).reset_index()
        require(np.allclose(set_mass.q_min, set_mass.q_max, rtol=0, atol=1e-12),
                f"q_top3_set differs across orders of a set: {race_id}")
        require(np.allclose(set_mass.p_set, set_mass.q_min, rtol=0, atol=1e-12),
                f"head ordered joint does not preserve exact q set mass: {race_id}")
        require(np.allclose(set_mass.control_set, set_mass.q_min, rtol=0, atol=1e-12),
                f"fixed-score control does not preserve exact q set mass: {race_id}")
        mass_rows.append({"race_id": race_id, "field_n": len(roster), "ordered_joint_mass": float(rows.p_ordered_joint.sum()),
                          "control_ordered_mass": float(rows.control_p_ordered_joint.sum()),
                          "q_set_mass": float(set_mass.q_min.sum()),
                          "head_q_set_max_abs_error": float((set_mass.p_set - set_mass.q_min).abs().max()),
                          "control_q_set_max_abs_error": float((set_mass.control_set - set_mass.q_min).abs().max()),
                          "tla_set_count": int(len(set_mass))})

    # Aggregate the ordered event probabilities for the four order-sensitive pools.
    orders = joint[["race_id", "race_date", "field_n", "horse_no_1", "horse_no_2", "horse_no_3",
                    "p_ordered_joint", "control_p_ordered_joint"]].copy()
    a = orders.horse_no_1.to_numpy(int)
    b = orders.horse_no_2.to_numpy(int)
    c = orders.horse_no_3.to_numpy(int)
    orders["qnl_1"] = np.minimum(a, b)
    orders["qnl_2"] = np.maximum(a, b)
    records_by_model: dict[str, list[pd.DataFrame]] = {"F1_STYLE6_COND_ORDER_V1": [],
                                                       "F1_STYLE6_FIXED_SCORE_PL_CONTROL": []}
    specs = {
        "WIN": ["horse_no_1"],
        "QNL": ["qnl_1", "qnl_2"],
        "EXA": ["horse_no_1", "horse_no_2"],
        "TRI": ["horse_no_1", "horse_no_2", "horse_no_3"],
    }
    for pool, keys in specs.items():
        base = ["race_id", "race_date", "field_n", *keys]
        for probability_col, model in (("p_ordered_joint", "F1_STYLE6_COND_ORDER_V1"),
                                       ("control_p_ordered_joint", "F1_STYLE6_FIXED_SCORE_PL_CONTROL")):
            grouped = orders.groupby(base, sort=True, as_index=False)[probability_col].sum()
            records: list[dict[str, Any]] = []
            for row in grouped.itertuples(index=False):
                values = tuple(int(getattr(row, key)) for key in keys)
                records.append({"race_id": str(row.race_id), "race_date": row.race_date,
                                "field_n": int(row.field_n), "event_tuple": values,
                                "p": float(getattr(row, probability_col))})
            records_by_model[model].append(canonical_event_frame(records, model, pool))
    model_frames = [pd.concat(frames, ignore_index=True) for frames in records_by_model.values()]
    ordered_events = pd.concat(model_frames, ignore_index=True)

    # Preserve and verify the canonical native q values. The full joint is used only
    # for an invariance check; summing it never supplies TLA ranking or EV values.
    canonical = pd.read_parquet(TLA_NATIVE)
    canonical["race_id"] = canonical.race_id.astype(str)
    canonical["race_date"] = pd.to_datetime(canonical.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    for col in ("horse_no_1", "horse_no_2", "horse_no_3", "field_n"):
        canonical[col] = pd.to_numeric(canonical[col], errors="raise").astype(int)
    canonical["event_tuple"] = [tuple(sorted((int(a), int(b), int(c)))) for a, b, c in
                                zip(canonical.horse_no_1, canonical.horse_no_2, canonical.horse_no_3)]
    canonical["event_key"] = canonical.event_tuple.map(key_text)
    canonical["p"] = pd.to_numeric(canonical.set_probability, errors="raise")
    require(canonical.race_id.nunique() == 467 and len(canonical) == 50017,
            "canonical native F1_STYLE6 TLA source coverage changed")
    require(canonical.race_id.isin(set(cohort.race_id)).all() and not canonical.duplicated(["race_id", "event_key"]).any(),
            "canonical native TLA event keys are invalid")
    canonical = canonical.loc[:, ["race_id", "race_date", "field_n", "event_key", "event_tuple", "p"]]
    joint_sets = joint[["race_id", "race_date", "field_n", "horse_no_1", "horse_no_2", "horse_no_3",
                        "q_top3_set", "p_ordered_joint", "control_p_ordered_joint"]].copy()
    nums = np.sort(joint_sets[["horse_no_1", "horse_no_2", "horse_no_3"]].to_numpy(int), axis=1)
    joint_sets["event_key"] = [key_text(tuple(row)) for row in nums]
    set_sums = joint_sets.groupby(["race_id", "event_key"], as_index=False).agg(
        q_min=("q_top3_set", "min"), q_max=("q_top3_set", "max"),
        head_p=("p_ordered_joint", "sum"), control_p=("control_p_ordered_joint", "sum"))
    require(np.allclose(set_sums.q_min, set_sums.q_max, rtol=0, atol=1e-12), "q values differ across ordered set rows")
    set_sums = set_sums.merge(canonical[["race_id", "event_key", "p"]].rename(columns={"p": "canonical_p"}),
                              on=["race_id", "event_key"], how="outer", validate="one_to_one", indicator=True)
    require(set_sums._merge.eq("both").all(), "joint ordered sets and canonical TLA keys differ")
    for column in ("q_min", "head_p", "control_p"):
        require(np.allclose(set_sums[column], set_sums.canonical_p, rtol=0, atol=1e-12),
                f"joint-derived TLA does not match canonical F1 q: {column}")
    tla_diagnostic = pd.concat([
        canonical.assign(model="F1_STYLE6_NATIVE_TLA_Q"),
        canonical.assign(model="F1_STYLE6_COND_ORDER_V1_TLA_Q"),
        canonical.assign(model="F1_STYLE6_FIXED_SCORE_PL_CONTROL_TLA_Q"),
    ], ignore_index=True)
    tla_diagnostic = tla_diagnostic.rename(columns={"event_tuple": "_unused_tuple"})
    tla_diagnostic["pool"] = "TLA"
    nums = tla_diagnostic.event_key.map(parse_event_key)
    tla_diagnostic[["horse_no_1", "horse_no_2", "horse_no_3"]] = pd.DataFrame(nums.tolist(), index=tla_diagnostic.index)
    tla_diagnostic["model"] = tla_diagnostic.model.astype(str)
    tla_diagnostic = tla_diagnostic.drop(columns=["_unused_tuple"])
    diagnostic_events = tla_diagnostic[["race_id", "race_date", "pool", "model", "event_key", "horse_no_1",
                                        "horse_no_2", "horse_no_3", "field_n", "p"]]
    all_events = pd.concat([ordered_events, diagnostic_events], ignore_index=True)

    # Categorical pool probability mass must be one for every race and model.
    mass = all_events.groupby(["model", "pool", "race_id"], as_index=False).p.sum()
    require(np.allclose(mass.p.to_numpy(float), 1.0, rtol=0, atol=1e-12),
            "one or more event probability spaces do not sum to one")
    tla_diff = set_sums.copy()
    tla_diff["head_abs_error"] = (tla_diff.head_p - tla_diff.canonical_p).abs()
    tla_diff["control_abs_error"] = (tla_diff.control_p - tla_diff.canonical_p).abs()
    return all_events, pd.DataFrame(mass_rows), tla_diff


def load_and_validate_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame,
                                         dict[str, tuple[int, ...]], set[str], set[str], dict[str, Any]]:
    cohort_all = pd.read_csv(PREVIOUS_COHORT, dtype={"race_id": "string", "race_date": "string"})
    eligible = cohort_all.qpl_eligible.astype(str).str.lower().isin({"true", "1"})
    cohort = cohort_all.loc[eligible, ["race_id", "race_date", "field_n"]].copy()
    cohort["race_id"] = cohort.race_id.astype(str)
    cohort["race_date"] = pd.to_datetime(cohort.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    cohort["field_n"] = pd.to_numeric(cohort.field_n, errors="raise").astype(int)
    require(len(cohort) == cohort.race_id.nunique() == 467, "fixed common cohort changed")
    require(cohort.race_date.nunique() == 70 and cohort.race_date.min() == "2026-01-02"
            and cohort.race_date.max() == "2026-09-12", "fixed common cohort date range changed")
    common_ids = set(cohort.race_id)
    exclusion = pd.read_csv(PREVIOUS_OTHER / "source_exclusions.csv", dtype={"race_id": "string"})
    tri_incomplete = set(exclusion.race_id.astype(str))
    require(len(tri_incomplete) == 245 and tri_incomplete.issubset(common_ids), "fixed TRI exclusions changed")
    universal_ids = common_ids - tri_incomplete
    require(len(universal_ids) == 222, "fixed universal race scope changed")

    # Restrict source reads to the frozen HY probability columns. Its odds and labels
    # are intentionally excluded; raw quotes are read from the separate quote source.
    usecols = ["race_id", "race_date", "pool", "model", "selection_key", "field_n",
               "horse_no_1", "horse_no_2", "horse_no_3", "p"]
    hy = pd.read_csv(PREVIOUS_OTHER / "candidate_rows.csv", usecols=usecols,
                     dtype={"race_id": "string", "race_date": "string", "pool": "string",
                            "model": "string", "selection_key": "string"})
    hy = hy.loc[hy.model.eq("operating_hy_r_form") & hy.pool.isin(ORDERED_POOLS)].copy()
    hy["race_id"] = hy.race_id.astype(str)
    hy = hy.loc[hy.race_id.isin(common_ids)].copy()
    for col in ("field_n", "horse_no_1", "horse_no_2", "horse_no_3"):
        hy[col] = pd.to_numeric(hy[col], errors="coerce").astype("Int64")
    hy["p"] = pd.to_numeric(hy.p, errors="raise")
    require(hy.p.notna().all() and np.isfinite(hy.p.to_numpy(float)).all()
            and ((hy.p >= 0) & (hy.p <= 1)).all(), "invalid frozen HY event probability")
    hy["source_event_tuple"] = hy.selection_key.map(parse_event_key)
    def hy_key(row: pd.Series) -> tuple[int, ...]:
        pool = row.pool
        cols = {"WIN": ["horse_no_1"], "QNL": ["horse_no_1", "horse_no_2"],
                "EXA": ["horse_no_1", "horse_no_2"], "TRI": ["horse_no_1", "horse_no_2", "horse_no_3"]}[pool]
        values = tuple(int(row[col]) for col in cols)
        return tuple(sorted(values)) if pool == "QNL" else values
    hy["event_tuple"] = hy.apply(hy_key, axis=1)
    require((hy.source_event_tuple == hy.event_tuple).all(),
            "HY selection keys do not match their frozen candidate runner columns")
    hy["event_key"] = hy.event_tuple.map(key_text)
    hy["model"] = "HY_R_FORM"
    cohort_dates = cohort.set_index("race_id").race_date.astype(str).to_dict()
    hy["race_date"] = pd.to_datetime(hy.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    require(all(cohort_dates[rid] == date for rid, date in zip(hy.race_id, hy.race_date)),
            "HY candidate dates differ from the fixed common cohort")
    hy = hy[["race_id", "race_date", "pool", "model", "event_key", "horse_no_1", "horse_no_2",
             "horse_no_3", "field_n", "p"]].copy()

    # Runner support is derived from the one-event WIN rows of the frozen HY table.
    win = hy.loc[hy.pool.eq("WIN")]
    roster_map = {rid: tuple(sorted(part.horse_no_1.astype(int))) for rid, part in win.groupby("race_id", sort=True)}
    require(set(roster_map) == common_ids, "HY WIN roster does not cover fixed cohort")
    for rid, roster in roster_map.items():
        require(len(roster) == len(set(roster)) == int(cohort.set_index("race_id").loc[rid, "field_n"]),
                f"invalid frozen HY runner roster: {rid}")

    # Validate the historical HY probabilities against complete event spaces.
    for pool in ORDERED_POOLS:
        part = hy.loc[hy.pool.eq(pool)]
        expected_total = sum(expected_event_count(pool, len(roster_map[rid])) for rid in common_ids)
        require(len(part) == expected_total and not part.duplicated(["race_id", "event_key"]).any(),
                f"HY {pool} candidate cardinality/keys changed")
        for rid, rows in part.groupby("race_id", sort=False):
            expected = expected_keys(pool, roster_map[rid])
            actual = set(rows.event_key.map(parse_event_key))
            require(actual == expected, f"HY {pool} candidate set differs from full event space: {rid}")
            require(np.isclose(rows.p.sum(), 1.0, rtol=0, atol=1e-12), f"HY {pool} event mass != 1: {rid}")
            require(rows.field_n.nunique() == 1 and int(rows.field_n.iloc[0]) == len(roster_map[rid]),
                    f"HY field size differs: {rid} {pool}")
    require(hy.race_id.nunique() == 467, "HY event table does not cover all 467 races")
    require(set(hy.race_id) == common_ids, "HY event table has unexpected races")

    return cohort, hy, exclusion, cohort_all, roster_map, common_ids, universal_ids, {
        "tri_incomplete_races": len(tri_incomplete), "universal_races": len(universal_ids),
        "cohort_dates": int(cohort.race_date.nunique()),
    }


def load_joint_for_common(joint_sha: str, cohort: pd.DataFrame, roster_map: dict[str, tuple[int, ...]]) -> pd.DataFrame:
    require(sha256_file(ORDERED_JOINT) == joint_sha, "ordered-joint artifact changed after approval")
    columns = ["evaluation_year", "race_date", "race_id", "distance_m", "field_n", "horse_no_1", "horse_no_2",
               "horse_no_3", "q_top3_set", "p_conditional_order", "p_ordered_joint",
               "control_p_conditional_order", "control_p_ordered_joint"]
    joint = pd.read_parquet(ORDERED_JOINT, columns=columns)
    common = set(cohort.race_id.astype(str))
    joint["race_id"] = joint.race_id.astype(str)
    joint = joint.loc[joint.race_id.isin(common)].copy()
    return joint


def load_quotes_and_build_candidates(event_prob: pd.DataFrame, source_path: Path,
                                     roster_map: dict[str, tuple[int, ...]],
                                     common_ids: set[str], universal_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    quotes = pd.read_csv(source_path, dtype={"race_id": "string", "race_date": "string", "pool": "string",
                                             "selection_key": "string", "raw_odds": "string",
                                             "source_run_id": "string", "source_page_path": "string",
                                             "source_page_sha256": "string"})
    quotes["race_id"] = quotes.race_id.astype(str)
    quotes["race_date"] = pd.to_datetime(quotes.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    quotes = quotes.loc[quotes.race_id.isin(common_ids) & quotes.pool.isin(ALL_POOLS)].copy()
    quotes["event_tuple"] = quotes.selection_key.map(parse_event_key)
    quotes["event_key"] = quotes.event_tuple.map(key_text)
    quotes["parsed_odds"] = pd.to_numeric(quotes.parsed_odds, errors="coerce")
    quotes["quote_status"] = quotes.quote_status.astype(str)
    require(len(quotes) == 412758 and not quotes.duplicated(["race_id", "pool", "event_key"]).any(),
            "full candidate quote table row count or keys changed")
    require(quotes.groupby("pool").size().to_dict() == {"EXA": 38776, "QNL": 19388, "TLA": 50017,
                                                         "TRI": 300102, "WIN": 4475},
            "candidate quote pool counts changed")
    valid = quotes.quote_status.eq("valid")
    sentinel = ~valid
    require(int((~valid).sum()) == 15343 and set(quotes.loc[sentinel, "pool"]) == {"TRI"},
            "invalid quote status coverage differs from reviewed source audit")
    require(quotes.loc[valid, "parsed_odds"].notna().all()
            and np.isfinite(quotes.loc[valid, "parsed_odds"].to_numpy(float)).all()
            and (quotes.loc[valid, "parsed_odds"] > 0).all(), "valid quote has invalid numeric odds")
    raw_invalid = pd.to_numeric(quotes.loc[sentinel, "raw_odds"], errors="coerce")
    require(raw_invalid.notna().all() and np.allclose(raw_invalid.to_numpy(float), 9999.9, rtol=0, atol=1e-9),
            "invalid TRI quote rows are not the declared 9999.9 sentinel")
    invalid_races = set(quotes.loc[sentinel, "race_id"])
    require(len(invalid_races) == 245 and invalid_races == set(common_ids) - set(universal_ids),
            "whole-race TRI price exclusions differ from source exclusion ledger")

    # Exact full event-space coverage against the operating runner roster.
    for pool in ALL_POOLS:
        actual_all = quotes.loc[quotes.pool.eq(pool)]
        for rid, roster in roster_map.items():
            part = actual_all.loc[actual_all.race_id.eq(rid)]
            actual_keys = set(part.event_tuple)
            require(actual_keys == expected_keys(pool, roster), f"quote event keys differ from full {pool} space: {rid}")
            require(len(part) == expected_event_count(pool, len(roster)), f"quote event count differs: {rid} {pool}")
    require(quotes.loc[quotes.pool.ne("TRI"), "quote_status"].eq("valid").all(),
            "a non-TRI pool contains an invalid quote")
    require(quotes.loc[quotes.pool.eq("TLA"), "quote_status"].eq("valid").all(),
            "TLA diagnostic source has an invalid quote")

    # Keep a quote-only audit before any official label join.
    quote_export = quotes.drop(columns="event_tuple").copy()

    # Ensure every model candidate table has exactly the same candidate keys as quotes.
    event_prob = event_prob.copy()
    event_prob["race_id"] = event_prob.race_id.astype(str)
    event_prob["event_tuple"] = event_prob.event_key.map(parse_event_key)
    required_models = {
        "WIN": set(ORDERED_MODELS), "QNL": set(ORDERED_MODELS), "EXA": set(ORDERED_MODELS), "TRI": set(ORDERED_MODELS),
        "TLA": set(TLA_MODELS),
    }
    for pool in ALL_POOLS:
        qkeys = set(quotes.loc[quotes.pool.eq(pool), ["race_id", "event_key"]].itertuples(index=False, name=None))
        for model in required_models[pool]:
            part = event_prob.loc[event_prob.pool.eq(pool) & event_prob.model.eq(model)]
            pkeys = set(part[["race_id", "event_key"]].itertuples(index=False, name=None))
            require(pkeys == qkeys, f"probability candidate key coverage differs from quotes: {model} {pool}")
    candidate = event_prob.merge(
        quotes.drop(columns="event_tuple"), on=["race_id", "race_date", "pool", "event_key"],
        how="left", validate="many_to_one", indicator=True,
    )
    require(candidate._merge.eq("both").all(), "candidate probability row lacks matching raw quote")
    candidate = candidate.drop(columns=["_merge", "event_tuple"])
    candidate["ev"] = np.where(candidate.quote_status.eq("valid"), candidate.p * candidate.parsed_odds - 1.0, np.nan)

    scope_ids = {
        "per_pool_primary": {"WIN": common_ids, "QNL": common_ids, "EXA": common_ids,
                             "TRI": universal_ids, "TLA": common_ids},
        "universal_222": {pool: universal_ids for pool in ALL_POOLS},
    }
    scoped: list[pd.DataFrame] = []
    for (model, pool), part in candidate.groupby(["model", "pool"], sort=True):
        for scope, pool_ids in scope_ids.items():
            eligible_ids = pool_ids[pool]
            sub = part.loc[part.race_id.isin(eligible_ids)].copy()
            require(sub.race_id.nunique() == len(eligible_ids), f"candidate scope race support missing: {model} {pool} {scope}")
            sub["scope"] = scope
            sub = sub.sort_values(["race_id", "p", "horse_no_1", "horse_no_2", "horse_no_3"],
                                  ascending=[True, False, True, True, True], kind="mergesort")
            sub["probability_rank"] = sub.groupby("race_id", sort=False).cumcount() + 1
            scoped.append(sub)
    scoped_frame = pd.concat(scoped, ignore_index=True)
    return scoped_frame, quote_export, {"quote_rows": int(len(quotes)), "invalid_sentinel_rows": int((~valid).sum()),
                                       "tri_incomplete_races": len(invalid_races), "all_scopes": scope_ids}


def policy_choices(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    decisions: list[dict[str, Any]] = []
    chosen_rows: list[dict[str, Any]] = []
    for (model, pool, scope), base in candidates.groupby(["model", "pool", "scope"], sort=True):
        require(base.quote_status.eq("valid").all(), f"incomplete prices reached policy selection: {model} {pool} {scope}")
        eligible_races = sorted(base.race_id.unique())
        require(base.groupby("race_id").race_date.nunique().eq(1).all(),
                "race date/race id mismatch in policy candidates")
        per_race = {rid: part for rid, part in base.groupby("race_id", sort=True)}
        for policy_id, label in POLICIES:
            for race_id in eligible_races:
                frame = per_race[race_id]
                rank1 = frame.loc[frame.probability_rank.eq(1)]
                require(len(rank1) == 1, f"probability rank 1 missing: {model} {pool} {race_id}")
                if policy_id.startswith("p_rank_") and policy_id != "p_rank_1_ev_positive":
                    rank = int(policy_id.rsplit("_", 1)[1])
                    candidate = frame.loc[frame.probability_rank.eq(rank)]
                elif policy_id == "p_rank_1_ev_positive":
                    candidate = rank1 if float(rank1.iloc[0].ev) > 0 else frame.iloc[0:0]
                else:
                    rank_cap, threshold = {
                        "all_max_ev_positive": (None, 0.0),
                        "top3_max_ev_positive": (3, 0.0),
                        "top5_max_ev_positive": (5, 0.0),
                        "top3_max_ev_gt_020": (3, 0.20),
                    }[policy_id]
                    pool_frame = frame if rank_cap is None else frame.loc[frame.probability_rank.le(rank_cap)]
                    candidate = pool_frame.sort_values(["ev", "horse_no_1", "horse_no_2", "horse_no_3"],
                                                       ascending=[False, True, True, True], kind="mergesort").head(1)
                    if len(candidate) and float(candidate.iloc[0].ev) <= threshold:
                        candidate = frame.iloc[0:0]
                selected = len(candidate) == 1
                row: dict[str, Any] = {
                    "race_id": race_id, "race_date": str(frame.race_date.iloc[0]), "pool": pool, "model": model,
                    "scope": scope, "policy_id": policy_id, "policy_label": label, "selected": selected,
                }
                if selected:
                    winner = candidate.iloc[0]
                    for dest, source in (("selected_event_key", "event_key"), ("selected_horse_no_1", "horse_no_1"),
                                         ("selected_horse_no_2", "horse_no_2"), ("selected_horse_no_3", "horse_no_3"),
                                         ("selected_probability_rank", "probability_rank"), ("selected_p", "p"),
                                         ("selected_quote", "parsed_odds"), ("selected_ev", "ev"),
                                         ("selected_raw_odds", "raw_odds"), ("selected_quote_status", "quote_status")):
                        row[dest] = winner[source]
                    chosen_rows.append(row.copy())
                else:
                    for column in ("selected_event_key", "selected_horse_no_1", "selected_horse_no_2", "selected_horse_no_3",
                                   "selected_probability_rank", "selected_p", "selected_quote", "selected_ev",
                                   "selected_raw_odds", "selected_quote_status"):
                        row[column] = None
                decisions.append(row)
    decision_frame = pd.DataFrame(decisions)
    chosen_frame = pd.DataFrame(chosen_rows)
    require(not decision_frame.duplicated(["race_id", "pool", "model", "scope", "policy_id"]).any(),
            "duplicate race-policy decisions")
    require(int(decision_frame.selected.sum()) == len(chosen_frame), "chosen rows do not reconcile to decision grid")
    return decision_frame, chosen_frame


def load_official_outcomes(cohort: pd.DataFrame, roster_map: dict[str, tuple[int, ...]]) -> tuple[pd.DataFrame, dict[tuple[str, str], tuple[int, ...]]]:
    official = pd.read_csv(OFFICIAL, dtype={"race_id": "string"})
    official["race_id"] = official.race_id.astype(str)
    official = official.loc[official.race_id.isin(set(cohort.race_id))].copy()
    official["horse_number"] = pd.to_numeric(official.horse_number, errors="raise").astype(int)
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="coerce")
    require(len(official) == 4475 and not official.duplicated(["race_id", "horse_number"]).any(),
            "official result roster row count or key uniqueness changed")
    require(official.scratched.astype(str).str.lower().isin({"false", "0"}).all(),
            "official result includes a scratched runner in the fixed cohort")
    require(official.disqualified.astype(str).str.lower().isin({"false", "0"}).all(),
            "official result includes a disqualified runner in the fixed cohort")
    hit_keys: dict[tuple[str, str], tuple[int, ...]] = {}
    result_rows: list[dict[str, Any]] = []
    for race_id, rows in official.groupby("race_id", sort=True):
        expected_roster = set(roster_map[race_id])
        actual_roster = set(rows.horse_number.astype(int))
        require(actual_roster == expected_roster, f"official runner roster differs from fixed cohort: {race_id}")
        finishes = rows.loc[rows.finish_position.isin([1, 2, 3])].sort_values("finish_position")
        require(finishes.finish_position.tolist() == [1.0, 2.0, 3.0], f"official top-three result invalid: {race_id}")
        ordered = tuple(finishes.horse_number.astype(int))
        hit_keys[(race_id, "WIN")] = (ordered[0],)
        hit_keys[(race_id, "QNL")] = tuple(sorted(ordered[:2]))
        hit_keys[(race_id, "EXA")] = ordered[:2]
        hit_keys[(race_id, "TLA")] = tuple(sorted(ordered[:3]))
        hit_keys[(race_id, "TRI")] = ordered[:3]
        for horse_no, finish in zip(finishes.horse_number.astype(int), finishes.finish_position.astype(int)):
            result_rows.append({"race_id": race_id, "finish_position": finish, "horse_number": horse_no})
    require(set(hit_keys) == {(rid, pool) for rid in cohort.race_id for pool in ALL_POOLS},
            "official winning event table incomplete")
    return official[["race_id", "horse_number", "finish_position"]], hit_keys


def attach_outcomes(candidates: pd.DataFrame, decisions: pd.DataFrame, chosen: pd.DataFrame,
                    official: pd.DataFrame, hit_keys: dict[tuple[str, str], tuple[int, ...]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate_out = candidates.copy()
    candidate_out["hit"] = [parse_event_key(row.event_key) == hit_keys[(row.race_id, row.pool)]
                             for row in candidate_out.itertuples(index=False)]
    # Values in event_key are already canonical numeric strings for unordered pools.
    decision_out = decisions.copy()
    def decision_hit(row: Any) -> Any:
        if not bool(row.selected):
            return None
        return parse_event_key(row.selected_event_key) == hit_keys[(row.race_id, row.pool)]
    decision_out["hit"] = [decision_hit(row) for row in decision_out.itertuples(index=False)]
    decision_out["stake_krw"] = decision_out.selected.astype(float) * STAKE
    decision_out["gross_return_krw"] = [
        float(row.selected_quote) * STAKE if bool(row.selected) and bool(row.hit) else 0.0
        for row in decision_out.itertuples(index=False)
    ]
    decision_out["net_profit_krw"] = decision_out.gross_return_krw - decision_out.stake_krw
    selected_out = decision_out.loc[decision_out.selected].copy()
    require(len(selected_out) == len(chosen), "outcome join changed chosen ticket count")
    return candidate_out, decision_out, selected_out


def weighted_draws(group: pd.DataFrame, weights: np.ndarray, date_index: dict[str, int]) -> dict[str, Any]:
    indices = group.race_date.astype(str).map(date_index)
    require(indices.notna().all(), "evaluation race date missing from fixed bootstrap inventory")
    row_weights = weights[:, indices.to_numpy(int)]
    selected = group.selected.to_numpy(bool).astype(float)
    hits = (group.hit.fillna(False).to_numpy(bool) & group.selected.to_numpy(bool)).astype(float)
    gross = group.gross_return_krw.to_numpy(float)
    stake = group.stake_krw.to_numpy(float)
    bets_draw = row_weights @ selected
    hits_draw = row_weights @ hits
    gross_draw = row_weights @ gross
    stake_draw = row_weights @ stake
    roi = np.divide(gross_draw - stake_draw, stake_draw, out=np.full(stake_draw.shape, np.nan), where=stake_draw > 0) * 100
    hit_rate = np.divide(hits_draw, bets_draw, out=np.full(bets_draw.shape, np.nan), where=bets_draw > 0) * 100
    return {"roi": roi, "hit_rate": hit_rate, "bets": bets_draw, "stake": stake_draw}


def ci_fields(values: np.ndarray, prefix: str, zero_count: int) -> dict[str, Any]:
    valid = values[np.isfinite(values)]
    return {f"{prefix}_ci95_low_pct": float(np.percentile(valid, 2.5)) if len(valid) else None,
            f"{prefix}_ci95_high_pct": float(np.percentile(valid, 97.5)) if len(valid) else None,
            f"{prefix}_valid_draws": int(len(valid)), f"{prefix}_zero_denominator_draws": int(zero_count)}


def summarize_and_bootstrap(decisions: pd.DataFrame, draws: np.ndarray, dates: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    date_index = {date: index for index, date in enumerate(dates)}
    weights = np.stack([np.bincount(row, minlength=269) for row in draws]).astype(np.int64)
    summary_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    vectors: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    summary_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for keys, group in decisions.groupby(["pool", "model", "scope", "policy_id"], sort=True):
        pool, model, scope, policy = keys
        chosen = group.loc[group.selected].copy()
        bets = len(chosen)
        hits = int(chosen.hit.sum())
        stake = float(group.stake_krw.sum())
        gross = float(group.gross_return_krw.sum())
        net = float(group.net_profit_krw.sum())
        roi = 100 * net / stake if stake else None
        point = {
            "pool": pool, "pool_korean": POOL_LABELS[pool], "model": model, "scope": scope,
            "policy_id": policy, "policy": next(label for item, label in POLICIES if item == policy),
            "eligible_races": int(group.race_id.nunique()), "selected_races": int(bets),
            "no_bet_races": int(group.race_id.nunique() - bets),
            "coverage_pct": (100 * bets / group.race_id.nunique()) if group.race_id.nunique() else None,
            "hits": hits, "hit_rate_pct": (100 * hits / bets) if bets else None,
            "mean_p_selected": float(chosen.selected_p.mean()) if bets else None,
            "mean_p_actual_hits": float(chosen.loc[chosen.hit, "selected_p"].mean()) if hits else None,
            "mean_selected_probability_rank": float(chosen.selected_probability_rank.mean()) if bets else None,
            "mean_final_quote": float(chosen.selected_quote.mean()) if bets else None,
            "mean_postrace_ev": float(chosen.selected_ev.mean()) if bets else None,
            "stake_krw": stake, "gross_return_krw": gross, "net_profit_krw": net, "roi_pct": roi,
        }
        winners = chosen.loc[chosen.hit].sort_values(
            ["gross_return_krw", "race_date", "race_id", "selected_event_key"],
            ascending=[False, True, True, True], kind="mergesort")
        for count in (1, 3, 5):
            removed = winners.head(count)
            removed_gross = float(removed.gross_return_krw.sum())
            removed_stake = float(removed.stake_krw.sum())
            remain_stake = stake - removed_stake
            point[f"top_{count}_winning_tickets_removed"] = int(len(removed))
            point[f"top_{count}_winning_gross_removed_krw"] = removed_gross
            point[f"top_{count}_winning_stake_removed_krw"] = removed_stake
            point[f"roi_without_top_{count}_winning_tickets_pct"] = (
                100 * ((gross - removed_gross) - (stake - removed_stake)) / remain_stake if remain_stake else None
            )
        draw_data = weighted_draws(group, weights, date_index)
        summary_rows.append(point)
        summary_index[keys] = point
        vectors[keys] = draw_data
        bootstrap_rows.append({"pool": pool, "model": model, "scope": scope, "policy_id": policy,
                               **ci_fields(draw_data["roi"], "roi", int((draw_data["stake"] == 0).sum())),
                               **ci_fields(draw_data["hit_rate"], "hit_rate", int((draw_data["bets"] == 0).sum()))})

    paired_rows: list[dict[str, Any]] = []
    for pool in ORDERED_POOLS:
        for scope in ("per_pool_primary", "universal_222"):
            for policy, _ in POLICIES:
                pairs = [
                    ("HY_R_FORM", "F1_STYLE6_COND_ORDER_V1"),
                    ("F1_STYLE6_FIXED_SCORE_PL_CONTROL", "F1_STYLE6_COND_ORDER_V1"),
                ]
                for model_a, model_b in pairs:
                    key_a, key_b = (pool, model_a, scope, policy), (pool, model_b, scope, policy)
                    require(key_a in vectors and key_b in vectors, f"paired model policy missing: {pool} {scope} {policy}")
                    roi_a, roi_b = vectors[key_a]["roi"], vectors[key_b]["roi"]
                    valid = np.isfinite(roi_a) & np.isfinite(roi_b)
                    delta = roi_a[valid] - roi_b[valid]
                    point_a, point_b = summary_index[key_a]["roi_pct"], summary_index[key_b]["roi_pct"]
                    paired_rows.append({"pool": pool, "scope": scope, "policy_id": policy,
                                        "model_a": model_a, "model_b": model_b,
                                        "roi_delta_a_minus_b_pp": (point_a - point_b) if point_a is not None and point_b is not None else None,
                                        "roi_delta_bootstrap_mean_pp": float(delta.mean()) if len(delta) else None,
                                        "roi_delta_ci95_low_pp": float(np.percentile(delta, 2.5)) if len(delta) else None,
                                        "roi_delta_ci95_high_pp": float(np.percentile(delta, 97.5)) if len(delta) else None,
                                        "roi_delta_valid_draws": int(len(delta)),
                                        "roi_delta_zero_stake_draws": int((~valid).sum()),
                                        "roi_delta_positive_draws": int((delta > 0).sum())})
    return pd.DataFrame(summary_rows), pd.DataFrame(bootstrap_rows), pd.DataFrame(paired_rows), pd.DataFrame()


def rank_diagnostics(candidates: pd.DataFrame, decisions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    calibration: list[dict[str, Any]] = []
    for keys, group in candidates.groupby(["pool", "model", "scope"], sort=True):
        pool, model, scope = keys
        valid = group.loc[group.quote_status.eq("valid")]
        for rank in range(1, 6):
            part = valid.loc[valid.probability_rank.eq(rank)]
            calibration.append({"pool": pool, "model": model, "scope": scope, "probability_rank": rank,
                                "candidate_events": int(len(part)), "mean_p": float(part.p.mean()) if len(part) else None,
                                "hits": int(part.hit.sum()), "observed_hit_rate": float(part.hit.mean()) if len(part) else None,
                                "brier_score": float(((part.p - part.hit.astype(float)) ** 2).mean()) if len(part) else None})
    dist = (decisions.loc[decisions.selected]
            .groupby(["pool", "model", "scope", "policy_id", "selected_probability_rank"], as_index=False)
            .size().rename(columns={"size": "selected"}))
    totals = (decisions.loc[decisions.selected]
              .groupby(["pool", "model", "scope", "policy_id"], as_index=False).size()
              .rename(columns={"size": "selected_total"}))
    if len(dist):
        dist = dist.merge(totals, on=["pool", "model", "scope", "policy_id"], validate="many_to_one")
        dist["selection_rank_pct"] = 100 * dist.selected / dist.selected_total
    return pd.DataFrame(calibration), dist


def load_bootstrap() -> tuple[np.ndarray, list[str], dict[str, Any]]:
    receipt = safe_json(BOOTSTRAP_RECEIPT)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == 269,
            "fixed date bootstrap receipt changed")
    dates_frame = pd.read_parquet(BOOTSTRAP_DATES, columns=["race_date"])
    dates = sorted(set(pd.to_datetime(dates_frame.race_date, errors="raise").dt.strftime("%Y-%m-%d")))
    digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == 269 and digest == receipt.get("date_inventory_sha256"),
            "fixed 269-date inventory differs from bootstrap receipt")
    draws = np.load(BOOTSTRAP, allow_pickle=False)
    require(draws.shape == (2000, 269) and draws.dtype.kind in "iu"
            and draws.min() >= 0 and draws.max() < 269, "fixed bootstrap schedule shape/range changed")
    return draws, dates, receipt


def main() -> None:
    # The independent fit and value approvals are checked before quote rows are read.
    fit, prediction, approval, joint_sha = verify_approvals_and_joint_hash()
    lock, input_hashes = verify_prefit_sources()
    source_manifest = freeze_source_manifest(fit, prediction, approval, joint_sha, input_hashes)

    cohort, hy, exclusions, cohort_all, roster_map, common_ids, universal_ids, source_counts = load_and_validate_sources()
    write_csv(cohort, "cohort.csv")
    write_csv(cohort_all.loc[~cohort_all.qpl_eligible.astype(str).str.lower().isin({"true", "1"})],
              "cohort_exclusions.csv")
    write_csv(exclusions, "tri_source_exclusions.csv")
    scope_rows = []
    for race in cohort.itertuples(index=False):
        for pool in ALL_POOLS:
            for scope in ("per_pool_primary", "universal_222"):
                eligible_scope = ((pool != "TRI" or race.race_id in universal_ids)
                                  if scope == "per_pool_primary" else race.race_id in universal_ids)
                scope_rows.append({"race_id": race.race_id, "race_date": race.race_date, "pool": pool,
                                   "scope": scope, "eligible": eligible_scope,
                                   "role": "tla_invariance_diagnostic" if pool == "TLA" else "ordered_pool_primary",
                                   "exclusion_reason": "tri_incomplete_quote_set" if not eligible_scope else ""})
    write_csv(pd.DataFrame(scope_rows), "scope_race_coverage.csv")
    joint = load_joint_for_common(joint_sha, cohort, roster_map)
    require("control_p_ordered_joint" in joint.columns and "q_top3_set" in joint.columns,
            "frozen predictions are missing predeclared control or q columns")
    order_events, mass_audit, tla_audit = aggregate_joint(joint, cohort, roster_map)
    all_events = pd.concat([hy, order_events], ignore_index=True)
    require(all_events.groupby(["model", "pool"]).size().to_dict() == {
        ("HY_R_FORM", "WIN"): 4475, ("HY_R_FORM", "QNL"): 19388,
        ("HY_R_FORM", "EXA"): 38776, ("HY_R_FORM", "TRI"): 300102,
        ("F1_STYLE6_COND_ORDER_V1", "WIN"): 4475, ("F1_STYLE6_COND_ORDER_V1", "QNL"): 19388,
        ("F1_STYLE6_COND_ORDER_V1", "EXA"): 38776, ("F1_STYLE6_COND_ORDER_V1", "TRI"): 300102,
        ("F1_STYLE6_FIXED_SCORE_PL_CONTROL", "WIN"): 4475,
        ("F1_STYLE6_FIXED_SCORE_PL_CONTROL", "QNL"): 19388,
        ("F1_STYLE6_FIXED_SCORE_PL_CONTROL", "EXA"): 38776,
        ("F1_STYLE6_FIXED_SCORE_PL_CONTROL", "TRI"): 300102,
        ("F1_STYLE6_NATIVE_TLA_Q", "TLA"): 50017,
        ("F1_STYLE6_COND_ORDER_V1_TLA_Q", "TLA"): 50017,
        ("F1_STYLE6_FIXED_SCORE_PL_CONTROL_TLA_Q", "TLA"): 50017,
    }, "event probability table row counts differ from full candidate space")
    tla_probabilities = all_events.loc[all_events.pool.eq("TLA")].pivot(
        index=["race_id", "event_key"], columns="model", values="p")
    require(set(tla_probabilities.columns) == set(TLA_MODELS)
            and np.array_equal(tla_probabilities[TLA_MODELS[0]].to_numpy(float),
                               tla_probabilities[TLA_MODELS[1]].to_numpy(float))
            and np.array_equal(tla_probabilities[TLA_MODELS[0]].to_numpy(float),
                               tla_probabilities[TLA_MODELS[2]].to_numpy(float)),
            "canonical TLA probabilities are not exactly invariant across control/head labels")
    write_csv(mass_audit, "probability_mass_audit.csv")
    write_csv(tla_audit, "tla_probability_invariance.csv")
    write_csv(all_events, "event_probabilities.csv")

    scoped, quote_export, quote_audit = load_quotes_and_build_candidates(
        all_events, PREVIOUS_OTHER / "candidate_quotes.csv", roster_map, common_ids, universal_ids)
    write_csv(quote_export, "candidate_quote_audit.csv")
    write_csv(scoped, "candidate_selection_inputs.csv")

    # Freeze all price-based choices before loading official labels.
    pre_outcome, pre_chosen = policy_choices(scoped)
    write_csv(pre_outcome, "policy_decisions_pre_outcome.csv")
    write_csv(pre_chosen, "chosen_rows_pre_outcome.csv")
    decisions_pre_hash = sha256_file(STUDY / "policy_decisions_pre_outcome.csv")

    official, hit_keys = load_official_outcomes(cohort, roster_map)
    candidate_out, decisions, selected = attach_outcomes(scoped, pre_outcome, pre_chosen, official, hit_keys)
    write_csv(candidate_out, "candidate_evaluation_rows.csv")
    write_csv(decisions, "policy_decisions.csv")
    write_csv(selected, "selected_tickets.csv")
    write_csv(official, "official_runner_labels.csv")

    draws, bootstrap_dates, bootstrap_receipt = load_bootstrap()
    summaries, bootstrap, paired, _ = summarize_and_bootstrap(decisions, draws, bootstrap_dates)
    rank_cal, rank_dist = rank_diagnostics(candidate_out, decisions)
    write_csv(summaries, "strategy_summary.csv")
    write_csv(bootstrap, "strategy_bootstrap_ci.csv")
    write_csv(paired, "paired_hy_minus_order_head.csv")
    write_csv(rank_cal, "probability_rank_calibration.csv")
    write_csv(rank_dist, "selection_rank_distribution.csv")

    # TLA head/control/native q use the exact same canonical values, prices, and keys.
    tla_dec = decisions.loc[decisions.pool.eq("TLA")]
    tla_choice_pivot = tla_dec.pivot(index=["race_id", "scope", "policy_id"], columns="model", values="selected")
    require(tla_choice_pivot.nunique(axis=1).eq(1).all(), "TLA policy choices differ across canonical q models")
    tla_key_pivot = tla_dec.pivot(index=["race_id", "scope", "policy_id"], columns="model", values="selected_event_key")
    require(tla_key_pivot.nunique(axis=1, dropna=False).eq(1).all(), "TLA selected event keys differ across canonical q models")
    tla_summary = summaries.loc[summaries.pool.eq("TLA")].copy()
    require(tla_summary.groupby(["scope", "policy_id"])["roi_pct"].nunique(dropna=False).eq(1).all(),
            "TLA returns differ across canonical q diagnostic models")
    tla_audit["canonical_q_policy_choices_identical"] = True
    tla_audit["canonical_q_roi_diagnostic_only"] = True
    write_csv(tla_audit, "tla_probability_invariance.csv")

    report = {
        "status": "DRAFT_PENDING_ROOT_POST_ANALYSIS_CHECK",
        "study": "20261017_order_head_value_comparison_v1",
        "plan_sha256": PLAN_SHA256,
        "source_manifest_sha256": sha256_file(STUDY / "SOURCE_MANIFEST.json"),
        "ordered_joint_sha256": joint_sha,
        "pre_outcome_decisions_sha256": decisions_pre_hash,
        "primary_scope": {
            "races": 467,
            "dates": 70,
            "pool_primary_eligible_races": {"WIN": 467, "QNL": 467, "EXA": 467, "TRI": 222},
            "universal_eligible_races": 222,
            "tri_incomplete_races": 245,
            "tri_sentinel_quotes": 15343,
        },
        "models": list(ORDERED_MODELS),
        "tla_scope": "canonical q invariance diagnostic only; no HY TLA comparison and no order-head gain claim",
        "policy_count": len(POLICIES),
        "stake_krw": STAKE,
        "bootstrap": {"draws": int(len(draws)), "dates_per_draw": int(draws.shape[1]),
                      "date_inventory_sha256": bootstrap_receipt.get("date_inventory_sha256")},
        "outcome_interpretation": "retrospective final-price oracle EV/ROI; not purchasable-price performance",
        "secondary_analysis_only": True,
        "network_calls": 0,
        "database_queries": 0,
        "model_fits": 0,
        "calibration_fits": 0,
        "generated_rows": {"candidate_evaluation_rows": len(candidate_out), "decision_grid": len(decisions),
                           "chosen_tickets": len(selected), "summary": len(summaries),
                           "bootstrap": len(bootstrap), "paired_differences": len(paired),
                           "probability_mass_audit": len(mass_audit)},
        "quote_audit": quote_audit,
        "top_policy_rows_for_root_review": summaries.loc[
            summaries.pool.isin(ORDERED_POOLS),
            ["pool", "model", "scope", "policy_id", "eligible_races", "selected_races", "hits",
             "stake_krw", "gross_return_krw", "net_profit_krw", "roi_pct",
             "roi_without_top_1_winning_tickets_pct", "roi_without_top_3_winning_tickets_pct",
             "roi_without_top_5_winning_tickets_pct"]
        ].to_dict(orient="records"),
    }
    save_json(STUDY / "REPORT_DRAFT.json", report)
    write_readme_draft(report, summaries, paired)
    outputs = [p for p in STUDY.iterdir() if p.is_file() and p.name not in {"OUTPUT_MANIFEST_DRAFT.json"}]
    output_hashes = {path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                     for path in sorted(outputs) if path.name not in {"OUTPUT_MANIFEST_DRAFT.json"}}
    save_json(STUDY / "OUTPUT_MANIFEST_DRAFT.json", {
        "status": "DRAFT_PENDING_ROOT_POST_ANALYSIS_CHECK",
        "plan_sha256": PLAN_SHA256,
        "report_draft_sha256": sha256_file(STUDY / "REPORT_DRAFT.json"),
        "files": output_hashes,
    })
    print(json.dumps({"status": "DRAFT_PENDING_ROOT_POST_ANALYSIS_CHECK",
                      "report": str(STUDY / "REPORT_DRAFT.json"),
                      "candidate_rows": len(candidate_out), "decision_rows": len(decisions),
                      "selected_rows": len(selected), "summary_rows": len(summaries),
                      "paired_rows": len(paired)}, ensure_ascii=False, indent=2))


def write_readme_draft(report: dict[str, Any], summaries: pd.DataFrame, paired: pd.DataFrame) -> None:
    rows = summaries.loc[(summaries.scope.eq("per_pool_primary")) & summaries.pool.isin(ORDERED_POOLS)]
    lines = [
        "# Conditional order head postrace value comparison",
        "",
        "This is a secondary retrospective comparison on the fixed 2026 cohort. EV and ROI use archived final displayed odds after the race and are oracle hindsight measures, not real purchase prices or operating profit. The results do not decide model adoption.",
        "",
        "The primary comparison covers WIN, QNL, EXA, and TRI. TRI uses only the 222 races with complete candidate prices; the universal comparison uses that same 222-race set for all four pools. Ten ticket policies and KRW 1,000 stakes were fixed in `PLAN.md` before any quote-based choices.",
        "",
        "TLA is only an invariance diagnostic. The order-head and fixed-score control probabilities are reconciled to the canonical saved F1_STYLE6 set probabilities, and the canonical values are used for ranking and EV. TLA choices are required to match exactly; they do not show an order-head gain.",
        "",
        "## Primary scope snapshot",
        "",
        "| Pool | Model | Policy | Bets / eligible | Hits | Net (KRW) | ROI | ROI after removing top hit |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows.itertuples(index=False):
        roi = "NA" if pd.isna(row.roi_pct) else f"{row.roi_pct:.2f}%"
        rem = "NA" if pd.isna(row.roi_without_top_1_winning_tickets_pct) else f"{row.roi_without_top_1_winning_tickets_pct:.2f}%"
        lines.append(f"| {row.pool} | {row.model} | {row.policy_id} | {row.selected_races} / {row.eligible_races} | {row.hits} | {row.net_profit_krw:.0f} | {roi} | {rem} |")
    lines.extend([
        "",
        "The complete fixed-rule outcomes are in `strategy_summary.csv`; same-draw HY−head differences are in `paired_hy_minus_order_head.csv`. The 2,000 × 269 date-block intervals are in `strategy_bootstrap_ci.csv`. The full candidate event, price, and hit tables retain losing as well as winning events.",
        "",
        "The root reviewer must check the draft outputs before `REPORT.json` and the final manifest are frozen. `REPORT_DRAFT.json` and `OUTPUT_MANIFEST_DRAFT.json` are the review artifacts.",
    ])
    path = STUDY / "README_DRAFT.md"
    require(path.parent.resolve() == STUDY.resolve(), "README output escaped study directory")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
