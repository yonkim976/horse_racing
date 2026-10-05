#!/usr/bin/env python3
"""Registry-verified status and offline replay for the frozen Jeju champion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
JEJU_DIR = Path(__file__).resolve().parent
PREDICTIONS_DIR = JEJU_DIR / "predictions"
REGISTRY_PATH = ROOT / "config/prediction_model_registry.json"
RESOLVER_PATH = ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
PIN_PATH = JEJU_DIR / "config/replay_fixture.json"
EXPECTED_MODEL_SHA256 = "f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706"
EXPECTED_CHAMPION = "HY_R_FORM"
EXPECTED_PROFILE = "jeju-hy-r-form-20260919-v1"
FLOAT_ATOL = 1e-12

# These are the already established inference and probability routines. Importing
# their module defines helpers only; this CLI never invokes its fetch/build main.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.predict_jeju_live_hy_r_form import order_scores, rank_scores  # noqa: E402
from horse_racing.analysis.jeju_hybrid_evaluation import distribution  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_champion() -> dict[str, Any]:
    """Run the repository resolver and pin the selected Jeju champion."""
    if not REGISTRY_PATH.is_file():
        raise RuntimeError(f"model registry is missing: {REGISTRY_PATH}")
    registry_sha = sha256_file(REGISTRY_PATH)
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"model registry is invalid JSON: {exc}") from exc
    active_profile = registry.get("domains", {}).get("jeju", {}).get("active_profile")
    if active_profile != EXPECTED_PROFILE:
        raise RuntimeError(f"unexpected active Jeju profile: {active_profile!r}")
    profile = registry.get("profiles", {}).get(active_profile, {})
    if (
        profile.get("domain") != "jeju"
        or profile.get("status") != "production"
        or profile.get("selection_policy") != "promoted_champion_only"
        or profile.get("champion_id") != EXPECTED_CHAMPION
    ):
        raise RuntimeError("the registry does not identify HY_R_FORM as the promoted Jeju champion")
    artifact = profile.get("artifacts", {}).get("HY_R_FORM_model", {})
    if artifact.get("sha256") != EXPECTED_MODEL_SHA256:
        raise RuntimeError("the registered Jeju champion hash differs from the pinned HY_R_FORM hash")
    if not RESOLVER_PATH.is_file():
        raise RuntimeError(f"official model resolver is missing: {RESOLVER_PATH}")

    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVER_PATH),
            "--repo-root",
            str(ROOT),
            "--domain",
            "jeju",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        resolution = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or result.stdout.strip() or str(exc)
        raise RuntimeError(f"model resolver returned invalid JSON: {detail}") from exc
    if result.returncode or resolution.get("ok") is not True:
        raise RuntimeError(resolution.get("error", "Jeju model resolution failed"))
    if (
        resolution.get("domain") != "jeju"
        or resolution.get("active_profile") != EXPECTED_PROFILE
        or resolution.get("champion_id") != EXPECTED_CHAMPION
        or resolution.get("registry_sha256") != registry_sha
    ):
        raise RuntimeError("resolver result does not match the current registered Jeju champion")
    verified = {
        entry["name"]: entry for entry in resolution.get("verified_artifacts", [])
    }
    model_entry = verified.get("HY_R_FORM_model")
    if model_entry is None or model_entry.get("sha256") != EXPECTED_MODEL_SHA256:
        raise RuntimeError("resolver did not verify the pinned HY_R_FORM model")
    registered_path = artifact.get("path")
    if model_entry.get("path") != registered_path:
        raise RuntimeError("resolver artifact path differs from the Jeju registry")
    model_path = (ROOT / registered_path).resolve()
    try:
        model_path.relative_to(ROOT)
    except ValueError as exc:
        raise RuntimeError("registered Jeju model path escapes the repository") from exc
    if not model_path.is_file() or sha256_file(model_path) != EXPECTED_MODEL_SHA256:
        raise RuntimeError("the resolved Jeju model does not match the pinned SHA-256")

    organized_link = JEJU_DIR / "models/current/HY_R_FORM.pkl"
    if not organized_link.is_file() or sha256_file(organized_link) != EXPECTED_MODEL_SHA256:
        raise RuntimeError("jeju/models/current/HY_R_FORM.pkl is missing or has a different hash")
    if sha256_file(REGISTRY_PATH) != registry_sha:
        raise RuntimeError("the shared model registry changed while it was being resolved")

    return {
        "domain": "jeju",
        "active_profile": EXPECTED_PROFILE,
        "champion_id": EXPECTED_CHAMPION,
        "model_path": registered_path,
        "resolved_model_path": str(model_path.relative_to(ROOT)),
        "model_sha256": EXPECTED_MODEL_SHA256,
        "registry_path": str(REGISTRY_PATH.relative_to(ROOT)),
        "registry_sha256": registry_sha,
        "resolver_path": str(RESOLVER_PATH.relative_to(ROOT)),
        "resolver_sha256": sha256_file(RESOLVER_PATH),
        "probability_contract": resolution.get("probability_contract"),
        "combination_algorithm_version": resolution.get("combination_algorithm_version"),
    }


def load_pinned_fixture() -> tuple[dict[str, Any], dict[str, Any], Path]:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    fixture = (ROOT / pin["fixture"]).resolve()
    manifest_path = fixture / "manifest.json"
    if sha256_file(manifest_path) != pin["manifest_sha256"]:
        raise RuntimeError("the preserved Jeju replay fixture manifest hash changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = pin["required_file_sha256"]
    if not set(required).issubset(manifest):
        raise RuntimeError("the pinned replay fixture manifest omits required prediction files")

    for relative, expected in manifest.items():
        path = (fixture / relative).resolve()
        try:
            path.relative_to(fixture)
        except ValueError as exc:
            raise RuntimeError(f"fixture manifest path escapes its directory: {relative}") from exc
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"replay fixture hash mismatch: {relative}")
        if relative in required and expected != required[relative]:
            raise RuntimeError(f"replay fixture pin disagrees with its manifest: {relative}")

    meta = json.loads((fixture / "metadata.json").read_text(encoding="utf-8"))
    if (
        meta.get("target_date") != pin["target_date"]
        or meta.get("meet") != pin["meet"]
        or meta.get("model") != pin["model"]
        or meta.get("model_sha256") != pin["model_sha256"]
        or meta.get("target_result_endpoints_called") != []
    ):
        raise RuntimeError("replay fixture provenance does not match the pinned Jeju card")
    if pin["model_sha256"] != EXPECTED_MODEL_SHA256 or pin["model"] != EXPECTED_CHAMPION:
        raise RuntimeError("fixture is not pinned to the registered HY_R_FORM champion")
    return pin, meta, fixture


def validate_complete_card(
    frame: pl.DataFrame,
    metadata: dict[str, Any],
    pin: dict[str, Any],
    required_features: set[str],
) -> None:
    """Require the full pinned Jeju field for every fixture race."""
    required_columns = {
        "entry_id",
        "race_id",
        "horse_id",
        "event_date",
        "distance_m",
        "field_size",
    }
    missing = sorted((required_columns | required_features) - set(frame.columns))
    if missing:
        raise ValueError(f"complete feature card is missing required columns: {missing}")
    if metadata.get("meet") != 2:
        raise ValueError("only the pinned Jeju meet=2 fixture is supported")
    if frame.height == 0:
        raise ValueError("feature card is empty")
    if any(frame.get_column(column).null_count() for column in ("entry_id", "race_id", "horse_id")):
        raise ValueError("entry, race, and horse identifiers must be complete")
    if frame.get_column("entry_id").n_unique() != frame.height:
        raise ValueError("duplicate entry_id in feature card")
    if frame.get_column("horse_id").n_unique() != frame.height:
        raise ValueError("duplicate horse_id in pinned feature card")
    if "official_top3" in frame.columns or "label_top3" in frame.columns:
        raise ValueError("replay input must not contain target labels")

    date_values = frame.get_column("event_date").unique().to_list()
    if len(date_values) != 1 or str(date_values[0]) != pin["target_date"]:
        raise ValueError("feature rows do not all belong to the pinned target date")
    expected = {int(race): int(size) for race, size in pin["race_sizes"].items()}
    observed: dict[int, int] = {}
    for group_key, rows in frame.group_by("race_id", maintain_order=True):
        race = int(group_key[0] if isinstance(group_key, tuple) else group_key)
        if race // 100 != int(pin["target_date"].replace("-", "")):
            raise ValueError(f"race_id is outside the pinned Jeju target date: {race}")
        count = rows.height
        field_sizes = set(rows.get_column("field_size").to_list())
        if field_sizes != {count}:
            raise ValueError(f"incomplete card for race {race}: rows={count}, field_size={field_sizes}")
        if count < 3:
            raise ValueError(f"race {race} has fewer than three starters")
        observed[race] = count
    if observed != expected:
        raise ValueError(f"fixture card race/count mismatch: expected={expected}, observed={observed}")


def _compare_frame(
    actual: pl.DataFrame,
    expected: pl.DataFrame,
    *,
    exact_columns: tuple[str, ...],
    float_columns: tuple[str, ...],
    label: str,
) -> dict[str, Any]:
    if actual.height != expected.height:
        raise RuntimeError(f"replay {label} row count differs from the preserved output")
    for column in (*exact_columns, *float_columns):
        if column not in actual.columns or column not in expected.columns:
            raise RuntimeError(f"replay {label} lacks comparison column {column}")
    for column in exact_columns:
        left = actual.get_column(column).cast(pl.String).to_list()
        right = expected.get_column(column).cast(pl.String).to_list()
        if left != right:
            raise RuntimeError(f"replay {label} identity/selection differs in {column}")
    maximum = 0.0
    for column in float_columns:
        left = actual.get_column(column).cast(pl.Float64).to_numpy()
        right = expected.get_column(column).cast(pl.Float64).to_numpy()
        if not np.isfinite(left).all() or not np.isfinite(right).all():
            raise RuntimeError(f"replay {label} contains a non-finite value in {column}")
        delta = float(np.max(np.abs(left - right))) if len(left) else 0.0
        maximum = max(maximum, delta)
        if not np.allclose(left, right, rtol=0.0, atol=FLOAT_ATOL):
            raise RuntimeError(f"replay {label} differs from the preserved output in {column}")
    return {"rows": actual.height, "max_abs_float_difference": maximum}


def attach_display_metadata(scores: pl.DataFrame, frozen_scores: pl.DataFrame) -> pl.DataFrame:
    """Join display-only values through verified one-to-one race entry keys."""
    keys = ("entry_id", "race_id", "horse_id")
    display_columns = ("horse_number", "horse_name", "jockey_name", "burden_kg")
    missing = sorted((set(keys) | set(display_columns)) - set(frozen_scores.columns))
    if missing:
        raise RuntimeError(f"preserved score fixture lacks display metadata: {missing}")
    frozen_rows = frozen_scores.select(*keys, *display_columns).iter_rows(named=True)
    metadata_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in frozen_rows:
        key = tuple(str(row[column]) for column in keys)
        if key in metadata_by_key:
            raise RuntimeError("preserved score fixture has duplicate display metadata keys")
        metadata_by_key[key] = {column: row[column] for column in display_columns}
    score_rows = scores.select(*keys).iter_rows(named=True)
    aligned = []
    for row in score_rows:
        key = tuple(str(row[column]) for column in keys)
        if key not in metadata_by_key:
            raise RuntimeError("preserved score fixture does not cover every feature-card entry")
        aligned.append(metadata_by_key[key])
    if len(metadata_by_key) != scores.height:
        raise RuntimeError("preserved score fixture contains entries outside the complete feature card")
    return scores.with_columns(
        pl.Series("horse_number", [row["horse_number"] for row in aligned]),
        pl.Series("horse_name", [row["horse_name"] for row in aligned]),
        pl.Series("jockey_name", [row["jockey_name"] for row in aligned]),
        pl.Series("burden_kg", [row["burden_kg"] for row in aligned]),
    ).select(
        "entry_id",
        "race_id",
        "horse_id",
        "event_date",
        "distance_m",
        "field_size",
        "rank_score",
        "order_score",
        "horse_number",
        "horse_name",
        "jockey_name",
        "burden_kg",
    )


def _compare_race_records(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> dict[str, Any]:
    if len(actual) != len(expected):
        raise RuntimeError("replay race count differs from the preserved output")
    max_difference = 0.0
    for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
        if left.keys() != right.keys():
            raise RuntimeError(f"replay race record fields differ at index {index}")
        for key in left:
            a, b = left[key], right[key]
            if isinstance(a, float) or isinstance(b, float):
                if not isinstance(a, (float, int)) or not isinstance(b, (float, int)):
                    raise RuntimeError(f"replay race field type differs at {key}")
                delta = abs(float(a) - float(b))
                max_difference = max(max_difference, delta)
                if not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=FLOAT_ATOL):
                    raise RuntimeError(f"replay race prediction differs at {key}")
            elif a != b:
                raise RuntimeError(f"replay race prediction differs at {key}")
    return {"races": len(actual), "max_abs_float_difference": max_difference}


def build_replay(
    frame: pl.DataFrame,
    frozen_scores: pl.DataFrame,
    model: dict[str, Any],
    pin: dict[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    rank_bundle = model["rank_bundle"]
    order_bundle = model["order_bundle"]
    required_features = set(rank_bundle["features"]) | set(order_bundle["features"])
    missing = sorted(required_features - set(frame.columns))
    if missing:
        raise ValueError(f"prepared feature card is missing HY_R_FORM inputs: {missing}")

    rank_raw = rank_scores(rank_bundle, frame)
    order_raw = order_scores(order_bundle, frame)
    if len(rank_raw) != frame.height or len(order_raw) != frame.height:
        raise RuntimeError("champion returned the wrong number of row scores")
    if not np.isfinite(rank_raw).all() or not np.isfinite(order_raw).all():
        raise RuntimeError("champion returned a non-finite raw score")
    score_core = frame.select(
        "entry_id",
        "race_id",
        "horse_id",
        "event_date",
        "distance_m",
        "field_size",
    ).with_columns(
        pl.Series("rank_score", rank_raw),
        pl.Series("order_score", order_raw),
    )
    scores = attach_display_metadata(score_core, frozen_scores)

    race_records: list[dict[str, Any]] = []
    horse_records: list[dict[str, Any]] = []
    invariant_max = {"set_sum_error": 0.0, "order_sum_error": 0.0, "marginal_sum_error": 0.0}
    for group_key, race_frame in scores.group_by("race_id", maintain_order=True):
        race_id = group_key[0] if isinstance(group_key, tuple) else group_key
        part = race_frame.sort("horse_id")
        ids = part.get_column("horse_id").cast(pl.String).to_list()
        set_scores = part.get_column("rank_score").to_numpy()
        ord_scores = part.get_column("order_score").to_numpy()
        sets, orders, log_sets, joint, marginals = distribution(
            set_scores,
            ord_scores,
            float(rank_bundle["beta"]),
            float(model["beta_order"]),
        )
        set_sum = float(np.exp(log_sets).sum())
        order_sum = float(np.exp(joint).sum())
        marginal_sum = float(marginals.sum())
        invariant_max["set_sum_error"] = max(invariant_max["set_sum_error"], abs(set_sum - 1.0))
        invariant_max["order_sum_error"] = max(invariant_max["order_sum_error"], abs(order_sum - 1.0))
        invariant_max["marginal_sum_error"] = max(
            invariant_max["marginal_sum_error"], abs(marginal_sum - 3.0)
        )
        if (
            not np.isfinite(marginals).all()
            or np.any(marginals < -FLOAT_ATOL)
            or np.any(marginals > 1.0 + FLOAT_ATOL)
            or abs(set_sum - 1.0) > FLOAT_ATOL
            or abs(order_sum - 1.0) > FLOAT_ATOL
            or abs(marginal_sum - 3.0) > FLOAT_ATOL
        ):
            raise RuntimeError(f"A/B/C probability invariant failed for race {race_id}")

        set_index = int(np.argmax(log_sets))
        order_slice = joint[set_index * 6 : set_index * 6 + 6]
        order_index = set_index * 6 + int(np.argmax(order_slice))
        pick_index = int(np.argmax(set_scores))
        predicted_set = [ids[index] for index in sets[set_index]]
        predicted_order = [ids[index] for index in orders[order_index]]
        by_horse = {row["horse_id"]: row for row in part.iter_rows(named=True)}
        names = {
            row["horse_id"]: f"{row['horse_number']}번 {row['horse_name']}"
            for row in part.iter_rows(named=True)
        }
        race_number = int(race_id) - int(pin["target_date"].replace("-", "")) * 100
        boundary = sorted(range(len(ids)), key=lambda index: (-marginals[index], ids[index]))
        record = {
            "race_number": race_number,
            "race_id": int(race_id),
            "distance_m": int(part.get_column("distance_m")[0]),
            "field_size": part.height,
            "pick_horse_id": ids[pick_index],
            "pick": names[ids[pick_index]],
            "pick_top3_probability": float(marginals[pick_index]),
            "predicted_set_horse_ids": predicted_set,
            "predicted_set": [names[value] for value in predicted_set],
            "set_probability": float(np.exp(log_sets[set_index])),
            "predicted_order_horse_ids": predicted_order,
            "predicted_order": [names[value] for value in predicted_order],
            "order_probability": float(np.exp(joint[order_index])),
            "third_by_probability": names[ids[boundary[2]]],
            "fourth_by_probability": names[ids[boundary[3]]],
            "third_fourth_probability_gap": float(marginals[boundary[2]] - marginals[boundary[3]]),
        }
        race_records.append(record)
        for model_rank, index in enumerate(boundary, 1):
            row = by_horse[ids[index]]
            horse_records.append(
                {
                    **row,
                    "race_number": race_number,
                    "top3_probability": float(marginals[index]),
                    "model_rank": model_rank,
                    "selected_pick": index == pick_index,
                    "selected_set": ids[index] in predicted_set,
                }
            )

    if max(invariant_max.values()) > FLOAT_ATOL:
        raise RuntimeError(f"A/B/C probability invariant exceeded tolerance: {invariant_max}")
    horses = pl.DataFrame(horse_records, infer_schema_length=None)
    return scores, horses, race_records, invariant_max


def output_directory(value: str) -> Path:
    proposed = Path(value).expanduser()
    if not proposed.is_absolute():
        proposed = ROOT / proposed
    destination = proposed.resolve(strict=False)
    parent = destination.parent.resolve()
    if parent != PREDICTIONS_DIR.resolve():
        raise ValueError("replay output must be a new direct child of jeju/predictions/")
    if proposed.is_symlink() or destination.exists():
        raise FileExistsError(f"refuse to overwrite existing replay output: {destination}")
    return destination


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def run_status() -> dict[str, Any]:
    state = resolve_champion()
    state.update(
        {
            "ok": True,
            "message": "등록된 제주 기준 모델은 HY_R_FORM이며 resolver·artifact SHA 검증을 통과했습니다.",
        }
    )
    return state


def run_replay(output_value: str) -> dict[str, Any]:
    state = resolve_champion()
    pin, metadata, fixture = load_pinned_fixture()
    with (ROOT / state["model_path"]).open("rb") as stream:
        model = pickle.load(stream)  # noqa: S301 - official resolver verified the local artifact
    if model.get("kind") != "hybrid" or model.get("model_name") != EXPECTED_CHAMPION:
        raise RuntimeError("registered model bundle has an unexpected HY_R_FORM layout")
    rank_bundle = model.get("rank_bundle", {})
    order_bundle = model.get("order_bundle", {})
    if not rank_bundle.get("features") or not order_bundle.get("features"):
        raise RuntimeError("HY_R_FORM rank/order feature contracts are incomplete")
    feature_frame = pl.read_parquet(fixture / "live_features.parquet")
    score_file = pl.read_parquet(fixture / "model_scores.parquet")
    validate_complete_card(
        feature_frame,
        metadata,
        pin,
        set(rank_bundle["features"]) | set(order_bundle["features"]),
    )
    scores, horses, races, invariant_errors = build_replay(
        feature_frame, score_file, model, pin
    )

    horse_file = pl.read_parquet(fixture / "horse_predictions.parquet")
    race_file = json.loads((fixture / "race_predictions.json").read_text(encoding="utf-8"))
    score_check = _compare_frame(
        scores,
        score_file,
        exact_columns=("entry_id", "race_id", "horse_id", "event_date", "distance_m", "field_size"),
        float_columns=("rank_score", "order_score"),
        label="model scores",
    )
    horse_check = _compare_frame(
        horses,
        horse_file,
        exact_columns=(
            "entry_id",
            "race_id",
            "horse_id",
            "race_number",
            "model_rank",
            "selected_pick",
            "selected_set",
        ),
        float_columns=("rank_score", "order_score", "top3_probability"),
        label="horse predictions",
    )
    race_check = _compare_race_records(races, race_file)
    registry_sha_before = state["registry_sha256"]
    if sha256_file(REGISTRY_PATH) != registry_sha_before:
        raise RuntimeError("the shared model registry changed during replay")

    destination = output_directory(output_value)
    destination.mkdir(exist_ok=False)
    scores.write_parquet(destination / "model_scores.parquet", compression="zstd")
    horses.write_parquet(destination / "horse_predictions.parquet", compression="zstd")
    write_json(destination / "race_predictions.json", races)
    verification = {
        "passed": True,
        "kind": "historical_fixture_replay",
        "fixture_target_date": pin["target_date"],
        "meet": pin["meet"],
        "races": len(races),
        "entries": scores.height,
        "score_comparison": score_check,
        "horse_prediction_comparison": horse_check,
        "race_prediction_comparison": race_check,
        "probability_invariant_max_abs_error": invariant_errors,
        "labels_loaded": False,
        "network_called": False,
        "database_opened": False,
    }
    write_json(destination / "replay_verification.json", verification)
    inference_manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "domain": "jeju",
        "model": EXPECTED_CHAMPION,
        "model_sha256": state["model_sha256"],
        "model_registry_sha256": state["registry_sha256"],
        "resolver_path": state["resolver_path"],
        "resolver_sha256": state["resolver_sha256"],
        "fixture": pin["fixture"],
        "fixture_manifest_sha256": pin["manifest_sha256"],
        "feature_card_sha256": pin["required_file_sha256"]["live_features.parquet"],
        "target_date": pin["target_date"],
        "meet": pin["meet"],
        "purpose": "기준 HY_R_FORM의 저장 카드 재현. 새로운 성능 평가나 live 예측이 아님.",
        "result_status": "historical_replay_only",
        "verification_passed": True,
    }
    write_json(destination / "inference_manifest.json", inference_manifest)
    generated_manifest = {
        path.name: sha256_file(path)
        for path in sorted(destination.iterdir())
        if path.is_file()
    }
    write_json(destination / "manifest.json", generated_manifest)
    state.update(
        {
            "ok": True,
            "output": str(destination.relative_to(ROOT)),
            **verification,
        }
    )
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="verify the registered Jeju champion and hashes")
    replay = subparsers.add_parser("replay", help="replay the pinned complete historical card")
    replay.add_argument(
        "--output",
        required=True,
        help="new output directory under jeju/predictions/; existing paths are rejected",
    )
    args = parser.parse_args()
    try:
        result = run_status() if args.command == "status" else run_replay(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
