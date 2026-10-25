# 입력 계약

열 수는 파생값을 포함한 수이며 독립 원천 수가 아니다. raw_sections와adjusted_sections는같은 구간 요약의값만 다르다.

| 후보 | 입력수 |
|---|---:|
|현재 월·게이트·부중|22|
|구간 원기록 추가|36|
|구간 보정 적용|36|
|회복·후퇴 이력 추가|53|
|상대 편성 추가|70|
|전개 예측값 추가|77|

## 최종77개 열

| 번호 | 입력 | 출처 |
|---:|---|---|
|1|`distance_m`|기존22|
|2|`grade`|기존22|
|3|`grade_kind`|기존22|
|4|`field_size`|기존22|
|5|`history_count`|기존22|
|6|`days_since_last`|기존22|
|7|`previous_age`|기존22|
|8|`previous_sex`|기존22|
|9|`moist_last_record_index`|기존22|
|10|`moist_last3_record_index_mean`|기존22|
|11|`moist_last5_record_index_best`|기존22|
|12|`moist_last5_record_index_count`|기존22|
|13|`profile_top2mean5`|기존22|
|14|`profile_previous3`|기존22|
|15|`profile_trend`|기존22|
|16|`profile_std5`|기존22|
|17|`profile_count3`|기존22|
|18|`profile_previous3_count`|기존22|
|19|`profile_valid5_support_fraction`|기존22|
|20|`previous_carried_weight`|기존22|
|21|`current_carried_weight`|기존22|
|22|`current_vs_previous_carried_weight`|기존22|
|23|`section_early_last`|과거 구간/거리|
|24|`section_early_mean3`|과거 구간/거리|
|25|`section_early_best5`|과거 구간/거리|
|26|`section_early_n5`|과거 구간/거리|
|27|`section_last600_last`|과거 구간/거리|
|28|`section_last600_mean3`|과거 구간/거리|
|29|`section_last600_best5`|과거 구간/거리|
|30|`section_last600_n5`|과거 구간/거리|
|31|`section_late_last`|과거 구간/거리|
|32|`section_late_mean3`|과거 구간/거리|
|33|`section_late_best5`|과거 구간/거리|
|34|`section_late_n5`|과거 구간/거리|
|35|`section_previous_distance`|과거 구간/거리|
|36|`section_same_distance_n5`|과거 구간/거리|
|37|`style_role0_rate5`|과거 통과조/회복·후퇴|
|38|`style_role1_rate5`|과거 통과조/회복·후퇴|
|39|`style_role2_rate5`|과거 통과조/회복·후퇴|
|40|`style_role3_rate5`|과거 통과조/회복·후퇴|
|41|`style_role_n5`|과거 통과조/회복·후퇴|
|42|`style_solo_mean5`|과거 통과조/회복·후퇴|
|43|`style_group_mean_relative_mean5`|과거 통과조/회복·후퇴|
|44|`style_middle_gain_mean5`|과거 통과조/회복·후퇴|
|45|`style_middle_gain_n5`|과거 통과조/회복·후퇴|
|46|`style_gain400_mean5`|과거 통과조/회복·후퇴|
|47|`style_gain400_n5`|과거 통과조/회복·후퇴|
|48|`style_gain200_mean5`|과거 통과조/회복·후퇴|
|49|`style_gain200_n5`|과거 통과조/회복·후퇴|
|50|`style_recovery_mean5`|과거 통과조/회복·후퇴|
|51|`style_recovery_n5`|과거 통과조/회복·후퇴|
|52|`style_fade_mean5`|과거 통과조/회복·후퇴|
|53|`style_fade_n5`|과거 통과조/회복·후퇴|
|54|`field_gate`|이번 상대/게이트|
|55|`field_gate_relative`|이번 상대/게이트|
|56|`field_other_section_early_mean3`|이번 상대/게이트|
|57|`field_support_section_early_mean3`|이번 상대/게이트|
|58|`field_gap_section_early_mean3`|이번 상대/게이트|
|59|`field_other_section_last600_mean3`|이번 상대/게이트|
|60|`field_support_section_last600_mean3`|이번 상대/게이트|
|61|`field_gap_section_last600_mean3`|이번 상대/게이트|
|62|`field_other_section_late_mean3`|이번 상대/게이트|
|63|`field_support_section_late_mean3`|이번 상대/게이트|
|64|`field_gap_section_late_mean3`|이번 상대/게이트|
|65|`field_other_style_role0_rate5`|이번 상대/게이트|
|66|`field_support_style_role0_rate5`|이번 상대/게이트|
|67|`field_other_style_recovery_mean5`|이번 상대/게이트|
|68|`field_support_style_recovery_mean5`|이번 상대/게이트|
|69|`field_faster_early_n`|이번 상대/게이트|
|70|`field_early_pair_n`|이번 상대/게이트|
|71|`pace_p0`|이전연도까지 학습한 보조예측|
|72|`pace_p1`|이전연도까지 학습한 보조예측|
|73|`pace_p2`|이전연도까지 학습한 보조예측|
|74|`pace_p3`|이전연도까지 학습한 보조예측|
|75|`pace_recovery`|이전연도까지 학습한 보조예측|
|76|`pace_fade`|이전연도까지 학습한 보조예측|
|77|`pace_supported`|이전연도까지 학습한 보조예측|
