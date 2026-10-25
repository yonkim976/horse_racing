"""Verify frozen time-ordered comparisons and publish a performance-state study."""
from pathlib import Path
import importlib.util
import json
import re
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
sp=importlib.util.spec_from_file_location('recent_form',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
sha=a.sha
def write(p,v):p.write_text(json.dumps(a.clean(v),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def new(name,txt):
    with (H/name).open('x',encoding='utf-8') as z:z.write(txt)
def tab(head,rows):return '\n'.join(['| '+' | '.join(head)+' |','|'+'|'.join(['---']*len(head))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'
def n(v):return f'{v:+.3f}'.replace('-','−')
def ci(r):return f'{n(r.ci_lo)}~{n(r.ci_hi)}'
central=json.loads((C/'source_manifest.json').read_text());assert all(sha(ROOT/z['path'])==z['sha256'] for z in central['files']);before={z['path']:z['sha256'] for z in central['files'] if z['role']=='conclusion_or_management'}
f=pd.read_csv(H/'features.csv',dtype={'horse_id':str},low_memory=False);p=pd.read_csv(H/'predictions.csv',dtype={'horse_id':str});models=json.loads((H/'models.json').read_text());lineage=json.loads((H/'feature_lineage.json').read_text());d,h=a.a.old.load();body=pd.read_csv(a.PRE/'source_lineage.csv',dtype={'horse_id':str},low_memory=False);bodydict=body.set_index('api_record_id').to_dict('index');datedict=d[['horse_id','race_distance_m','race_date','finish_time_seconds']].to_dict('index');historychecked=0
for r in lineage:
    for rid in r['time_history_ids']:
        z=datedict[rid];assert z['horse_id']==r['horse_id'] and z['race_distance_m']==r['distance'] and z['race_date']<=r['history_cutoff'];historychecked+=1
    for rid in r['body_history_ids']:
        z=bodydict[rid];assert z['horse_id']==r['horse_id'] and z['race_date']<=r['history_cutoff'];historychecked+=1
assert f.api_record_id.is_unique and p.api_record_id.is_unique and set(p.api_record_id)<=set(f.api_record_id)
assert not f.horse_id.eq('3005648').any()
def transform(g,m):
    raw=g[m['numeric_columns']].to_numpy(float);missing=np.isnan(raw);imputed=np.where(missing,np.array(m['imputer_median']),raw);num=np.column_stack([imputed,missing[:,m['missing_indicators']].astype(float)]);num=(num-np.array(m['scale_mean']))/np.array(m['scale_sd']);cats=[]
    for col,levels in zip(a.CATS,m['categorical_levels']):
        for level in levels:cats.append(g[col].astype(str).eq(level).to_numpy(float))
    return np.column_stack([num]+cats)
independent=[]
for m in models:
    train=f[f.year.lt(m['year'])&f.distance.eq(m['distance'])];test=f[f.year.eq(m['year'])&f.distance.eq(m['distance'])]
    assert train.race_date.max()==m['training_max_date'] and m['training_max_year']<m['year']
    x=transform(test,m);calc=x@np.array(m['coefficient'])+m['intercept'];saved=p.set_index('api_record_id').loc[test.api_record_id,'prediction_'+m['model']].to_numpy();assert np.allclose(calc,saved,atol=1e-9)
    if m['year'] in [2024,2026] and m['distance'] in [1000,1110] and m['model'] in ['B','D']:
        x=np.column_stack([np.ones(len(train)),transform(train,m)]);w=1/train.eligible_in_race.to_numpy();w/=w.mean();pen=np.r_[0,np.full(x.shape[1]-1,10.)];coef=np.linalg.solve(x.T@(x*w[:,None])+np.diag(pen),x.T@(train.time.to_numpy()*w));expected=np.r_[m['intercept'],m['coefficient']];err=float(np.max(np.abs(coef-expected)));assert err<1e-7;independent.append({'year':m['year'],'distance':m['distance'],'model':m['model'],'maximum_coefficient_error':err})
imp=pd.read_csv(H/'paired_improvements.csv');metrics=pd.read_csv(H/'metrics.csv');pers=pd.read_csv(H/'persistence_contrasts.csv');groups=pd.read_csv(H/'persistence_groups.csv');adj=pd.read_csv(H/'immediate_next_observed_persistence.csv');adje=pd.read_csv(H/'immediate_next_observed_improvements.csv');flags=pd.read_csv(H/'immediate_next_observed_flags.csv')
periods={'2024':[2024],'2025':[2025],'2024_2025':[2024,2025],'2026partial':[2026]}
for r in metrics.itertuples():
    g=p[p.year.isin(periods[str(r.period)])&p.distance.eq(r.distance)];w=g.race_weight;assert np.isclose(r.mae_s,np.average(g['abs_error_'+r.model],weights=w)) and np.isclose(r.rmse_s,np.sqrt(np.average(g['sq_error_'+r.model],weights=w)))
for r in imp.itertuples():
    g=p[p.year.isin(periods[str(r.period)])&p.distance.eq(r.distance)];right,left=r.contrast.split('_vs_');col='abs_error_' if r.metric=='mae' else 'relative_abs_error_';y=(g[col+left]-g[col+right]).to_numpy();w=g.race_weight.to_numpy();w/=w.sum();pt=w@y;scores=w*(y-pt);variance=0
    for ids in [g.race_date,g.horse_id]:
        codes=pd.factorize(ids)[0];sums=np.bincount(codes,weights=scores);variance+=len(sums)/(len(sums)-1)*(sums@sums)
    se=np.sqrt(variance);cr=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1);assert np.isclose(pt,r.effect) and np.isclose(pt-cr*se,r.ci_lo) and np.isclose(pt+cr*se,r.ci_hi)
for df,keys in [(imp,['period','contrast','metric']),(pers,['period']),(adj,['period']),(adje,['period','contrast'])]:
    for _,g in df.groupby(keys):assert np.allclose(a.a.old.bh(g.p.to_numpy()),g.q_BH)
idline={r['api_record_id']:r for r in lineage}
for r in flags[flags.is_immediate_observed_same_distance_7to60].itertuples():assert r.previous_observed_api_record_id==idline[r.api_record_id]['time_history_ids'][-1]
audit=json.loads((H/'input_audit.json').read_text());cov=pd.read_csv(H/'candidate_event_date_coverage_rows.csv',dtype={'horse_id':str});con=sqlite3.connect(a.a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');rng=np.random.default_rng(20261008);coverage_checks=0
for r in cov.iloc[rng.choice(len(cov),64,replace=False)].itertuples():
    start=(pd.Timestamp(r.race_date)-pd.Timedelta(days=28)).strftime('%Y-%m-%d');cut=(pd.Timestamp(r.race_date)-pd.Timedelta(days=2)).strftime('%Y-%m-%d');sql='SELECT COUNT(*) FROM daily_training_api_rows WHERE horse_id=? AND training_date>=? AND training_date<=?' if r.kind=='training' else 'SELECT COUNT(*) FROM medical_api_rows WHERE horse_id=? AND clinic_date>=? AND clinic_date<=?';nobs=con.execute(sql,(r.horse_id,start,cut)).fetchone()[0];assert nobs==r.observed_rows_last28days_through_Tminus2;coverage_checks+=1
con.close()
for r in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(r['path']))==r['sha256']
assert sha(a.a.old.DB)==audit['database_sha256']
write(H/'calculation_verification.json',{'status':'passed','all_prediction_coefficients_and_preprocessing_reconstructed':len(models),'independent_weighted_ridge_coefficient_checks':independent,'all_MAE_RMSE_and_date_horse_CI_recomputed':True,'all_BH_families_recomputed':True,'all_feature_history_endpoints_checked':historychecked,'coverage_independent_parameterized_SQL_checks':coverage_checks,'immediate_observed_ID_matches_verified':True,'excluded_horse_absent':True,'database_unchanged':True,'source_hashes_unchanged':True})

mainrows=[];bodyrows=[];adjrows=[];recentrows=[]
for period in ['2024_2025','2026partial']:
    for dist in [1000,1110,1200]:
        mm=metrics[(metrics.period==period)&metrics.distance.eq(dist)].set_index('model');r=imp[(imp.period==period)&imp.distance.eq(dist)&imp.metric.eq('mae')&imp.contrast.eq('B_vs_A')].iloc[0];mainrows.append([period,f'{dist}m',f'{int(r.rows):,} / {int(r.races):,}',f'{mm.loc["A","mae_s"]:.3f}',f'{mm.loc["B","mae_s"]:.3f}',n(r.effect),ci(r)])
        b=imp[(imp.period==period)&imp.distance.eq(dist)&imp.metric.eq('mae')&imp.contrast.eq('D_vs_B')].iloc[0];bodyrows.append([period,f'{dist}m',n(b.effect),ci(b),f'{b.q_BH:.4f}'])
        ar=adj[(adj.period==period)&adj.distance.eq(dist)].iloc[0];adjrows.append([period,f'{dist}m',f'{int(ar.rows):,}',f'{int(ar.good_rows)} / {int(ar.poor_rows)}',n(ar.effect),ci(ar)])
        rr=imp[(imp.period==period)&imp.distance.eq(dist)&imp.metric.eq('relative_mae')&imp.contrast.eq('B_vs_A')].iloc[0];recentrows.append([period,f'{dist}m',n(rr.effect),ci(rr),f'{rr.q_BH:.4f}'])
coverage=pd.read_csv(H/'candidate_event_date_coverage.csv');covrows=[[r.kind,int(r.year),f'{int(r.starts_with_observed_rows):,} / {int(r.starts):,}',f'{100*r.observed_fraction:.1f}%'] for r in coverage[coverage.year.isin([2024,2025,2026])].itertuples()]
report='''# 제주 최근 경기력 상태와 다음 경주 기록의 지속성

**최근 기록은 후속 기록에 이어지는 경기력 신호를 포함한다. 이번에 시험한 과거 마체중 요약은 최근 기록에 더했을 때 뚜렷한 추가 개선을 보이지 않았다.** 이는 생리적 컨디션·질병·회복 상태를 직접 확인했다는 뜻이 아니다. 최근 기록에는 능력 변화·주로·편성·부담중량·전개가 함께 섞인다. ‘최근 경기력 상태의 대용 지표’로 설명하며 건강 진단이나 확정 컨디션 확률로 표시하지 않는다.

학습 원천은2017~2026-09-19의52,155출전·5,206경주다. 충분한 과거 이력과 경주 내 비교 대상이 있는26,013출전·4,051경주를 후보로 만들었다. 같은 거리 과거 기록5회 이상과 경주 내 후보3두 이상을 요구하므로 신마·거리 전환 초기·정상 완주 외 출전까지 일반화하지 않는다. 연도별 학습·평가 지원을 통과한2024~2026부분기간7,709출전·1,273경주를 같은 표본으로 비교했다. 현재800~1610m를 모두 점검했지만1300·1400·1610m는 학습 또는 평가 지원이 부족해 효과를 내지 않았다.

## 다음 경주 전에 사용할 수 있는 정보만 비교

대상 경주의T−2까지 날짜가 지난 과거 출전만 사용했다. 대상 경주의 실제 체중·시간·함수율·부담중량·게이트·등급·성별·나이를 입력하지 않았다. 거리와 달력 날짜는 예정된 경주 정보라는 가정이다. 과거 기록은 현재 보유된 정정 후 스냅샷일 수 있어 당시 공개·정정 시각까지 입증한 것은 아니다.

각 거리별 간단한Ridge 연구 모형4개를 비교했다.2024년은2023년까지,2025년은2024년까지,2026년은2025년까지 학습했다. 계수 강도10과 입력 묶음·지원 기준을 결과 확인 전에 고정했고 동일 표본에 적용했다. 이 기간들은 이전 연구에서도 사용했으므로 새 독립 미래 검증이 아니라 시간 순서를 지킨 후향 개발 비교다. 운영HY_R_FORM의 개선 여부를 측정한 실험도 아니다.

| 모형 | 입력 |
|---|---|
| A | 최근2회를 제외한 동일 거리 과거 기록의 평균·중앙값,경력·간격,과거 중량·성별·등급·사건 나이,달력 주기 |
| B | A에 최근1·2·5회 기록,최근 추세·변동성·최고 기록 추가 |
| C | A에 과거 최대6회 관측 체중의 수준·편차·증감·변동성·측정 경과일 추가 |
| D | B에 C의 과거 체중 정보를 추가 |

체중 기준은 해당 시점 이전 최대6회로만 계산했다. 전체 경력 평균이나 미래 체중을 사용하지 않았다. 체중은현재 거리만이 아니라과거 보유 정상 출전의 모든 현재 거리를 포함하며,바로 직전 경력 전체 측정이라고 보장하지 않는다. 측정 경과일과 개수를 함께 입력하고 결측을 유지했다. 경주 당시 원문 나이는 과거 통제값이며2026년 고정 프로필 나이와 다르다.

## 최근 기록을 추가하면 다음 기록 오차가 줄어드는가

아래는실제 다음 기록에 대한평균 절대오차MAE,단위초다.경주별같은가중치를부여했다.오차 감소가양수면B가A보다좋은방향이며괄호는날짜+말군집의점별95%구간이다.이는최근 기록의가치를오래된기록기준과비교한값으로,이미최근기록을잘사용하는모형보다추가로개선된다는뜻은아니다.

'''+tab(['평가 기간','거리','출전 / 경주','A 오차 초','B 오차 초','오차 감소 초','95% 구간'],mainrows)+'''
2024~2025년합계1000·1110·1200m의오차감소는BH근거가남았다.다만2024년만따로보면어느거리도확실하지않았고,2025년에서개선이더컸다.2026년부분기간은1000·1110·1200m와표본이작은900m에서도감소했지만효과크기가기간에따라달라졌다.800·900m의2024~2025합계는평가최소기준때문에2024년만포함하고,800m2026년은미추정이다.[전체연도·거리지원](model_support.csv)과[전체오차](metrics.csv)를함께보존했다.

## 경주 전체의 시간 변화와 개별 말의 상태를 구분

절대기록개선에는최근경주들의공통주로·속도변화나장기모형의시기별편향을최근기록이따라가는효과도포함된다.평가에서같은경주의실제시간평균과예측시간평균을각각뺀상대시간오차를추가확인했다.이때실제경주평균은평가라벨에만사용하고예측입력으로넣지않았다.

'''+tab(['평가 기간','거리','상대시간 MAE 감소 초','95% 구간','BH q'],recentrows)+'''
2024~2025년1110m의상대오차개선은약0.045초로절대오차개선0.220초보다작다.1000m상대개선0.032초는구간이0을포함한다.2026년1000·1110m상대개선은약0.008·0.010초로불확실하다.**절대기록오차0.5초감소를그대로개별말컨디션파악능력이라고설명하지않는다.** 800m2024년상대개선은근거가있지만표본이175출전이고후기확인이부족하다.

## 바로 다음 출전에도 빠른 또는 느린 신호가 이어지는가

최근직전동일거리기록이그이전기록중앙값보다0.5초이상빠르면‘최근빠른군’,0.5초이상느리면‘최근느린군’으로고정분류했다.이는건강판정기준이나최적경계가아니다.다음경주에서A의예측오차를경주내평균에서얼마나벗어났는지로평가했다.

주분석의최근동일거리출전사이에다른거리출전이있을수있어,그최근출전이보유결과상바로직전출전과같고간격7~60일인경우로다시한정했다.원래모형예측을동결해재사용한4,960출전의후속확인이다.자료에서관측된연속출전이며공식전체경력의완전성을보증하지는않는다.[사후정의확인계획](ADJACENCY_CHECK_PLAN.json)에앞선주결과를이미확인했음을남겼다.

아래는**빠른군−느린군의다음경주상대예측오차차이**다.음수면최근빠른군이후속에서도상대적으로빠른방향이다.두군말들의실제완주시간차이나동일말의순수컨디션효과가아니다.

'''+tab(['평가 기간','거리','연속 조건 출전','빠른군 / 느린군','다음 상대오차 차이 초','95% 구간'],adjrows)+'''
모든표시거리·기간에서차이의BH근거가남았다.최근경기력의방향이바로다음출전의설명에사용할수있는신호라는근거다.다만그신호가현재체력·건강만으로발생했는지,개별말에게어느정도확률로이어지는지,얼마동안지속되는지는확정하지못했다.과거기록의오차·변화하는능력·연령·경주선택의잔여차이가남고개별진단정답은없다.

간격별주분석에서는2024~2025년1000·1110m의최근기록개선이30일이내와31~60일에서보였지만61일이상에서는불확실했다.2026년에는긴간격에서도감소해지속기간이나일정한감쇠율을확정하지않았다.간격별표는탐색용점별구간이며별도BH를적용하지않았다.[간격별전체표](rest_interval_improvements.csv)를따른다.

## 마체중을 더하면 최근 상태 파악이 좋아지는가

최근기록을이미사용한B에체중을추가한D의MAE개선이다.양수는개선,음수는악화다.

'''+tab(['평가 기간','거리','체중 추가의 오차 감소 초','95% 구간','BH q'],bodyrows)+'''
2024~2025년에는어느지원거리에서도체중추가의확실한개선이없었다.2026년1000m는약0.040초악화했고그차이의BH근거가남았다.바로다음관측출전으로한정한후속도체중추가개선은없었다.체중만추가한C도안정적인개선이없었다.**이번에시험한선형체중요약이최근기록이상의추가정보를제공했다고할수없다.** 모든체중표현·비선형모형·당일관측까지무용하다고확정한것은아니다.

## 미리 관측할 수 있는 다른 보유 자료

| 자료 | 만들 수 있는 후보 | 현재 해석과 제한 |
|---|---|---|
| 최근 기록 | 자기 과거 수준 대비 최근1~5회 편차·추세·변동성 | 이번 연구에서 후속 기록 신호를 확인.능력·주로·전개가 섞인 경기력 대용치 |
| 과거 체중 | 해당 시점 이전 체중 범위·최근 증감·변동성·측정 경과일 | 이번 표현의 추가 개선은 미확인.체중 증가·감소만으로 좋고 나쁨을 판정하지 않음 |
| 일별 조교 | 최근 관측 일수·유효 시간과 자기 이전 수준의 변화 | 검증된 시간 단위는 있음.긴 시간이 좋은 컨디션이거나 강한 훈련이라는 뜻은 아님.추가 예측력 미검증 |
| 진료 원문 | 과거 사건 날짜·검토된 진료 문구·시간 경과 | 자료 없는 말은 건강함이 아니라 미관측.처치·예방·검사를 질병으로 자동 분류하지 않음.회복·중증도 추정 안 함 |
| 출발조교 평가 | 원문에 관측된 진입·출발자세 관련 문구 | 일반 체력 평가가 아닌 별도 사건.반복 원행과결측을유지.이번추가효과미검증 |
| 출전 간격 | 최근 휴양 간격·이력의 오래됨 | 다음 기록 설명에 사용.긴 휴양을 무조건 회복 또는 악화로 판정하지 않음 |

일별조교와진료는공식ID로읽기전용집계했다.52,155출전모집단에서경주일전28일부터T−2까지원문이관측된출전비율은다음과같다.사건날짜가이전이라는뜻이며당시공개까지입증한가용비율은아니다.

'''+tab(['자료','경주 연도','원문 관측 출전 / 전체','비율'],covrows)+'''
일별조교는대상말2,813두에과거원문이있고,이모집단출전은모두해당창에최소1행이있었다.2017년이전도포함한대상말원문706,222행중시간미제공394행은NULL로유지한다.일별조교의run1/run2전기간0은실제횟수정보가아니므로사용하지않는다.

진료는대상말786두에11,571원행이연결됐다.2026년최근창관측비율18.2%를질병발생률이나나머지말의건강률로해석하지않는다.기록누락과제공범위의시기차이가크고원행은방문횟수의정답도아니다.조교·진료·출발조교의추가예측력은이번연구에서학습하지않았다.날짜뿐인사건의게시시점미확정과미검증문구·중복정책은기존입력계약을유지한다.

## 사용자에게 보여줄 상태 정보

현재는‘컨디션좋음80%’같은확정점수보다**최근경기력상승·유지·하락신호,이력수,마지막관측일,체중관측범위,자료부족표시**를함께제공할수있다.평소기록은해당시점이전이력으로정하고거리·조건의차이를설명해야한다.이번0.5초군경계는연구용이므로서비스판정기준으로자동채택하지않는다.

T−2평가에서알수있는체중은직전관측체중이며현재마체중의정답이아니다.당일체중을공개후별도갱신하는것은현재연구와별도입력시점으로평가해야한다.생리적컨디션·진료상태의직접확인은이대용지표로대체하지않는다.연구상최근기록은유용한후속정보이지만운영모형에새피처·점수·보정초를반영하지않았다.

## 저장과 검증

[계획](PLAN.json),[분석코드](analyze.py),[특징값](features.csv),[모든이력ID](feature_lineage.json),[동결예측](predictions.csv),[모형계수](models.json),[전체효과](paired_improvements.csv),[신호군비교](persistence_contrasts.csv),[바로다음출전비교](immediate_next_observed_persistence.csv),[과거사건관측범위](candidate_event_date_coverage.csv),[원천해시](source_manifest.json),[검증](verification.json),[별도계산검증](calculation_verification.json)을보존했다.48개모형의전처리·예측을재구성하고8개모형의가중Ridge계수를별도선형방정식으로검산했다.모든오차·군집구간·BH와이력시점을확인했다.즉시후속확인코드의최초인덱스정렬충돌은결과추정전발생했고기존코드를보존한[수정본](check_adjacency_v2.py)으로행인덱스만초기화했다.[재시도이력](adjacency_retry_provenance.json)을남겼다.

날짜군집과말군집공분산을교집합차감없이합산한보수적점별구간을사용했다.공통경주변동·이력의관측선택·과거정정·특정선형모형의제한이남는다.최근상태군의차이는인과효과·건강판정·개별지속확률·완전한순수기록보정정답이아니다.기존DB와과거연구·운영등록부를변경하지않았다.
'''
new('README.md',report)
decision={'recent_performance_followup_signal_observed':True,'physiological_condition_identified':False,'individual_health_diagnosis_or_condition_probability_validated':False,'main_absolute_MAE_improvement_recent_vs_older_2024_2025_BH_distances':[1000,1110,1200],'main_relative_MAE_improvement_recent_vs_older_2024_2025_BH_distances':[800,1110],'main_relative_MAE_improvement_recent_vs_older_2026_BH_distances':[],'body_addition_MAE_improvement_BH_distances':[],'body_addition_2026_1000_MAE_worsened':True,'immediate_observed_next_start_rows':4960,'immediate_observed_fast_vs_slow_signal_BH_2024_2025_distances':[800,1000,1110,1200],'immediate_observed_fast_vs_slow_signal_BH_2026_distances':[1000,1110,1200],'persistence_duration_or_decay_confirmed':False,'training_medical_predictive_value_tested':False,'condition_score_adopted':False,'operational_change':False,'independent_holdout':False};write(H/'decision.json',decision)
topic='''# 제주 최근 경기력 상태와 후속 기록

최근 기록은 후속 기록에 이어지는 경기력 신호를 포함하지만 생리적 컨디션을 직접 판정한 값은 아니다.과거 체중을 최근 기록에 추가한 이번 선형 요약은 안정적인 추가 개선을 보이지 않았다.기록 환산과 운영 예측 개선을 별도 목표로 유지한다.

2017~2026-09-19 원천52,155출전에서T−2 이력5회 이상과경주 내3두 이상을요구했다.2024·2025·2026년을전년도까지학습한7,709출전·1,273경주로비교했다.같은과거자료의후향개발분석이며독립미래검증이나HY_R_FORM운영모형비교가아니다.당일체중·기록·함수율·부담중량·게이트를사전입력에넣지않았다.

## 최근 기록의 후속 정보

오래된동일거리기록기준A에최근1~5회기록·추세를추가한B는2024~2025년1000mMAE1.396→1.273초(감소0.124,점별95%0.071~0.176),1110m1.780→1.560초(0.220,0.143~0.297),1200m1.982→1.885초(0.096,0.010~0.182)였다.2024년만은불확실하고2025년개선이더컸다.최근기록을이미잘사용하는모형의추가개선이라는뜻은아니다.

경주공통시간을평가에서제거하면2024~2025년1000m개선0.032초는불확실,1110m0.045초는BH근거가남았다.2026년의1000·1110m절대개선약0.55초에비해상대개선은0.008·0.010초로불확실하다.절대오차감소를개별말컨디션파악정확도로등치하지않는다.

보유결과상직전출전과동일거리이력이같고7~60일인4,960출전의동결예측후속에서최근빠른군−느린군의다음상대오차차이는2024~2025년1000m−0.687초(−0.894~−0.480),1110m−0.612초(−0.809~−0.416),1200m−0.780초(−1.078~−0.481)였고BH근거가남았다.2026년같은거리들도방향근거가남았다.군경계±0.5초는연구용이고상태의원인·개별확률·지속기간은미확정이다.

## 체중과 다른 사전 후보

최근기록에과거최대6회체중수준·편차·증감·경과일을추가해도2024~2025년지원거리의확실한개선은없고2026년1000mMAE는약0.040초악화했다.모든체중표현이나당일체중의무용함을확정한결과는아니다.[앞선체중증감·적정체중](04_WEIGHT_SPEED.md)도유지한다.

일별조교는52,155출전모집단에서경주전28일부터T−2창에모두최소1원행이관측됐다.진료원문같은창비율은2024년9.4%,2025년13.4%,2026부분18.2%다.관측부재는건강함·미훈련이아니고사건날짜는공개시각증명이아니다.조교시간은유효단위만사용하고0횟수·시간미제공·미검토진료문구·출발조교반복원행정책을지킨다.이자료들의추가예측력은이번에미검증이다.

최근경기력의방향·이력수·관측경과일·체중범위를설명정보로제시할수있지만확정컨디션점수나고정체중감점을채택하지않았다.[상세연구와전체표](../20261008_recent_form_persistence_v1/README.md),[최종판정](../20261008_recent_form_persistence_v1/decision.json)을따른다.
'''
(C/'05_RECENT_FORM.md').write_text(topic,encoding='utf-8')
p0=C/'README.md';txt=p0.read_text();marker='| [원 연구와 버전 목록]';assert marker in txt;txt=txt.replace(marker,'| [최근 경기력 상태와 후속 기록](05_RECENT_FORM.md) | 최근기록의후속신호관찰.체중추가개선미확인.생리적컨디션·개별확률미검증 | 시간순서비교완료,운영미반영 |\n'+marker,1);txt=txt.replace('마체중과 부담중량 연구다.','마체중과 부담중량·최근 경기력 상태 연구다.');p0.write_text(txt,encoding='utf-8')
p0=C/'SOURCES.md';txt=p0.read_text();marker='\n같은 출전 자료가 여러 버전에';assert marker in txt;txt=txt.replace(marker,'\n| [20261008_recent_form_persistence_v1](../20261008_recent_form_persistence_v1/README.md) | 최근경기력의후속기록신호·체중추가·T−2후향비교와조교진료관측범위.7,709평가출전·4,960즉시후속부분집합.컨디션진단·운영채택아님 |\n'+marker,1);p0.write_text(txt,encoding='utf-8')
p0=C/'research_register.json';reg=json.loads(p0.read_text());assert not any(z['id']=='recent_form' for z in reg['topics']);reg['topics'].append({'id':'recent_form','title':'최근 경기력 상태와 후속 기록','conclusion':'05_RECENT_FORM.md','latest_source':'../'+H.name+'/README.md','period_start':'2017-01-01','period_end':'2026-09-19','evaluation_years':[2024,2025,2026],'evaluation_rows':7709,'evaluation_races':1273,'immediate_observed_subset_rows':4960,'status':'retrospective_time_ordered_followup_comparison_completed_no_condition_score_adopted','operationally_applied':False,'decision':decision});write(p0,reg)
links=0
for path in [H/'README.md',C/'05_RECENT_FORM.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if '://' not in target:assert (path.parent/target.split('#')[0]).exists(),(path,target);links+=1
write(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'database_unchanged':True,'all_prior_research_unchanged':True,'management_previous_hashes':before,'management_current_files':[{'path':key,'sha256':sha(ROOT/key),'bytes':(ROOT/key).stat().st_size} for key in before],'new_topic':'05_RECENT_FORM.md','no_operational_changes':True})
art=[{'path':path.name,'sha256':sha(path),'bytes':path.stat().st_size} for path in sorted(H.iterdir()) if path.is_file() and path.name!='artifact_manifest.json'];write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(z['bytes'] for z in art),'links_checked':links})
files={z['path']:z for z in central['files']}
for key,z in files.items():
    if z['role']=='conclusion_or_management':z.update(sha256=sha(ROOT/key),bytes=(ROOT/key).stat().st_size)
path=C/'05_RECENT_FORM.md';key=str(path.relative_to(ROOT));files[key]={'path':key,'role':'conclusion_or_management','sha256':sha(path),'bytes':path.stat().st_size}
for path in sorted(H.iterdir()):
    if not path.is_file() or path.name=='publish_run.log':continue
    key=str(path.relative_to(ROOT));assert key not in files;files[key]={'path':key,'role':'source_recent_form_persistence','sha256':sha(path),'bytes':path.stat().st_size}
central['files']=list(files.values());central['verification'].update(recent_form_persistence_completed=True,condition_score_adopted=False,local_links_checked=links);central['managed_files_bytes_excluding_this_manifest']=sum(z['bytes'] for z in files.values() if z['role']=='conclusion_or_management');write(C/'source_manifest.json',central)
assert all(sha(ROOT/z['path'])==z['sha256'] for z in central['files']);assert sha(a.a.old.DB)==audit['database_sha256']
print(json.dumps({'saved_report':str(H/'README.md'),'models_verified':len(models),'independent_coefficient_checks':len(independent),'history_endpoints_verified':historychecked,'files':len(art)+1,'bytes_excluding_artifact_manifest':sum(z['bytes'] for z in art),'links_checked':links,'all_central_hashes_passed':True,'decision':decision},ensure_ascii=False,indent=2))
