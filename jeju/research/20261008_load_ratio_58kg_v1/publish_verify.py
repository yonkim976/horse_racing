"""Verify additional size modifiers and publish the conditional 58kg interpretation."""
from pathlib import Path
import importlib.util
import json
import hashlib
import re
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
sp=importlib.util.spec_from_file_location('conditional_study',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(path,v):path.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def new(name,v):
    with (H/name).open('x',encoding='utf-8') as f:f.write(v)
def f(v):return f'{v:+.3f}'.replace('-','−')
def table(head,rows):return '\n'.join(['| '+' | '.join(head)+' |','|'+'|'.join(['---']*len(head))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'
central=json.loads((C/'source_manifest.json').read_text());assert all(sha(ROOT/i['path'])==i['sha256'] for i in central['files'])
previous={i['path']:i['sha256'] for i in central['files'] if i['role']=='conclusion_or_management'}
source=pd.read_csv(a.PRE/'source_lineage.csv',dtype={'horse_id':str});z58=source[source.carried_weight_kg.eq(58)]
observed=pd.read_csv(H/'exact58_source_lineage.csv',dtype={'horse_id':str});assert np.array_equal(z58.api_record_id,observed.api_record_id)
raw=pd.read_csv(H/'exact58_body_groups.csv');assert raw.starts.sum()==2773 and len(observed)==2773
cost=pd.read_csv(H/'conditional_55_to58_costs.csv');diff=pd.read_csv(H/'small_minus_large_cost.csv');models=json.loads((H/'models.json').read_text())
# Explicitly name the 3kg effect units; preserved intermediate files inherited the older generic inference function's per-kg speed label.
cost=cost.rename(columns={'speed_change_pct_per_kg':'speed_change_pct_for_3kg'})
diff=diff.rename(columns={'speed_change_pct_per_kg':'relative_speed_response_ratio_pct'})
cost['contrast_units']=np.where(cost.target.eq('time_s'),'seconds_for_55_to58kg','100_log_time_change_for_55_to58kg')
diff['contrast_units']=np.where(diff.target.eq('time_s'),'seconds_small_minus_large_for_3kg','100_log_time_response_difference_small_minus_large_for_3kg')
a.csv('conditional_costs_explicit_units.csv',cost);a.csv('small_minus_large_explicit_units.csv',diff)
def bh(p):
    p=np.asarray(p);ix=np.argsort(p);v=p[ix]*len(p)/np.arange(1,len(p)+1);r=np.empty(len(p));r[ix]=np.minimum(1,np.minimum.accumulate(v[::-1])[::-1]);return r
for _,g in diff.groupby(['family','period','variant']):assert np.allclose(bh(g.p),g.q_BH)
pairs=pd.read_csv(a.PRE/'pair_lineage.csv',dtype={'horse_id':str});pairs['mean_body10']=((pairs.body_kg+pairs.previous_body_kg)/2-278)/10;pairs['mean_body_squared']=pairs.mean_body10**2;pairs['increase_by_body']=pairs.increase_kg*pairs.mean_body10;pairs['decrease_by_body']=pairs.decrease_kg*pairs.mean_body10
independent=[]
for item in models:
    if item['family']!='pair' or item['period']!='full' or item['variant']!='primary' or item['model']['target']!='time_s' or item['distance'] not in [1000,1110]:continue
    g=pairs[pairs.distance.eq(item['distance'])];m=item['model'];s=m['design'];values={}
    for col,mean,sd in zip(s['nuisance_columns'],s['nuisance_means'],s['nuisance_sd']):
        if col.endswith('_missing'):v=g[col[:-8]].isna().to_numpy(float)
        elif '=' in col and col not in s['nuisance_medians']:
            key,level=col.split('=',1);v=g[key].astype(str).eq(level).to_numpy(float)
        else:v=pd.to_numeric(g[col],errors='coerce').fillna(s['nuisance_medians'][col]).to_numpy(float)
        values[col]=(v-mean)/sd
    x=np.column_stack([np.ones(len(g)) if col=='intercept' else values[col] if col in values else g[col].to_numpy(float) for col in m['columns']]);pen=np.r_[np.zeros(5),np.ones(x.shape[1]-5)];bread=np.linalg.inv(x.T@x+np.diag(pen));b=bread@(x.T@g.time_delta.to_numpy());assert np.allclose(b,m['beta'],atol=1e-8)
    residual=g.time_delta.to_numpy()-x@b
    for ids,key in [(g.race_date,'date_cov'),(g.horse_id,'horse_cov')]:
        levels,codes=np.unique(ids,return_inverse=True);scores=np.zeros((len(levels),x.shape[1]));np.add.at(scores,codes,x*residual[:,None]);cov=bread@(scores.T@scores)@bread*(len(levels)/(len(levels)-1)*(len(g)-1)/m['residual_df']);assert np.allclose(cov,m[key],atol=1e-8)
    independent.append(item['distance'])
assert independent==[1000,1110]
for r in cost[cost.target.eq('time_s')].itertuples():
    matches=cost[(cost.family==r.family)&cost.period.eq(r.period)&cost.variant.eq(r.variant)&cost.distance.eq(r.distance)&cost.target.eq('time_s')]
    small=matches[matches.body_kg.eq(250)].iloc[0];large=matches[matches.body_kg.eq(300)].iloc[0];d=diff[(diff.family==r.family)&diff.period.eq(r.period)&diff.variant.eq(r.variant)&diff.distance.eq(r.distance)&diff.target.eq('time_s')].iloc[0];assert np.isclose(small.effect-large.effect,d.effect)
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.a.old.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
write(H/'calculation_verification.json',{'status':'passed','all_exact58_source_ids_match':True,'raw_group_count_total':2773,'independent_pair_coefficients_and_numpy_cluster_covariances':independent,'all_time_contrast_arithmetic_and_BH_verified':True,'published_units_are_3kg_cost_and_small_minus_large_response':True,'input_and_database_hashes_unchanged':True})
ratio=pd.read_csv(H/'ratio_examples.csv');rrows=[[int(r.body_kg),'58kg',f'{r.load_pct_body:.2f}%'] for r in ratio.itertuples()]
rows=[]
for distance in [800,900,1000,1110,1200,1300,1400]:
    c=cost[(cost.family=='row')&cost.distance.eq(distance)&cost.target.eq('time_s')];small=c[c.body_kg.eq(250)].iloc[0];large=c[c.body_kg.eq(300)].iloc[0];d=diff[(diff.family=='row')&diff.distance.eq(distance)&diff.target.eq('time_s')].iloc[0]
    rows.append([f'{distance}m',f(small.effect),f(large.effect),f(d.effect),f'{f(d.ci_lo)}~{f(d.ci_hi)}'])
rawrows=[[f'{int(r.race_distance_m)}m',r.body_bin,r.starts,r.horses,f'{r.load_mean_pct:.2f}%',f(r.relative_time_mean_s)] for r in raw[raw.race_distance_m.isin([1000,1110])].itertuples()]
prows=[[r.period,r.variant,f'{r.distance}m',r.rows,f(r.effect),f'{f(r.ci_lo)}~{f(r.ci_hi)}',f'{r.q_BH:.4f}'] for r in diff[(diff.family=='pair')&diff.target.eq('time_s')].itertuples()]
report='''# 同じ58kgの負担と馬体重による記録差

同じ58kgでも馬体重に対する負担率は異なる。'''
# The report is Korean throughout; keep the opening concise and separate arithmetic from measured effects.
report='''# 같은 58kg 부담중량에서 마체중에 따른 차이

**같은 58kg라도 체중 대비 부담 비율은 다르다. 그러나 작은 말의 실제 기록 손실이 얼마나 더 큰지, 또는 두 말의 영향이 같은지는 아직 확정하지 못했다.** 앞선 마체중과 부담중량의 약한 상관은 중량 배정과 체중의 관계이며, 같은 중량을 견디는 능력이 같다는 뜻이 아니다.

2017~2026-09-19 정상 완전순위 5,206경주·52,155출전의 중량 연구를 이어서 분석했다. 정확히 58kg인 출전은2,773건이다. 2026년은 부분연도이며 7~13두 편성을 포함한다. 이는 같은 자료의 후향 후속이며 새 독립 검증이 아니다.

## 체중 대비 부담 비율

'''+table(['마체중','부담중량','부담중량÷마체중'],rrows)+'''
250kg와300kg의 비율은23.20%와19.33%로 약3.87%p 다르다.250kg 말의 상대 비율이20% 높다는 산술적 사실이 감속도20% 크다는 뜻은 아니다.비율은 설명 변수이고 생리적 부담이나 실제 시간 손실의 정답은 아니다.

## 같은 58kg 출전만 보면

아래는 같은 경주 중앙값보다 얼마나 느리거나 빨랐는지의 조정 전 평균이다. 양수는 느린 방향이다. 서로 다른 말의 능력과 등급·나이·경주 선택이 섞여 있으므로 몸집의 인과효과로 읽지 않는다.거리 간 절대 시간을 합치지 않았다.

'''+table(['거리','마체중 구간 kg','출전','말','평균 부담 비율','경주 중앙값 대비 시간 초'],rawrows)+'''
1000m에서는 작은 말과 큰 말의 원시 평균이 단조롭게 나뉘지 않았고,1110m는300kg 이상군이 빠른 방향이었다.그 차이가 체중 대비 부담 때문인지 원래 말의 능력 차이인지는 이 표로 분리할 수 없다.[전체58kg 집계](exact58_body_groups.csv)를 보존했다.

## 55kg에서 58kg로 늘릴 때의 손실이 체중별로 다른가

58kg인 서로 다른 말의 절대 기록 대신,각 몸무게에서55→58kg 증가와 연관된 시간 변화를 비교했다.같은 말·같은 경주 효과와 과거 기록·마체중·나이·게이트 등을 고려한 앞선 상호작용 모형을 사용했다.마체중250kg와300kg을 설명용 지점으로 고정했다.

아래는 **3kg 증가에 대한 조건부 시간 차이, 단위 초**다.각 체중에서55kg 대비58kg의 추정치이며,250kg 말과300kg 말의 완주시간 자체를 비교한 값이 아니다.작은 말−큰 말의 양수는 작은 말의 추가 손실이 큰 방향이다.

'''+table(['거리','250kg에서55→58kg','300kg에서55→58kg','작은 말의 추가 손실','추가 손실95% 구간'],rows)+'''
1000m에서는0.188초 대0.154초,추가 차이+0.034초였으나 구간은−0.072~+0.140초였다.1110m는0.249초 대0.188초,추가 차이+0.061초이고−0.059~+0.182초였다.모든 지원 거리에서 추가 차이 구간이0을 포함하고 BH도 통과하지 못했다.이는 동등성 검정 결과가 아니므로 ‘두 말의 영향이 같다’고 결론내리지 않는다.

250kg·300kg 주변에서55kg와58kg를 모두 관측한 동일말은1000m32두·46두,1110m13두·39두였다.이 수치는±10kg 체중 범위의 장기 관측 중 두 중량이 모두 있는 말이며,즉시55→58kg로 변한 쌍 수가 아니다.[체중과 중량의 실제 지원](example_load_support.csv)을 함께 보존했다.회귀는 이 말들만의 자료가 아니라 전체 지원 자료를 사용한다.

## 같은 말의 연속 출전으로 다시 확인

앞선 동일 말·정확 거리·원문 등급·연도,7~60일 출전27,230쌍에 증량×평균 마체중과 감량×평균 마체중을 별도로 추가했다.평균 마체중 자체와 제곱도 통제했다.여기서250kg·300kg은 두 출전의 평균 체중이므로 현재 체중을 쓰는 위 모형과 정의가 다르다.

'''+table(['기간','조건','거리','출전 쌍','작은 말−큰 말의3kg 비용 차이 초','95% 구간','BH q'],prows)+'''
전체기간1000m는 작은 말의 추가 손실+0.069초(−0.214~+0.353),1110m는−0.069초(−0.471~+0.333)로 추정됐다.최근 기간과 같은 함수율 구간·같은 달·체중변화5kg 이내의 비교에서도 확정 근거가 없었다.어느 지원 구간도 BH 기준을 통과하지 못했고 방향도 일관되지 않았다.비율만으로 작은 말에게 고정 감점을 주지 않는다.

## 해석과 한계

같은58kg를 체중과 무관하게 같은 조건이라고 표현하면 상대 부담 비율을 놓친다.반면 비율이 높다는 이유만으로 실제 손실이 더 크다고 확정하면 근거를 넘는다.말의 능력·평소 체중·최근 증감·부담중량과 증감을 함께 해석하고,중량 및 체중 대비 비율은 별도 관측값으로 제공할 수 있다.현재 작은 말의 고정 추가 보정초·최적 부담 비율·두 체중의 동등한 영향은 모두 채택하지 않았다.

마체중은 현재 경주의 사후 설명 측정이며 T−2 가용 입력으로 간주하지 않는다.큰 몸집 자체를 체력이나 지구력으로 확정하지 않는다.중량 배정·시간에 따라 변하는 능력·기수·전개 등의 잔여 교란이 남는다.연속 출전 날짜 군집은 뒤 출전일 기준이라 서로 다른 말이 앞 출전일만 공유하는 상관을 완전히 반영하지 못한다.95%는 점별 구간이고 BH는 거리와 두 시간 목표 전체에 적용했다.지원 기준과 추정 방법은[계획](PLAN.json) 및[앞선 중량 연구](../20261008_weight_speed_v2/README.md)를 따른다.

## 원천과 검증

[코드](analyze.py),[단위가 명시된3kg 비용](conditional_costs_explicit_units.csv),[단위가 명시된 작은 말−큰 말 대비](small_minus_large_explicit_units.csv),[모형](models.json),[출전 연결](exact58_source_lineage.csv),[입력 해시](source_manifest.json),[검증](verification.json),[별도 계산 검증](calculation_verification.json)을 보존했다.58개 결과 모형의 작은 말−큰 말 대비를−15×상호작용 계수와 대조했고,1000·1110m 연속 출전 계수와 군집 공분산은 별도 NumPy 계산으로 확인했다.중간 계산 파일의 기존 추론 함수 열 이름을 최종 공개 표에서는3kg 단위로 명시했다.기존 원 연구·DB·운영 모델은 변경하지 않았다.
'''
new('README.md',report)
decision={'same58_load_ratio_equal':False,'ratio250_pct':23.2,'ratio300_pct':5800/300,'body_size_time_cost_difference_confirmed':False,'same_effect_equivalence_established':False,'exact58_starts':2773,'cost_comparison_reference':'55to58kg_at250versus300kg','causal_body_size_effect_identified':False,'fixed_extra_penalty_adopted':False,'operational_change':False};write(H/'decision.json',decision)
p=C/'04_WEIGHT_SPEED.md';txt=p.read_text();needle='## マ' if '## マ' in txt else '## 마체중과 부담중량';section='''## 같은 58kg의 체중별 상대 부담

250kg 말의58kg 부담 비율은23.20%,300kg는19.33%다.비율은 다르지만 기록 손실도 그 비율만큼 다르다는 근거는 아니다.추가 후속에서55→58kg의 조건부 비용은1000m에서250kg0.188초·300kg0.154초로 차이+0.034초(점별95%−0.072~+0.140),1110m는0.249·0.188초로 차이+0.061초(−0.059~+0.182)였다.어느 지원 거리에서도 추가 차이를 확정하지 못했다.연속 출전 상호작용과 최근·안정조건에서도 불확실하고 방향이 일관되지 않았다.차이 미확인은 동등함의 증명이 아니다.

정확58kg2,773출전과 체중별 실제 지원을 보존했다.몸집이 작은 말의 고정 추가 감점이나 최적 부담 비율은 채택하지 않았다.[같은58kg 체중별 상세 후속](../20261008_load_ratio_58kg_v1/README.md)을 따른다.기존 중량 전반의 결과는 아래에 보존한다.

''';assert needle in txt;p.write_text(txt.replace(needle,section+needle,1),encoding='utf-8')
p=C/'README.md';txt=p.read_text();txt=txt.replace('마체중·부담중량 상관은약함.증량과작은감속연관,최근연속출전기울기불확실','마체중·부담중량 상관은약함.같은58kg의부담비율은체중별차이,추가감속차이는불확실');p.write_text(txt,encoding='utf-8')
p=C/'SOURCES.md';txt=p.read_text();marker='\n같은 출전 자료가 여러 버전에';assert marker in txt;txt=txt.replace(marker,'\n| [20261008_load_ratio_58kg_v1](../20261008_load_ratio_58kg_v1/README.md) | 같은58kg의체중대비부담과55→58kg비용의체중별차이.정확58kg2,773출전·증량×체중후속.차이미확인은동등성증명이아님 |\n'+marker);p.write_text(txt,encoding='utf-8')
p=C/'research_register.json';reg=json.loads(p.read_text());topic=next(t for t in reg['topics'] if t['id']=='weight_speed');topic['weight_general_source']=topic['latest_source'];topic['latest_source']='../'+H.name+'/README.md';topic['latest_body_ratio_followup']=decision|{'source':'../'+H.name+'/README.md'};write(p,reg)
links=0
for p in [H/'README.md',C/'04_WEIGHT_SPEED.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
write(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'explicit_3kg_contrast_units':True,'prior_research_hashes_unchanged':True,'management_previous_hashes':previous,'management_current_hashes':{key:sha(ROOT/key) for key in previous}})
art=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(H.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'];write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(i['bytes'] for i in art),'local_links_checked':links})
files={i['path']:i for i in central['files']}
for key,item in files.items():
    if item['role']=='conclusion_or_management':item.update(sha256=sha(ROOT/key),bytes=(ROOT/key).stat().st_size)
for name in ['README.md','PLAN.json','analyze.py','publish_verify.py','ratio_examples.csv','exact58_body_groups.csv','example_load_support.csv','conditional_costs_explicit_units.csv','small_minus_large_explicit_units.csv','source_manifest.json','verification.json','calculation_verification.json','decision.json','publication_verification.json','artifact_manifest.json']:
    p=H/name;key=str(p.relative_to(ROOT));files[key]={'path':key,'role':'source_weight_body_ratio_58kg','sha256':sha(p),'bytes':p.stat().st_size}
central['files']=list(files.values());central['verification'].update(weight_body_ratio_58kg_followup_completed=True,body_size_cost_difference_confirmed=False,body_size_cost_equivalence_established=False,local_links_checked=links);central['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management');write(C/'source_manifest.json',central)
assert all(sha(ROOT/i['path'])==i['sha256'] for i in central['files'])
print(json.dumps({'files':len(art),'bytes':sum(i['bytes'] for i in art),'links':links,'exact58_starts':2773,'central_hashes_verified':True},indent=2))
