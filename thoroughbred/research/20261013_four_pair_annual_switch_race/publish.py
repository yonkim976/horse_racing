"""Annual current-race reports for all four frozen exploratory trainer-rider pairs."""
from pathlib import Path
import json
from decimal import Decimal,ROUND_HALF_UP
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';font='/System/Library/Fonts/AppleSDGothicNeo.ttc';fontManager.addfont(font);plt.rcParams.update({'font.family':FontProperties(fname=font).get_name(),'axes.unicode_minus':False,'savefig.dpi':160})
def clean(d):return json.loads(d.to_json(orient='records',force_ascii=False,double_precision=15))
def table(cols,rows):return '\n'.join(['| '+' | '.join(cols)+' |','|'+'|'.join(['---']*len(cols))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])
def pct(x):return '—' if pd.isna(x) else str(Decimal(str(100*x)).quantize(Decimal('0.1'),rounding=ROUND_HALF_UP))+'%'
def val(x,scale=100):return '—' if pd.isna(x) else f'{scale*x:+.2f}'
def ci(r,scale=100):return '추정불가' if r.status!='estimated' else f'{scale*r.ci_low:+.2f}~{scale*r.ci_high:+.2f}'
def notes(r):
 if r.status!='estimated':return '무출전' if r.switched_n==r.retained_n==0 else '유지 비교/식별 부족'
 return '기준 충족' if r.pair_period_supported else '표본 부족·진단용'
def main():
 v=json.loads((O/'verification.json').read_text());cv=json.loads((O/'coverage_verification.json').read_text());assert v['passed'] and cv['passed'];coverage_diag=pd.read_csv(O/'population_coverage_diagnostic.csv');a=json.loads((O/'source_audit.json').read_text());frozen=pd.read_csv(O/'frozen_four_pairs.csv');four=frozen.pair_key.tolist();e=pd.read_csv(O/'adjusted_period_effects.csv',dtype={'period':str});raw=pd.read_csv(O/'raw_period_metrics.csv',dtype={'period':str});cov=pd.read_csv(O/'coverage.csv');top=e[e.target.eq('top3')].copy();top.to_csv(O/'top3_period_comparison.csv',index=False)
 yearly=raw[raw.model.eq('annual')].copy();partial=raw[raw.model.eq('recent_partial')].copy();partial['period']='2026*';plotraw=pd.concat([yearly,partial]);years=[str(y) for y in range(2019,2026)]+['2026*']
 summary='四개 후보를 연도별로 나누면 최근까지 개선이 확정적으로 이어졌다고 판단할 조합은 없다. 배대선→이동하의 자료는2019~2020년에 집중되고2024~2026년에는 대상 출전이 없다. 김동균→조한별은2024년까지 신호가 있으나 그 해 변경7회뿐이며2025~2026년 대상 출전이 없다. 강환민→김용근과 민장기→최은경은 최근 완결2년에도 보정 입상률 차이의 추정 방향은 양수이나 불확실성이 크다.2026부분기간에서도 각각 변경2회와12회여서 현재의 개선조합으로 확정할 수 없다.'.replace('四개','네 개')
 # Every year shown including zero-start cells. No line bridges a missing year.
 fig,axes=plt.subplots(2,2,figsize=(13,9),sharex=True,sharey=True)
 for ax,p in zip(axes.ravel(),four):
  g=plotraw[plotraw.pair_key.eq(p)];x=np.arange(len(years));zs=g[g.state.eq('switched')].set_index('period').reindex(years);zr=g[g.state.eq('retained')].set_index('period').reindex(years)
  ax.plot(x,zs.top3_rate*100,'o-',color='#276d91',label='변경 당일');ax.plot(x,zr.top3_rate*100,'s--',color='#ad6b36',label='기수 유지')
  for i,row in enumerate(zs.itertuples()):
   if row.n:ax.annotate(f'{int(row.top3_events)}/{int(row.n)}',(i,row.top3_rate*100),xytext=(0,8),textcoords='offset points',ha='center',fontsize=9)
   else:ax.text(i,4,'없음',ha='center',fontsize=8,color='#777')
  name=frozen.set_index('pair_key').loc[p];ax.set_title(name.trainer_name+'→'+name.jockey_name);ax.set_xticks(x,years,rotation=30);ax.set_ylim(0,115);ax.set_ylabel('입상률 (%)');ax.grid(alpha=.2)
 axes[0,0].legend(loc='upper left',fontsize=9);fig.suptitle('기수가 바뀐 그 한 경주의 관측 입상률 · 숫자=입상/변경 출전\n2026*는 서울9/13·부산9/11까지의 부분기간 · 작은 표본의 비율에 주의',fontsize=13);fig.tight_layout(rect=(0,0,1,.94));fig.savefig(F/'annual_observed_top3.png');plt.close(fig)
 fig,axes=plt.subplots(2,2,figsize=(13,9),sharex=True)
 for ax,p in zip(axes.ravel(),four):
  z=top[top.model.eq('annual')&top.pair_key.eq(p)].set_index('period').reindex(years[:7]);valid=z.status.eq('estimated');x=np.arange(7);est=z.estimate*100;ax.errorbar(x[valid],est[valid],yerr=np.vstack([(z.estimate-z.ci_low)[valid]*100,(z.ci_high-z.estimate)[valid]*100]),fmt='o',color='#276d91',capsize=3);ax.axhline(0,color='#555');ax.set_xticks(x,years[:7],rotation=30)
  for i in x[~valid]:ax.text(i,0,'NA',ha='center',va='bottom',fontsize=9,color='#777')
  name=frozen.set_index('pair_key').loc[p];ax.set_title(name.trainer_name+'→'+name.jockey_name);ax.set_ylabel('보정 입상률 차이 (%p)');ax.grid(axis='y',alpha=.2)
 fig.suptitle('연도별 같은 조합 유지 대비 변경 당일 보정차와 95% 군집구간\n말·경주·과거상태·기수수준·평소조합의 연도변화 고려 · NA=추정불가',fontsize=13);fig.tight_layout(rect=(0,0,1,.94));fig.savefig(F/'annual_adjusted_top3.png');plt.close(fig)
 eras=top[top.model.eq('eras')&top.contrast.eq('pair_total')];recent=top[top.model.eq('recent_partial')];diff=top[top.contrast.eq('recent_minus_earlier')];era_rows=[]
 for p in four:
  for period in ['2019_2023','2024_2025','2026_partial']:
   r=(recent if period=='2026_partial' else eras).query('pair_key==@p and period==@period').iloc[0]
   era_rows.append([r.trainer_name+'→'+r.jockey_name,period,f'{int(r.switched_n)}/{int(r.retained_n)}',f'{int(r.switched_top3_events)}/{int(r.switched_n)}' if r.switched_n else '없음',pct(r.switched_top3_rate),pct(r.retained_top3_rate),val(r.estimate),ci(r),f'{r.q_fixed_family:.4f}',notes(r)])
 period_table=table(['조합','기간','변경/유지','변경 입상/출전','변경 당일율','유지율','보정차%p','95% 구간','탐색q','지원'],era_rows)
 annual_sections=[];annual_rows=[]
 for p in four:
  z=top[top.model.eq('annual')&top.pair_key.eq(p)].sort_values('period');rows=[]
  for r in z.itertuples():
   row=[r.period,f'{int(r.switched_n)}/{int(r.retained_n)}',pct(r.switched_previous_top3_rate),f'{int(r.switched_top3_events)}/{int(r.switched_n)}' if r.switched_n else '없음',pct(r.switched_top3_rate),pct(r.retained_top3_rate),val(r.estimate),ci(r),f'{r.q_fixed_family:.4f}',notes(r)];rows.append(row);annual_rows.append([r.trainer_name+'→'+r.jockey_name]+row)
  name=frozen.set_index('pair_key').loc[p];annual_sections+=['### '+name.trainer_name+'와 '+name.jockey_name,'',table(['연도','변경/유지','직전율','당일 입상/출전','당일율','유지율','보정차%p','95% 구간','탐색q','지원'],rows),'']
 (O/'all_annual_top3.md').write_text('# 네 조합의 모든 연도별 변경 당일 입상률\n\n입상=3위이내. 보정차는 같은 조합 유지 대비 변경 당일. 표본 미달은 진단용. 추정불가를0효과로 해석하지 않는다.\n\n'+'\n'.join(annual_sections)+'\n')
 diff_table=table(['조합','최근−과거 보정차%p','95% 구간','탐색q'],[[r.trainer_name+'→'+r.jockey_name,val(r.estimate),ci(r),f'{r.q_fixed_family:.4f}'] for r in diff.itertuples()])
 counts=[]
 for (model,target,contrast),z in e.groupby(['model','target','contrast']):
  favorable=z.estimate.gt(0) if target=='top3' else z.estimate.lt(0);counts.append(dict(model=model,target=target,contrast=contrast,family_size=len(z),estimated=int(z.status.eq('estimated').sum()),nominal=int((z.p<.05).sum()),favorable_bh=int((favorable&z.q_fixed_family.lt(.05)&z.status.eq('estimated')).sum()),all_targets_favorable_bh=int((favorable&z.q_all_targets_fixed_family.lt(.05)&z.status.eq('estimated')).sum()),supported=int(z.pair_period_supported.sum())))
 counts=pd.DataFrame(counts);counts.to_csv(O/'family_summary.csv',index=False)
 body=['# 네 마방 기수 조합의 연도별 변경 당일 성적','','2026-10-13 · 연구50D · 50C 후속 · 사후 선택된 후보의 탐색 분석','',summary,'','## 변경된 한 경주만 비교','','대상은50C에서7년 전체 입상률 보정차 양수·개별p<.05였던 네 조합이다. 이들은 원래213개 조합의 다중비교를 통과하지 못했다. 이번 결과도 그 사실을 바꾸는 독립 확인으로 취급하지 않는다. 출전표에 예정된 기수가 실제 그대로 기승하고 직전 실제 기수와 달라진 경우만 변경으로 본다. 카드 발표 후 대타와 미확정은 제외했다. **변경한 바로 그 현재 한 경주**의 결과만 분석했다. 이후 출전·이후 평균·최고성적을 이벤트 성과로 연결하지 않았다. 직전·최근5회는 비교/통제 변수다. 네 조합의 변경240건(2019~2025년226건,2026부분14건) 전필드가 원본의 현재행과 같은지 검증했다.','','서울·부산2019~2025 완결7년을 주기간으로 유지한다. 최근은2024~2025완결2년과2026부분을 각각 표시한다.2026은 서울9월13일·부산9월11일까지 계획대로 기승 지원이 있는 표본이며 올해 전체나10월 현재까지의 결과가 아니다. 주표본은 정상현재착순·같은조교사/지역·직전2~180일·기수ID지원·양기수전년도100회이상 기승지원 조건이다. 무출전은 이 연구 조건의 대상 부재이며 현역 여부를 뜻하지 않는다. 결과 확인 뒤 원본 전체의 조합 출전도 별도 점검해 배대선→이동하2024~2026과 김동균→조한별2025~2026의 부재가100회 조건 때문은 아님을 확인했다. [조건별 분모 점검](outputs/population_coverage_diagnostic.csv)은 보정모형과 구분한다.','',table(['모형','배경출전','전체변경','말','경주','네 조합 변경','시작','종료'],[[r.model,int(r.n),int(r.changed),int(r.horses),int(r.races),int(r.candidate_changed),r.start,r.end] for r in cov.itertuples()]),'','## 연도별 관측 성적','','관측 당일율은 변경출전 집단의 현재3위이내 비율이다. 직전율은 동일 집단 직전 결과의 원시율이며 직전 유효분모가 다를 수 있다. 원시표에 직전 유효수와 그에 짝지은 당일율을 별도로 보관했다. 유지율은 같은 마방–기수 조합으로 계속 기승한 별도 출전의 현재 입상률이다. 원시 직전→당일 또는 변경−유지 차이가 보정효과는 아니다.2020/2021년의1~3회 표본에서 나온0%/100%를 재현 가능한 규칙으로 취급하지 않는다.','','![연도별 관측 입상률](figures/annual_observed_top3.png)','',*annual_sections,'## 능력과 직전 성적을 고려한 연도별 차이','','50C와 같은 말/현재경주 고정효과,현재기수의 지역×연도 수준,마방 주효과,213개 지원조합 평소 주효과,일반변경항+조합별변경 추가항과 직전/최근 상태 통제를 사용했다. 네 후보의 평소조합 주효과와 변경 추가항만 연도별로 달라지도록 허용했다. 따라서 보정차는 **그 연도의 같은 조합 유지 대비 변경 당일 입상률 차이**다. 네 조합 밖209개에는 기간 공통 조합 계수를 유지한다.','','직전 상대착순/입상,최근5회 평균과 관측수,공백,거리/등급 변화,rating,나이,부담중량,마체중,상대게이트,직전기수 전년도 수준과 결측/제곱항을 고려했다. 말능력 고정효과는 전체 분석기간의 관측에서 추정한 사후 통제이며 경주전 예측모형이 아니다. 이후 출전을 교체의 목표성과로 쓰는 것과 능력통제 추정에 분석기간 전체를 사용하는 것은 구분한다. 기수 선택의 보이지 않는 판단까지 제거한 인과효과도 아니다.','','95%구간은 말/날짜 두 방향 군집분산의 보수적인 값이다. 주결과 연도별28개·3결과 공동84개에 BH를 제공하며 추정불가 p는1로 두고 고정분모를 유지했다. 별도의기간8개/기간차4개/2026부분4개 가족도 사전에 정했다. 모두 원래의 후보선정 뒤에 한 탐색검정으로 원래213조합의 선택 편향을 없애지 않는다. 선형확률모형의 소표본 계수나 구간은±100%p를 벗어날 수 있으며 실제 확률·가산점으로 사용하지 않는다.','','![연도별 보정 입상률 차이](figures/annual_adjusted_top3.png)','','## 과거와 최근의 비교','','연도별로 분모가 작으므로 사전에 정한2019~2023대2024~2025 두 기간 모형에서도 네 후보의 평소조합/변경항을 기간별로 허용했다. 그 외 말·경주·과거상태 통제는 유지한다.2026은 별도 해당기간 모형을 재추정했으며 사전예측 검증이 아니다.','',period_table,'','최근−과거는 두 기간 공동모형에서2024~2025변경차−2019~2023변경차다. 양수면 보정차가 최근에 더 크다는 추정이다. 단순히 두 점추정의 부호나 크기가 다르다는 이유로 시기 변화가 확인됐다고 선언하지 않는다.','',diff_table,'','## 조합별 해석','','**김동균→조한별:**2019년 대상이 없고2020/2021년은 변경1회씩,유지0회여서 연도 대조가 식별되지 않는다.2022년3/10입상,2023년6/17,2024년3/7로 변경 당일 관측률은 올라가는 방향이다. 보정치 역시2024년에 양수 신호가 있지만7회에 불과하다.2024년 상대착순 차이-0.505(95%-0.728~-0.283),우승마와 시간차-1.376초(95%-2.143~-0.609)로 순위와 기록에서도 개선 신호가 있다. 연도별4×7 탐색BH q는각각.000263/.012638,3결과 공동q는.000790/.018957다. 최근−과거 상대착순 차이도-0.434(95%-0.709~-0.159,탐색q=.0081)다. 다만 변경7/유지15출전으로 지원기준 미달이며 후보를 고른 뒤의 탐색 결과다.2025~2026년은 대상 출전이 없어 현재까지 유지된다는 결론을 낼 수 없다.','','**배대선→이동하:**55변경 중50회(90.9%)가2019~2020년에 몰렸다.2019년11/37,2020년5/13,2023년1/5다.2023년에는 변경20%·유지60%여도5회씩이라 단정할 수 없다.2024~2026년 표본이 없어 과거의 신호를 현재에도 유효하다고 적용할 근거가 없다.','','**강환민→김용근:**변경 당일 관측 입상률은2019~2023년46.8%(22/47)에서2024~2025년31.3%(5/16)로 낮아졌다. 그러나 유지율도38.8%→16.7%로 달라졌고 말/경주/직전상태를 고려한 보정차는 최근에도 양수다. 최근−과거 구간에0이 포함돼 보정효과가 약해졌거나 강해졌다고 확정할 수 없다.2026부분은2변경 모두 입상했지만 유지도14회 중10회 입상했다. 보정차+36.27%p의95%구간은-27.41~+99.95로 넓고 변경2회뿐이어서 재현 가능한 확정 이점으로 취급하지 않는다.','','**민장기→최은경:**변경 당일율은 과거44.0%(22/50)→최근31.8%(7/22)로 낮아졌지만 보정차의 추정 방향은 두 기간 모두 양수다. 최근−과거 구간에0이 포함돼 원시율 하락을 조합효과 약화로 단정하지 않는다.2026부분은 변경4/12입상(33.3%)·유지4/18입상(22.2%)이나 보정차-3.05%p(95%-55.33~+49.24)다. 원시율은 높아도 능력과 편성 등을 고려한 방향은 약한 음수로 바뀌며 구간이 넓다. 변경12회에 그치므로 악화나 개선 모두 확정하지 않는다.','','## 순위 기록과 검증','','연간100회 지원 제한만 해제한2026부분 범위점검에서는 강환민→김용근2/3입상,민장기→최은경4/13입상이다. 주표본의2/2와4/12보다 분모가 조금 늘지만 여전히 작다. 이 부록은 보정 없는 범위점검이며 새로운 개선효과 추정으로 사용하지 않는다. 상대착순 `(순위-1)/(출전수-1)`과 공식우승마 대비 시간차(초)는 음수가 개선이다. 보조결과까지 포함한 모든 연도/기간/기간차/2026계수와 고정분모 BH를 [전체 계수표](outputs/adjusted_period_effects.csv)에 남겼다. 시간차를 전 거리 공통 초 가산점으로 채택하지 않는다.','',table(['모형','결과','대조','고정검정수','식별수','개별신호','유리한BH','3결과유리BH','지원충족'],[[r.model,r.target,r.contrast,int(r.family_size),int(r.estimated),int(r.nominal),int(r.favorable_bh),int(r.all_targets_favorable_bh),int(r.supported)] for r in counts.itertuples()]),'',f'독립 SQL로 실제 직전 슬롯과80개 원시표 격자를 재계산하고240변경행의 현재 결과·출처를 전수 확인했다. 정확한 고정효과 투영/SVD와 다른 전체 희소LSQR로3모형×3결과의 모든 식별 가능한 대조를 재현하고 입상률 전구간 및 보조결과BH신호의 군집구간을 재계산했다. {v["checks"]:,}항목 검증 통과. [검증](outputs/verification.json) · [모형진단](outputs/model_diagnostics.csv).','','기존지원기준은 변경과 유지 각각≥30출전·≥15말·≥20경주다. 연도로 나누면 많은 셀이 미달한다. 식별 가능성과 충분한 표본지원은 다르며 작은 셀의 계수를0효과나 확정효과로 바꾸지 않았다. 처음 게시된 카드의 불변성 미인증,선택 편향과 미관측 마필 상태 한계도 유지한다. 기존50C는 보존하고50D후속으로 등록하며 운영모델/DB/배포는 변경하지 않는다.','','[출처와 재실행](SOURCES.md) · [게시용 요약](PUBLICATION.md) · [게시 JSON](outputs/publication.json) · [모든연도표](outputs/all_annual_top3.md) · [용량명세](outputs/artifact_inventory.json)']
 (H/'README.md').write_text('\n'.join(body)+'\n')
 pub=['# 네 마방 기수 조합의 개선 신호는 최근에도 이어지는가','','2026-10-13 · 서울 부산 · 변경한 바로 그 한 경주만 평가','',summary,'','## 최근 기간의 숫자','','아래 입상률은 변경 당일 관측률이고 보정차는 같은 기간 같은 조합의 기수 유지 대비 차이다. 최근에 관측률이 낮아져도 말의 수준·상대편성과 유지 집단이 달라졌다면 조합효과 약화로 바로 해석할 수 없다.','',period_table,'','## 연도별로 읽으면','','김동균→조한별은2022년3/10→2023년6/17→2024년3/7입상이다.2024년에는 상대착순과 우승마 대비 시간차에서도 탐색 다중비교를 통과한 개선 신호가 있다. 다만 변경7/유지15출전으로 지원기준 미달이며2025~2026년 대상 표본이 없다. 배대선→이동하는2019~2020년에55변경 중50회가 몰려 과거 중심의 결과다.','','강환민→김용근과 민장기→최은경은2024~2025년에도 보정차의 방향은 양수지만 구간에 감소와 증가가 모두 들어간다. 최근−과거 차이도0을 포함해 특정 시기에만 효과가 있었다고 확정할 수 없다.2026부분에서 강환민→김용근은2/2입상이지만 변경2회뿐이다. 민장기→최은경은4/12입상이며 보정차-3.05%p의구간이-55.33~+49.24로 넓어 최근 개선이 지속된다고 확정할 수 없다.','','원래 네 조합은213조합 검정에서 확정되지 않은 후보였다. 이번 연도별 분석도 후보를 고른 뒤 한 탐색 분석이다. 관측 부재·표본 부족을0효과로 처리하지 않았고 인과적 승부의지나 현재 예측 가산점으로 채택하지 않았다.2026자료는서울9/13·부산9/11까지의 부분기간이다.','','[모든연도와 보정·최근차](README.md) · [연도별표](outputs/all_annual_top3.md) · [독립 검증](outputs/verification.json) · [출처](SOURCES.md)']
 (H/'PUBLICATION.md').write_text('\n'.join(pub)+'\n')
 out=dict(study='50D',updated='2026-10-13',title='네 마방 기수 조합의 연도별 변경 당일 성적',status='exploratory_after_pair_selection_not_production',summary=summary,target_horizon_races=0,future_outcomes_created=False,current_switch_events=240,primary_period='2019~2025',partial_by_meet=a['partial_by_meet'],frozen_four_pairs=clean(frozen),top3_period_table=clean(top),raw_period_table=clean(raw),all_adjusted_effects=clean(e),family_summary=clean(counts),verification=v,coverage_verification=cv,population_coverage_diagnostic=clean(coverage_diag),original_213_BH_passed=False,ability_FE_retrospective=True,prediction_test=False,causal_intent_proven=False,production_changed=False)
 (O/'publication.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 (H/'SOURCES.md').write_text('''# 출처와 재실행

[50A의 출전별 분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행을 불변 참조한다. 원문 카드·공지 분류와 최초 게시본 불변성 미인증 한계는 [50A 출처](../20261012_planned_jockey_changes_by_stable/SOURCES.md)와 [검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을 따른다. [50C 후보표](../20261012_historical_planned_pair_switch_race/outputs/nominal_top3_candidates.csv)에서 양수인 네 조합을 고정했다. 원래213조합 BH를 통과한 후보는 없었다.

[사전계획](PLAN.md)은 연도별 결과를 보기 전에 연도/두기간/2026부분,고정분모BH,표본지원,검증을 정했다. 연도별 분모만 먼저 확인해 최근 표본 부재를 표시했다. 네 후보의 평소조합/변경항을 연도별 또는 기간별로 허용해 평소 조합의 수준 변화까지 고려했다. 해당기간에 새로 후보를 고르지 않았다.

[입력명세](outputs/source_audit.json)는 입력8개 경로·크기·SHA-256과 부분기간 종료일을 기록한다.50C의 순수 prepare/aggregate/fit과50의 controls/demean을 참조하고 이전 main은 실행하지 않았다. 새 원본 수집·DB 접근 없음. 결과 확인 뒤 별도의 조건별 분모 진단으로 연간100회 제한/다른 조건에 따른 범위 차이와 모든 원본 조합행의 부재도 확인했다. 이 진단은 추가 보정모형이 아니며 [범위검증](outputs/coverage_verification.json)에 사후 점검임을 표시했다. [이벤트](outputs/four_pair_switch_events.parquet)는 변경한 현재행과 직전행 키/현재결과·원문출처만 담으며 이후성과는 생성하지 않는다. 사후 말능력FE는 전체기간 관측으로 추정하므로 경주전 예측모형은 아니다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/verify.py
OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/coverage_audit.py
MPLCONFIGDIR=/private/tmp/horse_four_annual_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/publish.py
```

등록은 재실행하지 않는다. 문서 변경 시 중앙/공유해시를 갱신하고 final_review.py/record_inventory.py로 확인한다. 원본참조·DB·임시캐시는 산출물 용량에서 제외한다. 운영 예측·DB·배포를 바꾸는 스크립트가 아니다.
''')
 print(summary)
if __name__=='__main__':main()
