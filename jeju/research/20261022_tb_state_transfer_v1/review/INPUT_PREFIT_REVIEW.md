# Prefit 독립 검토

**판정: PASS — 검토한 해시 묶음에 한해 사전 적합 게이트를 통과했습니다.** 이 리뷰는 단 한 번의 fit/evaluation을 대신 승인하지 않습니다. supervisor는 `source_preflight.json`과 이 코드 묶음에 결합된 단일 실행 승인 receipt를 별도로 확인해야 합니다. 본 검토에서는 모델을 학습하거나 실제 결과 지표를 계산하지 않았습니다.

## 고정본과 확인

- `experiment/state_transfer.py`: SHA-256 `963b2bcb574f3d49e539ae4e944a8a2f8f9bd769568d83018c2dcbcd2fa0623c`
- `experiment/test_state_transfer.py`: SHA-256 `3769231f0e724cd0eeebb79964a5a34ac791e88cdf41e411c46ed2194d086bcf`
- `experiment/outputs/source_preflight.json`: SHA-256 `3dc10aea8b1ce689be536cb2cbc5a7d8d80d8e03313982d8998f9d7a704eb270`; status `PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS`이며 fitted, probabilities, outcome metrics 모두 false입니다.
- 코드 번들 SHA-256: `dd04eb410f32733bebcd95bec87f10066a5b869ef56e621459b32b828d21b47b` (preflight 기록과 일치)
- `inputs/input_manifest.json`: SHA-256 `7561d6f91d5a1a5059add0741d912e33896b04810a19dd1dab955b0ebd229f5e`
- 생성 feature/lineage SHA-256: `ac956c959ce853aa129c738113c598d4ecc968d88dc1306c0f5fa5f4712a78e7` / `62c4c0896b3a0a4c44b64e56f53ad1ad1b862953c6ded618892e1861624f5dd0`

독립적인 읽기 전용 확인에서 input manifest가 세 산출물의 SHA, 크기, 행수 및 열 순서와 일치했고 두 Parquet 파일 모두 ZSTD 압축을 사용했습니다. manifest에 고정된 원천 8개도 경로별 SHA와 바이트 수가 맞았습니다. supervisor 검증 receipt는 52,155 target 행 × 10 상태열 재계산 최대오차 `1.34e−15`, 전체 lineage cutoff/history ID/date/update count 일치, 7,066개 적격 경주의 DB roster 일치를 기록합니다. DB는 읽기 전용 대조였습니다.

최종 코드는 T−2 및 target/lineage exact key 검증, F1 feature 원천 고정 해시, 정상 완전 rank 이력 조건, 세 연도 동일 cohort, PLC 실제 5–7두 미확정 격리, 7승식 공통 full-field PL `Q`, R의 저장 WIN Top3 선택 1,023건 재현 및 R 손실 재현을 검사합니다. paired 평가와 사전 gate는 고정 계약과 일치합니다. 출력은 `experiment/` 아래 exclusive-create 경로로 제한됩니다. 마지막 코드 변경에서 preflight SHA를 승인 receipt에 결합하되 자기 자신을 preflight 내부 해시와 비교하지 않도록 고쳤습니다. 승인 없이는 run이 실행되지 않습니다.

synthetic 전용 검사는 9개 체크 PASS, `fit_calls=0`, `actual_probabilities_or_outcomes=false`였습니다. 실행은 `PYTHONDONTWRITEBYTECODE=1`로 했고 신규 bytecode 산출물은 없었습니다.

## 남는 해석 한계

기록 공개시각과 당시 명단은 확인되지 않았습니다. 따라서 T−2는 공식 공개 시점의 가용성 증거가 아니며, target 편성은 회고적으로 관측한 완주 출전 roster입니다. 상태는 정상 완주·완전한 1..N 순위·N≥4인 과거 경주만 사용하므로 비완주 위험을 모델링하지 않습니다. SD 값은 근사 필터 covariance 특징이며 보정된 사후 불확실성이 아닙니다. 2024–2026은 재사용 개발 평가이므로 통과하더라도 독립 미래 성능이나 운영 승격 근거로 볼 수 없습니다. 이 한계는 계약과 source audit에 기록되어 있어 사전 실행 blocker는 아닙니다.

검토 중 발견한 이전 코드 스냅샷의 사전 승인 self-hash 비교 오류는 최종 고정본에서 수정되고 preflight 재생성으로 확인되었습니다. 이 보고서 이후 코드·입력·preflight가 바뀌면 현재 PASS는 무효이며 새로운 해시 결합 검토가 필요합니다.
