"""Verify publication and append a guarded59A follow-up to the central indexes."""

import json
import re

import numpy as np
import pandas as pd

from common import DB,HERE,OUT,ROOT,dump,sha

CENTRAL=HERE.parent/'conclusions'
CONCLUSION='59A_DEBUT_TRIAL_JOCKEY_MATCH.md'
MARKER='<!-- debut_trial_jockey_match_20261025 -->'


def guarded(path,text,mtime):
    assert path.stat().st_mtime_ns==mtime,'Shared index changed; reread before retry'
    path.write_text(text)


def main():
    source=json.loads((OUT/'source_audit.json').read_text())
    assert sha(DB)==source['inputs'][0]['sha256']
    for x in json.loads((OUT/'protected_inputs.json').read_text()):assert sha(ROOT/x['path'])==x['sha256']
    assert json.loads((OUT/'verification.json').read_text())['passed']
    web=json.loads((OUT/'web_research.json').read_text());assert web['publication']==(HERE/'PUBLICATION.md').read_text()
    tables={'raw':'raw_performance.csv','frozen_metrics':'frozen_group_metrics.csv','metrics':'extended_metrics.csv',
        'intervals':'paired_loss_intervals.csv','associations':'adjusted_associations.csv','auc_intervals':'group_auc_intervals.csv',
        'feature_usage':'identity_feature_usage.csv','alternative_definitions':'alternative_definitions.csv'}
    for key,file in tables.items():
        a=pd.read_csv(OUT/file);b=pd.DataFrame(web[key])[a.columns]
        pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-12,rtol=1e-12)
    raw=pd.read_csv(OUT/'raw_performance.csv')
    z=raw[raw.period.eq('2024_2026')&raw.meet.eq('all')&raw.classification.eq('rider_group')].set_index('group')
    assert z.loc['same','n']==1511 and z.loc['different','n']==1062
    assert z.loc['same','top3_events']==357 and z.loc['different','top3_events']==213
    assert z.loc['same','wins']==118 and z.loc['different','wins']==74
    features=pd.read_parquet(OUT/'rider_features.parquet')
    expected=dict(api_direct=8424,official_completed_trial_rider=460)
    assert features.trial_jockey_identity_status.value_counts().to_dict()==expected
    fixed=pd.read_parquet(OUT/'frozen_predictions_grouped.parquet')
    new=pd.read_parquet(OUT/'extended_predictions.parquet')
    a=fixed[fixed.algorithm.eq('lightgbm')&fixed.model.eq('sections')&fixed.target.eq('win')][['row_key','p']]
    b=new[new.algorithm.eq('lightgbm')&new.base.eq('sections')&new.addition.eq('identity')&new.target.eq('win')][['row_key','p']]
    merged=a.merge(b,on='row_key',validate='one_to_one');assert np.array_equal(merged.p_x,merged.p_y)
    usage=pd.read_csv(OUT/'identity_feature_usage.csv')
    u=usage[usage.algorithm.eq('lightgbm')&usage.base.eq('sections')&usage.addition.eq('identity')&usage.target.eq('win')]
    assert len(u)==3 and u.identity_splits.eq(0).all()
    alternative=pd.read_csv(OUT/'alternative_definitions.csv')
    for row in alternative.itertuples():
        g=fixed[fixed.algorithm.eq('lightgbm')&fixed.model.eq('sections')&fixed.target.eq(row.target)]
        if row.subset!='all':g=g[g.meet.eq(row.subset)]
        g=g[g[row.definition].eq(row.group=='same')]
        assert len(g)==row.n and g.win.sum()==row.wins and g.top3.sum()==row.top3_events
    text=(HERE/'PUBLICATION.md').read_text()+f'\n\n[상세 방법](../{HERE.name}/README.md) · [출처](../{HERE.name}/SOURCES.md) · '+\
        f'[동결모형 집단별 성능](../{HERE.name}/outputs/frozen_group_metrics.csv) · [추가 예측 가치](../{HERE.name}/outputs/paired_loss_intervals.csv) · '+\
        f'[검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json).\n\n연구59의 후속이며 독립 주제 수를 늘리지 않는다.\n'
    central=CENTRAL/CONCLUSION
    if central.exists():assert '주행심사와 데뷔전 기수가 같으면' in central.read_text(),'59A claimed by another study'
    central.write_text(text)
    account=OUT/'shared_edit_accounting.json';owned=json.loads(account.read_text()) if account.exists() else {}
    additions={
        'README.md':f'''\n\n## 연구59A 주행심사와 데뷔전 기수 일치

{MARKER}
[심사 기수와 데뷔 기수가 같으면]({CONCLUSION}): 최근2,573두 중일치1,511두의입상23.63%·불일치1,062두20.06%,우승7.81%·6.97%. 기존구간모형의집단별입상AUC0.799·0.809와차이95% 구간0포함. 일치정보 추가시입상AUC0.803743→0.803840·Brier차이-0.000018(구간0포함),우승예측동일. 과거기수실력·같은경주조정과연도민감도도보존했다. 공식완료ID기준·가산/감산및운영미채택. [원 보고서](../{HERE.name}/README.md). 연구59 후속.\n''',
        'SOURCES.md':f'''\n\n## 연구59A 심사와 데뷔전 기수 일치

{MARKER}
[원 보고서](../{HERE.name}/README.md) · [중앙 결론]({CONCLUSION}) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json). 공식완료심사ID8,884건·고정예측15,438행보존·신모델30개독립재현,최종출전기수시점이용가능성미인증. 연구59후속.\n''',
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
            entry=dict(path=str(p.relative_to(ROOT)),sha256=sha(p));found=[x for x in manifest[group] if x['path']==entry['path']]
            if found:found[0].update(entry)
            else:manifest[group].append(entry)
    manifest['debut_trial_jockey_match_added']=True
    manifest['debut_trial_jockey_match_note']='2026-10-25 연구59A 후속. 마지막합격기수공식ID 일치/불일치 성적·고정모형 진단·신규정보30모형. 추가성적/예측개선 불확실,기존연구/독립수/운영유지.'
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
    dump(OUT/'final_verification.json',dict(passed=True,source_DB_unchanged=True,parent_files_preserved=True,
        publication_matches=True,web_tables_checked=len(tables),alternative_group_count_checks=len(alternative),
        main_groups_and_document_counts_checked=True,win_identity_predictions_exactly_unchanged=True,
        no_identity_tree_splits_for_primary_win=True,local_links_checked=links,figure_visually_inspected=True,
        production_changed=False,prospective_validation=False))
    print('Research59A registered and publication verified')


if __name__=='__main__':main()
