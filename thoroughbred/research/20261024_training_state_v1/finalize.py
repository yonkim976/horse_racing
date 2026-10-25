"""Write the audited research report and unpublished public-facing summary."""
import json,math
import duckdb
import numpy as np
import pandas as pd
import study_common as c
import archive

def pct(v):return f'{100*v:.2f}%'
def pp(v):return f'{100*v:+.2f}%p'
def interval(v):return f'{100*v[0]:+.2f}~{100*v[1]:+.2f}%p'
def number(v):return '미관측' if not math.isfinite(float(v)) else f'{v:.1f}'

def cases():
    changes=pd.read_parquet(c.OUT/'axis_changes.parquet');changes=changes[changes.variant.eq('personal_t2')]
    f=c.frame(2).set_index(['race_key','program_no']);chosen=[]
    for meet in [1,3]:
        for net in [1,-1]:
            sg=changes[changes.meet_base.eq(meet)&changes.net_hit.eq(net)].sort_values(['race_date','race_key'])
            chosen.append(sg.iloc[0])
    con=duckdb.connect(str(c.old.DB),read_only=True)
    names=con.sql("""SELECT cast(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||cast(race_no AS VARCHAR) race_key,
       chul_no program_no,horse_name_raw FROM entry_result WHERE race_date>=DATE '2024-01-01' AND canonical_meet IN (1,3)""").df()
    con.close();names=names.set_index(['race_key','program_no']).horse_name_raw
    lines=['# 축이 바뀐 실제 사례','',
        '선택 규칙은 서울/부산에서 이득1건·손실1건씩 날짜순 첫 사례다. 결과가 좋은 예만 고르지 않았다. '
        '표의 조교값은 경주2일 전까지의 관측이며, 축 교체가 이 변수 하나 때문에 일어났다는 인과 설명은 아니다.',
        '', '| 경주 | 결과 | 기존 축(착순) | 새 축(착순) | 기존/새 축14일 조교분 | 기존/새 축 평소 대비분 |',
        '|---|---|---|---|---:|---:|']
    records=[]
    for row in chosen:
        a=f.loc[(row.race_key,row.axis_program_no_base)];b=f.loc[(row.race_key,row.axis_program_no_new)]
        an=names.loc[(row.race_key,row.axis_program_no_base)];bn=names.loc[(row.race_key,row.axis_program_no_new)]
        city='서울' if row.meet_base==1 else '부산';race=row.race_key.split(':')[-1]
        lines.append(f'| {row.race_date} {city}{race}경주 | {"이득" if row.net_hit==1 else "손실"} | '
            f'{int(row.axis_program_no_base)}번 {an}({int(a.outcome)}착) | {int(row.axis_program_no_new)}번 {bn}({int(b.outcome)}착) | '
            f'{number(a.train_minutes14)} / {number(b.train_minutes14)} | '
            f'{number(a.train_minutes14_delta_self3)} / {number(b.train_minutes14_delta_self3)} |')
        records.append({'race_key':row.race_key,'net_hit':int(row.net_hit),'base_program_no':int(row.axis_program_no_base),
            'new_program_no':int(row.axis_program_no_new),'base_finish':int(a.outcome),'new_finish':int(b.outcome),
            'base_horse_name':str(an),'new_horse_name':str(bn)})
    lines+=['','평소 대비값은 같은 말·지역의 직전3출전 중 수치가 완전한2개 이상 준비의 평균과 비교했다. '
        '미관측은0분으로 대체하지 않았다. 실제 결과를 보고 좋은 준비만 골라 평균하지 않았다.',
        '', '[전체484건 축 변경](outputs/axis_changes.parquet) · [전체 보고서](README.md)']
    (c.HERE/'CASES.md').write_text('\n'.join(lines)+'\n');c.save(c.OUT/'case_selection.json',{'rule':'earliest gain and loss per venue','cases':records})

def main():
    c.check();v=json.loads((c.OUT/'verification.json').read_text());assert v['status']=='passed'
    results=json.loads((c.OUT/'results.json').read_text());source=json.loads((c.OUT/'source_audit.json').read_text())
    lookup={(x['variant'],x['group']):x for x in results['groups']}
    def get(variant,group='all',metric='axis_top3'):return lookup[variant,group]['metrics'][metric]
    main_axis=get('personal_t2');cases()
    note='기존 축3,051/4,799(63.58%)→말별 조교변화3,071(63.99%),+20건·+0.42%p(95%−0.25~+1.09). 확률오차 감소,축개선 미확정·상대10%미달.'
    lines=['# 일별조교와 말별 준비 변화 예측 실험','',
        '**실전 사이의 조교 정보를 추가했더니 축 적중은63.58%→63.99%(+20건)였다. '
        '확률오차는 줄었지만 축 적중 개선의95%구간은−0.25~+1.09%p로0을 포함한다.10% 이상 개선은 확인하지 못했다.**','',
        '현재 판단은 조교가 작은 추가 정보 후보라는 것이다. 개인별 준비 변화 후보를 보존하되 운영 모델을 교체하지 않는다. '
        '기준선은 연구58C state_gbm이며 실제 운영등록 모델과 다르다.','',
        '## 선택한 정보와 범위','',
        '현재118열에서 빠진 일별조교의 관측일수·시간·마지막 관측일과 같은 말의 평소 대비 변화를 시험했다. '
        'DB에 있는 모든 원천을 처음 사용했다는 뜻은 아니다. 기수/진료/장구/심판/주행심사와 비교한 근거는 [후보 감사](CANDIDATE_AUDIT.md)에 있다.',
        '', '서울2,838·부산1,961,합계4,799경주/50,754출전.평가2024-01-05~2026-09-20(부산9/18까지),'
        '이력준비2010년부터·학습2017년부터다. 기존 비교와 동일한 모든 경주·축1두·복승1/3조합·복연1/3조합을 유지했다. '
        '반복 연구해 온 후향 평가기간이며 새로운 미래검증이 아니다.','',
        '## 축 적중 비교','',
        '| 후보 | 추가 입력 | 적중/4,799 | 적중률 | 기준선 대비 | 같은 경주 차이95%구간 |',
        '|---|---:|---:|---:|---:|---:|',
        '| 기존 상태모델 |0|3,051|63.58%|—|—|']
    labels={'quantity_t2':'조교량 T−2','personal_t2':'말별 준비 변화 T−2(주후보)','personal_t7':'조교만 T−7(민감도)'}
    for variant in c.VARIANTS:
        m=get(variant);lines.append(f'| {labels[variant]} | {len(c.VARIANTS[variant][1])} | {int(m["candidate_total"]):,} | '
            f'{pct(m["candidate_mean"])} | {int(m["candidate_total"]-m["baseline_total"]):+d}건 / {pp(m["difference"])} | {interval(m["ci95"])} |')
    ab=results['personal_vs_quantity'][0]['metrics']['axis_top3']
    lines+=['',f'주후보의 상대 개선은{pct(main_axis["relative_change"])}다.10% 상대 개선에는3,357건 이상이 필요하다. '
        f'조교량만 추가한 모델 대비 개인별 변화의 추가분도+21건·{pp(ab["difference"])}이며95%구간{interval(ab["ci95"])}로 아직확정되지않았다.',
        '', '주후보는484경주에서 축을 바꿨다. 기존 실패→적중149건,기존 적중→실패129건,적중 여부가 같은206건으로 순증20건이다. '
        '조교 증가가 항상 좋다는 고정 가산점이나 위험 경주 제외 정책을 사용하지 않았다. [변경 사례](CASES.md)를 이득과 손실 모두 제시했다.',
        '', '## 지역·연도와 기존 취약 조건','',
        '| 구분 | 경주수 | 기존→주후보 적중 | 기존→주후보 적중률 | 차이 |95%구간|',
        '|---|---:|---:|---:|---:|---:|']
    groups={'seoul':'서울','busan':'부산','2024':'2024년','2025':'2025년','2026':'2026년',
        'busan_grade5_1300_1600':'부산 국5 1300/1600m','busan_grade5_1300_1600_2026':'위 조건2026년'}
    for key,label in groups.items():
        m=get('personal_t2',key);lines.append(f'| {label} | {m["n"]:,} | {int(m["baseline_total"]):,}→{int(m["candidate_total"]):,} | '
            f'{pct(m["baseline_mean"])}→{pct(m["candidate_mean"])} | {pp(m["difference"])} | {interval(m["ci95"])} |')
    lines+=['', '지역×연도 순증은 서울2024/2025/2026 +6/−4/+5건,부산 −4/+10/+7건이다. '
        '전체연도 합계는 모두 증가했지만 모든 지역·연도에서 개선된 것은 아니다. 부산 국5 조건은 이전 연구에서 선택한 하위집단이며 '
        '최근72경주의36→39건을 확정 개선 또는 새 채택 규칙으로 쓰지 않는다.',
        '', '설명용 조건에서는 신마 포함816경주512→515건,90일 이상 휴양마 포함2,085경주1,324→1,346건, '
        '기존 축 경력3전 이하1,577경주1,039→1,053건이었다. 휴양마가 포함된 편성은 휴양마 자체를 축으로 택한 표본과 다르다. '
        '조건별 다중탐색과 반복평가를 고려하면 이 결과로 특정 경주만 남기는 새 정책을 만들 근거는 부족하다.',
        '', '## 확률 품질과 조합','',
        '아래 오차는 작을수록 좋으며 경주별 동일 가중 평균이다. 축 적중의 불확실성과 별도로 조교가 확률 추정에 작은 정보를 더하는 신호는 남았다.',
        '', '| 지표 | 기존 | 조교량 T−2 | 개인 변화 T−2 | 조교만 T−7 | 주후보−기존95%구간 |',
        '|---|---:|---:|---:|---:|---:|']
    for metric,label in [('runner_brier','말별 Top3 Brier'),('trio_logloss','3두집합 NLL'),('ordered_logloss','1·2·3착 순서 NLL')]:
        m=get('personal_t2',metric=metric)
        lines.append(f'| {label} | {m["baseline_mean"]:.6f} | {get("quantity_t2",metric=metric)["candidate_mean"]:.6f} | '
            f'{m["candidate_mean"]:.6f} | {get("personal_t7",metric=metric)["candidate_mean"]:.6f} | '
            f'{m["ci95"][0]:+.6f}~{m["ci95"][1]:+.6f} |')
    lines+=['','개인 변화−단순 조교량의Brier 차이는−0.000097(95%−0.000209~+0.000021)로0을 포함한다. '
        '따라서 조교 원천의 추가 가치와 개인별 편차 설계 자체의 확정 우위를 구분한다. 조교만T−7로 제한해도 확률오차 개선이 남지만 '
        '이는 당시 공개시각의 인증이나 일주일 전 전체모델 실전 검증은 아니다. 기존118열의 입력 시점은 그대로다.',
        '', '| 예산 | 기존 적중 | 주후보 적중 | 차이 |', '|---|---:|---:|---:|']
    for metric,label in [('quinella_one','복승1조합'),('quinella_three','복승3조합 중 적중'),('qpl_one','복연1조합'),('qpl_three','복연3조합 중 적중')]:
        m=get('personal_t2',metric=metric);lines.append(f'| {label} | {int(m["baseline_total"]):,} | {int(m["candidate_total"]):,} | {int(m["candidate_total"]-m["baseline_total"]):+d} |')
    lines+=['','전체 조합 적중 차이의95%구간은 모두0을 포함한다. 부산만 보면 복승3조합589→586,복연3조합1,034→1,032로 소폭 감소했다. '
        '전국 합계 증가를 모든 지역·승식의 개선으로 일반화하지 않는다. 배당/구매액/ROI 실험은 아니다.',
        '', '## 원천 품질과 정확한 입력','',
        '일별조교5,173,033원문,자연키 중복을 묶은5,173,025일별말관측을 사용했다. 날짜×지역12,232칸 모두완전응답(정상0행2,021칸 포함)이었다. '
        '시간QA/자연키이형/2시간초과에 해당하는492일의 시간은미확정으로 보존했다. T−2 평가 출전50,754개 중28일관측50,321(99.15%),'
        '유효14일시간50,311,개인 기준2전이상44,544(87.76%)였다.28일창시간QA가있는평가출전15개도제외하지않았다.',
        '', '기본10열은7/14/28일 관측일수와유효시간,14일관측일당시간,28일마지막관측간격/시간QA일수/응답지원비율이다. '
        '개인8열은14/28일관측일수와시간·14일관측일당시간·마지막관측간격의직전3출전준비평균대비6편차,지원출전수와14일시간표준편차다. '
        '[정확한 계약](outputs/feature_contract.json)을 보존했다. 관측이 없는 시간은결측이며0분으로대체하지않았다. 관측일수0은API관측0을뜻하고실제무조교를확정하지않는다.',
        '', '## 방법·검증·적용 한계','',
        '서울/부산×3연도×3후보로최종18모델,초기18학습을수행했다. 기준선과같은GBM설정/seed20261004,최대800회/조기종료25,경주당같은가중치다. '
        '평가연도Y에2017..Y−3학습/Y−2조기종료/2017..Y−2재학습/Y−1확률온도/Y평가를적용했다. 현재/과거조교 모두정해진cutoff를지키고 '
        '개인기준을만들때이전착순으로준비사례를선별하지않았다. 세후보와주후보는평가전에[계획](PLAN.md)으로고정했다. '
        '추출SQL예약어수정3회는특징/학습생성전[구현수정원장](outputs/implementation_repairs.json)에기록했으며설계변경은없다.',
        '', f'독립원문계산52출전/1,872값과미래조교삽입104검사를통과했다. 저장18모델의319,866개보정·평가점수를재추론해오차0, '
        f'18개보정온도재계산오차0,14,397축선택과전체출전확률을대조해최대오차{v["max_independent_probability_error"]:.3g}였다. '
        '3두집합과순서분포에서우승·Top2·Top3·복승·복연을유도해확률합및주변확률일관성을유지했다. '
        '[특징검증](outputs/feature_verification.json)·[전체검증](outputs/verification.json).',
        '', '95%구간은경주일블록2,000회재표집이다. 주후보는사전지정했지만보조지표/하위집단은다중비교보정된확증검정이아니다. '
        '같은기간을여러번연구했으므로구간을미래성능보증으로해석하지않는다.',
        '', '**조교 당시 경주전 공개시각이 인증된 원문은0건이다.** 후향DB의사건일기준정보제한을지킨실험이며당시그시각에데이터를받을수있었는지까지검증하지못했다. '
        '기존기준선의부담중량/결과명부시점한계도유지된다. 기수·구보/습보·당일마체중·배당·현재주로빠르기를새입력에넣지않았다.',
        '', '다음에검증할가치가있는방향은출전사이의준비변화를사전스냅샷으로고정해새경주에서확인하는것이다. '
        '이번20건순증만으로축적중의확정개선,10%향상,최적조교량/일정,기수·조교사의승부의지또는운영채택을주장하지않는다.',
        '', '## 산출물과 재현','',
        '원천DB와기존모델을참조하고신규특징차분/모델/예측/검증만보관했다. 운영등록부·원천DB해시는동일하다. '
        '[입력해시](outputs/input_manifest.json)·[전체수치](outputs/results.json)·[판단](outputs/decision.json)·'
        '[미게시요약](PUBLICATION.md)·[자기포함용량명세](outputs/artifact_inventory.json).',
        '', '```sh', '.venv/bin/python -B thoroughbred/research/20261024_training_state_v1/verify_study.py features',
        '.venv/bin/python -B thoroughbred/research/20261024_training_state_v1/verify_study.py models', '```',
        '', '최초실행은study_common.py→build_features.py→preflight.py→verify_study.py features→train_models.py→evaluate_models.py→analyze_results.py→verify_study.py models→finalize.py 순서다. '
        '평가완료파일이있으면평가를덮어쓰지않는다. 코드/검증을수정하거나재실행해보존파일을바꾸면finalize.py로중앙해시와용량명세도갱신한다.']
    (c.HERE/'README.md').write_text('\n'.join(lines)+'\n')
    public='''# 출전 사이 조교 기록이 축 적중에 도움을 주는가

게시용 초안·미게시.2026-10-24,서울·부산 연구후보. 운영모델 반영 아님.

현재 모델에서 빠진 일별조교 기록을 시험했다. 단순 시간 합계와 함께 같은 말이 평소 출전을 준비했던 양과의 차이를 계산했다. 기존과 같은4,799경주에서축을1두씩고른결과3,051→3,071건으로20건늘었다. 적중률은63.58→63.99%,차이+0.42%p다. 불확실성구간은−0.25~+1.09%p로확정개선은아니며상대10%개선목표에도미달한다.

서울은1,841→1,848건,부산은1,210→1,223건이다. 조교량만추가하면전체3,050건,조교정보를7일전까지만사용하면3,062건이었다. 개인별변화가가장높은점추정이지만단순조교량대비추가우위도아직확정되지않았다. 입상확률의전체오차는감소했다.

조교시간은운동강도나속도가아니며많다고항상좋다는뜻도아니다. 원문이없는상태를실제무조교로판정하지않고시간이상과결측도따로보존했다. [축교체이득과손실사례](CASES.md)를함께제시한다.

이미여러번연구한과거기간의실험이고당시조교정보의공개시각도인증되지않았다. 새경주의사전스냅샷검증이필요하다. 이번결과로최적조교일정이나승부의지를추론하지않으며운영모델은변경하지않았다.

[전체보고서](README.md) · [미사용정보감사](CANDIDATE_AUDIT.md) · [검증](outputs/verification.json)
'''
    (c.HERE/'PUBLICATION.md').write_text(public)
    conclusion=f'''# 일별조교와 말별 준비 변화 예측

2026-10-24,연구58I. 서울·부산,기존연구58C state_gbm118열에새조교정보18열을더한시간순실험이다.

{note}

| 후보 | 축 적중/4,799 | 적중률 | 기존 대비 |
|---|---:|---:|---:|
| 기존 상태모델 |3,051|63.58%|—|
| 조교량만 T−2 |3,050|63.55%|−1건|
| 말별 준비 변화 T−2 |3,071|63.99%|+20건|
| 조교만 T−7 |3,062|63.80%|+11건|

주후보의서울적중1,841→1,848,부산1,210→1,223. 부산국5 1300/1600m210경주120→122,같은조건2026년72경주36→39지만모두불확실성구간에0이포함된다. 전체축484건을바꿔149건을얻고129건을잃었다. 전체연도순증은+2/+6/+12건이나서울2025/부산2024는각각4건감소했다.

말별Top3 Brier는0.171180→0.170796(차이95%−0.000587~−0.000179),3두집합NLL4.187351→4.178765,순서NLL5.905907→5.895944로감소했다. 조교원천이작은추가정보가될가능성은남지만개인별변화설계가단순조교량보다확실히우월하다는결과는아니다. 복승3조합전체1,505→1,522,복연3조합2,628→2,645이나부산만보면각각3건/2건감소했다.

일별조교약517만관측과완전응답날짜·지역원장을사용했다. 부산의과거구보/습보일괄0,기수역할,당일자료는제외하고시간QA·자연키중복·결측을처리했다. 평가출전의99.15%에서최근28일조교관측을연결했다. 최초기록일부터과거준비를계산하고2017년이후학습,2024–2026년동일경주를비교했다. 최종18모델을보존했다.

원문기반특징1,872값,미래조교삽입104검사,저장모델319,866예측,18보정온도,14,397축결정을검증했다. DB/기준선/운영등록부해시는동일하다. 후향수집본으로역사적공개시각인증은없고반복개발기간이므로새독립검증이아니다. 상대개선+0.66%이며10%향상은확인하지못했다. 운영·게시변경없음.

[원본](../{c.HERE.name}/README.md) · [후보감사](../{c.HERE.name}/CANDIDATE_AUDIT.md) · [전체수치](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json)
'''
    archive.CONCLUSION.write_text(conclusion)
    c.save(c.OUT/'publication.json',{'status':'draft_unpublished','production_changed':False,'page_id':None,
        'summary_path':str((c.HERE/'PUBLICATION.md').relative_to(c.ROOT))})
    archive.finish(note)
if __name__=='__main__':main()
