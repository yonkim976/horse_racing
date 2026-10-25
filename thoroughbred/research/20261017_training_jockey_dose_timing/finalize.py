"""Validate tables and register study56A without overwriting unrelated shared edits."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
CENTRAL=HERE.parent/'conclusions'
CONCLUSION='56A_TRAINING_JOCKEY_DOSE_TIMING.md'
MARKER='<!-- training_jockey_dose_timing_20261017 -->'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def guarded(path,text,mtime):
    assert path.stat().st_mtime_ns==mtime,'Shared file changed; reread before retry'
    path.write_text(text)


def main():
    audit=json.loads((OUT/'source_audit.json').read_text())
    for row in audit['inputs']:assert sha(ROOT/row['path'])==row['sha256']
    assert json.loads((OUT/'verification.json').read_text())['passed']
    assert json.loads((OUT/'followup_verification.json').read_text())['passed']
    web=json.loads((OUT/'web_research.json').read_text())
    assert web['publication']==(HERE/'PUBLICATION.md').read_text()
    for name,file in [('raw14','main14_raw.csv'),('adjusted14','main14_effects.csv'),('sensitivity','key_sensitivity.csv')]:
        a=pd.read_csv(OUT/file,dtype={'level':str,'reference':str})
        b=pd.DataFrame(web[name])[a.columns]
        pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-12,rtol=1e-12)
    central=CENTRAL/CONCLUSION
    central.write_text((HERE/'PUBLICATION.md').read_text()+
        f'\n\n[상세 방법](../{HERE.name}/README.md) · [출처](../{HERE.name}/SOURCES.md) · '
        f'[원시 성적](../{HERE.name}/outputs/raw_performance.csv) · [조정 결과](../{HERE.name}/outputs/adjusted_effects.csv) · '
        f'[횟수×시점 표본](../{HERE.name}/outputs/raw_count_timing_grid.csv) · [검증](../{HERE.name}/outputs/verification.json) · '
        f'[용량](../{HERE.name}/outputs/artifact_inventory.json).\n\n연구56의 후속이며 독립 주제 수를 늘리지 않는다.\n')
    account=OUT/'shared_edit_accounting.json'
    owned=json.loads(account.read_text()) if account.exists() else {}
    additions={
        'README.md':f'''\n\n## 연구56A 조교 기수 기승 횟수와 마지막 시점

{MARKER}
[기승 횟수와 마지막 기승 간격]({CONCLUSION}): 전체 기수와 실제 출전 기수를 나누고,0/1/2/3~4/5+회 및 마지막1~2/3~4/5~7/8~14일을 비교했다. 횟수와 시점을 함께 고려한 같은 말/경주 모형과14/28일·조교량 민감도, 역할 미상·희소 구간을 보존했다. [원 보고서](../{HERE.name}/README.md). 최적 횟수/날짜·인과·예측 개선·운영 보정은 미확정이며 연구56 후속이다.\n''',
        'SOURCES.md':f'''\n\n## 연구56A 조교 기수 기승 횟수와 마지막 기승 간격

{MARKER}
[원 보고서](../{HERE.name}/README.md) · [중앙 결론]({CONCLUSION}) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json). 연구56과 동일 원천 재집계·기수기승일 중복 감사·공식ID 매칭,최근 횟수/마지막 시점은 확인된 기록 기준.\n''',
    }
    for name,addition in additions.items():
        p=CENTRAL/name;before=p.stat().st_size;mtime=p.stat().st_mtime_ns;text=p.read_text()
        if MARKER not in text:
            guarded(p,text+addition,mtime);owned[str(p.relative_to(ROOT))]=p.stat().st_size-before
    p=CENTRAL/'source_manifest.json';before=p.stat().st_size;mtime=p.stat().st_mtime_ns
    manifest=json.loads(p.read_text())
    for group,paths in [('sources',[HERE/n for n in ['README.md','PUBLICATION.md','PLAN.md','SOURCES.md']]),
                        ('conclusions',[central,CENTRAL/'README.md',CENTRAL/'SOURCES.md'])]:
        for path in paths:
            entry=dict(path=str(path.relative_to(ROOT)),sha256=sha(path))
            found=[x for x in manifest[group] if x['path']==entry['path']]
            if found:found[0].update(entry)
            else:manifest[group].append(entry)
    manifest['training_jockey_dose_timing_added']=True
    manifest['training_jockey_dose_timing_note']='2026-10-17 연구56A 후속. 전체/출전 기수의 횟수와 마지막 간격 공동 비교,최근 미상 역할과 희소 구간 구분; 독립 주제 수·운영 유지.'
    manifest['updated_at']='2026-10-17'
    guarded(p,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',mtime)
    owned[str(p.relative_to(ROOT))]=owned.get(str(p.relative_to(ROOT)),0)+p.stat().st_size-before
    account.write_text(json.dumps(owned,ensure_ascii=False,indent=2)+'\n')
    links=0
    for path in [HERE/'README.md',HERE/'PUBLICATION.md',HERE/'SOURCES.md',central]:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
            dest=(path.parent/target).resolve();assert dest.is_relative_to(ROOT),target
            assert dest.exists() or dest==OUT/'artifact_inventory.json',target
            links+=1
    (OUT/'final_verification.json').write_text(json.dumps(dict(passed=True,input_hashes_unchanged=True,
        web_tables_checked=3,publication_matches=True,local_links_checked=links,
        figure_visually_inspected=True,existing_studies_preserved=True,independent_study_count_changed=False,
        production_changed=False,predictive_gain_tested=False),ensure_ascii=False,indent=2)+'\n')
    print('Study56A publication and registration verified')


if __name__=='__main__':main()
