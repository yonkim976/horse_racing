"""Verify and apply sourced calendar reviews without changing API event spines."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAL = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
REVIEW = ROOT / "thoroughbred/research/20261001_closure_gap_followup_v4/core_review"
START, END = date(2010, 1, 1), date(2026, 9, 29)
STATUSES = (
    "official_day_cancelled", "reported_day_cancelled", "official_closure_nonexecution",
    "race_cancelled", "race_invalid", "reason_recorded_outcome_unclassified",
)
CLOSURE_FIELDS = (
    "meet_code", "venue", "start_date", "end_date", "reason", "evidence_kind",
    "source_url", "source_page",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path: Path, headings: list[str], data: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headings, extrasaction="raise")
        writer.writeheader()
        writer.writerows(data)


def key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["meet"], row["date"], row["race_no"]


def safe_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("Invalid calendar review evidence path")
    return path


def joined(old: str, new: str) -> str:
    return ";".join(dict.fromkeys(value for value in (old + ";" + new).split(";") if value))


def build_review_exports() -> dict:
    """Use only root-approved, hash-pinned review inputs; preserve previous exports."""
    config_path = REVIEW / "approved_inputs.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pinned_paths = {record["path"] for record in config["pinned_files"]}
    required_inputs = [config["subtype_decisions_path"], config["subtype_label_verification_path"],
                       *config["closure_paths"], *config.get("extra_csv_exports", {}).values()]
    if any(path not in pinned_paths for path in required_inputs):
        raise ValueError("Calendar review input is not hash-pinned")
    for record in config["pinned_files"]:
        if sha(safe_path(record["path"])) != record["sha256"]:
            raise ValueError("Changed approved calendar evidence")
    decisions_path = safe_path(config["subtype_decisions_path"])
    decisions = rows(decisions_path)
    pinned_paths = {record["path"] for record in config["pinned_files"]}
    for decision in decisions:
        normalized = []
        for name in decision["evidence_files"].split(";"):
            if not name:
                continue
            path = safe_path(name if name.startswith("thoroughbred/") else
                             (decisions_path.parent / name).relative_to(ROOT).as_posix())
            relative = path.relative_to(ROOT).as_posix()
            if relative not in pinned_paths:
                raise ValueError("Subtype evidence is not hash-pinned")
            normalized.append(relative)
        decision["evidence_files"] = ";".join(dict.fromkeys(normalized))
    base = rows(CAL / "race_nonexecution_adjudication.csv")
    expected = {key(row) for row in base if row["adjudication_status"] == STATUSES[-1]}
    if len(decisions) != 29 or len({key(row) for row in decisions}) != 29 or expected != {key(row) for row in decisions}:
        raise ValueError("Subtype review must cover exactly the original 29 keys")
    labels = json.loads(safe_path(config["subtype_label_verification_path"]).read_text(encoding="utf-8"))
    label_by_key = {key(row): row["explicit_outcome_label"] for row in labels["events"]}
    if set(label_by_key) != expected:
        raise ValueError("Subtype label verification key coverage mismatch")
    for decision in decisions:
        required_label = {"race_cancelled": "취소", "race_invalid": "경주불성립"}.get(decision["reviewed_status"])
        if required_label and label_by_key[key(decision)] != required_label:
            raise ValueError("Subtype decision lacks an explicit matched official label")
    by_key = {key(row): row for row in decisions}
    adjudication = []
    for original in base:
        row = dict(original)
        decision = by_key.get(key(row))
        if decision:
            if decision["previous_status"] != row["adjudication_status"]:
                raise ValueError("Subtype review does not match original status")
            if decision["reviewed_status"] not in ("race_cancelled", "race_invalid", STATUSES[-1]):
                raise ValueError("Unsupported reviewed subtype")
            if decision["reason_text"] != row["reason_text"]:
                raise ValueError("Subtype review must preserve the original displayed reason")
            row["adjudication_status"] = decision["reviewed_status"]
            for field in ("supporting_reason", "evidence_files", "evidence_urls", "evidence_kind", "source_state"):
                row[field] = joined(row[field], decision[field])
            row["verified_date"] = decision["verified_date"]
            row["decision_note"] = decision["decision_note"]
        adjudication.append(row)
    if len(adjudication) != 116 or {key(row) for row in adjudication} != {key(row) for row in base}:
        raise ValueError("Nonexecution key coverage changed")
    if any(row["execution_verdict"] != "no_valid_completed_race" for row in adjudication):
        raise ValueError("Nonexecution verdict changed")
    closures = []
    seen = set()
    for name in config["closure_paths"]:
        for original in rows(safe_path(name)):
            row = {field: original[field] for field in CLOSURE_FIELDS}
            left, right = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
            if row["meet_code"] not in ("1", "3", "4") or right < left:
                raise ValueError("Invalid reviewed closure interval")
            if right < START or left > END:
                raise ValueError("Closure is outside scope")
            if row["source_url"].startswith("user-file:"):
                source_relative = row["source_url"].removeprefix("user-file:")
                safe_path(source_relative)
                if source_relative not in pinned_paths or row["evidence_kind"] != "kra_authored_plan_user_supplied":
                    raise ValueError("User-supplied closure document must be explicitly typed and hash-pinned")
            elif not row["source_url"].startswith("https://"):
                raise ValueError("Closure lacks supported source locator")
            identity = tuple(row[field] for field in CLOSURE_FIELDS)
            if identity not in seen:
                seen.add(identity)
                closures.append(row)
    daily_closures = defaultdict(list)
    for row in closures:
        current = max(START, date.fromisoformat(row["start_date"]))
        end = min(END, date.fromisoformat(row["end_date"]))
        while current <= end:
            daily_closures[(row["meet_code"], current.isoformat())].append(row)
            current += timedelta(days=1)
    daily_subtypes = defaultdict(Counter)
    for row in adjudication:
        iso = date.fromisoformat(row["date"]).isoformat()
        daily_subtypes[(row["meet"], iso)][row["adjudication_status"]] += 1
    calendar = rows(CAL / "daily_calendar.csv")
    for row in calendar:
        c = daily_closures.get((row["meet"], row["date"]), [])
        if c and int(row["executed_race_count"]):
            raise ValueError(f"Reviewed closure conflicts with actual races: {row['meet']}/{row['date']}")
        row["official_closure_reason"] = ";".join(sorted({x["reason"] for x in c}))
        row["official_closure_source_url"] = ";".join(sorted({x["source_url"] for x in c}))
        if c:
            row["race_day_status"] = "official_closure_recorded"
        for status in STATUSES:
            row[f"adjudication_{status}_count"] = str(daily_subtypes[(row["meet"], row["date"])][status])
        if sum(int(row[f"adjudication_{status}_count"]) for status in STATUSES) != int(row["adjudicated_no_valid_completed_race_count"]):
            raise ValueError("Daily subtype totals do not reconcile")
    annual = rows(CAL / "annual_summary.csv")
    for row in annual:
        row["official_closure_calendar_days_documented"] = str(sum(
            bool(day["official_closure_source_url"]) for day in calendar
            if day["meet"] == row["meet"] and day["date"].startswith(row["year"])))
    REVIEW.mkdir(parents=True, exist_ok=True)
    outputs = {
        "subtype_decisions.csv": (list(decisions[0]), decisions),
        "daily_calendar.csv": (list(calendar[0]), calendar),
        "annual_summary.csv": (list(annual[0]), annual),
        "race_nonexecution_adjudication.csv": (list(base[0]), adjudication),
        "official_closure_intervals.csv": (list(CLOSURE_FIELDS), closures),
    }
    allowed_extra_exports = {"closure_boundary_review.csv", "reported_closure_interval_leads.csv",
                             "closure_gap_review_candidates.csv", "closure_plan_amendment_review.csv",
                             "closure_review_questions.csv"}
    for name, source in config.get("extra_csv_exports", {}).items():
        if name not in allowed_extra_exports:
            raise ValueError("Unsupported extra calendar review export")
        source_path = safe_path(source)
        if source_path == REVIEW / name:
            raise ValueError("Extra review source must be distinct from generated export")
        with source_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headings = reader.fieldnames
            data = list(reader)
        if not headings:
            raise ValueError("Extra review export lacks headings")
        outputs[name] = (headings, data)
    output_records = {}
    for name, (fields, data) in outputs.items():
        path = REVIEW / name
        write(path, fields, data)
        output_records[name] = {"rows": len(data), "sha256": sha(path)}
    summary = {
        "calendar_rows": len(calendar), "closure_intervals": len(closures),
        "documented_closure_days": sum(bool(row["official_closure_source_url"]) for row in calendar),
        "adjudication_status_counts": dict(Counter(row["adjudication_status"] for row in adjudication)),
        "reviewed_subtype_rows": len(decisions),
        "subtype_rows_reclassified": sum(row["reviewed_status"] != row["previous_status"] for row in decisions),
        "closure_coverage_status": config["closure_coverage_status"],
        "closure_coverage_gaps": config.get("closure_coverage_gaps", []),
        "closure_source_coverage_path": config.get("closure_source_coverage_path"),
        "checks": {"original_116_keys_preserved": True, "original_29_reviewed_once": True,
                   "execution_verdict_preserved": True, "no_closure_execution_conflicts": True,
                   "daily_adjudication_totals_reconcile": True, "approved_hashes_verified": True},
    }
    manifest = {**summary, "approved_inputs_sha256": sha(config_path),
                "pinned_files": config["pinned_files"], "outputs": output_records}
    (REVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
