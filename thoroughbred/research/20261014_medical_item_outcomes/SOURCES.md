# 최근 의료기록 성과 분석의 출처

## 고정 입력

- 연구 코어 `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`: 2,742,300,672 bytes; SHA-256 `c46286df4773a7ffcea4c7bc431e2cd2a8fc03a4c38fdaa4403bd8f39c2a1668`. 읽기 전용 참조이며 신규 용량에서 제외한다.
- 원천은 최신 연도별 API16과 코어 경주 결과다. Text와 다른 API 관측본을 합산하지 않았다.
- 원천 공개 시각은 미확인이다. 이번 추정은 후향적 관측 연관성이며 임상 경중·치료 인과효과·운영 예측의 검증이 아니다.

## 공식 착순 코드 참고

[KRA 출전상세정보](https://race.kra.co.kr/chulmainfo/chulmaDetailInfo10Score.do?Act=02&Sub=1&meet=1&rcDate=20190602&rcNo=8)의 순위 특이사항에서 91 실격·92 주행중지와 93~95 제외·취소를 구분한다. 2026년 10월 14일 확인했으며 말별 임상 진단이나 모든 원천 코드의 검증 근거로 확장하지 않는다.

## 이전 자료 보존

다음 파일들은 내용·바이트·SHA-256을 작업 전후 대조했다. 사전 용어 문서는 의미·원천 한계의 참고이며 성적 효과의 근거는 새 추정치다.

- `thoroughbred/research/20261014_medical_record_feasibility/PUBLICATION.md`: 1546 bytes; `46e86e2c1b3de6f7c029ac88332ef442505d93ed3622802a741599f9ba349d20`
- `thoroughbred/research/20261014_medical_record_feasibility/audit.py`: 4772 bytes; `eb596c87ce76c6f30c5b03fb0096fcb5c014c52410dc15d25053e82a1a6b148e`
- `thoroughbred/research/20261014_medical_record_feasibility/SOURCES.md`: 935 bytes; `c58e4f2211e785bb06afbb280087b3063d94f9875e6440e72c5e7d65eed42a70`
- `thoroughbred/research/20261014_medical_record_feasibility/README.md`: 7629 bytes; `6074c4770dd3d721942e34a2b3493ee81079b6eeb0ac2534fe9c262d6a0ed2d4`
- `thoroughbred/research/20261014_medical_record_feasibility/register_finalize.py`: 6497 bytes; `ec49660e6e4f3267fa5122ab80ca6dc5ea15b6bcd1ee3a8ff2a17de5777e8dcd`
- `thoroughbred/research/20261014_medical_record_feasibility/outputs/artifact_inventory.json`: 2701 bytes; `630e0c3a003094e46479b5be1248295fd24e0d3045db2d85d53d1e591e5393d0`
- `thoroughbred/research/20261014_medical_record_feasibility/outputs/feasibility.json`: 7125 bytes; `45ffadd7be059499a59e350dd8a36975657b91423012a1cdfd583598f2ab0706`
- `thoroughbred/research/20261014_medical_record_feasibility/outputs/baseline.json`: 1590 bytes; `ccab92eb49e7e9bea93d30c25019258f7de73c7f407029ab179b2c43ff09b33d`
- `thoroughbred/research/20261014_medical_record_feasibility/outputs/artifact_size.md`: 247 bytes; `1924b2d06f222c921214231c536c526c8086b3a66e475c15a7c12cb7278a026b`
- `thoroughbred/research/20261014_medical_record_feasibility/outputs/verification.json`: 487 bytes; `ff78d172a5c74718b2d96b2605570c516ad15a1da7b7b7ad7e1024af20efc41e`
- `thoroughbred/research/20261002_medical_v1/root_text_inventory.json`: 1406067 bytes; `093ae343e921e68178a365d537de465c57ea4c5fe3e30b2dd849f5d93c99eda2`
- `thoroughbred/research/20261002_medical_v1/root_input_verification.log`: 1237 bytes; `f2067c979c90149e78c45a09051a7ae2ba57db7eb153c47f5942e8b91a71fb56`
- `thoroughbred/research/20261002_medical_v1/summary.json`: 4768 bytes; `b4ae62be2270e56c3a2b0eb49362fd2df715f43a121286babe5b725f4b0a20c9`
- `thoroughbred/research/20261002_medical_v1/root_input_verify.py`: 7802 bytes; `b137046f37d54a827ab656b7eb4080ed92c8899275bbd7981066b6a2a9f6d891`
- `thoroughbred/research/20261002_medical_v1/root_preservation_verification.json`: 8787 bytes; `73d7427cd51949afb3b73579d6d00632f338317c16b88ded5574c50cf59c92f0`
- `thoroughbred/research/20261002_medical_v1/root_dictionary_verify.py`: 4582 bytes; `e25ddca1eb35a52175dff39cd2fe6cda449ef5fe7264fecf8c82ac33dbcfda7d`
- `thoroughbred/research/20261002_medical_v1/root_input_verification.json`: 1369 bytes; `b9adbbaa8e415b99952b7a807cb7d6c087037491441b9dde8ddc4e1a788c2bbe`
- `thoroughbred/research/20261002_medical_v1/root_expected_horse_links.json`: 1004 bytes; `742f9425f86c3657aac40a87f25f262c5fe98dc4bee7c1ac8eb8fc0f6a5baa07`
- `thoroughbred/research/20261002_medical_v1/root_preservation_verify.py`: 4866 bytes; `35036ed7bb7f5b8d6e3d010ef631d4d178179a75db06068ec601c5aabb49d8e3`
- `thoroughbred/research/20261002_medical_v1/README.md`: 11228 bytes; `59762c2024fa6b2ba2f2455abd63e512ffd9b4381be7bc1696308b388a7cb11b`
- `thoroughbred/research/20261002_medical_v1/root_core_input_verification.json`: 4990 bytes; `e9a3465985220b67fe6caa70c54f99ecf331afa519771347643580d1af76e825`
- `thoroughbred/research/20261002_medical_v1/root_backup_attestation.json`: 1210 bytes; `8518ca990c8fff90a9aa8f985bcf28171d7fd88280b59bd046cfd98b9b59b5e1`
- `thoroughbred/research/20261002_medical_v1/root_core_input_verification.log`: 5191 bytes; `4e264136d52cedd7c68f57aeee1e19a44041b69dd4d6c7e2b27efe1ffe589b77`
- `thoroughbred/research/20261002_medical_v1/root_prepare_backup.py`: 1970 bytes; `d158e7aaebedecacea34825a8b59ffc15c317e9408c9cc340ab6104853e65cc5`
- `thoroughbred/research/20261002_medical_v1/root_dictionary_verification.json`: 331 bytes; `d910a36279a4f8abe20ecd4a8e31f30059adc2b72fc88170d4eba82a767f0fef`
- `thoroughbred/research/20261002_medical_v1/root_text_inventory.py`: 3512 bytes; `5d16d04ba2c1a146ffa76c68d83ef62df4ed59a348b506c9235b27fdde6231a5`
- `thoroughbred/research/20261002_medical_v1/root_preservation_verification.log`: 7342 bytes; `82c72bcc09a510b370b175ab073c35bd52012d1624ebf2fa1a2bdbb8d5a8d9a1`
- `thoroughbred/research/20261002_medical_v1/root_core_input_verify.py`: 7166 bytes; `0bf8ea127dd7ba785ee691bbf8d32768154f45d0b54a10b85a416756c43c5a36`
- `thoroughbred/research/20261002_medical_v1/loader/schema.sql`: 22714 bytes; `5547b02d14e2b07c47e0f515c835f1a64919479a32e81a1b6fe8bc25108a43ef`
- `thoroughbred/research/20261002_medical_v1/loader/input_contract.json`: 7525 bytes; `81898fd44f16f6298c6fbef777db1ccf82c16130265295675ccde74f574028b9`
- `thoroughbred/research/20261002_medical_v1/loader/apply.log`: 15528 bytes; `6bc3d0396108c32dcaacae8f4e4ed9b2a8697327defe2d6b9e34e215475f98a9`
- `thoroughbred/research/20261002_medical_v1/loader/apply_report.json`: 15528 bytes; `6bc3d0396108c32dcaacae8f4e4ed9b2a8697327defe2d6b9e34e215475f98a9`
- `thoroughbred/research/20261002_medical_v1/loader/load_medical.py`: 47566 bytes; `947795fafe1969f2020abd64f29d8c1ecef00461588b7cad09e293d598ea60b2`
- `thoroughbred/research/20261002_medical_v1/loader/dry_run_report.json`: 18917 bytes; `f8a7bff33d123ce4acd285126a50c868171050e1c6f43bbef548e2e31d0b800c`
- `thoroughbred/research/20261012_jockey_switch_trainer_intent/analyze.py`: 22183 bytes; `6e71294f772c839549e4a4d69f82c46113ec417c9a0985d5455a03f43618e878`
- `research/medical_injury_race_impact_20260925/medical_term_meaning_report_ko_20260928.md`: 83826 bytes; `e9ebea501f0d1bd324c595057305b1f04e380f05592b77cb128826e97719125e`
