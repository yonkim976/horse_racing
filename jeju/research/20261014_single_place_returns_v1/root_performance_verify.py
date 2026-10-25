"""Independent single-anchor calibration and gross payout accounting."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def make_rows():
 approval=json.loads((STUDY/'ROOT_CALCULATION_APPROVAL.json').read_text());assert approval['approved'] is True
 a=pd.read_csv(STUDY/'ROOT_ANCHOR_REFERENCE.csv',dtype={'race_id':str,'horse_id':str,'api_record_id':str})
 official=pd.read_csv(STUDY/'ROOT_OFFICIAL_RESULTS.csv',dtype={'race_id':str,'kra_horse_id':str})
 quotes=pd.read_csv(STUDY/'ROOT_PLC_REFERENCE.csv',dtype={'race_id':str})
 rows=a.merge(official[['race_id','horse_number','kra_horse_id','finish_position']],on=['race_id','horse_number'],validate='one_to_one')
 assert rows.horse_id.eq(rows.kra_horse_id).all() and len(rows)==1779
 rows['hit']=(rows.finish_position<=rows.place_finish_cutoff).astype(int)
 rows=rows.merge(quotes,on=['race_id','horse_number'],how='left',validate='one_to_one')
 assert rows.odds.notna().eq(rows.year.isin([2025,2026])).all()
 rows['return_krw']=np.where(rows.odds.notna(),rows.hit*rows.odds*1000,np.nan)
 rows['roi_eligible']=rows.odds.notna()
 rows['probability_eligible']=rows.p_place.notna()
 return rows

def make_statistics(rows):
 dates=sorted(rows.race_date.unique())
 schedule_path=ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
 assert sha(schedule_path)=='d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
 schedule=np.load(schedule_path,allow_pickle=False)
 weights=np.stack([np.bincount(draw,minlength=len(dates)) for draw in schedule])
 output=[]
 for period in ['all','2024','2025','2026']:
  q=rows if period=='all' else rows[rows.year.eq(int(period))]
  groups=[('all','all',q),('probability_support','supported',q[q.probability_eligible]),('probability_support','unavailable',q[~q.probability_eligible])]
  groups += [('field_n',str(n),q[q.field_n.eq(n)]) for n in sorted(rows.field_n.unique())]
  groups += [('probability_bin',f'[{k/10:.1f},{(k+1)/10:.1f}{"]" if k==9 else ")"}',q[q.p_place.ge(k/10)&(q.p_place.le(1) if k==9 else q.p_place.lt((k+1)/10))]) for k in range(10)]
  groups += [('threshold',f'p>={cut:.1f}',q[q.p_place.ge(cut)]) for cut in [.5,.6,.7,.8,.9]]
  for kind,label,g in groups:
   n=len(g);h=int(g.hit.sum());cal=g[g.probability_eligible];paid=g[g.roi_eligible]
   def ci(values,subset):
    idx=pd.Categorical(subset.race_date,categories=dates).codes
    count=np.bincount(idx,minlength=len(dates));sums=np.bincount(idx,weights=np.asarray(values),minlength=len(dates))
    den=weights@count;valid=den>0
    draws=(weights@sums)[valid]/den[valid]
    return [float(x) for x in np.quantile(draws,[.025,.975])] if valid.any() else None,int((~valid).sum())
   hit_ci,hit_undefined=ci(g.hit,g)
   gap_ci,gap_undefined=ci(cal.hit-cal.p_place,cal)
   roi_ci,roi_undefined=ci(paid.return_krw/1000-1,paid)
   mean_hit_odds=paid.loc[paid.hit.eq(1),'odds'].mean()
   stat={'period':period,'group_type':kind,'group':label,'n':n,'hits':h,'hit_rate':h/n if n else None,'hit_ci':hit_ci,'hit_undefined_draws':hit_undefined,
    'n_prob':len(cal),'mean_p':float(cal.p_place.mean()) if len(cal) else None,'prob_hit_rate':float(cal.hit.mean()) if len(cal) else None,
    'gap_actual_minus_predicted':float((cal.hit-cal.p_place).mean()) if len(cal) else None,'gap_ci':gap_ci,'gap_undefined_draws':gap_undefined,
    'brier':float(((cal.hit-cal.p_place)**2).mean()) if len(cal) else None,
    'log_loss':float(-(cal.hit*np.log(cal.p_place)+(1-cal.hit)*np.log1p(-cal.p_place)).mean()) if len(cal) else None,
    'n_roi':len(paid),'roi_hits':int(paid.hit.sum()),'stake_krw':len(paid)*1000,'return_krw':int(round(paid.return_krw.sum())),
    'net_krw':int(round(paid.return_krw.sum()-len(paid)*1000)),
    'roi':float((paid.return_krw/1000-1).mean()) if len(paid) else None,'roi_ci':roi_ci,'roi_undefined_draws':roi_undefined,
    'mean_hit_odds':float(mean_hit_odds) if paid.hit.sum() else None,
    'break_even_hit_rate':float(1/mean_hit_odds) if paid.hit.sum() else None}
   output.append(stat)
 return output

def main():
 rows=make_rows();statistics=make_statistics(rows)
 target=STUDY/'ROOT_RETURN_REFERENCE.csv';assert not target.exists();rows.to_csv(target,index=False)
 out=STUDY/'ROOT_STATISTICS_REFERENCE.json';assert not out.exists();out.write_text(json.dumps(statistics,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 print(json.dumps([r for r in statistics if r['period']=='all' and (r['group_type']=='all' or r['group_type']=='probability_bin' and r['n']>0)],ensure_ascii=False))

if __name__=='__main__':main()
