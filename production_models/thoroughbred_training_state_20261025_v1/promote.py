"""Register an immutable reviewed profile; retain old profiles byte-for-byte in content."""

from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, os

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE = "thoroughbred-training-state-20261025-v1"
OLD = "thoroughbred-main-20260919-v1"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    path = ROOT / "config/prediction_model_registry.json"
    registry = json.loads(path.read_text())
    original = json.loads((HERE / "previous_registry.json").read_text())
    if registry["domains"]["thoroughbred"]["active_profile"] == PROFILE:
        print("Already promoted; no change")
        return
    if registry["domains"]["thoroughbred"]["active_profile"] != OLD:
        raise RuntimeError("Active profile changed during promotion preparation")
    if (
        registry["profiles"][OLD] != original["profiles"][OLD]
        or registry["domains"]["jeju"] != original["domains"]["jeju"]
    ):
        raise RuntimeError("Existing profiles changed during preparation")
    verification = json.loads((HERE / "verification/technical_verification.json").read_text())
    for key in [
        "feature_builder_parity_passed",
        "numerical_replay_passed",
        "card_contract_checks_passed",
        "publication_payload_fixture_passed",
        "cli_preview_passed",
    ]:
        if verification.get(key) is not True:
            raise RuntimeError("Technical gate failed: " + key)
    # This decision records the user's explicit override of the recommendation
    # to wait for independent future evaluation; it does not falsify that gate.
    decision = {
        "decided_on": "2026-10-25",
        "authorization": "explicit_user_request_in_this_chat",
        "user_request": "운영모델을 교체하자 그리고 지금 이 모델은 지속적으로 발전시키자",
        "previous_profile": OLD,
        "selected_profile": PROFILE,
        "selected_variant": "personal_t2_2026",
        "production_changed": True,
        "technical_verification_passed": True,
        "new_training_fits": 0,
        "comparative_evidence": {
            "matched_races": 1258,
            "operating_axis_hits": 800,
            "selected_axis_hits": 830,
            "axis_difference_pp": 2.384737678855326,
            "axis_ci95_pp": [0.07029560201874559, 4.773468558089691],
            "training_only_increment_hits": 13,
            "busan_qpl_three_difference_hits": -15,
        },
        "independent_future_validation_passed": False,
        "historical_training_publication_times_certified": False,
        "stability_limitations_acknowledged": [
            "repeated historical development period",
            "Busan axis uncertainty",
            "Busan qpl3 deterioration",
            "data snapshot freshness requires ongoing audit",
        ],
        "promotion_basis": "User chose production adoption after comparative report and recommendation to defer; technical release gates completed.",
        "rollback_profile": OLD,
        "rollback_snapshot_sha256": sha(HERE / "previous_registry.json"),
        "future_candidates_auto_promote": False,
        "jeju_changed": False,
        "database_publications_changed": False,
    }
    (HERE / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    provenance = json.loads((HERE / "asset_provenance.json").read_text())
    provenance["generated_math_sha256"] = sha(HERE / "feature_math.py")
    provenance["formatting"] = (
        "Pure math mechanically extracted, module aliases adapted, formatted byruff; parity checked against frozen inputs."
    )
    (HERE / "asset_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    )
    files = {
        "meet1_model": HERE / "meet_1_model.txt",
        "meet1_metadata": HERE / "meet_1_metadata.json",
        "meet3_model": HERE / "meet_3_model.txt",
        "meet3_metadata": HERE / "meet_3_metadata.json",
        "deployment_spec": HERE / "model_spec.json",
        "feature_contract": HERE / "feature_contract.json",
        "feature_labels": HERE / "feature_labels.json",
        "feature_builder": HERE / "features.py",
        "feature_math": HERE / "feature_math.py",
        "training_daily_query": HERE / "daily_sql.sql",
        "training_window_query": HERE / "window_sql.sql",
        "probability_math": HERE / "probability.py",
        "inference_engine": HERE / "inference.py",
        "reference_inference": ROOT / "scripts/predict_thoroughbred_main.py",
        "source_reference_manifest": HERE / "source_manifest.json",
        "asset_provenance": HERE / "asset_provenance.json",
        "selection_decision": HERE / "decision.json",
        "release_verification": HERE / "verification/technical_verification.json",
        "release_verifier": HERE / "verify_release.py",
        "fixture_manifest": HERE / "fixtures/manifest.json",
        "comparative_results": ROOT
        / "thoroughbred/research/20261025_operating_training_comparison_v1/outputs/results.json",
        "comparative_verification": ROOT
        / "thoroughbred/research/20261025_operating_training_comparison_v1/outputs/verification.json",
    }
    artifacts = {
        name: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for name, p in files.items()
    }
    components = {
        name: {
            "candidate": "personal_t2",
            "model_version": "personal_t2_2026",
            "artifact_by_meet": {"1": "meet1_model", "3": "meet3_model"},
            "metadata_by_meet": {"1": "meet1_metadata", "3": "meet3_metadata"},
            "calibration": "frozen2025_set_and_conditional_order_temperatures",
            "role": role,
            "shared_coherent_joint": True,
        }
        for name, role in [("A", "runner_marginals"), ("B", "unordered_trio"), ("C", "exact_order")]
    }
    profile = {
        "domain": "thoroughbred",
        "status": "production",
        "selection_policy": "promoted_champion_only",
        "champion_id": "personal_t2_2026_seoul_busan_20261025",
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "probability_contract": "thoroughbred_training_state_joint_v1",
        "combination_algorithm_version": "trio_set_within_set_pl_v1",
        "components": components,
        "artifacts": artifacts,
        "supported_meets": [1, 3],
        "prediction_years": [2026],
        "rollback_profile": OLD,
        "promotion_authorization": "explicit_user_request_20261025",
        "verification_gates": [
            {
                "path": str((HERE / "verification/technical_verification.json").relative_to(ROOT)),
                "requires": {
                    "status": "passed",
                    "feature_builder_parity_passed": True,
                    "numerical_replay_passed": True,
                    "card_contract_checks_passed": True,
                    "publication_payload_fixture_passed": True,
                    "cli_preview_passed": True,
                },
            },
            {
                "path": str((HERE / "decision.json").relative_to(ROOT)),
                "requires": {
                    "production_changed": True,
                    "selected_profile": PROFILE,
                    "technical_verification_passed": True,
                    "jeju_changed": False,
                },
            },
            {
                "path": str(
                    (
                        ROOT
                        / "thoroughbred/research/20261025_operating_training_comparison_v1/outputs/verification.json"
                    ).relative_to(ROOT)
                ),
                "requires": {"status": "passed", "matched_races": 1258, "no_refit": True},
            },
        ],
    }
    if PROFILE in registry["profiles"]:
        raise RuntimeError("New immutable profile name already exists")
    registry["profiles"][PROFILE] = profile
    registry["domains"]["thoroughbred"]["active_profile"] = PROFILE
    assert (
        registry["profiles"][OLD] == original["profiles"][OLD]
        and registry["profiles"]["jeju-hy-r-form-20260919-v1"]
        == original["profiles"]["jeju-hy-r-form-20260919-v1"]
    )
    temp = path.with_suffix(".promotion-tmp")
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, path)
    (HERE / "verification/promotion_receipt.json").write_text(
        json.dumps(
            {
                "status": "registry_updated",
                "active_profile": PROFILE,
                "registry_sha256": sha(path),
                "previous_profile_preserved": True,
                "jeju_profile_preserved": True,
                "decision_sha256": sha(HERE / "decision.json"),
                "new_model_fits": 0,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "active_profile": PROFILE,
                "registry_sha256": sha(path),
                "previous_profile_preserved": True,
            }
        )
    )


if __name__ == "__main__":
    main()
