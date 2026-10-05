# 진료 용어와 뜻 정리 — 2026-09-27

- DB의 고유 원문 **5,397개**를 모두 수록했다. 진료기록 행은 697,695개이며 용어 빈도 합은 676,047이다.
- 이 산출물은 경주 성적 영향·임상 중증도·출전 가능 여부를 다루지 않는다.
- 원문과 term_id는 그대로 보존한다. 쉼표 원문 중 v3에서 명확히 분리한 3,722개만 구성요소 뜻을 병기하고 원문 용어의 빈도를 구성요소별로 나누지 않는다. 내부 쉼표로 보존하기로 한 9개는 나누지 않는다.
- `meaning_summary`는 확인된 공식 풀이, 안전한 형태소 규칙, 또는 판정 보류를 구별한다. rule-derived 설명은 후보 해석이며 수의학적 확정 진단이 아니다.

## 분류 건수

- administrative: 3
- anatomic_condition: 2
- behavior_or_condition: 1
- compound_source: 3,722
- disease: 355
- disease_or_anatomic_condition: 79
- disease_or_injury: 155
- disease_or_symptom: 9
- examination: 14
- injury: 850
- prevention: 7
- symptom: 77
- symptom_or_condition: 7
- treatment: 88
- unknown: 8
- unspecified_diagnosis_group: 20

## 뜻 확인 상태

- auto_interpreted_candidate: 5,281
- meaning_checked_against_kra_or_user_source: 24
- meaning_checked_against_veterinary_reference: 64
- meaning_checked_retain_as_single_phrase: 9
- partially_interpreted_unknown_component: 11
- unknown_manual_review: 8

검색과 안전한 규칙으로도 뜻을 확정하지 못한 `unknown_manual_review` 원문은 8개다.

## 검색으로 대조한 용어

검색으로 확인한 참고자료 풀이를 반영한 원문은 **64개**다. 좌우·다리 위치가 붙은 변형은 각각 원문 표기를 보존했다.

| term_id | 빈도 | 원문 | 분류 후보 | 검색 대조 풀이 | 출처 |
|---:|---:|---|---|---|---|
| 559 | 61 | 우상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 442 | 35 | 좌상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 695 | 20 | 좌후구근통 | symptom | 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 323 | 17 | 좌비절연종(좌급성활막염기인성경족관절낭 급성종창) | disease_or_anatomic_condition | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1284 | 17 | 우비절연종(우급성활막염기인성경족관절낭 급성종창) | disease_or_anatomic_condition | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 191 | 9 | 좌비절내종(좌비절원위관절퇴행성관절염) | disease_or_anatomic_condition | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 2231 | 7 | 양상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 1251 | 6 | 우후구근통 | symptom | 원문 부위 표기(오른쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 2472 | 6 | 인두림프양증생 | disease_or_anatomic_condition | 인두 점막에 퍼져 있는 림프소포가 도드라지거나 커진 상태(pharyngeal lymphoid hyperplasia). 어린 말에서 흔하고 정상 면역 발달 소견일 수도 있어, 이 용어만으로 임상 질환의 중요도를 단정하지 않음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/pharyngeal-lymphoid-hyperplasia-in-horses |
| 567 | 5 | 우비절내종(우비절원위관절퇴행성관절염) | disease_or_anatomic_condition | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1350 | 5 | 비절연종 | disease_or_anatomic_condition | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 2314 | 5 | 우전구근통 | symptom | 원문 부위 표기(오른쪽 앞다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 563 | 4 | 비절내종 | disease_or_anatomic_condition | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 629 | 4 | 피열후두개주름허탈 | disease_or_anatomic_condition | 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 1634 | 4 | 위식체 | disease | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 1832 | 4 | 이기(이물섭취증) | behavior_or_condition | 흙·모래·기타 먹을 수 없는 물질을 먹는 행동(pica/geophagia 등). 행동 기록만으로 원인 질환을 특정하지 않음. | https://www.merckvetmanual.com/behavior/behavior-of-horses/behavior-problems-of-horses |
| 3913 | 4 | 동물  좌비절연종(좌급성활막염기인성경족관절낭 급성종창) | disease_or_anatomic_condition | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1737 | 3 | 우슬개골상방고정 | disease_or_anatomic_condition | 슬개골 안쪽 인대가 대퇴골 활차융기에 걸려 무릎관절이 펴진 채 고정되는 상태(upward fixation of the patella). 좌우 표기는 원문을 따름. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses |
| 227 | 2 | 양제2중수골근위부비대 | disease_or_anatomic_condition | 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 561 | 2 | 양비절내종(양비절원위관절퇴행성관절염) | disease_or_anatomic_condition | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 2251 | 2 | 우제2중수골근위부비대 | disease_or_anatomic_condition | 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 3220 | 2 | 위선부궤양 | disease | 위의 선부(glandular mucosa)에 생긴 궤양(equine glandular gastric disease). | https://www.merckvetmanual.com/digestive-system/gastrointestinal-ulcers-in-large-animals/gastric-ulcers-in-horses |
| 4574 | 2 | 바이러스성유두종증 | disease | 바이러스성 유두종(사마귀 모양 증식)이 생기는 말의 질환군. 세부 유형과 발생 부위는 원문만으로 특정하지 않음. | https://pubmed.ncbi.nlm.nih.gov/24267681/ |
| 652 | 1 | 기관지염,우상악동염 | compound_source | 원문 부위 표기(기관지)의 기록. 기관지에 생긴 염증. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 946 | 1 | 우급성활막염기인성경족관절낭 급성종창/우비절연종 | disease_or_anatomic_condition | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1415 | 1 | 좌상악동염,안면골개봉술(개동술) | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 부비강에 접근하기 위해 안면골에 구멍을 내는 개방·천공 수술(개동술/trephination 계열). 수술명만으로 정확한 접근 부위나 적응증은 확정하지 않음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 1501 | 1 | 좌전지 욕창 | injury | 원문 부위 표기(원문 접두 `좌전`)의 기록. 지속적인 압박·마찰로 피부와 아래 조직에 생긴 압박성 궤양(pressure sore). 부위와 깊이는 원문만으로 알 수 없음. | https://www.merckvetmanual.com/integumentary-system/saddle-sores/saddle-sores-in-horses |
| 1515 | 1 | 비절내종,담마진 | compound_source | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. / 두드러기(urticaria). 피부에 팽진·가려움이 나타날 수 있는 반응. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1736 | 1 | 운동기인성 피로회복,좌후구근통 | compound_source | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. / 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 1762 | 1 | 우비절내종(우비절원위관절퇴행성관절염),우후제1지골근위배측부골절 | compound_source | 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. / 원문 부위 표기(오른쪽 뒷다리)의 기록. 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 1797 | 1 | 피부사상균증 | disease | 피부·털에 생기는 피부사상균 감염(dermatophytosis, ringworm). | https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses |
| 1866 | 1 | 좌전제저티눈 | injury | 원문 부위 표기(왼쪽 앞다리)의 기록. 발굽 바닥의 티눈(corn): 보통 제저 특정 부위의 압박·타박으로 인한 멍/출혈성 손상으로 쓰임. 깊이와 통증 정도는 원문만으로 알 수 없음. | https://www.petmd.com/horse/conditions/skin/c_hr_corns |
| 1921 | 1 | 마횡문근변성증 | disease | 운동과 관련해 골격근이 손상·괴사하는 운동성 횡문근융해증(exertional rhabdomyolysis) 계열. 원문만으로 원인 아형은 특정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses |
| 1935 | 1 | 좌전구절만성증식성활막염,우비절내종(우비절원위관절퇴행성관절염) | compound_source | 원문 부위 표기(왼쪽 앞다리)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 2088 | 1 | 좌전구근통 | symptom | 원문 부위 표기(왼쪽 앞다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 2265 | 1 | 위식체,변비산 | compound_source | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. / 변비와 관련된 산통(복부 통증)으로 풀이되는 용어. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 2352 | 1 | 좌제2중수골근위부비대 | disease_or_anatomic_condition | 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 2470 | 1 | 위식체,경련산 | compound_source | 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. / 경련성 산통(복부 통증)으로 풀이되는 용어. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 2517 | 1 | 부비강낭종 | disease | 말의 부비강 안에 생겨 자랄 수 있는 액체가 찬 낭성 병변(paranasal sinus cyst). 부위와 범위는 원문만으로 특정하지 않음. | https://vethospital.tamu.edu/large-animal/equine-soft-tissue-surgery/sinus-cyst/ |
| 2688 | 1 | 구내염,바이러스성유두종증 | compound_source | 입안 점막의 염증. / 바이러스성 유두종(사마귀 모양 증식)이 생기는 말의 질환군. 세부 유형과 발생 부위는 원문만으로 특정하지 않음. | https://pubmed.ncbi.nlm.nih.gov/24267681/ |
| 2788 | 1 | 양후낭축농증,양상악동염 | compound_source | 원문 부위 표기(원문 접두 `양후`)의 기록. 말의 인두낭(guttural pouch)에 고름이 차는 상태(empyema). 원인과 범위는 개별 기록으로 확인해야 함. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 2931 | 1 | 양슬개골상방고정 | disease_or_anatomic_condition | 슬개골 안쪽 인대가 대퇴골 활차융기에 걸려 무릎관절이 펴진 채 고정되는 상태(upward fixation of the patella). 좌우 표기는 원문을 따름. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses |
| 3010 | 1 | 원거술(전두동/상악동 천공술),좌상악동염 | compound_source | 원거술(전두동/상악동 천공술): 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3011 | 1 | 소화기 질환 기타,부정맥 | compound_source | 세부 병명이 기재되지 않은 기타 분류. / 심장 박동의 발생 또는 전도 리듬이 비정상적인 상태(arrhythmia). 종류와 임상적 의미는 원문만으로 특정하지 않음. | https://www.merckvetmanual.com/horse-owners/heart-and-blood-vessel-disorders-of-horses/introduction-to-heart-and-blood-vessel-disorders-of-horses |
| 3414 | 1 | 우후지파행,우제2중수골근위부비대 | compound_source | 원문 부위 표기(오른쪽 뒷다리)의 기록. 절뚝거림 등 비정상 보행 증상. 원인은 별도 진단이 필요함. / 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 3652 | 1 | 양전구절만성증식성활막염,우상악동염 | compound_source | 원문 부위 표기(양쪽 앞다리)의 기록. 구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3660 | 1 | 마체검사,양상악동염 | compound_source | 말의 몸 상태를 확인하는 검사. 검사명만으로 특정 질환이나 결과를 알 수 없음. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3767 | 1 | 동물  좌상악동염 | disease | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 3855 | 1 | 좌중간완골골편골절,좌전계인대관련성원발성근위종자골골증식증 | compound_source | 뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함. / 원문 부위 표기(왼쪽 앞다리)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |
| 3871 | 1 | 좌후구근통,우후구근통 | compound_source | 원문 부위 표기(왼쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. / 원문 부위 표기(오른쪽 뒷다리)의 기록. 발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음. | https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/ |
| 3931 | 1 | 동물  좌비절연종(좌급성활막염기인성경족관절낭 급성종창),요배통 | compound_source | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. / 원문 부위 표기(허리·등)의 기록. 허리·등 부위 통증. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38 |
| 4003 | 1 | 우상악동염,우비염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 코 점막의 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4038 | 1 | 동물  우제2중수골근위부비대 | disease_or_anatomic_condition | 제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses |
| 4064 | 1 | 좌후계인대관련성원발성근위종자골골증식증 | disease_or_anatomic_condition | 원문 부위 표기(왼쪽 뒷다리)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |
| 4193 | 1 | 좌후두편마비,피열후두개주름허탈 | compound_source | 왼쪽 후두의 반쪽 마비. 후두 기능과 호흡에 영향을 주는 상태. / 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 4421 | 1 | 우상악동염,후두염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 원문 부위 표기(후두)의 기록. 후두 점막의 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4613 | 1 | 산통,위식체 | compound_source | 말의 복부 통증(colic) 증상. 원인은 다양해 세부 진단은 별도 확인이 필요함. / 위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음. | https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177 |
| 4689 | 1 | 좌비절연종(좌급성활막염기인성경족관절낭 급성종창),정치 | compound_source | 비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음. / 치아의 이상 마모를 수동·자동 정치기구로 교정하는 치과 처치. 병명이나 건강 확인 자체를 뜻하지 않음. | https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38; https://race.kra.co.kr/racehorse/profileTreatmentItem.do |
| 4807 | 1 | 호흡기질환기타,피열후두개주름허탈 | compound_source | 호흡기 질환의 구체 병명을 적지 않은 기타 분류. / 피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음. | https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/ |
| 4830 | 1 | 술후처치(원거술),좌상악동염 | compound_source | 술후처치(원거술): 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. / 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 4946 | 1 | 좌상악동염,기관지염 | compound_source | 상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음. / 원문 부위 표기(기관지)의 기록. 기관지에 생긴 염증. | https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses |
| 5153 | 1 | 피부사상균증,피부염 | compound_source | 피부·털에 생기는 피부사상균 감염(dermatophytosis, ringworm). / 원문 부위 표기(피부)의 기록. 피부에 생긴 염증. | https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses |
| 5262 | 1 | 좌제3완골연골하골낭 | disease_or_anatomic_condition | 제3완골의 연골 바로 밑 뼈에 생긴 낭성 병변(subchondral cyst-like lesion). 정확한 위치·크기·관절 침범은 기록만으로 알 수 없음. | https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/subchondral-cystic-lesions-in-horses |
| 5370 | 1 | 양전계인대관련성원발성근위종자골골증식증 | disease_or_anatomic_condition | 원문 부위 표기(양쪽 앞다리)의 기록. 계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음. | https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis |

## 검색 후에도 미확인인 항목

아래 원문은 검색에서 확실한 표준 대응을 찾지 못했거나 원문이 잘려 있어 자동 복원하지 않았다. 상세 목록과 구성요소는 CSV에서 확인할 수 있다.

### 원문 전체가 미확인

- `지연발정정지기` (10회)
- `구개연종(구개종)` (5회)
- `진드기교창` (3회)
- `양전지근관증후군` (3회)
- `우비절외종` (1회)
- `과잉익상추벽` (1회)
- `좌비절외종` (1회)
- `특발성 좌경부 근위축` (1회)

### 쉼표 원문 중 일부 구성요소 미확인

- `운동기인성피로회복,각막?`: 미확인 구성요소 `각막?` (2회)
- `운동기인성피로회복,찰과?`: 미확인 구성요소 `찰과?` (1회)
- `우전구절염,운동기인성피?`: 미확인 구성요소 `운동기인성피?` (1회)
- `운동기인성피로회복,좌제3`: 미확인 구성요소 `좌제3` (1회)
- `좌후구절부찰과상,정장처?`: 미확인 구성요소 `정장처?` (1회)
- `림프관염(임파관염),양전?`: 미확인 구성요소 `양전?` (1회)
- `마비성근색소뇨증,우후지?`: 미확인 구성요소 `우후지?` (1회)
- `좌중수부계인대염,좌완관?`: 미확인 구성요소 `좌완관?` (1회)
- `좌중족부찰과상,우비절부?`: 미확인 구성요소 `우비절부?` (1회)
- `좌중족부찰과상,발목피부?`: 미확인 구성요소 `발목피부?` (1회)
- `마체검사,확인서 발급`: 미확인 구성요소 `확인서 발급` (1회)


## 빈도 상위 20개

| term_id | 빈도 | 원문 | 분류 후보 | 뜻 |
|---:|---:|---|---|---|
| 18 | 106,530 | 운동기인성 피로회복 | treatment | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. |
| 280 | 29,558 | 각막염 | disease | 원문 부위 표기(눈 각막)의 기록. 눈의 투명한 앞부분인 각막에 생긴 염증. |
| 5 | 22,977 | 운동기인성 피로회복(수액처치) | treatment | 운동기인성 피로회복(수액처치): 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. |
| 3092 | 21,516 | 동물  운동기인성 피로회복 | treatment | 운동기인성 피로회복: 처치·치료·관리 항목. 적응증이나 원래 질환은 이 표현만으로 확인 불가. |
| 1579 | 21,431 | 인푸렌자예방접종,선역예방접종 | compound_source | 인푸렌자예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. / 선역예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. |
| 1974 | 20,469 | 인푸렌자예방접종,일본뇌염예방접종 | compound_source | 인푸렌자예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. / 일본뇌염예방접종 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님. |
| 9 | 17,112 | 양각막염 | disease | 원문 부위 표기(양쪽 눈 각막)의 기록. 눈의 투명한 앞부분인 각막에 생긴 염증. |
| 1 | 16,987 | 양후지 근육통 | symptom | 원문 부위 표기(양쪽 뒷다리)의 기록. 근육 부위 통증. |
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
- Other veterinary references used are linked in `meaning_source_url` and component details in the CSV.
- 표준 참고자료의 일반적인 정의를 옮겼으며, 특정 말의 진단 확정·검사 결과·중증도를 확인한 것은 아니다. 검색 출처에 경주 성과 내용이 있어도 이 산출물에서는 의학적 뜻만 사용했다.
- 파일 재생성: `python3 research/medical_injury_race_impact_20260925/build_term_meaning_catalog.py`
