"""Local report, shared indexes, and exact self-inclusive artifact inventory."""
import json
import re
import pandas as pd
import analyze as a

CENTRAL=a.R/'conclusions/58P_PERSONAL_T2_TRIO_TOP6.md'
MARKER='<!-- personal_t2_trio_top6_20261025 -->'


def main():
    verify=json.loads((a.OUT/'verification.json').read_text());assert verify['status']=='passed'
    s=pd.read_csv(a.OUT/'summary.csv');b=pd.read_csv(a.OUT/'paired_differences.csv')
    t=pd.read_csv(a.OUT/'gain_loss_summary.csv');r=pd.read_parquet(a.OUT/'race_results.parquet')
    def table(scope,subgroups=('all','2024','2025','2026')):
        lines=['| 연도/집단 | 경주 | 축6 적중 | 공동6 적중 | 축6 ROI | 공동6 ROI | 환급 차이 |',
               '|---|---:|---:|---:|---:|---:|---:|']
        for subgroup in subgroups:
            z=s[s.scope.eq(scope)&s.subgroup.eq(subgroup)].set_index('policy')
            if not len(z):continue
            old=z.loc['axis_six'];new=z.loc['joint_top6']
            lines.append(f'| {subgroup} | {int(old.races):,} | {int(old.hits):,} ({old.hit_rate:.2%}) | {int(new.hits):,} ({new.hit_rate:.2%}) | {old.roi:.2%} | {new.roi:.2%} | {int(new.return_krw-old.return_krw):+,}원 |')
        return '\n'.join(lines)
    def money(scope,subgroups=('all','2024','2025','2026')):
        lines=['| 연도 | 방식 | 구매액 | 환급액 | 순손익 |','|---|---|---:|---:|---:|']
        for row in s[s.scope.eq(scope)&s.subgroup.isin(subgroups)].itertuples():
            lines.append(f'| {row.subgroup} | {"축6" if row.policy=="axis_six" else "공동6"} | {row.stake_krw:,}원 | {row.return_krw:,}원 | {row.net_krw:+,}원 |')
        return '\n'.join(lines)
    def changes(scope):
        lines=['| 연도 | 새 적중 / 상실 | 새 평균배당 / 상실 평균배당 | 새 환급 / 상실 환급 |',
               '|---|---:|---:|---:|']
        for row in t[t.scope.eq(scope)&t.subgroup.isin(['all','2024','2025','2026'])].itertuples():
            lines.append(f'| {row.subgroup} | {row.gained} / {row.lost} | {row.gained_mean:.2f} / {row.lost_mean:.2f}배 | {row.gained_return:,} / {row.lost_return:,}원 |')
        return '\n'.join(lines)
    ci=['| 표본 | 연도 | 적중차이 %p [95%] | ROI차이 %p [95%] |','|---|---|---:|---:|']
    for scope in ['previous_4133','all_4799','promoted_1258']:
        for subgroup in ['all','2024','2025','2026']:
            z=b[b.scope.eq(scope)&b.subgroup.eq(subgroup)].set_index('metric')
            if not len(z):continue
            vals=[f'{z.loc[m,"difference"]*100:+.2f} [{z.loc[m,"ci_low"]*100:+.2f}, {z.loc[m,"ci_high"]*100:+.2f}]' for m in ['hit','roi']]
            ci.append(f'| {scope} | {subgroup} | {vals[0]} | {vals[1]} |')
    dates=[]
    for scope,g in a.cohorts(r):
        dates.append(f'- `{scope}`: {len(g):,}경주, {g.race_date.min()}~{g.race_date.max()}.')
    text='\n\n'.join([
        '# personal_t2: 축 고정6조합과 공동확률 상위6조합',
        '2026-10-25 · 연구58P · 현재운영2026가중치일치 · 새학습0 · 운영/DB변경없음.',
        '**이전과 같은4,133경주에서 공동6은 적중27.22→29.18%로1.96%p 높았다. 세전ROI는−23.16→−23.42%로 거의 같았고 환급64,000원이 줄었다.2024·2026은환급증가,2025는감소했다.적중증가와달리ROI우위는불확실하다.**',
        '## 모델과 비교 정의',
        '현재 등록프로필은 thoroughbred-training-state-20261025-v1, personal_t2_2026 서울·부산이다. 등록resolver의모든경로·해시·검증게이트를통과한상태를동결했다.2026연구가중치2개는운영가중치와해시가정확히같고set온도도같다.기존상태118+조교18=136입력이다.',
        '**2024·2025는현재2026가중치를과거에적용한성적이아니다.** 각평가연도Y에2017~Y−2자료로학습하고Y−1로보정한보존personal_t2연구버전을쓴다.2024는학습끝2022/보정2023,2025는학습끝2023/보정2024,2026은학습끝2024/보정2025다.이미반복분석한개발기간의후향비교이며실전미래검증이아니다.',
        '- 축 고정6: Top3 주변확률1위축과차순위4두를고른뒤축이포함된C(4,2)=6개삼복집합.\n- 공동확률6: 동일모델이부여한전삼복집합에서확률상위6개.축/5두제한없음.\n- q(T)∝exp(3두raw점수합/고정set온도).집합내6개PL순서확률은합1이므로삼복선택에는원래set확률을쓴다.말별입상확률을곱하지않는다.\n- 확률12자리반올림후동점은마번오름차순.현재정답·확정배당은티켓선택에넣지않는다.',
        '매경주두정책모두6개고유조합·조합당1,000원·총6,000원이다.ROI=(환급−구매)/구매이며표의금액차이는공동6−축6이다.공시확정배당을쓴세전가상정산이고개인세금·절사·실제구매풀영향은제외했다.극단배당을주결과에서빼지않았다.',
        '## 표본을 섞지 않은 세 가지 범위',
        '\n'.join(dates),
        '주표본previous_4133은이전58M의5모델동일명단비교표본을그대로사용한다.현재모델자체의가용성을이유로좋은경주만추린것이아니다.전체저장예측4,799경주는별도보조표에모두포함했고,승격당시1,258경주도따로대조했다.취소·제외의기존모집단을유지하고비정상완주마를후보에서추가로빼지않았다.입상동착제외등기존정답계약은그대로다.',
        '## 주 비교: 이전과 같은4,133경주',
        table('previous_4133'),
        money('previous_4133'),
        '2024적중+27건·환급+184,200원,2025적중+22건·환급−303,900원,2026적중+32건·환급+55,700원이다.전체적중은81건늘고환급은64,000원줄었다.운영가중치인2026만보면주표본에서공동6의적중과ROI점추정이모두나아졌으나두정책모두손실이다.',
        '## 새 적중과 상실 배당',
        changes('previous_4133'),
        '전체새225경주·상실144경주다.평균배당22.05대34.89배,새환급4,960,200원보다상실환급5,024,200원이64,000원커서적중이늘어도ROI는약간낮아졌다.2025에는새73건의평균20.33배대상실51건35.06배로환급이감소했다.2026도상실평균44.54배가새24.10배보다높았지만새67대상실35로적중수증가가이를상쇄했다.이것은확정배당의사후분해이며가격을사용한구매전략은시험하지않았다.',
        '4,133경주중3,777경주에서티켓이바뀌었고평균1.52장만교체됐다.공동6의후보말합집합은평균6.23두,기존축없는조합은평균0.283장이다.이번은축없는3장같은고정비중정책과다르다.',
        '## 지역별 주표본',
        table('previous_4133',('seoul','busan')),
        '지역별ROI점추정은서울이약간낮아지고부산이약간높아졌다.동일모델내선택정책의차이이며조교18개입력의독립효과나지역인과효과를추정한것은아니다.',
        '## 전체저장4,799경주 보조 확인',
        table('all_4799'),
        money('all_4799'),
        '현재2026가중치로평가된전체1,288경주에서는축6이382/1,288(29.66%),공동6이415/1,288(32.22%)였다.동일구매7,728,000원,환급6,488,400→6,578,200원으로89,800원증가,ROI−16.04→−14.88%였다.2026미래기간을새로확보한성적이아니다.',
        '전체4,799경주에서는적중1,338→1,436(+98),환급22,326,400→22,334,300(+7,900원),ROI−22.46→−22.43%다.전체표본에서도적중은늘었지만수익률차이는거의없다는결론이같다.표본범위에따라작은ROI차이의부호가바뀌는점자체가수익우위를확정하지못하는근거다.',
        '## 승격당시1,258경주와의 교차검증',
        table('promoted_1258',('all',)),
        '승격보고서의삼복6조합408건은이미공동확률상위6개결과였다.그같은1,258경주에서새로구성한축고정6은375건,공동6은기존과똑같은408건이었다.이번주표본의2026공동6은344건으로다르게보이지만분모가1,081경주라서그렇다.1,288전체저장·1,258승격비교·1,081기존비교부분을섞지않는다.',
        '## 차이의 불확실성',
        '날짜단위paired bootstrap2,000회,seed20261025.아래는공동6−축6의차이이며각지표별구간이다.동일한날짜의경주를함께재표집했다.',
        '\n'.join(ci),
        '주표본전체적중차이+1.96%p의95%구간은+1.05~+2.83%p다.ROI차이−0.26%p는−6.37~+5.21%p로0을포함한다.연도별·보조표본ROI구간도모두0을포함해공동6이수익에서더좋다고확정할수없다.각지표구간이며다중비교·같은말의장기관련성을완전히조정한것은아니다.',
        '최고환급1경주를각정책에서제외하는꼬리민감도도summary.csv에보존했다.주표본축6은−23.98%,공동6은−24.00%로역시거의같다.결과를본뒤고배당을선별제외하는실행정책을만든것은아니다.',
        '## 검증·한계·적용 판단',
        f'원천파일·현재등록부·운영가중치해시를대조했다.4,799경주에서운영용확률함수로전분포를독립재현하고57,588장티켓·확률·정답라벨을전수확인했다.전체/연도/지역32개정산행은Decimal로검산했다.승격1,258경주의공동6적중라벨408건도전수일치했다.날짜bootstrap재현·마번순열·균등확률동점검사를통과했다.입상주변확률최대재현오차는{verify["marginal_max_error"]:.3g}다.',
        '연구결론은적중기준에서는공동6의우위가관측되지만수익기준에서는아직우위를확인하지못했다는것이다.이비교로가중치·등록·조합추천코드·실제게시를변경하지않았다.원래운영추천의trio6도이미공동6방식이다.2024/25연구버전과2026운영버전을명확히구분하고,새가중치가옛운영보다우수한가의다른비교와섞지않는다.',
        '반복분석한개발기간,2026부분연도,과거조교공개시각미인증,당시출마명단/부중공개시각제약은유지한다.이번에도원본DB·전체특징·기존모델·전체공동분포를복사하지않고기존예측·확정배당을재사용했다.새학습0·외부수집0·DB쓰기0·운영변경0이다.',
        '[사전계획](PLAN.md) · [재현](analyze.py) · [독립검증](verify.py) · [모든표본집계](outputs/summary.csv) · [차이95%구간](outputs/paired_differences.csv) · [새적중/상실](outputs/gain_loss_summary.csv) · [연도별가중치](outputs/year_models.json) · [검증결과](outputs/verification.json) · [용량](outputs/artifact_inventory.json)',
        ''
    ])
    (a.HERE/'README.md').write_text(text)
    CENTRAL.write_text('\n\n'.join(['# 연구58P personal_t2 삼복 축6·공동6',
        '2026-10-25.운영2026가중치동일,2024/25는당시이전자료로학습한연구버전.학습/운영변경없음.',
        table('previous_4133'),
        '동일4,133경주에서새225·상실144,평균배당22.05/34.89배.적중81건늘었지만환급64,000원감소.전체저장4,799경주도적중98건증가·환급7,900원증가로ROI거의동일.2026전체1,288경주에서적중29.66→32.22%,ROI−16.04→−14.88%.모든ROI차이95%구간0포함·미래우위미확정.',
        '승격1,258경주기존408건은공동6이며이번에도라벨전수일치.해당축6은375건.1,081/1,258/1,288분모혼용금지.기존정책비교와새입력의효과구분.',
        '[원문](../20261025_personal_t2_trio_top6_v1/README.md) · [전체표](../20261025_personal_t2_trio_top6_v1/outputs/summary.csv) · [검증](../20261025_personal_t2_trio_top6_v1/outputs/verification.json)', '']))
    (a.HERE/'PUBLICATION.md').write_text('# 게시준비: personal_t2에서같은6조합비교\n\n같은4,133경주와경주당6,000원에서축6적중27.22%,공동6은29.18%였다.세전ROI는−23.16%와−23.42%로거의같았다.2024/26환급은늘고2025는줄었다.2026전체1,288경주는적중29.66→32.22%,ROI−16.04→−14.88%였다.수익차이의95%구간은0을포함한다.2024/25는당시연도이전자료로학습한같은계열연구모델이며현재2026가중치의과거실전성적이아니다.\n\n[상세](README.md) · [검증](outputs/verification.json)\n\n게시준비만완료,배포/DB/운영변경없음.\n')
    for path,line in [
        (a.R/'README.md','[연구58P personal_t2 축6·공동6](20261025_personal_t2_trio_top6_v1/README.md):동일4133경주적중27.22→29.18%,ROI−23.16→−23.42%;2026전체1288은적중29.66→32.22%,수익우위미확정.'),
        (a.R/'conclusions/README.md','[연구58P personal_t2 동일6조합](58P_PERSONAL_T2_TRIO_TOP6.md):모든연도적중증가·ROI거의동일,2024/25연구버전과2026운영가중치구분.'),
        (a.R/'conclusions/SOURCES.md','[연구58P](58P_PERSONAL_T2_TRIO_TOP6.md) · [원문](../20261025_personal_t2_trio_top6_v1/README.md) · [원천해시](../20261025_personal_t2_trio_top6_v1/outputs/input_manifest.json) · [검증](../20261025_personal_t2_trio_top6_v1/outputs/verification.json).personal_t2연도별보존점수·기존확정배당재사용,신규학습0.')]:
        old=path.read_text()
        if MARKER not in old:path.write_text(old+'\n\n'+MARKER+'\n'+line+'\n')
    sm=a.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    paths=[CENTRAL,a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'verify.py',a.HERE/'finalize.py',
        a.OUT/'summary.csv',a.OUT/'paired_differences.csv',a.OUT/'verification.json',a.OUT/'input_manifest.json']
    additions={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inventory=a.OUT/'artifact_inventory.json'
    if not inventory.exists():a.save('artifact_inventory.json',{})
    before=json.loads((a.OUT/'publication_before.json').read_text());log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(25):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CENTRAL])
        total=sum(p.stat().st_size for p in files)
        line=f'| 2026-10-25 | 58P personal_t2 축6·공동6 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_personal_t2_trio_top6_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58P personal_t2 축6·공동6' not in x)+'\n'+line+'\n')
        modified=[dict(path=p,before_bytes=x['bytes'],after_bytes=(a.ROOT/p).stat().st_size,
            delta_bytes=(a.ROOT/p).stat().st_size-x['bytes']) for p,x in before.items()]
        obj=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(a.ROOT)),bytes=p.stat().st_size,sha256=None if p==inventory else a.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),new_models=0)
        old=inventory.read_text();a.save('artifact_inventory.json',obj)
        if old==inventory.read_text():break
    else:raise AssertionError('inventory convergence')
    assert sum(p.stat().st_size for p in files)==obj['new_bytes']<2*1048576
    for path in [a.HERE/'README.md',a.HERE/'PUBLICATION.md',CENTRAL]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' not in link:assert (path.parent/link).exists(),(path,link)
    for row in obj['files']:
        p=a.ROOT/row['path'];assert p.stat().st_size==row['bytes']
        if row['sha256']:assert a.sha(p)==row['sha256']
    for path,h in additions.items():assert a.sha(a.ROOT/path)==h
    print(json.dumps({k:v for k,v in obj.items() if k not in ['files','modified_files']},ensure_ascii=False))
    print(json.dumps(max(obj['files'],key=lambda x:x['bytes']),ensure_ascii=False))


if __name__=='__main__':main()
