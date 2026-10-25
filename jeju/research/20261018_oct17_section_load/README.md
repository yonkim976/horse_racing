# 2026-10-17 제주 구간상세·통과조 적재 및 5R 거리 정정

측정 정의 후속 확인: [공식 제주 용어해설에서 1110m·1610m의 말별 S1F는 210m임을 확인했다](../20261018_s1f_measurement_official_review/README.md). 아래 API6 첫 110m 펄롱 구간과 말별 S1F는 서로 다른 측정이다. 이 후속 정의 확인으로 이 적용 원장이나 DB 시간값을 변경하지 않았다.

## 범위와 상태

**2026-10-18 실제 적재·독립 검증 완료.** 완료 원장은 `completion_receipt.json`이며 적용 전 백업, 적용·검증 원장과 현재 DB SHA를 연결한다. 이 문서는 원천 확인만 수행한 앞선 보고서와 구분한다.

- API6 7행 + API303 7행, 홈페이지 거리 검토 6행을 추가했다. 현재 API6 정규 적재는 **71경주**, 그중 1110m는 **19경주**다.
- 기존 **41개 테이블·2,792,617행의 모든 열과 기존 스키마**를 적용 전 백업과 대조해 보존을 확인했다. 시간·순위 정정, 충돌 보류, 기승자 보완도 기존 행 그대로다.
- 무결성 `ok`, 외래키 위반 0, 제외 말 3005648의 6개 활성 테이블 편입 0, 실제 적재기 롤백 재실행에서 14행 전부 재적재 방지, 독립 원문·거리 후검증 PASS.
- 현재 DB SHA-256: `940feb05de4b385e4e44c624644b955dc72b29852102a07a218a8786d6958f29`. `jeju/data/jeju_native_core.refresh_manifest.json`이 이번 적용 원장을 가리키며 해당 SHA·원장 해시를 재검증했다.

- 대상 DB: `jeju/data/jeju_native_core.sqlite3` (제주 연구용 SQLite).
- 대상: 2026-10-17 제주 1~7경주, 기존 출전 69행에 대응하는 경주 단위 API6 7행·API303 7행.
- 홈페이지: 공식 결과 7페이지와 말 ID·마번·착순 69두를 직접 대조했다.
- 구간별 시간·누적시간 39지점과 각 API의 제공 통과조 29지점이 홈페이지와 일치했다.
- 거리 지점은 33개 일치, 5R의 6개만 차이가 있다. 5R의 **경주거리 자체는 API·DB·홈페이지 모두 1110m**다.

## 저장과 조회 계약

| 내용 | DB 저장·조회 |
|---|---|
| API6 경주 단위 원문 | `api_records` + `refresh_section_records`, 원문 조회 `api6_section_records_current` |
| API303 경주 단위 통과조 원문 | `api_records` + `api303_corner_rank_rows` |
| 5R 홈페이지 거리 정정 6칸 | `api6_section_distance_reviews` |
| 구간별 유효 거리·시간·원값·상태·근거 | **`api6_section_points_current`** |
| 기존 말별 통과순위·시간과 통과조 품질 조회 | `sections_current` (기존 조회 정의 보존) |

API 원문 JSON·해시와 원문 조회를 보존한다. 거리 정정은 새 구간별 조회의 `distance_m`에 적용하고 `api_distance_m_raw`로 API 원값을 추적한다. `api6_section_records_current.payload_json`에서 거리를 직접 읽으면 정정 전 API 값이다. 말별 기록과 경주 단위 기록을 같은 단위로 합산하지 않는다.

### 5R 적용값

| API 필드 | API 원값(m) | 홈페이지·유효값(m) |
|---|---:|---:|
| `dist_1f` | 100 | 110 |
| `dist_2f` | 300 | 310 |
| `dist_3f` | 500 | 510 |
| `dist_4f` | 700 | 710 |
| `dist_5f` | 900 | 910 |
| `dist_6f` | 1100 | 1110 |

정정 지점의 상태는 `website_corrected`다. 해당 API record ID·경주키·경주거리·거리 원값·payload SHA·페이지 SHA·source artifact ID에 바인딩했다. 검토행이 없으면 알려진 5R 6칸을 NULL·`website_review_not_applied`, 적용 당시 원천과 달라지면 NULL·`api_source_changed_since_review`로 차단한다. 홈페이지 URL·원문 경로·SHA와 비교 증거 경로·SHA를 각 검토행에 남긴다.

다른 양수 API 거리의 상태는 `api_positive_unreviewed`다. 이번 정정은 이 5R만을 대상으로 하며 다른 1110m 경주에 일괄 +10m 보정하지 않는다. 0·미사용 칸은 실제 측정값 0으로 바꾸지 않는다. 괄호 내부 순서와 `^`, `-`, `=`를 임의의 말별 순위로 변환하지 않는다.

## 다른 1100·1110 기록의 상태

[독립 과거 감사](history_audit/README.md)의 수치는 이번 적재 **전** 스냅샷이다.

- API4 경주결과의 원문 `rcDist`와 DB `race_distance_m`는 1110m 관련 12,945행 전부 일치한다. 1110m 1,289경주이며 실제 경주거리 1100m 자료는 없다. `race_current`는 현재 제주마 프로필·후보 필터를 적용하므로 1,253경주·12,578행으로 원천 전체와 범위가 다르다.
- 기존 DB API6는 64경주 중 1110m 18경주이며, 18개 모두 `100·300·500·700·900·1100`의 API 거리 칸을 보존한다. 이 18경주의 홈페이지 정정은 이번 범위에 포함하지 않았다.
- 반영 후 1110m 19경주의 구간 지점 114개 중 기존 18경주의 108개는 `api_positive_unreviewed`이고 이번 5R 6개만 `website_corrected`다. 홈페이지 정정이 과거 전체에 적용됐다고 간주하지 않는다.
- 보관 중인 연도별 API6 원문 25페이지·19,651경주에는 1110m 1,259경주가 있고 전부 같은 거리 칸 패턴이다. 이 원문 아카이브와 정규 DB 적재를 혼동하지 않는다. 기존 2017년 이후 후보 경주키와 교차한 범위는 1,062경주다.
- 따라서 이번 5R 현상은 과거 API에도 반복된다. 홈페이지와의 과거 전수 대조 없이 원인·과거 전체 정답을 확정하지 않는다. API 거리 칸을 실제 측정거리로 전제한 속도·거리 대비 시간 계산에는 추가 검토가 필요하다.

## 근거와 실행

- [앞선 홈페이지·API 원문 대조](../20261018_oct17_sections_website_review/README.md)
- `plan.json`: 입력 원문 9개와 비교·수집 메타데이터 SHA, 기대 행 증가량, 적용 코드·DDL 해시, 적용 전 DB SHA.
- `plan_initial.json`: 백업 SHA 검사를 SQLite의 정상적인 헤더 차이를 허용하도록 수정하기 전 준비안. 적용에는 사용하지 않았다.
- `plan_before_migration.json`: 동일 DDL·VIEW의 재구축용 마이그레이션을 입력 SHA 목록에 추가하기 전 준비안. 적용에는 사용하지 않았다. 실제 적용은 `plan.json` 하나에 바인딩했다.
- `jeju/data/schema/migrations/20261018_add_api6_section_distance_reviews.sql`: 새 테이블·뷰 재현용 SQL이며 적용 코드의 DDL·VIEW와 정확히 일치한다. 마이그레이션의 파일 SHA도 계획에 고정했다.
- `verification/source_verification.json`: Luna xhigh의 별도 HTMLParser·JSON 원문 대조.
- `verification/preapply.json`: 적용 전 독립 검토 게이트.
- `before_section_load.sqlite3` + `prior_refresh_pointer.json`: 이번 적용 직전 백업과 당시 current manifest 포인터. 삭제된 옛 고정 기준 DB의 복원본이 아니다.
- `application_manifest.json`: 새 원행·검토행 적용 및 DB/백업 SHA. 이전 정기 갱신 원장은 변경하지 않고 current refresh sidecar가 이 좁은 적용 원장을 가리키도록 갱신한다.
- `verification/preservation.json`: 기존 전체 테이블·모든 열·스키마 보존, 기대 추가량, FK·무결성·롤백 재실행 확인.
- `verification/post_load_verification.json`: 적재된 원문·item 위치·SHA·거리 유효값의 독립 후검증.
- `completion_receipt.json`: 원장 해시·현재 DB/sidecar·과거 자료 보존과 적용 후 1110m 상태를 최종 확인한 완료 기록.

```sh
.venv/bin/python jeju/research/20261018_oct17_section_load/apply_sections.py prepare
# 독립 검토 후 verification/preapply.json 작성
.venv/bin/python jeju/research/20261018_oct17_section_load/apply_sections.py apply
.venv/bin/python jeju/research/20261018_oct17_section_load/apply_sections.py verify
```

원장·계획·백업이 있는 상태에서 `prepare`/`apply`는 덮어쓰지 않고 중단한다. 재구축 DB에 그대로 실행하는 범용 복구 명령이 아니며, 재구축 시 새 record ID·원문 SHA를 대조한 별도 재연결 계획이 필요하다. 새 원천 공개 시각은 정확히 확정하지 않았으며 수집 시각은 공개 시각이 아니다. 이번 사후 기록을 같은 경주의 사전 예측 입력으로 사용하지 않는다. 기존 2026-09-19 분석 상한·시간 정정 3건·광해청명 NULL·순위 정정 14건·충돌 보류 90행·기승자 보완·제외 말 정책은 보존한다.
