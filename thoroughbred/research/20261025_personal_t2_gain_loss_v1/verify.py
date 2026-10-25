"""Independent frozen selections, passage groups and exact year/condition receipts."""
from decimal import Decimal
from itertools import combinations
import json
import numpy as np
import pandas as pd
from scipy.special import softmax
import analyze as a


def main():
    for name,v in json.loads((a.OUT/'input_manifest.json').read_text()).items():
        p=a.ROOT/name;assert p.stat().st_size==v['bytes'] and a.sha(p)==v['sha256'],name
    d=pd.read_parquet(a.OUT/'race_diagnostics.parquet').set_index('race_key')
    c=pd.read_csv(a.OUT/'changed_cases.csv')
    assert len(d)==4133 and d.index.is_unique
    assert c.transition.value_counts().to_dict()=={'gained':225,'lost':144}
    assert d.groupby('year').size().to_dict()=={2024:1530,2025:1522,2026:1081}
    official=pd.read_parquet(a.DIV).set_index('race_key')
    assert d.actual.eq(official.loc[d.index,'actual']).all()
    assert np.array_equal(d.dividend,official.loc[d.index,'dividend'])
    prior=pd.read_parquet(a.PRIOR/'race_results.parquet').query('previous_4133').set_index('race_key')
    for col in ['axis','axis_six_hit','joint_top6_hit','transition','payout']:
        assert np.array_equal(d[col],prior.loc[d.index,col]),col
    t=pd.read_parquet(a.PRIOR/'selected_tickets.parquet')
    t=t[t.race_key.isin(d.index)]
    truths={key:tuple(map(int,value.split(','))) for key,value in d.actual.items()}
    tickets_checked=0
    for (key,policy),g in t.groupby(['race_key','policy']):
        tickets=list(zip(g.a,g.b,g.c))
        assert len(tickets)==len(set(tickets))==6
        labels=np.array([ts==truths[key] for ts in tickets])
        assert np.array_equal(g.hit,labels)
        assert labels.any()==d.loc[key,policy+'_hit']
        tickets_checked+=6
    runners=pd.read_parquet(a.OUT/'changed_runner_context.parquet')
    saved={(key,policy):g.sort_values('rank') for (key,policy),g in t.groupby(['race_key','policy'],sort=False)}
    for key,g in runners.groupby('race_key'):
        g=g.sort_values('program_no');nums=g.program_no.to_numpy(int)
        tr=np.array(list(combinations(range(len(g)),3)))
        q=softmax(g.energy.to_numpy(float)[tr].sum(axis=1))
        marg=np.array([q[(tr==i).any(axis=1)].sum() for i in range(len(g))])
        assert np.max(np.abs(marg-g.top3.to_numpy()))<2e-10
        rank=np.argsort(-np.round(marg,12),kind='stable')
        ranks={int(nums[i]):j+1 for j,i in enumerate(rank)}
        pattern=','.join(map(str,sorted(ranks[n] for n in truths[key])))
        assert pattern==d.loc[key,'podium_model_ranks']
        qorder=np.argsort(-np.round(q,12),kind='stable')
        allsets=[tuple(nums[x]) for x in tr]
        assert next(i+1 for i,j in enumerate(qorder) if allsets[j]==truths[key])==d.loc[key,'actual_joint_rank']
        fixed={tuple(sorted((int(nums[rank[0]]),int(nums[x]),int(nums[y])))) for x,y in combinations(rank[1:5],2)}
        assert set(zip(saved[key,'axis_six'].a,saved[key,'axis_six'].b,saved[key,'axis_six'].c))==fixed
        assert list(zip(saved[key,'joint_top6'].a,saved[key,'joint_top6'].b,saved[key,'joint_top6'].c))==[allsets[i] for i in qorder[:6]]
    lost=c[c.transition.eq('lost')];gained=c[c.transition.eq('gained')]
    assert lost.actual_axis_in_podium.all()
    assert set(lost.podium_model_ranks)<=set(['1,3,4','1,3,5','1,4,5'])
    assert set(gained.podium_model_ranks)<=set(['1,2,6','1,2,7','1,2,8','2,3,4'])
    annual={2024:184200,2025:-303900,2026:55700}
    oldsummary=pd.read_csv(a.PRIOR/'summary.csv')
    for period in ['all',2024,2025,2026]:
        z=d if period=='all' else d[d.year.eq(period)]
        old=sum((Decimal(str(x))*1000 for x in z.loc[z.axis_six_hit,'dividend']),Decimal(0))
        new=sum((Decimal(str(x))*1000 for x in z.loc[z.joint_top6_hit,'dividend']),Decimal(0))
        assert old==int(z.old_return.sum()) and new==int(z.new_return.sum())
        assert new-old==(-64000 if period=='all' else annual[period])
        base=oldsummary[oldsummary.scope.eq('previous_4133')&oldsummary.subgroup.eq(str(period))].set_index('policy')
        assert Decimal(str(base.loc['axis_six','return_krw']))==old
        assert Decimal(str(base.loc['joint_top6','return_krw']))==new
    summary=pd.read_csv(a.OUT/'condition_summary.csv');partitions=0
    for (period,dimension),g in summary.groupby(['period','dimension']):
        total=summary[summary.period.eq(period)&summary.dimension.eq('all')].iloc[0]
        for col in ['races','gained','lost','old_hits','new_hits','gained_return','lost_return','old_return','new_return','delta_return']:
            assert g[col].sum()==total[col],(period,dimension,col)
        partitions+=1
    # Independently verify every actual S1F group from the saved source, including missing coverage.
    obs=pd.read_parquet(a.GROUPS,columns=['source_key','gate','horse_id','group_observed','leader_conflict_race','first_group'])
    obs['race_key']=obs.source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    lookup={key:g for key,g in obs[obs.race_key.isin(d.index)].groupby('race_key')}
    source=pd.read_parquet(a.FEATURES,columns=['race_key','program_no','horse_id'])
    rosters={key:dict(zip(g.program_no,g.horse_id.astype(str))) for key,g in source[source.race_key.isin(d.index)].groupby('race_key')}
    coverage=0
    for row in d.itertuples():
        key=row.Index;z=lookup.get(key)
        valid=z is not None and dict(zip(z.gate,z.horse_id.astype(str)))==rosters[key] and z.group_observed.all() and not z.leader_conflict_race.any()
        assert bool(valid)==row.observed_notation_coverage
        if valid:
            front=set(z.loc[z.first_group.eq(True),'gate'].astype(int))
            assert len(front)==row.observed_front_count
            assert len(front&set(truths[key]))==row.observed_front_podium
            assert bool(row.axis in front)==row.observed_axis_front
            coverage+=1
    assert coverage==4048 and d.observed_pace.eq('unknown').sum()==85
    assert d.predicted_pace.ne('unknown').all() and d.min_history_date_ok.all()
    tails=pd.read_csv(a.OUT/'tail_decomposition.csv')
    for (period,threshold),g in tails.groupby(['period','threshold']):
        z=d if period=='all' else d[d.year.eq(int(period))]
        assert g.delta_return.sum()==z.delta_return.sum()
        assert abs(g.annual_contribution_pp.sum()-z.delta_return.sum()/(len(z)*6000)*100)<1e-10
        for label in ['below','at_least']:
            part=z[z.dividend.lt(threshold) if label=='below' else z.dividend.ge(threshold)]
            assert g[g.band.eq(label)].delta_return.iloc[0]==part.delta_return.sum()
    sensitivity=pd.read_csv(a.OUT/'cohort_sensitivity.csv')
    for row in sensitivity.itertuples():
        assert row.stake==row.races*6000 and row.new_return-row.old_return==row.delta_return
        assert abs(row.delta_roi_pp-row.delta_return/row.stake*100)<1e-10
    contrib=pd.read_csv(a.OUT/'annual_contributions.csv')
    for (period,dim),g in contrib.groupby(['period','dimension']):
        total=summary[summary.period.eq(period)&summary.dimension.eq('all')].iloc[0]
        assert abs(g.annual_contribution_pp.sum()-total.delta_roi_pp)<1e-10
    a.save('verification.json',dict(status='passed',races=4133,gained=225,lost=144,
        frozen_ticket_labels_checked=tickets_checked,changed_runner_races_reconstructed=369,
        partitions_verified=partitions,decimal_all_annual_settlements=True,
        actual_s1f_rosters_rechecked=4133,actual_pace_known=coverage,actual_pace_unknown=85,
        tail_decomposition_verified=True,annual_contributions_verified=True,
        new_models=0,database_writes=0,production_changed=False,independent_future_test=False,causal_claim=False))
    print((a.OUT/'verification.json').read_text())


if __name__=='__main__':main()
