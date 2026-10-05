# v9 결과 읽기

REPORT.md: 최종 검증 결과 및 선택. WEIGHT_CONTEXT_EXAMPLES.md: 실제 과거 말별 체중 설명 사례.
selection.json: 전체/서울/부산 연구 선택. candidate_features.json: 정확한 입력 변수.
comparison.csv / venue_comparison.csv / annual_metrics.csv: 동일경주 전체·장소·연도 비교.
descriptive_next_race_cohorts.csv: 실제 출전마의 다음 경주 입상 비율에 대한 기술적 집계; 모델 적중률/인과 효과가 아니다.
latest_historical_weight_context.parquet: 장소별 가장 최근 보존 역사 출마표에서 사용 가능했던 과거체중 설명. 당일 실시간 예측이 아니다.

새 빈 연구 폴더에 코드만 복사해 prepare → pytest → protocol_lock 생성 → run_study → verify/summarize → explain → report 순서로 재현한다. 봉인된 폴더에서 결과 생성기를 재실행하지 않는다. 읽기 전용 무결성 검사는 integrity.py verify.

기존110변수 대조, 개인/거리15변수 추가, 기간/기록15변수 추가, 두 그룹30변수 추가. 실제 휴양과 체중관측간격을 구분하며, 기준 체중에 마지막 체중관측의 결과를 포함하지 않는다. 좋은 기록과 연관된 참고범위이지 생리학적 최적 체중이나 의학적 컨디션 판정이 아니다.

본 디렉터리는 연구 아티팩트이며 운영 DB/모델/registry는 갱신하지 않는다. 운영 예측 게시·모델 승격은 별도 명시적 작업이다.
