# 연령 곡선과 출전 중단의 출처

## 고정 로컬 자료

- [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet):151,074행. 출전 당시 나이·성별·기록·함수율·등급·ID와 원문 포인터를 재사용한다. 기존 공통 백분위 점수는 사용하지 않는다.
- [코어DB](../../data/core_api_2010_20260929_v1/thoroughbred_core.duckdb):confirmed_runners와horse_profile_snapshot_membership를읽기전용조회. 실제출발추적과생일대조에만사용하며현재프로필성별·등급을과거에덮어쓰지않는다.
- [원천감사](outputs/source_audit.json):모집단SHA-256,코어추출해시,DB크기·수정시각,연령/생일일치,원시착순코드별수를보존한다.코어에는확정퇴사일·불용사유열이없고현재API8_2active/inactive요청범위는퇴사정답이아니다.
- [출전 추적 원장](outputs/observed_starts.parquet) · [연말 기준 원장](outputs/annual_followup_landmarks.parquet) · [정확 매칭 셀](outputs/matched_transition_cells.parquet).

## 외부 1차 자료

2026년10월7일조회했다. 외부자료의 해외 효과 크기를 한국 경마 보정값으로 가져오지 않는다.

- [Gramm와Marksteiner 2010, The Effect of Age on Thoroughbred Racing Performance](https://www.jstage.jst.go.jp/article/jes/21/4/21_4_73/_article/-char/en):미국수컷274두의Beyer속도지수로추정한모형에서평균정점4.45세를보고한다.별도집단·척도·모형의결과여서국내4.45세정점의증거가아니다.
- [2021, Drivers of exit and outcomes for Thoroughbred racehorses participating in the 2017–2018 Australian racing season](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0257581):비활동말의후속상태를조사해은퇴·사망·휴양등을구분한다.출전부재를모두은퇴로정의하지않는방법적근거로참고한다.국내중단사유를입증하지않는다.
- [한국마사회 경주마 상세정보API8_2](https://www.data.go.kr/data/15058115/openapi.do):생일등프로필정의의공식경로다.최신성적·상태의과거적용을허용하는근거가아니다.
- [한국마사회 마필종합 상세정보 API42](https://www.data.go.kr/data/15057985/openapi.do):공식설명에등록·불용·입사·퇴사·최종휴양정보가포함된다.이번에는명세존재만확인했고원문대량수집·퇴사이력검증은하지않았다.입퇴사와영구은퇴의의미를대조하는후속자료다.

## 계산과 한계

기상·월효과는회귀통제또는정확매칭으로맞췄다.게이트초단위보정·풍향·풍속·주로빠르기는넣지않았다.새연령보정계수나미관측은퇴후기록을만들지않았다.자세한식별·선택·시간순적용한계는[계획](PLAN.md)과[보고서](README.md)에보존했다.
