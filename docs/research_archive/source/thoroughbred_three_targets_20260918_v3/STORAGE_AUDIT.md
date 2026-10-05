# 연구 저장소 감사

감사 범위는 `data/research`이며, 어떤 파일도 삭제·이동·압축하지 않았다. 용량은 하위 파일의 논리 바이트 합계이고, 중복 해시는 같은 크기의 그럴듯한 후보 8개에만 제한적으로 계산했다. 수십 GB 전체를 해시하지 않았다.

## 큰 폴더와 보존 원칙

상위 용량은 `storage_top_folders.csv`에 있다. 가장 큰 항목은 서울 backfill(약 3.70 GiB), 부경 history(약 2.42 GiB), 부경 complete DB(약 2.28 GiB), 제주 Text DB(약 1.43 GiB), 통합 더러브렛 DB(약 1.42 GiB)다.

| 분류 | 대상 | 판단 |
| --- | --- | --- |
| 보존 필수 | `thoroughbred_unified_20260918` | 현 통합 원천·manifest·재현 기준이다. |
| 보존 필수 | `seoul_backfill_20260915_v1`, `busan_history_20260915`, `busan_complete_db_20260916` | 통합 데이터의 대형 원천/파생 provenance다. 재생성 전 원천 및 의존성 확인이 필요하다. |
| 보존 필수 | 버전이 붙은 기존 모델·평가 디렉터리 | 모델, 예측, metrics, manifest가 서로 참조하며 운영·연구 재현성을 가진다. |
| 조건부 검토 | SHA 동일 `jeju_native_top3_dataset_v1_20260915*/entries.parquet` | 파일당 3,441,543 bytes가 동일하지만 서로 다른 버전 폴더의 artifact/manifest다. 참조 해제·재현 검증 전 삭제 불가. |
| 조건부 검토 | `thoroughbred_model_20260918_v1`의 identical `model.txt` 사본 | fixed/expanding fold가 같은 학습 기간일 때 byte-identical이다. fold artifact·manifest를 깨므로 제거 후보로 산정하지 않는다. |
| 조건부 보관/재생성 | `thoroughbred_win_research_20260918_v2/features_v2_rows.csv` | 139,748,563 bytes (133.3 MiB)의 원시 feature export다. 410,168 키와 34 feature 열이 `prepared_v2.parquet`에 모두 동일하게 흡수된 것을 직접 대조했다. 현재 manifest가 이 CSV를 해시하므로 현 버전에서 삭제하면 안 된다. |
| 즉시 재생성 가능 후보 | 두 `__pycache__` 디렉터리, 파일 논리 합계 470,647 bytes (약 460 KiB; 현재 할당 520 KiB) | Python 캐시다. 현재 작업이 종료된 뒤에만 별도 정리할 수 있으며, 이번 감사에서는 삭제하지 않았다. |

## 제한적 SHA 결과

검증된 exact duplicate는 세 그룹이다.

- 첫 번째 3개의 LightGBM `model.txt`가 같은 SHA-256이며, 각각 current fixed/expanding model 또는 calibration auxiliary artifact다.
- 두 번째 3개의 LightGBM `model.txt`가 별도의 같은 SHA-256이며, 각각 current fixed/expanding model 또는 calibration auxiliary artifact다.
- 2개의 Jeju `entries.parquet`가 같은 SHA-256이며, 버전 폴더가 다르다.

두 경우 모두 기존 manifest·실험 재현성·다른 작업의 활성 여부를 이 감사만으로 해제할 수 없다. 따라서 exact duplicate에서의 **실제 reclaimable 용량은 0 bytes**다. 단순히 `N-1`을 합산하면 서로 다른 실험이 참조하는 파일을 중복 계산하게 된다.

## 재생성 가능한 중간 export

`thoroughbred_win_research_20260918_v2/features_v2_rows.csv`는 139,748,563 bytes (133.3 MiB), `prepared_v2.parquet`는 45,762,002 bytes (43.6 MiB)다. feature 생성 코드는 CSV의 410,168개 `(race_id, hr_no)`와 feature 열을 타입 변환해 v1 prepared base에 join하고 Parquet을 작성한다. 이번 감사에서 두 파일의 행 수와 키가 모두 410,168개이며, CSV의 모든 feature 값이 Parquet 대응 열과 0건 차이임을 대조했다. 따라서 CSV는 분석 결과 자체가 아니라 재생성 가능한 원시 feature export다.

이 파일은 **현재 frozen artifact에서는 보존**, 다음 버전에서만 조건부 archive/remove 후보로 분류한다. 조건을 모두 충족할 경우 논리적으로 139,748,563 bytes를 확보할 수 있다. 이는 지금 바로 회수 가능한 용량이 아니며 exact duplicate 회수량과 합산하지 않는다.

1. 새 artifact 정책/인덱스에 `derived_regenerable`로 분류하고, 원래 SHA-256·바이트 수·입력/코드 SHA·재생성 명령을 남긴다.
2. 원본 manifest를 수정하지 않고 archive 포함 여부를 명시한 새 버전 manifest를 생성·검증한다. 재현은 기존 코드가 요구하는 새 격리 출력 경로에서 수행한다.
3. `prepared_v2.parquet`, `feature_audit.json`, 코드, 입력 참조와 재현 명령은 계속 보존한다. archive 복원 또는 재생성 뒤 row/key/value 대조와 연구 verifier를 통과시킨다.

대형 DB는 서로 단계가 다른 원천·backfill·통합 provenance이며, 파일명·용량만으로 중복이라고 판정하지 않았다. `unresolved_medical.csv`와 section export도 해당 단계의 원천 증적일 수 있으므로 이 감사에서는 재생성 후보로 올리지 않았다.

모델 artifact는 byte-identical이라도 경로별 fold/manifest 계약을 유지한다. 실험 종료 후 장기 보관으로 전환하려면 각 model bundle의 reload 검증과 manifest 인덱스를 먼저 완료한 뒤, 복사본을 archive에 압축해 보존하는 방법만 조건부로 검토한다. 운영·연구 모델 파일을 deduplicate하거나 삭제하는 계획은 이 감사의 범위에 없다.

`storage_audit.json`에는 해시 대상·SHA·바이트 수·분류 근거와 v2 CSV/Parquet 대조를, `storage_top_folders.csv`에는 전체 상위 폴더를 기록했다. 삭제 요청이 생기면 먼저 manifest 참조, 재현 명령, 현재 실행 프로세스 및 운영/연구 의존성을 개별 확인해야 한다.
