#!/usr/bin/env python3
"""Read-only registry-backed Thoroughbred prediction and replay commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "thoroughbred" / "predictions"
REGISTRY_PATH = ROOT / "config" / "prediction_model_registry.json"
RESOLVER_PATH = (
    ROOT
    / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
)
REPLAY_ROOT = ROOT / "research" / "thoroughbred_restart_20260928"
TARGETS_CODE = (
    ROOT / "data/research/thoroughbred_three_targets_20260918_v3/code"
)

if str(TARGETS_CODE) not in sys.path:
    sys.path.insert(0, str(TARGETS_CODE))

import targets_core as tc  # noqa: E402
from infer_targets import IDENTITY, read_frame, validate_frame  # noqa: E402

VALIDATED_VENUES = frozenset({"SEOUL", "BUSAN"})
KNOWN_VENUES = VALIDATED_VENUES | {"YEONGCHEON"}
REPLAY_INPUT = REPLAY_ROOT / "retained_replay_input.parquet"
REPLAY_A = REPLAY_ROOT / "retained_A_predictions.parquet"
REPLAY_BC = REPLAY_ROOT / "retained_BC_predictions.parquet"
REPLAY_SCORES = REPLAY_ROOT / "retained_raw_scores.npz"
REPLAY_MANIFEST = REPLAY_ROOT / "manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_production_model() -> dict[str, Any]:
    """Run the repository's hash and promotion-gate resolver read-only."""
    if not RESOLVER_PATH.is_file():
        raise RuntimeError(f"registered model resolver is missing: {RESOLVER_PATH}")
    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVER_PATH),
            "--repo-root",
            str(ROOT),
            "--domain",
            "thoroughbred",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or result.stdout.strip() or str(exc)
        raise RuntimeError(f"model resolver returned invalid JSON: {detail}") from exc
    if result.returncode or payload.get("ok") is not True:
        raise RuntimeError(payload.get("error", "registered model resolution failed"))
    return payload


def load_registered_models(
    resolution: dict[str, Any],
) -> tuple[dict[str, Any], tc.TargetBundle, tc.TargetBundle, tc.TargetBundle]:
    registry_bytes = REGISTRY_PATH.read_bytes()
    if hashlib.sha256(registry_bytes).hexdigest() != resolution.get("registry_sha256"):
        raise RuntimeError("registry changed after model resolution; resolve again")
    registry = json.loads(registry_bytes)
    profile_name = registry["domains"]["thoroughbred"]["active_profile"]
    profile = registry["profiles"][profile_name]
    if resolution.get("active_profile") != profile_name:
        raise RuntimeError("registry changed after model resolution; resolve again")

    verified = {item["name"]: item["path"] for item in resolution["verified_artifacts"]}
    required_artifacts = (
        "A_model",
        "A_metadata",
        "BC_model",
        "BC_metadata",
        "WIN_ORDER_model",
        "WIN_ORDER_metadata",
    )
    for key in required_artifacts:
        if key not in verified:
            raise RuntimeError(f"resolver did not verify required artifact: {key}")

    def artifact_path(name: str) -> Path:
        path = (ROOT / verified[name]).resolve()
        path.relative_to(ROOT)
        return path

    a_bundle = tc.load_bundle(artifact_path("A_model").parent)
    bc_bundle = tc.load_bundle(artifact_path("BC_model").parent)
    win_bundle = tc.load_v2_win_bundle(artifact_path("WIN_ORDER_model").parent)
    if set(a_bundle.models) != {"top3"} or set(bc_bundle.models) != {"top3"}:
        raise RuntimeError("registered Thoroughbred artifacts have an unexpected model layout")
    if set(win_bundle.models) != {"win"}:
        raise RuntimeError("registered win-order artifact has an unexpected model layout")
    return profile, a_bundle, bc_bundle, win_bundle


def _required_feature_columns(
    frame: pd.DataFrame, bundles: tuple[tc.TargetBundle, ...]
) -> None:
    needed = {
        name
        for bundle in bundles
        for name in bundle.categorical_features + bundle.numeric_features
    }
    missing = sorted(needed - set(frame.columns))
    if missing:
        raise ValueError(f"prepared feature card is missing model columns: {missing}")


def _validate_venues(frame: pd.DataFrame, allow_unvalidated: bool) -> list[str]:
    venues = set(frame["venue_code"].astype(str))
    unknown = sorted(venues - KNOWN_VENUES)
    if unknown:
        raise ValueError(
            f"unknown Thoroughbred venue code(s): {unknown}; "
            f"known codes are {sorted(KNOWN_VENUES)}"
        )
    unvalidated = sorted(venues - VALIDATED_VENUES)
    if unvalidated and not allow_unvalidated:
        raise ValueError(
            f"the registered Thoroughbred models were not validated for {unvalidated}; "
            "use --allow-unvalidated-venue to score them with the global calibration"
        )
    return unvalidated


def _validate_model_cutoff(
    frame: pd.DataFrame, bundles: tuple[tc.TargetBundle, ...]
) -> None:
    cutoffs: list[pd.Timestamp] = []
    for bundle in bundles:
        training = bundle.metadata.get("training", {})
        value = training.get("max_race_date") or training.get("max_date")
        if not value:
            raise ValueError("registered model metadata has no training cutoff")
        cutoffs.append(pd.Timestamp(value))
    latest_training_date = max(cutoffs)
    race_dates = pd.to_datetime(frame["race_date"], errors="coerce")
    if race_dates.min() <= latest_training_date:
        raise ValueError(
            "the prepared card must be later than every registered model's training cutoff "
            f"({latest_training_date.date()})"
        )


def predict_frame(
    frame: pd.DataFrame,
    profile: dict[str, Any],
    a_bundle: tc.TargetBundle,
    bc_bundle: tc.TargetBundle,
    win_bundle: tc.TargetBundle,
    *,
    historical_replay: bool = False,
    allow_unvalidated_venues: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, np.ndarray], float]:
    """Score a validated full card with the registered A, B/C, and order bundles."""
    inference_status = validate_frame(frame, historical_replay)
    _validate_venues(frame, allow_unvalidated_venues)
    bundles = (a_bundle, bc_bundle, win_bundle)
    _required_feature_columns(frame, bundles)
    _validate_model_cutoff(frame, bundles)

    a_scores = tc.raw_scores(a_bundle, frame)["top3"]
    bc_scores = tc.raw_scores(bc_bundle, frame)["top3"]
    win_scores = tc.raw_scores(win_bundle, frame)["win"]
    raw_scores = {"A": a_scores, "BC": bc_scores, "order": win_scores}

    a_temperatures = a_bundle.metadata["temperature_by_target_and_venue"]["A"]
    bc_temperatures = bc_bundle.metadata["temperature_by_target_and_venue"]
    win_temperatures = win_bundle.metadata["temperature_by_venue"]
    a_rows: list[dict[str, Any]] = []
    combo_rows: list[dict[str, Any]] = []
    max_invariant_error = 0.0

    for race_id, positions in frame.groupby("race_id", sort=False).indices.items():
        positions = np.asarray(positions, dtype=int)
        card = frame.iloc[positions]
        venue = str(card["venue_code"].iloc[0])
        horses = card["hr_no"].astype(str).to_numpy()
        # Match the frozen evaluation contract: venues without an explicit win
        # temperature use 1.0, even when a GLOBAL calibration entry exists.
        win_temperature = float(win_temperatures.get(venue, 1.0))
        a_temperature = float(a_temperatures.get(venue, a_temperatures.get("GLOBAL")))

        a_joint = tc.top3_set_joint(
            a_scores[positions], win_scores[positions], a_temperature, win_temperature
        )
        max_invariant_error = max(
            max_invariant_error, *tc.probability_invariants(a_joint).values()
        )
        orders = a_joint.orders
        order_probability = a_joint.order_probability
        p_win = np.bincount(
            orders[:, 0], weights=order_probability, minlength=len(card)
        )
        p_exact_2 = np.bincount(
            orders[:, 1], weights=order_probability, minlength=len(card)
        )
        p_raw3 = np.bincount(
            orders[:, 2], weights=order_probability, minlength=len(card)
        )
        p_top2 = p_win + p_exact_2
        p_top3 = a_joint.inclusion_probability
        if not np.allclose(p_top3, p_win + p_exact_2 + p_raw3, rtol=0.0, atol=1e-12):
            raise RuntimeError(f"A joint marginals are inconsistent for race {race_id}")
        a_rank = np.argsort(np.argsort(-p_top3, kind="stable"), kind="stable") + 1
        for local, (_, row) in enumerate(card.iterrows()):
            a_rows.append(
                {
                    **{column: row[column] for column in IDENTITY},
                    "feature_cutoff": row["feature_cutoff"],
                    "p_win": float(p_win[local]),
                    "p_top2": float(p_top2[local]),
                    "p_top3": float(p_top3[local]),
                    "p_exact_2": float(p_exact_2[local]),
                    "p_exact_3": float(p_raw3[local]),
                    "A_slot_inclusion_probability": float(p_top3[local]),
                    "raw_score_A": float(a_scores[positions[local]]),
                    "raw_score_BC": float(bc_scores[positions[local]]),
                    "raw_score_WIN_ORDER": float(win_scores[positions[local]]),
                    "pred_rank": int(a_rank[local]),
                    "target": "A",
                    "target_label": "legacy A: runner top-three inclusion",
                    "candidate": profile["components"]["A"]["candidate"],
                    "model_version": profile["champion_id"],
                    "temperature": a_temperature,
                    "availability_profile": "registered_2026_model_features",
                    "inference_status": inference_status,
                }
            )

        for target in ("B", "C"):
            temperature_map = bc_temperatures[target]
            temperature = float(temperature_map.get(venue, temperature_map.get("GLOBAL")))
            joint = tc.top3_set_joint(
                bc_scores[positions], win_scores[positions], temperature, win_temperature
            )
            max_invariant_error = max(
                max_invariant_error, *tc.probability_invariants(joint).values()
            )
            probabilities = joint.set_probability if target == "B" else joint.order_probability
            support = joint.sets if target == "B" else joint.orders
            semantics = "unordered_top3_set" if target == "B" else "ordered_1_2_3"
            for rank, support_index in enumerate(np.argsort(-probabilities, kind="stable")[:10], 1):
                combo_rows.append(
                    {
                        "race_id": race_id,
                        "race_date": card["race_date"].iloc[0],
                        "venue_code": venue,
                        "race_no": card["race_no"].iloc[0],
                        "feature_cutoff": card["feature_cutoff"].iloc[0],
                        "target": target,
                        "target_label": (
                            "legacy B: unordered top-three set"
                            if target == "B"
                            else "legacy C: exact ordered 1-2-3 triple"
                        ),
                        "combination_semantics": semantics,
                        "prediction_rank": rank,
                        # Keep the established JSON key form for downstream table compatibility.
                        "predicted_key": json.dumps(
                            horses[support[support_index]].tolist(), ensure_ascii=False
                        ),
                        "predicted_probability": float(probabilities[support_index]),
                        "candidate": profile["components"][target]["candidate"],
                        "model_version": profile["champion_id"],
                        "temperature": temperature,
                        "inference_status": inference_status,
                    }
                )

    a_frame = pd.DataFrame(a_rows)
    combo_frame = pd.DataFrame(combo_rows)
    if len(a_frame) != len(frame):
        raise RuntimeError("runner prediction output does not cover the complete input card")
    expected_combo_rows = 0
    for size in frame.groupby("race_id", sort=False).size().to_numpy(int):
        expected_combo_rows += min(10, math.comb(int(size), 3))
        expected_combo_rows += min(10, int(size) * (int(size) - 1) * (int(size) - 2))
    if len(combo_frame) != expected_combo_rows:
        raise RuntimeError("B/C output does not cover the supported combinations for every race")
    if not math.isfinite(max_invariant_error) or max_invariant_error > 1e-10:
        raise RuntimeError(
            f"probability invariant error exceeds tolerance: {max_invariant_error}"
        )
    return a_frame, combo_frame, raw_scores, max_invariant_error


def _validate_output_path(
    output: Path, predictions_root: Path = OUTPUT_ROOT
) -> Path:
    destination = output.expanduser().resolve()
    allowed_root = predictions_root.resolve()
    try:
        destination.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"output must be under {allowed_root}") from exc
    if destination == allowed_root:
        raise ValueError("output must name a new run directory below the predictions folder")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {destination}")
    return destination


def _write_outputs(
    output: Path,
    a_frame: pd.DataFrame,
    combo_frame: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    if sha256_file(REGISTRY_PATH) != manifest["registry_sha256"]:
        raise RuntimeError("registry changed during inference; no output published")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".prediction-", dir=OUTPUT_ROOT))
    try:
        a_frame.to_parquet(stage / "A_predictions.parquet", index=False)
        combo_frame.to_parquet(stage / "B_C_top10_predictions.parquet", index=False)
        (stage / "inference_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        if sha256_file(REGISTRY_PATH) != manifest["registry_sha256"]:
            raise RuntimeError("registry changed during output serialization; no output published")
        os.rename(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _build_manifest(
    features: Path,
    profile: dict[str, Any],
    a_frame: pd.DataFrame,
    combo_frame: pd.DataFrame,
    max_invariant_error: float,
) -> dict[str, Any]:
    unvalidated_venues = sorted(set(a_frame["venue_code"].astype(str)) - VALIDATED_VENUES)
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "domain": "thoroughbred",
        "active_profile": profile.get("profile_name"),
        "champion_id": profile["champion_id"],
        "probability_contract": profile["probability_contract"],
        "combination_algorithm_version": profile["combination_algorithm_version"],
        "registry_sha256": profile["registry_sha256"],
        "verified_artifacts": profile["verified_artifacts"],
        "components": {
            target: {
                "candidate": component["candidate"],
                "model_version": component["model_version"],
            }
            for target, component in profile["components"].items()
        },
        "input_path": str(features.resolve()),
        "input_sha256": sha256_file(features),
        "inference_status": a_frame["inference_status"].iloc[0],
        "races": int(a_frame["race_id"].nunique()),
        "runners": len(a_frame),
        "B_C_top10_rows": len(combo_frame),
        "max_probability_invariant_error": max_invariant_error,
        "training": False,
        "database_writes": 0,
        "publication": False,
        "p_exact_3_definition": "P(finish_position == 3), marginalized from the A joint",
        "legacy_target_labels": {
            "A": "legacy A; coherent top-3-set joint and runner marginals",
            "B": "legacy B; unordered top-three set probability",
            "C": "legacy C; exact 1-2-3 ordered triple probability",
        },
        "unvalidated_venues": unvalidated_venues,
        "warning": (
            "global calibration used for a venue without venue-specific validation"
            if unvalidated_venues
            else None
        ),
    }


def _load_verified_replay_fixture() -> pd.DataFrame:
    if not REPLAY_MANIFEST.is_file():
        raise RuntimeError(f"preserved replay manifest is missing: {REPLAY_MANIFEST}")
    manifest = json.loads(REPLAY_MANIFEST.read_text(encoding="utf-8"))
    indexed = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    for path in (REPLAY_INPUT, REPLAY_A, REPLAY_BC, REPLAY_SCORES):
        relative = path.relative_to(ROOT).as_posix()
        expected = indexed.get(relative)
        if not expected:
            raise RuntimeError(f"replay manifest has no hash for {relative}")
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"preserved replay fixture hash mismatch: {relative}")
    # The persisted raw-score fixture is aligned to this physical parquet order.
    frame = pd.read_parquet(REPLAY_INPUT).reset_index(drop=True)
    if len(frame) != 294 or frame["race_id"].nunique() != 27:
        raise RuntimeError("preserved replay fixture must contain 294 runners across 27 races")
    return frame


def _verify_exact_replay(
    a_frame: pd.DataFrame,
    combo_frame: pd.DataFrame,
    raw_scores: dict[str, np.ndarray],
) -> dict[str, float]:
    expected_a = pd.read_parquet(REPLAY_A)
    expected_combo = pd.read_parquet(REPLAY_BC)
    actual_a = a_frame[["race_id", "hr_no", "p_top3"]].rename(
        columns={"p_top3": "probability"}
    )
    actual_combo = combo_frame[
        ["race_id", "target", "prediction_rank", "predicted_key", "predicted_probability"]
    ].rename(columns={"predicted_key": "key", "predicted_probability": "probability"})
    pd.testing.assert_frame_equal(actual_a.reset_index(drop=True), expected_a, check_exact=True)
    pd.testing.assert_frame_equal(
        actual_combo.reset_index(drop=True), expected_combo, check_exact=True
    )
    with np.load(REPLAY_SCORES, allow_pickle=False) as expected_scores:
        if set(expected_scores.files) != set(raw_scores):
            raise AssertionError("preserved raw score fixture has an unexpected component set")
        for name, values in raw_scores.items():
            if not np.array_equal(values, expected_scores[name]):
                raise AssertionError(
                    f"registered model raw scores differ from replay fixture: {name}"
                )
    return {
        "runner_rows": len(actual_a),
        "B_C_rows": len(actual_combo),
        "max_probability_error": 0.0,
        "raw_scores_exact": True,
    }


def _default_run_dir(prefix: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return OUTPUT_ROOT / f"{prefix}_{timestamp}"


def command_status() -> dict[str, Any]:
    result = resolve_production_model()
    result["profile_name"] = result["active_profile"]
    return result


def command_predict(
    features: Path,
    output: Path,
    historical_replay: bool,
    allow_unvalidated_venue: bool = False,
) -> Path:
    destination = _validate_output_path(output)
    resolution = resolve_production_model()
    profile, a_bundle, bc_bundle, win_bundle = load_registered_models(resolution)
    frame = read_frame(features).reset_index(drop=True)
    a_frame, combo_frame, _, max_error = predict_frame(
        frame,
        profile,
        a_bundle,
        bc_bundle,
        win_bundle,
        historical_replay=historical_replay,
        allow_unvalidated_venues=allow_unvalidated_venue,
    )
    profile = {
        **profile,
        "profile_name": resolution["active_profile"],
        "registry_sha256": resolution["registry_sha256"],
        "verified_artifacts": resolution["verified_artifacts"],
    }
    manifest = _build_manifest(features, profile, a_frame, combo_frame, max_error)
    _write_outputs(destination, a_frame, combo_frame, manifest)
    return destination


def command_replay(output: Path | None = None) -> tuple[Path, dict[str, Any]]:
    destination = _validate_output_path(output or _default_run_dir("replay"))
    frame = _load_verified_replay_fixture()
    resolution = resolve_production_model()
    profile, a_bundle, bc_bundle, win_bundle = load_registered_models(resolution)
    a_frame, combo_frame, scores, max_error = predict_frame(
        frame,
        profile,
        a_bundle,
        bc_bundle,
        win_bundle,
        historical_replay=True,
        allow_unvalidated_venues=True,
    )
    comparison = _verify_exact_replay(a_frame, combo_frame, scores)
    profile = {
        **profile,
        "profile_name": resolution["active_profile"],
        "registry_sha256": resolution["registry_sha256"],
        "verified_artifacts": resolution["verified_artifacts"],
    }
    manifest = _build_manifest(REPLAY_INPUT, profile, a_frame, combo_frame, max_error)
    manifest["exact_replay"] = comparison
    _write_outputs(destination, a_frame, combo_frame, manifest)
    return destination, comparison


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="resolve the promoted Thoroughbred profile read-only")

    predict = commands.add_parser("predict", help="score a complete prepared feature card")
    predict.add_argument("--features", type=Path, required=True)
    predict.add_argument("--output", type=Path, required=True)
    predict.add_argument("--historical-replay", action="store_true")
    predict.add_argument(
        "--allow-unvalidated-venue",
        action="store_true",
        help="score known venues without venue-specific validation using global calibration",
    )

    replay = commands.add_parser(
        "replay", help="exactly compare the preserved 294-runner fixture"
    )
    replay.add_argument(
        "--output", type=Path, help="new run directory under thoroughbred/predictions"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(command_status(), ensure_ascii=False, indent=2))
        elif args.command == "predict":
            output = command_predict(
                args.features,
                args.output,
                args.historical_replay,
                args.allow_unvalidated_venue,
            )
            print(json.dumps({"output": str(output)}, ensure_ascii=False))
        else:
            output, comparison = command_replay(args.output)
            print(
                json.dumps(
                    {"output": str(output), "exact_replay": comparison}, ensure_ascii=False
                )
            )
    except (FileExistsError, OSError, RuntimeError, ValueError, AssertionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
