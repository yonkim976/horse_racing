"""Post-protocol robustness checks; exploratory, no candidate selection/model promotion."""
import re
import numpy as np
import pandas as pd
from common import *
from analyze import controls,cluster_fit,contrast,paired_raw,bh

def fit(g):
    C,names=controls(g);cols=[g.band.eq('MIDDLE').to_numpy(float),g.band.eq('OUTER').to_numpy(float)];labels=['MIDDLE','OUTER'];cats={}
    for key in ['quarter','distance_m','condition']:
        cats[key]=sorted(g[key].unique())
        for value in cats[key][1:]:
            for band in ['MIDDLE','OUTER']:
                cols.append((g.band.eq(band)&g[key].eq(value)).to_numpy(float));labels.append(f'{band}:{key}:{value}')
    cols.extend(C.T);labels.extend(names);X=np.column_stack(cols)
    b,V,G,rank=cluster_fit(g,X,g.top3.to_numpy(float));idx={s:i for i,s in enumerate(labels)}
    races=g.drop_duplicates('race_id');weights={key:races[key].value_counts(normalize=True).to_dict() for key in cats}
    rc=pd.factorize(g.race_id)[0];counts=np.bincount(rc)
    xc=np.column_stack([x-np.bincount(rc,weights=x)[rc]/counts[rc] for x in X.T]);gram=xc.T@(xc/counts[rc,None])
    projector=np.linalg.pinv(gram,rcond=1e-10)@gram
    errors=[]
    def vec(fixed=None):
        c=np.zeros(len(labels));c[idx['OUTER']]=1
        for key in cats:
            for value in cats[key][1:]:
                c[idx[f'OUTER:{key}:{value}']]=float(fixed[key]==value) if fixed and key in fixed else weights[key][value]
        errors.append(float(np.max(np.abs(c-projector@c))))
        return c
    mean=vec();periods=[];conditions=[]
    for q in cats['quarter']:
        c=vec({'quarter':q});block=g[g.quarter.eq(q)]
        periods.append({'quarter':q,'races':block.race_id.nunique(),'days':block.race_date.nunique(),**contrast(b,V,G,c),**{'deviation_'+k:v for k,v in contrast(b,V,G,c-mean).items()}})
    dry=vec({'condition':'건조'})
    for condition in cats['condition']:
        c=vec({'condition':condition})
        conditions.append({'condition':condition,**contrast(b,V,G,c),**{'vs_dry_'+k:v for k,v in contrast(b,V,G,c-dry).items()}})
    assert max(errors)<1e-7,errors
    return periods,conditions,{'columns':len(labels),'rank':rank,'max_contrast_nonestimability':max(errors),'longrun':contrast(b,V,G,mean)}

def main():
    d=pd.read_parquet(OUT/'runners.parquet');periods=[];conditions=[];diagnostics=[];overall=[]
    for name in ['primary','common_1200_1300_1400','innermost3_outermost3_N8plus']:
        f=d.copy()
        if name.startswith('common'):f=f[f.distance_m.isin([1200,1300,1400])].copy()
        if name.startswith('innermost'):
            f=f[f.n.ge(8)].copy();r=f.groupby('race_id').gate_number.rank();f['band']=np.where(r.le(3),'INNER',np.where(r.gt(f.n-3),'OUTER','MIDDLE'))
        for venue,g in f.groupby('venue'):
            ps,cs,diag=fit(g)
            periods.extend({'variant':name,'venue':venue,**x} for x in ps)
            conditions.extend({'variant':name,'venue':venue,**x} for x in cs)
            diagnostics.append({'variant':name,'venue':venue,**diag})
            C,_=controls(g);X=np.column_stack([g.band.eq('MIDDLE'),g.band.eq('OUTER'),C]).astype(float)
            b,V,G,_=cluster_fit(g,X,g.top3.to_numpy(float));c=np.zeros(len(b));c[1]=1
            overall.append({'variant':name,'venue':venue,**contrast(b,V,G,c)})
            print(name,venue,'done',flush=True)
    ps=pd.DataFrame(periods);ps['deviation_q_within_variant']=ps.groupby('variant').deviation_p.transform(lambda x:bh(x));ps.to_parquet(OUT/'sensitivity_quarters.parquet',index=False)
    cs=pd.DataFrame(conditions);cs['vs_dry_q_within_variant']=cs.groupby('variant').vs_dry_p.transform(lambda x:bh(x));cs.to_parquet(OUT/'standardized_conditions.parquet',index=False)
    pd.DataFrame(overall).to_parquet(OUT/'sensitivity_overall.parquet',index=False);dump('sensitivity_diagnostics.json',diagnostics)
    # Same fixed quarters, delete each day in turn from unadjusted race-equal contrasts.
    loo=[]
    for (venue,quarter),g in d.groupby(['venue','quarter']):
        z=g.groupby(['race_id','race_date','band']).top3.mean().unstack('band');z=z.OUTER-z.INNER
        daily=z.groupby(level='race_date').agg(['sum','count']);est=(z.sum()-daily['sum'])/(len(z)-daily['count'])
        loo.append({'venue':venue,'quarter':quarter,'raw':float(z.mean()),'leave_one_day_min':float(est.min()),'leave_one_day_max':float(est.max())})
    pd.DataFrame(loo).to_parquet(OUT/'quarter_leave_one_day.parquet',index=False)
    # Independent raw-text rank/number extraction: first and last available date per venue-quarter.
    checks=[];missing=[]
    for (venue,quarter),g in d.groupby(['venue','quarter']):
        for date in [g.race_date.min(),g.race_date.max()]:
            meet=1 if venue=='SEOUL' else 3;stamp=date.strftime('%Y%m%d');f=ROOT/f'data/raw/kra_text/dacom11/meet={meet}/year={stamp[:4]}/month={stamp[4:6]}/day={stamp[6:]}/{stamp}dacom11.rpt'
            if not f.exists():missing.append(str(f));continue
            text=f.read_bytes().decode('cp949',errors='replace')
            for block in re.split(r'제목\s*:',text)[1:]:
                race_match=re.search(r'제\s*(\d+)경주',block)
                if not race_match:continue
                rn=int(race_match[1]);subset=g[g.race_date.eq(date)&g.race_number.eq(rn)]
                if subset.empty:continue
                first=block.split('순위 마번')[1].split('순위 마번')[0] if '순위 마번' in block else ''
                raw={int(m[2]):int(m[1]) for line in first.splitlines() if (m:=re.match(r'^\s*(\d+)\s+(\d+)\s+[^\d\s]',line))}
                stored=dict(zip(subset.horse_number.astype(int),subset.finish_position.astype(int)))
                checks.append({'venue':venue,'quarter':quarter,'date':str(date.date()),'race':rn,'matched':all(raw.get(k)==v for k,v in stored.items()),'entries':len(stored),'source_path':str(f.relative_to(ROOT))})
    dump('raw_rank_checks.json',{'checks':checks,'missing_files':missing,'matched_races':sum(x['matched'] for x in checks),'checked_races':len(checks),'checked_entries':sum(x['entries'] for x in checks),'gate_number_storage':'dacom11 loader assigns gate_number=horse_number; actual stall changes are not independently observed'})
    assert checks and all(x['matched'] for x in checks),[x for x in checks if not x['matched']][:10]
    primary=ps[ps.variant.eq('primary')].merge(pd.read_parquet(OUT/'quarter_effects.parquet'),on=['venue','quarter'])
    assert np.allclose(primary.effect,primary.standardized_effect,atol=1e-9)
    print('source checks',len(checks),'matched; sensitivity complete',flush=True)

if __name__=='__main__':main()
