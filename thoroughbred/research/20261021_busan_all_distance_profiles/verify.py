"""Independent segment/history replay and saved-model checks; no new fitting."""

import gzip
import json
import re

import lightgbm as lgb
import numpy as np
import pandas as pd

import prepare as p


def main():
    p.check()
    d=pd.read_parquet(p.OUT/'profiles.parquet');x=pd.read_parquet(p.OUT/'features.parquet')
    sets=json.loads((p.OUT/'feature_sets.json').read_text())
    old=pd.read_csv(p.R/'20261017_section_layout_by_distance_v1/outputs/distance_layouts.csv')
    current=pd.read_csv(p.OUT/'distance_support.csv')
    cells=0
    for dist,g in d.groupby('distance'):
        expected=old[(old.meet.eq(3))&old.distance_m.eq(dist)].iloc[0]
        assert len(g)==expected['rows'] and g.complete.sum()==expected.detail_complete
        points=expected.points.split(' → ');lens=np.array(list(map(int,expected.lengths_m.split('+'))))
        matrix=np.column_stack([np.zeros(len(g))]+[g[z].to_numpy() for z in points[1:-1]]+[g.finish.to_numpy()])
        times=np.diff(matrix,axis=1);valid=np.isfinite(matrix).all(axis=1)&(times>0).all(axis=1)
        assert np.array_equal(valid,g.complete)
        total=np.zeros(valid.sum())
        for j,length in enumerate(lens,1):
            np.testing.assert_allclose(g.loc[valid,f's{j}_seconds'],times[valid,j-1],atol=1e-10,rtol=0)
            index=(length/times[valid,j-1])/(dist/g.loc[valid,'finish'].to_numpy())*100
            np.testing.assert_allclose(g.loc[valid,f's{j}_index'],index,atol=1e-10,rtol=0)
            np.testing.assert_allclose(g.loc[valid,f's{j}_delta'],index-100,atol=1e-10,rtol=0)
            total+=100*length/index;cells+=len(index)
        np.testing.assert_allclose(total,dist,atol=1e-9,rtol=0)
    previous=pd.read_parquet(p.R/'20261020_busan1200_six_section_profile/outputs/runner_profiles.parquet')
    a=d[d.distance.eq(1200)&d.complete].merge(previous[previous.complete_six],on=['date','race_no','horse_id'],suffixes=('_now','_old'),validate='one_to_one')
    assert len(a)==34660
    for i in range(1,7):
        np.testing.assert_allclose(a[f's{i}_index_now'],a[f's{i}_index_old'],atol=1e-10,rtol=0)
    history_cells=0
    for scope,keys in [('all',['horse_id']),('same',['horse_id','distance'])]:
        order=d.sort_values(keys+['date','race_no']).index.to_numpy();g=d.loc[order]
        i=np.arange(len(g));start=np.maximum.accumulate(np.where(g[keys].ne(g[keys].shift()).any(axis=1),i,0))
        indices=i[:,None]-np.arange(1,6);mask=indices>=start[:,None];take=order[np.maximum(indices,0)]
        for column in x.columns:
            match=re.fullmatch(scope+r'_(.+)_(mean|n)',column)
            if match is None:continue
            source,kind=match.groups()
            if source not in d:continue
            values=d[source].to_numpy(float)[take];good=mask&np.isfinite(values)
            count=good.sum(axis=1)
            if kind=='mean':
                result=np.divide(np.where(good,values,0).sum(axis=1),count,out=np.full(len(g),np.nan),where=count>0)
            else:result=count.astype(float)
            segment=re.match(r's([1-8])_',source)
            if segment is not None:
                applicable=d.loc[order,'s'+segment.group(1)+'_length'].notna().to_numpy()
                result[~applicable]=np.nan
            np.testing.assert_allclose(x.loc[order,column],result,atol=2e-8,rtol=0,equal_nan=True)
            history_cells+=len(result)
        parent=x.loc[order,scope+'_previous_row'].to_numpy(int);has=parent>=0
        assert (d.loc[parent[has],'date'].to_numpy()<g.loc[has,'date'].to_numpy()).all()
    assert d.style8.isin(p.STYLES+['미확인']).all()
    known=d.style8.ne('미확인')
    np.testing.assert_allclose(d.loc[known,['style_'+str(i) for i in range(8)]].sum(axis=1),1)
    models=json.loads((p.OUT/'model_manifest.json').read_text())
    prediction=pd.read_parquet(p.OUT/'predictions.parquet');replay_error=0
    for entry in models:
        path=p.ROOT/entry['path'];assert p.sha(path)==entry['sha256']
        assert entry['train_first']>='20170101' and entry['train_last']<str(entry['year'])+'0101'
        sub=prediction[prediction.year.eq(entry['year'])];ids=sub.row_id.to_numpy()
        model=lgb.Booster(model_file=str(path));assert model.feature_name()==sets[entry['model']]
        raw=model.predict(x.loc[ids,entry['features']],num_threads=4)
        error=float(np.max(np.abs(raw-sub['raw_'+entry['model']].to_numpy())));replay_error=max(replay_error,error)
        np.testing.assert_allclose(raw,sub['raw_'+entry['model']],atol=1e-12,rtol=0)
        centered=raw-pd.Series(raw,index=sub.index).groupby([sub.date,sub.race_no]).transform('median').to_numpy()
        np.testing.assert_allclose(centered,sub['pred_'+entry['model']],atol=1e-12,rtol=0)
    np.testing.assert_allclose(prediction.target,d.loc[prediction.row_id,'performance'],atol=0,rtol=0)
    rr=pd.read_csv(p.OUT/'race_metrics.csv',dtype={'date':str})
    for name in sets:
        value=(prediction['pred_'+name]-prediction.target).abs().groupby([prediction.date,prediction.race_no]).mean()
        observed=rr.set_index(['date','race_no'])[name+'_mae'].reindex(value.index)
        np.testing.assert_allclose(value,observed,atol=1e-12,rtol=0)
    # Deterministic raw sample: latest complete race, first two programme numbers at each distance.
    samples=[]
    for dist,g in d[d.complete].groupby('distance'):
        g=g.sort_values(['date','race_no','program_no']);last=g.iloc[-1]
        samples.append(g[g.date.eq(last.date)&g.race_no.eq(last.race_no)].head(2))
    sample=pd.concat(samples);raw_cells=0;raw_sources=[]
    fields=dict(zip(p.POINTS,['buS1fAccTime','buG8fAccTime','buG6fAccTime','buG4fAccTime','buG3fAccTime','buG2fAccTime','buG1fAccTime']))
    for source,g in sample.groupby('source_file'):
        path=(p.ROOT/source).resolve();assert path.is_relative_to(p.ROOT)
        before=p.sha(path)
        with gzip.open(path,'rt',encoding='utf-8') as f:items=json.load(f)['response']['body']['items']['item']
        for row in g.itertuples():
            raw=items[int(row.source_item_index)]
            assert str(raw['rcDate'])==row.date and int(raw['rcNo'])==row.race_no
            assert str(raw['hrNo']).zfill(7)==row.horse_id and int(raw['rcDist'])==row.distance
            for label,_ in p.layout(int(row.distance))[1:-1]:
                assert abs(float(raw[fields[label]])-getattr(row,label))<1e-10;raw_cells+=1
            assert abs(float(raw['rcTime'])-row.finish)<1e-10;raw_cells+=1
        assert p.sha(path)==before
        raw_sources.append(dict(path=source,sha256=before,bytes=path.stat().st_size,rows=len(g)))
    p.save('raw_source_manifest.json',raw_sources)
    p.save('verification.json',dict(status='verified',rows=len(d),complete_rows=int(d.complete.sum()),
        verified_segment_values=cells,previous1200_rows=34660,prior_mean_count_cells=history_cells,
        strictly_earlier_history=True,no_backfilled_slots=True,models_replayed=len(models),
        model_prediction_max_error=replay_error,race_metric_error_below=1e-12,
        source_sample_rows=len(sample),source_sample_cells=raw_cells,source_sample_error=0,
        database_mode='read_only',operating_registry_unchanged=True,jeju_access=False,
        new_model_types=4,new_year_models=12,operating_model_changed=False))
    print((p.OUT/'verification.json').read_text())


if __name__=='__main__':main()
