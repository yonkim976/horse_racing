"""Create a factual, prediction-free A4 information sheet for Jeju 2026-09-17."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/horse_racing.sqlite3"
OUTPUT = ROOT / "output/pdf/jeju_2026-09-17_basic_entry_sheet_sample.pdf"
DATE = "2026-09-17"
MEET = 2
FONT = "ArialUnicode"
INK = colors.HexColor("#17232B")
GREEN = colors.HexColor("#0C6B63")
MUTED = colors.HexColor("#526269")
LINE = colors.HexColor("#C6D0D2")
PALE = colors.HexColor("#EEF3F2")


def fit_text(pdf: canvas.Canvas, value: str, x: float, y: float, width: float, size: float) -> None:
    while pdfmetrics.stringWidth(value, FONT, size) > width and size > 7.2:
        size -= 0.2
    pdf.setFont(FONT, size)
    pdf.drawString(x, y, value)


def source_document(conn: sqlite3.Connection, endpoint: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT local_path, retrieved_at_ms, sha256
        FROM source_documents
        WHERE endpoint = ? AND request_params_json LIKE ?
          AND request_params_json LIKE ?
        ORDER BY retrieved_at_ms DESC LIMIT 1
        """,
        (
            endpoint,
            '%"rc_date":"20260917"%' if endpoint.startswith("/API26") else '%"race_dt":"20260917"%',
            '%"meet":2%' if endpoint.startswith("/API26") else '%"rccrs_cd":2%',
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Missing source document: {endpoint}")
    return row


def load_data() -> tuple[list[dict], datetime]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    entry_doc = source_document(conn, "/API26_2/entrySheet_2")
    gate_doc = source_document(conn, "/API78/chulmainfo")
    entry_items = json.loads((ROOT / entry_doc["local_path"]).read_text())["response"]["body"]["items"]["item"]
    gate_items = json.loads((ROOT / gate_doc["local_path"]).read_text())["response"]["body"]["items"]["item"]
    source_by_key = {(int(v["rcNo"]), int(v["chulNo"]), v["hrName"]): v for v in entry_items}
    import re

    gate_keys = {(int(re.search(r"\d+", str(v["raceNo"])).group()), int(v["gtno"]), v["hrnm"]) for v in gate_items}
    if len(entry_items) != 76 or len(gate_items) != 76 or set(source_by_key) != gate_keys:
        raise RuntimeError("Official source entry counts or keys do not match")
    races = [dict(x) for x in conn.execute(
        """
        SELECT r.id, r.race_number, r.grade, r.distance_m, r.race_name,
               r.field_size, r.burden_type, r.scheduled_at_ms
        FROM races r JOIN racecourses c ON c.id = r.racecourse_id
        WHERE r.race_date_local = ? AND c.kra_meet_code = ?
        ORDER BY r.race_number
        """,
        (DATE, MEET),
    )]
    if len(races) != 8:
        raise RuntimeError(f"Expected 8 Jeju races, found {len(races)}")
    db_keys: set[tuple[int, int, str]] = set()
    for race in races:
        race["entries"] = [dict(x) for x in conn.execute(
            """
            SELECT e.horse_number, e.gate_number, e.carried_weight_kg,
                   h.kra_horse_id, h.name_ko AS horse_name, h.sex, h.birth_date,
                   j.name_ko AS jockey, t.name_ko AS trainer, o.name_ko AS owner
            FROM race_entries e
            JOIN horses h ON h.id = e.horse_id
            LEFT JOIN jockeys j ON j.id = e.jockey_id
            LEFT JOIN trainers t ON t.id = e.trainer_id
            LEFT JOIN owners o ON o.id = e.owner_id
            WHERE e.race_id = ? ORDER BY e.horse_number
            """,
            (race["id"],),
        )]
        if len(race["entries"]) != race["field_size"]:
            raise RuntimeError(f"Race {race['race_number']} field size mismatch")
        for entry in race["entries"]:
            key = (race["race_number"], entry["horse_number"], entry["horse_name"])
            db_keys.add(key)
            source = source_by_key[key]
            entry["age"] = int(source["age"])
            if any(entry[k] is None for k in ("gate_number", "carried_weight_kg", "sex", "birth_date", "jockey", "trainer", "owner")):
                raise RuntimeError(f"Missing basic field for {key}")
            for db_field, api_field in (
                ("kra_horse_id", "hrNo"), ("sex", "sex"), ("jockey", "jkName"),
                ("trainer", "trName"), ("owner", "owName"),
            ):
                if str(entry[db_field]).strip() != str(source[api_field]).strip():
                    raise RuntimeError(f"DB/source mismatch in {db_field} for {key}")
            if float(entry["carried_weight_kg"]) != float(source["wgBudam"]):
                raise RuntimeError(f"DB/source burden weight mismatch for {key}")
    if db_keys != set(source_by_key):
        raise RuntimeError("DB entries do not match the official source")
    retrieved = datetime.fromtimestamp(max(entry_doc["retrieved_at_ms"], gate_doc["retrieved_at_ms"]) / 1000, tz=ZoneInfo("Asia/Seoul"))
    conn.close()
    return races, retrieved


def draw_page(
    pdf: canvas.Canvas, race: dict, retrieved: datetime, page_number: int, total_pages: int = 8
) -> None:
    width, height = A4
    left = 12 * mm
    right = width - 12 * mm
    pdf.setFillColor(INK)
    fit_text(pdf, "TRACK NOTE  /  출전정보", left, height - 16 * mm, 100 * mm, 12)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "2026.09.17 목요일 · 제주", right - 57 * mm, height - 16 * mm, 57 * mm, 9)
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(1.6 * mm)
    pdf.line(left, height - 21 * mm, right, height - 21 * mm)

    pdf.setFillColor(GREEN)
    fit_text(pdf, "RACE ENTRY / 경주 기본 정보", left, height - 30 * mm, 90 * mm, 8.4)
    pdf.setFillColor(INK)
    fit_text(pdf, f"제주 {race['race_number']}경주", left, height - 42 * mm, 90 * mm, 21)
    start = datetime.fromtimestamp(race["scheduled_at_ms"] / 1000, tz=ZoneInfo("Asia/Seoul"))
    pdf.setFillColor(GREEN)
    fit_text(pdf, start.strftime("%H:%M"), right - 34 * mm, height - 42 * mm, 34 * mm, 20)
    pdf.setFillColor(MUTED)
    fit_text(pdf, race["race_name"] or "일반", left, height - 49 * mm, 185 * mm, 9.2)

    pdf.setFillColor(PALE)
    pdf.roundRect(left, height - 71 * mm, right - left, 15 * mm, 2 * mm, fill=1, stroke=0)
    pdf.setFillColor(INK)
    meta = f"{race['grade']}   |   {race['distance_m']}m   |   {race['field_size']}두   |   부담 {race['burden_type'] or '—'}"
    fit_text(pdf, meta, left + 4 * mm, height - 65 * mm, 176 * mm, 11)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "출전번호순 · 출전표에 기재된 기본 사항", left, height - 78 * mm, 130 * mm, 8.5)

    top = height - 83 * mm
    card_h = 16.5 * mm
    gap = 1.2 * mm
    for idx, entry in enumerate(race["entries"]):
        y_top = top - idx * (card_h + gap)
        y_bottom = y_top - card_h
        pdf.setStrokeColor(LINE)
        pdf.setLineWidth(0.55)
        pdf.roundRect(left, y_bottom, right - left, card_h, 1.6 * mm, fill=0, stroke=1)
        pdf.setFillColor(PALE)
        pdf.roundRect(left, y_bottom, 13 * mm, card_h, 1.6 * mm, fill=1, stroke=0)
        pdf.setFillColor(GREEN)
        fit_text(pdf, f"{entry['horse_number']:02d}", left + 3.2 * mm, y_top - 10.7 * mm, 10 * mm, 12)
        pdf.setFillColor(INK)
        fit_text(pdf, entry["horse_name"], left + 17 * mm, y_top - 6.2 * mm, 65 * mm, 12.4)
        pdf.setFillColor(MUTED)
        born = datetime.fromisoformat(entry["birth_date"]).strftime("%Y.%m.%d")
        id_line = f"{entry['sex']} · {entry['age']}세  |  생일 {born}  |  마필번호 {entry['kra_horse_id']}"
        fit_text(pdf, id_line, left + 17 * mm, y_top - 12.2 * mm, 74 * mm, 8.3)
        pdf.setFillColor(INK)
        upper = f"게이트 {entry['gate_number']}  |  부담 {entry['carried_weight_kg']:.1f}kg  |  기수 {entry['jockey']}"
        fit_text(pdf, upper, left + 94 * mm, y_top - 6.2 * mm, 88 * mm, 9.3)
        pdf.setFillColor(MUTED)
        lower = f"조교사 {entry['trainer']}  |  마주 {entry['owner']}"
        fit_text(pdf, lower, left + 94 * mm, y_top - 12.2 * mm, 88 * mm, 8.6)

    pdf.setFillColor(PALE)
    pdf.roundRect(left, 20.5 * mm, right - left, 15 * mm, 1.6 * mm, fill=1, stroke=0)
    pdf.setFillColor(INK)
    terms = (
        f"표기 읽기   {race['grade']}: 제주마 등급(숫자가 작을수록 상위)"
        f"   |   {race['distance_m']}m: 경주거리   |   {race['field_size']}두: 출전마 수"
    )
    fit_text(pdf, terms, left + 3 * mm, 31.2 * mm, 174 * mm, 8.1)
    burden = (
        "별정A: 제주 6등급은 성별 무관 기준 55kg. 수습기수 감량 시 실제 부담중량은 달라질 수 있음."
        if race["burden_type"] == "별정A"
        else "핸디캡: 말의 레이팅 차이를 부담중량에 반영(1점당 0.5kg). 수습기수 감량 등도 적용."
    )
    fit_text(pdf, f"부담 방식   {burden}", left + 3 * mm, 26.8 * mm, 174 * mm, 8.1)
    pdf.setFillColor(MUTED)
    fit_text(pdf, "용어 기준: 한국마사회 2026년 제주경마 시행계획 · '부담'은 말이 지고 달리는 무게", left + 3 * mm, 22.6 * mm, 174 * mm, 7.1)

    pdf.setStrokeColor(LINE)
    pdf.line(left, 16 * mm, right, 16 * mm)
    pdf.setFillColor(MUTED)
    as_of = retrieved.strftime("%Y.%m.%d %H:%M KST")
    fit_text(pdf, f"출전표 수집 {as_of} · 생일은 보유 마필 프로필 · 출전취소/기수변경/당일 마체중 변동 가능", left, 11 * mm, 165 * mm, 7.8)
    pdf.setFillColor(INK)
    fit_text(pdf, f"{page_number:02d} / {total_pages:02d}", right - 21 * mm, 11 * mm, 21 * mm, 9)
    pdf.showPage()


def main() -> None:
    pdfmetrics.registerFont(TTFont(FONT, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
    races, retrieved = load_data()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("제주 2026-09-17 목요 경주 기본 출전 정보지 샘플")
    pdf.setAuthor("horse_racing project")
    for i, race in enumerate(races, start=1):
        draw_page(pdf, race, retrieved, i)
    pdf.save()
    print(f"{OUTPUT}: {len(races)} races, {sum(len(r['entries']) for r in races)} horses, source {retrieved.isoformat()}")


if __name__ == "__main__":
    main()
