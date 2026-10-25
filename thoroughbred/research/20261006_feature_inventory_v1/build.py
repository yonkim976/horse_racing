"""Read-only inventory of the current model contract, definitions and example values."""
from pathlib import Path
import html
import json
import re
import hashlib
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
STUDY=HERE.parent/'20261006_moisture_no_jockey_v1'
RAW=HERE.parent/'20261004_outsider_joint_v1/outputs/features.parquet'
ADJUSTED=HERE.parent/'20261005_moisture_finish_v1/outputs/adjusted_features.parquet'

MEASURES={
 'win':('우승 여부','0/1 또는 비율'),'top3':('1~3착 여부','0/1 또는 비율'),
 'nonfinish':('미완주 여부','0/1 또는 비율'),'rank_fraction':('최종착순의 상대 위치: (착순−1)/(출전두수−1), 미완주1','비율'),
 'record_index':('지역·거리의 이전 연도 기록 중앙값과 척도로 표준화한 전체시간: 클수록 빠름','지수'),
 'start_200':('실전 출발200m 시간','초'),'last_200':('실전 마지막200m 시간','초'),
 'last_600':('실전 마지막600m 시간','초'),
 'S1F_fraction':('S1F 통과순위 상대 위치: (순위−1)/(출전두수−1), 0이 선두','비율'),
 'S1F_lead':('S1F 통과순위1위 여부','0/1 또는 비율'),
 'S1F_front':('S1F 통과순위3위 이내 여부','0/1 또는 비율'),
 'G3F_fraction':('G3F 통과순위 상대 위치: 0이 선두','비율'),
 'G3F_lead':('G3F 통과순위1위 여부','0/1 또는 비율'),
 'G3F_front':('G3F 통과순위3위 이내 여부','0/1 또는 비율'),
 'advance':('S1F 상대 위치−G3F 상대 위치: 양수면 앞으로 진출','비율 차이'),
 'historical_start_time':('과거 S1F 출발200m 시간','초')}
DIRECT={
 'history_count':('과거 실전 출전수','회'),
 'previous_result_distance':('직전 실전 거리','m'),'previous_age':('직전 실전 당시 나이','세'),
 'previous_sex':('직전 실전 당시 성별','범주'),'previous_carried_weight':('직전 실전 부담중량','kg'),
 'previous_body_weight':('직전 실전 마체중','kg'),
 'body_weight_change':('직전 마체중−그 이전 출전 마체중','kg'),
 'carried_weight_change':('직전 부담중량−그 이전 출전 부담중량: 이번 중량 차이가 아님','kg'),
 'same_distance_history_count':('이번과 같은 거리의 과거 출전수','회'),
 'same_distance_top3_rate':('이번과 같은 거리의 과거 입상률','비율'),
 'same_distance_last_finish':('이번과 같은 거리에서 가장 최근 유효 전체시간','초'),
 'same_distance_last5_finish_mean':('이번과 같은 거리의 최근5회 유효 전체시간 평균','초'),
 'distance_m':('이번 경주 거리','m'),'grade':('이번 경주 숫자 등급','등급'),
 'grade_kind':('이번 경주 국/혼/기타 구분','범주'),'month':('이번 경주 월','월'),
 'field_size':('이번 평가 편성 출전두수','두'),'days_since_last':('직전 실전 이후 경과일','일'),
 'distance_change':('이번 거리−직전 실전 거리','m'),
 'record_index_change':('직전 기록지수−그 이전 출전 기록지수','지수 차이'),
 'last5_record_index_std':('최근5전 기록지수의 표준편차','지수'),
 'pace_unknown_early_count':('편성 중 최근3전 초반 상대위치가 없는 말의 수','두'),
 'pace_habitual_lead_count':('최근5전 S1F 선두 비율이25% 이상인 편성 말 수','두'),
 'pace_faster_competitors':('최근3전 초반시간이 자신보다0.2초 넘게 빠른 상대 수','두'),
 'pace_close_competitors':('최근3전 초반시간이 자신과0.2초 이내인 상대 수','두'),
 'gate_number_proxy':('출발마번을 사용한 게이트번호 대리값','번호'),
 'gate_fraction_proxy':('(마번−1)/(결과카드 최대마번−1): 내측0~외측1','비율'),
 'gate_inner_proxy':('상대게이트1/3 미만이면1','0/1'),
 'gate_outer_proxy':('상대게이트2/3 이상이면1','0/1'),
 'gate_style_interaction':('상대게이트×최근3전 S1F 상대위치','곱'),
 'conditioned_gate_style':('상대게이트×거리조건을 완화한 S1F 앞선3두 성향','곱'),
 'trial_count':('해당 경마장의 유효 주행심사 이력수','회'),
 'trial_days_since':('최근 유효 주행심사 이후 경과일','일'),
 'trial_time_minus_race':('주행심사 최근3회 S1F시간−실전 최근3전 S1F시간','초'),
 'trial_has_time':('주행심사 최근3회 유효 S1F시간이 있으면1','0/1'),
 'trial_field_unknown_count':('편성 중 주행심사 최근3회 S1F시간이 없는 말 수','두'),
 'distance_band':('이번 거리군: ≤1300/1301~1600/>1600m, 미상 별도','범주'),
 'conditioned_faster_competitors':('거리조건을 고려한 과거초반시간이0.2초 넘게 빠른 상대 수','두'),
 'conditioned_close_competitors':('거리조건을 고려한 과거초반시간이0.2초 이내인 상대 수','두'),
 'conditioned_unknown_count':('거리조건을 고려한 S1F 상대위치가 없는 편성 말 수','두'),
 'context_previous_grade':('직전 실전 숫자등급','등급'),
 'context_grade_change':('이번 숫자등급−직전 숫자등급: 음수는 높은 등급으로 이동','등급 차이'),
 'context_grade_history_known':('직전 등급을 알면1','0/1'),
 'context_direction':('직전 대비 거리 변화: 늘림1/줄임−1/동일0/미상3','범주'),
 'transition_style_history_count':('이번과 같은 거리 변화 방향의 과거 출전수','회'),
 'transition_style_days_since':('이번과 같은 거리 변화 방향의 최근 출전 이후 경과일','일'),
 'moist_last_correction_seconds':('직전 유효 전체시간에 적용한 건조환산 보정초: 미지원0, 직전 미완주 결측','초'),
 'moist_last5_supported_fraction':('최근5전 유효 전체시간 중 계수 지원조건을 충족한 비율','비율'),
 'moist_last5_abs_correction_mean':('최근5전 유효 전체시간의 절대보정초 평균','초')}
UPSIDE={
 'best_gap':'최근5전 최고기록지수−최근3전 평균지수',
 'best_relative':'최근5전 최고기록지수−이번 다른 상대들의 최고지수 평균',
 'best_rank':'최근5전 최고기록지수의 편성 내 상대순위: 높을수록 우위',
 'last_rank':'직전 기록지수의 편성 내 상대순위: 높을수록 우위',
 'closing_rank':'최근3전 막판600m 시간의 편성 내 상대순위: 빠를수록 높음',
 'start_rank':'최근3전 출발200m 시간의 편성 내 상대순위: 빠를수록 높음',
 'trial_rank':'주행심사 최근3회 세션중앙값 대비 S1F시간의 편성 내 상대순위',
 'balance':'막판600m 상대순위−초반200m 상대순위',
 'low_history':'1/(1+과거 출전수)',
 'record_count':'최근5전 유효 기록지수 관측수/5',
 'low_history_trial':'적은경력값×주행심사 상대순위',
 'low_history_best':'적은경력값×최고기록의 다른 상대 대비 차이',
 'growth':'직전 기록지수 변화×직전 당시4세 이하 표시',
 'distance_closing':'거리변경/400을−2~2로 제한한 값×막판−초반 상대순위',
 'grade_best':'등급변화를−2~2로 제한한 값×최고기록의 다른 상대 대비 차이',
 'pressure':'이번 다른 상대들의 거리군 조건 S1F 앞선3두 성향 평균',
 'pressure_closing':'상대 앞선성향 압력×자신의 막판 상대순위',
 'pressure_front':'상대 앞선성향 압력×자신의 앞선성향'}

def describe(col):
    if col in DIRECT:return DIRECT[col]
    if col.startswith('moist_'):
        desc,unit=describe(col[6:]);return '건조환산 전체기록을 사용한 '+desc,unit
    if col.startswith('relative_'):
        stem=col[9:]
        if stem=='career_top3_rate':desc,unit=describe(stem)
        elif stem.startswith('trial_'):desc,unit=describe(stem)
        else:desc,unit=describe(stem)
        return desc+' − 이번 편성의 평균',unit
    if col.startswith('career_') and col.endswith('_rate'):
        stem=col[7:-5];desc,_=MEASURES[stem];return '과거 전체 출전의 '+desc+' 평균','비율'
    if col.startswith('upside_'):return UPSIDE[col[7:]],'가공값'
    match=re.fullmatch(r'last(5|10)_record_index_(best|count)',col)
    if match:return f'최근{match[1]}전 기록지수의 '+('최댓값' if match[2]=='best' else '유효 관측수'),('지수' if match[2]=='best' else '회')
    match=re.fullmatch(r'(last|last(3|5|10))_(.+?)(?:_mean)?',col)
    if match and match[3] in MEASURES:
        desc,unit=MEASURES[match[3]];return ('직전 '+desc if match[1]=='last' else f'최근{match[2]}전 '+desc+' 평균'),unit
    if col.startswith('pace_relative_'):
        desc,unit=describe(col[14:]);return desc+' − 이번 편성의 평균',unit
    match=re.fullmatch(r'pace_(previous|last(3|5|10))_(.+?)(_count)?',col)
    if match and match[3] in MEASURES:
        desc,unit=MEASURES[match[3]]
        if match[4]:return f'최근{match[2]}전 '+desc+' 유효 관측수','회'
        return ('직전 '+desc if match[1]=='previous' else f'최근{match[2]}전 '+desc+' 평균'),unit
    match=re.fullmatch(r'(band_style|exact_style)_(.+)',col)
    if match:
        where='같은 경마장·거리군' if match[1]=='band_style' else '같은 경마장·동일 거리'
        stem=match[2]
        if stem=='history_count':return where+'의 과거 출전수','회'
        if stem=='days_since':return where+'의 최근 출전 이후 경과일','일'
        metric,stat=stem.rsplit('_',1);desc,unit=MEASURES[metric]
        return where+' 최근5회의 '+desc+(' 평균' if stat=='mean' else ' 유효 관측수'),unit if stat=='mean' else '회'
    match=re.fullmatch(r'conditioned_(band|exact|difference)_(.+)',col)
    if match and match[2] in MEASURES:
        desc,unit=MEASURES[match[2]]
        text={'band':'거리군 평균을 최근5전 전체이력 쪽으로 완화한 ',
              'exact':'동일거리 평균을 완화된 거리군 이력 쪽으로 추가 완화한 ',
              'difference':'완화된 동일거리 값−최근5전 전체이력: '}[match[1]]
        return text+desc,unit
    if col.startswith('field_relative_conditioned_'):
        metric=col.removeprefix('field_relative_conditioned_');desc,unit=describe('conditioned_exact_'+metric)
        return desc+' − 이번 편성의 평균',unit
    match=re.fullmatch(r'transition_style_transition_(.+)_(mean|count)',col)
    if match:
        label={'fraction_delta':'S1F 상대위치가 이전출전 대비 변한 정도',
               'advance_delta':'S1F→G3F 진출 정도가 이전출전 대비 변한 정도',
               'front_lost':'이전출전 S1F3위이내였으나 이번에3위밖으로 나온 여부',
               'lead_lost':'이전출전 S1F1위였으나 이번에1위를 잃은 여부'}[match[1]]
        return '이번과 같은 거리 변화 방향 최근5회: '+label+(' 평균' if match[2]=='mean' else ' 유효 관측수'),'비율' if match[2]=='mean' else '회'
    match=re.fullmatch(r'trial_(previous|last3)_(time|fraction|session_delta|pass)(_count)?',col)
    if match:
        label={'time':'주행심사 S1F 출발200m 시간','fraction':'주행심사 S1F 상대 통과순위',
               'session_delta':'주행심사 S1F시간−동일 심사세션 S1F중앙값','pass':'주행심사 합격 여부'}[match[2]]
        unit={'time':'초','fraction':'비율','session_delta':'초','pass':'0/1 또는 비율'}[match[2]]
        if match[3]:return '최근3회 '+label+' 유효 관측수','회'
        return ('최근1회 '+label if match[1]=='previous' else '최근3회 '+label+' 평균'),unit
    raise ValueError('Unmapped input: '+col)

GROUPS=[(1,25,'경력·성적·과거 상태'),(26,53,'시간기록·중량 변화'),(54,66,'편성 조건·상대 비교'),
        (67,115,'통과순위 전개 이력'),(116,120,'기본 게이트'),(121,140,'주행심사'),
        (141,203,'거리별 전개·편성 관계'),(204,217,'거리·등급 변화 이력'),
        (218,235,'기량 변화·후순위 파생값'),(236,258,'주로 보정 기록·지원 이력')]

def main():
    contract=STUDY/'outputs/feature_contract.json';cols=json.loads(contract.read_text())['no_jockey']
    assert len(cols)==258 and len(set(cols))==258
    raw=pd.read_parquet(RAW);adj=pd.read_parquet(ADJUSTED)
    assert raw[['race_key','program_no','horse_id']].equals(adj[['race_key','program_no','horse_id']])
    sample=raw[raw.meet.eq(1)&raw.race_date.eq(raw.loc[raw.meet.eq(1),'race_date'].max())].sort_values(['race_no','program_no']).index[0]
    records=[]
    for i,col in enumerate(cols,1):
        group=next(g for lo,hi,g in GROUPS if lo<=i<=hi);desc,unit=describe(col)
        if col.startswith('moist_'):v=adj.loc[sample,col] if col in adj else adj.loc[sample,col[6:]]
        else:v=raw.loc[sample,col]
        value=None if pd.isna(v) else v.item() if hasattr(v,'item') else v
        records.append(dict(index=i,feature=col,group=group,description=desc,unit=unit,example=value))
    meta=dict(date='2026-10-06',model='research/no_jockey',features=258,
              sample_race=raw.loc[sample,'race_key'],sample_program=int(raw.loc[sample,'program_no']),
              sample_horse=str(raw.loc[sample,'horse_name']),sample_is_historical=True,
              contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
              source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [RAW,ADJUSTED]},
              groups=[dict(group=g,count=hi-lo+1) for lo,hi,g in GROUPS])
    (HERE/'inventory.json').write_text(json.dumps(dict(metadata=meta,inputs=records),ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for r in records:
        value='없음' if r['example'] is None else f'{r["example"]:.4g}' if isinstance(r['example'],float) else str(r['example'])
        cells=[r['index'],r['feature'],r['description'],r['unit'],value]
        rows.append('<tr data-group="'+html.escape(r['group'],quote=True)+'">'+''.join('<td>'+html.escape(str(c))+'</td>' for c in cells)+'</tr>')
    options=''.join('<option>'+html.escape(g)+'</option>' for _,_,g in GROUPS)
    title=html.escape(f'{meta["sample_race"]} / {meta["sample_program"]}번 {meta["sample_horse"]}')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>연구 모델 입력258개</title><style>body{font-family:system-ui,sans-serif;margin:32px;color:#16252e;background:#f7fafb}main{max-width:1300px;margin:auto}h1{font-size:27px}p{line-height:1.7}input,select{padding:12px;font-size:15px;border:1px solid #bccbd1;border-radius:6px;margin:6px 8px 18px 0}table{width:100%;border-collapse:collapse;background:white}td,th{padding:11px;text-align:left;vertical-align:top;border-bottom:1px solid #e2e9ec}th{position:sticky;top:0;background:#eaf1f4}td:nth-child(2){font-family:monospace;font-size:12px;overflow-wrap:anywhere;max-width:310px}td:last-child{font-variant-numeric:tabular-nums;white-space:nowrap}.note{background:#e8f1f7;padding:18px;border-radius:8px}small{color:#546b78}@media(max-width:700px){body{margin:14px}td,th{padding:8px;font-size:13px}table{min-width:760px}.scroll{overflow:auto}}</style>
<main><h1>현재 연구 모델의 입력258개</h1><p>258개는 한 말의 한 경주 예측에 사용하는 <b>열의 수</b>입니다. 같은 원천의 직전값·여러 기간 평균·최고값·상대값·관계값이 각각 한 열이며 독립적인 정보258종이 아닙니다.</p>
<div class="note">기수 입력26개는 제외했습니다. 별도 전개 모델 예측값과 통과조 마군·간격·실제 내외측은 현재 사용하지 않습니다. 게이트 내/외는 출발번호 대리값입니다. joint 조합관계12개는 이258개 단일말 입력과 별도입니다.</div>
<p><b>과거 입력 예시:</b> SAMPLE<br><small>새 경주 예측이나 추천이 아닙니다. 과거 이력은 해당 경주의T−2까지 사용합니다. 빈 값은 없는 정보이며 임의의0과 다릅니다. 중량·나이·성별의 previous_는 직전 출전 당시 값입니다.</small></p>
<input id="search" placeholder="입력명·설명 검색"><select id="group"><option value="">전체 묶음</option>OPTIONS</select><span id="count">258개</span>
<div class="scroll"><table><thead><tr><th>번호</th><th>입력명</th><th>실제 정의</th><th>단위</th><th>예시값</th></tr></thead><tbody>ROWS</tbody></table></div>
<p>같은 정보에서 나온 열은 함께 평가하고, 최근3전/5전/10전 선택은 별도 비교하는 단계가 적절합니다. 이 화면은 입력 정의를 설명하며 변수의 유효성이나 채택을 보장하지 않습니다.</p></main>
<script>const rows=[...document.querySelectorAll('tbody tr')];const search=document.querySelector('#search');const group=document.querySelector('#group');function filter(){let n=0;const q=search.value.toLowerCase();for(const row of rows){const show=(!group.value||row.dataset.group===group.value)&&row.textContent.toLowerCase().includes(q);row.hidden=!show;if(show)n++;}document.querySelector('#count').textContent=n+'개';}search.addEventListener('input',filter);group.addEventListener('change',filter);</script></html>'''
    page=page.replace('SAMPLE',title).replace('OPTIONS',options).replace('ROWS',''.join(rows))
    (HERE/'inputs.html').write_text(page)
    print(json.dumps(meta,ensure_ascii=False));print('Definitions:',len(records),'no unmapped columns')

if __name__=='__main__':main()
