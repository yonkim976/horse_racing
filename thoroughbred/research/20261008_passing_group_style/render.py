"""Render group-based definitions, comparisons and publication artifacts."""
from pathlib import Path
import os,json
os.environ['MPLCONFIGDIR']='/private/tmp/passing_group_style_mpl'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
plt.rcParams['font.family']=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc').get_name();plt.rcParams['axes.unicode_minus']=False
a=json.loads((O/'source_audit.json').read_text());pr=json.loads((O/'profile_summary.json').read_text());v=json.loads((O/'verification.json').read_text());d=pd.read_parquet(O/'observations.parquet');r=pd.read_csv(O/'race_group_summary.csv');early=r[r.point.eq('S1F')];p=pd.read_parquet(O/'temporal_evaluation.parquet');m=pd.read_csv(O/'evaluation_metrics.csv',dtype={'window':str});main=m[m.window.eq('2024_2025')&m.meet.eq('전체')].iloc[0];repeat=pd.read_csv(O/'repeatability.csv');strong=pd.read_csv(O/'strong_style_repeatability.csv');profiles=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str})
ct=pd.read_csv(O/'rank_group_crosstab.csv',index_col=0);ct.columns=ct.columns.astype(int);pct=ct.div(ct.sum(axis=1),axis=0)*100
fig,ax=plt.subplots(1,2,figsize=(11.8,4.8),layout='constrained');im=ax[0].imshow(pct,vmin=0,vmax=100,cmap='Blues');ax[0].set_xticks(range(4),['선행권','앞선추종','중단','후미']);ax[0].set_yticks(range(4),['선두1위','앞선','중단','후미']);ax[0].set_xlabel('통과조의 마군 기준');ax[0].set_ylabel('이전 개별 순위 기준');ax[0].set_title('같은 선두마군을 함께 분류하면 달라진다')
for i in range(4):
 for j in range(4):ax[0].text(j,i,f'{pct.iloc[i,j]:.1f}%\n{ct.iloc[i,j]:,}',ha='center',va='center',color='white' if pct.iloc[i,j]>50 else '#26394b',fontsize=10)
counts=early.first_group_size.value_counts().sort_index();ax[1].bar(counts.index,counts.values,color='#2d869c');ax[1].set_xticks(counts.index);ax[1].set_xlabel('초반 첫 마군에 속한 두수');ax[1].set_ylabel('경주 수');ax[1].set_title('선두1두 마군과 여러 두 선두마군을 구분')
for n,c in counts.items():
 if n<=6:ax[1].text(n,c+80,f'{c:,}',ha='center',fontsize=9)
ax[1].set_ylim(0,counts.max()*1.17);ax[1].spines[['top','right']].set_visible(False);fig.suptitle('서울·부산 S1F 통과조 | 범주 변화는 전개 정의의 차이, 성적 우위·경합의 입증 아님',fontsize=12);fig.savefig(F/'rank_vs_passing_group.png',dpi=170);plt.close(fig)
examples=d[d.horse_id.isin(['0044166','0044515','0046818','0045836'])].groupby('horse_id',group_keys=False).tail(5).copy();names=['선두1두','선두마군','앞선추종','중단','후미'];examples['observed_role']=examples.role5.map(dict(enumerate(names)));examples[['horse_id','horse_name','meet','date','source_key','gate','s1f','first_group_size','observed_role','notation_raw','selected_source','selection_status']].to_csv(O/'examples.csv',index=False)
solo=int(early.solo.sum());multi=len(early)-solo;strict=int(early.solo_ge2_lengths.sum())
lines=['# 통과조 기준 각질 성향: 같은 마군을 함께 읽기','',
'**통과조로 다시 판단할 수 있다. 같은 선두마군의 말들은 함께 선행권으로 분류하고, 첫 마군1두와여러 두 선두마군을 구분했다.** 순위1위 여부만으로는 단독선행과 선두마군 동반 주행을 구별할 수 없었다. 이번 결과는 각질 연구28의 후속이며 원 연구의 결과와 정의를 보존한다.','',
f"서울·부산2018~2026년 검증 명단159,014행·14,636경주에서 공식 S1F 통과조가 완전한 **{a['group_n']:,}출전·{a['group_races']:,}경주**를 분류했다. 이전 순위 기준과 공통인 {a['common_n']:,}출전 중 **{a['different_n']:,}출전({a['different_rate']:.1%})**의4구분이 달라졌다.",'',
'## 통과조를 읽는 근거','',
'마사회 공식 설명에 따르면 S1F는 출발 후200m 지점이다. 괄호는1마신 미만의 마군이고 괄호 내부 번호는 내측부터 표시한다. 쉼표는1~2마신 미만,하이픈은2~5마신 미만,등호는5~10마신 미만,≡는10마신 이상의 간격 구분이다. 이 기호를 정확한 마신 수나 시간으로 바꾸지 않았다. [마사회 공식 통과조 해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1).','',
'예를 들어 **`(2,^5,8),1,(3,4),(6,7),(9,10),(11,12)`**라면2·5·8번이 첫 마군이다. 괄호 내부의2→5→8을 앞뒤1→2→3위로 읽지 않는다. 세 말 모두 선두마군 소속이며,1번은 그 다음 마군이다. ^를 별도의 독주나 경합 압박의 증거로 사용하지 않는다. 이 예시는 문법 설명용이며 특정 실제 경주가 아니다.','',
'| 연구 분류 | 통과조에서의 기준 | 해석 범위 |','|---|---|---|',
'| 선두1두 | 첫 마군이1두 | 다음 마군과1마신 이상 분리된 선두1두 마군, 독주·무압박 확정 아님 |',
'| 선두마군 | 첫 마군이2두 이상 | 가까이 함께 앞에 있는 말들, 실제 경합 확정 아님 |',
'| 앞선추종 | 첫 마군 밖, 마군 평균 상대위치≤1/3 | 선입권 후보의 관측 위치 |',
'| 중단 | 마군 평균 상대위치1/3 초과~2/3 이하 | 중간 마군 위치 |',
'| 후미 | 마군 평균 상대위치>2/3 | 뒤쪽 마군, 추입 적성 확정 아님 |','',
'선두1두와선두마군을 합쳐 **선행권**이라 부른다. 나머지 마군은 앞선두수b,마군크기k,출주두수N에 대해 q=(b+(k+1)/2−1)/(N−1)로 분류한다. 마군이 순위 경계를 걸쳐도 소속말 전원이 같은 범주를 갖는다. 앞선추종·중단·후미 경계는 기존 마군 연구를 따른 연구용 구획이며 공식 각질 기준이 아니다. 1/4·3/4로 바꾸면 공통 표본21,883출전(14.1%)이 달라져 연속값·마군번호·크기·기호도 함께 보존한다.','',
'선행권이 언제나 소수의 공격적인 선행마만 뜻하는 것은 아니다. 첫 마군이8두처럼 큰 경주도 있으며 해당 표식은 그 지점의 밀집 상태다. 마군 번호만으로 두 번째 마군을 무조건 선입형이라 붙이지 않는다. 전체 두수와마군크기를 함께 보되, 다음 연구에서는 선두와의 간격 구간도 조건으로 사용할 수 있다.','',
'## 순위 기준과 얼마나 다른가','',
f"공통155,349출전에서 이전 초반1위는14,306출전이었다. 통과조 첫 마군 소속은37,619출전이며,그중 **순위1위가 아닌23,314출전**이 포함됐다. 첫 마군을선행권으로 보는 정의가 순위1위보다 넓다는 뜻이며 더 많은 말이 실제로 단독선행했다는 뜻은 아니다.",'',
f"통과조 유효 {len(early):,}경주에서 첫 마군1두는 **{solo:,}경주({solo/len(early):.1%})**,첫 마군2두 이상은 **{multi:,}경주({multi/len(early):.1%})**였다. 1두 마군 중 다음 마군과2마신 이상 분리된 보조 표식은 {strict:,}경주다. 1마신 분리·2마신 분리·실제 압박 유무를 같은 의미로 사용하지 않는다.",'',
'![순위와 통과조 비교](figures/rank_vs_passing_group.png)','',
'공식 순위1위가 첫 마군 밖에 기록된 모순1경주(서울2019-02-17 4R)는 원문대로 남기고 표식했다. API303과성적표 통과조 문자열이 일치해도 다른 성적 API의 통과순위와 완전히 일치한다는 보장은 없다. 이 경주12출전을 제외해도 분류 변경률27.4307%로 전체27.4311%와 거의 같았다. API303 선택분만의 변경률은27.5673%다. 결과에 맞춰 문자열이나 원천 선택을 수정하지 않았다.','',
'## 말별 판단이 어떻게 달라지는가','',
'최근5전은 공통 기준일2026-09-22,자료 마감9/20까지 실제 명단 관측순서를 유지한다. 결측을 건너뛰어 유효5전으로 만들지 않고 모두 유효·730일 이내일 때만 지원한다. 아래는 그5개 출전 슬롯을 동일하게 비교한 사례다.','',
'| 마필 | 순위 기준 초반1위 | 통과조 최근5전 | 판단 |','|---|---:|---|---|',
'| 닥터시저·부산 | 5/5 | 선두마군5회, 선두1두0회 | 자주1위지만 단독 선두 마군을 반복한 말은 아님 |',
'| 대박스타·서울 | 1/5 | 선두마군4회·앞선추종1회 | 순위1위 빈도보다 선행권 성향이 강하게 관측됨 |',
'| 성실대로·서울 | 0/5 | 선두마군2회·앞선추종2회·중단1회 | 이전 앞선5회라는 표현보다 마군 구성이 다양함 |',
'| 태양으뜸·부산 | 0/5 | 중단3회·후미2회 | 중·후미 중심, 추입형 확정은 아님 |','',
f"최근5전 비교가능 **{pr['comparable_profiles']:,}두** 중1위3/5 이상은 {pr['rank_leader_60']:,}두,첫 마군3/5 이상은 {pr['group_leader_60']:,}두였다. 그중 {pr['new_group_leader_60']:,}두가1위 빈도로는 잡히지 않았던 선행권 성향이다. 여러 두 선두마군을 포함해 정의가 넓어진 결과이며 말의 선행 능력이 새로 향상됐다는 뜻은 아니다. 최근365일 관측 말 중 최근5전 지원은 {pr['recent_supported5']:,}두다. 등록상 현역 여부는 확인하지 않았다.",'',
'[전체 말 프로필](outputs/horse_profiles.csv),[최근 관측 말](outputs/recent_horse_profiles.csv),[사례의 원문5전](outputs/examples.csv)에 선두1두율/선두마군율/앞선추종율/중단율/후미율,5/10전 표본·관측기간·2마신 분리 표식을 보존했다. 평균순위 하나로 합치지 않았다.','',
'## 통과조 성향도 다음 경주에서 반복되는가','',
'선두1두/선두마군을 합친4구분의 시간순 검증이다. 각 경주T−2까지 최근5전 빈도를 사용하고2024년 기준은2023년 말,2025년 기준은2024년 말까지의 지역·거리·두수 빈도로 만들었다. 두수별20회·말 이력3회 강도 축소는 계산 전 계획을 유지했다. 현재 경주의 위치·착순과미래 이력은 입력하지 않는다.','',
f"2024/2025년 **{int(main.n):,}출전·{int(main.horses):,}두·{int(main.dates):,}실제 날짜**에서 분류 정확도는 기준 **{main.baseline_accuracy:.1%}→말 이력 {main.history_accuracy:.1%}**,Brier는 **{main.baseline_brier:.6f}→{main.history_brier:.6f}**였다. 주 차이 {main.estimate:+.6f},말/실제 날짜 군집95% 구간[{main.lower:+.6f},{main.upper:+.6f}]로 말 이력의 반복 신호를 확인했다.",'',
'이전 순위 분류의44.2%와이번45.8%는 맞혀야 하는 범주 자체가 다르므로1.6%p의 예측 개선이나 더 정확한 각질 정답이라고 해석하지 않는다. 표본은 우연히 동일24,613출전이지만 표적이 다르다. 이번 정의 안에서 같은 기준과말 이력을 비교한 결과만 추가 반복 정보의 근거다.','',
'최근5전 중4번 이상 같은4구분이었던7,425출전의 다음 반복은59.9%였다. 강한 선행권2,324출전의 다음 선행권은58.1%였다. 같은 공통 표본에서 순위1위4/5 이상인381출전의 다음1위는49.3%지만 대상집단과범주가 다르므로 직접 우열을 주장하지 않는다.','',
'| 강한 반복 성향(최근5전 중4회 이상) | 평가 출전 | 다음 같은 범주 |','|---|---:|---:|']
for row in strong.itertuples():lines.append(f'| {row.style} | {row.n:,} | {row.repeat:.1%} |')
lines +=['','앞선추종 강한 성향은58출전으로 특히 적고 유지율도 낮았다. 따라서 이 범주를 안정된 선입형의 확정 라벨로 채택하지 않는다. 많은 앞선 말이 첫 마군에 포함돼 범주가 작아졌고,주변 마군크기와경계에 따라 이동할 수 있다. 다른 성향도 고정 각질·기수 의도·생리적 적성을 입증한 것은 아니다.','',
'## 원천 감사·한계','',
'사용 원문은 기존 읽기 전용 단일 트랜잭션의 공식 통과조 선택 스냅샷이다. API303 기본·공식 성적표 보완 선택,원문 문자열·선택 원천·상태를 유지했다. 새 DB 조회나공식 성적표 재수집은 하지 않았다. 원문 전체와원출전번호 집합이 일치할 때만 분류한다.','',
'S1F는327경주·3,627명단행을 보류했다. 이 중324경주는지원하지 않는 표기(· 등),3경주는명단 불일치였다. 주행중지 등으로 보이는 표시를 임의로 후미마군에 넣거나 실제 통과로 승격하지 않았다. 이 선택에 따른 편향 가능성은 남는다. 이전 순위 기준과공통표본155,349출전 외38출전은통과조만 관측 가능해 순위 변경률 계산에 넣지 않았다.','',
'서울3C와부산G4F의 보조 통과조도 지점명을 보존한 [지점별 마군 자료](outputs/passing_group_points.parquet)에 남겼다. 이 둘은 공간이 다른 지점이라 같은 중반으로 합치거나 그 이동을 공통 시간으로 바꾸지 않았다. 전 지점 지원 불가666건은 [보류표](outputs/notation_issues.csv)에 있다. 이번 말 성향·시간순 검증은S1F만 사용한다.','',
'선두마군 동반 주행은 경합·강제 선행·기수 의도를 뜻하지 않는다. 통과조는 마군과간격 구간·상대 내외측을 보여주지만 정확한 주행경로·절대 레일 거리·압박 정도·에너지 소비를 관측한 것은 아니다. 후미 성향만으로 추입 능력을 정하지 않고 막판 기록과순위 회복은 별도 연구로 연결한다.','',
'각질이 맞는지는같은 말이 다른 전개에서 조건을 맞춘 성과와이후 재현을 확인해야 한다. 이번에는 각질 변경 원인·성적 손실·게이트나상대의 강함으로 선행하지 못한 효과를 추정하지 않았다. 현재 실제 통과조를같은 경주의 사전 예측 입력에 사용하면 결과 누수다.','',
'## 독립 검증과 보존','',
f"독립 문자 스캐너가전체28,781지점 원문을 다시 읽고 {v['accepted_points']:,}유효 지점과 {v['held_points']:,}보류 지점을 확인했다. 전체 명단159,014행의 실제 최근5전·T−2,확률·Brier·말/날짜 군집구간,말별5/10전 수와현재/미래 결과 변조24사례를 검증했다. **{v['checks']:,}검사 통과**,기존 관련 {v['prior_files_unchanged']:,}파일을 보존했다. 원 통과조 스냅샷 해시가기존 읽기 전용 매니페스트와 일치했다.",'',
'[계산 전 계획](PLAN.md) · [분석](run.py) · [독립 검증](verify.py) · [검증 결과](outputs/verification.json) · [출처](SOURCES.md) · [게시 요약](PUBLICATION.md) · [용량](outputs/artifact_inventory.json). 기존 각질 연구28을 보존한 후속28A이며 독립 연구 수는 늘리지 않았다. 운영 모델·DB·웹 배포 변경 없음. 분석은완성 출력 덮어쓰기를 거부한다.']
(H/'README.md').write_text('\n'.join(lines)+'\n')
summary=dict(title='통과조 기준 각질 성향',date='2026-10-08',status='연구28의 후속28A·관측 정의·운영 미반영',group_n=a['group_n'],group_races=a['group_races'],common_n=a['common_n'],changed_rate=a['different_rate'],nonrank1_frontgroup=a['non_rank1_in_first_group'],solo_races=solo,multiple_front_group_races=multi,strict_ge2_lengths_races=strict,profile_summary=pr,temporal_evaluation=dict(n=int(main.n),baseline_accuracy=float(main.baseline_accuracy),history_accuracy=float(main.history_accuracy),brier_difference=float(main.estimate),ci95=[float(main.lower),float(main.upper)]),group_order_is_not_individual_rank=True,first_group_is_not_proven_contested_pace=True,optimal_style_proven=False,accuracy_not_comparable_across_definitions=True,report='README.md')
(O/'publication.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
(H/'PUBLICATION.md').write_text('''# 통과조로 다시 본 말의 각질 성향

2026-10-08 · 서울·부산 · 연구28의 후속28A · 운영 미반영

같은 선두마군에 속한 말은 함께 선행권으로 읽는다. 첫 마군이 1두인 경우와 여러 두인 경우를 나누고, 나머지 말도 마군 평균 위치로 함께 분류했다. 괄호 안 번호는 상대 내측부터의 순서이며 앞뒤 순위가 아니다. 공식 통과조 해설과 출주명단에 근거했다.

초반 통과조 155,387출전·14,309경주를 분류했다. 이전 순위와 공통인 155,349출전 중 27.4%의 4구분이 달라졌고, 순위 1위가 아닌 23,314출전이 선두마군에 포함됐다. 첫 마군이 1두인 경우는 2,966경주, 여러 두인 경우는 11,343경주였다. 여러 두 선두마군을 실제 경합이 확인된 것으로 읽지 않는다.

닥터시저의 최근 5전은 모두 순위 1위였으나, 통과조에서는 5회 모두 여러 두 선두마군이었다. 대박스타는 순위 1위가 1회지만 선두마군 4회·앞선추종 1회로 선행권 성향을 확인했다. 같은 5전에서 마군·순위·원문을 함께 보여준다.

2024/2025년 24,613출전에서 말 이력을 쓰면 통과조 4구분 정확도는 34.0%→45.8%, Brier 차이는 −0.054246[−0.060389,−0.048102]였다. 다른 정의인 순위 방식의 44.2%보다 예측이 개선됐다고 주장하지 않는다. 강한 선행권 성향의 다음 선행권 유지율도 58.1%로 고정 각질은 아니다.

‘맞는 각질’·성적 손실·의도적 변경·강제 선행 실패의 인과효과는 미확정이다. 보류 327경주·공식 순위와 첫 마군의 모순 1경주·원천별 민감도·연구용 경계를 함께 게시한다.

[보고서](README.md) · [최근 말 프로필](outputs/recent_horse_profiles.csv) · [사례 원문](outputs/examples.csv) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [요약JSON](outputs/publication.json) · [용량](outputs/artifact_inventory.json).
''')
print('Rendered group study report and figure')
