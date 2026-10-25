"""Compare frozen study metrics to independently derived probabilities."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MAIN=ROOT/'jeju/research/20261017_conditional_order_head_v1/outputs'

def main():
    saved=pd.read_parquet(MAIN/'evaluation_race_pool_metrics.parquet')
    own=pd.read_csv(HERE/'ROOT_EVENT_METRICS.csv');hy=pd.read_csv(HERE/'ROOT_SAME467_METRICS.csv');hy=hy[hy.model.eq('HY')]
    own=pd.concat([own,hy],ignore_index=True);names={'learned':'F1_STYLE6_COND_ORDER_V1','fixed':'fixed_score_conditional_PL','uniform':'uniform_conditional_order','HY':'operating_hy_r_form'};own['model']=own.model.map(names)
    j=saved.merge(own,on=['race_id','pool','model'],validate='one_to_one',suffixes=('','_root'));assert len(j)==len(saved)==len(own)
    errors={c:float(abs(j[c]-j[c+'_root']).max()) for c in ['nll','brier']};assert max(errors.values())<1e-11
    dif=j[j.rank1_hit.ne(j.hit)]
    # Numeric roundoff can only alter exact probability ties; report explicitly.
    if len(dif):
        print('TIE_DIFFERENCES',dif[['race_id','pool','model','rank1_hit','hit']].to_string(index=False))
        joint=pd.read_parquet(MAIN/'evaluation_ordered_joint.parquet')
        pcols={'F1_STYLE6_COND_ORDER_V1':'p_ordered_joint','fixed_score_conditional_PL':'control_p_ordered_joint','uniform_conditional_order':'uniform_p_ordered_joint'}
        for row in dif.itertuples(index=False):
            f=joint[joint.race_id.eq(row.race_id)];cols=['horse_no_1'] if row.pool=='WIN' else ['horse_no_1','horse_no_2']
            sums=f.groupby(cols)[pcols[row.model]].sum();near=sums[sums.ge(sums.max()-1e-12)]
            assert len(near)>=2 and abs(near.max()-near.min())<=1e-12
            best=sorted(sums.index,key=lambda k:(-sums.loc[k],k))[0];best=(best,) if isinstance(best,(int,np.integer)) else best
            saved_key=tuple(getattr(row,f'rank1_horse_no_{i}') for i in range(1,len(cols)+1));assert saved_key==best
        dif[['race_id','pool','model','rank1_hit','hit']].to_csv(HERE/'ROOT_FLOATING_TIE_AUDIT.csv',index=False)
    cond=pd.read_parquet(MAIN/'evaluation_conditional_order_metrics.parquet');reference=pd.read_csv(HERE/'ROOT_NLL_DECOMPOSITION.csv');reference['model']=reference.model.map(names)
    k=cond.merge(reference,on=['race_id','model'],validate='one_to_one',suffixes=('','_root'));assert len(k)==len(cond)
    assert np.allclose(k.conditional_order_nll,k.conditional_nll,atol=1e-11,rtol=0)
    assert np.allclose(k.full_tri_nll,k.tri_nll,atol=1e-11,rtol=0)
    decomp=pd.read_parquet(MAIN/'hy_same467_tri_nll_decomposition.parquet');dr=pd.read_csv(HERE/'ROOT_HY_NLL_DECOMPOSITION.csv');d=decomp.merge(dr,on='race_id',validate='one_to_one');assert len(d)==467
    for a,b in [('q_nll_gap_f1_minus_hy','base_gap'),('conditional_order_nll_gap_f1_minus_hy','order_gap'),('full_tri_nll_gap_f1_minus_hy','full_gap')]:assert np.allclose(d[a],d[b],atol=1e-11,rtol=0)
    report=json.loads((MAIN/'METRICS.json').read_text());primary=json.loads((HERE/'ROOT_PRIMARY_METRICS.json').read_text())
    assert abs(report['primary_candidate_minus_fixed_score_conditional_nll']['mean']-primary['mean_conditional_nll_difference'])<1e-11
    assert np.allclose(report['primary_candidate_minus_fixed_score_conditional_nll']['bootstrap_95pct'],primary['bootstrap_95'],atol=1e-11,rtol=0)
    assert report['primary_research_gate']['gate_pass'] is True
    receipt={'status':'PASS','race_pool_metric_rows':len(j),'conditional_rows':len(k),'hy_decomposition_races':len(d),'max_metric_errors':errors,'floating_ties_audited_against_frozen_joint_and_predeclared_numeric_rule':len(dif),'primary_gate_independently_reproduced':True,'no_fits':True,'metrics_sha256':hashlib.sha256((MAIN/'METRICS.json').read_bytes()).hexdigest()}
    (HERE/'ROOT_METRICS_REVIEW.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
