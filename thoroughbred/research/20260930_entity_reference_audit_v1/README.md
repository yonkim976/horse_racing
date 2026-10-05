# Thoroughbred entity reference audit v1

이 작업은 새 더러브렛 core DB의 말·기수·조교사·마주 ID 기준정보와 이름 관측을 공식 KRA 원천에서 대조한 읽기 전용 감사 산출물입니다. 감사 스크립트는 core DB를 read-only로 열고, 별도 builder가 검증된 exports를 적재합니다. 기간은 2010-01-01~2026-09-29, 대상은 서울(1)·부산경남(3)·영천(4)이며 제주(2)는 제외했습니다.

## 원천과 연결 규칙

- 확정경주 ID·이름의 기준은 날짜가 붙은 KRA API4_3 원문이고, 주행심사는 API20_1 원문입니다. 이 두 원천의 ID가 역사적 관측의 기준입니다.
- 말 프로필은 공식 API8_2, 기수·조교사·마주 스냅샷은 승인된 API307·API308·API309에서 가져왔습니다. 현재 프로필은 ID/이름 coverage 확인에만 사용했습니다. 프로필에 있는 현재 조교사·마주, 소속, 날짜 및 성적을 과거 경주나 심사에 붙이지 않았습니다.
- 원천 ID는 문자열 그대로 비교합니다. 숫자형·문자열형이 섞인 말 프로필 ID는 원래 JSON 타입도 함께 기록하며 숫자형 변환이나 0-padding을 하지 않습니다. 영숫자 ID도 허용합니다.
- 이름은 ID를 대신하는 키가 아닙니다. 경주·심사 원문의 이름 표기를 날짜별 alias 관측으로 보존했고, 감사 CSV의 사건 날짜는 `YYYY-MM-DD`로 정규화했습니다. 원천 경주·심사 날짜 문자열은 source spine에 그대로 있습니다. `[서울]`·`[부산경남]`·`[영남]` 접두어 제거값은 검토용 진단에만 사용합니다.
- RPT 자료는 기존 별도 심사 말 연결을 확인하는 보조 근거로만 남겼습니다. 이름만 맞는 행을 확정 ID로 자동 연결하지 않았습니다.

공식 카탈로그는 [데이터 원천 카탈로그](../../../docs/DATA_SOURCE_CATALOG.md)의 §4·§6과 [2026-09-30 KRA 승인 API 목록](../../../docs/KRA_APPROVED_42_API_CATALOG_2026-09-30.md)을 참고하세요. 공식 API 문서: [API8_2 경주마 상세](https://www.data.go.kr/data/15058115/openapi.do), [API307 기수](https://apis.data.go.kr/B551015/API307/jockeyInfo), [API308 조교사](https://apis.data.go.kr/B551015/API308/trainerInfo), [API309 마주](https://apis.data.go.kr/B551015/API309/horseOwnerInfo).

## 확인 결과

- core 확정 출전은 330,465행, 주행심사 참가자는 61,777행이며 출전/심사 행의 key 카디널리티를 보존했습니다.
- 고유 ID 기준 roster는 말 23,814개, 기수 337개, 유효 조교사 225개, 마주 1,438개입니다. 기수 `08A068` 같은 영숫자 ID도 그대로 다룹니다.
- 38개 확정 출전행에서 조교사·마주 ID가 동시에 비어 있습니다. 조교사 미확정 원천은 이 38행에 API20_1의 `api_trNo='-'`, `api_trName='-'` 84행과 비인물 placeholder 163행을 더해 총 285행입니다.
- 확정경주 23행과 심사 140행에 있는 `0AAAAA` / `휴양마`는 조교사 사람이 아니라 원천 placeholder로 분리했습니다. 유효 조교사 master ID에서 제외하고 원문 값·행 위치를 검토 원장에 남겼습니다.
- 심사 기수 ID와 이름이 모두 빠진 행은 5,121개입니다. 말 ID가 API20_1에서 빠진 104건은 원문을 그대로 두고 별도 검토된 연결 근거를 `trial_horse_id_source_exceptions.csv`에 보존했습니다. 이 중 99건은 RPT와 기존 경주 ID를 대조했고 5건은 사용자 확인 기록이 있습니다.
- 전체 미확정/예외 ledger는 5,548행입니다. 조교사 placeholder 163행은 별도 `non_person_placeholder_observations.csv`에도 남아 있습니다.
- 공식 현재 프로필 ID coverage: horse 23,814/23,814, jockey 337/337, trainer 225/225, owner 581/1,438. owner 나머지 857개 ID는 이 제한된 현재 프로필 캡처에서 찾지 못했으며 역사적 ID가 틀렸다는 의미는 아닙니다.
- API309 owner directory는 meet=1 484행, meet=3 384행을 반환했습니다. 전역 고유 ID는 597개이며 271개 ID가 두 meet query에 중복 등장합니다. 중복 ID의 현재 이름 충돌은 0입니다. 마주 roster는 event API ID 기준으로 한 ID당 한 행입니다.
- API307는 614+132행에서 전역 746 ID, API308은 252+53행에서 전역 305 ID를 확인했습니다. 두 API 모두 meet 간 ID 중복이 없었습니다.
- API8_2의 2026-09-23 `act_gubun=y` 3,061 ID는 각 meet에서 `n` cohort 안에 전부 포함됩니다. 따라서 `n`을 “비현역만”으로 해석하지 않고 요청 cohort와 관측 날짜만 저장했습니다.
- 검토한 API8_2 meet=4 호출은 성공 응답이지만 `totalCount=0`이었습니다. 영천 확정경주 119행의 말 ID 119개는 meet=1/3 프로필 집합에서 ID만 교차 확인했습니다. 현재 프로필의 경마장·소속·관계는 영천 사건에 소급하지 않습니다.
- API307/API309 스냅샷은 2026-09-30 코어 cutoff 이후, API308은 cutoff 날짜인 2026-09-29에 관측했습니다. API308의 시각 정보로 사건 당시 소속을 추론하지 않았고 세 API 모두 현재 프로필로만 취급합니다.

원문 ID별 이름 차이도 roster에 그대로 있습니다. 말 ID 961개는 확정경주·심사 관측을 합쳤을 때 둘 이상의 원문 이름을 가집니다. 조교사는 유효 ID 1개에서 복수 이름이 관측됐고, 마주는 14개 ID에서 복수 이름이 관측됐습니다. 특히 마주 `124017`에는 `(주)쎄쎄쎄`, `(주)쎄쎄쎄송도점`, `주식회사 쎄쎄쎄` 표기가 있습니다. 이 이름들은 병합 키로 쓰지 않습니다.

## 산출물

`exports/manifest.json`은 read-only로 연 core DB 경로와 고정 source spine CSV 2개의 SHA-256, 각 원문 page의 SHA-256·응답 코드·`totalCount`·페이지별 건수, export별 row count/hash 및 검증 결과를 기록합니다. builder가 이 manifest를 core DB에 적재하므로 core DB 자체 해시는 순환 변경 방지를 위해 넣지 않았습니다. 설정된 API 키의 원문/URL-인코딩 값이 54개 프로필 원문 페이지 어디에도 없는지도 검사했습니다. 키 값은 저장하거나 출력하지 않습니다.

| 파일 | 내용 |
|---|---|
| `entity_reference_summary.csv` | 엔티티별 원천 ID coverage, 별칭 충돌 및 미확정 개수 |
| `entity_reference_roster.csv` | ID별 한 행 roster, 사건 관측 기간, 이름 alias 요약, 현재 프로필 이름은 별도 표시 |
| `entity_name_observations.csv` | 공식 사건 원문의 ID-이름별 최초/최종 관측일, 건수와 source pointer |
| `horse_profile_snapshot_membership.csv` | API8_2 말 기본 프로필·혈통·현재 관계 스냅샷과 요청 cohort |
| `person_reference_profile_snapshots.csv` | API307/308/309 ID·이름·영문명·소속/기준일 등 프로필 필드. 성적은 포함하지 않음 |
| `entity_profile_coverage.csv` / `entity_profile_coverage_gaps.csv` | 사건 ID roster와 bounded current-profile 캡처 간 coverage/gap |
| `unresolved_entity_references.csv` | ID 공란, 미확정 링크, 비인물 placeholder 전 행 원장 |
| `non_person_placeholder_observations.csv` | 조교사 `0AAAAA` / `휴양마` 원문 163행 |
| `trial_horse_id_source_exceptions.csv` | 심사 API의 말 ID 결측 104건 및 별도 검토 근거 |
| `horse_profile_page_manifest.csv` / `person_profile_page_manifest.csv` | API별 원문 페이지 해시, query meet, `totalCount`, 페이지 건수 |

CSV는 UTF-8 BOM으로 저장했습니다. 재생성 명령은 저장소 루트에서 실행합니다.

```bash
.venv/bin/python thoroughbred/research/20260930_entity_reference_audit_v1/audit_entity_references.py
```

`--core-db`, `--raw-root`, `--output` 인자로 읽을 DB·원문 디렉터리·내보낼 위치를 지정할 수 있습니다. 스크립트는 core DB를 read-only로 엽니다.
