"""Complete exact-phrase research attention catalog; no clinical severity or direct-effect claims."""
from pathlib import Path
import importlib.util,json,re,hashlib
import numpy as np,pandas as pd,duckdb
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs'
PREV=H.parent/'20261014_medical_item_outcomes';D=H.parent/'20261002_medical_v1/dictionary'
spec=importlib.util.spec_from_file_location('medical_prepare',PREV/'prepare.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
SOURCES={
 'bone':('Fractures and athletic activity','https://www.merckvetmanual.com/horse-owners/bone-joint-and-muscle-disorders-in-horses/disorders-of-the-carpus-and-metacarpus-in-horses','골절의 부위·형태에 따라 운동 복귀가 다르므로 구조 손상 문구를 우선 검토한다.'),
 'tendon':('Tendinitis in Horses','https://www.merckvetmanual.com/musculoskeletal-system/tendon-and-ligament-disorders-in-horses/tendinitis-in-horses','굴건 손상은 경주 복귀·재손상 우려와 관련돼 주행 검토 우선도가 높다.'),
 'ligament':('Suspensory Desmitis in Horses','https://www.merckvetmanual.com/musculoskeletal-system/tendon-and-ligament-disorders-in-horses/suspensory-desmitis-in-horses','계인대 관련 손상의 운동 복귀는 위치·손상 상태에 따라 달라진다.'),
 'eiph':('Exercise-Induced Pulmonary Hemorrhage in Horses','https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/exercise-induced-pulmonary-hemorrhage-in-horses','운동기인성 폐출혈은 경기력 저하와 관련될 수 있다. 비출혈 단독 표기는 같은 확정 진단이 아니다.'),
 'airway':('Laryngeal Hemiplegia in Horses','https://www.merckvetmanual.com/respiratory-system/respiratory-diseases-of-horses/laryngeal-hemiplegia-in-horses','후두 기능 저하는 운동 중 공기 흐름을 제한해 경기력과 관련될 수 있다.'),
 'laminitis':('Laminitis in Horses','https://www.merckvetmanual.com/musculoskeletal-system/disorders-of-the-foot-in-horses/laminitis-in-horses','제엽염은 지지·보행 기능과 관련되는 상태이므로 문구를 우선 검토한다.'),
 'myopathy':('Exertional Myopathies in Horses','https://www.merckvetmanual.com/musculoskeletal-system/myopathies-in-horses/exertional-myopathies-in-horses','운동성 근육질환은 운동 후 근육 기능 이상과 관련된다. 일반 근육통 문구와 구분한다.')}

def single(s):
 """Literal attention candidates. These categories do not diagnose or rate a horse."""
 if s in ['재료판매','진단서 발급','진단서발급']:return ('T','행정','질병 신호를 추정하지 않음',[])
 if '예방접종' in s:return ('T','예방','예방 기록으로 질병 발생을 추정하지 않음',[])
 if re.search(r'피로회복|진정|술후처치|물리치료|침치료|마체검사|검진|검사|^정치$|^발치$|치료장제|^수액|처치|수술|봉합|세척',s):
  return ('T','처치검사','처치·검사만으로 원래 진단과 중증도를 추정하지 않음',[])
 if '기타' in s:return ('U','불명확','구체 상태가 없는 기타 문구',[])
 if '골절' in s:return ('A','질환손상','골 구조 손상 문구를 우선 확인; 부위별 영향량은 미검증',['bone'])
 if re.search(r'천지굴건|심지굴건|굴건.*(염|좌상|단열|파열)',s):return ('A','질환손상','굴건 관련 문구로 지지·운동 기능 검토',['tendon'])
 if re.search(r'계인대.*(염|좌상|손상|단열|파열)|인대.*파열',s):return ('A','질환손상','계인대·인대 구조 문구 검토',['ligament'])
 if '운동기인성폐출혈' in s.replace(' ',''):return ('A','질환손상','폐출혈 명시 문구; 국내 직접 성적효과 표본은 부족',['eiph'])
 if re.search(r'후두.*(편마비|반마비|마비)|반회후두신경',s):return ('A','질환손상','운동 중 호흡 기능 관련 문구 검토',['airway'])
 if '제엽염' in s:return ('A','질환손상','발굽 지지·보행 관련 문구 검토',['laminitis'])
 if re.search(r'근색소뇨증|횡문근융해|운동성근병증',s):return ('A','질환손상','운동성 근육 기능 이상 문구; 일반 근육통과 구분',['myopathy'])
 if '비출혈' in s:return ('B','증상','출혈 원인 확인; 운동기인성 폐출혈로 자동 변환하지 않음',['eiph'])
 if re.search(r'파행|근육통|요배통|골막염|관절염|구절염|염좌|건염|인대염|건초염|부종|폐렴|기관지염|호흡|산통|감기|각막|식욕부진|골연골염|탈구',s):
  return ('B','질환증상','통증·보행·전신 상태 등에 따라 달라질 수 있는 문구; 개인 위험량 미검증',[])
 if re.search(r'염$|찰과상|교돌상|피부|외상|좌상|창$|궤양|기생충|병$|증$',s):return ('C','질환증상','현재 성적 근거만으로 영향 크기를 확정하지 못함',[])
 return ('U','불명확','세부 뜻과 주행 관련 근거를 보류',[])

def classify(raw,decision,components,canonical):
 if decision is not None and (decision.contextual_evidence_required==True or decision.review_status=='excluded'):
  return dict(priority='U',record_type='검토보류',reason='문맥 필요·이전 파서 전용·제외 판정을 전역 위험도로 재사용하지 않음',clinical_sources=[],targets=[],mapping_scope='blocked_context_or_excluded',mechanism_priority='U')
 if raw in canonical:targets=[raw];scope='exact_canonical_title'
 elif decision is not None and decision.mapping_rule_scope=='reviewed_phrase_candidate_only':
  targets=components.get(raw,[]);scope='reviewed_components_metadata_only'
 else:targets=[];scope='unreviewed_raw_phrase'
 if not targets:return dict(priority='U',record_type='검토보류',reason='검토된 뜻 대응이 없어 원문 이름만으로 위험도를 확정하지 않음',clinical_sources=[],targets=[],mapping_scope=scope,mechanism_priority='U')
 a=[single(t) for t in targets];ps=[t[0] for t in a];src=sorted(set(z for t in a for z in t[3]));reason=' / '.join(dict.fromkeys(t[2] for t in a))
 priority='U' if 'U' in ps else 'A' if 'A' in ps else 'B' if 'B' in ps else 'C' if 'C' in ps else 'T'
 typ=a[0][1] if len(a)==1 else '복합문구'
 return dict(priority=priority,record_type=typ,reason=reason,clinical_sources=src,targets=targets,mapping_scope=scope,mechanism_priority=priority)

def gap_band(row):
 if row is None:return 'U 분류 근거 없음'
 if not row.restricted_wait_180_supported:return 'U 분류 표본 부족'
 if row.restricted_wait_180_estimate>0 and row.restricted_wait_180_q_joint<.05:
  return 'D3 큰 지연 연관' if row.restricted_wait_180_estimate>=30 else 'D2 지연 연관' if row.restricted_wait_180_estimate>=7 else 'D1 작은 지연 연관'
 if row.restricted_wait_180_estimate>0 and row.restricted_wait_180_q_domain<.05:return 'D1 검정 범위 민감'
 return 'D0 지연 미확인'

def main():
 decisions=pd.read_parquet(D/'phrase_decisions.parquet');api=pd.read_parquet(D/'api33_terms.parquet');pc=pd.read_parquet(D/'phrase_components.parquet')
 counts=pd.read_parquet(O/'source_phrase_counts.parquet');known=set(api.ill_name)
 cm=pc.sort_values('reviewed_target_ordinal').groupby('raw_text').target_ill_name.agg(list).to_dict();dm={r.raw_text:r for r in decisions.itertuples()}
 universe=sorted(set(counts.raw)|set(decisions.raw_text)|known)
 study=pd.read_csv(PREV/'outputs/raw_phrase_family_mapping.csv');famstats=pd.read_csv(PREV/'outputs/item_summary.csv').set_index('family')
 effects=pd.read_csv(PREV/'outputs/adjusted_associations.csv');primary=effects.query("period=='2024_2025' and variant=='primary' and state=='new'")
 # Exact phrase observation support is counted independently; no exact-term effect is estimated.
 c=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
 md=c.execute('''select distinct linked_horse_official_id horse_id,event_date,ill_name1_raw,ill_name2_raw
 from medical_current_api_records where linked_horse_official_id is not null''').df();c.close()
 md['date']=pd.to_datetime(md.event_date)
 sl=pd.concat([md[['horse_id','date']].assign(raw=md[f'ill_name{i}_raw']) for i in [1,2]],ignore_index=True)
 sl=sl[sl.raw.notna()&~sl.raw.isin(['','-'])].drop_duplicates(['horse_id','date','raw'])
 sl['index_date']=sl.date+pd.to_timedelta(7-sl.date.dt.dayofweek,unit='D');sl['family']=sl.raw.map(prior.family)
 lm=pd.read_parquet(PREV/'outputs/landmark_rows.parquet');lm=lm[lm.year.le(2025)]
 joined=sl.merge(lm[['horse_id','index_date']+[c for c in lm if c.startswith('new14_')]],on=['horse_id','index_date'],how='inner',validate='many_to_one').drop_duplicates(['horse_id','index_date','raw'])
 joined['family_new']=np.array([getattr(x,'new14_'+x.family) for x in joined.itertuples()],dtype=int)
 support=joined.groupby('raw').agg(observed_weeks=('horse_id','size'),horses=('horse_id','nunique'),family_new_weeks=('family_new','sum'))
 support.to_csv(O/'exact_phrase_observation_support.csv',index_label='raw')
 src=counts.pivot(index='raw',columns='source_kind',values='observations').fillna(0).astype(int).to_dict('index')
 rows=[];component_rows=[]
 for raw in universe:
  info=classify(raw,dm.get(raw),cm,known);targets=info.pop('targets');cs=info.pop('clinical_sources')
  families=sorted(set(prior.family(t) for t in targets));families=[f for f in families if f!='other']
  # A compound has no single pooled coefficient; component-group references remain metadata only.
  one=prior.family(raw) if raw in set(study.raw) else families[0] if len(families)==1 and len(targets)==1 else None
  if one=='other':one=None
  st=famstats.loc[one] if one in famstats.index else None
  band=gap_band(st);obs=support.loc[raw] if raw in support.index else None
  blocked=info['mapping_scope']=='blocked_context_or_excluded'
  if blocked:band='U 문맥 검토 필요';st=None;one=None
  # Family estimates do not establish a direct raw-term risk. Observed support is separately shown.
  scope='국내 원문별 직접 효과 미추정'
  if st is not None:scope='동일 분류 참고; 원문별 직접 효과 미추정'
  if len(targets)>1:scope='복합문구 구성요소 참고만; 조합 효과 미추정';st=None;band='U 복합문구 개별 효과 미추정';one=None
  priority=info['priority']
  if priority!='U' and obs is not None and band.startswith('D3'):
   priority='A';info['reason']+=' / 해당 원문이 주 분석에서 관측됐고 같은 분류의 큰 출전 지연 연관이 있어 우선 검토'
  elif priority in ['C','T'] and obs is not None and band.startswith('D2'):
   priority='B';info['reason']+=' / 해당 분류의 출전 지연 연관을 별도 확인'
  perf='U 분류 표본 부족' if st is None else st.performance_status
  first='분류 근거 없음';second='분류 근거 없음';later='분류 근거 없음'
  if st is not None:
   for h in [1,2,3]:
    z=primary[primary.family.eq(one)&primary.horizon.eq(h)&primary.supported&primary.identified]
    bad=(z.target.str.startswith('top3')&z.estimate.lt(0))|(~z.target.str.startswith('top3')&z.estimate.gt(0))
    status='저하 후보; 검정 범위 민감' if (bad&z.q_joint.lt(.05)).any() else '저하 미확인' if len(z) else '표본 부족'
    if h==1:first=status
    elif h==2:second=status
    elif h==3:later=status
  row=dict(raw_text=raw,raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),priority=priority,**{k:v for k,v in info.items() if k!='priority'},
   canonical_title=raw in known,reviewed_phrase=raw in dm,observed_source_phrase=raw in src,
   reviewed_targets_json=json.dumps(targets,ensure_ascii=False),component_count=len(targets),
   clinical_source_ids='|'.join(cs),clinical_source_urls=' | '.join(SOURCES[k][1] for k in cs),
   statistical_family=one or '',family_delay_band=band,evidence_scope=scope,
   primary_raw_observed_weeks=0 if obs is None else int(obs.observed_weeks),
   primary_raw_horses=0 if obs is None else int(obs.horses),primary_raw_family_new_weeks=0 if obs is None else int(obs.family_new_weeks),
   family_delay_days=None if st is None else float(st.restricted_wait_180_estimate),
   family_delay_ci_low=None if st is None else float(st.restricted_wait_180_ci_low),
   family_delay_ci_high=None if st is None else float(st.restricted_wait_180_ci_high),
   family_delay_q_joint=None if st is None else float(st.restricted_wait_180_q_joint),
   family_performance_status=perf,first_return_status=first,second_return_status=second,third_return_status=later,
   direct_raw_term_effect_estimated=False,verified_performance_decline=False,
   api16_observations=src.get(raw,{}).get('api16',0),archive_observations=src.get(raw,{}).get('api16_archived',0),text_observations=src.get(raw,{}).get('dacom72',0))
  rows.append(row)
  for i,t in enumerate(targets):
   p,typ,reason,ss=single(t);component_rows.append(dict(raw_text=raw,target_ordinal=i+1,target=t,priority=p,record_type=typ,reason=reason,source_ids='|'.join(ss),metadata_not_event_link=True))
 out=pd.DataFrame(rows).sort_values(['priority','raw_text']).reset_index(drop=True)
 out.to_parquet(O/'medical_risk_catalog.parquet',index=False)
 # Excel-safe CSV preserves exact source strings in the Parquet and stable SHA column.
 safe=out.copy();escaped=0
 for col in safe.select_dtypes('object'):
  mask=safe[col].map(lambda x:isinstance(x,str) and x.lstrip().startswith(('=','+','-','@')))
  escaped+=int(mask.sum());safe.loc[mask,col]="'"+safe.loc[mask,col]
 safe.to_csv(O/'medical_risk_catalog.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(component_rows).to_parquet(O/'reviewed_component_attention.parquet',index=False)
 summary=dict(total_exact_phrases=len(out),canonical_titles=len(known),reviewed_phrases=len(decisions),observed_source_phrases=counts.raw.nunique(),
  primary_observed_phrases=int(out.primary_raw_observed_weeks.gt(0).sum()),priority_counts=out.priority.value_counts().sort_index().to_dict(),
  direct_raw_term_effects_estimated=0,confirmed_conditional_performance_declines=0,blocked_context_rows=int(out.mapping_scope.eq('blocked_context_or_excluded').sum()),
  current_api_unique_phrases=int(counts[counts.source_kind.eq('api16')].raw.nunique()),csv_formula_safety_escapes=escaped,
  new_regressions=0,group_models_reused=41,production_changed=False)
 (O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 notes=[dict(source_id=k,title=v[0],url=v[1],access_date='2026-10-14',supported_claim=v[2],role='mechanistic_attention_prior_not_local_effect_estimate') for k,v in SOURCES.items()]
 (O/'clinical_source_notes.json').write_text(json.dumps(notes,ensure_ascii=False,indent=2)+'\n')
 # A compact typed JSON matrix is the only input to the workbook authoring step.
 cols=[('raw_text','원문 항목'),('priority','검토 등급'),('record_type','기록 종류'),('reason','등급 근거'),
  ('family_delay_band','분류별 출전 지연'),('first_return_status','첫 복귀 성적'),('second_return_status','두 번째 성적'),('third_return_status','세 번째 성적'),
  ('primary_raw_observed_weeks','원문 관측 주'),('primary_raw_horses','원문 관측 두수'),('family_delay_days','분류 대기 차이 일'),
  ('evidence_scope','통계 근거 범위'),('mapping_scope','뜻 대응 상태'),('reviewed_targets_json','검토된 구성요소'),('clinical_source_urls','수의학 참고 출처')]
 values=out[[k for k,_ in cols]].astype(object).where(pd.notna(out[[k for k,_ in cols]]),None).values.tolist()
 (O/'workbook_data.json').write_text(json.dumps(dict(headers=[v for _,v in cols],rows=values,summary=summary,sources=notes),ensure_ascii=False,allow_nan=False)+'\n')
 print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
