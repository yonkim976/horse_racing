"""Research58Q findings and compact reproducible publication inventory."""
import json
import re
import pandas as pd
import analyze as a

CENTRAL=a.R/'conclusions/58Q_PERSONAL_T2_GAIN_LOSS.md'
MARKER='<!-- personal_t2_gain_loss_20261025 -->'


def main():
    v=json.loads((a.OUT/'verification.json').read_text());assert v['status']=='passed'
    s=pd.read_csv(a.OUT/'condition_summary.csv')
    d=pd.read_parquet(a.OUT/'race_diagnostics.parquet');c=d[d.transition.isin(['gained','lost'])]
    tail=pd.read_csv(a.OUT/'tail_decomposition.csv')
    def matrix(dim):
        out=['| 조건 | 2025 전체/새/상실 | 2025 환급차 | 2026 전체/새/상실 | 2026 환급차 |',
             '|---|---:|---:|---:|---:|']
        q=s[s.dimension.eq(dim)&s.period.isin(['2025','2026'])]
        values=list(dict.fromkeys(q.value))
        for val in values:
            cells=[]
            for year in ['2025','2026']:
                z=q[q.period.eq(year)&q.value.eq(val)]
                if len(z):
                    row=z.iloc[0];cells.extend([f'{int(row.races)}/{int(row.gained)}/{int(row.lost)}',f'{int(row.delta_return):+,}원'])
                else:cells.extend(['0/0/0','0원'])
            out.append(f'| {val} | '+ ' | '.join(cells)+' |')
        return '\n'.join(out)
    annual=['| 연도 | 전체 | 새 적중 / 상실 | 새 평균 / 상실 평균배당 | 환급차 | ROI차 |',
            '|---|---:|---:|---:|---:|---:|']
    for row in s[s.dimension.eq('all')].itertuples():
        annual.append(f'| {row.period} | {row.races:,} | {row.gained} / {row.lost} | {row.gained_mean:.2f} / {row.lost_mean:.2f}배 | {row.delta_return:+,}원 | {row.delta_roi_pp:+.2f}%p |')
    annual='\n'.join(annual)
    bands=['| 연도 | 배당 구간 | 새 적중 / 상실 | 새 환급 | 상실 환급 | 환급차 | 연간구매액 대비 기여 |',
           '|---|---|---:|---:|---:|---:|---:|']
    for row in tail[tail.threshold.eq(50)&tail.period.isin(['2025','2026'])].itertuples():
        label='50배 미만' if row.band=='below' else '50배 이상'
        bands.append(f'| {row.period} | {label} | {row.new_races} / {row.lost_races} | {row.new_return:,}원 | {row.lost_return:,}원 | {row.delta_return:+,}원 | {row.annual_contribution_pp:+.2f}%p |')
    bands='\n'.join(bands)
    patterns=['| 연도 | 구분 | 실제 입상마의 모델순위 집합 | 경주 | 평균배당 |',
              '|---|---|---|---:|---:|']
    for row in pd.read_csv(a.OUT/'rank_pattern_summary.csv').query("period in ['2025','2026']").itertuples():
        patterns.append(f'| {row.period} | {"새 적중" if row.transition=="gained" else "상실"} | {row.podium_model_ranks} | {row.races} | {row.mean_dividend:.2f}배 |')
    patterns='\n'.join(patterns)
    examples=['| 사례 | 거리·등급 | 정답 마번집합 | 모델순위집합 | 삼복배당 |',
              '|---|---|---|---|---:|']
    ids=['1:20250823:9','3:20250530:3','1:20260329:5','3:20260621:7']
    for key in ids:
        row=c[c.race_key.eq(key)].iloc[0];meet,date,no=key.split(':')
        examples.append(f'| {date} {"서울" if meet=="1" else "부산"}{no} {"새 적중" if row.transition=="gained" else "상실"} | {row.distance}m·{row.grade_raw} | {row.actual} | {row.podium_model_ranks} | {row.dividend:.1f}배 |')
    examples='\n'.join(examples)
    text='\n\n'.join([
        '# personal_t2 새225·상실144: 2025 악화와2026 개선의 조건',
        '2026-10-25 · 연구58Q · 58P 고정4,133경주·6조합 · 새 학습/운영변경 없음.',
        '**2025년은1600m·3/6등급에서놓친고배당환급이컸다.2026년은부산1600/1800m와1300m에서늘어난적중이서울1200/1400m의손실을상쇄했다.2026에도고배당상실문제는남았으며50배미만의추가환급이이를간신히넘어전체+55,700원이됐다.**',
        '## 고정한 범위와 회계 정의',
        '58P에서비교한같은서울·부산4,133경주(2024-01-05~2026-09-13),연도별1,530/1,522/1,081경주를유지했다.각경주두정책모두삼복6조합·장당1,000원이다.2025구매액은9,132,000원,2026은6,486,000원으로연도별표본수와금액이다르다.2026은부분연도다.아래환급차는공동확률6−축고정6이며이것이같은구매액에서의손익차이이기도하다.각지역·거리·등급·전개는별도로완전히분해한축이므로서로금액을더하면중복계상된다.',
        '모델은personal_t2로고정했다.2024/25는당시이전자료로학습·보정한연구버전이며2026만현재운영과같은가중치다.현재2026가중치를과거연도에적용하지않았다.확정배당·현재정답·실제전개는진단용이며선택이나새학습에넣지않았다.공시확정배당세전가상정산으로개인세금·절사·풀영향은제외한다.',
        annual,
        '2025년축6ROI−25.67→공동6−28.99%,2026년−18.29→−17.43%다.2026의개선은수익률이양수가됐다는뜻이아니다.전체ROI는−23.16→−23.42%다.',
        '## 2026년이플러스로돌아선가장직접적인이유',
        '새적중평균배당은2025년20.33배에서2026년24.10배로높아졌지만,상실배당도35.06→44.54배로더높아졌다.고배당상실문제가해결돼서좋아진것은아니다.새/상실건수비가73/51=1.43배에서67/35=1.91배로커졌고,그해환급을같게만드는사후배당비35.06/20.33=1.72배,44.54/24.10=1.85배에대해2025는미달·2026은초과했다.',
        '이는225/144변경경주의회계적분해이지미래구매를고르는임계값이아니다.2026에는경주수가적어새적중자체도73→67로줄었지만상실이51→35로더크게줄어비율이달라졌다.두연도를완전동조건으로맞춘인과비교라고하지않는다.',
        bands,
        '**ROI기준으로보면50배이상구간의손실기여는2025−5.64%p에서2026−6.68%p로오히려더커졌다.50배미만의기여가+2.31→+7.54%p로늘어그것을상쇄했다.** 연도별금액만보면고배당손실이−514,700→−433,300원으로작아보이지만2026의구매액이더작으므로정규화하면해석이다르다.저장한annual_contributions.csv도같은연간구매액을분모로쓴다.',
        '## 지역별: 2026의부산회복과서울손실',
        matrix('venue'),
        '2025에는서울−167,800원·부산−136,100원으로둘다감소했다.2026에는부산+331,200원이서울−275,500원을상쇄했다.따라서2026의작은전체개선을서울·부산공통의안정적인향상으로읽으면맞지않는다.',
        '## 거리별: 1600m의반전,1300/1800m추가환급',
        matrix('distance'),
        '2025년1600m는새12·상실7인데새평균16.37배,상실57.00배로−202,600원이었고1300m도−109,600원이었다.1400m는새20·상실10에도배당차이때문에−67,800원이었다.반면2026년1600m는새9·상실1로+188,000원,1300m는새10·상실3으로+187,200원,1800m는새9·상실1로+159,000원이었다.',
        '특히2026부산1600m는87경주중새5·상실0으로+141,700원,부산1800m는74경주중새7·상실0으로+206,700원이었다.두거리에서새12경주·상실0,합계+348,400원이부산증가를이끌었다.그러나서울1800m는−47,700원으로반대였고,전지역1200m−157,800원·1400m−281,600원도남았다.거리명하나만으로전환규칙을정할근거는아니다.',
        '## 등급별: 2025의3·6등급상실,2026의5등급증가',
        '숫자등급은국산/혼합을합친층이다.원문등급과지역×거리×등급은전체CSV에유지했다.표의등급차이는거리·지역구성이섞인관측값이지독립적인등급효과가아니다.',
        matrix('grade_label'),
        '2025년3등급은새2·상실7로−333,800원,6등급은새17·상실13으로−243,300원이었다.3등급손실중서울1400m가전체36경주중새0·상실2로−226,800원이었다.부산1600m·6등급은29경주중새2·상실1로−139,500원이었는데,그상실1건배당이168배였다.복합셀은이렇게몇건에크게영향받는다.',
        '2026년5등급은새21·상실10으로+140,100원이었다.3등급은+26,800원,6등급은−24,700원으로2025보다손실이작았다.반면4등급−49,600원,1등급−100,600원으로전체가좋아진것은아니다.서울1400m·1등급은전체2경주중168배1건상실이므로일반적인1등급효과로확대하지않는다.',
        '## 경주전전개지표',
        '기존각말의front_gate_probability를전마합해<2 / 2이상3미만 / 3이상으로나눴다.58O와같은고정경계이며이번정답을보고최적화하지않았다.전4,133경주에서전마관측·예측지원을확인했다.이것은예상앞선두수의지표로,실제로3두가선행했거나빠른속도경합이있었다는뜻은아니다.',
        matrix('predicted_pace'),
        '2025년에는중간구간2~<3도새69·상실48로−146,400원이었지만2026에는새64·상실32로+304,600원이었다.반면합3이상은2025새3·상실2로−126,500원,2026새2·상실2로−257,000원으로두연도모두환급이감소했다.후자의변경표본은겨우5·4경주다.전개고정경계에서보이는차이가새로운예측력검증이나정책전환근거는아니다.',
        '## 실제S1F통과조: 사후설명만',
        '실제통과착순1위한마리가아니라S1F통과조의첫묶음두수다.전체명단·말ID·관측·모순조건으로4,048경주는확인됐고85경주는미상이다.미상을후미/경합없음으로채우지않고전체분모에보존했다.',
        matrix('observed_pace'),
        '2025년실제첫묶음1두인경주는새15·상실12로−432,800원이었지만2026년은새13·상실4로+175,300원이었다.2025손실에는서울1400m207.5배와부산1600m168배가포함됐다.그렇다고첫묶음1두가좋다는사전규칙은아니다.이실제묶음은경주후에알수있고집단의속도·실제경합정도를그자체로확정하지못한다.',
        matrix('observed_front_podium_label'),
        '위표의조건0/1/2/3은실제첫묶음에서입상한마리수다.첫묶음이전부입상실패한0두경주에서2026은새13·상실3으로+223,000원이었고,2025는새15·상실8로+73,300원이었다.선두묶음밖입상구성을추가로담은사후패턴이다.예상선행붕괴를사전에더잘맞혔다는검증은아니다.',
        '2026실제전개가확인된상실35경주중28경주(80%)는축이실제첫묶음소속이었다.새적중은66관측중34경주(51.52%)였다.상실표본에서축입상은원래축고정적중을잃었다는정의상필수다.이비율을축붕괴위험의새신호처럼해석하지않고앞선축의동반마조합을덜담은사후설명으로만쓴다.',
        '## 어떤조합을서로바꿨나',
        '여기서숫자는마번이나실제착순이아닌**그경주의모델예측순위**다.전체새225건중175건(77.78%)은1·2위+6~8위,50건은2·3·4위였다.상실144건중134건(93.06%)은5위말포함,그중92건은1·4·5위였다.모든상실에서모델2위는입상하지못했다.',
        patterns,
        '2025에는1·4·5위상실32건평균39.56배,2026에는21건49.08배였다.2026이상실조합을해결한것은아니고,1·2위+후순위새적중56건이2025의51건보다늘어난점이함께작용했다.가산형3두점수분포에서상위6개를고르는구조상생기는패턴이므로별도예측신호의효과로주장하지않는다.',
        '## 한두경주에얼마나민감한가',
        '2025년상실환급상위10건은936,400원으로상실환급의52.37%였다.가장큰상실207.5배한건을두정책에서같이제외해도환급차는−96,400원으로여전히감소했다.2026년상실상위10건은1,041,800원,상실환급의66.82%였다.',
        '**2026년가장큰새적중136.9배(2026-03-29서울5경주)를양쪽표본에서함께제외하면+55,700원이−81,200원으로바뀐다.** 반대로가장큰상실168배경주를제외하면+223,700원,양집단최대각1건을제외하면+86,800원이다.경주를빼는경우양쪽구매액에서도동일하게경주당6,000원을뺐다.이는사후민감도일뿐실행가능한배당제외정책이아니다.2026의양의차이는안정적우위라고말하기어렵다.',
        '## 조건차이가새/상실배당격차를설명하는가',
        '연도×지역공통셀에서양집단각5건이상기준을적용하고같은가중치로표준화한전체배당은새22.11배·상실34.99배로차이가남았다.연도×거리에서도지원281건에서22.11대36.76배였다.2026거리공통셀은2개·58건으로지원이제한됐다.연도×지역×거리×등급을동시에맞춘공통셀은0개라완전동조건비교는못했다.',
        '2025새/상실의축예상입상확률은평균64.8/64.4%,2026은65.4/65.3%로가까웠다.과거이력수나5·6위확률차도뚜렷한단일분리기준을보이지않았다.이는탐색평균이며변수가효과없다는검정도아니다.조건에맞춘새분류기·필터를만들어성능을올렸다고주장하지않는다.',
        '## 사례',
        examples,
        '2026최고새적중136.9배는1400m인데그거리전체환급차는여전히−281,600원이다.개별고배당사례나거리표중한쪽만골라성공요인으로설명하지않는다.',
        '## 판단과검증',
        '이번비교에서2026의개선은부산중거리·장거리및낮은배당구간의추가적중이손실을상쇄한결과다.2025에는그상쇄가부족했다.다음검증의초점은축입상상태에서모델2위이탈·3~5위동반입상을얼마나덜평가하는지,또외부6~8위후보와어떻게배분할지다.이번진단을근거로특정거리·등급·앞선확률구간에서구매정책을바꾸지는않았다.',
        '원58P의ROI차이95%구간은2025−12.91~+5.75%p,2026−12.38~+14.67%p로모두0을포함했다.이번은그같은반복개발기간의사후조건분해다.2026부분연도·당시조교/명단/부중공개시각미인증·표본구성과다수소표본셀을고려해야하며인과효과나새미래수익을확인한것은아니다.',
        f'정답49,596장·변경369경주가산형분포와모델순위·Decimal전체/연도별정산·52개분할항등식·실제통과조4,133전체명단을독립코드로검증했다.실제전개4,048확인·85미상을유지했고연간구매액정규화와꼬리분해도일치했다.원천해시는그대로다.신규학습0·DB접속/쓰기0·운영변경0·외부수집0이다.',
        '[고정계획](PLAN.md) · [분석](analyze.py) · [정규화·민감도](supplement.py) · [독립검산](verify.py) · [전체조건표](outputs/condition_summary.csv) · [연간기여](outputs/annual_contributions.csv) · [225/144변경경주](outputs/changed_cases.csv) · [배당구간분해](outputs/tail_decomposition.csv) · [최고배당민감도](outputs/cohort_sensitivity.csv) · [공통셀](outputs/common_cell_standardization.csv) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)',
        ''
    ])
    (a.HERE/'README.md').write_text(text)
    CENTRAL.write_text('\n\n'.join(['# 연구58Q personal_t2 새225·상실144',
        '2026-10-25 · 사후진단 · 학습/운영변경없음.',annual,
        '2025:1600m−202,600원·3등급−333,800원·6등급−243,300원.2026:부산+331,200원이서울−275,500원상쇄;부산1600/1800m새12·상실0으로+348,400원.지역/거리/등급금액은겹치는별도분해로합산하지않는다.',
        bands,
        '2026도고배당상실은해결되지않음.50배미만기여+7.54%p가50배이상−6.68%p상쇄.최대새적중136.9배1건을양쪽에서제외하면환급차−81,200원으로반전해안정적수익우위미확정.',
        '사전앞선확률합2~<3은2026+304,600원이나3+는−257,000원(새2/상실2)으로소표본.실제S1F첫묶음1두는2025−432,800/2026+175,300원,사후관측이며전개예측성능과혼동하지않음.4,048관측·85미상.',
        '2024/25당시연구버전·2026운영동일가중치.반복개발기간·부분연도·공개시각미인증유지.전티켓/금액/통과조검산통과.',
        '[원문](../20261025_personal_t2_gain_loss_v1/README.md) · [전체표](../20261025_personal_t2_gain_loss_v1/outputs/condition_summary.csv) · [검증](../20261025_personal_t2_gain_loss_v1/outputs/verification.json)', '']))
    (a.HERE/'PUBLICATION.md').write_text('# 게시준비: personal_t2 연도별환급차진단\n\n같은4,133경주에서새225·상실144를비교했다.2025환급−303,900원은1600m·3/6등급고배당상실이컸다.2026+55,700원은부산1600/1800m와1300m추가적중의상쇄결과였다.2026에도50배이상구간은손실이었고50배미만이이를넘었다.최대새적중136.9배한건을양쪽에서제외하면차이가마이너스로바뀌어안정적수익우위는미확정이다.사전예상앞선확률합과실제S1F통과조를구분했다.2024/25는당시연구버전이며사후탐색·부분연도·소표본한계를유지한다.\n\n[상세](README.md) · [검증](outputs/verification.json)\n\n게시준비만완료,공개게시/모델/DB변경없음.\n')
    for path,line in [
        (a.R/'README.md','[연구58Q personal_t2 새225·상실144](20261025_personal_t2_gain_loss_v1/README.md):2025고배당상실·2026부산1600/1800추가적중의상쇄.2026+55,700원은최대새적중1건제외시반전,사전/사후전개구분.'),
        (a.R/'conclusions/README.md','[연구58Q personal_t2 연도별득실조건](58Q_PERSONAL_T2_GAIN_LOSS.md):2025−303,900원·2026+55,700원.고배당상실남고낮은배당회복,수익우위불확실.'),
        (a.R/'conclusions/SOURCES.md','[연구58Q](58Q_PERSONAL_T2_GAIN_LOSS.md) · [원문](../20261025_personal_t2_gain_loss_v1/README.md) · [원천해시](../20261025_personal_t2_gain_loss_v1/outputs/input_manifest.json) · [검증](../20261025_personal_t2_gain_loss_v1/outputs/verification.json).58P동결티켓·점수·확정배당과기존통과조사용,신규학습/DB접속없음.')]:
        old=path.read_text()
        if MARKER not in old:path.write_text(old+'\n\n'+MARKER+'\n'+line+'\n')
    sm=a.R/'conclusions/source_manifest.json';m=json.loads(sm.read_text())
    paths=[CENTRAL,a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'supplement.py',a.HERE/'verify.py',
           a.HERE/'finalize.py',a.OUT/'condition_summary.csv',a.OUT/'tail_decomposition.csv',
           a.OUT/'verification.json',a.OUT/'input_manifest.json']
    additions={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inventory=a.OUT/'artifact_inventory.json'
    if not inventory.exists():a.save('artifact_inventory.json',{})
    before=json.loads((a.OUT/'publication_before.json').read_text());log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(25):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CENTRAL])
        total=sum(p.stat().st_size for p in files)
        line=f'| 2026-10-25 | 58Q personal_t2 새225·상실144 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_personal_t2_gain_loss_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58Q personal_t2 새225·상실144' not in x)+'\n'+line+'\n')
        modified=[dict(path=p,before_bytes=x['bytes'],after_bytes=(a.ROOT/p).stat().st_size,
                       delta_bytes=(a.ROOT/p).stat().st_size-x['bytes']) for p,x in before.items()]
        obj=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(a.ROOT)),bytes=p.stat().st_size,sha256=None if p==inventory else a.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),
            shared_delta_scope='Task-start to current shared-file size differences; includes concurrent sessions, not exclusive attribution.',new_models=0)
        old=inventory.read_text();a.save('artifact_inventory.json',obj)
        if old==inventory.read_text():break
    else:raise AssertionError('inventory failed convergence')
    assert sum(p.stat().st_size for p in files)==obj['new_bytes']<2*1048576
    for path in [a.HERE/'README.md',a.HERE/'PUBLICATION.md',CENTRAL]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' not in link:assert (path.parent/link).exists(),(path,link)
    for row in obj['files']:
        path=a.ROOT/row['path'];assert path.stat().st_size==row['bytes']
        if row['sha256']:assert a.sha(path)==row['sha256']
    for path,h in additions.items():assert a.sha(a.ROOT/path)==h
    print(json.dumps({k:v for k,v in obj.items() if k not in ['files','modified_files']},ensure_ascii=False))
    print(json.dumps(max(obj['files'],key=lambda x:x['bytes']),ensure_ascii=False))


if __name__=='__main__':main()
