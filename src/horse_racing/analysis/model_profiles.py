"""학습 목적별 feature 선택 계약.

기존 실험은 manifest의 모든 feature를 사용했지만, 능력모델 v2는 공식 레이팅과
배당을 학습 입력에서 구조적으로 차단한다. 프로필 선택은 데이터셋을 변경하지 않고
학습 직전에 적용하므로 기존 모델과 산출물을 그대로 재현할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass


class ModelProfileError(ValueError):
    """프로필 feature 계약 위반."""


RATING_FEATURES = frozenset(
    {
        "rating",
        "rating_race_z",
        "rating_race_rank",
        "rating_vs_field_median",
        "rating_within_race_rank_pct",
    }
)

MARKET_FEATURE_MARKERS = ("odds", "dividend", "market", "배당")

# 공식 능력 배정의 대리변수까지 제거하는 진단용 프로필. 기본 운영 후보는
# 부담중량을 실제 물리적 경주 조건으로 남기는 ability_v2를 사용한다.
STRICT_PROXY_FEATURES = frozenset(
    {
        "carried_weight_kg",
        "carried_weight_rel",
        "carried_weight_kg_race_z",
        "carried_weight_kg_race_rank",
        "load_ratio_pct",
        "burden_type",
        "burden_type_clean",
        "grade_mix",
        "grade_tier",
        "grade_is_open",
        "grade_system",
    }
)

# 트리 모델이 원변수로 직접 상호작용을 학습할 수 있는데도 조합 문자열을 함께 주면
# 현재 표본에서는 과적합이 늘었다. 수치형 경합 강도와 gate_band는 남긴다.
REDUNDANT_INTERACTION_KEYS = frozenset(
    {
        "course_distance_key",
        "course_distance_gate_band",
        "style_pace_key",
        "style_gate_key",
    }
)

# 계층형 게이트 prior는 각각 단독/부분 ablation이 가능하도록 별도 계약으로 둔다.
# V6 탐색에서 거리+계절 두 지수만 최근 valid의 win LL을 개선했고, 주로·세부조건·
# 표본량 피처는 개선을 상쇄했다. 기존 core 계약은 모든 실험 피처를 계속 제외한다.
EXPERIMENTAL_GATE_BIAS_FEATURES = frozenset(
    {
        "gate_top3_index_course_distance",
        "gate_top3_index_season",
        "gate_top3_index_going",
        "gate_top3_index_context",
        "gate_context_expected_slots",
        "gate_context_reliability",
        "gate_early_speed_course",
        "gate_early_speed_distance",
        "gate_early_speed_context",
        "gate_early_speed_evidence",
        "gate_early_speed_reliability",
        "gate_early_speed_front_fit",
    }
)
EARLY_GATE_SPEED_FEATURES = frozenset(
    {
        "gate_early_speed_course",
        "gate_early_speed_distance",
        "gate_early_speed_context",
        "gate_early_speed_evidence",
        "gate_early_speed_reliability",
        "gate_early_speed_front_fit",
    }
)
GATE_DISTANCE_SEASON_FEATURES = frozenset(
    {
        "gate_top3_index_course_distance",
        "gate_top3_index_season",
    }
)

# RaceFit V1 검증에서 구간 에너지 변수는 미래 연도 성능을 개선했지만, 아래의
# 잠재 컨디션 합성치는 개선을 상쇄했다. 데이터셋에는 계속 보존하되 운영 후보의
# 기본 학습 입력에서는 제외하여 재현 가능한 ablation 계약으로 고정한다.
EXPERIMENTAL_CONDITION_STATE_FEATURES = frozenset(
    {
        "condition_speed_delta",
        "condition_form_delta",
        "condition_weight_z",
        "condition_state",
        "condition_evidence",
        "condition_uncertainty",
    }
)

EXPERIMENTAL_DYNAMIC_STATE_FEATURES = frozenset(
    {
        "dynamic_ability_state",
        "dynamic_condition_state",
        "dynamic_condition_sd",
        "dynamic_condition_z",
        "dynamic_total_state",
        "dynamic_state_observations",
        "dynamic_days_since_observation",
    }
)

LIVE_BIAS_FEATURES = frozenset(
    {
        "live_bias_races",
        "live_bias_reliability",
        "live_track_speed_variant",
        "live_front_bias",
        "live_inner_bias",
        "live_style_fit",
        "live_gate_fit",
        "live_finish_energy_fit",
    }
)

EXPERIMENTAL_SAND_RESPONSE_FEATURES = frozenset(
    {
        "sand_incident_count_prior",
        "sand_incident_count_365d",
        "sand_days_since_incident",
        "sand_sensitivity_state",
        "sand_recovery_evidence",
        "sand_recovery_score",
        "sand_recovered_flag",
        "sand_exposure_risk",
        "sand_expected_penalty",
        "sand_state_reliability",
    }
)
SAND_STATE_CORE_FEATURES = frozenset(
    {
        "sand_incident_count_prior",
        "sand_incident_count_365d",
        "sand_days_since_incident",
        "sand_sensitivity_state",
        "sand_exposure_risk",
    }
)
SAND_EVENT_FEATURES = frozenset(
    {
        "sand_incident_count_prior",
        "sand_incident_count_365d",
        "sand_days_since_incident",
        "sand_exposure_risk",
    }
)

# 직전 출전 이후의 기수 조교·교정심사·재갈 변경을 연결한 신규 실험군이다.
# 기존 프로필 재현성을 위해 V6 후보 외 모든 비-legacy 프로필에서는 차단한다.
EXPERIMENTAL_REMEDIATION_FEATURES = frozenset(
    {
        "current_jockey_train_n_28d",
        "current_jockey_train_duration_28d",
        "current_jockey_train_gallop_28d",
        "current_jockey_train_2plus_28d",
        "jockey_changed_from_last_start",
        "remedial_trial_passed_since_start",
        "remedial_trial_winner_since_start",
        "remedial_trial_current_jockey",
        "remedial_trial_current_jockey_winner",
        "remedial_trial_new_jockey_winner",
        "remedial_trial_finish_percentile",
        "bit_changed_from_last_start",
        "remedial_trial_bit_changed",
    }
)
JOCKEY_TRAINING_FEATURES = frozenset(
    {
        "current_jockey_train_n_28d",
        "current_jockey_train_duration_28d",
        "current_jockey_train_gallop_28d",
        "current_jockey_train_2plus_28d",
        "jockey_changed_from_last_start",
    }
)
REMEDIAL_TRIAL_FEATURES = frozenset(
    {
        "jockey_changed_from_last_start",
        "remedial_trial_passed_since_start",
        "remedial_trial_winner_since_start",
        "remedial_trial_current_jockey",
        "remedial_trial_current_jockey_winner",
        "remedial_trial_new_jockey_winner",
        "remedial_trial_finish_percentile",
    }
)


@dataclass(frozen=True)
class ModelProfile:
    name: str
    description: str
    excluded_features: frozenset[str]
    forbid_market: bool = True


PROFILES: dict[str, ModelProfile] = {
    "legacy_all": ModelProfile(
        name="legacy_all",
        description="기존 manifest feature 전체(과거 실험 재현용)",
        excluded_features=frozenset(),
        forbid_market=False,
    ),
    "ability_v2": ModelProfile(
        name="ability_v2",
        description="배당·공식 레이팅 제외, 부담중량·등급은 실제 경주 조건으로 유지",
        excluded_features=RATING_FEATURES,
    ),
    "ability_v2_strict": ModelProfile(
        name="ability_v2_strict",
        description="배당·레이팅과 공식 능력 배정 대리변수까지 제외한 진단형",
        excluded_features=RATING_FEATURES | STRICT_PROXY_FEATURES,
    ),
    "ability_v2_core": ModelProfile(
        name="ability_v2_core",
        description=(
            "엄격형에서 검증상 중복·과적합을 보인 조합 문자열을 추가 제외한 2차 핵심 능력모델"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
    "ability_v2_gate": ModelProfile(
        name="ability_v2_gate",
        description=("2차 핵심 능력모델에 누수 없는 거리·계절 게이트 지수만 추가한 V6 후보"),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | (EXPERIMENTAL_GATE_BIAS_FEATURES - GATE_DISTANCE_SEASON_FEATURES)
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
    "racefit_v1_core": ModelProfile(
        name="racefit_v1_core",
        description=(
            "ability_v2_core에 누수 없는 구간 에너지 변수를 추가하고 "
            "미검증 잠재 컨디션 합성치는 제외한 RaceFit V1 운영 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
    "racefit_v4_gate_pace": ModelProfile(
        name="racefit_v4_gate_pace",
        description=(
            "RaceFit V1 핵심 입력에 과거 S1F로 추정한 거리·출전두수별 "
            "게이트 초반속도 효과를 허용한 2단계 전개 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | (EXPERIMENTAL_GATE_BIAS_FEATURES - EARLY_GATE_SPEED_FEATURES)
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
    "racefit_v5_sand": ModelProfile(
        name="racefit_v5_sand",
        description=(
            "RaceFit V1 핵심 입력에 시간감쇠와 후속 정상노출 회복을 반영한 "
            "말별 모래 민감도만 허용한 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
        ),
    ),
    "racefit_v5_sand_event": ModelProfile(
        name="racefit_v5_sand_event",
        description="명시적 모래 사건·최근성·이번 경주 노출위험만 허용한 안정형 축마 후보",
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | (EXPERIMENTAL_SAND_RESPONSE_FEATURES - SAND_EVENT_FEATURES)
        ),
    ),
    "racefit_v6_remediation": ModelProfile(
        name="racefit_v6_remediation",
        description=(
            "RaceFit V5 안정형에 이번 기수 직접 조교와 직전 출전 이후 "
            "교정 주행심사·재갈 변경 신호를 추가한 검증 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | (EXPERIMENTAL_SAND_RESPONSE_FEATURES - SAND_EVENT_FEATURES)
        ),
    ),
    "racefit_v6_jockey_training": ModelProfile(
        name="racefit_v6_jockey_training",
        description="V5 안정형에 이번 기수 직접 조교와 직전 기수 변경만 추가한 소거실험",
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | (EXPERIMENTAL_SAND_RESPONSE_FEATURES - SAND_EVENT_FEATURES)
            | (EXPERIMENTAL_REMEDIATION_FEATURES - JOCKEY_TRAINING_FEATURES)
        ),
    ),
    "racefit_v6_remedial_trial": ModelProfile(
        name="racefit_v6_remedial_trial",
        description="V5 안정형에 직전 출전 이후 교정 주행심사 신호만 추가한 소거실험",
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | (EXPERIMENTAL_SAND_RESPONSE_FEATURES - SAND_EVENT_FEATURES)
            | (EXPERIMENTAL_REMEDIATION_FEATURES - REMEDIAL_TRIAL_FEATURES)
        ),
    ),
    "racefit_v5_sand_state": ModelProfile(
        name="racefit_v5_sand_state",
        description=(
            "모래 사건·경과일·노출위험과 후속 정상노출로 낮아지는 민감도 상태만 "
            "허용한 안정형 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | (EXPERIMENTAL_SAND_RESPONSE_FEATURES - SAND_STATE_CORE_FEATURES)
        ),
    ),
    "racefit_v5_sand_gate_pace": ModelProfile(
        name="racefit_v5_sand_gate_pace",
        description="V4 게이트 전개에 시간가변 모래 민감도·회복 상태를 결합한 후보",
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | (EXPERIMENTAL_GATE_BIAS_FEATURES - EARLY_GATE_SPEED_FEATURES)
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
        ),
    ),
    "racefit_v2_core": ModelProfile(
        name="racefit_v2_core",
        description=(
            "RaceFit V1 에너지 계약에 동적 Kalman 상태와 예측시각 제한 당일 편향을 "
            "허용한 V2 후보"
        ),
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | EXPERIMENTAL_DYNAMIC_STATE_FEATURES
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
    "racefit_v2_no_live": ModelProfile(
        name="racefit_v2_no_live",
        description="RaceFit V2 운영 후보에서 당일 편향까지 제외한 paired-ablation 기준",
        excluded_features=(
            RATING_FEATURES
            | STRICT_PROXY_FEATURES
            | REDUNDANT_INTERACTION_KEYS
            | EXPERIMENTAL_GATE_BIAS_FEATURES
            | EXPERIMENTAL_CONDITION_STATE_FEATURES
            | EXPERIMENTAL_DYNAMIC_STATE_FEATURES
            | LIVE_BIAS_FEATURES
            | EXPERIMENTAL_SAND_RESPONSE_FEATURES
        ),
    ),
}


def select_profile_features(feature_names: list[str], profile_name: str) -> list[str]:
    """manifest feature에서 프로필 허용 목록을 만들고 금지 항목을 검증한다."""
    try:
        profile = PROFILES[profile_name]
    except KeyError as exc:
        choices = ", ".join(PROFILES)
        raise ModelProfileError(f"알 수 없는 모델 프로필: {profile_name}. 지원: {choices}") from exc

    excluded = profile.excluded_features
    if profile_name not in {
        "legacy_all",
        "racefit_v6_remediation",
        "racefit_v6_jockey_training",
        "racefit_v6_remedial_trial",
    }:
        excluded = excluded | EXPERIMENTAL_REMEDIATION_FEATURES
    selected = [
        name
        for name in feature_names
        if name not in excluded
        and not (profile_name != "legacy_all" and name.lower().startswith("rating"))
    ]
    if profile.forbid_market:
        leaked = [
            name
            for name in selected
            if any(marker in name.lower() for marker in MARKET_FEATURE_MARKERS)
        ]
        if leaked:
            raise ModelProfileError(
                "능력모델에 시장/배당 feature가 포함되었습니다: " + ", ".join(leaked)
            )

    forbidden = sorted(set(selected) & RATING_FEATURES)
    if profile_name != "legacy_all" and forbidden:
        raise ModelProfileError("레이팅 feature 제거 실패: " + ", ".join(forbidden))
    if not selected:
        raise ModelProfileError(f"프로필 '{profile_name}' 적용 후 feature가 없습니다.")
    return selected
