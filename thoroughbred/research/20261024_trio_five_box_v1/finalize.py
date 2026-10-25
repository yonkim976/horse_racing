"""Publish compact local notes, preserving original model artifacts."""
import json
import pandas as pd
import compare as c


def main():
    verification=json.loads((c.OUT/'verification.json').read_text())
    assert verification['status']=='passed'
    s=pd.read_csv(c.OUT/'summary.csv')
    names={'operating_A_v5':'운영 A v5 계열','full103':'이전 연구 full103',
        'state_gbm118':'연구 기준 state_gbm118','state_joint118':'공동착순 신경망',
        'axis_failure_selected':'축 이탈 위험 보조안'}
    def table(scope):
        lines=['| 모델 | 6장 적중 | 10장 적중 | 증가 | 추가 적중 경주 |',
            '|---|---:|---:|---:|---:|']
        a=s[s.scope.eq(scope)&s.subgroup.eq('all')].set_index('model')
        for model,label in names.items():
            r=a.loc[model]
            lines.append(f'| {label} | {r.six_rate:.2%} ({int(r.six_hits):,}) | {r.ten_rate:.2%} ({int(r.ten_hits):,}) | +{100*r.difference:.2f}%p | {int(r.extra_hits)} |')
        return '\n'.join(lines)
    content='\n'.join([
        '# 동일5두: 축 고정 삼복6장과 박스10장', '',
        '2026-10-24 · 연구58J · 기존58H의 선택5두·모델·모집단 고정 · 신규 학습0 · 운영 변경 없음.', '',
        '**입상3두 포착은 운영26.74→33.20%, 연구 기준27.12→34.04%로 약6~7%p 증가했다. 조합당 동일 금액이면 구매액은66.67% 증가한다. 적중 수의 상대 증가 약24~26%보다 비용 증가가 크며, 배당 없는 결과로 수익률을 판정할 수 없다.**', '',
        '## 무엇을 바꿨는가', '',
        '직전58H에서 고른 축A·상대B/C/D/E를 그대로 유지했다. 기존6장은 ABC/ABD/ABE/ACD/ACE/ADE, 추가4장은 BCD/BCE/BDE/CDE다. 추가4장이 축이 빠지고 상대4두 중3두가 모두 입상하는 경주를 구제한다. 모델의 말별 예측을 바꾸거나 더 좋은5두를 사후 고른 효과가 아니다. 최신 다른 세션의 후속 모델을 섞지 않았다.', '',
        '운영은 당시 v5 rolling_all 계열의 저장 예측, 연구 기준은 state_gbm118이며 신경망·축 이탈 위험 보조는 비교 후보다. 운영B의 자유 삼복확률 상위10장과도 다른 정책이다. 모든 말5두에서 C(5,3)=10장을 구매하는 사건이다.', '',
        '## 명단이 동일한4,133경주', '',
        '서울2,356·부산1,777경주, 2024-01-05~2026-09-13. 아래 숫자는 과거 경주에서 한 장 이상 맞힌 비율이다.', '',table('identical_roster'), '',
        '연구 기준의 추가286경주는 모두 원래 축이3착 밖으로 빠진 경주다. 축 실패1,536경주 중18.62%를 더 구제했다. 나머지는10장을 사더라도 실제 입상마 중 한 두 이상이 선택5두 밖에 있었다. 10장으로 늘려도 전체4,133경주 중2,726경주(65.96%)는 실패했다.', '',
        '## 비용과 적중 수를 함께 읽기', '',
        '연구 기준으로100경주당 적중은 약27.12→34.04경주, 약6.92경주 증가다. 조합당1,000원의 단순 계산이면 경주당 구매액6,000→10,000원이다. 적중 경주 수의 상대 증가는25.51%이고 구매액 증가는66.67%다.', '',
        '모든 경주에서 같은 장당 금액을 쓴다고 할 때 구매 티켓 중 적중 티켓 비율은 연구 기준4.52→3.40%로 약24.69% 감소한다. 추가4장의 적중 티켓 비율은286/(4,133×4)=약1.73%다. 동착 없는 이 모집단에서는 한 경주에 적중 삼복 티켓이 최대1장이어서 계산 가능하다. 이는 수량 효율이며 실제 배당을 포함한 수익률이나 손익분기 배당이 아니다. 같은 총예산이면10장의 장당 금액은6장 대비60%가 된다는 산술 관계만 말할 수 있다.', '',
        '축 없는4장이 적중할 때의 배당이 더 크거나 작을 수 있으므로 환급 합계와 수익률은 실제 배당을 조인해야 판정할 수 있다. 이번에는 배당 수집·조회·가정 또는 구매 권유를 하지 않았다.', '',
        '## 연도별: 운영과 연구 기준', '',
        '| 연도 | 경주 | 운영6→10 | 연구 기준6→10 |', '|---|---:|---:|---:|',
        *[f'| {y} | {int(s[(s.scope=="identical_roster")&(s.subgroup==str(y))&(s.model=="state_gbm118")].iloc[0].races):,} | '+
          ' | '.join(f'{s[(s.scope=="identical_roster")&(s.subgroup==str(y))&(s.model==m)].iloc[0].six_rate:.2%}→{s[(s.scope=="identical_roster")&(s.subgroup==str(y))&(s.model==m)].iloc[0].ten_rate:.2%}' for m in ['operating_A_v5','state_gbm118'])+' |' for y in [2024,2025,2026]], '',
        '現행2026H2 가중치에 해당하는7월~9/13 동일명단304경주에서는 운영87→104적중(28.62→34.21%), 연구 기준88→109적중(28.95→35.86%)이다. 작은 부분표본의 기술통계이며 모델 우위의 확인은 아니다.'.replace('現행','현행'), '',
        '## 취소마 제거 민감도4,769경주', '',table('matched_starters_sensitivity'), '',
        '운영 명단에만 있던 말을 제거하고 기존 A 주변확률로 재정렬한 보조 분석이다. 모델을 취소 후 다시 추론하거나 공동분포를 재구성한 성적은 아니다. 명단이 같은 주 비교와 분모를 혼합하지 않는다.', '',
        '## 검증·한계·재현', '',
        f'공식 감사 파일의 finish_order로 {verification["race_policy_records_checked"]:,}개 경주·모델·범위 기록을 다시 채점했다. 실제6/10장 열거와 집합 포함 조건이 일치하고,6장은10장의 부분집합이며 새 적중은 모두 축 이탈 사건이었다. 기존 표의 모든6장 적중 수와 분모가 일치했고 원천 해시는 변하지 않았다.', '',
        '직전 평가처럼 입상 동착 경주는 제외됐고 완주 실패마는 출전 후보에 남는다. 반복 사용한 역사적 개발기간, 명단·중량 공시시각 미확인,2026부분연도와 운영 계열의 시기별 가중치 차이를 유지한다. 정책 간 적중 증가를 새로운 모델의 학습 개선이나 미래 적중 보장으로 해석하지 않는다.', '',
        '[사전계획](PLAN.md) · [재현 코드](compare.py) · [전체 집계](outputs/summary.csv) · [추가 적중 경주](outputs/extra_hits.parquet) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json) · [직전6장 연구](../20261024_axis4_trio_comparison_v1/README.md)', ''])
    (c.HERE/'README.md').write_text(content)
    (c.HERE/'PUBLICATION.md').write_text('# 5두 삼복 박스10장의 추가 효과\n\n같은4,133경주에서 운영26.74→33.20%, 연구 기준27.12→34.04%로 증가했다. 추가4장은 축 이탈 경주를 구제하지만 동일 장당 금액의 구매액은66.67% 늘어난다. 연구 기준의 적중 수는25.51% 증가했다. 배당을 평가하지 않아 수익 개선을 주장하지 않는다. 선택5두는 직전6장 평가와 동일하다. 운영 미변경·공개 미게시.\n')
    central=c.R/'conclusions/58J_TRIO_FIVE_BOX.md'
    central.write_text('# 같은5두: 삼복6장과 박스10장\n\n2026-10-24 · 연구58J · 운영 변경 없음.\n\n'+table('identical_roster')+'\n\n명단 동일4,133경주에서 고른5두를 유지한 정책 비교다. 연구 기준 추가286경주는 모두 축 이탈이며, 적중 수는25.51%·동일 장당 구매액은66.67% 증가한다. 배당 미평가로 수익성 결론은 없다.\n\n[원문](../20261024_trio_five_box_v1/README.md) · [결과](../20261024_trio_five_box_v1/outputs/summary.csv) · [검증](../20261024_trio_five_box_v1/outputs/verification.json)\n')
    marker='<!-- trio_five_box_20261024 -->'
    for path,line in [
        (c.R/'README.md','[연구58J 동일5두 삼복6→10장](20261024_trio_five_box_v1/README.md): 운영26.74→33.20%, 연구 기준27.12→34.04%; 구매액66.67% 증가, 배당 미평가.'),
        (c.R/'conclusions/README.md','[연구58J 동일5두 삼복6→10장](58J_TRIO_FIVE_BOX.md): 연구 기준+6.92%p, 추가286경주·구매액66.67% 증가.'),
        (c.R/'conclusions/SOURCES.md','[연구58J](58J_TRIO_FIVE_BOX.md) · [원문](../20261024_trio_five_box_v1/README.md) · [검증](../20261024_trio_five_box_v1/outputs/verification.json). 직전58H의 선택5두와 공식 착순을 재사용해6/10장 직접 열거.')]:
        old=path.read_text()
        if marker not in old:path.write_text(old+'\n\n'+marker+'\n'+line+'\n')
    sm=c.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    sources=[c.HERE/'README.md',c.HERE/'PLAN.md',c.HERE/'compare.py',c.OUT/'summary.csv',c.OUT/'verification.json',central]
    additions={str(p.relative_to(c.ROOT)):c.sha(p) for p in sources}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inv=c.OUT/'artifact_inventory.json'
    if not inv.exists():c.save(inv,{})
    before=json.loads((c.OUT/'publication_before.json').read_text())
    log=c.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(20):
        files=sorted([p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[central])
        total=sum(p.stat().st_size for p in files)
        row=f'| 2026-10-24 | 58J 삼복5두 박스10장 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261024_trio_five_box_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58J 삼복5두 박스10장' not in x)+'\n'+row+'\n')
        modified=[dict(path=p,before_bytes=v['bytes'],after_bytes=(c.ROOT/p).stat().st_size,
            delta_bytes=(c.ROOT/p).stat().st_size-v['bytes']) for p,v in before.items()]
        value=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(c.ROOT)),bytes=p.stat().st_size,sha256=None if p==inv else c.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),new_models=0)
        old=inv.read_text();c.save(inv,value)
        if old==inv.read_text():break
    else:raise AssertionError('Inventory convergence failed')
    assert sum(p.stat().st_size for p in files)==value['new_bytes']<1_000_000
    print(json.dumps({k:v for k,v in value.items() if k not in ['files','modified_files']},indent=2))


if __name__=='__main__':main()
