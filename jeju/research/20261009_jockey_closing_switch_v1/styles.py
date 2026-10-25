"""Describe measured riding traits without forcing permanent tactic labels."""
import pandas as pd
from data import HERE,OLD,save

def main():
 out=HERE/'styles01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={'jockey_id':str},low_memory=False)
 e=pd.read_csv(OLD/'effects01/jockey_effects.csv',dtype={'jockey_id':str})
 e=e[e.variant.eq('primary')&e.target.isin(['first_pack','late_gain','g3f_rank'])&e.period.isin(['2024_2025','2026'])].copy()
 e.to_csv(out/'traits_full.csv',index=False,encoding='utf-8-sig')
 rows=[]
 for kid,g in a[a.year.eq(2026)].groupby('jockey_id'):
  if len(g)<100:continue
  r={'jockey_id':kid,'name':g.jockey_display_name.iloc[0],'starts_2026':len(g),'back_starts_2026':int(g.back.sum()),'raw_first_pack_pct':100*g.first_pack.mean(),'raw_late_gain_pct':100*g.late_gain.mean(),'raw_mean_g3f_rank_fraction':g.g3f_rank.mean()}
  repeated=[];limited=[]
  for target in ['first_pack','late_gain','g3f_rank']:
   values=[]
   for period in ['2024_2025','2026']:
    v=e[(e.jockey_id==kid)&(e.target==target)&(e.period==period)].iloc[0]
    for c in ['effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported','starts']:r[target+'_'+period+'_'+c]=v[c]
    values.append(v)
   if all(v.direction_supported and v.effect>0 for v in values):repeated.append(target)
   elif any(v.direction_supported and v.effect>0 for v in values):limited.append(target)
  r['repeat_supported_positive_traits']='|'.join(repeated);r['period_limited_positive_traits']='|'.join(limited)
  r['label']='초반 첫집단 확보 반복 후보' if 'first_pack' in repeated else '후반 특성 반복 후보' if repeated else '기간 한정 신호·고정 스타일 미확정' if limited else '고정 기승 스타일 미확정'
  rows.append(r)
 pd.DataFrame(rows).to_csv(out/'current_riders.csv',index=False,encoding='utf-8-sig')
 save(out/'decision.json',{'status':'traits_described_without_permanent_tactic_assignment','current_100plus_riders':len(rows),'repeat_supported_positive_first_pack':[r['name'] for r in rows if 'first_pack' in r['repeat_supported_positive_traits']],'repeat_supported_positive_late_traits':[r['name'] for r in rows if any(v in r['repeat_supported_positive_traits'] for v in ['late_gain','g3f_rank'])],'permanent_lead_or_closing_labels_assigned':False})
 print('Styles saved',len(rows),flush=True)
if __name__=='__main__':main()
