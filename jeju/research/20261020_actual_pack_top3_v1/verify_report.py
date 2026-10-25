"""Check the one-row-per-race export against independently verified group rows."""
import pandas as pd
from analysis import HERE,save
def main():
 out=HERE/'verification01/export_verification.json';assert not out.exists()
 p=pd.read_csv(HERE/'경주별_초반3그룹.csv').set_index('경주ID');r=pd.read_csv(HERE/'run01/race_groups.csv');r=r[r.point.eq('s1f')]
 assert len(p)==5200 and not p.index.duplicated().any()
 assert p[['선두_두수','두번째_두수','뒤쪽_두수']].sum(axis=1).eq(p['출전두수']).all()
 assert p[['선두_입상수','두번째_입상수','뒤쪽_입상수']].sum(axis=1).eq(3).all()
 assert p[['선두_우승수','두번째_우승수','뒤쪽_우승수']].sum(axis=1).eq(1).all()
 checks=0
 for code,label in [(0,'선두'),(1,'두번째'),(2,'뒤쪽')]:
  z=r[r.group_code.eq(code)].set_index('race_id').loc[p.index]
  for field,name in [('entries','두수'),('top3_count','입상수'),('winner_count','우승수'),('rate_pp','입상률')]:
   pd.testing.assert_series_equal(p[label+'_'+name],z[field],check_names=False,check_dtype=False);checks+=len(p)
 save(out,{'status':'passed','race_rows':len(p),'export_values_matched':checks,'all_group_count_and_finish_accounting_passed':True});print('Per-race export verified',len(p),flush=True)
if __name__=='__main__':main()
