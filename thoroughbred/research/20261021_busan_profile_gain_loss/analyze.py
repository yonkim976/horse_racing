"""Saved-score gain/loss diagnosis. No DB access, training, or model mutation."""

import hashlib
import json
import re
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
OLD=R/'20261021_busan_all_distance_profiles/outputs'
SEED=20261021
RACE=['date','race_no']


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for name,v in json.loads((OUT/'input_manifest.json').read_text()).items():
        path=ROOT/name
        assert path.stat().st_size==v['bytes'] and sha(path)==v['sha256'],name


def choose(frame,model):
    return frame.sort_values(RACE+['raw_'+model,'program_no'],ascending=[True,True,False,True]).groupby(RACE).head(1)


def prior_raw(d):
    """Direct last-five same-distance window, with invalid full partitions withheld."""
    order=d.sort_values(['horse_id','distance','date','race_no']).index.to_numpy();g=d.loc[order]
    i=np.arange(len(g));new=g[['horse_id','distance']].ne(g[['horse_id','distance']].shift()).any(axis=1)
    start=np.maximum.accumulate(np.where(new,i,0));slots=i[:,None]-np.arange(1,6);valid=slots>=start[:,None]
    take=order[np.maximum(slots,0)];out={}
    raw=dict(early200=d.S1F,late600=d.finish-d.G3F,late400=d.finish-d.G2F,late200=d.finish-d.G1F)
    for name,source in raw.items():
        z=source.where(d.complete).to_numpy()[take];good=valid&np.isfinite(z);count=good.sum(axis=1)
        mean=np.divide(np.where(good,z,0).sum(axis=1),count,out=np.full(len(d),np.nan),where=count>0)
        a=np.full(len(d),np.nan);a[order]=mean;out['same_'+name+'_seconds']=a
        a=np.zeros(len(d),int);a[order]=count;out['same_'+name+'_n']=a
    return pd.DataFrame(out)


def condition_table(cases,column):
    rows=[]
    for (year,value),g in cases.groupby(['year',column],dropna=False):
        swap=g[g.changed]
        rows.append(dict(year=int(year),condition=str(value),all_races=len(g),changed=len(swap),
            gain=int(g.gain.sum()),loss=int(g.loss.sum()),net=int(g.gain.sum()-g.loss.sum()),
            changed_gain_rate=float(swap.gain.mean()) if len(swap) else None,
            changed_loss_rate=float(swap.loss.mean()) if len(swap) else None))
    return pd.DataFrame(rows)


def mean_contrast(g,metric,rng):
    q=g[g.outcome.isin(['gain','loss'])&g[metric].notna()].copy()
    count=q.groupby('outcome').size()
    if count.get('gain',0)<5 or count.get('loss',0)<5:return None
    pivot=q.pivot_table(index='date',columns='outcome',values=metric,aggfunc=['sum','count'],fill_value=0)
    ix=rng.integers(0,len(pivot),size=(2000,len(pivot)))
    means=[]
    for kind in ['gain','loss']:
        sums=pivot['sum',kind].to_numpy()[ix].sum(axis=1)
        n=pivot['count',kind].to_numpy()[ix].sum(axis=1)
        means.append(np.divide(sums,n,out=np.full(2000,np.nan),where=n>0))
    delta=means[0]-means[1];delta=delta[np.isfinite(delta)]
    return dict(metric=metric,gain_n=int(count['gain']),loss_n=int(count['loss']),
        gain_mean=float(q[q.outcome.eq('gain')][metric].mean()),loss_mean=float(q[q.outcome.eq('loss')][metric].mean()),
        mean_difference=float(q[q.outcome.eq('gain')][metric].mean()-q[q.outcome.eq('loss')][metric].mean()),
        low=float(np.quantile(delta,.025)),high=float(np.quantile(delta,.975)),bootstrap=len(delta))


def main():
    check()
    d=pd.read_parquet(OLD/'profiles.parquet');x=pd.read_parquet(OLD/'features.parquet')
    prediction=pd.read_parquet(OLD/'predictions.parquet');rawhist=prior_raw(d)
    a=choose(prediction,'B0').set_index(RACE);b=choose(prediction,'B3').set_index(RACE)
    cases=a[['row_id','year','distance']].rename(columns={'row_id':'old_id'}).join(b[['row_id']].rename(columns={'row_id':'new_id'})).reset_index()
    cases['case_id']=cases.date+':'+cases.race_no.astype(str)
    cases['changed']=cases.old_id.ne(cases.new_id)
    selected=[]
    for role in ['old','new']:
        ids=cases[role+'_id'].to_numpy(int);info=d.loc[ids].reset_index(drop=True)
        assert np.array_equal(info.date,cases.date) and np.array_equal(info.distance,cases.distance)
        model=x.loc[ids].reset_index(drop=True);history=rawhist.loc[ids].reset_index(drop=True)
        keep=['horse_id','horse_name','program_no','finish_rank','finish','grade','S1F','G3F','G2F','G1F','p_S1F','p_G2F','p_G1F','complete']
        values={name:info[name] for name in keep}
        values.update(hist_all_n=model.all_performance_n,hist_same_n=model.same_performance_n,
            hist_style_n=model.all_style_0_n,hist_performance=model.all_performance_mean,
            hist_same_performance=model.same_performance_mean,hist_early_q=model.all_early_q_mean,
            hist_late_gain=model.all_late_gain_mean)
        for label,col,length in [('early200','early',200),('late600','tail600',600),('late400','tail400',400),('late200','tail200',200)]:
            values['hist_'+label+'_index']=model['all_c_'+col+'_index_mean']
            values['hist_'+label+'_field_adv_seconds']=model['all_c_'+col+'_adv_mean']*length/1000
            values['same_'+label+'_seconds']=history['same_'+label+'_seconds']
            values['same_'+label+'_n']=history['same_'+label+'_n']
            current=info.S1F if label=='early200' else info.finish-info['G'+str(length//200)+'F']
            values['actual_'+label+'_seconds']=current.where(info.complete)
        joined=pd.DataFrame(values)
        cases=pd.concat([cases,joined.add_prefix(role+'_')],axis=1)
        selected.append(pd.concat([cases[['case_id','date','race_no','year','distance']].assign(role=role,row_id=ids),joined],axis=1))
    cases['old_hit']=cases.old_finish_rank.le(3);cases['new_hit']=cases.new_finish_rank.le(3)
    cases['gain']=~cases.old_hit&cases.new_hit;cases['loss']=cases.old_hit&~cases.new_hit
    cases['outcome']=np.select([cases.gain,cases.loss,cases.old_hit&cases.new_hit],['gain','loss','both_hit'],default='both_miss')
    assert not (cases.loc[~cases.changed,'gain']|cases.loc[~cases.changed,'loss']).any()
    assert cases.old_grade.fillna('').eq(cases.new_grade.fillna('')).all()
    cases['grade_label']=cases.old_grade.fillna('미상').map(lambda z:re.sub(r'등급|\s','',str(z)))
    cases['grade_number']=pd.to_numeric(cases.grade_label.str.extract(r'(\d+)',expand=False),errors='coerce').fillna(-1).astype(int)
    cases['distance_grade']=cases.distance.astype(str)+'m·'+cases.grade_number.astype(str)+'등급'
    cases['monthday']=cases.date.str[4:]
    numeric=['hist_all_n','hist_same_n','hist_style_n','hist_performance','hist_same_performance','hist_early_q','hist_late_gain']
    for label in ['early200','late600','late400','late200']:
        numeric += ['hist_'+label+'_index','hist_'+label+'_field_adv_seconds','same_'+label+'_seconds','same_'+label+'_n','actual_'+label+'_seconds']
    for name in numeric:cases['delta_'+name]=cases['new_'+name]-cases['old_'+name]
    for scope in ['all','same']:
        old=cases['old_hist_'+scope+'_n'];new=cases['new_hist_'+scope+'_n']
        cases[scope+'_history_pair']=np.select([old.eq(0)&new.eq(0),old.ge(3)&new.ge(3),old.ge(3)&new.lt(3),old.lt(3)&new.ge(3)],
            ['둘다0','둘다3~5','기존3~5·신규0~2','기존0~2·신규3~5'],default='그외0~2')
    e=cases.delta_hist_early200_field_adv_seconds;l=cases.delta_hist_late200_field_adv_seconds
    cases['early_late_pair']=np.select([e.isna()|l.isna(),e.ge(0)&l.ge(0),e.ge(0)&l.lt(0),e.lt(0)&l.ge(0)],
        ['미확인','초반·종반둘다우위','초반우위·종반열위','초반열위·종반우위'],default='초반·종반둘다열위')
    cases.to_parquet(OUT/'all_race_pairs.parquet',index=False)
    pd.concat(selected).to_parquet(OUT/'selected_horses.parquet',index=False)
    changed=cases[cases.changed].copy()
    changed.to_csv(OUT/'changed_races.csv',index=False)
    for col in ['distance','grade_label','grade_number','distance_grade','all_history_pair','same_history_pair','early_late_pair']:
        condition_table(cases,col).to_csv(OUT/(col+'_counts.csv'),index=False)
    summary=[]
    for year,g in cases.groupby('year'):
        summary.append(dict(year=int(year),races=len(g),changed=int(g.changed.sum()),gain=int(g.gain.sum()),loss=int(g.loss.sum()),
            both_hit=int((g.changed&g.outcome.eq('both_hit')).sum()),both_miss=int((g.changed&g.outcome.eq('both_miss')).sum()),net=int(g.gain.sum()-g.loss.sum())))
    assert [(z['gain'],z['loss'])for z in summary]==[(16,24),(29,27),(22,12)]
    pd.DataFrame(summary).to_csv(OUT/'year_summary.csv',index=False)
    stat=[]
    for (year,outcome),g in changed.groupby(['year','outcome']):
        for name in numeric:
            for role in ['old','new','delta']:
                values=g[role+'_'+name].dropna()
                stat.append(dict(year=int(year),outcome=outcome,metric=name,role=role,n=len(values),mean=float(values.mean())if len(values)else None,median=float(values.median())if len(values)else None))
    pd.DataFrame(stat).to_csv(OUT/'feature_summaries.csv',index=False)
    rng=np.random.default_rng(SEED);contrasts=[]
    for year,g in changed.groupby('year'):
        for name in numeric:
            contrast=mean_contrast(g,'delta_'+name,rng)
            if contrast:contrasts.append(dict(year=int(year),**contrast))
    pd.DataFrame(contrasts).to_csv(OUT/'gain_loss_contrasts.csv',index=False)
    # Calendar matching and shared distance×grade cells, with coverage explicitly retained.
    common=cases[cases.year.isin([2024,2026])&cases.monthday.le('0918')].copy()
    cal=common.groupby('year').agg(races=('case_id','size'),gain=('gain','sum'),loss=('loss','sum'),changed=('changed','sum'))
    cal['net']=cal.gain-cal.loss;cal.to_csv(OUT/'calendar_matched.csv')
    cell=common.assign(net=common.gain.astype(int)-common.loss.astype(int)).groupby(['year','distance','grade_number']).agg(races=('case_id','size'),net=('net','sum')).reset_index()
    cells=cell.pivot(index=['distance','grade_number'],columns='year',values='races').fillna(0)
    supported=cells[(cells[2024]>=10)&(cells[2026]>=10)].index
    restricted=cell.set_index(['distance','grade_number']).loc[supported].reset_index()
    weight=restricted.groupby(['distance','grade_number']).races.sum();weight=weight/weight.sum()
    standardized=[]
    for year in [2024,2026]:
        z=restricted[restricted.year.eq(year)].set_index(['distance','grade_number'])
        standardized.append(dict(year=year,cells=len(supported),covered_races=int(z.races.sum()),calendar_races=int(cal.loc[year,'races']),
            covered_raw_net=int(z.net.sum()),covered_raw_net_rate=float(z.net.sum()/z.races.sum()),
            pooled_weight_standardized_net_rate=float((z.net/z.races*weight).sum())))
    restricted.to_csv(OUT/'standardization_cells.csv',index=False);save('standardization.json',standardized)
    # Apply only earlier-trained frozen2024 models to later2026; never reverse time.
    features=json.loads((OLD/'feature_sets.json').read_text());manifest=json.loads((OLD/'model_manifest.json').read_text())
    frozen=prediction[prediction.year.eq(2026)].copy()
    for model_name in ['B0','B3']:
        entry=next(m for m in manifest if m['model']==model_name and m['year']==2024)
        booster=lgb.Booster(model_file=str(ROOT/entry['path']))
        frozen['raw_'+model_name]=booster.predict(x.loc[frozen.row_id,features[model_name]],num_threads=4)
        frozen['pred_'+model_name]=frozen['raw_'+model_name]-frozen.groupby(RACE)['raw_'+model_name].transform('median')
    fa=choose(frozen,'B0').set_index(RACE);fb=choose(frozen,'B3').set_index(RACE)
    a_hit=fa.finish_rank.le(3);b_hit=fb.finish_rank.le(3)
    mae={model:float((frozen['pred_'+model]-frozen.target).abs().groupby([frozen.date,frozen.race_no]).mean().mean())for model in ['B0','B3']}
    save('frozen2024_on2026.json',dict(races=len(fa),B0_hits=int(a_hit.sum()),B3_hits=int(b_hit.sum()),gain=int((~a_hit&b_hit).sum()),loss=int((a_hit&~b_hit).sum()),
        net=int(b_hit.sum()-a_hit.sum()),changed=int(fa.horse_id.ne(fb.horse_id).sum()),mae_seconds_per1000m=mae,
        training_end='2023-12-31 or earlier',new_fits=0))
    frozen.to_parquet(OUT/'frozen2024_scores_on2026.parquet',index=False)
    # Exact local score decomposition, with changed basic-input contributions after refit.
    blocks=dict(base=features['B0'],curve=features['B1'][len(features['B0']):],section_position=features['B2'][len(features['B1']):],style8=features['B3'][len(features['B2']):])
    contribution_rows=[];group_rows=[];max_error=0
    pred_index=prediction.set_index('row_id')
    for year,g in changed.groupby('year'):
        ids=np.r_[g.new_id.to_numpy(int),g.old_id.to_numpy(int)];n=len(g)
        diffs={}
        for model_name in ['B0','B3']:
            entry=next(m for m in manifest if m['model']==model_name and m['year']==year)
            booster=lgb.Booster(model_file=str(ROOT/entry['path']));cols=features[model_name]
            values=booster.predict(x.loc[ids,cols],pred_contrib=True,num_threads=4)
            diff=values[:n,:-1]-values[n:,:-1]
            expected=pred_index.loc[g.new_id,'raw_'+model_name].to_numpy()-pred_index.loc[g.old_id,'raw_'+model_name].to_numpy()
            error=float(np.abs(diff.sum(axis=1)-expected).max());max_error=max(max_error,error)
            np.testing.assert_allclose(diff.sum(axis=1),expected,atol=1e-10,rtol=0)
            diffs[model_name]=pd.DataFrame(diff,columns=cols,index=g.index)
        for ix,row in g.iterrows():
            grouped={name:float(diffs['B3'].loc[ix,cols].sum()) for name,cols in blocks.items()}
            b0gap=float(diffs['B0'].loc[ix].sum());b3gap=sum(grouped.values())
            group_rows.append(dict(case_id=row.case_id,year=int(year),outcome=row.outcome,
                B0_new_minus_old=b0gap,B3_new_minus_old=b3gap,
                base_retrained_change=grouped['base']-b0gap,curve=grouped['curve'],section_position=grouped['section_position'],style8=grouped['style8']))
            for feature,value in diffs['B3'].loc[ix].items():
                contribution_rows.append(dict(case_id=row.case_id,year=int(year),outcome=row.outcome,feature=feature,new_minus_old_contribution=float(value)))
    pd.DataFrame(group_rows).to_csv(OUT/'score_group_differences.csv',index=False)
    pd.DataFrame(contribution_rows).to_parquet(OUT/'feature_contribution_differences.parquet',index=False)
    save('analysis_summary.json',dict(years=summary,common_calendar=cal.reset_index().to_dict('records'),
        changed_races=len(changed),gain_loss_races=int(changed.outcome.isin(['gain','loss']).sum()),
        score_contribution_max_error=max_error,standardization=standardized,new_fits=0,database_access=False,
        descriptions_are_posthoc_not_causal=True,operating_model_changed=False))
    print((OUT/'analysis_summary.json').read_text())
    print((OUT/'frozen2024_on2026.json').read_text())
    print(pd.read_csv(OUT/'feature_summaries.csv').query("role=='delta' and outcome in ['gain','loss'] and year in [2024,2026] and metric in ['hist_same_n','same_early200_seconds','same_late200_seconds','hist_early200_field_adv_seconds','hist_late200_field_adv_seconds','hist_same_performance']").to_string(index=False))


if __name__=='__main__':main()
