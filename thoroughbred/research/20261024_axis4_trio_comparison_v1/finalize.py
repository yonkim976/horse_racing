"""Compact research publication and self-inclusive logical byte inventory."""
import json
from pathlib import Path
import pandas as pd
import compare as c


def table(rows):
    labels = {'operating_A_v5':'운영 A v5 계열', 'full103':'이전 연구 full103',
        'state_gbm118':'연구 기준 state_gbm118', 'state_joint118':'공동착순 신경망 state_joint118',
        'axis_failure_selected':'최신 축 이탈 위험 보조 정책'}
    lines = ['| 모델 | 경주 | 삼복6 적중 | 적중률 | 축 입상률 | 축 입상시 삼복6 성공 |',
             '|---|---:|---:|---:|---:|---:|']
    for model in labels:
        r = rows[rows.model.eq(model)].iloc[0]
        lines.append(f'| {labels[model]} | {r.races:,} | {r.hits:,} | {r.hit_rate:.2%} | {r.axis_rate:.2%} | {r.hit_given_axis:.2%} |')
    return '\n'.join(lines)


def main():
    assert json.loads((c.OUT/'verification.json').read_text())['official_ticket_checks'] > 0
    s = pd.read_csv(c.OUT/'summary.csv')
    lines = ['# 운영·최신 연구 모델의 축+4 삼복승 6조합 비교', '',
        '2026-10-24 · 연구58H · 서울·부산 · 기존 예측 재채점 · 신규 학습0 · 운영 변경 없음.', '',
        '**같은 출전명단4,133경주의 적중률은 운영26.74%, 연구 기준27.12%, 최신 위험보조27.20%다. 연구안의 운영 대비 차이는 확정 개선이 아니다. 취소마를 제거한 더 넓은4,769경주에서는 운영27.80%, 연구 기준27.72%로 순서가 바뀐다.**', '',
        '## 현재 모델의 구분', '',
        '- 운영 등록부: `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`. A=v5 2026H2 rolling_all, B/C=v4 2026 top3_growth_strength, 순서=v2 2026 H3_relative. resolver의 경로·해시 검증 통과. 운영은 full103 또는 state_gbm이 아니다.',
        '- 연구 기준: 58C의 state_gbm118. 능력·과거 초반/종반89열+시간순 동적 상태29열을 입력한 LightGBM이다. state_joint118은 같은118입력의 공동착순 신경망 비교 후보다.',
        '- 최신 실험: 20261024_axis_failure_risk_v1의 축 이탈 위험 보조. 기존 state_gbm의 축 입상/이탈 조건부 분포를 전년도 선택lambda로 재가중한다. 원 연구의 위험/축 개선조건 모두 실패해 기준 교체 근거가 없다. 이번 비교 시점에는 README가 없었고 검증·의사결정·예측 산출물을 직접 확인했다.', '',
        '## 티켓 정책과 정답', '',
        '말별 Top3 주변확률1위가 축이고 차순위4두가 상대다. 소수12자리 동률은 마번으로 정렬한다. 축A와 상대B/C/D/E이면 A-B-C, A-B-D, A-B-E, A-C-D, A-C-E, A-D-E의6장이다. 축이 실제 Top3이고 실제 나머지 입상2두가 상대4두 안에 있어야 적중한다. 무조건 상위5두만 포함하면 적중하는 정책이나 B의 자유 삼복확률 상위6장 정책과 다르다.', '',
        '이번 숫자는 여섯 장 중 하나 이상 맞힌 과거 경주 비율이다. 새 경주의 보장 확률이나 말별 확률의 곱이 아니다. 운영 B/C는 현재 구성 설명에 포함하지만 이번 티켓 순위에는 A만 사용한다.', '',
        '## 주 비교: 명단이 정확히 같은4,133경주', '',
        '2024-01-05~2026-09-13, 서울2,356·부산1,777경주. 운영 저장 결과의 각 시기 v5 rolling_all 모델을 사용했다. 현행2026H2 가중치를2024/2025 학습 구간에 재적용한 성적이 아니다. 당시 계열과 현재 등록 모델의 차이를 유지한다.', '',
        table(s[s.scope.eq('identical_roster') & s.subgroup.eq('all')]), '',
        '연도별 동일분모는2024년1,530·2025년1,522·2026년1,081경주다.', '',
        '| 모델 | 2024 | 2025 | 2026(~9/13) |', '|---|---:|---:|---:|']
    for model in ['operating_A_v5','full103','state_gbm118','state_joint118','axis_failure_selected']:
        g = s[s.scope.eq('identical_roster') & s.model.eq(model)].set_index('subgroup')
        lines.append('| '+model+' | '+' | '.join(f'{g.loc[str(y),"hit_rate"]:.2%} ({int(g.loc[str(y),"hits"])})' for y in [2024,2025,2026])+' |')
    lines += ['', '## 差와 불확실성'.replace('差','차이'), '',
        '날짜403개를 함께 재표집한 paired bootstrap2,000회다. 연구 기준−운영은+0.39%p,95%구간−0.80~+1.52%p. 위험보조−운영은+0.46%p,−0.73~+1.61%p. 위험보조−연구 기준은+0.07%p,−0.19~+0.34%p다. 신경망−운영도+0.12%p,−1.09~+1.31%p로0을 포함한다. 지표별 구간이며 다중비교 보정이나 같은 말의 장기 상관을 완전히 처리한 구간은 아니다.', '',
        '연구 기준은 운영보다 새로339경주를 맞히고 기존 적중323경주를 잃어 순증16이다. 위험보조는 연구 기준보다 새로16·상실13으로 순증3이다. 축 입상률이 약63%여도 상대 두 마리까지 포착해야 하므로 삼복6은 약27%로 낮아진다.', '',
        '現행2026H2 가중치를 사용한2026-07-01~09-13의 동일명단304경주만 보면 운영87/304=28.62%, 연구 기준88/304=28.95%, 신경망84/304=27.63%, 위험보조88/304=28.95%다. 운영 학습 자료에 포함된 과거 시점에 현행 가중치를 적용하지 않고, 저장 예측의2026H2 구간만 구분한 기술통계다. 연구 기준과 차이는 단1경주로 작다.'.replace('現행','현행'), '',
        '## 취소마 명단 차이를 다룬 보조 분석', '',
        '운영 저장 결과4,804경주와 연구4,799경주 중 겹치는경주는4,769다. 그중636경주에서 운영 저장 명단에 연구 명단 밖의 말이 있다. 이 말을 제거한 뒤 운영의 저장 A 주변확률로 다시 순위를 매긴 민감도이며, 취소 후 모델 재추론 또는 공동분포 재계산이 아니다. 주 비교의 정확히 같은 명단 표본은 이런 선택 때문에 전체 경주와 구성 차이가 있다.', '',
        table(s[s.scope.eq('matched_starters_sensitivity') & s.subgroup.eq('all')]), '',
        '운영의 취소마 제거 전 원래 선택 성적을 이 민감도 성적으로 대체하지 않는다. 완전한 최종 출전명단 계약을 맞춘 재추론 없이 전체 운영 우열을 확정할 수 없다. 연구 전체4,799경주에서는 full103 1,234(25.71%), state_gbm1,329(27.69%), state_joint1,325(27.61%), 위험보조1,327(27.65%)다. 이 다른 분모를 운영 표와 직접 비교하지 않는다.', '',
        '## 검증과 적용 범위', '',
        '공식 결과 감사 파일의 finish_order로 모든6장 선택을 다시 채점하고, 연구50,754행의 Top3 정답, 원래 운영 최고선택4,133건, 연구/위험모델의 저장 축14,397건과 대조했다. 표·날짜bootstrap 재계산, 원천 해시 불변도 확인했다. 신규 학습·DB 쓰기·배포·운영 승격은 없다.', '',
        '반복 사용한2024~2026 역사적 개발 자료이며 독립 미래 검증이 아니다. 연구 모집단의 podium동착 제외, 명단·부담중량 공시시각 미확인, 원천/전처리/학습기간 차이를 유지한다. 2026년은 부분연도다. 서로 다른 계열/자료/학습 일정 전체의 비교여서 알고리즘 하나의 인과효과가 아니다. 배당·구매금액·환급·수익률은 평가하지 않았다.', '',
        '[계획](PLAN.md) · [재현 코드](compare.py) · [검산](verify.py) · [전체 표](outputs/summary.csv) · [차이 구간](outputs/paired_differences.csv) · [검증 기록](outputs/verification.json) · [용량](outputs/artifact_inventory.json)', '']
    text = '\n'.join(lines)
    (c.HERE/'README.md').write_text(text)
    (c.HERE/'PUBLICATION.md').write_text('# 게시 준비 요약: 축+4 삼복6\n\n같은4,133경주에서 운영26.74%, 연구 기준27.12%, 최신 위험보조27.20%였다. 더 넓은 취소마 제거 민감도에서는 운영27.80%, 연구27.72%로 순서가 바뀌었다. 안정적인 운영 대비 개선 근거가 없으므로 운영을 유지한다. 약63%의 축 입상률이 삼복6에서는 약27%로 낮아지는 이유는 나머지 입상2두도 상대4두에서 찾아야 하기 때문이다. 반복 개발 자료이며 미래·수익률 보장은 아니다. 공개 게시나 배포는 하지 않았다.\n')
    central = c.R/'conclusions/58H_AXIS_FOUR_TRIO_COMPARISON.md'
    central.write_text('# 축+4 삼복승6: 운영과 최신 연구 비교\n\n2026-10-24 · 연구58H · 운영 변경 없음.\n\n'+
        table(s[s.scope.eq('identical_roster') & s.subgroup.eq('all')])+ '\n\n출전명단이 정확히 같은2024-01-05~2026-09-13의4,133경주다. 운영은 현재 등록 모델과 같은 v5 rolling_all 계열의 당시 저장 예측이다. 연구 기준의+0.39%p 차이95%구간−0.80~+1.52%p로 우위는 미확정이다. 취소마 제거 후4,769경주에서는 운영27.80%, 연구 기준27.72%로 순서가 바뀐다. 최신 위험보조도 원 연구의 개선 조건을 통과하지 못했다.\n\n'+
        '[원문](../20261024_axis4_trio_comparison_v1/README.md) · [전체 표](../20261024_axis4_trio_comparison_v1/outputs/summary.csv) · [검증](../20261024_axis4_trio_comparison_v1/outputs/verification.json)\n')
    marker = '<!-- axis4_trio_20261024 -->'
    for path, line in [
        (c.R/'README.md','[연구58H 운영·최신 연구 축+4 삼복6](20261024_axis4_trio_comparison_v1/README.md): 동일4,133경주 운영26.74%·연구 기준27.12%, 우위 미확정。'.replace('。','.')),
        (c.R/'conclusions/README.md','[연구58H 축+4 삼복6](58H_AXIS_FOUR_TRIO_COMPARISON.md): 운영26.74%·연구 기준27.12%, 명단 민감도에서 순서 역전.'),
        (c.R/'conclusions/SOURCES.md','[연구58H](58H_AXIS_FOUR_TRIO_COMPARISON.md) · [원문](../20261024_axis4_trio_comparison_v1/README.md) · [출처 해시](../20261024_axis4_trio_comparison_v1/outputs/input_manifest.json) · [검증](../20261024_axis4_trio_comparison_v1/outputs/verification.json). 신규 학습 없이 운영 A 저장 예측과 연구 후보를 고정6장 정책으로 재채점.')]:
        old = path.read_text()
        if marker not in old:
            path.write_text(old+'\n\n'+marker+'\n'+line+'\n')
    sm = c.R/'conclusions/source_manifest.json'
    manifest = json.loads(sm.read_text())
    selected = [c.HERE/'README.md', c.HERE/'PLAN.md', c.HERE/'compare.py', c.HERE/'verify.py',
        c.OUT/'summary.csv', c.OUT/'paired_differences.csv', c.OUT/'verification.json', central]
    additions = {str(p.relative_to(c.ROOT)): c.sha(p) for p in selected}
    manifest['sources'] = [x for x in manifest['sources'] if x['path'] not in additions]
    manifest['sources'] += [dict(path=p, sha256=h) for p,h in additions.items()]
    sm.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    inv = c.OUT/'artifact_inventory.json'
    log = c.R/'ARTIFACT_SIZE_LOG.md'
    before = json.loads((c.OUT/'publication_before.json').read_text())
    if not inv.exists():
        c.save(inv, {})
    for _ in range(20):
        files = sorted([p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[central])
        total = sum(p.stat().st_size for p in files)
        entry = f'| 2026-10-24 | 58H 축+4 삼복6 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261024_axis4_trio_comparison_v1/outputs/artifact_inventory.json) |'
        lines = [x for x in log.read_text().splitlines() if '58H 축+4 삼복6' not in x]
        log.write_text('\n'.join(lines)+'\n'+entry+'\n')
        modified = [{'path':name, 'before_bytes':v['bytes'], 'after_bytes':(c.ROOT/name).stat().st_size,
            'delta_bytes':(c.ROOT/name).stat().st_size-v['bytes']} for name,v in before.items()]
        value = dict(new_files=len(files), new_bytes=total, new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(c.ROOT)), bytes=p.stat().st_size,
                sha256=c.sha(p) if p != inv else None) for p in files], modified_files=modified,
            modified_delta_bytes=sum(x['delta_bytes'] for x in modified), new_models=0)
        old = inv.read_text()
        c.save(inv, value)
        if inv.read_text() == old:
            break
    else:
        raise AssertionError('Inventory did not converge')
    assert sum(p.stat().st_size for p in files) == value['new_bytes'] < 5_000_000
    for p in selected:
        assert c.sha(p) == additions[str(p.relative_to(c.ROOT))]
    print(json.dumps({k:v for k,v in value.items() if k != 'files' and k != 'modified_files'}, indent=2))


if __name__ == '__main__':
    main()
