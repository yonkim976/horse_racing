"""Supplementary retrospective market evidence, never supplied to ticket selection."""
import json
import duckdb
import numpy as np
import pandas as pd
import analyze as a


def main():
    cases=pd.read_csv(a.OUT/'changed_cases.csv')
    r=pd.read_parquet(a.OUT/'changed_runner_context.parquet')
    target=a.ROOT/'thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb'
    con=duckdb.connect(str(target),read_only=True)
    query='''select canonical_meet, race_date, race_no, chul_no as program_no,
             hr_no as horse_id, win_odds, place_odds, finish_order,
             source_path, source_row from entry_result
             where race_date >= ? and race_date <= ? and canonical_meet in (1,3)'''
    d=con.execute(query,['2024-01-05','2026-09-13']).fetchdf()
    con.close()
    d['race_key']=d.canonical_meet.astype(str)+':'+pd.to_datetime(d.race_date).dt.strftime('%Y%m%d')+':'+d.race_no.astype(str)
    d=d[d.race_key.isin(cases.race_key)].copy()
    assert not d.duplicated(['race_key','program_no']).any()
    d=r[['race_key','program_no','horse_id','model_rank','outcome']].merge(d,
          on=['race_key','program_no','horse_id'],validate='one_to_one',how='left')
    assert d.win_odds.notna().all() and d.win_odds.ge(1).all()
    d['market_rank']=d.groupby('race_key').win_odds.rank(method='min')
    d.to_parquet(a.OUT/'market_projection.parquet',index=False)
    source_files=sorted(set(d.source_path))
    a.save('market_provenance.json',dict(database=str(target.relative_to(a.ROOT)),database_bytes=target.stat().st_size,
        query=query,parameters=['2024-01-05','2026-09-13'],rows=len(d),races=d.race_key.nunique(),
        database_opened_read_only=True,database_hashed_or_copied=False,
        source_files={s:dict(available=(a.ROOT/s).is_file(),
            bytes=(a.ROOT/s).stat().st_size if (a.ROOT/s).is_file() else None,
            sha256=a.sha(a.ROOT/s) if (a.ROOT/s).is_file() else None) for s in source_files},
        projection_sha256=a.sha(a.OUT/'market_projection.parquet'),selected_with_odds=False))
    values=[]
    for key,g in d.groupby('race_key'):
        w=g[g.outcome.between(1,3)]
        assert len(w)==3 and (w.finish_order==w.outcome).all()
        values.append(dict(race_key=key,podium_max_win_odds=float(w.win_odds.max()),
            podium_mean_win_odds=float(w.win_odds.mean()),
            podium_max_market_rank=float(w.market_rank.max()),
            podium_market_top2=int(w.market_rank.le(2).sum()),
            podium_market_rank6plus=int(w.market_rank.ge(6).sum()),
            winner_market_rank=float(g.loc[g.outcome.eq(1),'market_rank'].iloc[0]),
            fifth_win_odds=float(g.loc[g.model_rank.eq(5),'win_odds'].iloc[0]),
            model_second_market_rank=float(g.loc[g.model_rank.eq(2),'market_rank'].iloc[0])))
    c=cases.merge(pd.DataFrame(values),on='race_key',validate='one_to_one')
    c.to_csv(a.OUT/'market_case_diagnostics.csv',index=False,encoding='utf-8-sig')
    summaries=[]
    for period in ['all',2024,2025,2026]:
        z=c if period=='all' else c[c.year.eq(period)]
        for transition,g in z.groupby('transition'):
            for col in values[0]:
                if col=='race_key':continue
                summaries.append(dict(period=period,transition=transition,variable=col,n=len(g),
                                      mean=g[col].mean(),median=g[col].median()))
    pd.DataFrame(summaries).to_csv(a.OUT/'market_condition_comparison.csv',index=False)
    print(pd.DataFrame(summaries).query("period=='all'").round(3).to_string(index=False))


if __name__=='__main__':main()
