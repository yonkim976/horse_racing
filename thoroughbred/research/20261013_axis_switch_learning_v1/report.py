"""Publish the frozen learned switch experiment locally, with uncertainty intact."""
import json
import pandas as pd
import run as e


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |'for r in rows])


def main():
    e.check();v=json.loads((e.OUT/'verification.json').read_text());assert v['status']=='verified'
    central=e.R/'conclusions/51_AXIS_SWITCH_LEARNING.md'
    assert not central.exists() or '20261013_axis_switch_learning_v1'in central.read_text(),'conclusion number already used'
    m=pd.read_csv(e.OUT/'metrics.csv',dtype={'period':str}).set_index(['variant','period'])
    diff=pd.read_csv(e.OUT/'paired_differences.csv',dtype={'period':str});rows=[]
    for period,label in [('2024','2024'),('2025','2025'),('2026','2026 ~09-20'),('all','합산')]:
        a=m.loc[('frozen122',period)];b=m.loc[('joint_logit',period)]
        x=diff[diff.variant.eq('joint_logit')&diff.reference.eq('frozen122')&diff.period.eq(period)&diff.metric.eq('axis_top3')].iloc[0]
        rows.append([label,int(a.n),f'{a.axis_top3*100:.2f}%',f'{b.axis_top3*100:.2f}%',
                     f'{int(x.net):+d}경주',f'{x.difference_pp:+.3f}',f'[{x.lo_pp:+.3f},{x.hi_pp:+.3f}]'])
    annual=table(['기간','경주','기존122 축 입상','별도선택학습','적중 순증감','차이%p','95%구간%p'],rows)
    training=[]
    for year in [2024,2025,2026]:
        a=json.loads((e.OUT/'selector_models'/f'joint_logit_{year}'/'metadata.json').read_text())
        training.append([year,f'2020~{year-1}',a['training_rows'],a['outcome_counts']['1'],
                         a['outcome_counts']['-1'],a['outcome_counts']['0'],a['encoded_feature_count']])
    train_table=table(['평가연도','선택학습 사례기간','교체 사례','새 축만 입상','기존 축만 입상','중립','인코딩 열'],training)
    rows=[]
    for period,label in [('2024','2024'),('2025','2025'),('2026','2026 ~09-20'),('all','합산')]:
        a=m.loc[('frozen122',period)];b=m.loc[('joint_logit',period)]
        rows.append([label]+[f'{a[c]*100:.2f}% → {b[c]*100:.2f}%'for c in ['axis_top2','axis_win','quinella_one','axis_next3']])
    secondary=table(['기간','축2위 이내','축 우승','복승1조합','축복승3조합'],rows)
    transitions=pd.read_csv(e.OUT/'switch_transitions.csv',dtype={'period':str});rows=[]
    for period,label in [('2024','2024'),('2025','2025'),('2026','2026 ~09-20'),('all','합산')]:
        a=transitions[transitions.variant.eq('joint_logit')&transitions.period.eq(period)&~transitions.choose_new].iloc[0]
        rows.append([label,int(a.n),int(a.original_loss),int(a.original_gain),int(a.both_hit),int(a.both_miss),f'{int(a.change_net_vs122):+d}'])
    changes=table(['기간','122축 대신 기존축 선택','적중 회복','적중 상실','둘다 입상','둘다 실패','순증감'],rows)
    rows=[]
    names={'frozen103':'기존103','frozen122':'기존122','joint_logit':'득실 다항로지스틱(주후보)','joint_tree':'득실 작은트리(분리대조)'}
    for variant in ['frozen103','frozen122','joint_logit','joint_tree']:
        rows.append([names[variant]]+[f'{m.loc[(variant,period)].axis_top3*100:.2f}%'for period in ['2024','2025','2026','all']])
    family=table(['선택 방식','2024','2025','2026 ~09-20','합산'],rows)
    old=pd.read_csv(e.R/'20261012_joint_axis_guard_v1/outputs/metrics.csv',dtype={'period':str}).set_index(['variant','period'])
    fixed=table(['기간','이전 필수조건 방식','이번 득실 학습','적중 순증감'],
        [[p,f'{old.loc[("joint_recent",p)].axis_top3*100:.2f}%',f'{m.loc[("joint_logit",p)].axis_top3*100:.2f}%',
          f'{n:+d}']for p,n in [('2024',9),('2025',0),('2026',17),('all',26)]])
    body=f'''# 축 교체의 득실을 별도로 학습한 결과

2026-10-13. 서울·부산 연구51. **주후보의 축 입상은 기존122의60.83%에서61.12%로 소폭 높아졌지만, 확정적인 개선 근거는 아직 없다.** 2024+6경주/2025+10경주/2026-09-20−2경주, 합산+14경주였다. 합산차이+0.292%p의95%구간[−0.266,+0.852]는0을포함한다. 복승1조합은+1경주,축복승3조합은−3경주로 종합적인 동반마 개선은 확인되지 않았다.

이번에는G1F·관측수·최근기록으로통과여부를정하지않고,교체의득/중립/실을별도로학습했다. 기존122능력모델·확률은동결했다. 새로저장한것은과거학습용능력16개와선택6개이며운영·선택22·미래계약은유지했다.

## 1. 무엇을 예측하는 모델인가

기존103의축A와122의축B가다를때, B만1~3위이면득(+1),A만1~3위이면실(−1),둘다입상/둘다실패이면중립(0)을학습한다. 세범주모델이낸P(득)−P(실)≥0이면B,음수이면A를선택한다. A=B면변경할결정자체가없다. 세확률은합1인**교체결과의조건부추정**이며말의우승확률/입상확률이아니다. 동일축경주의서빙출력확률은선택에사용하지않는다. 별도독립기간확률교정은하지않았다.

후보는A/B두말로제한된다. 제3의말을새로발굴하는모델은아니다. 선택축을맨앞으로옮긴뒤나머지순서는122순위를보존한다. 복승1조합=선택1·2위,축복승3조합=선택축과선택2~4위각1조합이다. 122원점수·말별입상확률은그대로이므로이번결과를그확률의교정개선으로표현하지않는다.

## 2. 시간 누수를 막은 학습 자료

기초능력학습은2017부터,그이전은워밍업이라는기준을유지했다. 선택학습은기초모델의정직한시간외예측이가능한2020부터다. 2020~2023각연도의103/122모델은Y−3까지최초학습,Y−2조기종료·재학습,Y−1온도교정뒤Y를예측했다. 지역2×연도4×계약2=16모델과5,971경주의과거예측을새로만들었다. 자기학습자료의예측을선택학습에쓰지않았다.

평가2024~2026은이미동결된12능력모델의같은4,799경주/50,754출전을그대로썼다. 선택모델은연도별로다음과거교체사례만학습했다. 2025가2024실제를학습하는것은허용하지만2024선택모델은그결과를보지못한다.

{train_table}

전처리중앙값·평균·표준편차·범주어휘도해당선택학습기간에서만계산했다. 현재착순·실제구간기록은특성생성과선택API가거부한다. 평가라벨을섞어도입력과선택은바뀌지않는다. 다만동일2024~2026결과를이미보고연구방향을정한반복후향실험이며,시점분리자체가독립미래검증을뜻하지않는다.

## 3. 어떤 정보가 들어갔나

두말각각빠른초반뒤G3F/G1F/공동관측수/동시유지율,최근3전보정기록/유효수/추세/편성평균대비기록,예상첫조확률/게이트상대위치/경력/출전간격12항목을A/B/차이36열로표현했다. 거리·등급·두수·지역·국혼구분5,두기초모델의상대확률/순위6,G3F또는G1F×관측비율또는최근상대기록을A/B/차이12로추가해**원입력59열**이다. 결측표시와원핫화후119열이다. A/B/차이에는선형중복이있으므로독립정보가59종이라는뜻은아니다.

G3F/G1F는같은과거출전사건을공유하고서로겹치는구간이라합산하지않았다. 과거기록은표본축소가이미적용된상대초이며최근보정기록은지수가높을수록좋다. 관측부족이나결측은자동탈락조건이아니다. 숫자결측은학습중앙값과결측표시로다루며관측횟수0은그대로남긴다. 학습기간전체결측인열에만대체중앙값0을쓰고결측표시를보존한다.

주후보joint_logit은L2다항로지스틱C=0.1,max_iter2000. 분리대조joint_tree는같은입력의작은3범주LightGBM(leaves4,min_leaf60,L2=20,lr0.03,80rounds)이다. 후보·설정·기대득실0문턱은이번결과전에고정했다. 평가연도조기종료/문턱튜닝/결과후후보교체는없다. 전처리와로지스틱계수는JSON으로저장하며pickle은쓰지않았다.

## 4. 연도별 축 입상

{annual}

세연도주지표구간모두0을포함한다. 경주일군집bootstrap2,000회seed20261013의고정예측짝비교이며다중비교미보정·모델재학습불확실성미포함이다. 2025와2026을동일9월20일까지로맞춘지표도원표에남겼다. 부분연도차이뿐아니라선택학습자료와각기초모델도연도마다달라진다.

{family}

분리대조작은트리는합산60.70%,2026 61.49%로좋아지지않았다. 이결과를주후보의튜닝에사용하지않았다. 주후보합산61.12%도기존122를안정적으로넘었다고판정하지않는다. 103축입상60.47%보다+31경주지만122를넘는지가이번주질문이다.

## 5. 교체를 되돌려 무엇을 얻거나 잃었나

{changes}

전체671개기초축차이중307개는122의새축을사용하고364개는103축으로되돌렸다. 후자의입상회복102/상실88이+14의전부다. 중립군도학습에포함했으며회복/상실만보고학습자료를고르지않았다. 2026은78개되돌림중회복19/상실21로−2,새축유지89개에는기존모델대비교체득34/실16이남았다.

2025주후보는서울+12/부산−2,중거리+9였다. 2026은서울+3/부산−5,5등급+5/6등급−10이었다. 서로겹치는조건은더하면안된다. 2026의6등급은회복1/상실11로여전히기존122의새포착을많이놓쳤다. 이번결과에맞춰등급문턱을추가하지않았다.

## 6. 앞선 필수조건 방식과 어떻게 다른가

{fixed}

2026의−19경주손실이−2로줄어앞선필수조건방식보다17경주많이맞췄다. 선택모델은2026관측2회미만인32개교체중19개에서새축을썼고그안의교체득9/실5였다. G1F공동기록결측6개중4개에서새축을썼고4개모두교체득이었다. 최근평균보정기록이기존축보다낮은89개중38개에서새축을썼고득15/실8이었다. 조건들은겹치며,사후선택군의성적이어서그변수의인과효과로볼수없다.

이전확인규칙이거부할2026 112개중52개를새축으로남겨득20/실11을보존했다. 반대로확인규칙이통과시킨곳에서도선택을바꿀수있으므로이순이익9가두방식전체차이17과같지는않다. 전체가중치에서G1F·관측수·최근기록을함께쓰면서각각을필수문턱으로삼지않았음을확인했다.

## 7. 복승과 다른 축 지표

{secondary}

합산복승1조합은583→584(+1경주),축복승3조합1,342→1,339(−3),축2위이내2,292→2,305(+13),축우승1,468→1,469(+1)였다. 복승1조합95%차이구간은[−0.122,+0.164]%p,축복승3조합[−0.438,+0.333]%p로0을포함한다. 축선택의소폭개선이동반마조합개선으로이어진것은아니다.

## 결론과 검증

이번득실학습은필수조건방식의과도한제외를줄였고기존122대비합산축입상을소폭높였다. 다만연도별방향과복승결과가일관되지않아운영교체나검증완료로판정하지않는다. 2026 6등급의잘못된되돌림과축입상목표로학습한선택의동반마성능을추가로연구할근거가남았다. 결과후보정·새모형·새문턱은추가하지않았다.

과거능력16/고정평가능력12/선택6=34모델재추론최대오차0,로지스틱전처리재계산과재학습계수일치,학습/교정/평가시계열,59입력계약,정답API거부/변조불변,19,196개경주선택·복승독립계산,원지표정확재현,37원자료·보호파일hash를검증했다. 새능력16개는선택학습을위한과거예측용이며122운영모델교체를뜻하지않는다. DB·외부수집·제주접근없음. 기록보정·기존부담중량시점검증한계·2018이전구간관측부족·실제경로/전술/컨디션미관측·COVID기간·적은교체학습표본·고정자료반복사용한계를상속한다.

재현: `run.py past` → `run.py prepare` → `run.py learn` → `run.py analyse` → `verify.py` → `diagnostics.py` → `report.py` → `finalize_inventory.py`. 이전모델과원자료는동결재사용하며입력hash가달라지면중단한다.

[입력계약](outputs/feature_contract.json) · [과거교체표본](outputs/switch_training_counts.csv) · [연도별지표](outputs/metrics.csv) · [짝비교·신뢰구간](outputs/paired_differences.csv) · [교체득실](outputs/switch_transitions.csv) · [경주별선택](outputs/switched_races.csv) · [조건별득실](outputs/conditions.csv) · [필수조건없는선택사례](outputs/no_hard_filter_cases.csv) · [고정규칙대비](outputs/comparison_to_fixed_guard.csv) · [검증](outputs/verification.json) · [용량명세](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 축 교체를 따로 학습하면 기존 모델보다 좋아질까

2026-10-13. 서울·부산 연구51. 연구후보이며 운영 반영 아님.

무엇을 알았는가: 기존122축입상60.83→61.12%,2024+6/2025+10/2026-09-20−2경주로합산+14였다. 차이+0.292%p의95%구간[−0.266,+0.852]는0을포함해확정개선은아니다. 복승1조합12.15→12.17%(+1),축복승3조합27.96→27.90%(−3)로동반마개선도불확실했다.

기록을 어떻게 읽는가: 103축과122축이다를때새축만입상/기존축만입상/중립을별도로학습했다. G3F·G1F·관측수·최근보정기록등두말의값과차이59입력을사용하며각각을필수문턱으로두지않았다. P(교체득)−P(교체실)의부호로축을선택하고나머지122순서는유지한다. 이확률은말의우승/입상확률이아니다.

사례: 2026선택학습에는2025까지의교체1,355개만사용했다. 관측2회미만에서도19번새축을유지해교체득9/실5,최근기록이낮은경우38번유지해득15/실8이었다. 조건들은겹치며인과증거가아니다. 앞선필수조건방식의2026−19경주에비해이번−2경주로17개를더맞췄다. 그래도2026 6등급에서는기존122대비−10경주가남았다.

어디까지 적용되는가: 과거OOF능력16개를새로학습하고각평가연도이전교체사례로선택6개를학습했다. 고정평가능력12개와함께34모델재현오차0,4,799경주검증. 주후보는다항로지스틱이며작은트리대조는합산60.70%로개선되지않았다. 이미같은기간연구결과를본후향연구/다중비교미보정/부분연도/적은교체표본한계가있다. 운영·선택22·미래계약·원122확률은유지한다.

[전체 보고서](README.md) · [연도별 지표](outputs/metrics.csv) · [선택 경주](outputs/switched_races.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/')
                      +'\n원연구: '+e.HERE.name+'\n')
    marker='<!-- axis_switch_learning_v1_20261013 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=e.R/name;link=f'{e.HERE.name}/README.md'if name=='README.md'else central.name
        if marker not in path.read_text():
            with path.open('a')as handle:
                handle.write(f'\n\n{marker}\n[축 교체 득실의 별도 학습]({link}): 과거OOF16+선택6학습,고정평가12포함34모델재현오차0. 122대비축입상60.83→61.12%(+14경주),2024+6/2025+10/2026−2. 95%구간0포함,복승거의동일,운영유지.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',past_races=5971,test_races=4799,
        new_past_ability_models=16,new_selector_models=6,frozen_ability_models=12,primary='joint_logit',
        primary_axis_net_vs122=14,primary_2026_axis_net_vs122=-2,primary_quinella_one_net=1,
        primary_axis_next3_net=-3,promoted=False,horse_probability_changed=False,
        production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts and'publication_before'not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for path in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(path.relative_to(e.ROOT));source['sources']=[r for r in source['sources']if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(path),bytes=path.stat().st_size))
    e.save(manifest,source);e.check();print('Conclusion51 saved locally; no promotion')


if __name__=='__main__':main()
