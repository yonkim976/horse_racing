# 진료 용어와 뜻 정리 — 2026-09-28

- DB의 고유 원문 **5,397개**를 모두 수록했다. 진료기록 행은 697,695개이며 용어 빈도 합은 676,047이다.
- 이 산출물은 경주 성적 영향·임상 중증도·출전 가능 여부를 다루지 않는다.
- 원문과 term_id는 그대로 보존한다. 쉼표 원문 중 v3에서 명확히 분리한 3,722개만 구성요소 뜻을 병기하고 원문 용어의 빈도를 구성요소별로 나누지 않는다. 내부 쉼표로 보존하기로 한 9개는 나누지 않는다.
- `meaning_summary`는 확인된 공식 풀이, 안전한 형태소 규칙, 또는 판정 보류를 구별한다. rule-derived 설명은 후보 해석이며 수의학적 확정 진단이 아니다.
- 아래 `자동 분류 가능`은 문구 풀이 후보를 만들 수 있다는 뜻이다. 5,397개 모두 `review_status=candidate_not_clinically_reviewed`로 두었으며 수의사가 전체 용어를 검증한 상태는 아니다.

## 분류 건수

- administrative: 3
- anatomic_condition: 12
- behavior_or_condition: 1
- compound_source: 3,722
- disease: 306
- disease_or_anatomic_condition: 132
- disease_or_injury: 146
- disease_or_symptom: 9
- examination: 14
- injury: 853
- prevention: 7
- symptom: 77
- symptom_or_condition: 8
- treatment: 87
- unspecified_diagnosis_group: 20

## 뜻 확인 상태

- auto_interpreted_candidate: 4,213
- meaning_checked_against_kra_or_user_source: 1,067
- meaning_checked_against_veterinary_reference: 108
- meaning_checked_retain_as_single_phrase: 9

## 이번 검토의 결론과 사람 검토 범위

- **자동 분류 가능(뜻 후보): 4,213개.** 증상·손상·질환·처치·예방·검사·행정 등 문구 유형과 뜻을 규칙으로 후보화했다. 진단 확정이나 심각도를 뜻하지 않는다.
- **공개 자료/사용자 확인을 대조한 항목: 1,175개** (KRA·사용자 제공 정의 1,067; 수의학 참고자료 108). 이 출처 확인도 개별 말의 임상 검토와는 다르다.
- **사람 검토 필요: 0개**는 문구 전체를 원문만으로 확정하지 못해 보류했다. 쉼표가 내부 열거로 확인돼 보존한 9개도 구성요소 분해 대상이 아니다.
- **원문 자체에 세부 병명이 없는 ‘기타’ 묶음: 20개, 총 14,107회.** 사용자는 이를 이번 작업에서 대체로 ‘크지 않은 기타 질환’으로 보는 해석을 제시했다. 이는 분류표의 `user_interpretation`에 별도 기록했으며, 개별 말의 실제 진단·중증도나 영향이 낮다고 확인한 뜻은 아니다. 각 말의 상세 기록에서 구체 병명을 복원할 수 없는 한계는 남는다.
- **현 자료로 판정 불가:** 개별 말의 확진 여부·중증도·현재 회복 상태·경주 성적에 미친 실제 영향·공식 출전 가능 여부. 이번 용어 사전만으로는 결론을 낼 수 없다.

## 위험한 오분류와 수정

- `우제2,3중수골골간인대염좌/파열`처럼 `인대염` 글자가 포함된 손상 문구가 과거에는 염증 규칙에 먼저 걸릴 수 있었다. `염좌/파열`을 우선 인식하도록 고쳐 해당 표현을 손상 후보로 분류한다.
- 사용자 확인으로 `좌전제차부란/제차퇴행성?`는 KRA의 `좌전제차부란(제차퇴행성괴사) (LF. THRUSH)`, `양전구절특발성활막염(구?`는 `구건연종 (WINDPUFFS)`, `좌척측인대염기인성비부골척측비대/좌비절후종`은 `좌비절후종(좌척측인대염기인성비부골척측비대) (L. CURB)`로 확인해 풀이를 반영했다. DB 원문은 모두 그대로 보존한다.
- 늘기쁨(term_id 689)의 `좌척측인대염기인성비부골`도 사용자가 위 `L. CURB`와 같은 병명이라고 확인하여 해당 뜻으로 확정했다. 짧은 원문은 그대로 두고, 분류표 설명과 검토 로그에만 전체 풀이를 기록한다.
- `비절후종`의 좌·우·양측 표기 변형에도 같은 KRA 풀이를 적용했다. `발목피부염/계군`, `주두점액낭염/주종`, `비절외상성점액낭염/비절단종`을 구체화했고, `환골류/지골류`는 사전 표기대로 함께 풀이했다.
- `치료장제(제엽염)` 등 처치 괄호 속 병변·상태 표현은 원문에 함께 적힌 내용으로만 설명한다. 개별 말의 진단 확정으로 취급하지 않는다.

## 재검토에서 발견해 수정한 자동 풀이 오류

- 해부 부위 탐색에서 한 글자 부분 문자열(`위`, `지`)을 독립 부위로 처리하지 않도록 바꾸고, 경골·거골·관절·발굽 등 구체 용어를 우선 인식한다. 기존에 `원문 부위 표기(원문 접두 …)`로만 남던 **1,145개 용어(44,836회)**를 부위 문맥에 따라 풀이했다. 현재 같은 접두 미풀이 표기는 0개다.
- `원위단`의 `위`를 부위로 오인한 **4개 용어(5회)**를 바로잡았다. 예: `좌 경골원위단내측과이단성골연골염`은 왼쪽 경골 부위로 풀이한다.
- `이단성골연골염` **56개 용어(142회)**를 일반적인 “염증성 질환” 규칙보다 먼저 인식하고, 말의 골연골증/OCD 계열로 풀이한다. 영상상 병변·크기·임상증상은 원문만으로 확정하지 않는다.
- `양후낭축농증`은 `양후`를 뒷다리로 읽지 않고 양쪽 인두낭으로 처리한다. 문맥별 예외를 적용했다.
- 위 변경은 자동 풀이의 명백한 오류를 줄이기 위한 것이며, 모든 후보 의미가 수의사에게 검증됐다는 뜻은 아니다.

검색과 안전한 규칙으로도 뜻을 확정하지 못해 `unknown_manual_review`로 남긴 원문은 0개다.

## 검색으로 대조한 용어

검색으로 확인한 참고자료 풀이를 반영한 원문은 **108개**다. 좌우·다리 위치가 붙은 변형은 각각 원문 표기를 보존했다.

| term_id | 빈도 | 원문 | 분류 후보 | 검색 대조 풀이 | 출처 |
|---:|---:|---|---|---|---|
| 559 | 61 | 우상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 442 | 35 | 좌상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 246 | 32 | 우요완골이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 695 | 20 | 좌후구근통 | symptom | 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 513 | 18 | 우제3중수골원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1558 | 12 | 좌제3중수골원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 611 | 11 | 양제3중수골원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2231 | 7 | 양상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 1251 | 6 | 우후구근통 | symptom | 원문 부위 표기(오른쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 2472 | 6 | 인두림프양증생 | disease_or_anatomic_condition | 인두 점막에 퍼져 있는 림프소포가 도드라지거나 커진 상태(pharyngeal lymphoid hyperplasia). 어린 말에서 흔하고 정상 면역 발달 소견일 수도 있어, 이 용어만으로 임상 질환의 중요도를 단정하지 않음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/pharyngeal-lymphoid-hyperplasia-in-horses |
| 2314 | 5 | 우전구근통 | symptom | 원문 부위 표기(오른쪽 앞다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 629 | 4 | 피열후두개주름허탈 | disease_or_anatomic_condition | 원문 부위 표기(후두)의 기록. 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 1634 | 4 | 위식체 | disease | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 1832 | 4 | 이기(이물섭취증) | behavior_or_condition | 흙·모래·기타 먹을 수 없는 물질을 먹는 행동(pica/geophagia 등). 행동 기록만으로 원인 질환을 특정하지 않음. | https://www.merckvetmanual.com/behavior/behavior-of-horses/behavior-problems-of-horses |
| 435 | 3 | 좌전제1지골근위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 977 | 3 | 우 요완골 이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1698 | 3 | 양 요완골 이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1737 | 3 | 우슬개골상방고정 | disease_or_anatomic_condition | 슬개골 안쪽 인대가 대퇴골 활차융기에 걸려 무릎관절이 펴진 채 고정되는 상태(upward fixation of the patella). 좌우 표기는 원문을 따름. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses |
| 2167 | 3 | 좌요골전측원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 요골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3671 | 3 | 우요골원위단골편골절,우요완골이단성골연골염 | compound_source | 원문 부위 표기(오른쪽 요골)의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3904 | 3 | 좌요완골이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 5259 | 3 | 양전지근관증후군 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 앞다리)의 기록. 앞다리 완관절 뒤쪽의 근관(수근관) 안에서 굴건·건초·굴근지대 등 주변 구조의 병변이나 부종으로 문제가 생기는 말의 carpal canal syndrome. 원문에 기록된 증후군 이름까지만 풀이하며, 원인 병변은 특정하지 않음. | https://aaep.org/wp-content/uploads/2024/02/Proceedings-61st-Annual-Convention-2015.pdf |
| 227 | 2 | 양제2중수골근위부비대 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 중수골(앞다리 관골))의 기록. 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 648 | 2 | 좌 경골원위단내측과이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 경골(정강뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1711 | 2 | 좌 요완골 이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1908 | 2 | 좌전구절만성증식성활막염,좌제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(왼쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 원문 부위 표기(왼쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2251 | 2 | 우제2중수골근위부비대 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 중수골(앞다리 관골))의 기록. 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 2605 | 2 | 좌제3중족골원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 제3중족골(뒷다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3220 | 2 | 위선부궤양 | disease | 위의 선부(glandular mucosa)에 생긴 궤양(equine glandular gastric disease). | https://www.merckvetmanual.com/digestive-system/gastrointestinal-ulcers-in-large-animals/gastric-ulcers-in-horses |
| 4574 | 2 | 바이러스성유두종증 | disease | 바이러스성 유두종(사마귀 모양 증식)이 생기는 말의 질환군. 세부 유형과 발생 부위는 원문만으로 특정하지 않음. | https://pubmed.ncbi.nlm.nih.gov/24267681/ |
| 4987 | 2 | 우요완골이단성골연골염,좌요완골골연골증 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 440 | 1 | 양요완골이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 465 | 1 | 우중간완골이단성골연골염 | disease_or_anatomic_condition | 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 551 | 1 | 좌 경골원위단중간과이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 경골(정강뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 604 | 1 | 좌중간완골이단성골연골염 | disease_or_anatomic_condition | 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 652 | 1 | 기관지염,우상악동염 | compound_source | 원문 부위 표기(기관지)의 기록. 기관지에 생긴 염증. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 902 | 1 | 우요완골골편골절,우제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 969 | 1 | 우 요완골 이단성골연골염,정장처치 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / KRA 말정보 툴팁의 TONIC. 혈중 전해질 불균형 교정과 소화관 정상화를 위한 처치라고 풀이한다. | https://race.kra.co.kr/racehorse/profileTreatmentItem.do; https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1415 | 1 | 좌상악동염,안면골개봉술(개동술) | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 부비강에 접근하기 위해 안면골에 구멍을 내는 개방·천공 수술(개동술/trephination 계열). 수술명만으로 정확한 접근 부위나 적응증은 확정하지 않음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 1501 | 1 | 좌전지 욕창 | injury | 원문 부위 표기(왼쪽 앞다리)의 기록. 지속적인 압박·마찰로 피부와 아래 조직에 생긴 압박성 궤양(pressure sore). 부위와 깊이는 원문만으로 알 수 없음. | https://www.merckvetmanual.com/integumentary-system/saddle-sores/saddle-sores-in-horses |
| 1530 | 1 | 좌제3중수골원위단이단성골연골염,좌전구절만성증식성활막염 | compound_source | 원문 부위 표기(왼쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1614 | 1 | 양제3중수골원위단이단성골연골염,좌전구절만성증식성활막염 | compound_source | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1615 | 1 | 양슬관절이단성골연골염,좌제3중수골골막염 | compound_source | 원문 부위 표기(양쪽 슬관절(무릎관절))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / KRA 말정보 툴팁의 PERIOSTITIS & FRACTURE OF THE DORSAL METACARPUS. 왼쪽 앞다리 제3중수골 배측면의 압박·외상에 따른 골막하출혈 및 미세골절 소견이라고 풀이한다. | https://race.kra.co.kr/racehorse/profileTreatmentItem.do; https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1685 | 1 | 우 요완골 이단성골연골염,좌전제1지골골절 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1736 | 1 | 운동기인성 피로회복,좌후구근통 | compound_source | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. / 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 1797 | 1 | 피부사상균증 | disease | 원문 부위 표기(피부)의 기록. 피부·털에 생기는 피부사상균 감염(dermatophytosis, ringworm). | https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses |
| 1866 | 1 | 좌전제저티눈 | injury | 원문 부위 표기(왼쪽 앞다리 발굽 바닥)의 기록. 발굽 바닥의 티눈(corn): 보통 제저 특정 부위의 압박·타박으로 인한 멍/출혈성 손상으로 쓰임. 깊이와 통증 정도는 원문만으로 알 수 없음. | https://www.petmd.com/horse/conditions/skin/c_hr_corns |
| 1921 | 1 | 마횡문근변성증 | disease | 운동과 관련해 골격근이 손상·괴사하는 운동성 횡문근융해증(exertional rhabdomyolysis) 계열. 원문만으로 원인 아형은 특정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses |
| 1937 | 1 | 좌전제골염,좌 요완골 이단성골연골염 | compound_source | 왼쪽 앞다리 발굽뼈 부위의 염증성 질환. 정확히 어떤 조직이 침범됐는지는 세부 병명·검사로 확인해야 함. / 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1969 | 1 | 양제3중수골원위단이단성골연골염,우전구절만성증식성활막염 | compound_source | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(오른쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 1995 | 1 | 양제3중수골원위단이단성골연골염,양전구절만성증식성활막염 | compound_source | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(양쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2088 | 1 | 좌전구근통 | symptom | 원문 부위 표기(왼쪽 앞다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 2130 | 1 | 우 중간완골 골연골증,우 요완골 이단성골연골염 | compound_source | 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. / 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2132 | 1 | 우주관절이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 주관절(팔꿈치관절))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2151 | 1 | 좌전답창,우제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(왼쪽 앞다리)의 기록. 발굽 등에 밟히거나 찍혀 생긴 상처를 나타내는 용어. / 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2160 | 1 | 우 요완골 이단성골연골염,좌 중간완골 골연골증 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2179 | 1 | 우요골전측원위단이단성골연골염,우 중간완골 골연골증 | compound_source | 원문 부위 표기(오른쪽 요골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2180 | 1 | 양슬관절이단성골연골염,좌중족부근위부천지굴건염 | compound_source | 원문 부위 표기(양쪽 슬관절(무릎관절))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 굴건)의 기록. 천지굴건에 생긴 염증. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2265 | 1 | 위식체,변비산 | compound_source | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. / 변비와 관련된 산통(복부 통증)으로 풀이되는 용어. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 2274 | 1 | 양슬관절이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 슬관절(무릎관절))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 2352 | 1 | 좌제2중수골근위부비대 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 중수골(앞다리 관골))의 기록. 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 2470 | 1 | 위식체,경련산 | compound_source | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. / 경련성 산통(복부 통증)으로 풀이되는 용어. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 2517 | 1 | 부비강낭종 | disease | 말의 부비강 안에 생겨 자랄 수 있는 액체가 찬 낭성 병변(paranasal sinus cyst). 부위와 범위는 원문만으로 특정하지 않음. | https://vethospital.tamu.edu/large-animal/equine-soft-tissue-surgery/sinus-cyst/ |
| 2688 | 1 | 구내염,바이러스성유두종증 | compound_source | 입안 점막의 염증. / 바이러스성 유두종(사마귀 모양 증식)이 생기는 말의 질환군. 세부 유형과 발생 부위는 원문만으로 특정하지 않음. | https://pubmed.ncbi.nlm.nih.gov/24267681/ |
| 2788 | 1 | 양후낭축농증,양상악동염 | compound_source | 원문 부위 표기(양쪽 인두낭)의 기록. 말의 인두낭(guttural pouch)에 고름이 차는 상태(empyema). 원인과 범위는 개별 기록으로 확인해야 함. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 2931 | 1 | 양슬개골상방고정 | disease_or_anatomic_condition | 슬개골 안쪽 인대가 대퇴골 활차융기에 걸려 무릎관절이 펴진 채 고정되는 상태(upward fixation of the patella). 좌우 표기는 원문을 따름. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses |
| 3010 | 1 | 원거술(전두동/상악동 천공술),좌상악동염 | compound_source | 원거술(전두동/상악동 천공술): 처치·치료·관리 항목. 괄호 안에 `전두동/상악동 천공술`이 함께 기록됨. 개별 말에서 해당 병변·적응증의 확진 여부나 중증도는 이 문자열만으로 확인할 수 없음. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3011 | 1 | 소화기 질환 기타,부정맥 | compound_source | 세부 병명이 기재되지 않은 기타 분류. / 심장 박동의 발생 또는 전도 리듬이 비정상적인 상태(arrhythmia). 종류와 임상적 의미는 원문만으로 특정하지 않음. | https://www.merckvetmanual.com/horse-owners/heart-and-blood-vessel-disorders-of-horses/introduction-to-heart-and-blood-vessel-disorders-of-horses |
| 3218 | 1 | 우제3중수골원위단이단성골연골염,좌 제3중수골 원위관절면 골연골증 | compound_source | 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 제3중수골(앞다리 관골))의 기록. 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3281 | 1 | 우요골원위단골편골절,양요골전측원위단이단성골연골염 | compound_source | 원문 부위 표기(오른쪽 요골)의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(양쪽 요골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3414 | 1 | 우후지파행,우제2중수골근위부비대 | compound_source | KRA 말정보 툴팁의 RH. LAMENESS. 오른쪽 뒷다리의 비정상 보행·절음으로 풀이한다. / 원문 부위 표기(오른쪽 중수골(앞다리 관골))의 기록. 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://race.kra.co.kr/racehorse/profileTreatmentItem.do; https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 3652 | 1 | 양전구절만성증식성활막염,우상악동염 | compound_source | 원문 부위 표기(양쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3660 | 1 | 마체검사,양상악동염 | compound_source | 말의 몸 상태를 확인하는 검사. 검사명만으로 특정 질환이나 결과를 알 수 없음. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3665 | 1 | 좌요골원위단골편골절,우제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(왼쪽 요골)의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3767 | 1 | 동물  좌상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3828 | 1 | 좌요완골이단성골연골염,양전구절만성증식성활막염 | compound_source | 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(양쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3855 | 1 | 좌중간완골골편골절,좌전계인대관련성원발성근위종자골골증식증 | compound_source | 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(왼쪽 앞다리 계인대)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |
| 3856 | 1 | 좌전제1지골근위면골연골증,양제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. / 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3859 | 1 | 좌전제1지골근위단이단성골연골염,우중간완골골편골절 | compound_source | 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3871 | 1 | 좌후구근통,우후구근통 | compound_source | 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. / 원문 부위 표기(오른쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 3874 | 1 | 양제3중수골원위단이단성골연골염,우후제1지골근위면골연골증 | compound_source | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(오른쪽 뒷다리 제1지골(발가락뼈))의 기록. 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3891 | 1 | 좌요완골이단성골연골염,담마진 | compound_source | 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 두드러기(urticaria). 피부에 팽진·가려움이 나타날 수 있는 반응. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3933 | 1 | 우제3중족골원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 제3중족골(뒷다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 3965 | 1 | 양요골전측원위단이단성골연골염,양제2,3중수골골간인대염 | compound_source | 원문 부위 표기(양쪽 요골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(양쪽 중수골(앞다리 관골))의 기록. 인대에 생긴 염증. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4003 | 1 | 우상악동염,우비염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 코 점막의 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4030 | 1 | 우요완골골연골증,좌중간완골이단성골연골염 | compound_source | 원문 부위 표기(오른쪽 요완골(앞다리 아래쪽 뼈))의 기록. 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. / 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4038 | 1 | 동물  우제2중수골근위부비대 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 중수골(앞다리 관골))의 기록. 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 4041 | 1 | 특발성 좌경부 근위축 | symptom_or_condition | 근육량이 줄어든 소견. `특발성 좌경부 근위축`은 원문상 왼쪽 목 부위 근육 위축이며 원인을 특정하지 못했다고 기록한 표현으로 해석됨. 근위축의 원인과 임상적 의미는 별도 평가가 필요함. | https://pmc.ncbi.nlm.nih.gov/articles/PMC7915466/ |
| 4064 | 1 | 좌후계인대관련성원발성근위종자골골증식증 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 뒷다리 계인대)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |
| 4193 | 1 | 좌후두편마비,피열후두개주름허탈 | compound_source | 왼쪽 후두의 반쪽 마비. 후두 기능과 호흡에 영향을 주는 상태. / 원문 부위 표기(후두)의 기록. 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 4198 | 1 | 좌요골전측원위단이단성골연골염,좌요완골이단성골연골염 | compound_source | 원문 부위 표기(왼쪽 요골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 원문 부위 표기(왼쪽 요완골(앞다리 아래쪽 뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4358 | 1 | 좌제3완골골연골증,좌중간완골이단성골연골염 | compound_source | 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. / 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4421 | 1 | 우상악동염,후두염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 원문 부위 표기(후두)의 기록. 후두 점막의 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4586 | 1 | 우전제1지골근위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(오른쪽 앞다리 제1지골(발가락뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4613 | 1 | 산통,위식체 | compound_source | 말의 복부 통증(colic) 증상. 원인은 다양해 세부 진단은 별도 확인이 필요함. / 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 4758 | 1 | 양대퇴골외측활차이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 대퇴골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4765 | 1 | 좌전제1지골근위단이단성골연골염,양비절염 | compound_source | 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 양쪽 비절 관절 부위의 염증성 질환. 정확히 어떤 조직이 침범됐는지는 세부 병명·검사로 확인해야 함. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 4807 | 1 | 호흡기질환기타,피열후두개주름허탈 | compound_source | 호흡기 질환의 구체 병명을 적지 않은 기타 분류. / 원문 부위 표기(후두)의 기록. 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 4830 | 1 | 술후처치(원거술),좌상악동염 | compound_source | 술후처치(원거술): 처치·치료·관리 항목. 괄호에는 술후 관리와 연결된 수술·상황 `원거술`이 표기됨. 개별 말에서 해당 병변·적응증의 확진 여부나 중증도는 이 문자열만으로 확인할 수 없음. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4946 | 1 | 좌상악동염,기관지염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 원문 부위 표기(기관지)의 기록. 기관지에 생긴 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 5153 | 1 | 피부사상균증,피부염 | compound_source | 원문 부위 표기(피부)의 기록. 피부·털에 생기는 피부사상균 감염(dermatophytosis, ringworm). / 원문 부위 표기(피부)의 기록. 피부에 생긴 염증. | https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses |
| 5262 | 1 | 좌제3완골연골하골낭 | disease_or_anatomic_condition | 제3완골의 연골 바로 밑 뼈에 생긴 낭성 병변(subchondral cyst-like lesion). 정확한 위치·크기·관절 침범은 기록만으로 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/subchondral-cystic-lesions-in-horses |
| 5303 | 1 | 양 경골원위단중간과이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 경골(정강뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 5306 | 1 | 양전구절만성증식성활막염,좌전제1지골근위단이단성골연골염 | compound_source | 원문 부위 표기(양쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 원문 부위 표기(왼쪽 앞다리 제1지골(발가락뼈))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 5335 | 1 | 우제3중수골원위단이단성골연골염,좌 중간완골 골연골증 | compound_source | 원문 부위 표기(오른쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. / 관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 5369 | 1 | 양전구절만성증식성활막염,양제3중수골원위단이단성골연골염 | compound_source | 원문 부위 표기(양쪽 앞다리 구절 관절)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |
| 5370 | 1 | 양전계인대관련성원발성근위종자골골증식증 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 앞다리 계인대)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |
| 5395 | 1 | 좌거골내측활차원위단이단성골연골염 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 거골)의 기록. 이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses |

## 검색 후에도 미확인인 항목

아래 원문은 검색에서 확실한 표준 대응을 찾지 못했거나 원문이 잘려 있어 자동 복원하지 않았다. 상세 목록과 구성요소는 CSV에서 확인할 수 있다.

현재 원문 전체를 미확인으로 남긴 항목은 없다.

### ‘기타’ 분류별 확인 예시

각 고유 `기타` 원문마다 최근 진료기록 한 건을 연결했다. 예시는 용어 분류 확인용이며 개별 말의 확진을 뜻하지 않는다. 서울·제주·부산경남·영천은 DB 경마장 코드 기준이다.

| term_id | 빈도 | 원문 | 예시 말 (마사회 번호) | 경마장·조 | 진료일 |
|---:|---:|---|---|---|---|
| 88 | 1,046 | `호흡기질환기타` | 즐거운여정 (0045245) | 부산경남 27조 | 2026-09-22 |
| 100 | 7,886 | `운동기질환 기타` | 한라장사 (3103390) | 제주 6조 | 2026-09-20 |
| 129 | 4,206 | `외상기타` | 청풍윈드 (3109233) | 제주 13조 | 2026-09-17 |
| 159 | 276 | `제질환기타` | 위즈포인트 (0053705) | 서울 13조 | 2026-01-22 |
| 236 | 17 | `순환기질환 기타` | 블루칸 (3107876) | 제주 2조 | 2026-02-01 |
| 251 | 264 | `소화기 질환 기타` | 캐치윈드 (0061446) | 서울 14조 | 2026-09-15 |
| 266 | 52 | `기타` | 천년수 (3104789) | 제주 14조 | 2026-09-20 |
| 362 | 143 | `안질환기타` | 델타최강 (0053874) | 서울 28조 | 2026-09-01 |
| 428 | 101 | `피부질환기타` | 투혼여제 (3107908) | 제주 16조 | 2026-06-07 |
| 448 | 10 | `비뇨생식기기타` | 바로다나은 (0046900) | 서울 48조 | 2026-07-14 |
| 1192 | 3 | `소화기질환기타` | 어키쓰윈 (0012449) | 서울 3조 | 2004-10-25 |
| 2287 | 5 | `종양기타` | 비제이스톰 (0044853) | 서울 34조 | 2023-03-17 |
| 3144 | 16 | `동물  외상기타` | 마더트레저 (1411565) | 부산경남 2조 | 2023-10-24 |
| 3178 | 1 | `신경계질환기타` | 우승이지 (0030513) | 부산경남 24조 | 2014-01-08 |
| 3247 | 56 | `동물  호흡기질환기타` | 패스트멜로디 (0050872) | 부산경남 22조 | 2024-12-31 |
| 3332 | 3 | `동물  운동기질환 기타` | 월드메이드캣 (0047529) | 부산경남 6조 | 2024-05-20 |
| 3348 | 8 | `동물  제질환기타` | 선샤인볼트 (0035082) | 부산경남 5조 | 2018-03-23 |
| 3882 | 2 | `동물  안질환기타` | 럭키히트 (0047189) | 부산경남 24조 | 2024-02-13 |
| 3989 | 9 | `기타(입원)` | 적벽신화 (0039816) | 서울 99조 | 2019-08-28 |
| 4201 | 3 | `동물  소화기 질환 기타` | 로맨스블루 (0050250) | 부산경남 28조 | 2024-01-31 |

## 말별 KRA 진료페이지 툴팁 재확인

원문을 가진 말의 한국마사회 진료사항에서 같은 진료일의 상세항목을 대조했다. 상세 검토 로그는 `kra_profile_tooltip_review_20260928.csv` (30행)이며, 툴팁 설명은 원문 문구를 기록한 것이다. 이는 개별 말의 검사결과나 진단 확정은 아니다.

| term_id | 원문 | 확인한 말·진료일 | KRA 상세 용어(영문) | 툴팁 설명 / 확인 결과 |
|---:|---|---|---|---|
| 412 | `진드기교창` | 미라클골드 (0036885), 2018-06-09 | 진드기교창 (TICK BITES) | 대부분이 Hard tick이며 ear tick만 가시가 있고 진드기는 equine babesiosis 와 Ehrlichia equi를 전염시킬 수 있으며 tick paralysis를 유발할 수도 있음 [meaning_confirmed_from_KRA_profile_tooltip] |
| 654 | `운동기인성피로회복,각막?` | 정석 (0011497), 2003-09-20 | 운동기인성 피로회복 (FATIGUE HEAL) | 운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함 [component_matched_by_horse_and_date] |
| 654 | `운동기인성피로회복,각막?` | 정석 (0011497), 2003-09-20 | 각막염 (KERATITIS) | 눈의 각막에 발생하는 염증으로 경주마의 경우 주로의 모래가 튀어올라 눈에 맞음으로써 잘 발생하며 조교나 주로직후 각막세척과 치료를 적절히 하지 않으면 악화되기 쉽고, 간혹 채찍 등으로 인한 외상, 안구사상충 등의 기생충이나 화학물질에 의해서도 발생할 수 있음 [component_matched_by_horse_and_date] |
| 654 | `운동기인성피로회복,각막?` | 브라보걸 (0012056), 2003-10-05 | 운동기인성 피로회복 (FATIGUE HEAL) | 운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함 [component_matched_by_horse_and_date] |
| 654 | `운동기인성피로회복,각막?` | 브라보걸 (0012056), 2003-10-05 | 각막염 (KERATITIS) | 눈의 각막에 발생하는 염증으로 경주마의 경우 주로의 모래가 튀어올라 눈에 맞음으로써 잘 발생하며 조교나 주로직후 각막세척과 치료를 적절히 하지 않으면 악화되기 쉽고, 간혹 채찍 등으로 인한 외상, 안구사상충 등의 기생충이나 화학물질에 의해서도 발생할 수 있음 [component_matched_by_horse_and_date] |
| 656 | `운동기인성피로회복,찰과?` | 남대풍 (0015321), 2003-09-20 | 툴팁 항목 미노출 | 진료사항 페이지 1–10까지 확인했으나 2003-09-20 기록은 노출되지 않았다. 페이지 10에 표시된 가장 오래된 진료일은 2008-05-12였다. [not_visible_in_available_KRA_profile_pages] |
| 656 | `운동기인성피로회복,찰과?` | 남대풍 (0015321), 2003-09-20 | 찰과상 | 사용자가 해당 말의 KRA 진료기록에서 `찰과?`가 `찰과상`으로 표시된 것을 확인함. 이전 페이지 열람에서는 해당 날짜 원기록을 확인할 수 없었음. [meaning_confirmed_by_user_visual_review] |
| 664 | `우전구절염,운동기인성피?` | 당대한 (0011977), 2003-09-25 | 우전구절염 (RF FETLOCK JOINT DISEASE) | 오른쪽 앞다리 구절의 관절염 [component_matched_by_horse_and_date] |
| 664 | `우전구절염,운동기인성피?` | 당대한 (0011977), 2003-09-25 | 운동기인성 피로회복 (FATIGUE HEAL) | 운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함 [component_matched_by_horse_and_date] |
| 667 | `운동기인성피로회복,좌제3` | 오리온킹 (0012235), 2003-09-27 | 좌제3중수골골막염 (PERIOSTITIS & FRATURE OF THE DORSAL METACARPUS) | 왼쪽 앞다리 제3중수골 배측면에 압박이 가해지거나 외상의 결과로 골막하출혈 및 미세골절 나타남으로써 보이는 증상 [component_matched_by_horse_and_date] |
| 667 | `운동기인성피로회복,좌제3` | 오리온킹 (0012235), 2003-09-27 | 운동기인성 피로회복 (FATIGUE HEAL) | 운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함 [component_matched_by_horse_and_date] |
| 675 | `과잉익상추벽` | 땡큐 (0013387), 2003-10-02 | 과잉익상추벽 (REDUNDANT ALAR FOLDS) | 부분적으로 상부기도를 폐쇄 [meaning_confirmed_from_KRA_profile_tooltip] |
| 680 | `좌후구절부찰과상,정장처?` | 지덕장 (0012281), 2003-10-06 | 정장처치 (TONIC) | 혈중 전해질 불균형 교정과 소화관의 정상화를 위한 처치 [component_matched_by_horse_and_date] |
| 680 | `좌후구절부찰과상,정장처?` | 지덕장 (0012281), 2003-10-06 | 좌후 구절부 찰과상 (ABRASION OF LH. FETLOCK) | 비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 구절 부위 피부의 표면에 입는 외상 [component_matched_by_horse_and_date] |
| 688 | `림프관염(임파관염),양전?` | 컴플리트클래스 (0015207), 2003-10-10 | 림프관염(임파관염) (LYMPHANGEITIS) | 림프관의 염증, 급성 림프관염은 림프관계에 세균감염의 파급에 의하여 발생하며, 림프관의 경로에 따라 피하에 붉은 동통성 선조(線條)가 나타남. [component_matched_by_horse_and_date] |
| 688 | `림프관염(임파관염),양전?` | 컴플리트클래스 (0015207), 2003-10-10 | 양전제염 (BF. HOOF INFLAMMATION) | 양측 앞다리의 발굽에 나타나는 외상등 여러원인에 의해 생기는 일반적인 염증질환 [component_matched_by_horse_and_date] |
| 692 | `마비성근색소뇨증,우후지?` | 영해정 (0013356), 2003-10-11 | 마비성근색소뇨증 (EXERCISE RELATED MYOPATHY (PARALYTIC MYOGLOBULINURIA, MONDAY MORNING SICKNESS)) | 월요병 이라고도 불리며 근육(횡문근)이 손상되어 마비가 나타나는 근육질병 중의 하나로서, 이름에서도 알수 있듯이 근육속에 함유되어 있는 근색소(마이오글로빈)의 일부가 오줌을 통해 몸 밖으로 배출되기 때문에 쵸콜릿 색깔의 소변을 배설하고, 온몸이 마비되어 뻣뻣하게 서있거나 심한 경우 드러누워 일어나지 못하는 증상을 나타냄. [meaning_confirmed_from_KRA_profile_tooltip] |
| 692 | `마비성근색소뇨증,우후지?` | 영해정 (0013356), 2003-10-11 | 우후지파행 (RH. LAMENESS) | 오른쪽 뒷다리의 비정상적인 보행(다리 절음)의 총칭 [component_matched_by_horse_and_date] |
| 696 | `좌중수부계인대염,좌완관?` | 즐거운하루 (0010138), 2003-10-14 | 좌중수부계인대염 (DESMITIS OF THE SUSPENSORY LIGAMENT OF THE DEEP MC.) | 왼쪽 앞다리 중수부 계인대의 염증 [meaning_confirmed_from_KRA_profile_tooltip] |
| 696 | `좌중수부계인대염,좌완관?` | 즐거운하루 (0010138), 2003-10-14 | 좌완관절염 (L. CARPAL JOINT DISEASE) | 왼쪽 앞다리 완관절의 관절염 [component_matched_by_horse_and_date] |
| 713 | `좌중족부찰과상,우비절부?` | 조타수 (0011374), 2003-10-23 | 우비절부 찰과상 (ABRASION OF R. HOCK) | 비 정상적인 기계적 마찰에 의하여 오른쪽 뒷다리 비절 부위 피부의 표면에 입는 외상 [component_matched_by_horse_and_date] |
| 713 | `좌중족부찰과상,우비절부?` | 조타수 (0011374), 2003-10-23 | 좌중족부찰과상 (ABRASION OF L. METATARSUS) | 비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 중족부 부위 피부의 표면에 입는 외상 [meaning_confirmed_from_KRA_profile_tooltip] |
| 717 | `좌중족부찰과상,발목피부?` | 불비지혜 (0011621), 2003-10-26 | 좌중족부찰과상 (ABRASION OF L. METATARSUS) | 비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 중족부 부위 피부의 표면에 입는 외상 [meaning_confirmed_from_KRA_profile_tooltip] |
| 717 | `좌중족부찰과상,발목피부?` | 불비지혜 (0011621), 2003-10-26 | 발목피부염(계군) (PASTERN DERMATITIS (= SCRATCHES, GREASE HEEL, MUD FEVER, CRACKED HEEL)) | 발목 및 발굽 뒷꿈치 부위의 가피성 지루성 피부염 [component_matched_by_horse_and_date] |
| 714 | `좌전제차부란/제차퇴행성?` | 부움 (0012656), 2003-10-23 | 좌전제차부란(제차퇴행성괴사) (LF. THRUSH) | 좌측 앞다리 제차(발굽바닥에 삼각형으로 솟아오른 부위)의 가운데 홈과 외측면 홈의 퇴행성 변화로 괴사조직이 나타남 [meaning_confirmed_by_user_visual_review] |
| 676 | `양전구절특발성활막염(구?` | 인리스티드 (0015236), 2003-10-02 | 양전구절특발성활막염(구건연종) (WINDPUFFS) | 관절낭이나 건초에 활액과다로 인한 확장을 의미하며 파행과는 관계가 없음 [meaning_confirmed_by_user_visual_review] |
| 760 | `좌척측인대염기인성비부골척측비대/좌비절후종` | 지석 (0013643), 2003-11-23 | 좌비절후종(좌척측인대염기인성비부골척측비대) (L. CURB) | 왼쪽 뒷다리 척측인대의 염증 및 비후로 인하여 종골의 척측면 종창이 나타나는 것 [meaning_confirmed_by_user_visual_review] |
| 689 | `좌척측인대염기인성비부골` | 늘기쁨 (0011151), 2003-10-11 | 좌비절후종(좌척측인대염기인성비부골척측비대) (L. CURB) | 왼쪽 뒷다리 척측인대의 염증 및 비후로 인하여 종골의 척측면 종창이 나타나는 것 [meaning_confirmed_by_user_confirmation_of_canonical_term] |
| 1554 | `구개연종(구개종)` | 대한해협 (0018341), 2005-10-22 | 구개연종(구개종) (LAMPAS) | 절치 뒷부분의 구개 연부조직의 종창 [meaning_confirmed_from_KRA_profile_tooltip] |
| 4315 | `지연발정정지기` | 홍시 (0043366), 2020-04-27 | 지연발정정지기 (PROLONGED DIESTRUS) | 정상적인 자궁을 가진 암말이 불충분한 PG분비로 인하거나 출혈체의 존재로 인하여 0차 항체를 분해시키지 못함으로 인해 나타남 [meaning_confirmed_from_KRA_profile_tooltip_and_user_supplied_definition] |


## 빈도 상위 20개

| term_id | 빈도 | 원문 | 분류 후보 | 뜻 |
|---:|---:|---|---|---|
| 18 | 106,530 | 운동기인성 피로회복 | treatment | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. |
| 280 | 29,558 | 각막염 | disease | 원문 부위 표기(눈 각막)의 기록. 눈의 투명한 앞부분인 각막에 생긴 염증. |
| 5 | 22,977 | 운동기인성 피로회복(수액처치) | treatment | 운동기인성 피로회복(수액처치): 처치·치료·관리 항목. 괄호 안에 `수액처치`이 함께 기록됨. 개별 말에서 해당 병변·적응증의 확진 여부나 중증도는 이 문자열만으로 확인할 수 없음. |
| 3092 | 21,516 | 동물  운동기인성 피로회복 | treatment | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. |
| 1579 | 21,431 | 인푸렌자예방접종,선역예방접종 | compound_source | 인푸렌자예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. / 선역예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. |
| 1974 | 20,469 | 인푸렌자예방접종,일본뇌염예방접종 | compound_source | 인푸렌자예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. / 일본뇌염예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. |
| 9 | 17,112 | 양각막염 | disease | 원문 부위 표기(양쪽 눈 각막)의 기록. 눈의 투명한 앞부분인 각막에 생긴 염증. |
| 1 | 16,987 | 양후지 근육통 | symptom | 원문 부위 표기(양쪽 뒷다리 근육)의 기록. 근육 부위 통증. |
| 30 | 15,836 | 정치 | treatment | 치아의 이상 마모를 수동·자동 정치기구로 교정하는 치과 처치. 병명이나 건강 확인 자체를 뜻하지 않음. |
| 43 | 15,617 | 좌후지교돌상 | injury | 원문 부위 표기(왼쪽 뒷다리)의 기록. 달릴 때 서로 반대쪽 다리 등이 부딪혀 생긴 상처. |
| 4 | 12,091 | 교돌상 | injury | 달릴 때 서로 반대쪽 다리 등이 부딪혀 생긴 상처. |
| 25 | 11,809 | 감기 | disease | 감기 또는 상기도 호흡기 질환을 가리키는 포괄 표현. |
| 83 | 10,501 | 좌각막찰과상 | injury | 원문 부위 표기(왼쪽 눈 각막)의 기록. 눈의 각막 표면이 쓸려 벗겨진 상처(corneal abrasion). 깊이와 범위는 원문만으로 알 수 없음. |
| 54 | 10,106 | 좌전지파행 | symptom | 원문 부위 표기(왼쪽 앞다리)의 기록. 절뚝거림 등 비정상 보행 증상. 원인은 별도 진단이 필요함. |
| 95 | 10,072 | 양제3중수골골막염 | disease_or_injury | 원문 부위 표기(양쪽 제3중수골(앞다리 관골))의 기록. 뼈를 싸는 골막의 염증. |
| 17 | 9,313 | 요배통 | symptom | 원문 부위 표기(허리·등)의 기록. 허리·등 부위 통증. |
| 34 | 8,866 | 우전지파행 | symptom | 원문 부위 표기(오른쪽 앞다리)의 기록. 절뚝거림 등 비정상 보행 증상. 원인은 별도 진단이 필요함. |
| 121 | 8,028 | 인푸렌자예방접종 | prevention | 인푸렌자예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. |
| 100 | 7,886 | 운동기질환 기타 | unspecified_diagnosis_group | 운동기 질환의 구체 병명을 적지 않은 기타 분류. 특정 질환을 뜻하지 않음. |
| 84 | 7,357 | 우각막찰과상 | injury | 원문 부위 표기(오른쪽 눈 각막)의 기록. 눈의 각막 표면이 쓸려 벗겨진 상처(corneal abrasion). 깊이와 범위는 원문만으로 알 수 없음. |

## 읽는 법

- `symptom`: 증상이며 원인 질병을 확정하지 않는다. 예: 파행, 근육통.
- `injury`: 외상·조직 손상 표현. 크기·깊이·회복 상태는 포함하지 않는다.
- `disease`: 병명·질환 표현. 개별 말의 확진이나 현재 상태를 보증하지 않는다.
- `disease_or_injury`, `disease_or_anatomic_condition`, `disease_or_symptom`, `symptom_or_condition`, `anatomic_condition`: 원문이 질환·손상·해부학적 상태를 겹쳐 표현해 한 가지로 단정하기 어려운 후보. 상세 설명과 상태를 함께 본다.
- `treatment`: 처치·치료 기록이며 원래 진단을 뜻하지 않는다. 예: 정치, 발치, 피로회복.
- `examination`: 검사·검진 기록으로 결과나 질환을 뜻하지 않는다.
- `prevention`: 예방접종 등 예방 항목이다. 질병 진단이 아니다.
- `administrative`: 행정·기록 처리 항목.
- `unspecified_diagnosis_group`: “기타”처럼 구체 병명을 특정하지 않는 묶음.
- `compound_source`: 쉼표 원문을 v3 경계 검토 결과에 따라 자식 구성요소로 풀이했다. 자식 빈도는 산출하지 않았다.
- `unknown`: 검색에서도 확실한 대응 풀이가 없어 판정 보류로 남긴 항목.

## 출처와 제한

- KRA 질병용어 사전: https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=2, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=3, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=4, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=5
- KRA 경마용어 사전(비절 질환 용어): https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38
- Merck Veterinary Manual: https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/pharyngeal-lymphoid-hyperplasia-in-horses, https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses, https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses, https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses
- AAEP prolonged-luteal-phase proceedings (지속 황체/지연 발정휴지기 설명): https://aaep.org/wp-content/uploads/2024/02/Proceedings-59th-Annual-Convention-2013.pdf
- Other veterinary references used are linked in `meaning_source_url` and component details in the CSV.
- 표준 참고자료의 일반적인 정의를 옮겼으며, 특정 말의 진단 확정·검사 결과·중증도를 확인한 것은 아니다. 검색 출처에 경주 성과 내용이 있어도 이 산출물에서는 의학적 뜻만 사용했다.
- 파일 재생성: `python3 research/medical_injury_race_impact_20260925/build_term_meaning_catalog.py`
