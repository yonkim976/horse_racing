"""Generate publication figures and Korean report from verified outputs."""
from pathlib import Path
import os,json
os.environ['MPLCONFIGDIR']='/private/tmp/running_style_foundation_mpl'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
font=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams['font.family']=font.get_name();plt.rcParams['axes.unicode_minus']=False
audit=json.loads((O/'source_audit.json').read_text());profile=json.loads((O/'profile_summary.json').read_text());verify=json.loads((O/'verification.json').read_text());metrics=pd.read_csv(O/'evaluation_metrics.csv',dtype={'window':str});main=metrics[(metrics.window=='2024_2025')&(metrics.meet=='전체')&(metrics.weighting=='start')].iloc[0];styles=pd.read_csv(O/'style_repeatability.csv');repeat=pd.read_csv(O/'repeatability.csv');comp=pd.read_csv(O/'same_distance_comparison.csv').iloc[0];defs=pd.read_csv(O/'definition_sensitivity.csv')
fig,ax=plt.subplots(1,2,figsize=(11,4.2),layout='constrained')
vals=[100*main.baseline_accuracy,100*main.history_accuracy];ax[0].bar(['지역·거리·두수 기준','+ 말 최근5전'],vals,color=['#8596aa','#227f98'],width=.55);ax[0].set_ylim(0,65);ax[0].set_ylabel('다음 경주 초반 위치 분류 정확도 (%)');ax[0].set_title('과거 말 이력에 반복 신호가 있다')
for i,v in enumerate(vals):ax[0].text(i,v+1.2,f'{v:.1f}%',ha='center',fontsize=12)
ax[1].bar(styles.prior_style,100*styles.strong_repeat,color=['#e29145','#56a1b0','#8596aa','#596eaa']);ax[1].set_ylim(0,85);ax[1].set_title('최근5전 중4번 이상 같았어도 변한다');ax[1].set_ylabel('다음 경주 같은 초반 위치 (%)')
for i,r in enumerate(styles.itertuples()):ax[1].text(i,r.strong_repeat*100+1.3,f'{r.strong_repeat:.1%}\nn={r.strong_n:,}',ha='center',fontsize=10)
for a in ax:a.spines[['top','right']].set_visible(False)
fig.suptitle('2024·2025년 시간순 검증 | 24,613출전·3,084두 | 각질 적합도·우승확률 아님',fontsize=12);fig.savefig(F/'repeatability.png',dpi=170);plt.close(fig)
d=pd.read_parquet(O/'observed_styles.parquet');q=d[d.s1f_complete&d.g3f_complete];matrix=pd.crosstab(q.s1f_class,q.g3f_class).reindex(index=range(4),columns=range(4),fill_value=0);pct=matrix.div(matrix.sum(axis=1),axis=0)*100
fig,ax=plt.subplots(figsize=(6.3,5.2),layout='constrained');im=ax.imshow(pct,vmin=0,vmax=100,cmap='Blues');ax.set_xticks(range(4),['선두','앞선','중단','후미']);ax.set_yticks(range(4),['선두','앞선','중단','후미']);ax.set_xlabel('G3F: 결승600m 전 관측 위치');ax.set_ylabel('S1F: 초반 관측 위치');ax.set_title('초반 위치와 중반 위치를 따로 보존\n같은 경주의 이동이며 말의 고정 각질이 아님')
for i in range(4):
 for j in range(4):ax.text(j,i,f'{pct.iloc[i,j]:.1f}%\n{matrix.iloc[i,j]:,}',ha='center',va='center',color='white' if pct.iloc[i,j]>50 else '#24394e')
fig.colorbar(im,ax=ax,label='각 초반 집단 안의 비율 (%)');fig.savefig(F/'early_middle_positions.png',dpi=170);plt.close(fig)

lines=['# 각질의 분류 근거와 말별 반복 성향','',
'**말마다 반복되는 초반 위치 성향은 확인됐다. 그러나 자주 보인 각질이 그 말에게 가장 유리한 각질이라는 근거는 아직 아니다.** 초반 위치, 중반 이후 이동, 과거 성향, 성적에 유리한 전개를 분리해야 이후 각질 변경과 선행 실패를 연구할 수 있다.','',
f"서울·부산2018~2026년 관측 명단 {audit['roster_rows']:,}행·{audit['ledger_races']:,}경주·{audit['roster_horses']:,}두에서 시작했다. 공식 S1F 순위가 출주두수만큼 완전한 {audit['valid_s1f_rows']:,}출전·{audit['valid_s1f_races']:,}경주를 초반 분류했다. 2024·2025년 과거 이력 검증은 {int(main.n):,}출전·{int(main.horses):,}두다.",'',
'## 이번 단계에서 구분할 것','',
'| 구분 | 근거 | 지금 판단 가능한 것 |','|---|---|---|',
'| 한 경주의 관측 전개 | 공식 S1F·G3F·G1F 통과순위 | 이번에 어디에서 달렸는가 |',
'| 말의 반복 성향 | 현재 경주를 제외한 최근5/10전 위치 분포 | 과거 어떤 위치가 잦았고 다음에도 반복되는가 |',
'| 말에게 맞는 각질 | 같은 말의 조건을 맞춘 여러 전개별 이후 성과 검증 | 이번 연구로 확정하지 않음 |','',
'선행·선입·추입을 먼저 하나씩 붙이는 것보다 **선두율·앞선율·중단율·후미율과 중반 위치·막판 회복을 함께 저장**하는 것이 이번 연구의 기준이다. 5전 평균만 쓰면 극단적인 선두와 후미가 섞인 말이 매번 중단에서 달린 말처럼 보일 수 있다. 순위1위만으로 단독 선행·선두 경합·기수의 의도를 알 수 없고, 게이트 번호는 실제 주행 경로가 아니다.','',
'## 초반 분류의 재현 가능한 기준','',
'원래 출주두수N에 대해 상대 위치 p=(S1F순위−1)/(N−1)을 계산한다. 선두를 별도로 분리하고 나머지를 다음과 같이 구획했다. 아래 경계는 이번 연구용이며 마사회의 공식 각질 등급이나 확정 표준이 아니다.','',
'| 관측 구분 | 기준 | 12두 경주의 예 | 각질 연구에서의 해석 |','|---|---|---|---|',
'| 선두 | S1F1위 | 1위 | 선행 성향의 직접적인 관측 근거 |',
'| 앞선 | 선두 제외 p≤1/3 | 2~4위 | 선입 후보의 초반 근거, 중반 유지도 확인 |',
'| 중단 | 1/3<p≤2/3 | 5~8위 | 중간 위치, 이후 진출 시점을 별도 확인 |',
'| 후미 | p>2/3 | 9~12위 | 뒤에 있었다는 뜻, 추입형·추입 성공 확정 아님 |','',
'선행형 후보에는 반복 선두율과 중반 앞선 유지가, 선입형 후보에는 반복 앞선 위치와 중반 유지가 근거가 된다. 추입형 후보는 중·후미 출발에 더해 중반 진출/막판 회복과 조건을 맞춘 막판 기록을 확인해야 한다. 순위 회복은 상대의 지침도 포함하고 뒤에 있던 말에게 회복할 여지가 더 크므로 그것만으로 추입 능력을 확정하지 않는다. 이번에는 막판 기록을 보정한 능력 분류를 만들지 않았다.','',
'G3F는 결승600m 전, G1F는 결승200m 전 위치다. S1F→G3F, G3F→결승, G1F→결승의 상대 위치 변화를 각각 저장했다. 다른 거리에서 동일한 코너를 무리하게 중반 기준으로 합치지 않았다. 1/3·2/3 경계 대신1/4·3/4를 사용하면 관측 분류가16.0% 달라진다. 따라서 단일 명칭보다 연속 상대위치와 원래 순위도 보존한다.','',
'기존 feature 코드의 rank/N <0.35/0.55/0.75와 웹의0.25/0.50/0.75 규칙도 서로 다르다. 두 규칙을 **단일 경주에 적용한 정의 비교**에서 첫 범주에 실제 선두가 아닌 말이 각각32,545/19,261출전 포함됐다. 이는 기존 최근5전 평균 분류의 실제 오분류율 검증이 아니며 코드 오류로 단정하지 않는다. 이번 선두 범주는 실제 초반1위만 뜻한다.','',
'![시간순 반복성 검증](figures/repeatability.png)','',
'## 과거 성향은 다음 경주에서도 반복되는가','',
'각 경주 이틀 전(T−2)까지 최근5개 명단 관측을 사용했다. 결측 경주를 건너뛰어 유효5전을 모으지 않았다. 5전 모두 S1F가 관측되고730일 이내에 있어야 평가한다. 3/5 이상 같은 위치는 우세,4/5 이상은 강한 반복 표시다. 짧은5전의 잠정 표시이며 개인별 통계적 확정값이 아니다. 현재 경주의 착순·통과순위·미래 이력은 입력하지 않았다.','',
'2024년 기준 확률은2023년 말까지,2025년은2024년 말까지 자료로 학습했다. 지역×정확거리의 위치 비율에 두수별 빈도를20회 강도로 축소했고, 말 최근5전 빈도를 그 기준3회 강도로 축소했다. 검증 연도 안에서도 해당 경주 전까지 새로 관측된 말 이력은 사용한다. 표본이 부족한 신마 등은 이 비교에서 제외됐다.','',
'| 평가 | 지역·거리·두수 기준 | + 말 최근5전 |','|---|---:|---:|',
f'| 초반 위치 분류 정확도 | {main.baseline_accuracy:.2%} | {main.history_accuracy:.2%} |',
f'| Brier 오차(낮을수록 좋음) | {main.baseline_brier:.6f} | {main.history_brier:.6f} |','',
f'주 비교 Brier 차이는 **{main.estimate:+.6f},95% 군집 구간[{main.lower:+.6f},{main.upper:+.6f}]**였다. 말 이력에 반복 신호가 있다는 근거다. 우승 예측 정확도나 수익 개선이 아니다. 같은 말의 반복 출전과 같은 날짜의 경주 의존을 함께 고려했다. 경주 동일가중에서도 개선 방향이 유지됐으며1/5/10회 축소 민감도도 보존했다. 좋은 민감도 수치를 골라 주 설정을 바꾸지 않았다.','',
'최근5전 중3번 이상 같은 집단17,637출전에서 다음에도 같은 위치였던 비율은47.7%였다. 4번 이상 같았던6,782출전에서도56.9%로,43.1%는 다른 범주로 이동했다. **이는 각질 전환을 의도했다는 비율이 아니다.** 경계 한 순위 차이·거리·편성·말 상태·기수·출발·게이트가 함께 바뀔 수 있다.','',
'| 과거 우세 위치 | 3/5 이상 표본 | 다음 같은 위치 | 4/5 이상 표본 | 다음 같은 위치 |','|---|---:|---:|---:|---:|']
for r in styles.itertuples():lines.append(f'| {r.prior_style} | {r.n:,} | {r.repeat:.1%} | {r.strong_n:,} | {r.strong_repeat:.1%} |')
lines +=['','후미 집단의 반복이 상대적으로 높았다. 그렇다고 후미 각질의 성적이 더 좋다는 뜻은 아니다. 위 비율은 각 집단의 두수·경계·편성 분포에 의존하며 범주 수가4개라고25%를 공정한 무작위 기준으로 놓지 않았다.','',
f'같은 장소·정확거리 최근5전이 충분한 {int(comp.n):,}출전만 짝지어 비교했을 때 Brier는 혼합거리 이력 {comp.mixed_brier:.6f},동일거리 이력 {comp.same_distance_brier:.6f}였다. 동일거리−혼합 차이 {comp.estimate:+.6f} [{comp.lower:+.6f},{comp.upper:+.6f}]로 이번 단순 빈도 방식의 추가 이득은 확인되지 않았다. 거리별 각질이 없다는 증명은 아니며, 오래된 이력·표본 제한·상대 편성 차이를 더 다뤄야 한다.','',
'## 말별 관측 프로필','',
f"공통 기준일2026-09-22,관측 마감9/20에서 최근5전 조건을 충족한 {profile['supported5']:,}두의 분포를 보존했다. 그중 우세 성향 {profile['dominant5']:,}두,강한 반복 {profile['strong5']:,}두,혼합 {profile['mixed5']:,}두였다. 최근365일 내 관측된 {profile['recent365']:,}두 중 최근5전 지원은 {profile['recent_supported5']:,}두,강한 반복은 {profile['recent_strong5']:,}두다. 현역 등록 여부는 별도로 확인하지 않았다.",'',
'| 예시 마필 | 최근5전 선두/앞선/중단/후미 | 최근10전 우세 위치 | 읽는 방법 |','|---|---|---|---|',
'| 닥터시저·부산 | 5/0/0/0 | 선두 | 최근 초반 선두 성향 |',
'| 성실대로·서울 | 0/5/0/0 | 앞선 | 최근 앞선 성향, 선행1위와 구분 |',
'| 킹아너·서울 | 0/0/5/0 | 중단 | 중단 위치의 반복 |',
'| 스타티세·부산 | 0/0/0/5 | 후미 | 후미 성향, 추입 적성은 별도 |',
'| 태양으뜸·부산 | 0/1/2/2 | 혼합 | 한 명칭으로 고정하지 않음 |','',
'예시는 최근 관측·지원 여부 안에서 성적을 선택 기준으로 사용하지 않은 설명 사례다. 이 말들의 최적 작전·현역 여부·다음 출전 추천이 아니다. [전체 말 프로필](outputs/horse_style_profiles.csv),[최근 관측 말](outputs/recent_horse_style_profiles.csv),[장소·거리별 프로필](outputs/horse_distance_style_profiles.parquet)에 관측수·날짜·5/10전 분포·중반 앞선율·구간별 회복을 남겼다. 5/10전이 모두 지원된1,349두에서 혼합까지 포함한 표시 일치율은59.7%로 창 길이에 민감했다.','',
'![초반과 중반 위치](figures/early_middle_positions.png)','',
'## 자료 감사와 한계','',
'원문18파일162,427행에서 이미 검증된 실전14,636경주의 명단만 썼다. 원장158,528행에 원래 명단의 비정상486행을 보완했다. 이 중484행은91/92 코드,2행은0 코드다. 이2행은 실제 주행을 새로 확정한 것으로 해석하지 않고 초반 결측 명단 관측으로 유지했다. 93/94/95는 기존 출주두수 계약대로 제외했다. 원장 밖3413행은 취소·제외 또는 검증 실전 키 밖의 행이며 새 실전으로 승격하지 않았다. 모든 말의 등록 이후 전체 경력이라는 보장은 없다.','',
'159,014명단행 중330경주·3,665행은 S1F 완전 순열 조건을 통과하지 못했다. 전체 경주를 미관측으로 두었고 남은 말끼리 재순위를 매기지 않았다. 초반 분류155,349출전에는 기존 정상 기록 연구 밖4,284출전과 유효 결승착순이 없는114출전도 포함됐다. 중반/막판 순위의 결측은 각각 별도 표시했다. 완전 관측 경주 선택에 따른 편향 가능성은 남는다.','',
'2024년 유효 초반18,233출전 중 최근5전 지원12,025출전,2025년18,405 중12,588출전만 검증했다. 이력 부족·결측·오래된 이력 때문에 나머지12,025출전은 비교 대상이 아니었다. 신마 전체나 실시간 출전표 전원의 성능으로 일반화하지 않는다. 2026년은 프로필 작성에만 사용했고 평가에 사용하지 않았다.','',
'주 검정은 통합 Brier 한 비교다. 장소·연도·성향별 표와 거리 비교는 기술적/보조 결과이며 여러 하위집단을 탐색해 유의한 전략을 채택하지 않았다. 관측 위치는 상대마의 구성에 의존한다. 위치 유지가 적성·기수 의도·타고난 능력의 인과 증거가 아니며, 이번 정확도44.2%는 충분히 높은 실전 각질 확정 성능이라고 주장하지 않는다.','',
'## 다음 연구로 넘길 정의','',
'‘맞는 각질’은 그 각질을 자주 쓰는지를 넘어서 **같은 말이 다른 전개를 했을 때 조건을 맞춘 성과가 반복적으로 달랐는지** 검증해야 한다. 먼저 과거 성향을 고정하고 현재 실제 위치와의 차이를 표시한다. 거리·등급·연령·부담중량·함수율·최근 컨디션·상대 편성 등의 변화와 함께 성과를 비교하고 이후 기간에서 재현되는지 본다. 선행을 못 잡은 것은 빠른 상대나 불리한 출발의 결과일 수도 있어 현재 실제 전개를 임의 배정된 처치로 취급하면 안 된다.','',
'각질 변경은 과거 창과 이후 창의 분포 변화로 탐지하되 겹치는 최근5전 창끼리의 자동 반복을 피한다. 부진 후 작전 변경 여부는 부진 시점 이전 성향을 먼저 고정한다. 게이트/상대 때문에 앞선을 못 잡은 연구는 출전 전 앞선 예상과 상대의 과거 초반 속도로 예상 경쟁을 만들고, 실제 이탈과 이후 성과를 연결한다. 관측만으로 의도적 변경·강제 실패 원인을 확정하지 않으며 필요하면 심판기록·영상의 별도 근거를 연결한다. 이번에는 그 성적 손실과 인과효과를 추정하지 않았다.','',
'## 검증·보존','',
f"독립 검증 {verify['checks']:,}검사를 통과했다. 원문159,014행의 식별키·통과순위·게이트,19개 입력 해시,독립SQL의 완전 경주,별도 pandas shift/rolling의 실제 명단 최근5전·T−2·확률·Brier·군집 구간을 재계산했다. 현재/미래 결과 변조24사례의 현재 입력 불변을 확인했다. 시작 시 관련 기존364파일 중 공유5개를 제외한359파일이 변하지 않았음을 확인했다.",'',
'[계산 전 계획](PLAN.md) · [분석](run.py) · [독립 검증](verify.py) · [검증 결과](outputs/verification.json) · [출처](SOURCES.md) · [게시용 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json). 기존 운영 평가표·모델·DB·웹 배포를 변경하지 않았다. 프로젝트 루트에서 `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261008_running_style_foundation/run.py`로 재현하되 완성된 분석 출력 덮어쓰기는 거부한다.']
(H/'README.md').write_text('\n'.join(lines)+'\n')
summary=dict(title='각질의 분류 근거와 말별 반복 성향',date='2026-10-08',status='관측 분류·시간순 반복성 연구, 운영 미반영',scope=['서울','부산'],period_end={'서울':'2026-09-20','부산':'2026-09-18'},roster_rows=audit['roster_rows'],classified_rows=audit['valid_s1f_rows'],definition={'leader':'S1F=1','forward':'nonleader,p<=1/3','middle':'1/3<p<=2/3','rear':'p>2/3','p':'(rank-1)/(N-1)','rear_is_not_confirmed_closer':True},temporal_evaluation=dict(n=int(main.n),horses=int(main.horses),baseline_accuracy=float(main.baseline_accuracy),history_accuracy=float(main.history_accuracy),baseline_brier=float(main.baseline_brier),history_brier=float(main.history_brier),brier_difference=float(main.estimate),ci95=[float(main.lower),float(main.upper)]),profiles=profile,optimal_style_proven=False,style_change_causal_effect_estimated=False,gate_failure_effect_estimated=False,report='README.md',figures=['figures/repeatability.png','figures/early_middle_positions.png'])
(O/'publication.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
(H/'PUBLICATION.md').write_text('''# 각질 연구: 말의 반복 성향과 최적 전개의 구분

2026-10-08 · 서울·부산 · 연구용 관측 기준 · 운영 미반영

초반 위치 성향은 반복되지만 고정된 각질은 아니다. 원문 명단159,014행에서 공식 초반 통과순위가 완전한155,349출전을 분류했다. 선두·앞선·중단·후미를 출주두수로 표준화해 구분하고 중반과 막판 회복을 별도 저장했다. 후미라는 이유만으로 추입형이라고 부르지 않는다.

2024·2025년24,613출전·3,084두에서 말 최근5전을 반영한 다음 초반 위치 정확도는35.0%→44.2%였다. Brier 차이−0.043613,95% 군집 구간[−0.049493,−0.037734]로 반복 신호를 확인했다. 최근5전 중4번 이상 같은 위치였어도 다음 반복은56.9%였다. 강한 선두 성향의 다음 선두는49.3%,강한 후미 성향의 다음 후미는68.6%다.

최근 관측 말의 최근5전 지원2,132두 중 강한 반복629두를 표시하고5/10전 분포·중반 앞선율·구간별 위치 회복·관측수를 보존했다. 단일 확정 각질, 생리적 적성, 우승확률, 현역 등록 확인을 뜻하지 않는다. 동일거리 이력의 추가 이득은 이번 단순 방식에서 확인되지 않았다.

각질이 ‘맞는다’는 결론에는 같은 말의 다른 전개별 조건을 맞춘 성과와 이후 재현 검증이 더 필요하다. 각질 변경·게이트 또는 상대 때문에 앞선을 못 잡았을 때의 성적 손실은 다음 단계다. 전체보고서와표본·결측·선택 편향·임시 경계를 함께 게시해야 한다.

[보고서](README.md) · [최근 말 프로필](outputs/recent_horse_style_profiles.csv) · [그림](figures/repeatability.png) · [기계 요약](outputs/publication.json) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json).
''')
print('Rendered report and two figures')
