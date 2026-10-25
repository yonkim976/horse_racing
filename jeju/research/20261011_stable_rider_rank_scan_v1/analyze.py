"""Complete descriptive scan, with independent paired-start reconciliation."""
from pathlib import Path
import hashlib,json,math
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'jeju/research/20261011_stable_rider_rank_change_v1'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'results01';out.mkdir(exist_ok=False)
 source=OLD/'results01/all_cells.csv';pairs=ROOT/'jeju/research/20261011_stable_rider_switch_v1/input01/pairs.csv'
 a=pd.read_csv(source,dtype={'trainer_id':str,'jockey_id':str});z=pd.read_csv(pairs,dtype={'horse_id':str,'trainer_id':str,'jockey_id':str},low_memory=False)
 assert len(a)==3119 and len(z)==43024
 periods={'all':z,'past':z[z.year<=2023],'2024_2025':z[z.year.between(2024,2025)],'2026':z[z.year==2026]}
 groups={period:{(c,bool(b)):g for (c,b),g in x.groupby(['cell','changed_jockey'])} for period,x in periods.items()}
 for r in a.to_dict('records'):
  g=groups[r['period']][(r['cell'],r['changed'])];d=g.previous_finish_position-g.finish_position
  assert len(g)==r['pairs'] and math.isclose(d.mean(),r['mean_rank_gain'],abs_tol=1e-12)
  assert math.isclose((9*(g.rank_quality-g.previous_rank_quality)).mean(),r['normalized10_mean_gain'],abs_tol=1e-12)
  assert (int(d.gt(0).sum()),int(d.eq(0).sum()),int(d.lt(0).sum()))==(r['up'],r['equal'],r['down'])
  assert r['trainer_id']==g.trainer_id.iloc[0] and r['jockey_id']==g.jockey_id.iloc[0]
  assert r['trainer_name']==g.trainer_name.iloc[-1] and r['jockey_name']==g.jockey_display_name.iloc[-1]
 new=a[a.changed&a.period.eq('2026')&a.pairs.ge(20)].copy()
 prev=a[a.changed&a.period.eq('2024_2025')].drop(columns=['changed','period'])
 merged=new.merge(prev,on='cell',suffixes=('_2026','_2024_2025'),validate='one_to_one')
 merged['both_periods20']=merged.pairs_2024_2025.ge(20)
 merged['raw_positive_both']=merged.mean_rank_gain_2026.gt(0)&merged.mean_rank_gain_2024_2025.gt(0)&merged.both_periods20
 merged['raw_and_normalized_positive_both']=merged.raw_positive_both&merged.normalized10_mean_gain_2026.gt(0)&merged.normalized10_mean_gain_2024_2025.gt(0)
 merged['outside_previously_displayed_stables']=~merged.trainer_id_2026.isin(['002029','002034'])
 merged=merged.sort_values('mean_rank_gain_2026',ascending=False)
 merged.to_csv(out/'all_recent20_with_previous.csv',index=False,encoding='utf-8-sig')
 merged[merged.outside_previously_displayed_stables].to_csv(out/'other_stables_recent20.csv',index=False,encoding='utf-8-sig')
 repeated=merged[merged.raw_and_normalized_positive_both]
 repeated.to_csv(out/'repeated_direction_candidates.csv',index=False,encoding='utf-8-sig')
 assert len(merged)==16 and merged.both_periods20.sum()==13 and len(repeated)==6
 assert set(repeated[repeated.outside_previously_displayed_stables].cell)=={'002033:003082','002031:003087'}
 save(out/'verification.json',{'status':'passed','all_input_summary_rows_reconciled':len(a),'pairs_read':len(z),'recent20_combinations':len(merged),'recent20_raw_positive':int(merged.mean_rank_gain_2026.gt(0).sum()),'recent20_normalized_positive':int(merged.normalized10_mean_gain_2026.gt(0).sum()),'both_periods20_combinations':int(merged.both_periods20.sum()),'both_periods_positive_raw_and_normalized':len(repeated),'repeated_outside_previous_two_stables':2,'official_ids_and_display_names_reconciled':True,'no_statistical_or_causal_winner_selection':True})
 files=[source,pairs,OLD/'source_manifest.json',OLD/'results01/verification.json',HERE/'PLAN.md']
 save(HERE/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'source_period':'2017-01-13..2026-09-19','selected_pairs_start':'2017-01-20','partial_2026':True,'input_contract':'Inherited normal-complete-field selected starts, same horse/trainer/owner, 2..90 days, official IDs; histories T-2, no new forecast input','database_opened':False})
 print(json.dumps(json.loads((out/'verification.json').read_text()),ensure_ascii=False))
if __name__=='__main__':main()
