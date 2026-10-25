"""Moisture-band panels and all-original-starter outcome selection sensitivity."""
import re
from pathlib import Path
import pandas as pd
import numpy as np
import analyze as model

HERE=Path(__file__).resolve().parent
OUT=HERE/'outputs'
ROOT=HERE.parents[2]


def main():
    d=pd.read_parquet(OUT/'population.parquet')
    d['age_squared']=d.age**2
    for (meet,dist,band),g in d[d.distance_m.isin([1200,1400])].groupby(['meet','distance_m','band']):
        for target,reference in model.PAIRS:
            for spec,names in [('grade',[]),('full',model.LOAD+model.FORM)]:
                model.run(g,target,reference,model.BASE+['grade'],names,['finish'],
                    dict(scope='moisture_panel',meet=meet,distance_m=int(dist),subgroup=band,window='all',specification=spec))
    raw=[]
    ledger=pd.read_parquet(OUT/'selection_ledger.parquet')
    if 'finish' in ledger:
        ledger.rename(columns={'finish':'finish_ms'}).to_parquet(OUT/'selection_ledger.parquet',index=False)
    keys=set(ledger.source_key)
    paths=d.source_file.unique()
    for filename in paths:
        meet='서울' if 'meet_1.' in filename else '부산'
        for j,x in enumerate(model.source_items(ROOT/filename)):
            key=f"{meet}:{int(x['rcDate'])}:{int(x['rcNo'])}"
            if key not in keys:continue
            rank=int(x['ord'])
            if rank in [93,94,95]:continue  # Same explicit nonstarter codes as inherited cohort.
            body=re.match(r'^\s*(\d+)',str(x.get('wgHr','')))
            body=float(body[1]) if body and float(body[1])>0 else np.nan
            sex=str(x.get('sex',''))
            raw.append(dict(source_key=key,row_key=key+':'+str(x['hrNo']).zfill(7),horse_id=str(x['hrNo']).zfill(7),
                meet=meet,distance_m=int(x['rcDist']),date=pd.to_datetime(str(x['rcDate'])),rank_code=rank,
                age=float(x['age']),weight=float(x['wgBudam']),body_weight=body,sex=sex,
                sex_condition=str(x.get('sexCond','')),source_file=filename,source_item_index=j,
                top3=float(1<=rank<=3) if rank>0 else np.nan,win=float(rank==1) if rank>0 else np.nan))
    r=pd.DataFrame(raw)
    assert not r.row_key.duplicated().any()
    r['day_key']=r.meet+':'+r.date.dt.strftime('%Y%m%d')
    r['age_squared']=r.age**2
    r['weight_squared']=r.weight**2
    r['body_squared']=r.body_weight**2
    r['retained']=r.row_key.isin(d.row_key)
    r.to_parquet(OUT/'original_starter_outcomes.parquet',index=False)
    for (meet,dist),g in r[r.sex.isin(model.SEXES)&r.top3.notna()&~r.sex_condition.eq('암')].groupby(['meet','distance_m']):
        for target,reference in model.PAIRS:
            for spec,cols in [('all_starters_race',[]),('all_starters_load_body',['age','age_squared']+model.LOAD)]:
                model.run(g,target,reference,['source_key'],cols,['top3','win'],
                    dict(scope='original_starter_sensitivity',meet=meet,distance_m=int(dist),subgroup='all',window='all',specification=spec))
    pd.DataFrame(model.RESULTS).to_csv(OUT/'supplement_contrasts.csv',index=False)
    model.write_json(OUT/'starter_sensitivity_audit.json',dict(original_starters=len(r),original_races=r.source_key.nunique(),
        ranks=r.rank_code.value_counts().to_dict(),sex_counts=r.sex.value_counts().to_dict(),additional_rows_vs_final=int((~r.retained).sum()),
        scope='All original nonscratched API rows for official race keys in inherited audit population; original rank codes >20 are non-top3 outcomes, not invented finish times. Does not include cancelled or unverified API-only races.',
        race_condition_missing_rows=int(r.sex_condition.eq('').sum()),unknown_rank_rows=int(r.top3.isna().sum())))
    print('supplement',len(model.RESULTS),'contrasts',len(r),'original starters')


if __name__=='__main__':main()
