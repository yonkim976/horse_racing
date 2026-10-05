"""Pre-race history to S1F/G3F position and opening-200m tempo estimates."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
BASE_PATH = HERE.parent / "20261003_baseline_v1"
SPEC = importlib.util.spec_from_file_location("tb_base", BASE_PATH / "run.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
KEY = BASE.KEY
POINTS = ["S1F", "G3F"]


def cfg(): return json.loads((HERE / "config.json").read_text())


def read_points(db):
    with duckdb.connect(str(db), read_only=True) as c:
        rows = c.execute("""
          SELECT cast(source_meet as int) meet,
            strptime(result_date,'%Y%m%d')::DATE race_date,
            cast(result_race_no as int) race_no,
            cast(horse_program_no_raw as int) program_no,horse_id_raw horse_id,
            try_cast(result_rank_raw as int) outcome
          FROM confirmed_runners WHERE source_meet IN ('1','3')
           AND (try_cast(result_rank_raw as int) BETWEEN 1 AND 20 OR try_cast(result_rank_raw as int) IN (91,92))
        """).fetchdf()
        points = c.execute("""
          SELECT meet,strptime(race_date,'%Y%m%d')::DATE race_date,race_no,horse_id,
            max(passing_order) FILTER(WHERE point_code='S1F' AND measure_kind='passing_order') AS S1F_rank,
            max(passing_order) FILTER(WHERE point_code='G3F' AND measure_kind='passing_order') AS G3F_rank,
            max(time_ms) FILTER(WHERE point_code='S1F' AND measure_kind='cumulative_time')/1000.0 AS start_time
          FROM section_measurements_api WHERE meet IN (1,3) AND point_code IN ('S1F','G3F')
          GROUP BY meet,race_date,race_no,horse_id
        """).fetchdf()
        conflicts = c.execute("""
          SELECT count(*) FROM (SELECT meet,race_date,race_no,horse_id,point_code,measure_kind
          FROM section_measurements_api WHERE meet IN (1,3) AND point_code IN ('S1F','G3F')
          GROUP BY ALL HAVING count(distinct passing_order)>1 OR count(distinct time_ms)>1)
        """).fetchone()[0]
    if conflicts: raise ValueError("Conflicting point observations")
    rows["race_date"],points["race_date"] = pd.to_datetime(rows.race_date),pd.to_datetime(points.race_date)
    rows["race_key"] = rows.meet.astype(str)+":"+rows.race_date.dt.strftime("%Y%m%d")+":"+rows.race_no.astype(str)
    if rows.duplicated(KEY).any() or rows.duplicated(["horse_id","race_date"]).any(): raise ValueError("Duplicate start")
    h = rows.merge(points,on=["meet","race_date","race_no","horse_id"],how="left",validate="one_to_one")
    h["n"] = h.groupby("race_key").horse_id.transform("size")
    for point in POINTS:
        rank = h[f"{point}_rank"]
        complete = rank.notna().groupby(h.race_key).transform("all")
        complete &= rank.between(1,h.n).groupby(h.race_key).transform("all")
        complete &= rank.groupby(h.race_key).transform("nunique").eq(h.n)
        h[f"{point}_complete"] = complete
        h[f"{point}_fraction"] = ((rank-1)/(h.n-1)).where(complete)
        h[f"{point}_lead"] = rank.eq(1).astype(float).where(complete)
        h[f"{point}_front"] = rank.le(3).astype(float).where(complete)
    h["advance"] = h.S1F_fraction-h.G3F_fraction
    time_ok = h.start_time.between(10,30)
    h["tempo_complete"] = time_ok.groupby(h.race_key).transform("all")
    h["historical_start_time"] = h.start_time.where(time_ok & h.race_date.ge("2017-01-01"))
    return h


def add_history(frame,h,lag,margin):
    h = h.sort_values(["horse_id","race_date"]).copy()
    g = h.groupby("horse_id",sort=False)
    post = h[["horse_id","race_date"]].rename(columns={"race_date":"pace_source_date"})
    post["pace_available_date"] = post.pace_source_date+pd.Timedelta(days=lag)
    cols = []
    measures = [f"{p}_{kind}" for p in POINTS for kind in ["fraction","lead","front"]]+["advance","historical_start_time"]
    for measure in measures:
        name = f"pace_previous_{measure}"
        post[name]=h[measure]; cols.append(name)
        for k in (3,5,10):
            name = f"pace_last{k}_{measure}"
            post[name] = g[measure].rolling(k,min_periods=1).mean().reset_index(level=0,drop=True)
            cols.append(name)
        name = f"pace_last10_{measure}_count"
        post[name] = g[measure].rolling(10,min_periods=1).count().reset_index(level=0,drop=True)
        cols.append(name)
    f = pd.merge_asof(frame.sort_values("race_date"),post.sort_values("pace_available_date"),left_on="race_date",right_on="pace_available_date",by="horse_id",direction="backward")
    for col in ["pace_last3_S1F_fraction","pace_last3_S1F_front","pace_last3_G3F_fraction","pace_last3_advance","pace_last3_historical_start_time"]:
        name="pace_relative_"+col
        f[name]=f[col]-f.groupby("race_key")[col].transform("mean"); cols.append(name)
    f["pace_unknown_early_count"] = f.pace_last3_S1F_fraction.isna().groupby(f.race_key).transform("sum")
    f["pace_habitual_lead_count"] = f.pace_last5_S1F_lead.ge(.25).groupby(f.race_key).transform("sum")
    faster=np.full(len(f),np.nan); close=np.full(len(f),np.nan)
    for _,idx in f.groupby("race_key",sort=False).indices.items():
        values=f.iloc[idx].pace_last3_historical_start_time.to_numpy(dtype=float,na_value=np.nan)
        difference=values[None,:]-values[:,None]
        known=np.isfinite(values)
        faster[idx]=np.where(known,(difference < -margin).sum(axis=1),np.nan)
        close[idx]=np.where(known,(np.abs(difference)<=margin).sum(axis=1)-1,np.nan)
    f["pace_faster_competitors"],f["pace_close_competitors"] = faster,close
    cols += ["pace_unknown_early_count","pace_habitual_lead_count","pace_faster_competitors","pace_close_competitors"]
    if not (f.pace_source_date.isna() | f.pace_source_date.le(f.race_date-pd.Timedelta(days=lag))).all(): raise ValueError("Pace history leak")
    return f.sort_values(["race_date","meet","race_no","program_no"]).reset_index(drop=True),cols


def race_features(f):
    group=f.groupby("race_key",sort=False)
    r=group[["meet","race_date","year","distance_m","grade","grade_kind","month","field_size","pace_unknown_early_count","pace_habitual_lead_count"]].first()
    columns=["distance_m","grade","grade_kind","month","field_size","pace_unknown_early_count","pace_habitual_lead_count"]
    for col in ["pace_last3_historical_start_time","pace_last3_S1F_front","pace_last3_S1F_fraction","pace_last3_advance","previous_age"]:
        for stat in ["mean","min","std"]:
            name=f"field_{col}_{stat}"
            r[name]=getattr(group[col],stat)(); columns.append(name)
    r["past_fast3_time"]=group.pace_last3_historical_start_time.agg(lambda s:s.dropna().nsmallest(3).mean() if s.notna().sum()>=3 else np.nan)
    columns.append("past_fast3_time")
    return r.reset_index(),columns


def prepare():
    c=cfg(); OUT.mkdir(exist_ok=False)
    db=ROOT/c["source_db"]; baseline=ROOT/c["baseline"]
    audit=json.loads((baseline/"outputs/data_audit.json").read_text())
    digest=BASE.sha(db)
    if digest!=audit["source_sha256"]: raise ValueError("Baseline and current source differ")
    h=read_points(db)
    f=pd.read_parquet(baseline/"outputs/features.parquet")
    original_contract=json.loads((baseline/"outputs/feature_contract.json").read_text())
    f,extra=add_history(f,h,c["history_lag_days"],c["competition_time_margin_seconds"])
    target=h[KEY+[f"{p}_{k}" for p in POINTS for k in ["rank","fraction","complete"]]+["tempo_complete"]]
    labels=f[KEY].merge(target,on=KEY,validate="one_to_one")
    r,rcols=race_features(f)
    target_race=h.groupby("race_key").agg(tempo_complete=("tempo_complete","first"),tempo_time=("start_time",lambda x:x.nsmallest(3).mean()))
    rlabels=r[["race_key"]].merge(target_race.reset_index(),on="race_key",validate="one_to_one")
    f.to_parquet(OUT/"features.parquet",index=False); labels.to_parquet(OUT/"labels.parquet",index=False)
    r.to_parquet(OUT/"race_features.parquet",index=False); rlabels.to_parquet(OUT/"race_labels.parquet",index=False)
    cohort=f[["race_key","meet","race_date","year","field_size"]].drop_duplicates("race_key").merge(labels.groupby("race_key")[["S1F_complete","G3F_complete","tempo_complete"]].first().reset_index(),on="race_key")
    cohort.to_csv(OUT/"cohort.csv",index=False)
    cohort.groupby(["meet","year"])[["S1F_complete","G3F_complete","tempo_complete"]].sum().to_csv(OUT/"coverage.csv")
    BASE.save_json(OUT/"feature_contract.json",{"runner":original_contract["history_records"]+extra,"race":rcols})
    if digest!=BASE.sha(db): raise ValueError("Source changed")
    snapshot={"source_sha256":digest,"source_db":str(db),"baseline_code_sha256":BASE.sha(BASE_PATH/"run.py"),
      "baseline_features_sha256":BASE.sha(baseline/"outputs/features.parquet"),"code_sha256":BASE.sha(__file__),"config_sha256":BASE.sha(HERE/"config.json"),
      "registry_sha256":BASE.sha(ROOT/"config/prediction_model_registry.json"),"history_rows":len(h),"target_runners":len(f),"target_races":len(r),
      "input_hashes":{p.name:BASE.sha(p) for p in OUT.iterdir() if p.is_file()},"production_changed":False}
    BASE.save_json(OUT/"data_audit.json",snapshot)
    print(json.dumps({"runners":len(f),"races":len(r),"complete_targets":cohort[["S1F_complete","G3F_complete","tempo_complete"]].sum().to_dict()}),flush=True)


def fit_regression(frame,columns,target,eligible,year,c,path,race_weight=False):
    first=frame.year.between(c["training_start_year"],year-3)&eligible
    valid=frame.year.eq(year-2)&eligible
    final=(first|valid)
    x,vocab=BASE.category_encode(frame,first,columns)
    weights=1/frame.field_size if race_weight else np.ones(len(frame))
    params=c["training"].copy(); rounds=params.pop("max_rounds"); early=params.pop("early_stopping_rounds"); params["seed"]=c["seed"]
    def dataset(mask): return lgb.Dataset(x[mask],label=frame.loc[mask,target],weight=np.asarray(weights)[mask],free_raw_data=False)
    model=lgb.train(params,dataset(first),num_boost_round=rounds,valid_sets=[dataset(valid)],callbacks=[lgb.early_stopping(early,verbose=False)])
    chosen=model.best_iteration
    model=lgb.train(params,dataset(final),num_boost_round=chosen)
    model.save_model(str(path))
    needed=frame.year.isin([year-1,year])
    predictions=np.full(len(frame),np.nan); predictions[needed]=model.predict(x[needed])
    meta={"file":path.name,"sha256":BASE.sha(path),"columns":columns,"vocabulary":vocab,"trees":chosen,"training_year_end":year-2,"calibration_year":year-1,"evaluation_year":year,
      "training_rows":int(final.sum()),"feature_gain":dict(sorted(zip(columns,map(float,model.feature_importance(importance_type="gain"))),key=lambda x:-x[1]))}
    return predictions,meta


def point_evaluation(frame,point,predictions,year,name,c):
    cal=frame.year.eq(year-1)&frame[f"{point}_complete"]
    test=frame.year.eq(year)&frame[f"{point}_complete"]
    ranking=frame.assign(outcome=frame[f"{point}_rank"])
    scores=np.repeat(-predictions[:,None],3,axis=1)
    temps=[BASE.temperature_fit(ranking[cal],scores,k,c["temperature_bounds"]) for k in range(3)]
    runner,race=[],[]
    for key,one in frame[test].groupby("race_key",sort=False):
        idx=one.index.to_numpy(); n=len(one); target=one[f"{point}_rank"].to_numpy(dtype=int)
        ix,q,p=BASE.joint(scores[idx],temps)
        actual=[int(np.flatnonzero(target==k)[0]) for k in (1,2,3)]
        estimate=1+np.clip(predictions[idx],0,1)*(n-1)
        front=np.argsort(-p[:,2],kind="stable")[:3]
        actual_front=set(actual)
        brier,ll=BASE.binary_metrics(p[:,2],np.isin(np.arange(n),actual).astype(int))
        row={"race_key":key,"meet":int(one.meet.iloc[0]),"year":year,"race_date":str(one.race_date.iloc[0].date()),"point":point,"variant":name,
          "fraction_mae":float(np.mean(np.abs(predictions[idx]-one[f"{point}_fraction"].to_numpy(dtype=float)))),
          "position_mae":float(np.mean(np.abs(estimate-target))),"leader_hit":int(np.argmax(p[:,0])==actual[0]),
          "top3_exact_hit":int(set(front)==actual_front),"front_recall":len(set(front)&actual_front)/3,
          "leader_nll":float(-np.log(p[actual[0],0])),"ordered_top3_nll":float(-np.log(q[np.all(ix==actual,axis=1)].sum())),"top3_brier":brier,"top3_logloss":ll,
          "probability_sum_error":float(np.max(np.abs(p.sum(axis=0)-[1,2,3])))}
        race.append(row)
        for loc,(_,entry) in enumerate(one.iterrows()):
            runner.append({**{k:entry[k] for k in KEY},"meet":int(entry.meet),"year":year,"race_date":entry.race_date,"point":point,"variant":name,
              "predicted_fraction":float(predictions[idx[loc]]),"expected_position":float(estimate[loc]),"prob_lead":float(p[loc,0]),"prob_front3":float(p[loc,2]),
              "actual_rank":int(target[loc])})
    return runner,race,temps


def tempo_probabilities(prediction,residuals,q25,q75):
    if q25>q75 or not len(residuals): raise ValueError("Invalid tempo reference")
    fast=float(np.mean(prediction+residuals<q25)); slow=float(np.mean(prediction+residuals>q75))
    return np.array([fast,1-fast-slow,slow])


def tempo_evaluation(frame,predictions,year,name,c):
    cal=frame[frame.year.eq(year-1)&frame.tempo_complete]
    bias=float(np.mean(cal.tempo_time.to_numpy()-predictions[cal.index]))
    residual=cal.tempo_time.to_numpy()-predictions[cal.index]-bias
    reference=cal.groupby("distance_m").tempo_time.agg(["count",lambda x:x.quantile(.25),lambda x:x.quantile(.75)])
    reference.columns=["count","q25","q75"]
    reference=reference[reference['count'].ge(c["minimum_tempo_reference_races"])]
    rows=[]
    for i,entry in frame[frame.year.eq(year)&frame.tempo_complete].iterrows():
        estimate=float(predictions[i]+bias)
        row={"race_key":entry.race_key,"meet":int(entry.meet),"year":year,"race_date":str(entry.race_date.date()),"variant":name,
          "distance_m":float(entry.distance_m),"predicted_time":estimate,"actual_time":float(entry.tempo_time),"absolute_error":abs(estimate-entry.tempo_time)}
        if entry.distance_m in reference.index:
            ref=reference.loc[entry.distance_m]; probs=tempo_probabilities(estimate,residual,ref.q25,ref.q75)
            truth=0 if entry.tempo_time<ref.q25 else 2 if entry.tempo_time>ref.q75 else 1
            row.update({"prob_fast":probs[0],"prob_normal":probs[1],"prob_slow":probs[2],"actual_class":truth,"class_hit":int(np.argmax(probs)==truth),
              "class_brier":float(np.sum((probs-np.eye(3)[truth])**2)),"class_logloss":float(-np.log(max(1e-12,probs[truth])))})
        rows.append(row)
    return rows,{"bias":bias,"residuals":residual.tolist(),"references":reference.reset_index().to_dict("records")}


def train():
    c=cfg(); audit=json.loads((OUT/"data_audit.json").read_text())
    if BASE.sha(__file__)!=audit['code_sha256'] or BASE.sha(HERE/"config.json")!=audit['config_sha256']: raise ValueError("Frozen definition changed")
    if BASE.sha(BASE_PATH/"run.py")!=audit['baseline_code_sha256']: raise ValueError("Baseline helper changed")
    for name,digest in audit['input_hashes'].items():
        if BASE.sha(OUT/name)!=digest: raise ValueError("Input changed: "+name)
    (OUT/"models").mkdir(exist_ok=False)
    contracts=json.loads((OUT/"feature_contract.json").read_text())
    f=pd.read_parquet(OUT/"features.parquet").merge(pd.read_parquet(OUT/"labels.parquet"),on=KEY,validate="one_to_one")
    r=pd.read_parquet(OUT/"race_features.parquet").merge(pd.read_parquet(OUT/"race_labels.parquet"),on="race_key",validate="one_to_one")
    runner_rows,race_rows,tempo_rows,bundles=[],[],[],[]
    for meet in c["venues"]:
        one=f[f.meet.eq(meet)].reset_index(drop=True); races=r[r.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            dest=OUT/"models"/f"{meet}_{year}"; dest.mkdir()
            print(f"Training pace meet={meet} year={year}",flush=True)
            bundle={"meet":meet,"year":year,"models":[],"point_temperatures":{},"tempo":{}}
            for point in POINTS:
                eligible=one[f"{point}_complete"]
                model_pred,meta=fit_regression(one,contracts['runner'],f"{point}_fraction",eligible,year,c,dest/f"{point}.txt",race_weight=True)
                bundle['models'].append(meta)
                for name,pred in [("past_style",one[f"pace_last3_{point}_fraction"].fillna(.5).to_numpy(dtype=float)),("field_model",model_pred)]:
                    a,b,t=point_evaluation(one,point,pred,year,name,c)
                    runner_rows.extend(a); race_rows.extend(b); bundle['point_temperatures'][point+":"+name]=t
            tempo_pred,meta=fit_regression(races,contracts['race'],'tempo_time',races.tempo_complete,year,c,dest/"tempo.txt")
            bundle['models'].append(meta)
            train_reference=races[races.year.between(c['training_start_year'],year-2)&races.tempo_complete].groupby('distance_m').tempo_time.median()
            simple=races.past_fast3_time.fillna(races.distance_m.map(train_reference)).fillna(float(train_reference.median())).to_numpy(dtype=float)
            for name,pred in [('past_style',simple),('field_model',tempo_pred)]:
                rows,calibration=tempo_evaluation(races,pred,year,name,c)
                tempo_rows.extend(rows); bundle['tempo'][name]=calibration
            BASE.save_json(dest/'metadata.json',bundle); bundles.append(bundle)
            print(f"Evaluated pace meet={meet} year={year}",flush=True)
    rp,rm,tp=pd.DataFrame(runner_rows),pd.DataFrame(race_rows),pd.DataFrame(tempo_rows)
    rp.to_parquet(OUT/'runner_predictions.parquet',index=False); rm.to_csv(OUT/'point_metrics.csv',index=False); tp.to_csv(OUT/'tempo_predictions.csv',index=False)
    metrics=['fraction_mae','position_mae','leader_hit','top3_exact_hit','front_recall','leader_nll','ordered_top3_nll','top3_brier']
    summaries=[]
    for (meet,point,name),one in rm.groupby(['meet','point','variant']):
        for period,cell in [('all',one),*[(str(y),g) for y,g in one.groupby('year')]]:
            summaries.append({'meet':int(meet),'point':point,'variant':name,'period':period,'races':len(cell),**{m:float(cell[m].mean()) for m in metrics}})
    summary=pd.DataFrame(summaries); summary.to_csv(OUT/'metrics.csv',index=False)
    tempo_summary=tp.groupby(['meet','variant','year']).agg(races=('race_key','size'),time_mae=('absolute_error','mean'),class_hit=('class_hit','mean'),class_brier=('class_brier','mean'),classified_races=('class_hit','count')).reset_index()
    tempo_summary.to_csv(OUT/'tempo_metrics.csv',index=False)
    # Separate marginal predictions support an expected change, not a joint trajectory probability.
    advance=rp[rp.point.eq('S1F')].merge(rp[rp.point.eq('G3F')],on=KEY+['variant','year'],suffixes=('_early','_late'),validate='one_to_one')
    advance['predicted_advance']=advance.expected_position_early-advance.expected_position_late
    advance['actual_advance']=advance.actual_rank_early-advance.actual_rank_late
    advance['advance_error']=abs(advance.predicted_advance-advance.actual_advance)
    advance.to_parquet(OUT/'position_changes.parquet',index=False)
    advance.groupby(['meet_early','variant','year']).advance_error.agg(['size','mean']).to_csv(OUT/'position_change_metrics.csv')
    differences=[]; rng=np.random.default_rng(c['seed'])
    for meet in c['venues']:
        for point in POINTS:
            cell=rm[(rm.meet==meet)&rm.point.eq(point)]
            paired=cell[cell.variant.eq('past_style')].merge(cell[cell.variant.eq('field_model')],on='race_key',suffixes=('_base','_model'),validate='one_to_one')
            for metric in ['fraction_mae','leader_hit','top3_brier']:
                d=paired[f'{metric}_model']-paired[f'{metric}_base']
                groups=pd.DataFrame({'day':paired.race_date_base,'d':d}).groupby('day').d.agg(['sum','size']).to_numpy()
                draws=groups[rng.integers(0,len(groups),(c['bootstrap_draws'],len(groups)))]
                interval=np.quantile(draws[:,:,0].sum(axis=1)/draws[:,:,1].sum(axis=1),[.025,.975])
                differences.append({'meet':meet,'point':point,'metric':metric,'model_minus_past':float(d.mean()),'ci95':interval.tolist()})
    BASE.save_json(OUT/'paired_differences.json',differences)
    result={'experiment':c['experiment'],'models':bundles,'metrics':summary.to_dict('records'),'tempo_metrics':tempo_summary.to_dict('records'),
      'production_changed':False,'final_finish_model_changed':False,'code_sha256':BASE.sha(__file__),'config_sha256':BASE.sha(HERE/'config.json'),
      'result_hashes':{p.name:BASE.sha(p) for p in OUT.iterdir() if p.is_file()}}
    BASE.save_json(OUT/'summary.json',result)
    report(summary,tempo_summary,rp,differences)
    print('Completed: '+str(OUT/'REPORT.md'),flush=True)


def report(summary,tempo_summary,rp,differences):
    lines=['# 더러브렛 전개 예측 v1 — 후향 검증','',
      '과거 성적·기록 기반 착순 모델과 별도로 전개기 자체를 학습했다. 2010~2016 warm-up, 정답 학습2017년 이후, 매년 평가 이전 자료만 사용한다. 현재 결과로 재구성한 편성이며 전체 경로·기수 의도·선행 경합의 인과효과를 예측했다고 표시하지 않는다.','',
      '## 통과순위 예측','', '| 경마장 | 지점 | 모델 | 경주 | 순위 MAE ↓ | 통과1위 선택 | 상위3두 전부 포함 | Top3 Brier ↓ |', '|---|---|---|---:|---:|---:|---:|---:|']
    for _,r in summary[summary.period.eq('all')].iterrows():
        lines.append(f"| { {1:'서울',3:'부산'}[r.meet]} | {r.point} | {r.variant} | {r.races:,} | {r.position_mae:.3f}두 | {r.leader_hit:.1%} | {r.top3_exact_hit:.1%} | {r.top3_brier:.4f} |")
    lines+=['','S1F=출발200m, G3F=마지막600m 진입 지점. 같은 마군 안의 발표순위는 물리적인 단독 선두/주행거리와 구분한다. 단순 기준은 최근3회 상대 통과순위, field_model은 과거 성향과 현재 편성 경쟁을 학습한 모델이다.','',
      '## 출발200m 초반 페이스','', '| 경마장 | 연도 | 모델 | 경주 | 상위3두 평균시간 MAE ↓ | 페이스 분류 적중 | 분류 표본 |', '|---|---|---|---:|---:|---:|---:|']
    for _,r in tempo_summary.iterrows():
        lines.append(f"| { {1:'서울',3:'부산'}[r.meet]} | {r.year} | {r.variant} | {r.races:,} | {r.time_mae:.3f}초 | {r.class_hit:.1%} | {r.classified_races:,} |")
    lines+=['','빠름/보통/느림의 구간은 평가 이전 보정연도의 같은 거리 분위수로 고정했다. 표본40경주 미만 거리는 분류하지 않는다. 이 값은 초반200m 페이스이며 전체 경주의 경합 강도가 아니다.','',
      '## 동일 경주 비교','', '| 경마장 | 지점 | 지표 | 모델−단순 기준 | 경주일 bootstrap 95% 구간 |', '|---|---|---|---:|---:|']
    for d in differences:
        lo,hi=d['ci95']; lines.append(f"| { {1:'서울',3:'부산'}[d['meet']]} | {d['point']} | {d['metric']} | {d['model_minus_past']:+.5f} | {lo:+.5f} ~ {hi:+.5f} |")
    lines+=['','## 역사 경주 출력 예시','', '아래는 평가자료 중 서울 최신 시행일 첫 경주의 전개 예측 재현이다. 실제 사전 발행 예측이 아니다. 현재 경주의 실제 통과순위는 입력하지 않았다.','']
    sample=rp[(rp.meet==1)&rp.year.eq(2026)&rp.variant.eq('field_model')]
    lastdate=sample.race_date.max(); key=sorted(sample[sample.race_date.eq(lastdate)].race_key.unique(),key=lambda x:int(x.rsplit(':',1)[1]))[0]
    a=sample[sample.race_key.eq(key)&sample.point.eq('S1F')].merge(sample[sample.race_key.eq(key)&sample.point.eq('G3F')],on=KEY,suffixes=('_early','_late'))
    lines += [f'경주키 `{key}`','', '| 번호 | 초반 예상순위 | S1F 통과1위 확률 | S1F 상위3위 확률 | G3F 예상순위 |', '|---:|---:|---:|---:|---:|']
    for _,row in a.sort_values('expected_position_early').iterrows():
        lines.append(f"| {row.program_no} | {row.expected_position_early:.1f} | {row.prob_lead_early:.1%} | {row.prob_front3_early:.1%} | {row.expected_position_late:.1f} |")
    lines += ['','입상 개선은 아직 연결 검증하지 않았다. 다음 단계는 학습 표본에도 시간순 외부 전개 예측을 만든 뒤, 기존 착순 모델과 같은 경주에서 전개 추가 효과를 비교하는 것이다. 코너별 확장·게이트·기수·주행심사·전개 시나리오는 이후 후보다.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['prepare','train']); args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
