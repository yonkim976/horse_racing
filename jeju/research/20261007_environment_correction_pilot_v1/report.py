"""Render complete, auditable Korean results and publication figures."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm
from audit import HERE,ROOT,DB,BANDS,sha,save,csv
from modeling import paired_ci,NUM,CAT,load

def table(df,formats=None):
    formats=formats or {};lines=['| '+' | '.join(map(str,df.columns))+' |','| '+' | '.join('---' for _ in df.columns)+' |']
    for _,r in df.iterrows():
        vals=[]
        for c,v in r.items():
            if pd.isna(v):v='—'
            elif c in formats:v=formats[c].format(v)
            elif isinstance(v,(float,np.floating)):v=f'{v:.6f}'
            vals.append(str(v).replace('|','/'))
        lines.append('| '+' | '.join(vals)+' |')
    return '\n'.join(lines)

def bh(p):
    p=np.asarray(p);order=np.argsort(p);q=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];out=np.empty(len(p));out[order]=np.minimum(1,q);return out

def main():
    out=HERE/'report_01';out.mkdir(exist_ok=False)
    audit=json.loads((HERE/'audit/summary.json').read_text());selection=json.loads((HERE/'comparison_01/selection_locked_before_evaluation.json').read_text());decision=json.loads((HERE/'comparison_01/decision.json').read_text())
    coeff=pd.read_csv(HERE/'analysis_02/moisture_coefficients.csv');latest=coeff[(coeff.record_year==2026)&(coeff.variant=='median')].copy();wet=latest.band!='건조'
    se=(latest.loc[wet,'ci_hi']-latest.loc[wet,'ci_lo'])/3.92;latest.loc[wet,'p_pointwise']=2*norm.sf(np.abs(latest.loc[wet,'effect_s']/se));latest.loc[wet,'q_BH_eight_moisture_comparisons']=bh(latest.loc[wet,'p_pointwise']);csv(out/'moisture_latest_with_multiplicity.csv',latest)
    gates=pd.read_csv(HERE/'analysis_02/number_coefficients.csv');gl=gates[gates.record_year==2026].copy()
    for target in ['time','top3']:
        mask=gl.target==target;se=(gl.loc[mask,'ci_hi']-gl.loc[mask,'ci_lo'])/3.92;pv=2*norm.sf(np.abs(gl.loc[mask,'effect']/se));gl.loc[mask,'q_BH_20_number_comparisons']=bh(pv)
    csv(out/'number_latest_with_multiplicity.csv',gl)
    dev=pd.read_csv(HERE/'comparison_01/development_candidate_metrics.csv');dev=dev[dev.axis=='all'].copy();base=pd.read_csv(HERE/'comparison_01/dev_0_0_0_race_metrics.csv')
    cis=[]
    for tag,label in [('0_0_0','R0'),('25_0_0','함수율25%'),('50_0_0','함수율50%'),('75_0_0','함수율75%'),('100_0_0','함수율100%'),('0_25_0','월25%'),('0_50_0','월50%')]:
        a=pd.read_csv(HERE/f'comparison_01/dev_{tag}_race_metrics.csv');ci=paired_ci(a,base);ci.update(candidate=label,log_loss=a.log_loss.mean(),brier=a.brier.mean(),mae_s=a.mae_s.mean(),delta_mae_s=float((a.set_index('race_id').mae_s-base.set_index('race_id').mae_s).mean()),six_combo_hit=a.six_combo_hit.mean());cis.append(ci)
    ci=pd.DataFrame(cis);csv(out/'development_delta_table.csv',ci)
    ev=pd.read_csv(HERE/'comparison_01/evaluation_metrics.csv');calendar=pd.read_csv(HERE/'descriptive_01/matched_calendar_comparisons.csv');season=calendar[(calendar.comparison=='summer_winter')&(calendar.period!='partial_2026')]
    months=pd.read_csv(HERE/'analysis_02/month_coefficients.csv');monthly=months[months.record_year==2026];support=pd.read_csv(HERE/'descriptive_01/all_distance_support.csv')
    ru=pd.read_csv(HERE/'comparison_01/R0_runner_predictions.csv');ra=pd.read_csv(HERE/'comparison_01/R0_race_metrics.csv')
    mainperiod=[]
    for name,years in [('2024~2025',[2024,2025]),('2026 부분연도',[2026]),('전체 후향 평가',[2024,2025,2026])]:
        a=ra[ra.year.isin(years)];b=ru[ru.year.isin(years)];mainperiod.append({'기간':name,'경주':len(a),'행':len(b),'일수':a.race_date.nunique(),'Top3 log loss':a.log_loss.mean(),'Brier':a.brier.mean(),'시간 MAE(s)':a.mae_s.mean(),'5두 내 3두 전부':a.all3_in_top5.mean()*100,'최대6조합 적중':a.six_combo_hit.mean()*100})
    bins=pd.read_csv(HERE/'comparison_01/calibration_bins.csv');bins=bins[bins.model=='R0'];ece=float((np.abs(bins.predicted-bins.observed)*bins.weight).sum()/bins.weight.sum())
    exposures,_=load();exposures=exposures[exposures.year>=2017].copy();exposures['start_number_rank']=exposures.groupby('race_id').horse_number.rank(method='min');exposures['start_number_relative_position']=(exposures.start_number_rank-1)/(exposures.field_n-1)
    csv(out/'start_number_exposure.csv',exposures[['api_record_id','race_id','race_date','race_distance_m','horse_number','field_n','start_number_rank','start_number_relative_position','strict']])
    variants=coeff[(coeff.record_year==2026)&(coeff.band.isin(['포화','불량']))].pivot(index=['distance','band'],columns='variant',values='effect_s').reset_index()
    effecttable=latest[['distance','band','effect_s','ci_lo','ci_hi','races','days','supported','q_BH_eight_moisture_comparisons']].rename(columns={'distance':'거리m','band':'함수율','effect_s':'건조 대비 초','ci_lo':'95% 하한','ci_hi':'95% 상한','races':'경주','days':'일수','supported':'설계 지원','q_BH_eight_moisture_comparisons':'탐색 BH q'})
    devtable=ci[['candidate','log_loss','delta','lo','hi','brier','mae_s','delta_mae_s','six_combo_hit']].rename(columns={'candidate':'후보','log_loss':'log loss','delta':'LL 차이','lo':'차이95% 하한','hi':'차이95% 상한','mae_s':'시간MAE','delta_mae_s':'MAE 차이','six_combo_hit':'6조합 적중률'})
    seasontable=season[['period','distance','source','raw_unmatched_difference','matched_difference','ci_lo','ci_hi','common_strata','target_races_in_common','reference_races_in_common']]
    text=f'''# 제주 전체시간 환경 보정 첫 연구 결과

2026-10-07. **이번 파일럿은 원기록 R0를 유지한다.** 함수율·월에 따른 관찰 차이는 있었지만, 과거 기록 보정이 말별 Top3 예측을 개선했다는 사전 기준을 통과하지 못했다. 함수율·월·출발번호의 선택 적용률은 모두0%다. 제주 운영 모델 HY_R_FORM·등록부·예측 파이프라인을 변경하지 않았다.

## 1. 직접 확인한 사실과 분석 범위

DB SHA-256은 `{audit['database_sha256']}`이고 기존 감사와 동일하다. 상한2026-09-19, 전체92,513행/9,494경주, 2017+59,042행/5,901경주, 엄격 정상·완전순위53,341행/5,332경주/873일, 동일거리 T−2 이력 보유마≥4인5,193경주를 재확인했다. 기존 지원 감사의 출전ID 집합이 완전히 일치하여 집계·원천 추적을 재사용할 수 있었다. 기존 단순 최근3평균을 환경계수로 재사용하지 않고 새 연도 밖 기대시간을 만들었다.

첫 추정 대상은1000·1110m다. 2019+ 엄격 표본은 각각1,282·906경주이고, 기대시간 정답 학습은2017부터 시작하면서2017~18 시대와 원문 등급을 따로 유지했다. `제1`의 마지막2018-08-25, 현행 형식 첫2018-08-31은 관측 경계이며 제도 개편일이나 등급 동등성 판정이 아니다.

엄격 표본은 정상완주·1~N 유일순위·결과 원장 대비 후보 수 일치 등을 **사후** 요구한 모집단이다. 제외569경주 중 비정상/비양수510, 순위불완결569는 중복 사유다. 완전한 당시 T−2 출전표, 역사적 품종, 최초 공개시각을 입증하지 못했다. 과거 사건 날짜T−2 기준과 결과 원장으로 복원한 이번 거리·등급·나이·중량·성별·두수의 가용성을 가정한 회고 연구다. 운영 대상 전체나 특수결과 경주로 성능을 확대하지 않는다.

전체 후보의 함수율 unknown은691행, 2017+에서는 `(%)`319행과 `(0%)`20행이다. 숫자20%이나 라벨이 빈20행은2023-12-15의 비정상 결과이며 정상 표본의 라벨 상충이 아니다. 엄격 표본과 더 넓은 정상·양수시간 표본에는 알려진 숫자/라벨 상충이 없다. unknown을 건조0%로 바꾸지 않았다.

## 2. 조건을 조정한 함수율 관찰 차이

2019~2025의 연도 밖 기대시간 잔차를 사용한 **2026년 기록용 후보 계수**다. 실제시간−기대시간을 이력 보유마≥4인 경주의 중앙값으로 집계하고, 경주당 가중치1로 거리별 함수율·연도·원문 등급·연중 곡선·편성과 과거능력을 조정했다. 기대시간과 잔차 대상 연도는 겹치지 않는다. 단위는 초, 음수는 건조보다 빠른 방향이다. 아래 수치는 적용초나 채택표가 아니다.

{table(effecttable,{'건조 대비 초':'{:+.3f}','95% 하한':'{:+.3f}','95% 상한':'{:+.3f}','탐색 BH q':'{:.3f}'})}

1110m 포화의 점별 구간은0을 조금 벗어나지만, 8개 함수율 대비의 탐색 BH 조정 후 q<0.05인 대비는 없다. 표본 지원 통과는 효과 확정이나 예측 유용성의 증거가 아니다. 이 구간은 기대시간 적합을 고정한 날짜 cluster 근사구간이며 전체 추정 단계의 불확실성을 모두 포함하지 않는다. 날짜 재표집200회도 별도로 보존했다.

무절단 경주 중앙값을 주 기준으로 했고, 무절단 경주평균·Huber·최근3기록 기대시간·2019+ 기대시간·불완전 경주 정상시간 보존을 비교했다. 특히 불량의 부호가 Huber에서 바뀐다. 빠르거나 느린 정상 평가 정답을 삭제하지 않았다.

{table(variants)}

## 3. 계절·월 및 출발번호

정확거리×연도×원문등급×숫자함수율 공통층에서 여름(6~8월)−겨울(12/1/2월)을 계산했다. 층의 양쪽 경주수 중 작은 수를 가중치로 쓰며, 계절 내부 월별 동일가중치는 아니다. raw_population은 전체 엄격 경주평균, ability_adjusted_common_population은 과거 이력 적격마의 기대시간 잔차 중앙값이다. 두 모집단과 두 종속변수는 다르므로 단순 차감으로 원인을 분해하지 않는다.

{table(seasontable)}

1000m 완결2019~25의 능력조정 공통층 차이는 약−0.650초(95% −1.198~−0.260)지만, 최근2024~25는−0.402초(−0.912~+0.064)다. 1110m는 능력조정 후 두 기간 모두 구간이0을 포함한다. 2026 부분연도의 능력조정 여름−겨울도 두 거리 모두 구간이0을 포함하며12월이 없는 불완전 연간 비교다. 모든 세부 월 비교와 분모는 `descriptive_01/matched_calendar_comparisons.csv`에 있다.

함수율과 월을 같은 환경모형에서 추정하여 중복을 피했다. 연중1·2차 sin/cos로 날짜별 부드러운 곡선을 만들었으며 실제 적용 후보는 매월15일의 표 값이 아닌 그 기록 날짜의 위상을 사용한다. 월계수는 해당거리 연중평균0 참조다. 최신12개월은 설계 지원을 갖췄지만 곡선이 확인된 기온의 인과효과나 검증된 보정값은 아니다. 월곡선의 겨울 느림 관찰과 다음 출전 Top3 개선은 서로 다른 질문이다.

번호 연구는 정확10두·마번1~10의 경주에서 과거능력·나이·중량·경력·간격·성별과 경주 고정효과를 조정했다. 초 단위와 Top3 %p를 따로 추정하고10번호 평균0으로 표시했다. 원시 번호·두수·번호순 상대위치를 `report_01/start_number_exposure.csv`에 구분했다. 실제 물리 게이트나 실제 내외측 위치를 확인한 것으로 해석하지 않는다.

2025년 말까지1000m의 번호 시간효과 범위는 약−0.092~+0.091초,1110m는−0.085~+0.060초다. 번호별 점별 차이가 있어도 거리×10번호의 탐색 다중대비 후 뚜렷한 시간 차이를 확정하지 못했다. **2021~2026 기록연도의 모든 사전 번호 진단이 날짜 불확실성 기준을 통과하지 못했다.** 번호 초 효과는 추정표에 남겼지만 보정 기록에서는 NULL/`seconds_not_validated_raw_fallback`, 실제 적용0으로 처리했다. %p를 초로 바꾸거나 주행위치를 추가 가산하지 않았다.

## 4. 과거 기록 보정의 유효성과 실제 예측 비교

각 기록 h는 h 이전 연도까지로 만든 계수만 참조했다. 2019~20과 지원 없는 조건은 원기록을 유지한다. 이력은 T−2까지 정확거리 최근5개이며 다른거리 계수나 시간을 차용하지 않았다. 원기록·성분별 추정초/CI/지원/상태·적용률/적용초·보정시간·계수버전/종료일을 별도 CSV에 보존했다. NULL 효과와 추정0초, 적용률0으로 원기록을 유지하는 상태를 구분했다.

모형은 거리별 동일 Ridge 시간모형과 동일 Logistic Top3 점수모형이다. 평가연도y의 모형학습은2017~y−2, 확률 온도보정y−1, 평가y다. 연도 내 모형 재학습 없이 T−2 이력만 갱신한다. 점수로 정확3두 집합 분포를 정규화하여 Top3 주변확률을 합산하므로 말별 확률 합은3이다. 이는 교호작용 없는 조건부 집합 모형의 가정이며 실제 공동분포 정확성이나 순서 예측을 입증한 것이 아니다. 최대6개의 서로 다른 삼복 집합을 같은 규칙으로 선택했다.

**2022~2023 선택633경주·192일** 결과다. 차이는 후보−원기록이고 음수가 LL/MAE 개선이다. 아래 날짜 paired bootstrap은 고정된 모형·선택에 조건부인1000회 결과다.

{table(devtable)}

함수율50%가 점최소 LL이지만0%가 paired 1SE 범위에 들어 더 작은0%를 선택했다. 월50%의 LL 차이는−0.000181(95% −0.000425~+0.000068)로 개선 확정 기준을 통과하지 못했고 시간 MAE도 약+0.000647초다. 따라서 월0%를 유지했다. 번호는 허용된 초 성분이 없어0/25/50% 후보가 실제로 같은 입력이다. 시간 MAE의 아주 작은 변화만으로 입상 개선이나 수익 개선이라고 해석하지 않았다.

선택을 저장한 뒤2024~2025와2026을 평가했다. R1/R2/R3의 선택률이 전부0%이므로 **이 평가에서 세 모형은 R0와 정확히 같다. 비영 보정의 후향 평가 개선을 새로 주장할 수 없다.** 비영 적용률을 평가기간 결과에 맞춰 다시 선택하지 않았다.

{table(pd.DataFrame(mainperiod))}

990경주/9,738행 전체 R0의 race-mean Top3 LL은0.576620, Brier0.195151이며 균등3/N은0.614969/0.211971이다. 이는 최소 원기록 모형의 균등 대비 결과이며 HY_R_FORM 대비 승격 근거가 아니다. 거리별 보정구간을 나눠 합산한 race-weighted ECE는 {ece:.6f}; 10개 확률구간의 예측/관측/분모는 `comparison_01/calibration_bins.csv`에 있다. 상위3/4/5/6 입상마 포함률과3두 전부 포함률, 이력0/1~4/5+·거리·등급·연도별 결과 및 날짜/주간/반복말 민감도도 보존했다. 균등 조합의 동률은 번호순이며 임의의 무작위 조합 기준과는 다르다. 적중률은 수익률이 아니다.

## 5. 채택·보류·지원 부족

| 대상 | 이번 판단 |
| --- | --- |
| 원기록 최소 기준선 R0 | 연구 비교 기준으로 유지. 운영모델 교체 없음 |
| 1000·1110m 함수율 | 별도 후보 계수 추정 완료, 비영 보정은 보류·선택률0% |
| 월·계절 | 조정 관찰과 연속 곡선 후보 계산 완료, 예측 개선 미확정·선택률0% |
| 출발번호 | 초/%p 추정 완료, 사전 초 검증 미통과·보정효과 NULL·실제적용0 |
| 900·1200m 및 과거800m | 확장 지원표만 작성. 최신 희소 조건과 시대 변화 표시, 이번 계수 미추정 |
| 1300·1400·1610m 및 과거400m | 참조 부족, 다른거리 계수로 채우지 않음 |
| 구간시간 | S1F/코너 및1110/1610·1300 정의 미확정, 전체시간 비례 배분 없음 |

`descriptive_01/all_distance_support.csv`는 과거/2019+/2024+의 거리별 조건을 모두 남긴다. 최근900m 불량12일,1200m 불량18일,800m 포화·불량 각각8일이며 이번30일 지원보다 부족하다. 1300/1400/1610·400의 부족을 매끈한 모형값으로 감추지 않았다.

## 6. 아직 모르는 부분과 다음 연구

관측 함수율·월 차이는 미측정 관리·날씨·편성·능력 오차와 얽혀 있다. 특히 불량은 강건 추정에 민감하고, 과거 원기록 자체가 기대시간 입력이라 그 기록의 환경 차이도 잔차에 남는다. 2017~18 원문 등급의 의미, 역사적 출전집합/품종과 공개시각, 번호의 실제 물리 게이트 대응은 여전히 미확정이다. 첫 전체시간 연구에는 이들의 미확정을 유지한 채 진행 가능한 범위만 사용했다.

2019~2026 자료는 이미 반복 사용한 후향 개발자료다. 시간순 분할·확률 보정·별도 계산 검증을 했어도 새 독립 미래 검증은 아니다. 추정단계 전체 재학습 bootstrap, 번호별 인과효과, 비정상 결과를 포함하는 운영 모집단, 미관측 미래 Top3/공동집합 검증은 이번에 완료하지 않았다.

다음 연구는 원기록 기준선의 재현을 유지하며 기대시간 사양/시대 변화와 고함수율의 불안정을 먼저 진단하고, 필요한 경우 새 사전 계약으로 더 많은 구조를 비교하는 것이다. 적용률과 입력 규칙을 동결한 뒤 미관측 기간을 확보해야 실제 미래 효용을 판단할 수 있다. 이번 실패를 근거로 환경효과가 없다고 결론짓거나 운영 보정으로 승격하지 않는다.

## 재현·보존

- 사전 계약: `RESEARCH_CONTRACT.md`, 해시 잠금 `contract_lock.json`.
- 감사/원천: `audit/summary.json`, `source_rows.csv`, `history_ids.json`, `race_inclusion_ledger.csv`, 제외/결과코드/주로 표, 참조파일 해시.
- 연도 밖 잔차/계수/민감도: `analysis_02/`의 기대시간 모델 JSON, 경주잔차, 함수율/월/번호 전체표, 계수 날짜 재표집, 번호 초 진단, 기록별 효과.
- 예측/선택/보정기록: `comparison_01/`의 개발 후보별 예측, 적용률 선택 잠금, 평가 예측/지표/보정도/불확실성, 모든 전처리·모형계수 JSON, 성분별 보정기록.
- 계산 검증: `verification_02/verification.json`과 별도 구현으로 재계산한 저장모형 추론 오차·T−2 경계·원천보존·손실/보정 산술·동일표본/확률합 검사. 같은 에이전트의 별도 계산 구현이며 독립 심사자 검증이라고 부르지 않는다.
- 첫 `analysis_01`은 pandas3의 읽기 전용 배열 가중치 변경 오류로 **학습 전 중단**, 로그와 빈 폴더 보존. `analysis_02`에서 배열을 복사하여 정상 완료했다. `verification_01`은 index/column 동명 정렬 검사 오류로 중단했고 수정한 `verification_02`를 새 폴더로 실행했다. 기존 결과를 삭제·덮어쓰지 않았다.
- 분석 코드는 출력 하위폴더를 새로 만드는 옵션이 있다. `audit.py`·`describe.py`·이 보고서 생성은 고정된 새 폴더의 첫 실행 전용이며 같은 경로 재실행 시 중단한다. 완전 재현은 **이 연구 폴더를 새 날짜/버전 연구 폴더로 복사하되 산출물 폴더와 로그를 제외**하고 같은 DB/참조 해시를 확인한 뒤 audit → 계약 잠금 확인 → analyze → compare → describe → verify → report 순서로 실행한다. 분석/검증 기본 출력명은 아래 재현 메모를 따른다.
'''
    # Formatting templates above are literal values, not nested format substitutions.
    text=text.replace('{:+.3f}','{:+.3f}')
    with (HERE/'RESULTS.md').open('x',encoding='utf-8') as f:f.write(text)
    readme='''# 제주 환경 보정 파일럿 v1

2026-10-07. **원기록 R0 유지. 함수율·월·번호 선택률은 모두0%.** 환경의 조정 관찰 차이는 있지만 Top3 예측 개선 기준은 통과하지 못했다. DB·HY_R_FORM·등록부·더러브렛 자산은 보존했다.

- [핵심 결과표와 해석](RESULTS.md)
- [학습 전 고정한 연구 계약](RESEARCH_CONTRACT.md)
- [원천·집계 재확인](audit/summary.json)
- [시간순 적용률 선택](comparison_01/selection_locked_before_evaluation.json)
- [최종 판단](comparison_01/decision.json)
- [계산·누수·원천 보존 검증](verification_02/verification.json)
- [함수율·월 관찰 그림](report_01/environment_effects.png)

새 결과만 이 폴더 아래 보존했다. 2019~2026은 후향 개발자료이며 독립 미래 검증이나 운영 적용 완료가 아니다. 효과 추정값과 실제 적용초/NULL 지원 상태를 구분한다.

재현 환경은 프로젝트 `.venv`의 Python3.12이며 numpy2.5.2/pandas3.0.5/scipy1.18.1/sklearn1.9.0을 사용했다. 분석 실행에는 `--output analysis_02`를 명시한다. compare 기본 입력 `analysis_02`/출력 `comparison_01`, verify `verification_02`다. 각 산출물 폴더가 없는 새 연구 복사본에서만 실행한다. 출력 폴더가 있으면 덮어쓰지 않고 중단한다. 단일 실행 예시는 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -u jeju/research/새연구폴더/analyze.py --output analysis_02`다. `modeling.py` 등은 동일 새 폴더에서 자동 참조한다. 원천 감사와 계약 해시는 재현 전에 확인한다.
'''
    with (HERE/'README.md').open('x',encoding='utf-8') as f:f.write(readme)
    # Standard standalone publication figure; English labels avoid unavailable CJK fonts.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    colors={1000:'#1f77b4',1110:'#d95f02'}
    for i,dist in enumerate([1000,1110]):
        a=latest[latest.distance==dist].set_index('band').loc[BANDS]
        ax=axs[0,i];ax.errorbar(np.arange(5),a.effect_s,yerr=np.array([a.effect_s-a.ci_lo,a.ci_hi-a.effect_s]),fmt='o',capsize=4,color=colors[dist]);ax.axhline(0,color='gray',ls='--');ax.set_xticks(range(5),['Dry','Good','Moist','Saturated','Heavy']);ax.set_title(f'{dist}m: moisture vs dry, annual OOY residuals');ax.set_ylabel('Estimated seconds (95% pointwise CI)')
        m=monthly[monthly.distance==dist];ax=axs[1,i];ax.plot(m.month,m.effect_s,color=colors[dist]);ax.fill_between(m.month,m.ci_lo,m.ci_hi,color=colors[dist],alpha=.2);ax.axhline(0,color='gray',ls='--');ax.set_xticks(range(1,13));ax.set_title(f'{dist}m: joint calendar component (mid-month display)');ax.set_xlabel('Month');ax.set_ylabel('Seconds vs annual mean')
    fig.suptitle('Jeju research candidates, trained through 2025 | Selected correction rates: 0%\nObservational contrasts; no demonstrated Top3 gain',fontsize=13)
    fig.savefig(out/'environment_effects.png',dpi=160);fig.savefig(out/'environment_effects.svg');plt.close(fig)
    manifest=[]
    for p in sorted(HERE.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:manifest.append({'path':str(p.relative_to(HERE)),'sha256':sha(p),'bytes':p.stat().st_size})
    save(out/'artifact_manifest.json',manifest)
    print('Report saved',HERE/'RESULTS.md',flush=True)
if __name__=='__main__':main()
