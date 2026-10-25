"""Verify exploratory regressions by full-design least squares and pseudoinverse."""
from pathlib import Path
import importlib.util,json
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs'
spec=importlib.util.spec_from_file_location('validation',H/'verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def matrix(g,races):
    blocks=[np.ones((len(g),1))]
    fields=[g[['meet','distance_m','grade_bucket','year']].astype(str).agg('|'.join,axis=1),g.field_size.astype(str),g.moisture.fillna(-1).astype(str)]
    for field in fields:
        values=sorted(field.unique())
        for value in values[1:]:blocks.append(field.eq(value).to_numpy(float)[:,None])
    for col in (['past_finish_mean','support_fraction'] if races else ['finish_p_mean5','field_past_finish_mean','support_fraction','gate_relative']):
        a=g[col];blocks.extend([a.isna().to_numpy(float)[:,None],a.fillna(.5).to_numpy(float)[:,None],(a.fillna(.5)**2).to_numpy(float)[:,None]])
    return np.hstack(blocks)
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');q=pd.read_parquet(O/'race_context.parquet');d=d.merge(q[['source_key','past_finish_mean']].rename(columns={'past_finish_mean':'field_past_finish_mean'}),on='source_key',validate='many_to_one');d['gate_relative']=(d.gate-1)/(d.field_size-1)
    profiles=pd.read_parquet(H.parent/'20261008_middle_late_style_validation/outputs/trajectory_rows.parquet',columns=['row_key','front_profile','fore_strict_profile']);d=d.merge(profiles,on='row_key',validate='one_to_one')
    flags={'past_back':'back_profile','back_repeat':'closer_candidate','back_low':'back_low_recovery','past_lead':'lead_profile','past_front':'front_profile','past_fore_strict':'fore_strict_profile'};n=0
    for filename,races in [('additive_adjusted_comparisons.csv',False),('additive_race_pace_comparisons.csv',True),('following_adjusted_comparisons.csv',False)]:
        table=pd.read_csv(O/filename)
        for r in table.itertuples():
            g=v.v.window(q if races else d,r.window)
            if not races:g=g[g[flags[r.cohort]]]
            g=g[g[r.exposure].isin([r.a,r.b])&g[r.target].notna()];x=g[r.exposure].eq(r.a).to_numpy(float);z=matrix(g,races);X=np.column_stack([x,z]);y=g[r.target].to_numpy();beta,_,rank,_=np.linalg.lstsq(X,y,rcond=None);resid=y-X@beta;bread=np.linalg.pinv(X);score=bread[0]*resid*np.sqrt(len(g)/(len(g)-rank))
            v.close([len(g),x.sum(),len(g)-x.sum(),rank-1],[r.n,r.n_a,r.n_b,r.control_rank],'full design support rank')
            v.close(v.v.scored(g,score,beta[0]),[r.estimate,r.se,r.lower,r.upper,r.p,r.df],'full design independent regression/CI');n+=1
        if 'bh_q' in table:
            for _,g in table.groupby('window'):v.close(v.v.bh(g.p),g.bh_q,'regression BH')
    # New following raw rates and current-position opportunity are also recomputed.
    for filename,cols in [('following_cohort_metrics.csv',['top3','top5','finish_p','recovery','gain_late','fade','nonfinish']),('position_opportunity.csv',['p_s1f','p_g3f','p_g1f','finish_p','gain_late'])]:
        table=pd.read_csv(O/filename)
        for r in table.itertuples():
            g=v.v.window(d,r.window);g=g[g[flags[r.cohort]]&g[r.exposure].eq(r.status)];v.close([len(g)]+[item for c in cols for item in [g[c].notna().sum(),g[c].mean()]],[r.n]+[item for c in cols for item in [getattr(r,c+'_n'),getattr(r,c+'_mean')]],'following/position rates')
    out=dict(passed=True,checks=v.checks,full_design_regressions_verified=n,controls_independently_reconstructed=True,post_plan_exploratory=True,prediction_models_trained=0)
    (O/'adjusted_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
