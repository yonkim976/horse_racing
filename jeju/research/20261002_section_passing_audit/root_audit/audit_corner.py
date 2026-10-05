"""Read-only API303/API6 source, roster and cross-source audit. No DB writes."""
import collections,csv,hashlib,json,re,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
BASE=ROOT/'jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/20260929T143902.196014Z'
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'

def write(name,value):
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def csv_write(name,rows):
 if not rows:(OUT/name).write_text('');return
 if rows:
  keys=list(dict.fromkeys(k for r in rows for k in r))
  with (OUT/name).open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def k(raw):
 d=str(raw['rcDate']);return (d[:4]+'-'+d[4:6]+'-'+d[6:],int(raw['rcNo']))
def usable(value):return value is not None and str(value).strip() not in ('','0','-','X','0:00.0')
def parse_groups(value):
 s=str(value).replace(' ','')
 if not re.fullmatch(r'[0-9(),^=≡\-]+',s):return None
 matches=list(re.finditer(r'\([^()]+\)|\^?\d+',s));end=0;groups=[]
 for m in matches:
  if s[end:m.start()] and not re.fullmatch(r'[,=≡\-]+',s[end:m.start()]):return None
  t=m.group();g=[int(x) for x in re.findall(r'\d+',t)]
  if t.startswith('(') and not re.fullmatch(r'\(\^?\d+(?:,\^?\d+)*\)',t):return None
  groups.append(g);end=m.end()
 if end!=len(s):return None
 return groups

def main():
 manifest=json.loads((BASE/'run_manifest.json').read_text());datasets={};page_count=0;locators={}
 for name,ds in manifest['datasets'].items():
  vals={};count=0
  for part in ds['yearly']:
   local=0
   for page in part['pages']:
    path=(BASE/page['response_file']).resolve();assert path.is_relative_to(BASE.resolve())
    blob=path.read_bytes();assert hashlib.sha256(blob).hexdigest()==page['response_sha256'];assert len(blob)==page['response_bytes']
    obj=json.loads(blob);assert obj['response']['header']['resultCode']=='00'
    rows=obj['response']['body']['items']['item'];rows=rows if isinstance(rows,list) else [rows]
    assert len(rows)==page['actual_page_rows'];page_count+=1
    for pos,raw in enumerate(rows,1):
     key=k(raw);assert key not in vals;assert raw['meet']=='제주';assert key[0][:4]==str(part['year'])
     vals[key]=raw
     locators[(name,key)]=(path.relative_to(ROOT).as_posix(),pos,page['response_sha256'])
    count+=len(rows);local+=len(rows)
   assert local==part['api_total_count']==part['actual_total_rows']
  datasets[name]=vals
 c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 candidates={r[0] for r in c.execute('SELECT api_record_id FROM jeju_race_population_candidates')}
 races=collections.defaultdict(list);candidate_races=collections.defaultdict(list)
 for r in c.execute('SELECT r.*,a.payload_json FROM race_result_rows r JOIN api_records a USING(api_record_id)'):
  d=dict(r);d['raw']=json.loads(d.pop('payload_json'));key=(d['race_date'],d['race_number']);races[key].append(d)
  if d['api_record_id'] in candidates:candidate_races[key].append(d)
 corner=datasets['passing_corner'];section=datasets['detail_section'];cornerdb={}
 for r in c.execute('SELECT cr.*,a.payload_json,a.payload_sha256,a.record_index,s.sha256 AS page_sha,s.raw_relative_path FROM api303_corner_rank_rows cr JOIN api_records a USING(api_record_id) JOIN source_artifacts s ON s.source_artifact_id=a.source_artifact_id'):
  key=(r['race_date'],r['race_number']);raw=corner[key]
  assert r['meet_code']==2
  assert (r['raw_relative_path'],r['record_index'],r['page_sha'])==locators[('passing_corner',key)]
  for source,col in [('passtime_3f','passtime_3f_raw'),('passtime_4f','passtime_4f_raw'),('tempo','tempo_raw')]:assert r[col]==(None if raw.get(source) is None else str(raw[source]))
  assert json.loads(r['payload_json'])==raw;assert hashlib.sha256(r['payload_json'].encode()).hexdigest()==r['payload_sha256']
  for n in range(1,10):assert r['corner_'+str(n)+'_raw']==(None if raw.get('corner_'+str(n)) is None else str(raw['corner_'+str(n)]))
  cornerdb[key]=raw
 assert set(cornerdb)==set(corner)
 mapping={'S1F':('corner_7','passrankS1f','sjS1fOrd'),'1C':('corner_1','passrankG8f_1c','sj_1cOrd'),'2C':('corner_2','passrankG6f_2c','sj_2cOrd'),'3C':('corner_3','passrankG4f_3c','sj_3cOrd'),'4C':('corner_4','passrankG3f_4c','sj_4cOrd'),'G1F':('corner_8','passrankG1f','sjG1fOrd')}
 stats=collections.Counter();pointstats=collections.defaultdict(collections.Counter);coverage=[];issues=[];differences=[];orderissues=[];unparsed=[];compact=[];api6issues=[];api6checks=collections.Counter()
 for key,can in candidate_races.items():
  full=races[key];roster={r['horse_number'] for r in full if r['horse_number'] is not None};candidate_numbers={r['horse_number'] for r in can}
  positive=any((r['finish_time_seconds'] or 0)>0 and r['finish_position'] is not None and 1<=r['finish_position']<=89 for r in full)
  candidate_positive=any((r['finish_time_seconds'] or 0)>0 and r['finish_position'] is not None and 1<=r['finish_position']<=89 for r in can)
  cr=corner.get(key);sr=section.get(key)
  cov={'date':key[0],'race_no':key[1],'candidate_rows':len(can),'full_rows':len(full),'partial_candidate_race':len(can)!=len(full),'positive_finish_any':positive,'candidate_positive_finish_any':candidate_positive,'api303_present':cr is not None,'api6_present':sr is not None,'api303_nonempty_points':0,'api6_nonempty_points':0}
  if not cr:stats['api303_missing_key']+=1
  if not sr:stats['api6_missing_key']+=1
  for point,(cf,sf,of) in mapping.items():
   cv=cr.get(cf) if cr else None;sv=sr.get(sf) if sr else None
   if usable(cv):cov['api303_nonempty_points']+=1
   if usable(sv):cov['api6_nonempty_points']+=1
   if usable(cv) and usable(sv):
    stats['both_source_usable_points']+=1
    if str(cv)==str(sv):stats['api6_api303_exact_points']+=1
    else:differences.append({'date':key[0],'race_no':key[1],'point':point,'api303_field':cf,'api6_field':sf,'api303_raw':cv,'api6_raw':sv,'api6_value_matching_api303_fields':','.join(n for n,v in cr.items() if n.startswith('corner_') and str(v)==str(sv))})
   if not usable(cv):continue
   ps=pointstats[point];ps['nonempty_points']+=1;groups=parse_groups(cv)
   if groups is None:unparsed.append({'date':key[0],'race_no':key[1],'point':point,'notation_raw':cv});ps['not_parsed']+=1;continue
   ps['parsed_points']+=1;numbers=[x for g in groups for x in g];unknown=set(numbers)-roster;dup=[n for n,v in collections.Counter(numbers).items() if v>1]
   if unknown or dup:
    item={'date':key[0],'race_no':key[1],'point':point,'unknown_program_numbers':sorted(unknown),'repeated_program_numbers':dup,'notation_raw':cv}
    if unknown and key[0].startswith('2002'):
     item['interpretation']='legacy_compact_number_notation_ambiguous_do_not_split_or_infer_invalid_horse';compact.append(item);continue
    issues.append(item)
   bounds={};pos=1
   for g in groups:
    for n in g:bounds[n]=(pos,pos+len(g)-1)
    pos+=len(g)
   for row in can:
    ordval=row['raw'].get(of);num=row['horse_number']
    if isinstance(ordval,(int,float)) and 0<ordval<90 and num in bounds:
     ps['positive_candidate_orders_compared']+=1;lo,hi=bounds[num]
     if not lo<=ordval<=hi:orderissues.append({'date':key[0],'race_no':key[1],'point':point,'horse_id':row['horse_id'],'program_no':num,'api4_order':ordval,'group_rank_min':lo,'group_rank_max':hi,'notation_raw':cv})
    elif isinstance(ordval,(int,float)) and 0<ordval<90 and num not in bounds:
     orderissues.append({'date':key[0],'race_no':key[1],'point':point,'horse_id':row['horse_id'],'program_no':num,'api4_order':ordval,'issue':'positive_order_horse_absent_from_group','notation_raw':cv})
  if sr and positive:
   previous_distance=None
   for n in range(1,11):
    dist=sr.get('dist_'+str(n)+'f');current=sr.get('passtime_'+str(n)+'f');segment=sr.get('time_'+str(n)+'f');previous=0 if n==1 else sr.get('passtime_'+str(n-1)+'f')
    if isinstance(dist,(int,float)) and dist>0:
     api6checks['positive_distance_points']+=1
     if dist>sr['rcDist'] or (previous_distance is not None and dist<=previous_distance):api6issues.append({'date':key[0],'race_no':key[1],'field':'dist_'+str(n)+'f','issue':'distance_range_or_progression','value':dist,'prior':previous_distance})
     previous_distance=dist
    if all(isinstance(x,(int,float)) for x in [current,previous,segment]) and current>0 and segment>0 and (n==1 or previous>0):
     api6checks['cumulative_segment_arithmetic_compared']+=1
     if abs(current-previous-segment)>0.15:api6issues.append({'date':key[0],'race_no':key[1],'field':'passtime_'+str(n)+'f','issue':'cumulative_difference_vs_segment','value':current,'prior':previous,'segment':segment})
  coverage.append(cov)
 missing_completed=[r for r in coverage if r['positive_finish_any'] and (not r['api303_present'] or not r['api6_present'])]
 empty_completed=[r for r in coverage if r['positive_finish_any'] and r['api303_nonempty_points']==0]
 yearstats=collections.defaultdict(collections.Counter)
 for row in coverage:
  y=yearstats[row['date'][:4]];y['candidate_races']+=1;y['positive_finish_races']+=row['positive_finish_any'];y['api303_present']+=row['api303_present'];y['api6_present']+=row['api6_present'];y['api303_nonempty']+=row['api303_nonempty_points']>0
 report={'scope':'current jeju_race_population_candidates, exact race date/number; full current result roster used for program-number validation','source_pages_hash_size_count_year_validated':page_count,'api303_source_rows':len(corner),'api6_source_rows':len(section),'api303_all_db_payloads_and_projected_fields_equal':True,'candidate_races':len(candidate_races),'candidate_rows':len(candidates),'partial_candidate_races':sum(r['partial_candidate_race'] for r in coverage),'positive_finish_races':sum(r['positive_finish_any'] for r in coverage),'zero_finish_races':sum(not r['positive_finish_any'] for r in coverage),'candidate_zero_finish_races':sum(not r['candidate_positive_finish_any'] for r in coverage),'coverage_counts':dict(stats),'point_statistics':{k:dict(v) for k,v in pointstats.items()},'completed_missing_source_keys':len(missing_completed),'completed_without_any_api303_group':len(empty_completed),'notation_roster_or_repeated_number_points':len(issues),'legacy_compact_notation_points':len(compact),'api6_numeric_checks':dict(api6checks),'api6_numeric_arithmetic_or_distance_flags':len(api6issues),'unparsed_notations':len(unparsed),'api6_api303_raw_disagreement_points':len(differences),'api4_order_outside_group_bounds_observations':len(orderissues),'api4_order_outside_group_bounds_races':len({(r['date'],r['race_no']) for r in orderissues}),'year_coverage':{k:dict(v) for k,v in sorted(yearstats.items())},'limits':['Conservative common-grammar parsing is audit only; no interpretation of exact distances or internal group order.','Cross-group rank check uses member-count bounds and default Jeju point correspondence; flags need original-source verification, not automatic correction.','Full current result roster is larger than partial 제주마 candidate rosters; outside candidate does not imply wrong horse.','Race-level API6/API303 times are not individual horse times.']}
 write('summary.json',report)
 for name,rows in [('race_coverage.csv',coverage),('completed_missing_source_keys.csv',missing_completed),('completed_empty_groups.csv',empty_completed),('notation_roster_issues.csv',issues),('legacy_compact_notations.csv',compact),('api6_arithmetic_distance_flags.csv',api6issues),('unparsed_notations.csv',unparsed),('api6_api303_raw_differences.csv',differences),('api4_group_order_disagreements.csv',orderissues)]:csv_write(name,rows)
 print(json.dumps({k:v for k,v in report.items() if k not in ['year_coverage','point_statistics','limits']},ensure_ascii=False))
if __name__=='__main__':main()
