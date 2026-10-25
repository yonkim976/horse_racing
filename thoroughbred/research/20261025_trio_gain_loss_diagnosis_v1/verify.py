"""Independent frozen-ticket labels, Decimal settlement, partitions and source checks."""
from decimal import Decimal
from itertools import combinations
import duckdb
import json
import numpy as np
import pandas as pd
import analyze as a


def main():
    for path,v in json.loads((a.OUT/'input_manifest.json').read_text()).items():
        p=a.ROOT/path
        assert p.stat().st_size==v['bytes'] and a.sha(p)==v['sha256'], path
    d=pd.read_parquet(a.OUT/'race_diagnostics.parquet').set_index('race_key')
    c=pd.read_csv(a.OUT/'changed_cases.csv')
    assert len(d)==4133 and not d.index.duplicated().any()
    assert c.transition.value_counts().to_dict()=={'gained':210,'lost':145}
    assert d.groupby('year').size().to_dict()=={2024:1530,2025:1522,2026:1081}
    official=pd.read_parquet(a.DIV).set_index('race_key')
    assert d.actual.eq(official.loc[d.index,'actual']).all()
    assert np.allclose(d.dividend,official.loc[d.index,'dividend'],atol=0,rtol=0)
    t=pd.read_parquet(a.PRIOR/'selected_tickets.parquet')
    t=t[t.model.eq('state_gbm118')]
    truth={k:tuple(map(int,v.split(','))) for k,v in d.actual.items()}
    checks=0
    for (key,policy),g in t.groupby(['race_key','policy']):
        tickets=list(zip(g.a,g.b,g.c))
        hit=truth[key] in tickets
        assert len(tickets)==len(set(tickets))==6
        assert bool(d.loc[key,policy+'_hit'])==hit
        checks+=6
    # Independently check score ranks, lost ticket mechanism, and source roster.
    r=pd.read_parquet(a.OUT/'changed_runner_context.parquet')
    for key,g in r.groupby('race_key'):
        ranked=g.sort_values(['energy','program_no'],ascending=[False,True])
        assert ranked.model_rank.tolist()==list(range(1,len(g)+1))
        number_rank=dict(zip(g.program_no,g.model_rank))
        actual_ranks=sorted(number_rank[n] for n in truth[key])
        assert ','.join(map(str,actual_ranks))==d.loc[key,'podium_model_ranks']
        tr=list(combinations(sorted(g.program_no.astype(int)),3))
        v=dict(zip(g.program_no,g.energy))
        tr.sort(key=lambda ts:(-sum(v[n] for n in ts),ts))
        assert tr.index(truth[key])+1==d.loc[key,'actual_joint_rank']
        g=g.set_index('program_no').loc[ranked.program_no]
        # The axis-six set is 1 + every pair from ranks2..5.
        old={tuple(sorted((g.index[0],x,y))) for x,y in combinations(g.index[1:5],2)}
        assert (truth[key] in old)==bool(d.loc[key,'axis_six_hit'])
    lost=c[c.transition.eq('lost')]
    gained=c[c.transition.eq('gained')]
    assert lost.actual_axis_in_podium.all() and lost.podium_fifth.sum()==132
    assert lost.podium_model_ranks.value_counts().to_dict()=={'1,4,5':90,'1,3,5':42,'1,3,4':13}
    assert gained.podium_model_ranks.value_counts().to_dict()=={'1,2,6':105,'1,2,7':44,'2,3,4':42,'1,2,8':19}
    annual={2024:411800,2025:-611400,2026:-456100}
    for period in ['all',2024,2025,2026]:
        z=d if period=='all' else d[d.year.eq(period)]
        old=sum(Decimal(str(x))*1000 for x in z.loc[z.axis_six_hit,'dividend'])
        new=sum(Decimal(str(x))*1000 for x in z.loc[z.joint_top6_hit,'dividend'])
        assert old==int(z.old_return.sum()) and new==int(z.new_return.sum())
        assert new-old==(-655700 if period=='all' else annual[period])
        prior=pd.read_csv(a.PRIOR/'summary.csv')
        prior=prior[prior.model.eq('state_gbm118')&prior.subgroup.eq(str(period))].set_index('policy')
        assert old==Decimal(str(prior.loc['axis_six','return_krw']))
        assert new==Decimal(str(prior.loc['joint_top6','return_krw']))
    s=pd.read_csv(a.OUT/'condition_summary.csv')
    partitions=0
    for (period,dim),g in s.groupby(['period','dimension']):
        base=s[s.period.eq(period)&s.dimension.eq('all')].iloc[0]
        for col in ['races','gained','lost','old_hits','new_hits','gained_return','lost_return','old_return','new_return','delta_return']:
            assert g[col].sum()==base[col],(period,dim,col)
        assert np.allclose((g.new_roi-g.old_roi)*100,g.delta_roi_pp)
        partitions+=1
    assert d.observed_notation_coverage.sum()==4048 and d.observed_pace.eq('unknown').sum()==85
    assert d.predicted_pace.ne('unknown').all() and d.min_history_date_ok.all()
    # Independently reread market cells from the canonical read-only DB. The old
    # raw JSON paths are recorded but unavailable; no raw-file validation is claimed.
    mp=json.loads((a.OUT/'market_provenance.json').read_text())
    market=pd.read_parquet(a.OUT/'market_projection.parquet')
    assert a.sha(a.OUT/'market_projection.parquet')==mp['projection_sha256']
    con=duckdb.connect(str(a.ROOT/mp['database']),read_only=True)
    raw=con.execute('''select source_path, source_row, canonical_meet, race_date, race_no,
                      chul_no, hr_no, win_odds, finish_order from entry_result
                      where race_date between ? and ?''',mp['parameters']).fetchdf()
    con.close()
    raw=raw.set_index(['source_path','source_row'])
    assert not raw.index.duplicated().any()
    raw_checks=0
    for row in market.itertuples():
        item=raw.loc[(row.source_path,row.source_row)]
        assert pd.Timestamp(item.race_date)==pd.Timestamp(row.race_date)
        assert item.canonical_meet==row.canonical_meet and item.race_no==row.race_no
        assert item.chul_no==row.program_no and item.hr_no==row.horse_id
        assert Decimal(str(item.win_odds))==Decimal(str(row.win_odds))
        raw_checks+=1
    a.save('verification.json',dict(status='passed',races=len(d),gained=210,lost=145,
        frozen_ticket_labels_checked=checks,partitions_verified=partitions,
        decimal_all_annual_settlements=True,actual_pace_known=4048,actual_pace_unknown=85,
        market_db_rows_checked=raw_checks,market_original_json_available=False,market_not_a_selection_input=True,
        no_new_training=True,no_production_changes=True,causal_claim=False,independent_future_test=False))
    print((a.OUT/'verification.json').read_text())


if __name__=='__main__':main()
