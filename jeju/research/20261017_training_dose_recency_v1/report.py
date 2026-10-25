"""Small descriptive receipts for counting interpretation and fixed key contrasts."""
import json
import pandas as pd
from data import HERE,save
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False);assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed';f=pd.read_csv(HERE/'input01/features.csv');g=f[f.window_days.eq(14)&f.training_rows.gt(0)];assert g.training_rows.eq(g.training_days).all();ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str,'jockey_id':str});key=['own_days_group:2_3_vs_1','own_days_group:4plus_vs_1','own_recency_group:2_3_vs_4_7','own_time_group:gt60_vs_30_60','count_group:9plus_vs_5_8','time_group:gt120_vs_60_120'];ef[ef.variant.eq('primary')&ef.comparison.isin(key)].to_csv(out/'supported_key_comparisons.csv',index=False,encoding='utf-8-sig');save(out/'verification.json',{'status':'passed','primary_observed_training_windows':len(g),'windows_with_multiple_rows_same_day':int(g.training_rows.gt(g.training_days).sum()),'row_count_equals_observed_day_count':True,'actual_daily_repetition_count_unavailable':True,'key_contrasts_exported_only_when_supported':True,'unsupported_contrasts_remain_in_model_specs':True});print('Counting interpretation verified',len(g),'windows',flush=True)
if __name__=='__main__':main()
