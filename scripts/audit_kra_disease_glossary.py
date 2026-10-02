"""Collect KRA's public disease glossary and audit exact operational-term coverage.

This is a read-only audit of the operational SQLite database. It never assigns a
medical explanation to a horse or writes to either operational database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup


SOURCE_URL = "https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do"
PAGE_COUNT = 5
EXPECTED_GLOSSARY_ROWS = 50


def _korean_name(heading: str) -> str:
    """Extract only the unambiguous Korean prefix; keep the whole heading too."""
    match = re.match(r"^([가-힣0-9 ]+)", heading)
    return match.group(1).strip() if match else ""


def _without_spaces(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _collect_glossary() -> tuple[list[dict[str, object]], list[bytes]]:
    entries: list[dict[str, object]] = []
    pages: list[bytes] = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for page_number in range(1, PAGE_COUNT + 1):
            response = client.get(SOURCE_URL, params={"pageIndex": page_number})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("ul.slideList > li")
            if len(rows) != 10:
                raise ValueError(f"Page {page_number} returned {len(rows)} glossary rows")
            for position, row in enumerate(rows, start=1):
                heading_node = row.select_one("a")
                description_node = row.select_one("div")
                if heading_node is None or description_node is None:
                    raise ValueError(f"Missing heading/description on page {page_number}")
                heading = heading_node.get_text(" ", strip=True)
                description = description_node.get_text(" ", strip=True)
                name = _korean_name(heading)
                if not name or not description:
                    raise ValueError(f"Blank disease name/description on page {page_number}")
                entries.append(
                    {
                        "page": page_number,
                        "position": position,
                        "heading": heading,
                        "korean_name_prefix": name,
                        "description_ko": description,
                        "source_url": str(response.url),
                    }
                )
            pages.append(response.content)
    if len(entries) != EXPECTED_GLOSSARY_ROWS or len({e["heading"] for e in entries}) != len(entries):
        raise ValueError("Incomplete or duplicate KRA disease glossary")
    return entries, pages


def _load_terms(database_path: Path) -> list[dict[str, object]]:
    uri = f"file:{database_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """SELECT t.id, t.raw_text, COUNT(l.horse_medical_id) AS use_count
               FROM medical_diagnosis_terms AS t
               LEFT JOIN horse_medical_diagnoses AS l ON l.term_id = t.id
               GROUP BY t.id, t.raw_text
               ORDER BY t.id"""
        ).fetchall()
    return [{"term_id": row[0], "raw_text": row[1], "use_count": row[2]} for row in rows]


def _match_terms(
    terms: list[dict[str, object]], entries: list[dict[str, object]]
) -> list[dict[str, object]]:
    exact = {str(entry["korean_name_prefix"]): entry for entry in entries}
    space_normalized: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        space_normalized.setdefault(_without_spaces(str(entry["korean_name_prefix"])), []).append(entry)
    matches: list[dict[str, object]] = []
    for term in terms:
        raw_text = str(term["raw_text"])
        compact = _without_spaces(raw_text)
        if raw_text in exact:
            status = "exact"
            candidates = [exact[raw_text]]
        elif compact in space_normalized:
            status = "spacing_candidate"
            candidates = space_normalized[compact]
        else:
            candidates = [
                entry
                for entry in entries
                if len(_without_spaces(str(entry["korean_name_prefix"]))) >= 2
                and _without_spaces(str(entry["korean_name_prefix"])) in compact
            ]
            status = "substring_candidate" if candidates else "unmatched"
        matches.append(
            {
                **term,
                "match_status": status,
                "candidate_glossary_names": " | ".join(
                    str(entry["korean_name_prefix"]) for entry in candidates
                ),
            }
        )
    return matches


def _write_results(
    output_dir: Path,
    entries: list[dict[str, object]],
    pages: list[bytes],
    matches: list[dict[str, object]],
) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True)
    page_hashes: list[dict[str, object]] = []
    for page_number, body in enumerate(pages, start=1):
        (raw_dir / f"page_{page_number}.html").write_bytes(body)
        page_hashes.append(
            {"page": page_number, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        )
    fetched_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    (output_dir / "glossary.json").write_text(
        json.dumps(
            {
                "source_kind": "KRA public website, not API33",
                "source_url": SOURCE_URL,
                "fetched_at_kst": fetched_at,
                "raw_pages": page_hashes,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (output_dir / "term_matches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["term_id", "raw_text", "use_count", "match_status", "candidate_glossary_names"],
        )
        writer.writeheader()
        writer.writerows(matches)

    term_counts = Counter(str(row["match_status"]) for row in matches)
    use_counts = Counter()
    for row in matches:
        use_counts[str(row["match_status"])] += int(row["use_count"])
    exact_names = {str(row["candidate_glossary_names"]) for row in matches if row["match_status"] == "exact"}
    top_unmatched = sorted(
        (row for row in matches if row["match_status"] == "unmatched"),
        key=lambda row: (-int(row["use_count"]), str(row["raw_text"])),
    )[:15]
    lines = [
        "# KRA 공식 질병용어와 운영 진단명 대조",
        "",
        f"- 수집 시각: {fetched_at}",
        f"- 출처: {SOURCE_URL}",
        "- API33은 기존 인증키에 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR(30)`을 반환했으므로, 이 수집물은 API 응답이 아닌 KRA 공식 공개 웹 화면 5쪽의 자료다.",
        f"- 공식 화면 설명 항목: {len(entries):,}개; 운영 DB 고유 진료 문구: {len(matches):,}개; 진료기록-문구 연결: {sum(int(row['use_count']) for row in matches):,}건",
        "- `exact`만 원문과 공식 한글 표제가 동일하다. 나머지 상태는 검토 후보이며 의학적 동의어 확정이나 설명 자동 연결이 아니다.",
        "- 공식 제목의 첫 한글 부분만 비교했다. 예: `일사병 / 열사병`처럼 복합 제목은 별도 검토가 필요하다.",
        "",
        "| 매칭 상태 | 고유 문구 | 진료기록 연결 건수 |",
        "|---|---:|---:|",
    ]
    for status in ("exact", "spacing_candidate", "substring_candidate", "unmatched"):
        lines.append(f"| `{status}` | {term_counts[status]:,} | {use_counts[status]:,} |")
    lines.extend(
        [
            "",
            f"- 공식 표제 중 운영 진단명과 완전 일치한 표제: {len(exact_names):,}/{len(entries):,}개",
            "",
            "## 사용 빈도가 높은 미일치 원문 예시",
            "",
            "| 원문 | 연결 건수 |",
            "|---|---:|",
        ]
    )
    for row in top_unmatched:
        lines.append(f"| {str(row['raw_text']).replace('|', '\\|')} | {int(row['use_count']):,} |")
    lines.extend(
        [
            "",
            "## 해석 제한",
            "",
            "- 운영 진료 문구에는 질병 외에 검사·처치·행정 표현과 부위·좌우 구분이 포함된다.",
            "- 공식 일반 설명은 해당 말의 상태, 중증도, 완치 여부 또는 경주 영향을 설명하지 않는다.",
            "- 원본 진료 데이터와 Supabase 운영 DB는 변경하지 않았다.",
            "",
        ]
    )
    (output_dir / "coverage_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.database.is_file():
        raise FileNotFoundError(args.database)
    entries, pages = _collect_glossary()
    matches = _match_terms(_load_terms(args.database), entries)
    _write_results(args.output_dir, entries, pages, matches)
    print(f"Collected {len(entries)} KRA glossary rows; compared {len(matches)} operational terms")
    print(f"Report: {args.output_dir / 'coverage_report.md'}")


if __name__ == "__main__":
    main()
