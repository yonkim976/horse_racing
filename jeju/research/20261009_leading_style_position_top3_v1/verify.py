"""Rebuild pre-race style inputs from raw snapshot targets and independently sum rates."""
from bisect import bisect_left,bisect_right
from datetime import date,timedelta
import numpy as np
import pandas as pd
from analyze import HERE,ROOT,FEATURES,OUTCOMES,DEFS,sha,save,style

def main():
    out=HERE/'verification01';out.mkdir(exist_ok=False)
    manifest=__import__('json').loads((HERE/'run01/source_manifest.json').read_text())
    assert all(sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'] for r in manifest['files'])
    a=pd.read_csv(FEATURES/'features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    labels=pd.read_csv(HERE/'run01/start_labels_and_outcomes.csv',dtype={'horse_id':str})
    lineage=pd.read_csv(FEATURES/'history_lineage.csv',keep_default_na=False)
    original=pd.read_csv(OUTCOMES,usecols=['api_record_id','finish_position','top3'])
    target=original.set_index('api_record_id')
    assert (labels.top3.to_numpy()==target.loc[labels.api_record_id].finish_position.le(3).to_numpy()).all()
    assert (labels.top3.to_numpy()==target.loc[labels.api_record_id].top3.to_numpy()).all()
    lin=lineage.set_index('api_record_id');idx=a.set_index('api_record_id');rebuilt=[];windows=0
    for horse,g in a.groupby('horse_id'):
        g=g.sort_values(['race_date','race_number','api_record_id']);dates=g.race_date.tolist()
        for r in g.itertuples():
            dt=date.fromisoformat(r.race_date);lo=(dt-timedelta(days=730)).isoformat();cut=(dt-timedelta(days=2)).isoformat()
            prev=g.iloc[bisect_left(dates,lo):bisect_right(dates,cut)]
            row={'api_record_id':r.api_record_id}
            for scope in ['any','same']:
                hist=(prev if scope=='any' else prev[prev.race_distance_m.eq(r.race_distance_m)]).tail(10)
                expected='|'.join(hist.api_record_id.astype(str));assert lin.loc[r.api_record_id,scope+'_ids']==expected
                assert lin.loc[r.api_record_id,'history_cutoff']==cut
                assert r.api_record_id not in hist.api_record_id.values
                assert hist.horse_id.eq(horse).all()
                valid=hist.y_s1f_pack3.notna();frontvalid=hist.s1f_zone.notna()
                # Ensure group and position-observation validity coincide in this snapshot.
                assert np.array_equal(valid.to_numpy(),frontvalid.to_numpy())
                p='h_'+scope+'_'
                stats={p+'n':len(hist),p+'s1f_n':int(valid.sum()),p+'s1f_first_mean':hist.loc[valid].y_s1f_pack3.eq(0).mean(),p+'s1f_front_mean':hist.loc[frontvalid].s1f_zone.eq('front').mean()}
                for col,v in stats.items():assert np.isclose(idx.loc[r.api_record_id,col],v,equal_nan=True), (r.api_record_id,col)
                row.update(stats);windows+=1
            rebuilt.append(row)
    independent=pd.DataFrame(rebuilt).set_index('api_record_id').loc[labels.api_record_id].reset_index()
    for name,(scope,threshold) in DEFS.items():assert np.array_equal(style(independent,scope,threshold),labels['style_'+name])
    # Classification only reads eight historical fields, so perturb all current outcomes/positions.
    changed=labels.copy();changed['top3']=1-changed.top3;changed['finish_position']=99
    for c in ['y_s1f_pack3','y_s1f_position4','s1f_pack_index','s1f_zone']:changed[c]=np.nan
    for name,(scope,threshold) in DEFS.items():assert np.array_equal(style(changed,scope,threshold),labels['style_'+name])
    rates=pd.read_csv(HERE/'run01/rates.csv');checks=0
    def filter_view(a,view,key):
        if view=='all':return a
        if view=='period':return a[a.year.isin([2024,2025])] if key=='2024_2025' else a[a.year.eq(2026)]
        if view=='year':return a[a.year.eq(int(key))]
        if view=='distance':return a[a.race_distance_m.eq(int(key))]
        dist,yr=map(int,key.split('_'));return a[a.race_distance_m.eq(dist)&a.year.eq(yr)]
    for r in rates.itertuples():
        g=filter_view(labels,r.view,str(r.key));g=g[g['style_'+r.definition]&g.y_s1f_pack3.notna()]
        codes={'first':[0],'second':[1],'farther':[2],'nonfirst':[1,2]}
        g=g[g.y_s1f_pack3.isin(codes[r.actual_group])]
        assert len(g)==r.starts and g.top3.sum()==r.top3
        assert not len(g) or np.isclose(g.top3.mean(),r.rate)
        checks+=1
    for name in DEFS:
        rr=rates[(rates.definition==name)&rates.view.eq('all')].set_index('actual_group')
        assert rr.loc['second','starts']+rr.loc['farther','starts']==rr.loc['nonfirst','starts']
        assert rr.loc['second','top3']+rr.loc['farther','top3']==rr.loc['nonfirst','top3']
    assert not labels.horse_id.eq('3005648').any()
    save(out/'verification.json',{'status':'passed','history_windows_independently_rebuilt':windows,'classification_labels_checked':len(labels)*len(DEFS),
                                'rates_independently_recomputed':checks,'current_outcome_perturbation_style_invariant':True,
                                'finish_top3_identity':True,'source_hashes_unchanged':True,'excluded_horse_absent':True,
                                'no_database_opened':True})
    print('Independent verification passed',windows,checks,flush=True)
if __name__=='__main__':main()
