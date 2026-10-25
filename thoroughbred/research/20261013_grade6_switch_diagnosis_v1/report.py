"""Local report of all missed cases and exact frozen decision contributions."""
import json
import pandas as pd
import run as e


LABELS={
 'g1_level':'G1F 수준','g3_level':'G3F 수준','observation_support':'공동관측 수·유지율',
 'recent_records':'최근 보정기록·유효수·추세','front_probability':'예상 첫조 확률',
 'gate_position':'두 후보의 게이트 배치','experience_interval':'경력·출전간격',
 'base_model_assessment':'기초모델 확률차·후보순위','race_context':'거리·등급·두수·지역',
 'g1_support_interaction':'G1F×관측 수','g3_support_interaction':'G3F×관측 수',
 'g1_recent_interaction':'G1F×최근 상대기록','g3_recent_interaction':'G3F×최근 상대기록'}


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |'for r in rows])


def race_label(row):
    return f'{row.race_date:%m-%d} {"서울"if row.meet==1 else"부산"}{int(row.race_no)}경주'


def main():
    e.check();v=json.loads((e.OUT/'verification.json').read_text());assert v['status']=='verified'
    central=e.R/'conclusions/52_GRADE6_SWITCH_DIAGNOSIS.md'
    assert not central.exists()or e.HERE.name in central.read_text(),'conclusion52 used elsewhere'
    d=pd.read_parquet(e.OUT/'cases.parquet');f=pd.read_csv(e.OUT/'feature_comparisons.csv')
    b=pd.read_csv(e.OUT/'bundle_contributions.csv');comparison=pd.read_csv(e.OUT/'bundle_comparisons.csv')
    groups=[('blocked_gain','되돌려 놓친11'),('kept_gain','새축만 입상·유지10'),('kept_hit_all','새축 유지입상 전체14')]
    rows=[]
    specs=[('keep_fast_g3','새 축 과거 빠른초반 뒤 G3F 우위','초'),('keep_fast_g1','새 축 과거 빠른초반 뒤 G1F 우위','초'),
           ('keep_fast_n','새 축 공동관측 수','회'),('history_count','새 축 경력','전'),
           ('front_gate_probability','새 축 예상 첫조 확률','%'),('field_size','편성 두수','두')]
    for feature,label,unit in specs:
        values=[]
        for group,_ in groups:
            x=f[f.comparison_group.eq(group)&f.feature.eq(feature)].iloc[0]
            val=x.new_mean*(100 if unit=='%'else 1)
            values.append(f'{val:.3f}{unit} (관측{int(x.new_n)}/{int(x.races)})')
        rows.append([label]+values)
    rows.append(['새 축−기존 축 최근3전 보정지수']+[f'{f[f.comparison_group.eq(g)&f.feature.eq("moist_last3_record_index_mean")].iloc[0].delta_mean:+.3f} (짝관측{int(f[f.comparison_group.eq(g)&f.feature.eq("moist_last3_record_index_mean")].iloc[0].paired_n)})'for g,_ in groups])
    conditions=table(['경주 전 특성: 평균']+[label for _,label in groups],rows)
    rows=[]
    for bundle in ['recent_records','race_context','g1_support_interaction','gate_position','g1_level',
                   'observation_support','g3_support_interaction','g1_recent_interaction']:
        vals=[]
        for group,_ in groups:
            a=comparison[comparison.comparison_group.eq(group)&comparison.bundle.eq(bundle)].iloc[0]
            vals.append(f'{a["mean"]:+.3f}')
        rows.append([LABELS[bundle]]+vals)
    contributions=table(['모델 선택의 평균 기여(log-odds)']+[label for _,label in groups],rows)
    rows=[]
    for row in d[d.group.eq('blocked_gain')].itertuples():
        z=b[b.race_key.eq(row.race_key)].sort_values('contribution')
        reasons=' / '.join(LABELS[x]for x in z.bundle.head(2))
        rows.append([race_label(row),f'{row.old_program_no} {row.old_horse_name} ({row.old_outcome}위)',
                     f'{row.new_program_no} {row.new_horse_name} ({row.new_outcome}위)',
                     f'{row.p_loss*100:.1f}% / {row.p_gain*100:.1f}%',reasons])
    missed=table(['경주','실제 선택한 기존축','되돌려 놓친 새축','모델 교체실/득 추정','기존축 방향의 큰 기여묶음'],rows)
    rows=[]
    for row in d[d.kept_hit].itertuples():
        rows.append([race_label(row),f'{row.new_program_no} {row.new_horse_name}',row.new_outcome,row.old_outcome,
                     '새축만 입상'if row.switch_outcome==1 else'둘다 입상'])
    kept=table(['경주','유지한 새축','새축 실제','기존축 실제','분류'],rows)
    body=f'''# 2026 6등급: 좋은 축 교체를 되돌린 이유

2026-10-13. 연구52. 연구51의2026다항로지스틱선택모델을고정한후향진단이다. 서울·부산2026-09-20까지6등급의기초축차이44경주를모두비교했다. **좋은교체를되돌려놓친11경주는새축의G1F·최근기록이상대적으로약하게보였고,게이트배치와작은두수도선택모델에서불리하게작용했다.** 관측부족만으로는설명되지않았다. 아래‘이유’는모델이선택한수학적이유이며실제착순의인과원인은아니다.

## 비교 대상을 정확히 나누기

| 선택 | 새축만 입상 | 기존축만 입상 | 둘다 입상 | 둘다 실패 | 합계 |
| --- | --- | --- | --- | --- | --- |
| 기존축으로 되돌림 | 11: 놓침 | 1: 회복 | 8 | 4 | 24 |
| 새축 유지 | 10: 추가적중 유지 | 4: 실패 유지 | 4 | 2 | 20 |

사용자가말한‘새축을유지해서맞춘경주’는14개다. 그중기존축도입상한4개와새축만입상한10개는구분해야한다. 주비교는동일하게‘새축만입상’이었던11놓침대10유지다. 확장14개비교도함께남겼다. 이전122대비회복1/상실11=−10경주가재현됐다. 모델은실패한교체5개중1개만막았고좋은교체21개중11개를되돌렸다.

## 1. 기록과 조건은 어떻게 달랐나

{conditions}

G3F/G1F는같은과거빠른초반사건의상대초이고양수일수록그과거편성보다빠르다. 표본축소가이미적용됐고겹치는구간이라합산하지않는다. 최근보정기록은높을수록좋은지수이며초가아니다. 평균은결측을제외했고짝차이는양쪽모두관측된경주만썼다.

되돌려놓친11개중9개는새축의최근3전평균보정기록이기존축보다낮았다. 새축만입상·유지10개중그런경우는3개였다. 하지만청강여름/판타스틱로열은최근기록차이가오히려양수여도되돌렸다. 하나의공통원인이모든놓침을설명하지않는다.

관측수는놓친쪽2.0회대유지한쪽1.4회로놓친쪽이더많았다. 2회미만은각5/11대6/10, G1F결측은1/11대4/10이었다. 최근추세결측도각8/11대8/10이라‘추세가없으면못맞춘다’는일반화는맞지않는다. 유지군은관측이적어도다른조건이받쳐주면선택됐다. 관측된G1F평균차이는표본10개대6개에서나온값이므로소수말의영향이클수있다.

놓친쪽의새축예상첫조확률은39.1%,유지한추가적중군은24.9%였다. 모델이미리본초반이유리하다고해서입상유지가보장되는것은아니지만,이번놓친군에는초반지표가상대적으로좋은말도많았다. 추가설명용내측최고초반대비차이는놓친쪽+0.102초(10관측),유지추가적중쪽−0.242초(8관측)였다. 이는과거기록으로만든예상초반차이이고이번실제선행을관측한것이아니다. 이내측차이와동일거리관측수는이번선택모델의59입력에는없고기초122입력에있는설명용정보다.

거리분포도같지않다. 놓친군에는1000m가없고유지추가적중군에는3개가있다. 1200~1600m공통거리만보는추가기술비교에서도유지군7개중G1F관측5개평균+0.186초/최근지수짝차이+0.106으로방향은같았으나,이역시사후소표본비교다. 이추가비교는새정책이나문턱에사용하지않았다.

## 2. 선택 모델이 기존축을 고른 정확한 이유

모델의판단량은 **log(P교체득/P교체실)** 이다. 0보다작으면기존축을선택한다. 2020~2025의학습교체1,355개평균특성을기준점으로해119인코딩입력의기여를정확히분해했다. 기준점은{d.reference_log_odds.iloc[0]:+.6f}이고,기준점+모든기여합은44개모두저장확률의log비와일치했다. 양수기여는새축,음수는기존축방향이다.

{contributions}

되돌려놓친군은최근기록·관측·추세묶음이평균−0.232,G1F×관측−0.141,G1F수준−0.120,게이트배치−0.137로기존축방향이었다. G3F×관측은+0.159로새축방향이었지만다른불리한평가를뒤집지못했다. 관측수·동시유지율묶음자체는+0.071로새축방향이므로관측이없어일괄차단한것이아니다.

게이트는새축의절대위치보다두후보사이의차이가컸다. 놓친군의새축상대위치0.475/기존축0.686(새축이상대적으로안쪽),유지추가적중군은0.445/0.334(새축이상대적으로바깥쪽)였다. 선택모델은이상대배치를과거교체사례에서학습한계수로평가했고놓친군에음의기여를줬다. **실제내측게이트가불리하다는증거가아니며실제주행경로나외측손실을측정한것도아니다.** 능력예측모델의게이트유불리와교체선택모델의조건부계수는구분해야한다.

편성조건묶음도놓친군−0.197대유지추가적중군−0.046이었다. 놓친군평균9.82두/유지군10.80두였고,현재선택모델에서작은두수는교체를보수적으로보는방향이었다. 이선형주후보의등급/거리/두수는가감항이며G1F·게이트효과를6등급에서별도로학습하는등급상호작용은없다. 기존관측수/최근기록과의상호작용은있지만그것이신마·저경력의기량변화를완전히표현하지는못한다.

기여는log-odds단위다. 확률%p나경주능력초로읽으면안된다. A/B/차이와상호작용이상관돼있으므로개별계수를독립인과효과로해석하지않으며관련열을묶었다. 이표는결과로선별한집단의모델설명이고새로운성능검증이아니다.

## 3. 되돌려 놓친 11경주 전부

아래착순은실제결과다. 교체실/득은그말의입상확률이아니고두후보교체로입상을잃거나얻을조건부모델추정이다. 큰기여묶음은학습평균기준음의기여상위2개이며단독원인이아니다.

{missed}

청강여름은최근평균지수가기존축보다+0.386으로좋았는데도추세결측·기존축상대기록등최근상태묶음(−0.758),G1F×관측(−0.419),게이트(−0.259)가되돌림쪽으로작용했다. ‘최근평균기록이낮아서’라는설명은이경주에맞지않는다.

금아온포인트는과거G1F우위−0.366초여서G1F수준기여−0.943/G1F×관측−0.905가컸다. 그래도이번에는2위였다. 판타스틱로열도최근기록차이는+0.062였지만G1F수준·추세결측등최근상태·게이트기여가음수였다. 이런사례는과거G1F가나쁘면이번에입상할수없다는뜻이아님을보여준다.

## 4. 새축을 유지해 맞춘 14경주 전부

{kept}

유지추가적중군10개는G1F수준평균기여+0.081,게이트+0.066,G1F×최근상대기록+0.093으로놓친군보다유리하게평가됐다. 관측이없던말들도포함되므로이표를G1F평균좋은말만의성공표로읽으면안된다. 기존축도입상한4개는확장비교에서만합쳤다.

## 5. 과거 학습환경과 2026이 달랐던 점

선택학습의2020~2025 6등급교체420개에는새축만입상107/기존축만입상119/중립194였다. 2026은44개중21/5/18로바뀌었다. 입상이갈린경주만보면새축우세가과거107/226(47.3%)에서2026 21/26(80.8%)였다. 후향적으로골라본소표본이므로변화의원인이나향후동일비율을보장하지않는다.

과거보다2026의122새축이유리한상황에서선택모델이익숙한최근기록·G1F·상대게이트패턴을보수적으로적용한모습으로해석할수있다. 다만라벨빈도변화자체가잘못된되돌림의단독원인이거나2026을학습에넣으면해결된다는증거는아니다. 이번에는이44경주로보정을학습하거나6등급예외문턱을만들지않았다.

## 결론과 검증

이번문제는관측수가적은말을못쓰는문제만은아니다. 기존축보다최근기록이낮거나G1F가약한새축,상대적으로내측인새축을과거조건부선택계수로낮게평가한경우가놓침에모였다. 추가연구방향은저경력말에서G1F/최근기록의신뢰도·거리/등급·편성초반우위가어떻게달라지는지를과거OOF자료로따로검증하는것이다. 2026소표본에맞춘문턱을즉시채택할근거는없다.

44개전부의키/모델확률/집단,11놓침/14유지적중,5,236개입력기여/정보묶음합,모델재추론최대오차0,현재결과변조불변,원−10순차이,16원자료·보호파일hash를검증했다. 신규모델0,운영·선택22·미래계약·DB·제주변경없음. 소표본/결과조건화/상관입력/반복후향/부분연도/미관측전술·주행로·컨디션과기존보정·부담중량시점검증한계가남는다.

재현: `run.py` → `verify.py` → `report.py` → `finalize_inventory.py`.

[44경주 전체](outputs/all44_cases.csv) · [놓친11](outputs/missed11.csv) · [유지적중14](outputs/kept_hit14.csv) · [특성비교](outputs/feature_comparisons.csv) · [조건수](outputs/condition_counts.csv) · [입력별기여](outputs/feature_contributions.csv) · [묶음기여](outputs/bundle_contributions.csv) · [묶음비교](outputs/bundle_comparisons.csv) · [과거6등급교체](outputs/grade6_prior_outcomes.csv) · [검증](outputs/verification.json) · [용량명세](outputs/artifact_inventory.json)
'''
    (e.HERE/'README.md').write_text(body)
    pub='''# 2026 6등급의 좋은 축 교체를 왜 되돌렸을까

2026-10-13. 연구52. 고정선택모델의 후향진단이며새보정·운영반영아님.

무엇을 알았는가: 44개축교체중되돌려놓친11/새축유지추가적중10/두축모두입상유지4였다. 놓친군은새축G1F우위평균+0.046초(10관측),유지추가적중군은+0.163초(6관측),최근지수차이는−0.266대+0.091이었다. 관측수는오히려2.0대1.4회로관측부족만의문제가아니다.

기록을 어떻게 읽는가: 119인코딩입력을정확히분해하니놓친군의최근상태−0.232/G1F×관측−0.141/게이트배치−0.137/G1F수준−0.120이기존축방향이었다. G3F×관측은+0.159로새축방향이었다. 단위는log-odds이며입상확률%p나실제착순원인이아니다. 상대적게이트배치의조건부선택계수를실제내측유불리로해석하면안된다.

사례: 04-05서울1경주에서10나인스피어(10위)를유지해6청강여름(1위)을놓쳤다. 청강여름은최근평균지수가더좋아도추세결측/기존축평가등의묶음이선택을뒤집었다. 05-16서울3경주의10금아온포인트는과거G1F가약해8제주프린세스로되돌렸으나실제2위/7위였다. 전체11개와유지적중14개를보고서에실었다.

어디까지 적용되는가: 과거6등급교체는새축만입상107/기존축만입상119였지만2026은21/5였다. 모델의과거선택패턴과2026결과가달랐으나소표본·결과조건화·반복후향으로원인이나새규칙을확정할수없다. 44개확률재현오차0/5,236입력기여합검증,신규모델0,운영·선택22·미래계약유지.

[전체 보고서](README.md) · [놓친11경주](outputs/missed11.csv) · [유지적중14경주](outputs/kept_hit14.csv) · [검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/')+'\n원연구: '+e.HERE.name+'\n')
    marker='<!-- grade6_switch_diagnosis_v1_20261013 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=e.R/name;link=f'{e.HERE.name}/README.md'if name=='README.md'else central.name
        if marker not in path.read_text():
            with path.open('a')as handle:handle.write(f'\n\n{marker}\n[2026 6등급의 좋은 축 교체 되돌림 진단]({link}): 44교체/놓친11·유지추가적중10·유지입상전체14. 최근기록/G1F/상대게이트의음의선택기여,관측부족만으로설명불가. 확률재현오차0·5,236기여검증,새학습·운영반영없음.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',cases=44,missed=11,kept_gain=10,kept_hits=14,
        new_models=0,diagnostic_only=True,production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts and'publication_before'not in p.parts
         and p.name not in ['publication_before.json','artifact_inventory.json']]
    for path in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(path.relative_to(e.ROOT));source['sources']=[r for r in source['sources']if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(path),bytes=path.stat().st_size))
    e.save(manifest,source);e.check();print('Conclusion52 saved locally; no model change')


if __name__=='__main__':main()
