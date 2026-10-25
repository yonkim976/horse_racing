"""Build the completed evidence report and self-inclusive artifact inventory."""
import json,re
from pathlib import Path
import pandas as pd
import common as c

CONCLUSION=c.RESEARCH/'conclusions/58C_DYNAMIC_RACE_MODEL.md'
MARKER='dynamic_race_model_20261022'
INVENTORY=c.OUT/'artifact_inventory.json'
LABELS={'additive89':'기존 EL89','full103':'기존 F103','strong89':'EL89 충분학습 대조군',
        'state_gbm':'동적 상태 + GBM','state_joint':'동적 상태 + 공동착순 신경망'}
BEFORE=json.loads((c.OUT/'preexisting_files.json').read_text())

def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->';old=path.read_text()
    block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end);text=old[:a]+block+old[b:]
    else:
        assert c.sha(path)==BEFORE[str(path.relative_to(c.ROOT))]['sha256'],path
        text=old+'\n\n'+block+'\n'
    path.write_text(text)

def report(results):
    ordered=['additive89','full103','strong89','state_gbm','state_joint']
    rows={r['variant']:r for r in results['overall']}
    tables=['| 모델 | 축 Top3 | 복승1 | 복승3 | 복연1 | 복연3 | 복연 적중 수/경주 | 공동착순 NLL |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for v in ordered:
        a=rows[v];m=a['means'];cells=[f"{100*m[k]:.2f}% ({a['hits'][k]:,})" for k in ['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three']]
        tables.append('| '+LABELS[v]+' | '+' | '.join(cells)+f" | {m['qpl_count']:.5f} | {m['ordered_logloss']:.5f} |")
    differences=['| 후보 / 기준 | 축 차이 %p [95%] | 복승3 차이 %p [95%] | 복연3 차이 %p [95%] |',
        '|---|---:|---:|---:|']
    for cand,ref in [('strong89','additive89'),('state_gbm','additive89'),('state_gbm','strong89'),
                     ('state_joint','additive89'),('state_joint','strong89'),('state_joint','state_gbm')]:
        m=results['comparisons'][f'{cand}_vs_{ref}']['all']['metrics'];cells=[]
        for k in ['axis_top3','quinella_three','qpl_three']:
            x=m[k];lo,hi=x['difference_ci95'];cells.append(f"{100*x['difference']:+.3f} [{lo*100:+.3f}, {hi*100:+.3f}]")
        differences.append('| '+LABELS[cand]+' / '+LABELS[ref]+' | '+' | '.join(cells)+' |')
    relative=['| 새 후보 | 축 상대변화 | 복승1 상대변화 | 복승3 상대변화 | 복연3 상대변화 |',
        '|---|---:|---:|---:|---:|']
    for cand in ['state_gbm','state_joint']:
        m=results['comparisons'][f'{cand}_vs_additive89']['all']['metrics'];cells=[]
        for k in ['axis_top3','quinella_one','quinella_three','qpl_three']:
            x=m[k];lo,hi=x['relative_percent_ci95'];cells.append(f"{x['relative_percent']:+.2f}% [{lo:+.2f}, {hi:+.2f}]")
        relative.append('| '+LABELS[cand]+' | '+' | '.join(cells)+' |')
    strata=['| 구간 | 모델 | 경주 | 축 | 복승3 | 복연3 |','|---|---|---:|---:|---:|---:|']
    allrows=pd.read_parquet(c.OUT/'race_metrics.parquet')
    old=pd.read_parquet(c.BASE/'outputs/race_metrics.parquet')
    old=old[old.scope.eq('all_starters')&old.variant.isin(['additive89','full103'])]
    allrows=pd.concat([old,allrows],ignore_index=True)
    for field in ['year','meet']:
        for val in sorted(allrows[field].unique()):
            for variant in ordered:
                g=allrows[allrows[field].eq(val)&allrows.variant.eq(variant)]
                name=str(val) if field=='year' else {1:'서울',3:'부산'}[int(val)]
                strata.append(f"| {name} | {LABELS[variant]} | {len(g):,} | {g.axis_top3.mean()*100:.2f}% | {g.quinella_three.mean()*100:.2f}% | {g.qpl_three.mean()*100:.2f}% |")
    models=[]
    for p in sorted((c.OUT/'models').glob('*/metadata.json')):models.append(json.loads(p.read_text()))
    train=['| 모델 | 지역 | 평가연도 | 선택 학습량 | 보정 온도 | 학습 초 |','|---|---|---:|---:|---:|---:|']
    for m in models:train.append(f"| {LABELS[m['variant']]} | {m['venue']} | {m['evaluation_year']} | {m.get('trees',m.get('epochs'))} | {m['temperature']:.4f} | {m['elapsed_s']:.1f} |")
    state=json.loads((c.OUT/'state_contract.json').read_text());verify=json.loads((c.OUT/'verification.json').read_text())
    decisions=results['decisions'];retained=[LABELS[k] for k,v in decisions.items() if v['retain_candidate']]
    decision=('후보 유지 조건을 만족한 모델: '+', '.join(retained)+'.') if retained else '두 새 후보 모두 사전 후보 유지 조건을 통과하지 못했다.'
    ten=[f'{LABELS[k]} {m}' for k,v in decisions.items() for m,passed in v['ten_percent_point_estimate'].items() if passed]
    ten_note=('EL89 대비 상대 10% 점추정을 넘은 항목: '+', '.join(ten)+'. 이는 미래 개선 보장이 아니다.') if ten else '두 새 후보에서 EL89 대비 상대 10% 개선을 달성한 적중 지표는 없었다.'
    q=results['comparisons']['state_joint_vs_additive89']['all']['metrics']['quinella_three']
    headline=f"공동착순 모델의 복승3 적중률은 {100*q['reference']:.2f}%→{100*q['candidate']:.2f}%, 상대 {q['relative_percent']:+.2f}%({q['net_hits']:+d}경주)였다. 개선은 확인했지만 요청한 상대 10%에는 미달했다."
    text=f'''# 동적 상태·경주 공동착순 모델 실행 결과

2026-10-22 · 연구58C · 서울·부산 · 구현·학습·역사적 개발 평가 완료 · 운영 미반영.

**{headline}** 승인받은 새 구조를 실제 구현해 정해진 예산으로 시험한 결과다. {decision}

## 비교 결과

모든 행은 같은 4,799경주·50,754출전마(2024-01-05~2026-09-20), 같은 추천 수다. 괄호는 적중 경주 수다. 복승/복연3은 세 쌍 중 하나 이상 맞은 경주 비율이다. 금전 수익률은 측정하지 않았다.

{chr(10).join(tables)}

{chr(10).join(differences)}

{chr(10).join(relative)}

차이와 상대변화 구간은 날짜 406개를 단위로 한 paired bootstrap 2,000회다. 양의 차이는 적중 증가, NLL/Brier는 낮을수록 좋다. 지표별 구간이며 다중비교 보정은 하지 않았다. 날짜가 떨어진 동일 말의 잔여 상관까지 완전히 처리한 구간은 아니다. 전체·연도·지역별 모든 지표와 F103 기준 비교는 [결과 JSON](outputs/results.json)에 있다.

## 무엇이 효과가 있었나

**현재 가장 강한 근거는 과거 상대를 반영하는 동적 상태 입력 묶음이다.** state_gbm은 충분히 학습한 strong89보다 축 +94경주, 복승3 +98경주, 복연3 +154경주다. 복승3 차이는 +2.042%p, 95% 구간 +0.996~+3.025%p로 0을 넘었다. 단순히 학습을 더 오래 한 효과만으로 설명되지 않는다. 상태 변수 중 과거 상대를 고려한 현재 거리 능력의 편성 내 차이·순위가 큰 학습 gain을 차지했지만, 변수 중요도를 독립적인 인과 효과로 해석하지 않는다. 과거 착순 정보·긴 이력·시간 갱신·불확실성을 함께 넣었으므로 어느 한 요소가 개선의 원인인지는 아직 분리하지 않았다.

**신경망이 추가로 적중을 올렸다는 근거는 아직 약하다.** state_joint는 state_gbm보다 복승3·복연3을 각각 21경주 더 맞혔지만, 복승3 차이 +0.438%p의 구간은 −0.460~+1.305%p로 0을 포함한다. 축은 18경주, 복승1은 19경주 덜 맞혔다. 공동착순 NLL은 더 낮았으나 모든 승식에서 우월한 모델은 아니다. 실용적인 다음 기준 후보는 구조가 간단한 state_gbm, 공동착순 모델은 추가 비교 후보로 보존한다.

state_joint의 복승3 상대 개선 95% 구간은 EL89 대비 +5.86~+13.98%다. 이 개발 자료에서 양의 개선 근거가 있다는 뜻이며, 최소 10% 개선을 확인했다는 뜻은 아니다. 더 강한 F103 대비 점추정은 +8.61%, strong89 대비 +8.46%다. 10% 목표에 가까운 기준만 골라 성공으로 판정하지 않는다.

## 확률 품질에서 남은 점

전체 출전마 Top3 Brier와 모든 복승 쌍의 Brier, 공동착순 NLL은 두 새 후보에서 개선됐다. 하지만 선택한 복승3 사건의 Brier는 EL89 0.194791에서 state_gbm 0.201924, state_joint 0.205531로 높아졌다. 추천 사건과 그 발생률 자체가 달라지므로 이 차이를 확률 보정 악화 하나로 단정할 수는 없다. 신경망의 평균 복승3 예측은 30.31%, 실제 적중은 31.80%로 전체 평균에서 낮게 예측했다. 고정 10구간 보정오차(ECE)는 복승3에서 EL89 1.28%p, state_gbm 1.82%p, state_joint 1.53%p였다. 축 ECE도 신경망에서 1.02→2.24%p로 커졌다. ECE는 구간과 표본에 민감한 기술통계이며 별도 확증 시험은 아니다. 적중 개선과 추천 확률 숫자의 신뢰성을 함께 검증해야 한다. [보정·입력 기술통계](outputs/descriptive_diagnostics.json).

## 실제로 새로 만든 구조

1. **동적 상태 29변수**: 당시 상대들과의 순위로 갱신한 능력·거리 반응과 공분산, 함수율 보정 기록지수의 수준·추세, 초반/종반600m 상태와 불확실성, 이력 수·불완주 완화 추정, 편성 내 상대 위치다. 과거 관측 {state['observations']:,}행·{state['historical_races']:,}경주를 시간순으로 읽고 각 예측의 T−2일까지 필터링했다. 거리 없는 2010년 부산 1경주 10행은 이력에서 제외했으며 평가 출전마를 제외한 것은 아니다.
2. **state_gbm**: 기존 EL89 입력에 같은 동적 상태 29변수를 더한 118변수 LightGBM. 이 단계는 정보를 추출하는 방법의 증분을 본다.
3. **state_joint**: 같은 118변수를 입력한 32차원·2-head attention 한 층과 두 잠재 성분, 조건부 1→2→3착 decoder. 이전에 선택된 말과 편성에 조건부한 확률을 직접 학습한다. 잠재 성분은 실제 빠른/느린 전개라는 관측 해석이 보장되지 않는다.
4. **strong89 대조군**: 기존 EL89와 입력·목표·학습률·복잡도는 같고 최대 학습 회수를 200→800으로 늘렸다. 기존 조기중단 25회는 유지했다. 학습 상한의 영향과 새 입력·구조를 구분하기 위한 대조군이다.

state_gbm과 state_joint의 비교에서는 attention뿐 아니라 함수 계열·목표함수도 달라진다. 따라서 차이를 attention 한 요소의 인과적 효과로 주장하지 않는다. 기존 유효한 요약 입력은 보존했으므로 순수 상태만 사용하는 모델의 시험도 아니다. 최초 제안의 최소 구현이며, 조교·진료·심사·시장 정보까지 결합한 완성형을 시험한 것은 아니다.

근사 Bayesian 순위 갱신과 Kalman filter를 사용했으며 TrueSkill2 원문 그대로의 구현은 아니다. 신마의 상태는 공통 사전분포에서 시작하고, 나이 등 조건은 예측 모형 입력으로 반영한다. 상태 불확실성은 근사 필터의 내부 수치이며 보정된 적중 확률이 아니다. 겹치는 종반200m를 새 상태의 독립 관측으로 추가하지 않았다. 주로빠르기, 사후 배당, 현재 경주의 실제 구간/착순은 새 입력에 없다.

## 학습과 시점 통제

지역별·평가연도별 6분할, 각 계열에서 초기학습과 재학습을 한 번씩 수행했다. 총 18개 최종 모델·36회 fit. 평가연도 Y의 초기학습은 2017..Y−3, 조기중단 검증 Y−2, 재학습 2017..Y−2, 확률 보정 Y−1이다. 말별 행을 섞어 경주를 분할하지 않는다. 평가기간 중 이미 끝난 과거 경주의 상태 갱신은 해당 예측 기준일까지 허용하는 순차 운용이다.

신경망은 최대 64 epoch, patience 10, AdamW lr .001, weight_decay .01, batch 128, dropout .1, gradient clip 1, 시드 1개다. 초기학습 자료로만 결측 대체/정규화/범주 사전을 만들고 재학습에도 고정했다. 공동착순 NLL로 epoch를 선택한다. Torch 2.10.0·safetensors 0.7.0을 로컬 가상환경에 설치해 CPU로 학습했다.

{chr(10).join(train)}

GBM은 기존 삼두 집합 확률과 순서 보정을 유지한다. 신경망은 각 단계에서 이미 뽑힌 말을 가리고 조건부 확률을 정규화하며 두 성분을 합산한다. 모든 축·복승·복연은 하나의 공동착순 분포에서 합산한다. 복연3의 선택은 기존과 같은 개별확률 상위 세 쌍이며, 선택 사건의 합집합 확률은 정확히 계산한다.

## 연도·지역

{chr(10).join(strata)}

## 검증과 한계

- 학습 전 합성 경주에서 순열 대응, padding/마스킹, teacher forcing likelihood와 전체 공동분포 일치, 유한 gradient, 미래 관측 변조 불변성, 휴양 시 불확실성 증가를 확인했다.
- 저장된 모델 재로드 예측 {verify['safe_saved_model_replayed_rows']:,}행, 최대 차이 {verify['maximum_model_replay_error']:.3g}. GBM의 보정/평가 점수 전부와 신경망의 각 분할 처음·마지막 경주를 재현했다.
- 새 티켓 {verify['independently_scored_tickets']:,}장을 원 정답으로 별도 채점하고, 전체 주변확률 합과 단조성·경주별 추천 수를 확인했다. 실제 과거 prefix 100행의 핵심 상태를 다시 생성해 차이 0을 확인했다.
- 입력·코드·DB·운영 레지스트리 해시와 모든 상태의 cutoff를 검사했다. [검증](outputs/verification.json), [학습 전 검증](outputs/preflight.json), [구동 전 보완 기록](outputs/protocol_amendments.json)을 보존했다. 외부 독립 리뷰어의 검증은 아니다.
- **2024~2026년은 반복 사용한 개발 자료이며 미래 독립 시험이 아니다.** 후기 fold에는 앞선 평가연도가 과거 학습/검증에 들어간다. 전체 설계를 경기 전에 봉인한 새 기간의 평가가 필요하다.
- 현재 부담중량 및 당시 확정 출전명단의 공개시각 한계는 기존 연구와 동일하다. 학습을 늘리거나 작은 신경망을 시험한 결과만으로 현장 성능과 10% 개선을 보장할 수 없다.

## 결론과 보관

{decision} {ten_note} 계획한 세 계열 비교 뒤 추가 시드·하이퍼파라미터 탐색을 중단했다. 개선 미달을 이유로 경주나 승식을 사후 선별하지 않았다. 운영 모델 교체·예측 게시·배포·원천 DB 쓰기는 수행하지 않았다.

[사전계획](PLAN.md) · [결과](outputs/results.json) · [미게시 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json).

선행 연구: [58](../20261022_probability_comparison_v1/README.md), [58A](../20261022_probability_followup_v1/README.md), [설계58B](../20261022_race_state_design_v1/README.md). 구조 참고: [TrueSkill2](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/03/trueskill2.pdf), [Set Transformer](https://proceedings.mlr.press/v97/lee19d.html), [PyTorch MultiheadAttention 2.10](https://docs.pytorch.org/docs/2.10/generated/torch.nn.MultiheadAttention.html). 해당 원문은 이 경마 모델의 적중 개선 근거가 아니다.
'''
    (c.HERE/'README.md').write_text(text)
    short=f'''# 동적 상태와 공동착순 모델의 실제 비교

2026-10-22 · 연구 후보 평가 · 웹사이트 미게시 · 운영 미반영.

{headline} {decision} {ten_note}

같은 서울·부산 4,799경주에 대해 말의 능력 변화를 추적하는 상태 모델과 경주 전체 착순을 직접 학습하는 작은 신경망을 만들었다. 기존 모델을 더 오래 학습한 대조군도 같이 비교했다. 축 한 두, 복승·복연 각각 세 쌍 등 추천 수를 고정했다.

{chr(10).join(tables)}

기록은 고정 평균 외에 변화 속도와 불확실성으로 표현할 수 있다. 예를 들어 같은 최근 기록이라도 휴양 기간이 길면 현재 상태 추정의 불확실성이 커진다. 그러나 그 표현의 변화가 실제 적중 개선으로 이어지는지는 별도의 검증 문제다.

이 결과는 반복 사용한 2024~2026년 개발 자료의 비교다. 미래 기간에서의 적중이나 수익을 보증하지 않는다. 운영 모델은 바꾸지 않았다. [전체 방법·검증·한계](README.md).
'''
    (c.HERE/'PUBLICATION.md').write_text(short)
    CONCLUSION.write_text(f'''# 동적 상태·경주 공동착순 모델 실행

2026-10-22 · 연구58C · 구현·학습·개발 평가 완료 · 운영 미반영.

{headline} {decision} {ten_note}

{chr(10).join(tables)}

서울·부산 동일 4,799경주·동일 추천 수. 29개 동적 상태를 기존89 입력에 더한 GBM과 같은 입력의 작은 공동착순 신경망을 실제 학습했다. 별도로 기존89의 800회 상한 대조군을 두었다. 최종18모델, 초기+재학습36회. 확률·시점·저장모델 재현 및 전체 티켓 채점을 검증했다.

2024~2026은 반복 사용한 개발자료로 미래 독립시험이 아니며, 당일 공개시점/확정명단 한계가 남는다. DB 쓰기·운영 승격·게시·배포는 하지 않았다.

[원 보고서](../{c.HERE.name}/README.md) · [사전계획](../{c.HERE.name}/PLAN.md) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json).
''')
    return headline+' '+decision

def sources():
    target=c.RESEARCH/'conclusions/source_manifest.json';m=json.loads(target.read_text())
    if MARKER not in m['data_end_by_study']:assert c.sha(target)==BEFORE[str(target.relative_to(c.ROOT))]['sha256']
    paths=[x for x in c.HERE.rglob('*') if x.is_file() and x.suffix in {'.md','.py','.json'} and x!=INVENTORY]
    for key,files in [('sources',paths),('conclusions',[CONCLUSION])]:
        lookup={x['path']:i for i,x in enumerate(m[key])}
        for p in sorted(files):
            item={'path':str(p.relative_to(c.ROOT)),'sha256':c.sha(p)}
            if item['path'] in lookup:m[key][lookup[item['path']]]=item
            else:m[key].append(item)
    m['data_end_by_study'][MARKER]={'study':c.HERE.name,'evaluation_start':'2024-01-05','evaluation_end':'2026-09-20',
        'races':4799,'runner_rows':50754,'new_models':18,'new_independent_test':False,'production_changed':False}
    m['updated_at']='2026-10-22';dump(target,m)

def inventory():
    paths=[p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CONCLUSION]
    files=[{'path':str(p.relative_to(c.ROOT)),'bytes':p.stat().st_size} for p in sorted(paths)]
    modifications=[]
    for name,old in BEFORE.items():
        p=c.ROOT/name
        modifications.append({'path':name,'bytes_before':old['bytes'],'bytes_after':p.stat().st_size,
            'delta_bytes':p.stat().st_size-old['bytes'],'sha256_before':old['sha256'],'sha256_after':c.sha(p)})
    total=sum(x['bytes'] for x in files);assert total+53_756_748<300_000_000
    s={'new_file_count':len(files),'new_bytes':total,'largest_file':max(files,key=lambda x:x['bytes']),
        'modified_file_count':5,'modified_final_bytes':sum(x['bytes_after'] for x in modifications),
        'modified_delta_bytes':sum(x['delta_bytes'] for x in modifications),
        'previous_three_studies_new_bytes':53_756_748,'combined_new_bytes':53_756_748+total}
    return {'study':c.HERE.name,'status':'complete','summary':s,'new_files':files,
        'modified_existing_files':modifications,'self_inclusive':True,'units':'logical bytes; MiB=bytes/1048576',
        'excluded':'Existing source DB/features/models and transient cache/bytecode/virtualenv dependencies'}

def indexes(note,s):
    title='연구58C 동적 상태·공동착순 모델 실행'
    upsert(c.RESEARCH/'README.md',f'[{title}]({c.HERE.name}/README.md): {note} 같은4,799경주·최종18모델·운영 유지.')
    upsert(c.RESEARCH/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(c.RESEARCH/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · '
        f'[결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json). {note}')
    upsert(c.RESEARCH/'ARTIFACT_SIZE_LOG.md',
        '| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-22 | 동적 상태·공동착순 모델 구현과 비교 | {s["new_file_count"]} | {s["new_bytes"]} | '
        f'{s["new_bytes"]/1048576:.6f} | 5 | {s["modified_final_bytes"]} | {s["modified_delta_bytes"]:+d} | '
        f'[명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{s["largest_file"]["path"]}` {s["largest_file"]["bytes"]:,} bytes. 네 연구 합계 {s["combined_new_bytes"]:,} bytes. '
        '원천/운영 유지. 설치한 가상환경 의존성은 세션 정책에 따라 산출물에서 제외.')

def main():
    c.check_inputs();v=json.loads((c.OUT/'verification.json').read_text());assert v['status']=='passed'
    results=json.loads((c.OUT/'results.json').read_text());note=report(results)
    c.save(c.OUT/'completion_checks.json',{'status':'passed','final_models':18,'new_evaluation_variants':3,
        'new_race_rows':14397,'source_database_unchanged':True,'operating_registry_unchanged':True,
        'bounded_experiment_complete':True,'additional_tuning_stopped':True,'production_changed':False})
    if not INVENTORY.exists():dump(INVENTORY,{})
    s=inventory()['summary']
    for _ in range(20):
        indexes(note,s);sources();value=inventory();dump(INVENTORY,value);after=inventory()
        if value==after and s==after['summary']:break
        s=after['summary']
    else:raise RuntimeError('Artifact inventory did not stabilize')
    assert json.loads(INVENTORY.read_text())==inventory()
    links=0
    for p in [c.HERE/'README.md',c.HERE/'PUBLICATION.md',CONCLUSION]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' in link or link.startswith('#'):continue
            assert (p.parent/link.split('#')[0]).exists(),(p,link)
            links+=1
    m=json.loads((c.RESEARCH/'conclusions/source_manifest.json').read_text())
    entries=[x for k in ['sources','conclusions'] for x in m[k] if c.HERE.name in x['path'] or x['path']==str(CONCLUSION.relative_to(c.ROOT))]
    assert all(c.sha(c.ROOT/x['path'])==x['sha256'] for x in entries)
    print(json.dumps({'status':'passed',**s,'local_links_checked':links,'source_hashes_checked':len(entries)},ensure_ascii=False))

if __name__=='__main__':main()
