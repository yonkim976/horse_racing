# 입력별 계약

22개기준입력은원본변경없이유지한다.나머지는현재착순·현재구간·기수·조교사·심판·직접게이트를사용하지않는다.아래구간은지원되는과거기록의환경보정값이다.평균은최근실제3슬롯내유효기록,유효수는최근실제5슬롯이다.결측행을건너뛰어5개를채우지않는다.

| 이름 | 의미 |
| --- | --- |
| section_last600_mean3 / section_late_mean3 | 과거 G3F600m / G1F200m 최근3전 평균초,낮을수록빠름 |
| section_last600_n5 / section_late_n5 | 각구간최근5슬롯유효관측수 |
| last600_relative_adv / late_relative_adv | 현재편성의다른말과거구간평균−자기과거구간평균,양수면빠름;상대관측없으면결측 |
| last600_percentile / late_percentile | 편성내과거시간역순평균순위/유효말수,높을수록빠름;동률평균순위 |
| style_recovery_mean5 / style_recovery_n5 | 과거후반회복표식의최근5전평균/관측수.남은600m상대순위>=.5이면서결승까지상대순위회복>=.25 |
| section_early_mean3 / section_early_n5 | 과거 S1F200m 최근3평균/최근5전유효수 |
| style_role0_rate5 / style_role_n5 | 통과조기준과거선행빈도/최근5전유효각질관측수 |
| field_other_lead_mass | 자기제외,유효각질3전이상다른말의과거선행빈도합;아무상대관측없으면결측 |
| field_strong_front_n | 위상대중과거선행빈도>=.4말수;상대관측없으면결측 |
| field_early_faster_n | 자기보다과거S1F평균이빠른상대수;자기/상대구간각유효3전이상,자기미지원또는상대관측없으면결측 |
| field_early_support | 자기제외S1F유효3전이상관측말수/(두수−1);미지원상대비율을표시 |
| last600_x_lead_pressure / late_x_lead_pressure | 종반상대차×(field_other_lead_mass/(두수−1)) |
| recovery_x_lead_pressure | 과거회복빈도×위선행밀도 |

600m와200m는겹치는구간이며점수를독립가산하지않는다.선행밀도는동일편성자료에대한대리변수로당일경합의도나검증된실제선행수확률이아니다.모든입력전체목록은 [feature_contract.json](outputs/feature_contract.json)에보존했다.
