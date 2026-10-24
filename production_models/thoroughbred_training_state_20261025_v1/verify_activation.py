"""Read-only checks of the active release, retained profiles and registered dry-run."""

from pathlib import Path
import json
import subprocess
import sys
import numpy as np
import pandas as pd
import features

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    registry = json.loads((ROOT / "config/prediction_model_registry.json").read_text())
    old = json.loads((HERE / "previous_registry.json").read_text())
    name = "thoroughbred-training-state-20261025-v1"
    require(registry["domains"]["thoroughbred"]["active_profile"] == name, "Wrong profile")
    for key, profile in old["profiles"].items():
        require(registry["profiles"][key] == profile, "Retained profile changed: " + key)
    require(registry["domains"]["jeju"] == old["domains"]["jeju"], "Jeju routing changed")
    for domain in ["thoroughbred", "jeju"]:
        result = json.loads(
            (
                HERE
                / f"verification/{'registered_thoroughbred' if domain == 'thoroughbred' else 'unchanged_jeju'}_resolver.json"
            ).read_text()
        )
        require(result["ok"] is True, "Resolver failed")
        require(
            result["registry_sha256"]
            == features.sha(ROOT / "config/prediction_model_registry.json"),
            "Outdated resolver",
        )
    out = HERE / "verification/registered_dry_run_final"
    meta = json.loads((out / "run_metadata.json").read_text())
    require(
        meta["model_profile"] == name and meta["preview"] is False and meta["dry_run"] is True,
        "Wrong inference mode",
    )
    require(meta["database_writes"] == 0 and meta["network_calls"] == 0, "Unexpected writes")
    require(
        meta["registry_sha256"] == features.sha(ROOT / "config/prediction_model_registry.json"),
        "Outdated run",
    )
    for filename, digest in meta["files"].items():
        require(features.sha(out / filename) == digest, "Output hash mismatch")
    predicted = pd.read_parquet(out / "runner_predictions.parquet")
    expected = pd.read_parquet(HERE / "fixtures/expected_probabilities.parquet")
    joined = expected.merge(
        predicted, on=["race_key", "program_no", "horse_id"], validate="one_to_one"
    )
    require(len(joined) == len(expected) == len(predicted) == 432, "Runner loss")
    for before, after in [("win", "prob_win"), ("top2", "prob_top2"), ("top3", "prob_top3")]:
        np.testing.assert_allclose(joined[before], joined[after], rtol=0, atol=1e-12)
    validated = subprocess.run(
        [
            sys.executable,
            "-B",
            str(
                ROOT
                / ".agents/skills/horse-racing-prediction-publisher/scripts/validate_prediction_payload.py"
            ),
            str(out / "runner_predictions.parquet"),
            "--domain",
            "thoroughbred",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    # No real card or DB connection is supplied: the incompatible old builder
    # must reject immediately, before creating the output or querying sources.
    legacy_output = HERE / "verification/legacy_must_not_create"
    require(not legacy_output.exists(), "Unexpected existing legacy output")
    legacy = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/build_current_prediction_bundles.py"),
            "--date",
            "20261025",
            "--seoul-snapshot",
            "/nonexistent/card",
            "--jeju-inference",
            "/nonexistent/inference",
            "--output",
            str(legacy_output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(
        legacy.returncode != 0 and "use scripts/predict_thoroughbred_main.py" in legacy.stderr,
        "Old builder failed to reject wrong champion",
    )
    require(not legacy_output.exists(), "Old builder created output")
    result = {
        "status": "passed",
        "active_profile": name,
        "registry_sha256": features.sha(ROOT / "config/prediction_model_registry.json"),
        "all_previous_profiles_preserved": True,
        "jeju_routing_preserved": True,
        "registered_dry_run_races": 40,
        "registered_dry_run_runners": 432,
        "locked_probabilities_reproduced": True,
        "payload_validation": json.loads(validated.stdout),
        "legacy_builder_rejects_new_profile": True,
        "database_or_network_writes": 0,
        "verifier_sha256": features.sha(Path(__file__).resolve()),
    }
    (HERE / "verification/activation_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
