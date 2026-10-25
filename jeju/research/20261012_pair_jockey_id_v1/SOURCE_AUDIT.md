# 제주 pair jockey-ID source audit

상태: read-only cached source, official event ID, fold roster와 H1 category 지원을 확인했다. [label-free preflight](outputs/SOURCE_PREFLIGHT.json)는 finish labels와 성과 지표를 읽지 않았다. 네트워크 접속이나 DB 조회도 없었다.

기수 event snapshot은 이전 [jockey effects source audit](../20261009_jockey_effects_v1/SOURCE_AUDIT.md)에 기록된 로컬 [`starts.csv`](../20261009_jockey_effects_v1/input01/starts.csv)와 source manifest를 그대로 쓴다. 캐시는 52,155 출전·5,206경주, 2017-01-13~2026-09-19, 공식 기수 ID 40개다. `api_record_id`를 기준으로 frozen STYLE6 runner roster를 연결하고 race ID·horse ID·날짜를 대조한다. 이름으로 ID를 추정하지 않고 숫자형 ID 값은 feature로 사용하지 않는다.

| evaluation fold | H1 출전/경주/일 | H1 ID | ID별 최소~최대 H1 출전 | H1 범위 | H2 unknown | evaluation unknown |
|---:|---:|---:|---:|---|---:|---:|
| 2024 | 21,861 / 2,147 / 361 | 39 | 52~1,295 | 2019-01-11~2023-06-24 | 0 / 3,327 | 0 / 6,329 |
| 2025 | 28,522 / 2,818 / 462 | 39 | 52~1,768 | 2019-01-11~2024-06-29 | 0 / 3,085 | 0 / 6,410 |
| 2026 | 34,845 / 3,458 / 560 | 39 | 52~2,114 | 2019-01-11~2025-06-28 | 0 / 3,172 | 0 / 4,673 |

각 fold의 ID vocabulary는 그 fold H1 rows에서만 생성했다. 동일한 39개 ID가 각 fold에 관측됐고 모든 ID는 적어도 52 eligible starts를 지원하므로 pooling은 하지 않는다. H2/evaluation에서 unknown ID가 없었지만 helper는 H1 vocabulary 밖의 기수에 대해 categorical runner contribution을 정확히 0으로 만든다.

범주 moments는 각 H1 경주 안의 unordered pair를 균등하게 평균한 뒤 경주를 균등 평균한다. ID `r`별 `u_r`은 pair에 속한 해당 ID runner 수, `pi_r=E_H1[u_r]/2`, `sigma_r=sd_H1(u_r-E_H1[u_r])`다. 분산 구현의 closed form `sum(u_r²)=c*n+c²−2c`는 direct pair enumeration과 세 fold 모두 일치했다. `pi` 합은 1에서 2e-14 이내였으며 모든 `sigma`가 양수이고 fold별 최소는 0.0550~0.0697이다.

Source join은 캐시의 공식 event ID를 사용하고 이전 audit의 `api_record_id` cross-check를 상속한다. 다만 출전 결과의 최초 게시 timestamp와 당시 기수배정 공개시각은 보유하지 않아, `T−2` 과거 결과 cutoff와 현재 event ID snapshot의 실제 공개 가능 여부는 확정되지 않는다. Cohort는 저장된 정상완주 완전 편성이라 과거 eligible starts가 전체 현실 기승 수는 아니다. 제외 말 3005648, 400m 제외, 경주 상한 2026-09-19 규칙을 상속한다. 평가 1,779경주·269일은 과거 반복 개발 구간으로 independent future holdout이 아니다.

Source hashes, split inventory, H1 vocabulary·support·moments는 [source preflight JSON](outputs/SOURCE_PREFLIGHT.json)에 고정되어 있다. 새 후보는 F1_STYLE6 frozen runner scores와 pre-existing 21-column rolling candidate inputs를 그대로 사용한다. 기존 점수 provider, rolling scalar code, saved baseline coefficients, date bootstrap schedule은 후속 receipt와 artifact manifest에서 해시로 추적한다.

