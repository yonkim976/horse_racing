import sqlite3,json,collections,csv,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
TIMES=['jeS1fTime','je_1cTime','je_2cTime','je_3cTime','je_4cTime','jeG3fTime','jeG1fTime'];ORDERS=['sjS1fOrd','sj_1cOrd','sj_2cOrd','sj_3cOrd','sj_4cOrd','sjG1fOrd']
def numeric(v):
 if isinstance(v,bool):return None
 try:return float(v) if v is not None and v!='' else None
 except (ValueError,TypeError):return None
def main():
 c=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 ids={r[0] for r in c.execute('SELECT api_record_id FROM jeju_race_population_candidates')};full=collections.Counter((r[0],r[1]) for r in c.execute('SELECT race_date,race_number FROM race_result_rows'))
 counts=collections.Counter();field=collections.defaultdict(collections.Counter);flags=[];perrace=collections.defaultdict(collections.Counter)
 for r in c.execute('SELECT r.api_record_id,r.race_date,r.race_number,r.horse_id,r.horse_number,r.finish_time_seconds,r.finish_position,a.payload_json,a.payload_sha256 FROM race_result_rows r JOIN api_records a USING(api_record_id)'):
  if r['api_record_id'] not in ids:continue
  assert hashlib.sha256(r['payload_json'].encode()).hexdigest()==r['payload_sha256']
  d=json.loads(r['payload_json']);key=(r['race_date'],r['race_number']);positive=(r['finish_time_seconds'] or 0)>0 and r['finish_position'] is not None and 1<=r['finish_position']<=89
  counts['candidate_rows']+=1;counts['positive_finish_rows']+=positive
  for f in TIMES+ORDERS+['sjG3fOrd']:
   v=d.get(f);n=numeric(v);field[f]['missing_key' if f not in d else 'null' if v is None else 'invalid_numeric' if n is None else 'zero' if n==0 else 'negative' if n<0 else 'positive']+=1
  tv=[numeric(d.get(f)) or 0 for f in TIMES];ov=[numeric(d.get(f)) or 0 for f in ORDERS]
  counts['rows_with_positive_time']+=any(x>0 for x in tv);counts['rows_with_positive_order']+=any(0<x<90 for x in ov)
  perrace[key]['rows']+=1;perrace[key]['positive_time_rows']+=any(x>0 for x in tv);perrace[key]['positive_order_rows']+=any(0<x<90 for x in ov);perrace[key]['positive_finish_rows']+=positive
  base={'date':r['race_date'],'race_no':r['race_number'],'horse_id':r['horse_id'],'program_no':r['horse_number']}
  for f in ORDERS:
   n=numeric(d.get(f))
   if n is not None and 0<n<90 and (n>full[key] or not n.is_integer()):flags.append(dict(base,issue='order_range_or_noninteger',field=f,value=n,full_roster_count=full[key]))
  if positive:
   if not any(x>0 for x in tv):flags.append(dict(base,issue='positive_finisher_all_times_unavailable'))
   if not any(0<x<90 for x in ov):flags.append(dict(base,issue='positive_finisher_all_orders_unavailable'))
   g1=numeric(d.get('jeG1fTime'));g3=numeric(d.get('jeG3fTime'))
   if g1 is not None and g3 is not None and g1>0 and g3>0 and g1>g3+0.05:flags.append(dict(base,issue='g1f_exceeds_g3f_review',field='jeG1fTime',value=g1,G3F=g3))
   previous=None
   for f in TIMES[:5]:
    n=numeric(d.get(f))
    if n is None or n<=0:continue
    if f=='je_3cTime' and (numeric(d.get('rcDist')) or 0)>=800 and n<(numeric(d.get('jeS1fTime')) or 0)-0.05:flags.append(dict(base,issue='s1f_exceeds_c3_review',field=f,value=n,previous=numeric(d.get('jeS1fTime'))))
    if f=='je_4cTime' and n<(numeric(d.get('je_3cTime')) or 0)-0.05:flags.append(dict(base,issue='c3_exceeds_c4_review',field=f,value=n,previous=numeric(d.get('je_3cTime'))))
    if n>r['finish_time_seconds']+0.05:flags.append(dict(base,issue='cumulative_exceeds_finish',field=f,value=n,finish=r['finish_time_seconds']))
    previous=n
   for f in TIMES[5:]:
    n=numeric(d.get(f))
    if n is not None and n>r['finish_time_seconds']+0.05:flags.append(dict(base,issue='closing_exceeds_finish',field=f,value=n,finish=r['finish_time_seconds']))
 summary={'counts':dict(counts),'field_value_states':{f:dict(v) for f,v in field.items()},'candidate_races':len(perrace),'issue_counts':dict(collections.Counter(r['issue'] for r in flags)),'issue_observations':len(flags),'payload_sha_every_candidate_row_equal':True,'positive_finish_races_without_any_time':sum(v['positive_finish_rows']>0 and v['positive_time_rows']==0 for v in perrace.values()),'positive_finish_races_without_any_order':sum(v['positive_finish_rows']>0 and v['positive_order_rows']==0 for v in perrace.values())}
 (OUT/'horse_independent_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 keys=list(dict.fromkeys(k for r in flags for k in r)) or ['date','race_no','horse_id','issue']
 with (OUT/'horse_independent_flags.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(flags)
 print(json.dumps({k:v for k,v in summary.items() if k!='field_value_states'},ensure_ascii=False))
if __name__=='__main__':main()
