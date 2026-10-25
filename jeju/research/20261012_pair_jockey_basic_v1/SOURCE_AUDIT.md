# 제주 직접 Top3 pair 기수 기본정보 입력 원천 감사

상태: 2026-10-12 read-only 원천·구조 감사. 새 pair feature를 만들거나 후보 결과를 계산하지 않았고, 모델 적합·예측을 실행하지 않았다. 새 산출물은 이 연구 폴더에만 둔다.

## 확인한 규칙과 범위

작업 시작 시 `jeju/AGENTS.md`, `docs/RESTART_PLAN_20260928.md`, `docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md`, `review_documents/README.md`, `research/RESEARCH_PUBLICATION_POLICY.md` 및 `~/.codex/skills/code-security/SKILL.md`를 읽었다. 제주 현지 자료의 공식 식별자·시점·제외·보존 기준과 완료 연구 발행 정책을 적용한다. 로컬 캐시만 읽었으며 DB·network를 열지 않았다.

기준 pair 연구는 [2026-10-11 H1 확장 연구](../20261011_pair_top3_oos_expansion_v1/README.md), [설계](../20261011_pair_top3_oos_expansion_v1/PLAN.md), [원천 감사](../20261011_pair_top3_oos_expansion_v1/SOURCE_AUDIT.md)다. 저장 F1_STYLE6 말 입력·점수, 평가 cohort 및 pair 참조는 이 결과에서 읽기 전용으로 가져온다. 고정 코호트는 2024-01-05~2026-09-19, 정상 완주 완전 편성 1,779경주·269경주일·17,412출전·76,848 unordered pair다. 2026년은 부분연도다.

## 기수 연결 원천

기존 기수 연구의 캐시 [`starts.csv`](../20261009_jockey_effects_v1/input01/starts.csv)는 출전마다 `api_record_id`, `race_id`, `horse_id`, 경주일·거리·편성 크기, 완주 순위와 사건 당시 `jockey_id`를 보존한다. 해당 연구의 [`source_manifest.json`](../20261009_jockey_effects_v1/input01/source_manifest.json)은 사건 결과 행과의 공식 join key `(api_record_id, horse_id, race_date, race_distance_m, jockey_id)`, 결과 payload SHA 52,155건 대조, DB read-only 조회 및 전후 DB SHA 동일을 기록한다. 이 연구는 그 저장 검증을 참조하며 DB 재조회·재검증을 수행하지 않았다. `api_record_id`가 현재 이벤트 기수를 연결하는 키다. 기수 이름은 표시에도 사용하지 않으며, 이름으로 ID를 추정하거나 ID의 숫자 순서를 수치로 사용하지 않는다.

새로 확인한 캐시 구조는 다음과 같다.

| 범위 | 출전 | 경주 | 경주일 | 날짜 범위 | 기수 ID |
|---|---:|---:|---:|---|---:|
| 기수 기본정보 원천 전체 | 52,155 | 5,206 | — | 2017-01-13~2026-09-19 | 40 |
| pair H1·H2 source years 2019–2025 | 38,017 | 3,783 | 608 | 2019-01-11~2025-12-27 | 39 |
| pair 평가 cohort 2024–2026-09-19 | 17,412 | 1,779 | 269 | 2024-01-05~2026-09-19 | 29 |

캐시의 `api_record_id`는 전체 52,155행에서 유일·nonnull이고, `jockey_id` 결측은 0행이며 6자리 숫자 형식 위반은 0행이다. 사용자 제외 말 `3005648`은 포함되지 않았다. 원천의 대상 거리는 800·900·1000·1110·1200·1300·1400·1610m이고 400m는 없다. 보유 자료는 선택된 정상완주 완전 편성 cohort다. 과거 기승수는 전체 실제 기승 횟수가 아니라 이 cohort에서 관측된 eligible starts 수로 설명해야 하며, 미완주·취소·제외 또는 저장 cohort 밖의 기승을 의미하지 않는다.

정확한 runner key와 source relationship을 추가로 확인하기 위해 STYLE6 frozen feature table의 `api_record_id`를 문자열로 정규화한 뒤 pair input years 2019–2025를 join했다. 38,017/38,017 runner key가 일치했고 race ID, horse ID, 날짜 불일치가 각각 0이었다. 평가연도도 17,412/17,412 key를 연결했으며 race ID·horse ID·날짜 불일치 0, 기수 ID 결측 0이었다. 매칭은 `api_record_id`만으로 수행했다. 문자열/정수 저장형 차이는 정규화만 했고 숫자 값 자체는 변환하지 않았다.

| 사용 파일 | 역할 | SHA-256 |
|---|---|---|
| `20261009_jockey_effects_v1/input01/starts.csv` | 사건 ID·기수 ID·과거 eligible starts 및 Top3 결과 캐시 | `78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a` |
| `20261009_jockey_effects_v1/input01/source_manifest.json` | 기존 원천·payload join 감사 기록 | `68e38ee6b2ec32040fa6a8a8fdce4039ece3f25e0869004d910c92a288f50bdc` |
| `20261010_style_history_ablation_v1/outputs/features.parquet` | frozen runner key, date, race, horse, field-size cohort | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| `20261011_pair_top3_oos_expansion_v1/outputs/evaluation_pair_predictions.parquet` | 고정 evaluation pair roster·참조 source | `f983d9c5dfa7c4d1129b407d5a3e367dc38e193c0c8fdbbaeff34d86b31af499` |

## 시간과 해석 제한

입력 후보는 같은 공식 기수 ID의 과거 시작 기록만 사용한다. 대상 경주일을 `T`라 할 때 과거 기록은 달력 기준 `race_date <= T−2일`이며, 최근 365일 창은 `((T−2일)−365일, T−2일]`로 정의한다. 해당 출전 자체 및 같은 날·직전 날 결과는 포함하지 않는다. 고정 과거 OOS H1은 2019년부터 시작하며 원천 캐시는 그보다 1년 이상 앞선 2017년부터 기록한다. 과거 결과 자료의 게시 timestamp가 저장되어 있지 않으므로 T−2 cutoff 이후 실제 게시시각까지 재생한 가용성 검증은 아니다. 현재 event의 기수 배정 역시 기존 연구와 마찬가지로 후향 사건 snapshot이 사전에 알려졌다고 두는 가정이다.

지난 365일 기승 표본은 평상시의 기수 능력, 배정된 말의 질, 거리·등급·편성, 정상 완주 cohort 선택을 함께 반영하는 설명용 최근 기록이다. 이를 순수 기수 능력·기수 변경 효과·전문 각질 또는 인과 효과로 해석할 수 없다. 현재 기수 효과를 말별 F1_STYLE6 점수나 말 점수 산식에 넣지 않는다. 이 연구는 두 말 pair 선택 단계에만 한 개 basic-information 입력을 더하는 제한 비교다.

## Source lock 전 확인

fit 전 source preflight는 사용 파일의 해시, `api_record_id` 유일성, race/horse/date 일치, event jockey ID 유무, history cutoff, H1/H2/evaluation roster counts, score provider role과 pair label arithmetic을 다시 확인해야 한다. 결과·모델 성능값은 source preflight에서 계산하지 않는다. 평가기간은 반복 개발에 사용된 과거 자료이므로 independent future holdout이 아니다. 중앙 결론 문서·등록부는 root의 후속 출판 절차로 관리한다.
