"""Repair the terminal manifest assertion without refitting or changing results."""
import json
import pandas as pd
import numpy as np
from features import HERE,ROOT,sha,save


def main():
    out=HERE/'run02'
    assert not (out/'verification_v3.json').exists()
    save(out/'failure.json',{'status':'completed_all_fit_and_scoring_failed_terminal_manifest_assertion',
        'exception':"TypeError: 'PosixPath' object is not subscriptable",
        'cause':"ROOT[r['path']] was used instead of ROOT / r['path'] in the final hash assertion",
        'repair':'this separate script validates the saved input manifest and finished outputs',
        'models_refit':False,'data_plan_metrics_changed':False})
    manifest=json.loads((out/'input_manifest.json').read_text())
    for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256']
    fits=json.loads((out/'fit_audit.json').read_text())
    pr=pd.read_csv(out/'predictions.csv')
    cmp=pd.read_csv(out/'paired_comparisons.csv')
    for _,g in pr.groupby('task'):
        columns=[c for c in ['p0','p1','p2','p3'] if g[c].notna().any()]
        p=g[columns].to_numpy();assert np.isfinite(p).all() and (p>0).all() and np.allclose(p.sum(axis=1),1,atol=1e-12)
    assert len(fits)==60 and all(r['converged'] and r['train_last_date']<=r['cutoff']<str(r['year'])+'-01-01' for r in fits)
    assert cmp.confirmatory_family.sum()==30
    save(out/'verification_v3.json',{'status':'passed','models':len(fits),'all_converged':True,
        'all_probabilities_positive_sum1':True,'all_train_cutoffs_precede_eval_year':True,
        'source_hashes_unchanged':True,'prediction_rows':len(pr),
        'evaluation_rows':pr.api_record_id.nunique(),'evaluation_races':pr.race_id.nunique(),
        'BH_family_size':30,'no_hyperparameter_search':True,'retrospective_not_independent_holdout':True,
        'terminal_assertion_repaired_without_refitting':True,'code_sha256':sha(HERE/'finalize_run_v3.py')})
    print('Final manifest check passed',flush=True)


if __name__=='__main__':main()
