# T6. 라벨 경계 사례 감사

확인일: **2026-08-26** (Asia/Seoul)  
DB: `data/horse_racing.sqlite3` (읽기 전용)  
범위: 완료 경주 4,145건, 출전·결과 43,463건, 경주일 `2025-01-03` ~ `2026-08-23`  
설계 맥락: [MODELING_ROADMAP](MODELING_ROADMAP.md) §2.2 · T6  
재현: 아래 각 절의 SQL을 `sqlite3 "file:data/horse_racing.sqlite3?mode=ro"` 로 실행

이 문서는 예측 라벨 `win` / `top2` / `top3` 정책을 확정하기 위해
동착·특수코드·실격·결측 경계를 전수 집계한다. DB에 쓰지 않았다.

## 0. 한줄 결론

계획된 라벨 정책(정상 착순 1~89, `≥90`·`scratched`·`NULL` 제외, 동착 허용,
공식 착순 신뢰)은 **골격 그대로 유효**하다. 수정은 세 가지다.

1. **`disqualified` 컬럼은 전 행 0**이다. 실격 1건은 `finish_position=91` +
   `rank_remark='실격'` 로만 남는다. 플래그를 쓰지 말고 착순·비고를 따른다.
2. 동착은 전량 **올림픽 스킵**(1,1,3). `top2=(pos≤2)`, `top3=(pos≤3)` 는
   이 규칙과 맞으므로 **착순을 밀집(1,1,2)으로 바꾸지 않는다.**
3. 특수코드 실제 값은 **91·92·93·94·95·99** 여섯 가지뿐이고,
   `rank_remark`와 1:1이다. `formatting.py`의 `SPECIAL_FINISH_LABELS` 와는
   어긋나므로 라벨 구현은 **DB 실측 매핑**을 쓴다.

모순 행(`scratched=true` 인데 착순 1~89)은 **0건**이다.
정상 착순이 있는 경주 4,108건 모두 1착이 있다.

| 항목 | 실측 |
|---|---|
| 동착 경주 / 그룹 / 두수 | **49 / 50 / 100** (그룹당 항상 2두) |
| 1착·2착·3착 동착 그룹 | 5 / 9 / 10 |
| 동착 다음 착순 | **전량 스킵** (1,1,3). 밀집(1,1,2) 0건 |
| `rank_remark` 비NULL 고유값 | **6종** (경주제외·경주취소·출전취소·주행중지·출발제외·실격) |
| `disqualified=true` | **0행**. 실격은 91+비고 1건 |
| 특수코드 `≥90` 종류 | **91, 92, 93, 94, 95, 99** (90·96·97·98 없음) |
| `scratched` ∧ 착순 1~89 | **0건** |
| 착순 NULL | **131행 / 12경주** (경주 단위 전원 NULL) |
| 정상 착순 있는데 1착 없음 | **0경주** |

## 1. 동착 (dead heat)

같은 `race_id` 안에서 정상 착순(`1~89`)이 2두 이상인 그룹.

| 집계 | 값 |
|---|---:|
| 동착 그룹 | 50 |
| 동착 경주 | 49 (한 경주가 그룹 2개) |
| 그룹당 두수 | 전부 2 (3두 이상 동착 0) |
| 동착 말 합 | 100 |

### 1.1 착순별 건수

| `finish_position` | 그룹 | 경주 | 두수 |
|---:|---:|---:|---:|
| 1 (1착 동착) | 5 | 5 | 10 |
| 2 | 9 | 9 | 18 |
| 3 | 10 | 10 | 20 |
| 4 | 4 | 4 | 8 |
| 5 | 4 | 4 | 8 |
| 6 | 6 | 6 | 12 |
| 7 | 7 | 7 | 14 |
| 8 | 2 | 2 | 4 |
| 9 | 1 | 1 | 2 |
| 10 | 2 | 2 | 4 |
| **합** | **50** | | **100** |

다음 정상 착순이 있는 48그룹은 모두 `next_pos = pos + 2` (올림픽 스킵).
나머지 2그룹은 최하위 동착이라 다음 정상 착순이 없다.
**밀집 순위(1,1,2)는 0건**이다. 동착 말 100두 중 50두의 `margin_text`가
`동순위`다 (쌍의 한쪽).

```sql
WITH dh AS (
  SELECT e.race_id, rr.finish_position AS pos, COUNT(*) AS n_horses
  FROM race_results rr
  JOIN race_entries e ON e.id = rr.race_entry_id
  WHERE rr.finish_position BETWEEN 1 AND 89
  GROUP BY e.race_id, rr.finish_position
  HAVING COUNT(*) >= 2
)
SELECT pos, COUNT(*) AS n_groups, COUNT(DISTINCT race_id) AS n_races
FROM dh
GROUP BY pos
ORDER BY pos;
```

```sql
-- 스킵 vs 밀집
WITH dh AS (
  SELECT e.race_id, rr.finish_position AS pos, COUNT(*) AS n_horses
  FROM race_results rr
  JOIN race_entries e ON e.id = rr.race_entry_id
  WHERE rr.finish_position BETWEEN 1 AND 89
  GROUP BY e.race_id, rr.finish_position
  HAVING COUNT(*) >= 2
)
SELECT
  CASE
    WHEN next_pos IS NULL THEN 'no_next'
    WHEN next_pos = pos + n_horses THEN 'skip (1,1,3)'
    WHEN next_pos = pos + 1 THEN 'dense (1,1,2)'
    ELSE 'other'
  END AS pattern,
  COUNT(*) AS n_groups
FROM (
  SELECT dh.*,
         (SELECT MIN(rr.finish_position)
          FROM race_entries e
          JOIN race_results rr ON rr.race_entry_id = e.id
          WHERE e.race_id = dh.race_id
            AND rr.finish_position > dh.pos
            AND rr.finish_position BETWEEN 1 AND 89) AS next_pos
  FROM dh
)
GROUP BY 1;
```

### 1.2 1착 동착 전수 (5경주)

공식 순서는 모두 `1, 1, 3, …`. `win` 라벨이 경주당 2두.

| 경주일 | 경마장 | R | 거리 | 동착 출주번호 | 3착 이후 |
|---|---|---:|---:|---|---|
| 2025-04-13 | 서울 | 2 | 1400 | #5, #9 | #7이 3착 |
| 2025-05-16 | 제주 | 8 | 1200 | #1, #8 | #2가 3착 |
| 2025-12-06 | 서울 | 2 | 1200 | #6, #8 | #5가 3착 |
| 2026-02-28 | 서울 | 8 | 1800 | #3, #7 | #9가 3착 |
| 2026-03-27 | 제주 | 4 | 1110 | #1, #2 | #3이 3착 |

이 5경주에서 `pos≤2` 두수는 **2** (2착이 없음), `pos≤3` 두수는 **3**.

### 1.3 2착 동착 사례 (9경주, `1, 2, 2, 4`)

| 경주일 | 경마장 | R | 동착 출주번호 |
|---|---|---:|---|
| 2025-03-02 | 부산경남 | 6 | #3, #6 |
| 2025-03-23 | 서울 | 6 | #1, #5 |
| 2025-05-18 | 서울 | 4 | #6, #10 |
| 2025-08-30 | 서울 | 7 | #4, #5 |
| 2025-11-07 | 제주 | 5 | #5, #9 |
| 2025-12-28 | 부산경남 | 2 | #3, #12 |
| 2026-03-14 | 서울 | 9 | #7, #11 |
| 2026-06-28 | 서울 | 4 | #6, #7 |
| 2026-07-25 | 서울 | 7 | #6, #7 |

예: 2025-03-02 부산경남 R6 선두 `12#1, 3#2, 6#2(동순위), 9#4`.
이 9경주에서 `pos≤2` 두수 **3**, `pos≤3` 두수 **3** (3착이 없음).

### 1.4 3착 동착 사례 (10경주, `1, 2, 3, 3, 5`)

| 경주일 | 경마장 | R | 동착 출주번호 |
|---|---|---:|---|
| 2025-06-27 | 제주 | 4 | #8, #10 |
| 2025-08-22 | 제주 | 8 | #3, #9 |
| 2025-08-22 | 부산경남 | 1 | #1, #4 |
| 2025-10-17 | 제주 | 5 | #8, #10 |
| 2025-11-07 | 제주 | 1 | #2, #3 |
| 2025-11-14 | 제주 | 4 | #7, #9 |
| 2025-11-29 | 제주 | 2 | #1, #10 |
| 2026-02-14 | 서울 | 7 | #3, #7 |
| 2026-04-17 | 부산경남 | 4 | #3, #11 |
| 2026-04-24 | 부산경남 | 5 | #1, #6 |

이 10경주에서 `pos≤3` 두수 **4**.

### 1.5 한 경주 두 그룹 · 최하위 동착

- 2025-11-29 제주 R2: 3착 동착(#1,#10)과 7착 동착(#3,#5) 동시.
  순서 `… 1#3, 10#3(동순위), 6#5, … 3#7, 5#7(동순위), 4#9 …`
- 최하위 동착 2건: 2026-04-10 부산경남 R7 10착(#2,#7),
  2026-08-09 서울 R6 10착(#3,#6). 라벨 top2/top3에 영향 없음.

## 2. `rank_remark` 고유값

비NULL 6종. **정상 착순 행에는 비고가 하나도 없다.**
특수코드 837행은 비고가 비지 않고, 비고↔착순 코드는 1:1이다.
`착변`은 `rank_remark`가 아니라 `margin_text`에만 있다 (11행).

| `rank_remark` | 행 수 | 대응 `finish_position` | 정상/특수/NULL |
|---|---:|---:|---|
| (NULL) | 42,626 | — | 42,495 / 0 / 131 |
| 경주제외 | 315 | 94 | 0 / 315 / 0 |
| 경주취소 | 246 | 99 | 0 / 246 / 0 |
| 출전취소 | 192 | 95 | 0 / 192 / 0 |
| 주행중지 | 79 | 92 | 0 / 79 / 0 |
| 출발제외 | 4 | 93 | 0 / 4 / 0 |
| 실격 | 1 | 91 | 0 / 1 / 0 |
| **합** | **43,463** | | |

의미 추정 (KRA 관행 + `race_scratches.reason` 대조):

| 비고 | 추정 의미 | 출주 여부 |
|---|---|---|
| 출전취소 | 경주 전 마체이상·절음 등으로 출전 철회 | 미출주 (`scratched`) |
| 경주제외 | 당일 마체이상·입장불량·낙마 등 게이트 전후 제외 | 미출주 (`scratched`) |
| 출발제외 | 출발대 진입거부·방마 | 미출주 (`scratched`) |
| 주행중지 | 경주 중 DNF | 출주 후 미완주 |
| 실격 | 완주 후 실격. 시계는 남음 | 출주·완주 후 착순 말소 |
| 경주취소 | 경주 자체가 취소 (제주 악천후 등) | 경주 무효 |

```sql
SELECT COALESCE(rank_remark, '(NULL)') AS rank_remark,
       finish_position,
       COUNT(*) AS n
FROM race_results
WHERE rank_remark IS NOT NULL
GROUP BY rank_remark, finish_position
ORDER BY n DESC;
```

## 3. `disqualified=true` 전수

`disqualified` 는 **전 43,463행이 정수 0**이다. true 행은 없다.

실격은 컬럼이 아니라 특수코드로만 남는다.

| 경주일 | 경마장 | R | 출주 | 착순 | 기록 | 착차 | 비고 | `disqualified` | `scratched` |
|---|---|---:|---:|---:|---|---|---|---:|---:|
| 2026-05-10 | 서울 | 9 | #4 | **91** | 1:16.3 | 2 | 실격 | 0 | 0 |

같은 경주 착순: `1,2,3,4,5, 7,8,9,10` + 91 실격 + 92 주행중지.
#4의 시계(76.3초)는 5착(75.9초)과 7착(76.4초) 사이라, 원래 6착이었다가
실격되며 **6착이 비는** 형태다. 공식 1~3착은 그대로다.

정책: `disqualified` 플래그는 쓰지 않는다. `finish_position ≥ 90` 이면
라벨 행에서 제외(또는 전부 음수 — §8). 남은 말의 공식 착순은 재계산하지 않는다.

```sql
SELECT disqualified, COUNT(*) FROM race_results GROUP BY disqualified;

SELECT r.race_date_local, c.name_ko, r.race_number, e.horse_number,
       rr.finish_position, rr.finish_time_ms, rr.margin_text, rr.rank_remark
FROM race_results rr
JOIN race_entries e ON e.id = rr.race_entry_id
JOIN races r ON r.id = e.race_id
JOIN racecourses c ON c.id = r.racecourse_id
WHERE rr.rank_remark = '실격';
```

## 4. 특수코드 `finish_position ≥ 90`

837행. 존재하는 값은 아래 여섯 개뿐. 90·96·97·98은 **0건**.

| 코드 | 행 수 | `rank_remark` | `scratched` | `finish_time_ms` | `race_scratches` 겹침 |
|---:|---:|---|---:|---|---|
| 91 | 1 | 실격 | 0 | 1건 있음 | 없음 |
| 92 | 79 | 주행중지 | 0 | 없음 | 없음 |
| 93 | 4 | 출발제외 | 4 | 없음 | **4/4** |
| 94 | 315 | 경주제외 | 315 | 없음 | **315/315** |
| 95 | 192 | 출전취소 | 192 | 없음 | **192/192** |
| 99 | 246 | 경주취소 | 0 | 없음 | 없음 |

UI용 `SPECIAL_FINISH_LABELS`(91=출전취소, 92=출전제외, …)는 이 표와
**일치하지 않는다.** 라벨·제외 로직은 이 실측 표를 따른다.

### 4.1 `race_scratches` 대조

`race_scratches` 512행은 전부 출전 행과 조인된다.
512행 모두 `scratched=true`.

| 조인 결과 | 건수 |
|---|---:|
| 특수코드 93·94·95 | 511 |
| 착순 NULL (2025-12-26 부산 R6 #9, 공백 경주) | 1 |
| 정상 착순 1~89 | **0** |
| 91·92·99 와 겹침 | **0** |

즉 출전취소 테이블은 **미출주(93/94/95)** 와 같고,
주행중지·실격·경주취소는 별 경로다.

출발제외 4건 사유: 진입거부 2, 진입불량 1, 출발 준비 중 방마 1.
경주제외 다수 사유는 `마체이상`(182)과 입장·낙마 계열.
출전취소 다수 사유는 절음·산통 등 수의학적 사전 취소.

```sql
SELECT rr.finish_position, rr.rank_remark, COUNT(*) AS n,
       SUM(e.scratched) AS n_scratched
FROM race_results rr
JOIN race_entries e ON e.id = rr.race_entry_id
WHERE rr.finish_position >= 90
GROUP BY rr.finish_position, rr.rank_remark
ORDER BY rr.finish_position;
```

### 4.2 경주취소(99) · 주행중지(92)

- 99가 있는 경주 25건 중 **24건은 전원 99** (제주 취소일:
  2025-05-03 R4–6, 2025-05-09 R7, 2026-03-20 전 경주 등).
- 혼합 1건: 2025-05-24 제주 R2 — #1–#9는 99, #10은 94 경주제외
  (`scratched`). 라벨 가능한 말이 없어 경주 제외와 같다.
- 92(주행중지) 70경주: 64경주는 1두, 소수만 2~4두.
  70경주 **전부 1착이 있다.** 완주마 착순은 1…n 연속
  (실격과 겹친 2026-05-10 서울 R9만 6착 공백).

## 5. `scratched=true` 인데 정상 착순인 모순

**0건.**

| `scratched` | 착순 1~89 | `≥90` | NULL | 합 |
|---:|---:|---:|---:|---:|
| 0 | 42,495 | 326 | 130 | 42,951 |
| 1 | **0** | 511 | 1 | 512 |

`scratched=1` 의 511 특수코드는 93·94·95뿐. NULL 1행은
2025-12-26 부산경남 R6 #9 (경주 전원 착순 공백 + 출전취소 테이블 등록).

`scratched=0` 이면서 `≥90` 인 326행은 99(246)+92(79)+91(1)이다.
모순이 아니라 **출주 후 특수 처리**다.

```sql
SELECT COUNT(*) AS n_contradiction
FROM race_entries e
JOIN race_results rr ON rr.race_entry_id = e.id
WHERE e.scratched = 1
  AND rr.finish_position BETWEEN 1 AND 89;
```

## 6. `finish_position` NULL 131행

**12경주 전원 NULL.** 일부만 NULL인 혼합 경주는 0건.
알려진 착순 공백과 **정확히 일치**한다.

| 경주일 | 경마장 | 경주 | 행 수 | 알려진 원인 |
|---|---|---|---:|---|
| 2025-12-13 | 제주 | R6 | 12 | 2025 제주 R6 공백 |
| 2025-12-20 | 제주 | R6 | 8 | 2025 제주 R6 공백 |
| 2025-12-26 | 부산경남 | R6 | 12 | 2025 부산 R6 공백 |
| 2026-07-06 | 서울 | R1–R6 | 66 | API 착순 공백 (같은 날 R7은 정상 16두) |
| 2026-07-06 | 부산경남 | R1–R3 | 33 | API 착순 공백 (국제 트로피일) |
| **합** | | **12경주** | **131** | |

2026-07-07은 착순이 **정상**이다 (서울 6경주·제주 4경주).
07-06/07 “API 공백”은 구간기록(`API4_3`) 이슈이고, 착순 NULL은 07-06만이다.

정책: 이 12경주는 경주 단위로 학습·평가에서 제외.
행만 빼고 경주를 남길 정상 착순이 없다.

```sql
SELECT r.race_date_local, c.name_ko, COUNT(*) AS n_null_rows,
       COUNT(DISTINCT r.id) AS n_races,
       GROUP_CONCAT(DISTINCT r.race_number) AS race_numbers
FROM race_results rr
JOIN race_entries e ON e.id = rr.race_entry_id
JOIN races r ON r.id = e.race_id
JOIN racecourses c ON c.id = r.racecourse_id
WHERE rr.finish_position IS NULL
GROUP BY r.race_date_local, c.kra_meet_code
ORDER BY 1, c.kra_meet_code;
```

## 7. 1착 없는 완료 경주

`status='completed'` 4,145경주.

| 유형 | 경주 수 | 출전 행 | 라벨 가능? |
|---|---:|---:|---|
| 정상 착순 있음, 1착 있음 (단일) | 4,103 | — | 예 |
| 정상 착순 있음, 1착 동착 2두 | 5 | — | 예 (`win` 2두) |
| 전원 특수코드 (주로 경주취소) | 25 | 247 | 아니오 |
| 전원 착순 NULL (§6) | 12 | 131 | 아니오 |
| **정상 착순 있는데 1착 없음** | **0** | | |

정상 착순이 한 두라도 있는 4,108경주는 모두 `MIN(pos)=1` 이다.
라벨 무결성 결함은 없다.

```sql
SELECT e.race_id
FROM race_results rr
JOIN race_entries e ON e.id = rr.race_entry_id
WHERE rr.finish_position BETWEEN 1 AND 89
GROUP BY e.race_id
HAVING MIN(rr.finish_position) != 1;
-- 0 rows
```

## 8. 확정 라벨 정책

계획([MODELING_ROADMAP](MODELING_ROADMAP.md) §2.2)을 실측으로 고정한다.
**바꾸는 것은 실격 플래그·특수코드 표·동착 스킵을 명시한 것뿐이다.**

### 8.1 행 포함

| 조건 | 학습·평가 행 | 경주 내 출주 두수 |
|---|---|---|
| `1 ≤ finish_position ≤ 89` | **포함.** win=(pos==1), top2=(pos≤2), top3=(pos≤3) | 포함 |
| `scratched=true` 또는 pos ∈ {93,94,95} | 제외 (미출주) | 제외 |
| pos = 99 (경주취소) | 제외. 사실상 경주 제외 | 경주 제외 |
| pos = 92 (주행중지) | 제외 (미완주, 공식 착순 없음) | **포함** (출주함) |
| pos = 91 (실격) | 제외 (공식 착순 말소) | **포함** (출주함) |
| `finish_position IS NULL` | 제외. 경주 전원 NULL이면 경주 제외 | — |

91·92는 80행뿐이라 제외해도 표본은 거의 안 줄지만, 예측 시점에는
실격·주행중지를 모르므로 **출주 두수에는 넣는다.**
원하면 이후 변형으로 91·92를 `win=top2=top3=0` 음수 행으로 남길 수 있다.
v1은 제외가 계획과 같고 구현이 단순하다.

`착변`(`margin_text`)은 공식 착순에 이미 반영되어 있다. 재조정하지 않는다.

### 8.2 동착 규칙 (top2 / top3)

착순을 다시 매기지 않는다. **올림픽 스킵을 그대로 쓴다.**

| 공식 순서 | win | top2 (`pos≤2`) | top3 (`pos≤3`) |
|---|---|---|---|
| 1,1,3 (1착 동착, 5경주) | 두 1착 | 그 2두만 (2착 없음) | 2두 + 3착 = 3 |
| 1,2,2,4 (2착 동착, 9경주) | 1착 1두 | 1착+두 2착 = **3** | 같은 3두 (3착 없음) |
| 1,2,3,3,5 (3착 동착, 10경주) | 1착 1두 | 2두 | 1·2·두 3착 = **4** |

정상 착순 42,495행 기준 라벨 양성: win **4,113** / top2 **8,225** / top3 **12,334**.
win 양성 4,113 = 1착 있는 경주 4,108 + 동착 여분 5.

예측 확률은 경주 안에서 `Σ P(win) = 1` 로 정규화한다.
평가 때는 공식 라벨을 그대로 두어 **한 경주에 win=1이 두 말**일 수 있다.
밀집 순위(1,1,2)로 바꾸면 1착 동착의 3착 말이 top2가 되어 공식 복승
대상과 어긋난다.

### 8.3 구현 시 특수코드 표 (실측)

| `finish_position` | `rank_remark` |
|---:|---|
| 91 | 실격 |
| 92 | 주행중지 |
| 93 | 출발제외 |
| 94 | 경주제외 |
| 95 | 출전취소 |
| 99 | 경주취소 |

제외 판정은 `pos ≥ 90 OR pos IS NULL OR scratched` 로 충분하다.
의미 표시만 위 표를 쓴다.

### 8.4 경주 필터와의 관계

최소 요건(완료, 출주 두수 ≥ 5) 적용 전 분모:

- 라벨 가능한 경주: **4,108**
- 경주 제외 후보: 전원 특수 25 + 전원 NULL 12 = **37**

구현 후 연도·경마장별 제외 행 통계를 데이터셋 리포트에 넣는다
(로드맵 §2.2 후속).
