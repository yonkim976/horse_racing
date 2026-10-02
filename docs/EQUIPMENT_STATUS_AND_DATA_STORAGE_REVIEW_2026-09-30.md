# 장구 데이터 작업 현황과 data 폴더 저장공간 정리 검토

기준일: 2026-09-30. 이 문서는 장구 API78 백필·누락 출전마 보정의 완료 범위와 남은 일, 로컬 `data/`의 저장공간 정리 결과를 다음 작업자가 판단하기 위한 것이다. 최초 검토에서는 삭제하지 않았고, **이후 사용자의 지시로 대형 SQLite 백업 5개와 구간 정리 전 압축 CSV 백업을 제거했다.** 현행 운영 DB·원천·연구 산출물은 보존했다. 삭제된 파일을 직접 읽는 과거 스크립트·테스트 경로는 아직 수정하지 않았다.

## 장구 데이터와 누락 출전마 작업 현황

| 항목 | 확인된 상태 | 남은 일 |
| --- | --- | --- |
| API78 출마표 장구 증감 | 로컬 운영 SQLite와 Supabase `horse-racing-prod`에 2017-01-01~2026-09-30의 경주일·경마장 2,648조합을 소급 조회했다. `+` 27,980건, `-` 14,440건, 합계 42,420건이 양쪽에 있다. | 역사적 최종 출마표를 **초기 출마표 당시 관측값**으로 해석하지 않는다. 라이브 예측에는 실제 사전 관측 시각을 사용한다. |
| 운영 출전행과 API78 원문 연결 | 서울 2020-11-22 3경주 2번을 보정한 **현재** 2017년 이후 출전행은 238,279건이다. API78 원문 연결 238,175건, 미연결 104건이다. 백필 직후 보고서의 238,278/238,174는 보정 **이전** 수치다. | 원문 미연결 104두를 장구 없음으로 처리하지 않는다. 사용자 결정에 따라 이번에는 수정하지 않았다. |
| 공식 성적표 대조 | API78과 성적표에서 마번·마명이 일치한 1,828행은 공백 제거 후 장구 문자열이 전부 일치했다. 104두도 공식 성적표에 정상 순위와 장구 문자열이 있다. | 104두를 보완하려면 성적표 원문·조회 시각·출처를 별도로 저장하고, 경주 전 API78 관측으로 소급 표기하지 않는다. |
| 돌아온셀라 11착 | 2020-11-22 서울 3경주 2번, 공식 말 ID `0041616`의 출전·결과를 로컬과 Supabase에 추가했다. 양쪽 모두 11착, 90.0초, 출전두수 11이며 1~11착이 한 번씩 있다. 보존 API78 장구 `망사눈, 혀끈`을 소급 조회 시각과 함께 연결했다. | 최초 운영 수집 응답이 보존되지 않아 왜 처음 빠졌는지는 확정 불가. 2015년 이전만 다루는 이후 역사 백필과 기존 출전행만 갱신하는 API78 백필이 이 경주를 복구하지 못한 경로는 확인됐다. |
| API78에만 있는 과거 출전마·경주 | 최초 감사 시 기존 경주에 운영 출전행이 없던 2,371두 중 정상 11착 1두는 위와 같이 보정했다. **현재 기준 나머지 2,370두**는 공식 결과 코드 91~95인 2,368두와 `0`인 2두다. 운영 DB에 경주 자체가 없는 API78 경주는 제주 1,044개와 서울·부산 23개다. | 제주 1,044경주 중 정상 착순이 있는 996경주는 별도 결과 백필 검토가 필요하다. 제주 48경주와 서울·부산 23경주는 정상 착순이 없어 일반 완주 경주로 만들지 않는다. 특수코드 출전행도 결과 상태별로 다룬다. |

이 작업은 모델·예측 결과·Cloud Run 배포를 변경하지 않았다. 세부 감사 근거는 [API78 백필 결과](API78_EQUIPMENT_HISTORY_BACKFILL_2017_2026_2026-09-30.md)와 [독립 검증 및 11착 보정 기록](API78_EQUIPMENT_HISTORY_INDEPENDENT_VALIDATION_2026-09-30.md), 재현용 로컬 코드 `scripts/repair_seoul_20201122_r3_runner.py`에 있다. 2026-09-30에 Supabase를 다시 읽어 장구 증감 42,420행, 원문 미연결 104행, 보정 출전마 1행을 확인했다.

## 현재 로컬 data 폴더의 공간 사용

삭제 전 `du` 기준 `data/`는 약 **30GiB**, 해당 볼륨의 사용 가능 공간은 약 **26GiB**였다. 백업 5개 삭제 후 `data/`는 약 **17GiB**, 사용 가능 공간은 약 **40GiB**다. `du` 값은 반올림된 실제 디스크 사용량이고 아래 항목은 서로 포함 관계가 있으므로 합산하지 않는다.

| 범위 | 크기 | 현재 판단 |
| --- | ---: | --- |
| `data/horse_racing.sqlite3` | 약 2.9GiB | 앱·수집의 현행 로컬 운영 DB. 보존 |
| 운영 DB 변경 전 대형 SQLite 백업 | 0개 | 사용자 지시로 5개 삭제. 정확한 과거 복구 지점은 남지 않음 |
| `data/research/` | 약 7.0GiB | 통합·제주·구간 원천과 연구 재현 DB 포함. 일괄 삭제 금지 |
| `data/raw/` | 약 5.7GiB | KRA API/Text 원문과 DB `source_documents.local_path`의 근거. 일괄 삭제 금지 |
| `data/datasets/`, `data/experiments/` | 약 997MiB, 316MiB | 모델 입력·평가·등록 산출물 참조가 있어 파일별 의존성 조사 필요 |
| `data/backups/supabase_point_cleanup_20260928/` | 삭제 전 약 20MiB | 사용자의 추가 지시로 압축 CSV 2개와 해시 manifest 삭제. 현재 `data/backups/`는 비어 있음 |

SQLite의 현행 `horse_racing.sqlite3-wal`·`-shm`은 DB 동작에 속한다. **백업이나 임시 찌꺼기로 보고 수동 삭제하지 않는다.** Supabase의 DB 사용량은 이 로컬 `data/` 크기에 포함되지 않는다.

## 운영 DB 백업 5개 삭제

아래 다섯 파일은 전부 `.gitignore` 대상이며 Git에 저장된 복사본이 아니다. 처음 두 파일은 현행 DB와 테이블별 **행 수와 스키마 존재 여부**를 읽기 전용으로 비교했다. 행 수가 같아도 내용이 동일하다는 증명은 아니다. 사용자는 처음 두 파일을 삭제하도록 지시했고, 이어 남은 대형 백업도 삭제하도록 지시했다. 이후 세 파일은 삭제 전 정확한 경로·크기·해시·열린 프로세스 여부를 확인했다. 다섯 복구 지점의 완전한 대체 가능성은 입증하지 못했다.

| 파일 | 크기 | 현재 참조·보존 이유 | 공간 정리 판정 |
| --- | ---: | --- | --- |
| `data/backups/after_historical_backfill_20260918.sqlite3` | 2.50GiB | Supabase 최초 이전의 고정 원천. `scripts/migrate_sqlite_to_postgres.py` 기본 입력 및 `tests/test_supabase_migration.py` 3곳에서 직접 참조한다. | **삭제 완료.** 해당 기본 경로·테스트는 현재 파일 부재로 실패 가능 |
| `data/backups/horse_racing_pre_sync_20260923.sqlite3` | 2.50GiB | 9월 23일 동기화 전 복구 지점이었다. 실행 코드의 직접 입력 참조는 발견되지 않았다. | **삭제 완료.** 외부 보관본은 확인하지 못했다. |
| `data/horse_racing_pre_medical_terms_20260925.sqlite3` | 2.62GiB | 진료 용어 분리 전 복구 지점이었다. 현재 운영에는 `horse_medical_diagnoses` 676,047행과 `medical_diagnosis_terms` 5,397행이 새로 있다. | **삭제 완료.** 과거 조사 스크립트의 경로 참조는 남았다. |
| `data/backups/horse_racing_before_point_migration_20260928.sqlite3` | 2.64GiB | 구간·통과 운영 전환 전 복구 지점. `scripts/remove_legacy_point_duplicates.py`가 이 경로를 참조하고, 당시 Supabase 중복 제거 전 CSV 백업과 쌍을 이룬다. | **삭제 완료.** 과거 정리 스크립트의 직접 경로는 부재 |
| `data/horse_racing_before_20260929_identity.sqlite3` | 2.87GiB | 제주 말 신원 및 방문 조교사 연결 전 온라인 백업. 보정 내역의 최신 롤백 지점이며 현재와 DB 파일 바이트 크기가 같아도 내용은 다르다. | **삭제 완료.** 동일 시점 복구 불가 |

두 오래된 백업(`after_historical_backfill`, `pre_sync`)에만 있다는 서울·부산 **16경주·180출전**은 9월 29일 원천 목록에서 미판정이었으나, 이후 [운영 상태 기록](CURRENT_STATUS.md)과 [공식 날짜 원장](../thoroughbred/research/20260929_calendar_api_v1/README.md)에서 **2026-07-06·07의 비시행 유령 경주**로 판정됐다. 제주 4경주·40출전까지 합하면 해당 두 날짜의 운영 DB 삭제 대상은 20경주다. API154 경주계획은 0건인데 API155/156 결과가 날짜를 바꿔 이전 경주를 재방출한 사례다. 따라서 그 16경주를 유효한 경주로 복원하려고 백업을 유지할 필요는 없다. **다만 삭제한 `pre_sync`의 다른 모든 표가 현행 DB/원문으로 재현된다는 검증은 완료하지 못했다.** 이는 남은 세 백업의 삭제 안전성을 증명하지 않으며, 이들은 별도 사용자 지시에 따라 제거했다.

삭제한 다섯 DB의 원래 크기 합계는 **14,101,532,672 bytes(13.13GiB)**다. 삭제 전에 확인한 SHA-256은 다음과 같다.

| 삭제한 파일 | SHA-256 |
| --- | --- |
| `data/backups/horse_racing_pre_sync_20260923.sqlite3` | `e55610a0e45efaab13f810e763779ed441b7275ed3f90db877168ae42e16ed33` |
| `data/horse_racing_pre_medical_terms_20260925.sqlite3` | `359a1bdc1e9d23b5923462c9262a6f3e266f404cc8409d50ebb6b12d1c0ce892` |
| `data/backups/after_historical_backfill_20260918.sqlite3` | `79708446f6aea3840c01589906c0c3e4d9ec744d94fc22b82c9edc83ce3dc322` |
| `data/backups/horse_racing_before_point_migration_20260928.sqlite3` | `c998e28caea67c8c204cf0c9886d1b8e33139ba9c3a3e6533c01262c96a713aa` |
| `data/horse_racing_before_20260929_identity.sqlite3` | `acd813d99e9f931248043177988c71c97b4bf65607e5ba12ce6109eda56b048a` |

각 파일의 0-byte `-wal`과 32KiB `-shm` 보조 파일도 함께 제거했다. 삭제 전 `lsof`에서 열린 프로세스는 없었고, 삭제 후 대상 부재·현행 운영 DB 존재·디스크 여유 공간 증가를 확인했다. **휴지통 이동이나 외부 복사 없이 삭제했으므로 다섯 백업의 정확한 시점 상태는 Git에서 복구할 수 없다.** 현행 DB나 원천에서 일부 데이터는 얻을 수 있지만, 삭제한 파일과 바이트 단위로 같은 복구본이라는 뜻은 아니다. `thoroughbred/research/20260929_source_inventory_v1/catalog_operational_backups.py`는 삭제된 백업 경로를 여전히 가리켜 재실행 시 경로 조정이 필요하다. 기존 비교 JSON/CSV는 삭제 전 조사 기록으로만 읽는다.

추가 지시로 `data/backups/supabase_point_cleanup_20260928/`의 `race_section_results.csv.gz`(19,153,527 bytes), `race_passing_summaries.csv.gz`(2,134,973 bytes), `manifest.json`(665 bytes)을 정확한 경로로 삭제하고 빈 디렉터리도 제거했다. 합계 **21,289,165 bytes(약 20.30MiB)**다. 이 파일은 Supabase 구간 중복 제거 **이전**의 행을 되돌릴 수 있는 로컬 사본이었으며, 별도 원격 사본은 확인하지 못했다. 삭제 후 `data/backups/` 아래 파일이 없음을 확인했다.

## 다른 대용량 파일의 삭제 가능성

- `data/research/section_point_db_20260925/section_points.sqlite3` 약 680MiB는 현재 분석용으로 쓰지 않지만, [기존 독립 정리 검증](../thoroughbred/maintenance/20260928_cleanup/REPORT.md)에서 최종 판정 DB와 강한 원천 키로 대응되지 않은 튜플 756,700개가 확인됐다. 완전 대체가 입증되지 않아 **보존**한다.
- 같은 폴더의 `section_points_verified.sqlite3` 약 1.3GiB는 `scripts/adjudicate_section_points.py`의 직접 입력이다. `section_points_adjudicated.sqlite3` 약 1.3GiB는 현재 판정 DB다. 둘 다 **보존**한다. 이전 중간 파일 `section_points_ext.sqlite3`·`section_points_repaired.sqlite3`는 9월 28일 검증 후 이미 삭제돼 약 2.03GiB를 확보했다. 다시 삭제 대상으로 세지 않는다.
- `data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb` 약 1.2GiB와 제주 Text 연구 DB 약 1.4GiB는 역사 원천·재현 참조가 남아 있다. 각 폴더의 새 코어 DB와 이름만으로 중복이라고 볼 수 없다.
- `data/raw/`의 API JSON과 KRA Text는 출처·해시 검증, 구간 판정, 누락 자료 재구축에 쓰인다. 특히 API78 원문은 Supabase의 `source_documents`가 **로컬 경로**를 가리켜, 로컬 파일을 제거하면 원격 DB 행만으로 원문 재현이 되지 않는다. 별도 스토리지로 해시·경로를 보존하는 설계 전에는 삭제하지 않는다.
- `data/datasets/`·`data/experiments/`에는 과거 산출물도 있지만 모델 원장과 스크립트가 파일 경로를 직접 참조한다. 한 폴더 전체를 일괄 삭제해 절약하는 공간도 운영 백업에 비해 작다. 개별 모델·해시·재현 의존성을 대조한 뒤 별도 후보를 만든다.

## 다음 정리 순서

1. 운영 DB에 필요한 복구 정책을 새로 정한다. 현행 DB를 로컬 `data/` 밖의 독립 저장소에 새로 백업하고 해시·SQLite 무결성·복원시험을 확인한다. 같은 디스크 안에서 위치만 옮기면 저장공간이 늘지 않는다.
2. `after_historical_backfill`의 이전 스크립트·테스트, `before_point_migration`의 정리 스크립트처럼 삭제된 파일 경로를 읽는 과거 코드를 정리한다. 이 문서 작성 과정에서는 코드를 바꾸지 않았다.
3. 연구 원천·모델 산출물은 백업 파일과 다르다. 개별 의존성과 재현 가능성을 확인하기 전에는 삭제하지 않는다.

현재 결론은 **사용자 지정 대형 SQLite 백업 5개와 구간 정리 전 압축 백업 3개 파일 삭제 완료**다. `data/backups/`는 비어 있고, 현행 운영 DB와 원천·연구 DB는 삭제하지 않았다.
