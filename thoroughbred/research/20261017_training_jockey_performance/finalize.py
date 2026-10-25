"""Verify publication values and append this independent study to shared indexes."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
CENTRAL=HERE.parent/'conclusions'
CONCLUSION='56_TRAINING_JOCKEY_PERFORMANCE.md'
MARKER='<!-- training_jockey_performance_20261017 -->'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def guarded(path,text,mtime):
    assert path.stat().st_mtime_ns==mtime,'Shared file changed; reread before retry'
    path.write_text(text)


def main():
    audit=json.loads((OUT/'source_audit.json').read_text())
    for inp in audit['inputs']:assert sha(ROOT/inp['path'])==inp['sha256']
    assert json.loads((OUT/'verification.json').read_text())['passed']
    web=json.loads((OUT/'web_research.json').read_text())
    assert web['publication']==(HERE/'PUBLICATION.md').read_text()
    selections={
        'raw14':pd.read_csv(OUT/'binary_raw_performance.csv').query('window_days==14'),
        'main14':pd.read_csv(OUT/'main14_effects.csv'),
        'split_raw14':pd.read_csv(OUT/'raw_performance.csv').query("window_days==14 and grouping=='split_group'"),
        'sensitivity':pd.read_csv(OUT/'top3_sensitivity.csv'),
    }
    for name,expected in selections.items():
        actual=pd.DataFrame(web[name])[expected.columns]
        pd.testing.assert_frame_equal(expected.reset_index(drop=True),actual.reset_index(drop=True),check_dtype=False,atol=1e-12)
    coverage=pd.read_csv(OUT/'classification_coverage.csv')
    a=coverage[coverage.window_days.eq(14)]
    assert a[a.normal_outcome].n.sum()==158528
    assert a[~a.normal_outcome].n.sum()==486
    assert a[a.normal_outcome&a.classification.eq('no_training')].n.sum()==1053
    assert a[~a.window_supported].n.sum()==0
    assert selections['raw14'].n.sum()==103501
    e=selections['main14']
    expected_values={('2018_2020','서울'):2.66,('2018_2020','부산'):1.40,('2024_2025','서울'):2.86,('2024_2025','부산'):2.08}
    for (period,meet),expected in expected_values.items():
        row=e[e.period.eq(period)&e.meet.eq(meet)&e.target.eq('top3')&e.term.eq('any_jockey_vs_reference')].iloc[0]
        assert round(row.estimate*100,2)==expected
    central=CENTRAL/CONCLUSION
    central.write_text((HERE/'PUBLICATION.md').read_text()+
        f'\n\n[상세 방법](../{HERE.name}/README.md) · [출처](../{HERE.name}/SOURCES.md) · '
        f'[원시 성적](../{HERE.name}/outputs/raw_performance.csv) · '
        f'[조정 효과](../{HERE.name}/outputs/adjusted_effects.csv) · '
        f'[검증](../{HERE.name}/outputs/verification.json) · '
        f'[용량](../{HERE.name}/outputs/artifact_inventory.json).\n')
    accounting=OUT/'shared_edit_accounting.json'
    owned=json.loads(accounting.read_text()) if accounting.exists() else {}
    additions={
        'README.md':f'''\n\n## 연구56 조교 기수 기승과 출전 성적

{MARKER}
[조교 기수 기승 확인과 성적]({CONCLUSION}): 새로운 독립 관측 연구다. 경주 전14/28일·원문 역할·공식ID로 분류했다.2018~2020년 입상률 차이는 원시 서울+10.15%p·부산+11.84%p, 같은 말/경주·과거능력·기수·조교사·조교량 통제 후+2.66%p·+1.40%p다. 최근2024~2025년은+2.86%p·+2.08%p지만 미상 역할을 포함한 비교이며 입상률 다중비교 확정은 아니다. 출전 기수의 직접기승 우위는 시기·지역별 일관성이 없다. [원 보고서](../{HERE.name}/README.md). 인과·예측 개선·운영 보정 미확정.\n''',
        'SOURCES.md':f'''\n\n## 연구56 조교 기수 기승 확인과 출전 성적

{MARKER}
[원 보고서](../{HERE.name}/README.md) · [중앙 결론]({CONCLUSION}) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json). 읽기전용 연구DB의 선택된 완전수집 일반조교와159,014출전 신원 원장. 최근 역할 미상은 비기수로 판정하지 않음.\n''',
    }
    for name,addition in additions.items():
        p=CENTRAL/name; before=p.stat().st_size; mtime=p.stat().st_mtime_ns; text=p.read_text()
        if MARKER not in text:
            guarded(p,text+addition,mtime);owned[str(p.relative_to(ROOT))]=p.stat().st_size-before
    p=CENTRAL/'source_manifest.json'
    before=p.stat().st_size;mtime=p.stat().st_mtime_ns;manifest=json.loads(p.read_text())
    for group,paths in [('sources',[HERE/n for n in ['README.md','PUBLICATION.md','SOURCES.md','PLAN.md']]),
                        ('conclusions',[central,CENTRAL/'README.md',CENTRAL/'SOURCES.md'])]:
        for path in paths:
            entry=dict(path=str(path.relative_to(ROOT)),sha256=sha(path))
            found=[x for x in manifest[group] if x['path']==entry['path']]
            if found:found[0].update(entry)
            else:manifest[group].append(entry)
    manifest['training_jockey_performance_added']=True
    manifest['training_jockey_performance_note']='2026-10-17 연구56 독립 관측 연구. 기수 표기/출전기수 ID,2018~2020 명시분류와 최근 역할미상 비교 분리; 인과·예측·운영 보정 미확정.'
    manifest['updated_at']='2026-10-17'
    guarded(p,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',mtime)
    owned[str(p.relative_to(ROOT))]=owned.get(str(p.relative_to(ROOT)),0)+p.stat().st_size-before
    accounting.write_text(json.dumps(owned,ensure_ascii=False,indent=2)+'\n')
    link_count=0
    for path in [HERE/'README.md',HERE/'PUBLICATION.md',HERE/'SOURCES.md',central]:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
            dest=(path.parent/target).resolve()
            assert dest.is_relative_to(ROOT),target
            assert dest.exists() or dest==OUT/'artifact_inventory.json',target
            link_count+=1
    (OUT/'final_verification.json').write_text(json.dumps(dict(
        passed=True,source_hashes_unchanged=True,publication_matches=True,web_tables_checked=len(selections),
        static_document_counts_and_coefficients_checked=True,local_links_checked=link_count,
        figure_visually_inspected=True,figure='outputs/adjusted_top3.png',
        existing_conclusions_preserved=True,new_independent_study_document_number=56,
        production_changed=False,prediction_validation=False),ensure_ascii=False,indent=2)+'\n')
    print('Publication and central conclusion registered; verification passed')


if __name__=='__main__':main()
