"""Readable Korean findings, chronological cases and verified publication data."""
from pathlib import Path
import json
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';G=H/'figures'
fp=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams.update({'font.family':fp.get_name(),'axes.unicode_minus':False,'font.size':11,'figure.facecolor':'#f6f8fc','axes.facecolor':'white'})
ORDER=[('부산','600'),('부산','400'),('부산','200'),('서울','600'),('서울','200')]
def table(headers,rows):return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)
def pct(x):return f'{100*x:.2f}%'
def diff(r):return f'{100*r.estimate:+.2f} [{100*r.lower:+.2f}, {100*r.upper:+.2f}]'
def clean(df):return json.loads(df.to_json(orient='records',force_ascii=False))
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');metrics=pd.read_csv(O/'cohort_metrics.csv',dtype={'segment':str});comp=pd.read_csv(O/'comparisons.csv',dtype={'segment':str});stages=pd.read_csv(O/'adjustment_stages.csv',dtype={'segment':str});audit=json.loads((O/'source_audit.json').read_text());coverage=pd.read_csv(O/'coverage.csv',dtype={'segment':str})
    primary=metrics[(metrics.window=='2024_2025')&(metrics.definition=='race_fast20')];contrasts=comp[(comp.window=='2024_2025')&(comp.definition=='race_fast20')&(comp.target=='next_top3')]
    rows=[];nextrows=[];three=[];adjustrows=[];pastrows=[];returns=[];confirmation=[]
    def metric(m,s,flag,window='2024_2025',definition='race_fast20'):return metrics[(metrics.window==window)&metrics.meet.eq(m)&metrics.segment.eq(s)&metrics.definition.eq(definition)&metrics.fast.eq(flag)].iloc[0]
    def contrast(m,s,method='raw',target='next_top3',window='2024_2025',definition='race_fast20'):return comp[(comp.window==window)&comp.meet.eq(m)&comp.segment.eq(s)&comp.method.eq(method)&comp.target.eq(target)&comp.definition.eq(definition)].iloc[0]
    for m,s in ORDER:
        a=metric(m,s,True);b=metric(m,s,False);raw=contrast(m,s);adj=contrast(m,s,'same_race_adjusted');same=contrast(m,s,'same_horse')
        rows.append([f'{m} 마지막{s}m',f'{pct(a.next_top3_mean)} ({a.next_top3_n:,})',f'{pct(b.next_top3_mean)} ({b.next_top3_n:,})',diff(raw),diff(adj)])
        nextrows.append(dict(meet=m,segment=s,fast_n=int(a.next_top3_n),fast_rate=float(a.next_top3_mean),other_n=int(b.next_top3_n),other_rate=float(b.next_top3_mean),raw_difference=float(raw.estimate),raw_lower=float(raw.lower),raw_upper=float(raw.upper),raw_bh_q=float(raw.bh_q),adjusted_difference=float(adj.estimate),adjusted_lower=float(adj.lower),adjusted_upper=float(adj.upper),adjusted_bh_q=float(adj.bh_q),adjusted_coverage=float(adj.coverage)))
        three.append([f'{m} {s}m',f'{pct(a.three_top3_mean)} ({a.three_top3_n:,})',f'{pct(b.three_top3_mean)} ({b.three_top3_n:,})',diff(contrast(m,s,target='three_top3')),diff(contrast(m,s,'same_race_adjusted','three_top3'))])
        adjustrows.append([f'{m} {s}m',diff(same),f'{int(same.n_a)}/{int(same.n_b)}',f'{same.coverage*100:.1f}%',f'{same.bh_q:.3g}'])
        a0=metric(m,s,True,definition='prior_fast20');b0=metric(m,s,False,definition='prior_fast20');r0=contrast(m,s,definition='prior_fast20');ad0=contrast(m,s,'same_race_adjusted',definition='prior_fast20');cv=coverage[(coverage.window=='2024_2025')&coverage.meet.eq(m)&coverage.segment.eq(s)&coverage.definition.eq('prior_fast20')].iloc[0]
        pastrows.append([f'{m} {s}m',f'{pct(a0.next_top3_mean)} ({a0.next_top3_n:,})',f'{pct(b0.next_top3_mean)} ({b0.next_top3_n:,})',diff(r0),diff(ad0),f'{cv.supported_n/cv.nonpodium_quality_n*100:.1f}%'])
        returns.append([f'{m} {s}m',f'{pct(a.return180_mean)} ({a.n:,})',f'{pct(b.return180_mean)} ({b.n:,})',f'{a.finish_rank_mean:.2f}/{b.finish_rank_mean:.2f}',f'{a.next_days_median:.0f}/{b.next_days_median:.0f}일'])
        fa=metric(m,s,True,'2026_mature');fb=metric(m,s,False,'2026_mature');rr=contrast(m,s,window='2026_mature');confirmation.append([f'{m} {s}m',f'{pct(fa.next_top3_mean)} ({fa.next_top3_n})',f'{pct(fb.next_top3_mean)} ({fb.next_top3_n})',diff(rr),f'{rr.bh_q:.3g}'])
    pd.DataFrame(nextrows).to_csv(O/'primary_summary.csv',index=False)
    # Cases are illustrative success/failure pairs, selected after analysis by a
    # stated deterministic rule, never presented as prospective predictions.
    case_rows=[]
    for meet in ['부산','서울']:
        pool=d[d.year.eq(2025)&d.meet.eq(meet)&d.normal_outcome&d.raw_finish_rank.gt(3)&d.race_fast20_600.eq(1)&d.next_top3.notna()].sort_values(['date','source_key','gate'])
        for answer in [1,0]:case_rows.append(pool[pool.next_top3.eq(answer)].iloc[0])
    cases=pd.DataFrame(case_rows);casecols=['row_key','horse_id','horse_name','meet','date','source_key','distance_m','raw_finish_rank','time600','race_q20_600','future_key1','future_date1','future_rank1','next_days','next_top3'];cases[casecols].to_csv(O/'illustrative_cases.csv',index=False)
    casetable=[[r.meet,r.horse_name,str(r.date.date()),int(r.raw_finish_rank),f'{r.time600:.1f} / {r.race_q20_600:.1f}',str(r.future_date1.date()),int(r.future_rank1),int(r.next_days)] for r in cases.itertuples()]
    # Figure1: conditional next-start rates and valid denominators.
    fig,ax=plt.subplots(figsize=(12,5));x=np.arange(5);width=.35
    for offset,flag,color,label in [(-width/2,True,'#2864c3','막판 빠른 비입상마'),(width/2,False,'#c1c8d3','다른 비입상마')]:
        vals=[metric(m,s,flag) for m,s in ORDER];bars=ax.bar(x+offset,[r.next_top3_mean*100 for r in vals],width,color=color,label=label)
        for bar,r in zip(bars,vals):ax.text(bar.get_x()+width/2,bar.get_height()+.65,f'{r.next_top3_mean*100:.1f}%\nn={r.next_top3_n:,}',ha='center',va='bottom',fontsize=9)
    ax.set_xticks(x,[m+' '+s+'m' for m,s in ORDER]);ax.set_ylim(0,37);ax.set_ylabel('다음 출전3위 이내율 (%)');ax.set_title('과거 전체에서는 막판 빠른 비입상마의 다음 입상률이 높았다',loc='left',fontweight='bold');ax.legend(frameon=False,loc='upper left');ax.spines[['top','right']].set_visible(False);fig.text(.05,.01,'색인2024~2025 · 180일 내 실제 다음 출전, 정상결승만 · 같은 경주 빠른20% 경계(동률 포함) · 원시 비교',fontsize=10);fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(G/'next_start_rates.png',dpi=140);plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,5));y=np.arange(5)
    for off,method,color,label in [(-.13,'raw','#999','원시 차이'),(.13,'same_race_adjusted','#2864c3','같은 경주·현재 성적·능력·초반 조정')]:
        rs=[contrast(m,s,method) for m,s in ORDER];est=np.array([r.estimate for r in rs])*100;lo=np.array([r.lower for r in rs])*100;hi=np.array([r.upper for r in rs])*100;ax.errorbar(est,y+off,xerr=[est-lo,hi-est],fmt='o',capsize=4,color=color,label=label)
    ax.axvline(0,color='#777',lw=1);ax.set_yticks(y,[m+' '+s+'m' for m,s in ORDER]);ax.invert_yaxis();ax.set_xlim(-6,11);ax.set_xlabel('다음 출전 입상률 차이 (%p), 보수적 군집95%구간');ax.set_title('현재 성적과 초반까지 고려하면 막판만의 추가 차이는 불확실했다',loc='left',fontweight='bold');fig.legend(*ax.get_legend_handles_labels(),frameon=False,loc='lower center',bbox_to_anchor=(.6,.005),ncol=2);ax.spines[['top','right']].set_visible(False);fig.tight_layout(rect=[0,.08,1,1]);fig.savefig(G/'adjusted_next_differences.png',dpi=140);plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,5));colors=['#2766bd','#4c91d0','#87b7d8','#ce6a21','#e3a15a'];stageorder=['race_only','past','finish','full']
    for (m,s),color in zip(ORDER,colors):
        ss=stages[(stages.window=='2024_2025')&stages.meet.eq(m)&stages.segment.eq(s)&stages.definition.eq('race_fast20')].set_index('stage').loc[stageorder];ax.plot(range(4),ss.estimate*100,marker='o',color=color,label=m+' '+s+'m')
    ax.axhline(0,color='#777',lw=1);ax.set_xticks(range(4),['같은 경주만','과거 성적·rating·연령 추가','현재 착순·패배 시간차 추가','초반 위치 추가']);ax.set_ylabel('다음 입상률 차이의 점추정 (%p)');ax.set_title('신호가 겹치는 부분: 현재 착순과 패배 시간차를 추가하면 차이가 줄었다',loc='left',fontweight='bold');ax.legend(frameon=False,ncol=5,loc='lower left');ax.set_ylim(-6,10);ax.spines[['top','right']].set_visible(False);fig.text(.05,.01,'같은 공통경주 표본을 고정한 해석용 탐색 · 구간은 adjustment_stages.csv · 각 단계는 다른 조건부 질문',fontsize=10);fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(G/'adjustment_stages.png',dpi=140);plt.close(fig)
    conclusion='막판이 빠르면서 비입상한 말은 과거 전체에서 다른 비입상마보다 다음 입상률이 대체로 높았다. 그러나 현재 착순·패배 시간차·기존 능력·초반 위치까지 고려한 추가 효과는 불확실했고,2026초반 후속관측에서도 안정적으로 재현되지 않았다.'
    pub=f'''# 막판이 좋았지만 비입상한 말, 다음에는 입상할까

{conclusion}

서울·부산2024~2025의4위이하 출전을 출발점으로,180일 안의 실제 바로다음 출전에서3위 이내에 들었는지 확인했다. ‘막판 좋음’은 그 경주 전체에서 해당구간의 빠른20% 경계 이내(동률포함)다. 입상마도 경계 계산에 포함했다.

{table(['구간','빠른 비입상마 다음입상률(n)','다른 비입상마(n)','원시차이%p[95%]','조건조정 차이%p[95%]'],rows)}

서울600m는28.51% 대22.67%,200m는28.26% 대22.41%였다. 부산400m는26.62% 대22.58%로 차이가 있었지만,부산600m의 원시차이 구간은0을 포함했다. 현재성적 등 조건조정 후에는 다섯 구간 모두 증가를 확정하지 못했다. 이 수치는180일 내 재출전한 말의 집단 관측률이며 개별마의 현재 예측확률이 아니다.

빠른 그룹은 당시에도 평균5~6위,다른 그룹은7~8위였고 재출전율도 높았다. 같은경주와과거능력만 맞추면 신호가 남았지만,현재착순·우승마와의전체시간차를 추가하면 차이가 크게 줄었다. 막판만 독립적으로 좋아졌다고 해석하지 않는다.

180일 내3번 모두 출전해 성적이 확인된 말에서는 서울600m59.63% 대53.30%,200m59.99% 대52.87%가 그3전 중 한 번 이상 입상했다. 부산은53.85/55.30/53.70% 대52.95/52.66/52.94%였고 차이가 불확실했다.3번 출전한 말만 남긴 별도 표본으로,전체 비입상마의180일 입상확률과 다르다.

2026은180일 관측 가능한1월1일~3월22일 출전만 확인했다. 다음입상의 증가가 모든 구간에서 통계적으로 불확실했고,서울600m의 원시차이는 오히려 반대 방향이었다. 같은달범위 비교도 별도로 보존했다. ‘막판이 좋으면 다음에 반드시 입상한다’는 규칙은 뒷받침되지 않았다.

막판기록은 비입상마를 다시 살펴볼 후보 정보로 활용할 근거가 있다. 현재착순·패배시간차·초반위치·거리·기존성적을 함께 봐야 하며 일률적인 확률 가산점은 만들지 않았다. 부산600/400/200과서울600/200을 분리했으며 서울400m는 생성하지 않았다. 중첩구간 점수를 더하지 않는다.

[원 보고서](README.md) · [주검증](outputs/verification.json) · [민감도검증](outputs/sensitivity_verification.json) · [지역거리](outputs/distance_metrics.csv).
'''
    (H/'PUBLICATION.md').write_text(pub)
    data=dict(title='막판 우수·비입상 이후 입상 관측',followup='28H',status='research_candidate',conclusion=conclusion,index_years=[2024,2025],followup_days=180,common_followup_end=audit['common_followup_end'],mature_2026_index_cutoff=audit['mature_index_cutoff'],primary_summary=nextrows,raw_metrics=clean(metrics),contrasts=clean(comp),adjustment_stages_exploratory=clean(stages),same_calendar_confirmation=clean(pd.read_csv(O/'same_calendar_confirmation.csv',dtype={'segment':str})),overlapping_sections_summed=False,Seoul400_generated=False,predictive_models_trained=0,operating_model_changed=False,causal_effect_identified=False)
    (H/'PUBLICATION.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    stage_rows=[]
    for m,s in ORDER:
        z=stages[(stages.window=='2024_2025')&stages.meet.eq(m)&stages.segment.eq(s)&stages.definition.eq('race_fast20')].set_index('stage');stage_rows.append([m+' '+s+'m']+[diff(z.loc[k]) for k in stageorder])
    calendar=pd.read_csv(O/'same_calendar_confirmation.csv',dtype={'segment':str});calrows=[]
    for m,s in ORDER:
        vals=[]
        for window in ['2024_2025','2026_mature']:
            z=calendar[(calendar.window==window)&calendar.meet.eq(m)&calendar.segment.eq(s)].set_index('fast');vals.append(f"{pct(z.loc[True,'next_top3_mean'])} / {pct(z.loc[False,'next_top3_mean'])}")
        calrows.append([m+' '+s+'m']+vals)
    ties=pd.read_csv(O/'threshold_tie_selection.csv',dtype={'segment':str});tie_rows=[[r.meet+' '+r.segment+'m',r.all_section_valid_n,r.selected_fast_n,pct(r.actual_fast_fraction)] for r in ties[ties.window=='2024_2025'].itertuples()]
    report=f'''# 막판 우수·비입상 이후의 입상 관측

2026-10-09 · 연구28 후속28H · 연구 후보 · 예측모델/운영/DB/배포 변경 없음.

{conclusion}

## 질문과 표본

현재 경주에서4위 이하였더라도 막판600/400/200m가 빠른 말은 이후 입상 가능성이 높은가? 원문 전체159,014실전·14,636경주를 시간순으로 연결했다. 다음출전 연결에는 정상구간 모집단 밖의 실제출전도 포함해 나쁜기록이나이상결승을 건너뛰지 않았다.

색인2024~2025 전체37,345출전·3,532경주 중 기존정상구간 품질을 만족한4위이하 기록은부산10,881·서울14,787출전이다. 같은경주 구간기준까지지원되는주표본은부산10,874·서울14,787출전이다. 자료종료일서울2026-09-20·부산2026-09-18,공통미래관측종료일2026-09-18.180일성숙조건의2026색인마감은2026-03-22다. 이후색인출전을실패로채우지않았다. 과거2018~2023은기술표에분리했다. 제주·영천·주행심사·주로빠르기는제외한다.

## 구간과 ‘좋은 기록’ 정의

부산 마지막600/400/200m는원문bu_3fGTime/bu_2fGTime/bu_1fGTime이며전체시간−G3F/G2F/G1F누적시간과대조했다. 서울 마지막600/200m는전체시간−seG3fAccTime/seG1fAccTime. 서울400m를추정하지않았다. 부산600→400,400→200,마지막200의독립200m세조각 합이600m와같음을검증했으나,주지표는중첩하는마지막600/400/200초다. 이점수들을합산하지않는다.

기존151,074정상구간품질모집단을재사용했다. 부산400m만별도로원문양수/누적합/600≥400≥200을확인해1행을제외했다(2020-11-22R1,누적G2F0·마지막400이전체시간으로들어간기록). 부산400정상62,830행,600/200은62,831행,서울600/200은88,243행이다. 정상적으로빠르거나느린기록을효과방향에맞춰절삭하지않았다.

주정의는현재경주전체 유효구간시간의P20이하,최소6두·전체명단80%이상구간지원. 현재입상마도기준계산에포함하며4위이하말들끼리만상위20%를뽑지않았다.0.1초동률을모두포함하므로실제빠른그룹비중은20%를넘는다.

{table(['지역구간','전체유효','빠른경계포함','실제선택비율'],tie_rows)}

보조정의는평가연도이전3개연도의동일지역×정확거리×등급×함수율상태P20,최소100출전·10경주다. 함수율1~5/6~9/10~14/15~19/20이상. 연초고정이라평가연도/미래기록을문턱에넣지않았다. 표본부족은다른거리/등급으로채우지않았다. 이보조기준은상태내정확함수율·월까지완전히맞춘보정값이아니며,같은현재경주비교는이환경차이를경주절편으로제거한다.

현재경주의기록과착순은경주후선별용으로알려진정보다. 경주전현재성적을알고예측했다는뜻이아니다. 과거평균착순/유효이력수는기존T−2·730일·직전5실제슬롯을사용했다.

## 다음 출전 입상률: 원시와 조건조정을 나눠 읽는다

다음출전은말별전체실제명단의바로다음1슬롯이며180일안의서울/부산출전만유효다. 정상순위1..N 중1~3위면1,4위이하면0,이상순위는NaN이다. ‘다음정상출전’을찾아뒤기록으로넘어가지않았다. 미래편성의등급·거리·게이트를조정입력에사용하지않았다.

{table(['구간','빠른비입상마 다음입상률(n)','다른비입상마(n)','원시차이%p[95%]','조건조정 차이%p[95%]'],rows)}

![다음출전입상률](figures/next_start_rates.png)

원시비교에서부산400/200,서울600/200은다중비교BH후차이가남았지만부산600은q=.087로불확실했다. 부산400점추정이가장크다고다른구간보다우월한신호임을검증한것은아니다. 구간과말/경주는겹친다.

조건조정은현재경주절편(양상태모두있는공통경주),현재착순범주,우승마와전체시간차,과거5슬롯평균상대착순/유효수,현재rating·연령,초반상대위치의일차/제곱·결측표시다. 같은경주로거리·등급·주로·편성환경을맞췄다. 연속변수결측은계산을위해0또는0.5와결측표시를사용했으며관측값으로확정하지않았다. 현재착순/전체기록을통제하면‘그성적까지이미알고도막판기록에추가정보가있는가’라는다른질문이된다.

현재경주평균을제거한뒤노출/결과를통제변수에잔차화한선형연관성계수다. 다섯구간모두증가의95%구간이0을포함했다. 조정후확률그자체를만들거나개별마에게그%p를더하지않는다. 다음출전공통경주피복은63.2~79.2%,과거문턱보조는28.5~52.0%로표본이달라진다.

![조건조정차이](figures/adjusted_next_differences.png)

## 어느 정보를 맞추면 차이가 줄어드는가

주결과를본뒤해석용단계분해를추가했다. 각구간의같은공통경주표본을고정한탐색이며주검정을대체하지않는다. 단위%p[95%].

{table(['구간','경주만','과거능력추가','현재착순·패배시간차추가','초반추가=주조정'],stage_rows)}

![조정단계](figures/adjustment_stages.png)

같은경주와과거성적/rating/연령만맞춰도빠른비입상마의다음입상신호는남았다. 현재착순과패배시간차를추가하면대체로0근처로줄었고,초반위치추가시다소바뀌지만주조정은모두불확실했다. ‘과거능력만으로설명된다’고단정하지않는다. 부산600의현재성적단계음수만골라역효과라고채택하지않았다. 미래예측성능추가가치는별도의시간순학습/평가가필요하다.

## 재출전과3전 조건

{table(['구간','빠른그룹 재출전율(색인n)','다른그룹 재출전율(n)','당시평균착순 빠름/다른','다음출전중앙간격 빠름/다른'],returns)}

빠른그룹이재출전할비율도약94~96%대90%로높았다. 재출전하지않은말을다음출전입상실패0으로채우지않았다. 군집을고려해도이차이가컨디션/휴양/퇴역/전적누락의인과효과임을알수는없다. 재출전표본의예측대상과전체색인의향후관측사건을구분한다.

‘3전내입상’은180일안에실제3번모두출전하고세성적정상관측이있는말의그3전중1회이상3위사건이다. 중간이상결승을건너뛰지않으며,한번성공했어도3출전지원이없으면주3전지표에는넣지않았다. 따라서재출전지속에따른선택편향이있다.

{table(['구간','빠른그룹3전내 입상률(n)','다른그룹(n)','원시차이%p[95%]','조건조정%p[95%]'],three)}

서울600/200은원시3전입상차이가있었지만조건조정후불확실했다. 부산은원시도불확실했다. any180_top3는180일전체색인에서최대첫3전중입상이관측됐는지의별도사건으로,미출전=관측입상없음0이다. 이것을재출전마의경기입상확률과혼동하지않았다. 이상결승을0으로놓는next_abnormal_zero민감도도저장했다.

## 과거조건 기준과 같은말 민감도

{table(['구간','과거문턱빠름 다음입상률(n)','다른비입상마(n)','원시차이%p[95%]','같은경주조건조정%p[95%]','문턱피복'],pastrows)}

과거절대조건문턱에서는서울600/200의원시신호가더컸지만조건조정구간은0포함이다. 기준이없는최근등급조합을제외하므로같은경주P20과같은모집단은아니다.

같은말×지역×정확거리×등급에서빠른비입상/다른비입상상태를각1회이상보인공통셀조화표본가중 민감도(현재착순/컨디션은별도로맞추지않음)는다음과같다.

{table(['구간','같은말 다음입상 차이%p[95%]','빠름/다른n','피복','BH q'],adjustrows)}

서울같은말의신호는남았으나같은말도당시착순·패배시간차가다르므로완전조정의대체가아니다. P10/P30 문턱 민감도·4~5/6~8/9+착순대·거리별기술표를따로보존했다. 결과가좋은문턱으로주정의를바꾸지않았다.

## 2026 성숙자료에서 재현됐는가

2026-01-01~03-22색인만180일을완전히볼수있다. 주정의의다음입상은다음과같다.

{table(['구간','빠른그룹(n)','다른그룹(n)','원시차이%p[95%]','BH q'],confirmation)}

다섯구간모두원시구간0포함으로안정적증가를확인하지못했다. 서울600원시점추정은반대방향,같은경주조정은−10.62%p[−20.41,−0.83]였으나BH q=.348이어서역효과를확정하지않았다. 기간이짧고색인날짜군집이적어불확실성이크다.

부분연도와전체연도를그대로비교하지않도록각연도1월1일~3월22일만맞춘원시율도보존했다. 아래각칸은빠름/다른그룹의다음입상률이며연도차이의인과검정이아니다.

{table(['구간','2024~2025 같은달범위','2026 같은달범위'],calrows)}

2024~2025초반부산은오히려빠른그룹입상률이낮았다. 시기별로일률적인법칙이아니다.2026자료는과거연구와말/이력이공유되는후속관측이고별도의미래예측정확도검증이아니다.

## 사례

2025색인에서600m좋음·비입상·다음출전정상인표본중,지역별다음입상성공/실패를각하나씩날짜·경주·게이트순첫사례로선택했다. 성공/실패를보여주는사후설명사례이며검정/사전추천이아니다.

{table(['지역','마명','색인날짜','당시착순','600초 / 경주P20','다음날짜','다음착순','간격일'],casetable)}

## 불확실성·검증·적용

말·색인날짜·교차점수합최대분산에공유미래경주날짜의점수합분산을추가해최댓값을썼다.3전지표는세미래날짜에점수를중복배치한보수적민감도라구간이넓다. t 자유도는말/색인날짜/유효미래날짜군집수최솟값−1,회귀잔차자유도수정n/(n−경주절편수−통제행렬rank−1). 동일말의출전과동일미래성적이여러색인에겹치는것을독립표본으로보지않았다. 지역5구간×두정의×다음/3전입상20비교를기간·방법별BH. 재출전/180일사건/이상결승0/문턱/단계분해는보조탐색이다.

막판우수·비입상은다시볼후보를추리는정보다. 이미보이는착순·패배시간차와정보가겹치며단독확률가산점이나개별마예측확률은만들지않았다. 미래출전에서는편성·거리·등급·주로·게이트·휴양·컨디션이달라질수있다. 기수/조교사효과나실제외측경로/전술의도를추가추정하지않았다. 입상실패의이유/다음경주작전변경/능력향상의인과효과를입증한연구가아니다.

원문159,014행의600/400/200와누적합,독립SQL LEAD 전체미래슬롯/180일/결측,현재/과거문턱연결,요약·회귀·같은말공통셀·군집구간/BH와원래1,208파일보존을검증했다. 보조단계80회귀와착순/거리/동일달범위221요약행도독립계산했다. 수치검증결과는JSON을따른다.

[설계](PLAN.md) · [출처/입력해시](SOURCES.md) · [출전자료](outputs/analysis_rows.parquet) · [주요표](outputs/primary_summary.csv) · [전체비교](outputs/comparisons.csv) · [과거문턱](outputs/prior_thresholds.csv) · [3전/재출전](outputs/cohort_metrics.csv) · [단계분해](outputs/adjustment_stages.csv) · [거리별](outputs/distance_metrics.csv) · [같은달확인](outputs/same_calendar_confirmation.csv) · [검증](outputs/verification.json) · [민감도검증](outputs/sensitivity_verification.json) · [게시MD](PUBLICATION.md) · [게시JSON](PUBLICATION.json) · [용량](outputs/artifact_inventory.json).
'''
    (H/'README.md').write_text(report)
    sources=['# 출처와 재현\n','2026-10-09 · 서울/부산기존보관원문/API실전자료. 추가외부조회없음. 원문과이전파생자료를수정하지않았다.\n','| 입력 | 바이트 | SHA-256 |\n|---|---:|---|']
    for r in audit['inputs']:sources.append(f"| [{r['path']}](../{Path(r['path']).relative_to('thoroughbred/research')}) | {r['bytes']} | {r['sha256']} |")
    sources+=['\n기존28F 전체명단159,014출전과28C 정상구간151,074출전. 미래연결은전체명단의실제슬롯으로하며이상기록을건너뛰지않았다. 현재선별자료와미래정답을구분했다. 부산원문bu_3fGTime/bu_2fGTime/bu_1fGTime·누적G3F/G2F/G1F,서울rcTime−seG3fAccTime/seG1fAccTime을대조했다. 서울400추정없음.', '\n[기존구간자료](../20261008_field_pace_prediction/SOURCES.md) · [이전중간/막판연구](../20261008_middle_late_style_validation/README.md) · [입력감사](outputs/source_audit.json) · [원문/SQL검증](outputs/verification.json) · [민감도검증](outputs/sensitivity_verification.json).']
    (H/'SOURCES.md').write_text('\n'.join(sources)+'\n');print('Published Korean report, 3 figures and chronological cases',flush=True)
if __name__=='__main__':main()
