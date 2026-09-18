"""Verify saved descriptive calculations and write their Korean interpretation."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/jeju_conditions_questions_20260917'
DOC = ROOT / 'docs/JEJU_NATIVE_CONDITIONS_PACE_WEIGHT_REVIEW_2026-09-17.md'
s = json.loads((OUT/'summary.json').read_text())
d = pl.read_parquet(OUT/'race_entries.parquet')
p = pl.read_parquet(OUT/'trial_next_race_pairs.parquet')
m = json.loads((OUT/'manifest.json').read_text())
sha = lambda path: hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
for k,v in m['inputs'].items():
    assert sha(ROOT/k)==v,k
for k,v in m['outputs'].items():
    assert sha(OUT/k)==v,k
assert d.height==s['entries'] and d['race_id'].n_unique()==s['races']
for key,groups in [('interval',['interval']),('good_weight_proximity',['weight_proximity']),
                   ('corner4_rank',['distance_m','corner4_rank_group']),
                   ('late_rank',['distance_m','late_rank_group']),
                   ('bodyweight_by_distance',['distance_m','weight_bin'])]:
    for row in s[key]:
        x=d
        for g in groups: x=x.filter(pl.col(g)==row[g])
        assert x.height==row['entries']
        assert x['top3'].sum()==row['top3']
        assert abs(x['top3'].mean()-row['top3_rate'])<1e-9
        assert x['race_id'].n_unique()==row['races']
same=p.filter(pl.col('trial_distance')==pl.col('race_distance'))
assert same.height==1015
assert abs(same['total_delta_seconds'].mean()-s['trial_vs_race'][0]['mean_delta'])<1e-9
db=ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
raw={r[0]:r[1:] for r in c.execute('SELECT e.id,e.hr_no,v.event_date,e.finish_time_ms,v.distance_m FROM entry e JOIN event v ON v.id=e.event_id')}
for r in p.to_dicts():
    a,b=raw[r['trial_entry_id']],raw[r['race_entry_id']]
    assert a[0]==b[0]==r['horse_id'] and a[1]<b[1]
    assert a[2]/1000==r['trial_seconds'] and b[2]/1000==r['race_seconds']
    assert a[3]==r['trial_distance'] and b[3]==r['race_distance']
c.close()
# All contrast coefficients of the rank-deficient good-weight nuisance design
# must remain estimable (nullspace confined to nuisance columns).
import pandas as pd
from analyze_jeju_conditions_questions import adjusted
df=pd.DataFrame(d.to_dicts())
check=adjusted(df,'weight_proximity','top3',['year_grade','month','distance_m','sex'],
               ['elo_gap','field_size','age','burden_kg'],'within1pct')
for a,b in zip(check['contrasts'],s['good_weight_adjusted']['contrasts'],strict=True):
    assert abs(a['estimate']-b['estimate'])<1e-10
cat_names=['year_grade','month','distance_m','sex']
num_names=['elo_gap','field_size','age','burden_kg']
dd=df[['weight_proximity','top3',*cat_names,*num_names]].dropna().copy()
dd['weight_proximity']=pd.Categorical(dd.weight_proximity,categories=['within1pct','1to2pct','over2pct'])
cats=pd.get_dummies(dd[['weight_proximity',*cat_names]].astype({k:'category' for k in cat_names}),drop_first=True,dtype=float)
nums=dd[num_names].astype(float)
nums=(nums-nums.mean())/nums.std().replace(0,1)
design=pd.concat([pd.Series(1.,index=dd.index,name='intercept'),cats,nums],axis=1)
x=design.to_numpy()
null_projection=np.eye(x.shape[1])-np.linalg.pinv(x)@x
for i,name in enumerate(design.columns):
    if name.startswith('weight_proximity_'):
        assert np.linalg.norm(null_projection[:,i])<1e-8,name
verification=dict(status='passed',checked='input/output hashes; saved counts/rates; all trial IDs, dates, distances and times; good-weight regression replay',
                  model_files_modified=False)
(OUT/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2))

def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |' for r in rows])
def pct(x): return f'{100*x:.1f}%'
labels={'dry':'건조 1~5%','good':'양호 6~9%','moist':'다습 10~14%','saturated':'포화 15~19%','sloppy':'불량 20% 이상'}
lines=['# 제주마 주로·전개·체중·출전 간격 분석','',
'2026-09-17. 코드 확인과 보유 자료의 탐색적 회고 분석. 기존 HY_R_FORM·저장 예측·원천 DB는 변경하지 않았다. 새 예측 모델의 개선 성적이 아니다.','',
'## 1. 모집단과 해석','',
f"- 모델 연구 이력에서 2023-01-01~2026-09-12, 거리 800m 이상 제주마 {s['races']:,}경주·{s['entries']:,}출전행·{s['horses']:,}두·{s['days']}경기일을 분석했다. 전체 원천의 모든 경주를 뜻하지 않는다.",
f"- 마체중 관측 {s['body_weight_known']:,}행, 미관측 {s['entries']-s['body_weight_known']:,}행. 유효 통과순위는 초반/4C/G1F 각각 {s['entries']-3:,}행이다.",
'- 입상은 정상 결과의 공식 착순 1~3위다. 경계 동착을 포함하므로 경주당 입상 말이 3두를 넘는 경우가 있다. 실격·미완주는 입상 실패로 집계했다. 기록 비교에는 정상 완주·usable·양수 시간만 사용했다.',
'- 표의 입상률은 해당 조건이 실제 발생한 뒤 집계한 비율이다. 특히 당일 통과순위·체중·주로는 현재 사전 모델의 입력이 아니다.',
'- 설명용 선형회귀는 인과효과나 외부 검증된 예측 모델이 아니다. 체중/간격은 말·경기일 이중 군집, 주로는 경기일 군집의 근사 95% 구간이다. 여러 비교에 대한 다중검정 보정은 하지 않았다.',
'- 체중 회귀는 일부 통제변수의 선형 중복이 있어 의사역행렬로 계산했다. 좁은 연관성 점검이며 최적 체중을 추정한 것이 아니다.','',
'## 2. HY_R_FORM에 구현된 것과 부족한 것','',
table(['질문','현재 구현','아직 없는 구분'],[
['주로','과거 함수율 1~9%/10% 이상 성적·같은 경주 대비 상대시간','현재 주로 예측·함수율별 초 단위 보정·말별 세부 주로 적성'],
['기록 빠르기','동일 거리·시대 기준 시간 잔차와 100m당 환산시간','주로 효과만 분리한 기록 보정'],
['전개','과거 초반 상위3 비율·선행 성향 상대 수·기수 성향·과거 순위 변화','실제 지속 경합·단독 선행·말 간 간격·외곽 이동거리·공기저항'],
['체중','과거 마지막 체중·과거 두 기록 차이·과거 추세','당일 체중과 말별 적정 범위·거리별 최적 체중'],
['출전 간격','직전 출전 후 일수','말별 최적 회복기간이 검증되었다는 근거'],
['능력 발전','Elo 변화·최근3회 대 이전3회 성적·최근 최고성적·부진 중 막판 양호','생리적 성장과 편성/전개 변화의 분리'],
['주행심사','심사 횟수·마지막 총시간 등의 기본정보','실전으로 환산하는 검증된 상수; 상세 구간 보강 후보는 기존 채택 모델과 별개']]),'',
'초반 상위3 비율은 거리 혼합이며, 선두만 뜻하지 않는다. 선행과 선입을 엄밀히 나눈 분류도 아니다. 막판 상대속도는 추입능력의 단서이며 고정된 각질 라벨이 아니다.','',
'## 3. 주로별 기록','',
'각 경주의 정상 유효 완주시간 중앙값을 구하고, 그 값을 경주별 동일 가중으로 평균했다. 단위 초. 괄호는 경주 수. 편성·나이·계절 차이가 포함된 원자료 평균이다.','']
rows=[]
for dist in [800,900,1000,1110,1200,1300,1400,1610]:
    g={r['track']:r for r in s['track_by_distance'] if r['distance_m']==dist}
    rows.append([dist]+[f"{g[k]['mean_race_median_seconds']:.2f} ({g[k]['races']})" if k in g else '—' for k in labels])
lines += [table(['거리',*labels.values()],rows),'',
'거리별로 연도×등급·월·평균 사전 Elo·평균 연령·평균 부담중량·출전수를 함께 고려한 탐색적 차이(기준 건조):','',
table(['거리','주로','시간 차이 초','95% 구간'],[
[dist,labels[r['term'].removeprefix('track_')],f"{r['estimate']:+.2f}",f"[{r['low95']:+.2f}, {r['high95']:+.2f}]"]
for dist,a in s['track_adjusted'].items() for r in a['contrasts']]),'',
'포화에서 빨라지는 방향이 일부 거리에서 보이지만 전 거리 공통 법칙은 아니며, 불량은 표본이 작고 구간이 넓다. 이 표의 차이를 각 말의 기록에 즉시 더하거나 빼는 보정값으로 사용하지 않는다.','',
'## 4. 주행심사와 다음 실전','',
'공식 말 ID로 심사 후 첫 실전을 연결했다. 2~90일 이내, 다음 실전은 2023년 이후이며 2026-09-12까지 정상 유효 완주한 경우다. 같은 실전에 여러 심사가 연결되면 마지막 심사만 남겼다. 총 2,639쌍 중 동일 거리는 800m 1,015쌍·834두이고 모두 합격 심사다. 미출전·미완주를 제외한 선택된 집단이며 심사 목적·성장·주로·중량 변화가 함께 포함된다.','',
table(['항목','심사','실전','실전−심사'],[
['800m 전체 평균','69.59초','68.63초','−0.97초'],
['초반 200m 평균 차이','—','—','−0.39초'],
['막판 200m 평균 차이','—','—','+0.34초']]),'',
'전체 기록 차이 중앙값 −1.20초, 가운데 50%는 −2.40~+0.10초다. 실전에서 초반은 빨라지고 막판은 느려지는 평균 패턴이 있어 총시간만으로 심사 능력을 환산하면 불충분하다. 800m 심사→900m 실전 528쌍에서도 초반 −0.49초·막판 +0.62초였지만, 거리 자체가 달라 총시간 차이를 같은 의미로 비교하지 않았다.','',
'## 5. 마지막 코너와 결승 200m 전 위치','',
'4C는 결승선 전 약 400m의 코너 계측점이다. 실제 직선 진입 순간과 동일하다고 보장하지 않는다. 아래는 각 지점에서 해당 순위였던 말의 최종 입상률이다.','']
for key,title,col in [('corner4_rank','4C 통과순위','corner4_rank_group'),('late_rank','결승 200m 전 통과순위','late_rank_group')]:
    rows=[]
    for dist in [800,900,1000,1110,1200,1300,1400,1610]:
        g={r[col]:r for r in s[key] if r['distance_m']==dist}
        rows.append([dist]+[f"{pct(g[k]['top3_rate'])} ({g[k]['entries']})" for k in ['1','2to3','4to5','6plus']])
    lines += ['### '+title,'',table(['거리','1위','2~3위','4~5위','6위 이하'],rows),'']
lines += ['짧은 거리에서 4C 선두의 높은 입상률이 관찰되지만, 말의 능력·등급·전개 선택 효과를 분리한 인과 결론은 아니다. 1610m는 8경주뿐이어서 전개 법칙을 정할 수 없다. 다음 경주에서는 이 실제 위치를 알 수 없으므로 사전 위치 예측의 오차까지 검증해야 한다.','',
'### 앞선 말 사이 간격의 대리지표','',
'초반과 4C에서 모두 1위인 말에 한정했다. 4C에서 두 번째 말과의 누적 통과시간 차이이며, 실제 거리나 지속 경합의 증거가 아니다.','',
table(['4C 선두 시간차','경주 수','선두 말 입상률'],[[r['lead_gap_group'],r['entries'],pct(r['top3_rate'])] for r in s['lead_gap_proxy']]),'',
'초반/4C 사이 구간에서 선두가 바뀌었는지, 서로 붙어서 힘을 썼는지, 외곽으로 돌았는지는 이 두 계측점만으로 확정하지 못한다.','',
'## 6. 거리별 체중과 과거 좋은 체중','',
'체중이 알려진 출전만 집계했다. 표는 다른 말들 사이의 원자료 비교다. 체격·성별·능력·성장·편성 차이가 섞여 있어 특정 체중이 최적이라는 뜻이 아니다.','',
table(['거리','체중 kg','출전 수','입상률'],[[r['distance_m'],r['weight_bin'],r['entries'],pct(r['top3_rate'])] for r in s['bodyweight_by_distance']]),'',
'같은 말·같은 거리에서 과거 입상 체중이 최소3개 있을 때 최근 최대5개 입상 체중의 중앙값을 기준으로 삼았다. 현재/미래 결과는 기준 체중 계산에 넣지 않았다. 이는 과거 좋은 체중의 대용치이며 생리적 최적 체중이 아니다.','',
table(['기준 체중과 차이','출전 수','입상률'],[[r['weight_proximity'],r['entries'],pct(r['top3_rate'])] for r in s['good_weight_proximity']]),'',
table(['조건 대비 1% 이내','보정 후 차이 %p','95% 구간 %p'],[[r['term'],f"{100*r['estimate']:+.2f}",f"[{100*r['low95']:+.2f}, {100*r['high95']:+.2f}]"] for r in s['good_weight_adjusted']['contrasts']]),'',
'연도×등급·월·거리·성별·사전 상대 Elo·출전수·나이·부담중량을 함께 고려하면 차이가 뚜렷하지 않았다. 현재 체중은 사후 분석에만 사용했다. 기존 경주 전 모델에서는 당일 체중을 알 수 없으므로 그대로 입력하지 않는다.','',
'## 7. 출전 간격','',
table(['직전 출전 후 일수','출전 수','입상률'],[[r['interval'],r['entries'],pct(r['top3_rate'])] for r in s['interval']]),'',
table(['15~28일 대비','보정 후 차이 %p','95% 구간 %p'],[[r['term'],f"{100*r['estimate']:+.2f}",f"[{100*r['low95']:+.2f}, {100*r['high95']:+.2f}]"] for r in s['interval_adjusted']['contrasts']]),'',
'원자료의 최고 입상률 구간을 모든 말의 최적 주기로 채택할 근거는 없다. 같은 통제변수로 설명한 뒤 네 차이 모두 구간에 0이 포함됐다. 말별 휴양 사유·훈련·건강·복귀전과 두 번째 출전 등은 이번 회귀에서 분리하지 못했다.','',
'## 8. 거리 구분과 공기저항','',
'2026년 제주 공식 운영 거리는 800·900·1000·1110·1200·1300·1400·1610m다. 확인한 시행계획에는 단/중/장거리의 숫자 경계를 별도로 적시하지 않았다. 연구 설명용으로 800~1000m를 짧은 거리, 1110~1200m를 중간, 1300~1610m를 긴 거리로 묶을 수 있으나 공식 분류나 동일 생리 적성으로 단정하지 않는다. 실제 모델 비교는 정확한 거리별로 한다.',
'주행심사는 2026년 현재 800m, 합격 기준은 2025년 70.5초에서 2026년 70.0초로 변경되었다. 심사 시간을 시대 구분 없이 합치지 않아야 한다.',
'앞선 말 뒤에서 달릴 때 공기저항을 줄이는 drafting 효과는 서러브레드 추적 연구에서 확인된 근거가 있다. 제주마의 효과 크기나 특정 말의 이득을 그대로 추정할 수는 없다. 순위만으로 앞말과의 거리·좌우 정렬·바람·지속시간을 알 수 없으며 진로 막힘 위험도 함께 고려해야 한다. 현재 HY_R_FORM에 직접적인 공기저항 변수가 들어 있지는 않다.','',
'## 9. 다음 연구 우선순위','',
'1. 기존 계획대로 2025년 심판 리포트의 출발·진로·접촉 정보를 정형화하고 다음 출전과 연결한다.',
'2. 과거 실제 4C 위치·선두와의 시간차·상대 초반 속도를 이력으로 보강하는 소수 가설을 검토한다. 현재 경기의 실제 값은 사전 입력에서 제외한다.',
'3. 주로별 기준시간은 거리·연도/제도·등급·계절·편성을 함께 고려하여 과거 자료에서만 학습하고, 말별 관측 수에 따른 불확실성을 보존한다.',
'4. 각질은 최근/거리별 선두 확률·선입 확률·종반 상대속도·순위 상승률로 표현한다. 현재처럼 초반 상위3 빈도만으로 선행/선입을 합치지 않는 후보를 검토한다.',
'5. 체중·출전 간격에 일괄 가산점을 주지 않는다. 세 목표의 예측 개선 여부로 채택한다.','',
'## 근거와 재현','',
'- [마사회 2026 제주 시행계획](https://race.kra.co.kr/down/raceplan2026_jeju.pdf)',
'- [마사회 주로 함수율 구분](https://race.kra.co.kr/chulmainfo/trackView.do?Act=02&Sub=10&meet=1)',
'- [Spence 외, Speed, pacing strategy and aerodynamic drafting in Thoroughbred horse racing](https://pubmed.ncbi.nlm.nih.gov/22399784/)',
'- 분석: `scripts/analyze_jeju_conditions_questions.py`; 결과 원장과 요약: `data/research/jeju_conditions_questions_20260917/`.',
'- 기존 결과 폴더 덮어쓰기를 거부한다. 재현은 별도 출력 경로에서 수행해야 한다. 관련 원천·분석 코드·산출물 해시를 manifest에 저장했다.',
'- 검증: 저장 집계 별도 재계산, 모든 심사 쌍의 원천 ID·날짜·거리·시간 대조, 해시 확인을 완료했다. 전체 예측 모델 재학습·교체는 하지 않았다.','']
DOC.write_text('\n'.join(lines),encoding='utf-8')
print(DOC)
print(json.dumps(verification,ensure_ascii=False))
