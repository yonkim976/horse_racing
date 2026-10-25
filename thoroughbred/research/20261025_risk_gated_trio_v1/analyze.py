"""Fixed prior-year risk thresholds for conditional extra trio tickets."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=R.parents[1]
OUT=HERE/'outputs'
RISK=R/'20261024_axis_failure_risk_v1/outputs'
RET=R/'20261025_trio_six_ten_returns_v1/outputs'
OLD=R/'20261024_axis4_trio_comparison_v1/outputs'
OP=ROOT/'data/research/thoroughbred_boundary_20260918_v6/A_horse_predictions.parquet'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(p,obj):
    assert p.resolve().is_relative_to(HERE)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def flags(g,policy):
    if policy=='always_six':return np.zeros(len(g),dtype=bool)
    if policy=='always_ten':return np.ones(len(g),dtype=bool)
    if policy=='risk_model':return g.model_warning.to_numpy(bool)
    if policy=='risk_simple':return g.simple_warning.to_numpy(bool)
    raise ValueError(policy)


def policies(model):
    return ['always_six','always_ten','risk_model','risk_simple'] if model=='state_gbm118' else ['always_six','always_ten','risk_simple']


def prepare():
    rp=pd.read_parquet(RISK/'race_predictions.parquet')
    parts=[];thresholds=[]
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=RISK/'risk_models'/f'axis_failure_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            pred=pd.read_parquet(folder/'predictions.parquet')
            cal=pred[pred.phase.eq('calibration')]
            assert cal.year.eq(year-1).all() and meta['calibration_year']==year-1
            assert pd.Timestamp(meta['calibration_last_date'])<pd.Timestamp(f'{year}-01-01')
            g=rp[rp.meet.eq(meet)&rp.year.eq(year)].copy()
            g['model']='state_gbm118'
            g['simple_risk']=g.base_risk
            g['simple_threshold']=float(np.quantile(cal.base_risk,.8))
            g['model_threshold']=float(np.quantile(cal.model_risk,.8))
            assert abs(g.simple_threshold.iloc[0]-meta['warning_thresholds']['base_risk'])<1e-12
            assert abs(g.model_threshold.iloc[0]-meta['warning_thresholds']['model_risk'])<1e-12
            g['simple_warning']=g.simple_risk.ge(g.simple_threshold)
            g['model_warning']=g.model_risk.ge(g.model_threshold)
            assert g.simple_warning.eq(g.base_risk_warning).all() and g.model_warning.eq(g.model_risk_warning).all()
            g['source_axis']=g.axis_program_no
            parts.append(g[['race_key','race_date','year','meet','model','source_axis','simple_risk','simple_threshold','simple_warning','model_risk','model_threshold','model_warning']])
            thresholds.append(dict(model='state_gbm118',meet=meet,year=year,calibration_year=year-1,
                calibration_races=len(cal),calibration_last_date=str(cal.race_date.max()),
                simple_threshold=float(g.simple_threshold.iloc[0]),model_threshold=float(g.model_threshold.iloc[0])))
    op=pd.read_parquet(OP)
    op=op[op.candidate.eq('current_A')&op.venue_code.isin(['SEOUL','BUSAN'])&op.race_date.ge('2023-01-01')].copy()
    z=op.race_id.str.extract(r'RACE:(SEOUL|BUSAN):(\d{8}):(\d+)')
    op['race_key']=z[0].map({'SEOUL':'1','BUSAN':'3'})+':'+z[1]+':'+z[2].astype(int).astype(str)
    races=op.groupby('race_key').agg(probability=('probability','max'),race_date=('race_date','first'),venue=('venue_code','first')).reset_index()
    races['year']=races.race_date.dt.year;races['meet']=races.venue.map({'SEOUL':1,'BUSAN':3})
    races['simple_risk']=1-races.probability
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            cal=races[races.meet.eq(meet)&races.year.eq(year-1)]
            assert len(cal)>0 and cal.race_date.max()<pd.Timestamp(f'{year}-01-01')
            g=races[races.meet.eq(meet)&races.year.eq(year)].copy()
            g['model']='operating_A_v5';g['source_axis']=pd.NA
            g['simple_threshold']=float(np.quantile(cal.simple_risk,.8))
            g['simple_warning']=g.simple_risk.ge(g.simple_threshold)
            g['model_risk']=np.nan;g['model_threshold']=np.nan;g['model_warning']=False
            thresholds.append(dict(model='operating_A_v5',meet=meet,year=year,calibration_year=year-1,
                calibration_races=len(cal),calibration_last_date=str(cal.race_date.max()),
                simple_threshold=float(g.simple_threshold.iloc[0]),model_threshold=None))
            parts.append(g[['race_key','race_date','year','meet','model','source_axis','simple_risk','simple_threshold','simple_warning','model_risk','model_threshold','model_warning']])
    gate=pd.concat(parts,ignore_index=True)
    assert not gate.duplicated(['race_key','model']).any()
    f=pd.read_parquet(RET/'race_returns.parquet')
    f=f[f.model.isin(['state_gbm118','operating_A_v5'])].copy()
    # Operating risk is attached to the original A maximum. A withdrawal-filtered
    # roster can change that axis, so only exact-roster operating races are used.
    f=f[~f.model.eq('operating_A_v5')|f.scope.eq('identical_roster')].copy()
    axes=pd.read_parquet(OLD/'race_results.parquet',columns=['race_key','model','scope','axis','axis_hit'])
    f=f.merge(axes,on=['race_key','model','scope'],validate='1:1')
    fields=['race_key','model','source_axis','simple_risk','simple_threshold','simple_warning','model_risk','model_threshold','model_warning']
    f=f.merge(gate[fields],on=['race_key','model'],validate='m:1')
    assert f.groupby(['scope','model']).size().loc[('identical_roster','state_gbm118')]==4133
    actual=f[f.model.eq('state_gbm118')]
    assert actual.axis.eq(actual.source_axis).all()
    assert np.max(np.abs(actual.simple_risk-(1-rp.set_index('race_key').loc[actual.race_key,'base_axis_probability'].to_numpy())))<1e-12
    used=f[['race_key','model']].drop_duplicates()
    gate=gate.merge(used,on=['race_key','model'],validate='1:1')
    return f,gate,thresholds


def groups(f):
    yield 'all',f
    for y,g in f.groupby('year'):yield str(y),g
    for m,g in f.groupby('meet'):yield 'seoul' if m==1 else 'busan',g


def summarize(f):
    rows=[];diagnostics=[];contrasts=[]
    for (scope,model),one in f.groupby(['scope','model']):
        for name,g in groups(one):
            for policy in policies(model):
                warn=flags(g,policy)
                ticket_count=6+4*warn.astype(int)
                hit=g.six_hit.to_numpy(bool)|(g.extra_hit.to_numpy(bool)&warn)
                extra_hit=g.extra_hit.to_numpy(bool)&warn
                returned=g.dividend.to_numpy()*hit*1000
                extra_return=g.dividend.to_numpy()*extra_hit*1000
                cost=int(ticket_count.sum())*1000;extra_cost=int(warn.sum())*4000
                paid=g.dividend.to_numpy()[extra_hit]
                rows.append(dict(scope=scope,subgroup=name,model=model,policy=policy,races=len(g),
                    extra_bought_races=int(warn.sum()),extra_bought_fraction=float(warn.mean()),
                    mean_tickets=float(ticket_count.mean()),hits=int(hit.sum()),hit_rate=float(hit.mean()),
                    stake_krw=cost,return_krw=round(float(returned.sum()),6),
                    net_krw=round(float(returned.sum()-cost),6),roi=float(returned.sum()/cost-1),
                    extra_hits=int(extra_hit.sum()),extra_stake_krw=extra_cost,
                    extra_return_krw=round(float(extra_return.sum()),6),
                    extra_net_krw=round(float(extra_return.sum()-extra_cost),6),
                    extra_roi=float(extra_return.sum()/extra_cost-1) if extra_cost else None,
                    extra_winning_mean=float(paid.mean()) if len(paid) else None,
                    extra_winning_median=float(np.median(paid)) if len(paid) else None))
            for policy in [x for x in policies(model) if x.startswith('risk_')]:
                warn=flags(g,policy)
                for high in [True,False]:
                    z=g[warn==high]
                    diagnostics.append(dict(scope=scope,subgroup=name,model=model,policy=policy,high_risk=high,
                        races=len(z),axis_failures=int((~z.axis_hit).sum()),actual_axis_failure_rate=float((~z.axis_hit).mean()),
                        extra_four_events=int(z.extra_hit.sum()),extra_four_event_rate=float(z.extra_hit.mean()),
                        extra_four_payout_units=float((z.dividend*z.extra_hit).sum()),
                        extra_four_hypothetical_roi=float((z.dividend*z.extra_hit).sum()/(4*len(z))-1)))
            if scope=='identical_roster' and name in ['all','2024','2025','2026']:
                daily={}
                for policy in policies(model):
                    warn=flags(g,policy);hit=g.six_hit.to_numpy(bool)|(g.extra_hit.to_numpy(bool)&warn)
                    z=g.assign(cost=6+4*warn.astype(int),paid=g.dividend.to_numpy()*hit,hit=hit)
                    daily[policy]=z.groupby('race_date').agg(n=('race_key','size'),cost=('cost','sum'),paid=('paid','sum'),hits=('hit','sum'))
                n_dates=len(daily['always_six']);rng=np.random.default_rng(20261025)
                w=rng.multinomial(n_dates,np.full(n_dates,1/n_dates),size=2000)
                boot_roi={p:(w@d.paid.to_numpy())/(w@d.cost.to_numpy())-1 for p,d in daily.items()}
                boot_hit={p:(w@d.hits.to_numpy())/(w@d.n.to_numpy()) for p,d in daily.items()}
                for policy in [x for x in policies(model) if x.startswith('risk_')]:
                    for baseline in ['always_six','always_ten']:
                        for metric,b in [('roi',boot_roi),('hit_rate',boot_hit)]:
                            ci=np.quantile(b[policy]-b[baseline],[.025,.975])
                            cand=daily[policy];base=daily[baseline]
                            value=(cand.paid.sum()/cand.cost.sum()-base.paid.sum()/base.cost.sum()) if metric=='roi' else (cand.hits.sum()-base.hits.sum())/cand.n.sum()
                            contrasts.append(dict(scope=scope,subgroup=name,model=model,policy=policy,baseline=baseline,
                                metric=metric,races=len(g),dates=n_dates,difference=float(value),ci_low=float(ci[0]),ci_high=float(ci[1])))
    return pd.DataFrame(rows),pd.DataFrame(diagnostics),pd.DataFrame(contrasts)


def main():
    OUT.mkdir(exist_ok=True)
    paths=[HERE/'PLAN.md',OP,RISK/'race_predictions.parquet',RISK/'verification.json',
        RET/'race_returns.parquet',RET/'return_summary.csv',RET/'verification.json',
        OLD/'race_results.parquet',ROOT/'config/prediction_model_registry.json']
    for folder in sorted((RISK/'risk_models').iterdir()):
        if folder.is_dir():paths += [folder/'metadata.json',folder/'predictions.parquet']
    manifest={str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in paths}
    save(OUT/'input_manifest.json',manifest)
    shared=[R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md',R/'conclusions/source_manifest.json',R/'ARTIFACT_SIZE_LOG.md']
    if not (OUT/'publication_before.json').exists():save(OUT/'publication_before.json',{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
    f,gate,thresholds=prepare()
    gate.to_parquet(OUT/'risk_gates.parquet',compression='zstd',index=False)
    save(OUT/'thresholds.json',thresholds)
    s,d,c=summarize(f)
    s.to_csv(OUT/'summary.csv',index=False);d.to_csv(OUT/'risk_diagnostics.csv',index=False);c.to_csv(OUT/'paired_differences.csv',index=False)
    print(s[s.scope.eq('identical_roster') & s.subgroup.isin(['all','2024','2025','2026'])][['subgroup','model','policy','races','extra_bought_races','hits','hit_rate','stake_krw','return_krw','net_krw','roi','extra_roi']].to_string(index=False))
    for path,m in manifest.items():assert sha(ROOT/path)==m['sha256']


if __name__=='__main__':main()
