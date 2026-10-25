"""Reproducible report selections from already independently verified results."""
import pandas as pd
from data import HERE,save

def main():
 out=HERE/'report01';out.mkdir(exist_ok=True);assert not any(out.iterdir())
 assert __import__('json').loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
 p=pd.read_csv(HERE/'input01/horse_profiles.csv',dtype={'horse_id':str})
 g=p[p.window_days.eq(14)&p.observed_in_selected_2026&p.supported]
 assert len(g)==849
 metrics=['training_days','training_minutes','minutes_per_observed_day']
 q={c:{str(v):float(g[c].quantile(v)) for v in [.25,.5,.75]} for c in metrics}
 assert [q['training_days'][str(v)] for v in [.25,.5,.75]]==[7.,7.5,9.]
 assert [q['training_minutes'][str(v)] for v in [.25,.5,.75]]==[85.,102.,123.]
 effects=pd.read_csv(HERE/'analysis01/effects.csv');raw=pd.read_csv(HERE/'analysis01/raw_primary.csv')
 primary=effects[effects.variant.eq('primary')]
 assert len(primary)==66 and not primary.direction_supported.any()
 sensitivity=effects[~effects.variant.eq('primary')&(((effects.date_low>0)&(effects.horse_low>0))|((effects.date_high<0)&(effects.horse_high<0)))]
 assert len(sensitivity)==1
 assert sensitivity.iloc[0]['variant']=='short_gap' and sensitivity.iloc[0]['target']=='top3_pp'
 def records(frame):return frame.astype(object).where(pd.notna(frame),None).to_dict('records')
 save(out/'summary.json',{'latest_supported_active_horses':len(g),'latest_profile_quantiles':q,'primary_effects':records(primary),'raw_cells':records(raw),'exploratory_nonzero_intervals':records(sensitivity)})
 save(out/'verification.json',{'status':'passed','primary_rows_checked':len(primary),'raw_rows_checked':len(raw),'latest_active_profiles_checked':len(g),'exploratory_nonzero_sensitivity_rows':len(sensitivity)})
 print('Report selections verified',len(primary),len(raw),len(g),flush=True)
if __name__=='__main__':main()
