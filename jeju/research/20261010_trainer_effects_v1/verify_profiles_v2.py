"""Check profile assembly, repeated-trait decisions and selected report numbers."""
import json
import pandas as pd
import numpy as np
from data import HERE,save
def main():
 out=HERE/'profile_verification.json';assert not out.exists()
 a=pd.read_csv(HERE/'forecast01/assignment.csv',dtype={'trainer_id':str});e=pd.read_csv(HERE/'effects01/trainer_effects.csv',dtype={'trainer_id':str});p=pd.read_csv(HERE/'current_trainer_profiles.csv',dtype={'trainer_id':str});d=json.loads((HERE/'decision.json').read_text())
 expected=a[a.period.eq('2026')&a.starts.ge(100)].set_index('trainer_id').loc[p.trainer_id]
 assert len(p)==18==d['current_100plus_trainers'] and p.trainer_id.is_unique
 assert p.trainer_id.tolist()==expected.index.tolist()
 for c in a.columns.drop('trainer_id'):
  assert np.allclose(p[c],expected[c],equal_nan=True) if pd.api.types.is_numeric_dtype(p[c]) else p[c].tolist()==expected[c].tolist(),c
 for target in ['time','top3','first_pack','late_gain','g3f_rank']:
  s=e[e.period.eq('2026')&e.variant.eq('primary')&e.target.eq(target)].set_index('trainer_id').loc[p.trainer_id]
  for c in ['effect','date_low','date_high','horse_low','horse_high','BH_q','support','direction_supported']:assert np.allclose(p[target+'_'+c],s[c]),(target,c)
 r=e[e.variant.eq('primary')&e.period.isin(['2024_2025','2026'])];groups=r.groupby(['trainer_id','target']);repeat=sum(len(g)==2 and g.direction_supported.all() and np.prod(np.sign(g.effect))>0 for _,g in groups)
 assert repeat==0==d['recent_repeat_supported_primary_traits']
 z=a[a.period.eq('2026')].set_index('trainer_display_name');assert z.loc['심도연','starts']==295 and round(100*z.loc['심도연','raw_top3'],1)==48.8 and round(100*z.loc['심도연','expected_top3'],1)==37.1
 s=pd.read_csv(HERE/'switch02/summary.csv',dtype={'trainer_id':str});pair=s[s.trainer_id.isna()&s.subset.eq('all')&s.changed_trainer.eq(True)&s.target.eq('time_gain')];assert pair.pairs.tolist()==[287,105] and np.allclose(pair['mean'],[.644990,.952270],atol=1e-6)
 save(out,{'status':'passed','current_profiles':len(p),'profile_cells_recomputed':18*5*9,'recent_repeat_supported_primary_traits':int(repeat),'report_examples_checked':True})
 print('Profiles and decision checks passed',flush=True)
if __name__=='__main__':main()
