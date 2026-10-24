# 서울·부산 조교 변화 운영 모델

프로필 `thoroughbred-training-state-20261025-v1`, champion `personal_t2_2026_seoul_busan_20261025`.

2026-10-25 사용자의 명시적 요청으로 연구58I의 personal_t2_2026 서울/부산 가중치를 그대로 운영에 승격한다. 재학습한 다른 모델이 아니다. 이전 프로필 `thoroughbred-main-20260919-v1`은 복구와 과거 예측 재현을 위해 원래 내용으로 보존한다. 제주는 변경하지 않는다.

## 근거와 해석

운영과 동일한2026년1,258경주에서 축800→830건(63.59→65.98%),차이+2.38%p,경주일95%구간+0.07~+4.77%p였다. 서울464→486,부산336→344건이다. 조교 없는 연구 상태모델817건과 비교한 조교 추가분은13건이며 구간은0을 포함한다. 전체 삼복6조합384→408,부산145→166이지만 부산 복연3조합은314→299로 감소했다. [원 비교](../../thoroughbred/research/20261025_operating_training_comparison_v1/README.md).

반복 연구한 과거자료의 후향 결과다. 독립 미래검증과 조교의 역사적 공개시각 인증은 아직 없다. 이 한계를 통과한 것으로 바꾸지 않는다. 승격은 사용자의 운영 선택이며 성능보장이 아니다. 새 자료에 대한 지속 검증은 별도 수행한다.

## 동결한 모델·확률

서울/부산 각각136개 입력의LightGBM Top3 점수 모델1개,합계2개다. 2017–2024학습/2025확률 보정/2026적용의 기존 연구 가중치다. 입력은 실전기록·프로필·구간/각질·게이트 관계·동적 상태118열과 조교18열이다. [계약](feature_contract.json), [모델 명세](model_spec.json), [한국어 설명](feature_labels.json), [복제·수학 출처](asset_provenance.json).

한 개의3두집합 확률을 만들고 각 집합 내 Plackett–Luce 순서확률을 붙인다. A는 이 공동분포의 말별 주변확률,B는 집합확률,C는 정확한 순서확률이다. set temperature와 conditional order temperature는 원 연구의 고정값이며,A/B/C를 서로 곱하거나 다른 모델의 보정과 섞지 않는다. `trio_set_within_set_pl_v1`과 `thoroughbred_training_state_joint_v1` 계약을 사용한다. 기존 운영의 full-field 순서조건부 알고리즘으로 대체하면 같은 예측이 아니다. 보존 원점수3열은 같은 모델점수이며 알고리즘/각 지역 온도가 역할을 구분한다.

이 프로필은2026년 meet1/3만 지원한다. 제주/영천과2027년 이후에 이 가중치를 자동 적용하지 않는다. 신규연도 모델은 별도 검증한다.

## 추론 경로

프로젝트 루트에서 먼저 등록부를 확인한다.

```sh
.venv/bin/python .agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py --repo-root . --domain thoroughbred
```

새 예측은 다음 진입점을 사용한다. `--card`는 결과가 없는 전체 출마표parquet, `--card-metadata`는 사전 관측시각/해시/전체출전수/출발예정시각 원장이다. 출력폴더는 매번 새 경로여야 한다.

```sh
.venv/bin/python -B scripts/predict_thoroughbred_main.py --card PATH_TO_CARD.parquet --card-metadata PATH_TO_CARD_METADATA.json --sources PATH_TO_VERSIONED_SOURCE_MANIFEST.json --output PATH_TO_NEW_OUTPUT
```

필수 출마표 열은 `meet,race_date,race_no,program_no,horse_id,distance_m,grade_raw,current_carried_weight`다. 공식말ID는 앞자리0을 보존한7자리 문자열이다. `field_size`를 제공하면 취소 반영 전 전체 명부 크기와 일치해야 한다. `scratched`가 있으면 취소마를 제외한 뒤 상대 피처와출전수를재계산한다. 모든실제출전마가3두이상이어야한다. 결과/배당 열을 넣으면 거부한다. 경주일별로 실행한다.

실시간 card metadata는다음을포함한다. `runner_counts_by_race`와 `scheduled_at_utc_by_race`의 키는 `1:20261030:1` 형식이다. datetime은명시적timezone이있는ISO형식이다. 관측시각이실행후이거나출발30분전기한이지나면실패한다.

```json
{
  "card_sha256": "SHA256_OF_CARD_FILE",
  "observed_at_utc": "2026-10-29T05:00:00+00:00",
  "complete_card": true,
  "runner_counts_by_race": {"1:20261030:1": 12},
  "scheduled_at_utc_by_race": {"1:20261030:1": "2026-10-30T02:00:00+00:00"}
}
```

날짜·말ID·현재출마표조건만입력하고과거결과는T−2cutoff로조립한다. 현재경주 결과가 없어도136열을만든다. 지원이없는말의관측은규정된결측/초기상태로표현하며missing열을임의0으로만들지않는다. 원천조회는DuckDB읽기전용이다. 조교의자연키중복/원천QA/2시간초과/불완전응답을보수적으로처리한다. 상태필터는과거경주만순서대로갱신한다.

기본 [입력 manifest](source_manifest.json)는 검증 당시의 자료를 참조한다. **이 기본 실전 이력은2026-09-20,조교는09-28 종료**다. 현재 경기의 최신 자료라는 뜻이 아니다. 자료를 갱신하면 새로운해시와출처를가진별도manifest를`--sources`로전달한다. 기존고정manifest/모델을수정하지않는다. 소스해시불일치는실패하며,오래된이력과불완전조교창은출력metadata에드러낸다. 기본고정자료를최신으로표현하지않는다.

출력은전체출전마확률·원점수·순위의 `runner_predictions.parquet`, top3양성/음성기여 각각3개씩의 `runner_explanations.json`,동일예산조합의 `recommendations.json`,재현용 `prepared_features.parquet`,해시·시점·모델의 `run_metadata.json`이다. 설명은모델기여이며인과효과가아니다.

운영 DB 실제ID매핑parquet를 `--entry-map`으로제공하면일치하는전체출전마에한해canonical ID와`publication_metadata.json`도준비한다. ID는추정하지않는다. 이명령은DB/네트워크쓰기와게시를하지않는다. 실제저장/게시는별도승인된publisher절차를따른다. 새algorithm을해석하는코드로조합을계산해야하며옛알고리즘으로임의대체하지않는다.

기존 `scripts/build_current_prediction_bundles.py`는이전모델을직접읽으므로새프로필아래에서는명확히실패하도록했다. 새모델이름으로이전가중치를발행하지않는다. 과거날짜재현은`--dry-run`,등록전preview는추가로`--preview`이며실시간발행용envelope를생성하지않는다.

## 기술 검증

- 결과없는출마표40경주432두에서136입력58,752값을다시만들어원연구와대조했다. 최대오차2.84e−14.
- 2026년1,288경주13,638두의40,914개확률을동결모델로재추론해오차0,모든축선택과7,728개복승/복연조합이일치했다.
- 말별우승/Top2/Top3합1/2/3,확률단조성,출전마누락/취소재계산,미래관측배제,지원지역/연도,누락열,기여합과6개부호설명을검사했다.
- 결과없는40경주432두의출력을별도fixture ID로canonical validator에통과시켰다. 이synthetic ID는검증용이며게시하지않았다.
- 운영입력검사는Python최적화옵션으로사라지는assert에의존하지않는다. 등록파일/모델/온도/코드해시는resolver와추론전에검증한다.

[기술 검증](verification/technical_verification.json), [입력 조립 metadata](verification/feature_build_metadata.json), [과거 고정카드](fixtures/manifest.json), [승격 결정](decision.json).

운영 등록부 전환 후에도 resolver와 40경주·432두의 기본 경로 시험 실행을 통과했다. 원 연구 확률이 일치했고, 관련 pytest 10개가 통과했다. 이전 프로필 전체와 제주 라우팅은 보존됐다. 중복 마번과 소수 경주번호 거부를 추가한 뒤 해시를 최종 확정했다. [전환 확인](verification/activation_verification.json), [최종 확정 기록](verification/release_finalization.json), [시험 실행](verification/registered_dry_run_final/run_metadata.json), [테스트](verification/post_activation_tests.txt).

검증/시험실행은라이브예측이나새성능검증이아니다. 과거연구는당시registry해시를동결했으므로승격후그검증의전역registry일치를다시주장하지않는다. 당시manifest는보존하고현재승격검증을사용한다.

## 복구와 지속 개선

문제가발견되면`config/prediction_model_registry.json`의Thoroughbred active_profile을`thoroughbred-main-20260919-v1`로되돌리고resolver를확인한다. 이전프로필의모델/게이트는변경하지않았다. 과거예측은수정하지않고새run으로남긴다. [이전등록부](previous_registry.json)를보존했다.

[지속 개선 절차](../../docs/THOROUGHBRED_MODEL_IMPROVEMENT_2026-10-25.md)와[기록](IMPROVEMENT_LOG.md)에따라매주월요일오전10시한국시간이대화에서새자료/사전평가/후보실험을진행한다. 의미있는변화만알리고새후보를자동승격하지않는다.

주간 작업은 이 대화에 연결된 활성 heartbeat로 등록했다. [등록 정보](automation.json). 모델 교체 커밋은 `git log -- production_models/thoroughbred_training_state_20261025_v1 config/prediction_model_registry.json`으로 확인할 수 있다.

[용량명세](artifact_inventory.json)는모델2개·코드·fixture·검증·보고서를자기포함집계한다. 기존DB/전체이력은참조하며복제하지않았다.
