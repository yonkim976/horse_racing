# 서울·부산경남 휴장 근거 목록 v1

> 2026-09-29 날짜 우선 재조사에서는 [API 날짜 원장](../20260929_calendar_api_v1/README.md)을 사용한다. 그 원장은 이 파일의 공식 구간에 2026-09-25~27 서울·부산경남·영천 추석 휴장을 추가했으며, 조사 상한은 2026-09-29다. 아래 설명은 이 목록을 만들 당시의 2026-09-20 상한 기준이다.

이 목록은 더러브렛 연구 DB의 원천 커버리지 조사에 쓰기 위해 만든 **공식 시행계획에 명시된 휴장 구간의 부분 목록**이다. `closures.csv`의 한 행은 한 개최지의 한 날짜 구간이다. 영천은 2026-09-13부터 경주가 확인되며, 이 목록의 2026년 휴장 구간은 영천 경주 시작 전이라 행을 만들지 않았다.

## 확인한 원천

| 연도 | 공식 한국마사회 근거 | 이 목록의 범위 |
|---|---|---|
| 2018 | [2018년 경마시행계획 8쪽](https://race.kra.co.kr/down/raceplan_2018.pdf) | 설·혹서기 교차휴장·추석·연말 교차휴장 |
| 2019 | [2019년 경마시행계획 10쪽](https://race.kra.co.kr/down/raceplan_2019.pdf) | 설·혹서기 교차휴장·추석·연말 교차휴장 |
| 2020 | [2020년 조정 경마시행계획 6쪽](https://race.kra.co.kr/down/raceplan_2020.pdf) | 코로나19에 따른 2월 23일~6월 18일 경마 미시행 |
| 2022 | [2022년 경마시행계획 10쪽](https://race.kra.co.kr/down/raceplan_2022.pdf) | 신정·설·혹서기 교차휴장·추석 |
| 2023 | [2023년 경마시행계획 10쪽](https://race.kra.co.kr/down/raceplan_2023.pdf) | 신정·설·혹서기 교차휴장·추석 |
| 2024 | [2024년 경마시행계획 12쪽](https://race.kra.co.kr/down/raceplan2024_20240828.pdf) | 설·혹서기 교차휴장·추석 |
| 2025 | [2025년 경마시행계획 12쪽](https://race.kra.co.kr/down/raceplan2025_20250103.pdf) | 설·혹서기 교차휴장·추석 |
| 2026 | [2026년 경마시행개요의 휴장기 표](https://race.kra.co.kr/raceoper/RaceoperView.do?Act=13&Sub=1&meet=3) | 설·혹서기 동시휴장. 9월 추석 휴장은 이번 DB 기준일 2026-09-20 이후이므로 제외 |

`closures.csv`는 서울·부산경남별 50행이다. `verify.py`가 운영 SQLite를 읽기 전용으로 대조한 결과, 표시한 구간 내부의 경주 행은 **0건**이다. 세부 결과는 `validation.json`에 있다.

원천을 달리하면 충돌이 있다. [2020년 조정 시행계획](https://race.kra.co.kr/down/raceplan_2020.pdf)은 2월 23일~6월 18일을 경마 미시행 기간으로 명시하지만, historical unified와 연구 v1 스냅샷에는 **2020-02-23 서울 11경주·부산경남 6경주** 행이 각각 남아 있다. 현재 운영 SQLite에는 없다. [source_conflicts.json](source_conflicts.json)에 17개 키와 공식 근거를 기록했다. 이 행은 원문·결과 상태를 판정할 때까지 정상 개최 경주로 확정하지 않는다. `verify_source_conflicts.py`로 다시 대조할 수 있다.

이것은 현재 적재 대상인 2010년 이후의 완전한 휴장 달력이 아니다. 2020년의 다른 중단 기간, 2021년과 더 이른 기간, 이 표에 없는 임시 중단·경주일 변경은 연도별 시행계획과 변경 공지의 원문을 추가 확보해 따로 판정해야 한다. 특히 **일반적인 비경주 요일, 무경주일, 개별 경주 취소, 주행심사 미시행**을 휴장과 동일하게 취급하지 않는다. 공식 연간 계획은 예정 정보이므로, 추후 변경 공지가 발견되면 원래 계획과 수정 계획을 모두 보존한다.

재검증:

```bash
python3 thoroughbred/research/20260929_closure_inventory_v1/verify.py
.venv/bin/python thoroughbred/research/20260929_closure_inventory_v1/verify_source_conflicts.py
```
