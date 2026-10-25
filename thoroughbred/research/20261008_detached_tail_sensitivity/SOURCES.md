# 결승 이탈 후미 연구의 자료와 근거

2026-10-08. 로컬 고정 자료를 읽기 전용으로 사용했다. 입력 SHA256은 [summary.json](outputs/summary.json)에 보존한다.

- [완전한 경주 명단](../20261002_gate_lateral_bias/outputs/runners.parquet):151,115출전·13,928경주, 서울·부산. 결승 시간차·중앙값·MAD와 원래 출전 두수 계산용.
- [구간·말 상태 결합](../20261007_sex_ability_gap/outputs/population.parquet):151,074출전. 출발200m·마지막600m·마지막200m·전체시간·등급·함수율·월·말 상태 통제.
- [기존4MAD 표식](../20261008_record_normalization_seconds/outputs/runner_normalization_candidates.parquet):기존 전체기록 이상치 기준을 보존했다. 경주 내 이탈 후미 표식과 별개의 기준이다.
- [직전 구간 모형](../20261008_section_normalization_candidate_v1/analyze.py), [기본 게이트 모형](../20261008_gate_lateral_seconds/analyze.py), [정확 함수율·월 설계](../20261008_record_normalization_seconds/analyze.py):외부 모형을 새로 설치하지 않고 고정 설계·말/경주 고정효과·군집 분산을 재사용했다. 과거 모형의 쓰기 함수는 호출하지 않았다.
- [한국마사회 부산경남 경마가이드](https://park.kra.co.kr/race_guide_.pdf):검색 색인에 제공된 안내 본문에서1마신0.18초·6마신약1초를 확인했다. 2026-10-08 직접 열기는 오류 페이지로 이동해 PDF 원본은 보관하지 못했다.
- [한국마사회 속도지수 설명](https://studbook.kra.co.kr/html/info/ind/s_rc_age_idx.jsp?mabun=0040561):검색 도구가 제공한 해당 페이지 본문에는0.2초(1마신)마다 속도지수1을 가감한다고 명시한다. 직접 재열기는 캐시 오류였다. 지수의 단순 환산 기준과 실제 결승 시간차를 구분한다.
- [BHA 착차 계산 안내](https://www.britishhorseracing.com/faqs/how-does-the-judge-calculate-the-distances/):직접 본문을 확인했다. 평지 경주의 초당 마신 환산은 주로에 따라5~6으로 달라진다. 영국 수치를 한국의 고정 환산으로 적용하지 않았다.

마신 안내는 사용자의0.5초 가정을 점검하는 근거이고, 분석의 제외 기준은 실제 관측 시간차다. 2.5배수·시간/비율 문턱은 분석 전 [계획](PLAN.md)에 고정한 정책 후보다. 공식적인 이탈 후미 기준이나 예측 최적값이라고 주장하지 않는다. 웹 게시용 데이터는 로컬 JSON이며 배포하지 않았다.
