"""Interpretive decomposition on fixed common races and descriptive finish bands."""
from pathlib import Path
import importlib.util
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;O=H/'outputs'
spec=importlib.util.spec_from_file_location('study',H/'analyze.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');stages=[];bands=[];selection=[];calendar=[]
    for window,full in m.windows(d):
        if window=='2018_2023':continue
        for meet,segment in m.SEGMENTS:
            for definition in ['race_fast20','prior_fast20']:
                g=m.sample(full,meet,segment,definition);col=definition+'_'+segment
                for stage in ['race_only','past','finish','full']:
                    result=m.adjusted(g,col,'next_top3',stage)
                    if result:stages.append(dict(window=window,meet=meet,segment=segment,definition=definition,stage=stage,method='same_race_adjusted',target='next_top3')|result)
                g=g.copy();g['finish_band']=np.where(g.raw_finish_rank.le(5),'4~5',np.where(g.raw_finish_rank.le(8),'6~8','9+'))
                for (band,flag),z in g.groupby(['finish_band',col]):bands.append(dict(window=window,meet=meet,segment=segment,definition=definition,finish_band=band,fast=bool(flag))|m.summary(z))
            col='race_fast20_'+segment;valid=full[full.meet.eq(meet)&full[col].notna()];selection.append(dict(window=window,meet=meet,segment=segment,all_section_valid_n=len(valid),selected_fast_n=int(valid[col].eq(1).sum()),actual_fast_fraction=float(valid[col].mean())))
    cutoff=(d.groupby('meet').date.max().min()-pd.Timedelta(days=180)).strftime('%m-%d')
    for period,full in m.windows(d):
        if period=='2018_2023':continue
        full=full[full.date.dt.strftime('%m-%d').le(cutoff)]
        for meet,segment in m.SEGMENTS:
            g=m.sample(full,meet,segment,'race_fast20');col='race_fast20_'+segment
            for flag,z in g.groupby(col):calendar.append(dict(window=period,calendar_cutoff=cutoff,meet=meet,segment=segment,fast=bool(flag))|m.summary(z))
    pd.DataFrame(calendar).to_csv(O/'same_calendar_confirmation.csv',index=False)
    problem=d[d.meet.eq('부산')&d.quality_base&d.time400.isna()];problem[['row_key','horse_name','raw_tail600','raw_tail400','raw_tail200','raw_acc400','raw_finish_seconds']].to_csv(O/'busan400_quality_exceptions.csv',index=False)
    pd.DataFrame(stages).to_csv(O/'adjustment_stages.csv',index=False);pd.DataFrame(bands).to_csv(O/'finish_band_metrics.csv',index=False);pd.DataFrame(selection).to_csv(O/'threshold_tie_selection.csv',index=False);print('Completed interpretive sensitivity',len(stages),flush=True)
if __name__=='__main__':main()
