"""Local research report, source index, and bounded artifact inventory."""
import json
import pandas as pd
import analyze as a


def main():
    v=json.loads((a.OUT/'verification.json').read_text());assert v['status']=='passed'
    s=pd.read_csv(a.OUT/'summary.csv');b=pd.read_csv(a.OUT/'paired_differences.csv')
    r=pd.read_parquet(a.OUT/'race_results.parquet')
    names={'operating_A_v5':'운영 A v5 계열','full103':'이전 full103','state_gbm118':'연구 기준 state_gbm118',
        'state_joint118':'공동착순 신경망','axis_failure_selected':'축 이탈 위험 보조안'}
    def results(years):
        lines=['| 모델 | 연도 | 경주 | 축6 적중 | 공동6 적중 | 축6 수익률 | 공동6 수익률 |',
            '|---|---|---:|---:|---:|---:|---:|']
        for model,label in names.items():
            for year in years:
                q=s[s.model.eq(model)&s.subgroup.eq(year)].set_index('policy');old=q.loc['axis_six'];new=q.loc['joint_top6']
                lines.append(f'| {label} | {"전체" if year=="all" else year} | {int(old.races):,} | {old.hit_rate:.2%} ({int(old.hits):,}) | {new.hit_rate:.2%} ({int(new.hits):,}) | {old.roi:.2%} | {new.roi:.2%} |')
        return '\n'.join(lines)
    changes=[]
    for model,label in names.items():
        g=r[r.model.eq(model)];gained=g[~g.axis_six_hit&g.joint_top6_hit];lost=g[g.axis_six_hit&~g.joint_top6_hit]
        changes.append(dict(model=model,gained=len(gained),lost=len(lost),
            gained_mean=float(gained.dividend.mean()),lost_mean=float(lost.dividend.mean()),
            gained_return_krw=round(float(gained.dividend.sum()*1000),6),lost_return_krw=round(float(lost.dividend.sum()*1000),6)))
    pd.DataFrame(changes).to_csv(a.OUT/'gain_loss_summary.csv',index=False)
    text='\n'.join([
        '# 같은6조합·같은구매액: 축 고정과 공동확률 상위6개', '',
        '2026-10-25 · 연구58M · 신규 학습0 · 운영 변경 없음 · 동일명단4,133경주.', '',
        '**공동확률 상위6장은 모든 비교 모델에서 적중률을1.21~1.72%p 높였다. 수익률은 운영 A 계열에서−23.37→−20.81%로 나아졌지만 연구 기준은−21.92→−24.57%로 낮아졌다. 모델별 ROI 차이의95%구간은 모두0을 포함해 안정적 수익 우위는 미확정이다.**', '',
        '## 비교 조건', '',
        '앞선 연구와 같은 서울·부산4,133경주,2024-01-05~2026-09-13을 유지했다. 연도별 경주 수는1,530/1,522/1,081이며2026년은 부분연도다. 매경주 정확히6개 고유 삼복티켓을 장당1,000원 구매한다. 두 정책의 연도별·전체 구매액이 완전히 같다. 전체 구매액은 정책별24,798,000원이다. 확정배당은 이미 검증한 이전 정산 투영을 재사용하며 누락은0이다.', '',
        '- 축 고정6장: 각 모델의 기존 Top3 주변확률1위 축과 차순위4두의 모든 짝을 유지했다.',
        '- 공동확률 상위6장: 동일 모델이 부여한 모든 삼복집합 확률에서 상위6개를 골랐다. 축·후보5두 제한을 풀었으며 배당을 보고 고르지 않았다.',
        '- 현재모델의 학습자료에 과거경주를 다시 추론해 얻은 인샘플 성적이 아니다. 운영은 시기별 v5 rolling_all 계열의 보존 예측, 연구 후보는 해당연도 이전 자료로 동결된 모형이다. 서로 다른 운영A/B 모형으로 선택법을 바꾼 차이는 이번 효과로 섞지 않았다.', '',
        '수익률은(환급−구매)/구매다. 공시 확정배당을 넣은 세전 가상정산이며 실제 계좌 거래, 개인 기타소득세·절사·풀 변동은 반영하지 않았다. 구매액이 같으므로 이번 순수익률 개선/악화는 환급액 차이와 같은 방향이다.', '',
        '## 전체 결과', '',results(['all']), '',
        '## 연도별 모든 모델', '',results(['2024','2025','2026']), '',
        '## 운영과 연구 기준의 금액 차이', '',
        '| 모델 | 방식 | 구매액 | 환급액 | 순손익 |', '|---|---|---:|---:|---:|',
        '| 운영 A 계열 | 축6 | 24,798,000원 | 19,001,900원 | −5,796,100원 |',
        '| 운영 A 계열 | 공동6 | 24,798,000원 | 19,636,500원 | −5,161,500원 |',
        '| 연구 기준 | 축6 | 24,798,000원 | 19,362,000원 | −5,436,000원 |',
        '| 연구 기준 | 공동6 | 24,798,000원 | 18,706,300원 | −6,091,700원 |', '',
        '운영 계열은 세 연도 모두 적중률과 수익률의 점추정이 나아졌고 전체 환급이634,600원 증가했다. 연구 기준은2024년에만 ROI가 개선됐고2025·2026년에는 악화해 전체 환급이655,700원 감소했다. 공통 예산 아래 결과지만 각 모델의 확률·학습 목표·자료와 학습 일정이 달라 한 알고리즘의 인과효과로 해석하지 않는다.', '',
        '## 더 맞혔는데 환급이 줄어든 이유', '',
        '연구 기준은 새로210경주를 맞히고 기존145경주를 놓쳐 순증65경주였다. 새 적중 평균배당은21.68배, 놓친 적중은35.91배다. 새 적중 환급4,551,800원보다 잃은 환급5,207,500원이 커서 수익이 낮아졌다. 전체 적중배당 평균도 축6의17.27배에서 공동6의15.77배로 낮아졌다.', '',
        '운영 계열은 새 적중197경주·기존 적중상실142경주, 새 적중 평균23.81배·놓친 적중28.56배였다. 새 환급4,690,600원이 잃은 환급4,056,000원보다 커서 전체 환급이 증가했다. 적중 수와 환급을 함께 평가해야 하는 이유다. 다른 세 모델도 같은 진단을 CSV에 보관했다.', '',
        '공동6장은 모델 확률 기준으로6개 사건의 합을 최대화한다. 이것은 확률×배당을 최대화하는 목표와 다르다. 이번에는 현재경주 확정배당을 선택에 넣거나 결과를 본 뒤 배당조건을 추가하지 않았다.', '',
        '## 어떤 조합으로 바뀌었나', '',
        '연구 기준은3,736/4,133경주에서 티켓이 바뀌었고 평균1.50장만 교체됐다. 선택한 말의 합집합은 평균6.22두였다. 공동6장 중 기존축을 빼는 티켓은 평균0.285장으로, 대부분의 티켓은 여전히 원래축을 포함했다. 축 없는 조합을 무조건3장씩 넣는 정책을 시험한 것이 아니며, 후보 폭과 조합 확률을 함께 조정한 효과다.', '',
        '## 분포 재현과 운영A 역산의 의미', '',
        'full103/state_gbm은 기존 raw score와 전년도 온도로q(T)∝exp(세점수합/온도)를 재현했다. 신경망은 기존 safetensors·encoding·온도를 그대로 사용해 모든1→2→3순서의 확률을 추론한 뒤 같은 삼복집합의6개 순서를 합산했다. 축위험 보조는 기존축 포함/미포함 사건의 질량을 기존 lambda대로 재가중했다. 말별 입상확률을 곱하지 않았다.', '',
        '운영A의 과거 가중치는 정리됐지만 모든 말의A주변확률은 보존돼 있다. 일반적인 주변확률만으로 임의 공동분포를 결정할 수는 없다. 이번에는 원래운영A가 알려진 가산형 고정3두집합 모형이라는 코드계약을 확인한 뒤, 그 모형 안에서 log-partition의 gradient가 저장주변확률과 일치하는 에너지를 Newton법으로 복원했다. 이는 현재정답·배당에 맞춘 새모델 학습이 아니다. 운영B의 별도 삼복분포를 복원하거나 비교한 것으로 표현하지 않는다.', '',
        f'합성18개 역산에서 원공동분포를 복원했고 실제4,133경주를 서로 다른 초기값2개로 풀어 상위6개가 전부 일치했다. 실제주변확률 최대오차는{v["operating_inverse_max_error"]:.3g}였다. 마번순열과 균등확률 동점처리도 검사했다. 운영 재구성 에너지는 작은 parquet로만 보존했다.', '',
        '## 불확실성', '',
        '날짜403개 paired bootstrap2,000회다. 연구 기준 적중차이+1.57%p의95%구간은+0.66~+2.48%p, 운영은+1.33%p에+0.44~+2.21%p였다. 이 개발표본에서는 적중 증가의 근거가 있지만 새 미사용 기간의 확증으로 볼 수 없다.', '',
        '운영 ROI차이+2.56%p의95%구간은−2.43~+7.94%p, 연구 기준−2.64%p는−8.97~+3.39%p다. 다른 모델도 ROI 구간이0을 포함했다. 지표별 구간이며 다중비교·같은 말의 장기간 관련성을 완전히 조정하지 않았다. 최고 환급1경주를 제외한 민감도도 모든 표에 보존했다. 운영 공동6의 해당ROI는−24.53%, 연구 공동6은−25.40%다. 사후고배당제외를 실행가능한정책으로 주장하지 않는다.', '',
        '## 검증과 판단', '',
        f'경주·모델{v["model_races"]:,}개와 티켓{v["tickets"]:,}장을 확인했다. 기존 축6장의 적중/환급 전수와30개집계행, 독립Decimal정산60행이 일치했다. 별도식으로전체공동분포와상위6개를검산한{v["independent_full_joint_top6_checks"]:,}건, 신경망독립순서합산18경주를 포함한다. 주추론에서는 신경망전체주변확률도기존저장값과대조했다. 축위험분포의주변확률도원래조건부분포와독립대조했다.', '',
        '같은말두수를사용하는제약과같은티켓수를사용하는제약은다르다.자유6장은후보말의범위를넓힐수있지만돈은더쓰지않았다.이번결론은적중목표의유효한비교후보를확보했다는것이며안정적수익·흑자·운영승격을확인했다는뜻은아니다.모델과정책을경기전에봉인한새기간검증이필요하다.운영변경·신규학습·튜닝·DB쓰기·신규배당수집은하지않았다.', '',
        '기존 모집단의 입상동착 제외, 명단·부담중량의 당시 공개시각 미확인,2026부분연도와 반복개발기간 한계는 유지한다. 전체삼복/순서분포나원본DB/피처/모델은 복사하지 않고 선택티켓·최소 역산값·집계만 보존했다.', '',
        '[계획](PLAN.md) · [재현](analyze.py) · [독립검산](verify.py) · [전체표](outputs/summary.csv) · [차이구간](outputs/paired_differences.csv) · [새적중/상실](outputs/gain_loss_summary.csv) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)', ''])
    (a.HERE/'README.md').write_text(text)
    (a.HERE/'PUBLICATION.md').write_text('# 게시 준비: 같은6장, 축 고정과 공동확률 상위\n\n같은4,133경주·장당1,000원으로비교했다.운영A는적중26.74→28.07%,세전ROI−23.37→−20.81%였다.연구기준은적중27.12→28.70%지만ROI−21.92→−24.57%로낮아졌다.연구기준새적중210경주평균21.68배,놓친145경주평균35.91배여서더맞혀도환급은줄었다.적중은모든비교모델에서증가했으나ROI우위는미확정이다.새학습·운영변경·공개게시없음.\n')
    central=a.R/'conclusions/58M_TRIO_JOINT_TOP6.md'
    central.write_text('# 같은6장: 축 고정과 공동확률 상위\n\n2026-10-25 · 연구58M · 운영 미변경.\n\n'+results(['all'])+'\n\n연구기준새적중210·상실145로적중은늘었으나놓친배당이더높아환급655,700원감소했다.운영은세연도모두점추정이개선돼환급634,600원증가했지만전체ROI차이95%구간은0을포함했다.확률합최대와환급최대는다른목표다.\n\n[원문](../20261025_trio_joint_top6_v1/README.md) · [연도별전체](../20261025_trio_joint_top6_v1/outputs/summary.csv) · [검증](../20261025_trio_joint_top6_v1/outputs/verification.json)\n')
    marker='<!-- trio_joint_top6_20261025 -->'
    for path,line in [(a.R/'README.md','[연구58M 축6·공동확률상위6](20261025_trio_joint_top6_v1/README.md):같은예산에서모든모델적중+1.21~1.72%p.운영ROI−23.37→−20.81%,연구−21.92→−24.57%;수익우위미확정.'),
        (a.R/'conclusions/README.md','[연구58M 같은6장 공동확률선택](58M_TRIO_JOINT_TOP6.md):적중은증가했으나수익방향은모델별상이,운영도확정우위아님.'),
        (a.R/'conclusions/SOURCES.md','[연구58M](58M_TRIO_JOINT_TOP6.md) · [원문](../20261025_trio_joint_top6_v1/README.md) · [분포재현/정산검증](../20261025_trio_joint_top6_v1/outputs/verification.json).기존5모델분포에서동일6개티켓만선택,새학습0.')]:
        old=path.read_text()
        if marker not in old:path.write_text(old+'\n\n'+marker+'\n'+line+'\n')
    sm=a.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    paths=[a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'verify.py',a.OUT/'summary.csv',a.OUT/'verification.json',central]
    additions={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inv=a.OUT/'artifact_inventory.json'
    if not inv.exists():a.save(inv,{})
    before=json.loads((a.OUT/'publication_before.json').read_text());log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(20):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[central])
        total=sum(p.stat().st_size for p in files)
        line=f'| 2026-10-25 | 58M 축6·공동확률상위6 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_trio_joint_top6_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58M 축6·공동확률상위6' not in x)+'\n'+line+'\n')
        modified=[dict(path=p,before_bytes=v['bytes'],after_bytes=(a.ROOT/p).stat().st_size,delta_bytes=(a.ROOT/p).stat().st_size-v['bytes']) for p,v in before.items()]
        obj=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(a.ROOT)),bytes=p.stat().st_size,sha256=None if p==inv else a.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),new_models=0)
        old=inv.read_text();a.save(inv,obj)
        if old==inv.read_text():break
    else:raise AssertionError('Inventory convergence failed')
    assert sum(p.stat().st_size for p in files)==obj['new_bytes']<5_000_000
    print(json.dumps({k:v for k,v in obj.items() if k not in ['files','modified_files']},indent=2))


if __name__=='__main__':main()
