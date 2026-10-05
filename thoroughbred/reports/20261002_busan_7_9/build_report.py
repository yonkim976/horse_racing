from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import csv, html, json, sqlite3, hashlib

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MODEL = ROOT / 'thoroughbred/predictions/20261002_busan_3_9_readonly_20261002T041207Z'
ESC = lambda x: html.escape(str(x), quote=True)
hist = json.loads(Path('/private/tmp/busan_remaining_db_history.json').read_text())
with (MODEL / 'runner_probabilities.csv').open() as f:
    probs = {(int(r['race_no']), int(r['horse_number'])): r for r in csv.DictReader(f)}
metadata = json.loads((MODEL / 'metadata.json').read_text())
combos = json.loads((MODEL / 'combination_predictions.json').read_text())
weights = {n: json.loads(Path(f'/private/tmp/busan{n}_weight.json').read_text()) for n in (7, 8, 9)}
changes = json.loads(Path('/private/tmp/busan_remaining_changes.json').read_text())
con = sqlite3.connect('file:' + str(ROOT / 'data/horse_racing.sqlite3') + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row

# 판단은 예측 확률과 별개다. 번호별 의견: 역할, 긍정 근거, 걱정거리, 대체 후보.
notes = {
7: {
1: ('후순위', '1600m에서 우승과 입상 경험. 서승운과 올해 5전 2승·4회 입상.', '직전 1600m 1:46.6, G3F 44.8·G1F 16.9로 종반 급락. 오늘 492kg(+7)은 이전 최고 491kg 부근이므로 체중만으로 회복을 단정하지 않음.', '최근 안정성은 11·3, 같은 거리 입상 경험은 10을 먼저 선택.'),
2: ('후순위', '최근 1800m 입상 경험. 거리 자체가 큰 미지수는 아님.', '직전 1:40.1은 영천 기록이라 부산의 같은 숫자와 직접 비교하지 않음. 56.5kg으로 감량 이점 작음.', '부산 1600m 최근 내용이 좋은 9·11·3 우선.'),
3: ('상향 상대', '최근 1600m 2착·1착·2착. 직전 56→51kg, G3F 38.4·G1F 13.1. 김성현과 올해 세 번 모두 입상.', '국5→국4 승급. 초반 뒤에서 시작하면 진로와 추입 타이밍이 관건.', '9가 실패할 때 11과 함께 대체 중심. 빠른 흐름에서 8·7보다 먼저 올림.'),
4: ('추가 복병', '직전 혼4 1600m 3착, G3F 38.3·G1F 13.2. 같은 경주 1보다 종반이 빠름.', '47일 간격, 이현종과 올해 첫 호흡. 최근 S1F가 10·11·10위로 출발 후 위치가 뒤임.', '앞선이 크게 무너지면 후보지만 6조합에서는 3·10을 우선해 제외.'),
5: ('모델 상위 재검토', '직전 1200m 3착, G3F 35.4·G1F 12.3. 1600m 우승 경험도 있음.', '57.5kg으로 이번 편성 최고 중량. 1200m 종반 속도를 1600m 능력으로 그대로 옮길 수 없음. 524kg(-9)은 과거 범위 안이라 감소만으로 악재라고 하지 않음.', '거리·감량 근거가 더 직접적인 11·3·10을 올림. 5는 6조합에서 제외.'),
6: ('후순위', '1400m 입상 이력, 52.5kg.', '직전 같은 1600m 경주에서 11보다 1.0초 늦었고 종반 41.6·14.7. 1600m 두 번 모두 입상 없음.', '같은 경주에서 앞섰고 오늘 더 감량한 11 우선.'),
7: ('전개 조건부', '최근 1200·1400m 1착·2착·1착. 오늘 직전보다 3.5kg 감량.', '첫 1600m·승급·이동하와 올해 첫 호흡. 최근 G3F 통과가 모두 1위라 앞에서 힘을 쓰는 편.', '8·10과 경합하면 3·11·9로 무게 이동. 느린 흐름이면 유지.'),
8: ('주력 상대, 경계', '직전 혼4 1400m 1:26.9 우승. 같은 경주 10보다 1.7초 빨랐음.', '52.5→56.5kg으로 4kg 증량. 첫 1600m, 다나카와 올해 첫 호흡. 7·10과 앞선 경합 가능.', '빠른 흐름이면 11·3을 앞에 둠. 조합에는 상승세를 인정해 남김.'),
9: ('중심 후보', '직전 1600m 우승, G3F 38.0·G1F 13.1. 56.5→52.5kg, 같은 다실바. 446kg(+5).', '국5→국4 승급. 직전 함수율 15%라 1:40.1만으로 건조 주로 우위를 단정하지 않음. 모델 입상 51.1%로 확정 축 수준은 아님.', '입상하지 못하면 11·3을 중심으로 10, 전개가 편한 경우 8을 연결.'),
10: ('거리 복병', '7월 건조 1600m 1:39.1로 3착, 당시와 같은 조인권·52.5kg. 올해 이 기수와 4전 3회 입상.', '앞선에서 오래 버티는 유형. 7·8과 무리하게 경합하면 종반 약해질 수 있음.', '9 이탈 시 3·11에 붙임. 단독으로 강한 축을 맡기지는 않음.'),
11: ('상향 상대', '직전 국4 1600m 57.5kg으로 3착, 오늘 52.5kg. 그전 같은 거리 우승. 482kg(-2).', '홍환웅과 올해 첫 실전 호흡. 5kg 감량 효과가 기승 차이까지 모두 보상한다고 단정하지 않음.', '9 이탈 시 가장 먼저 대체 중심으로 검토. 3·10 연결.'),
},
8: {
1: ('전개 조건부', '직전 1400m 3착, 이동하 유지. 초반 위치를 잡는 능력.', '첫 1800m. 최근 1400m에서도 앞선에서 종반 순위가 밀렸고 오늘 0.5kg 증량.', '거리 검증을 우선하면 9·3. 6조합에서는 제외.'),
2: ('주력 상대', '최근 5전 모두 입상. 채상현 유지. 선입과 후미 출발 모두 최근 입상 경험.', '1800m 세 번에서 입상 없음. 과거 1800m보다 오늘 중량도 높음. 직전 대비 0.5kg 증량.', '거리 부담이 나타나면 9·3, 경합이 크면 6도 다음 후보.'),
3: ('거리 복병', '1800m 최근 두 번 1착·3착. 신윤섭·52.5kg 그대로. 같은 8월 9일 경주에서 6·5보다 앞섬.', '54일 간격. 1:56.7과 1:59.2는 다른 날·다른 함수율 기록이라 하나의 능력값으로 취급하지 않음.', '10·11이 거리에서 무너지면 9·2와 함께 2-3-9를 선택.'),
4: ('승급 복병', '직전 1600m 우승, G3F 37.6·G1F 12.8. 송경윤 유지, 2kg 감량.', '국6→국5 승급과 첫 1800m. 직전 함수율 20%, 이전 건조 주로 기록의 기복 큼.', '성장 여지는 인정하지만 6조합에서는 3의 실제 거리 입상 근거를 우선.'),
5: ('모델 상위 재검토', '직전 1600m 3착, G3F 38.0·G1F 13.3. 오늘 1kg 감량.', '최근 1800m에서는 10착. 뒤에서 출발하는 경우가 많고 다비드와 올해 첫 호흡.', '모델보다 9·3을 올림. 6조합에서는 제외.'),
6: ('추입 예비 후보', '1800m 2착 경험. 직전 1800m G3F 40.3·G1F 13.6, 오늘 1kg 감량.', '초반 S1F가 최근 세 번 11위라 늦게 도착할 위험. 54일 간격.', '앞선이 크게 무너지면 올라오지만 6조합에서는 3·9를 우선.'),
7: ('후순위', '직전 1300m 2착, 1800m 입상 이력은 있음.', '직전 단거리 회복을 1800m 회복으로 단정하기 어려움. 최근 1800m 9착.', '같은 거리 최근 내용은 9·3 우선.'),
8: ('추가 상대', '직전 1800m 1:58.9, G3F 39.5·G1F 13.6. 오늘 0.5kg 감량.', '같은 경주 9보다 0.5초 늦었고 아직 이 거리 입상 없음.', '9를 먼저 선택하고 6조합에서는 제외.'),
9: ('거리 상대', '직전 1800m 3착, 이성재·54.5kg 그대로. 해당 경주에서 8보다 0.5초 빠름.', '직전 S1F·G3F·G1F 통과 1위 후 3착. 앞에서 경합하면 끝까지 버티는 힘이 관건.', '10·11 이탈 시 2·3과 대체 조합. 경합 시 3의 비중을 올림.'),
10: ('잠정 중심', '직전 1600m 1:40.7 2착, G3F 37.9·G1F 13.1. 같은 경주 5보다 1.7초 빠름.', '첫 1800m. 다실바→손경민, 올해 첫 호흡. 감량 표기를 추가로 빼지 않고 실제 출전 중량 54kg을 적용.', '실패하면 11·9·2. 10·11 모두 거리 적응 실패 시 3을 올림.'),
11: ('주력 상대, 경계', '1400m 2착 때 G3F 36.9·G1F 12.5. 진겸과 올해 5전 2회 입상, 같은 54kg.', '첫 1800m. 단거리 종반 속도는 강점이지만 장거리 지구력은 미검증.', '거리 문제로 빠지면 9·2·3. 10과 동시에 강한 축으로 고정하지 않음.'),
},
9: {
1: ('후순위', '과거 1800m 입상 경험은 충분.', '직전 같은 경주에서 2보다 1.6초 늦었음. 오늘 최고 중량 57kg, 1.5kg 증량. 다비드와 올해 첫 호흡.', '같은 조건 최근 검증은 2를 먼저 선택.'),
2: ('검증 상대', '직전 혼3 1800m 3착, G3F 39.3·G1F 13.2. 같은 52.5kg. 진겸과 올해 세 번 모두 입상.', '직전 G3F 통과 3위→G1F 5위로 중간에 위치가 밀렸다가 최종 3착. 진로·추입 타이밍 변수는 남음.', '10·4가 실패할 때 대체 중심. 5와 함께 연결.'),
3: ('종반 복병', '8월 부산 1600m 우승 때 G3F 36.7·G1F 12.8. 그전 1400m도 종반 기록 좋음.', '첫 1800m. 직전은 영천 1400m, 오늘 1kg 증량·이동하와 올해 첫 호흡. 1600m 우승 당시보다 2.5kg 높음.', '10·4가 동시에 실패하는 경합 시나리오에서 2·5에 연결. 지구력 확신은 금물.'),
4: ('공동 중심 후보', '직전 1800m 우승, G3F 38.6·G1F 12.9. 송경윤 유지, 55.5→53kg.', '혼4→혼3 승급. 1:52.6은 함수율 20% 기록이며 과거 1800m 10착도 있어 기복 확인 필요.', '실패하면 10·2·5. 10도 실패하면 2·3·5.'),
5: ('주력 상대', '1800m 반복 입상, 7월 건조 1:55.2 2착. 직전 같은 경주 8보다 종반 빠름.', '직전 52.5→53.5kg. 다실바와 올해 기존 1전은 입상 없음이라 교체만으로 상승을 단정하지 않음. 후미 출발·진로 변수.', '빠른 흐름이면 8보다 우선. 10·4 이탈 시 2와 함께 대체 중심.'),
6: ('후순위', '1800m 우승 경험과 최근 종반 기록은 있음.', '직전 8착, 55.5→56.5kg. 뒤에서 출발하는 경향이라 위치 회복이 관건.', '중량과 최근 입상 근거는 2·5 우선.'),
7: ('후순위', '2.5kg 감량으로 실제 부담은 낮아짐.', '최근 1800m 6·7착, 아직 이 거리 입상 없음. 이성재와 올해 첫 호흡.', '같은 거리 검증된 2·5 우선.'),
8: ('경계 상대', '직전 혼3 1800m 3착. 같은 경주 5보다 총기록 0.1초 빨랐음.', '오늘 1.5kg 증량. 직전 G3F 41.0·G1F 14.2로 같은 경주의 5보다 종반 느림. 서승운과 올해 첫 호흡.', '느린 흐름이면 살아남을 수 있지만 6조합 제한에서 축 이탈 대비와 2·5를 우선해 제외.'),
9: ('후순위', '이전 1400·1600m에서 입상 및 종반 경쟁 이력.', '직전 92/11은 정상 착순이 아니므로 평균 착순·시간 계산에서 제외. 이번 거리 최근 정상 완주 근거가 약함.', '정상 거리 기록과 최근 흐름이 확인되는 2·5 우선.'),
10: ('중심 후보', '직전 국4 1800m 1:53.3 우승. 조인권 유지, 올해 이 조합 5전 3승·4회 입상.', '국4→혼3 승급, 0.5kg 증량. 최근 S1F 2위·G3F 1위로 앞에서 힘을 쓰며 외곽 10번의 자리 경쟁도 변수.', '실패하면 4·2·5. 4도 실패하면 2·3·5로 이동.'),
11: ('추입 예비 후보', '직전 1800m G3F 38.3·G1F 13.1. 같은 경주 6보다 총기록 0.4초 빠름.', '최근 1800m 착순이 5·5·6착. 오늘 0.5kg 증량. 좋은 종반이 입상으로 이어지지 못함.', '극단적 앞선 붕괴 때 후보지만 6조합에서는 2·5·3 우선.'),
}}

plans = {
7: dict(time='16:55', condition='국4등급 · 1600m · 핸디캡', title='9 중심, 11·3을 올려 본다', certainty='상대적 중심 · 확정 축 없음', view='9의 거리 우승·감량·기수 유지가 가장 직접적인 근거다. 8·7의 상승세는 인정하되 첫 거리와 앞선 경합을 감안해, 최근 1600m 입상에 감량까지 있는 11·3을 모델보다 높게 평가한다.', lanes=[('앞선 경쟁',[7,8,10]),('선입·중단',[1,2,9,11]),('중단 이후',[3,4,5,6])], pace='보통 이상 가능성. 7·8의 최근 선행 성향과 10의 선입 성향이 겹친다. 9·11이 바로 뒤에서 무리하지 않으면 유리하고, 3은 빠른 흐름에서 종반 위치를 올릴 수 있다.', evidence=['7: 최근 S1F 2·1·2위, G3F 모두 1위 → 앞선에서 경주를 주도.', '8: 직전 1400m S1F→G3F→G1F 모두 1위. 10: 최근 S1F 2·2·3위 → 앞선 압박 가능.', '9: 직전 S1F 3위→G3F 5위→G1F 2위→최종 1착. 3: 직전 8위→7위→2위→2착.', '11: 직전 4위→3위→3위→3착. 자리 확보와 감량이 함께 작용할지 확인.'], tickets=[([3,9,11],'주력','거리·감량 근거가 있는 중심 9와 상대 3·11'),([8,9,11],'주력','8이 늘어난 거리와 중량을 버티는 경우'),([3,9,10],'보완','3의 추입과 10의 거리 경험 연결'),([7,8,9],'전개 보완','앞선 경합이 약해 7·8이 함께 버티는 경우'),([3,10,11],'9 이탈 대비','9가 빠지고 거리 검증된 세 말이 들어오는 경우'),([3,8,11],'9 이탈 대비','8의 상승세를 남기면서 3·11로 대체')], scenarios=[('기본','9 중심, 11·3 우선. 8은 상승세를 인정하되 위험을 함께 반영.', [0,1,2]),('앞선 경합','7·8·10이 일찍 힘을 쓰면 3·11을 올린다. 10도 경합에 참여할 수 있어 무조건 추입 수혜마로 보지 않는다.',[0,1]),('9 이탈','11·3이 먼저 올라온다. 10은 거리 경험, 8은 성장세로 보완한다.',[4,5])], exclusions='5는 1200m 종반 기록을 인정하지만 최고 중량 57.5kg 때문에 11·3·10 뒤로 둔다. 1은 직전 종반 급락, 4는 후미 출발·기수 교체로 이번 6조합에서 제외한다.'),
8: dict(time='17:25',condition='국5등급 · 1800m · 핸디캡',title='10은 잠정 중심, 거리 검증 9·3으로 대비',certainty='세 경주 중 중심 확신 가장 낮음',view='모델 상위 10·11이 모두 첫 1800m다. 두 말을 동시에 강하게 고정하기보다 최근 능력은 10·11, 실제 거리 입상은 9·3으로 나눠 본다. 2의 연속 입상도 과거 1800m 부진과 함께 평가한다.',lanes=[('앞선 경쟁',[1,4,9,10]),('선입·중단',[2,3,8,11]),('후미·추입',[5,6,7])],pace='초반 자리 경쟁 가능성은 있으나 첫 장거리 말들이 속도를 아낄 수도 있다. 빠른 흐름이라고 확정할 수 없다. 9·10이 편하게 자리를 잡으면 유리하고, 경합이 심해지면 3·11의 위치 회복을 본다.',evidence=['1: 최근 1400m G3F 통과 1위가 반복. 4: 직전 1600m S1F 1위→G3F 2위→우승.', '9: 직전 1800m 1위→1위→1위→최종 3착. 10: 직전 1600m 1위→1위→2위→2착.', '11: 직전 1400m 6위→7위→4위→5착. 좋은 종반 기록이 첫 1800m에서도 유지될지 미검증.', '3: 직전 1800m 6위→1위→3위→3착. 후미 추입만 하는 말이 아니라 중간에 움직일 수 있음.'],tickets=[([2,10,11],'주력','모델 상위 두 말과 최근 안정적인 2'),([9,10,11],'주력','1800m 입상 경험의 9 연결'),([2,9,10],'보완','11의 거리 적응 실패를 대비'),([3,9,10],'거리 보완','실제 1800m 입상한 3·9 연결'),([2,9,11],'10 이탈 대비','10이 빠져도 11의 종반 능력은 남기는 조합'),([2,3,9],'10·11 이탈 대비','첫 거리 상위마가 함께 실패하는 경우')],scenarios=[('기본','10을 잠정 중심으로 11·2·9 연결. 10·11 모두 첫 1800m라 강한 이중 축으로 보지 않는다.',[0,1,2]),('거리 검증 우선','1800m 실제 입상이 있는 9·3을 올린다. 9도 직전 선행 후 3착이므로 경합 부담은 남는다.',[1,3]),('상위마 거리 실패','10이 빠지면 2·9·11. 10·11이 함께 빠지면 2·3·9. 2 역시 과거 1800m 입상은 없다는 약점이 있다.',[4,5])],exclusions='1·4는 첫 1800m와 앞선 경합, 5는 최근 1800m 10착 때문에 뒤로 둔다. 6은 추입 예비 후보지만 6조합 제한에서 실제 거리 우승·입상이 있는 3을 먼저 넣는다.'),
9: dict(time='17:55',condition='혼3등급 · 1800m · 핸디캡',title='10·4 중심, 검증 상대 2·5',certainty='중심 두 말 모두 승급 변수',view='모델 상위 10·4는 거리 우승 근거가 있지만 이번 등급은 새 도전이다. 10의 기수 호흡과 4의 감량을 인정하고, 현 등급·거리 기록이 있는 2·5를 핵심 상대로 둔다. 3은 종반 능력은 좋지만 첫 1800m다.',lanes=[('선행·선입',[10]),('앞선 추격·중단',[1,2,3,4,7,8,9]),('후미·추입',[5,6,11])],pace='10이 먼저 자리를 잡고 4·8 등이 뒤따를 가능성. 4는 직전 중단에서 올라와 우승해 무조건 선행형으로 보지 않는다. 10의 외곽 자리 확보나 8의 압박으로 흐름이 빨라지면 2·5의 기회가 커진다.',evidence=['10: 최근 1800m 두 번 모두 S1F 2위·G3F 1위. 직전 G1F 1위→우승.', '4: 직전 S1F 4위→G3F 5위→G1F 1위→우승. 앞에서만 버티는 말은 아님.', '2: 직전 혼3 1800m 8위→3위→5위→3착. 기수 교체 후 위치 확보가 관건.', '5: 직전 같은 경주의 8보다 총기록은 0.1초 늦었지만 G3F 39.4 대 41.0, G1F 13.6 대 14.2로 종반 우세.'],tickets=[([2,4,10],'최우선','공동 중심 두 말과 현 등급·거리 검증 2'),([4,5,10],'주력','경합 시 종반 상대 5 연결'),([3,4,10],'보완','3이 첫 1800m에서도 종반 능력을 유지하는 경우'),([2,5,10],'4 이탈 대비','4가 승급·기복으로 빠지면 10에 2·5 연결'),([2,4,5],'10 이탈 대비','10이 앞선에서 소진되면 4·2·5'),([2,3,5],'10·4 이탈 대비','중심 두 말이 함께 빠지는 경우의 대비')],scenarios=[('기본','10·4를 중심으로 2·5를 연결. 두 말의 서로 다른 날짜 총기록만으로 순위를 단정하지 않는다.',[0,1,2]),('한 축 이탈','4가 빠지면 2·5·10, 10이 빠지면 2·4·5. 어느 축의 문제가 발생하는지 구분한다.',[3,4]),('두 축 이탈','2·5를 대체 중심으로 3 연결. 3도 첫 거리라 이 시나리오는 주력보다 확신이 낮다.',[5])],exclusions='8은 현 등급 1800m 3착을 인정하지만 1.5kg 증량과 같은 경주에서 5보다 느린 종반 때문에 제외한다. 1의 최고 중량 57kg, 11의 최근 5·5·6착도 고려했다. 제외는 입상 불가능을 뜻하지 않는다.'),
}

def val(v):
    return '—' if v is None else f'{v:g}'
def sec(h, point, kind):
    return next((s for s in h['sections'] if s['point_code']==point and s['time_kind']==kind), {})
def timefmt(ms):
    if ms is None: return '—'
    return f'{int(ms//60000)}:{ms%60000/1000:04.1f}'
def position(h, point):
    n=sec(h,point,'cumulative').get('position_raw')
    return str(n) if n and 0<n<=h['field_size'] else '—'
def pair_stats(e):
    r=con.execute('''SELECT count(*) starts, sum(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) wins, sum(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) top3 FROM race_entries e JOIN races r ON r.id=e.race_id JOIN race_results rr ON rr.race_entry_id=e.id WHERE e.horse_id=? AND e.jockey_id=? AND r.race_date_local>=? AND r.race_date_local<? AND rr.finish_position BETWEEN 1 AND 20''',(e['horse_id'],e['jockey_id'],'2026-01-01','2026-10-02')).fetchone()
    return f"{r['starts']}전 · {r['wins'] or 0}승 · 입상 {r['top3'] or 0}회"
def dist_stats(e,d):
    r=con.execute('''SELECT count(*) starts, sum(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) top3 FROM race_entries e JOIN races r ON r.id=e.race_id JOIN race_results rr ON rr.race_entry_id=e.id WHERE e.horse_id=? AND r.race_date_local<? AND r.distance_m=? AND rr.finish_position BETWEEN 1 AND 20''',(e['horse_id'],'2026-10-02',d)).fetchone()
    return '첫 거리 · DB 정상 완주 이력 없음' if not r['starts'] else f"{r['starts']}전 · 입상 {r['top3'] or 0}회"

css='''
:root{--bg:#f2f5f8;--ink:#162639;--muted:#657589;--line:#dce4ed;--blue:#1554be;--amber:#a65d00;--green:#157d61;--paper:#fff}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}a{color:var(--blue)}button{font:inherit;cursor:pointer}.hero{background:#13283f;color:white;padding:44px max(24px,calc((100vw - 1200px)/2));}.eyebrow{letter-spacing:.15em;font-size:12px;color:#a8c9f5}.hero h1{font-size:35px;line-height:1.3;margin:12px 0}.hero p{color:#d4dfed;max-width:900px}.nav{position:sticky;top:0;z-index:5;display:flex;gap:10px;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);padding:12px max(20px,calc((100vw - 1200px)/2));backdrop-filter:blur(10px)}.nav a,.nav button{border:1px solid var(--line);border-radius:8px;padding:7px 13px;text-decoration:none;background:white;color:var(--ink)}.nav a.active{background:var(--blue);color:white;border-color:var(--blue)}main{max-width:1240px;margin:auto;padding:24px 20px 50px}.overview{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:15px 0 24px}.mini,.panel{background:white;border:1px solid var(--line);border-radius:13px;padding:22px}.mini b{font-size:23px}.mini p{margin:8px 0}.subtle,.small{color:var(--muted);font-size:13px}.alert{border-left:4px solid #d48a2c;background:#fff7e9;padding:13px 18px;margin:16px 0;border-radius:0 8px 8px 0}.race{scroll-margin-top:85px;margin:30px 0 44px}.race-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;padding:20px 2px}.race-head h2{font-size:28px;line-height:1.35;margin:5px 0}.tag{display:inline-block;background:#eaf1fb;color:var(--blue);padding:3px 9px;border-radius:5px;font-size:12px;font-weight:650}.badge{color:var(--amber);background:#fff1d9;padding:5px 10px;border-radius:5px;font-size:13px;white-space:nowrap}h3{font-size:20px;margin:0 0 14px}h4{font-size:17px;margin:16px 0 7px}p{margin:9px 0 13px}.grid{display:grid;grid-template-columns:1.25fr 1fr;gap:16px;margin-bottom:16px}.lane{display:flex;gap:13px;padding:15px 0;border-bottom:1px solid var(--line)}.lane:last-child{border:0}.lane-label{min-width:105px;font-size:13px;color:var(--muted);padding-top:5px}.horses{display:flex;gap:7px;flex-wrap:wrap}.horse-chip{border:1px solid #cbd8e7;background:#f6f9fe;border-radius:5px;padding:4px 10px;font-weight:650;font-variant-numeric:tabular-nums}.flow{font-size:12px;color:var(--muted);margin-top:12px}.evidence{padding-left:19px;font-size:14px}.evidence li{padding-bottom:7px}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.tabs button{border:1px solid var(--line);border-radius:6px;background:#fff;padding:7px 12px}.tabs button.selected{background:var(--blue);color:#fff;border-color:var(--blue)}.scenario-output{min-height:64px;padding:12px 16px;border:1px solid #cbdcf4;border-radius:8px;background:#f3f7ff}.tickets{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:15px 0}.ticket{border:1px solid var(--line);padding:16px;border-radius:9px;background:#fff;transition:opacity .15s,border-color .15s}.ticket.match{border:2px solid var(--blue);padding:15px;background:#f6f9ff}.ticket.dim{opacity:.52}.ticket .combo{font-size:29px;font-weight:750;letter-spacing:.04em;margin:5px 0;line-height:1.25;font-variant-numeric:tabular-nums}.ticket p{font-size:13px;color:var(--muted);margin:6px 0 0}.ticket .kind{font-size:12px;color:var(--blue)}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th{background:#f3f6fa;color:#536579;font-weight:600;text-align:left}th,td{border-bottom:1px solid var(--line);padding:11px 9px;vertical-align:top}tbody tr:last-child td{border-bottom:0}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.name{white-space:nowrap;font-weight:650}.prob{min-width:112px}.bar{height:5px;border-radius:4px;background:#e5edf8;margin-top:5px}.bar span{display:block;height:5px;border-radius:4px;background:var(--blue)}.role{font-size:12px;white-space:nowrap;color:var(--green)}.runner{border:1px solid var(--line);border-radius:9px;margin-top:10px;background:white;overflow:hidden}summary{cursor:pointer;list-style:none;padding:15px 18px;display:flex;gap:14px;align-items:center}summary::-webkit-details-marker{display:none}summary:after{content:'기록 펼치기 +';margin-left:auto;white-space:nowrap;font-size:12px;color:var(--muted)}details[open] summary:after{content:'접기 −'}summary strong{font-size:17px}summary .summary-note{font-size:13px;color:var(--muted)}.runner-content{padding:0 18px 20px}.pros-cons{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pros-cons div{padding:14px;border-radius:8px;background:#f5f8fc}.pros-cons .risk{background:#fff8ed}.next{border-left:3px solid var(--blue);padding:10px 13px;background:#f3f7ff}.history td,.history th{font-size:12px;padding:8px}.footer{font-size:13px;color:var(--muted);padding:23px}.print-note{display:none}@media(max-width:850px){.hero h1{font-size:28px}.overview,.grid,.pros-cons{grid-template-columns:1fr}.tickets{grid-template-columns:repeat(2,1fr)}.race-head{display:block}.badge{white-space:normal}summary{flex-wrap:wrap;gap:5px 12px}summary .summary-note{width:100%}.nav{overflow-x:auto;white-space:nowrap}.mini{padding:16px}}@media(max-width:480px){.tickets{grid-template-columns:1fr}.hero{padding:28px 20px}main{padding:16px 12px}.panel{padding:16px}.lane-label{min-width:82px}}@media print{body{background:white;font-size:11px}.hero{background:white;color:#162639;padding:10px}.hero p,.eyebrow{color:#536579}.nav,.tabs,.flow{display:none}.race{break-before:page;margin:10px 0}.panel,.mini{border-color:#ccc}.tickets{grid-template-columns:repeat(3,1fr)}.ticket.dim{opacity:1}.ticket.match{border:1px solid #aaa;padding:16px}.grid{display:block}.grid>.panel{margin-bottom:10px}.table-wrap{overflow:visible}.print-note{display:block}.runner summary:after{display:none}.footer{padding:8px}.ticket,.runner,tbody tr{break-inside:avoid}}
'''

css += '.hero h1,.mini b,.race-head h2{word-break:keep-all}'
parts=['<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026.10.02 부산 7–9경주 | 모델 확률·기록·삼복 6조합</title><style>'+css+'</style></head><body>']
now=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M KST')
parts.append(f'<header class="hero"><div class="eyebrow">BUSAN · 2026.10.02 · RACE 7 / 8 / 9</div><h1>모델 확률에서, 삼복승 6조합까지</h1><p>전 출전마 33두의 입상 확률과 최근 기록을 함께 보고, 상위마가 버틸 근거·걱정거리·대체 후보를 구분했습니다. 전개는 최근 통과 위치에서 추론한 예상이며 최종 착순 예측과는 다릅니다.</p><div class="small" style="color:#afc5dd">작성 {ESC(now)} · 삼복승은 순서 없는 3두 조합 · 경주별 최종 추천 6개 고정</div></header>')
parts.append('<nav class="nav" aria-label="경주 이동"><a href="#overview">전체 요약</a><a href="#race7">부산 7경주</a><a href="#race8">부산 8경주</a><a href="#race9">부산 9경주</a><button id="print-button" type="button">인쇄 / PDF 저장</button></nav><main>')
parts.append('<section id="overview"><h2>먼저 볼 판단</h2><div class="overview">')
for n,p in plans.items():
    first=p['tickets'][0][0]
    parts.append(f'<article class="mini"><span class="tag">부산 {n}경주 · {p["time"]}</span><p><b>{ESC(p["title"])}</b></p><p class="small">{ESC(p["certainty"])}</p><p>첫 조합 <strong>{"-".join(map(str,first))}</strong></p><a href="#race{n}">확률·전개·6조합 보기 →</a></article>')
parts.append('</div><div class="alert"><strong>“확실한 말”로 분류한 출전마는 없습니다.</strong> 모델 1순위의 입상 확률도 7경주 51.1%, 8경주 47.7%, 9경주 51.0%입니다. 상대적으로 중심을 맡길 근거와, 실패할 때 올라올 후보를 함께 구성했습니다.</div>')
parts.append(f'<p class="small">당일 자료 확인 {ESC(changes["observed_at_kst"][:19].replace("T"," "))} KST. 부산 7–9경주 취소·기수·시각 변경 없음. 7경주 체중 반영, 8·9경주 체중 미공개. 0kg 표시는 미공개 값으로 처리했습니다. 현재 배당·당일 주로 상태는 판단에 반영하지 않았습니다.</p></section>')

for n,p in plans.items():
    runners=hist[str(n)]
    names={r['entry']['horse_number']:r['entry']['name_ko'] for r in runners}
    wr={int(r[0]):r for r in weights[n]['tables'][2][1:] if r and r[0].isdigit()}
    ranked=sorted(runners,key=lambda r:int(probs[n,r['entry']['horse_number']]['pred_rank']))
    model_order=' → '.join(str(r['entry']['horse_number']) for r in ranked)
    parts.append(f'<section class="race" id="race{n}"><div class="race-head"><div><span class="tag">{p["time"]} 출발 예정 · {p["condition"]}</span><h2>부산 {n}경주 · {ESC(p["title"])}</h2><p>{ESC(p["view"])}</p></div><span class="badge">{ESC(p["certainty"])}</span></div>')
    parts.append('<div class="grid"><article class="panel"><h3>예상 전개</h3>')
    for label, nums in p['lanes']:
        parts.append(f'<div class="lane"><span class="lane-label">{ESC(label)}</span><div class="horses">'+''.join(f'<span class="horse-chip">{i} {ESC(names[i])}</span>' for i in nums)+'</div></div>')
    parts.append(f'<p>{ESC(p["pace"])}</p><div class="flow">초반 예상 위치입니다. 최근 각질이 고정돼 있다는 뜻은 아니며 출발·진로·기수 선택에 따라 달라집니다.</div></article><article class="panel"><h3>전개를 뒷받침하는 기록</h3><ul class="evidence">'+''.join('<li>'+ESC(t)+'</li>' for t in p['evidence'])+'</ul><p class="small">위치는 S1F(초반 200m) → G3F(결승선 전 600m 지점) → G1F(결승선 전 200m 지점) → 최종 착순 순서입니다. 위치와 구간 소요시간은 서로 다른 값입니다.</p></article></div>')
    parts.append(f'<article class="panel"><h3>최종 삼복승 · 6조합</h3><p>기본 조합은 아래 여섯 개입니다. 시나리오 버튼은 해당 조합을 강조할 뿐, 추가 조합을 만들지 않습니다.</p><div class="tabs" data-race="{n}">')
    for ix,(label,desc,ids) in enumerate(p['scenarios']):
        parts.append(f'<button type="button" data-scenario="{ix}" aria-pressed="false">{ESC(label)}</button>')
    parts.append(f'</div><div class="scenario-output" id="scenario-{n}" aria-live="polite">{ESC(p["scenarios"][0][1])}</div><div class="tickets">')
    for ix,(nums,kind,why) in enumerate(p['tickets']):
        parts.append(f'<article class="ticket" data-race="{n}" data-ticket="{ix}"><span class="kind">{ix+1} · {ESC(kind)}</span><div class="combo">{"-".join(map(str,nums))}</div><p>{ESC(why)}</p></article>')
    parts.append(f'</div><p class="small">앞의 주력 조합과 뒤의 축 이탈 대비 조합은 역할이 다릅니다. 모두 같은 확신으로 평가하지 않았습니다. 실제 배당을 확인하지 않아 기대수익·배당 가치는 산출하지 않았습니다.</p><div class="alert"><strong>6조합에서 제외한 이유</strong><br>{ESC(p["exclusions"])}</div></article>')
    parts.append(f'<article class="panel" style="margin-top:16px"><h3>전 출전마 모델 확률 · 제 의견</h3><p class="small">모델 입상 확률 순서: {model_order}. 입상 = 3위 이내. 제 의견은 수동 판단이며 별도 확률로 환산하지 않았습니다.</p><div class="table-wrap"><table class="probability-table"><thead><tr><th>모델순</th><th>번호·마명</th><th>기수 / kg</th><th class="num">우승</th><th class="num">2위 내</th><th>3위 내 입상</th><th>제 역할 판단</th><th>당일 체중</th></tr></thead><tbody>')
    for r in ranked:
        e=r['entry'];i=e['horse_number'];q=probs[n,i];role=notes[n][i][0];w=wr[i]
        bw=f'{w[2]}kg ({int(w[3]):+d})' if int(w[2])>0 else '미공개'
        parts.append(f'<tr><td>{q["pred_rank"]}</td><td class="name"><a href="#runner-{n}-{i}">{i} {ESC(e["name_ko"])}</a></td><td>{ESC(e["jockey_name"])}<br>{val(e["carried_weight_kg"])}kg</td><td class="num">{float(q["win_probability"])*100:.1f}%</td><td class="num">{float(q["top2_probability"])*100:.1f}%</td><td class="prob"><strong>{float(q["top3_probability"])*100:.1f}%</strong><div class="bar"><span style="width:{float(q["top3_probability"])*100:.2f}%"></span></div></td><td class="role">{ESC(role)}</td><td>{ESC(bw)}</td></tr>')
    parts.append('</tbody></table></div>')
    b=[x for x in combos if x['race_no']==n and x['target']=='B'][:3]
    parts.append('<p class="small">모델 자체 삼복 상위: '+ ' / '.join('-'.join(map(str,x['horse_numbers']))+f' {x["probability"]*100:.2f}%' for x in b)+'. 이는 B 모델의 조합 확률입니다. 위 A 모델 입상 확률을 곱한 값이 아니며, 제 6조합의 적중 확률도 아닙니다.</p></article>')
    parts.append('<h3 style="margin-top:24px">말별 종합 의견과 최근 5전 근거</h3><p class="small">말을 누르면 긍정 근거·걱정거리·대체 후보와 기록표가 펼쳐집니다. DB 정상 완주 이력 기준 거리 통계와 올해 기수 호흡을 함께 표시했습니다.</p>')
    for r in ranked:
        e=r['entry'];i=e['horse_number'];q=probs[n,i];role,good,risk,nextup=notes[n][i]
        parts.append(f'<details class="runner" id="runner-{n}-{i}"><summary><strong>{i} {ESC(e["name_ko"])}</strong><span class="role">{ESC(role)}</span><span class="summary-note">모델 입상 {float(q["top3_probability"])*100:.1f}% · {ESC(e["jockey_name"])} / {val(e["carried_weight_kg"])}kg</span></summary><div class="runner-content"><div class="pros-cons"><div><strong>지지 근거</strong><p>{ESC(good)}</p></div><div class="risk"><strong>걱정거리</strong><p>{ESC(risk)}</p></div></div><p class="next"><strong>그렇다면 다음 후보는?</strong><br>{ESC(nextup)}</p><p class="small">이번 거리: {ESC(dist_stats(e,1600 if n==7 else 1800))} · 해당 기수와 올해 호흡: {ESC(pair_stats(e))}. 기수 호흡 표본은 작으며 기수 교체의 효과를 확정하지 않습니다.</p><div class="table-wrap"><table class="history"><thead><tr><th>일자 / 경마장</th><th>등급 / 거리</th><th>함수율</th><th>착순</th><th>중량</th><th>총기록</th><th>S1F 시간</th><th>G3F 시간</th><th>G1F 시간</th><th>통과 위치<br>S1F→G3F→G1F</th></tr></thead><tbody>')
        for h in r['history']:
            normal=h['finish_position'] and 0<h['finish_position']<=h['field_size'] and not h['disqualified']
            finish=f'{h["finish_position"]}/{h["field_size"]}' if normal else '정상 착순 제외'
            s1=sec(h,'S1F','cumulative').get('elapsed_time_ms');g3=sec(h,'G3F','closing').get('elapsed_time_ms');g1=sec(h,'G1F','closing').get('elapsed_time_ms')
            # 보충 화면과 불일치가 확인된 영천 초반 구간은 표시하지 않는다.
            if n==7 and i==2 and h['course']=='영천': s1=None
            st=lambda ms:f'{ms/1000:.1f}' if ms is not None and normal else '—'
            locs=' → '.join(position(h,k) for k in ('S1F','G3F','G1F')) if normal else '—'
            parts.append(f'<tr><td>{h["race_date_local"]}<br>{ESC(h["course"])}</td><td>{ESC(h["grade"])}<br>{h["distance_m"]}m</td><td>{val(h["track_moisture_percent"])}%</td><td>{finish}</td><td>{val(h["carried_weight_kg"])}kg</td><td>{timefmt(h["finish_time_ms"]) if normal else "—"}</td><td>{st(s1)}</td><td>{st(g3)}</td><td>{st(g1)}</td><td>{locs}</td></tr>')
        parts.append('</tbody></table></div><p class="small">총기록과 구간시간은 거리·함수율·경주 흐름이 다르면 직접 우열 비교를 하지 않았습니다. 정상 착순이 아닌 결과는 분석 통계에서 제외하며, DB에서 확인하지 못한 값은 —로 표시했습니다.</p></div></details>')
    u=f'https://race.kra.co.kr/chulmainfo/chulmaDetailInfo10Score.do?Act=02&Sub=1&meet=3&rcDate=20261002&rcNo={n}'
    parts.append(f'<p class="small" style="margin-top:16px">당일 보충 자료: <a href="{ESC(u)}" target="_blank" rel="noopener noreferrer">마사회 {n}경주 최근 전적</a> · <a href="{ESC(weights[n]["url"])}" target="_blank" rel="noopener noreferrer">출전마 체중</a></p></section>')

parts.append(f'<footer class="panel footer"><strong>분석 기준과 자료 시점</strong><p>기존 검증 완료 모델 {ESC(metadata["model_profile"])}. 모델 생성 {ESC(metadata["generated_at_utc"])} UTC, 경주 이력 최대 {ESC(metadata["race_history_max_date"])}, 주행심사 최대 {ESC(metadata["trial_history_max_date"])}. 모든 대상일 결과는 제외했습니다. 모델은 사전 출전표 기반이며 오늘 체중·최신 통과 위치 검토는 사람 의견에만 반영했습니다.</p><p>각 경주의 A 입상 확률 합은 300%, 우승은 100%, 2위 이내는 200%입니다. 전체 출전마가 각각 3개·1개·2개의 자리를 나눠 갖는 주변확률이기 때문입니다. B 조합 확률은 별도 등록 모델이 산출한 값입니다.</p><p>기록: 로컬 DB data/horse_racing.sqlite3 읽기 전용, 최근 최대 5전. 당일 출전·체중·변경사항: 마사회 공식 자료. 전개 예상·말별 역할·대체 후보·최종 6조합은 작성자의 종합 판단이며 모델 출력을 변경한 것이 아닙니다. 체중 미공개·실제 배당 미확인 상태를 그대로 표시했습니다.</p><p><a href="https://race.kra.co.kr/thisweekrace/ThisWeekChulmapyoChange.do" target="_blank" rel="noopener noreferrer">공식 출전 변경사항</a> · 이 문서는 자동 갱신되지 않습니다. 인쇄 버튼은 브라우저에서 PDF 저장에도 사용할 수 있습니다.</p></footer></main>')
scenario_data={str(n):[{'text':d,'tickets':ids} for _,d,ids in p['scenarios']] for n,p in plans.items()}
safe=json.dumps(scenario_data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
parts.append('<script type="application/json" id="scenario-data">'+safe+'</script>')
parts.append('''<script>
const scenarios=JSON.parse(document.getElementById('scenario-data').textContent);
document.querySelectorAll('.tabs').forEach(tabs=>{
 tabs.addEventListener('click',event=>{
  const button=event.target.closest('button[data-scenario]');if(!button)return;
  const race=tabs.dataset.race;const scenario=scenarios[race][Number(button.dataset.scenario)];
  document.getElementById('scenario-'+race).textContent=scenario.text;
  tabs.querySelectorAll('button').forEach(b=>{const active=b===button;b.classList.toggle('selected',active);b.setAttribute('aria-pressed',String(active));});
  document.querySelectorAll('.ticket[data-race="'+race+'"]').forEach(card=>{const active=scenario.tickets.includes(Number(card.dataset.ticket));card.classList.toggle('match',active);card.classList.toggle('dim',!active);});
 });
});
document.getElementById('print-button').addEventListener('click',()=>window.print());
document.querySelectorAll('a[href^="#runner-"]').forEach(a=>a.addEventListener('click',()=>{const target=document.getElementById(a.getAttribute('href').slice(1));if(target)target.open=true;}));
const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.isIntersecting){document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+entry.target.id));}});},{rootMargin:'-15% 0px -65% 0px'});
document.querySelectorAll('.race').forEach(section=>observer.observe(section));
</script></body></html>''')
report=OUT/'부산_7-9경주_입상확률_전개분석_삼복6조합.html'
report.write_text('\n'.join(parts),encoding='utf-8')
manifest={'generated_at_kst':now,'model_source':str(MODEL.relative_to(ROOT)),'model_metadata':metadata,'official_observed_at_kst':changes['observed_at_kst'],'weights_available':{'7':True,'8':False,'9':False},'races':3,'runners':33,'tickets_per_race':6,'plans':plans,'analysis_notes':notes,'probability_rows':[probs[n,i] for n in (7,8,9) for i in range(1,12)],'html_sha256':hashlib.sha256(report.read_bytes()).hexdigest()}
(OUT/'analysis_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
con.close()
print(report)
