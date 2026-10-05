"""Reproduce the per-race evidence ledger for unresolved zero-time Jeju races."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUTPUT = Path(__file__).with_name("unresolved_76_review.jsonl")
EVIDENCE = Path(__file__).with_name("official_period_evidence.jsonl")
EARLY_RPT_EVIDENCE = Path(__file__).with_name("official_rpt_early_evidence.jsonl")
HEADING = re.compile(r"제목\s*:\s*\d{4}년\d{2}월\d{2}일[^\n]*?제\s*(\d+)경주")
OFFICIAL_WEB_RESULTS_URL = "https://race.kra.co.kr/raceScore/scoretablePeriodScoreList.do"


def official_cause(reason: str | None) -> str | None:
    if reason is None:
        return None
    if "안개" in reason:
        return "dense_fog"
    if "태풍" in reason:
        return "typhoon_nari"
    if "주로상태 불량" in reason:
        return "poor_track_condition"
    if "출발불성립" in reason:
        return "invalid_start"
    if "출발대 고장" in reason:
        return "starting_gate_failure"
    raise ValueError(f"Unclassified official reason: {reason}")


def report_path(race_date: str) -> Path:
    year, month, day = race_date.split("-")
    return (
        ROOT
        / "data/raw/kra_text/dacom11"
        / "meet=2"
        / f"year={year}"
        / f"month={month}"
        / f"day={day}"
        / f"{year}{month}{day}dacom11.rpt"
    )


def main() -> None:
    evidence_rows = [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines()]
    evidence = {(row["race_date"], row["race_number"]): row for row in evidence_rows}
    if len(evidence) != 76 or len(evidence_rows) != 76:
        raise ValueError("Official evidence does not cover exactly 76 distinct races")
    rpt_rows = [json.loads(line) for line in EARLY_RPT_EVIDENCE.read_text(encoding="utf-8").splitlines()]
    early_rpt = {(row["race_date"], row["race_number"]): row for row in rpt_rows}
    if len(early_rpt) != 7 or len(rpt_rows) != 7:
        raise ValueError("Expected exactly seven early official RPT checks")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        races = conn.execute(
            """SELECT race_date, race_number, count(*) AS entrant_rows,
                      group_concat(DISTINCT weather_raw) AS api_weather,
                      group_concat(DISTINCT finish_status_raw) AS api_status,
                      min(finish_time_seconds) AS min_time,
                      max(finish_time_seconds) AS max_time
               FROM jeju_race_population_candidates
               WHERE meet_code=2 AND
                    (race_date<'2017-10-13' OR (race_date='2021-01-22' AND race_number=1))
               GROUP BY race_date, race_number
               HAVING max(finish_time_seconds)=0
               ORDER BY race_date, race_number"""
        ).fetchall()
        if len(races) != 76 or sum(r["entrant_rows"] for r in races) != 680:
            raise ValueError("The unresolved population has changed")

        ledger = []
        for race in races:
            date, number = race["race_date"], race["race_number"]
            codes = conn.execute(
                """SELECT DISTINCT json_extract(a.payload_json,'$.ord')
                   FROM jeju_race_population_candidates r
                   JOIN api_records a USING(api_record_id)
                   WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=?
                   ORDER BY 1""",
                (date, number),
            ).fetchall()
            corner = conn.execute(
                """SELECT corner_1_raw,corner_2_raw,corner_3_raw,corner_4_raw,
                          corner_5_raw,corner_6_raw,corner_7_raw,corner_8_raw,
                          corner_9_raw,passtime_3f_raw,passtime_4f_raw
                   FROM api303_corner_rank_rows
                   WHERE race_date=? AND meet_code=2 AND race_number=?""",
                (date, number),
            ).fetchone()
            if corner and tuple(corner) != (
                "-", "-", "-", "-", "X", "X", "-", "-", "X", "0:00.0", "0:00.0"
            ):
                raise ValueError(f"Unexpected API303 values for {date} {number}R")
            path = report_path(date)
            if path.exists():
                text = path.read_bytes().decode("cp949", errors="replace")
                headings = {int(match) for match in HEADING.findall(text)}
                if number in headings or not any(heading > number for heading in headings):
                    raise ValueError(f"Unexpected report evidence for {date} {number}R")
                report_status = "target_absent_later_races_present"
                report_file = str(path.relative_to(ROOT))
            else:
                report_status = "local_report_not_archived"
                report_file = None
            official = evidence[(date, number)]
            reason_text = official["official_detail_text"]
            cause = official_cause(reason_text)
            if official["official_cancel_confirmed"] != bool(cause):
                raise ValueError(f"Official cancellation mismatch: {date} {number}R")
            rpt = early_rpt.get((date, number))
            if bool(rpt) != (cause is None):
                raise ValueError(f"Early RPT check mismatch: {date} {number}R")
            if rpt:
                early_rpt_status = (
                    "target_result_absent_later_result_present"
                    if rpt["later_result_heading_present"]
                    else "no_rpt_result_evidence"
                )
            else:
                early_rpt_status = None
            ledger.append(
                {
                    "race_date": date,
                    "race_number": number,
                    "entrant_rows": race["entrant_rows"],
                    "api4_3_finish_time_seconds": 0,
                    "api4_3_ord_codes": [row[0] for row in codes],
                    "api4_3_weather_raw": (race["api_weather"] or "").split(","),
                    "api303_status": "corner_and_time_placeholders" if corner else "absent",
                    "dacom11_status": report_status,
                    "dacom11_file": report_file,
                    "api_valid_completed_result_present": False,
                    "official_website_cause": cause,
                    "official_website_reason_text": reason_text,
                    "official_website_checked_on": official["checked_on"],
                    "official_website_results_url": OFFICIAL_WEB_RESULTS_URL,
                    "official_website_detail_status": (
                        "explicit_cancellation_reason" if cause else "blank_detail_unconfirmed"
                    ),
                    "official_website_response_sha256": official["response_sha256"],
                    "official_website_raw_html_file": official["raw_html_file"],
                    "official_early_rpt_status": early_rpt_status,
                    "official_early_rpt_raw_file": rpt["raw_rpt_file"] if rpt else None,
                    "official_early_rpt_response_sha256": rpt["response_sha256"] if rpt else None,
                    "exact_cause_status": "official_website_confirmed" if cause else "unconfirmed",
                }
            )
        if sum(row["dacom11_status"] == "target_absent_later_races_present" for row in ledger) != 14:
            raise ValueError("Unexpected dacom11 coverage")
        if sum(row["api303_status"] == "corner_and_time_placeholders" for row in ledger) != 63:
            raise ValueError("Unexpected API303 coverage")
        if sum(row["official_website_cause"] == "dense_fog" for row in ledger) != 64:
            raise ValueError("Unexpected official-web fog coverage")
        if sum(row["exact_cause_status"] == "unconfirmed" for row in ledger) != 7:
            raise ValueError("Unexpected unconfirmed coverage")
        if sum(row["official_early_rpt_status"] == "target_result_absent_later_result_present" for row in ledger) != 2:
            raise ValueError("Unexpected early RPT result-omission coverage")
        with OUTPUT.open("w", encoding="utf-8") as output:
            for row in ledger:
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"Wrote {len(ledger)} races, {sum(row['entrant_rows'] for row in ledger)} rows to {OUTPUT}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
