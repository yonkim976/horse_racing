"""As-of horse summaries; a future field is required before issuing probabilities."""
import json,warnings
import numpy as np,pandas as pd,duckdb
import data
warnings.filterwarnings('ignore',category=pd.errors.PerformanceWarning)
def main():
 a=pd.read_parquet(data.O/'observations.parquet');cutoff=pd.Timestamp('2026-09-22');last=a.groupby('horse_id',sort=False).tail(1).copy();dummy=last.copy();dummy['date']=cutoff;dummy['row_key']=dummy.horse_id+'@20260922';dummy['role4']=-1;dummy['role5']=-1;dummy['group_observed']=False
 for c in data.HISTORY_VALUES:
  if c!='solo_rate':dummy[c]=np.nan
 h=data.histories(pd.concat([a,dummy],ignore_index=True));z=h[h.row_key.str.endswith('@20260922')].copy();checkcols=['history_last','past_total','slots5','fresh_slots5','valid_position5','supported5','strong5','position_sd5']+[f'count{w}_{j}' for w in [5,10] for j in range(4)]+[f'{v}_{p}5' for v in data.HISTORY_VALUES for p in ['n','mean']]
 out=z[['horse_id','horse_name','meet','grade_normalized']+checkcols].copy();out.insert(0,'as_of_date',cutoff.strftime('%Y-%m-%d'));out['days_since_last']=(cutoff-out.history_last).dt.days;out['active_365']=out.days_since_last.le(365);out['style_history_label']=[data.LABELS[int(np.argmax(v))] if sum(v==max(v))==1 else ('동률' if sum(v)>0 else '관측 부족') for v in z[[f'count5_{j}' for j in range(4)]].to_numpy()];out['probability_status']='이번 출전 편성 미지정: 위치확률 미발행';out.to_csv(data.O/'latest_horse_pace_profiles.csv',index=False)
 # Independent SQL latest actual slots, including every missing/nonfinish appearance.
 db=duckdb.connect();aa=a.copy();aa['solo_rate']=np.where(aa.group_observed,aa.role5.eq(0).astype(float),np.nan);db.register('a',aa);db.execute('CREATE TABLE ranked AS SELECT *, row_number() OVER(PARTITION BY horse_id ORDER BY date DESC) rn FROM a')
 fields=['horse_id','count(*) past_total']
 for w in [5,10]:
  for j in range(4):fields.append(f"sum(CASE WHEN rn<={w} AND date>=DATE '2024-09-22' AND date<=DATE '2026-09-20' AND role4={j} THEN 1 ELSE 0 END) count{w}_{j}")
 for v in data.HISTORY_VALUES:
  val=f"CASE WHEN rn<=5 AND date>=DATE '2024-09-22' AND date<=DATE '2026-09-20' THEN {v} ELSE NULL END";fields.extend([f'avg({val}) {v}_mean5',f'count({val}) {v}_n5'])
 b=db.execute('SELECT '+','.join(fields)+' FROM ranked GROUP BY horse_id').df().set_index('horse_id').loc[out.horse_id];n=0
 for col in b.columns:assert np.allclose(b[col].to_numpy(float),out[col].to_numpy(float),atol=1e-9,rtol=1e-9,equal_nan=True),col;n+=len(b)
 assert out.horse_id.is_unique and len(out)==12516;meta=dict(as_of_date='2026-09-22',data_cutoff='2026-09-20',horses=len(out),active365=int(out.active_365.sum()),supported5=int(out.supported5.sum()),active365_supported5=int((out.active_365&out.supported5).sum()),independent_SQL_values_verified=n,field_predictions_issued=False,history_method='Actual latest 5/10 roster slots, no missing-record skipping, fresh <=730 days and <=T-2')
 data.dump(data.O/'profile_verification.json',meta);print(json.dumps(meta,ensure_ascii=False))
if __name__=='__main__':main()
