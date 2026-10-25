"""Independent stepwise absorption, descriptive subgroups and tie audits."""
from pathlib import Path
import json,importlib.util
import numpy as np,pandas as pd,duckdb
H=Path(__file__).resolve().parent;O=H/'outputs'
spec=importlib.util.spec_from_file_location('verification',H/'verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');db=duckdb.connect();st=pd.read_csv(O/'adjustment_stages.csv',dtype={'segment':str})
    for r in st.itertuples():
        g,col=v.sample(d,r);v.verify_contrast(db,g,col,r)
    maincols=['next_top3','three_top3','return180','any180_top3','next_abnormal_zero'];nrows=0
    for filename in ['finish_band_metrics.csv','same_calendar_confirmation.csv','distance_metrics.csv']:
        table=pd.read_csv(O/filename,dtype={'segment':str})
        for r in table.itertuples():
            w=getattr(r,'window','2024_2025');definition=getattr(r,'definition','race_fast20');row=type('Row',(),dict(window=w,definition=definition,meet=r.meet,segment=r.segment))();g,col=v.sample(d,row);g=g[g[col].eq(int(r.fast))]
            if filename=='finish_band_metrics.csv':
                band=np.where(g.raw_finish_rank.le(5),'4~5',np.where(g.raw_finish_rank.le(8),'6~8','9+'));g=g[band==r.finish_band]
            elif filename=='same_calendar_confirmation.csv':g=g[g.date.dt.strftime('%m-%d').le(r.calendar_cutoff)]
            elif filename=='distance_metrics.csv':g=g[g.distance_m.eq(r.distance_m)]
            db.register('sample',g);out=db.execute('SELECT count(*),count(DISTINCT source_key),count(DISTINCT horse_id),count(DISTINCT date),'+','.join(f'count({c}),avg({c}),sum({c})' for c in maincols)+' FROM sample').fetchone();v.close(out,[r.n,r.races,r.horses,r.dates]+[x for c in maincols for x in [getattr(r,c+'_n'),getattr(r,c+'_mean'),getattr(r,c+'_events')]],'independent sensitivity summary');nrows+=1
    for r in pd.read_csv(O/'threshold_tie_selection.csv',dtype={'segment':str}).itertuples():
        full=v.choose(d,r.window);col='race_fast20_'+r.segment;g=full[full.meet.eq(r.meet)&full[col].notna()];v.close([len(g),g[col].eq(1).sum(),g[col].mean()],[r.all_section_valid_n,r.selected_fast_n,r.actual_fast_fraction],'ties preserved')
    for r in pd.read_csv(O/'coverage.csv',dtype={'segment':str}).itertuples():
        g,col=v.sample(d,r);full=v.choose(d,r.window);v.close([(full.meet.eq(r.meet)&full.normal_outcome&full.raw_finish_rank.gt(3)&full.quality_base).sum(),len(g),g[col].eq(1).sum()],[r.nonpodium_quality_n,r.supported_n,r.fast_n],'coverage')
    exceptions=pd.read_csv(O/'busan400_quality_exceptions.csv');expected=d[d.meet.eq('부산')&d.quality_base&d.time400.isna()];v.ck(exceptions.row_key.tolist()==expected.row_key.tolist() and len(exceptions)==1,'sole Busan400 exception preserved')
    out=dict(passed=True,checks=v.checks,stage_regressions_verified=len(st),subgroup_summary_rows_verified=nrows,threshold_ties_preserved=True,current_finish_control_stages_exploratory=True,prediction_models_trained=0)
    (O/'sensitivity_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
