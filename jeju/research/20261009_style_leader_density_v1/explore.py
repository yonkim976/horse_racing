"""Post-primary diagnostic: historical leaders simultaneously in the first S1F pack."""
import pandas as pd
from features import HERE
from analyze import bootstrap,ci

def main():
 out=HERE/'explore01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False)
 a=a[a.coverage_any.ge(.8-1e-12)].copy();a['first_lead']=a.style_any.eq('lead')&a.y_s1f_pack3.eq(0)
 r=a.groupby(['race_id','race_date','year','race_distance_m'],as_index=False).agg(leaders=('leaders_any','first'),first_leaders=('first_lead','sum'),all_actual_known=('y_s1f_pack3',lambda v:v.notna().all()),field_n=('field_n','first'))
 r['top3']=r.first_leaders.ge(2).astype(int);r.to_csv(out/'race_diagnostic.csv',index=False,encoding='utf-8-sig')
 rows=[]
 for period,g in [('all',r),('2024_2025',r[r.year.isin([2024,2025])]),('2026',r[r.year.eq(2026)])]:
  g=g[g.all_actual_known];masks=[g.leaders.eq(j) for j in [0,1,2]]+[g.leaders.ge(3)];bd=bootstrap(g,'race_date',masks)
  for j,(label,mask) in enumerate(zip(['0','1','2','3plus'],masks)):
   z=g[mask];rows.append({'period':period,'leaders':label,'races':len(z),'two_or_more_prior_leaders_in_actual_first_pack':int(z.top3.sum()),'rate':z.top3.mean() if len(z) else None,'date_low':ci(bd[:,j])[0],'date_high':ci(bd[:,j])[1]})
 pd.DataFrame(rows).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig');print(pd.DataFrame(rows).to_string(index=False))
if __name__=='__main__':main()
