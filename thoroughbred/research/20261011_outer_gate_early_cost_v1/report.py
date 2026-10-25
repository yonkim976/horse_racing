"""Preserve results and a Korean publication summary; never promote a model."""
import json
import pandas as pd
import run as e


def table(d):
    def text(v):
        return f'{v:.4f}' if isinstance(v,float) else str(v)
    return '\n'.join(['| '+' | '.join(d.columns)+' |','| '+' | '.join(['---']*len(d.columns))+' |']+
                     ['| '+' | '.join(text(v) for v in row)+' |' for row in d.itertuples(index=False,name=None)])


def main():
    e.check()
    assert json.loads((e.OUT/'verification.json').read_text())['passed']
    c=json.loads((e.OUT/'coverage.json').read_text())
    roles=pd.read_csv(e.OUT/'outer_roles.csv')
    prior=roles[(roles.scope=='all') & (roles.basis=='prior')][['gap_band','n','front_rate','stalk_rate','middle_rate','rear_rate']]
    actual=roles[(roles.scope=='all') & (roles.basis=='actual')][['gap_band','n','front_rate','stalk_rate','middle_rate','rear_rate']]
    pair=pd.read_csv(e.OUT/'same_race_front_pairs.csv')
    pair=pair[pair.scope.isin(['all','2024','2025','2026'])]
    contrasts=pd.read_csv(e.OUT/'finish_contrasts.csv')
    con=contrasts[contrasts.contrast=='difference_in_differences']
    fe=json.loads((e.OUT/'fixed_effects.json').read_text())
    body=f'''# 외측 게이트의 초반 우위와 종반 저하

2026-10-11. **외측 말의 앞선 진입에는 내측 상대의 초반기록과의 차이가 중요하다. 다만 외측에서 빠르게 앞선을 잡으면 언제나 종반이 처진다는 결과는 확인하지 못했다.** 2026년에는 외측 앞선 말의 종반 저하 신호가 나타났으나 이전 두 해와 합산에서는 불확실했다. 게이트 일괄 감점이나 새 모델 채택은 하지 않는다.

## 자료와 정의

서울·부산 {c['races']:,}경주 {c['runners']:,}출전, 2024-01-01~2026-09-20. 2026은 부분연도다. 연도별 경주수는 1,774/1,758/1,295다. 기존 능력모델 검증4,799경주와 필터가 다른 **관측 전개 자료4,827경주**이며 모델 적중률 비교가 아니다. 통과조 유효 출전은 {c['role_valid']:,}개다. 원자료는2018년부터, 실제 최근5슬롯 구성에 사용한 모든 출전 이력은2010년부터다.

내/외측은 실제 출전한 말의 게이트 번호 순서 중 첫/마지막1/3이다. 원 번호의 결번을 보존하고 '내측 상대'는 자신보다 작은 게이트 번호의 말 전체다. **게이트 위치는 실제 주행 내·외측 경로가 아니다.** S1F 공식 첫 통과조를 '앞선'으로 표기한다. 첫 조에 여러 말이 있을 수 있어 단독 선행 확률이 아니다. 나머지 조의 평균 상대위치≤1/3은선입,≤2/3은중위,그외후미다.

초반200m, G3F마지막600m, G1F마지막200m는 초 단위 기록이다. s1f/g3f/g1f 통과착순 숫자를 시간으로 사용하지 않았다. G1F는G3F에 포함되므로 두 독립 손실을 합산하지 않는다.

## 경주 전에 비교할 수 있는 초반 기록

각 말 T−2일까지730일 내 최근 **실제5출전 슬롯** 중 이번과 동일거리 초반기록이 최소2개 있을 때 그 평균을 쓴다. 관측된 기록만 찾아 과거5개를 채우지 않는다. 자기 기록과 내측의 가장 빠른 평균을 비교하며, 내측 최소3두·80% 이상 이력 확보 조건을 요구했다. 외측 전체18,545출전 중 엄격한 사전 비교 가능 표본은 **1,413출전**이다. 신마·거리 변경·기록 부족이 배제되어 전체 외측 말에 그대로 일반화할 수 없다.

gap=내측 가장 빠른 평균−자신의 평균. 양수면 자신이 더 빠르다. faster_ge_0.2=0.2초이상빠름, faster_0_to_0.2=0초초과0.2초미만빠름, tie_or_slower_le_0.2=같거나0.2초이내느림, slower_gt_0.2=0.2초초과느림이다. 아래는 비율(0~1)이다.

{table(prior)}

앞선 진입률은68.57%(35출전),59.86%(142),32.30%(322),11.16%(914) 순서다. 가장 빠른 집단35개는 특히 소표본이다. 거의 비슷한 기록이면 선입도17.08%지만 앞선32.30%,중위31.37%,후미19.25%로 다양했다. 내측보다0.2초초과느리면 중위31.84%·후미48.03%였다. **빠르지 않으면 보통 선입이라는 일반화는 지지되지 않는다.** 서울1200m의 근접/느린 집단 앞선24.78/7.77%,부산1200m38.78/12.08%,부산1800m43.18/16.87% 등 지역·거리에 따라서도 달랐다. 상세 표는 탐색 기술통계이며 보정계수로 채택하지 않는다.

과거 원시 초반 평균은 함수율·계절·전개 변화가 남는다. 이번 연구는 게이트 효과를 먼저 제거하지 않고 비교했으며, 기존 연구의 보정 기록이나 능력 확률로 이 표를 오인하면 안 된다.

## 실제 그날 초반기록과 위치

동일한 계산을 당일 실제 초반기록으로 하면 다음과 같다.

{table(actual)}

내측보다 실제로0.2초이상빠르면 첫 조98.01%,0.1초빠르면94.81%였다. 그러나 기록과 통과조가 같은200m에서 관측된 결과여서 상당 부분 기계적 관계다. **이98%를 경주 전 선행 예측 정확도로 쓸 수 없다.** 200m 이후 코너까지의 자리 변화도 이 표에서 직접 관측하지 않았다.

## 외측에서 앞선을 잡았을 때 종반

같은 경주에 내·외측 말이 모두 첫 조로 들어간1,724경주에서, 외측 첫 조 말들의 평균 종반초−내측 첫 조 말들의 평균 종반초를 계산했다. 양수면 외측이 느리다. 경주별 동일 가중치이며 경주일 군집2,000회bootstrap95%구간이다.

{table(pair)}

전체 G3F+0.0558초[-0.0480,+0.1648],G1F+0.0338초[-0.0222,+0.0899]로0을 포함한다. 2026만 G3F+0.2097초[+0.0443,+0.3719],G1F+0.1144초[+0.0259,+0.1979]였다.2024·2025는 차이 불확실했고2025점추정은반대다. 거리별표도 별도보존했으며2026신호를모든거리의확정효과로확장하지않는다. 같은경주조건을맞춰도말능력·컨디션·자리선택차이는남는다.

## 평소보다 빠르게 쓴 초반인지 추가 확인

현재 초반의 '같은경주 자기제외 상대평균−자기시간'과, 동일거리 실제최근5슬롯의 평균을 비교했다. 상대우위가평소보다0.2초이상증가하면faster,±0.2초미만이면similar,0.2초이상감소하면slower다. 각 과거 평균은최소2개,구간별동료5두이상·80%관측확보조건이다. 이는생리적힘사용량이나기수의무리한의도가아닌**상대초반증가대리변수**다. 편성강도변화에도영향받는다. 과거기준에는첫조가아닌출전도포함된다.

종반악화초=과거동일거리평균상대우위−현재상대우위. 양수면평소보다상대적으로느려졌다. 외측faster638출전의G3F/G1F악화는+0.2697/+0.2173초,외측similar985출전은+0.2986/+0.1608초였다. 따라서외측에서초반을더빠르게썼다는조건만으로G3F까지일관되게더악화하지않았다. 두집단의G1F차이+0.0565초95%CI[-0.0171,+0.1348]도불확실했다.

'외측의faster−similar'에서'내측의faster−similar'를뺀이중차이는다음과같다. 양수면외측의추가악화신호다.

{table(con)}

합산G3F+0.0830초[-0.1190,+0.2842],G1F+0.0579초[-0.0535,+0.1693]. 모든연도의이중차이구간이0을포함했다.2026의faster끼리외측−내측차이는G3F+0.3999초,G1F+0.2148초였지만,외측의일반적저하와초반추가소모를분리하는이중차이는확정되지않았다.

말·경주고정효과를함께적용한보조회귀도새증거를주지못했다. 반복비교가가능한표본은3,703중826출전,잔여자유도152로급감했다. 연도별유효표본77/220/58,자유도12/29/5라서불안정하다. 외측×초반증가계수의합산95%구간도G3F[-1.646,+2.290],G1F[-0.915,+1.361]로매우넓었다. 이러한회귀를손실보정계수로사용하지않는다.

## 모델에 연결한다면

먼저검증할입력은게이트번호단독보다①내측최고초반기록과의사전차이②내측의빠른말수와기록관측수③앞선/선입진입확률④같은과거출전에서외측·빠른초반뒤G3F/G1F유지경험및표본수다. 당일실제초반기록은경주전입력에넣지않는다. 과거원시평균의주로차이를줄인버전과결측지원까지시간순검증해야한다. **이번연구에서는새능력모델학습0개,운영변경0개,확률보정채택0개**다.

## 검증과 재현

`run.py`→`verify.py`→`contrasts.py`→`report.py`→`finalize_inventory.py`. 최초보조회귀의반복투영이수렴하지않아희소최소제곱과수렴검증·단일관측제거·자유도보정으로교체했다. 질문·임계값·기간을바꾸지않았으며해시변경을`implementation_amendment.json`에남겼다.180개과거슬롯표본/그중평가66개과거평균,120개게이트·상대기록을독립재검산했다. 원자료·운영레지스트리·선택22입력·이전미래검증계약해시불변이다. 로컬자료만사용했고DB접근/외부수집/제주분석은없다.

주요파일: [통과조분포](outputs/outer_roles.csv),[동일경주앞선비교](outputs/same_race_front_pairs.csv),[자기평소대비변화](outputs/front_finish_changes.csv),[공동부트스트랩대조](outputs/finish_contrasts.csv),[고정효과](outputs/fixed_effects.json),[검증](outputs/verification.json),[용량명세](outputs/artifact_inventory.json).
'''
    assert not (e.HERE/'README.md').exists()
    (e.HERE/'README.md').write_text(body)
    pub='''# 외측 말은 내측보다 얼마나 빨라야 앞선을 잡는가

2026-10-11. 연구 관측 결과이며 운영 반영 아님.

무엇을 알았는가: 서울·부산2024~2026-09-20의4,827경주를확인했다. 엄격한과거기록비교가가능한외측1,413출전에서는내측최고초반평균보다0.2초이상빠른말의첫조진입68.57%(35개),0~0.2초빠르면59.86%(142),같거나0.2초이내느리면32.30%(322),더느리면11.16%(914)였다. 기록이빠르지않으면선입으로만가는것은아니며중·후미도많았다.

기록을어떻게읽는가: 경주T−2일까지실제최근5슬롯중동일거리초반200m기록최소2개의평균이다. 내측상대최소3두·80%이력이있을때만비교한다. 첫조는단독선행과다르다. 가장빠른집단35개는소표본이고전체외측18,545중1,413만비교가능하므로일반화에주의해야한다. 게이트위치는실제주행경로가아니다.

사례: 같은경주내·외측말이모두첫조에진입한1,724경주에서외측G3F는평균0.056초,G1F0.034초느렸지만95%구간은0을포함했다.2026만각0.210/0.114초느린신호가있었고2024·2025에반복되지않았다. 자기평소보다초반상대우위가0.2초이상늘어난경우까지확인했지만,외측특유의추가종반저하를확정하지못했다.

어디까지적용되는가: 내측경쟁마와의초반차이는전개입력연구후보로가치가있다. 외측이면일괄감점하거나무리한선행의인과효과로해석할근거는부족하다. 당일초반98%첫조관계는같은지점의관측관계라사전예측정확도가아니다. 함수율·계절이남는과거원시평균,컨디션·실제경로·전술의미관측한계가있다. 새모델·확률보정은채택하지않았다.

[전체보고서](README.md) · [거리별·연도별통과조](outputs/outer_roles.csv) · [종반비교와불확실성](outputs/same_race_front_pairs.csv)
'''
    (e.HERE/'PUBLICATION.md').write_text(pub)
    central=e.R/'conclusions/45_OUTER_GATE_EARLY_COST.md'
    assert not central.exists()
    central.write_text(pub.replace('(README.md)',f'(../{e.HERE.name}/README.md)').replace('(outputs/',f'(../{e.HERE.name}/outputs/'))
    marker='<!-- outer_gate_early_cost_v1_20261011 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=e.R/name
        link=f'{e.HERE.name}/README.md' if name=='README.md' else central.name
        with path.open('a') as f:
            f.write(f'\n\n{marker}\n[外측게이트·내측초반차이·종반저하]({link}):4,827경주,사전비교외측1,413출전.내측최고기록우위별첫조68.57/59.86/32.30/11.16%.동일앞선1,724경주종반차이합산불확실/2026만외측저하,평소대비추가소모인과미확인.운영유지.\n')
    e.save(e.OUT/'completion.json',dict(status='complete_verified_published_locally',races=c['races'],
         new_ability_models=0,production_changed=False,future_contract_changed=False,database_access=False,network_access=False))
    manifest=e.R/'conclusions/source_manifest.json'
    m=json.loads(manifest.read_text())
    own=[p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts and p.name not in ['publication_before.json','artifact_inventory.json']]
    for p in own+[central]+[e.R/n for n in ['README.md','conclusions/README.md','conclusions/SOURCES.md']]:
        key=str(p.relative_to(e.ROOT))
        m['sources']=[r for r in m['sources'] if r['path']!=key]
        m['sources'].append(dict(path=key,sha256=e.sha(p),bytes=p.stat().st_size))
    e.save(manifest,m)
    e.check()
    print('Published conclusion45 locally')


if __name__=='__main__':
    main()
