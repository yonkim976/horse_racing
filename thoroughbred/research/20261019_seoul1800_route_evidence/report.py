"""Publish the evidence limit and usable timing layouts without route labels as truth."""
import json
import re

import pandas as pd

import run as e


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    e.check()
    s=json.loads((e.OUT/'summary.json').read_text());v=json.loads((e.OUT/'verification.json').read_text())
    assert v['status']=='verified'
    d=pd.read_csv(e.OUT/'race_evidence.csv',dtype={'date_key':str})
    central=e.R/'conclusions/57B_SEOUL1800_ROUTE_EVIDENCE.md'
    assert not central.exists() or e.HERE.name in central.read_text()
    cases=table(['일자','경주','성적표 시각','정상 동일/정상 표시행','실제 출발점 변경'],[
        [r.date_key,r.race_no,r.clock,f'{r.live_equal}/{r.live_rows}',f'[개별 미확정]({r.scorecard_url})']
        for r in d.itertuples()])
    body=f'''# 서울1800m47경주의 실제 출발점 근거와 구간 분할

2026-10-19. 연구57B, 연구57A 후속. **47개 공식 성적표를 실제로 재조회해 정상 동일480건을 확인했지만,47경주 전부의 실제 출발점 변경을 직접 확정할 자료는 확보하지 못했다. 과거 변경 운용과2024 정상화는 공식 계획으로 확인됐다. 개별 경주의 출발점 변경 여부와 관측시간의 중복 여부를 별도 상태로 보존한다.**

## 확인한 것과 미확정인 것

기존 대상47경주를 고정해 마사회 한국어 상세 성적표47페이지의 경주일자·번호·1800m·표시시각·S1F/1C 시간 패턴과 출발점/주로 변경 명시를 브라우저로 확인했다. 정상 표시481행 중 동일480행과2010-07-17서울10경주6번 아리새의−0.1초 역순1행이 재현됐다. 비정상 원문착순91의 성장엔진1행은 정상 표시 표에 없으며 이전 전체481건과 분모가 다르다.

47개 성적표 본문에서 출발지점/주로 변경·내외주로를 명시한 문구는 검출되지 않았다. 같은 날짜에 보관된 공식 텍스트156파일·42일자도 해당 용어를 검색했지만 경주별 실제 변경을 확정하는 문구를 찾지 못했다. 공식 공지 게시판의 제목/내용 출발지점 검색은0건이었다. 이는 검색 당시 접근 범위의 결과이지 과거 공지의 완전한 부재나47경주가 변경되지 않았다는 증거가 아니다.

영상보기 링크1회 시도는 재생 가능한 영상 화면이 열리지 않아 실제 출발장소 검증으로 세지 않았다. **직접 변경 확인0/47, 변경 아님 확인0/47, 개별 실제 코스 미확정47/47**이다. 제목의47개는 동일 패턴 대상이지 변경 확정 대상이 아니다.

성적표 표시시각도47경주 모두18시 이후다. 다만2010-07-17서울10경주20:05(기존 계획20:00),2012-07-21서울10경주19:55(계획19:50),2018-08-11서울11경주20:40(계획20:35)로3개는 기존 예정시각과 다르다. 표시시각을 정밀 실측 출발시각으로 단정하지 않고 예정과 분리했다.

## 공식적으로 확인된 출발·코스 운용

2019년 시행계획 PDF16쪽과2023년 계획 PDF14쪽은 서울 악천후·야간경주에서1800m 출발점을1700m 출발점으로 바꾸고2코너에서 외주로로 주행해 전체 거리를 유지할 수 있다고 설명한다. 변경 가능 규정을 개별 경주 시행 사실로 대체하지 않는다. [2019계획](https://race.kra.co.kr/down/raceplan_2019.pdf) · [2023계획](https://race.kra.co.kr/down/raceplan_2023.pdf).

추가로 확인한2024년 시행계획 PDF11쪽(인쇄7쪽)의 운영 개선에는 **야간경마 장거리 출발지점 정상화**, 야간1800m·1900m를 당초 거리 출발지점에서 운영한다고 명시돼 있다. 기존 보유 결과에서2024~2026 동일 기록이 없는 현상과 부합한다. 이전 연구57A의 단순 관측 공백에 공식 제도 변경 근거가 추가된 것이다. [2024계획](https://race.kra.co.kr/down/raceplan2024_20240828.pdf#page=11).

따라서 과거 일부 야간1800m의 출발·주행 경로 변경 운용 자체는 확인됐다.47개 개별 경주에 대해서는 동일 시간과 야간 집중이 그 운용과 강하게 부합하는 **간접 근거**다. 별도 출발대 위치 기록·변경 공지·확인 가능한 영상 없이47개 모두를 변경 확정으로 승격하지 않는다. 기존 야간114경주 중67경주가 비중복형이라는 반례도 유지한다.

## 일반 비중복형8개 시간 구간

`출발 → S1F → 1C → 2C → 3C → G3F → 4C → G1F → 결승`

| 순서 | 구간 | 길이 확정 여부 |
| --- | --- | --- |
| 1 | 출발→S1F | 200m |
| 2 | S1F→1C | 코너 길이 미확정 |
| 3 | 1C→2C | 코너 길이 미확정 |
| 4 | 2C→3C | 코너 길이 미확정 |
| 5 | 3C→G3F | 코너 길이 미확정 |
| 6 | G3F→4C | 코너 길이 미확정 |
| 7 | 4C→G1F | 코너 길이 미확정 |
| 8 | G1F→결승 | 200m |

이는S1F/1C가 서로 다른 관측 패턴의 이름이지 나머지 모든 경주의 실제 일반 코스를 직접 확인했다는 표시가 아니다. 정상 완주 중17,532행에서 모든 지점의 누적시간이 양수 순서이며 합이 완주시간과 일치했다.1C가 뒤에 찍힌 정상17,533행 중1행은 다른 지점 순서 문제로 전체8구간 평가에 부적합하다.

## S1F·1C 중복형7개 시간 구간

`출발 → S1F(1C중복) → 2C → 3C → G3F → 4C → G1F → 결승`

| 순서 | 구간 | 일반형과 차이 |
| --- | --- | --- |
| 1 | 출발→S1F | 첫200m. 같은1C값을 다시 가산하지 않음 |
| 2 | S1F→2C | S1F→1C와1C→2C를 한 구간으로 표시 |
| 3 | 2C→3C | 구간 이름은 같아도 코스 영향을 구분해 평가 |
| 4 | 3C→G3F | 해당 유형의 관측시간 차 |
| 5 | G3F→4C | 해당 유형의 관측시간 차 |
| 6 | 4C→G1F | 해당 유형의 관측시간 차 |
| 7 | G1F→결승 | 마지막200m |

정상 동일480행 모두7구간 합이 완주시간과 일치했다. 비정상 착순까지 포함한 동일481행도 산술 분할은 가능하지만 정상 능력 표본에 자동 편입하지 않는다. 대상47경주의 전체490행 중 역순1·미제공8은 중복형 정상 구간 표본에 넣지 않는다. 역순1행에서1C를 삭제하면 합계가 맞을 수 있더라도 동일 기록으로 처리하지 않았다.

2019-07-20서울9경주2번 클린업시크릿의 누적시간은14.0 /14.0 /26.4 /64.7 /77.6 /84.0 /103.4 /117.5초다. 중복 제거 후 **14.0+12.4+38.3+12.9+6.4+19.4+14.1=117.5초**로7개가 된다.14.0→14.0의0초를 독립 구간 점수로 만들지 않는다.

출발점 변경 규정상 전체 경주거리는1800m다. 경계를 하나 줄이는 것은 중복 계측을 합치는 것이며 경주거리를1700m로 줄이거나 누락100m를 임의로 채우는 것이 아니다. 초기 출발·연결 경로가 달라질 수 있어 단지 구간 이름이 같다는 이유로 두 유형의 코너 기준치를 합치면 안 된다.

## 먼저 공통 비교할 수 있는4구간

| 구간 | 확정 길이 |
| --- | --- |
| 출발→S1F | 200m |
| S1F→G3F | 1000m |
| G3F→G1F | 400m |
| G1F→결승 | 200m |

두 유형 모두 이4분할의 명목 길이는1800m이며 정상18,014행의 합계를 검증했다. 같은 길이가 같은 코스·난도라는 뜻은 아니다. 초중반은 관측 유형을 표시해 별도 기준으로 비교하는 것이 타당하다. G3F→G1F는 결승 전600~200m의400m이며 마지막400m가 아니다. 마지막600m 요약은 결승−G3F로 별도 표시하고 세부 구간과 중복 합산하지 않는다.

정확한 코너 계측 위치·유형별 미터 길이가 아직 확정되지 않아S1F→1C를100m, G3F→4C를70m 또는100m로 단정하지 않았다. 선두의 펄롱 기록과 말별 누적시간이 비슷하다는 이유로 물리적 거리를 역산하지 않는다. 일반형/중복형 관측 상태와 실제 코스 변경의 증거 상태를 다른 열로 유지해야 한다.

##47개 경주의 증거 상태

아래 시각은 현재 공식 성적표 표시값이다. 링크는 실제 재조회한 각 경주의 성적표다. 개별 미확정은 변경 안 됨이라는 뜻이 아니다.

{cases}

## 검증과 보존

47개 대상키 완전 일치, 공식 표시행 수와 기존 정상 완주 수·480개 동일 패턴 일치,3개 시각 차이 분리,156개 보관 원문 해시·검색 결과, 전체 분할 원장과 코너 길이NULL을 독립 검증했다. 일반8개17,532정상·중복7개480정상·공통4개18,014정상 기록의 양수 구간과 완주시간 합이 맞는다. 브라우저 요약 전사 중2018-08-25서울10경주 인원12→실제10의 오류는 원천 수와 독립 대조해 수정했고 준비 기록을 보존했다.

보유 결과는2026-09-20까지이며 라이브 성적표 재조회일은2026-10-19다. 새 학습·보정·운영 반영·DB 접근·제주 접근·배포는 없다. 이 결과로47개 실제 코스 확정 작업이 끝났다고 표시하지 않는다.

[계획](PLAN.md) · [브라우저 관측 요약](browser_checks.csv) · [47개 증거 상태](outputs/race_evidence.csv) · [분할 정의](outputs/partition_definitions.csv) · [분할 검증 원장](outputs/partition_audit.parquet) · [공식 출처·조회 범위](outputs/official_sources.json) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 서울1800m 과거 야간 출발점과7·8구간의 구분

2026-10-19. 연구57B,57A 후속. 관측시간 분할과 실제 코스 확인을 구분한다.

확인 결과: 대상47개 공식 성적표를 모두 재조회해 정상 동일480행·역순1행을 재확인했다. 다만 개별 출발점 변경을 직접 명시한 자료는 확보하지 못해 변경 확정0/47·개별 미확정47/47로 보존했다. 이는 변경 안 됨이라는 뜻이 아니다. 보관 공식 텍스트156개와 공지 검색도 확인했다.

새 공식 근거:2024 시행계획 PDF11쪽에는 야간1800·1900m 출발점을 원래 위치로 정상화한다고 명시돼 있다.2019/2023 대체 출발 규정과 함께 과거 운용과 이후 변경을 뒷받침한다. 개별47경주 실제 시행 여부는 별도 증거가 필요하다.

기록 읽기: 일반 비중복형은 출발→S1F→1C→2C→3C→G3F→4C→G1F→결승의8구간,중복형은1C를 중복 제거한7구간이다. 클린업시크릿2019-07-20은14.0+12.4+38.3+12.9+6.4+19.4+14.1=117.5초다.0초 구간을 독립 점수로 만들지 않는다.

적용 범위: 공통 확정길이는200+1000+400+200m다. 실제 경주거리를 줄이거나 코너 길이를 추정 생성하지 않는다. 초중반 코스가 다를 가능성을 표시하고 같은 이름의 구간을 무조건 같은 기준으로 평가하지 않는다. 정상8구간17,532·중복7구간480·공통4구간18,014행 합계 검증. 새 보정·모델 적용 없음.

[전체 보고서와47경주 링크](README.md) · [증거 상태](outputs/race_evidence.csv) · [분할 정의](outputs/partition_definitions.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/')+'\n원연구: '+e.HERE.name+'\n')
    marker='<!-- seoul1800_route_evidence_20261019 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        p=e.R/name;link=f'{e.HERE.name}/README.md' if name=='README.md' else central.name
        if marker not in p.read_text():
            with p.open('a') as f:f.write(f'\n\n{marker}\n[연구57B 서울1800 출발점 근거와 구간 분할]({link}): 공식47성적표480동일 재확인, 개별 변경 직접 확정0/47·미확정47.2024 야간 출발점 정상화 공식 확인. 일반8/중복7/공통4구간을 검증하고 실제 코스 증거와 관측 유형을 분리했다. 새 모델·운영 변경 없음.\n')
    e.save(e.OUT/'completion.json',dict(status='evidence_audit_completed_individual_routes_unresolved',
        verified_timing_layouts=True,route_confirmation_complete=False,route_unresolved=47,
        new_models=0,database_access=False,production_changed=False,deployed=False))
    mf=e.R/'conclusions/source_manifest.json';source=json.loads(mf.read_text())
    own=[p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        k=str(p.relative_to(e.ROOT));source['sources']=[r for r in source['sources'] if r['path']!=k]
        source['sources'].append(dict(path=k,sha256=e.sha(p),bytes=p.stat().st_size))
    e.save(mf,source)
    for p in [e.HERE/'README.md',e.HERE/'PUBLICATION.md',central]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if not link.startswith(('https:','http:','#')) and not link.endswith('artifact_inventory.json'):assert (p.parent/link).exists(),link
    e.check();print('Evidence audit preserved;47 individual route confirmations remain unresolved')


if __name__=='__main__':main()
