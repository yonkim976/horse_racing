# 감독관 학습 전 검토

원천·시간·코드 검토 PASS. 사용자 승인 범위에서 새 B의 초기학습 3회와 refit 3회, L/B 이전연도 OOS 보정 6회만 실행한다. 운영 변경은 없다.

- S와 동일 40개 입력, 범주 어휘·행 순서·전처리·분할·LightGBM 설정·1/N 가중치를 대조했다. 달라지는 학습 정답은 정확한 Bottom3다.
- 원천 감사와 최신 정적 리뷰의 code/contract/source hashes를 별도 계산으로 확인했다. 정상 완주 1..N 순위 코호트, T−2 포함 경계와 provider-year별 calibration/evaluation 역할을 확인했다.
- 공통 exact3 unordered subset 분포, previous-year set-NLL 보정, race-equal proper losses, 고정 날짜 bootstrap 및 별도 예측/제외 보호 gate가 계약과 일치한다.
- 전체 set 확률 누적을 fixed-bin streaming 통계로 바꾸고, 모델 경로·전체 코호트 명칭·환경 버전을 수정했다. 저장 JSON과 fresh 구조의 어휘 연도 키가 달라지는 실행 차단 문제도 학습 전에 수정·재검증했다. 수정은 결과를 보기 전에 이루어졌다.
- 감독관의 별도 수식 synthetic 검사가 통과했고, 기존 연구·운영 286개 파일 보존을 확인했다. 독립 결과 검산 코드를 준비했다.
- 2024–2026 반복 평가, 정상완주 조건부 표본, 공개시각 및 구매 전 명단 미확인 한계를 유지한다. 하위 집합 분포를 상위 공동 착순·승식 분포로 부르지 않는다.

EXECUTION_APPROVAL.json은 계약·최종 코드·원천을 결합한 내부 실행 승인이다. 결과 채택 승인이 아니다.
