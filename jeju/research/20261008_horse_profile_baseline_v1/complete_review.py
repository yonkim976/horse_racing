"""Add material subgroup interpretation; preserve generated reports and frozen fits."""
import json
import re
from pathlib import Path
from urllib.parse import unquote
import pandas as pd
import run as e


def main():
    h=e.HERE;o=e.OUT;c=h.parent/'conclusions'
    assert json.loads((o/'final_verification.json').read_text())['passed']
    e.check_prepared()
    r=pd.read_csv(o/'runner_metrics.csv')
    q=r[r.group.eq('observed_starts')&r.value.eq('0')].set_index('variant')
    a=q.loc['J0'];b=q.loc['uniform']
    note=f'''# 無이력 말 평가와 첫 비교의 해석

전체에서는 J0가 균등 확률보다 좋은 결과를 냈지만, **보유 과거 출전 이력 0인 {int(a.rows):,}출전에서 J0의 확률 오차는 더 컸다.** 이 집단을 제외한 전체 지표만으로 신마 예측이 해결됐다고 설명하지 않는다. 과거 이력 0은 공식 신마 판정과 다르다.

| 관측 출전 이력 0인 말 | Top3 log loss | Brier | 평균 예측 확률 | 실제 입상 비율 |
|---|---|---|---|---|
| 균등 확률 | {b.log_loss:.6f} | {b.brier:.6f} | {b.predicted*100:.2f}% | {b.actual*100:.2f}% |
| J0 | {a.log_loss:.6f} | {a.brier:.6f} | {a.predicted*100:.2f}% | {a.actual*100:.2f}% |

이 표는 해당 말만의 runner 균등 지표다. 전체 보고서의 경주 균등 지표와 가중 방식이 다르고, 집단 간 실제 입상률 차이에는 거리·등급·편성 구성이 포함된다. 집단별 차이의 별도 신뢰구간이나 무이력 전용 대체 확률 정책은 이번에 적합하지 않았다. 현재 확률을 임의로 위로 올리면 경주 내 합 3·다른 말 확률까지 함께 바뀌므로 새 비교 없이 적용하지 않는다.

J1은 J0 대비 전체 log loss·Brier가 조금 컸지만 차이의 95% 구간에 0이 포함됐다. 최고·편차·추세가 무용하다고 확정한 결과가 아니라, 이번 묶음·모델·시간 분할에서 추가 개선을 확인하지 못한 결과다. 다음 기준선은 J0로 두고 부담중량 추가 비교에서 무이력·저경력·거리 전환 표본을 계속 분리한다. 주행심사처럼 다른 정보 묶음도 이후 같은 표본·평가 규칙에서 검증한다.

균등 모델의 상위 후보·6조합 동점은 출발번호 오름차순으로 정렬했다. 따라서 균등 확률의 6조합 적중률은 무작위 6조합의 기대 적중률이 아니다. J0/J1과 동일한 정렬 정책을 사용한 진단 기준이다. 특히 단거리 번호 연관이 있는 자료에서 이 차이를 구분해야 한다.

## 저장과 검산의 후속 처리

학습 전 첫 평가표 저장은 인덱스로 옮긴 ID 열을 다시 열로 찾는 오류로 멈췄다. 초기 코드·부분 산출물은 그대로 보존하고 ID를 유지하는 수정본에서 학습 전 검증을 통과했다. [준비 재시도 기록](PREPARATION_RETRY.json). 모델 성능을 본 후 입력·모형을 수정한 재시도가 아니다.

첫 별도 조합 검산에서는 Python의 내장 sum과 NumPy의 세 항 덧셈이 약 4.44e−16까지 달라 거의 같은 점수의 조합 순위가 바뀌었다. 검산 코드를 동결된 계약과 같은 정렬 후 좌결합 덧셈으로 명시한 [verify_v2.py](verify_v2.py)에서 모델 6개 재로딩·확률·조합·지표가 모두 일치했다. 학습 모델·예측·지표는 변경하지 않았다. [검산 수정 근거](VERIFICATION_RETRY.json), [최종 검증](outputs_v2/final_verification.json). 최신 실행 순서는 준비·학습 전 검산·학습 후 **verify_v2.py final**이다.
'''
    # Use a Korean descriptive title without the character typo in the literal above.
    note=note.replace('# 無이력 말 평가와 첫 비교의 해석','# 과거 이력이 없는 말의 평가와 첫 비교 해석',1)
    e.save(o/'interpretation_review.json',dict(no_history_rows=int(a.rows),
        no_history_J0_brier=float(a.brier),no_history_uniform_brier=float(b.brier),
        no_history_J0_predicted=float(a.predicted),no_history_actual=float(a.actual),
        subgroup_uncertainty_not_estimated=True,model_or_predictions_changed=False))
    with (h/'INTERPRETATION.md').open('x',encoding='utf-8') as f:f.write(note)
    backup=o/'generated_report_before_review';backup.mkdir(exist_ok=False)
    additions={h/'README.md':f'\n\n## 과거 이력이 없는 말의 성능\n\n과거 출전 이력 0인 {int(a.rows):,}출전에서는 J0 Brier {a.brier:.6f}로 균등 확률 {b.brier:.6f}보다 오차가 컸고, 평균 입상 예측 {a.predicted*100:.2f}%는 실제 {a.actual*100:.2f}%보다 낮았다. 전체 개선만으로 무이력 말 평가가 해결됐다고 설명하지 않는다. [무이력 집단 해석과 동점·검산 후속 처리](INTERPRETATION.md)를 함께 본다. 다음 실험에서도 이 집단을 유지해 따로 확인한다.\n',
        c/'07_HORSE_PROFILE_BASELINE.md':f'\n\n무이력 {int(a.rows):,}출전에서는 J0 Brier {a.brier:.6f}가 균등 확률 {b.brier:.6f}보다 컸다. 이 집단의 평균 예측 {a.predicted*100:.2f}%와 실제 입상 {a.actual*100:.2f}% 차이를 별도 약점으로 남긴다. [추가 해석](../20261008_horse_profile_baseline_v1/INTERPRETATION.md).\n'}
    for p,addition in additions.items():
        old=p.read_text(encoding='utf-8')
        with (backup/p.name).open('x',encoding='utf-8') as f:f.write(old)
        text=old
        if p==h/'README.md':
            text=text.replace('`verify.py final`','`verify_v2.py final`')
            text=text.replace('[별도 검산 코드](verify.py)','[별도 검산 코드](verify_v2.py)')
        p.write_text(text+addition,encoding='utf-8')
    # Ensure all new document links resolve locally; no network access.
    checked=[]
    for p in [h/'README.md',h/'CONTRACT.md',h/'EXAMPLE_SCORECARDS.md',h/'INTERPRETATION.md',c/'07_HORSE_PROFILE_BASELINE.md']:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if target.startswith(('http:','https:','#')):continue
            dest=(p.parent/unquote(target.split('#')[0])).resolve()
            assert dest.exists(),(p,target)
            checked.append(str(dest.relative_to(e.ROOT)))
    # The known artifact hashes, including frozen training code, remain unchanged.
    e.check_prepared();e.check_protected(json.loads((o/'prepared_lock.json').read_text())['protected'])
    e.save(o/'delivery_verification.json',dict(passed=True,local_document_links_checked=len(checked),
         fixed_models_unchanged=True,conclusion_updated=True,subgroup_weakness_reported=True))
    sm=c/'source_manifest.json';manifest=json.loads(sm.read_text());entries={x['path']:x for x in manifest['files']}
    files=[p for p in h.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='ARTIFACT_INVENTORY.json']
    files += [c/'07_HORSE_PROFILE_BASELINE.md']
    for p in files:
        rel=str(p.relative_to(e.ROOT));entries[rel]=dict(path=rel,role='horse_profile_baseline_research' if p.is_relative_to(h) else 'conclusion_or_management',sha256=e.sha(p),bytes=p.stat().st_size)
    manifest['files']=list(entries.values());sm.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    for p in files:assert e.sha(p)==entries[str(p.relative_to(e.ROOT))]['sha256']
    old_inventory=h/'ARTIFACT_INVENTORY.json'
    with (backup/'ARTIFACT_INVENTORY.json').open('x') as f:f.write(old_inventory.read_text())
    inventory=[]
    for p in sorted(h.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p!=old_inventory:
            inventory.append(dict(path=str(p.relative_to(e.ROOT)),bytes=p.stat().st_size,sha256=e.sha(p)))
    for n in ['README.md','SOURCES.md','03_FOUNDATION.md','07_HORSE_PROFILE_BASELINE.md','research_register.json','source_manifest.json']:
        p=c/n;inventory.append(dict(path=str(p.relative_to(e.ROOT)),bytes=p.stat().st_size,sha256=e.sha(p),role='updated_conclusion'))
    old_inventory.write_text(json.dumps(dict(files=inventory,new_research_bytes=sum(p.stat().st_size for p in h.rglob('*') if p.is_file()),
        previous_versions_preserved=True,self_hash_excluded=True),ensure_ascii=False,indent=2)+'\n')
    print('Delivery checks passed; no-history weakness and latest verifier documented',len(checked),'links')


if __name__=='__main__':main()
