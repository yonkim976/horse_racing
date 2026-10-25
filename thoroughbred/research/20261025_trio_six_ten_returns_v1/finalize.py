"""Document fixed-stake historical returns and exact artifact sizes."""
import json
import pandas as pd
import analyze as a


def main():
    v=json.loads((a.OUT/'verification.json').read_text());assert v['status']=='passed'
    s=pd.read_csv(a.OUT/'return_summary.csv');d=pd.read_csv(a.OUT/'dividend_summary.csv')
    boot=pd.read_csv(a.OUT/'paired_roi_intervals.csv')
    primary=s[s.scope.eq('identical_roster')].copy()
    names={'operating_A_v5':'운영 A v5 계열','full103':'이전 full103','state_gbm118':'연구 기준 state_gbm118',
        'state_joint118':'공동착순 신경망','axis_failure_selected':'축 이탈 위험 보조안'}
    def roi_table():
        lines=['| 모델 | 연도 | 경주 | 6장 순수익률 | 10장 순수익률 | 추가4장 순수익률 |',
            '|---|---|---:|---:|---:|---:|']
        for model,label in names.items():
            for y in ['2024','2025','2026','all']:
                q=primary[primary.model.eq(model)&primary.subgroup.eq(y)].set_index('policy')
                lines.append(f'| {label} | {"전체" if y=="all" else y} | {int(q.loc["six","races"]):,} | {q.loc["six","roi"]:.2%} | {q.loc["ten","roi"]:.2%} | {q.loc["extra_four","roi"]:.2%} |')
        return '\n'.join(lines)
    def cash_table(model):
        lines=['| 연도 | 정책 | 구매액(원) | 환급액(원) | 순손익(원) | 순수익률 |','|---|---|---:|---:|---:|---:|']
        for y in ['2024','2025','2026','all']:
            for policy in ['six','ten']:
                q=primary[primary.model.eq(model)&primary.subgroup.eq(y)&primary.policy.eq(policy)].iloc[0]
                lines.append(f'| {"전체" if y=="all" else y} | {6 if policy=="six" else 10}장 | {q.stake_krw:,.0f} | {q.return_krw:,.0f} | {q.net_krw:,.0f} | {q.roi:.2%} |')
        return '\n'.join(lines)
    dist=d[d.scope.eq('identical_roster') & d.policy.eq('extra_four')]
    extra_lines=['| 모델 | 연도 | 추가 적중 | 평균배당 | 중앙값 | 25~75분위 | 최대배당 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for model,label in names.items():
        for y in ['2024','2025','2026','all']:
            q=dist[dist.model.eq(model)&dist.subgroup.eq(y)].iloc[0]
            extra_lines.append(f'| {label} | {"전체" if y=="all" else y} | {int(q.hits)} | {q["mean"]:.2f}배 | {q["median"]:.2f}배 | {q.q25:.2f}~{q.q75:.2f}배 | {q["max"]:.1f}배 |')
    text='\n'.join([
        '# 삼복6장과5두박스10장: 추가4장 배당과 연도별 실제 배당 정산', '',
        '2026-10-25 · 연구58K · 이전 선택5두 고정 · 신규학습0 · 운영변경 없음 · 공시배당 기준 세전 가상정산.', '',
        '**추가4장이 맞으면 평균배당은 높았지만 구매액을 회수하지 못했다. 연구 기준의6장 순수익률은−21.92%,10장은−24.03%였다. 운영 계열은−23.37%→−26.63%였다. 같은 장당1,000원에서 연구 기준의 추가4장은16,532,000원을 구매하고12,036,700원을 환급받아4,495,300원을 더 잃었다.**', '',
        '## 고정 조건과 금액의 의미', '',
        '주 비교는58H/58J와 같은 서울·부산4,133경주,2024-01-05~2026-09-13이다. 연도별분모는1,530/1,522/1,081경주다. 말5두·축·후보4두는 기존 저장 예측대로이며 배당으로 순위나 참여경주를 고르지 않았다. 각 시기의 운영 A v5 rolling_all 계열 예측과 이전 연구모델들을 비교하며 현행2026H2 가중치를 과거학습기간에 적용하지 않았다. 운영B의 자유조합상위6/10장 성적과 다르다.', '',
        '각 조합1,000원, 매경주6,000원 또는10,000원 구매다. 축A와B/C/D/E에서 기존6장+축없는BCD/BCE/BDE/CDE4장을 산다. 원래 포함된 경주들은 실제입상3두가 고유해 적중삼복티켓은 최대1장이다. 환급액=적중티켓구매액×공식삼복배당, 순수익=환급−구매, 순수익률=순수익/구매다. 환급배당에서 마권 발매단계의 공제율을 다시 빼지 않는다.', '',
        '실제배당을 넣은 정액 가상정산이지 사용자의 계좌거래 원장이 아니다. 개인 기타소득세·거래별 원단위 절사·베팅이 배당풀에 미치는 영향은 반영하지 않았다. 따라서 세후실수령으로 표현하지 않는다. 개인과세가 별도라는 일반 배경은 [한국마사회 안내](https://board.kra.co.kr/board/viewPost.do?artNo=213779&boardNo=135&remarkNo=0)를 참고했으며, 오래된 공지의 과세기준 숫자를 이번 계산에 적용하지 않았다.', '',
        '## 배당 원천과 누락 확인', '',
        '기존 연구 전체4,799경주의 당첨배당을 전부 확보했고 공통주비교4,133경주에서 누락·충돌0건이다.2024년1,761경주는 보관된 공식dacom11 결과원문의 당첨조합·배당,2025년1,750경주는SQLite의공식API301확정배당을 사용했다.2026년1,288경주 중40경주는RPT(동일API와값교차확인),1,248경주는API다. 전체선택원천은RPT1,801/API2,998경주다.모두 공식1~3착 마번 조합과 일치한다.', '',
        f'공식RPT {v["source_files_hash_checked"]}개 파일은 복사하지 않고SHA256으로 참조했다. SQLite는read_only·query_only와단일읽기트랜잭션으로 조회했다. 선택조합키·completed상태·SQLite실제1~3착 일치를 검사했고3038개의당첨배당원행ID를 별도재조회했다. RPT/API동시보유40건은배당이일치했다.2024년API배당이없는것을0으로처리하지않고RPT에서복원했다. 자세한원천가용성·마번16표기변경은[기록](PROTOCOL_AMENDMENT.md)에남겼다.', '',
        '## 축 없는 추가4장이 맞았을 때 배당', '',
        '\n'.join(extra_lines), '',
        '연구 기준의기존6장적중배당은전체평균17.27배·중앙값11.40배,추가4장은평균42.09배·중앙값25.65배다. 추가4장의당첨배당이높은것과포트폴리오가흑자인것은다르다.4,133경주추가구매16,532장중286장적중이므로실제총환급은12,036,700원으로추가원금보다작다.이표본에서추가4장의원금만회수하려면적중배당합계16,532배(286회평균57.80배)가필요했지만실제합계12,036.7배였다.이는과거표본의산술기준이며미래손익분기배당예측이아니다.', '',
        '## 연도별 수익률: 모든 비교 모델', '',roi_table(), '',
        '2026년은9/13까지의부분연도다. 연구기준2024년만은6장−28.32%→10장−27.75%로수익률이0.57%p개선됐지만,추가4장자체도−26.90%로손실이다.더많이구매해분모가커지므로손실률이조금개선돼도총손실액은늘수있다.2025·2026년연구기준과운영의세연도는10장순수익률이더낮았다.전체기간의다섯모델모두10장이6장보다낮았다.', '',
        '## 연구 기준 모델: 연도별 원금·환급·손익', '',cash_table('state_gbm118'), '',
        '## 운영 A 계열: 연도별 원금·환급·손익', '',cash_table('operating_A_v5'), '',
        '## 고배당 의존도와 불확실성', '',
        '극단값은실제정산의주결과에서제외하지않았다.연구기준추가4장의최고적중377.5배는추가환급의3.14%다.최고적중경주1건을빼면추가4장ROI−27.19→−29.46%,적중배당상위1%인3경주를빼면−33.02%다.운영추가4장의최대677.9배는환급의5.99%이며최고1경주제외ROI−35.60%다. 제거진단은당첨을사후제외한민감도로실행가능한필터성적이아니다.', '',
        '날짜403개를paired bootstrap2,000회재표집했다. 연구기준10장−6장ROI차이−2.11%p의95%구간은−7.69~+3.55%p,운영−3.26%p는−9.23~+3.40%p다.따라서미래에도언제나6장이우월하다고확정하지않는다.다만추가4장자체의ROI구간은연구기준−38.63~−14.98%,운영−43.68~−16.77%로이번개발표본에서는원금미회수다.동일말의장기상관과다중비교를완전히조정한구간은아니다.', '',
        '## 검증·범위·판단', '',
        f'6/4/10장총환급의합과{v["settlement_summary_rows_independently_decimal_checked"]}개집계행을별도Decimal계산으로검증했다.이전모든적중집계와분모가일치하고공식당첨원문·API원행·출처해시불변을확인했다.지급배당의결측을실패0으로치환하지않았다.모델·정책·경주를배당으로다시고르지않았다.', '',
        '반복사용한역사적개발자료이며독립미래수익증거가아니다.기존모집단의입상동착제외,확정명단·부담중량공시시각미확인,출처·학습기간차이도유지한다.4,769경주취소마제거민감도와연구전체4,799경주의결과는별도CSV에있으며주비교와분모를섞지않는다.10장을추천하는새정책이나운영승격으로해석하지않는다.', '',
        '[계획](PLAN.md) · [재현](analyze.py) · [검산 코드](verify.py) · [수익 집계](outputs/return_summary.csv) · [배당 통계](outputs/dividend_summary.csv) · [추가4장 적중 경주](outputs/extra_four_winners.csv) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)', ''])
    (a.HERE/'README.md').write_text(text)
    (a.HERE/'PUBLICATION.md').write_text('# 게시 준비: 삼복6→10장의 비용과 배당\n\n동일4,133경주에서연구기준의추가4장적중286회평균배당42.09배·중앙값25.65배였다.하지만추가16,532,000원구매에환급12,036,700원으로4,495,300원손실이었다.6장세전순수익률−21.92%,10장−24.03%다.운영도−23.37→−26.63%였다.실제확정배당기준의고정금액가상정산이며개인세금과실제계좌거래는반영하지않았다.배당누락0·새학습0·운영미변경·미게시.\n')
    central=a.R/'conclusions/58K_TRIO_SIX_TEN_RETURNS.md'
    central.write_text('# 삼복6장과10장: 추가4장 실제배당과 연도별 수익\n\n2026-10-25 · 연구58K · 운영미변경 · 조합당1,000원공시배당세전가상정산.\n\n'+roi_table()+'\n\n연구기준의추가4장은286적중·평균42.09배·중앙값25.65배였다.추가구매16,532,000원과환급12,036,700원의차이는−4,495,300원이다.동일명단4,133경주배당누락0건,기존연구전체4,799경주당첨배당확보.미래수익이나세후실수령증거가아니다.\n\n[원문](../20261025_trio_six_ten_returns_v1/README.md) · [집계](../20261025_trio_six_ten_returns_v1/outputs/return_summary.csv) · [검증](../20261025_trio_six_ten_returns_v1/outputs/verification.json)\n')
    marker='<!-- trio_six_ten_returns_20261025 -->'
    for path,line in [(a.R/'README.md','[연구58K 삼복6·10장 연도별 실제배당 정산](20261025_trio_six_ten_returns_v1/README.md): 연구기준−21.92→−24.03%,추가4장평균42.09배이나추가손실449.53만원.'),
        (a.R/'conclusions/README.md','[연구58K 삼복6·10장 실제배당 정산](58K_TRIO_SIX_TEN_RETURNS.md): 연구기준추가4장286적중·평균42.09배,세전순수익률−27.19%.'),
        (a.R/'conclusions/SOURCES.md','[연구58K](58K_TRIO_SIX_TEN_RETURNS.md) · [원문](../20261025_trio_six_ten_returns_v1/README.md) · [공식RPT출처](../20261025_trio_six_ten_returns_v1/outputs/report_source_manifest.json) · [검증](../20261025_trio_six_ten_returns_v1/outputs/verification.json). RPT1,801/API2,998경주당첨배당,기존선택5두고정.')]:
        old=path.read_text()
        if marker not in old:path.write_text(old+'\n\n'+marker+'\n'+line+'\n')
    sm=a.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    paths=[a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'verify.py',a.OUT/'return_summary.csv',a.OUT/'dividend_summary.csv',a.OUT/'verification.json',central]
    entries={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in entries]+[dict(path=p,sha256=h) for p,h in entries.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inv=a.OUT/'artifact_inventory.json'
    if not inv.exists():a.save(inv,{})
    before=json.loads((a.OUT/'publication_before.json').read_text());log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(20):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[central])
        total=sum(p.stat().st_size for p in files)
        row=f'| 2026-10-25 | 58K 삼복6·10장 실제배당 정산 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_trio_six_ten_returns_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58K 삼복6·10장 실제배당 정산' not in x)+'\n'+row+'\n')
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
