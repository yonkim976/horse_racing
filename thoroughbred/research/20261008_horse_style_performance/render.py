"""Create Korean evidence report, frozen examples, figures and publication payload."""
from pathlib import Path
import os,json
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/horse_style_performance_mpl')
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
font=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11})
labels=['선행','선입','중단','후미'];colors=['#e17248','#e6bd54','#4e9ba1','#667eb5']
pr=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str});a=pd.read_parquet(O/'roster.parquet');d=pd.read_parquet(O/'performance_observations.parquet');cells=pd.read_csv(O/'horse_distance_style.csv',dtype={'horse_id':str});cp=pd.read_csv(O/'change_performance.csv',dtype={'horse_id':str});metrics=pd.read_csv(O/'conditional_evaluation_metrics.csv');rep=pd.read_csv(O/'candidate_replication.csv');fm=pd.read_csv(O/'change_followup_metrics.csv');ev=pd.read_csv(O/'change_events.csv');summary=json.loads((O/'profile_summary.json').read_text());audit=json.loads((O/'source_audit.json').read_text())
ids=['0044166','0044515','0045836','0050078'];ex=pr.set_index('horse_id').loc[ids].reset_index();ex.to_csv(O/'examples.csv',index=False)
raw=a[a.horse_id.isin(ids)].groupby('horse_id',group_keys=False).tail(10).merge(d[['row_key','finish','rank_raw','adjusted_performance','good_adjusted']],on='row_key',how='left',validate='one_to_one');raw.to_csv(O/'example_actual_starts.csv',index=False)
fig,axs=plt.subplots(2,2,figsize=(12,7.8),sharex=True)
for ax,row in zip(axs.ravel(),ex.itertuples()):
 old=np.array([getattr(row,f'old_count5_{j}') for j in range(4)]);new=np.array([getattr(row,f'count5_{j}') for j in range(4)]);left=np.zeros(2)
 for j in range(4):
  vals=np.array([old[j],new[j]]);ax.barh([1,0],vals,left=left,color=colors[j],label=labels[j]);
  for yy,v,l in zip([1,0],vals,left):
   if v:ax.text(l+v/2,yy,str(v),ha='center',va='center',color='#222')
  left+=vals
 ax.set_title(row.horse_name);ax.set_yticks([1,0],['그전 5전','최근 5전']);ax.set_xlim(0,5);ax.set_xticks(range(6));ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
fig.suptitle('말별 초반200m 통과조: 최근 각질과 이전 각질',fontsize=16);fig.legend(*axs[0,0].get_legend_handles_labels(),loc='lower center',ncol=4,bbox_to_anchor=(.5,.015));fig.text(.5,.065,'선행은 첫 마군 전체. 각질 변화 후보이며 전술 의도·원인·최적 각질을 확정하지 않음.',ha='center',fontsize=10);fig.tight_layout(rect=(0,.10,1,.94));fig.savefig(F/'horse_style_examples.png',dpi=160);plt.close(fig)
fig,axs=plt.subplots(1,2,figsize=(12,5.4));m=metrics[metrics.scope.eq('supported')].reset_index(drop=True);ys=np.arange(len(m));axs[0].errorbar(m.estimate,ys,xerr=np.vstack([m.estimate-m.lower,m.upper-m.estimate]),fmt='o',color='#285b80',capsize=4);axs[0].axvline(0,color='#888',linestyle='--');axs[0].set_yticks(ys,m.window.str.replace('_','·'));axs[0].invert_yaxis();axs[0].set_title('말별 각질 편차 추가의 조건부 설명 오차 차이');axs[0].set_xlabel('MAE 차이: 음수면 오차 감소 (-100log시간 단위)');axs[0].grid(axis='x',alpha=.2)
e=ev[ev.followup_supported];new=int(e.new_retained3of5.sum());old=int(e.old_hits.ge(3).sum());mixed=len(e)-new-old;axs[1].bar(['새 각질 3/5 이상','이전 각질 3/5 이상','그 외'],[new,old,mixed],color=['#4e9ba1','#e17248','#a0a7b4']);axs[1].set_ylabel('말 수');axs[1].set_title(f'과거 변화 후보의 이후 실제5전 ({len(e):,}두)')
for i,n in enumerate([new,old,mixed]):axs[1].text(i,n+5,f'{n:,}두\n{n/len(e)*100:.1f}%',ha='center',fontsize=10)
axs[1].set_ylim(0,max(new,old,mixed)*1.22);fig.text(.5,.015,'현재 각질에 조건부인 기록 설명 검증이다. 출전 전 예측·개인 최적 각질·각질 변경 인과효과 검증이 아니다.',ha='center',fontsize=10);fig.tight_layout(rect=(0,.06,1,1));fig.savefig(F/'conditional_evidence.png',dpi=160);plt.close(fig)
def dist(row,prefix):return '·'.join(f'{labels[j]}{int(row[f"{prefix}_{j}"])}' for j in range(4) if int(row[f'{prefix}_{j}'])>0)
examplelines=[]
for _,r in ex.iterrows():
 candidate=f"{int(r.reference_distance)}m {r.performance_candidate} 잠정후보" if r.performance_comparison_supported else '동일 거리 각질 비교 자료 부족'
 examplelines.append(f"| {r.horse_name} | {dist(r,'old_count5')} → {dist(r,'count5')} | {dist(r,'good_style')} ({int(r.good_adjusted_n)}회) | {candidate} |")
metriclines=[]
for rr in metrics[metrics.scope.eq('supported')].itertuples():metriclines.append(f'| {rr.window} | {rr.n:,} | {rr.global_mae:.6f} | {rr.personal_mae:.6f} | {rr.estimate:+.6f} [{rr.lower:+.6f}, {rr.upper:+.6f}] |')
replines=[]
for rr in rep.itertuples():replines.append(f'| {rr.year} | {rr.horses} | {rr.n} | {rr.estimate:+.3f} [{rr.lower:+.3f}, {rr.upper:+.3f}] |')
vpath=O/'verification.json';v=json.loads(vpath.read_text()) if vpath.exists() else {'checks':None,'prior_files_preserved':136}
strict=pd.read_csv(O/'candidate_replication_supported_styles.csv')
strictlines=[]
for rr in strict.itertuples():strictlines.append(f'| {rr.year} | {rr.horses} | {rr.n} | {rr.estimate:+.3f} [{rr.lower:+.3f}, {rr.upper:+.3f}] |')
body=(H/'REPORT_TEMPLATE.md').read_text()
for key,value in {'@EXAMPLES@':examplelines,'@METRICS@':metriclines,'@REPLICATION@':replines,'@STRICT_REPLICATION@':strictlines}.items():body=body.replace(key,'\n'.join(value))
(H/'README.md').write_text(body)
pub='''# 말마다 평소 각질과 잘 달리는 각질이 같은가

**평소 초반 위치, 좋은 경기의 초반 위치, 최근 변화는 구분해 볼 수 있다. 개인에게 가장 잘 맞는 각질의 확정은 아직 어렵다.** 서울·부산의 출발 후200m 통과조를 선행·선입·중단·후미로 읽었다. 선행은 첫 마군 전체이고 후미만으로 추입형을 정하지 않는다.

최근5전 분포는2,601두, 이전5전과의 비교는1,349두에서 가능했다. 그중302두의 우세 각질이 달라졌지만 다중검정을 통과한 개별 변화는0두였다. 거리 구성도 함께 바뀔 수 있어 전술 변경의 확정이 아니다. 과거 변화후보734두의 이후5전을 따라가면 새 각질이3회 이상 유지된 비율은34.3%였다.

잘 달림은 실제5위 이내와 조건 대비 빠른 기록으로 나눴다. 같은 경주·말 기본 수준·거리·부담중량·마체중·rating·과거성적 등을 고려해 좋은 기록의 각질 분포를 따로 보존했다. 같은 정확거리에서 다른 각질로 반복 출전한1,753두는 기록 우세 잠정후보를 비교할 수 있고 최근365일 관측말은553두다.

닥터시저는 최근5전 모두 선행이고 좋은8경기도 모두 선행이지만 다른 각질의 동일거리 비교가 부족해 최적 판정을 보류했다. 태양으뜸은 선행4·선입1에서 중단3·후미2로 이동하며 성적도 떨어졌다. 블랙질주는 같은1200m에서 뒤쪽으로 이동했지만 최근 성적은 좋아졌다. 위치 변화의 원인과 성적 변화의 원인은 별도다.

2024·2025년의 과거 고정 검증에서 말별 각질편차 추가의 조건부 설명오차 감소는 작고95% 구간이0을 포함했다. 현재 경주의 실제 각질을 쓰는 검증이므로 출전 전 예측 개선으로 표현하지 않는다. 개인 최적 각질·전술 처방·강제 선행실패의 인과손실·운영 반영은 미확정이다.

자료 종료일: 서울2026-09-20·부산2026-09-18. 프로필 기준일2026-09-22(T−2). [상세 보고서](README.md) · [최근 말 표](outputs/recent_horse_profiles.csv) · [거리별 개인 비교](outputs/horse_distance_style.csv) · [검증](outputs/verification.json).
'''
(H/'PUBLICATION.md').write_text(pub)
sources=['# 출처·자료와계산정의\n','2026-10-08. 원본을수정하지않고기존검증스냅샷3개를재사용했다. 원천이력·선택문법·명단복원은각이전연구를따른다.\n','| 입력 | 바이트 | SHA-256 |\n|---|---:|---|']
for item in audit['input_files']:sources.append(f"| {item['path']} | {item['bytes']} | {item['sha256']} |")
sources+=['\n- [통과조원연구28A](../20261008_passing_group_style/README.md): API303우선/공식성적표보완,문법/명단감사,선두1두/여러두표식과role4의출처.\n- [명단복원28](../20261008_running_style_foundation/README.md): 18개2018~2026년원자료의출전명단·순위·말이름·기록품질기준.\n- [기록모집단](../20261007_sex_ability_gap/README.md): 11거리151,074행,출전당시rating/체중/부담중량/과거이력. 이번모형에성별효과·기존전체기간점수·주로빠르기를사용하지않았다.\n- [공식경주성적표해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1): 2026-10-08확인. S1F출발후200m,괄호1마신미만마군,괄호내내측순서. 공식해설은관측위치의근거이며개인최적각질의근거가아니다.\n','이번통계방법·수축강도·지원조건·단위는[계산전계획](PLAN.md)과[분석코드](run.py)의명시적연구선택이다. 웹문서에서개인적성의확증근거를가져온것이아니다. 새DB조회·원천재수집·기존연구재실행없음. 최종잔차는전체기간회고평가,2024/2025시간순모형은각전년까지의학습과실제각질조건부평가다.']
(H/'SOURCES.md').write_text('\n'.join(sources)+'\n')
payload=dict(title='말별각질:평소·좋은경기·최근변화',study='28B',status='research_candidate',asof=audit['asof'],data_end=audit['end_by_meet'],position_point='S1F_200m',labels=labels,summary=summary,performance_n=len(d),conditional_metrics=metrics.to_dict('records'),candidate_replication=rep.to_dict('records'),candidate_replication_supported_styles=strict.to_dict('records'),change_followup=fm.to_dict('records'),personal_optimal_style_proven=False,causal_change_effect_proven=False,prerace_prediction_verified=False,operational=False,examples=ex.replace({np.nan:None}).to_dict('records'),tables={'profiles':'horse_profiles.csv','recent_profiles':'recent_horse_profiles.csv','distance_style':'horse_distance_style.csv','changes':'current_change_candidates.csv','change_performance':'change_performance.csv'})
(O/'publication.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print('Rendered reports, 2 figures and website-ready JSON')
