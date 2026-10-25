# 입력·출처와 보존

2026-10-08. 신규 수집 없이28C의 검증된 전체 명단·시점 제한 과거 이력을 읽기 전용 재사용했다. 아래7개 직접 입력과 전이 출처 원문18개·파생3개의 해시는 이전 [출처](../20261008_field_pace_prediction/SOURCES.md)와 [원천 감사](../20261008_field_pace_prediction/outputs/source_audit.json)에 연결된다. 기존119파일을 계산 전 목록화하고 공유5개를 제외한114개를 보존한다.

| 직접 입력 | 바이트 | SHA-256 |
|---|---:|---|
| [feature_context.parquet](../20261008_field_pace_prediction/outputs/feature_context.parquet) | 58823119 | `c5c89aae95bc5489158289790fe9b0fac8279ea10ec2bafc2ff1de9d59ed4857` |
| [feature_frame.parquet](../20261008_field_pace_prediction/outputs/feature_frame.parquet) | 45084556 | `fa838cd8960eafec5405d96b14ad68a63ed270ba78138e27e368585f5f932804` |
| [feature_groups.json](../20261008_field_pace_prediction/outputs/feature_groups.json) | 11897 | `083ef4f7af46bbac4233464c6fdeda7380cf96812699a9a14fe92bde62911493` |
| [early_predictions.parquet](../20261008_field_pace_prediction/outputs/early_predictions.parquet) | 7065737 | `dc5ea85290b5b831c2cf6ab3b6bdfb1e785ac0920caa72fa32fd46204f709885` |
| [example_cards.csv](../20261008_field_pace_prediction/outputs/example_cards.csv) | 16152 | `cdb9edef5b75d5164f0d8cc2c01e23b416f327373cb31d03432e081a5e54d8ec` |
| [source_audit.json](../20261008_field_pace_prediction/outputs/source_audit.json) | 5267 | `80661d6cf1f54b50a305bc51928d58617abb802d051f657309a229c992002587` |
| [verification.json](../20261008_field_pace_prediction/outputs/verification.json) | 2567 | `bd865a11f1fd6247c9d4381c1600df1f2fb0c832ffbfc3ebbe72ab95daf60f40` |

원문은 한국마사회 API4_3 실전 결과와 기존 S1F 통과조 자료다. [공식 경주성적표 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)의 S1F200m·G3F/G1F 지점과 마지막600/200m 시간을 구분한다. 첫 마군은 단독 선두와 다르다. 최종 명단의 당시 사전 공개시각·사후 정정은 감사하지 않았다. 기수/조교사 관련 변수는 이번 모형에서 모두 제외했으며 과거 말 기록에 남은 기수 영향을 인과적으로 제거한 것은 아니다.
