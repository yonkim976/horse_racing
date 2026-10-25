"""Audit nominal distances separately from general corner definitions."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
POINTS=['START','S1F','1C','2C','3C','G3F','4C','G1F','FIN']
KNOWN={'START':0,'S1F':200,'G3F':1200,'G1F':1600,'FIN':1800}
GENERAL={'START':0,'S1F':200,'1C':120,'2C':400,'3C':990,'G3F':1200,'4C':1270,'G1F':1600,'FIN':1800}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for k,v in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/k)==v,k


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=R/'20261019_seoul1800_s1f_1c_audit/outputs/runner_audit.parquet'
    paths=[HERE/'PLAN.md',HERE/'run.py',source,ROOT/'docs/SEOUL_CORNER_POSITIONS_2026-09-09.md',
           ROOT/'src/horse_racing/web/seoul_metric.py',ROOT/'data/raw/seoul_section_audit/web_1800.html',
           ROOT/'config/prediction_model_registry.json']
    expected={str(p.relative_to(ROOT)):sha(p) for p in paths};mf=OUT/'input_manifest.json'
    if mf.exists():assert json.loads(mf.read_text())==expected
    else:save(mf,expected)
    before=OUT/'publication_before.json'
    if not before.exists():
        shared=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','SEOUL1800_RECORD_GROUPS.md']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
    points=[dict(point=p,verified_elapsed_m=KNOWN.get(p),verified_remaining_m=1800-KNOWN[p] if p in KNOWN else None,
        status='confirmed_nominal' if p in KNOWN else 'unresolved_for_standard1800',
        general_glossary_elapsed_m_not_adopted=GENERAL[p],general_glossary_remaining_m=1800-GENERAL[p]) for p in POINTS]
    pd.DataFrame(points).to_csv(OUT/'checkpoint_distances.csv',index=False)
    parts=[]
    for left,right in zip(POINTS,POINTS[1:]):
        known=left in KNOWN and right in KNOWN
        parts.append(dict(left=left,right=right,verified_length_m=KNOWN[right]-KNOWN[left] if known else None,
            status='confirmed_nominal' if known else 'unresolved_corner_timing_line',
            general_glossary_only_candidate_m_not_adopted=GENERAL[right]-GENERAL[left]))
    pd.DataFrame(parts).to_csv(OUT/'adjacent_distances.csv',index=False)
    coarse=[dict(left=a,right=b,length_m=KNOWN[b]-KNOWN[a]) for a,b in zip(['START','S1F','G3F','G1F'],['S1F','G3F','G1F','FIN'])]
    pd.DataFrame(coarse).to_csv(OUT/'confirmed_coarse_distances.csv',index=False)
    raw=pd.read_parquet(source);ordinary=raw[raw.normal_finish&raw.comparison.eq('later')].copy()
    assert len(ordinary)==17533 and (ordinary['1C_ms']>ordinary.S1F_ms).all()
    sample=ordinary[ordinary.date_key.eq('20260906')&ordinary.race_no.eq(9)&ordinary.program_no.eq(8)].iloc[0]
    # Values independently viewed on KRA live scorecard2026-09-06race9.
    live=[14.2,19.8,32.3,65.8,73.2,80.3,98.5,111.7]
    observed=[float(sample[p+'_ms']/1000) for p in POINTS[1:-1]]+[float(sample.finish_seconds)]
    np.testing.assert_allclose(observed,live,rtol=0,atol=1e-8)
    save(OUT/'sample_scorecard.json',dict(date='20260906',race_no=9,program_no=8,horse='딕테이언',
        points=POINTS[1:],seconds=live,source='https://race.kra.co.kr/raceScore/ScoretableDetailList.do?meet=1&realRcDate=20260906&realRcNo=9',
        live_checked_on='2026-10-19',positions_not_inferred_from_times=True))
    assert sum(x['length_m'] for x in coarse)==1800
    assert sum(x['verified_length_m'] is None for x in parts)==6
    assert GENERAL['1C']<KNOWN['S1F'] and GENERAL['1C']-KNOWN['S1F']==-80
    save(OUT/'verification.json',dict(status='verified_available_evidence',ordinary_normal_rows=17533,
        s1f_before_1c_rows=17533,glossary_chain_invalid_for_ordinary1800=True,
        glossary_s1f_to_1c_m=-80,unresolved_corners=['1C','2C','3C','4C'],
        unresolved_adjacent_intervals=6,confirmed_coarse_sum_m=1800,live_sample_time_error=0,
        no_corner_lengths_fabricated=True,source_hashes=len(expected),new_models=0,database_access=False))
    save(OUT/'official_sources.json',dict(checked_on='2026-10-19',sources=[
        dict(url='https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1',scope='general glossary;not distance-specific survey',
             s1f_after_start_m=200,g3f_remaining_m=600,g1f_remaining_m=200,corners_remaining_m={'1C':1680,'2C':1400,'3C':810,'4C':530}),
        dict(url='https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=11&meet=1',scope='track geometry and200m furlong boards;no corner camera timing-line coordinates'),
        dict(url='https://race.kra.co.kr/images/sub/seoul_racemap02.jpg',scope='visually inspected official dimension map;straight450m,inner curve350m,outer curve450m;circlednumbers are furlong boards,not1C-4C'),
        dict(url='https://race.kra.co.kr/raceScore/ScoretableDetailList.do?meet=1&realRcDate=20260906&realRcNo=9',scope='live scorecard observation;time ordering only,not physical-distance survey')],
        rejected_methods=['SVG pixel measurement','time-to-distance interpolation','minimum corner time matched to leader furlong as surveyed coordinate','unverified historical third-party distance tables']))
    point_table=table(['계측점','출발 후 위치','결승까지 거리','일반1800 적용 상태'],[
        [p,'출발' if p=='START' else '결승' if p=='FIN' else str(KNOWN[p])+'m' if p in KNOWN else '미확정',
         str(1800-KNOWN[p])+'m' if p in KNOWN else '미확정','확정 명목거리' if p in KNOWN else '거리별 계측선 명세 필요'] for p in POINTS])
    interval_table=table(['인접 구간','일반1800 확정 길이'],[
        [x['left']+'→'+x['right'],str(x['verified_length_m'])+'m' if x['verified_length_m'] is not None else '미확정'] for x in parts])
    body=f'''# 일반 서울1800m 계측 지점 사이의 거리 확정 범위

2026-10-19. 연구57C. **S1F·G3F·G1F의 명목 위치는 확정할 수 있지만,1C·2C·3C·4C의 일반1800m 계측선 위치는 확보한 공식 자료로 아직 확정하지 못했다. 따라서 전체8개 인접 구간 중 첫200m와 마지막200m만 확정 길이를 쓸 수 있다.** 시간 구간을 나눌 수 있다는 사실과 미터 길이가 검증됐다는 사실을 구분한다.

## 대상

[기록군 구분 결정](../SEOUL1800_RECORD_GROUPS.md)에 따른 일반 비중복 정상17,533건이다. 동일480건과 역순1건은 제외했다. 원천 결과 기간2010-01-09~2026-09-20,공식 자료 재확인2026-10-19. 일반군17,533건 모두1C 누적시간이S1F보다 뒤다. 다른 계측지점까지 포함해8구간 전체가 유효한 건17,532건으로,이번에 그 기준이나 표본을 바꾸지 않았다.

## 지점 위치

{point_table}

확정은 경주 기준거리의 정의다. 개별 말이 외측으로 돌거나 사행한 실제 이동거리,계측 장비의 측량 오차까지 확정했다는 뜻은 아니다.

## 인접8구간

{interval_table}

각 코너의 누적시간 차는 계산 가능하지만 길이가 없는 구간에서m/s 또는200m 환산 속도를 확정값으로 산출하지 않는다.

## 일반 용어해설을 그대로 대입하면 생기는 모순

마사회 일반 설명은1C/2C/3C/4C를 결승 전1680/1400/810/530m라고 적는다. 이를1800에서 빼면 출발 후120/400/990/1270m가 된다. 그러나S1F는 출발 후200m이므로 **1C120m가S1F200m보다 앞서고,S1F→1C가−80m가 된다.** 일반군17,533건의 실제 시간 순서와 맞지 않는다. [공식 용어해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1).

예를 들어2026-09-06서울9경주8번 딕테이언은S1F14.2초→1C19.8초→2C32.3초→3C65.8초→G3F73.2초→4C80.3초→G1F98.5초→결승111.7초다. 일반1800의1C를 출발120m라고 적용할 수 없는 구체적인 대조 사례다. [공식 성적표](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?meet=1&realRcDate=20260906&realRcNo=9).

2C400m·3C990m·4C1270m도 일반 설명으로 계산되는 값일 뿐,거리별 내주로 계측선 명세로 확인한 값이 아니다. 공식4C530m 설명은 그대로 보존한다. 다만 이를 일반1800에 적용해G3F→4C70m,4C→G1F330m로 확정하지 않는다. ‘공식 일반 설명’과 ‘해당 거리에서 검증된 물리적 계측점’을 구분한다. 기존 웹 지도4C530m 표시는 그 일반 설명을 사용한 참고 위치이지 이번 연구의 거리별 확정 결과가 아니다. 웹 지도는 수정하지 않았다.

## 공식 도면으로 확인되는 범위

공식 수치 도면과 주로 구조 설명은 내주로1600m/외주로1800m,직선450m,내곡선350m/외곡선450m와 거리별 출발부를 설명한다. 하지만 코너 누적시간을 찍는 정확한 계측선과 해당 거리의 기준 주행선 교점을 표시하지 않는다. 도면의 원 안 숫자1~8은200m 간격 펄롱 표지다. 그것을1C·2C·3C·4C로 읽어 거리를 재면 안 된다. [공식 주로 구조](https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=11&meet=1) · [공식 수치 도면](https://race.kra.co.kr/images/sub/seoul_racemap02.jpg).

기존9월9일 코너 참고 위치 연구도1800m의 코너 위치를 참고 좌표에 채택하지 않았다. 선두 펄롱시간과 코너 최소시간이 비슷하다고 해서 같은 계측 위치나 정확한 길이가 증명되지는 않는다. 다른 거리의 참고값을 복사하거나 과거 비공식 표를 현재 계측거리로 채택하지 않았다.

## 현재 사용할 확정 분할과 남은 자료

**출발→S1F200m / S1F→G3F1000m / G3F→G1F400m / G1F→결승200m**,합1800m다. 마지막600m는 별도 요약이고,G3F→G1F400m는 결승 전600~200m 구간이다. 마지막400m로 표시하지 않는다.

코너 구간을 확정하려면 마사회의 **일반1800m 주행 경로별 계측선 배치도 또는 출발점 기준1C·2C·3C·4C 계측거리 명세**가 필요하다. 내·외주로 구분과 적용 연도,기준선 정의까지 있어야2010~2026 자료에 어느 범위로 쓸지 판단할 수 있다. 이번에 그 문서를 확보하지 못했으므로 미확정4지점·6인접구간을NULL로 보존한다.

7개 보호 입력 해시,일반군 시간 순서17,533행,라이브 성적표 표본과 보관 원천의 오차0,공통 길이합1800m와−80m 모순을 검증했다. 새 모델·보정·DB 접근·웹 변경·배포 없음. 물리적 코너거리의 전부 확정은 미완료 상태다.

[계획](PLAN.md) · [지점별 거리·상태](outputs/checkpoint_distances.csv) · [인접 거리](outputs/adjacent_distances.csv) · [확정4분할](outputs/confirmed_coarse_distances.csv) · [원문 표본](outputs/sample_scorecard.json) · [출처와 제외한 방법](outputs/official_sources.json) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
'''
    (HERE/'README.md').write_text(body)
    pub='''# 일반 서울1800m 구간 거리는 어디까지 확정됐나

2026-10-19. 연구57C. S1F·1C 동일480건을 제외한 일반 비중복군 기준이다.

출발 후 위치는S1F200m/G3F1200m/G1F1600m/결승1800m가 확정 명목거리다.1C·2C·3C·4C의 거리별 실제 계측선 위치는 아직 미확정이다. 전체8개 인접 구간 중 출발→S1F200m와G1F→결승200m만 확정 길이를 쓸 수 있다.

공식 일반 용어해설의1C 결승 전1680m를1800에 대입하면 출발120m가 돼S1F200m보다 앞선다. 실제 일반군17,533건은 모두1C가S1F보다 뒤여서 순서가 맞지 않는다. 딕테이언2026-09-06서울9경주도S1F14.2초/1C19.8초다. 일반 설명을 거리별 측량 명세로 대신할 수 없다.

주로 수치 도면에는 코너 계측선이 표시돼 있지 않고 원 안 숫자1~8은 펄롱 표지다.4C의 공식 일반 설명530m는 유지하지만 일반1800의G3F→4C70m/4C→G1F330m로 확정 적용하지 않는다. 현재 공통 분할은200+1000+400+200m이며 코너 계측선 배치도·거리별 측정거리 명세가 추가로 필요하다. 새 보정·모델·웹 지도 변경 없음.

[전체 지점·구간 표](README.md) · [거리와 상태](outputs/checkpoint_distances.csv) · [검증](outputs/verification.json)
'''
    (HERE/'PUBLICATION.md').write_text(pub)
    central=R/'conclusions/57C_SEOUL1800_CHECKPOINT_DISTANCES.md'
    assert not central.exists() or HERE.name in central.read_text()
    central.write_text(pub.replace('(README.md)',f'(../{HERE.name}/README.md)').replace('(outputs/',f'(../{HERE.name}/outputs/')+'\n원연구: '+HERE.name+'\n')
    marker='<!-- seoul1800_checkpoint_distances_20261019 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        p=R/name;link=f'{HERE.name}/README.md' if name=='README.md' else central.name
        if marker not in p.read_text():
            with p.open('a') as f:f.write(f'\n\n{marker}\n[연구57C 일반 서울1800 계측 지점 거리]({link}): S1F200/G3F1200/G1F1600m 확정, 코너4지점·인접6구간 미확정. 일반 해설의1C120m는 실제 시간 순서와 충돌. 도면의 펄롱 표지와 계측선을 구분하고200+1000+400+200m만 확정 적용한다. 새 모델·웹 변경 없음.\n')
    policy=R/'SEOUL1800_RECORD_GROUPS.md'
    if marker not in policy.read_text():
        with policy.open('a') as f:f.write(f'\n\n{marker}\n일반 비중복군의 코너별 미터 길이는 [연구57C의 지점 거리 감사]({HERE.name}/README.md)를 따른다. 일반 용어해설의 잔여거리를 그대로 대입하지 않으며 코너4지점과 인접6구간은 아직 미확정이다.\n')
    save(OUT/'completion.json',dict(status='available_evidence_audited_corner_distances_unresolved',unresolved_corners=4,
        all_corner_distances_confirmed=False,new_models=0,database_access=False,web_changed=False))
    mpath=R/'conclusions/source_manifest.json';m=json.loads(mpath.read_text())
    own=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central,policy]+[R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        k=str(p.relative_to(ROOT));m['sources']=[x for x in m['sources'] if x['path']!=k]
        m['sources'].append(dict(path=k,sha256=sha(p),bytes=p.stat().st_size))
    save(mpath,m)
    for p in [HERE/'README.md',HERE/'PUBLICATION.md',central]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if not link.startswith(('http:','https:','#')) and not link.endswith('artifact_inventory.json'):assert (p.parent/link).exists(),(p,link)
    check();print((OUT/'verification.json').read_text())


if __name__=='__main__':main()
