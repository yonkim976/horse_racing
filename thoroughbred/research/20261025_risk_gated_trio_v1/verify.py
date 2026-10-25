"""Independent direct-ticket and decimal checks of fixed risk policies."""
from decimal import Decimal
import itertools
import json

import numpy as np
import pandas as pd
import analyze as a


def main():
    f,gate,thresholds=a.prepare()
    saved=pd.read_parquet(a.OUT/'risk_gates.parquet')
    gate['source_axis']=gate.source_axis.astype('Float64')
    saved['source_axis']=saved.source_axis.astype('Float64')
    pd.testing.assert_frame_equal(gate,saved,check_dtype=False)
    assert json.loads((a.OUT/'thresholds.json').read_text())==thresholds
    assert all(x['calibration_year']==x['year']-1 and pd.Timestamp(x['calibration_last_date']).year==x['year']-1 for x in thresholds)
    s=pd.read_csv(a.OUT/'summary.csv')
    rows_checked=0
    for (scope,model),one in f.groupby(['scope','model']):
        for subgroup,g in a.groups(one):
            for policy in a.policies(model):
                flag=a.flags(g,policy)
                cost=0;paid=Decimal(0);hit=0;extra_n=0
                for row,high in zip(g.itertuples(),flag):
                    buy=10 if high else 6;cost+=buy*1000;extra_n+=int(high)
                    success=bool(row.six_hit or (row.extra_hit and high))
                    hit+=int(success)
                    if success:paid+=Decimal(str(row.dividend))*1000
                r=s[s.scope.eq(scope)&s.model.eq(model)&s.subgroup.eq(subgroup)&s.policy.eq(policy)].iloc[0]
                assert r.races==len(g) and r.hits==hit and r.extra_bought_races==extra_n
                assert r.stake_krw==cost and Decimal(str(r.return_krw))==paid
                assert Decimal(str(r.net_krw))==paid-cost
                assert abs(r.roi-(float(paid)/cost-1))<1e-12
                rows_checked+=1
    # Enumerate purchased sets directly from the old frozen five-horse picks.
    source=pd.read_parquet(a.OLD/'race_results.parquet')
    source=source[source.model.isin(['state_gbm118','operating_A_v5']) & source.scope.eq('identical_roster')]
    chosen=f[f.scope.eq('identical_roster')].merge(source[['race_key','model','companions','actual']],on=['race_key','model'],validate='1:1')
    checks=0
    for model,g in chosen.groupby('model'):
        for policy in a.policies(model):
            flag=a.flags(g,policy)
            for row,high in zip(g.itertuples(),flag):
                other=list(map(int,row.companions.split(',')))
                six={tuple(sorted((row.axis,*x))) for x in itertools.combinations(other,2)}
                extra={tuple(sorted(x)) for x in itertools.combinations(other,3)}
                tickets=six|extra if high else six
                assert len(tickets)==(10 if high else 6) and not six.intersection(extra)
                truth=tuple(map(int,row.actual.split(',')))
                assert (truth in tickets)==bool(row.six_hit or (row.extra_hit and high))
                checks+=1
    changed=f.copy()
    changed['dividend']=999999.;changed['six_hit']=~changed.six_hit;changed['extra_hit']=~changed.extra_hit
    changed['axis_hit']=~changed.axis_hit
    for model in f.model.unique():
        mask=f.model.eq(model)
        for p in a.policies(model):assert np.array_equal(a.flags(f[mask],p),a.flags(changed[mask],p))
    previous=pd.read_csv(a.RET/'return_summary.csv')
    matched=0
    for policy,old in [('always_six','six'),('always_ten','ten')]:
        q=s[s.policy.eq(policy)].merge(previous[previous.policy.eq(old)],on=['scope','subgroup','model'],validate='1:1')
        for col in ['races','hits','stake_krw','return_krw','net_krw','roi']:
            assert np.allclose(q[col+'_x'],q[col+'_y'],atol=1e-9)
        matched+=len(q)
    computed,diagnostics,pairs=a.summarize(f)
    pd.testing.assert_frame_equal(computed,s,check_dtype=False,atol=1e-9)
    pd.testing.assert_frame_equal(diagnostics,pd.read_csv(a.OUT/'risk_diagnostics.csv'),check_dtype=False,atol=1e-9)
    pd.testing.assert_frame_equal(pairs,pd.read_csv(a.OUT/'paired_differences.csv'),check_dtype=False,atol=1e-9)
    manifest=json.loads((a.OUT/'input_manifest.json').read_text())
    for p,v in manifest.items():assert a.sha(a.ROOT/p)==v['sha256']
    report=dict(status='passed',prior_year_threshold_folds_checked=len(thresholds),
        gate_runner_races_checked=len(gate),summary_rows_decimal_checked=rows_checked,
        purchased_ticket_policy_records_enumerated=checks,prior_six_ten_summaries_matched=matched,
        original_state_gbm_axes_unchanged=True,stored_model_warning_flags_reproduced=True,
        gate_unchanged_by_current_outcome_or_dividend_mutation=True,all_costs_ratio_of_totals=True,
        date_bootstrap_reproduced=True,protected_source_files_unchanged=len(manifest),
        new_models=0,production_changed=False,independent_future_test=False,external_independent_review=False)
    a.save(a.OUT/'verification.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
