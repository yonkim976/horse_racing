import pytest

from horse_racing.analysis.model_profiles import (
    ModelProfileError,
    select_profile_features,
)

FEATURES = [
    "distance_m",
    "rating",
    "rating_race_z",
    "rating_race_rank",
    "carried_weight_kg",
    "carried_weight_rel",
    "grade_tier",
    "form_recent5_pct",
]


def test_ability_v2_removes_rating_but_keeps_physical_race_conditions() -> None:
    selected = select_profile_features(FEATURES, "ability_v2")
    assert "rating" not in selected
    assert "rating_race_z" not in selected
    assert "rating_race_rank" not in selected
    assert "carried_weight_kg" in selected
    assert "grade_tier" in selected


def test_strict_profile_removes_rating_and_assignment_proxies() -> None:
    selected = select_profile_features(FEATURES, "ability_v2_strict")
    assert selected == ["distance_m", "form_recent5_pct"]


def test_ability_profile_rejects_market_features() -> None:
    with pytest.raises(ModelProfileError, match="시장/배당"):
        select_profile_features(["distance_m", "win_odds"], "ability_v2")


def test_legacy_profile_preserves_existing_experiment_contract() -> None:
    assert select_profile_features(FEATURES, "legacy_all") == FEATURES


def test_core_profile_removes_redundant_interaction_keys() -> None:
    selected = select_profile_features(
        ["distance_m", "front_rival_count", "course_distance_key", "style_pace_key"],
        "ability_v2_core",
    )
    assert selected == ["distance_m", "front_rival_count"]


def test_gate_profile_keeps_only_distance_and_season_gate_priors() -> None:
    features = [
        "distance_m",
        "gate_top3_index_course_distance",
        "gate_top3_index_season",
        "gate_top3_index_going",
        "gate_top3_index_context",
        "gate_context_expected_slots",
        "gate_context_reliability",
    ]

    assert select_profile_features(features, "ability_v2_core") == ["distance_m"]
    assert select_profile_features(features, "ability_v2_gate") == [
        "distance_m",
        "gate_top3_index_course_distance",
        "gate_top3_index_season",
    ]


def test_racefit_v1_core_keeps_energy_but_removes_experimental_condition_state() -> None:
    features = [
        "distance_m",
        "energy_early_rel_avg5",
        "energy_early_late_balance_avg5",
        "condition_state",
        "condition_uncertainty",
    ]

    assert select_profile_features(features, "racefit_v1_core") == [
        "distance_m",
        "energy_early_rel_avg5",
        "energy_early_late_balance_avg5",
    ]


def test_gate_pace_profile_isolates_early_speed_gate_priors() -> None:
    features = [
        "distance_m",
        "gate_top3_index_course_distance",
        "gate_early_speed_course",
        "gate_early_speed_context",
        "gate_early_speed_front_fit",
    ]

    assert select_profile_features(features, "racefit_v1_core") == ["distance_m"]
    assert select_profile_features(features, "racefit_v4_gate_pace") == [
        "distance_m",
        "gate_early_speed_course",
        "gate_early_speed_context",
        "gate_early_speed_front_fit",
    ]


def test_sand_profiles_are_isolated_from_core_and_gate_only_profiles() -> None:
    features = [
        "distance_m",
        "gate_early_speed_context",
        "sand_sensitivity_state",
        "sand_recovery_score",
        "sand_expected_penalty",
    ]

    assert select_profile_features(features, "racefit_v1_core") == ["distance_m"]
    assert select_profile_features(features, "racefit_v4_gate_pace") == [
        "distance_m",
        "gate_early_speed_context",
    ]
    assert select_profile_features(features, "racefit_v5_sand") == [
        "distance_m",
        "sand_sensitivity_state",
        "sand_recovery_score",
        "sand_expected_penalty",
    ]
    assert select_profile_features(features, "racefit_v5_sand_gate_pace") == features


def test_sand_state_profile_keeps_recovery_adjusted_state_but_not_sparse_outputs() -> None:
    features = [
        "distance_m",
        "sand_incident_count_prior",
        "sand_days_since_incident",
        "sand_sensitivity_state",
        "sand_exposure_risk",
        "sand_recovery_evidence",
        "sand_recovery_score",
        "sand_recovered_flag",
        "sand_expected_penalty",
    ]
    assert select_profile_features(features, "racefit_v5_sand_state") == [
        "distance_m",
        "sand_incident_count_prior",
        "sand_days_since_incident",
        "sand_sensitivity_state",
        "sand_exposure_risk",
    ]


def test_sand_event_profile_keeps_only_stable_incident_and_exposure_inputs() -> None:
    features = [
        "distance_m",
        "sand_incident_count_prior",
        "sand_incident_count_365d",
        "sand_days_since_incident",
        "sand_sensitivity_state",
        "sand_exposure_risk",
        "sand_recovery_evidence",
        "sand_recovered_flag",
        "sand_expected_penalty",
    ]
    assert select_profile_features(features, "racefit_v5_sand_event") == [
        "distance_m",
        "sand_incident_count_prior",
        "sand_incident_count_365d",
        "sand_days_since_incident",
        "sand_exposure_risk",
    ]


def test_remediation_features_are_opt_in_and_do_not_change_v5_contract() -> None:
    features = [
        "distance_m",
        "sand_incident_count_prior",
        "current_jockey_train_n_28d",
        "remedial_trial_current_jockey_winner",
        "bit_changed_from_last_start",
    ]

    assert select_profile_features(features, "racefit_v5_sand_event") == [
        "distance_m",
        "sand_incident_count_prior",
    ]
    assert select_profile_features(features, "racefit_v6_remediation") == features


def test_racefit_v2_core_rejects_dynamic_state_but_keeps_live_bias() -> None:
    features = [
        "distance_m",
        "energy_resilience_avg5",
        "condition_state",
        "dynamic_condition_state",
        "dynamic_condition_sd",
        "live_style_fit",
    ]

    assert select_profile_features(features, "racefit_v2_core") == [
        "distance_m",
        "energy_resilience_avg5",
        "live_style_fit",
    ]
    assert select_profile_features(features, "racefit_v2_no_live") == [
        "distance_m",
        "energy_resilience_avg5",
    ]
