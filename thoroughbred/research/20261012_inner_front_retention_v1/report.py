"""Korean report and central conclusion for the frozen combined-feature experiment."""
import json
import pandas as pd
import run as e


def table(d):
    def text(v): return f'{v:.6f}' if isinstance(v,float) else str(v)
    return '\n'.join(['| '+' | '.join(d.columns)+' |','| '+' | '.join(['---']*len(d.columns))+' |']+
                     ['| '+' | '.join(text(v) for v in row)+' |' for row in d.itertuples(index=False,name=None)])


def annual(m,a,b):
    rows=[]
    for period in ['2024','2025','2026','all']:
        old=m[(m.variant==b)&(m.period==period)].iloc[0]
        new=m[(m.variant==a)&(m.period==period)].iloc[0]
        row=dict(period=period,n=int(new.n))
        for metric in ['axis_top3','axis_top2','quinella_one','axis_next3']:
            row[metric]=f'{100*old[metric]:.2f}% → {100*new[metric]:.2f}%'
        row['Brier']=f'{old.target_brier:.6f} → {new.target_brier:.6f}'
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    e.check();v=json.loads((e.OUT/'verification.json').read_text());assert v['passed']
    m=pd.read_csv(e.OUT/'metrics.csv',dtype={'period':str});d=pd.read_csv(e.OUT/'paired_differences.csv',dtype={'period':str})
    ablation=m[(m.period=='all')&m.variant.isin(['baseline22','inner37','front39','combined55','previous_full103'])]
    ablation=ablation[['variant','n','axis_top3','axis_top2','quinella_one','axis_next3','top5_all','trio6','target_brier']]
    primary=d[(d.variant=='combined55')&(d.reference=='baseline22')]
    secondary=d[(d.variant=='combined55_top2')&(d.reference=='baseline22_top2')]
    increment=d[(d.variant=='combined55')&(d.reference=='front39')&(d.period=='all')]
    oldcomparison=d[(d.variant=='combined55')&(d.reference=='previous_full103')&(d.period=='all')]
    coverage=pd.read_csv(e.OUT/'coverage.csv');gain=pd.read_csv(e.OUT/'gain_loss.csv',dtype={'period':str})
    body=f'''# 내측 초반 경쟁·앞선 진입 확률·종반 유지력을 결합한 모델

2026-10-12. **선택22입력 모델보다 입상확률 오차와 축복승3조합은 개선됐다. 축마 입상률도 세 연도에서 올랐지만, 합산 축마·복승1조합 개선은 불확실하다. 이전103입력 연구모델을 전반적으로 넘지는 못했다.** 새55입력은 연구 후보로 보존하고 운영·선택22·미래검증계약은 유지한다.

## 비교 대상과 지표

서울·부산 같은4,799경주/50,754출전이다.2024년1,761경주,2025년1,750경주,2026-09-20까지1,288경주. 관측연구45의4,827경주와는 능력모형의 유효결과/카드 필터가 다르다. 신마·구간기록결측도 이번 평가에서 제외하지 않았다. 연구의 기존 기준은 사용자가 선택한 **월·게이트·부담중량22입력**이고 운영모델 자체의 교체 시험으로 해석하지 않는다.

- axis_top3:예측1위 축마가 실제3위이내. axis_top2:같은축마가2위이내.
- quinella_one:예측상위2두가 실제1·2착을 순서무관 모두 차지한 복승1조합.
- axis_next3:축마1두를 고정하고 예측2~4위와 짝지은 **복승3조합 중 적중**. 삼복3조합이나 3두가 함께 입상한 비율이 아니다.
- top5_all:예측상위5두 안에 실제입상3두 모두 포함. trio6:전체삼복조합의 말점수합 상위6조합 중 실제삼복 적중.6두선정과다르며 배당/수익률평가가아니다.
- Brier:예측입상확률과 실제입상여부의 제곱오차 평균, 작을수록좋다. 입상라벨 모형에서 말별 입상확률합은경주당3,상위2착라벨은합2다. 축우승확률을직접학습한모형이아니다.

## 추가 입력과 시점

22→37→39→55의 고정 세 단계다. [전체열계약](outputs/feature_contract.json)에55개를보존했다.

**초반 경쟁15개:** 최근실제3슬롯 보정초반평균과최근5지원수,게이트상대위치,내측두수/초반지원수,내측최고및평균시간−자기시간,내측더빠른말수/±0.15초근접수,동일거리최근5슬롯초반평균/지원수/내측최고대비차이/내측지원수,과거첫조율/지원수. 동일거리평균은기록2개이상,내측차이는내측3두·80%지원조건이며 일반최근3채널은관측수가작아도차이를계산하고지원수를함께둔다. 게이트번호결번유지,실제내·외측주행경로아님.

**앞선 확률2개:** 첫통과조진입확률과지원표시. 첫조여러두가능,단독선행확률과다르고합1을강제하지않는다.37입력으로2020~2026각년도이전자료만보조모형7개학습했다.2017~2019는이확률결측보존. 현재실제초반이나현재통과조를입력하지않는다.

**종반 유지12개:** 같은과거출전의초반/G3F/G1F를짝지어,첫조진입시G3F·G1F상대우위/관측수/동시유지율4개,상대평균보다초반이빨랐을때같은4개,외측이면서초반빨랐을때G3F·G1F상대우위/관측수3개,전체유효짝수1개다. 각구간상대5두·80%관측과정상결과요구. 평균n/(n+3)수축,유지율(유지+1)/(n+2),사건0회면평균/비율결측이다. 첫조는공식통과조,빠른초반은상대시간기준으로구분한다. 생리적힘사용이나'무리했다'는의도는관측하지못한다.

**관계4개:** 앞선확률×첫조G3F/G1F우위2개,앞선확률×내측빠른상대관측비율×빠른초반G3F/G1F우위2개. G1F는G3F에포함되므로두초손실을더해감점하지않는다. 외측일괄감점도없다.

기록은기존section_style의연도이전자료로적합한함수율·월·게이트보정값을동결재사용했고미지원은원시초를유지했다. 게이트보정이후의추가전개설명력을시험한것이다. 별도서울구간후속02C의새보정은동시에반영하지않았다. 현재기수/조교사/배당/실측전개/실측함수율은새입력에없다. 과거는T−2/730일/실제최근5전,결측을건너뛰어5개를채우지않는다.

입력관측범위:

{table(coverage)}

동일거리내측차이는지원이엄격해전체의약6%뿐이다. 일반초반채널/결측표시로나머지말도남겼다. 앞선후유지경험과빠른초반유지경험은서로다른조건이다.

## 학습 방법

능력학습은2017년부터,이전2010~2016은기존이력워밍업이다. 연도Y의모형은Y−3까지최초학습,Y−2조기종료선택후재학습,Y−1조합온도교정,Y시험. LightGBM이진/learning_rate0.04/leaves15/minleaf150/L2=5/max200/earlystop25/seed20261004/1두수가중을기존과동일하게고정했다. 앞선보조는각자기연도이전2017년이후자료/180회/L2=10/seed42다. 자기연도정답으로만든앞선확률을능력훈련행에넣지않았다.

입상라벨3후보×서울·부산×3연도=18능력모형. 상위2착라벨55입력도6개추가,최종저장능력24개+앞선7개다. 기존baseline22와previous_full103은동결예측재사용. 결과후열선별/임계값검색/최적후보선택은하지않았다.

## 입상라벨 주 후보: 연도별 기존22 → 결합55

{table(annual(m,'combined55','baseline22'))}

전체축3위이내2,862→2,911경주로49경주증가,축2위이내2,274→2,300으로26증가,복승1조합576→595로19증가,축복승3조합1,258→1,323으로65증가했다. 축3위추가적중419경주와기존적중상실370경주가함께발생했다.2024순증39경주,2025는6경주,2026은4경주로효과크기는일정하지않다.

같은경주차이의경주일군집bootstrap2,000회/seed20261012/95%CI다. 적중지표는%p,오차는원단위이며음수Brier가개선이다.

{table(primary)}

전체축3위+1.021%p구간[-0.163,+2.266]과복승1조합+0.396%p[-0.417,+1.205]는0을포함한다. 축복승3조합+1.354%p[+0.408,+2.347]와Brier−0.001418[-0.001951,-0.000893]는이번표본에서개선신호다.2025/2026Brier도개선했지만2024는불확실하다.2025축2위는47.66→47.26%로소폭하락했다. 여러지표·연도를탐색한반복후향검증이므로독립미래재현을대신하지않는다.

삼복6조합은전체25.59→26.36%,2024는25.21→24.70%로하락,2025는24.17→25.31%,2026은28.03→30.05%다. 삼복을주목표로이후후보를고른것이아니다.

## 어느 묶음에서 달라졌는가

아래비율은0~1이다.

{table(ablation)}

37입력초반경쟁만으로축입상59.64→60.22%,39입력앞선확률까지는60.08%,55입력종반까지60.66%였다. 앞선확률을넣으면모든지표가단조롭게좋아지는구조는아니다. 최종55−39의Brier는−0.000726[-0.001094,-0.000362]로개선됐지만축입상+0.583%p[-0.378,+1.655],축복승3조합+0.250%p[-0.624,+1.153]는불확실했다. 즉 **종반묶음의추가효과는확률오차에서더명확하며적중률에서는미확정**이다.

{table(increment)}

보조앞선모형의최고확률말첫조진입은2024년67.13%,2025년67.48%,2026년68.44%다. 전원통과조관측경주1,725/1,719/1,258에서계산했다. 이지표는입상/우승확률정확도와다르며이번표에앞선보조의동일입력기준모형대비개선검증을추가하지않았다. 모델이사용한묶음별gain은[중요도](outputs/bundle_importance.csv)에보존했고인과효과로해석하지않는다.

## 상위2착 목표로 별도 학습한 보조 시험

기존상위2착22입력 → 상위2착55입력이다. 입상라벨표와Brier수준을직접비교하면안된다.

{table(annual(m,'combined55_top2','baseline22_top2'))}

복승1조합전체12.38→12.42%,축2위47.43→47.78%로매우작은변화다. 두지표와축복승3조합의합산차이95%구간은모두0을포함한다.2026축2위는49.30→48.68%로하락했다. 확률Brier는세연도및합산에서개선됐지만복승적중문제를해결했다는근거는없다.

{table(secondary[secondary.metric.isin(['axis_top2','quinella_one','axis_next3','target_brier'])])}

## 이전103입력 연구와 비교하면

이번55입력은선택22모델을기준으로새로쌓은작은입력구성이며이전103입력에추가한159입력모형이아니다. 이전full103은다양한구간·각질·비선행추월관계까지포함했다. 축입상60.47→60.66%차이는불확실하고,복승1조합은둘다595/4,799로같다. 축복승3조합은28.07→27.57%,상위5두입상전체포착32.86→31.36%로낮았다. Brier도0.174657→0.176165로악화됐다. 따라서새후보가전체연구중최선이라고말할수없다.

{table(oldcomparison)}

## 판단과 검증

내측초반차이·앞선확률·과거종반유지를연결하는정보에는추가가치의신호가있다. 특히22입력대비확률오차와축복승3조합개선은후속검증후보로남길만하다. 하지만축단독/복승1조합향상확정및103입력대체근거는부족하다. 이번결과로선택22·운영모형·미래계약을변경하지않았다. 기존동결계약은그대로보존하며새55후보의별도미래검증설계가필요하다.

24저장능력모형과7앞선모형재추론,19,196개모형·경주지표,확률합/축/복승/상위5/삼복조합/Brier를확인했다. 최대점수재현오차0,기준22입력/예측불변.250개실제과거슬롯과180개원시관측의같은출전유지사건을독립재계산했고80개전체편성의현재정답변조에도입력불변이었다. 앞선/능력학습·교정시점및730일을검증했다.

한계는반복후향표본/다중비교미보정/2026부분연도/2018이전구간자료결측/같은거리지원부족/보정미지원원시초/과거와현재편성변화다. 기수의도·실제주행경로·생리적소모는추정하지않았다. 기존22입력의당일부담중량시점은상속된검증범위이며원선택문서의`current_weight_pit_verified=false`를이번작업이해결한것은아니다. 로컬자료만사용했고DB쓰기/외부수집/제주변경은없다.

재현순서: `run.py prepare`→`run.py train`→`run.py analyse`→`verify.py`→`diagnostics.py`→`report.py`→`finalize_inventory.py`.

[연도별전체지표](outputs/metrics.csv) · [짝비교와95%구간](outputs/paired_differences.csv) · [적중획득·상실](outputs/gain_loss.csv) · [검증](outputs/verification.json) · [용량명세](outputs/artifact_inventory.json)
'''
    assert not (e.HERE/'README.md').exists();(e.HERE/'README.md').write_text(body)
    pub='''# 내측 초반차이·앞선확률·종반유지 결합 모델 검증

2026-10-12. 연구후보이며 운영반영아님.

무엇을알았는가:선택22입력에초반경쟁15개,첫조진입확률/지원2개,같은과거출전종반유지12개와관계4개를더해55입력을학습했다. 같은4,799경주의축입상59.64→60.66%,복승1조합12.00→12.40%,축복승3조합26.21→27.57%,입상확률Brier0.177583→0.176165다. 축복승3조합차이95%구간[+0.408,+2.347]%p와Brier차이[-0.001951,-0.000893]는개선신호지만축입상/복승1조합구간은0을포함했다.

기록을어떻게읽는가:내측말의과거보정초반평균−자기평균으로초반우위를계산한다. 첫조확률은단독선행확률과다르며자기연도이전자료만학습했다. 과거초반·G3F·G1F는같은출전끼리묶고첫조/빠른초반/외측빠른초반경험을구분했다. T−2·730일·실제최근5슬롯,상대5두·80%관측,소표본수축·경험수표시를적용했다. 실제힘소모나외측주행거리손실을관측한지표는아니다.

사례:2024축입상58.77→60.99%,2025는59.03→59.37%,2026-09-20은61.65→61.96%다. 축복승3조합은25.44→27.20%,25.43→26.80%,28.34→29.11%였다. 전체축입상은새적중419경주와기존적중상실370경주가함께발생했다. 상위2착라벨별도학습도Brier는좋아졌지만복승1조합12.38→12.42%라적중향상은불확실했다.

어디까지적용되는가:2017이후학습/이전워밍업,연도이전학습·교정으로능력24개/앞선7개를검증했다. 이전103입력연구보다상위5두입상포착과확률오차는낮아전반적최고후보가아니다. 반복후향/다중비교/2026부분연도/관측부족한계가있다. 운영·선택22·이전미래검증계약은유지하고새55후보를연구결과로보존했다.

[전체보고서](README.md) · [연도별지표](outputs/metrics.csv) · [차이와신뢰구간](outputs/paired_differences.csv) · [재현검증](outputs/verification.json)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central=e.R/'conclusions/46_INNER_FRONT_RETENTION.md';assert not central.exists()
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/'))
    marker='<!-- inner_front_retention_v1_20261012 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        p=e.R/name;link=f'{e.HERE.name}/README.md' if name=='README.md' else central.name
        with p.open('a') as handle:
            handle.write(f'\n\n{marker}\n[내측초반·앞선확률·종반유지55입력 결합]({link}):4,799경주/능력24+앞선7모형.22대비축입상59.64→60.66%(불확실),축복승3조합26.21→27.57%(차이CI양수),Brier0.177583→0.176165.이전103입력전체능력초과미확인,운영유지.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',new_ability_models=24,new_front_models=7,
         races=4799,runners_per_variant=50754,production_changed=False,selected_baseline_changed=False,
         future_contract_changed=False,database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';sm=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(p.relative_to(e.ROOT));sm['sources']=[row for row in sm['sources'] if row['path']!=key]
        sm['sources'].append(dict(path=key,sha256=e.sha(p),bytes=p.stat().st_size))
    e.save(manifest,sm);e.check();print('Published conclusion46 locally; no model promotion')


if __name__=='__main__':
    main()
