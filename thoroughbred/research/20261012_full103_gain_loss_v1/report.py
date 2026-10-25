"""Publish diagnostic evidence locally, without changing models or the website."""
import json
import pandas as pd
import run as e


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |' for r in rows])


def main():
    e.check();v=json.loads((e.OUT/'verification.json').read_text());assert v['status']=='verified'
    s=pd.read_csv(e.OUT/'summary.csv').set_index('period')
    rows=[]
    for period,label in [('2025','2025 전체'),('2025_to0920','2025 01-01~09-20'),('2026','2026 01-01~09-20')]:
        x=s.loc[period]
        rows.append([label,int(x.races),f'{x.old_rate*100:.2f}% → {x.new_rate*100:.2f}%',int(x.switches),
                     int(x.gain),int(x.loss),f'{int(x.net):+d}',f'{x.delta*100:+.2f}%p'])
    annual=table(['기간','경주','기존→새 축 입상률','축 변경','새 적중','적중 상실','순증감','입상률 차이'],rows)
    c=pd.read_csv(e.OUT/'conditions.csv',keep_default_na=False)
    specs=[('부산','meet','3'),('서울','meet','1'),('≤1300m','distance_band','short'),
           ('1400~1600m','distance_band','middle'),('≥1700m','distance_band','long'),
           ('5등급','grade','5.0'),('6등급','grade','6.0'),('새 축 내측','new_gate_band','inner'),
           ('새 축 중간','new_gate_band','middle'),('새 축 외측','new_gate_band','outer'),
           ('신마 포함 편성','newhorse_field','True'),('새 축 첫조 종반이력 0회','new_front_support','0'),
           ('새 축 첫조 종반이력 1회','new_front_support','1'),('새 축 첫조 종반이력 ≥2회','new_front_support','2+')]
    rows=[]
    for label,col,value in specs:
        vals=[]
        for period in ['2025_to0920','2026']:
            q=c[c.period.eq(period)&c.condition.eq(col)&c.value.eq(value)].iloc[0]
            vals.append(f'{q.gain}/{q.loss} ({int(q.net):+d}, 변경 {q.switches}경주)')
        rows.append([label]+vals)
    cond=table(['조건','2025 동기간 새 적중/상실 (순증감)','2026 동기간 새 적중/상실 (순증감)'],rows)
    f=pd.read_csv(e.OUT/'features_by_switch.csv');rows=[]
    for feature,label,unit in [('front_gate_probability','새 축 예상 첫조 확률','%'),
                               ('gate_fraction','새 축 게이트 상대위치',''),
                               ('record_field_rank','새 축 최근3전 보정기록의 편성 내 순위',''),
                               ('keep_fast_g3','새 축 과거 빠른초반 뒤 G3F 상대우위','초'),
                               ('keep_fast_g1','새 축 과거 빠른초반 뒤 G1F 상대우위','초')]:
        vals=[]
        for year,kind in [('2025','gain'),('2025','loss'),('2026','gain'),('2026','loss')]:
            q=f[f.period.eq(year)&f.kind.eq(kind)&f.feature.eq(feature)].iloc[0]
            n=q.new_mean*(100 if unit=='%'else 1)
            vals.append(f'{n:.3f}{unit} (관측{int(q.new_count)}/{int(q.n)})')
        rows.append([label]+vals)
    pre=table(['경주 전 정보: 평균','2025 새 적중','2025 적중 상실','2026 새 적중','2026 적중 상실'],rows)
    d=pd.read_parquet(e.OUT/'races.parquet');ex=[]
    criteria=[('2025 5등급 적중 상실',d.year.eq(2025)&d.kind.eq('loss')&d.grade.eq(5)),
              ('2026 부산6등급 새 적중',d.year.eq(2026)&d.kind.eq('gain')&d.meet.eq(3)&d.grade.eq(6)),
              ('2026 외측 승격 적중 상실',d.year.eq(2026)&d.kind.eq('loss')&d.new_gate_band.eq('outer'))]
    for label,mask in criteria:
        q=d[mask].sort_values(['race_date','race_key']).iloc[0]
        ex.append([label,q.race_key,f'{q.old_program_no} {q.old_horse_name} ({q.old_outcome}위)',
                   f'{q.new_program_no} {q.new_horse_name} ({q.new_outcome}위)',q.new_rank_old])
    example=table(['분류','경주키','기존 축 실제착순','새 축 실제착순','새 축의 기존 순위'],ex)
    e.save(e.OUT/'example_selection.json',dict(posthoc_categories=True,
           rule='Within each reported diagnostic category choose the first race sorted by date then race_key',
           examples=[dict(category=row[0],race_key=row[1]) for row in ex],representative_sample=False))
    body=f'''# 103→122 모델의 축 입상: 2025 손실과 2026 이익의 조건

2026-10-12. 연구47의 baseline103 대 combined122를 고정한 **후향적 진단**. 연구후보이며 운영 모델 반영은 아니다. 서울·부산 2024~2026-09-20의 같은4,799경주/50,754출전을 비교했다. 이번에는 학습·추가보정·모델 선택을 하지 않았다.

## 확인한 결론

2026 개선은 부산·6등급·단중거리의 축 변경에서 주로 발생했다. 2025 손실은 중장거리·5등급과 일부 단일 과거관측을 가진 말의 승격에서 컸다. 하지만 조건들은 겹치며, ‘종반 유지력이 좋은 선행마를 더 잘 골라서 좋아졌다’는 단일 설명은 자료와 맞지 않는다. 두 해 모두 잘못 승격한 말도 과거 G3F·G1F가 좋았다. 2026의 추가이익은 과거 첫조 종반이력이 없는 말에게서도 상당 부분 발생했다.

## 1. 먼저 기간과 변경 수를 맞춰 보기

{annual}

축이 실제로 바뀐 경주는 전체671/4,799(13.98%)다. 바뀐 경우만 새 적중186/상실169/둘 다 적중171/둘 다 실패145경주였다. 2025 변경252경주의 새 축 입상128/252(50.79%) 대 기존141/252(55.95%), 2026 변경167경주는93/167(55.69%) 대73/167(43.71%)다. 전체 경주 입상률과 이 조건부 비율은 다른 분모다.

2026은 변경을 더 많이 해서 좋아진 것이 아니다(2025 14.40%,2026 12.97%). 2025의9월21일 이후에는20개를 새로 맞추고20개를 잃어 순차이가0이었다. 2025도9월20일까지 맞추면58.53% 대 기존59.56%, 2026은62.66% 대61.10%로 반대 방향이 남는다.

동기간 순개선의 연도차이는+2.584%p, 독립 연도 경주일 군집 부트스트랩95%구간은[+0.570,+4.739]%p다. 전체연도2025 대 부분연도2026 차이는+2.296%p,[+0.340,+4.162]%p. 모두2,000회이며 반복후향·다중비교는 보정하지 않았다. 2026 자체개선+1.553%p의 구간은[+0.153,+2.968],2025−0.743%p는[−2.053,+0.640]이다. 연도별 재학습 자료도 달라져 경주 조건만의 인과효과는 분리하지 못한다.

## 2. 어디서 새로 맞추고, 어디서 잃었나

아래는 모두01-01~09-20. 새 적중은 기존 축만 입상 실패/새 축 입상, 적중 상실은 그 반대다. 각 행의 순증감은 단순 경주 수이고 서로 다른 조건의 행을 더하면 중복된다. 전체 분모와 둘 다 적중/실패도 원표에 보관했다.

{cond}

2026 순이익20 중 부산이18,서울이2였다. 부산1400~1600m만18새 적중/4상실=+14였다. 6등급 전체는+16(서울+7/부산+9)인 반면5등급은−3,≥1700m는−4로 여전히 손실이다. 부산과6등급의 이익을 더하면 안 된다. 부산6등급은19회 변경에서11새 적중/2상실/둘 다 적중5/둘 다 실패1, 2025 동기간은14회 변경에서4/3/3/4였다.

2025 동기간의5등급 손실−10은 서울−7/부산−3, 중거리−7·장거리−7이었다. 신마가 들어간 편성만의 문제는 아니다(동기간 신마없는 편성−13,신마포함0). 첫조 종반관측1회인 새 축은5새 적중/16상실이지만,2026에는14/11이었다. 이것도 작은 하위집단의 후향적 관찰이다.

지역×거리대 구성의 변화가 설명하는 동기간 연도차이는+0.039%p, 같은 층 안의 성과 변화는+2.544%p였다. 지역×등급으로 나눠도 구성−0.003%p/층내+2.586%p. 이 거친 층에서는 단순 편성 비율 변화가 주원인으로 나타나지 않았다. 모든 층에 두 연도 표본이 있었으며, 층내 말의 경력·능력 변화와 재학습 변화까지 통제했다는 뜻은 아니다.

## 3. 승격한 말들의 과거 기록은 어떻게 달랐나

{pre}

게이트 상대위치0은가장내측/1은가장외측이며 기수의 실제 주행로가 아니다. 최근기록의 편성 내 순위는 낮을수록 좋고, 보정기록 지수 자체는 높을수록 좋다. G3F/G1F는 동일 과거 출전에서 초반 상대우위>0이고 구간 관측을 충족한 사건의, 상대마보다 빠른 시간(양수)이며 표본축소가 적용된 이력값이다. 현재 경주의 실측이 아니며 두 구간은 겹치므로 합산하지 않는다.

2025 적중 상실에서는 새 축의 첫조 확률이 기존보다 평균+10.54%p, 내측 최고초반 대비 차이가+0.178초 개선됐고, 빠른초반 뒤 종반도G3F+0.106초/G1F+0.070초 좋았다. 그런데 최근3전 보정기록은−0.055지수, 추세는−0.126지수였다(각 비교는 양쪽 모두 관측된75/47경주,구간차이는65/70경주). 과거 초반·종반 장점과 최근 기량이 엇갈린 사례가 손실군에 있었다.

반대로2026 새 적중에서는 새 축의 첫조 확률이 기존보다−5.66%p였고, 최근3전 보정기록도−0.124지수였다(양쪽 관측53경주). 그럼에도 빠른초반 뒤G3F/G1F는+0.181/+0.123초(양쪽 관측44경주)였다. 2026에는 최근기록이 기존 축보다 낮은 말로 바꾼 경우31새 적중/17상실=+14,2025 전체는27/36=−9였다. 따라서 ‘최근기록이 낮으면 승격 금지’도 바로 정답으로 정할 수 없다.

2026 새 적중 말의 예상 첫조확률36.63%는 적중 상실군42.99%보다 낮고, 게이트 상대위치도0.427 대0.580으로 더 안쪽이었다. 과거 첫조 종반이력0회인 새 축이21새 적중/7상실=+14였으므로, 개선 전부를 검증된 선행 유지형 포착으로 해석하면 안 된다. 첫조 이력0은 빠른초반 사건도0이라는 뜻이 아니다. 관측0·결측을 유지력0점이나 추입형으로 치환하지 않았다.

## 4. 모델은 무엇 때문에 선택을 바꿨나

12개 동결 모델을 재추론했으며 저장 점수와 최대오차0이다. 각 모델 안에서 ‘새 축−기존 축’의SHAP 기여를 계산해 모든 변경671경주의 점수차와 합이 맞는지 검증했다. 새 입력 중에서는 **빠른초반 뒤G3F(keep_fast_g3)**가 축 승격에 가장 크게 기여했다. G1F·내측차이·확률×구간 관계는 이 선택 차이에서 상대적으로 작았다.

하지만 이G3F 입력은 새 적중뿐 아니라 적중 상실에서도 크게 작용했다. combined122의 승격 대비 평균SHAP은2025 새 적중+0.110/상실+0.115,2026+0.156/+0.190이었다. 이는 해당 연도 모델 내부의 원점수 척도이며 연도 간 직접적인 능력 단위 비교가 아니다. 결과가 나쁜 승격에서도 큰 긍정기여였으므로 ‘값이 높으면 승격’만으로 득실을 나눌 수 없다.

2025 상실군에서는 기존 게이트 묶음도 승격에 긍정기여(+0.062),최근기록 묶음은 음의기여(−0.016)였다. 2026 새 적중군에서는 기존 게이트·첫조확률의 합산기여가 음수였고,새G3F와경력·출전간격 등 조건의 기여가 선택을 뒤집었다. 새 변수만 단순 가산한 모델이 아니라 전체를 재학습했으므로 공통 입력의 작용도 바뀐다. SHAP은 모델 선택의 설명이며 실제 입상 원인의 증명이 아니다.

현재 경주의 첫조가 관측된 모든 축 변경에서 새 축의 예상/실제 첫조 진입률은2025 43.60%/42.57%(249경주),2026 40.51%/43.48%(161경주)였다. 2025 전체에서 초반 예측이 크게 과대였다고 단정할 근거도 없다. 실제 G3F/G1F는별도사후진단표에만 남겼고 입상군이 실제종반도좋다는 결과를 원인처럼 사용하지 않았다.

## 5. 사례와 다음 연구의 범위

아래는 결과를 확인한 뒤 정한 각 분류에서 날짜/경주키가 가장 빠른 사례다. 대표성을 보장하는 표본이나 모델 독립효과의 증거가 아니다. 전체671개 변경표와 사례선정 규칙을 함께 제공한다.

{example}

2025-01-05 서울6경주1700m5등급에서는1프로시드→10블랙시대로 바꿨지만실제1위→10위였다. 새 말의 과거 빠른초반 뒤G3F는0.521초로기존0.508초보다조금좋고G1F는0.262초로기존0.378초보다낮았다. 반면2026-01-23 부산3경주1400m6등급에서는9스마트유림→11탐라브라보로바꿔7위→3위를포착했다. 예시는단독원인을설명하지않는다.

다음 검증에서는 현재후보를그대로 채택하기보다, 빠른초반 뒤G3F와G1F가 모두 뒷받침되는지/관측수가얼마인지/최근기량과엇갈리는지에 따른 승격을 사전정의해 연도별로검증하는 방향이타당하다. 외측·중장거리·5등급에서는보호할기존축과새축의차이를별도로보되,2026부산6등급에만맞춘문턱을만들지않는다. 2025손실과2026이익은완전히동일한조건이아니며,현재고정자료에서여러가설을반복확인한만큼독립미래검증이필요하다. 이번에는그가설을모델에추가하거나보정강도를조정하지않았다.

## 검증·한계·재현

독립순위재구성/변경유형/조건685셀/구성분해 항등식/모델12개원점수/SHAP합/원자료와보호파일36해시를검증했다. 동점은마번오름차순으로결정하며기존모형동점변경3건도보존했다. 원자료·기존모형·운영·선택22·미래계약·DB·제주변경없음. 2017이후학습과이전워밍업,2일전컷오프,기존주로보정 및부담중량시점검증한계는연구47을상속한다. 미관측실제주행경로/전술/당일컨디션,2018이전구간결측,동일거리관측부족,부분연도,재학습의혼입,후향집단화/다중비교/고정검증자료반복사용한계를유지한다.

재현: `run.py` → `followup.py` → `verify.py` → `report.py` → `finalize_inventory.py`. `ADDITIONAL_DIAGNOSTICS.md`는결과확인뒤추가한교차표를명시한다. 입력해시가다르면중단하며재학습하지않는다.

[기간별 요약](outputs/summary.csv) · [조건별 전체표](outputs/conditions.csv) · [교차조건](outputs/cross_conditions.csv) · [변경671경주](outputs/switched_races.csv) · [선택마 과거특성](outputs/features_by_switch.csv) · [연도차 분해](outputs/year_decomposition.csv) · [SHAP 묶음](outputs/attribution_summary.csv) · [개별입력SHAP](outputs/feature_attribution_summary.csv) · [실제첫조 사후진단](outputs/observed_front_diagnostics.csv) · [검증](outputs/verification.json) · [용량명세](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 새 입력이 축 입상을 높인 해와 낮춘 해

2026-10-12. 103→122입력 연구후보의 후향 진단이며 운영 반영은 아니다.

무엇을 알았는가: 2025는62경주를새로맞추고75개를잃어축입상59.60→58.86%,2026-09-20은55개를맞추고35개를잃어61.10→62.66%였다. 같은9월20일까지로맞춰도2025는42/55로손실이남았다. 2026이익20개는부산18/서울2,6등급16에집중됐지만서로겹치는조건이라더하면안된다. 5등급과장거리·외측말승격은2026에도순손실이었다.

기록을 어떻게 읽는가: 새 입력 중과거빠른초반뒤G3F가축변경에가장크게작용했다. 그러나득실군모두좋은G3F·G1F를갖고있어좋은종반값만으로적중여부를가르지못했다. 2025상실군에는초반/종반장점과최근기량저하가엇갈린사례가있었고,2026새적중군은첫조확률이오히려낮았다. 첫조종반이력0회의승격에서도2026순이익14개가나와‘검증된선행유지형만잘찾았다’고볼수없다.

사례: 2025-01-05서울6경주1700m5등급은1프로시드(1위)→10블랙시대(10위)로바꿔잃었고,2026-01-23부산3경주1400m6등급은9스마트유림(7위)→11탐라브라보(3위)로바꿔새로맞췄다. 사례는선정조건별첫경주이며인과증거가아니다.

어디까지 적용되는가: 지역×거리대구성변화는동기간연도차2.584%p중0.039%p,층내변화는2.544%p였다. 단순비율차보다같은조건안의선택성능이달랐으나연도별재학습의영향을분리하지못한다. 12개모델점수재현최대오차0,671개변경과685조건셀검증. 후향집단화·다중비교·부분연도한계로새문턱이나보정을채택하지않았다. 운영·선택22·미래계약유지.

[전체 보고서](README.md) · [조건별 표](outputs/conditions.csv) · [변경 경주](outputs/switched_races.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central=e.R/'conclusions/48_FULL103_GAIN_LOSS.md'
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/'))
    marker='<!-- full103_gain_loss_v1_20261012 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        p=e.R/name;link=f'{e.HERE.name}/README.md'if name=='README.md'else central.name
        if marker not in p.read_text():
            with p.open('a') as handle:
                handle.write(f'\n\n{marker}\n[103→122 축 변경의 연도별 득실 진단]({link}): 4,799경주/변경671개. 2025 새 적중62·상실75,2026 55·35. 동기간 차이 유지,2026 부산·6등급 집중. 12개 고정모델 재현오차0; 새 학습·운영 반영 없음.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',races=4799,
        switched_races=671,models_replayed=12,new_models=0,retrospective_diagnostic=True,
        production_changed=False,selected22_changed=False,future_contract_changed=False,
        previous_study_changed=False,database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts and'publication_before'not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(p.relative_to(e.ROOT));source['sources']=[r for r in source['sources']if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(p),bytes=p.stat().st_size))
    e.save(manifest,source);e.check();print('Conclusion48 published locally; operating model unchanged')


if __name__=='__main__': main()
