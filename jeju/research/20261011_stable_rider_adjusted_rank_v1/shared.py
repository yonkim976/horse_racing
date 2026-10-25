"""Exploratory shared nuisance slopes with cell-specific switch contrasts."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ID_COLS,TARGETS,save,sha,ROOT
from analysis import design,demean,bh
def main():
 out=HERE/'supplement01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False);s=pd.read_csv(HERE/'analysis01/support.csv',dtype={'period':str});rows=[];models=[]
 for period in ['2024_2025','2026']:
  cells=s[s.period.eq(period)&s.qualified].cell.tolist();z=a[a.year.le(2025)] if period=='2024_2025' else a[a.year.eq(2026)];g=z[z.cell.isin(cells)].copy()
  x,spec=design(g,g.changed_jockey);n=x.to_numpy()[:,2:];D=np.column_stack([(g.cell.eq(c)&g.changed_jockey).to_numpy(float) for c in cells]);X=np.column_stack([D,n]);X,H=demean(X,g.cell);C=len(cells);pen=np.r_[np.zeros(C),np.ones(n.shape[1])];rank=np.linalg.matrix_rank(X,tol=1e-8);df=len(g)-rank-H;assert df>15
  bread=np.linalg.inv(X.T@X+np.diag(pen));specrows=[]
  for target in TARGETS:
   y=demean(g[target].to_numpy()[:,None],g.cell)[0][:,0];beta=bread@X.T@y;res=y-X@beta;variances={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    scores=pd.DataFrame(X*res[:,None]);scores['key']=g[key].to_numpy();ss=scores.groupby('key').sum().to_numpy();G=len(ss);V=bread@ss.T@ss@bread*(G/(G-1)*(len(g)-1)/df);variances[label]=np.diag(V)[:C]
   for i,cell in enumerate(cells):
    q=g[g.cell.eq(cell)];deg=min(q.race_date.nunique(),q.horse_id.nunique())-1;crit=float(t.ppf(.975,deg));sd=np.sqrt(max(0,variances['date'][i]));sh=np.sqrt(max(0,variances['horse'][i]));point=float(beta[i]);c=q[q.changed_jockey];v=q[~q.changed_jockey]
    rows.append({'period':period,'cell':cell,'target':target,'trainer_name':q.trainer_name.iloc[-1],'jockey_name':q.jockey_display_name.iloc[-1],'changed':len(c),'retained':len(v),'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'raw_changed_mean':c[target].mean(),'raw_retained_mean':v[target].mean(),'crit':crit})
   specrows.append({'target':target,'beta':beta.tolist(),'date_variance':variances['date'].tolist(),'horse_variance':variances['horse'].tolist()})
  models.append({'period':period,'cells':cells,'rows':len(g),'row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'models':specrows,'df':int(df)})
 r=pd.DataFrame(rows);r['BH_q']=bh(r.date_p);r['exploratory_positive_supported']=r.BH_q.lt(.05)&r.date_low.gt(0)&r.horse_low.gt(0);r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in [HERE/'SUPPLEMENT_PLAN.md',HERE/'input01/pairs.csv',HERE/'analysis01/support.csv',HERE/'analysis01/effects.csv']]})
 print('SHARED TESTS',len(r),'POSITIVE',int(r.exploratory_positive_supported.sum()),flush=True);print(r[r.period.eq('2026')&r.target.eq('normalized10_gain')][['cell','trainer_name','jockey_name','changed','retained','effect','date_low','date_high','horse_low','horse_high','BH_q','exploratory_positive_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
