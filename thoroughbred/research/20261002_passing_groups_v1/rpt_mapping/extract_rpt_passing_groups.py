"""Extract Dacom11 passing-group print lines and compare with the frozen research snapshot.

The script reads only the precheck's pinned RPT file inventory, the RPT source files,
the independent root parse artifact, and the named research passing snapshot in
read-only mode. It never opens the operating database or uses network access.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRECHECK = ROOT / "thoroughbred/research/20261002_report_passing_precheck_v1"
INVENTORY_PATH = PRECHECK / "passing_rpt_file_evidence.json"
SUMMARY_PATH = PRECHECK / "summary.json"
INVENTORY_JSON_PATH = PRECHECK / "passing_inventory.json"
EXPECTED_RPT_PATH = ROOT / "thoroughbred/research/20261002_passing_groups_v1/root_expected_rpt_points.parquet"
SNAPSHOT_DB = ROOT / "thoroughbred/data/section_passing_raw_2010plus_20260929_v1/section_passing_raw.duckdb"
CAPTURE_MANIFEST = ROOT / "data/raw/kra_text/_manifests/dacom11/manifest.jsonl"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"

VENUE_TO_MEET = {"서울": 1, "부산": 3, "부경": 3, "부산경남": 3, "영천": 4}
HEADER_RE = re.compile(r"^제목\s*:\s*(\d{2,4})년(\d{1,2})월(\d{1,2})일.*?제\s*(\d+)\s*경주")
VENUE_RE = re.compile(r"^\(([^)]+)\)\s*제\s*\d+일")
POINT_RE = re.compile(
    r"^\s*(?:통과순위\s+)?(?P<label>S-?1F|C[1-4]|[1-4]C|G-?(?:8|6|4|3|2|1)F)\s*:"
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(*parts: Any) -> str:
    payload = b"\0".join(str(part).encode("utf-8") for part in parts)
    return hashlib.sha256(payload).hexdigest()


def read_capture_manifest() -> tuple[dict[tuple[str, str], list[dict[str, Any]]], str, int, int]:
    manifest_hash = sha256_file(CAPTURE_MANIFEST)
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    row_count = 0
    downloaded_count = 0
    with CAPTURE_MANIFEST.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row_count += 1
            record = json.loads(line)
            if record.get("status") != "downloaded":
                continue
            downloaded_count += 1
            local_path, source_hash = record.get("local_path"), record.get("sha256")
            if local_path and source_hash:
                index[(local_path, source_hash)].append({"manifest_line_no": line_no, **record})
    return index, manifest_hash, row_count, downloaded_count


def capture_metadata(rel: str, source_hash: str,
                     capture_index: dict[tuple[str, str], list[dict[str, Any]]],
                     capture_manifest_hash: str) -> dict[str, Any]:
    matches = capture_index.get((rel, source_hash), [])
    if len(matches) == 1:
        match = matches[0]
        captured_ms = int(match["retrieved_at_ms"])
        captured_at = datetime.fromtimestamp(captured_ms / 1000, tz=timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        status = "exact_local_path_and_sha256_capture_match"
        line_no = int(match["manifest_line_no"])
        run_id = str(match.get("run_id")) if match.get("run_id") is not None else None
    elif len(matches) > 1:
        captured_ms, captured_at = None, None
        status, line_no, run_id = "multiple_exact_capture_matches_time_not_selected", None, None
    else:
        captured_ms, captured_at = None, None
        status, line_no, run_id = "no_exact_local_path_and_sha256_capture_match", None, None
    return {
        "source_capture_time_status": status,
        "source_captured_at_utc": captured_at,
        "source_captured_at_ms": captured_ms,
        "source_capture_timestamp_basis": "manifest.retrieved_at_ms" if captured_ms is not None else None,
        "source_capture_manifest_path": CAPTURE_MANIFEST.relative_to(ROOT).as_posix(),
        "source_capture_manifest_sha256": capture_manifest_hash,
        "source_capture_manifest_match_count": len(matches),
        "source_capture_manifest_line_no": line_no,
        "source_capture_run_id": run_id,
    }


def write_parquet(name: str, rows: list[dict[str, Any]], schema: pa.Schema) -> dict[str, Any]:
    table = pa.Table.from_pylist(rows, schema=schema)
    path = OUT / name
    pq.write_table(table, path, compression="zstd")
    return {"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size, "row_count": table.num_rows}


def line_parts(raw_line: bytes) -> tuple[bytes, bytes, str]:
    if raw_line.endswith(b"\r\n"):
        return raw_line[:-2], b"\r\n", "CRLF"
    if raw_line.endswith(b"\n"):
        return raw_line[:-1], b"\n", "LF"
    if raw_line.endswith(b"\r"):
        return raw_line[:-1], b"\r", "CR"
    return raw_line, b"", "none"


def make_schemas() -> tuple[pa.Schema, pa.Schema, pa.Schema, pa.Schema]:
    race_schema = pa.schema([
        ("race_locator", pa.string()), ("source_path", pa.string()), ("source_sha256", pa.string()),
        ("source_file_bytes", pa.int64()), ("source_path_meet_code", pa.int16()),
        ("actual_meet_code", pa.int16()), ("actual_venue_label_raw", pa.string()),
        ("venue_bridge_status", pa.string()), ("event_date", pa.string()), ("event_year", pa.int16()),
        ("race_no", pa.int16()), ("title_line_no", pa.int32()), ("title_byte_offset", pa.int64()),
        ("title_line_raw", pa.string()), ("title_line_bytes_hex", pa.string()),
        ("venue_line_no", pa.int32()), ("venue_byte_offset", pa.int64()),
        ("venue_line_raw", pa.string()), ("venue_line_bytes_hex", pa.string()),
        ("source_capture_time_status", pa.string()), ("source_captured_at_utc", pa.string()),
        ("source_captured_at_ms", pa.int64()), ("source_capture_timestamp_basis", pa.string()),
        ("source_capture_manifest_path", pa.string()), ("source_capture_manifest_sha256", pa.string()),
        ("source_capture_manifest_match_count", pa.int16()), ("source_capture_manifest_line_no", pa.int32()),
        ("source_capture_run_id", pa.string()),
    ])
    point_schema = pa.schema([
        ("observation_locator", pa.string()), ("race_locator", pa.string()),
        ("source_path", pa.string()), ("source_sha256", pa.string()), ("source_file_bytes", pa.int64()),
        ("source_path_meet_code", pa.int16()), ("actual_meet_code", pa.int16()),
        ("actual_venue_label_raw", pa.string()), ("venue_bridge_status", pa.string()),
        ("event_date", pa.string()), ("event_year", pa.int16()), ("race_no", pa.int16()),
        ("source_line_no", pa.int32()), ("source_line_byte_offset", pa.int64()),
        ("source_line_byte_length", pa.int32()), ("source_line_ending", pa.string()),
        ("raw_line_text", pa.string()), ("raw_line_bytes_hex", pa.string()),
        ("print_label_raw", pa.string()), ("colon_byte_offset_in_line", pa.int32()),
        ("notation_raw", pa.string()), ("notation_raw_bytes_hex", pa.string()),
        ("notation_state", pa.string()), ("canonical_point_code", pa.string()),
        ("api_field_nominal", pa.string()), ("mapping_status", pa.string()),
        ("source_capture_time_status", pa.string()), ("source_captured_at_utc", pa.string()),
        ("source_captured_at_ms", pa.int64()), ("source_capture_timestamp_basis", pa.string()),
        ("source_capture_manifest_path", pa.string()), ("source_capture_manifest_sha256", pa.string()),
        ("source_capture_manifest_match_count", pa.int16()), ("source_capture_manifest_line_no", pa.int32()),
        ("source_capture_run_id", pa.string()),
    ])
    source_schema = pa.schema([
        ("source_path", pa.string()), ("source_sha256", pa.string()), ("source_file_bytes", pa.int64()),
        ("source_path_meet_code", pa.int16()), ("path_year", pa.int16()),
        ("source_capture_time_status", pa.string()), ("source_captured_at_utc", pa.string()),
        ("source_captured_at_ms", pa.int64()), ("source_capture_timestamp_basis", pa.string()),
        ("source_capture_manifest_path", pa.string()), ("source_capture_manifest_sha256", pa.string()),
        ("source_capture_manifest_match_count", pa.int16()), ("source_capture_manifest_line_no", pa.int32()),
        ("source_capture_run_id", pa.string()), ("source_capture_manifest_entries_json", pa.string()),
        ("decoded_physical_line_count", pa.int32()), ("race_header_count", pa.int32()),
        ("point_line_count", pa.int32()), ("nonempty_point_line_count", pa.int32()),
        ("blank_or_placeholder_point_line_count", pa.int32()),
    ])
    snapshot_schema = pa.schema([
        ("actual_meet_code", pa.int16()), ("event_date", pa.string()), ("race_no", pa.int16()),
        ("canonical_point_code", pa.string()), ("rpt_observation_locator", pa.string()),
        ("rpt_print_label_raw", pa.string()), ("rpt_notation_raw", pa.string()),
        ("rpt_notation_compare_text", pa.string()), ("rpt_notation_state", pa.string()),
        ("snapshot_present", pa.bool_()), ("snapshot_notation_raw", pa.string()),
        ("snapshot_notation_compare_text", pa.string()), ("snapshot_source_batch_id", pa.int64()),
        ("raw_literal_equal", pa.bool_()), ("equal_after_outer_space_trim", pa.bool_()),
        ("comparison_status", pa.string()),
    ])
    return race_schema, point_schema, source_schema, snapshot_schema


def point_maps() -> dict[int, dict[str, tuple[str, str]]]:
    # The source print label is exact; it is not normalized or grammar-parsed.
    return {
        1: {
            "S-1F": ("S1F", "corner_7"),
            "C1": ("1C", "corner_1"), "C2": ("2C", "corner_2"),
            "C3": ("3C", "corner_3"), "C4": ("4C", "corner_4"),
            "G-1F": ("G1F", "corner_8"),
        },
        3: {
            "S1F": ("S1F", "corner_7"), "G8F": ("G8F", "corner_1"),
            "G6F": ("G6F", "corner_2"), "G4F": ("G4F", "corner_3"),
            "G3F": ("G3F", "corner_5"), "G2F": ("G2F", "corner_8"),
            "G1F": ("G1F", "corner_9"),
        },
        4: {
            "S1F": ("S1F", "corner_7"), "G8F": ("G8F", "corner_1"),
            "G6F": ("G6F", "corner_2"), "G4F": ("G4F", "corner_3"),
            "G3F": ("G3F", "corner_5"), "G2F": ("G2F", "corner_8"),
            "G1F": ("G1F", "corner_9"),
        },
    }


def write_point_mapping(mapping: dict[int, dict[str, tuple[str, str]]]) -> tuple[str, str, int]:
    fields = ["actual_meet_code", "actual_venue_label_raw", "print_label_raw", "canonical_point_code",
              "api_field_nominal", "rpt_label_mapping_status", "mapping_basis"]
    venue_names = {1: "서울", 3: "부산/부산경남", 4: "영천"}
    rows = []
    for meet, labels in sorted(mapping.items()):
        for label, (point, api_field) in labels.items():
            rows.append({
                "actual_meet_code": meet, "actual_venue_label_raw": venue_names[meet],
                "print_label_raw": label, "canonical_point_code": point,
                "api_field_nominal": api_field,
                "rpt_label_mapping_status": "exact_observed_print_label_mapping",
                "mapping_basis": "Exact print label and venue from Dacom11 RPT; official API point correspondence from PASSING_RANK_GROUP_HANDOFF_2026-09-26 section 3",
            })
    path = OUT / "rpt_point_mapping.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path.name, sha256_file(path), len(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    inventory_hash = sha256_file(INVENTORY_JSON_PATH)
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    inventory_summary_hash = sha256_file(INVENTORY_JSON_PATH)
    expected_inventory_hash = summary.get("source_pins", {}).get("passing_inventory.json")
    if expected_inventory_hash and inventory_summary_hash != expected_inventory_hash:
        raise RuntimeError("Pinned passing_inventory.json hash mismatch")
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    evidence_rows = json.loads((PRECHECK / "passing_rpt_file_evidence.json").read_text(encoding="utf-8"))
    mapping = point_maps()
    capture_index, capture_manifest_hash, capture_manifest_row_count, capture_manifest_downloaded_count = read_capture_manifest()

    race_schema, point_schema, source_schema, snapshot_schema = make_schemas()
    races: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    header_mismatches: list[dict[str, Any]] = []
    observed_labels: dict[int, Counter[str]] = defaultdict(Counter)
    bridges: Counter[tuple[int, int, str]] = Counter()
    expected_evidence = {row["path"]: row for row in evidence_rows}
    files_seen: set[str] = set()
    total_out_of_scope_points = 0

    title_re = re.compile(HEADER_RE)
    for rel in sorted(expected_evidence):
        if rel in files_seen:
            raise RuntimeError(f"Duplicate source path in pinned file evidence: {rel}")
        files_seen.add(rel)
        path = (ROOT / rel).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"Pinned RPT path escapes repository root: {rel}")
        if not path.is_file():
            raise FileNotFoundError(path)
        meta = re.search(r"/meet=(\d+)/year=(\d+)/", "/" + rel)
        if not meta:
            raise RuntimeError(f"Cannot parse source meet/year from path: {rel}")
        path_meet, path_year = int(meta.group(1)), int(meta.group(2))
        if path_meet not in (1, 3, 4) or not 2010 <= path_year <= 2026:
            raise RuntimeError(f"Unexpected source path scope: {rel}")
        raw_file = path.read_bytes()
        file_hash = sha256_bytes(raw_file)
        expected = expected_evidence[rel]
        if file_hash != expected["sha256"]:
            raise RuntimeError(f"Pinned source hash mismatch: {rel}")
        file_size = len(raw_file)
        current_race: dict[str, Any] | None = None
        pending_title: tuple[int, int, int, int, int, str, str] | None = None
        file_header_count = 0
        file_point_count = 0
        file_nonempty = 0
        file_blank_or_placeholder = 0
        byte_offset = 0
        physical_line_count = 0

        for line_no, physical_line in enumerate(raw_file.splitlines(keepends=True), 1):
            physical_line_count += 1
            body_bytes, eol_bytes, eol_name = line_parts(physical_line)
            try:
                line = body_bytes.decode("cp949", errors="strict")
            except UnicodeDecodeError as exc:
                parse_errors.append({"source_path": rel, "line_no": line_no, "error": str(exc)})
                raise RuntimeError(f"CP949 decode error: {rel}:{line_no}") from exc
            line_hex = physical_line.hex()

            if line.startswith("제목") and "경주" in line:
                header_match = title_re.search(line)
                if not header_match:
                    parse_errors.append({"source_path": rel, "line_no": line_no, "raw_line": line,
                                         "error": "unparsed_title_header"})
                    pending_title = None
                    current_race = None
                else:
                    yy, month, day, race_no = map(int, header_match.groups())
                    year = yy + 2000 if yy < 100 else yy
                    date = f"{year:04d}-{month:02d}-{day:02d}"
                    if date[:4] != str(path_year):
                        header_mismatches.append({"source_path": rel, "line_no": line_no,
                                                  "header_date": date, "path_year": path_year})
                    pending_title = (line_no, byte_offset, year, month, day, date, race_no, line, line_hex)
                    current_race = None

            venue_match = VENUE_RE.match(line)
            if venue_match and pending_title:
                venue_raw = venue_match.group(1)
                actual_meet = VENUE_TO_MEET.get(venue_raw)
                if actual_meet is None:
                    parse_errors.append({"source_path": rel, "line_no": line_no,
                                         "error": "unknown_venue", "venue_raw": venue_raw})
                    current_race = None
                else:
                    title_no, title_offset, year, month, day, date, race_no, title_raw, title_hex = pending_title
                    if not START_DATE <= date <= END_DATE:
                        total_out_of_scope_points += 0
                        current_race = None
                    else:
                        venue_bridge_status = (
                            "header_venue_matches_path_meet" if actual_meet == path_meet
                            else "explicit_header_venue_bridge" if (path_meet, actual_meet) == (3, 4)
                            else "unexpected_path_venue_mismatch"
                        )
                        if venue_bridge_status == "unexpected_path_venue_mismatch":
                            parse_errors.append({"source_path": rel, "line_no": line_no,
                                                 "error": "unexpected_path_venue_mismatch",
                                                 "source_path_meet_code": path_meet,
                                                 "actual_meet_code": actual_meet,
                                                 "venue_raw": venue_raw})
                        race_locator = stable_hash(rel, file_hash, "race_header", title_no, date, race_no)
                        current_race = {
                            "race_locator": race_locator, "source_path": rel, "source_sha256": file_hash,
                            "source_file_bytes": file_size, "source_path_meet_code": path_meet,
                            "actual_meet_code": actual_meet, "actual_venue_label_raw": venue_raw,
                            "venue_bridge_status": venue_bridge_status, "event_date": date,
                            "event_year": year, "race_no": race_no, "title_line_no": title_no,
                            "title_byte_offset": title_offset, "title_line_raw": title_raw,
                            "title_line_bytes_hex": title_hex, "venue_line_no": line_no,
                            "venue_byte_offset": byte_offset, "venue_line_raw": line,
                            "venue_line_bytes_hex": line_hex,
                            **capture_metadata(rel, file_hash, capture_index, capture_manifest_hash),
                        }
                        races.append(current_race)
                        file_header_count += 1
                        bridges[(path_meet, actual_meet, venue_raw)] += 1
                pending_title = None

            point_match = POINT_RE.match(line)
            if point_match:
                if current_race is None:
                    # Keep a parse audit instead of silently attaching a line to a prior race.
                    parse_errors.append({"source_path": rel, "line_no": line_no,
                                         "error": "point_line_without_in_scope_race_header",
                                         "raw_line": line})
                else:
                    label = point_match.group("label")
                    colon_byte_offset = body_bytes.find(b":")
                    if colon_byte_offset < 0:
                        raise RuntimeError(f"Point label regex matched without colon: {rel}:{line_no}")
                    notation_bytes = body_bytes[colon_byte_offset + 1:]
                    notation_raw = notation_bytes.decode("cp949", errors="strict")
                    compare_text = notation_raw.strip(" ")
                    if compare_text == "":
                        notation_state = "blank"
                    elif compare_text == "-":
                        notation_state = "placeholder_minus"
                    elif compare_text == "X":
                        notation_state = "placeholder_X"
                    else:
                        notation_state = "nonempty_literal"
                    actual_meet = current_race["actual_meet_code"]
                    map_entry = mapping.get(actual_meet, {}).get(label)
                    if map_entry:
                        canonical_point, api_field = map_entry
                        mapping_status = "exact_observed_print_label_mapping"
                    else:
                        canonical_point, api_field = None, None
                        mapping_status = "unmapped_print_label_hold"
                    point = {
                        "observation_locator": stable_hash(rel, file_hash, "rpt_print_line", line_no, physical_line),
                        "race_locator": current_race["race_locator"], "source_path": rel,
                        "source_sha256": file_hash, "source_file_bytes": file_size,
                        "source_path_meet_code": path_meet, "actual_meet_code": actual_meet,
                        "actual_venue_label_raw": current_race["actual_venue_label_raw"],
                        "venue_bridge_status": current_race["venue_bridge_status"],
                        "event_date": current_race["event_date"], "event_year": current_race["event_year"],
                        "race_no": current_race["race_no"], "source_line_no": line_no,
                        "source_line_byte_offset": byte_offset, "source_line_byte_length": len(physical_line),
                        "source_line_ending": eol_name, "raw_line_text": line,
                        "raw_line_bytes_hex": line_hex, "print_label_raw": label,
                        "colon_byte_offset_in_line": colon_byte_offset, "notation_raw": notation_raw,
                        "notation_raw_bytes_hex": notation_bytes.hex(), "notation_state": notation_state,
                        "canonical_point_code": canonical_point, "api_field_nominal": api_field,
                        "mapping_status": mapping_status,
                        **capture_metadata(rel, file_hash, capture_index, capture_manifest_hash),
                    }
                    points.append(point)
                    file_point_count += 1
                    observed_labels[actual_meet][label] += 1
                    if notation_state == "nonempty_literal":
                        file_nonempty += 1
                    else:
                        file_blank_or_placeholder += 1
            byte_offset += len(physical_line)

        file_capture = capture_metadata(rel, file_hash, capture_index, capture_manifest_hash)
        source_files.append({
            "source_path": rel, "source_sha256": file_hash, "source_file_bytes": file_size,
            "source_path_meet_code": path_meet, "path_year": path_year,
            **file_capture,
            "source_capture_manifest_entries_json": json.dumps(
                capture_index.get((rel, file_hash), []), ensure_ascii=False, sort_keys=True),
            "decoded_physical_line_count": physical_line_count, "race_header_count": file_header_count,
            "point_line_count": file_point_count, "nonempty_point_line_count": file_nonempty,
            "blank_or_placeholder_point_line_count": file_blank_or_placeholder,
        })
        if file_point_count != int(expected.get("nonempty_point_lines", -1)) + 0:
            # Precheck's count is non-empty valid notation only. Check below against recomputed non-empty.
            if file_nonempty != int(expected.get("nonempty_point_lines", -1)):
                raise RuntimeError(f"Per-file non-empty point count mismatch: {rel}")
        if file_nonempty != int(expected.get("nonempty_point_lines", -1)):
            raise RuntimeError(f"Per-file non-empty point count mismatch: {rel}")

    if parse_errors:
        raise RuntimeError(f"RPT parsing had {len(parse_errors)} errors; first={parse_errors[0]}")
    if header_mismatches:
        raise RuntimeError(f"RPT header/path year mismatch: {header_mismatches[:3]}")
    if len(files_seen) != len(evidence_rows):
        raise RuntimeError("Not every pinned RPT file was processed")

    capture_statuses = Counter(row["source_capture_time_status"] for row in source_files)
    if capture_statuses != Counter({"exact_local_path_and_sha256_capture_match": 1826,
                                    "no_exact_local_path_and_sha256_capture_match": 1}):
        raise RuntimeError(f"Unexpected exact capture-manifest join coverage: {capture_statuses}")

    # Only exact observed labels are included in the crosswalk; any new label is held.
    for actual_meet, labels in observed_labels.items():
        unknown = set(labels) - set(mapping.get(actual_meet, {}))
        if unknown:
            raise RuntimeError(f"Unmapped observed RPT labels for meet {actual_meet}: {sorted(unknown)}")
    if len(races) != 17371 or len(points) != 111467:
        raise RuntimeError(f"Unexpected extraction counts races={len(races)} points={len(points)}")
    nonempty_count = sum(row["notation_state"] == "nonempty_literal" for row in points)
    placeholder_count = len(points) - nonempty_count
    if nonempty_count != 83390 or placeholder_count != 28077:
        raise RuntimeError(f"Unexpected group states nonempty={nonempty_count} placeholders={placeholder_count}")

    output_files = [
        write_parquet("rpt_race_headers.parquet", races, race_schema),
        write_parquet("rpt_point_observations.parquet", points, point_schema),
        write_parquet("rpt_source_files.parquet", source_files, source_schema),
    ]
    mapping_csv_name, mapping_csv_hash, mapping_row_count = write_point_mapping(mapping)
    output_files.append({"path": mapping_csv_name, "sha256": mapping_csv_hash,
                         "bytes": (OUT / mapping_csv_name).stat().st_size, "row_count": mapping_row_count})

    # Compare the independent root parse, one-to-one by source coordinates.
    expected_table = pq.read_table(EXPECTED_RPT_PATH)
    expected_rows = expected_table.to_pylist()
    ours_by_key = {(r["source_path"], r["source_sha256"], r["source_line_no"], r["source_line_byte_offset"]): r
                   for r in points}
    if len(ours_by_key) != len(points):
        raise RuntimeError("Duplicate source locator among extracted RPT point lines")
    expected_by_key = {(r["source_path"], r["source_sha256"], int(r["line_no"]), int(r["byte_offset"])): r
                       for r in expected_rows}
    if len(expected_by_key) != len(expected_rows):
        raise RuntimeError("Duplicate source locator in independent root parse")
    field_mismatches: Counter[str] = Counter()
    missing_in_ours = 0
    missing_in_root = 0
    for key in set(ours_by_key) | set(expected_by_key):
        ours = ours_by_key.get(key)
        expected = expected_by_key.get(key)
        if ours is None:
            missing_in_ours += 1
            continue
        if expected is None:
            missing_in_root += 1
            continue
        pairs = {
            "actual_meet_code": (ours["actual_meet_code"], int(expected["actual_meet_code"])),
            "event_date": (ours["event_date"], expected["race_date_iso"]),
            "race_no": (ours["race_no"], int(expected["race_no"])),
            "print_label_raw": (ours["print_label_raw"], expected["point_label_raw"]),
            "notation_compare_text": (ours["notation_raw"].strip(" "), expected["notation_trim"]),
            "raw_line_text": (ours["raw_line_text"], expected["raw_line"]),
        }
        for name, (left, right) in pairs.items():
            if left != right:
                field_mismatches[name] += 1
    root_parity = {
        "independent_root_artifact": "thoroughbred/research/20261002_passing_groups_v1/root_expected_rpt_points.parquet",
        "independent_root_artifact_sha256": sha256_file(EXPECTED_RPT_PATH),
        "our_point_rows": len(points), "root_point_rows": len(expected_rows),
        "missing_from_our_extraction": missing_in_ours, "missing_from_root_parse": missing_in_root,
        "field_mismatch_counts": dict(field_mismatches),
        "all_source_coordinate_rows_match": not missing_in_ours and not missing_in_root and not field_mismatches,
    }
    parity_path = OUT / "root_independent_parse_parity.json"
    parity_path.write_text(json.dumps(root_parity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_files.append({"path": parity_path.name, "sha256": sha256_file(parity_path),
                         "bytes": parity_path.stat().st_size, "row_count": None})
    if not root_parity["all_source_coordinate_rows_match"]:
        raise RuntimeError(f"Independent parse parity failed: {root_parity}")

    # Read only the explicitly designated research snapshot; no core/operating DB is opened.
    snapshot_hash_before = sha256_file(SNAPSHOT_DB)
    snapshot_conn = duckdb.connect(str(SNAPSHOT_DB), read_only=True)
    snapshot_rows = snapshot_conn.execute(
        """SELECT c.meet_code, c.race_date, c.race_number, p.point_code,
                  p.notation_raw, p.source_batch_id
             FROM op_race_passing_groups AS p
             JOIN op_race_context AS c USING (race_id)
            WHERE c.meet_code IN (1, 3, 4)
              AND c.race_date >= ? AND c.race_date <= ?
            ORDER BY c.meet_code, c.race_date, c.race_number, p.point_code""",
        [START_DATE, END_DATE],
    ).fetchall()
    snapshot_conn.close()
    snapshot_hash_after = sha256_file(SNAPSHOT_DB)
    if snapshot_hash_after != snapshot_hash_before:
        raise RuntimeError("Research snapshot file hash changed during read-only access")
    snapshot_by_key: dict[tuple[int, str, int, str], tuple[str | None, int | None]] = {}
    snapshot_duplicate_keys = 0
    for meet, date, race_no, point_code, notation, batch_id in snapshot_rows:
        key = (int(meet), str(date), int(race_no), str(point_code))
        if key in snapshot_by_key:
            snapshot_duplicate_keys += 1
        else:
            snapshot_by_key[key] = (notation, int(batch_id) if batch_id is not None else None)
    if snapshot_duplicate_keys:
        raise RuntimeError(f"Research snapshot has duplicate race-point keys: {snapshot_duplicate_keys}")

    rpt_by_key: dict[tuple[int, str, int, str], dict[str, Any]] = {}
    for point in points:
        key = (int(point["actual_meet_code"]), point["event_date"], int(point["race_no"]),
               str(point["canonical_point_code"]))
        if key in rpt_by_key:
            raise RuntimeError(f"RPT has duplicate race-point label: {key}")
        rpt_by_key[key] = point
    comparison_rows = []
    for key in sorted(set(rpt_by_key) | set(snapshot_by_key)):
        rpt = rpt_by_key.get(key)
        snap = snapshot_by_key.get(key)
        rpt_raw = rpt["notation_raw"] if rpt else None
        snap_raw = snap[0] if snap else None
        rpt_cmp = rpt_raw.strip(" ") if rpt_raw is not None else None
        snap_cmp = snap_raw.strip(" ") if snap_raw is not None else None
        rpt_state = rpt["notation_state"] if rpt else "no_rpt_print_label"
        raw_equal = bool(rpt_raw is not None and snap_raw is not None and rpt_raw == snap_raw)
        trimmed_equal = bool(rpt_cmp is not None and snap_cmp is not None and rpt_cmp == snap_cmp)
        if rpt is None:
            status = "snapshot_only_no_rpt_print_label"
        elif rpt_state != "nonempty_literal":
            status = "rpt_blank_or_placeholder_snapshot_has_value" if snap is not None else "rpt_blank_or_placeholder_snapshot_absent"
        elif snap is None:
            status = "rpt_nonempty_snapshot_absent"
        elif trimmed_equal:
            status = "rpt_snapshot_raw_exact" if raw_equal else "rpt_snapshot_equal_after_outer_space_trim"
        else:
            status = "rpt_snapshot_nonempty_conflict"
        comparison_rows.append({
            "actual_meet_code": key[0], "event_date": key[1], "race_no": key[2],
            "canonical_point_code": key[3],
            "rpt_observation_locator": rpt["observation_locator"] if rpt else None,
            "rpt_print_label_raw": rpt["print_label_raw"] if rpt else None,
            "rpt_notation_raw": rpt_raw, "rpt_notation_compare_text": rpt_cmp,
            "rpt_notation_state": rpt_state, "snapshot_present": snap is not None,
            "snapshot_notation_raw": snap_raw, "snapshot_notation_compare_text": snap_cmp,
            "snapshot_source_batch_id": snap[1] if snap else None,
            "raw_literal_equal": raw_equal, "equal_after_outer_space_trim": trimmed_equal,
            "comparison_status": status,
        })
    output_files.append(write_parquet("rpt_snapshot_comparison.parquet", comparison_rows, snapshot_schema))

    status_counts = dict(Counter(row["comparison_status"] for row in comparison_rows))
    summary_counts = {
        "source_file_count": len(source_files), "race_header_count": len(races),
        "point_line_count": len(points), "nonempty_point_line_count": nonempty_count,
        "blank_or_placeholder_point_line_count": placeholder_count,
        "distinct_rpt_race_point_keys": len(rpt_by_key), "snapshot_scope_row_count": len(snapshot_rows),
        "snapshot_duplicate_race_point_keys": snapshot_duplicate_keys,
        "snapshot_union_comparison_key_count": len(comparison_rows),
        "snapshot_comparison_status_counts": status_counts,
        "actual_venue_bridges": [
            {"source_path_meet_code": p, "actual_meet_code": m, "venue_raw": v, "race_count": count}
            for (p, m, v), count in sorted(bridges.items())
        ],
        "rpt_labels_by_actual_meet": {str(meet): dict(sorted(counter.items()))
                                      for meet, counter in sorted(observed_labels.items())},
        "source_capture_manifest_row_count": capture_manifest_row_count,
        "source_capture_manifest_downloaded_row_count": capture_manifest_downloaded_count,
        "source_capture_matched_file_count": capture_statuses["exact_local_path_and_sha256_capture_match"],
        "source_capture_unmatched_files": [row["source_path"] for row in source_files
                                           if row["source_capture_time_status"] == "no_exact_local_path_and_sha256_capture_match"],
        "snapshot_db_sha256": snapshot_hash_before,
    }
    manifest = {
        "package": "thoroughbred/research/20261002_passing_groups_v1/rpt_mapping",
        "scope": {"start_date": START_DATE, "end_date": END_DATE,
                  "actual_meets": {"1": "Seoul", "3": "Busan-Gyeongnam", "4": "Yeongcheon"},
                  "Jeju_excluded": True},
        "source_read_contract": {
            "rpt_source": "CP949 local Dacom11 RPT files listed in passing_rpt_file_evidence.json; bytes read only",
            "path_meet_is_not_actual_meet": "actual meet is bridged only from the RPT header venue label; source path meet code is separately retained",
            "capture_timestamp": "retrieved_at_ms from data/raw/kra_text/_manifests/dacom11/manifest.jsonl only when both local_path and sha256 match exactly; all others null; filesystem mtime is not used",
            "notation_handling": "entire text after the label colon is preserved including padding; no notation grammar is parsed",
            "comparison_only_normalization": "ASCII outer spaces are trimmed only in separate comparison fields; raw line, notation, and source bytes remain unchanged",
            "snapshot": "section_passing_raw_2010plus_20260929_v1/section_passing_raw.duckdb opened read_only=True; file SHA-256 checked unchanged before/after",
            "operating_database": "not opened or modified",
            "network": "not used",
        },
        "precheck_inputs": {
            "passing_rpt_file_evidence_sha256": sha256_file(INVENTORY_PATH),
            "passing_inventory_sha256": inventory_hash,
            "passing_inventory_expected_pinned_sha256": expected_inventory_hash,
            "precheck_summary_sha256": sha256_file(SUMMARY_PATH),
            "independent_root_rpt_parse_sha256": sha256_file(EXPECTED_RPT_PATH),
            "dacom11_capture_manifest_path": CAPTURE_MANIFEST.relative_to(ROOT).as_posix(),
            "dacom11_capture_manifest_sha256": capture_manifest_hash,
            "dacom11_capture_manifest_row_count": capture_manifest_row_count,
            "dacom11_capture_manifest_downloaded_row_count": capture_manifest_downloaded_count,
        },
        "builder_sha256": sha256_file(Path(__file__)),
        "counts": summary_counts,
        "root_independent_parse_parity": root_parity,
        "outputs": output_files,
    }
    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = """# Dacom11 passing-group extraction and comparison\n\nThis package preserves the original Dacom11 passing-group print lines for Seoul, Busan-Gyeongnam, and Yeongcheon from 2010-01-01 through 2026-09-29. Jeju is excluded. Source RPT files are decoded as CP949 and never modified.\n\n`rpt_point_observations.parquet` contains every observed passing-group print line, including blank and placeholder rows. `raw_line_bytes_hex` includes the physical line ending; `notation_raw` and `notation_raw_bytes_hex` preserve everything after the colon, including source padding. No group grammar is parsed. A separate comparison field trims only outer ASCII spaces. Source download time is populated only when `local_path + sha256` exactly matches `data/raw/kra_text/_manifests/dacom11/manifest.jsonl`; unmatched files remain null, and filesystem mtime is not used.\n\n`rpt_point_mapping.csv` maps exact labels by actual header venue. The path meet code is retained because it can differ from the actual venue: path meet 3 on 2026-09-13 contains six Yeongcheon races (actual meet 4).\n\n`rpt_snapshot_comparison.parquet` is a read-only comparison with the named research snapshot, not a replacement instruction. Both values remain available for every key. Conflicts, absent rows, and placeholder rows are explicit. The old snapshot is opened read-only and its file SHA-256 is checked unchanged.\n\n`root_independent_parse_parity.json` records exact source-coordinate parity against the independently created root parse. `manifest.json` pins all generated output hashes, source file hashes/counts, scope, and safety boundaries.\n"""
    readme_path = OUT / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    manifest["outputs"].append({"path": readme_path.name, "sha256": sha256_file(readme_path),
                                "bytes": readme_path.stat().st_size, "row_count": None})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary_counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
