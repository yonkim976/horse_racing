"""Where preselected leading-pack candidates actually ran, with explicit denominators."""
import numpy as np
import pandas as pd
from features import HERE,save,sha


def aggregate(g):
    k=g[g.known].copy();miss=k[k.actual_pack3.ne(0)]
    n=len(miss);second=int(miss.actual_pack3.eq(1).sum());behind=int(miss.actual_pack3.eq(2).sum())
    front=int(miss.actual_position4.eq(1).sum());mr=int(miss.actual_position4.isin([2,3]).sum());unknown=int(miss.actual_position4.isna().sum())
    assert second+behind==n and front+mr+unknown==n
    return {'selected':len(g),'known':len(k),'unknown':len(g)-len(k),'hits':int(k.actual_pack3.eq(0).sum()),'misses':n,
        'hit_rate':k.actual_pack3.eq(0).mean(),'second':second,'behind':behind,'second_given_miss':second/n if n else np.nan,
        'behind_given_miss':behind/n if n else np.nan,'front':front,'middle_rear':mr,'position_unknown':unknown,
        'front_given_miss':front/n if n else np.nan,'middle_rear_given_miss':mr/n if n else np.nan,
        'position_unknown_given_miss':unknown/n if n else np.nan,'front_given_miss_known_position':front/(front+mr) if front+mr else np.nan}


def intervals(g,rng):
    g=g[g.known].copy();g['miss']=g.actual_pack3.ne(0).astype(int);g['second']=g.actual_pack3.eq(1).astype(int)
    g['behind']=g.actual_pack3.eq(2).astype(int);g['front']=(g.actual_position4.eq(1)&g['miss'].eq(1)).astype(int)
    g['mr']=(g.actual_position4.isin([2,3])&g['miss'].eq(1)).astype(int)
    g['pu']=(g.actual_position4.isna()&g['miss'].eq(1)).astype(int);g['hit']=1-g['miss'];g['n']=1
    z=g.groupby('race_date')[['miss','second','behind','front','mr','pu','hit','n']].sum()
    if z.empty:return {}
    ix=rng.integers(len(z),size=(2000,len(z)));ans={}
    den=z['miss'].to_numpy()[ix].sum(axis=1)
    for col in ['second','behind','front','mr','pu']:
        num=z[col].to_numpy()[ix].sum(axis=1);valid=den>0
        lo,hi=np.quantile(num[valid]/den[valid],[.025,.975]) if valid.any() else [np.nan,np.nan]
        ans[col+'_lo']=lo;ans[col+'_hi']=hi
    hits=z['hit'].to_numpy()[ix].sum(axis=1)/z.n.to_numpy()[ix].sum(axis=1)
    ans['hit_lo'],ans['hit_hi']=np.quantile(hits,[.025,.975]);return ans


def main():
    out=HERE/'failures01';out.mkdir(exist_ok=False)
    top=pd.read_csv(HERE/'run01/top_first_pack.csv',dtype={'selected_horse_id':str})
    pr=pd.read_csv(HERE/'run01/predictions.csv',dtype={'horse_id':str})
    rng=np.random.default_rng(20261009);rows=[]
    period_masks=[('2024_2025',lambda g:g.year.le(2025)),('2026_partial',lambda g:g.year.eq(2026)),
        ('2024',lambda g:g.year.eq(2024)),('2025',lambda g:g.year.eq(2025))]
    all_argmax=pr[pr.task.eq('s1f_pack3')].copy()
    all_argmax=all_argmax[np.argmax(all_argmax[['p0','p1','p2']].to_numpy(),axis=1)==0]
    all_argmax=all_argmax.rename(columns={'y':'actual_pack3','y_s1f_position4':'actual_position4','race_distance_m':'distance'})
    all_argmax['known']=all_argmax.actual_pack3.notna()
    for kind,frame in [('top1_per_race',top),('all_argmax_firstpack',all_argmax)]:
        for model,g in frame.groupby('model'):
            for period,mask in period_masks:
                z=g[mask(g)]
                for dist in ['all']+sorted(z.distance.unique().tolist()):
                    v=z if dist=='all' else z[z.distance.eq(dist)]
                    for band in ['all','inner','middle','outer']:
                        w=v if band=='all' else v[v.gate_band.eq(band)]
                        if w.empty:continue
                        stats=aggregate(w)
                        # Intervals for the main per-race comparison; fine gate cells remain descriptive counts.
                        ints=intervals(w,rng) if kind=='top1_per_race' and band=='all' else {}
                        rows.append({'kind':kind,'model':model,'period':period,'distance':dist,'gate_band':band,**stats,**ints})
    counts=pd.DataFrame(rows);counts.to_csv(out/'miss_destination_counts.csv',index=False)
    # A conventional four-position forecast has its own labels and unknown coverage.
    four=pr[pr.task.eq('s1f_position4')].copy();four['predicted']=np.argmax(four[['p0','p1','p2','p3']].to_numpy(),axis=1)
    four=four[four.predicted.eq(0)];fourrows=[]
    for model,g in four.groupby('model'):
        for period,mask in period_masks:
            z=g[mask(g)]
            for dist in ['all']+sorted(z.race_distance_m.unique().tolist()):
                v=z if dist=='all' else z[z.race_distance_m.eq(dist)]
                k=v[v.y.notna()];miss=k[k.y.ne(0)];n=len(miss)
                front=int(miss.y.eq(1).sum());mr=int(miss.y.isin([2,3]).sum());assert front+mr==n
                fourrows.append({'model':model,'period':period,'distance':dist,'predicted_lead':len(v),'known':len(k),
                    'unknown':len(v)-len(k),'hits':int(k.y.eq(0).sum()),'misses_known':n,'front':front,'middle_rear':mr,
                    'front_given_miss_known':front/n if n else np.nan,'middle_rear_given_miss_known':mr/n if n else np.nan})
    pd.DataFrame(fourrows).to_csv(out/'four_position_lead_failures.csv',index=False)
    top['result']=np.select([~top.known,top.actual_pack3.eq(0),top.actual_pack3.eq(1)],['unknown','firstpack','secondpack'],default='third_or_beyond')
    top.to_csv(out/'all_top1_candidates_with_destinations.csv',index=False,encoding='utf-8-sig')
    # Independently count all selected rows by model/period against the aggregate table.
    for r in counts[(counts.kind=='top1_per_race')&(counts.distance.astype(str)=='all')&(counts.gate_band=='all')].itertuples():
        z=top[top.model.eq(r.model)];z=z[z.year.le(2025)] if r.period=='2024_2025' else z[z.year.eq(2026 if r.period=='2026_partial' else int(r.period))]
        assert len(z)==r.selected and z.result.eq('secondpack').sum()==r.second and z.result.eq('third_or_beyond').sum()==r.behind
    save(out/'verification.json',{'status':'passed','all_miss_denominators_partitioned':True,
        'secondpack_not_automatically_called_front_position':True,'unknown_position_retained_in_main_denominator':True,
        'primary_top1_rows':len(top),'aggregate_rows':len(counts),'code_sha256':sha(HERE/'failures.py')})
    print(counts[(counts.kind=='top1_per_race')&(counts.model.isin(['M1','M3','M4']))&(counts.distance.astype(str)=='all')&(counts.gate_band=='all')].to_string(index=False),flush=True)


if __name__=='__main__':main()
