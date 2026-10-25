"""Separate reviewed combinations and unique complete dictionary parses, preserving lineage."""
from pathlib import Path
from functools import lru_cache
import importlib.util,json,hashlib
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';PREV=H.parent/'20261014_medical_risk_catalog';D=H.parent/'20261002_medical_v1/dictionary'
spec=importlib.util.spec_from_file_location('risk_prior',PREV/'build_catalog.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

def unique_parse(raw,lexicon):
 """Consume the whole string; commas inside canonical titles remain within that title."""
 ends=[];depth=0
 for i,ch in enumerate(raw):
  if ch in '([{（':depth+=1
  elif ch in ')]}）':depth=max(0,depth-1)
  elif ch==',' and depth==0:ends.append(i)
 ends.append(len(raw))
 @lru_cache(None)
 def walk(start):
  paths=[]
  for end in ends:
   if end<=start:continue
   token=raw[start:end].strip(' ')
   if token not in lexicon:continue
   if end==len(raw):paths.append((token,))
   else:paths.extend((token,)+tail for tail in walk(end+1))
   paths=list(dict.fromkeys(paths))
   if len(paths)>1:return paths[:2]
  return paths
 paths=walk(0)
 return paths[0] if len(paths)==1 else None,len(paths)

def main():
 catalog=pd.read_parquet(PREV/'outputs/medical_risk_catalog.parquet');by=catalog.set_index('raw_text')
 canonical=set(pd.read_parquet(D/'api33_terms.parquet').ill_name)
 links=[];new_decisions=[];all_atoms=set(canonical)
 for r in catalog.itertuples():
  reviewed=json.loads(r.reviewed_targets_json);parts=[];parse_count=0
  if r.mapping_scope=='blocked_context_or_excluded':status='context_or_parser_hold'
  elif r.raw_text in canonical:parts=[r.raw_text];status='official_title_kept_whole'
  elif reviewed:parts=reviewed;status='reviewed_components' if len(parts)>1 else 'reviewed_single_target'
  else:
   found,parse_count=unique_parse(r.raw_text,canonical)
   if found and len(found)>1:parts=list(found);status='unique_complete_dictionary_parse_candidate'
   elif found:parts=list(found);status='exact_dictionary_single_candidate'
   else:status='ambiguous_dictionary_parse_hold' if parse_count>1 else 'unresolved_hold'
  all_atoms.update(parts)
  new_decisions.append(dict(raw_text=r.raw_text,raw_sha256=r.raw_sha256,status=status,component_count=len(parts),
   targets_json=json.dumps(parts,ensure_ascii=False),original_priority=r.priority,original_mapping_scope=r.mapping_scope,
   dictionary_parse_path_count=parse_count,raw_source_preserved=True,new_event_links_created=False))
  for i,t in enumerate(parts or [None],1):
   links.append(dict(parent_raw=r.raw_text,parent_sha256=r.raw_sha256,component_ordinal=i if t else 0,
    component=t,status=status,parent_priority=r.priority,split_component_count=len(parts),
    parent_direct_weeks=r.primary_raw_observed_weeks,parent_direct_horses=r.primary_raw_horses,
    parent_frequency_not_assigned_to_component=True))
 link=pd.DataFrame(links);decision=pd.DataFrame(new_decisions)
 stats=pd.read_csv(H.parent/'20261014_medical_item_outcomes/outputs/item_summary.csv').set_index('family')
 atoms=[]
 for t in sorted(all_atoms):
  if t in by.index:
   x=by.loc[t];record=dict(term=t,priority=x.priority,record_type=x.record_type,reason=x.reason,
    family_delay_band=x.family_delay_band,first_return=x.first_return_status,second_return=x.second_return_status,
    third_return=x.third_return_status,direct_weeks=int(x.primary_raw_observed_weeks),direct_horses=int(x.primary_raw_horses),
    family_delay_days=None if pd.isna(x.family_delay_days) else float(x.family_delay_days),evidence_scope=x.evidence_scope,
    clinical_sources=x.clinical_source_urls,rule_source='own_exact_term_catalog_record')
  else:
   p,typ,reason,source=old.single(t);fam=old.prior.family(t);st=stats.loc[fam] if fam in stats.index and fam!='other' else None
   record=dict(term=t,priority=p,record_type=typ,reason=reason,family_delay_band=old.gap_band(st),
    first_return='단독 원문별 미검증',second_return='단독 원문별 미검증',third_return='단독 원문별 미검증',
    direct_weeks=0,direct_horses=0,family_delay_days=None if st is None else float(st.restricted_wait_180_estimate),
    evidence_scope='검토된 구성요소; 단독 원문별 직접 효과 미추정',clinical_sources=' | '.join(old.SOURCES[k][1] for k in source),rule_source='existing_literal_candidate_rule')
  record['canonical_title']=t in canonical;record['direct_term_effect_estimated']=False
  atoms.append(record)
 atomic=pd.DataFrame(atoms)
 refs=link[link.component.notna()].groupby('component').agg(linked_parent_phrases=('parent_sha256','nunique')).reset_index()
 atomic=atomic.merge(refs,left_on='term',right_on='component',how='left',validate='one_to_one').drop(columns='component')
 atomic.linked_parent_phrases=atomic.linked_parent_phrases.fillna(0).astype(int)
 atomic=atomic.sort_values(['priority','term']).reset_index(drop=True)
 grade=atomic.set_index('term').priority
 link['component_priority']=link.component.map(grade).fillna('U')
 decision.to_parquet(O/'parent_split_decisions.parquet',index=False);link.to_parquet(O/'component_lineage.parquet',index=False);atomic.to_parquet(O/'individual_term_catalog.parquet',index=False)
 for name,frame in [('parent_split_decisions',decision),('component_lineage',link),('individual_term_catalog',atomic)]:frame.to_csv(O/(name+'.csv'),index=False,encoding='utf-8-sig')
 counts=decision.status.value_counts().to_dict();s=dict(parent_phrases=len(catalog),individual_terms=len(atomic),
  split_parent_phrases=int(decision.component_count.gt(1).sum()),
  reviewed_split_parents=int(((decision.status=='reviewed_components')&decision.component_count.gt(1)).sum()),
  additional_complete_dictionary_split_parents=int(((decision.status=='unique_complete_dictionary_parse_candidate')&decision.component_count.gt(1)).sum()),
  held_parent_phrases=int(decision.component_count.eq(0).sum()),lineage_rows=len(link),
  resolved_parent_component_links=int(link.component.notna().sum()),official_comma_titles_kept_whole=sum(',' in t for t in canonical),
  blocked_context_parents=int(decision.status.eq('context_or_parser_hold').sum()),status_counts=counts,
  individual_grade_counts=atomic.priority.value_counts().sort_index().to_dict(),new_regressions=0,new_event_links=0)
 (O/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
 cols=[('term','단일 항목'),('priority','개별 검토 등급'),('record_type','기록 종류'),('reason','개별 판별 근거'),
  ('family_delay_band','분류별 출전 지연'),('first_return','첫 복귀 성적'),('second_return','두 번째 성적'),('third_return','세 번째 성적'),
  ('direct_weeks','단독 원문 관측 주'),('direct_horses','단독 원문 관측 두수'),('family_delay_days','분류 대기 차이 일'),
  ('linked_parent_phrases','연결된 원문 수'),('evidence_scope','근거 범위'),('clinical_sources','수의학 참고')]
 lc=[('parent_raw','원문'),('component_ordinal','항목 순서'),('component','분리된 항목'),('component_priority','개별 등급'),
  ('parent_priority','기존 원문 등급'),('status','분리 근거'),('split_component_count','분리 항목 수'),('parent_sha256','원문 식별 해시')]
 def matrix(frame,columns):
  x=frame[[k for k,_ in columns]].astype(object);x=x.where(pd.notna(x),None)
  return dict(headers=[v for _,v in columns],rows=x.values.tolist())
 payload=dict(individual=matrix(atomic,cols),lineage=matrix(link,lc),summary=s)
 (O/'workbook_data.json').write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False)+'\n')
 print(json.dumps(s,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
