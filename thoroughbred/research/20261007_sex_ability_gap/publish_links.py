"""Append this completed study to shared research indexes without replacing prior studies."""
from pathlib import Path
import hashlib,json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RESEARCH=HERE.parent
OUT=HERE/'outputs'
SHARED=[RESEARCH/'README.md',RESEARCH/'conclusions/README.md',RESEARCH/'conclusions/SOURCES.md',RESEARCH/'conclusions/source_manifest.json',RESEARCH/'ARTIFACT_SIZE_LOG.md']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    before=OUT/'shared_edits_baseline.json'
    if not before.exists():
        initial={x['path']:x for x in json.loads((OUT/'baseline_inventory.json').read_text())['related_existing_files']}
        rec=[]
        for p in SHARED:
            name=str(p.relative_to(ROOT)); prior=initial[name]
            rec.append(dict(path=name,bytes=p.stat().st_size,sha256=sha(p),start_bytes=prior['bytes'],outside_task_delta_before_edit=p.stat().st_size-prior['bytes']))
        before.write_text(json.dumps(dict(captured_immediately_before_shared_edits=True,files=rec),ensure_ascii=False,indent=2)+'\n')
    conclusion='''# 암말·수말·거세마의 기록과 경기력

2026-10-07 · 관찰 연구 완료 · 성별 보정/성별 전용 운영 기준 미채택.

서울·부산 실전11거리151,074출전·13,928경주·12,435두를 분석했다. 암60,066·수54,908·거36,100행이며 출전 당시 공식 결과의 분류를 사용했다. 거세마는 수컷의 거세 상태를 구분한 집단이다. 최신 프로필을 과거에 적용하지 않았다. 수→거 변경은 확대 감사 모집단1,382두·최종 모집단1,366두이며 역방향/암말 포함 변경은 발견되지 않았다.

암−수 원시 평균 전체시간은1200m 서울+0.605초·부산+0.583초다. 같은 연령·등급·정확 함수율·월·연도를 맞추고 중량·마체중·rating·과거 성적을 고려하면 서울+0.114초 [0.038,0.191], 부산+0.119초 [0.040,0.198]로 줄었다. 같은 공통 표본의 원시 차이는+0.419/+0.433초이며 표본 변경과 통제 효과를 구분했다. 등급/rating/중량을 맞춘 차이는 전체 출전 집단 차이와 다른 질문이고 원인 분해가 아니다.

전체 통제 암−수는 서울1700+0.338초 [0.177,0.498], 부산1600+0.234초 [0.084,0.385]처럼 더 남는 조건이 있으나1000m와 서울1600에서는 확실하지 않다. 연령3~5세 이상·국5에서 작은 차이가 남는 반면2세/국6은 약하거나 불확실하다. 상위/OPEN·1900m 이상 및 세부 함수율 상태는 표본과 민감도가 제한된다. 거리·연령·상태 상호작용의 보편 법칙을 확정하지 않았다.

1200m 암말은 출발200m에서 서울−0.047·부산−0.056초, 마지막200m에서+0.077/+0.116초다. 독립 구간 합과 계수 합을 검증했고 겹치는 마지막600m를 중복 합산하지 않았다. 서울 미계측 마지막400m를 생성하지 않았다. 거−수는 서울1200−0.056초 [−0.123,0.010], 부산1200+0.054초 [−0.041,0.149]로 일정한 우열이 없다.

같은 경주에 실제 함께 출전한 암−수의3위 이내 차이는 전체 통제 후 서울1200−3.580%p [−5.748,−1.412], 부산1200−2.684%p [−5.164,−0.204]다. 기록시간과 성과는 별도 결과다. 암말 제한 경주를 혼합 경쟁으로 세지 않았다. 원래 출전자159,014행의 확대 성과 민감도에서도 통제 전 낮은 방향이 유지됐다.

공통1~8월의2018~2023 대2024~2026 비교에서 지원 가능한 전체 통제25개 격차 변화의95%구간은 모두0을 포함했다. 최근 격차가 동일하다는 동등성 증명이 아니다. 완결연도·가까운기간은 같은 자료의 민감도이며 독립 미래 검증이 아니다.

마필·지역별 날짜 이원 군집 불확실성, 표본/제외율·공통 표본·완전관측 민감도를 보존했다. 원문151,074행·별도 희소 더미회귀/군집 오차72개·원래 출전자159,014행 검증을 통과했다. 생물학적·인과적 능력, 거세 수술의 효과, 예측 개선을 입증하지 않았다.

개별 기록은 기존 공통 지역·거리·등급·함수율 기준에서 먼저 읽고 당시 분류·전개를 맥락으로 참고한다. 이번 평균차를 모든 말에게 일률 가산하지 않는다. 별도 성별 보정·운영 기준은 미채택이다. 기존 전체시간 환경 차이 반영률 서울80%·부산90%, 구간 보정 보류 및 기존 거리별 기준은 유지했다. 웹 구현/배포·운영 모델 반영은 하지 않았다.

[원 보고서](../20261007_sex_ability_gap/README.md) · [원천·방법](../20261007_sex_ability_gap/SOURCES.md) · [전체 표](../20261007_sex_ability_gap/ALL_RESULTS.md) · [검증](../20261007_sex_ability_gap/outputs/verification.json) · [보조 검증](../20261007_sex_ability_gap/outputs/supplement_verification.json) · [게시 요약](../20261007_sex_ability_gap/PUBLICATION.md) · [용량](../20261007_sex_ability_gap/outputs/artifact_inventory.json)
'''
    (RESEARCH/'conclusions/25_SEX_ABILITY_GAP.md').write_text(conclusion)
    p=RESEARCH/'README.md';text=p.read_text()
    text=text.replace('[주로·전개·게이트·주행심사 연구 결론 모음](conclusions/README.md)에서 2026년 10월 5일까지 이어 진행한 18개 연구','[주로·기록·전개·성별 연구 결론 모음](conclusions/README.md)에서 2026년 10월 7일까지 이어 진행한 32개 연구',1)
    if '(20261007_sex_ability_gap/README.md)' not in text:
        text+='\n\n[암말·수말·거세마의 기록과 경기력 차이](20261007_sex_ability_gap/README.md):출전 당시 분류151,074행·13,928경주를 대조하고 조건·등급·중량·체중·rating·이력,같은 경주 성과와 최근 변화를 분리했다.1200m 암−수 전체 통제 차이는 서울+0.114·부산+0.119초,거−수는 일관된 우열이 없다.마필/날짜 군집·선택 민감도·독립 계산을 검증했다. [중앙 결론](conclusions/25_SEX_ABILITY_GAP.md),성별 보정·운영 기준 미채택.\n'
    p.write_text(text)
    p=RESEARCH/'conclusions/README.md';text=p.read_text()
    text=text.replace('# 주로 전개 게이트 주행심사 연구 결론 모음','# 주로·기록·전개·성별 연구 결론 모음',1).replace('서울·부산·영천 연구 31개','서울·부산·영천 연구 32개',1).replace('31개 연구와 결정 문서','32개 연구와 결정 문서',1)
    marker='| [원 보고서 목록](SOURCES.md)'
    row='| [암말·수말·거세마의 기록과 경기력](25_SEX_ABILITY_GAP.md) | 출전 당시 분류·조건/등급/중량/체중/이력·같은 경주 성과·최근 격차, 성별 보정 미채택 |\n'
    if '[암말·수말·거세마의 기록과 경기력](25_SEX_ABILITY_GAP.md)' not in text:text=text.replace(marker,row+marker,1)
    if '<!-- sex_ability_gap_v1 -->' not in text:
        text+='\n\n## 성별 출전 집단 연구\n\n[암말·수말·거세마](25_SEX_ABILITY_GAP.md)는 같은 지역·거리·연령·등급·정확 함수율·월의 차이와 중량·체중·기존 성적 통제를 구분한다.151,074행을 원문 대조하고 마필·날짜 이원 군집 불확실성·실제 동반 출전 성과·최근 격차를 검증했다. 관찰된 조건부 차이이며 생물학적 인과효과·성별 보정·운영 반영을 확정하지 않았다. <!-- sex_ability_gap_v1 -->\n'
    p.write_text(text)
    p=RESEARCH/'conclusions/SOURCES.md';text=p.read_text().replace('거리별 기준31개 연구','거리별 기준·성별32개 연구',1)
    if '<!-- sex_ability_gap_v1 -->' not in text:
        text+='\n\n## 암말·수말·거세마의 기록과 경기력\n\n- 32. [출전 당시 성별·조건부 기록·같은 경주 성과·최근 격차](../20261007_sex_ability_gap/README.md)\n- [중앙 결론](25_SEX_ABILITY_GAP.md) · [원천/방법/해시](../20261007_sex_ability_gap/SOURCES.md) · [검증](../20261007_sex_ability_gap/outputs/verification.json) · [보조 검증](../20261007_sex_ability_gap/outputs/supplement_verification.json) · [게시 요약](../20261007_sex_ability_gap/PUBLICATION.md) · [파일별 용량](../20261007_sex_ability_gap/outputs/artifact_inventory.json)\n- 기존11거리151,074행·13,928경주를 그대로 재사용했다. 원래 출전자159,014행으로 선택 민감도를 추가했다. 기존 연구·함수율 보정·거리 기준·운영은 변경하지 않았다. <!-- sex_ability_gap_v1 -->\n'
    p.write_text(text)
    p=RESEARCH/'conclusions/source_manifest.json';manifest=json.loads(p.read_text())
    manifest['assembled_on']='2026-10-07'
    manifest['scope']=manifest['scope'].replace('연구31개','연구32개').replace('거리별 기록 기준 연구','거리별 기록 기준·성별 연구')
    for key,paths in [('sources',[HERE/'README.md',HERE/'SOURCES.md',HERE/'PUBLICATION.md']),('conclusions',[RESEARCH/'conclusions/25_SEX_ABILITY_GAP.md'])]:
        existing={v['path'] for v in manifest[key]}
        for path in paths:
            name=str(path.relative_to(ROOT))
            if name not in existing:manifest[key].append(dict(path=name,sha256=sha(path)))
    for entry in manifest['conclusions']:
        if entry['path'] in ['thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md','thoroughbred/research/conclusions/25_SEX_ABILITY_GAP.md']:
            entry['sha256']=sha(ROOT/entry['path'])
    for entry in manifest['sources']:
        if entry['path'].startswith(str(HERE.relative_to(ROOT))):entry['sha256']=sha(ROOT/entry['path'])
    manifest['sex_ability_gap_added']=True
    manifest['sex_ability_gap_note']='출전 당시 분류 원문 대조·조건부 기록·같은 경주 성과·마필/날짜 군집·시기 민감도. 관찰 연구, 성별 보정/운영 미채택.'
    manifest['data_end_by_study'].update(sex_ability_gap_seoul='2026-09-20',sex_ability_gap_busan='2026-09-18')
    p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('central conclusion and shared indexes updated')


if __name__=='__main__':main()
