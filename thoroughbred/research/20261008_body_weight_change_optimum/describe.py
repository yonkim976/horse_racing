"""Observed body distributions; these are not optimal-weight prescriptions."""
from pathlib import Path
import json,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs';d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');f=pd.read_parquet(O/'body_features.parquet');d=d.merge(f,on='row_key',validate='one_to_one');e=pd.read_csv(O/'eligibility.csv');d=d.merge(e[e.eligible][['meet','distance_m']],on=['meet','distance_m'],validate='many_to_one')
a=d.groupby('horse_id').body_weight.agg(n='size',mean='mean',sd='std',minimum='min',maximum='max',unique='nunique');a['span']=a.maximum-a.minimum;a.reset_index().to_csv(O/'horse_body_variation.csv',index=False)
rows=[]
for scope,dd in [('all',d),('age4plus',d[d.age.ge(4)])]:
 for (meet,dist),q in dd.groupby(['meet','distance_m']):rows.append(dict(scope=scope,meet=meet,distance_m=dist,n=len(q),horses=q.horse_id.nunique(),body_mean=q.body_weight.mean(),body_median=q.body_weight.median(),body_p20=q.body_weight.quantile(.2),body_p80=q.body_weight.quantile(.8),mean_change=q.body_change.mean(),sd_change=q.body_change.std(),median_usual_body=q.usual_body.median()))
pd.DataFrame(rows).to_csv(O/'distance_body_distribution.csv',index=False)
b=a[a.n.ge(8)];obj=dict(horses_at_least8_starts=len(b),usual_body_p10=float(b['mean'].quantile(.1)),usual_body_median=float(b['mean'].median()),usual_body_p90=float(b['mean'].quantile(.9)),within_horse_sd_median=float(b.sd.median()),observed_span_median=float(b.span.median()),reported_change_zero=int(d.body_change.eq(0).sum()),effective_change_sd=float(d.body_change.std()),large_change_ge15=int(d.body_change.abs().ge(15).sum()),observed_not_optimal=True);(O/'variation_summary.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Observed body descriptions saved')
