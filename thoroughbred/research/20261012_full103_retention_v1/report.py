"""Publish the full103 augmentation, including the exploratory deletion control."""
import json
import pandas as pd
import run as e


def table(d):
    def text(v):return f'{v:.6f}' if isinstance(v,float) else str(v)
    return '\n'.join(['| '+' | '.join(d.columns)+' |','| '+' | '.join(['---']*len(d.columns))+' |']+
                     ['| '+' | '.join(text(v) for v in row)+' |' for row in d.itertuples(index=False,name=None)])


def annual(m,new):
    rows=[]
    for period in ['2024','2025','2026','all']:
        b=m[(m.variant=='baseline103')&(m.period==period)].iloc[0]
        a=m[(m.variant==new)&(m.period==period)].iloc[0]
        row=dict(period=period,n=int(a.n))
        for metric in ['axis_top3','axis_top2','quinella_one','axis_next3']:
            row[metric]=f'{100*b[metric]:.2f}% → {100*a[metric]:.2f}%'
        row['Brier']=f'{b.target_brier:.6f} → {a.target_brier:.6f}'
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    e.check()
    verification=json.loads((e.OUT/'verification.json').read_text())
    sensitivity=json.loads((e.OUT/'sensitivity_verification.json').read_text())
    assert verification['passed'] and sensitivity['passed']
    m=pd.read_csv(e.OUT/'metrics.csv',dtype={'period':str})
    sm=pd.read_csv(e.OUT/'sensitivity_metrics.csv',dtype={'period':str})
    allm=pd.concat([m,sm],ignore_index=True)
    d=pd.read_csv(e.OUT/'paired_differences.csv',dtype={'period':str})
    sd=pd.read_csv(e.OUT/'sensitivity_differences.csv',dtype={'period':str})
    keymetrics=['axis_top3','axis_top2','quinella_one','axis_next3','target_brier']
    primary=d[(d.variant=='combined122')&(d.reference=='baseline103')&d.metric.isin(keymetrics)]
    swap=d[(d.variant=='swapped122')&(d.reference=='combined122')&(d.period=='all')&d.metric.isin(keymetrics)]
    sens=sd[(sd.period=='all')&sd.metric.isin(keymetrics)]
    ablation=allm[allm.period=='all'][['variant','n','axis_top3','axis_top2','quinella_one','axis_next3','top5_all','trio6','target_brier']]
    dedup=json.loads((e.OUT/'deduplication.json').read_text())
    gains=pd.read_csv(e.OUT/'gain_loss.csv',dtype={'period':str})
    gains=gains[(gains.variant=='combined122')&(gains.reference=='baseline103')]
    body=f'''# 기존103입력에 내측 초반차이·앞선확률·종반유지 통합 검증

2026-10-12. **기존103입력보다 축마 입상률은 조금 높아졌으나, 복승 적중률과 확률 오차를 함께 개선하지 못했다.** 중복을 정리한122입력 주 후보의 전체 축입상60.47→60.83%,복승1조합12.40→12.15%,축복승3조합28.07→27.96%다. 합산차이의95%구간은모두0을포함한다. 기존종반4항목을남긴126입력탐색대조도복승개선을확인하지못했다.103입력연구모형을이번후보로교체할근거가없다.

## 질문과 비교 기준

이전46번은22입력에새정보를추가한55입력이었다. 이번에는이미구간·각질·게이트·앞선확률·조건부종반관계를가진full103을직접기준으로삼았다. 동일서울·부산4,799경주/50,754출전,2024년1,761·2025년1,750·2026-09-20까지1,288경주다. 신마·구간결측을배제하지않는다. 관측연구45의4,827경주와는다른능력검증표본이다.

축입상=점수1위말실제3위이내,축2위=동일축의1·2착이내. 복승1조합=점수상위2두가실제1·2착을순서무관모두차지. 축복승3조합=점수1위축과2·3·4위를각각짝지은복승3개중적중이다. 삼복3조합이나상위3두동반입상률이아니다. 능력학습라벨은3위이내이며복승목표전용학습은이번에추가하지않았다.

## 중복을 어떻게 정리했는가

103+55를그대로158입력으로합치지않았다.55의기본22개도103에이미있다.55의새33개중정확중복6,결정적게이트비율1,같은목적각질이력2,앞선확률1을제외해23개를고유추가후보로남겼다. 기존종반상대평균/지원4개는주후보에서새표현으로대체하여 **103−4+23=122**가됐다. 기존기초103내의구간별지원수는서로다른계측정보의관측수라,우연히값이같다는이유만으로삭제하지않았다.

{table(pd.DataFrame(dedup['map']))}

- 정확중복6개는전체178,497행에서같았다. 초반평균/지원,내측수/지원/빠른수,앞선확률지원이다.
- 게이트상대위치는기존내측두수/(두수−1)로복원가능하다. 실제주행내외측경로는관측하지않는다.
- 새첫조율/지원은기존각질빈도와같은목적이다. 충돌통과조제외차이로20/52행은달랐지만이번전개정보효과와품질개정을섞지않고기존빈도를유지했다.
- 앞선확률은기존103에이미있다. 주후보는기존65입력보조모형확률을쓰고,새37입력보조확률을동시에추가하지않았다. 뒤의swapped122만교체한다.
- 기존첫조G3F/G1F상대평균및각지원수4개는새엄격짝G3F/G1F우위·공동지원·동시유지율4개로대체했다. 절대구간초와상대우위는다른정보여서기존절대기록·비선행추월관계는남겼다.4개의옛상대표현은관측범위가달라정확중복은아니므로제거영향을126입력추가대조로분리했다.

신규초반7개는내측최고/평균초반기록과의차이,각질조건없이±0.15초근접한내측수,동일거리최근5슬롯초반평균/유효수/내측최고대비차이/내측지원수다. 기존근접선행수는과거첫조율≥0.4조건이어서새근접수와다르다. 동일거리평균최소2기록,내측동일거리차이최소3두·80%지원조건은46번그대로다.

종반12개는첫조진입시G3F/G1F우위·지원·동시유지율4,빠른초반시동일4,외측빠른초반시우위2·지원1,전체유효짝수1이다. 같은과거출전의세구간을묶고정상결과·구간별상대5두·80%관측을요구한다. 평균n/(n+3)수축,유지율(유지+1)/(n+2),사건0이면평균/비율결측이다. 현재T−2/730일/실제최근5출전슬롯을지키고유효기록만찾아슬롯을채우지않았다.

관계4개는앞선확률×첫조종반우위2,앞선확률×내측빠른말비율×빠른초반종반우위2다. G1F는G3F에포함되므로두초를더해손실보정하지않는다. 실제추가힘사용·경합의도·외측주행거리손실을관측한변수는아니다.

## 고정한 후보와 학습

- baseline103:기존full103의동결모형·예측.
- gap110:103+초반7개. 기존앞선확률/종반표현유지.
- combined122(주후보):중복정리통합122개,기존앞선확률유지.
- swapped122:122개구성에서앞선확률만새37입력보조로교체. 이에의존하는기존편성종반관계12와신규관계4를모두재계산하여옛확률이직·간접입력에남지않게했다.

주능력후보3×지역2×연도3=18최종모형,새앞선보조학습0개다. 양쪽각7개보조를동결재사용·재검증했다.2017학습/이전워밍업,연도Y의2017~Y−3최초학습,Y−2조기종료·재학습,Y−1조합온도교정,Y시험. learning_rate0.04/leaves15/minleaf150/L2=5/max200/earlystop25/seed20261004/1두수가중은기존과같다. 기존연도이전함수율·월·게이트구간보정재사용,지원없으면원시초유지다. 새서울02C보정은혼합하지않았다. 기수·조교사·배당·현재실측초반/종반/통과조는새입력에없다.

## 주 후보 연도별: 기존103 → 통합122

{table(annual(allm,'combined122'))}

축입상은전체2,902→2,919로17경주증가,축2위2,280→2,292로12증가했다. 복승1조합595→583으로12감소,축복승3조합1,347→1,342로5감소했다. 축입상은새적중186경주와기존적중상실169경주가함께발생했다.2024축입상+10경주/2025−13/2026+20으로효과가연도별로엇갈렸다. 확률Brier는0.174657→0.174808로소폭악화했다. 이오차는경주별말평균을낸뒤경주동일가중이며작을수록좋다.

{table(gains)}

## 차이와 불확실성

같은경주짝비교,경주일군집bootstrap2,000회seed20261012,95%CI다. 적중률차이는%p,오차는원단위다.

{table(primary)}

전체축입상+0.354%p[-0.447,+1.175],복승1조합−0.250%p[-0.820,+0.342],축복승3조합−0.104%p[-0.870,+0.647]다. 모두0을포함한다.2026축입상+1.553%p[+0.153,+2.968]의후향신호는있지만2025에반복되지않았고,2026복승개선도확정되지않았다. 많은후보·지표·연도를반복탐색한자료이며다중비교미보정이다.

상위5두전체입상포착은32.86→32.36%로낮아졌고,삼복6조합은27.13→27.28%로작은변화다. 삼복6개는전체말점수합상위6조합이며6두를고르는것이아니다. 이보조결과로주후보판정을바꾸지않는다.

## 초반차이 추가와 앞선확률 교체

전체비율은0~1이다.

{table(ablation)}

초반7개만추가한110개는축입상60.39%,복승1조합12.48%,축복승3조합27.90%였다. 기존103대비일관된개선이없었다. 앞선확률을새37보조로교체한122개는축입상60.58%,복승1조합12.25%,축복승3조합27.67%였다. 기존확률을쓰는주122보다복승이나축입상이일관되게좋아지지않았다. 교체후모든확률의존관계를재계산했고,옛확률만바꾼채옛관계를남기는혼합은하지않았다.

새확률교체−주후보122의합산차이:

{table(swap)}

## 옛 종반4항목을 남긴126개: 탐색 민감도 대조

주후보의연도별예비결과를확인한뒤,제거한4개가완전히같은정보는아니라는점을분리하려고추가했다. [별도계획](SENSITIVITY_PLAN.md)과코드·입력해시를추가학습전에동결했다. 주후보122/주판정을대체하지않는다.126=103+초반7+종반12+관계4. 정확중복/결정적비율/동일목적각질·앞선확률중복은이후보에서도추가하지않았고,관측범위가다른기존종반4열만남겼다. 같은설정으로6능력모형을추가했다.

{table(annual(allm,'additive126'))}

126입력도전체축입상60.87%로+0.396%p였지만CI[-0.370,+1.150]로불확실했다. 복승1조합12.29%로기존12.40%보다낮고,축복승3조합28.15%도기존28.07%대비+0.083%p[-0.652,+0.820]로불확실했다. Brier0.174754도기존보다좋지않았다. **기존4개제거만복구해도복승향상이확인되지않았다.**122와126차이의합산구간도모두0을포함한다. 후속대조는탐색결과이며최고숫자의후보를골라채택하지않는다.

{table(sens)}

## 판단

이번표현·학습조건에서103입력을통합122로바꿀근거는없다.22입력에더했을때의46번개선이103입력에더했을때재현된것은아니다. 기존103이이미초반경쟁·첫조확률·종반관계를포함해추가정보량이작았을가능성이있다. 이는중복지도와단계시험을바탕으로한해석이며,전개가중요하지않다거나다른표현도실패한다는증거는아니다.

축입상이조금올라도상대말순위가함께좋아진것은아니었다. 다음연구를한다면관측변수추가만반복하기보다축고정후상대후보의동반1·2착관계를직접검증할필요가있다. 이번에는새로운후속모형이나미래검증계약을자동추가하지않았다. 운영모형・선택22・기존103연구・기존미래계약은유지한다.

## 검증과 재현

원103입력/예측불변,전체178,497행의중복대조,같은4,799경주와50,754출전,실제과거슬롯/동일말/T−2/730일을확인했다.200표본종반수축·지원/내측차이를독립재계산했고,60전체편성의현재정답변조에도입력이같았다. 교체후보에서기존앞선확률을임의변조해도교체특징이변하지않는지검증했다. 같은출전원시사건검증은해시동결한46번원본을재사용한다.

주실험18능력+동결14보조를재추론해최대점수오차0,14,397개모형·경주의축/복승/조합/확률합/Brier/NLL을검증했다. 추가126의6능력모형도점수및4,799경주지표를재검증했다. 최종신규능력24개,신규앞선0개다. 원자료・선택22・운영레지스트리・미래계약해시가유지됐다. DB접근/외부수집/제주변경은없다.

한계:반복후향검증/다중비교미보정/2026부분연도/2018이전구간결측/동일거리관측부족/과거보정미지원원시초/실제주행경로·전술·컨디션미관측. 기존부담중량의시점검증한계도상속하며이번연구가해결한것은아니다.126대조는주결과예비확인후추가한탐색시험임을유지한다.

재현: `run.py prepare`→`run.py train`→`run.py analyse`→`verify.py`; 별도민감도는`sensitivity.py train`→`sensitivity.py analyse`→`sensitivity.py verify`; 이후`report.py`→`finalize_inventory.py`.

[중복지도](outputs/deduplication.json) · [주입력계약](outputs/feature_contract.json) · [연도별지표](outputs/metrics.csv) · [짝비교](outputs/paired_differences.csv) · [126추가대조](outputs/sensitivity_metrics.csv) · [주검증](outputs/verification.json) · [추가검증](outputs/sensitivity_verification.json) · [용량명세](outputs/artifact_inventory.json)
'''
    assert not (e.HERE/'README.md').exists();(e.HERE/'README.md').write_text(body)
    pub='''# 기존103입력에 초반차이·앞선확률·종반유지를 더하면

2026-10-12. 연구후보이며 운영반영아님.

무엇을알았는가:같은서울·부산4,799경주에서103→중복정리122입력의축입상60.47→60.83%,복승1조합12.40→12.15%,축복승3조합28.07→27.96%였다. 합산차이95%구간은각[-0.447,+1.175],[-0.820,+0.342],[-0.870,+0.647]%p로모두0을포함했다. Brier도0.174657→0.174808로개선하지못했다.

기록을어떻게읽는가:103에이미있는6개정확중복,결정적게이트비율,동일목적각질빈도와앞선확률을중복추가하지않았다. 내측최고·평균초반차이와동일거리비교등7개,같은과거출전의첫조/빠른초반/외측빠른초반뒤G3F·G1F유지12개,확률×유지관계4개를쓰고옛상대종반4개를교체해122개다. 첫조확률은기존65입력보조모형을활용했다. 새37입력보조로교체한후보는모든확률의존관계도재계산했다.

사례:2024축입상60.87→61.44%,2025는59.60→58.86%,2026-09-20은61.10→62.66%로엇갈렸다.2026축입상에는후향신호가있었지만복승향상은확정되지않았다. 전체축추가적중186경주와기존적중상실169경주가함께발생했다. 옛종반4개를남긴126개탐색대조도축60.87%/복승1조합12.29%/축복승3조합28.15%로확실한개선이없었다.

어디까지적용되는가:2017이후학습/이전워밍업/각연도이전학습·교정,신규능력24개와동결앞선14개를재검증했다.126대조는주결과예비확인뒤추가한탐색시험이다. 반복후향/다중비교미보정/2026부분연도/관측부족한계가있다.22기준55입력의개선이103기준에서도재현된것은아니다.103연구모형・선택22・운영・미래계약은유지한다.

[전체보고서](README.md) · [연도별지표](outputs/metrics.csv) · [중복정리](outputs/deduplication.json) · [추가126대조](outputs/sensitivity_metrics.csv)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central=e.R/'conclusions/47_FULL103_RETENTION.md';assert not central.exists()
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/'))
    marker='<!-- full103_retention_v1_20261012 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        p=e.R/name;link=f'{e.HERE.name}/README.md' if name=='README.md' else central.name
        with p.open('a') as handle:
            handle.write(f'\n\n{marker}\n[103입력 중복정리·초반차이·종반유지 통합]({link}):4,799경주/신규능력24·동결앞선14재검증.103→122축입상60.47→60.83%,복승1조합12.40→12.15%,축복승3조합28.07→27.96%,합산CI0포함.126추가대조도확정개선없음,운영유지.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',new_ability_models=24,
          preregistered_ability_models=18,exploratory_sensitivity_models=6,new_front_models=0,frozen_front_models_replayed=14,
          races=4799,runners_per_variant=50754,production_changed=False,selected22_changed=False,
          previous103_changed=False,future_contract_changed=False,database_access=False,network_access=False,jeju_access=False))
    manifest=e.R/'conclusions/source_manifest.json';source=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(p.relative_to(e.ROOT));source['sources']=[r for r in source['sources'] if r['path']!=key]
        source['sources'].append(dict(path=key,sha256=e.sha(p),bytes=p.stat().st_size))
    e.save(manifest,source);e.check();print('Published conclusion47 locally; no promotion')


if __name__=='__main__':main()
