"""Independent raw-value grouping, SQL counts, and retained report comparison."""
import ast
import json

import duckdb
import numpy as np
import pandas as pd
from horse_racing.parsers.dacom11 import parse_dacom11_report

import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    d=pd.read_parquet(e.OUT/'runner_audit.parquet');raw=pd.read_parquet(e.OUT/'raw_fields.parquet')
    summary=json.loads((e.OUT/'summary.json').read_text())
    x=d.merge(raw,on=e.KEY,validate='one_to_one');labels=[]
    for row in x.itertuples():
        a,b=row.seS1fAccTime,row.se_1cAccTime
        labels.append('missing' if a<=0 or b<=0 else 'equal' if a==b else 'later' if b>a else 'earlier')
    assert x.comparison.tolist()==labels
    assert d.comparison.value_counts().to_dict()==summary['all_counts']
    assert d[d.normal_finish].comparison.value_counts().to_dict()==summary['normal_counts']
    with duckdb.connect(str(e.DB),read_only=True) as c:
        n=c.execute("select count(*) from confirmed_runners where source_meet='1' and try_cast(race_distance_m_raw as int)=1800").fetchone()[0]
        independent=c.execute("""with base as(select result_date,try_cast(result_race_no as int) race_no,horse_id_raw
        from confirmed_runners where source_meet='1' and try_cast(race_distance_m_raw as int)=1800),
        s as(select race_date,race_no,horse_id,time_ms from section_measurements_api where meet=1 and point_code='S1F' and measure_kind='cumulative_time'),
        b as(select race_date,race_no,horse_id,time_ms from section_measurements_api where meet=1 and point_code='1C' and measure_kind='cumulative_time')
        select sum(s.time_ms=b.time_ms),sum(b.time_ms>s.time_ms),sum(b.time_ms<s.time_ms),sum(s.time_ms is null or b.time_ms is null)
        from base left join s on s.race_date=base.result_date and s.race_no=base.race_no and s.horse_id=base.horse_id_raw
        left join b on b.race_date=base.result_date and b.race_no=base.race_no and b.horse_id=base.horse_id_raw""").fetchone()
    assert n==len(d)==len(raw)==summary['rows']
    assert list(independent)==[summary['all_counts'][k] for k in ['equal','later','earlier','missing']]
    races=pd.read_csv(e.OUT/'race_counts.csv',dtype={'date_key':str})
    years=pd.read_csv(e.OUT/'yearly_counts.csv')
    for scope,h in [('all',d),('normal',d[d.normal_finish])]:
        z=years[years.scope.eq(scope)];assert z.rows.sum()==len(h)
        for row in z.itertuples():
            counts=h[h.year.eq(row.year)].comparison.value_counts()
            for label in ['equal','later','earlier','missing']:assert getattr(row,label)==counts.get(label,0)
    assert races.rows.sum()==len(d) and len(races)==summary['races']
    for label in ['equal','later','earlier','missing']:assert races[label].sum()==summary['all_counts'][label]
    month=pd.read_csv(e.OUT/'monthly_counts.csv')
    for row in month.itertuples():
        assert row.rows==int((d.year.eq(row.year)&d.month.eq(row.month)&d.comparison.eq(row.comparison)).sum())
    eq=races[races.equal.gt(0)]
    assert eq.later.sum()==0 and eq.scheduled_night.eq(True).all()
    assert d.loc[d.comparison.eq('equal'),'month'].between(7,9).all()
    previous=pd.read_csv(e.R/'20261017_section_layout_by_distance_v1/outputs/distance_layouts.csv')
    old=previous[previous.meet.eq(1)&previous.distance_m.eq(1800)].iloc[0]
    assert old.rows==summary['normal_rows'] and old.overlap_alternative==summary['normal_counts']['equal']
    # Compare every1800 horse on equal-date cards with a locally retained report.
    checks=[];files=[];missing=[]
    for ds in sorted(eq.date_key.unique()):
        p=e.ROOT/'data/raw/kra_text/dacom11/meet=1'/('year='+ds[:4])/('month='+ds[4:6])/('day='+ds[6:])/f'{ds}dacom11.rpt'
        if not p.exists():missing.append(ds);continue
        files.append(dict(path=str(p.relative_to(e.ROOT)),sha256=e.sha(p),bytes=p.stat().st_size))
        for race in parse_dacom11_report(p.read_bytes()):
            if race.distance_m!=1800:continue
            for entry in race.entries:
                rows=d[d.date_key.eq(ds)&d.race_no.eq(race.race_number)&d.program_no.eq(entry.horse_number)]
                assert len(rows)==1
                row=rows.iloc[0]
                for point,value in [('S1F',entry.s1f_ms),('1C',entry.corner_times_ms.get('1C'))]:
                    actual=row[point+'_ms']
                    if value is None and pd.isna(actual):continue
                    delta=None if value is None or pd.isna(actual) else float(value-actual)
                    checks.append(dict(date_key=ds,race_no=race.race_number,program_no=entry.horse_number,
                        point=point,report_ms=value,api_ms=None if pd.isna(actual) else actual,delta_ms=delta,
                        match=bool(delta==0)))
    cross=pd.DataFrame(checks);cross.to_csv(e.OUT/'dacom11_crosscheck.csv',index=False)
    e.save(e.OUT/'independent_source_manifest.json',files)
    e.save(e.OUT/'verification.json',dict(status='verified',all_rows=len(d),normal_rows=summary['normal_rows'],
        independent_raw_grouping=True,independent_sql_counts=True,all_year_month_race_sums_verified=True,
        no_equal_later_mixed_races=True,equal_races_all_scheduled_night=True,old480_reproduced=True,
        dacom11_files=len(files),dacom11_cells=len(cross),dacom11_mismatches=int((~cross.match).sum()),
        dacom11_unavailable_equal_dates=missing,source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),
        raw_cells_checked=summary['raw_cells_checked'],max_raw_error=0,
        scheduled_time_not_actual_time=True,route_change_per_race_unverified=True,new_models=0,database_access='read_only'))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':main()
