import importlib.util
from pathlib import Path

import pandas as pd

H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('october_analysis',H/'analyze.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
d=pd.read_csv(m.SOURCE,dtype={'horse_id':str})
d=d[d.year.ge(2019)].copy()
d['month']=d.race_date.str[5:7].astype(int)
d['month_day']=d.race_date.str[5:10]
rows=[]
details=[]
for dist,z in d.groupby('race_distance_m'):
    for field in m.FIELDS:
        for label,left,right,strata in [
            ('recent3_vs_full_same_Jan1_Sep19',z.month_day.le('09-19'),z.year.ge(2024)&z.month_day.le('09-19'),['rank_class_raw','track_state']),
            ('recent3_vs_full_same_Jan1_Sep19_month_matched',z.month_day.le('09-19'),z.year.ge(2024)&z.month_day.le('09-19'),['rank_class_raw','track_state','month']),
            ('pooled_October_vs_JanSep',z.year.le(2025)&z.month.le(9),z.year.le(2025)&z.month.eq(10),['year','rank_class_raw','track_state'])]:
            rows.append(m.contrast(z,left,right,strata,label,int(dist),field,details))
m.save('calendar_sensitivity.csv',pd.DataFrame(rows))
m.save('calendar_sensitivity_contributions.csv',pd.concat(details,ignore_index=True))
m.save('calendar_sensitivity_contract.json',{
    'status':'additional_descriptive_check_after_primary_outputs',
    'purpose':'recent3 comparison under same calendar coverage; October alone vs January-September',
    'same_support_policy_and_weights_as_primary':True,'cutoff':'09-19'})
