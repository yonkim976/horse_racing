"""Tables, publication text and a static uncertainty figure from the frozen estimates."""
from pathlib import Path
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]

def main():
 e=pd.read_csv(O/'adjusted_associations.csv');a=e.query("period=='2024_2025' and variant=='primary' and state=='new'")
 items=[]
 for fam,g in a.groupby('family',sort=False):
  ix=g.set_index('target');w=ix.loc['restricted_wait_180'];row=dict(family=fam,label=w.label,new_onset_weeks=int(w.exposed_rows),new_horses=int(w.exposed_horses))
  for target in ['restricted_wait_180','no_start_30','no_start_60','no_start_90','no_start_180','top3_1','top3_2','top3_3','time_1','time_2','time_3']:
   t=ix.loc[target]
   for col in ['estimate','ci_low','ci_high','q_joint','q_domain','exposed_rows','exposed_horses','supported']:row[target+'_'+col]=t[col]
  row['gap_status']='출전지연연관' if w.supported and w.estimate>0 and w.q_joint<.05 else '출전지연탐색신호' if w.supported and w.estimate>0 and w.q_domain<.05 else '표본부족' if not w.supported else '지연미확인'
  perf=g[g.horizon.gt(0)&g.supported&g.identified]
  bad=(perf.target.str.startswith('top3')&perf.estimate.lt(0))|(~perf.target.str.startswith('top3')&perf.estimate.gt(0))
  row['performance_status']='검정범위민감한저하후보' if (bad&perf.q_joint.lt(.05)).any() else '저하미확인_영향없음판정아님'
  row['domain_FDR_confirmed_performance_decline']=bool((bad&perf.q_domain.lt(.05)).any())
  items.append(row)
 pd.DataFrame(items).to_csv(O/'item_summary.csv',index=False)
 selected=['fracture','tendon_ligament','post_arthroscopy','post_castration','lameness','physical_therapy']
 display={'fracture':'골절 관련 문구','tendon_ligament':'건·인대·건초 관련 문구',
          'post_arthroscopy':'관절경 술후처치','post_castration':'거세 술후처치',
          'lameness':'파행','physical_therapy':'물리·침치료'}
 e[e.family.isin(selected)&e.variant.eq('primary')&e.state.eq('new')].to_csv(O/'annual_key_items.csv',index=False)
 gap=a[a.target.eq('restricted_wait_180')].set_index('family').loc[selected]
 lines=['| 기록 문구 분류 | 새 시작 관측 주 / 말 | 추가 대기일 | 95% 구간 | 전체 지표 BH q |',
        '|---|---:|---:|---:|---:|']
 for fam,t in gap.iterrows():
  lines.append(f'| {display[fam]} | {t.exposed_rows} / {t.exposed_horses} | {t.estimate:+.1f}일 | {t.ci_low:.1f}~{t.ci_high:.1f}일 | {t.q_joint:.3g} |')
 table='\n'.join(lines)
 (O/'key_gap_table.md').write_text(table+'\n')
 summary={'primary_horses':1621,'primary_landmark_rows':70587,'all_horses':1794,'all_landmark_rows':85384,
  'medical_families':33,'models':41,'conditional_performance_domain_FDR_declines':0,
  'primary_new_supported_domain_tests':{'return_gap':155,'conditional_performance':258,'joint_nonreturn_nonpodium':93},
  'figure_is_association_not_causal_effect':True,'medical_severity_not_estimated':True,
  'joint_BH_per_state_family_size':561,'conditional_performance_BH_per_state_family_size':297}
 (O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 font=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc')
 plt.rcParams['axes.unicode_minus']=False
 fig,axes=plt.subplots(1,2,figsize=(12,5.3),gridspec_kw={'width_ratios':[1.1,1]})
 ax=axes[0];ys=list(range(len(gap)))
 ax.errorbar(gap.estimate,ys,xerr=[gap.estimate-gap.ci_low,gap.ci_high-gap.estimate],fmt='o',color='#b54b42',capsize=4)
 ax.set_yticks(ys,[display[x] for x in gap.index],fontproperties=font);ax.invert_yaxis();ax.axvline(0,color='#777',lw=1)
 ax.set_xlabel('추가 대기일 (180일 상한)',fontproperties=font);ax.set_title('출전 지연과의 보정 연관성',fontproperties=font)
 t=a[a.family.eq('tendon_ligament')&a.target.str.startswith('top3')].sort_values('horizon');ax=axes[1]
 ax.errorbar(t.estimate*100,t.horizon,xerr=[(t.estimate-t.ci_low)*100,(t.ci_high-t.estimate)*100],fmt='o',color='#356b8c',capsize=4)
 ax.set_yticks([1,2,3],['첫 경주 n=45','두 번째 n=35','세 번째 n=21'],fontproperties=font);ax.invert_yaxis();ax.axvline(0,color='#777',lw=1)
 ax.set_xlabel('3위 이내 비율 차이 (%p)',fontproperties=font);ax.set_title('건·인대·건초 문구 이후 복귀 성적',fontproperties=font)
 fig.suptitle('2024~2025년 관측 진료와 이후 출전·성적',fontproperties=font,fontsize=15)
 fig.text(.5,.035,'점은 보정 차이, 막대는 95% 구간. 복귀 성적의 항목 간 검정에서는 확정 저하 없음. 세 번째는 표본 부족.',ha='center',fontproperties=font,fontsize=10)
 for ax in axes:ax.grid(axis='x',alpha=.2)
 fig.tight_layout(rect=[0,.08,1,.94]);fig.savefig(O/'medical_associations.png',dpi=180);plt.close(fig)
 body='''# 최근 의료기록과 출전 공백 및 복귀 성적

말의 기본 능력과 진료 전 성적을 고려해도 골절 문구, 건·인대·건초 관련 문구, 관절경·거세 술후처치, 파행 등은 이후 출전이 늦어지는 방향이었다. 복귀한 말의 경기력에서는 건·인대 관련 첫 경주 저하와 구절염·진정처치의 세 번째 경주 입상 저하가 후보로 나왔다. 다만 **복귀 성적끼리 별도로 다중비교하면 확정 저하는 없으며, 두세 경주 지속 저하도 확정하지 못했다.** 임상 중증도·치료의 인과효과·예측 개선을 추정한 결과는 아니다.

## 대상과 비교 기준

서울·부산의 최신 연도별 API16 수집본에서 공식 말 번호가 연결되는 관측 집단을 사용했다. 과거 Text와 다른 API 수집본은 중복·공식 번호 문제로 합치지 않았다. 주 분석은 2024~2025년 기준주 70,587개·1,621두, 별도 확인은 2024년 23,477주·864두, 2025년 47,110주·1,603두, 2026년 1월 5일~3월 16일 14,797주·1,724두다. 전체는 85,384주·1,794두이며 연도별 말 수를 합한 값이 아니다.

매주 월요일 직전 7일의 진료를 확인하고 월요일 이후를 추적했다. 직전 실제 출전이 8~180일 전이고 노출 주보다 앞선 8~365일 사이에 진료 관측이 있었던 말만 비교했다. 비교군을 미래에 진료받은 말이라는 이유로 소급해 만들지 않았다. 이 요건은 관측 이력이 있는 집단 안에서 비교하기 위한 것이며 전체 경주마의 의료기록 완전성을 보증하지 않는다. 마지막 기준주도 180일을 모두 추적할 수 있도록 2026년 3월 16일로 제한했다. 경주 원천은 공통 9월 18일 종료 범위를 기준으로 삼았고 실제 포함된 후속 출전의 최종 날짜는 9월 12일이다. 기준주 2024년 1월 1일의 노출은 2023년 12월 25~31일에 해당한다.

진료 항목 720개 원문을 33개의 명시적 문구 분류로 묶었다. 좌·우 등의 부위 표기를 묶은 연구 분류이며 확정 질병이나 임상 중증도 사전이 아니다. 두 진료 칸을 각각 보존하고 쉼표 원문을 새로 분해하지 않았다. 1개 원문은 규칙 우선순위에 따라 한 분류로만 배정하며 실제 복합질환을 완전히 복원하지 못한다. 같은 말·분류의 기록이 14일 넘게 끊긴 후 다시 나오면 새 시작 후보, 그 외 최근 주의 기록은 이어지는 진료로 구분했다. 7일 기준에서도 재추정했다. 정확한 원문과 분류는 `outputs/raw_phrase_family_mapping.csv`에 전부 남겼다.

새 진료와 이어지는 진료, 다른 항목의 동시 관측을 함께 모형에 넣었다. 기준은 해당 항목이 최근 주에 관측되지 않은 상태이며, 건강함을 뜻하지 않는다. 관측 주 수는 실제 병원 방문이나 임상적으로 독립적인 발병 건수가 아니다.

## 출전 공백

출전까지 남은 시간을 기준주부터 180일까지 계산했다. 180일 안에 출전하지 않으면 대기일을 180일로 두었다. 따라서 아래 숫자는 복귀한 말만의 평균 복귀일이나 진료일부터의 평균 공백이 아니라 **같은 말의 능력과 이전 상태를 고려한 180일 제한 대기기간의 차이**다. 30·60·90·180일 미출전도 각각 평가했다.

__GAP_TABLE__

모두 주 분석 전체 561개 항목·지표 비교에서 BH q<0.05이고 기본 표본 지원을 갖췄다. 골절 문구의 180일 미출전 차이는 +44.1%p(95% 35.5~52.7), 건·인대·건초 문구는 +16.4%p(4.1~28.7), 파행은 +2.5%p(1.0~3.9)다. 파행의 30일 미출전 차이는 +19.4%p(16.7~22.2)로 짧은 기간의 지연이 더 컸다.

7일 묶음으로 바꾸어도 골절 +60.4일, 건·인대 +39.9일, 관절경 술후처치 +34.6일, 파행 +12.8일로 주요 방향이 유지됐다. 처치 기록과의 연관성을 처치가 출전을 늦춘 원인으로 읽지 않는다. 관절경 술후처치의 날짜가 수술 시행일이라는 뜻도 아니다.

## 복귀 첫 경주와 이후 두세 경주

기준주 후 180일 안의 실제 출전 순서 1·2·3번째를 각각 평가했다. 주행중지·실격은 실제 출전에 남겨 3위 이내 여부는 0, 상대착순은 최하단으로 표시했다. 이때 실제 착순을 91위·92위로 계산하지 않았으며 정상 완주시간도 만들지 않았다. 제외·취소는 실제 출전 순서에서 뺐다. 각 단계의 분모는 따로 두었다.

| 구분 | 첫 경주 | 두 번째 | 세 번째 |
|---|---:|---:|---:|
| 주 분석에서 180일 안에 출전 확인 | 65,446주 | 61,463주 | 55,613주 |
| 유효 기록 확보 | 65,344주 | 61,387주 | 55,567주 |
| 건·인대·건초 새 진료 후 출전 | 45주·40두 | 35주·32두 | 21주·19두 |
| 해당 문구의 3위 이내 비율 보정 차이 | −13.5%p | −3.7%p | +7.7%p |
| 해당 차이의 95% 구간 | −22.4~−4.5%p | −12.7~+5.3%p | −5.2~+20.6%p |

건·인대 문구의 첫 경주 상대착순 악화는 +0.071(95% 0.026~0.116), 기록 차이는 +0.196초/1000m(0.058~0.334)였다. 상대착순은 0이 선두·1이 최하단이므로 양수가 악화다. 기록은 같은 경주의 정상 완주시간 중앙값 대비 차이를 1000m 단위로 표시했고 같은 경주 고정효과로 공통 조건을 고려했다. 일별 주로빠르기 보정이나 운영 기록 환산표를 만든 것은 아니다.

전체 지표 BH에서 첫 경주 3개 지표의 q는 0.020·0.014·0.031이지만, 복귀 성적 297개 비교만 따로 검정하면 모두 q=0.340이다. 구절염의 세 번째 경주 입상 −7.1%p(−12.2~−2.0), 진정처치 −4.1%p(−6.6~−1.5)도 전체 지표에서는 q=0.037·0.012이나 복귀 성적만 보면 q=0.342·0.340이다. 많은 출전 지연 신호가 성적 검정의 유의성 판단에 영향을 주는지를 확인하려고 이 영역별 검정을 결과 확인 후 추가했으며, 이 구분을 숨기지 않는다. **복귀 성적 저하는 후보로 남기고 확정 결과로 채택하지 않는다.**

복귀 간격과 마체중을 추가로 고려한 경우 건·인대의 첫 경주 입상 차이는 −12.9%p, 기록은 +0.179초/1000m로 방향이 비슷했지만 여러 성적 비교를 고려한 유의성은 확보되지 않았다. 두 번째 경주 차이는 불명확하고 세 번째는 표본 지원이 부족하다. 이를 두세 경주면 회복한다는 근거로 해석할 수 없다. 각 단계에서 복귀한 말의 구성이 달라진다.

근육통·감기·각막찰과상·피로회복 등의 관측에서도 복귀 성적의 뚜렷한 저하를 확인하지 못했다. 이것만으로 가벼운 질병이나 영향 없는 항목으로 분류하지 않는다. 일부 항목은 다음 출전이 오히려 가까운 방향인데, 출전 준비 중의 관리·기록 선택·회복 후 출전 판단이 섞일 수 있어 질환이나 처치가 경기력을 개선했다고 읽지 않는다.

## 미복귀까지 함께 읽으면

골절 문구의 새 시작 79주 중 180일 안에 첫 출전이 있는 것은 18주, 세 번째는 9주뿐이다. 관절경 술후처치는 58주 중 첫 출전 3주·세 번째 1주다. 이 소수의 성적만 보고 장기 영향이 없다고 판단하면 출전 지연을 놓친다.

그래서 각 경주 순서에 대해 **180일 안에 그 순서의 출전에 도달하지 못했거나, 도달했지만 3위 이내가 아님**도 평가했다. 골절 문구는 첫·둘째·셋째에서 이 불리한 결과가 각각 +23.9·+17.7·+10.7%p였고, 이 영역 99개 비교의 BH q도 0.05 미만이었다. 건·인대 문구는 첫 경주 +15.8%p, 파행은 두 번째 +4.1%p가 이 기준을 통과했다. 이는 출전 기회와 성적을 합친 결과이며, 복귀 후 세 경주 동안 계속 느렸다는 뜻은 아니다.

## 연도와 최근 확인

2025년만 분석해도 골절 문구 +61.5일, 건·인대 +37.4일, 파행 +11.9일의 지연이 전체 지표 다중비교 후 남았다. 관절경 술후처치는 +19.8일이나 전체 지표 q=0.074이고 출전 공백만 검정하면 q=0.024여서 근거 강도가 낮다.

2026년 첫 분기는 골절 새 시작 28주, 건·인대 8주, 관절경 술후처치 20주로 기본 지원 기준 30주에 못 미친다. 파행은 211주에서 +4.5일(0.4~8.6)이었지만 전체 지표·영역별 다중비교를 통과하지 못했다. 2026년에는 11개 기준일만 있어 기준일 공통 변화에 대한 불확실성도 크다. 복귀 성적 저하는 이 기간에서도 확정하지 못했다. 2024·2025년 차이를 넘어 최근 효과가 같거나 사라졌다고 단정하지 않는다.

## 보정 방법과 한계

출전 공백에는 같은 말 고정효과와 지역별 기준주 고정효과를, 복귀 성적에는 같은 말과 해당 경주 고정효과를 적용했다. 진료 노출 주보다 앞선 마지막 출전의 순위·입상·상대기록, 최근5전 성적·기록, 나이·레이팅·등급·거리·부담중량·마체중·과거 출전 간격·경력·관측 이력과 과거 연도 기수·마방 수준을 고려했다. 복귀 성적에서는 출전 당시 부담중량·상대게이트·직전 대비 거리/등급 변화·이전 연도 기수/마방 수준도 고려했다. 두세 번째 경주에서도 진료 전 상태를 유지하고 첫 복귀 결과를 직전 성적 통제로 다시 넣지 않았다.

출전 간격 자체가 결과인 공백 분석에서 복귀 후 간격을 보정으로 제거하지 않았다. 복귀 성적의 주 분석도 복귀 간격·복귀 마체중을 제외하고 이를 포함한 조건부 비교를 별도 제시했다. 고정효과는 후향적으로 추정한 같은 말의 기본 수준으로 실시간 사전 능력 점수가 아니다. 같은 진료 주·말·미래 출전이 여러 관측에서 겹치므로 독립 건수로 간주하지 않았다. 말·기준일 군집과 성적의 해당 경주 군집을 고려하고 단일/이중 군집 분산 중 큰 값을 사용했다.

항목별 기본 지원은 새 시작 30주·20두 및 해당 항목 관측/미관측이 모두 있는 말 20두다. 지원이 부족한 항목도 결과와 미식별 상태를 숨기지 않고 전체 검정에 남겼다. 주 분석의 새 시작 561개 비교는 출전 공백 165개·복귀 성적 297개·미복귀/비입상 결합 99개다. 이 중 실제 지원된 비교는 각각 155·258·93개다. 이어지는 진료도 별도 동일 범위로 평가했으나 긴 치료 중인 말이 여러 주 반복되는 조건부 관측이므로 새 발병의 효과와 같지 않다.

현재 API의 역사적 말 모집단 누락과 진료 누락 여부는 해결되지 않았다. 특히 은퇴한 말까지 전체 장기 위험을 대표한다고 볼 수 없다. 여기서 미출전은 현재 스냅샷에 실제 출전이 관측되지 않은 상태이며 은퇴·이적·사망·질병 원인을 구분한 값이 아니다. 진료일과 공개일도 다르고 최초 공개 시각이 확인되지 않아 운영 예측의 경기 전 정보로 곧바로 사용할 수 없다. 진료 강도·정확한 수술일·검사결과·회복 상태·훈련·출전 결정 등의 관측되지 않은 차이가 남는다. 임상 경증/중증 또는 인과효과 판정, 자동 기록 감점과 운영 반영은 하지 않았다.

## 검증과 재현

순서대로 `prepare.py`, `analyze.py`, `verify.py`, `report.py`를 프로젝트 `.venv/bin/python`으로 실행한다. 41개 모형 전체를 고정효과의 정확한 희소 투영·SVD로 추정하고 별도 전체 설계 희소 LSQR로 재현했다. 최대 예측값 오차는 4.87e-9, 항목 계수 오차는 9.02e-10이었다. 전수 노출일·복귀 순서·이전5전과 다중비교를 독립 계산해 검증했다. 상세 건수는 `outputs/verification.json`에 있다. 원 DB는 읽기 전용이며 원문·이전 연구·운영을 수정하지 않았다.

![출전 지연과 복귀 성적의 불확실성](outputs/medical_associations.png)

[전체 항목 요약](outputs/item_summary.csv) · [모든 보정 결과](outputs/adjusted_associations.csv) · [연도별 주요 항목](outputs/annual_key_items.csv) · [설계](design.json) · [출처](SOURCES.md) · [게시 요약](PUBLICATION.md) · [파일 용량](outputs/artifact_inventory.json)
'''
 body=body.replace('__GAP_TABLE__',table)
 # Correct the observed number of calendar landmarks from the data rather than assuming full quarter weeks.
 d=pd.read_parquet(O/'landmark_rows.parquet',columns=['year','index_date']);weeks=d[d.year.eq(2026)].index_date.nunique()
 body=body.replace('11개 기준일만',f'{weeks}개 기준일만')
 (H/'README.md').write_text(body)
 publication='''# 의료기록 이후 출전 지연과 복귀 성적

최근 관측 자료에서는 말의 기본 능력과 진료 전 성적을 고려한 뒤에도 골절 문구, 건·인대 관련 문구, 파행과 일부 술후처치 기록이 출전 지연과 연결됐다. 반면 복귀 첫 경주나 이후 두세 경주의 경기력이 지속해서 낮아진다는 결론은 아직 확정하지 못했다.

2024~2025년 1,621두·70,587개 주간 관측에서, 기준주 이후 대기기간을 180일까지 계산한 보정 차이는 골절 문구 +62.9일, 건·인대 +38.7일, 관절경 술후처치 +35.7일, 거세 술후처치 +21.4일, 파행 +12.5일이었다. 실제 평균 진료 공백이나 처치의 인과효과가 아니라 관측 진료와의 조건부 차이다.

건·인대 관련 첫 복귀 경주는 입상률 −13.5%p, 상대기록 +0.196초/1000m의 저하 후보였다. 복귀 성적끼리 여러 항목을 검정하면 확정 수준에 못 미쳤고, 두 번째는 차이가 불명확하며 세 번째는 관측 21주로 표본이 부족했다. 이 숫자로 두세 번 뛰면 회복한다고 해석하면 안 된다.

골절 문구 79개 새 시작 관측 중 180일 안에 첫 출전이 확인된 것은 18개였다. 돌아온 말의 성적만 보면 출전하지 못한 사례를 놓친다. 따라서 출전 공백과 복귀 성적을 함께 읽어야 한다. 2025년에도 주요 지연 방향이 남았지만 2026년 첫 분기에서는 표본과 불확실성 때문에 재확정하지 못했다.

진료 미관측은 건강함을 뜻하지 않는다. 이 결과는 공식 말 번호로 연결되는 관측 집단에 한정되며 은퇴마를 포함한 전체 위험이나 임상 중증도를 대표하지 않는다. 연구 후보이며 운영 예측과 자동 감점에는 적용하지 않았다.
'''
 (H/'PUBLICATION.md').write_text(publication)
 central='''# 의료 항목별 출전 공백과 복귀 성적

이전 [분석 가능성 점검](55_MEDICAL_RECORD_FEASIBILITY.md)은 공식 번호·진료일의 경주 연결만 확인했다. 이번에는 최근 자료로 출전 공백과 이후 1·2·3번째 실제 출전의 성적을 추정했다. 독립 의료 성과 연구로 등록하되 운영 적용은 하지 않는다.

주 분석은 2024~2025년 1,621두·70,587주이며, 2026년 첫 분기 14,797주를 별도 확인했다. 같은 말의 능력·진료 전 성적과 경주 조건을 고려한 180일 제한 추가 대기기간은 골절 문구 +62.9일, 건·인대 +38.7일, 관절경 술후처치 +35.7일, 거세 술후처치 +21.4일, 파행 +12.5일이었다. 7일/14일 진료 묶음에서도 주요 방향이 유지됐다. 평균 임상 회복기간이나 인과효과가 아니다.

건·인대 첫 복귀 저하(입상 −13.5%p·기록 +0.196초/1000m)는 전체 지표 BH에서는 남았지만 복귀 성적만 따로 검정하면 q=0.340으로 후보 수준이다. 구절염·진정처치의 세 번째 입상 저하도 검정 범위에 민감하다. 복귀 성적 영역에서 확정 저하는 0개이고 두세 경주 지속 또는 회복은 미확정이다. 미복귀·비입상을 함께 보면 골절 문구는 첫/둘째/셋째 순서의 불리한 결과가 각각 +23.9/+17.7/+10.7%p로 남았다. 이는 복귀한 말이 세 번 연속 부진했다는 뜻이 아니다.

2025년 주요 출전 지연은 유지됐으나 2026년 첫 분기에는 지원 부족과 다중비교 불확실성으로 재확정하지 못했다. 현재 API의 모집단·진료 누락 및 과거 공개 시점의 한계가 남는다. 경증/중증, 치료의 인과효과 또는 경기 전 예측 개선으로 해석하지 않는다.

[원 보고서](../20261014_medical_item_outcomes/README.md) · [전체 항목 표](../20261014_medical_item_outcomes/outputs/item_summary.csv) · [검증](../20261014_medical_item_outcomes/outputs/verification.json) · [게시 요약](../20261014_medical_item_outcomes/PUBLICATION.md)
'''
 (H.parent/'conclusions/55A_MEDICAL_ITEM_OUTCOMES.md').write_text(central)
 print('reports and figure written',flush=True)
if __name__=='__main__':main()
