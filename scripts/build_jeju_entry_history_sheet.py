"""Add verified prior race results to the 2026-09-17 Jeju entry sheet."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from build_jeju_basic_info_sheet import (
    DATE,
    DB,
    FONT,
    GREEN,
    INK,
    LINE,
    MUTED,
    PALE,
    ROOT,
    draw_page,
    fit_text,
    load_data,
    source_document,
)


MAIN_OUTPUT = ROOT / "output/pdf/jeju_2026-09-17_entry_with_recent_history.pdf"
APPENDIX_OUTPUT = ROOT / "output/pdf/jeju_2026-09-17_full_horse_history_appendix.pdf"
EXCLUDED_API_DATE = "2026-07-07"


def format_time(milliseconds: int | None) -> str:
    if milliseconds is None or milliseconds <= 0:
        return "-"
    minutes, tenths = divmod(round(milliseconds / 100), 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def short_grade(value: str | None) -> str:
    return (value or "-").removeprefix("제").replace("등급", "등")


def finish_label(row: dict) -> str:
    position = row["finish_position"]
    if position == 91:
        return "실격"
    if position == 92:
        return "중지"
    return str(position)


def load_verified_history(races: list[dict]) -> tuple[int, int]:
    """Match every horse's prior starts and 1-3 places to the KRA entry sheet."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    entry_doc = source_document(conn, "/API26_2/entrySheet_2")
    entry_items = json.loads((ROOT / entry_doc["local_path"]).read_text())["response"]["body"]["items"]["item"]
    official = {str(item["hrNo"]): item for item in entry_items}
    if len(official) != 76:
        raise RuntimeError("The official entry sheet does not contain 76 unique horse IDs")

    total = 0
    without_history = 0
    unmatched_total = 0
    for race in races:
        for entry in race["entries"]:
            horse_id = entry["kra_horse_id"]
            source = official[horse_id]
            all_results = [dict(row) for row in conn.execute(
                """
                SELECT r.race_date_local, r.race_number, r.grade, r.distance_m,
                       r.field_size, c.name_ko AS course, c.kra_meet_code,
                       e.horse_number, e.carried_weight_kg,
                       j.name_ko AS jockey, rr.finish_position, rr.finish_time_ms,
                       rr.rank_remark
                FROM horses h
                JOIN race_entries e ON e.horse_id = h.id
                JOIN races r ON r.id = e.race_id
                JOIN racecourses c ON c.id = r.racecourse_id
                JOIN race_results rr ON rr.race_entry_id = e.id
                LEFT JOIN jockeys j ON j.id = e.jockey_id
                WHERE h.kra_horse_id = ? AND r.race_date_local < ?
                  AND rr.finish_position BETWEEN 1 AND 92
                ORDER BY r.race_date_local DESC, r.race_number DESC
                """,
                (horse_id, DATE),
            )]
            history = [row for row in all_results if row["race_date_local"] != EXCLUDED_API_DATE]
            unmatched = [row for row in all_results if row["race_date_local"] == EXCLUDED_API_DATE]
            if any(row["kra_meet_code"] != 2 for row in history):
                raise RuntimeError(f"Unexpected non-Jeju prior result for {horse_id}")
            places = Counter(row["finish_position"] for row in history)
            expected_places = tuple(int(source[f"ord{n}CntT"]) for n in (1, 2, 3))
            actual_places = tuple(places[n] for n in (1, 2, 3))
            if len(history) != int(source["rcCntT"]) or actual_places != expected_places:
                raise RuntimeError(
                    f"Historical results disagree with the official career summary: "
                    f"{horse_id} {entry['horse_name']} {len(history)} / {source['rcCntT']} "
                    f"{actual_places} / {expected_places}"
                )
            entry["history"] = history
            entry["unmatched_history"] = unmatched
            entry["career_places"] = actual_places
            total += len(history)
            without_history += not history
            unmatched_total += len(unmatched)
    conn.close()
    if total != 1616 or without_history != 6 or unmatched_total != 9:
        raise RuntimeError(
            f"Unexpected historical coverage: {total} starts, "
            f"{without_history} horses without starts, {unmatched_total} unmatched results"
        )
    return total, without_history


def draw_result_columns(pdf: canvas.Canvas, x: float, y: float, row: dict | None) -> None:
    starts = [0, 24, 37, 53, 69, 80, 102, 124, 140]
    widths = [23, 12, 15, 15, 10, 21, 21, 15, 27]
    if row is None:
        values = ["일자", "경주", "등급", "거리", "마번", "착순/편성", "주파기록", "부담", "기수"]
        color, size = MUTED, 7.1
    else:
        values = [
            row["race_date_local"][2:].replace("-", "."),
            f"{row['race_number']}R",
            short_grade(row["grade"]),
            f"{row['distance_m']}m",
            str(row["horse_number"]),
            f"{finish_label(row)}/{row['field_size']}",
            format_time(row["finish_time_ms"]),
            f"{row['carried_weight_kg']:.1f}" if row["carried_weight_kg"] is not None else "-",
            row["jockey"] or "-",
        ]
        color, size = INK, 7.7
    pdf.setFillColor(color)
    for offset, width, value in zip(starts, widths, values, strict=True):
        fit_text(pdf, value, x + offset * mm, y, width * mm, size)


def draw_recent_history_page(
    pdf: canvas.Canvas, race: dict, entries: list[dict], part: int,
    page_number: int, total_pages: int, retrieved: datetime,
) -> None:
    width, height = A4
    left, right = 12 * mm, width - 12 * mm
    pdf.setFillColor(INK)
    fit_text(pdf, "TRACK NOTE  /  최근 5회 경주기록", left, height - 16 * mm, 120 * mm, 12)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "2026.09.17 목요일 · 제주", right - 57 * mm, height - 16 * mm, 57 * mm, 9)
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(1.6 * mm)
    pdf.line(left, height - 21 * mm, right, height - 21 * mm)
    pdf.setFillColor(GREEN)
    fit_text(pdf, "RACE HISTORY / 과거 출전 성적", left, height - 30 * mm, 110 * mm, 8.4)
    pdf.setFillColor(INK)
    fit_text(pdf, f"제주 {race['race_number']}경주  ·  최근 5회", left, height - 42 * mm, 150 * mm, 19)
    pdf.setFillColor(MUTED)
    fit_text(
        pdf,
        f"{race['grade']}  |  {race['distance_m']}m  |  {race['field_size']}두  |  출전번호순  |  {part}/2",
        left, height - 50 * mm, 178 * mm, 9.2,
    )

    card_top = height - 60 * mm
    card_height = 38 * mm
    card_gap = 2 * mm
    for index, entry in enumerate(entries):
        top = card_top - index * (card_height + card_gap)
        bottom = top - card_height
        pdf.setStrokeColor(LINE)
        pdf.setLineWidth(0.55)
        pdf.roundRect(left, bottom, right - left, card_height, 1.6 * mm, fill=0, stroke=1)
        pdf.setFillColor(PALE)
        pdf.roundRect(left, bottom, 13 * mm, card_height, 1.6 * mm, fill=1, stroke=0)
        pdf.setFillColor(GREEN)
        fit_text(pdf, f"{entry['horse_number']:02d}", left + 3 * mm, top - 7.5 * mm, 10 * mm, 12)
        pdf.setFillColor(INK)
        fit_text(pdf, entry["horse_name"], left + 17 * mm, top - 6.5 * mm, 68 * mm, 11.2)
        one, two, three = entry["career_places"]
        summary = f"통산 {len(entry['history'])}전  |  1·2·3착 {one}·{two}·{three}회  |  마필번호 {entry['kra_horse_id']}"
        pdf.setFillColor(MUTED)
        fit_text(pdf, summary, left + 94 * mm, top - 6.5 * mm, 88 * mm, 8.0)
        pdf.setStrokeColor(LINE)
        pdf.line(left + 17 * mm, top - 10 * mm, right - 3 * mm, top - 10 * mm)
        draw_result_columns(pdf, left + 17 * mm, top - 14 * mm, None)
        if entry["history"]:
            for line_index, row in enumerate(entry["history"][:5]):
                draw_result_columns(pdf, left + 17 * mm, top - (18.3 + 3.6 * line_index) * mm, row)
        else:
            pdf.setFillColor(MUTED)
            fit_text(pdf, "출전표 기준 통산 0전 · 이전 공식 출전 성적 없음", left + 17 * mm, top - 23 * mm, 150 * mm, 9)

    pdf.setFillColor(MUTED)
    note = "최근 5회는 통산 출전횟수에 포함된 과거 경주. 경주취소·출전취소·경주제외 및 2026.07.07 별도 결과 제외."
    fit_text(pdf, note, left, 27 * mm, 180 * mm, 7.6)
    pdf.setStrokeColor(LINE)
    pdf.line(left, 16 * mm, right, 16 * mm)
    as_of = retrieved.strftime("%Y.%m.%d %H:%M KST")
    pdf.setFillColor(MUTED)
    fit_text(pdf, f"출전표 수집 {as_of} · 과거 기록은 한국마사회 결과 원천과 출전표 통산 전적 대조", left, 11 * mm, 165 * mm, 7.8)
    pdf.setFillColor(INK)
    fit_text(pdf, f"{page_number:02d} / {total_pages:02d}", right - 21 * mm, 11 * mm, 21 * mm, 9)
    pdf.showPage()


def build_main(races: list[dict], retrieved: datetime) -> None:
    MAIN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(MAIN_OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("제주 2026-09-17 출전정보 및 말별 최근 5회 경주기록")
    pdf.setAuthor("horse_racing project")
    page = 1
    for race in races:
        draw_page(pdf, race, retrieved, page, total_pages=24)
        page += 1
        split = min(5, (len(race["entries"]) + 1) // 2)
        groups = (race["entries"][:split], race["entries"][split:])
        for part, group in enumerate(groups, 1):
            if len(group) > 5:
                raise RuntimeError("Recent-history page would exceed five horse cards")
            draw_recent_history_page(pdf, race, group, part, page, 24, retrieved)
            page += 1
    if page != 25:
        raise RuntimeError(f"Expected 24 pages, got {page - 1}")
    pdf.save()


def draw_appendix_header(pdf: canvas.Canvas, page: int) -> float:
    width, height = A4
    left, right = 12 * mm, width - 12 * mm
    pdf.setFillColor(INK)
    fit_text(pdf, "TRACK NOTE  /  전 경주 이력 부록", left, height - 16 * mm, 120 * mm, 12)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "2026.09.17 목요일 · 제주", right - 57 * mm, height - 16 * mm, 57 * mm, 9)
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(1.6 * mm)
    pdf.line(left, height - 21 * mm, right, height - 21 * mm)
    pdf.setFillColor(GREEN)
    fit_text(pdf, "FULL HISTORY / 말별 과거 출전 전체", left, height - 30 * mm, 140 * mm, 8.4)
    pdf.setFillColor(INK)
    fit_text(pdf, "제주 출전마 76두 · 확인된 과거 1,616전", left, height - 42 * mm, 170 * mm, 18)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "말별 최신순 · 경주취소/미출전 결과 제외 · 2026.07.07 결과는 통산 이력과 분리", left, height - 49 * mm, 181 * mm, 8.0)
    pdf.setStrokeColor(LINE)
    pdf.line(left, 16 * mm, right, 16 * mm)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "한국마사회 결과 원천·9/17 출전표 통산 전적 대조  |  착순/편성: 당시 순위/편성두수", left, 11 * mm, 165 * mm, 7.6)
    pdf.setFillColor(INK)
    fit_text(pdf, f"p.{page:02d}", right - 16 * mm, 11 * mm, 16 * mm, 9)
    return height - 56 * mm


def draw_appendix_section(pdf: canvas.Canvas, entry: dict, race_number: int, y: float, continued: bool) -> float:
    width, _ = A4
    left, right = 12 * mm, width - 12 * mm
    pdf.setFillColor(PALE)
    pdf.roundRect(left, y - 8 * mm, right - left, 8 * mm, 1.2 * mm, fill=1, stroke=0)
    pdf.setFillColor(INK)
    suffix = " (계속)" if continued else ""
    title = f"제주 {race_number}R  #{entry['horse_number']:02d} {entry['horse_name']}{suffix}"
    fit_text(pdf, title, left + 3 * mm, y - 5.6 * mm, 75 * mm, 9.4)
    one, two, three = entry["career_places"]
    summary = f"ID {entry['kra_horse_id']}  |  통산 {len(entry['history'])}전  |  1·2·3착 {one}·{two}·{three}회"
    pdf.setFillColor(MUTED)
    fit_text(pdf, summary, left + 84 * mm, y - 5.4 * mm, 96 * mm, 8.0)
    y -= 8 * mm
    if entry["history"]:
        draw_result_columns(pdf, left + 3 * mm, y - 4.6 * mm, None)
        y -= 6 * mm
    return y


def build_appendix(races: list[dict]) -> int:
    APPENDIX_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(APPENDIX_OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("제주 2026-09-17 출전마 76두 전 경주 이력 부록")
    pdf.setAuthor("horse_racing project")
    page = 1
    y = draw_appendix_header(pdf, page)
    left = 12 * mm
    for race in races:
        for entry in race["entries"]:
            if y < 42 * mm:
                pdf.showPage()
                page += 1
                y = draw_appendix_header(pdf, page)
            y = draw_appendix_section(pdf, entry, race["race_number"], y, continued=False)
            if not entry["history"]:
                pdf.setFillColor(MUTED)
                fit_text(pdf, "출전표 기준 통산 0전 · 이전 공식 출전 성적 없음", left + 3 * mm, y - 4 * mm, 150 * mm, 8.5)
                y -= 9 * mm
            for row in entry["history"]:
                if y < 28.5 * mm:
                    pdf.showPage()
                    page += 1
                    y = draw_appendix_header(pdf, page)
                    y = draw_appendix_section(pdf, entry, race["race_number"], y, continued=True)
                draw_result_columns(pdf, left + 3 * mm, y - 2.7 * mm, row)
                y -= 4.25 * mm
            y -= 3 * mm

    unmatched = [
        (race, entry, row)
        for race in races
        for entry in race["entries"]
        for row in entry["unmatched_history"]
    ]
    if len(unmatched) != 9:
        raise RuntimeError("Expected nine separately reported 2026-07-07 results")
    if y < 76 * mm:
        pdf.showPage()
        page += 1
        y = draw_appendix_header(pdf, page)
    width, _ = A4
    right = width - 12 * mm
    pdf.setFillColor(PALE)
    pdf.roundRect(left, y - 8 * mm, right - left, 8 * mm, 1.2 * mm, fill=1, stroke=0)
    pdf.setFillColor(INK)
    fit_text(pdf, "별도 원천 결과 9건 · 출전표 통산 전적에 미포함", left + 3 * mm, y - 5.5 * mm, 174 * mm, 9.2)
    y -= 10 * mm
    pdf.setFillColor(MUTED)
    fit_text(
        pdf,
        "2026.07.07 결과 API에는 있으나 이번 출전표의 통산 횟수·1~3착 횟수에는 들어 있지 않아 위 이력과 분리했습니다.",
        left + 3 * mm, y, 174 * mm, 7.7,
    )
    y -= 5 * mm
    headings = ["이번 출전마", "당시 경주", "거리", "착순", "기록", "부담"]
    starts = [3, 68, 91, 113, 143, 164]
    widths = [63, 21, 20, 28, 19, 17]
    pdf.setFillColor(MUTED)
    for offset, column_width, value in zip(starts, widths, headings, strict=True):
        fit_text(pdf, value, left + offset * mm, y, column_width * mm, 7.5)
    y -= 4 * mm
    for race, entry, row in unmatched:
        values = [
            f"{race['race_number']}R #{entry['horse_number']:02d} {entry['horse_name']}",
            f"{row['race_date_local'][5:].replace('-', '.')} {row['race_number']}R",
            f"{row['distance_m']}m",
            finish_label(row),
            format_time(row["finish_time_ms"]),
            f"{row['carried_weight_kg']:.1f}" if row["carried_weight_kg"] is not None else "-",
        ]
        pdf.setFillColor(INK)
        for offset, column_width, value in zip(starts, widths, values, strict=True):
            fit_text(pdf, value, left + offset * mm, y, column_width * mm, 8.0)
        y -= 4 * mm
    pdf.save()
    return page


def main() -> None:
    pdfmetrics.registerFont(TTFont(FONT, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
    races, retrieved = load_data()
    total, without_history = load_verified_history(races)
    build_main(races, retrieved)
    appendix_pages = build_appendix(races)
    print(f"{MAIN_OUTPUT}: 24 pages, 76 horses, 324 recent-result rows")
    print(f"{APPENDIX_OUTPUT}: {appendix_pages} pages, {total} prior starts, {without_history} horses without prior starts")


if __name__ == "__main__":
    main()
