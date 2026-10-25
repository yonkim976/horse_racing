"""Independent calculation checks, report, and immutable research publication."""
from pathlib import Path
import importlib.util
import json
import re
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
sp=importlib.util.spec_from_file_location('body_study',H/'analyze.py');s=importlib.util.module_from_spec(sp);sp.loader.exec_module(s)
a=s.a;sha=s.sha
def write(p,v):p.write_text(json.dumps(s.clean(v),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def new(name,text):
    with (H/name).open('x',encoding='utf-8') as z:z.write(text)
def tab(head,rows):return '\n'.join(['| '+' | '.join(head)+' |','|'+'|'.join(['---']*len(head))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'
def num(z):return f'{z:+.3f}'.replace('-','−')
def ci(r):return f'{num(r.ci_lo)}~{num(r.ci_hi)}'
central=json.loads((C/'source_manifest.json').read_text());assert all(sha(ROOT/z['path'])==z['sha256'] for z in central['files']);before={z['path']:z['sha256'] for z in central['files'] if z['role']=='conclusion_or_management'}
models=json.loads((H/'models.json').read_text());effects=pd.read_csv(H/'effects.csv');curves=pd.read_csv(H/'body_curves.csv');sex=pd.read_csv(H/'sex_differences.csv');raw=pd.read_csv(H/'body_by_distance_sex.csv');ind=pd.read_csv(H/'individual_period_comparison.csv',dtype={'horse_id':str});audit=json.loads((H/'input_audit.json').read_text());inds=json.loads((H/'individual_summary.json').read_text())
pairs=pd.read_csv(a.H/'pair_lineage.csv',dtype={'horse_id':str},low_memory=False);pairs['gain10']=pairs.body_change_kg.clip(lower=0)/10;pairs['loss10']=-pairs.body_change_kg.clip(upper=0)/10;pairs['previous_body10']=(pairs.previous_body_kg-278)/10;pairs['previous_body2']=pairs.previous_body10**2
d,h=a.old.load();q=a.old.all_features(d,h).reset_index(drop=True);lineage=pd.read_csv(a.H/'source_lineage.csv',dtype={'horse_id':str},low_memory=False);q=q.merge(lineage[['api_record_id','body_kg']],on='api_record_id',validate='one_to_one');q['body10']=(q.body_kg-278)/10;q['body2']=q.body10**2;q['burden']=q.carried_weight_kg-55;q['time']=q.finish_time_seconds
q['prior_finish_fraction']=[(d.loc[h[str(rid)][-1],'finish_position']-1)/(d.loc[h[str(rid)][-1],'field_n']-1) if h[str(rid)] else np.nan for rid in q.api_record_id]
def design(g,m):
    st=m['design'];v={}
    for name,mean,sd in zip(st['nuisance_columns'],st['nuisance_means'],st['nuisance_sd']):
        if name.endswith('_missing'):z=g[name[:-8]].isna().to_numpy(float)
        elif name not in st['nuisance_medians'] and '=' in name:
            key,level=name.split('=',1);z=g[key].astype(str).eq(level).to_numpy(float)
        else:z=pd.to_numeric(g[name],errors='coerce').fillna(st['nuisance_medians'][name]).to_numpy(float)
        v[name]=(z-mean)/sd
    return np.column_stack([np.ones(len(g)) if name=='intercept' else v[name] if name in v else g[name].to_numpy(float) for name in m['columns']])
checks=[]
for item in models:
    if item['family'] not in ['row','pair'] or item['period']!='full' or item['variant'] not in ['primary','absolute'] or item['distance'] not in [1000,1110] or item['model']['target']!='time_s':continue
    m=item['model'];isrow=item['family']=='row';g=q[q.race_distance_m.eq(item['distance'])] if isrow else pairs[pairs.distance.eq(item['distance'])];x=design(g,m);y=g.time.to_numpy() if isrow else g.time_delta.to_numpy()
    if isrow:
        z,lu,_=a.prior.fe_matrix(g);xr=x-z@lu.solve(np.asarray(z.T@x));yr=y-z@lu.solve(np.asarray(z.T@y));pen=np.r_[np.zeros(2),np.ones(x.shape[1]-2)]
    else:xr=x;yr=y;pen=np.r_[np.zeros(3),np.ones(x.shape[1]-3)]
    bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@(xr.T@yr);err=float(np.max(np.abs(beta-np.array(m['beta']))));assert err<1e-8
    residual=yr-xr@beta;cov_errors=[]
    for ids,key in [(g.race_date,'date_cov'),(g.horse_id,'horse_cov')]:
        levels,codes=np.unique(ids,return_inverse=True);scores=np.zeros((len(levels),x.shape[1]));np.add.at(scores,codes,xr*residual[:,None]);cov=bread@(scores.T@scores)@bread*len(levels)/(len(levels)-1)*(len(g)-1)/m['residual_df'];cov_errors.append(float(np.max(np.abs(cov-np.array(m[key])))));assert cov_errors[-1]<1e-8
    checks.append({'family':item['family'],'distance':item['distance'],'beta_max_error':err,'cov_max_error':max(cov_errors)})
assert len(checks)==4
for df,keys in [(effects,['family','period','variant','sex','exposure']),(curves,['period','variant','sex']),(sex,['family','period','contrast'])]:
    for _,g in df.groupby(keys,dropna=False):assert np.allclose(a.old.bh(g.p.to_numpy()),g.q_BH)
assert np.allclose(pairs.gain10-pairs.loss10,pairs.body_change_kg/10)
assert not curves.candidate_supported.any()
sample=curves[curves.period.eq('full')&curves.variant.eq('absolute')&curves.target.eq('time_s')]
for r in sample[sample.quadratic.gt(0)].itertuples():assert np.isclose(r.vertex_kg_or_deviation,278-10*r.linear/(2*r.quadratic))
histchecked=0
for r in q[['api_record_id','horse_id','race_distance_m','history_cutoff']].itertuples():
    ids=h[str(r.api_record_id)]
    if ids:
        z=d.loc[ids];assert z.horse_id.eq(r.horse_id).all() and z.race_distance_m.eq(r.race_distance_m).all() and z.race_date.le(r.history_cutoff).all();histchecked+=len(ids)
assert set(q.api_record_id)==set(lineage.api_record_id)
assert not q.horse_id.eq('3005648').any()
con=sqlite3.connect(a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');profiles=[]
for hid in ind[ind.candidate_past].horse_id:
    row=con.execute('SELECT horse_id,horse_name_raw,api_record_id,payload_sha256 FROM horse_profile_latest WHERE horse_id=?',(hid,)).fetchone();profiles.append(dict(zip(['horse_id','current_horse_name','profile_api_record_id','profile_payload_sha256'],row)))
con.close();s.csv('candidate_current_profile_names.csv',pd.DataFrame(profiles));names={z['horse_id']:z['current_horse_name'] for z in profiles}
res=pd.read_csv(H/'individual_adjusted_residuals.csv',dtype={'horse_id':str});available=[]
for r in ind.itertuples():
    later=res[res.period.eq('later')&res.horse_id.eq(r.horse_id)&res.race_distance_m.eq(r.distance)]
    available.append({'horse_id':r.horse_id,'distance':r.distance,'past_candidate':r.candidate_past,'later_starts':len(later),'later_distinct_body':later.body_kg.nunique()})
s.csv('individual_later_availability.csv',pd.DataFrame(available))
write(H/'calculation_verification.json',{'status':'passed','independent_coefficients_and_numpy_cluster_covariances':checks,'all_BH_families_recomputed':True,'positive_gain_and_positive_loss_units_verified':True,'quadratic_vertices_verified':True,'T_minus_2_history_endpoints_checked':histchecked,'official_ID_source_population_matches':True,'excluded_horse_absent':True,'database_sha256':sha(a.old.DB),'all_source_hashes_unchanged':True})

# Plot observed-change coefficients rather than unstable extrapolated vertices.
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(11,4.7),sharey=True)
for ax,exposure,label,color in zip(axes,['gain10','loss10'],['10 kg gain','10 kg loss'],['#bb5b32','#287e8b']):
    z=effects[effects.family.eq('pair')&effects.period.eq('full')&effects.variant.eq('primary')&effects.target.eq('time_s')&effects.exposure.eq(exposure)].sort_values('distance');yy=np.arange(len(z));ax.errorbar(z.effect,yy,xerr=np.vstack([z.effect-z.ci_lo,z.ci_hi-z.effect]),fmt='o',color=color,capsize=3);ax.axvline(0,color='#666',lw=1);ax.set_title(label);ax.set_xlabel('Adjusted time change (seconds; + = slower)');ax.set_yticks(yy,[f'{int(v)} m  (n={int(n):,})' for v,n in zip(z.distance,z.rows)]);ax.grid(axis='x',alpha=.2)
axes[0].invert_yaxis();fig.suptitle('Jeju body-mass change associations, 2017-2026 partial',fontsize=13);fig.text(.5,.012,'Same horse / exact distance / grade / year, 7-60 days. Pointwise 95% intervals; observational associations.',ha='center',fontsize=9);fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(H/'body_change_associations.png',dpi=180);fig.savefig(H/'body_change_associations.pdf');plt.close(fig)

primary=effects[effects.family.eq('pair')&effects.period.eq('full')&effects.variant.eq('primary')&effects.target.eq('time_s')]
rows=[]
for dist in [800,900,1000,1110,1200,1300,1400]:
    g=primary[primary.distance.eq(dist)].set_index('exposure');gain=g.loc['gain10'];loss=g.loc['loss10'];rows.append([f'{dist}m',f'{int(gain.rows):,}',f'{num(gain.effect)} ({ci(gain)})',f'{num(loss.effect)} ({ci(loss)})'])
sxrows=[]
for dist,g in raw[raw.race_distance_m.isin([800,900,1000,1110,1200,1300,1400,1610])].groupby('race_distance_m'):
    vals=g.set_index('sex');sxrows.append([f'{int(dist)}m']+[f'{vals.loc[sx,"mean_body_kg"]:.1f} / {int(vals.loc[sx,"starts"]):,}' for sx in ['암','수','거']])
candidate_rows=[]
for r in ind[ind.candidate_past].itertuples():
    n=next(z['later_starts'] for z in available if z['horse_id']==r.horse_id and z['distance']==r.distance)
    candidate_rows.append([f'{names[r.horse_id]} ({r.horse_id})',f'{r.distance}m',int(r.starts_past),f'{r.body_min_past:.0f}~{r.body_max_past:.0f}',f'{r.vertex_kg_past:.1f}',f'{n}회: 반복 확인 불가'])
sexrows=[]
for r in sex[sex.family.eq('pair')&sex.target.eq('time_s')].itertuples():sexrows.append([f'{r.distance}m','10kg 증가' if r.contrast.endswith('gain10') else '10kg 감소',num(r.effect),ci(r),f'{r.q_BH:.3f}'])
within=curves[curves.period.eq('full')&curves.variant.eq('within_median')&curves.target.eq('time_s')&curves.distance.isin([800,900,1000,1110,1200])]
wrows=[[f'{r.distance}m',f'{r.vertex_kg_or_deviation:+.1f}kg',f'{r.vertex_ci_lo:+.1f}~{r.vertex_ci_hi:+.1f}kg',f'{r.q_BH:.5f}'] for r in within.itertuples()]
report='''# 제주 마체중 증감과 말별 및 거리별 적정 체중 연구

**마체중과 기록의 연관성은 관찰되지만, 모든 말에 적용할 적정 체중이나 암수·거리별 고정 최적 kg은 확인하지 못했다.** 전체 출전 비교에서는 같은 말의 체중이 높은 때 기록이 느린 연관성이 있었고, 가까운 두 출전을 비교하면 800~1000m의 체중 감소가 빠른 기록과 연관됐다. 최근 기간·안정 조건에서는 불확실성이 커졌다. 체중 감소를 권장하거나 체중만으로 기록을 확정 보정하는 결과가 아니다.

2017-01-01~2026-09-19, 정상 완전순위 5,206경주·52,155출전·2,813두다. 2026년은 부분연도이며 7~13두 편성이다. 현재 거리 800·900·1000·1110·1200·1300·1400·1610m를 모두 확인하고 400m는 제외했다. 기존 과거 자료의 후향 개발 분석이며 독립 미래 검증이 아니다.

## 체중 증감과 기록 변화

동일 말·정확 거리·원문 등급·연도, 7~60일 간격의 27,230쌍에서 실제 측정 체중 차이를 계산했다. 증가는 양의 gain, 감소는 양의 loss로 따로 모형화했다. 부담중량 및 증감, 이전 체중, 이전 기록·착순·이력, 간격, 경주 당시 나이, 함수율 구간, 월의 연속 계절 주기, 게이트 등을 고려했다. 여기서 연속은 연구 조건을 만족한 동일 거리 출전 사이이며 모든 경력의 바로 다음 출전을 뜻하지 않는다.

아래 단위는 **10kg 변화와 연관된 시간 차이, 초**다. 양수는 느림, 음수는 빠름이다. 두 열 모두 체중 변동이 0인 경우와 비교한 회귀 기울기이며 실제 모든 10kg 사례를 단순 평균한 값은 아니다. 괄호는 점별 95% 구간이다.

'''+tab(['거리','출전 쌍','10kg 증가','10kg 감소'],rows)+'''
800m 증가는 +0.396초, 감소는 −0.381초였고, 900m 감소 −0.377초, 1000m 감소 −0.348초에서 거리·두 시간 목표에 대한 BH 근거가 남았다. 900m 증가의 점별 구간은 양수지만 BH q=0.114로 충족하지 않았다. 1110m 이상은 두 방향 모두 불확실했다. 1610m는 5쌍·9경주뿐이어서 효과를 추정하지 않았다.

2024~2025년과 2026년 부분기간의 증가·감소 기울기는 어느 지원 거리에서도 BH를 충족하지 못했다. 예를 들어 1000m 감소는 2024~2025년 −0.184초(−0.670~+0.301), 2026년 −0.433초(−0.976~+0.110)다. 같은 달·같은 함수율 구간·부담중량 변화 1kg 이내로 제한한 1000m 558쌍, 1110m 308쌍도 불확실했다. 직전 성적 통제를 빼면 감소 효과가 더 크게 나와 회귀 평균과 상태 변화의 영향을 보여준다. [기간·민감도 전체 표](effects.csv)를 따른다.

![체중 증감과 기록의 관찰 연관](body_change_associations.png)

별도의 전체 출전 경주·말 고정효과 모형에서 280→290kg와 연관된 시간은 1000m +0.259초(95% +0.191~+0.326), 1110m +0.260초(+0.184~+0.335)였다. 이는 동일 말의 체중 수준 차이에 대한 후향 비교이며, 위 가까운 두 출전의 증감 효과와 추정 대상이 다르다. 체중 증가가 모두 지방 증가이거나 감소가 모두 건강한 감량이라는 근거는 없다.

## 말마다 적정 체중이 있는가

다른 말끼리 큰 말과 작은 말을 비교하지 않고, 말·경주 효과와 부담중량·과거 성적·나이 등을 고려한 뒤 체중 곡선을 확인했다. 거리별 절대 kg 곡선은 어느 거리에서도 신뢰할 수 있는 내부 최저점을 확인하지 못했다. 곡선의 최저점을 무리하게 계산하면 표본이 드문 영역이나 비현실적 체중으로 외삽되는 경우가 있어 최적 kg으로 공개하지 않는다.

각 말의 전체 기간 중앙 체중에서 얼마나 벗어났는지를 사용한 민감도에서는 800~1200m에 U자형 곡률 신호가 있었다. 수학적 최저점 후보는 중앙 체중보다 약 6~10kg 낮은 쪽이었다. 그러나 구간이 넓고 대부분 표본의 주요 범위 하단에 걸려 **중앙 체중−10kg을 적정 체중으로 채택할 근거는 부족하다.** 중앙값도 미래를 포함한 전체 기간의 후향 기준이므로 사전 입력으로 쓸 수 없다.

'''+tab(['거리','전체 기간 중앙 체중 대비 최저점 후보','모수 정규근사 95% 구간','곡률 BH q'],wrows)+'''
위 구간은 양의 곡률을 가진 모수 추출에 조건부로 계산했다. 곡률이 음수인 경우까지 안정적인 최저점이 존재한다는 의미가 아니며, [곡선 전체 표](body_curves.csv)의 양의 곡률 추출 비율과 실제 체중 지원 범위를 함께 확인한다. 전체 및 민감도 모두 사전 고정한 최저점 지원 조건을 충족한 거리는 0개였다.

말별로는 2017~2023년 동일 거리 30회 이상·서로 다른 체중 8개 이상·체중 폭 20kg 이상인 51개 말×거리 조합을 선별했다. 각 기간에 따로 추정한 체중 제외 전역 모형의 잔차에 개별 곡선을 적합했다. 다중 비교와 내부 최저점·양쪽 표본을 확인하니 과거 후보 2건이 남았다.

'''+tab(['현재 프로필명과 공식 ID','거리','과거 출전','관측 체중 kg','과거 최저점 후보 kg','2024~2026 해당 거리 지원'],candidate_rows)+'''
이는 확정 적정 체중이 아니라 후향 탐색 후보다. 두 후보의 이후 출전은 각각 2회·0회로 반복 확인 기준 15회에 부족했다. 전체 51개 중 이후에도 최소 반복 비교 조건을 만족한 조합은 2개지만 이들은 과거 후보가 아니었다. 따라서 ‘후보가 이후에 실패했다’고 말할 수 없고 **이후 확인이 가능한 적정 체중을 확보하지 못했다**고 해석한다. 개인별 HC1 구간은 전역 잔차 추정의 불확실성을 전부 전파하지 않은 탐색용이며, 생존·은퇴 선택과 적은 반복 수를 고려해야 한다. 새 개체별 최적값은 채택하지 않았다.

## 암수와 거세마 비교

경주 당시 성별을 사용하고 거세마를 수말에 합치지 않았다. 암·수/거 이력 충돌 말은 이번 분석 모집단에 0두였고, 두 출전의 성별이 바뀐 4쌍은 성별 기울기 비교에서 제외했다. 최신 프로필 성별을 과거에 소급하지 않았다.

아래는 **평균 체중 kg / 출전 수**이며 적정 체중이 아니다.

'''+tab(['거리','암말','수말','거세마'],sxrows)+'''
같은 공동 모형에서 암말−수말의 증감 반응을 직접 비교했다. 800m 암말의 10kg 증가 기울기 +0.549초는 개별 성별의 BH 근거가 남았지만, 수말 대비 차이 +0.381초(95% −0.250~+1.012)는 불확실했다. 한 성별에서만 유의하다는 이유로 성별 차이가 유의하다고 해석하지 않는다.

'''+tab(['거리','비교 변화','암말−수말 시간 반응 차이 초','95% 구간','BH q'],sexrows)+'''
800~1200m에서 암말−수말 체중 곡선의 공동 차이도 BH q가 모두 0.958 수준으로 불확실했다. **암말의 체중 변화에 더 큰 고정 감점을 주거나 암수별 최적 kg을 정할 근거는 확보하지 못했다.** 이는 성별 반응이 같다는 동등성 증명이 아니다. 1300·1400m 암말은 각각 53·59출전이라 성별 공동 효과를 추정하지 않았고, 1610m 암말은 1출전이다.

## 거리별 적정 체중과 적용

긴 거리 출전마의 평균 체중은 상대적으로 높았다. 그러나 다른 말·나이·등급·경력의 거리 선택이 섞이므로 ‘긴 거리에는 무거울수록 좋다’고 해석할 수 없다. 같은 말과 경주 조건을 고려한 곡선, 최근 기간, 개별 말 반복 확인을 종합하면 **800~1610m에서 확정된 공통 적정 체중은 없다.** 1300·1400m는 소표본, 1610m는 효과 추정 불가로 제한한다.

현재 기록 보정에는 ‘증가 10kg당 몇 초’, ‘평균 체중−10kg’, ‘거리별 최적 kg’을 고정 적용하지 않는다. 사용자에게 실제 체중·측정 시점·최근 증감·해당 말의 과거 관측 범위와 표본 수를 보여줄 수 있다. 향후 입력 후보는 T−2까지 관측한 최근 체중 중앙값 대비 편차와 증감률이며, 전체 기간 중앙값이나 당일 사후 체중을 사전 입력에 넣지 않는다. 예측 개선은 이번 관찰 연구로 검증하지 않았다.

## 원천과 검증

마체중 괄호의 증감은 직전 동일 거리 증감으로 쓰지 않았다. DB의 보유 경주 결과 연대기와 비교 가능한 45,029행 중 44,460행(98.7%)이 일치했고, 569행은 이전 관측의 누락·심사 등 다른 사건 가능성 때문에 오류로 확정하지 않았다. 괄호 증감 수치 미제공 5,118행도 체중 자체가 결측인 것은 아니다. 원시 값과 실제 두 출전의 측정 체중을 구분한 [감사](reported_change_chronology_audit.csv)를 보존했다.

177개 결과 모형과 원천 ID·해시를 보존했다. 경주·말 고정효과의 공동 방정식과 투영 결과 최대 차이는 2.98×10⁻⁸ 이하였다. 1000·1110m의 출전 및 증감 계수·날짜/말 공분산을 별도 NumPy로 재검산하고 BH·체중 단위·최저점 산술·T−2 이력을 확인했다. 날짜+말 공분산을 합산한 보수적 구간이지만 쌍의 앞 출전일만 공유하는 서로 다른 말의 상관은 완전히 반영하지 못한다. 정규근사 최저점 구간은 점별 탐색 값이다.

현재 경주 체중은 사후 설명 측정이며 T−2 가용성을 가정하지 않았다. 사건 나이는 성장·노화 통제에 사용한 경주 원문 나이이고 2026년 고정 프로필 나이가 아니다. 성장·영양·질병·훈련·출전 선택·시변 능력·측정 오차의 잔여 교란이 남는다. 순수 생리적 최적 체중과 인과효과는 확인할 수 없다.

[계획](PLAN.json), [분석 코드](analyze.py), [별도 검산과 발행 코드](verify_publish.py), [전체 효과](effects.csv), [곡선](body_curves.csv), [성별 직접 비교](sex_differences.csv), [말별 전체 결과](individual_curve_results.csv), [말별 기간 비교](individual_period_comparison.csv), [출전 지원](model_support.csv), [원천 해시](source_manifest.json), [원천 감사](input_audit.json), [검증](verification.json), [별도 계산 검증](calculation_verification.json)을 연결한다. 최초 v1은 NumPy의 제거된 row_stack 별칭 때문에 최종 효과표 작성 전에 중단됐고, v2는 동일한 vstack 치환만 적용했다. [재실행 이력](RETRY_PROVENANCE.json)을 보존했다. 기존 연구·DB·운영 모델을 변경하지 않았다.
'''
new('README.md',report)
decision={'body_change_association_observed':True,'primary_full_gain_BH_distances':[800],'primary_full_loss_BH_distances':[800,900,1000],'recent_pair_BH_distances':[],'supported_absolute_distance_optima':0,'within_horse_median_curvature_signal_distances':[800,900,1000,1110,1200],'supported_within_median_optima':0,'individual_eligible_cells':51,'individual_past_candidates':2,'individual_past_candidates_later_supported':0,'individual_repeated_candidates':0,'female_minus_male_response_difference_confirmed':False,'sex_equivalence_proven':False,'fixed_body_correction_adopted':False,'individual_optimum_adopted':False,'distance_optimum_adopted':False,'operational_change':False,'retrospective_development':True};write(H/'decision.json',decision)
for z in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(z['path']))==z['sha256']
assert sha(a.old.DB)==audit['database_sha256']
write(H/'prepublication_verification.json',{'status':'passed','database_unchanged':True,'sources_unchanged':True,'central_before_hashes':before,'new_report_saved':True,'visual_inspection_pending':True})
print(json.dumps({'report':str(H/'README.md'),'independent_checks':checks,'individual':inds,'decision':decision},ensure_ascii=False,indent=2))
