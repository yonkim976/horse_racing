-- Retrospective, final-odds descriptive analysis. Never an executable pre-race strategy.
-- Run: sqlite3 -header -csv data/horse_racing.sqlite3 < scripts/research_odds_rank_roi_2025_2026.sql
-- Each race/horse gets one flat unit ticket for WIN and, separately, PLC.
-- PLC pays top 2 in 5-7 runner races and top 3 in >=8 runner races.
-- Exact equal odds share all occupied rank slots equally, avoiding horse-number bias.
WITH RECURSIVE
entry_data AS (
  SELECT r.id AS race_id,
         substr(r.race_date_local, 1, 4) AS year,
         e.horse_number,
         e.scratched,
         rr.finish_position,
         w.odds AS win_odds,
         p.odds AS plc_odds
  FROM races AS r
  JOIN race_entries AS e ON e.race_id = r.id
  LEFT JOIN race_results AS rr ON rr.race_entry_id = e.id
  LEFT JOIN odds_snapshots AS w
    ON w.race_id = r.id AND w.bet_type = 'WIN'
   AND w.selection_key = CAST(e.horse_number AS TEXT)
  LEFT JOIN odds_snapshots AS p
    ON p.race_id = r.id AND p.bet_type = 'PLC'
   AND p.selection_key = CAST(e.horse_number AS TEXT)
  WHERE r.race_date_local BETWEEN '2025-01-01' AND '2026-09-13'
    AND r.status = 'completed'
),
race_quality AS (
  SELECT race_id,
         year,
         SUM(CASE WHEN scratched = 0 THEN 1 ELSE 0 END) AS runners,
         SUM(CASE WHEN scratched = 0 AND finish_position IS NULL THEN 1 ELSE 0 END) AS missing_result,
         SUM(CASE WHEN scratched = 0 AND (win_odds IS NULL OR win_odds < 1 OR win_odds >= 9999.9)
                  THEN 1 ELSE 0 END) AS invalid_win,
         SUM(CASE WHEN scratched = 0 AND (plc_odds IS NULL OR plc_odds < 1 OR plc_odds >= 9999.9)
                  THEN 1 ELSE 0 END) AS invalid_plc,
         SUM(CASE WHEN scratched = 0 AND finish_position = 1 THEN 1 ELSE 0 END) AS winners
  FROM entry_data
  GROUP BY race_id, year
),
eligible AS (
  SELECT d.race_id, d.year, d.horse_number, d.finish_position,
         q.runners, d.win_odds, d.plc_odds
  FROM entry_data AS d
  JOIN race_quality AS q ON q.race_id = d.race_id
  WHERE d.scratched = 0 AND q.runners >= 5
    AND q.missing_result = 0 AND q.invalid_win = 0
    AND q.invalid_plc = 0 AND q.winners >= 1
),
tickets AS (
  SELECT race_id, year, horse_number, 'WIN' AS bet_type,
         win_odds AS odds, CASE WHEN finish_position = 1 THEN 1 ELSE 0 END AS hit
  FROM eligible
  UNION ALL
  SELECT race_id, year, horse_number, 'PLC' AS bet_type,
         plc_odds AS odds,
         CASE WHEN finish_position <= CASE WHEN runners >= 8 THEN 3 ELSE 2 END
              THEN 1 ELSE 0 END AS hit
  FROM eligible
),
ranked AS (
  SELECT *,
         RANK() OVER (PARTITION BY race_id, bet_type ORDER BY odds) AS first_rank,
         COUNT(*) OVER (PARTITION BY race_id, bet_type, odds) AS tied_count
  FROM tickets
),
rank_offsets(k) AS (
  SELECT 0 UNION ALL SELECT k + 1 FROM rank_offsets WHERE k < 15
),
rank_shares AS (
  SELECT r.year, r.bet_type, r.first_rank + s.k AS odds_rank,
         r.odds, r.hit, 1.0 / r.tied_count AS share
  FROM ranked AS r
  JOIN rank_offsets AS s ON s.k < r.tied_count
),
summary AS (
  SELECT year, bet_type, odds_rank,
         SUM(share) AS tickets,
         SUM(hit * share) AS hits,
         SUM(odds * share) / SUM(share) AS average_final_odds,
         SUM(hit * odds * share) / SUM(share) AS return_multiple
  FROM rank_shares
  GROUP BY year, bet_type, odds_rank
)
SELECT year, bet_type, odds_rank,
       ROUND(tickets, 6) AS tickets,
       ROUND(hits, 6) AS hits,
       ROUND(100.0 * hits / tickets, 4) AS hit_percent,
       ROUND(average_final_odds, 4) AS average_final_odds,
       ROUND(100.0 * return_multiple, 4) AS return_percent
FROM summary
ORDER BY bet_type, year, odds_rank;
