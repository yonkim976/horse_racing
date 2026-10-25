"""Independent selection, source-window, replay and score decomposition checks."""

import json
import lightgbm as lgb
import numpy as np
import pandas as pd

import analyze as a


def main():
    a.check()
    d=pd.read_parquet(a.OLD/'profiles.parquet');x=pd.read_parquet(a.OLD/'features.parquet')
    p=pd.read_parquet(a.OLD/'predictions.parquet');cases=pd.read_parquet(a.OUT/'all_race_pairs.parquet')
    selected=pd.read_parquet(a.OUT/'selected_horses.parquet')
    expected={}
    for key,g in p.groupby(a.RACE):
        expected[key]=[]
        for model in ['B0','B3']:
            values=g[['row_id','program_no','raw_'+model]].sort_values(['raw_'+model,'program_no'],ascending=[False,True])
            expected[key].append(int(values.iloc[0].row_id))
    assert len(expected)==len(cases)==1976
    for row in cases.itertuples():
        assert [row.old_id,row.new_id]==expected[row.date,row.race_no]
        assert row.gain==(row.old_finish_rank>3 and row.new_finish_rank<=3)
        assert row.loss==(row.old_finish_rank<=3 and row.new_finish_rank>3)
        assert row.changed==(row.old_id!=row.new_id)
        assert row.old_grade==row.new_grade
    # Historical raw means verified by traversing original same-distance rows, not the aggregate function.
    groups={key:g.index.to_numpy() for key,g in d.sort_values(['date','race_no']).groupby(['horse_id','distance'],sort=False)}
    checks=0
    lookup=selected.drop_duplicates('row_id').set_index('row_id')
    raw={'early200':d.S1F,'late600':d.finish-d.G3F,'late400':d.finish-d.G2F,'late200':d.finish-d.G1F}
    for rowid,observed in lookup.iterrows():
        current=d.loc[rowid];ids=groups[current.horse_id,current.distance]
        prior=ids[d.loc[ids,'date'].lt(current.date).to_numpy()][-5:]
        assert all(d.loc[prior,'date']<current.date)
        assert len(prior)==int(x.loc[rowid,'same_slots'])
        for kind,values in raw.items():
            v=values.loc[prior].where(d.loc[prior,'complete']).dropna()
            assert len(v)==observed['same_'+kind+'_n']
            expected_mean=v.mean() if len(v) else np.nan
            np.testing.assert_allclose(expected_mean,observed['same_'+kind+'_seconds'],atol=1e-10,rtol=0,equal_nan=True);checks+=1
    for role in ['old','new']:
        ids=cases[role+'_id'].to_numpy(int)
        np.testing.assert_allclose(cases[role+'_hist_all_n'],x.loc[ids,'all_performance_n'],atol=0,rtol=0)
        np.testing.assert_allclose(cases[role+'_hist_same_n'],x.loc[ids,'same_performance_n'],atol=0,rtol=0)
        for kind,code,length in [('early200','early',200),('late600','tail600',600),('late400','tail400',400),('late200','tail200',200)]:
            np.testing.assert_allclose(cases[role+'_hist_'+kind+'_field_adv_seconds'],x.loc[ids,'all_c_'+code+'_adv_mean']*length/1000,atol=1e-12,rtol=0,equal_nan=True)
    for column in cases.columns:
        if column.startswith('delta_'):
            name=column[6:]
            np.testing.assert_allclose(cases[column],cases['new_'+name]-cases['old_'+name],atol=1e-12,rtol=0,equal_nan=True)
    score=pd.read_csv(a.OUT/'score_group_differences.csv')
    assert len(score)==int(cases.changed.sum())==209
    expected_sum=score.B3_new_minus_old-score.B0_new_minus_old
    observed_sum=score[['base_retrained_change','curve','section_position','style8']].sum(axis=1)
    np.testing.assert_allclose(expected_sum,observed_sum,atol=1e-10,rtol=0)
    assert (score.B3_new_minus_old>=-1e-10).all() and (score.B0_new_minus_old<=1e-10).all()
    frozen=pd.read_parquet(a.OUT/'frozen2024_scores_on2026.parquet')
    manifest=json.loads((a.OLD/'model_manifest.json').read_text());features=json.loads((a.OLD/'feature_sets.json').read_text())
    maxerror=0
    for model in ['B0','B3']:
        entry=next(z for z in manifest if z['model']==model and z['year']==2024)
        assert entry['train_last']<'20240101'
        booster=lgb.Booster(model_file=str(a.ROOT/entry['path']))
        rawpred=booster.predict(x.loc[frozen.row_id,features[model]],num_threads=4)
        maxerror=max(maxerror,float(np.max(np.abs(rawpred-frozen['raw_'+model]))))
        np.testing.assert_allclose(rawpred,frozen['raw_'+model],atol=1e-12,rtol=0)
        median=pd.Series(rawpred,index=frozen.index).groupby([frozen.date,frozen.race_no]).transform('median')
        np.testing.assert_allclose(rawpred-median,frozen['pred_'+model],atol=1e-12,rtol=0)
    recovery=cases[(cases.year.eq(2024))&cases.monthday.le('0918')]
    assert len(recovery)==525 and recovery.gain.sum()==10 and recovery.loss.sum()==17
    standards=json.loads((a.OUT/'standardization.json').read_text())
    cells=pd.read_csv(a.OUT/'standardization_cells.csv')
    assert (cells.races>=10).all() and len(cells)==32
    weights=cells.groupby(['distance','grade_number']).races.sum();weights=weights/weights.sum()
    for entry in standards:
        g=cells[cells.year.eq(entry['year'])].set_index(['distance','grade_number'])
        value=(g.net/g.races*weights).sum()
        assert abs(value-entry['pooled_weight_standardized_net_rate'])<1e-12
    contrast=pd.read_csv(a.OUT/'gain_loss_contrasts.csv')
    for row in contrast.itertuples():
        g=cases[cases.year.eq(row.year)&cases.changed]
        gain=g[g.gain][row.metric].dropna();loss=g[g.loss][row.metric].dropna()
        assert len(gain)==row.gain_n and len(loss)==row.loss_n
        assert abs(gain.mean()-loss.mean()-row.mean_difference)<1e-10
    a.save('verification.json',dict(status='verified',race_selections=1976,changed_selections=209,
        historical_unique_selected_rows=len(lookup),historical_raw_mean_checks=checks,
        history_strictly_before_target=True,invalid_slots_not_backfilled=True,
        all_pair_difference_signs_checked=True,source_feature_unit_conversions_checked=True,
        frozen_model_replay_max_error=maxerror,contribution_additivity_max_error=float(np.max(np.abs(expected_sum-observed_sum))),
        standardization_cells=16,common_calendar_verified=True,contrast_points_verified=len(contrast),
        new_fits=0,database_access=False,operating_model_changed=False))
    print((a.OUT/'verification.json').read_text())


if __name__=='__main__':main()
