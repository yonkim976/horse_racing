"""Check publication and register an independent retrospective prediction study."""

import json
import re

import pandas as pd

from prepare import DB,HERE,OUT,ROOT,dump,sha

CENTRAL=HERE.parent/'conclusions'
CONCLUSION='59_DEBUT_TRIAL_PREDICTION.md'
MARKER='<!-- debut_trial_prediction_20261025 -->'


def guarded(path,text,mtime):
    assert path.stat().st_mtime_ns==mtime,'Shared index changed; reread before retry'
    path.write_text(text)


def main():
    audit=json.loads((OUT/'source_audit.json').read_text())
    assert sha(DB)==audit['inputs'][0]['sha256']
    assert json.loads((OUT/'verification.json').read_text())['passed']
    web=json.loads((OUT/'web_research.json').read_text())
    assert web['publication']==(HERE/'PUBLICATION.md').read_text()
    files={'metrics':'metrics.csv','high_groups':'high_group.csv','intervals':'paired_loss_intervals.csv',
           'time_bands':'heldout_time_bands.csv','same_debutant_choice':'same_debutant_choice.csv'}
    for key,name in files.items():
        a=pd.read_csv(OUT/name);b=pd.DataFrame(web[key])[a.columns]
        pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-12,rtol=1e-12)
    cohort=pd.read_parquet(OUT/'debut_cohort.parquet')
    assert cohort.domestic.sum()==8929 and cohort.primary_eligible.sum()==8884
    assert (cohort.primary_eligible&cohort.year.ge(2024)).sum()==2573
    m=pd.read_csv(OUT/'metrics.csv')
    def metric(model,target):return m[m.algorithm.eq('lightgbm')&m.subset.eq('all')&m.model.eq(model)&m.target.eq(target)].iloc[0]
    assert round(metric('context','top3').auc,3)==.682
    assert round(metric('total','top3').auc,3)==.795
    assert round(metric('sections','top3').auc,3)==.804
    assert round(metric('sections','win').auc,3)==.808
    high=pd.read_csv(OUT/'high_group.csv')
    r=high[high.algorithm.eq('lightgbm')&high.subset.eq('all')&high.model.eq('sections')&high.target.eq('top3')].iloc[0]
    assert r.selected_n==536 and r.selected_top3==288 and r.selected_wins==117
    central=CENTRAL/CONCLUSION
    text=(HERE/'PUBLICATION.md').read_text()+f'\n\n[상세 방법](../{HERE.name}/README.md) · [출처](../{HERE.name}/SOURCES.md) · '+\
        f'[지표](../{HERE.name}/outputs/metrics.csv) · [구간의 추가 가치](../{HERE.name}/outputs/paired_loss_intervals.csv) · '+\
        f'[검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json).\n'
    if central.exists():assert '주행심사로 신마의 첫 경주' in central.read_text(),'Conclusion59 was claimed elsewhere'
    central.write_text(text)
    account=OUT/'shared_edit_accounting.json'
    owned=json.loads(account.read_text()) if account.exists() else {}
    additions={
        'README.md':f'''\n\n## 연구59 주행심사와 신마 데뷔전 예측

{MARKER}
[주행심사로 첫 경주를 얼마나 예측하는가]({CONCLUSION}): 국내산 첫 출전8,929건 중심사 지원8,884두,2024~2026 평가2,573두. 기초→전체시간·착순→구간 추가의입상AUC0.682→0.795→0.804,우승0.696→0.802→0.808. 입상 Brier16.2% 감소, 높은 평가536두의입상53.73%·우승21.83%. 전체기록 추가 가치는확인했지만 구간의추가 입상 개선95% 구간은0 포함. 최종 명단은출전표 대용이며 전향/운영 검증은미완료다. [원 보고서](../{HERE.name}/README.md). 새로운 독립 시간순 예측 연구.\n''',
        'SOURCES.md':f'''\n\n## 연구59 신마 주행심사와 첫 출전 예측

{MARKER}
[원 보고서](../{HERE.name}/README.md) · [중앙 결론]({CONCLUSION}) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json). 읽기전용 연구DB·공식 말ID·2010년 이후 첫실제출발·T-2 심사,42모형의독립 예측재현. 전향/운영 적용과구분.\n''',
    }
    for name,addition in additions.items():
        path=CENTRAL/name;before=path.stat().st_size;mtime=path.stat().st_mtime_ns;value=path.read_text()
        if MARKER not in value:
            guarded(path,value+addition,mtime);owned[str(path.relative_to(ROOT))]=path.stat().st_size-before
    path=CENTRAL/'source_manifest.json';before=path.stat().st_size;mtime=path.stat().st_mtime_ns
    manifest=json.loads(path.read_text())
    for group,paths in [('sources',[HERE/name for name in ['README.md','PUBLICATION.md','SOURCES.md','PLAN.md']]),
                        ('conclusions',[central,CENTRAL/'README.md',CENTRAL/'SOURCES.md'])]:
        for p in paths:
            entry=dict(path=str(p.relative_to(ROOT)),sha256=sha(p))
            found=[x for x in manifest[group] if x['path']==entry['path']]
            if found:found[0].update(entry)
            else:manifest[group].append(entry)
    manifest['debut_trial_prediction_added']=True
    manifest['debut_trial_prediction_note']='2026-10-25 연구59 독립 시간순 후향 예측. 국내산 첫출전/심사지원2,573두 평가. 입상AUC0.804·구간 추가 불확실; 실시간 출전표 이용가능성/전향/운영 미검증.'
    manifest['updated_at']='2026-10-25'
    guarded(path,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',mtime)
    owned[str(path.relative_to(ROOT))]=owned.get(str(path.relative_to(ROOT)),0)+path.stat().st_size-before
    dump(account,owned)
    links=0
    for p in [HERE/'README.md',HERE/'PUBLICATION.md',HERE/'SOURCES.md',central]:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
            dest=(p.parent/target).resolve();assert dest.is_relative_to(ROOT),target
            assert dest.exists() or dest==OUT/'artifact_inventory.json',target
            links+=1
    dump(OUT/'execution_notes.json',dict(
        preparation_source_scope_fix='Initial assertion found venue4 in current core. Confirmed 12 Yeongcheon races; kept as prior-history evidence and excluded venue4 debut evaluation.',
        analysis_scope_unchanged=True,unused_imports_removed=True,
        additional_high_group_counts='Both outcomes reported for the SAME Top3-selected group, avoiding different target selections.',
        test_results_used_for_hyperparameter_or_threshold_selection=False))
    dump(OUT/'final_verification.json',dict(passed=True,source_hash_unchanged=True,web_tables_checked=len(files),
        publication_matches=True,document_counts_and_key_coefficients_checked=True,local_links_checked=links,
        figure_visually_inspected=True,model_files=len(json.loads((OUT/'model_manifest.json').read_text())),
        production_changed=False,prospective_validation=False))
    print('Study59 verified and registered')


if __name__=='__main__':main()
