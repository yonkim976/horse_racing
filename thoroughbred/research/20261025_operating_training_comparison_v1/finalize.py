"""Audited comparison report, central registration and self-inclusive storage log."""
import json,re
import compare as c

CONCLUSION=c.R/'conclusions/58K_OPERATING_TRAINING_COMPARISON.md'
MARKER='operating_training_comparison_20261025';INV=c.OUT/'artifact_inventory.json'
BEFORE=json.loads((c.OUT/'preexisting_files.json').read_text())
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def pct(x):return f'{100*x:.2f}%'
def pp(x):return f'{100*x:+.2f}%p'
def interval(x):return f'{100*x[0]:+.2f}~{100*x[1]:+.2f}%p'
def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->'
    old=path.read_text();h=c.sha(path);block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end);new=old[:a]+block+old[b:]
    else:new=old+'\n\n'+block+'\n'
    assert c.sha(path)==h,'Concurrent write before append';path.write_text(new)
def manifest():
    path=c.R/'conclusions/source_manifest.json';h=c.sha(path);v=json.loads(path.read_text())
    sources=[p for p in c.HERE.rglob('*') if p.is_file() and p.suffix in {'.md','.py','.json'} and p!=INV]
    for key,paths in [('sources',sources),('conclusions',[CONCLUSION])]:
        index={x['path']:i for i,x in enumerate(v[key])}
        for p in sorted(paths):
            x={'path':str(p.relative_to(c.ROOT)),'sha256':c.sha(p)}
            if x['path'] in index:v[key][index[x['path']]]=x
            else:v[key].append(x)
    v['data_end_by_study'][MARKER]={'study':c.HERE.name,'comparison_start':'2026-01-02','comparison_end':'2026-09-13',
        'matched_races':1258,'seoul_races':733,'busan_races':525,'operating_profile':'thoroughbred-main-20260919-v1',
        'candidate':'personal_t2','new_models':0,'actual_live_publications':False,'new_future_validation':False,'production_changed':False}
    v['updated_at']='2026-10-25';assert c.sha(path)==h,'Concurrent manifest write';dump(path,v)
def inventory():
    paths=[p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CONCLUSION]
    files=[{'path':str(p.relative_to(c.ROOT)),'bytes':p.stat().st_size} for p in sorted(paths)]
    concurrent=json.loads((c.OUT/'concurrent_updates.json').read_text());changed=[]
    for name,old in BEFORE.items():
        p=c.ROOT/name;delta=p.stat().st_size-old['bytes'];external=concurrent[name]['external_delta_bytes']
        changed.append({'path':name,'bytes_before':old['bytes'],'bytes_after':p.stat().st_size,'delta_bytes':delta,
            'external_delta_bytes':external,'task_delta_bytes':delta-external,'sha256_before':old['sha256'],'sha256_after':c.sha(p)})
    total=sum(x['bytes'] for x in files);assert total+c.PREVIOUS_BYTES<300_000_000
    s={'new_file_count':len(files),'new_bytes':total,'new_mib':total/1048576,'largest_file':max(files,key=lambda x:x['bytes']),
        'modified_file_count':5,'modified_final_bytes':sum(x['bytes_after'] for x in changed),
        'modified_delta_bytes':sum(x['delta_bytes'] for x in changed),'modified_external_delta_bytes':sum(x['external_delta_bytes'] for x in changed),
        'modified_task_delta_bytes':sum(x['task_delta_bytes'] for x in changed),'previous_nine_studies_new_bytes':c.PREVIOUS_BYTES,
        'combined_new_bytes':total+c.PREVIOUS_BYTES}
    return {'study':c.HERE.name,'status':'complete','summary':s,'new_files':files,'modified_existing_files':changed,
        'self_inclusive':True,'units':'logical bytes;1MiB=1048576bytes','excluded':'Referenced DB/model/feature/prediction assets and transient caches'}
def indexes(note,s):
    title='연구58K 운영 모델과 조교 변화 모델 비교'
    upsert(c.R/'README.md',f'[{title}]({c.HERE.name}/README.md): {note}')
    upsert(c.R/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(c.R/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · '
        f'[계획](../{c.HERE.name}/PLAN.md) · [결과](../{c.HERE.name}/outputs/results.json) · '
        f'[표본감사](../{c.HERE.name}/outputs/cohort_audit.json) · [검증](../{c.HERE.name}/outputs/verification.json). {note}')
    upsert(c.R/'ARTIFACT_SIZE_LOG.md','| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-25 | 운영·조교 변화 모델 직접 비교 | {s["new_file_count"]} | {s["new_bytes"]} | {s["new_mib"]:.6f} | '
        f'5 | {s["modified_final_bytes"]} | {s["modified_delta_bytes"]:+d} | [명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{s["largest_file"]["path"]}` {s["largest_file"]["bytes"]:,} bytes. 기존 모델·예측 참조, 신규 학습0. '
        f'연속10연구 합계 {s["combined_new_bytes"]:,} / 300,000,000bytes. 중앙 수정 중 다른 작업 순증 {s["modified_external_delta_bytes"]:,}bytes 보존, '
        f'이번 작업 순증 {s["modified_task_delta_bytes"]:,}bytes.')
def write_reports():
    c.check();verification=json.loads((c.OUT/'verification.json').read_text());assert verification['status']=='passed'
    result=json.loads((c.OUT/'results.json').read_text());lookup={(x['variant'],x['meet']):x for x in result['groups']}
    def get(metric,meet=0,variant='personal_t2'):return lookup[variant,meet]['metrics'][metric]
    note='2026년 동일1,258경주 축 운영800(63.59%)→조교변화830(65.98%),+30건·+2.38%p(95%+0.07~+4.77). 삼복6조합384→408. 후향 재추론·운영 유지.'
    lines=['# 운영 모델과 조교 변화 모델의 직접 비교','',
        '**같은2026년 1,258경주에서 새 조교 변화 모델은 축830건(65.98%), 운영 모델은800건(63.59%)으로 새 모델이30건 앞섰다. '
        '차이는+2.38%p, 상대+3.75%다. 이 후향 표본에서는 축 개선 신호가 있지만 운영 교체를 확정할 독립 미래검증은 아니다.**','',
        '## 같은 경주에서의 축 적중','',
        '| 비교 범위 | 경주수 | 운영 모델 | 새 조교 변화 모델 | 차이 | 경주일 bootstrap95%구간 |',
        '|---|---:|---:|---:|---:|---:|']
    for meet,name in [(0,'서울·부산 전체'),(1,'서울'),(3,'부산')]:
        m=get('axis_top3',meet);lines.append(f'| {name} | {m["races"]:,} | {int(m["operating_total"]):,} / {pct(m["operating_mean"])} | '
            f'{int(m["candidate_total"]):,} / {pct(m["candidate_mean"])} | {int(m["candidate_total"]-m["operating_total"]):+d}건 / {pp(m["difference"])} | {interval(m["ci95"])} |')
    lines+=['', '전체 축 선택이443경주에서 달랐다. 새 모델이 운영의 실패를 적중으로 바꾼146건, 운영이 적중하던 경주를 놓친116건, '
        '적중 여부가 같은181건으로 순증30건이다. 전체 구간은0을 간신히 웃돌지만 여러 번 연구한 기간이라는 점과 검정/표본 선택의 한계를 함께 본다. '
        '부산의 축 차이 구간은0을 포함한다.',
        '', '**앞서 보고한63.99%는2024–2026년 전체4,799경주 수치다. 이번65.98%는 운영과 정확히 맞춘2026년1,258경주 수치다.** '
        '평가기간과 표본이 달라 두 수치를 직접 차감하면 안 된다.',
        '', '## 차이 중 조교가 더한 부분','',
        '| 모델 | 같은1,258경주 축 적중 | 적중률 | 운영 대비 |',
        '|---|---:|---:|---:|',
        '| 현재 운영 A |800|63.59%|—|',
        '| 조교 없는 연구 상태모델58C |817|64.94%|+17건|',
        '| 조교 변화 추가58I personal_t2 |830|65.98%|+30건|','',
        '따라서 운영 대비30건 순증 전체를 조교 효과로 해석하지 않는다. 조교를 더하기 전 연구 구조가17건 앞섰고, '
        '조교 추가가 같은 표본에서13건을 더했다. 조교 추가분은+1.03%p(95%−0.23~+2.21)로 아직 확정되지 않았다. '
        '두 연구 모델의 입력·학습시점은 같고 조교 묶음만 다르지만, 운영 모델과 연구 모델 사이에는 학습시대·구조·입력·보정의 차이가 함께 있다.',
        '', '## 같은 예산의 조합 비교','',
        '삼복은 운영B, 삼쌍은 운영C의 원래 점수·온도로 계산했다. 복승/복연은 운영A 공동분포에서 같은 고정 선택 규칙으로 재구성한 보조 비교다. '
        '실제 사이트 게시/구매내역 집계는 아니다. A/B/C의 서로 다른 분포를 곱하거나 합쳐 새 분포로 만들지 않았다.',
        '', '| 선택 예산 | 운영 적중/1,258 | 새 모델 적중/1,258 | 차이 |95%구간|',
        '|---|---:|---:|---:|---:|']
    labels={'quinella_one':'복승1조합(A 재구성)','quinella_three':'복승3조합(A 재구성)','qpl_one':'복연1조합(A 재구성)',
        'qpl_three':'복연3조합(A 재구성)','trio_one':'삼복1조합(B)','trio_six':'삼복6조합(B)',
        'ordered_one':'삼쌍1조합(C)','ordered_six':'삼쌍6조합(C)'}
    for metric,label in labels.items():
        m=get(metric);lines.append(f'| {label} | {int(m["operating_total"]):,} / {pct(m["operating_mean"])} | '
            f'{int(m["candidate_total"]):,} / {pct(m["candidate_mean"])} | {int(m["candidate_total"]-m["operating_total"]):+d}건 / {pp(m["difference"])} | {interval(m["ci95"])} |')
    lines+=['', '삼복6조합은 전체384→408(+24),서울239→242(+3),부산145→166(+21)이다. '
        '부산은27.62%→31.62%,+4.00%p(95%+0.57~+7.37), 상대+14.48%지만 이는 삼복6조합의 결과다. '
        '축 적중10% 상대 개선 목표를 달성한 것은 아니다. 전체 축의 상대 개선은3.75%다.',
        '', '**모든 승식에서 우세한 것은 아니다.** 같은 규칙으로 재구성한 부산 복연3조합은314/525(59.81%)→299/525(56.95%), '
        '−15건·−2.86%p(95%−6.00~+0.19)였다. 부산 복승3조합도178→175,삼복1조합45→44로 감소했다. '
        '서울 삼쌍6조합은78→77이었다. 축 향상을 모든 조합의 향상으로 일반화하지 않는다.',
        '', '## 확률 오차','',
        '경주별 같은 가중 평균이며 작을수록 좋다. 운영A의 말별Top3,운영B의3두집합,운영C의정확한순서라는 각 목표를 해당 연구분포와 비교한다.',
        '', '| 지표 | 운영 | 새 모델 | 새−운영95%구간 |', '|---|---:|---:|---:|']
    for metric,label in [('runner_brier','말별Top3 Brier(A)'),('native_trio_logloss','3두집합 NLL(B)'),('native_ordered_logloss','순서 NLL(C)')]:
        m=get(metric);lines.append(f'| {label} | {m["operating_mean"]:.6f} | {m["candidate_mean"]:.6f} | {m["ci95"][0]:+.6f}~{m["ci95"][1]:+.6f} |')
    lines+=['', '전체 오차 점추정은 모두 감소했지만 말별Brier와3두집합NLL의 구간은0을 포함한다. 순서NLL은 이번 후향 표본에서 감소 신호가 남았다. '
        '보조지표와 지역별 결과는 다중비교 보정된 독립 확증검정이 아니다.',
        '', '## 무엇을 운영 모델이라고 비교했는가','',
        '2026-10-25 등록부의 `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`다. '
        'A는v5 `2026H2/rolling_all`, B/C는v4 `2026/top3_growth_strength`, 순서는v2 `2026/H3_relative`다. '
        '[Resolver 결과](outputs/operating_resolver.json)에서10개 등록 자산과 검증게이트를 확인했다.',
        '', '운영 가중치 A 학습은2006-01-06~2025-12-28,BC/WIN 학습은2006-01-06~2025-06-29,WIN 보정은2025-12-28까지다. '
        '새 연구 모델은2017년부터2024년 말까지 학습하고2025년으로 온도를 보정한2026년 모델이다. '
        '운영이 더 최근까지 학습한 부분도 있으며 같은 학습자료로 통제한 구조 실험은 아니다.',
        '', '[기존 운영 재추론 원장](../20261004_close_contenders_v1/README.md)의1,265경주 중 연구에 없는7경주를 제외한1,258경주를 사용했다. '
        '공통 키의 모든 경주는 마번·공식말ID·숫자착순 집합이 일치했다. 운영의 NaN/API91·92는 대조할 때만 비숫자착순0으로 통일했고 '
        '축 정답은1≤착순≤3으로 판정했다. 미완주를 적중으로 처리하지 않았다. '
        '[제외7경주와 표본 감사](outputs/cohort_audit.json)를 보존했다.',
        '', '서울733경주는2026-01-03~09-13,부산525경주는01-02~09-11이다. 현재 운영 가중치를 학습기간에 포함되는2024/25년에 소급 적용하지 않았다. '
        '반면 최근 실제 라이브 게시예측의 적중을 집계한 결과는 아니며 양쪽 모두 후향 재구성 편성의 재추론이다. '
        '반복 연구기간이고 조교 당시 공개시각·기준선의 일부 현재정보 시점 한계는 남는다.',
        '', '## 검증과 판단','',
        f'운영 원점수에서 전체3두집합과순서를 별도 산식으로 열거해 축·복승·복연·B/C 지표를 재계산했다. '
        f'운영/연구의 보존확률 및 축선택을 대조했고,운영B6조합7,548개를 기존 원장과 일치 확인했다. '
        f'검증 최대 수치오차는{verification["max_independent_numeric_error"]:.3g}다. '
        '6개 전체/지역 축 bootstrap 구간도 별도 행렬계산으로 재현했다. 모델·운영등록부·기존예측 해시는 유지됐다. '
        '[재생 검사](outputs/replay_checks.json)·[독립검증](outputs/verification.json).',
        '', '현시점 판단은 **운영 대비 축과 부산 삼복6조합에 유망한 개선 신호가 있다**는 것이다. '
        '조교 원천만으로10% 축 개선을 만들었다거나 모든 승식에서 운영을 넘었다고 말하지 않는다. '
        '새 모델을 새 경주의 사전 고정 입력으로 검증한 뒤 운영 채택을 판단할 수 있다. 이번에는 학습/운영승격/DB쓰기/실제 게시를 수행하지 않았다.',
        '', '## 재현·보존','',
        '[계획](PLAN.md) · [입력해시](outputs/input_manifest.json) · [전체결과](outputs/results.json) · '
        '[경주별수치](outputs/race_metrics.parquet) · [축 비교원장](outputs/axis_comparison.parquet) · '
        '[미게시요약](PUBLICATION.md) · [자기포함용량](outputs/artifact_inventory.json).',
        '', '```sh', '.venv/bin/python -B thoroughbred/research/20261025_operating_training_comparison_v1/verify.py', '```',
        '', '최초 실행은compare.py→verify.py→finalize.py 순서다. compare.py는 기존 입력동결·평가산출물이 있으면 덮어쓰지 않는다. '
        '검증파일을 재작성하면finalize.py로중앙해시와용량명세도갱신한다. 기존DB·가중치·전체특징·보존예측은복제하지않았다.']
    (c.HERE/'README.md').write_text('\n'.join(lines)+'\n')
    public='''# 현재 운영 모델과 비교한 새 조교 변화 모델

게시용 초안·미게시.2026-10-25. 서울·부산 연구후보이며 운영 반영 전이다.

출전마와 착순이 모두 일치하는2026년1,258경주에서 축을1두씩 선택했다. 운영 모델은800건(63.59%), 새 조교 변화 모델은830건(65.98%)으로30건 늘었다. 서울은464→486,부산은336→344건이었다. 전체 차이는+2.38%p,경주일 재표집95%구간은+0.07~+4.77%p다.

조교가 없는 연구 상태모델도817건이므로30건 전체가 조교 추가 효과는 아니다. 조교 추가분은13건이며 그 차이의 구간은0을 포함한다. 전체 축의 상대 개선은3.75%로10%목표에는 미달한다.

삼복6조합은384→408건,부산만 보면145→166건으로 증가했다. 반면 같은 규칙으로 재구성한 부산 복연3조합은314→299건으로 감소했다. 모든 승식에서 더 좋은 결과는 아니다.

이것은 실제 사전 게시 예측의 적중 집계가 아닌,같은 과거경주 재평가다. 학습범위와 입력구조가 다르고 이미 반복연구한 기간이므로 새경주의 사전입력 검증이 필요하다. 운영 교체나 게시를 수행하지 않았다.

[전체 보고서](README.md) · [표본 감사](outputs/cohort_audit.json) · [검증](outputs/verification.json)
'''
    (c.HERE/'PUBLICATION.md').write_text(public)
    conclusion='''# 현재 운영 모델과 조교 변화 연구 모델 비교

2026-10-25,연구58K. 현재 운영 프로필 thoroughbred-main-20260919-v1의등록가중치/온도를 보존된2026년 원점수에서 재생했다.

| 구분 | 공통경주 | 운영 축 | 새 조교 변화 축 | 차이 |
|---|---:|---:|---:|---:|
| 전체 |1,258|800(63.59%)|830(65.98%)|+30건,+2.38%p|
| 서울 |733|464(63.30%)|486(66.30%)|+22건,+3.00%p|
| 부산 |525|336(64.00%)|344(65.52%)|+8건,+1.52%p|

전체 축 차이의 경주일bootstrap95%구간은+0.07~+4.77%p다. 유망한 후향 개선 신호이지만,반복연구기간·당시 공개시각 미확인·서로 다른 학습시대와 입력구조를 고려해야 한다. 전체 상대개선은3.75%이며축10%목표달성은아니다. 조교없는연구기준선817건,조교추가830건이므로조교기여점추정은13건이고그구간은0을포함한다.

삼복6조합은전체384→408,부산145→166(27.62→31.62%,+4.00%p)으로증가했다. 운영B의원래온도를사용한동일6조합비교다. 반면운영A에서같은규칙으로재구성한부산복연3조합은314→299(59.81→56.95%)로감소했다. 모든승식의우위로해석하지않는다.

운영A말별Top3 Brier0.168735→0.167755,운영B집합NLL4.137058→4.113342,운영C순서NLL5.858744→5.821154로점추정은감소했다. A/B/C는서로다른목표·온도로평가했으며한분포로합치지않았다. 복승/복연은운영A분포로재구성한보조정책이며실제게시내역이아니다.

운영재추론1,265경주중연구에없는7경주를제외했고모든공통키1,258경주에서마번·말ID·숫자착순집합이일치했다. 최신운영가중치를2024/25학습기간에소급평가하지않았다. 새모델학습은없고모델/등록부/예측해시는유지됐다. 전체순열별독립계산과축·조합·구간재현검증을통과했다. 실제라이브게시성적/새미래검증/운영승격이아니다.

'''
    conclusion+=f'[원문](../{c.HERE.name}/README.md) · [표본](../{c.HERE.name}/outputs/cohort_audit.json) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json)\n'
    CONCLUSION.write_text(conclusion)
    c.save(c.OUT/'publication.json',{'status':'draft_unpublished','page_id':None,'production_changed':False})
    return note
def main():
    note=write_reports()
    if not (c.OUT/'concurrent_updates.json').exists():
        c.save(c.OUT/'concurrent_updates.json',{name:{'sha256_before_our_first_write':c.sha(c.ROOT/name),
            'external_delta_bytes':(c.ROOT/name).stat().st_size-v['bytes'],
            'handling':'Append own block to current file, merge only own source-manifest entries.'} for name,v in BEFORE.items()})
    c.save(c.OUT/'completion_checks.json',{'status':'passed','new_model_fits':0,'bounded_comparison_complete':True,
        'same_1258_races':True,'new_independent_test':False,'models_registry_and_existing_predictions_unchanged':True,
        'production_changed':False,'published':False})
    if not INV.exists():dump(INV,{})
    s=inventory()['summary']
    for _ in range(24):
        indexes(note,s);manifest();v=inventory();dump(INV,v);after=inventory()
        if v==after and s==after['summary']:break
        s=after['summary']
    else:raise RuntimeError('Inventory did not converge')
    assert json.loads(INV.read_text())==inventory();links=0
    for p in [c.HERE/'README.md',c.HERE/'PUBLICATION.md',CONCLUSION]:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' in target or target.startswith('#'):continue
            assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
    m=json.loads((c.R/'conclusions/source_manifest.json').read_text())
    own=[x for key in ['sources','conclusions'] for x in m[key] if c.HERE.name in x['path'] or x['path']==str(CONCLUSION.relative_to(c.ROOT))]
    assert all(c.sha(c.ROOT/x['path'])==x['sha256'] for x in own)
    print(json.dumps({'status':'passed',**s,'local_links_checked':links,'manifest_hashes_checked':len(own)},ensure_ascii=False))
if __name__=='__main__':main()
