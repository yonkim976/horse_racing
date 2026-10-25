"""Independent label-free replay; imports root reconstruction, no candidate code."""
from itertools import combinations
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from verify_fitted_models import raw_inputs, COUNTS,MEANS
H=Path(__file__).resolve().parent;ROOT=H.parents[2];S=H.parent/'20261025_top5_reward_learning_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    receipt=json.loads((S/'outputs/CHOICES_RECEIPT.json').read_text())
    cp=S/'outputs/candidate_choices.jsonl';assert sha(cp)==receipt['choices_sha256']
    choices={r['race_id']:r for r in map(json.loads,cp.read_text().splitlines())};assert len(choices)==1779
    a=json.loads((H/'ROOT_SOURCE_AUDIT.json').read_text())
    fp=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
    bp=ROOT/'jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet'
    assert sha(fp)==a['source_hashes'][str(fp.relative_to(ROOT))] and sha(bp)==a['source_hashes'][str(bp.relative_to(ROOT))]
    f=pd.read_parquet(fp,columns=['api_record_id','year','mean5_rank_fraction']+COUNTS+MEANS,filters=[('year','>=',2024)])
    b=pd.read_parquet(bp,columns=['api_record_id','race_id','horse_id','horse_number','score','year'])
    d=b.merge(f.drop(columns='year'),on='api_record_id',validate='one_to_one');assert len(d)==17412
    models={y:json.loads((S/f'outputs/model_{y}.json').read_text()) for y in [2024,2025,2026]}
    maxerr=0.;candidate_count=0;reordered=0
    for rid,g in d.groupby('race_id',sort=True):
        g=g.sort_values('horse_number');m=models[int(g.year.iloc[0])];n=len(g)
        x=raw_inputs(g);x=np.nan_to_num((x-np.array(m['feature_means']))/np.array(m['feature_scales']),nan=0.)
        score=g.score.to_numpy(float);z=(score-score.mean())/score.std(ddof=0) if score.std(ddof=0)>0 else np.zeros(n)
        u=z+x@np.array(m['beta']);ix=np.array(list(combinations(range(n),5)))
        energy=u[ix].sum(axis=1);prior=z[ix].sum(axis=1);nums=g.horse_number.to_numpy(int);ids=g.horse_id.astype(str).to_numpy()
        raw=sorted(range(n),key=lambda i:(-score[i],nums[i]))[:5];rawset=set(raw)
        def choose(e):
            tied=np.flatnonzero(abs(e-e.max())<=1e-12)
            return min(tied,key=lambda k:(-len(set(ix[k])&rawset),tuple(nums[ix[k]])))
        winner=choose(energy);zero=choose(prior);r=choices[rid]
        assert set(ids[ix[zero]])==set(ids[raw])==set(r['baseline_top5_horse_ids'])
        assert list(ids[ix[winner]])==r['selector_top5_horse_ids']
        assert list(nums[ix[winner]])==r['selector_top5_horse_numbers']
        err=abs(float(energy[winner])-r['selector_energy']);maxerr=max(maxerr,err);assert err<1e-10
        # Reverse row order: additive utility by horse ID is unchanged.
        rev=g.iloc[::-1];xr=raw_inputs(rev);xr=np.nan_to_num((xr-np.array(m['feature_means']))/np.array(m['feature_scales']),nan=0.)
        sr=rev.score.to_numpy(float);zr=(sr-sr.mean())/sr.std(ddof=0) if sr.std(ddof=0)>0 else np.zeros(n)
        assert np.allclose((zr+xr@np.array(m['beta']))[::-1],u,rtol=0,atol=1e-12)
        reordered+=1;candidate_count+=len(ix)
    out=dict(passed=True,evaluation_outcomes_read=False,independent_no_candidate_import=True,races=len(choices),candidate_sets=candidate_count,zero_beta_identity=1779,reverse_order_invariance=reordered,max_energy_error=maxerr,choices_sha256=sha(cp))
    with (H/'ROOT_CHOICES_AUDIT.json').open('x') as o:json.dump(out,o,indent=2);o.write('\n')
    print(json.dumps(out))
if __name__=='__main__':main()
