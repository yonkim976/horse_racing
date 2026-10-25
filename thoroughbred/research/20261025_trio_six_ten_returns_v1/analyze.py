"""Settle fixed historical trio portfolios using preserved official reports."""
from pathlib import Path
import hashlib
import itertools
import json
import re
import sqlite3

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=R.parents[1]
OUT=HERE/'outputs'
PREV=R/'20261024_axis4_trio_comparison_v1/outputs'
BOX=R/'20261024_trio_five_box_v1/outputs'
DB=ROOT/'data/horse_racing.sqlite3'
FLAGS=R/'20261022_probability_comparison_v1/outputs/population_flags.parquet'
TITLE=re.compile(r'^제목\s*:\s*(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?제\s*(\d+)경주',re.M)
TOKEN=r'(?:[①-⑳]|\(\s*\d{1,2}\s*\))'
PAY=re.compile(r'^\s*삼복\s*:\s*((?:'+TOKEN+r'\s*){3})([\d,]+(?:\.\d+)?)\s*$',re.M)
CIRC={chr(0x2460+i):i+1 for i in range(20)}


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(p,obj):
    assert p.resolve().is_relative_to(HERE)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def sqlite_winners(truth):
    # JSON parameter binding avoids SQL construction and temporary DB writes.
    with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        races=pd.read_sql_query('''SELECT r.id,rc.kra_meet_code meet,r.race_date_local,r.race_number,r.status
            FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
            WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?''',conn,
            params=('2024-01-01','2026-09-20'))
        races['race_key']=races.apply(lambda r:f'{r.meet}:{r.race_date_local.replace("-","")}:{r.race_number}',axis=1)
        assert not races.race_key.duplicated().any()
        wanted=[dict(race_id=int(row.id),selection='-'.join(map(str,truth[row.race_key])))
            for row in races.itertuples() if row.race_key in truth]
        query='''WITH wanted AS (
            SELECT json_extract(value,'$.race_id') race_id,json_extract(value,'$.selection') selection_key
            FROM json_each(?)
        ), ranked AS (
            SELECT o.*,ROW_NUMBER() OVER(PARTITION BY o.race_id,o.selection_key
                ORDER BY o.observed_at_ms DESC,o.id DESC) rn
            FROM odds_snapshots o JOIN wanted w ON w.race_id=o.race_id AND w.selection_key=o.selection_key
            WHERE o.bet_type=?
        ) SELECT race_id,selection_key,odds,observed_at_ms,id source_id FROM ranked WHERE rn=1'''
        odds=pd.read_sql_query(query,conn,params=(json.dumps(wanted),'TLA'))
        results=pd.read_sql_query('''SELECT r.id race_id,e.horse_number
            FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
            JOIN race_entries e ON e.race_id=r.id JOIN race_results rr ON rr.race_entry_id=e.id
            WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?
                AND rr.finish_position BETWEEN 1 AND 3 AND e.scratched=0 AND rr.disqualified=0''',conn,
            params=('2024-01-01','2026-09-20'))
        conn.rollback()
    z=races.merge(odds,left_on='id',right_on='race_id',how='left',validate='1:1')
    podium=results.groupby('race_id').horse_number.agg(lambda x:tuple(sorted(x.astype(int))))
    z['sqlite_actual']=z.id.map(podium)
    return z.set_index('race_key')


def payout_extract(truth):
    references={}; reports={}
    for key in truth:
        meet,date,_=key.split(':')
        path=ROOT/f'data/raw/kra_text/dacom11/meet={meet}/year={date[:4]}/month={date[4:6]}/day={date[6:]}/{date}dacom11.rpt'
        references[(meet,date)]=path
    manifest={};issues=[]
    for (meet,date),path in references.items():
        if not path.exists():continue
        raw=path.read_bytes()
        manifest[str(path.relative_to(ROOT))]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        try:text=raw.decode('cp949')
        except UnicodeDecodeError:text=raw.decode('utf-8-sig')
        headers=list(TITLE.finditer(text))
        for i,h in enumerate(headers):
            year=int(h[1]);year=year+2000 if year<80 else year
            actual_date=f'{year:04}{int(h[2]):02}{int(h[3]):02}'
            assert actual_date==date,(path,actual_date,date)
            block=text[h.start():headers[i+1].start() if i+1<len(headers) else len(text)]
            assert ('(서울)' in block) if meet=='1' else ('(부산)' in block or '(부경)' in block)
            key=f'{meet}:{date}:{int(h[4])}'
            if key not in truth:continue
            parsed=[]
            for m in PAY.finditer(block):
                picks=tuple(sorted(CIRC[x] if x in CIRC else int(re.sub(r'\D','',x)) for x in re.findall(TOKEN,m[1])))
                parsed.append((picks,float(m[2].replace(',','')),m.group(0).strip()))
            matched=[x for x in parsed if x[0]==truth[key]]
            unique={x[1] for x in matched}
            status='valid' if len(unique)==1 and next(iter(unique))>=1 else 'conflicting_report' if len(unique)>1 else 'report_combo_missing'
            assert key not in reports
            reports[key]=dict(race_key=key,report_status=status,
                report_dividend=matched[0][1] if status=='valid' else None,
                report_line=matched[0][2] if status=='valid' else None,
                report_path=str(path.relative_to(ROOT)),report_parsed_combinations=len(parsed))
    db=sqlite_winners(truth)
    rows=[]
    for key,t in truth.items():
        rec=reports.get(key,dict(race_key=key,report_status='report_file_missing',report_dividend=None,report_path=None,report_line=None))
        d=db.loc[key] if key in db.index else None
        api=float(d.odds) if d is not None and pd.notna(d.odds) else None
        disagreement=bool(rec['report_status']=='valid' and api is not None and abs(api-rec['report_dividend'])>.049)
        api_usable=bool(d is not None and d.status=='completed' and d.sqlite_actual==t and api is not None and np.isfinite(api) and 1<=api<9999.9)
        status='snapshot_conflict' if disagreement else 'valid' if rec['report_status']=='valid' or (rec['report_status']=='report_file_missing' and api_usable) else rec['report_status']
        selected=rec['report_dividend'] if rec['report_status']=='valid' else api if api_usable else None
        rows.append({**rec,'actual':','.join(map(str,t)),'api_dividend':api,
            'api_source_id':int(d.source_id) if d is not None and pd.notna(d.source_id) else None,
            'api_observed_at_ms':int(d.observed_at_ms) if d is not None and pd.notna(d.observed_at_ms) else None,
            'api_result_matches':api_usable,
            'selected_source':'rpt' if rec['report_status']=='valid' else 'sqlite_api301' if api_usable else None,
            'status':status,'dividend':selected if status=='valid' else None})
    result=pd.DataFrame(rows)
    result.to_parquet(OUT/'winning_dividends.parquet',compression='zstd',index=False)
    save(OUT/'report_source_manifest.json',manifest)
    save(OUT/'database_snapshot.json',dict(path=str(DB.relative_to(ROOT)),read_only=True,
        frozen_projection='winning_dividends.parquet',projection_sha256=sha(OUT/'winning_dividends.parquet'),
        query_parameters=['2024-01-01','2026-09-20','TLA'],reports=len(manifest),
        sqlite_crosschecks=int(result.api_dividend.notna().sum()),conflicts=int(result.status.eq('snapshot_conflict').sum()),
        whole_db_hash_omitted='Live SQLite/WAL; queried rows read in one read transaction'))
    return result


def dividend_stats(g):
    a=g.to_numpy(float)
    return dict(hits=len(a),mean=float(a.mean()) if len(a) else None,median=float(np.median(a)) if len(a) else None,
        q25=float(np.quantile(a,.25)) if len(a) else None,q75=float(np.quantile(a,.75)) if len(a) else None,
        max=float(a.max()) if len(a) else None,min=float(a.min()) if len(a) else None,
        over100_share=float((a>100).mean()) if len(a) else None)


def summaries(f):
    rows=[];dist=[];uncertainty=[]
    for scope,scoped in f.groupby('scope'):
        groups=[('all',scoped),*[(str(y),g) for y,g in scoped.groupby('year')],
            *[('seoul' if m==1 else 'busan',g) for m,g in scoped.groupby('meet')],
            ('2026H2',scoped[scoped.race_date.ge('2026-07-01')])]
        for label,g in groups:
            for model,z in g.groupby('model'):
                for policy,k,column in [('six',6,'six_hit'),('extra_four',4,'extra_hit'),('ten',10,'ten_hit')]:
                    paid=z.loc[z[column],'dividend'];n=len(z);stake=n*k*1000;returned=float(paid.sum()*1000)
                    best=float(paid.max()) if len(paid) else 0
                    drop_n=max(1,int(np.ceil(len(paid)*.01))) if len(paid) else 0
                    top1pct=float(paid.nlargest(drop_n).sum())
                    rows.append(dict(scope=scope,subgroup=label,model=model,policy=policy,races=n,
                        hits=int(z[column].sum()),hit_rate=float(z[column].mean()),tickets=n*k,stake_krw=stake,
                        return_krw=round(returned,6),net_krw=round(returned-stake,6),gross_return=returned/stake,
                        roi=returned/stake-1,best_dividend=best,best_payout_share=best*1000/returned if returned else None,
                        roi_without_best_race=(returned-best*1000)/((n-1)*k*1000)-1 if n>1 else None,
                        drop_top1pct_hits=drop_n,
                        roi_without_top1pct_hit_races=(returned-top1pct*1000)/((n-drop_n)*k*1000)-1 if n>drop_n else None))
                    dist.append(dict(scope=scope,subgroup=label,model=model,policy=policy,**dividend_stats(paid)))
                if scope=='identical_roster' and label in ['all','2024','2025','2026']:
                    daily=z.assign(six=z.dividend*z.six_hit/6,ten=z.dividend*z.ten_hit/10,
                        extra=z.dividend*z.extra_hit/4).groupby('race_date').agg(n=('race_key','size'),six=('six','sum'),ten=('ten','sum'),extra=('extra','sum'))
                    rng=np.random.default_rng(20261025);d=len(daily)
                    w=rng.multinomial(d,np.full(d,1/d),size=2000);den=w@daily.n.to_numpy()
                    roi_diff=(w@(daily.ten-daily.six).to_numpy())/den
                    ci=np.quantile(roi_diff,[.025,.975]);extra_ci=np.quantile((w@daily.extra.to_numpy())/den-1,[.025,.975])
                    uncertainty.append(dict(scope=scope,subgroup=label,model=model,races=len(z),dates=d,
                        ten_minus_six_roi=float((daily.ten.sum()-daily.six.sum())/len(z)),
                        ci_low=float(ci[0]),ci_high=float(ci[1]),extra_roi_ci_low=float(extra_ci[0]),extra_roi_ci_high=float(extra_ci[1])))
    return pd.DataFrame(rows),pd.DataFrame(dist),pd.DataFrame(uncertainty)


def main():
    OUT.mkdir(exist_ok=True)
    protected=[HERE/'PLAN.md',PREV/'race_results.parquet',BOX/'summary.csv',BOX/'extra_hits.parquet',FLAGS,ROOT/'config/prediction_model_registry.json']
    manifest={str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in protected}
    save(OUT/'input_manifest.json',manifest)
    shared=[R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md',R/'conclusions/source_manifest.json',R/'ARTIFACT_SIZE_LOG.md']
    if not (OUT/'publication_before.json').exists():save(OUT/'publication_before.json',{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
    flags=pd.read_parquet(FLAGS)
    truth={k:tuple(sorted(g.loc[g.finish_order.between(1,3),'program_no'].astype(int))) for k,g in flags.groupby('race_key')}
    assert len(truth)==4799 and all(len(t)==3 for t in truth.values())
    payouts=payout_extract(truth)
    f=pd.read_parquet(PREV/'race_results.parquet')
    six=[];ten=[]
    for row in f.itertuples():
        other=list(map(int,row.companions.split(',')));t=truth[row.race_key]
        assert t==tuple(map(int,row.actual.split(',')))
        s6={tuple(sorted((row.axis,*p))) for p in itertools.combinations(other,2)}
        s10={tuple(sorted(p)) for p in itertools.combinations([row.axis,*other],3)}
        assert len(s6)==6 and len(s10)==10 and s6.issubset(s10)
        six.append(t in s6);ten.append(t in s10)
    f['six_hit']=six;f['ten_hit']=ten;f['extra_hit']=f.ten_hit & ~f.six_hit
    assert f.six_hit.eq(f.hit).all()
    f=f.merge(payouts[['race_key','status','dividend']],on='race_key',validate='m:1')
    coverage=f.groupby(['scope','model','year','status'],dropna=False).agg(races=('race_key','size'),six_hits=('six_hit','sum'),ten_hits=('ten_hit','sum'),extra_hits=('extra_hit','sum')).reset_index()
    coverage.to_csv(OUT/'coverage.csv',index=False)
    accepted=f[f.status.eq('valid')].copy()
    accepted[['race_key','race_date','meet','year','model','scope','dividend','six_hit','ten_hit','extra_hit']].to_parquet(OUT/'race_returns.parquet',index=False,compression='zstd')
    accepted[accepted.scope.eq('identical_roster') & accepted.extra_hit][['race_key','race_date','meet','year','model','axis','companions','actual','dividend']].sort_values('dividend',ascending=False).to_csv(OUT/'extra_four_winners.csv',index=False)
    summary,stats,uncertainty=summaries(accepted)
    summary.to_csv(OUT/'return_summary.csv',index=False);stats.to_csv(OUT/'dividend_summary.csv',index=False);uncertainty.to_csv(OUT/'paired_roi_intervals.csv',index=False)
    for name,meta in manifest.items():assert sha(ROOT/name)==meta['sha256']
    print('COVERAGE',payouts.status.value_counts().to_dict())
    print(summary[(summary.scope=='identical_roster') & summary.model.isin(['operating_A_v5','state_gbm118']) & summary.subgroup.isin(['all','2024','2025','2026'])][['subgroup','model','policy','races','hits','stake_krw','return_krw','net_krw','roi']].to_string(index=False))


if __name__=='__main__':main()
