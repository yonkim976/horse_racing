# RaceFit V5 Sand Event 새 세션 인수인계 프롬프트

아래 내용을 새 Codex 세션의 첫 메시지로 그대로 붙여넣는다.

```text
우리는 한국 경마 예측 프로젝트를 계속 진행하고 있다. 기존 모델을 새로 만들거나 임의의 모델로 대체하지 말고, 아래 고정 모델과 데이터 계약을 먼저 확인한 뒤 사용해라.

프로젝트 위치
- /Users/kimyongjin/Desktop/horse_racing

현재 주력 모델
- 사용자 명칭: RaceFit V5 Sand Event
- run_id: a30cd09a-3b7b-402a-b010-5e7341fd4144
- 모델 형식: LightGBM LambdaRank + Plackett–Luce 순위확률
- artifact: /Users/kimyongjin/Desktop/horse_racing/data/experiments/models/a30cd09a-3b7b-402a-b010-5e7341fd4144/model.pkl
- feature contract: 177개 변수
- 데이터 시점 정책: start-minus-30m
- 2026 walk-forward 1,624경주 기준 성능: Top1 33.99%, 실제 우승마 예측 Top3 포함 64.96%, AUC 0.781, ECE 0.0083

중요 원칙
1. 경주 후 결과, 최종배당 등 예측 시점에 알 수 없는 정보를 절대로 입력하지 마라.
2. 예정 경주는 반드시 --mode live로 feature frame을 만든다.
3. 출발 30분 이내라 live frame 생성이 거부되면 historical 모드로 우회하지 마라. 가장 최근의 합법적인 pre-race frame 또는 오전 고정 예측을 사용하고 그 사실을 사용자에게 알려라.
4. 오전 고정 예측 파일은 수정하지 마라. 2026-09-04 예측은 다음 위치에 있다.
   /Users/kimyongjin/Desktop/horse_racing/data/predictions/20260904/1788451836921_a30cd09a/predictions.parquet
5. 이미 live 발행된 경주는 predict-and-publish가 중복 발행을 거부한다. 이 경우 새 live frame을 만든 뒤 predict_model_run으로 로컬 추론만 수행해라.
6. 최종배당을 실시간으로 안다고 가정하거나 배당을 만들어내지 마라. 배당이 없으면 손익분기 배당과 조건부 매수 기준만 제시해라.

예측 전 최신화 절차
- 현재 날짜와 한국시간을 먼저 확인한다.
- 경마장 코드는 서울=1, 제주=2, 부산경남=3이다.
- 공식 데이터 수집 예:
  .venv/bin/horse-racing collect-weights --date YYYYMMDD --meet MEET
  .venv/bin/horse-racing collect-scratches --date YYYYMMDD --meet MEET
  .venv/bin/horse-racing collect-jockey-changes --date YYYYMMDD --meet MEET
- 공식 결과 확인:
  .venv/bin/horse-racing collect-race-day --date YYYYMMDD --meet MEET
- 네트워크가 샌드박스에서 실패하면 필요한 범위의 승인을 요청해 다시 실행한다.

현재 코드에서 특히 확인할 점
- collect-weights가 horse_weight_history에는 기록하지만 race_entries.body_weight_kg를 갱신하지 않는 경우가 있었다.
- 예측 frame을 만들기 전에 대상 경주의 최신 horse_weight_history 값을 race_entries의 body_weight_kg와 body_weight_change_kg에 반영했는지 확인해라.
- 출전취소 말은 제외하며 체중 0을 정상 체중으로 넣지 마라.
- collect-race-day가 아직 결과가 없는 미래 경주를 completed로 표시하는 경우가 있었다. 실제 finish_position이 하나도 없다면 대상 경주만 scheduled로 바로잡은 뒤 live frame을 생성해라.
- 사용자가 소유한 다른 변경사항과 오전 예측 원장은 보존해라.

live frame 생성 예
  .venv/bin/horse-racing build-prediction-frame \
    --run-id a30cd09a-3b7b-402a-b010-5e7341fd4144 \
    --date YYYYMMDD \
    --mode live \
    --race-id RACE_ID \
    --output-dir data/predictions/current_weight_refresh/YYYYMMDD

추론 방법
- horse_racing.analysis.experiments.get_run으로 run을 불러온다.
- Polars로 방금 만든 parquet frame을 읽는다.
- horse_racing.analysis.prediction_frame.predict_model_run(run, frame)을 사용한다.
- 모든 출전마에 대해 prob_win, prob_top2, prob_top3를 제시한다.
- 말 이름은 SQLite의 race_entries와 horses를 연결해 확인한다.

조합확률 계산
- bundle.softmax_beta와 각 말의 rank_score를 사용한다.
- horse_racing.analysis.plackett_luce.ordered_top3_probabilities로 순서가 있는 1·2·3착 전체 분포를 계산한다.
- 복연승(QPL): 선택한 두 말이 모두 3착 안에 드는 모든 순서를 합산한다.
- 복승(QNL): 선택한 두 말이 1·2착을 차지하는 두 순서를 합산한다.
- 쌍승(EXA): 지정한 1착→2착 순서 확률을 계산한다.
- 삼복승(TLA): 선택한 세 말이 순서와 무관하게 정확히 1·2·3착을 차지하는 6개 순서를 합산한다.
- 삼연승(TRI): 지정한 정확한 1·2·3착 순서 확률이다.
- 손익분기 배당 = 1 / 모델 적중확률
- 보수적인 조건부 매수 기준은 모델확률 × 배당 >= 1.25로 표시한다. 최종배당이 없으면 기대수익을 확정하지 마라.

예측 결과를 사용자에게 보여주는 형식
1. 최신 정보가 관측된 한국시간
2. 출전취소와 기수변경
3. 모든 말의 일반 숫자 마번, 말 이름, 마체중 증감, 우승/2위 이내/3위 이내 확률
4. 핵심 축과 상대 후보
5. 주행 스타일·게이트·거리·마체중·휴양·훈련·모래반응 위험요소
6. 단승, 연승, 복연승, 복승, 쌍승, 삼복승 가운데 요청받은 승식의 조합확률
7. 배당이 없으면 손익분기 및 보수적 매수 배당
8. 예산을 사용할 때는 사용자가 실제로 '베팅 완료'라고 확인한 금액만 잔액에서 차감한다.

표기 취향
- 동그라미 숫자를 쓰지 말고 반드시 7번, 3-5-7처럼 일반 숫자로 쓴다.
- 확률은 모델 추정치임을 명확히 하고 적중이나 수익을 보장하지 않는다.
- 적중률과 환수율을 구분한다.
- 여러 승식에 같은 축을 반복하는 것은 분산이 아니라 상관된 집중이라는 점을 고려한다.

오늘 진행상태를 이어갈 경우
- 2026-09-04 제주 5경주까지 사용자가 베팅 완료를 확인했다.
- 추천안과 같은 금액을 실제로 샀다는 전제라면 제주 5 종료 후 추정 잔액은 31만원이지만, 새 세션에서는 실제 구매액과 현재 잔액을 사용자에게 확인해야 한다.
- 부경 6 및 제주 6 추천 금액은 사용자가 명시적으로 완료했다고 확인하기 전에는 차감하지 마라.
- 17:17 KST까지 공식 확정된 10경주의 오전 모델 성능은 Top1 3/10=30%, 실제 우승마 Top3 포함 7/10=70%, Top5 포함 8/10=80%였다.
- 부산경남 5경주는 Top1 3/5=60%, 모델 1순위 3착 이내 5/5=100%였다.
- 제주 5경주는 Top1 0/5, 모델 1순위 3착 이내 0/5였다. 표본은 작지만 당일 제주 예측에는 보수적인 금액 조정이 필요하다.

먼저 현재 날짜·시간, 대상 경주, 공식 최신 데이터 상태, 실제 남은 예산을 확인하고 기존 모델로 계속 분석해라.
```

