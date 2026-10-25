"""Compact local report and self-inclusive storage inventory."""
import json
import pandas as pd
import analyze as a


def main():
    v=json.loads((a.OUT/'verification.json').read_text());assert v['status']=='passed'
    s=pd.read_csv(a.OUT/'summary.csv');d=pd.read_csv(a.OUT/'risk_diagnostics.csv')
    main=s[s.scope.eq('identical_roster')]
    policy_names={'always_six':'항상6장','always_ten':'항상10장','risk_model':'학습 위험 조건부6/10장','risk_simple':'단순 위험 조건부6/10장'}
    def table(model):
        lines=['| 연도 | 정책 | 경주 | 10장 구매 | 적중 | 적중률 | 구매액(원) | 환급액(원) | 순손익(원) | 순수익률 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for y in ['2024','2025','2026','all']:
            for policy in a.policies(model):
                q=main[main.model.eq(model)&main.subgroup.eq(y)&main.policy.eq(policy)].iloc[0]
                lines.append(f'| {"전체" if y=="all" else y} | {policy_names[policy]} | {int(q.races):,} | {int(q.extra_bought_races):,} | {int(q.hits):,} | {q.hit_rate:.2%} | {q.stake_krw:,.0f} | {q.return_krw:,.0f} | {q.net_krw:,.0f} | {q.roi:.2%} |')
        return '\n'.join(lines)
    def short_table(model,policy):
        lines=['| 연도 | 10장 구매 경주 | 기본6장 적중률 | 조건부 적중률 | 기본6장 순수익률 | 조건부 순수익률 |',
            '|---|---:|---:|---:|---:|---:|']
        for y in ['2024','2025','2026','all']:
            q=main[main.model.eq(model)&main.subgroup.eq(y)].set_index('policy');b=q.loc['always_six'];z=q.loc[policy]
            lines.append(f'| {"전체" if y=="all" else y} | {int(z.extra_bought_races)} | {b.hit_rate:.2%} | {z.hit_rate:.2%} | {b.roi:.2%} | {z.roi:.2%} |')
        return '\n'.join(lines)
    text='\n'.join([
        '# 축 이탈 위험이 높은 경주에만 삼복4장 추가', '',
        '2026-10-25 · 연구58L · 기존 말5두·축·배당 고정 · 신규 학습0 · 운영 미변경.', '',
        '**연구 기준에서 조건부 구매는 적중률27.12→28.72%, 세전 순수익률−21.92→−20.82%였다. 하지만 추가 구매326.4만원에 환급285.68만원으로40.72만원을 더 잃었다.2025년은 수익률도 악화했고, 전체 ROI 차이의95%구간은0을 포함했다. 안정적인 수익 개선이나 정책 채택 근거는 부족하다.**', '',
        '## 고정한 규칙', '',
        'state_gbm118이 원래 고른 축을 유지했다. 이 축의3착 밖 위험을 학습한58G model_risk가 전년도 위험 예측80백분위 이상일 때만 축 없는4장을 추가한다. 나머지 경주는 축 고정6장이다. 평가할 해의 정답·배당으로 문턱을 고르지 않았다.2024/2025/2026 문턱은 각각2023/2024/2025 자료로 기존 연구에서 정한 값을 재현했다. 서울·부산의 문턱을 따로 사용했으며 대략44.3~49.9%의 위험값이다. 현재 평가자료 상위20%를 사후 골랐다는 뜻은 아니다.', '',
        '별도 대조군은1−원래 축의Top3확률과 그 값의 전년도80백분위다. 운영A는 축이 다른 만큼 state_gbm 축에 학습한 위험 모형을 전용하지 않고, 운영 저장 예측의 전년도 단순 위험만 사용했다. 새 축 교체, 새 말 선정, 거리·등급별 사후 문턱 탐색, 새 배당 필터는 없다.2024~2026은 이미 반복 사용한 개발기간이므로 시간분리를 지켰어도 새 미사용 시험은 아니다.', '',
        '## 동일한 평가와 금액', '',
        '주 비교는 명단 동일4,133경주,2024-01-05~2026-09-13이다.2024년1,530·2025년1,522·2026년1,081경주며2026은 부분연도다. 모든 경주에서 최소6장을 구매한다. 고위험 경주만 따로 분모로 삼아 전체 적중률이 오른 것처럼 표현하지 않았다. 같은 조합당1,000원으로 매경주6,000원 또는10,000원을 사는 공시 확정배당 기준 세전 가상정산이다. ROI는 전체 환급/전체 구매−1이며 경주별 ROI 단순평균을 쓰지 않았다. 개인 기타소득세·절사·배당풀 영향은 앞선 정산처럼 제외했다.', '',
        '## 주 결과: 학습한 위험으로 선택', '',short_table('state_gbm118','risk_model'), '',
        '전체4,133경주 중816경주(19.74%)만10장으로 늘렸다. 평균 구매장수는6.790장이다. 적중은1,121→1,187경주로66경주 증가했다. 항상10장일 때의1,407적중(34.04%)보다는 적지만 구매액도 훨씬 작다. 예산을 늘려 적중을 추가한 정책 효과이며 모델의 말 순위 예측 자체가 개선된 것은 아니다.', '',
        '| 방식 | 구매액 | 환급액 | 순손익 | 순수익률 |', '|---|---:|---:|---:|---:|',
        '| 항상6장 | 24,798,000원 | 19,362,000원 | −5,436,000원 | −21.92% |',
        '| 위험할 때만10장 | 28,062,000원 | 22,218,800원 | −5,843,200원 | −20.82% |',
        '| 항상10장 | 41,330,000원 | 31,398,700원 | −9,931,300원 | −24.03% |', '',
        '조건부 추가4장만 보면3,264,000원 구매·2,856,800원 환급·407,200원 손실, ROI−12.48%다. 전체를 무조건 추가할 때의 추가4장 ROI−27.19%보다 나았지만 원금 회수에는 못 미쳤다. 추가 적중66회의 배당 평균43.28배·중앙값27.50배였다. 손실률이 낮아진 것은 추가분의 손실률이 기본6장보다 작았기 때문이고, 총손실액이 줄었다는 뜻은 아니다.', '',
        '연도별 추가4장 손익은2024년+9,100원(ROI+0.74%),2025년−458,100원(−34.60%),2026년+41,800원(+5.87%)였다. 세 연도 중 두 해는 추가분이 소폭 흑자였지만2025년 손실을 상쇄하지 못했다. 이 결과를 보고2025년만 제외하는 정책은 만들지 않았다.', '',
        '## 위험은 구분했는가', '',
        '| 학습 위험 구분 | 경주 | 실제 축 이탈률 | 축 없는4장 적중사건 비율 | 그4장을 모두 살 때 ROI |',
        '|---|---:|---:|---:|---:|',
        '| 고위험 | 816 | 52.94% | 8.09% | −12.48% |',
        '| 그 외 | 3,317 | 33.28% | 6.63% | −30.81% |', '',
        '축 이탈은 구분했지만 축이 빠진 뒤 나머지4두 중3두가 모두 입상할 가능성의 증가는 제한적이었다. 고위험에서 실제 축이 빠진432경주 중 추가4장이 구제한 것은66경주(15.28%)다. 축 실패 위험과 대체3두 조합의 가치가 다른 예측 목표임을 보여주는 설명이며 새로운 규칙의 검증은 아니다.', '',
        '## 단순 위험과 운영 모델', '',
        '연구 기준의 단순 위험은853경주에서 추가해1,190적중·28.79%, ROI−20.82%였다. 학습 위험816경주·1,187적중·28.72%, ROI−20.82%와 매우 비슷하다. 구매액이 같지 않아 위험모형만의 인과 효과로 해석하지 않으며, 복잡한 위험모형이 더 낫다는 근거는 이번 결과에 없다.', '',
        short_table('operating_A_v5','risk_simple'), '',
        '운영 단순 위험은719경주(17.40%)에서 추가했다. 전체 ROI−23.37→−22.24%지만 추가구매2,876,000원에 환급2,517,900원, 추가손실358,100원이다.2025년에는운영에서도ROI가악화했다. 운영은 현재와 같은v5 rolling_all 계열의 당시 저장 예측이며, 현재2026H2 가중치를 과거학습구간에 적용한 성적이 아니다.', '',
        '## 불확실성과 판단', '',
        '날짜403개를paired bootstrap2,000회 재표집했다. 연구 기준의 조건부−항상6장 ROI 차이+1.10%p의95%구간은−1.96~+4.41%p다. 조건부−항상10장은+3.21%p,−1.49~+7.91%p다. 운영 단순 위험−항상6장은+1.14%p,−3.16~+7.49%p다. 모두0을 포함해 일관된 미래 개선으로 단정할 수 없다. 연도별 구간도 결과표에 모두 남겼으며 다중비교·동일 말의 장기 상관은 완전히 반영하지 못한다.', '',
        '현재 조건은 적중 수와 비용 비율 면에서 무조건10장보다 보수적인 중간 선택이지만, 이 표본에서 추가금 자체가 손실이므로 흑자 전략이나 운영 승격으로 채택하지 않는다. 위험 문턱을 더 탐색해 좋은 구간만 고르는 추가 실험은 하지 않았다. 새 기간에서 예측·문턱·티켓을 경기 전에 고정한 확인이 필요하다.', '',
        '## 전체 금액표: 연구 기준', '',table('state_gbm118'), '',
        '## 전체 금액표: 운영 계열', '',table('operating_A_v5'), '',
        '## 검증과 범위', '',
        f'전년도 문턱12개 분할, 저장 경고값, 기존 state_gbm 축을 재현했다. 독립 Decimal 금액검산{v["summary_rows_decimal_checked"]}행, 직접6/10장 열거{v["purchased_ticket_policy_records_enumerated"]:,}개 경주·정책 기록, 앞선 항상6/10장 집계{v["prior_six_ten_summaries_matched"]}행을 확인했다. 현재정답·배당변조로 위험판정이 바뀌지 않았고, 출처{v["protected_source_files_unchanged"]}개 해시를 확인했다. 배당은 이전 연구에서 모든 대상경주에 확보한 값을 재사용했으며 새 DB조회·쓰기·모델학습·배포는 없다.', '',
        '연구 기준의4,769경주 민감도와4,799경주 전체는 CSV의별도scope에 남겼다. 운영 단순 위험은 원래 축에 연결되므로 취소마 제거로 축이 달라질 수 있는 경주에는 전용하지 않았다. 운영 보조범위를 제한한 이유는[SCOPE_NOTE](SCOPE_NOTE.md)에 있다. 이전 연구의 입상동착 제외·당시 명단/부담중량 공시시각 미확인·사후 원천과 학습기간 차이도 유지한다.', '',
        '[계획](PLAN.md) · [재현](analyze.py) · [독립 검산](verify.py) · [전체 집계](outputs/summary.csv) · [위험별 진단](outputs/risk_diagnostics.csv) · [차이 구간](outputs/paired_differences.csv) · [문턱](outputs/thresholds.json) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)', ''])
    (a.HERE/'README.md').write_text(text)
    (a.HERE/'PUBLICATION.md').write_text('# 게시 준비: 축 이탈 위험에 따른 추가4장\n\n전년도80백분위위험문턱으로4,133경주중816경주에만추가4장을구매했다.연구기준적중률27.12→28.72%,세전ROI−21.92→−20.82%였다.그러나추가326.4만원에환급285.68만원으로40.72만원의추가손실이났다.2025년은ROI도악화했고전체차이95%구간은0을포함했다.단순위험과도성능이비슷해정책채택근거는부족하다.신규학습0·운영미변경·미게시.\n')
    central=a.R/'conclusions/58L_RISK_GATED_TRIO.md'
    central.write_text('# 축 이탈 위험이 높을 때만 삼복4장 추가\n\n2026-10-25 · 연구58L · 운영 미변경.\n\n'+short_table('state_gbm118','risk_model')+'\n\n전년도80백분위문턱으로816경주에만추가했다.추가구매3,264,000원·환급2,856,800원·손실407,200원이다.전체ROI차이+1.10%p의95%구간−1.96~+4.41%p로0을포함하고2025년에는악화했다.위험분리는됐지만흑자나안정적우위는확인하지못했다.\n\n[원문](../20261025_risk_gated_trio_v1/README.md) · [전체 표](../20261025_risk_gated_trio_v1/outputs/summary.csv) · [검증](../20261025_risk_gated_trio_v1/outputs/verification.json)\n')
    marker='<!-- risk_gated_trio_20261025 -->'
    for path,line in [(a.R/'README.md','[연구58L 축 위험 조건부 삼복6/10장](20261025_risk_gated_trio_v1/README.md): 연구기준적중27.12→28.72%·ROI−21.92→−20.82%,추가손실40.72만원·2025악화·우위미확정.'),
        (a.R/'conclusions/README.md','[연구58L 위험 조건부 삼복6/10장](58L_RISK_GATED_TRIO.md):816경주만추가,적중+66·추가손실40.72만원·개선불확실.'),
        (a.R/'conclusions/SOURCES.md','[연구58L](58L_RISK_GATED_TRIO.md) · [원문](../20261025_risk_gated_trio_v1/README.md) · [문턱](../20261025_risk_gated_trio_v1/outputs/thresholds.json) · [검증](../20261025_risk_gated_trio_v1/outputs/verification.json).58G의전년도위험문턱과58K배당을재사용해조건부구매를정산.')]:
        old=path.read_text()
        if marker not in old:path.write_text(old+'\n\n'+marker+'\n'+line+'\n')
    sm=a.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    paths=[a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'verify.py',a.OUT/'summary.csv',a.OUT/'thresholds.json',a.OUT/'verification.json',central]
    additions={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inv=a.OUT/'artifact_inventory.json'
    if not inv.exists():a.save(inv,{})
    before=json.loads((a.OUT/'publication_before.json').read_text());log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(20):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[central])
        total=sum(p.stat().st_size for p in files)
        line=f'| 2026-10-25 | 58L 위험 조건부 삼복6/10장 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_risk_gated_trio_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58L 위험 조건부 삼복6/10장' not in x)+'\n'+line+'\n')
        modified=[dict(path=p,before_bytes=v['bytes'],after_bytes=(a.ROOT/p).stat().st_size,delta_bytes=(a.ROOT/p).stat().st_size-v['bytes']) for p,v in before.items()]
        obj=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(a.ROOT)),bytes=p.stat().st_size,sha256=None if p==inv else a.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),new_models=0)
        old=inv.read_text();a.save(inv,obj)
        if old==inv.read_text():break
    else:raise AssertionError('Inventory convergence failed')
    assert sum(p.stat().st_size for p in files)==obj['new_bytes']<2_000_000
    print(json.dumps({k:v for k,v in obj.items() if k not in ['files','modified_files']},indent=2))


if __name__=='__main__':main()
