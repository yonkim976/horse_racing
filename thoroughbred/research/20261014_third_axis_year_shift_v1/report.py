"""Publish frozen third-anchor diagnostic findings without changing policies."""
import html
import json
import re

import pandas as pd

import run as e


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |'for row in rows])


def main():
    e.check()
    verification=json.loads((e.OUT/'verification.json').read_text());assert verification['status']=='verified'
    central=e.R/'conclusions/54_THIRD_AXIS_YEAR_SHIFT.md'
    assert not central.exists()or e.HERE.name in central.read_text(),'conclusion54 occupied'
    d=pd.read_parquet(e.OUT/'cases.parquet')
    f=pd.read_csv(e.OUT/'feature_comparisons.csv')
    counts=pd.read_csv(e.OUT/'period_decomposition.csv')
    conditions=pd.read_csv(e.OUT/'conditions.csv',dtype={'value':str})
    composition=pd.read_csv(e.OUT/'composition_decomposition.csv')
    sensitivity=pd.read_csv(e.OUT/'model_update_sensitivity.csv')
    summary=table(['기간','제3축수','회복','상실','제3축 순증감','그밖의 순증감','전체 순증감'],[
        [period,int(g[g.scope.eq('third')].iloc[0].n),int(g[g.scope.eq('third')].iloc[0].gains),
         int(g[g.scope.eq('third')].iloc[0].losses),int(g[g.scope.eq('third')].iloc[0].net),
         int(g[g.scope.eq('other')].iloc[0].net),int(g[g.scope.eq('all_races')].iloc[0].net)]
        for period,g in counts.groupby('period',sort=False)])
    rows=[]
    for feature,label in [('keep_fast_g3','과거 빠른초반 뒤 G3F 우위(초)'),('keep_fast_g1','동일사건 G1F 우위(초)'),
                          ('keep_fast_n','공동관측 수'),('front_gate_probability','예상 첫조 확률'),
                          ('history_count','실전 경력'),('profile_count3','최근3전 기록 유효수')]:
        vals=[]
        for period,group in [('2025_to0920','gain'),('2025_to0920','loss'),('2026_to0920','gain'),('2026_to0920','loss')]:
            x=f[f.period.eq(period)&f.group.eq(group)&f.feature.eq(feature)].iloc[0]
            vals.append(f'{x.third_mean:.3f} (관측{int(x.third_n)}/{int(x.races)})')
        rows.append([label]+vals)
    for statistic,label in [('difference_mean','기존축 대비 최근3전 보정기록 우위·평균'),
                            ('difference_median','같은 기록 우위·중앙값')]:
        vals=[]
        for period,group in [('2025_to0920','gain'),('2025_to0920','loss'),('2026_to0920','gain'),('2026_to0920','loss')]:
            x=f[f.period.eq(period)&f.group.eq(group)&f.feature.eq('moist_last3_record_index_mean')].iloc[0]
            vals.append(f'{x[statistic]:+.3f} (짝관측{int(x.paired_n)}/{int(x.races)})')
        rows.append([label]+vals)
    feature_table=table(['특성','2025회복58','2025상실56','2026회복39','2026상실48'],rows)
    condition_rows=[]
    specs=[('meet','1','서울'),('meet','3','부산'),('grade_band','grade6','6등급'),
           ('grade_band','grade5','5등급'),('grade_band','grade1_4','1~4등급'),
           ('distance_band','short','1300m이하'),('distance_band','middle','1400~1600m'),
           ('distance_band','long','1700m이상'),('history_band','le2','경력2전이하'),
           ('g1_missing','True','G1F관측없음')]
    for col,value,label in specs:
        vals=[]
        for period in ['2025_to0920','2026_to0920']:
            x=conditions[conditions.period.eq(period)&conditions.condition.eq(col)&conditions.value.eq(value)].iloc[0]
            vals += [int(x.n),f'{int(x.gains)}/{int(x.losses)}',f'{int(x.net):+d}']
        condition_rows.append([label]+vals)
    condition_table=table(['조건','2025제3축수','회복/상실','순증감','2026제3축수','회복/상실','순증감'],condition_rows)
    model_table=table(['2026동일1,288경주','축입상','축Top2','복승1개','축복승3개'],[
        [r.variant]+[f'{getattr(r,k)*100:.2f}%'for k in ['axis_top3','axis_top2','quinella_one','axis_next3']]
        for r in sensitivity.itertuples()])
    case_rows=[]
    for group in ['gain','loss']:
        for row in d[d.year.eq(2026)&d.group.eq(group)].head(3).itertuples():
            case_rows.append(['회복'if group=='gain'else'상실',f'{row.race_date:%m-%d} {"서울"if row.meet==1 else"부산"}{row.race_no}경주',
                f'{row.prior_program_no} {row.prior_horse_name} ({row.prior_outcome}위)',
                f'{row.axis_program_no} {row.third_horse_name} ({row.axis_outcome}위)'])
    examples=table(['분류','경주','직전 선택축','제3축'],case_rows)
    composition_table=table(['구성층','공통표본2025/26','제외2025/26','구성비 기여%p','셀내 변화%p','합계%p'],[
        [x.strata,f'{x.included25}/{x.included26}',f'{x.excluded25}/{x.excluded26}',
         f'{x.composition*100:+.3f}',f'{x.within*100:+.3f}',f'{x.change*100:+.3f}']for x in composition.itertuples()])
    body=f'''# 제3축 회복·상실 조건과2025/2026 반전 진단

2026-10-14. 연구54. 연구53/51의선택·가중치를동결한후향진단이다. **2025년제3축순증가+15중+13은9월20일이후였다. 같은날짜까지는2025+2대2026−9로격차가작아진다. 2026상실은저경력·G1F결측·작은최근보정기록우위가더많았지만,과거종반우위가좋아도실패했다. 지역·거리·등급구성변화또는선택모형갱신하나만으로반전을설명하지못한다.** 새학습·예외규칙·운영반영없음.

## 비교 정의와 분모

회복은 직전연구51의두축선택은3위밖/연구53제3축은Top3,상실은그반대다. 제3축은원래103/122의축모두와다른말이다. 기존122축대비회복과혼용하지않는다. 2025전체제3축286개(회복87/상실72/중립127),2026제3축176개(39/48/89)를보존했다. 2025는9월20일까지197개(58/56/83)를같은기간주비교로삼는다. 중립은둘다입상/둘다실패이며분석에서삭제하지않았다. 이군집은사후착순으로정의된진단집단이지사전성공/실패분류모델의성능이아니다.

## 1. 달력과 제3축외 선택의 영향

{summary}

원래전체변화2025+22/2026−22를제3축의+15/−9만으로설명하면안된다. 2026에는제3축을고르지않은경주에서도12회복/25상실=−13이있었다. 이는같은입력모형·학습방식변화로두원축중누구를고를지도달라졌기때문이다. 같은새학습모형two대비제3후보확대의순효과는2025전체+14/같은9월20일까지+2/2026−10이었다. 날짜를맞춰도반전방향은있지만2025전체기간의큰우위가그대로남는것은아니다.

2025제3축9월20일후89개는29회복/16상실=+13이었다. 2026에는비교되는연말자료가아직없다. 남은2026기간도2025와같아질것이라고가정하지않았다.

## 2. 회복군과 상실군의 기록

{feature_table}

최근보정기록지수는높을수록좋고초·공식rating·확률이아니다. 기존축대비차이는해당경주직전선택51축과제3축이모두관측된짝에서만계산했다. 각말의관측평균을별도로빼면결측집단이달라표의짝차이와다를수있다. G3F/G1F는같은과거빠른초반사건의편성대비상대초에표본축소를적용한값이며양수일수록빠르다. 겹치는구간을합산하지않는다.

2026회복39개중최근기록짝관측36개는평균우위+0.412/중앙값+0.419였다. 상실48개중짝관측42개는+0.149/+0.106으로작았다. 최근기록이기존축보다좋았던말도회복군29/36대상실군26/42였다. 하지만2025같은기간에는회복+0.249/상실+0.357,중앙값+0.337/+0.306으로2026과같은분리가없었다. **최근우위가작으면제외한다는새문턱을지지하는독립검증이아니다.**

종반기록은오히려과거우위가좋은상실도많다. 2026의기존축대비G3F짝차이는회복−0.082초(34짝)/상실+0.096초(38짝),G1F는−0.041/+0.033초였다. 2025도G3F회복+0.031/상실+0.158,G1F−0.022/+0.036으로과거상대종반우위가더큰상실군이있었다. 따라서G3F/G1F좋은말을고르면해결된다고보거나2026반전을종반기록악화로만설명하면안된다. 실제이번선행·종반·컨디션은이표에서관측하지않았다.

2026상실군의예상첫조확률은34.3%,회복군30.1%였다. 반면2025상실29.6%,회복31.6%였다. 이는예상전개분포의기술차이일뿐선행경합·외곽손실의실제발생증거가아니다. 내측최고초반대비격차도회복−0.203초(30관측)/상실−0.179초(40관측)로큰단일분리가아니었다. 연령·부담중량·거리변경·게이트·지원수·추세및결측의전체표는[특성비교](outputs/feature_comparisons.csv)에남겼다.

## 3. 저경력과 결측, 거리·등급의 변화

2026상실군은경력2전이하13/48(27.1%),G1F관측없음10/48(20.8%)였다. 회복군은각6/39(15.4%),5/39(12.8%)였다. 최근3전유효기록도상실2.40개대회복2.67개,추세결측17/48대7/39였다. 모든상실이관측부족은아니다. G1F관측이있는상실38개,경력3전이상상실35개가남는다.

같은기간전체제3축의저경력비중은2025 24/197(12.2%)→2026 34/176(19.3%),G1F결측비중은16/197(8.1%)→23/176(13.1%)였다. 선택군안에불확실한기록의말이더많아졌다는관찰이다. 저경력·결측·6등급·단거리집단은겹치므로아래순증감을더하면안된다. 결측을통과불가조건으로쓰거나현집단으로새규칙을학습하지않았다.

{condition_table}

특히1300m이하가+8→−6,6등급+3→−7,서울+8→−5로방향이바뀌었다. 5등급은−1→+2,장거리는−5→−2라모든조건에서나빠진것은아니다. 6등급의제3축비중은26.4%→25.6%로비슷하고단거리비중44.2%→46.6%차이도작다. 단순히6등급/단거리가많아진것만으로설명하기어렵다. 작은부분집단의사후분해이며확정적인해당조건회피정책이아니다.

## 4. 구성비가 바뀐 것인가, 같은 조건 안에서 달라진 것인가

두해9월20일까지제3축선택군의순득실률(회복−상실)/선택수는+1.015%→−5.114%,차이−6.129%p였다. 이는전체경주의축입상률차이가아니다. 공통조건셀의빈도와셀내순득실률을Kitagawa대칭항등식으로분해했다.

{composition_table}

한조건씩보면지역·거리·등급의구성비기여는작고셀내변화가크다. 세조건동시공통20셀에서는2025 4개가제외돼시작순득실률도0%로달라진다. 구성비−1.265%p/셀내−3.848%p이며희소셀도포함한다. 전체−6.129%p와다른분모의−5.114%p를혼용하지않는다. 이것은조건통제인과추정이아니며같은셀안의말·컨디션·기초능력모형·표본변동차이가여전히남는다. [공통셀과희소표시](outputs/composition_cells.csv).

## 5. 선택 모델은 왜 제3의 말을 골랐나

원래선택기준은모든후보의P득−P실최댓값이다. 선택된제3축의log(P득/P실)를각연도이전학습경주동일가중특성평균기준으로정확분해했다. 기준점은2025−1.570309/2026−1.543833이다. 기준점+127개기여합은462경주모두저장확률과일치한다. **이로그비는122기준축보다교체방향이양수인지설명하지만후보간순위를직접설명하는기준은아니다.** 중립확률때문에기대득실순위와로그비순위가달라질수있다.

2026회복/상실군평균에서기초모델평가묶음은+1.059/+1.031,최근상태는+0.439/+0.453으로둘다제3축방향이었다. 최근보정기록하나의우위가작더라도다른최근특성·결측표시·기초확률/순위가같이작용한다. G3F×최근상대기록은+0.102/+0.145로상실군에서도제3축방향이강했다. 기여는표준화된상관입력의log-odds이며능력초·확률%p·인과효과가아니다. 각해기준점도다르므로기여평균차이를그대로연도별경기력변화로읽지않는다.

선택제3축의평균기대득실은2026회복+0.0539/상실+0.0529,동일모형two축대비차이+0.0527/+0.0529로거의같았다. 실제결과로구분한두집단에비슷한이득을예상했다는뜻이다. 이수치는제3축의입상확률5%가아니다. 많은후보중최댓값을고르는과정의과대평가·추정불확실성과기초점수편향을완전히해결하지못한가능성이남지만,이번진단이그원인을단독입증하지는않는다. [선택점수와경쟁후보](outputs/decision_scores.csv),[묶음기여](outputs/bundle_comparisons.csv).

## 6. 2026 선택 모델 갱신 때문인가

2020~2024만학습한기존2025선택모형/전처리를2026의동일기초103/122입력에그대로적용했다. 2026선택모형은2020~2025학습이다. 둘다2026정답으로새로맞추지않았고미래모형을과거로적용하지않았다.

{model_table}

2025모형을유지해도2026축입상784/1288=60.87%,현재2026모형783/1288=60.79%로차이는1경주였다. 직전두축선택805/1288=62.50%보다여전히21경주낮았다. 제3축은163개로줄고37회복/44상실=−7,나머지−14로전체−21이다. 현재는제3축−9/나머지−13=−22다. 따라서선택계수갱신만으로2026하락이생겼다고보기어렵다. 입력분포·기초능력모형·실제결과환경이함께달라졌고그차이를인과적으로분리한것은아니다. 이민감도결과로2025모형을채택하지않는다.

## 7. 2026 사례와 전체 목록

각군의날짜순처음3개를표시했다. 대표성을주장하거나좋은설명만고른것이아니다.

{examples}

[2026회복39전체](outputs/2026_gain_cases.csv) · [2026상실48전체](outputs/2026_loss_cases.csv) · [2025회복87전체](outputs/2025_gain_cases.csv) · [2025상실72전체](outputs/2025_loss_cases.csv).

## 결론과 검증

반전에는첫째비교기간차이,둘째저경력/결측선택의증가와동일단거리·6등급집단내득실악화,셋째기존축대비최근보정기록우위가작은상실도제3축으로올리는문제가관련돼있다. 하지만변수하나가원인이라는근거는없고과거G3F/G1F우위만으로상실을구분하지못했다. 선택모형연도갱신하나나큰지역·거리·등급구성변화로도설명되지않는다. 전체악화−22중제3축−9외에두원축간선택−13도함께연구해야한다.

462사례군분류/짝특성/이름/기간분할/조건집계/구성분해항등식,58,674특성기여와확률합(재현오차0),기대득실최대선택,2025모형의시점과2026 1,288경주축·복승독립계산,현재정답변조불변,22보호입력hash를검증했다. 새학습0,운영·선택22·미래계약·DB·제주변경없음.

같은과거기간반복검증·결과조건화·희소집단·부분2026·PIT미감사·미관측컨디션/전술·상관입력한계를유지한다. 이진단은가설발견이며새문턱/규칙/확률보정의성능검증이아니다.

재현: `run.py` → `verify.py` → `report.py` → `finalize_inventory.py`.

[계획](PLAN.md) · [기간분해](outputs/period_decomposition.csv) · [특성비교](outputs/feature_comparisons.csv) · [조건별득실](outputs/conditions.csv) · [구성분해](outputs/composition_decomposition.csv) · [모형갱신민감도](outputs/model_update_sensitivity.csv) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 제3축의2025 개선과2026 악화는 왜 달랐을까

2026-10-14. 연구54. 고정모형사후진단,새규칙·운영반영아님.

무엇을알았는가: 2025제3축전체87회복/72상실=+15중+13은9월20일이후였다. 같은날짜까지2025 58/56=+2,2026 39/48=−9다.2026전체악화−22중나머지두원축선택의−13도있어제3축만의문제가아니다.

기록을어떻게읽는가: 2026회복군의기존축대비최근보정기록우위는평균+0.412/중앙값+0.419,상실군+0.149/+0.106이었다. 상실군저경력13/48·G1F결측10/48로회복6/39·5/39보다많았다. 하지만과거G3F/G1F우위가더좋은상실도많아종반하나로고를수없다.2025에는같은최근우위분리가없었다.

사례: 01-03서울7경주2블랙시대8위대7탭딘2위는회복,01-09부산8경주2미스터프라임1위대5플라이투더문7위는상실이었다. 전체2026회복39/상실48과2025사례를보존했다.

어디까지적용되는가: 단거리제3축순증감+8→−6,6등급+3→−7이지만분포변화만으로설명되지않고사후소표본이다.2025선택모형을그대로2026에적용해도784/1288로현재783보다1경주만높아모형갱신만의문제도아니다.462사례·58,674기여·1,288민감도경주검증,새학습0. 조건필터·운영교체는하지않는다.

[전체보고서](README.md) · [2026회복39](outputs/2026_gain_cases.csv) · [2026상실48](outputs/2026_loss_cases.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/')+'\n원연구: '+e.HERE.name+'\n')
    (e.HERE/'report.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>제3축 연도변화 진단54</title><style>body{margin:32px auto;max-width:1200px;padding:0 20px;font:16px/1.8 system-ui;color:#172033;background:#f4f7fb}pre{white-space:pre-wrap;background:white;padding:24px;border-radius:12px}</style><h1>제3축 회복·상실과 연도변화</h1><pre>'+html.escape(body)+'</pre></html>')
    marker='<!-- third_axis_year_shift_v1_20261014 -->'
    summary=('2025제3축+15중+13은9월20일후,동일기간+2대2026−9. '
             '2026상실저경력/결측/작은최근우위,종반단독분리불가. '
             '구성비/선택모형갱신단독설명불가,2025모형2026적용+1경주. '
             '462사례/58,674기여/1,288민감도검증,새학습·운영변경없음.')
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=e.R/name;link=f'{e.HERE.name}/README.md'if name=='README.md'else central.name
        if marker not in path.read_text():
            with path.open('a')as handle:handle.write(f'\n\n{marker}\n[제3축 회복·상실 조건과2025/2026 반전]({link}): {summary}\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',cases=462,
        year2026_gain=39,year2026_loss=48,new_models=0,diagnostic_only=True,
        production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts and'publication_before'not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for path in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(path.relative_to(e.ROOT));source['sources']=[r for r in source['sources']if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(path),bytes=path.stat().st_size))
    e.save(manifest,source)
    for path in [e.HERE/'README.md',e.HERE/'PUBLICATION.md',central]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if not link.startswith(('https:','http:','#'))and not link.endswith('artifact_inventory.json'):
                assert (path.parent/link).exists(),(path,link)
    e.check();print('Research54 published locally; no model or policy change')


if __name__=='__main__':
    main()
