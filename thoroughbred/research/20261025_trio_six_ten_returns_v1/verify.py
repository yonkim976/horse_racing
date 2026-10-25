"""Independent decimal accounting and report/API receipt checks."""
from decimal import Decimal
import json
import re
import sqlite3

import numpy as np
import pandas as pd
import analyze as a


def main():
    payouts=pd.read_parquet(a.OUT/'winning_dividends.parquet')
    assert len(payouts)==4799 and payouts.status.eq('valid').all()
    assert not payouts.race_key.duplicated().any()
    report_count=0
    for path,g in payouts[payouts.selected_source.eq('rpt')].groupby('report_path'):
        raw=(a.ROOT/path).read_bytes()
        try:text=raw.decode('cp949')
        except UnicodeDecodeError:text=raw.decode('utf-8-sig')
        for row in g.itertuples():
            assert row.report_line in text
            value=Decimal(re.search(r'([\d,]+\.\d+)\s*$',row.report_line).group(1).replace(',',''))
            assert value==Decimal(str(row.dividend))
            picks=[]
            for token in re.findall(r'[①-⑳]|\(\s*\d+\s*\)',row.report_line):
                picks.append(ord(token)-ord('①')+1 if len(token)==1 else int(token.strip('() ')))
            assert sorted(picks)==list(map(int,row.actual.split(',')))
            report_count+=1
    receipt=payouts[payouts.api_source_id.notna()]
    with sqlite3.connect(a.DB.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        q=pd.read_sql_query('''SELECT o.id,o.odds,o.selection_key,rc.kra_meet_code meet,r.race_date_local,r.race_number
            FROM odds_snapshots o JOIN races r ON r.id=o.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
            WHERE o.id IN (SELECT value FROM json_each(?)) AND o.bet_type=?''',conn,
            params=(json.dumps(receipt.api_source_id.astype(int).tolist()),'TLA'))
    q=q.set_index('id')
    for row in receipt.itertuples():
        source=q.loc[int(row.api_source_id)]
        assert abs(source.odds-row.api_dividend)<1e-9
        assert source.selection_key=='-'.join(row.actual.split(','))
        assert row.race_key==f'{source.meet}:{source.race_date_local.replace("-","")}:{source.race_number}'
        assert row.api_result_matches
    f=pd.read_parquet(a.OUT/'race_returns.parquet')
    s=pd.read_csv(a.OUT/'return_summary.csv')
    rows_checked=0
    for scope,scoped in f.groupby('scope'):
        for subgroup in s[s.scope.eq(scope)].subgroup.unique():
            if subgroup=='all':g=scoped
            elif subgroup=='seoul':g=scoped[scoped.meet.eq(1)]
            elif subgroup=='busan':g=scoped[scoped.meet.eq(3)]
            elif subgroup=='2026H2':g=scoped[scoped.race_date.ge('2026-07-01')]
            else:g=scoped[scoped.year.eq(int(subgroup))]
            for model,z in g.groupby('model'):
                totals={}
                for policy,k,column in [('six',6,'six_hit'),('extra_four',4,'extra_hit'),('ten',10,'ten_hit')]:
                    total=sum((Decimal(str(x))*1000 for x in z.loc[z[column],'dividend']),Decimal(0))
                    row=s[s.scope.eq(scope)&s.subgroup.eq(subgroup)&s.model.eq(model)&s.policy.eq(policy)].iloc[0]
                    assert total==Decimal(str(row.return_krw))
                    assert row.stake_krw==len(z)*k*1000 and row.hits==z[column].sum()
                    assert abs(row.roi-(float(total)/(len(z)*k*1000)-1))<1e-12
                    totals[policy]=total
                    rows_checked+=1
                assert totals['ten']==totals['six']+totals['extra_four']
                assert (z.ten_hit.astype(int)==z.six_hit.astype(int)+z.extra_hit.astype(int)).all()
    prior=pd.read_csv(a.BOX/'summary.csv')
    aligned=s[s.policy.eq('ten')].merge(prior,on=['scope','subgroup','model'],validate='1:1')
    assert len(aligned)==len(prior) and aligned.hits.eq(aligned.ten_hits).all() and aligned.races_x.eq(aligned.races_y).all()
    calc,stats,boot=a.summaries(f)
    pd.testing.assert_frame_equal(calc,s,check_dtype=False,atol=1e-9)
    pd.testing.assert_frame_equal(stats,pd.read_csv(a.OUT/'dividend_summary.csv'),check_dtype=False,atol=1e-9)
    pd.testing.assert_frame_equal(boot,pd.read_csv(a.OUT/'paired_roi_intervals.csv'),check_dtype=False,atol=1e-9)
    for name,meta in json.loads((a.OUT/'input_manifest.json').read_text()).items():
        assert a.sha(a.ROOT/name)==meta['sha256']
    reports=json.loads((a.OUT/'report_source_manifest.json').read_text())
    for name,meta in reports.items():assert a.sha(a.ROOT/name)==meta['sha256']
    result=dict(status='passed',race_payouts_checked=len(payouts),report_receipts_checked=report_count,
        sqlite_receipts_checked=len(receipt),report_api_overlap=int((payouts.report_dividend.notna()&payouts.api_dividend.notna()).sum()),
        source_files_hash_checked=len(reports),settlement_summary_rows_independently_decimal_checked=rows_checked,
        previous_ticket_hit_summaries_matched=len(prior),all_ten_returns_equal_six_plus_four=True,
        no_payout_missing=True,no_conflicting_dividends=True,date_bootstrap_reproduced=True,
        new_models=0,production_changed=False,read_only_database=True,personal_income_tax_included=False,
        independent_future_test=False,independent_external_review=False)
    a.save(a.OUT/'verification.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
