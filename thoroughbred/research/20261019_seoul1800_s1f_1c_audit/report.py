"""Publish the scope, timing pattern and supported explanation of the audit."""
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
    y=pd.read_csv(e.OUT/'yearly_counts.csv',keep_default_na=False)
    races=pd.read_csv(e.OUT/'race_counts.csv',dtype={'date_key':str});d=pd.read_parquet(e.OUT/'runner_audit.parquet')
    eq=races[races.equal.gt(0)];same_day=races[races.date_key.isin(eq.date_key)&races.later.gt(0)]
    central=e.R/'conclusions/57A_SEOUL1800_S1F_1C.md'
    assert not central.exists() or e.HERE.name in central.read_text()
    yearly=table(['연도','전체 출전행','동일','1C후행','1C역순','미제공','동일기록 날짜 범위','동일 경주수'],[
        [r.year,r.rows,r.equal,r.later,r.earlier,r.missing,
         f'{r.first_equal}~{r.last_equal}' if r.equal else '없음',
         int(eq.date_key.str.startswith(str(r.year)).sum())]
        for r in y[y.scope.eq('all')].itertuples()])
    examples=[]
    for date,no in [('20100822',7),('20100822',8),('20120727',7),('20120727',8),('20190720',9),('20190721',9),('20230716',9)]:
        r=races[races.date_key.eq(date)&races.race_no.eq(no)].iloc[0]
        examples.append([date,no,f'{int(r.scheduled_start_raw):04d}',r.equal,r.later,r.earlier,r.missing])
    cases=table(['날짜','경주','예정시각HHMM','동일','후행','역순','미제공'],examples)
    body=f'''# 서울1800m S1F·1C 동일 기록의 시점과 경주 범위

2026-10-19. 연구57A, 연구57의 후속 원천 감사. **모든 기록이 같은 것도, 특정 시점부터 일괄적으로 같아진 것도 아니다. 2010~2023년 일부7~9월 경주에서 반복됐다. 동일값은47개 경주에 몰려 있고 모두 예정 출발시각18시01분 이후다. 원천 API와 보관 공식 성적표에도 같은 값이 있어 연구 DB의 복사 오류로 설명되지 않는다. 다만 개별 경주의 실제 출발점 변경을 모두 확인한 것은 아니다.**

## 범위와 분모

보유 코어의 서울1800m2010-01-09~2026-09-20 전체1,617경주18,376출전행을 조사했다. 비정상 착순·미완주·취소 등도 처음부터 삭제하지 않았다. 두 시간 양수인18,095행에서 동일481(2.658%)·1C후행17,613·역순1이었다. 둘 중 한 값 이상이 미제공인281행은 동일에 포함하지 않았다. 원문의0=0은 유효 계측 일치가 아니다. 코어 묶음 기준일2026-09-29와 실제 결과 종료일을 구분한다.

기존 연구57의 정상 완주 기준(착순1~30·양수 완주시간)18,014행에서는 동일480·후행17,533·역순1이다. 전체481과의 차이1행은2011-07-23서울10경주1번 성장엔진, 원문착순91·완주125.2초의 비정상 착순이다. 코드91의 사유는 이번에 추정하지 않았다. 기존480건은 그대로 재현됐다.

## 연도별 전체 기록

{yearly}

동일은 최초2010-07-17, 마지막2023-08-19다.2013~2015·2020~2021·2024~2026 보유분에는 없다. 2026은9월20일까지1,038정상 완주 전부1C후행이다. 현재 관측 공백만으로 제도 폐지나 향후 재발 불가능을 단정하지 않는다. 2010~2016은 기존2017이후 학습 정책에서 과거 이력 범위이며 학습 정책을 바꾸지 않았다.

## 개별 말의 우연보다 경주 단위의 기록 패턴

47개 경주에서 동일값481행·역순1행·미제공{int(eq.missing.sum())}행이 관측됐고1C가 정상적으로 뒤에 찍힌 말은0행이었다. 동일481행의 S1F/1C 통과순위도481행 모두 같다. 이 결과는 시간과 통과순위를 별도로 대조한 것이며 순위로 시간을 생성하지 않았다. 같은 날에도 다른1800m 경주는 두 시간 차가 약6초인 경우가 {len(same_day)}경주 있었다.

{cases}

2010-08-22는 같은 날7경주17:45의14행이 모두1C후행인데8경주18:40의12행은 모두 동일이다.2012-07-27에는7경주19:30이 후행11행/미제공1행인데8경주20:00은10행 모두 동일이다. 따라서 날짜뿐 아니라 개별 경주를 구분해야 하고 **야간이라는 이유만으로 동일 처리해서도 안 된다.**

전체 예정 야간114경주 중 동일 패턴47경주, 후행 패턴67경주였다. 야간 출전1,220행 중 동일481·후행718·역순1·미제공20이다. 예정 비야간1,503경주에는 동일이 없다. 예정시각은 DB 계획 자료의 값이며 실제 출발시각을 재확인한 값이 아니다.

원천 사례2019-07-20서울9경주2번 클린업시크릿은 S1F14.0/1C14.0/2C26.4초,2023-07-16서울9경주2번 파이어파워는14.3/14.3/26.8초다. API와 보관 dacom11 성적표 양쪽에서 일치했다.

## 출발 위치 변경 규정과 해석의 한계

마사회2019년 시행계획 PDF16쪽과2023년 시행계획 PDF14쪽은 서울 악천후·야간경주에서1800m 출발을1700m 출발점으로 바꾸고2코너에서 외주로를 타되 전체 거리는 유지할 수 있다고 설명한다. 야간 기준은 계획상18시01분 이후다. [공식2019계획](https://race.kra.co.kr/down/raceplan_2019.pdf) · [공식2023계획](https://race.kra.co.kr/down/raceplan_2023.pdf).

연구57에서 서울1700m S1F/1C 동일 저장을 확인한 사실과 이번47경주의 야간 집중은 **출발·주행 경로 변경 운용과 부합한다**. 하지만 이 규정은 변경 가능 조건이지47개 경주 각각의 변경 명령서가 아니다. 특히2012년 같은 날 두 야간 경주의 패턴이 달라 예정시각·연도·월만으로 실제 코스를 확정할 수 없다. 개별 경주 변경 공지나 출발점 근거가 확보되기 전까지 원인은 유력한 해석으로 남긴다. 모든 동일값을 계측 장비의 동일 지점이나 정확한 물리적 좌표로 확정하지 않는다.

## 예외와 구간 평가에 필요한 처리

2010-07-17서울10경주6번 아리새는 S1F15.8/1C15.7초로−0.1초 역순이다. 원문부터 같고 임의 보정하지 않았다. 같은 경주 나머지 유효8행은 동일이고1행은 미제공이다. 이 행은 S1F→1C 구간 분석에서 제외해야 한다.

서울1800m를 평가할 때 모든 기록을 하나의 고정8구간으로 강제하면 안 된다. S1F/1C가 서로 다른 일반 패턴은8개 시간 구간을 유지하고, 동일 패턴은 중복 경계를 제거한7개 구간을 쓴다. 미제공·역순은 별도 플래그로 남긴다. 출발·코스 변경 가능성이 있으므로 초중반 코너 구간의 기준치를 두 유형에 동일하게 적용하기 전에 조건을 더 확인해야 한다. 이번에 새 보정이나 유형별 성능 점수를 학습하지 않았다.

동일하지 않은 기록의1C−S1F 차 중앙값은6.0초다. 이를 정확100m/200m 거리로 변환하거나 가속도·능력 손실로 해석하지 않는다. 관측이0초인 중복 경계를 독립 능력 항목으로 더하지 않는다.

## 검증

API 원문17파일18,376행의7개 누적시간과2개 통과순위, 총165,384셀을 확인했다. 시간·정상범위 순위는 DB와 일치하고 미제공·99 같은 순위 표시는 무효값으로 구분했다. 원문 값으로 동일/후행/역순/미제공을 독립 재분류하고 별도 SQL의 전체 집계, 연도·월·경주 합계, 기존480을 재현했다.

동일 경주 날짜에서 보관된 공식 dacom11은24파일이며 해당 카드1800m의 S1F/1C 총508셀을 대조해 불일치0이었다. 초기2010~2012년18개 날짜는 보관 dacom11이 없어 API 원문 대조까지만 완료했다. 라이브 영문 성적표 재조회는 도구 접근이 되지 않아 완료한 검증으로 세지 않았다. 출처 해시는 보존했다. 작업 중 원문99와 pandas 결측형 처리만 수정한 준비 기록을 남겼으며 시간값·비교 기준은 변경하지 않았다.

DB 읽기 전용, 새 학습·운영 변경·제주 접근 없음. 웹사이트 게시용 요약은 준비했으나 배포하지 않았다.

[계획](PLAN.md) · [개별 출전 원장](outputs/runner_audit.parquet) · [원문 필드](outputs/raw_fields.parquet) · [연도별](outputs/yearly_counts.csv) · [47개 경주](outputs/equal_races.csv) · [같은 날 대조](outputs/same_day_controls.csv) · [전체 경주](outputs/race_counts.csv) · [성적표 대조](outputs/dacom11_crosscheck.csv) · [공식근거](outputs/official_sources.json) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 서울1800m의 S1F와1C가 같은 경주는 언제인가

2026-10-19. 연구57A. 연구57 후속 원천 감사이며 새 보정·모델 적용이 아니다.

무엇을 알았는가: 모든1800m 기록이 같은 것도 특정 연도부터 일괄 변경된 것도 아니다. 보유2010-01-09~2026-09-20의1,617경주18,376행 중 동일481행이47개 경주에 집중됐다. 정상 완주 기준은 기존과 같은480행이다. 동일은 여러 해7~9월에 반복됐고 마지막2023-08-19이며2024~2026 보유분에는 없다.

기록을 어떻게 읽는가: 동일47경주는 모두 예정18시01분 이후였고 같은 경주의 유효 기록에 일반 후행 패턴이 섞이지 않았다. 하지만 야간114경주 중67개는 일반 후행이므로 야간 여부만으로 코스를 확정하면 안 된다. 일반 패턴의1C−S1F 중앙값은6.0초다. 마사회2019/2023 시행계획의 야간·악천후 출발점 변경 가능 규정과 부합하지만 개별 경주 실제 변경은 모두 확인한 것이 아니다.

사례:2010-08-22서울7경주17:45는14행 모두 후행,8경주18:40은12행 모두 동일이다.2012-07-27에는19:30 후행 경주와20:00 동일 경주가 함께 있어 날짜·야간만으로 일괄 분류할 수 없다.2019-07-20클린업시크릿은 S1F14.0/1C14.0초로 API와 공식 보관 성적표가 일치한다.

적용 범위: 서로 다른 일반 기록은8개, 동일 기록은 중복 제거7개 시간 구간으로 분리해야 한다. 원천 API165,384셀·보관 성적표508셀 대조, DB와 불일치0. 순위99 등 무효값과 미제공281행,−0.1초 역순1행은 별도 보존했다. 미터 길이·개별 코스·예측 개선은 이번 결과로 확정하지 않는다.

[전체 보고서](README.md) · [동일47경주](outputs/equal_races.csv) · [연도별](outputs/yearly_counts.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/')+'\n원연구: '+e.HERE.name+'\n')
    marker='<!-- seoul1800_s1f_1c_audit_20261019 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=e.R/name;link=f'{e.HERE.name}/README.md' if name=='README.md' else central.name
        if marker not in path.read_text():
            with path.open('a') as f:f.write(f'\n\n{marker}\n[연구57A 서울1800 S1F·1C 동일 기록 감사]({link}): 전체18,376행·정상18,014행. 동일481/정상480은47개 경주, 모두 예정 야간·여러 해7~9월 반복. 야간67경주는 후행이라 일괄 분류 불가. 원문165,384셀·보관 성적표508셀 대조. 출발점 변경 규정과 부합하나 개별 코스 미확정. 새 모델·운영 변경 없음.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',new_models=0,
        database_access='read_only',production_changed=False,jeju_access=False,deployed=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for path in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(path.relative_to(e.ROOT));source['sources']=[r for r in source['sources'] if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(path),bytes=path.stat().st_size))
    e.save(manifest,source)
    for path in [e.HERE/'README.md',e.HERE/'PUBLICATION.md',central]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if not link.startswith(('https:','http:','#')) and not link.endswith('artifact_inventory.json'):
                assert (path.parent/link).exists(),(path,link)
    e.check();print('Research57A preserved and published locally')


if __name__=='__main__':main()
