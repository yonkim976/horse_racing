"""Publish evidence tables and readable Korean research figures from saved results."""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures'
LABELS={'retained_ordinary':'보통 기수 유지','retained_top':'상위 기수 유지','ordinary_to_top':'보통→상위 교체','top_to_top':'상위→상위 교체','top_to_ordinary':'상위→보통 교체','ordinary_to_ordinary':'보통→보통 교체','upgrade_vs_retained_top':'교체 상위−유지 상위','upgrade_vs_ordinary_switch':'상위 교체−보통 교체'}
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'---|'*len(headers)]+['| '+' | '.join(map(str,row))+' |' for row in rows])
def clean(frame):return json.loads(frame.to_json(orient='records',force_ascii=False,double_precision=15))
def main():
    m=pd.read_csv(O/'category_metrics.csv');e=pd.read_csv(O/'adjusted_associations.csv');j=pd.read_csv(O/'destination_jockey_metrics.csv',dtype={'jockey_id':str});pairs=pd.read_csv(O/'trainer_jockey_pair_metrics.csv',dtype={'trainer_id':str,'jockey_id':str});pref=pd.read_csv(O/'preferred_booking_metrics.csv');dist=pd.read_csv(O/'distance_time_associations.csv');sens=pd.read_csv(O/'sensitivity.csv');cal=pd.read_csv(O/'same_calendar_year_associations.csv');joint=pd.read_csv(O/'destination_switch_associations.csv');audit=json.loads((O/'source_audit.json').read_text());v=json.loads((O/'verification.json').read_text());assert v['passed']
    a=m[(m.window=='2024_2025')&m.meet.eq('전체')].set_index('category');b=e[(e.window=='2024_2025')&e.meet.eq('전체')&e.model.eq('race_horse_controls')]
    chosen=j[j.window.eq('2024_2025')&j.jockey_name.isin(['문세영','서승운','다실바','김혜선'])].sort_values(['meet','jockey_name']);ps=pairs[pairs.window.eq('2024_2025')].sort_values('n',ascending=False)
    primary=b[b.term.eq('ordinary_to_top')].set_index('target');upgrade=primary.loc['top3'];rank=primary.loc['finish_p'];time=primary.loc['time_gap'];contrast=b[b.term.eq('upgrade_vs_retained_top')&b.target.eq('top3')].iloc[0]
    rows=[[LABELS[c],f'{int(a.loc[c,"n"]):,}',f'{100*a.loc[c,"top3_rate"]:.2f}%',f'{100*a.loc[c,"previous_top3_rate"]:.2f}% → {100*a.loc[c,"paired_current_top3_rate"]:.2f}%',f'{100*a.loc[c,"rank_improvement_mean"]:+.2f}점'] for c in ['retained_ordinary','retained_top','ordinary_to_top','top_to_top','top_to_ordinary','ordinary_to_ordinary']]
    rawtable=table(['구분','출전','현재 입상률','동일 출전쌍의 직전→현재 입상률','상대착순 개선'],rows)
    riderstable=table(['교체 후 기수','지역','교체 출전','직전→현재 입상률','상대착순 개선'],[[r.jockey_name,r.meet,r.n,f'{100*r.previous_top3_rate:.2f}% → {100*r.paired_current_top3_rate:.2f}%',f'{100*r.rank_improvement_mean:+.2f}점'] for r in chosen.itertuples()])
    pairstable=table(['조교사→기수','지역','교체 출전','직전→현재 입상률'],[[r.trainer_name+'→'+r.jockey_name,r.meet,r.n,f'{100*r.previous_top3_rate:.2f}% → {100*r.paired_current_top3_rate:.2f}%'] for r in ps.itertuples()])
    regional=e[e.model.eq('race_horse_controls')&e.target.eq('top3')&e.term.eq('ordinary_to_top')]
    adjtable=table(['기간','지역','조정 입상률 차이','95% 구간','BH q'],[[r.window,r.meet,f'{100*r.estimate:+.2f}%p',f'{100*r.ci_low:+.2f}~{100*r.ci_high:+.2f}%p',f'{r.q:.3f}'] for r in regional.itertuples()])
    seltop=joint[joint.window.eq('2024_2025')&joint.target.eq('top3')];significant=int(seltop[seltop.q<.05].shape[0]);assert significant==0
    pref_e=e[e.window.eq('2024_2025')&e.model.eq('preferred_among_switches')&e.target.eq('top3')&e.term.eq('to_preferred')].iloc[0]
    prefraw=pref[pref.window.eq('2024_2025')].set_index('preferred');case=pd.read_csv(O/'illustrative_cases.csv');case_text='\n'.join(f'- {r.date[:10]} {r.meet} {int(r.distance_m)}m {r.horse_name}: {r.trainer_name} 조교사·{r.jockey_name} 기수로 교체, 직전 {int(r.previous_raw_finish_rank)}위 → 현재 {int(r.raw_finish_rank)}위. 예시일 뿐 성공률 추정은 위 전체 표본으로 한다.' for r in case.itertuples())
    method='''상위 기수는 현년도 결과를 보지 않고 **전년도 같은 지역 정상 기승100회 이상** 중, 지역 평균50회 강도로 완화한 입상률 상위20%(올림)다. 직전 기수도 현재 출전연도의 같은 기준으로 재평가한다. 이름 대신 출전 당시 ID를 연결했다. 최소 기승 미지원은 보통 기수로 채우지 않는다. 신인·새 외국 기수의 일부는 이 기준으로 평가되지 않는다.

말별 전체 실제 출전에서 바로 직전 슬롯을 사용한다. 현재 정상 착순, 직전2~180일, 같은 지역·같은 조교사, 양 기수 순위지원이 주표본이다. 직전 이상 결과를 건너뛰지 않고 과거 성적 결측을 표시한다. 같은 현재 경주와 같은 말 고정효과, 직전/과거5전 착순·관측수, 휴양, 거리·등급 변화, rating·연령·부담중량·마체중·게이트·직전 기수 전년도 성적을 통제했다. 같은 경주 효과가 편성·거리·함수율·월 등 공통조건을 흡수한다. 현 경주 실제 전개·배당을 통제하지 않았다.

군집 구간은 말·날짜·이원 군집 중 최대 분산에 고정효과와 회귀 순위를 포함한 잔여 자유도 보정을 더했다. 같은 표본에서 여러 비교를 하므로 각 기간×지역×모형×성과군의 BH q도 제공한다. 회귀는 관찰된 가법 연관성이다. 개인 입상확률·무작위 배정 실험·독립 미래 검증이 아니다.'''
    key=f'''**상위 기수로 교체되는 출전에는 성적 개선 연관성이 있다. 그러나 ‘기수 교체는 조교사·마주의 승부의지다’라는 명제는 직접 입증되지 않는다.**

2024~2025 서울·부산 주표본26,109출전 중 보통→상위 교체2,283출전의 입상률은35.87%, 보통 기수 유지9,879출전은28.90%였다. 같은 말·현재 편성·이전 성적·휴양·거리/등급 변화·중량 등을 고려하면 차이는 **{100*upgrade.estimate:+.2f}%p(95% {100*upgrade.ci_low:+.2f}~{100*upgrade.ci_high:+.2f}%p, q={upgrade.q:.3f})**다. 기존에 좋은 말이 상위 기수에게 배정되는 부분을 고려해도 이 표본에서 양의 연관성이 남았다.

반면 모든 교체를 합치면 입상률은26.62%, 유지는32.66%다. 교체 전 성적도20.75%와41.82%로 크게 다르다. 부진 뒤 기수 교체, 좋은 성적 뒤 기수 유지라는 선택과 평균으로의 회귀가 섞여 있어, 교체 전후 반등을 전부 기수나 의지의 효과로 볼 수 없다.'''
    record=f'''보통→상위 교체의 상대착순은 통제 후 **{-100*rank.estimate:.2f}점 개선**되는 연관성(0=1위·100=최후위)이 남았다. 현재 경주 우승마와의 전체시간 차이는 **{-time.estimate:.3f}초 작았다**(시간차 차이95% {time.ci_low:+.3f}~{time.ci_high:+.3f}초). 이 수치는 관측 거리들을 섞은 회귀 평균이다. 거리별10개 지원 조합에서는 모두 신뢰구간에0이 포함되어 **말 기록에서 일괄0.14초를 빼는 보정표로 쓸 근거는 부족하다**. 같은 지역·정확 거리·등급을 연속 출전한 경우의 원시 시간 변화도 별도 표에 남겼으며, 날짜·주로·편성이 바뀌는 기술량이다.

상위 기수 교체와 상위 기수 유지의 조정 차이는 **{100*contrast.estimate:+.2f}%p(95% {100*contrast.ci_low:+.2f}~{100*contrast.ci_high:+.2f}%p)**로 구분되지 않았다. 이는 결과를 본 뒤 추가한 탐색 대비다. 기수 수준의 연관성과 ‘이번에 바꿨으니 특별한 의지가 추가됐다’는 설명은 분리해야 한다.'''
    relation=f'''전년도 조교사의 최다 기용 기수를 선호 후보로 정했다(조교사50회·그 기수20회 이상, 점유율15% 이상). 이미 교체한 출전 중 선호기수 기용은{int(prefraw.loc[True,'n']):,}출전·입상{100*prefraw.loc[True,'top3_rate']:.2f}%, 기타는{int(prefraw.loc[False,'n']):,}출전·{100*prefraw.loc[False,'top3_rate']:.2f}%다. 같은 말·경주·기수 수준·기존 상태를 고려한 차이는 **{100*pref_e.estimate:+.2f}%p(95% {100*pref_e.ci_low:+.2f}~{100*pref_e.ci_high:+.2f}%p)**로 추가 이점을 확인하지 못했다.

아래는 최소50교체·20말·20경주를 충족한 **모든6조합**이다. 해당 기수로 바꾸기 전 말 성적이 서로 다르므로 조합 능력이나 승부의지 순위가 아니다. 표본이 작은 기술표이며 쌍별 인과효과는 추정하지 않았다.

{pairstable}

동일 마주 출전만 남긴 민감도에서도 상위 교체 차이는+4.30%p(95% +1.28~+7.33%p)였다. 마주별 지시·사전 승부 계획·기수의 당일 가용성·부상/기승정지 정보는 없어 조교사와 마주의 의지를 각각 분리할 수 없다.'''
    limitations='''2026은 서울9월20일·부산9월18일까지의 부분연도다. 합산 조정 입상률은양의 방향이지만, 다중비교 q가0.05를 넘고 시간차 구간은0을 포함한다. 같은9월18일까지의 연도별 추가 분석도 표로 보존했으며, 기간별 효과 크기 변화나 독립 재현을 확정하지 않았다. 상위30%로 완화하면 입상 차이 구간이0을 포함한다. 같은 마주·직전 정상 결과·730일·최소50회 기준은 대체로 양의 방향이다.

같은 말 고정효과도 당일 컨디션·조교 상태·출전 계획·기수 가용성에 의한 배정 선택을 제거하지 못한다. 실제 조교사/마주의 의사결정 원문이 없어 승부의지의 정답 라벨이 없다. 기용 변화와 성과의 관계를 확인한 연구이며, 승부의지 감지나 미래 예측 개선을 검증한 연구가 아니다.''' 
    publication=f'''# 기수 교체·상위 기수와 조교사 기용 관계

2026-10-12 · 서울·부산 · 관찰 연구 후보 · 운영 미반영

{key}

{rawtable}

입상은3위 이내. 전후 입상률은 직전 정상 결과가 있는 동일 출전쌍의 분모다. 전체 현재율과 미세하게 다를 수 있다. 상대착순 개선은 직전 상대착순−현재 상대착순×100이며 양수일수록 개선이다.

![기수 교체별 관측 입상률](figures/category_rates.png)

{record}

{adjtable}

![조건 통제 후 연관성](figures/adjusted_effects.png)

특정 기수로 바뀐 경우에도 관측 차이가 있었다. 다음4명은 원자료에서 높은 기수 등급을 가진 대표 사례이며, 최소100교체·30말·30경주를 충족한 전체54명 표를 별도로 공개한다.

{riderstable}

이 수치는 그 기수의 전체 기승 입상률이 아니라 **연구 조건을 충족한 교체 출전**의 입상률이다. 같은 기수가 계속 타던 출전과 비교한 기수별 통제 모형에서는54명과 기타집단을 포함한 모든 비교에서 다중비교 후 입상률의 추가 교체 효과가 확정되지 않았다. 특정 기수 기용 자체와 ‘교체했으므로 특별히 달라지는 효과’를 혼동하지 않는다.

{relation}

![조교사·기수 조합의 전후 성과](figures/trainer_pairs.png)

관측 사례는 표본이 가장 큰4조합에서 입상·비입상 각각 첫 날짜를 고른 것이다. 좋은 사례만 고르지 않았다.

{case_text}

{limitations}

기록을 읽을 때는 ‘승부의지 확정’ 대신 **기수 수준 변화·해당 말과의 재기승·조교사 기용 점유율·교체 전 부진/휴양/승급**을 함께 보는 근거로 쓸 수 있다. 다음 모델 시험에는 이 과거 입력들의 추가 예측 가치를 따로 검증해야 한다.

[전체 방법](README.md) · [출처](SOURCES.md) · [기수 전체표](outputs/destination_jockey_metrics.csv) · [조교사 조합](outputs/trainer_jockey_pair_metrics.csv) · [검증](outputs/verification.json).
'''
    (H/'PUBLICATION.md').write_text(publication)
    report=f'''# 기수 교체·상위 기수·조교사 관계 연구

{key}

대상:2018~2026 전체159,014실제 출전·14,636경주·12,516마리. 전년도 이력 분류 후2024~2025 주표본26,109출전·3,497경주·3,854마리,2026부분9,024출전. 서울 종료2026-09-20·부산2026-09-18. 전체 원문기록을 연속 슬롯에 사용하고 정상 구간151,074모집단은 시간 성과에만 사용했다. 원천 API 보관 파일18개와 검증 파생자료2개를 입력 해시로 고정했다.

{method}

{rawtable}

{record}

{adjtable}

{riderstable}

{relation}

{limitations}

기수ID에영문자가 포함된55출전을 원문에서 복원했다. 이전 파생자료의 숫자 전용 필터를 이번 새 연구에 그대로 적용하지 않았다. 이들 원문과 모든159,014출전의 기수·조교사·마주·순위·시간·중량을 재대조했다. [방법 추가기록](METHOD_NOTES.md)에 계산 변경과 탐색 대비를 구분했다. 원문과 이전 연구를 수정하지 않았다.

독립 검증은 총{v['checks']:,}값/조건 대조를 통과했다. DuckDB LAG로 실제 직전 슬롯, 전년도 기수 순위1,166행·조교사 선호1,115행, 모든 원시 집계와 BH를 재계산했다. 희소 전체 고정효과 LSQR(분석의 LU 투영과 다른 경로)로 주3성과 회귀 계수·군집 구간을 독립 대조했다. 실제 확률모델 학습·운영 적용·DB 변경·배포는 없다.

결과 파일: category_metrics.csv(전체/6분류), adjusted_associations.csv(편성/말 통제), destination_jockey_metrics.csv(특정 기수), destination_switch_associations.csv(같은 기수의 교체/유지), trainer_jockey_pair_metrics.csv(모든 지원6조합), preferred_booking_metrics.csv, distance_time_associations.csv(정확 거리별 시간), sensitivity.csv, same_calendar_year_associations.csv(추가 탐색), coverage.csv(누적 제외), annual_jockey_rankings.csv, annual_trainer_preference.csv, model_diagnostics.csv. 모두 [outputs](outputs/artifact_inventory.json)에 보존했다.

재현: 프로젝트 .venv에서 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1을 설정하고 이 폴더의 analyze.py → verify.py → publish.py를 실행한다. 공유 목록 등록은 register.py의 일회성 작업이며 일반 분석 재현에서는 실행하지 않는다. final_review.py 후 record_inventory.py를 실행하면 완료 기록까지 포함한 용량이 고정된다. 현재 출판 수치의 원천은 CSV·PUBLICATION.json이다.

[결과를 읽는 요약](PUBLICATION.md) · [분석 전 계획](PLAN.md) · [출처/해시](SOURCES.md) · [검증](outputs/verification.json) · [중앙 결론](../conclusions/50_JOCKEY_SWITCH_TRAINER_INTENT.md) · [용량](outputs/SIZE_REPORT.md).
'''
    (H/'README.md').write_text(report)
    src='# 출처·계보\n\n마사회 실전 경주결과 보관 원문을 재사용했다. 외부 조회 없이 아래 동결 파일의 출전 당시 식별/순위/시간을 사용했다. 기존 각질의 기수 선행성향 점수를 기수 능력 순위로 사용하지 않았다.\n\n'+table(['입력','바이트','SHA-256'],[[r['path'],r['bytes'],r['sha256']] for r in audit['inputs']])+'\n\n주로빠르기 제외. 원문ID의 영문자 보존. 2024/25/26 분류는 각각2023/24/25년만 참조한다. 2027분류 행은 원천 완결성을 위한 보관일 뿐 부분연도2026 기반이며 이번 평가에 사용하지 않았다. 미래 모델 입력에 사용하려면 완결연도 계약을 따로 지켜야 한다.\n\n[전개 원천](../20261008_field_pace_prediction/SOURCES.md) · [정상 시간 모집단](../20261007_sex_ability_gap/SOURCES.md) · [입력 감사](outputs/source_audit.json) · [독립 검증](outputs/verification.json).\n'
    (H/'SOURCES.md').write_text(src)
    payload=dict(title='기수 교체·상위 기수와 조교사 기용 관계',central_document='50',published_on='2026-10-12',status='observational_research_candidate',causal_intent_identified=False,production_changed=False,definition=dict(top='prior calendar year venue-specific shrunk top3 rate; >=100 starts; top ceil(20%)',main='same horse previous actual start within 2~180d, same venue/trainer, both rider ranks supported, normal current finish'),source=audit,category_metrics=clean(m),adjusted_associations=clean(e),illustrative_jockeys=clean(chosen),trainer_jockey_pairs=clean(ps),preferred_metrics=clean(pref),distance_time_associations=clean(dist),sensitivity=clean(sens),same_calendar_year_associations=clean(cal),verification=v,limits=limitations)
    (H/'PUBLICATION.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    plt.rcParams['font.family']=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc').get_name();plt.rcParams['axes.unicode_minus']=False
    order=['retained_ordinary','retained_top','ordinary_to_top','top_to_top','top_to_ordinary','ordinary_to_ordinary'];x=np.arange(len(order));fig,ax=plt.subplots(figsize=(11.5,5));ax.bar(x-.18,[a.loc[c,'previous_top3_rate']*100 for c in order],.36,label='직전 출전',color='#b1bdc9');ax.bar(x+.18,[a.loc[c,'paired_current_top3_rate']*100 for c in order],.36,label='현재 출전',color='#247eaa');ax.set_xticks(x,[LABELS[c]+'\nN='+format(int(a.loc[c,'n']),',') for c in order]);ax.set_ylim(0,65);ax.set_ylabel('입상률 (%)');ax.set_title('기수 교체 전후 관측 입상률 · 서울/부산 2024~2025\n교체·유지는 출전 전 성적이 다르며 인과 비교가 아님');ax.legend();ax.spines[['right','top']].set_visible(False);fig.tight_layout();fig.savefig(F/'category_rates.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4.8));labels=['2024~25 전체','2024~25 부산','2024~25 서울','2026 부분 전체'];combos=[('2024_2025','전체'),('2024_2025','부산'),('2024_2025','서울'),('2026_partial','전체')]
    for ax,target,title,scale in zip(axes,['top3','finish_p','time_gap'],['입상률 차이 (%p)','상대착순 차이 (점, 음수=개선)','우승마 시간차 차이 (초)'],[100,100,1]):
        values=pd.DataFrame([e[(e.window==w)&e.meet.eq(meet)&e.model.eq('race_horse_controls')&e.target.eq(target)&e.term.eq('ordinary_to_top')].iloc[0] for w,meet in combos]);y=np.arange(4);ax.errorbar(values.estimate*scale,y,xerr=np.vstack([(values.estimate-values.ci_low)*scale,(values.ci_high-values.estimate)*scale]),fmt='o',capsize=4,color='#247eaa');ax.axvline(0,color='#999',lw=1);ax.set_yticks(y,labels if target=='top3' else ['']*4);ax.invert_yaxis();ax.set_xlabel(title);ax.spines[['right','top']].set_visible(False)
    fig.suptitle('보통→상위 교체 - 보통 기수 유지 · 같은 말/경주와 이전 상태 통제\n점과95% 군집 구간 · 관찰 연관성, 거리 공통 보정값 아님');fig.tight_layout(rect=(0,0,1,.87));fig.savefig(F/'adjusted_effects.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,5));y=np.arange(len(ps));ax.barh(y-.17,ps.previous_top3_rate*100,.34,color='#b1bdc9',label='직전');ax.barh(y+.17,ps.paired_current_top3_rate*100,.34,color='#247eaa',label='교체 후');ax.set_yticks(y,[r.trainer_name+' → '+r.jockey_name+'  N='+str(r.n) for r in ps.itertuples()]);ax.invert_yaxis();ax.set_xlabel('입상률 (%)');ax.set_title('조교사·기수 교체 조합 · 지원 기준 충족 전체6조합\n직전 말 성적이 서로 다름 · 승부의지/조합 능력 순위 아님');ax.legend();ax.spines[['right','top']].set_visible(False);fig.tight_layout();fig.savefig(F/'trainer_pairs.png',dpi=160);plt.close(fig)
    print('Published reports, structured data and 3 figures')
if __name__=='__main__':main()
