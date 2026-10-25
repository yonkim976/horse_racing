"""CAS publish the reviewed research result; never change operating selection."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
CENTRAL=ROOT/'jeju/research/conclusions'
NAMES=['22_DIRECT_PAIR_TOP3_MODEL.md','README.md','SOURCES.md','research_register.json','source_manifest.json']
KEY='pair_reliability_20261014'

def sha(b):return hashlib.sha256(b).hexdigest()
def encode(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def main():
 review=json.loads((STUDY/'ROOT_REVIEW.json').read_text())
 assert review['status']=='PASS' and not review['fixed_probability_gate_passed'] and not review['selection_improvement_confirmed']
 assert review['report_sha256']==sha((STUDY/'outputs/REPORT.json').read_bytes())
 for name,digest in review['reviewed_output_sha256'].items():assert sha((STUDY/name).read_bytes())==digest
 for name in ['ROOT_FIT_REVIEW.json','ROOT_PREDICTION_REVIEW.json']:assert json.loads((STUDY/name).read_text())['status']=='PASS'
 snapshot=json.loads((STUDY/'ARTIFACT_MANIFEST.json').read_text())
 for row in snapshot['local_artifacts']:
  path=STUDY/row['path'];assert path.resolve().is_relative_to(STUDY.resolve()) and not path.is_symlink()
  assert sha(path.read_bytes())==row['sha256'] and path.stat().st_size==row['bytes']
 before={n:(CENTRAL/n).read_bytes() for n in NAMES};after=dict(before)
 section=('\n## 2026-10-14 후속: 짝의 기록 지원도·변동성 7열 후보\n\n'
 '말 평가 F1_STYLE6를 고정하고 기존 기수 ID 연구 후보에 두 말 중 최소 관측 경력·동일거리 '
 '유효기록수·최근 5회 슬롯 유효시간수, 최대 시간 CV·동일거리 마지막 출전 간격 및 두 종류 '
 '미확보 말 수를 추가했다. 최근 이력은 T−2까지, 새 7열 정규화는 H1만 사용했다. '
 '3개 H1 학습과 H2 양의 기울기 확률 보정만 수행했으며 말 모델 재학습은 없다. '
 '기존 운영 HY_R_FORM과의 직접 비교는 아니다.\n\n'
 '| 비교 | 기존 기수 ID 후보 | 기록 지원도 후보 |\n'
 '|---|---:|---:|\n'
 '| 선택쌍 모두 Top3 | 438/1,779 (24.62%) | 439/1,779 (24.68%) |\n'
 '| 기존 선택쌍 고정 Brier | 0.177988 | 0.177969 |\n'
 '| 기존 선택쌍 고정 log loss | 0.538109 | 0.538062 |\n\n'
 '입상률 차이 +0.056%p의 날짜 95% 구간은 −0.114~+0.278%p다. 선택 변경 4경주는 '
 '새 적중 2·기존 적중 손실 1·양쪽 미적중 1이었다. 2024년 155→154, 2025년 157→158, '
 '2026년 126→127이다. 고정 선택쌍 Brier 차이 −0.00001844의 구간 '
 '−0.00005036~+0.00001170, log loss 차이 −0.00004788의 구간 '
 '−0.00013728~+0.00003675도 0을 포함해 두 주 평가 개선 기준은 통과하지 못했다.\n\n'
 '전체 쌍의 경주균등 Brier·log loss 차이는 −0.00000200·−0.00001361이며 날짜 구간도 '
 '0 아래였다. 보조 확률 분포의 약한 신호와 실제 선택쌍의 개선 확인을 구분한다. '
 '최종 복연 5~10배 구간의 과대평가 +7.676→+7.679%p도 거의 변하지 않았다. '
 '최종배당은 사후 진단에만 사용했다.\n\n'
 '2024~2026-09-19의 1,779경주·269일·76,848쌍은 반복 개발 자료이며 2026년은 부분연도다. '
 '지원도는 보유 관측수이고 CV는 원기록의 상대 변동이므로 생애 전수 경력·생리적 신뢰도로 '
 '해석하지 않는다. 후보는 미채택으로 보존하고 기존 기수 ID 연구 비교기를 유지한다. '
 '다음 가설은 확률 수준과 기록 지원도의 상호작용을 제한적으로 연구하는 것이다. '
 '새 후보 학습·운영 승격은 이번 결과에 포함되지 않는다.\n\n'
 'Luna xhigh 구현·보고 후 감독은 H1 목적함수와 7열 정규화, 모든 예측·선택, '
 '22개 요약과 242개 날짜 비교(484개 CI 경계), 사후 가격 5구간을 독립 검산했다. '
 '산술 PASS와 개선 미확인을 구분한다. DB·운영 모델 변경은 없다. '
 '[감독 판단](../20261014_pair_reliability_v1/REVIEW_AND_NEXT_STEPS.md), '
 '[원 보고서](../20261014_pair_reliability_v1/README.md), '
 '[독립 검토](../20261014_pair_reliability_v1/ROOT_REVIEW.json).\n')
 after[NAMES[0]]+=section.encode()
 after['README.md']+=('\n[짝의 기록 지원도·변동성 입력 비교](../20261014_pair_reliability_v1/REVIEW_AND_NEXT_STEPS.md): '
  '기존 말 평가 유지, 438→439/1,779(+0.056%p, 날짜 95% 구간 −0.114~+0.278%p). '
  '고정 선택쌍 확률·입상 개선 미확인으로 후보 미채택; 독립 검산 PASS, 운영 변경 없음.\n').encode()
 after['SOURCES.md']+=('\n- [20261014_pair_reliability_v1](../20261014_pair_reliability_v1/README.md): '
  '짝의 기록 지원도·변동성 7열 단일 후보, 3개 시간순 H1/H2 학습·보정. '
  '[감독 판단](../20261014_pair_reliability_v1/REVIEW_AND_NEXT_STEPS.md), '
  '[성과 독립 검산](../20261014_pair_reliability_v1/ROOT_REVIEW.json). '
  '기존 기수 ID 후보 대비 개선 미확인, 말 평가·DB·운영 유지.\n').encode()
 register=json.loads(before['research_register.json']);register['updated_at']='2026-10-14'
 topic=next(t for t in register['topics'] if t['id']=='pair_top3_direct_20261011');assert KEY not in topic
 topic[KEY]={'source':'../20261014_pair_reliability_v1/README.md','review_and_next_steps':'../20261014_pair_reliability_v1/REVIEW_AND_NEXT_STEPS.md',
  'review':'../20261014_pair_reliability_v1/ROOT_REVIEW.json','races':1779,'dates':269,'pairs':76848,
  'existing_jockey_id_hits':438,'candidate_hits':439,'difference_pp':100/1779,'date_95pct_ci_pp':[-.11428734787225353,.27762739835893637],
  'new_input_columns':7,'horse_scores_preserved':True,'new_h1_fits':3,'new_h2_maps':3,
  'fixed_pair_probability_improvement_confirmed':False,'selection_improvement_confirmed':False,'all_pair_guardrail_passed':True,
  'research_adoption':False,'operational_change':False,'repeated_historical_development_data':True,'evaluation_end':'2026-09-19','year_2026_partial':True}
 after['research_register.json']=encode(register)
 manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in manifest['files']};rows=dict(old_rows)
 assert len(rows)==len(manifest['files'])
 for n in NAMES[:-1]:
  key=(CENTRAL/n).relative_to(ROOT).as_posix();rows[key]={**rows[key],'sha256':sha(after[n]),'bytes':len(after[n])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  assert not p.is_symlink() and p.resolve().is_relative_to(STUDY.resolve())
  key=p.relative_to(ROOT).as_posix();assert key not in rows
  rows[key]={'path':key,'role':'pair_reliability_research_and_review','sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
 manifest['updated_at']='2026-10-14';manifest['files']=sorted(rows.values(),key=lambda v:v['path'])
 manifest['managed_files_bytes_excluding_this_manifest']=sum(v['bytes'] for v in rows.values())
 manifest['verification'][KEY]={'status':'PASS','new_source_rows':len(new),'old_nonmanagement_rows_preserved':True,'improvement_confirmed':False,'operational_change':False}
 after['source_manifest.json']=encode(manifest)
 backup=STUDY/'publication/before';backup.mkdir(parents=True,exist_ok=False)
 for n,b in before.items():(backup/n).write_bytes(b)
 assert all((CENTRAL/n).read_bytes()==before[n] for n in NAMES),'Concurrent edit'
 for n in NAMES:
  assert (CENTRAL/n).read_bytes()==before[n],'Concurrent edit'
  temp=CENTRAL/(n+'.pair_reliability.tmp');assert not temp.exists();temp.write_bytes(after[n]);temp.replace(CENTRAL/n)
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]}
 assert all(rows[k]==v for k,v in old_rows.items() if k not in changed)
 old_topics={t['id']:t for t in json.loads(before['research_register.json'])['topics']};new_topics={t['id']:t for t in register['topics']}
 assert old_topics.keys()==new_topics.keys()
 for key,old in old_topics.items():
  got=dict(new_topics[key])
  if key=='pair_top3_direct_20261011':del got[KEY]
  assert got==old
 for p in new:
  row=rows[p.relative_to(ROOT).as_posix()];assert sha(p.read_bytes())==row['sha256']
 assert all((CENTRAL/n).read_bytes()==after[n] for n in NAMES)
 receipt={'status':'PASS','before':{n:sha(v) for n,v in before.items()},'after':{n:sha(v) for n,v in after.items()},
  'new_source_rows':len(new),'old_nonmanagement_rows_preserved':len(old_rows)-4,'source_rows':len(rows),'topic_count':len(new_topics),
  'prior_topic_values_preserved':True,'operating_model_or_DB_changed':False}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))

if __name__=='__main__':main()
