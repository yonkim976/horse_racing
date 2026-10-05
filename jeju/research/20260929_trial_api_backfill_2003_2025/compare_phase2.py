"""Compare official riding-trial API rows with the read-only phase2 snapshot."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHASE2_DB = Path(__file__).resolve().parents[3] / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
YEARS = tuple(range(2003, 2026))
JEJU_RAW_LABEL = "제주"
PHASE2_JEJU_STATUSES = {"native_confirmed", "native_candidate_breed_unconfirmed"}
SIBLING_2026_ATTEMPT = Path(__file__).resolve().parents[3] / "jeju/research/20260929_core_collection_inventory/raw/trials/2026/attempts/20260929T131937.249978Z"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def integer(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def official_rows(year: int) -> tuple[list[dict], dict]:
    attempt_files = sorted((ROOT / "raw/trials" / str(year) / "attempts").glob("*/attempt_manifest.json"))
    completed: tuple[Path, dict] | None = None
    for manifest_path in reversed(attempt_files):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") == "completed_api_response":
            completed = manifest_path, manifest
            break
    if completed is None:
        raise RuntimeError(f"No completed official API attempt for {year}")
    manifest_path, manifest = completed
    rows: list[dict] = []
    for page in manifest.get("source_pages", []):
        source_path = manifest_path.parent / page["response_file"]
        raw = source_path.read_bytes()
        if sha256(raw) != page["response_sha256"]:
            raise RuntimeError(f"SHA-256 mismatch in {source_path}")
        payload = json.loads(raw)
        body = payload.get("response", payload).get("body", {})
        values = (body.get("items") or {}).get("item")
        if values is None:
            batch = []
        elif isinstance(values, dict):
            batch = [values]
        elif isinstance(values, list) and all(isinstance(row, dict) for row in values):
            batch = values
        else:
            raise RuntimeError(f"Unexpected row structure in {source_path}")
        rows.extend(batch)
    if len(rows) != manifest.get("upstream_total_count"):
        raise RuntimeError(f"API totalCount mismatch in year {year}")
    return rows, {"attempt_manifest": manifest_path.relative_to(ROOT).as_posix(), "attempt_id": manifest.get("attempt_id"), "manifest_status": manifest.get("status")}


def sibling_2026_rows() -> tuple[list[dict], dict]:
    manifest_path = SIBLING_2026_ATTEMPT / "attempt_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "completed_api_response":
        raise RuntimeError("The separately collected 2026 API attempt is not complete")
    rows: list[dict] = []
    for page in manifest.get("source_pages", []):
        raw = (SIBLING_2026_ATTEMPT / page["response_file"]).read_bytes()
        if sha256(raw) != page["response_sha256"]:
            raise RuntimeError("SHA-256 mismatch in the separate 2026 API attempt")
        payload = json.loads(raw)
        values = (payload.get("response", payload).get("body", {}).get("items") or {}).get("item")
        if values is None:
            batch = []
        elif isinstance(values, dict):
            batch = [values]
        elif isinstance(values, list) and all(isinstance(row, dict) for row in values):
            batch = values
        else:
            raise RuntimeError("Unexpected row structure in the separate 2026 API attempt")
        rows.extend(batch)
    if len(rows) != manifest.get("upstream_total_count"):
        raise RuntimeError("2026 API totalCount mismatch")
    return rows, {
        "attempt_manifest": "../20260929_core_collection_inventory/raw/trials/2026/attempts/20260929T131937.249978Z/attempt_manifest.json",
        "attempt_id": manifest.get("attempt_id"),
        "manifest_status": manifest.get("status"),
        "source_pages_sha256_verified": True,
    }


def api_key(row: dict) -> tuple[str, int | None, int | None]:
    return (digits(row.get("trainDate"))[:8], integer(row.get("trainNo")), integer(row.get("chulNo")))


def api_event_key(row: dict) -> tuple[str, int | None, int | None]:
    return (digits(row.get("trainDate"))[:8], integer(row.get("trainNo")), integer(row.get("daySerial")))


def api_hr_no(row: dict) -> str | None:
    value = integer(row.get("hrNo"))
    return str(value) if value is not None else None


def phase2_hr_no(row: tuple) -> str | None:
    value = integer(row[4])
    return str(value) if value is not None else None


def phase2_key(row: tuple) -> tuple[str, int | None, int | None]:
    return (digits(row[0])[:8], int(row[1]) if row[1] is not None else None, int(row[3]) if row[3] is not None else None)


def main() -> None:
    if not PHASE2_DB.exists():
        raise SystemExit(f"Read-only phase2 database not found: {PHASE2_DB}")
    phase2_hash = sha256(PHASE2_DB.read_bytes())
    phase_rows_by_year: dict[str, list[tuple]] = defaultdict(list)
    uri = f"file:{PHASE2_DB.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        query = """SELECT ev.event_date, ev.event_number, ev.trial_round,
                          en.horse_number, en.hr_no, en.horse_name,
                          en.breed_status, en.identity_status
                   FROM event ev JOIN entry en ON en.event_id=ev.id
                   WHERE ev.event_type='trial' AND ev.meet=2
                     AND ev.event_date BETWEEN '20030101' AND '20251231'
                   ORDER BY ev.event_date, ev.event_number, en.horse_number"""
        for row in connection.execute(query):
            phase_rows_by_year[digits(row[0])[:4]].append(row)

    report_years: dict[str, dict] = {}
    all_api_total = 0
    all_api_jeju_label = 0
    all_phase2_total = 0
    all_phase2_candidates = 0
    all_api_jeju_dates: list[str] = []
    all_api_jeju_events: set[tuple[str, int | None, int | None]] = set()
    for year in YEARS:
        api_rows, attempt_info = official_rows(year)
        phase_rows = phase_rows_by_year[str(year)]
        api_counts = Counter("(blank)" if row.get("majong") is None or str(row.get("majong")).strip() == "" else str(row.get("majong")).strip() for row in api_rows)
        api_jeju = [row for row in api_rows if str(row.get("majong") or "").strip() == JEJU_RAW_LABEL]
        phase_candidates = [row for row in phase_rows if row[6] in PHASE2_JEJU_STATUSES]
        api_all_by_key: dict[tuple, list[dict]] = defaultdict(list)
        api_by_key: dict[tuple, list[dict]] = defaultdict(list)
        phase_by_key: dict[tuple, list[tuple]] = defaultdict(list)
        for row in api_rows:
            api_all_by_key[api_key(row)].append(row)
        for row in api_jeju:
            api_by_key[api_key(row)].append(row)
        for row in phase_candidates:
            phase_by_key[phase2_key(row)].append(row)
        api_keys = set(api_by_key)
        phase_keys = set(phase_by_key)
        common_keys = api_keys & phase_keys
        matched_ids = []
        hr_conflicts = []
        missing_id_keys = []
        for key in sorted(common_keys):
            official_ids = sorted({api_hr_no(row) for row in api_by_key[key] if api_hr_no(row)})
            phase_ids = sorted({phase2_hr_no(row) for row in phase_by_key[key] if phase2_hr_no(row)})
            if set(official_ids) & set(phase_ids):
                matched_ids.append(key)
            elif not official_ids or not phase_ids:
                missing_id_keys.append({
                    "event_date": key[0],
                    "trial_number": key[1],
                    "horse_number": key[2],
                    "api_hr_no": official_ids,
                    "phase2_hr_no": phase_ids,
                    "phase2_identity_status": sorted({row[7] for row in phase_by_key[key]}),
                })
            else:
                hr_conflicts.append({
                    "event_date": key[0],
                    "trial_number": key[1],
                    "horse_number": key[2],
                    "api_hr_no": official_ids,
                    "phase2_hr_no": phase_ids,
                    "phase2_breed_status": sorted({row[6] for row in phase_by_key[key]}),
                    "phase2_identity_status": sorted({row[7] for row in phase_by_key[key]}),
                    "api_majong_labels": sorted({str(row.get("majong")) for row in api_by_key[key]}),
                    "api_day_serials": sorted({integer(row.get("daySerial")) for row in api_by_key[key]}),
                    "phase2_trial_rounds": sorted({row[2] for row in phase_by_key[key]}),
                })
        api_only = []
        for key in sorted(api_keys - phase_keys):
            for row in api_by_key[key]:
                api_only.append({
                    "event_date": key[0], "trial_number": key[1], "horse_number": key[2],
                    "hr_no": api_hr_no(row), "horse_name": row.get("hrName"),
                    "majong": row.get("majong"), "day_serial": integer(row.get("daySerial")),
                })
        phase2_only = []
        for key in sorted(phase_keys - api_keys):
            for row in phase_by_key[key]:
                phase2_only.append({
                    "event_date": key[0], "trial_number": key[1], "horse_number": key[2],
                    "hr_no": str(row[4]) if row[4] is not None else None,
                    "horse_name": row[5], "breed_status": row[6],
                    "identity_status": row[7], "trial_round": row[2],
                    "same_key_api_rows": [
                        {"hr_no": api_hr_no(api_row), "horse_name": api_row.get("hrName"), "majong": api_row.get("majong"), "day_serial": integer(api_row.get("daySerial"))}
                        for api_row in api_all_by_key.get(key, [])
                    ],
                })
        api_dates = [digits(row.get("trainDate"))[:8] for row in api_rows if len(digits(row.get("trainDate"))) >= 8]
        api_jeju_dates = [digits(row.get("trainDate"))[:8] for row in api_jeju if len(digits(row.get("trainDate"))) >= 8]
        phase2_dates = [digits(row[0])[:8] for row in phase_rows if len(digits(row[0])) >= 8]
        phase2_first_date = min(phase2_dates) if phase2_dates else None
        api_only_before_phase2 = [row for row in api_only if phase2_first_date and row["event_date"] < phase2_first_date]
        api_only_on_or_after_phase2 = [row for row in api_only if not phase2_first_date or row["event_date"] >= phase2_first_date]
        all_api_jeju_dates.extend(api_jeju_dates)
        all_api_jeju_events.update(api_event_key(row) for row in api_jeju)
        candidate_status_counts = Counter(row[6] for row in phase_candidates)
        year_report = {
            **attempt_info,
            "api_total_rows": len(api_rows),
            "api_raw_majong_value_counts": dict(sorted(api_counts.items())),
            "api_exact_majong_jeju_label_rows": len(api_jeju),
            "api_first_date": min(api_dates) if api_dates else None,
            "api_last_date": max(api_dates) if api_dates else None,
            "api_jeju_label_first_date": min(api_jeju_dates) if api_jeju_dates else None,
            "api_jeju_label_last_date": max(api_jeju_dates) if api_jeju_dates else None,
            "phase2_total_trial_rows": len(phase_rows),
            "phase2_first_date": phase2_first_date,
            "phase2_last_date": max(phase2_dates) if phase2_dates else None,
            "phase2_jeju_candidate_rows": len(phase_candidates),
            "phase2_jeju_candidate_status_counts": dict(sorted(candidate_status_counts.items())),
            "shared_event_trial_horse_keys": len(common_keys),
            "shared_keys_with_same_hr_no": len(matched_ids),
            "shared_keys_with_missing_hr_no": missing_id_keys,
            "shared_keys_with_hr_no_conflict": hr_conflicts,
            "api_jeju_label_rows_without_phase2_candidate_key": api_only,
            "api_jeju_only_keys_before_phase2_first_date": len(api_only_before_phase2),
            "api_jeju_only_keys_on_or_after_phase2_first_date": len(api_only_on_or_after_phase2),
            "phase2_candidate_rows_without_api_jeju_label_key": phase2_only,
        }
        report_years[str(year)] = year_report
        all_api_total += len(api_rows)
        all_api_jeju_label += len(api_jeju)
        all_phase2_total += len(phase_rows)
        all_phase2_candidates += len(phase_candidates)

    supplemental_years: dict[str, dict] = {}
    supplemental_api_rows = 0
    supplemental_api_jeju_rows = 0
    for year in (2000, 2001, 2002):
        rows, attempt_info = official_rows(year)
        label_counts = Counter("(blank)" if row.get("majong") is None or str(row.get("majong")).strip() == "" else str(row.get("majong")).strip() for row in rows)
        dates = [digits(row.get("trainDate"))[:8] for row in rows if len(digits(row.get("trainDate"))) >= 8]
        jeju_dates = [digits(row.get("trainDate"))[:8] for row in rows if str(row.get("majong") or "").strip() == JEJU_RAW_LABEL and len(digits(row.get("trainDate"))) >= 8]
        supplemental_years[str(year)] = {
            **attempt_info,
            "api_total_rows": len(rows),
            "api_raw_majong_value_counts": dict(sorted(label_counts.items())),
            "api_exact_majong_jeju_label_rows": label_counts.get(JEJU_RAW_LABEL, 0),
            "api_first_date": min(dates) if dates else None,
            "api_last_date": max(dates) if dates else None,
            "api_jeju_label_first_date": min(jeju_dates) if jeju_dates else None,
            "api_jeju_label_last_date": max(jeju_dates) if jeju_dates else None,
        }
        supplemental_api_rows += len(rows)
        supplemental_api_jeju_rows += label_counts.get(JEJU_RAW_LABEL, 0)
        all_api_jeju_dates.extend(jeju_dates)
        all_api_jeju_events.update(api_event_key(row) for row in rows if str(row.get("majong") or "").strip() == JEJU_RAW_LABEL)

    jeju_dates_2000_2025 = list(all_api_jeju_dates)
    rows_2026, attempt_2026 = sibling_2026_rows()
    rows_2026_jeju = [row for row in rows_2026 if str(row.get("majong") or "").strip() == JEJU_RAW_LABEL]
    dates_2026 = [digits(row.get("trainDate"))[:8] for row in rows_2026 if len(digits(row.get("trainDate"))) >= 8]
    jeju_dates_2026 = [digits(row.get("trainDate"))[:8] for row in rows_2026_jeju if len(digits(row.get("trainDate"))) >= 8]
    all_api_jeju_dates.extend(jeju_dates_2026)
    all_api_jeju_events.update(api_event_key(row) for row in rows_2026_jeju)
    year_2026_summary = {
        **attempt_2026,
        "api_total_rows": len(rows_2026),
        "api_exact_majong_jeju_label_rows": len(rows_2026_jeju),
        "api_first_date": min(dates_2026) if dates_2026 else None,
        "api_last_date": max(dates_2026) if dates_2026 else None,
        "api_jeju_label_first_date": min(jeju_dates_2026) if jeju_dates_2026 else None,
        "api_jeju_label_last_date": max(jeju_dates_2026) if jeju_dates_2026 else None,
    }

    summary = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "comparison_scope": {"first_year": 2003, "last_year": 2025, "meet": 2, "event_type": "trial"},
        "official_api_source": "KRA OpenAPI 15056974, /API20_1/ridingTestResult_1",
        "api_breed_semantics": "The official portal describes the response field majong as 마종, but the public page did not expose an enum code table. Exact majong=제주 counts are reported as raw labels; no extra normalization is applied.",
        "api_primary_total_rows_2003_2025": all_api_total,
        "api_primary_exact_majong_jeju_label_rows_2003_2025": all_api_jeju_label,
        "supplemental_api_coverage_2000_2002": supplemental_years,
        "api_total_rows_2000_2025": all_api_total + supplemental_api_rows,
        "api_exact_majong_jeju_label_rows_2000_2025": all_api_jeju_label + supplemental_api_jeju_rows,
        "api_exact_majong_jeju_label_first_date_2000_2025": min(jeju_dates_2000_2025) if jeju_dates_2000_2025 else None,
        "sibling_2026_api_coverage": year_2026_summary,
        "api_total_rows_2000_2026": all_api_total + supplemental_api_rows + len(rows_2026),
        "api_exact_majong_jeju_label_rows_2000_2026": all_api_jeju_label + supplemental_api_jeju_rows + len(rows_2026_jeju),
        "api_exact_majong_jeju_label_first_date_2000_2026": min(all_api_jeju_dates) if all_api_jeju_dates else None,
        "api_exact_majong_jeju_label_last_date_2000_2026": max(all_api_jeju_dates) if all_api_jeju_dates else None,
        "distinct_trial_events_majong_jeju_2000_2026": len(all_api_jeju_events),
        "phase2_db": str(PHASE2_DB.relative_to(ROOT.parents[3])),
        "phase2_db_sha256": phase2_hash,
        "phase2_db_open_mode": "read-only SQLite URI with query_only pragma",
        "phase2_trial_rows_2003_2025": all_phase2_total,
        "phase2_jeju_candidate_rows_2003_2025": all_phase2_candidates,
        "annual_comparison": report_years,
        "source_pages_sha256_verified": True,
        "sibling_2026_source_pages_sha256_verified": True,
        "database_modified": False,
    }
    output_path = ROOT / "api_vs_phase2_comparison.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 공식 주행심사 API와 phase2 제주 후보 비교",
        "",
        "비교 범위: 2003~2025년, 제주 시행 경주장(`meet=2`) 주행심사.",
        "",
        "공식 API의 `majong`은 포털 설명에서 마종 필드로 안내된다. 공개 포털 페이지에서 enum 코드표를 확인하지 못했으므로 `majong=제주`는 원문 값 그대로 세고, 별도 코드로 정규화하지 않았다. phase2 행은 연구 스냅샷을 SQLite 읽기 전용으로 조회했다.",
        "",
        f"공식 API 응답은 총 {all_api_total:,}행이며, `majong=제주` 원문 라벨은 {all_api_jeju_label:,}행이다. phase2 심사행은 {all_phase2_total:,}행이고, 기존 제주 후보 상태는 {all_phase2_candidates:,}행이다.",
        "",
        "| 연도 | API 전체행 | API `majong=제주` | phase2 전체행 | phase2 제주 후보 | 같은 날짜·심사·출주번호 | 같은 공식 말 ID | API 제주 후보 추가 | phase2만 제주 후보 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        row = report_years[str(year)]
        lines.append(
            f"| {year} | {row['api_total_rows']:,} | {row['api_exact_majong_jeju_label_rows']:,} | "
            f"{row['phase2_total_trial_rows']:,} | {row['phase2_jeju_candidate_rows']:,} | "
            f"{row['shared_event_trial_horse_keys']:,} | {row['shared_keys_with_same_hr_no']:,} | "
            f"{len(row['api_jeju_label_rows_without_phase2_candidate_key']):,} | "
            f"{len(row['phase2_candidate_rows_without_api_jeju_label_key']):,} |"
        )
    all_conflicts = [item for yr in report_years.values() for item in yr["shared_keys_with_hr_no_conflict"]]
    all_missing_ids = [item for yr in report_years.values() for item in yr["shared_keys_with_missing_hr_no"]]
    all_api_only = [item for yr in report_years.values() for item in yr["api_jeju_label_rows_without_phase2_candidate_key"]]
    all_phase2_only = [item for yr in report_years.values() for item in yr["phase2_candidate_rows_without_api_jeju_label_key"]]
    lines.extend(["", "## 키 차이", ""])
    if all_api_only:
        lines.append(f"- API `majong=제주`에만 있는 행: {len(all_api_only)}행. 상세 자연키는 JSON의 연도별 `api_jeju_label_rows_without_phase2_candidate_key`에 있다.")
        for item in all_api_only[:20]:
            lines.append(f"  - {item['event_date']} 심사 {item['trial_number']}, 출주 {item['horse_number']}, 말 ID {item['hr_no']} {item['horse_name']}")
        rows_2003 = report_years["2003"]
        lines.append(f"- 2003년 11행을 phase2 첫 관측일 {rows_2003['phase2_first_date']}과 비교하면 9행은 그 이전 공백이고, 2행은 이후인 2003-09-05 심사1 출주1·2다. 9/5 심사는 phase2에 없어 시작일 공백으로는 설명되지 않는다.")
    if all_phase2_only:
        lines.append(f"- phase2 제주 후보 중 API 원문 라벨이 `제주`가 아닌 행: {len(all_phase2_only)}행. 상세는 JSON의 `phase2_candidate_rows_without_api_jeju_label_key`에 있다.")
        for item in all_phase2_only[:20]:
            api_same_key = ", ".join(f"API majong={row['majong']} / 말 ID {row['hr_no']}" for row in item.get("same_key_api_rows", [])) or "API에 같은 출주키 없음"
            lines.append(f"  - {item['event_date']} 심사 {item['trial_number']}, 출주 {item['horse_number']}, 말 ID {item['hr_no']} ({item['breed_status']}); {api_same_key}")
    if all_conflicts:
        lines.extend(["", "## 같은 출주키의 말 ID 충돌", ""])
        for item in all_conflicts:
            lines.append(f"- {item['event_date']} 심사 {item['trial_number']}, 출주 {item['horse_number']}: API 말 ID {', '.join(item['api_hr_no'])}; phase2 말 ID {', '.join(item['phase2_hr_no'])}; API `majong`={', '.join(item['api_majong_labels'])}.")
    if all_missing_ids:
        lines.extend(["", "## 같은 출주키에서 phase2 말 ID 미연결", "", f"- 날짜·심사·출주번호가 일치하지만 phase2 말 ID가 확인되지 않아 API 공식 ID와 대조할 수 없는 키가 {len(all_missing_ids)}개 있다. 전체 목록은 JSON의 연도별 `shared_keys_with_missing_hr_no`에 저장했다."])
    lines.extend([
        "",
        "## 2000~2002 보충 조회",
        "",
        "| 연도 | API 전체행 | API `majong=제주` | 전체 날짜 범위 | 제주 라벨 날짜 범위 |",
        "|---:|---:|---:|---|---|",
    ])
    for year, row in supplemental_years.items():
        total_range = f"{row['api_first_date']}~{row['api_last_date']}" if row["api_first_date"] else "날짜 없음"
        jeju_range = f"{row['api_jeju_label_first_date']}~{row['api_jeju_label_last_date']}" if row["api_jeju_label_first_date"] else "해당 라벨 없음"
        lines.append(f"| {year} | {row['api_total_rows']:,} | {row['api_exact_majong_jeju_label_rows']:,} | {total_range} | {jeju_range} |")
    lines.extend([
        "",
        f"2000~2025 전체 API 응답은 {all_api_total + supplemental_api_rows:,}행이며, exact `majong=제주`는 {all_api_jeju_label + supplemental_api_jeju_rows:,}행이다. 이 raw label의 첫 관측일은 {min(all_api_jeju_dates) if all_api_jeju_dates else '미확인'}이다.",
        "",
        f"별도 보존된 2026 시도는 {len(rows_2026):,}행이며 exact `majong=제주` {len(rows_2026_jeju):,}행이다. 중복 호출 없이 이 원문을 참조했을 때 2000~2026 전체는 API {all_api_total + supplemental_api_rows + len(rows_2026):,}행, 제주 라벨 {all_api_jeju_label + supplemental_api_jeju_rows + len(rows_2026_jeju):,}행, {len(all_api_jeju_events):,}개 날짜·심사·daySerial 심사키이고 제주 라벨 기간은 {min(all_api_jeju_dates) if all_api_jeju_dates else '미확인'}~{max(all_api_jeju_dates) if all_api_jeju_dates else '미확인'}이다.",
        "",
        "이 비교는 원천/키 coverage 감사다. API `majong` 범주를 phase2 확정 제주마로 자동 승격하지 않으며, 두 원천 간 충돌은 격리 검토 대상으로 남긴다.",
        "",
        "기계 판독 연도별 표와 API 원문 페이지 SHA-256 검증 결과: [`api_vs_phase2_comparison.json`](api_vs_phase2_comparison.json).",
        "",
    ])
    (ROOT / "API_VS_PHASE2_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "report": str((ROOT / "API_VS_PHASE2_COMPARISON.md")),
        "json": str(output_path),
        "api_rows": all_api_total,
        "api_majong_jeju_rows": all_api_jeju_label,
        "api_only": len(all_api_only),
        "phase2_only": len(all_phase2_only),
        "hr_no_conflicts": len(all_conflicts),
        "missing_hr_no_keys": len(all_missing_ids),
        "api_total_2000_2025": all_api_total + supplemental_api_rows,
        "api_majong_jeju_2000_2025": all_api_jeju_label + supplemental_api_jeju_rows,
        "api_jeju_first_date_2000_2025": min(all_api_jeju_dates) if all_api_jeju_dates else None,
        "api_total_2000_2026": all_api_total + supplemental_api_rows + len(rows_2026),
        "api_majong_jeju_2000_2026": all_api_jeju_label + supplemental_api_jeju_rows + len(rows_2026_jeju),
        "jeju_events_2000_2026": len(all_api_jeju_events),
        "phase2_db_modified": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
