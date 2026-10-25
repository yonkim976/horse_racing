"""Check stored literal phrases against their captured KRA table cells."""

from __future__ import annotations

import html
import json
from pathlib import Path

import duckdb

PACKAGE = Path(__file__).resolve().parent
OUTPUT = PACKAGE / "outputs"
DB = OUTPUT / "horse_steward_phrases.duckdb"


def main():
    summary = json.loads((OUTPUT / "summary.json").read_text())
    with duckdb.connect(str(DB), read_only=True) as con:
        violations = {}
        violations["phrase_is_exact_website_cell_slice"] = con.execute("""
          SELECT count(*) FROM website_phrase_observations p
          JOIN website_card_rows r USING(website_row_id)
          WHERE substr(r.website_text_raw,p.span_start_codepoint+1,
                       p.span_end_codepoint-p.span_start_codepoint)<>p.phrase_text
        """).fetchone()[0]
        violations["phrase_keeps_parent_horse_and_history_key"] = con.execute("""
          SELECT count(*) FROM website_phrase_observations p
          JOIN website_card_rows r USING(website_row_id)
          WHERE p.horse_id<>r.horse_id OR p.event_meet<>r.event_meet
             OR p.event_date<>r.event_date OR p.event_race<>r.event_race
             OR p.current_program<>r.current_program
        """).fetchone()[0]
        violations["primary_view_has_only_verified_website_text"] = con.execute("""
          SELECT count(*) FROM horse_steward_phrases
          WHERE text_basis<>'official_website' OR NOT website_text_verified
        """).fetchone()[0]
        violations["published_history_has_complete_identity_key"] = con.execute("""
          SELECT count(*) FROM horse_steward_phrases
          WHERE horse_id IS NULL OR NOT regexp_full_match(horse_id,'[0-9]{7}')
            OR event_meet IS NULL OR event_date IS NULL OR event_race IS NULL
            OR historical_program IS NULL OR historical_program<=0
        """).fetchone()[0]
        violations["every_valid_observation_has_published_lineage"] = con.execute("""
          SELECT count(*) FROM website_phrase_observations p
          WHERE historical_identity_status='verified' AND current_identity_status<>'conflict'
            AND text_identity_status<>'conflict' AND NOT EXISTS (
              SELECT 1 FROM website_horse_phrase_history h
              CROSS JOIN json_each(h.source_phrase_ids_json) j
              WHERE json_extract_string(j.value,'$')=p.website_phrase_id)
        """).fetchone()[0]
        violations["unresolved_identity_not_in_published_history"] = con.execute("""
          SELECT count(*) FROM website_horse_phrase_history h
          CROSS JOIN json_each(h.source_phrase_ids_json) j
          JOIN website_phrase_observations p
            ON p.website_phrase_id=json_extract_string(j.value,'$')
          WHERE p.historical_identity_status<>'verified' OR p.current_identity_status='conflict'
             OR p.text_identity_status='conflict'
        """).fetchone()[0]
        violations["published_history_lineage_is_present"] = con.execute("""
          SELECT count(*) FROM website_horse_phrase_history h
          CROSS JOIN json_each(h.source_phrase_ids_json) j
          LEFT JOIN website_phrase_observations p
            ON p.website_phrase_id=json_extract_string(j.value,'$')
          WHERE p.website_phrase_id IS NULL
        """).fetchone()[0]
        empty_count = con.execute(
            "SELECT count(*) FROM website_card_rows WHERE field_state='empty'"
        ).fetchone()[0]
        published_observations = con.execute(
            "SELECT sum(source_observation_count) FROM website_horse_phrase_history"
        ).fetchone()[0]
        venue_counts = con.execute("""
          SELECT event_meet,count(*),count(DISTINCT horse_id),min(event_date),max(event_date)
          FROM horse_steward_phrases GROUP BY 1 ORDER BY 1
        """).fetchall()
        status_counts = con.execute("""
          SELECT comparison_status,count(*) FROM website_api_comparison GROUP BY 1 ORDER BY 1
        """).fetchall()
        samples = con.execute("""
          WITH chosen AS (
            SELECT *,row_number() OVER(PARTITION BY card_meet,substr(card_date,1,4)
                                      ORDER BY source_url,row_index,bullet_index) rn
            FROM website_phrase_observations WHERE historical_identity_status='verified'
              AND current_identity_status<>'conflict'
              AND text_identity_status<>'conflict'
          ) SELECT horse_name_raw,horse_id,card_date,current_program,event_meet,event_date,
                   event_race,historical_program,phrase_text,source_url
            FROM chosen WHERE rn<=2 ORDER BY card_date,card_meet,rn
        """).fetchall()
        references = con.execute("""
          SELECT horse_name_raw,horse_id,card_date,current_program,event_meet,event_date,
                 event_race,historical_program,phrase_text,source_url
          FROM website_phrase_observations
          WHERE ((card_meet=3 AND card_date='2018-02-23' AND card_race=9)
             OR (card_meet=1 AND card_date='2026-10-11' AND card_race=7))
            AND historical_identity_status='verified' AND current_identity_status<>'conflict'
            AND text_identity_status<>'conflict'
          ORDER BY card_date,current_program,event_date
        """).fetchall()
    checks = dict(
        violations=violations,
        all_passed=not any(violations.values()),
        checked_website_phrases=summary["counts"]["website_phrase_observations"],
        independent_html_rows=summary["independent_html_row_parity_count"],
        empty_website_rows_preserved=empty_count,
        published_source_observation_count=published_observations,
        target_horses=summary["target_horse_count"],
        target_horses_with_website_row=summary["target_horses_with_website_row"],
        missing_target_horses=summary["target_horses_missing_website_row"],
        venue_history_counts=venue_counts,
        website_api_comparison=status_counts,
    )
    (OUTPUT / "verification.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not checks["all_passed"]:
        raise ValueError(f"stored phrase validation failed: {violations}")
    e = html.escape

    def rows(records):
        result = []
        for name, horse, card, now, meet, event, race, past, text, url in records:
            result.append(
                f"<tr><td>{e(name)}<small>{e(horse)}</small></td>"
                f"<td>{e(card)}<br>{now}번</td><td>{meet} · {e(event)} · {race}R<br>{past}번</td>"
                f"<td><pre>{e(text)}</pre>"
                f"<a href='{e(url, quote=True)}'>마사회 원문 표</a></td></tr>"
            )
        return "\n".join(result)

    document = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
    <title>말별 심판 문구 저장·홈페이지 대조</title>
    <style>body{{font:16px/1.6 system-ui;margin:40px auto;max-width:1250px;color:#18212b}}
    h1{{font-size:28px}}table{{border-collapse:collapse;width:100%;margin:24px 0}}
    td,th{{border:1px solid #d6dde5;padding:12px;vertical-align:top;text-align:left}}
    th{{background:#eef3f8}}pre{{white-space:pre-wrap;font:inherit;margin:0 0 8px}}
    small{{display:block;color:#596778}}a{{color:#1564af}}.box{{background:#edf7f2;padding:20px}}</style>
    <h1>말별 심판 문구 저장·홈페이지 대조</h1>
    <p class="box">홈페이지 문구 {summary["counts"]["website_phrase_observations"]:,}관측,
    기본 조회 {summary["counts"]["horse_steward_phrases"]:,}문구.
    HTML 표 {summary["independent_html_row_parity_count"]:,}행을 별도 파서로 대조했습니다.
    보유 심판자료 {summary["target_horse_count"]:,}두 중
    {summary["target_horses_with_website_row"]:,}두의 홈페이지 행을 확보했습니다.</p>
    <p>본문은 홈페이지에 실제 배치된 문구입니다. 현재 출전번호와 과거 경주의 번호를 구분하며
    공식 마번으로 연결했습니다. 한 문구에 등장하는 다른 말은 원문대로 남겼습니다.
    상황 분류는 하지 않았습니다. 홈페이지는 선택한 출전표 기준 최근 1년의 이력이며,
    이번 조회가 각 말의 생애 전체 기록을 포함한다는 뜻은 아닙니다.</p>
    <p>API 원문 연결 {summary["counts"]["api_horse_paragraphs"]:,}행은 별도 대조 자료로 보존합니다.
    기본 조회에는 홈페이지에서 직접 확보하고 과거 명부와 연결한 문구만 제공합니다.</p>
    <h2>대화에서 사용한 실제 출전표</h2>
    <table><tr><th>말·공식 마번</th><th>조회 출전표·현재 번호</th>
    <th>과거 경주·당시 번호</th><th>저장한 홈페이지 문구</th></tr>{rows(references)}</table>
    <h2>지역·연도별 저장 예시</h2>
    <table><tr><th>말·공식 마번</th><th>조회 출전표·현재 번호</th>
    <th>과거 경주·당시 번호</th><th>저장한 홈페이지 문구</th></tr>{rows(samples)}</table>
    </html>"""
    (OUTPUT / "comparison_report.html").write_text(document, encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
