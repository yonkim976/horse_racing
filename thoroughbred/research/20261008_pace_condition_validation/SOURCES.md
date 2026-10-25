# 출처와 재현

입력은 기존 보존 자산을 읽기 전용으로 재사용했다. 원천 API4_3의 track는 실제 경주 함수율 확인용이고 사전 예측에 사용하지 않았다. 원문 말번호·날짜·경주번호·게이트·거리·지역을 검증했다. 파생 위치 정의와 이력 계약은28C/28D를 따른다.

| 경로 | 바이트 | SHA-256 |
|---|---:|---|
| [thoroughbred/research/20261008_bilateral_field_pace/outputs/early_predictions.parquet](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261008_bilateral_field_pace/outputs/early_predictions.parquet) | 6534189 | 06821757911a4d527d333defae5dca45ebf055a8d074ef17247056cff8b96628 |
| [thoroughbred/research/20261008_field_pace_prediction/outputs/early_predictions.parquet](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261008_field_pace_prediction/outputs/early_predictions.parquet) | 7065737 | dc5ea85290b5b831c2cf6ab3b6bdfb1e785ac0920caa72fa32fd46204f709885 |
| [thoroughbred/research/20261008_field_pace_prediction/outputs/feature_context.parquet](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261008_field_pace_prediction/outputs/feature_context.parquet) | 58823119 | c5c89aae95bc5489158289790fe9b0fac8279ea10ec2bafc2ff1de9d59ed4857 |
| [thoroughbred/research/20261004_pace_finish_stack_v1/README.md](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261004_pace_finish_stack_v1/README.md) | 10885 | d7adca727d989b24da8b4a7c33c85f418de0370c5ab6cf2ec42fa92366111d53 |
| [thoroughbred/research/20261003_pace_gate_moisture_v2/README.md](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261003_pace_gate_moisture_v2/README.md) | 8467 | 16f9edac5e6e3fe5f409f8a5e15c46ace7fa6f4553e7f93fa828d999e1401f9d |
| [thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2024/meet_1.json.gz](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2024/meet_1.json.gz) | 1441741 | 57d3d689be03d2b6b02db533746d3c236a125fd532b3ffe41a06cc4352a0e4eb |
| [thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2024/meet_3.json.gz](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2024/meet_3.json.gz) | 1117076 | a97d361760bd9f0f22ca0dc98204efb20e6ed90485bed643e82269ee72d85a4e |
| [thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2025/meet_1.json.gz](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2025/meet_1.json.gz) | 1463206 | 9c83304b29faa1cb1cb90d1e44a027ad3046ac071b4120bf3f6ebb7ad38382fb |
| [thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2025/meet_3.json.gz](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2025/meet_3.json.gz) | 1136732 | 5fc2fde4a6c91da4037ba7db6fbc874ea7ddf6c346d5d4ad9c09c89e311aa3dd |

구간 정의: S1F는 출발200m, G3F/G1F는 결승 전600/200m. 막판 겹치는 구간을 독립 능력으로 가산하지 않는다. 이번 목표는 S1F 통과조다. 함수율 층화는 실제 주로에서의 오차 진단이며 현재 주로를 넣은 비교 학습이 아니다.

코드: analyze.py(고정 예측 분석), verify.py(독립 검증), publish.py(보고서/그림), register.py(중앙 목록), record_inventory.py(자기 포함 용량).
