"""Literal horse-specific KRA text; no incident/role classification.

The source core is always opened read-only. Website rows are authoritative
for their own horse/history key; API paragraph links remain visibly distinct.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import httpx
import pyarrow as pa
from bs4 import BeautifulSoup
from lxml import html as lxml_html

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[2]
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
OUTPUT = PACKAGE / "outputs"
RAW = PACKAGE / "website_raw"
DB = OUTPUT / "horse_steward_phrases.duckdb"
ENDPOINT = "https://race.kra.co.kr/chulmainfo/chulmaDetailInfoStewardsReport.do"
VERSION = "literal_horse_phrases_v1"
HR = re.compile(r"""^javascript:goHrProfile\(\s*["'](\d+)["']\s*,\s*["'](\d{7})["']\s*\);?$""")
SCORE = re.compile(
    r"""^javascript:goScore\(\s*["'](\d+)["']\s*,\s*["'](\d{8})["']\s*,\s*["'](\d+)["']\s*\);?$"""
)
MENTION = re.compile(r'([①-⑳])\s*[“”"「]([^“”"」]+)[“”"」]')
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(text: str) -> str:
    # Only formatting differences; do not remove punctuation, names or predicates.
    return re.sub(r"\s+", "", text).lstrip("●")


def parity_text(text: str) -> str:
    # HTML parsers may normalize CRLF; preserve the primary raw text in storage.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def own_number_status(
    text: str, names: set[str], program: int | None, ambiguous_name: bool = False
) -> str:
    if program is None:
        return "historical_identity_unresolved"
    if ambiguous_name:
        return "same_name_multiple_horses_identity_from_official_row"
    numbers = {CIRCLED.index(m[1]) + 1 for m in MENTION.finditer(text) if m[2].strip() in names}
    if not numbers:
        return "identity_from_official_website_row"
    return "explicit_own_number_agrees" if numbers == {program} else "conflict"


def iso_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("invalid website date")
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}").isoformat()


def parse_page(content: bytes, card: dict) -> list[dict]:
    soup = BeautifulSoup(content, "html.parser")
    table = soup.select_one("#stewardsReportTbl table")
    if table is None:
        raise ValueError("missing horse steward table; not an empty result")
    for field, expected in (
        ("meet", card["meet"]),
        ("rcDate", card["date"]),
        ("rcNo", card["race"]),
    ):
        node = soup.select_one(f'form[name="form1"] input[name="{field}"]')
        if node is None or str(node.get("value")) != str(expected):
            raise ValueError(f"website selected-card mismatch: {field}")
    header = soup.select_one("form[name='form1'] .tableType1 table")
    if header is None:
        raise ValueError("missing selected race header")
    head = normalize(header.get_text())
    expected_date = card["date"]
    match = re.search(r"(\d{4})년(\d{1,2})월(\d{1,2})일.*?제(\d+)경주", head)
    if (
        not match
        or f"{int(match[1]):04}{int(match[2]):02}{int(match[3]):02}" != expected_date
        or int(match[4]) != card["race"]
    ):
        raise ValueError("rendered race header differs from request")
    rows = []
    for index, tr in enumerate(table.select("tbody > tr")):
        cells = tr.find_all("td", recursive=False)
        if len(cells) != 5:
            raise ValueError(f"unexpected table row {index}: {len(cells)} cells")
        hr_links = [HR.fullmatch(a.get("href", "")) for a in cells[1].select("a")]
        hr_links = [m for m in hr_links if m]
        if len(hr_links) != 1:
            raise ValueError(f"row {index} has no unique official horse-ID link")
        score_links = [SCORE.fullmatch(a.get("href", "")) for a in cells[3].select("a")]
        score_links = [m for m in score_links if m]
        if len(score_links) > 1:
            raise ValueError("multiple historical race links")
        pre = cells[4].find("pre")
        if pre is None:
            raise ValueError("missing literal pre text")
        text = pre.get_text("", strip=False)
        has_text = bool(text.strip())
        # KRA can display a dated history row with a blank comment.
        # A nonblank comment still requires its own explicit race locator.
        if has_text and not score_links:
            raise ValueError("historical race/text mismatch; preserve for review")
        historical = score_links[0] if score_links else None
        number = cells[0].get_text(strip=True)
        if not number.isdigit() or int(number) <= 0:
            raise ValueError("invalid current program number")
        rows.append(
            dict(
                row_index=index,
                card_meet=card["meet"],
                card_date=iso_date(card["date"]),
                card_race=card["race"],
                current_program=int(number),
                horse_id=hr_links[0][2],
                horse_name_raw=cells[1].get_text(strip=True),
                profile_meet=int(hr_links[0][1]),
                venue_label_raw=cells[2].get_text(strip=True),
                historical_label_raw=cells[3].get_text(strip=True),
                event_meet=int(historical[1]) if historical else None,
                event_date=iso_date(historical[2]) if historical else None,
                event_race=int(historical[3]) if historical else None,
                website_text_raw=text,
                field_state="text" if has_text else "empty",
            )
        )
    if not rows:
        raise ValueError("no horse rows; not interpreted as no incidents")
    return rows


def independent_rows(content: bytes) -> list[tuple]:
    """Separate parser and traversal for complete HTML-to-DB parity checks."""
    soup = BeautifulSoup(content, "html.parser")
    doc = lxml_html.fromstring(content.decode(soup.original_encoding or "euc-kr"))
    out = []
    for tr in doc.xpath('//*[@id="stewardsReportTbl"]//tbody/tr'):
        cells = tr.xpath("./td")
        horse = [HR.fullmatch(x) for x in cells[1].xpath(".//a/@href")]
        horse = [m for m in horse if m]
        score = [SCORE.fullmatch(x) for x in cells[3].xpath(".//a/@href")]
        score = [m for m in score if m]
        out.append(
            (
                int("".join(cells[0].itertext()).strip()),
                horse[0][2],
                int(score[0][1]) if score else None,
                iso_date(score[0][2]) if score else None,
                int(score[0][3]) if score else None,
                parity_text("".join(cells[4].xpath(".//pre")[0].itertext())),
            )
        )
    return out


def prepare() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(exist_ok=True)
    plan_path = PACKAGE / "collection_plan.json"
    if plan_path.exists():
        raise FileExistsError("collection plan already exists")
    with duckdb.connect(str(CORE), read_only=True) as con:
        cards = con.execute("""
            WITH races AS (
              SELECT DISTINCT try_cast(source_meet AS INTEGER) meet,
                     result_date d,try_cast(result_race_no AS INTEGER) r
              FROM runner_results WHERE result_date>='20170101'
                AND execution_status='executed_plan_and_result'
            ), ranked AS (
              SELECT *,row_number() OVER(PARTITION BY meet,substr(d,1,4)
                        ORDER BY d DESC,r DESC) rn FROM races
            ) SELECT meet,d,r FROM ranked WHERE rn IN (1,5) ORDER BY meet,d,r
        """).fetchall()
    cards.extend([(3, "20180223", 9), (1, "20261011", 7)])
    selected = [dict(meet=m, date=d, race=r) for m, d, r in sorted(set(cards))]
    for card in selected:
        card["url"] = (
            ENDPOINT
            + "?"
            + urlencode(
                dict(Act="02", Sub=1, meet=card["meet"], rcDate=card["date"], rcNo=card["race"])
            )
        )
        card["raw_file"] = f"meet{card['meet']}_{card['date']}_race{card['race']}.html"
    write_json(
        plan_path,
        dict(
            version=VERSION,
            selection=(
                "last and fifth-last executed card per venue/year, 2017 onward; "
                "two named reference cards"
            ),
            cards=selected,
        ),
    )
    write_json(
        PACKAGE / "input_manifest.json",
        dict(
            core_path=str(CORE.relative_to(ROOT)),
            core_sha256=file_hash(CORE),
            core_bytes=CORE.stat().st_size,
            version=VERSION,
        ),
    )
    print(json.dumps(dict(planned_pages=len(selected)), ensure_ascii=False))


def expand() -> None:
    """Cover every horse with an existing API report link, using recent cards."""
    path = PACKAGE / "coverage_collection_plan.json"
    if path.exists():
        raise FileExistsError("coverage plan already exists")
    with duckdb.connect(str(CORE), read_only=True) as con:
        universe = {
            x[0]
            for x in con.execute(
                "SELECT DISTINCT official_horse_id FROM steward_report_horse_links"
            ).fetchall()
        }
        runners = con.execute("""SELECT source_meet,result_date,result_race_no,horse_id_raw
            FROM runner_results WHERE result_date>='20170101'
            AND execution_status='executed_plan_and_result'""").fetchall()
    latest = {}
    for _meet, d, _race, horse in runners:
        if horse in universe:
            latest[horse] = max(latest.get(horse, "0"), d)
    cutoff = {
        horse: (date.fromisoformat(iso_date(d)) - timedelta(days=365)).strftime("%Y%m%d")
        for horse, d in latest.items()
    }
    eligible = defaultdict(set)
    for meet, d, race, horse in runners:
        if horse in universe and d >= cutoff[horse]:
            eligible[(int(meet), d, int(race))].add(horse)
    heap = [(-len(horses), key) for key, horses in eligible.items()]
    heapq.heapify(heap)
    uncovered = set(universe)
    selected = []
    while heap and uncovered:
        negative, key = heapq.heappop(heap)
        remaining = eligible[key] & uncovered
        if not remaining:
            continue
        if len(remaining) != -negative:
            heapq.heappush(heap, (-len(remaining), key))
            continue
        selected.append(key)
        uncovered -= remaining
    if uncovered:
        raise ValueError(f"no eligible website card for {len(uncovered)} horses")
    cards = []
    for meet, d, race in sorted(selected):
        cards.append(
            dict(
                meet=meet,
                date=d,
                race=race,
                url=ENDPOINT
                + "?"
                + urlencode(dict(Act="02", Sub=1, meet=meet, rcDate=d, rcNo=race)),
                raw_file=f"meet{meet}_{d}_race{race}.html",
            )
        )
    write_json(
        path,
        dict(
            target_horse_count=len(universe),
            target_horse_ids=sorted(universe),
            selection=(
                "deterministic greedy horse coverage; eligible cards within 365 days "
                "before each horse's latest core entry; this is not full lifetime coverage"
            ),
            cards=cards,
        ),
    )
    print(json.dumps(dict(target_horses=len(universe), coverage_cards=len(cards))))


def load_ledger() -> list[dict]:
    lines = PACKAGE / "collection_ledger.jsonl"
    if lines.exists():
        return [json.loads(line) for line in lines.read_text().splitlines() if line]
    path = PACKAGE / "collection_ledger.json"
    return json.loads(path.read_text()) if path.exists() else []


def revalidate() -> None:
    """Recheck preserved responses after the dated-blank-row parser correction."""
    ledger = load_ledger()
    known = {r["url"] for r in ledger if r["status"] == "captured"}
    recovered = 0
    for record in list(ledger):
        if record["status"] == "captured" or record["url"] in known:
            continue
        if not record.get("sha256"):
            continue
        path = RAW / record["raw_file"]
        if not path.exists() or digest(path.read_bytes()) != record["sha256"]:
            continue
        try:
            parsed = parse_page(path.read_bytes(), record)
        except ValueError:
            continue
        updated = {
            **record,
            "status": "captured",
            "error": None,
            "horse_rows": len(parsed),
            "text_rows": sum(r["field_state"] == "text" for r in parsed),
            "revalidated_at_utc": datetime.now(UTC).isoformat(),
            "revalidation_reason": "dated empty comment is retained as empty",
        }
        ledger.append(updated)
        with (PACKAGE / "collection_ledger.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(updated, ensure_ascii=False) + "\n")
        known.add(record["url"])
        recovered += 1
    write_json(PACKAGE / "collection_ledger.json", ledger)
    print(json.dumps(dict(revalidated_responses=recovered, captured_urls=len(known))))


def fetch() -> None:
    plan = json.loads((PACKAGE / "collection_plan.json").read_text())
    coverage_path = PACKAGE / "coverage_collection_plan.json"
    if coverage_path.exists():
        plan["cards"].extend(json.loads(coverage_path.read_text())["cards"])
    ledger_path = PACKAGE / "collection_ledger.json"
    ledger = load_ledger()
    lines_path = PACKAGE / "collection_ledger.jsonl"
    if not lines_path.exists():
        with lines_path.open("x", encoding="utf-8") as stream:
            for record in ledger:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    known = {r["url"] for r in ledger if r["status"] == "captured"}
    planned_urls = {card["url"] for card in plan["cards"]}
    completed = len(known & planned_urls)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for card in plan["cards"]:
            if card["url"] in known:
                continue
            expected_url = (
                ENDPOINT
                + "?"
                + urlencode(
                    dict(Act="02", Sub=1, meet=card["meet"], rcDate=card["date"], rcNo=card["race"])
                )
            )
            if card["url"] != expected_url or Path(card["raw_file"]).name != card["raw_file"]:
                raise ValueError("collection plan URL/path is not allowlisted")
            record = {**card, "captured_at_utc": datetime.now(UTC).isoformat()}
            try:
                response = client.get(expected_url)
                response.raise_for_status()
                if len(response.content) > 4 * 1024 * 1024:
                    raise ValueError("oversized HTML response")
                # Save even unparseable successful responses as review evidence.
                path = RAW / card["raw_file"]
                if path.exists() and path.read_bytes() != response.content:
                    path = path.with_name(path.stem + "_" + digest(response.content)[:12] + ".html")
                path.write_bytes(response.content)
                record.update(
                    raw_file=path.name,
                    http_status=response.status_code,
                    sha256=digest(response.content),
                    bytes=len(response.content),
                )
                rows = parse_page(response.content, card)
                record.update(
                    status="captured",
                    horse_rows=len(rows),
                    text_rows=sum(r["field_state"] == "text" for r in rows),
                )
            except Exception as exc:
                record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            ledger.append(record)
            with lines_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            if record["status"] == "captured":
                known.add(card["url"])
                completed += 1
            if completed % 50 == 0 or record["status"] != "captured":
                print(
                    json.dumps(
                        dict(
                            completed=completed,
                            planned=len(planned_urls),
                            last_card=[card["meet"], card["date"], card["race"]],
                            status=record["status"],
                            error=record.get("error"),
                        ),
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            time.sleep(0.25)
    write_json(ledger_path, ledger)
    print(json.dumps(dict(completed=completed, planned=len(planned_urls)), ensure_ascii=False))


def build() -> None:
    if DB.exists():
        raise FileExistsError("output DB already exists; use a new version directory")
    pinned = json.loads((PACKAGE / "input_manifest.json").read_text())
    if file_hash(CORE) != pinned["core_sha256"]:
        raise ValueError("core changed since input was pinned")
    ledger = load_ledger()
    api_rows = []
    api_by_key = defaultdict(list)
    roster = defaultdict(list)
    with duckdb.connect(str(CORE), read_only=True) as source:
        ambiguous_names = set(
            source.execute("""
          SELECT try_cast(source_meet AS INTEGER),result_date,
                 try_cast(result_race_no AS INTEGER),horse_name_raw
          FROM runner_results GROUP BY ALL HAVING count(DISTINCT horse_id_raw)>1
        """).fetchall()
        )
        roster_records = source.execute("""SELECT try_cast(source_meet AS INTEGER),
          result_date,try_cast(result_race_no AS INTEGER),horse_id_raw,
          try_cast(horse_program_no_raw AS INTEGER),horse_name_raw
          FROM runner_results WHERE horse_id_raw IS NOT NULL""").fetchall()
        for meet, d, r, h, n, name in roster_records:
            roster[(meet, iso_date(d), r, h)].append((n, name))
        arrow = source.execute("""
          SELECT sha256(l.paragraph_locator||'|'||l.official_horse_id) api_phrase_id,
            l.official_horse_id horse_id,l.roster_horse_name_raw horse_name_raw,
            l.target_actual_meet_code event_meet,l.target_event_date event_date,
            l.target_race_no event_race,try_cast(l.program_no_raw AS INTEGER) historical_program,
            p.paragraph_raw phrase_text,p.report_text_field source_field,
            p.span_start_codepoint,p.span_end_codepoint,p.paragraph_locator,
            p.observation_locator,p.source_row_sha256,p.page_sha256,
            p.source_captured_at_utc,l.match_rule,l.target_context_status,
            false historical_publication_time_verified
          FROM steward_report_horse_links l JOIN steward_report_paragraphs p
            ON l.paragraph_locator=p.paragraph_locator
          WHERE l.status='linked'
          ORDER BY api_phrase_id
        """).to_arrow_table()
        if (
            arrow.num_rows
            != source.execute("SELECT count(*) FROM steward_report_horse_links").fetchone()[0]
        ):
            raise ValueError("paragraph join lost or multiplied source links")
        api_rows = arrow.to_pylist()
    for record in api_rows:
        key = (record["event_meet"], record["event_date"], record["event_race"], record["horse_id"])
        entry = roster.get(key, [])
        if len(entry) != 1 or entry[0][0] != record["historical_program"]:
            raise ValueError("source API link failed same-race official-ID/program corroboration")
        api_by_key[key].append(record)
    website_rows, phrases, checks = [], [], []
    independent_count = 0
    for capture in ledger:
        if capture["status"] != "captured":
            continue
        content = (RAW / capture["raw_file"]).read_bytes()
        if digest(content) != capture["sha256"]:
            raise ValueError("captured website bytes changed")
        parsed = parse_page(content, capture)
        independent = independent_rows(content)
        comparison = [
            (
                r["current_program"],
                r["horse_id"],
                r["event_meet"],
                r["event_date"],
                r["event_race"],
                parity_text(r["website_text_raw"]),
            )
            for r in parsed
        ]
        if comparison != independent:
            raise ValueError("independent HTML parser disagrees")
        independent_count += len(parsed)
        for row in parsed:
            row_id = digest(capture["sha256"] + "|" + str(row["row_index"]))
            current = roster.get(
                (row["card_meet"], row["card_date"], row["card_race"], row["horse_id"]), []
            )
            current_conflict = bool(
                current and (len(current) != 1 or current[0][0] != row["current_program"])
            )
            key = (row["event_meet"], row["event_date"], row["event_race"], row["horse_id"])
            historical = roster.get(key, [])
            historical_status = (
                "verified"
                if len(historical) == 1
                else "missing_roster"
                if not historical
                else "ambiguous_roster"
            )
            base = {
                **row,
                "website_row_id": row_id,
                "source_url": capture["url"],
                "source_html_sha256": capture["sha256"],
                "source_raw_file": capture["raw_file"],
                "captured_at_utc": capture["captured_at_utc"],
                "current_identity_status": (
                    "conflict"
                    if current_conflict
                    else "verified"
                    if current
                    else "outside_core_card_scope"
                ),
                "historical_identity_status": historical_status
                if row["event_date"] is not None
                else "no_history_row",
                "historical_program": historical[0][0] if len(historical) == 1 else None,
            }
            website_rows.append(base)
            for bullet_index, match in enumerate(
                re.finditer(r"(?:^|●)([^●]*)", row["website_text_raw"])
            ):
                raw = match[1]
                if not raw.strip():
                    continue
                start = match.start(1)
                phrase = {
                    **base,
                    "website_phrase_id": digest(row_id + "|" + str(bullet_index)),
                    "bullet_index": bullet_index,
                    "phrase_text": raw,
                    "span_start_codepoint": start,
                    "span_end_codepoint": match.end(1),
                    "text_identity_status": own_number_status(
                        raw,
                        {row["horse_name_raw"]}
                        | ({historical[0][1]} if len(historical) == 1 else set()),
                        base["historical_program"],
                        any(
                            (
                                row["event_meet"],
                                (row["event_date"] or "").replace("-", ""),
                                row["event_race"],
                                name,
                            )
                            in ambiguous_names
                            for name in {row["horse_name_raw"]}
                            | ({historical[0][1]} if len(historical) == 1 else set())
                        ),
                    ),
                }
                phrases.append(phrase)
                candidates = api_by_key.get(key, [])
                exact = [p for p in candidates if normalize(p["phrase_text"]) == normalize(raw)]
                contained = [p for p in candidates if normalize(raw) in normalize(p["phrase_text"])]
                hits = exact or contained
                if historical_status != "verified":
                    status = "historical_identity_unresolved"
                elif exact:
                    status = "same_horse_exact_api_paragraph"
                elif contained:
                    status = "same_horse_website_excerpt_in_api_paragraph"
                elif not candidates:
                    status = "website_only_no_api_horse_paragraph"
                else:
                    status = "website_wording_differs_from_api_paragraph"
                checks.append(
                    dict(
                        website_phrase_id=phrase["website_phrase_id"],
                        website_row_id=row_id,
                        horse_id=row["horse_id"],
                        event_meet=row["event_meet"],
                        event_date=row["event_date"],
                        event_race=row["event_race"],
                        comparison_status=status,
                        website_text=raw,
                        api_candidate_count=len(candidates),
                        matched_api_phrase_ids_json=json.dumps([p["api_phrase_id"] for p in hits]),
                        api_candidate_texts_json=json.dumps(
                            [p["phrase_text"] for p in candidates], ensure_ascii=False
                        ),
                    )
                )
    staging = DB.with_name("horse_steward_phrases.building.duckdb")
    if staging.exists():
        raise FileExistsError("staging DB exists; preserve and inspect before a new build")
    con = duckdb.connect(str(staging))
    try:
        con.execute("BEGIN")
        con.register("api_input", arrow)
        con.execute("CREATE TABLE api_horse_paragraphs AS SELECT * FROM api_input")
        con.execute("ALTER TABLE api_horse_paragraphs ADD PRIMARY KEY(api_phrase_id)")
        for table, records in (
            ("website_card_rows", website_rows),
            ("website_phrase_observations", phrases),
            ("website_api_comparison", checks),
        ):
            if not records:
                raise ValueError("website capture produced no validation data")
            con.register("records_input", pa.Table.from_pylist(records))
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM records_input")
            con.unregister("records_input")
        con.execute("ALTER TABLE website_card_rows ADD PRIMARY KEY(website_row_id)")
        con.execute("ALTER TABLE website_phrase_observations ADD PRIMARY KEY(website_phrase_id)")
        con.execute("""CREATE VIEW website_phrase_review_candidates AS
          SELECT * FROM website_phrase_observations
          WHERE historical_identity_status<>'verified'
             OR current_identity_status='conflict' OR text_identity_status='conflict'
        """)
        con.execute(
            "CREATE INDEX api_horse_history_idx ON api_horse_paragraphs(horse_id,event_date)"
        )
        con.execute(
            "CREATE INDEX website_horse_history_idx "
            "ON website_phrase_observations(horse_id,event_date)"
        )
        con.execute("""CREATE VIEW website_horse_phrase_history AS
          SELECT horse_id,event_meet,event_date,event_race,historical_program,phrase_text,
            arg_max(horse_name_raw,card_date) display_horse_name,
            list(website_phrase_id ORDER BY website_phrase_id)::JSON source_phrase_ids_json,
            list(DISTINCT source_url ORDER BY source_url)::JSON source_urls_json,
            count(*) source_observation_count,min(captured_at_utc) first_captured_at_utc,
            max(captured_at_utc) latest_captured_at_utc
          FROM website_phrase_observations WHERE historical_identity_status='verified'
            AND current_identity_status<>'conflict'
            AND text_identity_status<>'conflict'
          GROUP BY horse_id,event_meet,event_date,event_race,historical_program,phrase_text""")
        con.execute("""CREATE VIEW horse_steward_phrases AS
          SELECT horse_id,display_horse_name,event_meet,event_date,event_race,
            historical_program,phrase_text,
            'official_website'::VARCHAR text_basis,true website_text_verified,
            source_phrase_ids_json provenance_ids_json,source_urls_json,
            false historical_publication_time_verified
          FROM website_horse_phrase_history
        """)
        con.execute("""CREATE VIEW api_horse_paragraphs_without_website AS
          SELECT a.horse_id,a.event_meet,a.event_date,a.event_race,
            a.historical_program,a.phrase_text,
            'api_linked_original_paragraph'::VARCHAR,false,
            json_array(a.api_phrase_id),NULL::JSON,false
          FROM api_horse_paragraphs a WHERE NOT EXISTS (
            SELECT 1 FROM website_horse_phrase_history w WHERE w.horse_id=a.horse_id
              AND w.event_meet=a.event_meet AND w.event_date=a.event_date
              AND w.event_race=a.event_race)
        """)
        con.execute(
            "CREATE TABLE build_metadata("
            "version VARCHAR,core_sha256 VARCHAR,created_at_utc VARCHAR)"
        )
        con.execute(
            "INSERT INTO build_metadata VALUES (?,?,?)",
            [VERSION, pinned["core_sha256"], datetime.now(UTC).isoformat()],
        )
        con.execute("COMMIT")
        counts = {
            table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in [
                "api_horse_paragraphs",
                "website_card_rows",
                "website_phrase_observations",
                "website_horse_phrase_history",
                "horse_steward_phrases",
                "api_horse_paragraphs_without_website",
                "website_phrase_review_candidates",
            ]
        }
        bases = con.execute(
            "SELECT text_basis,count(*),count(distinct horse_id) "
            "FROM horse_steward_phrases GROUP BY 1"
        ).fetchall()
        checks_counts = dict(Counter(x["comparison_status"] for x in checks))
        target_path = PACKAGE / "coverage_collection_plan.json"
        target_horses = (
            set(json.loads(target_path.read_text())["target_horse_ids"])
            if target_path.exists()
            else set()
        )
        captured_horses = {
            row["horse_id"] for row in website_rows if row["current_identity_status"] != "conflict"
        }
        missing_horses = sorted(target_horses - captured_horses)
        if file_hash(CORE) != pinned["core_sha256"]:
            raise ValueError("source core changed during build")
        summary = dict(
            version=VERSION,
            core_preserved=True,
            core_sha256=pinned["core_sha256"],
            successful_pages=len({r["url"] for r in ledger if r["status"] == "captured"}),
            failed_pages=len(
                {r["url"] for r in ledger} - {r["url"] for r in ledger if r["status"] == "captured"}
            ),
            failed_capture_attempts=sum(r["status"] != "captured" for r in ledger),
            revalidated_responses=sum(bool(r.get("revalidated_at_utc")) for r in ledger),
            counts=counts,
            text_bases=bases,
            website_api_comparison=checks_counts,
            independent_html_row_parity_count=independent_count,
            historical_identity_status=dict(
                Counter(r["historical_identity_status"] for r in website_rows)
            ),
            current_identity_status=dict(
                Counter(r["current_identity_status"] for r in website_rows)
            ),
            text_identity_status=dict(Counter(p["text_identity_status"] for p in phrases)),
            all_api_links_rechecked=True,
            no_situation_classification=True,
            target_horse_count=len(target_horses),
            target_horses_with_website_row=len(target_horses & captured_horses),
            target_horses_missing_website_row=missing_horses,
            website_history_horse_count=con.execute(
                "SELECT count(DISTINCT horse_id) FROM horse_steward_phrases"
            ).fetchone()[0],
            code_sha256=file_hash(Path(__file__)),
            collection_plan_sha256=file_hash(PACKAGE / "collection_plan.json"),
            coverage_plan_sha256=file_hash(target_path) if target_path.exists() else None,
            output_db_sha256=None,
        )
        write_json(OUTPUT / "summary.json", summary)
        with (OUTPUT / "website_api_comparison.jsonl").open("w", encoding="utf-8") as stream:
            for row in checks:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        con.close()
    staging.rename(DB)
    summary["output_db_sha256"] = file_hash(DB)
    write_json(OUTPUT / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "expand", "fetch", "revalidate", "build"])
    args = parser.parse_args()
    {
        "prepare": prepare,
        "expand": expand,
        "fetch": fetch,
        "revalidate": revalidate,
        "build": build,
    }[args.command]()
