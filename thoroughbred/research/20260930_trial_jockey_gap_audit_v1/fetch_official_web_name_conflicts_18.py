"""Fetch and reconcile the 18 KRA trial rows with local horse-name conflicts."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = HERE / "trial_jockey_missing_audit.jsonl"
RAW = HERE / "raw_official_web_name_conflicts_18"
OUTPUT = HERE / "official_web_name_conflicts_18.jsonl"
MANIFEST = HERE / "official_web_name_conflicts_18_manifest.json"
URL = "https://race.kra.co.kr/referee/RacingTrainCheckScoreTable.do"
ALLOWED_HOST = "race.kra.co.kr"
MAX_RESPONSE_BYTES = 5_000_000
TARGET_STATUS = "excluded_unresolved_horse_name_mismatch"
HORSE_LINK = re.compile(r"goPage1\('([0-9]+)'\s*,\s*'([0-9]+)'")
JOCKEY_LINK = re.compile(r"goPage2\('([0-9]+)'\s*,\s*'([0-9]+)'")
TIME_VALUE = re.compile(r"^(\d+):(\d{2})\.(\d+)$")
RESULT_STATUSES = {
    "합격", "불합격", "합격유보", "출주취소", "출전취소", "출전제외",
    "연습취소", "연습제외", "심사취소", "검사취소", "연습주행", "주행연습",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Keep this read-only fetch restricted to the official KRA host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise ValueError(f"Refusing redirect outside https://{ALLOWED_HOST}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ScoreTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.table_stack: list[dict] = []
        self.row: list[dict] | None = None
        self.cell: dict | None = None
        self.caption: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            table = {"caption": "", "rows": []}
            self.tables.append(table)
            self.table_stack.append(table)
        elif tag == "caption" and self.table_stack:
            self.caption = []
        elif tag == "tr" and self.table_stack:
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": [], "onclick": []}
        elif tag == "a" and self.cell is not None and attributes.get("onclick"):
            self.cell["onclick"].append(attributes["onclick"])

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)
        if self.caption is not None:
            self.caption.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "caption" and self.caption is not None:
            if self.table_stack:
                self.table_stack[-1]["caption"] = " ".join("".join(self.caption).split())
            self.caption = None
        elif tag == "td" and self.cell is not None:
            self.cell["text"] = " ".join("".join(self.cell["text"]).split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table_stack[-1]["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table_stack:
            self.table_stack.pop()


def get_score_page(meet: int, date: str, trial_no: int) -> bytes:
    if meet not in (1, 3) or not re.fullmatch(r"20\d{6}", date) or not 1 <= trial_no <= 20:
        raise ValueError("Unexpected official score request key")
    body = urlencode({
        "meet": meet,
        "trno": trial_no,
        "date": date,
        "Act": "06",
        "Sub": "7",
    }).encode("ascii")
    request = Request(
        URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    opener = build_opener(SameHostRedirectHandler())
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or urlparse(response.url).hostname != ALLOWED_HOST:
            raise ValueError("Unexpected KRA score response")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("Oversized KRA score response")
    return payload


def seconds_from_time(value: str | None) -> float | None:
    if not value:
        return None
    match = TIME_VALUE.fullmatch(value.strip())
    if not match:
        return None
    minutes, seconds, fraction = match.groups()
    return int(minutes) * 60 + int(seconds) + float(f"0.{fraction}")


def parse_score_rows(payload: bytes, date: str, trial_no: int) -> list[dict]:
    html = payload.decode("euc-kr", errors="replace")
    date_label = f"{date[:4]}년 {int(date[4:6]):02d}월 {int(date[6:]):02d}일"
    if date_label not in html or f"{trial_no}경주" not in html:
        raise ValueError(f"Official score page did not show requested date/trial: {date} {trial_no}")

    parser = ScoreTableParser()
    parser.feed(html)
    result_tables = [
        table for table in parser.tables
        if "주행심사결과를 순위" in table["caption"]
    ]
    if len(result_tables) != 1:
        raise ValueError("Official trial score table not found or not unique")

    rows = []
    for cells in result_tables[0]["rows"]:
        if len(cells) < 9 or not cells[1]["text"].isdigit():
            continue
        horse_match = HORSE_LINK.search(" ".join(cells[2]["onclick"]))
        jockey_match = JOCKEY_LINK.search(" ".join(cells[8]["onclick"]))
        cell_texts = [cell["text"] for cell in cells]
        time_values = [value for value in cell_texts if TIME_VALUE.fullmatch(value)]
        finish_time = time_values[0] if time_values else None
        status_values = [value for value in cell_texts if value in RESULT_STATUSES]
        status = status_values[-1] if status_values else None
        rows.append({
            "horse_program_no": int(cells[1]["text"]),
            "horse_name": cells[2]["text"],
            "horse_id": horse_match.group(1) if horse_match else None,
            "jockey_name": cells[8]["text"] or None,
            "jockey_id": jockey_match.group(1) if jockey_match else None,
            "finish_time": finish_time,
            "finish_time_seconds": seconds_from_time(finish_time),
            "result_status": status,
            "row_text": " ".join(value for value in cell_texts if value),
        })
    return rows


def api_seconds(value) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Unexpected API time value: {value!r}")


def main() -> None:
    targets = [
        json.loads(line)
        for line in SOURCE.open(encoding="utf-8")
        if json.loads(line).get("rpt_jockey_supplement_status") == TARGET_STATUS
    ]
    if len(targets) != 18:
        raise ValueError(f"Expected 18 name-conflict targets, found {len(targets)}")

    RAW.mkdir(exist_ok=True)
    observations = []
    captures = []
    for target in targets:
        meet = int(target["source_meet_query"])
        date = target["api_trainDate"]
        trial_no = int(target["api_trainNo"])
        horse_no = int(target["api_chulNo"])
        payload = get_score_page(meet, date, trial_no)
        path = RAW / f"meet_{meet}_date_{date}_trial_{trial_no}.html"
        path.write_bytes(payload)
        digest = sha256_bytes(payload)
        score_rows = parse_score_rows(payload, date, trial_no)
        matches = [
            row for row in score_rows
            if row["horse_program_no"] == horse_no and row["horse_id"] == target["api_hrNo"]
        ]
        if len(matches) != 1:
            raise ValueError(
                f"No unique official score row for {target['participant_row_id']}: {len(matches)}"
            )
        match = matches[0]

        if match["horse_name"] != target["api_hrName"]:
            raise ValueError(f"Official horse name differs from API for {target['participant_row_id']}")
        if match["horse_id"] != target["api_hrNo"]:
            raise ValueError(f"Official horse ID differs from API for {target['participant_row_id']}")

        api_time = api_seconds(target.get("api_rcTime"))
        if api_time is None or match["finish_time_seconds"] is None:
            raise ValueError(f"Missing API or official time for {target['participant_row_id']}")
        if round(api_time, 1) != round(match["finish_time_seconds"], 1):
            raise ValueError(f"API and official time differ for {target['participant_row_id']}")

        api_status = target.get("api_passFlag")
        if api_time == 0:
            if match["result_status"] != "출주취소" or api_status not in (None, "", "-"):
                raise ValueError(f"Expected cancelled trial row for {target['participant_row_id']}")
            jockey_semantics = "assigned_jockey_only_actual_ride_not_confirmed"
        else:
            if match["result_status"] != api_status:
                raise ValueError(f"API and official result status differ for {target['participant_row_id']}")
            jockey_semantics = "official_completed_trial_rider"

        candidate_jockey = target.get("rpt_jockey_name_candidate")
        observations.append({
            "participant_row_id": target["participant_row_id"],
            "meet": meet,
            "date": date,
            "trial_no": trial_no,
            "horse_program_no": horse_no,
            "api_horse_id": target["api_hrNo"],
            "api_horse_name": target["api_hrName"],
            "rpt_horse_name_candidate": target.get("rpt_horse_name_candidate"),
            "official_horse_id": match["horse_id"],
            "official_horse_name": match["horse_name"],
            "horse_identity_status": "exact_official_horse_id_and_event_key",
            "rpt_jockey_name_candidate": candidate_jockey,
            "official_jockey_id": match["jockey_id"],
            "official_jockey_name": match["jockey_name"],
            "jockey_candidate_comparison": (
                "exact_name_match" if candidate_jockey == match["jockey_name"]
                else "name_differs_from_official"
            ),
            "jockey_semantics": jockey_semantics,
            "api_finish_time_seconds": api_time,
            "official_finish_time": match["finish_time"],
            "official_finish_time_seconds": match["finish_time_seconds"],
            "api_result_status": api_status,
            "official_result_status": match["result_status"],
            "api_result_reason": target.get("api_reason"),
            "api_result_detail": target.get("api_nopassReason"),
            "official_web_row_text": match["row_text"],
            "official_web_source_file": relative(path),
            "official_web_source_sha256": digest,
            "official_web_source_url": URL,
            "official_web_request_form": {
                "meet": meet,
                "trno": trial_no,
                "date": date,
                "Act": "06",
                "Sub": "7",
            },
        })
        captures.append({
            "meet": meet,
            "date": date,
            "trial_no": trial_no,
            "source_file": relative(path),
            "sha256": digest,
            "score_rows": len(score_rows),
        })

    observations.sort(key=lambda row: row["participant_row_id"])
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        for row in observations:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    exact_jockey_matches = sum(
        row["jockey_candidate_comparison"] == "exact_name_match" for row in observations
    )
    jockey_name_differences = [
        row for row in observations if row["jockey_candidate_comparison"] != "exact_name_match"
    ]
    summary = {
        "source": relative(SOURCE),
        "source_sha256": sha256_bytes(SOURCE.read_bytes()),
        "official_score_url": URL,
        "request_method": "POST",
        "captures": captures,
        "observations": len(observations),
        "official_horse_id_exact_match_count": sum(
            row["horse_identity_status"] == "exact_official_horse_id_and_event_key"
            for row in observations
        ),
        "completed_trial_count": sum(
            row["jockey_semantics"] == "official_completed_trial_rider" for row in observations
        ),
        "cancelled_trial_count": sum(
            row["jockey_semantics"] == "assigned_jockey_only_actual_ride_not_confirmed"
            for row in observations
        ),
        "time_and_result_status_checks": "all matched API values",
        "official_jockey_id_count": sum(bool(row["official_jockey_id"]) for row in observations),
        "rpt_candidate_jockey_exact_match_count": exact_jockey_matches,
        "rpt_candidate_jockey_name_difference_count": len(jockey_name_differences),
        "rpt_candidate_jockey_name_differences": [
            {
                "date": row["date"],
                "meet": row["meet"],
                "trial_no": row["trial_no"],
                "horse_program_no": row["horse_program_no"],
                "rpt_candidate": row["rpt_jockey_name_candidate"],
                "official_name": row["official_jockey_name"],
                "official_id": row["official_jockey_id"],
            }
            for row in jockey_name_differences
        ],
        "output": relative(OUTPUT),
        "output_sha256": sha256_bytes(OUTPUT.read_bytes()),
    }
    MANIFEST.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "requests": len(captures),
        "targets": len(observations),
        "horse_id_exact_matches": summary["official_horse_id_exact_match_count"],
        "completed_trials": summary["completed_trial_count"],
        "cancelled_trials": summary["cancelled_trial_count"],
        "with_official_jockey_id": summary["official_jockey_id_count"],
        "rpt_jockey_name_differences": summary["rpt_candidate_jockey_name_differences"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
