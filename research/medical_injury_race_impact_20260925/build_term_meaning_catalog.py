#!/usr/bin/env python3
"""Build a read-only, source-preserving medical term/meaning review catalog."""
from __future__ import annotations
import csv, hashlib, json, re, sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(__file__).resolve().parents[2] / 'data' / 'horse_racing.sqlite3'
OUT = ROOT / 'medical_term_meaning_catalog_20260928.csv'
META = ROOT / 'medical_term_meaning_catalog_metadata_20260928.json'
REPORT = ROOT / 'medical_term_meaning_report_ko_20260928.md'
KRA_AUDIT = ROOT / 'kra_profile_tooltip_review_20260928.csv'
GLOSSARY = 'https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=3'
PROFILE_TOOLTIP = 'https://race.kra.co.kr/racehorse/profileTreatmentItem.do'
SOURCE_URLS = {
 'kra_profile_tooltip': PROFILE_TOOLTIP,
 'kra_official_glossary': 'https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=4',
 'kra_record_term': PROFILE_TOOLTIP,
 'user_supplied_kra_definition': 'https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=4',
 'user_visual_confirmation': PROFILE_TOOLTIP,
 'web_kra_racing_glossary': 'https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38',
 'web_kra_racing_glossary_ringbone': 'https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=121',
 'web_kra_racing_glossary_windgall': 'https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=151',
 'web_kra_racing_glossary_capped_spavin': 'https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38',
 'web_kra_disease_glossary': 'https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do',
 'web_msd_pharyngeal_lymphoid_hyperplasia': 'https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/pharyngeal-lymphoid-hyperplasia-in-horses',
 'web_umn_aryepiglottic_fold': 'https://open.lib.umn.edu/largeanimalsurgery/chapter/laryngeal-disorders/',
 'web_msd_splint_exostoses': 'https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-metacarpus-and-metatarsus/exostoses-of-the-second-and-fourth-metacarpal-bones-in-horses',
 'web_msd_patellar_fixation': 'https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses',
 'web_msd_dermatophytosis': 'https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses',
 'web_msd_exertional_myopathy': 'https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses',
 'web_msd_horse_behaviour': 'https://www.merckvetmanual.com/behavior/behavior-of-horses/behavior-problems-of-horses',
 'web_wiley_gastric_impaction': 'https://bvajournals.onlinelibrary.wiley.com/doi/full/10.1002/inpr.177',
 'web_tamu_sinus_cyst': 'https://vethospital.tamu.edu/large-animal/equine-soft-tissue-surgery/sinus-cyst/',
 'web_msd_paranasal_sinuses': 'https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/diseases-of-the-paranasal-sinuses-in-horses',
 'web_msd_gastric_ulcers': 'https://www.merckvetmanual.com/digestive-system/gastrointestinal-ulcers-in-large-animals/gastric-ulcers-in-horses',
 'web_merck_subchondral_cysts': 'https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/subchondral-cystic-lesions-in-horses',
 'web_sesamoid_lesions': 'https://www.sciencedirect.com/topics/agricultural-and-biological-sciences/sesamoiditis',
 'web_bhs_heel_bulb': 'https://prod.bhs.org.uk/horse-care-and-welfare/health-care-management/hoof-care/overreach-and-heel-bulb-injuries-in-horses/',
 'web_petmd_hoof_corn': 'https://www.petmd.com/horse/conditions/skin/c_hr_corns',
 'web_tamu_epiglottic_entrapment': 'https://vethospital.tamu.edu/large-animal/equine-soft-tissue-surgery/epiglottic-entrapment/',
 'web_msd_arhythmia': 'https://www.merckvetmanual.com/horse-owners/heart-and-blood-vessel-disorders-of-horses/introduction-to-heart-and-blood-vessel-disorders-of-horses',
 'web_msd_saddle_sore': 'https://www.merckvetmanual.com/integumentary-system/saddle-sores/saddle-sores-in-horses',
 'web_equine_papillomatosis': 'https://pubmed.ncbi.nlm.nih.gov/24267681/',
 'web_vet_anatomy': 'https://www.imaios.cn/en/vet-anatomy/anatomical-structures/proximal-sesamoid-bones-11073899576',
 'web_aaep_carpal_canal_syndrome': 'https://aaep.org/wp-content/uploads/2024/02/Proceedings-61st-Annual-Convention-2015.pdf',
 'web_equine_cervical_atrophy': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC7915466/',
 'web_aaep_prolonged_diestrus': 'https://aaep.org/wp-content/uploads/2024/02/Proceedings-59th-Annual-Convention-2013.pdf',
 'web_msd_osteochondrosis': 'https://www.merckvetmanual.com/musculoskeletal-system/developmental-orthopedic-disease-in-horses/osteochondrosis-in-horses',
}

# Search-verified medical roots. These are kept separate from literal morphology
# rules so the CSV can point readers to the reference used for each interpretation.
WEB_ROOTS = [
 ('비절외상성점액낭염','disease_or_anatomic_condition','musculoskeletal','비절 끝부분에 외상·진동 등으로 생기는 종창으로, KRA 용어사전의 비절단종(capped spavin)에 대응하는 표현. 부종 조직과 원인은 개별 기록만으로 확정하지 않음.','web_kra_racing_glossary_capped_spavin'),
 ('주두점액낭염','disease_or_anatomic_condition','musculoskeletal','주두부(팔꿈치 뒤쪽)에 마찰·외상 등으로 생기는 점액낭/연부조직의 종창(주종, capped elbow 또는 shoe boil). 원문만으로 크기·현재 통증·기능 영향은 알 수 없음.','web_kra_disease_glossary'),
 ('발목피부염','disease','skin','KRA 말 진료 툴팁의 발목피부염(계군), pastern dermatitis. 발목 및 발굽 뒤꿈치 부위의 가피성 지루성 피부염을 가리킴. 개별 기록만으로 병변의 범위·중증도는 알 수 없음.','kra_profile_tooltip'),
 ('제차퇴행성괴사','disease_or_injury','musculoskeletal','KRA 용어 풀이의 제차부란(thrush). 발굽 바닥의 제차(frog)가 부식·부패하고 괴사조직이 나타날 수 있는 발굽 질환. 이 원문만으로 병변 깊이·정도는 확정할 수 없음.','web_kra_disease_glossary'),
 ('제차부란','disease_or_injury','musculoskeletal','KRA 용어 풀이의 제차부란(thrush). 발굽 바닥의 제차(frog)가 부식·부패하고 괴사조직이 나타날 수 있는 발굽 질환. 이 원문만으로 병변 깊이·정도는 확정할 수 없음.','web_kra_disease_glossary'),
 ('구건연종','anatomic_condition','musculoskeletal','KRA 경마용어사전의 구건연종(wind gall/puff): 구절 관절낭이나 건초에 활액이 증가해 팽창한 상태. KRA 설명은 파행과 관계없는 소견으로 풀이함. 개별 말의 상태는 진찰 없이 확정하지 않음.','web_kra_racing_glossary_windgall'),
 ('비절후종','disease_or_anatomic_condition','musculoskeletal','사용자가 확인한 KRA 상세 용어 CURB: 뒷다리 비절의 척측인대 염증·비후로 종골 척측면에 종창이 나타나는 상태. 좌우·양측 표기는 원문을 따르며, 개별 기록만으로 병변 정도는 알 수 없음.','user_visual_confirmation'),
 ('지골류/환골류','disease_or_anatomic_condition','musculoskeletal','KRA 경마용어사전은 지골류와 환골류를 ringbone으로 함께 표기한다. 발가락뼈 주변의 골성 증식 표현이며, 개별 말의 부위·범위·증상은 원문만으로 알 수 없음. 슬래시 원문은 한 표현으로 보존한다.','web_kra_racing_glossary_ringbone'),
 ('인두림프양증생','disease_or_anatomic_condition','respiratory_or_upper_airway','인두 점막에 퍼져 있는 림프소포가 도드라지거나 커진 상태(pharyngeal lymphoid hyperplasia). 어린 말에서 흔하고 정상 면역 발달 소견일 수도 있어, 이 용어만으로 임상 질환의 중요도를 단정하지 않음.','web_msd_pharyngeal_lymphoid_hyperplasia'),
 ('피열후두개주름허탈','disease_or_anatomic_condition','respiratory_or_upper_airway','피열후두개 주름(aryepiglottic fold)이 기도 쪽으로 안쪽/축 방향으로 무너지는 상부기도 상태. 원문만으로 허탈의 동적 여부나 동반 병변은 특정하지 않음.','web_umn_aryepiglottic_fold'),
 ('상악동염','disease','respiratory_or_sinus','상악동(위턱 쪽 부비강)의 염증. 원인과 범위는 원문만으로 특정할 수 없음.','web_msd_paranasal_sinuses'),
 ('제2중수골근위부비대','disease_or_anatomic_condition','musculoskeletal','제2중수골(작은 부목뼈)의 근위부가 커졌다는 해부학적 소견. 말에서 제2·제4중수골은 부목뼈이며 골성 증식이 생길 수 있으나, 이 원문만으로 원인이나 병변 형태를 확정하지 않음.','web_msd_splint_exostoses'),
 ('중수골근위부비대','disease_or_anatomic_condition','musculoskeletal','중수골 근위부의 비대라는 해부학적 소견. 원문에 적힌 뼈 번호·부위는 보존하며 비대 원인은 별도 영상·진료로 확인해야 함.','web_msd_splint_exostoses'),
 ('비절내종','disease_or_anatomic_condition','musculoskeletal','비절 안쪽의 뼈·관절에 생기는 퇴행성 관절염(bone spavin). 원문 표현만으로 개별 말의 단계나 통증은 알 수 없음.','web_kra_racing_glossary'),
 ('비절연종','disease_or_anatomic_condition','musculoskeletal','비절의 앞·안쪽 관절낭에 활액이 차서 부어 보이는 상태(bog spavin). 부종의 원인과 임상적 의미는 원문만으로 확정되지 않음.','web_kra_racing_glossary'),
 ('슬개골상방고정','disease_or_anatomic_condition','musculoskeletal','슬개골 안쪽 인대가 대퇴골 활차융기에 걸려 무릎관절이 펴진 채 고정되는 상태(upward fixation of the patella). 좌우 표기는 원문을 따름.','web_msd_patellar_fixation'),
 ('이단성골연골염','disease_or_anatomic_condition','musculoskeletal','이단성 골연골염(osteochondritis dissecans, OCD)은 말의 골연골증 계열 병변으로, 관절 연골 또는 연골하골에 병변이 생기고 연골·골연골이 분리될 수 있는 상태다. 이 원문만으로 영상 소견, 병변 크기, 임상 증상은 알 수 없음.','web_msd_osteochondrosis'),
 ('피부사상균증','disease','skin','피부·털에 생기는 피부사상균 감염(dermatophytosis, ringworm).','web_msd_dermatophytosis'),
 ('바이러스성유두종증','disease','skin','바이러스성 유두종(사마귀 모양 증식)이 생기는 말의 질환군. 세부 유형과 발생 부위는 원문만으로 특정하지 않음.','web_equine_papillomatosis'),
 ('위식체','disease','digestive','위 안에 마르고 단단한 내용물이 지속적으로 쌓여 정체된 상태(gastric impaction). 개별 원인과 진단 확정 여부는 원문만으로 알 수 없음.','web_wiley_gastric_impaction'),
 ('마횡문근변성증','disease','musculoskeletal_or_metabolic','운동과 관련해 골격근이 손상·괴사하는 운동성 횡문근융해증(exertional rhabdomyolysis) 계열. 원문만으로 원인 아형은 특정하지 않음.','web_msd_exertional_myopathy'),
 ('이물섭취증','behavior_or_condition','behavioral_or_digestive','흙·모래·기타 먹을 수 없는 물질을 먹는 행동(pica/geophagia 등). 행동 기록만으로 원인 질환을 특정하지 않음.','web_msd_horse_behaviour'),
 ('부비강낭종','disease','respiratory_or_sinus','말의 부비강 안에 생겨 자랄 수 있는 액체가 찬 낭성 병변(paranasal sinus cyst). 부위와 범위는 원문만으로 특정하지 않음.','web_tamu_sinus_cyst'),
 ('위선부궤양','disease','digestive','위의 선부(glandular mucosa)에 생긴 궤양(equine glandular gastric disease).','web_msd_gastric_ulcers'),
 ('제3완골연골하골낭','disease_or_anatomic_condition','musculoskeletal','제3완골의 연골 바로 밑 뼈에 생긴 낭성 병변(subchondral cyst-like lesion). 정확한 위치·크기·관절 침범은 기록만으로 알 수 없음.','web_merck_subchondral_cysts'),
 ('원발성근위종자골골증식증','disease_or_anatomic_condition','musculoskeletal','근위 종자골에 골성 증식이 생긴 병변. 계인대 관련성 표기는 원문대로 보존하며, 부착부 병변과 종자골 골성 변화의 세부 관계는 영상·진찰 없이 더 좁혀 말하지 않음.','web_sesamoid_lesions'),
 ('구근통','symptom','musculoskeletal','발굽 뒤쪽의 둥근 구근(heel bulbs) 부위 통증이라는 증상 표현. 원인이나 조직 손상 여부는 원문만으로 확정할 수 없음.','web_bhs_heel_bulb'),
 ('욕창','injury','skin','지속적인 압박·마찰로 피부와 아래 조직에 생긴 압박성 궤양(pressure sore). 부위와 깊이는 원문만으로 알 수 없음.','web_msd_saddle_sore'),
 ('제저티눈','injury','musculoskeletal','발굽 바닥의 티눈(corn): 보통 제저 특정 부위의 압박·타박으로 인한 멍/출혈성 손상으로 쓰임. 깊이와 통증 정도는 원문만으로 알 수 없음.','web_petmd_hoof_corn'),
 ('중수부계인대관련성원발성근위종자골골증식증','disease_or_anatomic_condition','musculoskeletal','계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 긴 진단 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음.','web_sesamoid_lesions'),
 ('계인대관련성원발성근위종자골골증식증','disease_or_anatomic_condition','musculoskeletal','계인대가 붙는 근위 종자골 부위의 골성 증식 병변을 가리키는 표현. 개별 병변의 구조와 범위는 원문만으로 확정하지 않음.','web_sesamoid_lesions'),
 ('지근관증후군','disease_or_anatomic_condition','musculoskeletal','앞다리 완관절 뒤쪽의 근관(수근관) 안에서 굴건·건초·굴근지대 등 주변 구조의 병변이나 부종으로 문제가 생기는 말의 carpal canal syndrome. 원문에 기록된 증후군 이름까지만 풀이하며, 원인 병변은 특정하지 않음.','web_aaep_carpal_canal_syndrome'),
 ('근위축','symptom_or_condition','musculoskeletal','근육량이 줄어든 소견. `특발성 좌경부 근위축`은 원문상 왼쪽 목 부위 근육 위축이며 원인을 특정하지 못했다고 기록한 표현으로 해석됨. 근위축의 원인과 임상적 의미는 별도 평가가 필요함.','web_equine_cervical_atrophy'),
 ('비절외종','disease_or_anatomic_condition','musculoskeletal','한국마사회 사전은 비절내종과 유사한 비절 부위의 병변·종창 표현으로 비절외종을 함께 열거하지만, 이 항목의 독립된 정확한 병태는 별도로 정의하지 않음. 따라서 비절 부위 병변이라는 수준까지만 풀이하고 세부 진단은 미확정으로 둠.','web_kra_racing_glossary'),
 ('부정맥','disease_or_symptom','circulatory','심장 박동의 발생 또는 전도 리듬이 비정상적인 상태(arrhythmia). 종류와 임상적 의미는 원문만으로 특정하지 않음.','web_msd_arhythmia'),
 ('개봉술','treatment','respiratory_or_sinus','부비강에 접근하기 위해 안면골에 구멍을 내는 개방·천공 수술(개동술/trephination 계열). 수술명만으로 정확한 접근 부위나 적응증은 확정하지 않음.','web_msd_paranasal_sinuses'),
]
WEB_ROOTS.sort(key=lambda x:len(x[0]),reverse=True)

# Exact descriptions read from KRA's term-detail UI or official glossary.
EXACT = {
 '정치': ('treatment', 'dental_oral', '치아의 이상 마모를 수동·자동 정치기구로 교정하는 치과 처치. 병명이나 건강 확인 자체를 뜻하지 않음.', 'kra_profile_tooltip'),
 '낭치': ('disease_or_anatomic_condition', 'dental_oral', '재갈이 닿을 수 있는 위치에 나는 늑치(wolf tooth). 문제가 있으면 검사 후 발치할 수 있음.', 'kra_profile_tooltip'),
 '복대상': ('injury', 'skin', '복대끈 마찰로 아래가슴에 생기는 상처(girth wound). 부종·피부 마찰·감염 가능성이 설명되며, 이 문구만으로 상처 정도는 알 수 없음.', 'kra_profile_tooltip'),
 '의사선역': ('disease', 'lymphatic_or_infectious', 'KRA 표기: Pseudostreptococcus equi infection. 선역으로 알려진 감염 용어이며 림프절 농양이 나타날 수 있음. 개별 기록의 검사 확진 여부는 별도 확인 필요.', 'kra_profile_tooltip'),
 '안상': ('injury', 'skin', '안장·복대의 지속적인 마찰로 등성마루 등에 생기는 saddle sore(피부 상처).', 'kra_official_glossary'),
 '관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '관골(앞다리 완관절~구절 사이 또는 뒷다리 비절~구절 사이 뼈)에 생기는 외골증(splints). 통증·열감·파행 여부에 따라 상태가 다름.', 'kra_official_glossary'),
 '좌전관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '왼쪽 앞다리 관골의 외골증(splints). 관골류가 있다고 모두 통증·파행이 있는 것은 아니며, 구체 임상 상태는 따로 확인해야 함.', 'kra_official_glossary'),
 '우전관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '오른쪽 앞다리 관골의 외골증(splints). 관골류가 있다고 모두 통증·파행이 있는 것은 아니며, 구체 임상 상태는 따로 확인해야 함.', 'kra_official_glossary'),
 '양전관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '양쪽 앞다리 관골의 외골증(splints). 관골류가 있다고 모두 통증·파행이 있는 것은 아니며, 구체 임상 상태는 따로 확인해야 함.', 'kra_official_glossary'),
 '좌후관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '왼쪽 뒷다리 관골의 외골증(splints). 관골류가 있다고 모두 통증·파행이 있는 것은 아니며, 구체 임상 상태는 따로 확인해야 함.', 'kra_official_glossary'),
 '우후관골류': ('disease_or_anatomic_condition', 'musculoskeletal', '오른쪽 뒷다리 관골의 외골증(splints). 관골류가 있다고 모두 통증·파행이 있는 것은 아니며, 구체 임상 상태는 따로 확인해야 함.', 'kra_official_glossary'),
 '수종': ('symptom_or_condition', 'unknown', '조직에 체액이 고여 붓는 상태(부종). 원인과 발생 부위는 원문만으로 특정할 수 없음.', 'literal_medical_term'),
 '루관폐색': ('disease_or_anatomic_condition', 'eye', '눈물 배출 통로(누관·비루관)가 막힌 상태로 풀이되는 용어. 막힌 위치는 기록별 확인 필요.', 'literal_medical_term'),
 '좌전루관폐색': ('disease_or_anatomic_condition', 'eye', '왼쪽 눈물 배출 통로(누관·비루관)가 막힌 상태로 풀이되는 용어.', 'literal_medical_term'),
 '좌비루관폐색': ('disease_or_anatomic_condition', 'eye', '왼쪽 비루관(눈물 배출 통로)이 막힌 상태.', 'literal_medical_term'),
 '우비루관폐색': ('disease_or_anatomic_condition', 'eye', '오른쪽 비루관(눈물 배출 통로)이 막힌 상태.', 'literal_medical_term'),
 '우각막기질궤양': ('disease_or_injury', 'eye', '오른쪽 눈 각막의 기질층에 생긴 궤양.', 'literal_medical_term'),
 '육아종': ('disease_or_anatomic_condition', 'unknown', '염증 반응으로 면역세포 등이 뭉쳐 형성된 결절성 조직(육아종). 위치와 원인은 문구만으로 알 수 없음.', 'literal_medical_term'),
 '과잉육아조직': ('disease_or_anatomic_condition', 'skin', '상처 회복 과정에서 육아조직이 지나치게 자란 상태(exuberant granulation tissue).', 'literal_medical_term'),
 '식도폐색(식도경색)': ('disease', 'digestive', '식도 안에 사료 등이 걸려 통과가 막힌 상태(식도폐색). 괄호 속 원문 표현을 그대로 보존함.', 'literal_medical_term'),
 '림프절염(림프선염)': ('disease', 'lymphatic', '림프절에 생긴 염증. 괄호 안 동의 표현도 원문 그대로 보존함.', 'literal_medical_term'),
 '직장탈': ('disease_or_anatomic_condition', 'digestive', '직장 일부가 항문 밖으로 밀려나오는 상태(직장 탈출).', 'literal_medical_term'),
 '수송열': ('disease', 'systemic', '수송 스트레스와 관련해 발열·호흡기 증상이 나타나는 질환을 가리키는 용어.', 'kra_official_glossary'),
 '치성낭포': ('disease_or_anatomic_condition', 'dental_oral', '치아와 관련해 생긴 낭성 병변(치성 낭포). 위치와 크기는 원문만으로 알 수 없음.', 'literal_medical_term'),
 '나사고정술': ('treatment', 'musculoskeletal', '나사를 사용해 골절 또는 뼈 조각을 고정하는 수술 방법. 적응증은 별도 진료기록에서 확인해야 함.', 'literal_medical_term'),
 '폐렴': ('disease', 'respiratory', '폐 조직에 생긴 염증(폐렴).', 'literal_medical_term'),
 '좌슬개골상방고정': ('disease_or_anatomic_condition', 'musculoskeletal', '왼쪽 슬개골이 정상 위치보다 위쪽에 걸려 고정되는 상태(upward fixation of the patella).', 'literal_medical_term'),
 '우전 제저농양': ('disease', 'musculoskeletal', '오른쪽 앞발굽 바닥(제저)에 고름집이 생긴 상태(농양).', 'literal_medical_term'),
 '후두성형술': ('treatment', 'respiratory_or_laryngeal', '후두 구조를 교정하는 수술. 수술명만으로 적응증·회복 상태를 알 수 없음.', 'literal_medical_term'),
 '잠복고환': ('disease_or_anatomic_condition', 'reproductive', '고환이 정상적으로 음낭 안에 내려오지 않은 상태(cryptorchidism).', 'literal_medical_term'),
 '지골류': ('disease_or_anatomic_condition', 'musculoskeletal', 'KRA 경마용어사전에서 환골류와 함께 ringbone으로 표기하는 발가락뼈 주변 골성 증식 표현. 구체 부위·범위·증상은 개별 기록으로 확인해야 함.', 'web_kra_racing_glossary_ringbone'),
 '관골 골막염': ('disease_or_injury', 'musculoskeletal', '관골을 싸는 골막에 생기는 염증. 충격·타박·피로골절과 관련될 수 있음.', 'kra_official_glossary'),
 '견파행': ('symptom', 'musculoskeletal', '앞다리 움직임이 부자연스럽고 절뚝거리는 증상 표현. 어깨가 원인이라고 확정하는 병명이 아님.', 'kra_official_glossary'),
 '관파행': ('symptom', 'musculoskeletal', '뒷다리 문제로 절뚝거리는 증상 표현. 정확한 원인 부위가 확정된 진단명은 아님.', 'kra_official_glossary'),
 '파행': ('symptom', 'musculoskeletal', '걷거나 뛸 때 보행이 비정상적이거나 절뚝거리는 증상. 원인 질환은 별도 진단이 필요함.', 'kra_official_glossary'),
 '낭치제거': ('treatment', 'dental_oral', '늑치(wolf tooth)를 발치하는 치과 처치.', 'kra_profile_tooltip'),
 '치아이상': ('disease_or_anatomic_condition', 'dental_oral', '치아 이상을 묶어 부르는 넓은 표현. KRA 출주마 병력에서는 늑치 제거·어금니 정치 등이 포함될 수 있어 구체 상태는 상세 처치와 함께 확인해야 함.', 'kra_official_glossary'),
 '치아 이상': ('disease_or_anatomic_condition', 'dental_oral', '치아 이상을 묶어 부르는 넓은 표현. 구체 치아 상태와 처치 여부는 이 문구만으로 확정할 수 없음.', 'kra_official_glossary'),
 '비정상 치아 마모': ('disease_or_anatomic_condition', 'dental_oral', '어금니 등이 비정상적으로 닳거나 뾰족해지는 치아 상태. 뺨 통증·저작 문제를 일으킬 수 있고 치아를 갈아 교정하기도 함.', 'kra_official_glossary'),
 '운동기인성폐출혈': ('disease_or_symptom', 'respiratory', '운동과 관련해 폐에서 출혈이 발생했다는 용어(EIPH). 공식 발생 사건·횟수·제재 여부는 별도 출처로 확인해야 함.', 'kra_record_term'),
 '비출혈': ('symptom', 'respiratory_or_nasal', '코에서 피가 나는 증상(epistaxis). 이 용어만으로 운동기인성 폐출혈 또는 공식 폐출혈 사건이라고 확정하지 않음.', 'literal_medical_term'),
 '일,열사병': ('disease', 'systemic', '열사병(heat stroke). 강한 열 노출과 탈수·탈진 상태를 가리키는 용어. 내부 쉼표가 있어도 한 용어로 보존.', 'user_supplied_kra_definition'),
 '마비성근색소뇨증': ('disease', 'musculoskeletal_or_metabolic', '운동 뒤 근육 손상과 근색소(미오글로빈) 배출이 나타나는 질환(다발성 근염/운동 후 근육 손상 증후군 계열). 세부 아형은 원문만으로 특정하지 않음.', 'literal_medical_term'),
 '좌후두편마비': ('disease', 'respiratory_or_laryngeal', '왼쪽 후두의 반쪽 마비. 후두 기능과 호흡에 영향을 주는 상태.', 'literal_medical_term'),
 '후두개포착': ('disease_or_anatomic_condition', 'respiratory_or_laryngeal', '후두개가 주변 조직에 비정상적으로 덮이거나 고정되는 상태(epiglottic entrapment).', 'literal_medical_term'),
 '연구개배측변위': ('disease_or_anatomic_condition', 'respiratory_or_upper_airway', '연구개가 정상 위치에서 위쪽으로 이동하는 상태(dorsal displacement of the soft palate).', 'literal_medical_term'),
 '운동기질환 기타': ('unspecified_diagnosis_group', 'musculoskeletal', '운동기 질환의 구체 병명을 적지 않은 기타 분류. 특정 질환을 뜻하지 않음.', 'literal_category_label'),
 '호흡기질환기타': ('unspecified_diagnosis_group', 'respiratory', '호흡기 질환의 구체 병명을 적지 않은 기타 분류.', 'literal_category_label'),
 '외상기타': ('unspecified_diagnosis_group', 'unknown', '구체 외상명을 적지 않은 기타 분류.', 'literal_category_label'),
 '기타': ('unspecified_diagnosis_group', 'unknown', '세부 내용이 생략된 기타 분류. 무엇을 가리키는지 원문만으로 판별 불가.', 'literal_category_label'),
 '마체검사': ('examination', 'whole_body', '말의 몸 상태를 확인하는 검사. 검사명만으로 특정 질환이나 결과를 알 수 없음.', 'literal_medical_term'),
 '건강검진': ('examination', 'whole_body', '질병·건강 상태 확인을 위한 검진. 검사 결과나 건강함을 뜻하는 진단은 아님.', 'literal_medical_term'),
 '의동': ('disease_or_anatomic_condition', 'musculoskeletal', '발굽 앞쪽에서 감각 제엽과 무감각 제엽이 분리되고 그 틈에 오염·감염이 생길 수 있는 의동(seedy toe). 개별 말에서의 범위·감염 여부는 원문만으로 판단할 수 없음.', 'kra_official_glossary'),
 '진드기교창': ('disease_or_injury', 'skin_or_infectious', 'KRA 말정보 툴팁은 TICK BITES로 표기한다. 진드기 물림 기록으로 풀이되며, 툴팁은 진드기 종류와 말 전염병·진드기 마비 가능성을 설명한다. 이 문구만으로 해당 말의 감염 여부는 알 수 없음.', 'kra_profile_tooltip'),
 '과잉익상추벽': ('disease_or_anatomic_condition', 'respiratory_or_upper_airway', 'KRA 말정보 툴팁의 REDUNDANT ALAR FOLDS. 상부기도를 부분적으로 폐쇄하는 상태라고 설명한다. 구체 병태·정도는 원문만으로 특정하지 않음.', 'kra_profile_tooltip'),
 '구개연종(구개종)': ('disease_or_anatomic_condition', 'dental_oral', 'KRA 말정보 툴팁의 LAMPAS. 앞니(절치) 뒤쪽 구개 연부조직이 붓는 상태라고 설명한다. 붓기의 원인·정도는 이 용어만으로 확정되지 않음.', 'kra_profile_tooltip'),
 '지연발정정지기': ('disease_or_anatomic_condition', 'reproductive', 'KRA 말정보 툴팁의 PROLONGED DIESTRUS(지속성 발정휴지기/황체기). 정상 자궁을 가진 암말에서 불충분한 PG 분비 또는 출혈체의 존재로 황체 분해가 되지 않아 나타난다고 설명한다. AAEP 자료도 prolonged diestrus를 지속 황체(persistent corpus luteum)와 연결한다. KRA 원문에 있는 `0차 항체` 표현은 원문 표기를 보존했으며 별도 교정·해석하지 않음.', 'kra_profile_tooltip'),
 '운동기인성피로회복': ('treatment', 'musculoskeletal_or_systemic', 'KRA 말정보 툴팁의 FATIGUE HEAL. 운동 뒤 말의 근육 피로를 풀어주기 위한 처치로, 통상 피로회복처치라고도 설명한다. 독립 병명으로 보지 않음.', 'kra_profile_tooltip'),
 '각막?': ('disease', 'eye', '원문은 `각막?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `각막염`이 따로 표시된다. KRA 툴팁의 KERATITIS는 각막의 염증이라고 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '운동기인성피?': ('treatment', 'musculoskeletal_or_systemic', '원문은 `운동기인성피?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `운동기인성 피로회복`이 표시된다. 툴팁은 운동 후 근육 피로 회복 처치라고 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '좌제3': ('disease_or_injury', 'musculoskeletal', '원문은 `좌제3`으로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `좌제3중수골골막염`이 표시된다. KRA 툴팁은 왼쪽 앞다리 제3중수골 배측면의 압박·외상에 따른 골막하출혈 및 미세골절 소견으로 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '정장처?': ('treatment', 'digestive_or_systemic', '원문은 `정장처?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `정장처치`가 표시된다. 툴팁은 혈중 전해질 불균형 교정과 소화관 정상화를 위한 처치라고 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '양전?': ('disease', 'musculoskeletal', '원문은 `양전?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `양전제염`이 표시된다. 툴팁은 양쪽 앞발굽의 일반적 염증성 질환이라고 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '우후지?': ('symptom', 'musculoskeletal', '원문은 `우후지?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `우후지파행`이 표시된다. 툴팁은 오른쪽 뒷다리의 비정상 보행·절음으로 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '좌완관?': ('disease', 'musculoskeletal', '원문은 `좌완관?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `좌완관절염`이 표시된다. 툴팁은 왼쪽 앞다리 완관절의 관절염으로 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '우비절부?': ('injury', 'skin', '원문은 `우비절부?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `우비절부 찰과상`이 표시된다. 툴팁은 오른쪽 뒷다리 비절 부위 피부 표면의 마찰성 외상으로 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '발목피부?': ('disease', 'skin', '원문은 `발목피부?`로 잘려 있으나, 같은 말의 같은 진료일 KRA 기록에는 `발목피부염(계군)`이 표시된다. 툴팁은 발목·발굽 뒤꿈치 부위의 가피성 지루성 피부염(pastern dermatitis)이라고 풀이한다. 원문 문자열 자체는 수정하지 않음.', 'kra_profile_tooltip'),
 '좌중족부찰과상': ('injury', 'musculoskeletal_or_skin', 'KRA 말정보 툴팁의 ABRASION OF L. METATARSUS. 왼쪽 뒷다리 중족부 피부 표면에 생긴 마찰성 외상이라고 풀이한다.', 'kra_profile_tooltip'),
 '좌후 구절부 찰과상': ('injury', 'musculoskeletal_or_skin', 'KRA 말정보 툴팁의 ABRASION OF LH. FETLOCK. 왼쪽 뒷다리 구절 피부 표면에 생긴 마찰성 외상이라고 풀이한다.', 'kra_profile_tooltip'),
 '우비절부 찰과상': ('injury', 'musculoskeletal_or_skin', 'KRA 말정보 툴팁의 ABRASION OF R. HOCK. 오른쪽 뒷다리 비절 피부 표면에 생긴 마찰성 외상이라고 풀이한다.', 'kra_profile_tooltip'),
 '발목피부염(계군)': ('disease', 'skin', 'KRA 말정보 툴팁의 PASTERN DERMATITIS(= SCRATCHES, GREASE HEEL, MUD FEVER, CRACKED HEEL). 발목·발굽 뒤꿈치 부위의 가피성 지루성 피부염이라고 풀이한다.', 'kra_profile_tooltip'),
 '양전제염': ('disease', 'musculoskeletal', 'KRA 말정보 툴팁의 BF. HOOF INFLAMMATION. 양쪽 앞발굽의 외상 등 여러 원인으로 생기는 일반적인 염증성 질환이라고 풀이한다.', 'kra_profile_tooltip'),
 '우후지파행': ('symptom', 'musculoskeletal', 'KRA 말정보 툴팁의 RH. LAMENESS. 오른쪽 뒷다리의 비정상 보행·절음으로 풀이한다.', 'kra_profile_tooltip'),
 '좌완관절염': ('disease', 'musculoskeletal', 'KRA 말정보 툴팁의 L. CARPAL JOINT DISEASE. 왼쪽 앞다리 완관절의 관절염이라고 풀이한다.', 'kra_profile_tooltip'),
 '좌제3중수골골막염': ('disease_or_injury', 'musculoskeletal', 'KRA 말정보 툴팁의 PERIOSTITIS & FRACTURE OF THE DORSAL METACARPUS. 왼쪽 앞다리 제3중수골 배측면의 압박·외상에 따른 골막하출혈 및 미세골절 소견이라고 풀이한다.', 'kra_profile_tooltip'),
 '정장처치': ('treatment', 'digestive_or_systemic', 'KRA 말정보 툴팁의 TONIC. 혈중 전해질 불균형 교정과 소화관 정상화를 위한 처치라고 풀이한다.', 'kra_profile_tooltip'),
 '찰과?': ('injury', 'skin', '사용자가 해당 KRA 진료기록의 글자를 `찰과상`으로 확인했다. 피부 표면이 쓸려 벗겨진 상처를 뜻하며, 부위·깊이는 이 원문에서 확인할 수 없다. 원문 `찰과?` 표기는 그대로 보존한다.', 'user_visual_confirmation'),
}

# Manual audit trail from the horse-specific KRA profile pages. The date and
# horse connect a component visible on that profile to the original comma term.
KRA_TOOLTIP_AUDIT_ROWS = [
 {'term_id':412,'raw_text':'진드기교창','horse_name':'미라클골드','kra_horse_id':'0036885','clinic_date_local':'2018-06-09','kra_displayed_term':'진드기교창','english_label':'TICK BITES','kra_tooltip_text':'대부분이 Hard tick이며 ear tick만 가시가 있고 진드기는 equine babesiosis 와 Ehrlichia equi를 전염시킬 수 있으며 tick paralysis를 유발할 수도 있음','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':654,'raw_text':'운동기인성피로회복,각막?','horse_name':'정석','kra_horse_id':'0011497','clinic_date_local':'2003-09-20','kra_displayed_term':'운동기인성 피로회복','english_label':'FATIGUE HEAL','kra_tooltip_text':'운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함','review_result':'component_matched_by_horse_and_date'},
 {'term_id':654,'raw_text':'운동기인성피로회복,각막?','horse_name':'정석','kra_horse_id':'0011497','clinic_date_local':'2003-09-20','kra_displayed_term':'각막염','english_label':'KERATITIS','kra_tooltip_text':'눈의 각막에 발생하는 염증으로 경주마의 경우 주로의 모래가 튀어올라 눈에 맞음으로써 잘 발생하며 조교나 주로직후 각막세척과 치료를 적절히 하지 않으면 악화되기 쉽고, 간혹 채찍 등으로 인한 외상, 안구사상충 등의 기생충이나 화학물질에 의해서도 발생할 수 있음','review_result':'component_matched_by_horse_and_date'},
 {'term_id':654,'raw_text':'운동기인성피로회복,각막?','horse_name':'브라보걸','kra_horse_id':'0012056','clinic_date_local':'2003-10-05','kra_displayed_term':'운동기인성 피로회복','english_label':'FATIGUE HEAL','kra_tooltip_text':'운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함','review_result':'component_matched_by_horse_and_date'},
 {'term_id':654,'raw_text':'운동기인성피로회복,각막?','horse_name':'브라보걸','kra_horse_id':'0012056','clinic_date_local':'2003-10-05','kra_displayed_term':'각막염','english_label':'KERATITIS','kra_tooltip_text':'눈의 각막에 발생하는 염증으로 경주마의 경우 주로의 모래가 튀어올라 눈에 맞음으로써 잘 발생하며 조교나 주로직후 각막세척과 치료를 적절히 하지 않으면 악화되기 쉽고, 간혹 채찍 등으로 인한 외상, 안구사상충 등의 기생충이나 화학물질에 의해서도 발생할 수 있음','review_result':'component_matched_by_horse_and_date'},
 {'term_id':656,'raw_text':'운동기인성피로회복,찰과?','horse_name':'남대풍','kra_horse_id':'0015321','clinic_date_local':'2003-09-20','kra_displayed_term':'','english_label':'','kra_tooltip_text':'진료사항 페이지 1–10까지 확인했으나 2003-09-20 기록은 노출되지 않았다. 페이지 10에 표시된 가장 오래된 진료일은 2008-05-12였다.','review_result':'not_visible_in_available_KRA_profile_pages'},
 {'term_id':656,'raw_text':'운동기인성피로회복,찰과?','horse_name':'남대풍','kra_horse_id':'0015321','clinic_date_local':'2003-09-20','kra_displayed_term':'찰과상','english_label':'','kra_tooltip_text':'사용자가 해당 말의 KRA 진료기록에서 `찰과?`가 `찰과상`으로 표시된 것을 확인함. 이전 페이지 열람에서는 해당 날짜 원기록을 확인할 수 없었음.','review_result':'meaning_confirmed_by_user_visual_review'},
 {'term_id':664,'raw_text':'우전구절염,운동기인성피?','horse_name':'당대한','kra_horse_id':'0011977','clinic_date_local':'2003-09-25','kra_displayed_term':'우전구절염','english_label':'RF FETLOCK JOINT DISEASE','kra_tooltip_text':'오른쪽 앞다리 구절의 관절염','review_result':'component_matched_by_horse_and_date'},
 {'term_id':664,'raw_text':'우전구절염,운동기인성피?','horse_name':'당대한','kra_horse_id':'0011977','clinic_date_local':'2003-09-25','kra_displayed_term':'운동기인성 피로회복','english_label':'FATIGUE HEAL','kra_tooltip_text':'운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함','review_result':'component_matched_by_horse_and_date'},
 {'term_id':667,'raw_text':'운동기인성피로회복,좌제3','horse_name':'오리온킹','kra_horse_id':'0012235','clinic_date_local':'2003-09-27','kra_displayed_term':'좌제3중수골골막염','english_label':'PERIOSTITIS & FRATURE OF THE DORSAL METACARPUS','kra_tooltip_text':'왼쪽 앞다리 제3중수골 배측면에 압박이 가해지거나 외상의 결과로 골막하출혈 및 미세골절 나타남으로써 보이는 증상','review_result':'component_matched_by_horse_and_date'},
 {'term_id':667,'raw_text':'운동기인성피로회복,좌제3','horse_name':'오리온킹','kra_horse_id':'0012235','clinic_date_local':'2003-09-27','kra_displayed_term':'운동기인성 피로회복','english_label':'FATIGUE HEAL','kra_tooltip_text':'운동후 말의 근육피로를 풀어주기 위한 처치를 포함하며, 통상 피로회복처치 라고도 함','review_result':'component_matched_by_horse_and_date'},
 {'term_id':675,'raw_text':'과잉익상추벽','horse_name':'땡큐','kra_horse_id':'0013387','clinic_date_local':'2003-10-02','kra_displayed_term':'과잉익상추벽','english_label':'REDUNDANT ALAR FOLDS','kra_tooltip_text':'부분적으로 상부기도를 폐쇄','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':680,'raw_text':'좌후구절부찰과상,정장처?','horse_name':'지덕장','kra_horse_id':'0012281','clinic_date_local':'2003-10-06','kra_displayed_term':'정장처치','english_label':'TONIC','kra_tooltip_text':'혈중 전해질 불균형 교정과 소화관의 정상화를 위한 처치','review_result':'component_matched_by_horse_and_date'},
 {'term_id':680,'raw_text':'좌후구절부찰과상,정장처?','horse_name':'지덕장','kra_horse_id':'0012281','clinic_date_local':'2003-10-06','kra_displayed_term':'좌후 구절부 찰과상','english_label':'ABRASION OF LH. FETLOCK','kra_tooltip_text':'비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 구절 부위 피부의 표면에 입는 외상','review_result':'component_matched_by_horse_and_date'},
 {'term_id':688,'raw_text':'림프관염(임파관염),양전?','horse_name':'컴플리트클래스','kra_horse_id':'0015207','clinic_date_local':'2003-10-10','kra_displayed_term':'림프관염(임파관염)','english_label':'LYMPHANGEITIS','kra_tooltip_text':'림프관의 염증, 급성 림프관염은 림프관계에 세균감염의 파급에 의하여 발생하며, 림프관의 경로에 따라 피하에 붉은 동통성 선조(線條)가 나타남.','review_result':'component_matched_by_horse_and_date'},
 {'term_id':688,'raw_text':'림프관염(임파관염),양전?','horse_name':'컴플리트클래스','kra_horse_id':'0015207','clinic_date_local':'2003-10-10','kra_displayed_term':'양전제염','english_label':'BF. HOOF INFLAMMATION','kra_tooltip_text':'양측 앞다리의 발굽에 나타나는 외상등 여러원인에 의해 생기는 일반적인 염증질환','review_result':'component_matched_by_horse_and_date'},
 {'term_id':692,'raw_text':'마비성근색소뇨증,우후지?','horse_name':'영해정','kra_horse_id':'0013356','clinic_date_local':'2003-10-11','kra_displayed_term':'마비성근색소뇨증','english_label':'EXERCISE RELATED MYOPATHY (PARALYTIC MYOGLOBULINURIA, MONDAY MORNING SICKNESS)','kra_tooltip_text':'월요병 이라고도 불리며 근육(횡문근)이 손상되어 마비가 나타나는 근육질병 중의 하나로서, 이름에서도 알수 있듯이 근육속에 함유되어 있는 근색소(마이오글로빈)의 일부가 오줌을 통해 몸 밖으로 배출되기 때문에 쵸콜릿 색깔의 소변을 배설하고, 온몸이 마비되어 뻣뻣하게 서있거나 심한 경우 드러누워 일어나지 못하는 증상을 나타냄.','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':692,'raw_text':'마비성근색소뇨증,우후지?','horse_name':'영해정','kra_horse_id':'0013356','clinic_date_local':'2003-10-11','kra_displayed_term':'우후지파행','english_label':'RH. LAMENESS','kra_tooltip_text':'오른쪽 뒷다리의 비정상적인 보행(다리 절음)의 총칭','review_result':'component_matched_by_horse_and_date'},
 {'term_id':696,'raw_text':'좌중수부계인대염,좌완관?','horse_name':'즐거운하루','kra_horse_id':'0010138','clinic_date_local':'2003-10-14','kra_displayed_term':'좌중수부계인대염','english_label':'DESMITIS OF THE SUSPENSORY LIGAMENT OF THE DEEP MC.','kra_tooltip_text':'왼쪽 앞다리 중수부 계인대의 염증','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':696,'raw_text':'좌중수부계인대염,좌완관?','horse_name':'즐거운하루','kra_horse_id':'0010138','clinic_date_local':'2003-10-14','kra_displayed_term':'좌완관절염','english_label':'L. CARPAL JOINT DISEASE','kra_tooltip_text':'왼쪽 앞다리 완관절의 관절염','review_result':'component_matched_by_horse_and_date'},
 {'term_id':713,'raw_text':'좌중족부찰과상,우비절부?','horse_name':'조타수','kra_horse_id':'0011374','clinic_date_local':'2003-10-23','kra_displayed_term':'우비절부 찰과상','english_label':'ABRASION OF R. HOCK','kra_tooltip_text':'비 정상적인 기계적 마찰에 의하여 오른쪽 뒷다리 비절 부위 피부의 표면에 입는 외상','review_result':'component_matched_by_horse_and_date'},
 {'term_id':713,'raw_text':'좌중족부찰과상,우비절부?','horse_name':'조타수','kra_horse_id':'0011374','clinic_date_local':'2003-10-23','kra_displayed_term':'좌중족부찰과상','english_label':'ABRASION OF L. METATARSUS','kra_tooltip_text':'비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 중족부 부위 피부의 표면에 입는 외상','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':717,'raw_text':'좌중족부찰과상,발목피부?','horse_name':'불비지혜','kra_horse_id':'0011621','clinic_date_local':'2003-10-26','kra_displayed_term':'좌중족부찰과상','english_label':'ABRASION OF L. METATARSUS','kra_tooltip_text':'비 정상적인 기계적 마찰에 의하여 왼쪽 뒷다리 중족부 부위 피부의 표면에 입는 외상','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':717,'raw_text':'좌중족부찰과상,발목피부?','horse_name':'불비지혜','kra_horse_id':'0011621','clinic_date_local':'2003-10-26','kra_displayed_term':'발목피부염(계군)','english_label':'PASTERN DERMATITIS (= SCRATCHES, GREASE HEEL, MUD FEVER, CRACKED HEEL)','kra_tooltip_text':'발목 및 발굽 뒷꿈치 부위의 가피성 지루성 피부염','review_result':'component_matched_by_horse_and_date'},
 {'term_id':714,'raw_text':'좌전제차부란/제차퇴행성?','horse_name':'부움','kra_horse_id':'0012656','clinic_date_local':'2003-10-23','kra_displayed_term':'좌전제차부란(제차퇴행성괴사)','english_label':'LF. THRUSH','kra_tooltip_text':'좌측 앞다리 제차(발굽바닥에 삼각형으로 솟아오른 부위)의 가운데 홈과 외측면 홈의 퇴행성 변화로 괴사조직이 나타남','review_result':'meaning_confirmed_by_user_visual_review'},
 {'term_id':676,'raw_text':'양전구절특발성활막염(구?','horse_name':'인리스티드','kra_horse_id':'0015236','clinic_date_local':'2003-10-02','kra_displayed_term':'양전구절특발성활막염(구건연종)','english_label':'WINDPUFFS','kra_tooltip_text':'관절낭이나 건초에 활액과다로 인한 확장을 의미하며 파행과는 관계가 없음','review_result':'meaning_confirmed_by_user_visual_review'},
 {'term_id':760,'raw_text':'좌척측인대염기인성비부골척측비대/좌비절후종','horse_name':'지석','kra_horse_id':'0013643','clinic_date_local':'2003-11-23','kra_displayed_term':'좌비절후종(좌척측인대염기인성비부골척측비대)','english_label':'L. CURB','kra_tooltip_text':'왼쪽 뒷다리 척측인대의 염증 및 비후로 인하여 종골의 척측면 종창이 나타나는 것','review_result':'meaning_confirmed_by_user_visual_review'},
 {'term_id':689,'raw_text':'좌척측인대염기인성비부골','horse_name':'늘기쁨','kra_horse_id':'0011151','clinic_date_local':'2003-10-11','kra_displayed_term':'좌비절후종(좌척측인대염기인성비부골척측비대)','english_label':'L. CURB','kra_tooltip_text':'왼쪽 뒷다리 척측인대의 염증 및 비후로 인하여 종골의 척측면 종창이 나타나는 것','review_result':'meaning_confirmed_by_user_confirmation_of_canonical_term'},
 {'term_id':1554,'raw_text':'구개연종(구개종)','horse_name':'대한해협','kra_horse_id':'0018341','clinic_date_local':'2005-10-22','kra_displayed_term':'구개연종(구개종)','english_label':'LAMPAS','kra_tooltip_text':'절치 뒷부분의 구개 연부조직의 종창','review_result':'meaning_confirmed_from_KRA_profile_tooltip'},
 {'term_id':4315,'raw_text':'지연발정정지기','horse_name':'홍시','kra_horse_id':'0043366','clinic_date_local':'2020-04-27','kra_displayed_term':'지연발정정지기','english_label':'PROLONGED DIESTRUS','kra_tooltip_text':'정상적인 자궁을 가진 암말이 불충분한 PG분비로 인하거나 출혈체의 존재로 인하여 0차 항체를 분해시키지 못함으로 인해 나타남','review_result':'meaning_confirmed_from_KRA_profile_tooltip_and_user_supplied_definition'},
]
for _r in KRA_TOOLTIP_AUDIT_ROWS:
    _r['source_url'] = PROFILE_TOOLTIP

# Longest phrase first to avoid matching a generic suffix too early.
ROOTS = [
 ('골연골증', 'disease', 'musculoskeletal', '관절 연골과 인접 뼈에 손상·발달 이상이 생기는 골연골 질환.'),
 ('제차부란', 'disease_or_injury', 'musculoskeletal', '발굽 제차(개구리 모양의 탄력 조직)에 부패·퇴행성 변화가 생긴 상태.'),
 ('제차퇴행성괴사', 'disease_or_injury', 'musculoskeletal', '발굽 제차 조직의 퇴행·괴사성 변화.'),
 ('제차탈락', 'disease_or_injury', 'musculoskeletal', '발굽 제차 조직이 떨어져 나간 상태.'),
 ('의동', 'disease_or_anatomic_condition', 'musculoskeletal', '발굽 앞쪽에서 감각 제엽과 무감각 제엽이 분리되고 그 틈에 오염·감염이 생길 수 있는 의동(seedy toe). 개별 말에서의 범위·감염 여부는 원문만으로 판단할 수 없음.'),
 ('지골류', 'disease_or_anatomic_condition', 'musculoskeletal', '발가락뼈 주변의 골성 증식(ringbone). KRA 경마용어사전은 `환골류`와 `지골류`를 함께 표기한다.'),
 ('환골류', 'disease_or_anatomic_condition', 'musculoskeletal', '발가락뼈 주변의 골성 증식(ringbone). KRA 경마용어사전은 `환골류`와 `지골류`를 함께 표기한다.'),
 ('만성폐쇄성폐질환', 'disease', 'respiratory', '만성 기도 염증·폐쇄로 호흡이 어려워지는 질환 표현(COPD 계열).'),
 ('주상골질환증후군', 'disease', 'musculoskeletal', '발굽 안쪽 주상골과 주변 조직의 통증·퇴행성 변화를 포함하는 질환군(navicular syndrome). 개별 기록의 원인·단계는 원문만으로 특정하지 않음.'),
 ('낭축농증', 'disease', 'respiratory_or_upper_airway', '말의 인두낭(guttural pouch)에 고름이 차는 상태(empyema). 원인과 범위는 개별 기록으로 확인해야 함.'),
 ('낭진균증', 'disease', 'respiratory_or_upper_airway', '인두낭(guttural pouch)에 생기는 진균 감염.'),
 ('낭고창증', 'disease_or_anatomic_condition', 'respiratory_or_upper_airway', '인두낭(guttural pouch)에 공기가 차 팽창하는 상태(guttural pouch tympany).'),
 ('무한증', 'disease', 'systemic', '땀을 거의 흘리지 못하는 상태(anhidrosis). 원인과 중증도는 원문만으로 알 수 없음.'),
 ('골연골종', 'disease_or_anatomic_condition', 'musculoskeletal', '뼈와 연골 성분으로 이루어진 골성 증식 또는 종양(osteochondroma). 위치·크기·임상적 의미는 원문만으로 확정할 수 없음.'),
 ('골극', 'disease_or_anatomic_condition', 'musculoskeletal', '뼈 가장자리에 형성된 골성 돌기(osteophyte). 위치·통증 여부는 별도 확인이 필요함.'),
 ('인두허탈', 'disease_or_anatomic_condition', 'respiratory_or_upper_airway', '인두 기도가 좁아지거나 무너지는 상태.'),
 ('비인두허탈', 'disease_or_anatomic_condition', 'respiratory_or_upper_airway', '비인두 기도가 좁아지거나 무너지는 상태.'),
 ('우각막이물', 'disease_or_injury', 'eye', '오른쪽 눈 각막에 이물이 있는 상태.'),
 ('각막기질궤양', 'disease_or_injury', 'eye', '각막의 중간층인 기질에 생긴 궤양.'),
 ('각막상피미란', 'disease_or_injury', 'eye', '각막 표면 상피가 벗겨지거나 손상된 상태.'),
 ('세균성각막궤양', 'disease', 'eye', '세균 감염이 동반된 각막 궤양.'),
 ('각화종', 'disease_or_anatomic_condition', 'musculoskeletal', '발굽 안쪽에서 각질이 자라 공간을 차지하는 병변(keratoma). 위치와 범위는 기록에서 확인해야 함.'),
 ('악액질', 'disease_or_symptom', 'systemic', '만성 질환 등과 함께 나타날 수 있는 심한 체중·근육 감소 상태(cachexia). 원문에서 슬래시로 연결된 `전신쇠약` 표현도 분리하지 않고 그대로 보존한다.'),
 ('뇌진탕', 'injury', 'nervous_system', '외상 뒤 뇌 기능에 일시적 장애가 생기는 손상 표현. 원문만으로 손상 정도를 알 수 없음.'),
 ('이물질', 'disease_or_anatomic_condition', 'unknown', '원문에 적힌 부위에 이물이 존재한다는 표현. 이물 종류와 손상·염증 여부는 별도 확인이 필요함.'),
 ('소화불량', 'symptom_or_condition', 'digestive', '소화가 원활하지 않은 상태를 가리키는 포괄 표현.'),
 ('대결장폐색', 'disease', 'digestive', '대결장 통로가 막힌 상태. 원인과 폐색 정도는 개별 기록으로 확인해야 함.'),
 ('대결장 변비', 'symptom_or_condition', 'digestive', '대결장에 변이 정체되는 변비 표현.'),
 ('열사병', 'disease', 'systemic', '고온 노출로 체온조절이 무너져 전신 상태가 나빠지는 질환.'),
 ('과다치아', 'disease_or_anatomic_condition', 'dental_oral', '정상보다 치아 수가 많은 상태. 어느 치아인지 원문만으로는 알 수 없음.'),
 ('비정상치아맹출', 'disease_or_anatomic_condition', 'dental_oral', '치아가 정상 방향·위치와 다르게 맹출한 상태.'),
 ('계파', 'symptom_or_condition', 'musculoskeletal', '다리 움직임 또는 보행 이상을 나타내는 옛 표현일 수 있어 구체 진단은 원문만으로 확정할 수 없음.'),
 ('꼬리손상', 'injury', 'skin_or_soft_tissue', '꼬리 부위의 손상. 손상 형태와 정도는 원문만으로 알 수 없음.'),
 ('제저타박상', 'injury', 'musculoskeletal', '발굽 바닥(제저)에 생긴 타박상.'),
 ('제관상', 'injury', 'musculoskeletal', '발굽 윗부분의 제관부에 생긴 상처·손상으로 보이는 표현. 세부 손상 형태는 원문만으로 확인 불가.'),
 ('제저상', 'injury', 'musculoskeletal', '발굽 바닥(제저)의 상처·손상.'),
 ('열제', 'disease_or_injury', 'musculoskeletal', '발굽 벽에 생긴 균열·갈라짐(hoof crack). 위치·깊이는 원문만으로 확인 불가.'),
 ('좌창', 'injury', 'skin', '피부·연부조직이 눌리거나 부딪혀 생긴 상처(좌창). 세부 손상 깊이는 원문만으로 알 수 없음.'),
 ('농양', 'disease', 'unknown', '조직 안에 고름이 모여 생긴 농양. 발생 부위는 원문 표기를 따름.'),
 ('외상', 'injury', 'unknown', '외부 충격·사고로 생긴 손상. 부위와 손상 정도는 원문만으로 알 수 없음.'),
 ('창상', 'injury', 'skin', '피부나 연부조직에 생긴 상처.'),
 ('기관내이물', 'anatomic_condition', 'respiratory', '기관 안에 이물이 있다는 위치 소견. 이물 종류·기도 폐쇄·동반 손상 여부는 문구만으로 알 수 없음.'),
 ('안면신경손상', 'injury', 'nervous_system', '얼굴 움직임을 담당하는 안면신경의 손상. 손상 위치·원인·기능 저하는 원문만으로 알 수 없음.'),
 ('바이러스성유두종증', 'disease', 'skin', '바이러스와 관련된 유두종(사마귀 모양 증식)이 생기는 질환 표현. 바이러스 종류와 부위는 원문만으로 특정되지 않음.'),
 ('결절성육아종', 'disease_or_anatomic_condition', 'unknown', '결절 모양의 육아종성 병변이라는 형태 표현. 위치·원인·감염 여부는 이 원문만으로 특정할 수 없음.'),
 ('제종부제벽탈락', 'injury', 'musculoskeletal', '발굽 뒤꿈치(제종부) 쪽 발굽벽의 일부가 떨어져 나간 손상 표현. 범위와 속살 침범 여부는 원문만으로 알 수 없음.'),
 ('욕창', 'injury', 'skin', '지속적인 압박으로 피부·아래 조직이 손상된 욕창(pressure sore). 부위와 깊이는 원문만으로 알 수 없음.'),
 ('화상', 'injury', 'skin', '열원·화학물질 등으로 피부나 조직이 손상된 화상. 원인과 깊이는 원문만으로 알 수 없음.'),
 ('결손창', 'injury', 'skin', '조직 일부가 손실된 상처를 가리키는 표현. 깊이·크기·회복 상태는 원문만으로 알 수 없음.'),
 ('절창', 'injury', 'skin', '날카로운 물체 등에 베이거나 잘려 생긴 상처.'),
 ('백선', 'disease', 'skin', '피부사상균 감염(백선·ringworm) 계열의 피부 질환.'),
 ('후두편마비', 'disease', 'respiratory_or_laryngeal', '후두 한쪽의 마비 상태.'),
 ('잠복고환', 'disease_or_anatomic_condition', 'reproductive', '고환이 정상적으로 음낭 안에 내려오지 않은 상태(cryptorchidism).'),
 ('관골류', 'disease_or_anatomic_condition', 'musculoskeletal', '관골에 생기는 외골증(splints). 좌우·다리 위치가 적히면 그 부위를 함께 보존한다.'),
 ('제저농양', 'disease', 'musculoskeletal', '발굽 바닥(제저)에 고름집이 생긴 상태(농양).'),
 ('구절만성증식성활막염', 'disease', 'musculoskeletal', '구절 관절의 활막이 만성적으로 증식하며 염증이 생긴 상태.'),
 ('구절퇴행성관절염', 'disease', 'musculoskeletal', '구절 관절의 퇴행성 염증·변화.'),
 ('퇴행성관절염', 'disease', 'musculoskeletal', '관절 연골과 주변 조직에 퇴행성 변화와 염증이 생긴 상태.'),
 ('특발성활막염', 'disease', 'musculoskeletal', '명확한 원인이 특정되지 않은 활막 염증.'),
 ('활막염', 'disease', 'musculoskeletal', '관절 안쪽을 싸는 활막의 염증.'),
 ('점액낭염', 'disease', 'musculoskeletal', '관절·힘줄 주변 점액낭에 생긴 염증.'),
 ('봉와직염', 'disease', 'skin', '피부 아래 연부조직에 퍼지는 세균성 염증(cellulitis).'),
 ('림프관염', 'disease', 'lymphatic', '림프관의 염증.'),
 ('임파관염', 'disease', 'lymphatic', '림프관의 염증(림프관염과 같은 표현). 원문은 별도 보존.'),
 ('외이염', 'disease', 'ear', '귓바퀴 안쪽 외이도의 염증.'),
 ('구내염', 'disease', 'dental_oral', '입안 점막의 염증.'),
 ('담마진', 'disease', 'skin', '두드러기(urticaria). 피부에 팽진·가려움이 나타날 수 있는 반응.'),
 ('진드기성외이염', 'disease', 'ear', '진드기 감염과 관련된 외이도 염증.'),
 ('제구염', 'disease', 'musculoskeletal', '발굽 뒤꿈치 쪽 제구에 생긴 염증.'),
 ('제염', 'disease', 'musculoskeletal', '발굽 조직의 염증을 가리키는 표현. 발굽 내 세부 위치는 원문만으로 알 수 없음.'),
 ('열제', 'disease_or_injury', 'musculoskeletal', '발굽 벽에 생긴 균열·갈라짐(hoof crack). 위치·깊이는 원문만으로 확인 불가.'),
 ('고체온증', 'symptom_or_condition', 'systemic', '정상보다 체온이 높아진 상태. 원인과 열사병 여부는 별도 판단.'),
 ('열사병', 'disease', 'systemic', '고온 노출로 체온조절이 무너져 전신 상태가 나빠지는 질환.'),
 ('고환', 'anatomic_condition', 'reproductive', '생식기관 관련 기록. 단어 단독으로 질환 또는 수술 여부를 특정하지 않음.'),
 ('위궤양', 'disease', 'digestive', '위 점막에 생긴 궤양.'),
 ('위염', 'disease', 'digestive', '위 점막의 염증.'),
 ('비염', 'disease', 'respiratory', '코 점막의 염증.'),
 ('후두염', 'disease', 'respiratory_or_laryngeal', '후두 점막의 염증.'),
 ('유방염', 'disease', 'reproductive_or_mammary', '유선(유방)의 염증.'),
 ('우상악동염', 'disease', 'respiratory_or_sinus', '오른쪽 상악동(위턱 쪽 부비동)의 염증.'),
 ('경정맥염', 'disease', 'circulatory', '목의 경정맥에 생긴 염증.'),
 ('마비', 'symptom_or_condition', 'unknown', '신경·근육 기능이 저하되거나 움직이지 않는 상태.'),
 ('경련산', 'disease_or_symptom', 'digestive', '경련성 산통(복부 통증)으로 풀이되는 용어.'),
 ('변비산', 'disease_or_symptom', 'digestive', '변비와 관련된 산통(복부 통증)으로 풀이되는 용어.'),
 ('풍기산', 'disease_or_symptom', 'digestive', '가스 축적과 관련된 산통(복부 통증)으로 풀이되는 용어.'),
 ('계인대염', 'disease_or_injury', 'musculoskeletal', '다리 구절을 지지하는 계인대에 생긴 염증.'),
 ('천지굴건염', 'disease_or_injury', 'musculoskeletal', '천지굴건에 생긴 염증.'),
 ('심지굴건염', 'disease_or_injury', 'musculoskeletal', '심지굴건에 생긴 염증.'),
 ('건초염', 'disease_or_injury', 'musculoskeletal', '힘줄을 둘러싼 건초의 염증.'),
 ('골막염', 'disease_or_injury', 'musculoskeletal', '뼈를 싸는 골막의 염증.'),
 ('인대염', 'disease_or_injury', 'musculoskeletal', '인대에 생긴 염증.'),
 ('건염', 'disease_or_injury', 'musculoskeletal', '힘줄(건)에 생긴 염증.'),
 ('골절', 'injury', 'musculoskeletal', '뼈가 부러지거나 금이 간 손상. 부위와 골절 형태는 원문에서 확인해야 함.'),
 ('탈구', 'injury', 'musculoskeletal', '관절을 이루는 뼈가 정상 위치에서 벗어난 손상.'),
 ('염좌', 'injury', 'musculoskeletal', '관절 주변 인대·연부조직이 늘어나거나 손상된 상태.'),
 ('파열', 'injury', 'musculoskeletal', '조직이 찢어지거나 끊어진 손상. 조직 종류·범위는 원문에서 확인해야 함.'),
 ('단열', 'injury', 'musculoskeletal', '인대·힘줄 등 조직이 끊어진 손상.'),
 ('열창', 'injury', 'skin', '피부 또는 연부조직이 찢어진 상처.'),
 ('각막찰과상', 'injury', 'eye', '눈의 각막 표면이 쓸려 벗겨진 상처(corneal abrasion). 깊이와 범위는 원문만으로 알 수 없음.'),
 ('자창', 'injury', 'skin', '뾰족한 물체에 찔려 생긴 상처.'),
 ('찰과상', 'injury', 'skin', '피부 표면이 쓸려 벗겨진 상처.'),
 ('답창', 'injury', 'skin', '발굽 등에 밟히거나 찍혀 생긴 상처를 나타내는 용어.'),
 ('교돌상', 'injury', 'musculoskeletal', '달릴 때 서로 반대쪽 다리 등이 부딪혀 생긴 상처.'),
 ('추돌상', 'injury', 'musculoskeletal', '달릴 때 뒷다리 발굽이 앞다리 등에 부딪혀 생긴 상처.'),
 ('안상', 'injury', 'skin', '안장 마찰로 생기는 피부 상처(saddle sore).'),
 ('복대상', 'injury', 'skin', '복대끈 마찰로 아래가슴에 생기는 상처(girth wound).'),
 ('타박상', 'injury', 'unknown', '둔한 충격으로 생긴 타박 손상.'),
 ('좌상', 'injury', 'unknown', '압박·충격 등으로 연부조직이 손상된 상태를 가리킬 수 있음. 상세 부위·형태 확인 필요.'),
 ('혈종', 'disease_or_injury', 'unknown', '혈관 밖으로 혈액이 고여 생긴 멍울·부종(혈종).'),
 ('파행', 'symptom', 'musculoskeletal', '절뚝거림 등 비정상 보행 증상. 원인은 별도 진단이 필요함.'),
 ('근육통', 'symptom', 'musculoskeletal', '근육 부위 통증.'),
 ('요배통', 'symptom', 'musculoskeletal', '허리·등 부위 통증.'),
 ('근육염', 'disease', 'musculoskeletal', '근육에 생긴 염증.'),
 ('부종', 'symptom', 'unknown', '조직이 붓는 증상. 원인은 별도 확인이 필요함.'),
 ('동통', 'symptom', 'unknown', '통증 증상.'),
 ('통증', 'symptom', 'unknown', '통증 증상.'),
 ('산통', 'symptom', 'digestive', '말의 복부 통증(colic) 증상. 원인은 다양해 세부 진단은 별도 확인이 필요함.'),
 ('식욕부진', 'symptom', 'digestive', '먹으려는 양이나 식욕이 감소한 증상.'),
 ('설사', 'symptom', 'digestive', '묽거나 잦은 변을 보는 증상.'),
 ('감기', 'disease', 'respiratory', '감기 또는 상기도 호흡기 질환을 가리키는 포괄 표현.'),
 ('기관지염', 'disease', 'respiratory', '기관지에 생긴 염증.'),
 ('각막염', 'disease', 'eye', '눈의 투명한 앞부분인 각막에 생긴 염증.'),
 ('결막염', 'disease', 'eye', '눈꺼풀 안쪽·안구 표면을 덮는 결막의 염증.'),
 ('피부염', 'disease', 'skin', '피부에 생긴 염증.'),
 ('피부병', 'disease', 'skin', '구체 병명이 적히지 않은 피부 질환 표현.'),
 ('염증', 'disease', 'unknown', '염증 상태. 원인·부위의 구체 내용은 문맥에 따라 확인 필요.'),
 ('감염', 'disease', 'unknown', '감염 상태. 병원체·부위는 원문만으로 판별 불가.'),
 ('마비', 'disease_or_symptom', 'unknown', '신경·근육 기능이 저하되거나 움직이지 않는 상태.'),
 ('변위', 'disease_or_anatomic_condition', 'unknown', '조직·구조물이 정상 위치에서 벗어난 상태.'),
 ('포착', 'disease_or_anatomic_condition', 'unknown', '조직·구조물이 비정상적으로 걸리거나 덮이는 상태.'),
 ('기타', 'unspecified_diagnosis_group', 'unknown', '세부 병명이 기재되지 않은 기타 분류.'),
]
ROOTS.sort(key=lambda x: len(x[0]), reverse=True)
ANATOMY = [
 ('제3중수골','제3중수골(앞다리 관골)'),('제3중족골','제3중족골(뒷다리 관골)'),('제1지골','제1지골(발가락뼈)'),('중수골','중수골(앞다리 관골)'),('중족골','중족골(뒷다리 관골)'),('요완골','요완골(앞다리 아래쪽 뼈)'),('대퇴골','대퇴골'),('경골','경골(정강뼈)'),('거골','거골'),('요골','요골'),('척골','척골'),('지골','발가락뼈'),('골반골','골반뼈'),('슬관절','슬관절(무릎관절)'),('주관절','주관절(팔꿈치관절)'),('견관절','견관절(어깨관절)'),('구절','구절 관절'),('비절','비절 관절'),('완관절','완관절'),('계인대','계인대'),('굴건','굴건'),('제차','발굽 제차'),('제저','발굽 바닥'),('제관','발굽 제관부'),('제구','발굽 뒤꿈치'),('제엽','발굽 제엽'),('각막','눈 각막'),('결막','눈 결막'),('안구','눈'),('비루관','눈물 배출 통로(비루관)'),('누낭','눈물주머니(누낭)'),('후낭','인두낭'),('후두','후두'),('연구개','연구개'),('기관지','기관지'),('흉막','흉막'),('폐','폐'),('치은','잇몸(치은)'),('치아','치아'),('낭치','늑치'),('요도','요도'),('자궁','자궁'),('질','질'),('포피','포피'),('중이','중이'),('피열연골','피열연골'),('발목','발목·발굽 뒤쪽'),('복대','복대가 닿는 아래가슴'),('안장','안장 접촉부'),('둔부','엉덩이'),('요배','허리·등'),('근육','근육'),('관절','관절'),('피부','피부'),('위장','위·장'),('위','위'),('장','장')]
ANATOMY += [('제골','발굽뼈'),('제','발굽')]
ANATOMY.sort(key=lambda x:len(x[0]),reverse=True)
LIMB_PREFIX = {'양전':'양쪽 앞다리','양후':'양쪽 뒷다리','좌전':'왼쪽 앞다리','우전':'오른쪽 앞다리','좌후':'왼쪽 뒷다리','우후':'오른쪽 뒷다리'}
SIDE = re.compile(r'^(좌전|우전|양전|좌후|우후|양후|좌|우|양)')
VACCINES = ['인푸렌자','인플루엔자','일본뇌염','선역','파상풍','광견병','예방접종','백신접종']
PROC = ['피로회복','수액처치','물리치료','충격파','진정','장제','술후처치','거세술','거세','탐색적개복술','개복술','원거술','천공술','정복술','적출술','제거술','고정술','인대절단술','수술','절제술','봉합술','발치','구충','치료','처치','주사','정치','침치료','마사지','도수치료','골편적출술']
EXAMS = ['검사','검진','마체검사','방사선','초음파','내시경']
ADMIN = ['재료판매','진단서 발급','증명서 발급','서류발급','확인서 발급','등록','마체확인']

def anatomical_site(text:str, system:str='unknown') -> tuple[str,str]:
    """Return a conservative Korean site phrase and broad body system."""
    clean=text.strip()
    if clean.startswith('동물  '): clean=clean[len('동물  '):]
    # In these historical KRA labels, 후낭 means guttural pouch, not hind limb.
    pouch=re.match(r'^(양후|좌후|우후)낭',clean)
    if pouch:
        side={'양후':'양쪽','좌후':'왼쪽','우후':'오른쪽'}[pouch.group(1)]
        return f'{side} 인두낭', 'respiratory_or_upper_airway'
    limb=SIDE.match(clean)
    if limb and limb.group(1) in LIMB_PREFIX:
        prefix=limb.group(1); rest=clean[len(prefix):]
        non_limb_markers=('안구','각막','결막','비루관','누낭','눈물','후두','인두','자궁','난소','유선','질','포피','치은','치아','낭','폐','흉막','기관지','위장','요도','중이','피열연골')
        if not any(marker in rest for marker in non_limb_markers):
            limb_phrase=LIMB_PREFIX[prefix]
            # When a concrete limb structure follows, keep that detail too.
            for part,meaning in ANATOMY:
                if len(part)>=2 and part in rest:
                    return f'{limb_phrase} {meaning}', 'musculoskeletal'
            return limb_phrase, 'musculoskeletal'
    # Avoid one-character substring matches: e.g. `위` inside `원위단`.
    for part,meaning in ANATOMY:
        if len(part)>=2 and part in clean:
            side=''
            side_match=re.match(r'^(좌|우|양)',clean)
            if side_match:
                side={'좌':'왼쪽','우':'오른쪽','양':'양쪽'}[side_match.group(1)]+' '
            body_system=system
            if body_system=='unknown':
                if any(token in part for token in ('안구','각막','결막','비루관','누낭')): body_system='eye'
                elif any(token in part for token in ('구절','비절','완관','골','지골','제','관절','인대','건','근육')): body_system='musculoskeletal'
                elif any(token in part for token in ('후낭','후두','연구개','기관지','폐','흉막')): body_system='respiratory'
                elif '피열연골' in part: body_system='respiratory_or_laryngeal'
                elif '중이' in part: body_system='ear'
                elif any(token in part for token in ('위','장')): body_system='digestive'
                elif any(token in part for token in ('치은','치아','낭치')): body_system='dental_oral'
                elif part=='요도': body_system='urinary'
            return side+meaning,body_system
    return '',system

def meaning_one(raw:str):
    text=raw
    if text.startswith('동물  '): text=text[len('동물  '):]
    user_visual_confirmed={
        '좌전제차부란/제차퇴행성?': ('disease_or_injury','musculoskeletal','같은 말·진료일의 KRA 상세 표시에서 `좌전제차부란(제차퇴행성괴사) (LF. THRUSH)`로 확인했다. 좌측 앞다리 발굽 제차의 가운데 홈과 외측면 홈에 퇴행성 변화와 괴사조직이 나타나는 병변이라는 사용자 확인 툴팁 설명을 반영한다. DB 원문은 물음표 포함 상태로 보존한다.','user_visual_confirmation','사용자가 같은 말·진료일의 KRA 상세 툴팁을 확인; 원문에 없는 괴사 표기는 설명에만 반영'),
        '양전구절특발성활막염(구?': ('anatomic_condition','musculoskeletal','같은 말·진료일의 KRA 상세 표시에서 `양전구절특발성활막염(구건연종) (WINDPUFFS)`로 확인했다. 구절 관절낭 또는 건초에 활액이 많아져 팽창한 상태이며, KRA 설명은 파행과 관계없다고 한다. DB 원문의 잘린 괄호 표기는 그대로 보존한다.','user_visual_confirmation','사용자가 같은 말·진료일의 KRA 상세 툴팁을 확인; 원문은 보정하지 않음'),
        '좌척측인대염기인성비부골': ('disease_or_anatomic_condition','musculoskeletal','늘기쁨의 이 원문은 사용자가 확인한 `좌비절후종(좌척측인대염기인성비부골척측비대) (L. CURB)`와 같은 병명으로 확정했다. 왼쪽 뒷다리 척측인대의 염증 및 비후로 종골 척측면에 종창이 나타나는 상태. 원문 표기는 그대로 보존하고, 빠진 `척측비대`를 설명에서만 보완한다.','user_visual_confirmation','term_id 760의 사용자 확인 KRA 정의와 늘기쁨(term_id 689)의 동일 병명 여부를 사용자가 확인'),
    }
    if text in user_visual_confirmed:
        return user_visual_confirmed[text]
    if text in EXACT: return (*EXACT[text], '원문과 KRA 용어 설명 대조')
    for root,kind,system,desc,source in WEB_ROOTS:
        if root in text:
            site,parsed_system=anatomical_site(text,system)
            if system=='unknown' and parsed_system!='unknown': system=parsed_system
            lead=f'원문 부위 표기({site})의 기록. ' if site else ''
            return (kind,system,lead+desc,source,f'검색으로 대조한 수의학·경마 사전 어근 `{root}`; 원문 부위 표기는 별도 보존')
    for v in VACCINES:
        if v in text:
            label='예방접종' if '접종' in text or '백신' in text else '예방 항목'
            return ('prevention','unknown',f'{text} 관련 예방접종 기록. 특정 질병이 발생했다는 뜻은 아님.','literal_prevention_rule',f'예방접종 명시 ({label})')
    if text in ADMIN:
        return ('administrative','unknown',f'{text}: 행정·기록 처리 항목이며 질병 진단명이 아님.','literal_admin_rule','항목 이름 자체')
    if any(x in text for x in EXAMS):
        return ('examination','whole_body',f'{text}: 검사·검진 항목. 검사 대상이나 결과·진단은 이 표현만으로 알 수 없음.','literal_exam_rule','검사 표현')
    if any(x in text for x in PROC):
        # Preserve, but do not promote to a confirmed diagnosis, any text in
        # parentheses after a treatment/procedure. Several KRA records encode
        # purpose, indication, or procedure there (e.g. 치료장제(제엽염),
        # 술후처치(거세술), 진정(장제)). The original string is never edited.
        parenthetical=re.findall(r'\(([^()]*)\)',text)
        notes=[]
        for value in parenthetical:
            label=' '.join(value.split())
            if label:
                if text.startswith('진정('):
                    notes.append(f'괄호에는 진정 목적/상황 `{label}`이 표기됨')
                elif text.startswith('술후처치('):
                    notes.append(f'괄호에는 술후 관리와 연결된 수술·상황 `{label}`이 표기됨')
                elif text.startswith('치료장제('):
                    notes.append(f'괄호에는 치료장제의 대상 또는 표기 항목 `{label}`이 함께 기록됨')
                else:
                    notes.append(f'괄호 안에 `{label}`이 함께 기록됨')
        detail=' '.join(notes)
        suffix=f' {detail}. 개별 말에서 해당 병변·적응증의 확진 여부나 중증도는 이 문자열만으로 확인할 수 없음.' if detail else ' 적응증이나 원래 질환은 이 표현만으로 확인 불가.'
        return ('treatment','unknown',f'{text}: 처치·치료·관리 항목.{suffix}','literal_treatment_rule','처치 표현; 괄호 안 문구는 원문대로 보존하고 진단 확정으로 간주하지 않음' if detail else '처치 표현')
    if '인대' in text and text.endswith(('염좌','파열','염좌/파열')):
        site,system=anatomical_site(text,'musculoskeletal')
        lead=f'원문 부위 표기({site})의 기록. ' if site else ''
        return ('injury','musculoskeletal',f'{lead}인대 염좌 또는 파열·손상을 나타내는 표현. 원문이 둘을 함께 적었으므로 손상 형태와 정도는 별도 확인이 필요함.','literal_ligament_injury_rule','`인대`와 `염좌`/`파열` 표현을 우선 적용; 염증 어미 규칙보다 우선')
    # The broad suffix rules follow explicit terms and are intentionally conservative.
    for root,kind,system,desc in ROOTS:
        if root in text:
            site,parsed_system=anatomical_site(text,system)
            if system=='unknown' and parsed_system!='unknown': system=parsed_system
            lead=f'원문 부위 표기({site})의 기록. ' if site else ''
            return (kind,system,lead+desc, 'literal_root_rule',f'원문 어근 `{root}`; 부위는 표기된 경우만 설명')
    if text.endswith('염'):
        site,system=anatomical_site(text,'unknown')
        if system=='unknown' and any(k in text for k in ('골','관절','구절','중수','중족','제','근육','건','인대')):
            system='musculoskeletal'
        elif system=='unknown' and any(k in text for k in ('안구','각막','결막','누낭','비루관')):
            system='eye'
        elif system=='unknown' and any(k in text for k in ('후두','기관지','폐','흉막','후낭')):
            system='respiratory'
        elif system=='unknown' and '요도' in text:
            system='urinary'
        elif system=='unknown' and any(k in text for k in ('자궁','질','포피')):
            system='reproductive'
        return ('disease',system,f"{f'{site} 부위의 ' if site else ''}염증성 질환. 정확히 어떤 조직이 침범됐는지는 세부 병명·검사로 확인해야 함.",'literal_inflammation_suffix_rule','염증을 뜻하는 `염` 어미')
    # Anatomical lesion-ish phrase with recognizable condition suffix.
    if text.endswith(('부종','종창')):
        site,system=anatomical_site(text,'unknown')
        return ('symptom',system,f"{f'{site} 부위가 붓는 ' if site else ''}증상. 원인·조직·정도는 원문만으로 확인 불가.",'literal_suffix_rule','부종/종창; 부위는 명시된 경우만 풀이')
    return ('unknown','unknown','원문 표기는 보존했으나, 공개 용어 설명이나 안전한 단어 규칙으로 뜻을 확정하지 못함.','unknown','자동 해석 불가; 원자료 코드북 또는 수의사 확인 필요')

def csvrows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha_rows(rows):
    h=hashlib.sha256()
    for row in rows:h.update('\x1f'.join('' if v is None else str(v) for v in row).encode());h.update(b'\n')
    return h.hexdigest()
def build():
    con=sqlite3.connect(f'file:{DB.resolve()}?mode=ro',uri=True);con.row_factory=sqlite3.Row
    rows=con.execute('''SELECT t.id term_id,t.raw_text,COUNT(d.horse_medical_id) frequency FROM medical_diagnosis_terms t LEFT JOIN horse_medical_diagnoses d ON d.term_id=t.id GROUP BY t.id,t.raw_text ORDER BY t.id''').fetchall()
    old={int(r['term_id']):r for r in csvrows(ROOT/'candidate_terms.csv')}
    adjud={int(r['term_id']):r for r in csvrows(ROOT/'comma_terms_adjudicated_v3_20260926.csv')}
    components={}
    for c in csvrows(ROOT/'split_comma_components_v3_20260926.csv'):
        components.setdefault(int(c['source_term_id']),[]).append(c)
    fields=['term_id','raw_text','frequency','term_kind','anatomic_system','meaning_summary','meaning_status','meaning_basis','meaning_source_url','components_if_partitioned','definition_rule','user_interpretation','review_status','source_text_preserved']
    out=[]
    for r in rows:
        tid=int(r['term_id']); raw=r['raw_text']; parts=[]; status='auto_interpreted_candidate'; basis='literal_term_rules'
        adj=adjud.get(tid)
        if adj and adj['final_partition_status']=='split_into_two_review_candidates':
            for c in components.get(tid,[]):
                kind,sys,desc,src,why=meaning_one(c['component_raw_text'])
                parts.append({'text':c['component_raw_text'],'kind':kind,'system':sys,'meaning':desc,'source':src,'source_url':SOURCE_URLS.get(src,'')})
            kind='compound_source'; systems=';'.join(sorted(set(p['system'] for p in parts))) or 'unknown'
            summary=' / '.join(p['meaning'] for p in parts)
            if any(p['kind']=='unknown' for p in parts): status='partially_interpreted_unknown_component'
            elif any(p['source'].startswith('web_') and not p['source'].startswith('web_kra_') for p in parts): status='meaning_checked_against_veterinary_reference'
            elif any(p['source'].startswith('kra_') or p['source'].startswith('web_kra_') or p['source'] in ('user_supplied_kra_definition','user_visual_confirmation') for p in parts): status='meaning_checked_against_kra_or_user_source'
            basis='comma_adjudication_v3_plus_component_rules'
            if any(p['source']=='kra_profile_tooltip' for p in parts): basis+='; horse_specific_KRA_profile_tooltip_reconciliation'
            definition_rule='v3에서 두 표현으로 나눈 검토 후보; 원문과 빈도는 원행에 귀속되며 구성요소별 빈도는 배분하지 않음'
            component_json=json.dumps(parts,ensure_ascii=False)
        else:
            kind,sys,summary,src,why=meaning_one(raw)
            if kind=='unknown': status='unknown_manual_review'
            if src.startswith('kra_') or src.startswith('web_kra_') or src in ('user_supplied_kra_definition','user_visual_confirmation'): status='meaning_checked_against_kra_or_user_source'
            elif src.startswith('web_'): status='meaning_checked_against_veterinary_reference'
            basis=src
            if adj and adj['final_partition_status']=='retain_as_one_phrase_no_split':
                status='meaning_checked_retain_as_single_phrase' if kind!='unknown' else 'unknown_manual_review'
                basis+='; comma_boundary_v3_review'
                why+='; 원문 쉼표는 v3 판정에 따라 내부 열거 또는 단일 병명으로 보존'
            parts=[{'text':raw,'kind':kind,'system':sys,'meaning':summary,'source':src,'source_url':SOURCE_URLS.get(src,'')}]
            definition_rule=why
            component_json=json.dumps(parts,ensure_ascii=False)
            systems=sys
        source_urls=sorted({p['source_url'] for p in parts if p.get('source_url')})
        if raw=='지연발정정지기':
            source_urls.append(SOURCE_URLS['web_aaep_prolonged_diestrus'])
        user_interpretation=('사용자 해석: 대체로 크지 않은 기타 질환으로 취급. 원문은 구체 병명·원인·개별 말의 중증도를 확정하지 않음.' if kind=='unspecified_diagnosis_group' else '')
        out.append({'term_id':tid,'raw_text':raw,'frequency':r['frequency'],'term_kind':kind,'anatomic_system':systems,'meaning_summary':summary,'meaning_status':status,'meaning_basis':basis,'meaning_source_url':'; '.join(source_urls),'components_if_partitioned':component_json,'definition_rule':definition_rule,'user_interpretation':user_interpretation,'review_status':'candidate_not_clinically_reviewed','source_text_preserved':'yes'})
    with OUT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    audit_fields=['term_id','raw_text','horse_name','kra_horse_id','clinic_date_local','kra_displayed_term','english_label','kra_tooltip_text','review_result','source_url']
    with KRA_AUDIT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=audit_fields);w.writeheader();w.writerows(KRA_TOOLTIP_AUDIT_ROWS)
    cats=Counter(x['term_kind'] for x in out); stats=Counter(x['meaning_status'] for x in out)
    unknown_context={}
    for x in out:
        if x['meaning_status']=='unknown_manual_review':
            matches=con.execute('''SELECT h.name_ko,h.kra_horse_id,hm.clinic_date_local,hm.meet_code,hm.stable_part,hm.hospital_name
                FROM horse_medical_diagnoses d JOIN horse_medical hm ON hm.id=d.horse_medical_id
                JOIN horses h ON h.id=hm.horse_id WHERE d.term_id=? ORDER BY hm.clinic_date_local,hm.id''',(int(x['term_id']),)).fetchall()
            unknown_context[x['term_id']]=[dict(m) for m in matches]
    category_samples={}
    for x in out:
        if x['term_kind']=='unspecified_diagnosis_group':
            sample=con.execute('''SELECT h.name_ko,h.kra_horse_id,hm.clinic_date_local,hm.meet_code,hm.stable_part
                FROM horse_medical_diagnoses d JOIN horse_medical hm ON hm.id=d.horse_medical_id
                JOIN horses h ON h.id=hm.horse_id WHERE d.term_id=? ORDER BY hm.clinic_date_local DESC,hm.id DESC LIMIT 1''',(int(x['term_id']),)).fetchone()
            category_samples[x['term_id']]=dict(sample) if sample else None
    con.close()
    metadata={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'database_path':'data/horse_racing.sqlite3','unique_raw_terms':len(out),'medical_record_rows':697695,'source_term_frequency_total':sum(int(x['frequency']) for x in out),'source_term_catalog_sha256':sha_rows((x['term_id'],x['raw_text']) for x in out),'output_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'term_kind_counts':dict(cats),'meaning_status_counts':dict(stats),'web_reference_verified_terms':sum(x['meaning_status']=='meaning_checked_against_veterinary_reference' for x in out),'kra_profile_tooltip_audit_rows':len(KRA_TOOLTIP_AUDIT_ROWS),'user_interpretation_scope':'unspecified_diagnosis_group only; user supplied qualitative interpretation, not a clinical severity assessment','definitions_are_clinically_confirmed':False,'race_impact_and_severity_fields_included':False,'source_records_modified':False}
    META.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    top=sorted(out,key=lambda x:(-int(x['frequency']),int(x['term_id'])))[:20]
    unknown=sorted((x for x in out if x['meaning_status']=='unknown_manual_review'),key=lambda x:(-int(x['frequency']),int(x['term_id'])))
    web_checked=sorted((x for x in out if x['meaning_status']=='meaning_checked_against_veterinary_reference'),key=lambda x:(-int(x['frequency']),int(x['term_id'])))
    report=['# 진료 용어와 뜻 정리 — 2026-09-28','',f"- DB의 고유 원문 **{len(out):,}개**를 모두 수록했다. 진료기록 행은 697,695개이며 용어 빈도 합은 {sum(int(x['frequency']) for x in out):,}이다.",'- 이 산출물은 경주 성적 영향·임상 중증도·출전 가능 여부를 다루지 않는다.','- 원문과 term_id는 그대로 보존한다. 쉼표 원문 중 v3에서 명확히 분리한 3,722개만 구성요소 뜻을 병기하고 원문 용어의 빈도를 구성요소별로 나누지 않는다. 내부 쉼표로 보존하기로 한 9개는 나누지 않는다.','- `meaning_summary`는 확인된 공식 풀이, 안전한 형태소 규칙, 또는 판정 보류를 구별한다. rule-derived 설명은 후보 해석이며 수의학적 확정 진단이 아니다.','- 아래 `자동 분류 가능`은 문구 풀이 후보를 만들 수 있다는 뜻이다. 5,397개 모두 `review_status=candidate_not_clinically_reviewed`로 두었으며 수의사가 전체 용어를 검증한 상태는 아니다.','', '## 분류 건수','']
    for k,v in sorted(cats.items()):report.append(f'- {k}: {v:,}')
    report+=['','## 뜻 확인 상태','']
    for k,v in sorted(stats.items()):report.append(f'- {k}: {v:,}')
    unspecified_n=cats.get('unspecified_diagnosis_group',0)
    unspecified_freq=sum(int(x['frequency']) for x in out if x['term_kind']=='unspecified_diagnosis_group')
    meet_names={1:'서울',2:'제주',3:'부산경남',4:'영천'}
    report+=['','## 이번 검토의 결론과 사람 검토 범위','',f"- **자동 분류 가능(뜻 후보): {stats.get('auto_interpreted_candidate',0):,}개.** 증상·손상·질환·처치·예방·검사·행정 등 문구 유형과 뜻을 규칙으로 후보화했다. 진단 확정이나 심각도를 뜻하지 않는다.",f"- **공개 자료/사용자 확인을 대조한 항목: {stats.get('meaning_checked_against_kra_or_user_source',0)+stats.get('meaning_checked_against_veterinary_reference',0):,}개** (KRA·사용자 제공 정의 {stats.get('meaning_checked_against_kra_or_user_source',0):,}; 수의학 참고자료 {stats.get('meaning_checked_against_veterinary_reference',0):,}). 이 출처 확인도 개별 말의 임상 검토와는 다르다.",f"- **사람 검토 필요: {stats.get('unknown_manual_review',0):,}개**는 문구 전체를 원문만으로 확정하지 못해 보류했다. 쉼표가 내부 열거로 확인돼 보존한 {stats.get('meaning_checked_retain_as_single_phrase',0):,}개도 구성요소 분해 대상이 아니다.",f"- **원문 자체에 세부 병명이 없는 ‘기타’ 묶음: {unspecified_n:,}개, 총 {unspecified_freq:,}회.** 사용자는 이를 이번 작업에서 대체로 ‘크지 않은 기타 질환’으로 보는 해석을 제시했다. 이는 분류표의 `user_interpretation`에 별도 기록했으며, 개별 말의 실제 진단·중증도나 영향이 낮다고 확인한 뜻은 아니다. 각 말의 상세 기록에서 구체 병명을 복원할 수 없는 한계는 남는다.",'- **현 자료로 판정 불가:** 개별 말의 확진 여부·중증도·현재 회복 상태·경주 성적에 미친 실제 영향·공식 출전 가능 여부. 이번 용어 사전만으로는 결론을 낼 수 없다.','', '## 위험한 오분류와 수정','', '- `우제2,3중수골골간인대염좌/파열`처럼 `인대염` 글자가 포함된 손상 문구가 과거에는 염증 규칙에 먼저 걸릴 수 있었다. `염좌/파열`을 우선 인식하도록 고쳐 해당 표현을 손상 후보로 분류한다.','- 사용자 확인으로 `좌전제차부란/제차퇴행성?`는 KRA의 `좌전제차부란(제차퇴행성괴사) (LF. THRUSH)`, `양전구절특발성활막염(구?`는 `구건연종 (WINDPUFFS)`, `좌척측인대염기인성비부골척측비대/좌비절후종`은 `좌비절후종(좌척측인대염기인성비부골척측비대) (L. CURB)`로 확인해 풀이를 반영했다. DB 원문은 모두 그대로 보존한다.','- 늘기쁨(term_id 689)의 `좌척측인대염기인성비부골`도 사용자가 위 `L. CURB`와 같은 병명이라고 확인하여 해당 뜻으로 확정했다. 짧은 원문은 그대로 두고, 분류표 설명과 검토 로그에만 전체 풀이를 기록한다.','- `비절후종`의 좌·우·양측 표기 변형에도 같은 KRA 풀이를 적용했다. `발목피부염/계군`, `주두점액낭염/주종`, `비절외상성점액낭염/비절단종`을 구체화했고, `환골류/지골류`는 사전 표기대로 함께 풀이했다.','- `치료장제(제엽염)` 등 처치 괄호 속 병변·상태 표현은 원문에 함께 적힌 내용으로만 설명한다. 개별 말의 진단 확정으로 취급하지 않는다.']
    report+=['','## 재검토에서 발견해 수정한 자동 풀이 오류','', '- 해부 부위 탐색에서 한 글자 부분 문자열(`위`, `지`)을 독립 부위로 처리하지 않도록 바꾸고, 경골·거골·관절·발굽 등 구체 용어를 우선 인식한다. 기존에 `원문 부위 표기(원문 접두 …)`로만 남던 **1,145개 용어(44,836회)**를 부위 문맥에 따라 풀이했다. 현재 같은 접두 미풀이 표기는 0개다.','- `원위단`의 `위`를 부위로 오인한 **4개 용어(5회)**를 바로잡았다. 예: `좌 경골원위단내측과이단성골연골염`은 왼쪽 경골 부위로 풀이한다.','- `이단성골연골염` **56개 용어(142회)**를 일반적인 “염증성 질환” 규칙보다 먼저 인식하고, 말의 골연골증/OCD 계열로 풀이한다. 영상상 병변·크기·임상증상은 원문만으로 확정하지 않는다.','- `양후낭축농증`은 `양후`를 뒷다리로 읽지 않고 양쪽 인두낭으로 처리한다. 문맥별 예외를 적용했다.','- 위 변경은 자동 풀이의 명백한 오류를 줄이기 위한 것이며, 모든 후보 의미가 수의사에게 검증됐다는 뜻은 아니다.']
    report+=['',f'검색과 안전한 규칙으로도 뜻을 확정하지 못해 `unknown_manual_review`로 남긴 원문은 {len(unknown):,}개다.','', '## 검색으로 대조한 용어','', f'검색으로 확인한 참고자료 풀이를 반영한 원문은 **{len(web_checked):,}개**다. 좌우·다리 위치가 붙은 변형은 각각 원문 표기를 보존했다.','', '| term_id | 빈도 | 원문 | 분류 후보 | 검색 대조 풀이 | 출처 |','|---:|---:|---|---|---|---|']
    for x in web_checked:report.append(f"| {x['term_id']} | {int(x['frequency']):,} | {x['raw_text'].replace('|','\\|')} | {x['term_kind']} | {x['meaning_summary'].replace('|','\\|')} | {x['meaning_source_url']} |")
    report+=['','## 검색 후에도 미확인인 항목','', '아래 원문은 검색에서 확실한 표준 대응을 찾지 못했거나 원문이 잘려 있어 자동 복원하지 않았다. 상세 목록과 구성요소는 CSV에서 확인할 수 있다.']
    if unknown:
        report+=['','### 원문 전체가 미확인','']
        for x in unknown:
            report.append(f"- term_id {x['term_id']}: `{x['raw_text']}` ({int(x['frequency']):,}회)")
            for context in unknown_context.get(x['term_id'],[]):
                meet=meet_names.get(context['meet_code'],f"경마장 코드 {context['meet_code']}")
                report.append(f"  - 원기록 연결: {context['name_ko']} ({context['kra_horse_id']}), {meet}경마장 {context['stable_part']}조, {context['clinic_date_local']}, {context['hospital_name']}")
    else:
        report+=['','현재 원문 전체를 미확인으로 남긴 항목은 없다.']
    report+=['','### ‘기타’ 분류별 확인 예시','', '각 고유 `기타` 원문마다 최근 진료기록 한 건을 연결했다. 예시는 용어 분류 확인용이며 개별 말의 확진을 뜻하지 않는다. 서울·제주·부산경남·영천은 DB 경마장 코드 기준이다.','','| term_id | 빈도 | 원문 | 예시 말 (마사회 번호) | 경마장·조 | 진료일 |','|---:|---:|---|---|---|---|']
    for x in sorted((z for z in out if z['term_kind']=='unspecified_diagnosis_group'),key=lambda z:int(z['term_id'])):
        sample=category_samples.get(x['term_id'])
        if not sample:
            report.append(f"| {x['term_id']} | {int(x['frequency']):,} | `{x['raw_text']}` | 연결 기록 없음 | — | — |")
        else:
            meet=meet_names.get(sample['meet_code'],f"코드 {sample['meet_code']}")
            report.append(f"| {x['term_id']} | {int(x['frequency']):,} | `{x['raw_text']}` | {sample['name_ko']} ({sample['kra_horse_id']}) | {meet} {sample['stable_part']}조 | {sample['clinic_date_local']} |")
    report += ['', '## 말별 KRA 진료페이지 툴팁 재확인', '', f'원문을 가진 말의 한국마사회 진료사항에서 같은 진료일의 상세항목을 대조했다. 상세 검토 로그는 `{KRA_AUDIT.name}` ({len(KRA_TOOLTIP_AUDIT_ROWS)}행)이며, 툴팁 설명은 원문 문구를 기록한 것이다. 이는 개별 말의 검사결과나 진단 확정은 아니다.', '', '| term_id | 원문 | 확인한 말·진료일 | KRA 상세 용어(영문) | 툴팁 설명 / 확인 결과 |', '|---:|---|---|---|---|']
    for a in KRA_TOOLTIP_AUDIT_ROWS:
        where=f"{a['horse_name']} ({a['kra_horse_id']}), {a['clinic_date_local']}"
        label=(f"{a['kra_displayed_term']} ({a['english_label']})" if a['kra_displayed_term'] and a['english_label'] else a['kra_displayed_term'] if a['kra_displayed_term'] else '툴팁 항목 미노출')
        explanation=a['kra_tooltip_text'].replace('|','\\|')
        report.append(f"| {a['term_id']} | `{a['raw_text']}` | {where} | {label} | {explanation} [{a['review_result']}] |")
    partial=sorted((x for x in out if x['meaning_status']=='partially_interpreted_unknown_component'),key=lambda x:(-int(x['frequency']),int(x['term_id'])))
    if partial:
        report+=['','### 쉼표 원문 중 일부 구성요소 미확인','']
        for x in partial:
            components=json.loads(x['components_if_partitioned'])
            unresolved=[c['text'] for c in components if c['kind']=='unknown']
            report.append(f"- `{x['raw_text']}`: 미확인 구성요소 `{', '.join(unresolved)}` ({int(x['frequency']):,}회)")
    report+=['','', '## 빈도 상위 20개','', '| term_id | 빈도 | 원문 | 분류 후보 | 뜻 |','|---:|---:|---|---|---|']
    for x in top:report.append(f"| {x['term_id']} | {int(x['frequency']):,} | {x['raw_text'].replace('|','\\|')} | {x['term_kind']} | {x['meaning_summary'].replace('|','\\|')} |")
    report+=['','## 읽는 법','', '- `symptom`: 증상이며 원인 질병을 확정하지 않는다. 예: 파행, 근육통.','- `injury`: 외상·조직 손상 표현. 크기·깊이·회복 상태는 포함하지 않는다.','- `disease`: 병명·질환 표현. 개별 말의 확진이나 현재 상태를 보증하지 않는다.','- `disease_or_injury`, `disease_or_anatomic_condition`, `disease_or_symptom`, `symptom_or_condition`, `anatomic_condition`: 원문이 질환·손상·해부학적 상태를 겹쳐 표현해 한 가지로 단정하기 어려운 후보. 상세 설명과 상태를 함께 본다.','- `treatment`: 처치·치료 기록이며 원래 진단을 뜻하지 않는다. 예: 정치, 발치, 피로회복.','- `examination`: 검사·검진 기록으로 결과나 질환을 뜻하지 않는다.','- `prevention`: 예방접종 등 예방 항목이다. 질병 진단이 아니다.','- `administrative`: 행정·기록 처리 항목.','- `unspecified_diagnosis_group`: “기타”처럼 구체 병명을 특정하지 않는 묶음.','- `compound_source`: 쉼표 원문을 v3 경계 검토 결과에 따라 자식 구성요소로 풀이했다. 자식 빈도는 산출하지 않았다.','- `unknown`: 검색에서도 확실한 대응 풀이가 없어 판정 보류로 남긴 항목.','', '## 출처와 제한','', '- KRA 질병용어 사전: https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=2, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=3, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=4, https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=5','- KRA 경마용어 사전(비절 질환 용어): https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=38','- Merck Veterinary Manual: https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/pharyngeal-lymphoid-hyperplasia-in-horses, https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-stifle-in-horses/intermittent-upward-fixation-of-the-patella-and-delayed-patella-release-in-horses, https://www.merckvetmanual.com/integumentary-system/dermatophytosis/dermatophytosis-in-horses, https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses','- AAEP prolonged-luteal-phase proceedings (지속 황체/지연 발정휴지기 설명): https://aaep.org/wp-content/uploads/2024/02/Proceedings-59th-Annual-Convention-2013.pdf','- Other veterinary references used are linked in `meaning_source_url` and component details in the CSV.','- 표준 참고자료의 일반적인 정의를 옮겼으며, 특정 말의 진단 확정·검사 결과·중증도를 확인한 것은 아니다. 검색 출처에 경주 성과 내용이 있어도 이 산출물에서는 의학적 뜻만 사용했다.','- 파일 재생성: `python3 research/medical_injury_race_impact_20260925/build_term_meaning_catalog.py`','']
    REPORT.write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2));print('outputs:',OUT,META,REPORT)
if __name__=='__main__':build()
