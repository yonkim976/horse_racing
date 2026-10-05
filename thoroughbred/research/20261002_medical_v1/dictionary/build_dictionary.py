"""Build the frozen medical terminology and explanation dictionary snapshot."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
API33 = ROOT / "data/research/kra_disease_glossary_api33_20260930"
WEB = ROOT / "data/research/kra_disease_glossary_20260930"
PROFILE = API33 / "profile_hover_expansion_20261001"
PROFILE_OLD = API33 / "profile_hover_review_20260930/profile_hover_observations.csv"
PHRASE_RECHECK = API33 / "final_review_20260930/phrase_recheck_20261001"
REVIEW_CSV = PROFILE / "full_term_review_20261001.csv"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exact_text_hash(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def tuple_hash(values: list[str | None]) -> str:
    digest = hashlib.sha256()
    for value in values:
        if value is None:
            encoded = b"\xff"
        else:
            encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def portable_source_record(value: Any) -> Any:
    """Remove snapshot-local identifiers and old usage counters from copied evidence rows."""
    if isinstance(value, dict):
        return {
            key: portable_source_record(item)
            for key, item in value.items()
            if key not in {"term_id", "use_count"}
        }
    if isinstance(value, list):
        return [portable_source_record(item) for item in value]
    return value


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pa_schema(fields: list[tuple[str, str]]) -> pa.Schema:
    types = {
        "str": pa.string(),
        "i32": pa.int32(),
        "i64": pa.int64(),
        "bool": pa.bool_(),
    }
    return pa.schema([(name, types[kind]) for name, kind in fields])


def write_parquet(filename: str, rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> None:
    table = pa.Table.from_pylist(rows, schema=pa_schema(fields))
    pq.write_table(table, OUT / filename, compression="zstd", version="2.6")


def input_inventory(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        result[path.relative_to(ROOT).as_posix()] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return result


def verify_api33_xml(
    raw_entries: list[dict[str, str]], source_manifest: dict[str, Any], json_path: Path
):
    page_rows: list[tuple[int, int, dict[str, str], Path, str]] = []
    page_checks: list[dict[str, Any]] = []
    source_json_hash = sha256_file(json_path)
    cursor = 0
    for page in source_manifest["pages"]:
        xml_path = API33 / page["raw_file"]
        xml_hash = sha256_file(xml_path)
        if xml_hash != page["sha256"]:
            raise ValueError(f"API33 source XML hash mismatch: {page['raw_file']}")
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
            recover=False,
        )
        root = etree.fromstring(xml_path.read_bytes(), parser=parser)
        result_code = root.findtext("./header/resultCode")
        if result_code != "00":
            raise ValueError(
                f"API33 page result code mismatch: page={page['page_no']} code={result_code}"
            )
        xml_items = root.findall("./body/items/item")
        expected_count = int(page["item_count"])
        if len(xml_items) != expected_count:
            raise ValueError(f"API33 XML page item count mismatch: page={page['page_no']}")
        json_page = raw_entries[cursor : cursor + expected_count]
        if len(json_page) != expected_count:
            raise ValueError(f"API33 JSON page slice mismatch: page={page['page_no']}")
        for index, (xml_item, json_item) in enumerate(zip(xml_items, json_page, strict=True), 1):
            xml_record: dict[str, str] = {}
            for field in ("illName", "illEngName", "illDesc"):
                node = xml_item.find(field)
                # The API serializer omits blank values in some XML rows while JSON
                # represents the same field as an empty string.
                xml_record[field] = "" if node is None or node.text is None else node.text
            if xml_record != json_item:
                raise ValueError(f"API33 XML/JSON row mismatch: page={page['page_no']} row={index}")
            row_id = cursor + index
            page_rows.append((row_id, index, json_item, xml_path, xml_hash))
        page_checks.append(
            {
                "page_no": int(page["page_no"]),
                "source_xml_path": page["raw_file"],
                "source_xml_sha256": xml_hash,
                "manifest_item_count": expected_count,
                "xml_item_count": len(xml_items),
                "json_page_item_count": len(json_page),
                "xml_json_rows_equal_in_order": True,
            }
        )
        cursor += expected_count
    if cursor != len(raw_entries) or cursor != int(source_manifest["reported_total_count"]):
        raise ValueError("API33 manifest/page/JSON item totals do not agree")
    return page_rows, source_json_hash, page_checks


def build_api33() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    json_path = API33 / "api33_glossary.json"
    raw = read_json(json_path)
    source_manifest = read_json(API33 / "manifest.json")
    entries = raw["entries"]
    if len(entries) != 3523:
        raise ValueError(f"Unexpected API33 source row count: {len(entries)}")
    if int(raw["total_count_reported"]) != int(source_manifest["reported_total_count"]):
        raise ValueError("API33 JSON and source manifest totalCount differ")
    _xml_page_rows, json_sha, page_checks = verify_api33_xml(entries, source_manifest, json_path)
    # Keep explicit source row ordinals and their page coordinates.
    source_rows: list[dict[str, Any]] = []
    cursor = 0
    for page in source_manifest["pages"]:
        count = int(page["item_count"])
        xml_path = API33 / page["raw_file"]
        xml_hash = sha256_file(xml_path)
        for page_row_no, entry in enumerate(entries[cursor : cursor + count], 1):
            row_id = cursor + page_row_no
            source_rows.append(
                {
                    "source_row_id": row_id,
                    "page_no": int(page["page_no"]),
                    "page_row_no": page_row_no,
                    "ill_name": entry["illName"],
                    "ill_eng_name": entry["illEngName"],
                    "ill_desc": entry["illDesc"],
                    "source_url": raw["source_url"],
                    "fetched_at_kst": raw["fetched_at_kst"],
                    "source_json_path": json_path.relative_to(ROOT).as_posix(),
                    "source_json_sha256": json_sha,
                    "source_xml_path": xml_path.relative_to(ROOT).as_posix(),
                    "source_xml_sha256": xml_hash,
                    "source_record_sha256": tuple_hash(
                        [entry["illName"], entry["illEngName"], entry["illDesc"]]
                    ),
                    "source_record_json": canonical_json(entry),
                }
            )
        cursor += count

    ordered_exact: OrderedDict[tuple[str, str, str], list[int]] = OrderedDict()
    for row in source_rows:
        key = (row["ill_name"], row["ill_eng_name"], row["ill_desc"])
        ordered_exact.setdefault(key, []).append(row["source_row_id"])
    dedup_doc = read_json(API33 / "api33_glossary_deduplicated_exact.json")
    dedup_entries = dedup_doc["entries"]
    derived_rows: list[dict[str, Any]] = []
    for key, row_ids in ordered_exact.items():
        derived_rows.append(
            {
                "api33_tuple_sha256": tuple_hash(list(key)),
                "ill_name": key[0],
                "ill_eng_name": key[1],
                "ill_desc": key[2],
                "first_source_row_id": row_ids[0],
                "source_row_ids_json": canonical_json(row_ids),
                "source_duplicate_count": len(row_ids),
                "deduplication_rule": "exact_ill_name_ill_eng_name_ill_desc_tuple",
            }
        )
    expected_dedup = [
        (row["ill_name"], row["ill_eng_name"], row["ill_desc"]) for row in derived_rows
    ]
    if len(dedup_entries) != len(derived_rows):
        raise ValueError("API33 derived term count differs from exact-tuple source calculation")
    if [(x["illName"], x["illEngName"], x["illDesc"]) for x in dedup_entries] != expected_dedup:
        raise ValueError(
            "API33 existing deduplication artifact differs from exact-tuple derivation"
        )
    if len({x["ill_name"] for x in derived_rows}) != 3500:
        raise ValueError("Unexpected API33 unique Korean title count")
    if any(x["ill_desc"] != "-" for x in source_rows):
        raise ValueError("API33 source contains a non-dash description; review before publishing")
    write_parquet(
        "api33_source_rows.parquet",
        source_rows,
        [
            ("source_row_id", "i32"),
            ("page_no", "i32"),
            ("page_row_no", "i32"),
            ("ill_name", "str"),
            ("ill_eng_name", "str"),
            ("ill_desc", "str"),
            ("source_url", "str"),
            ("fetched_at_kst", "str"),
            ("source_json_path", "str"),
            ("source_json_sha256", "str"),
            ("source_xml_path", "str"),
            ("source_xml_sha256", "str"),
            ("source_record_sha256", "str"),
            ("source_record_json", "str"),
        ],
    )
    write_parquet(
        "api33_terms.parquet",
        derived_rows,
        [
            ("api33_tuple_sha256", "str"),
            ("ill_name", "str"),
            ("ill_eng_name", "str"),
            ("ill_desc", "str"),
            ("first_source_row_id", "i32"),
            ("source_row_ids_json", "str"),
            ("source_duplicate_count", "i32"),
            ("deduplication_rule", "str"),
        ],
    )
    metrics = {
        "source_row_count": len(source_rows),
        "exact_tuple_count": len(derived_rows),
        "unique_korean_title_count": len({x["ill_name"] for x in derived_rows}),
        "source_duplicate_excess_count": len(source_rows) - len(derived_rows),
        "all_ill_desc_are_dash": True,
        "xml_json_page_row_parity": True,
        "xml_page_count": len(source_manifest["pages"]),
        "xml_page_checks": page_checks,
    }
    return source_rows, derived_rows, metrics


def split_review_titles(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    # This is the saved review sheet's explicit display delimiter, not a phrase parser.
    return raw_value.split(" | ")


def build_phrase_tables() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = read_csv(REVIEW_CSV)
    if len(rows) != 5397:
        raise ValueError(f"Unexpected phrase review row count: {len(rows)}")
    decisions: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for row in rows:
        text = row["raw_text"]
        text_hash = exact_text_hash(text)
        if text_hash in seen_hashes:
            raise ValueError("Duplicate exact raw phrase in review CSV")
        seen_hashes.add(text_hash)
        decision = row["review_decision"]
        if decision.startswith("excluded_"):
            status = "excluded"
        elif decision.startswith("confirmed_"):
            status = "confirmed_review_mapping"
        else:
            status = "unresolved"
        mapped = split_review_titles(row["mapped_kra_titles"])
        if any(not title for title in mapped):
            raise ValueError(f"Empty target title in mapping list for {text!r}")
        note = row["evidence_note"]
        prefix_rule = decision == "confirmed_dacom72_title_after_prefix"
        contextual_required = (
            prefix_rule
            or decision
            in {
                "confirmed_profile_alias_after_source_check",
                "confirmed_user_kra_profile_replacement",
            }
            or any(
                token in note
                for token in (
                    "동일 날짜",
                    "동일 마필",
                    "같은 말·날짜",
                    "같은 날짜",
                    "KRA 화면에서 마필·날짜",
                )
            )
        )
        if prefix_rule:
            mapping_scope = "prior_rpt_parser_context_only"
        elif contextual_required:
            mapping_scope = "event_specific_reference_only"
        else:
            mapping_scope = "reviewed_phrase_candidate_only"
        decisions.append(
            {
                "raw_text_sha256": text_hash,
                "raw_text": text,
                "review_decision": decision,
                "review_status": status,
                "original_match_status": row["original_match_status"],
                "mapped_kra_titles_raw": row["mapped_kra_titles"],
                "reviewed_target_count": len(mapped),
                "description_status_in_review": row["description_status"],
                "description_sources_by_title_json": row["description_sources_by_title"],
                "evidence_note": note,
                "contextual_evidence_required": contextual_required,
                "mapping_rule_scope": mapping_scope,
                "prefix_rule_reusable": False if prefix_rule else None,
                "event_link_policy": "no_automatic_event_link_without_in_scope_evidence",
                "source_review_file": REVIEW_CSV.relative_to(ROOT).as_posix(),
                "source_review_sha256": sha256_file(REVIEW_CSV),
            }
        )
        for ordinal, title in enumerate(mapped, 1):
            components.append(
                {
                    "raw_text_sha256": text_hash,
                    "raw_text": text,
                    "reviewed_target_ordinal": ordinal,
                    "target_ill_name": title,
                    "target_order_semantics": "saved_review_target_list_order_only",
                    "review_decision": decision,
                    "review_status": status,
                    "contextual_evidence_required": contextual_required,
                    "mapping_rule_scope": mapping_scope,
                    "prefix_rule_reusable": False if prefix_rule else None,
                    "event_link_policy": "no_automatic_event_link_without_in_scope_evidence",
                    "evidence_note": note,
                    "source_review_file": REVIEW_CSV.relative_to(ROOT).as_posix(),
                    "source_review_sha256": sha256_file(REVIEW_CSV),
                }
            )
    exclusions = [row["raw_text"] for row in decisions if row["review_status"] == "excluded"]
    expected_exclusions = {
        "치료장제(기타)",
        "치료장제(백선열)",
        "치료장제(답  창)",
        "치료장제(제구염)",
        "치료장제(무  제)",
    }
    if len(exclusions) != 5 or set(exclusions) != expected_exclusions:
        raise ValueError(f"Unexpected exclusion set in review CSV: {exclusions}")
    if sum(row["review_status"] == "confirmed_review_mapping" for row in decisions) != 5392:
        raise ValueError("Expected 5,392 reviewed mappings and 5 exclusions")
    write_parquet(
        "phrase_decisions.parquet",
        decisions,
        [
            ("raw_text_sha256", "str"),
            ("raw_text", "str"),
            ("review_decision", "str"),
            ("review_status", "str"),
            ("original_match_status", "str"),
            ("mapped_kra_titles_raw", "str"),
            ("reviewed_target_count", "i32"),
            ("description_status_in_review", "str"),
            ("description_sources_by_title_json", "str"),
            ("evidence_note", "str"),
            ("contextual_evidence_required", "bool"),
            ("mapping_rule_scope", "str"),
            ("prefix_rule_reusable", "bool"),
            ("event_link_policy", "str"),
            ("source_review_file", "str"),
            ("source_review_sha256", "str"),
        ],
    )
    write_parquet(
        "phrase_components.parquet",
        components,
        [
            ("raw_text_sha256", "str"),
            ("raw_text", "str"),
            ("reviewed_target_ordinal", "i32"),
            ("target_ill_name", "str"),
            ("target_order_semantics", "str"),
            ("review_decision", "str"),
            ("review_status", "str"),
            ("contextual_evidence_required", "bool"),
            ("mapping_rule_scope", "str"),
            ("prefix_rule_reusable", "bool"),
            ("event_link_policy", "str"),
            ("evidence_note", "str"),
            ("source_review_file", "str"),
            ("source_review_sha256", "str"),
        ],
    )
    return (
        decisions,
        components,
        {
            "phrase_decision_count": len(decisions),
            "confirmed_mapping_count": sum(
                x["review_status"] == "confirmed_review_mapping" for x in decisions
            ),
            "excluded_count": len(exclusions),
            "excluded_raw_texts": sorted(exclusions),
            "component_link_row_count": len(components),
            "contextual_evidence_required_count": sum(
                x["contextual_evidence_required"] for x in decisions
            ),
            "prior_parser_prefix_rule_count": sum(
                x["review_decision"] == "confirmed_dacom72_title_after_prefix" for x in decisions
            ),
            "automatic_event_link_enabled": False,
        },
    )


def parse_hover_text(title: str, hover: str) -> tuple[str | None, str | None, str]:
    if not hover or not title or not hover.startswith(title):
        return None, None, "title_prefix_not_found_or_hover_text_empty"
    rest = hover[len(title) :].lstrip()
    if not rest.startswith("("):
        return None, rest or None, "english_delimited_segment_not_found"
    close = rest.find(")")
    if close < 0:
        return None, rest, "english_segment_unclosed"
    english = rest[1:close]
    description = rest[close + 1 :].lstrip()
    return english, description if description != "" else None, "parsed_from_saved_hover_text"


def build_explanation_observations() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    source_paths = [
        PROFILE_OLD,
        PHRASE_RECHECK / "kra_profile_observations.csv",
        PROFILE / "profile_hover_observations.csv",
        PROFILE / "profile_hover_observations_additional_20261001.csv",
        PROFILE / "source_manifest.json",
        WEB / "glossary.json",
        PHRASE_RECHECK / "user_provided_kra_term_details.json",
    ]
    hashes = input_inventory(source_paths)
    profile_manifest = read_json(PROFILE / "source_manifest.json")
    for basename, expected_hash in profile_manifest["observations_csv_sha256"].items():
        actual_hash = hashes[(PROFILE / basename).relative_to(ROOT).as_posix()]["sha256"]
        if actual_hash != expected_hash:
            raise ValueError(f"Profile source manifest hash mismatch: {basename}")

    def add_observation(
        *,
        source_kind: str,
        source_path: Path,
        source_row_ordinal: int,
        source_subrow_ordinal: int,
        source_title: str | None,
        source_english_name: str | None,
        description_text: str | None,
        raw_capture_text: str | None,
        source_url: str | None,
        collected_at_kst: str | None,
        source_meet: int | None,
        horse_name: str | None,
        horse_id: str | None,
        event_date_local: str | None,
        event_dates_json: str | None,
        hospital_name: str | None,
        observation_count: int | None,
        capture_status: str,
        parser_status: str,
        api33_title_exact_match: str | None,
        api33_english_exact_match: str | None,
        source_record: Any,
        source_publication_at_kst: str | None = None,
    ) -> None:
        relpath = source_path.relative_to(ROOT).as_posix()
        src_sha = hashes[relpath]["sha256"]
        portable_record = portable_source_record(source_record)
        row_hash = exact_text_hash(canonical_json(portable_record))
        desc_hash = exact_text_hash(description_text) if description_text is not None else None
        tuple_sha = tuple_hash([source_title, source_english_name, description_text])
        source_location = f"{relpath}#{source_row_ordinal}:{source_subrow_ordinal}"
        observation_id = tuple_hash([source_kind, source_location, row_hash, tuple_sha])
        if source_meet == 1:
            meet_name = "Seoul"
        elif source_meet == 2:
            meet_name = "Jeju"
        elif source_meet == 3:
            meet_name = "Busan-Gyeongnam"
        else:
            meet_name = None
        observations.append(
            {
                "explanation_observation_id": observation_id,
                "source_kind": source_kind,
                "source_title": source_title,
                "source_english_name": source_english_name,
                "description_text": description_text,
                "description_present": description_text is not None,
                "exact_explanation_tuple_sha256": tuple_sha,
                "description_text_sha256": desc_hash,
                "raw_capture_text": raw_capture_text,
                "source_url": source_url,
                "source_file": relpath,
                "source_file_sha256": src_sha,
                "source_row_ordinal": source_row_ordinal,
                "source_subrow_ordinal": source_subrow_ordinal,
                "source_row_sha256": row_hash,
                "source_record_json": canonical_json(portable_record),
                "collected_at_kst": collected_at_kst,
                "source_publication_at_kst": source_publication_at_kst,
                "source_meet": source_meet,
                "source_meet_name": meet_name,
                "horse_name": horse_name,
                "horse_id": horse_id,
                "event_date_local": event_date_local,
                "event_dates_json": event_dates_json,
                "hospital_name": hospital_name,
                "source_observation_count": observation_count,
                "capture_status": capture_status,
                "parser_status": parser_status,
                "api33_title_exact_match": api33_title_exact_match,
                "api33_english_exact_match": api33_english_exact_match,
            }
        )

    # Earlier profile observations: keep each source capture row and nested observation.
    for row_no, row in enumerate(read_csv(PROFILE_OLD), 1):
        entries = json.loads(row.get("kra_profile_entries_json") or "[]")
        capture_status = (
            "user_provided_profile_record"
            if "user" in row.get("status", "")
            else "captured_profile_record"
        )
        source_kind = (
            "user_provided_profile_detail"
            if capture_status.startswith("user_")
            else "kra_profile_hover"
        )
        for entry_no, entry in enumerate(entries, 1):
            title = entry.get("title")
            hover = entry.get("hover_text", "")
            english, description, parse_status = parse_hover_text(title or "", hover)
            add_observation(
                source_kind=source_kind,
                source_path=PROFILE_OLD,
                source_row_ordinal=row_no,
                source_subrow_ordinal=entry_no,
                source_title=title,
                source_english_name=english,
                description_text=description,
                raw_capture_text=hover,
                source_url=row.get("source_search_url"),
                collected_at_kst=row.get("collected_at_kst"),
                source_meet=int(row["meet"]) if row.get("meet") else None,
                horse_name=row.get("local_horse") or None,
                horse_id=row.get("kra_horse_id") or None,
                event_date_local=row.get("local_date") or None,
                event_dates_json=None,
                hospital_name=row.get("local_hospital") or None,
                observation_count=1,
                capture_status=capture_status,
                parser_status=parse_status,
                api33_title_exact_match=None,
                api33_english_exact_match=None,
                source_record={"parent_row": row, "profile_entry": entry},
            )

    # Later phrase recheck rows include three opened detail blocks and one title-only row.
    path = PHRASE_RECHECK / "kra_profile_observations.csv"
    for row_no, row in enumerate(read_csv(path), 1):
        entries = json.loads(row.get("kra_profile_entries_json") or "[]")
        for entry_no, entry in enumerate(entries, 1):
            title = entry.get("title")
            hover = entry.get("hover_text", "")
            english, description, parse_status = parse_hover_text(title or "", hover)
            add_observation(
                source_kind="kra_profile_row_recheck",
                source_path=path,
                source_row_ordinal=row_no,
                source_subrow_ordinal=entry_no,
                source_title=title,
                source_english_name=english,
                description_text=description,
                raw_capture_text=hover,
                source_url=row.get("source_search_url"),
                collected_at_kst=row.get("collected_at_kst"),
                source_meet=int(row["meet"]) if row.get("meet") else None,
                horse_name=row.get("local_horse") or None,
                horse_id=row.get("kra_horse_id") or None,
                event_date_local=row.get("local_date") or None,
                event_dates_json=None,
                hospital_name=row.get("local_hospital") or None,
                observation_count=1,
                capture_status=row.get("status") or "captured_profile_record",
                parser_status=parse_status,
                api33_title_exact_match=None,
                api33_english_exact_match=None,
                source_record={"parent_row": row, "profile_entry": entry},
            )

    # The 38 newer profile tuples are summary capture rows; retain their recorded count and dates.
    for path in [
        PROFILE / "profile_hover_observations.csv",
        PROFILE / "profile_hover_observations_additional_20261001.csv",
    ]:
        for row_no, row in enumerate(read_csv(path), 1):
            dates = row.get("example_dates_json") or None
            add_observation(
                source_kind="kra_profile_hover_tuple_capture",
                source_path=path,
                source_row_ordinal=row_no,
                source_subrow_ordinal=1,
                source_title=row.get("ill_name"),
                source_english_name=row.get("ill_eng_name"),
                description_text=row.get("ill_desc"),
                raw_capture_text=row.get("ill_desc"),
                source_url=row.get("source_profile_url") or row.get("source_search_url"),
                collected_at_kst=row.get("collected_at_kst"),
                source_meet=int(row["meet"]) if row.get("meet") else None,
                horse_name=row.get("example_horse_name") or None,
                horse_id=row.get("kra_horse_number") or None,
                event_date_local=None,
                event_dates_json=dates,
                hospital_name=row.get("representative_hospital") or None,
                observation_count=int(row["profile_row_observations"])
                if row.get("profile_row_observations")
                else None,
                capture_status="captured_profile_tuple_summary",
                parser_status="source_csv_fields_preserved",
                api33_title_exact_match=row.get("api33_exact_title_match") or None,
                api33_english_exact_match=row.get("api33_english_exact_match") or None,
                source_record=row,
            )

    # KRA web glossary descriptions remain a separate source from API33 and profile details.
    web_doc = read_json(WEB / "glossary.json")
    web_path = WEB / "glossary.json"
    for row_no, entry in enumerate(web_doc["entries"], 1):
        add_observation(
            source_kind="kra_web_disease_glossary",
            source_path=web_path,
            source_row_ordinal=row_no,
            source_subrow_ordinal=1,
            source_title=entry.get("korean_name_prefix"),
            source_english_name=None,
            description_text=entry.get("description_ko"),
            raw_capture_text=entry.get("heading"),
            source_url=entry.get("source_url") or web_doc.get("source_url"),
            collected_at_kst=web_doc.get("fetched_at_kst"),
            source_meet=None,
            horse_name=None,
            horse_id=None,
            event_date_local=None,
            event_dates_json=None,
            hospital_name=None,
            observation_count=1,
            capture_status="captured_web_glossary_entry",
            parser_status="source_json_fields_preserved;english_name_not_separately_encoded",
            api33_title_exact_match=None,
            api33_english_exact_match=None,
            source_record=entry,
        )

    # User-supplied detail is preserved as such; API33 illDesc '-' remains comparison metadata.
    user_path = PHRASE_RECHECK / "user_provided_kra_term_details.json"
    user_doc = read_json(user_path)
    for row_no, entry in enumerate(user_doc["entries"], 1):
        add_observation(
            source_kind="user_provided_kra_glossary_detail",
            source_path=user_path,
            source_row_ordinal=row_no,
            source_subrow_ordinal=1,
            source_title=entry.get("korean_name"),
            source_english_name=entry.get("english_name"),
            description_text=entry.get("description_ko"),
            raw_capture_text=None,
            source_url=user_doc.get("source_url"),
            collected_at_kst=user_doc.get("collected_at_kst"),
            source_meet=None,
            horse_name=None,
            horse_id=None,
            event_date_local=None,
            event_dates_json=None,
            hospital_name=None,
            observation_count=1,
            capture_status="user_provided_not_recollected_from_page",
            parser_status="source_json_fields_preserved",
            api33_title_exact_match=None,
            api33_english_exact_match=None,
            source_record={
                "manifest": {k: v for k, v in user_doc.items() if k != "entries"},
                "entry": entry,
            },
        )

    fields = [
        ("explanation_observation_id", "str"),
        ("source_kind", "str"),
        ("source_title", "str"),
        ("source_english_name", "str"),
        ("description_text", "str"),
        ("description_present", "bool"),
        ("exact_explanation_tuple_sha256", "str"),
        ("description_text_sha256", "str"),
        ("raw_capture_text", "str"),
        ("source_url", "str"),
        ("source_file", "str"),
        ("source_file_sha256", "str"),
        ("source_row_ordinal", "i32"),
        ("source_subrow_ordinal", "i32"),
        ("source_row_sha256", "str"),
        ("source_record_json", "str"),
        ("collected_at_kst", "str"),
        ("source_publication_at_kst", "str"),
        ("source_meet", "i32"),
        ("source_meet_name", "str"),
        ("horse_name", "str"),
        ("horse_id", "str"),
        ("event_date_local", "str"),
        ("event_dates_json", "str"),
        ("hospital_name", "str"),
        ("source_observation_count", "i32"),
        ("capture_status", "str"),
        ("parser_status", "str"),
        ("api33_title_exact_match", "str"),
        ("api33_english_exact_match", "str"),
    ]
    write_parquet("explanation_observations.parquet", observations, fields)

    grouped: OrderedDict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = (
        OrderedDict()
    )
    for row in observations:
        key = (row["source_title"], row["source_english_name"], row["description_text"])
        grouped.setdefault(key, []).append(row)
    terms: list[dict[str, Any]] = []
    for key, matches in grouped.items():
        terms.append(
            {
                "exact_explanation_tuple_sha256": tuple_hash(list(key)),
                "source_title": key[0],
                "source_english_name": key[1],
                "description_text": key[2],
                "description_present": key[2] is not None,
                "source_observation_count": len(matches),
                "source_kinds_json": canonical_json(sorted({x["source_kind"] for x in matches})),
                "source_meets_json": canonical_json(
                    sorted({x["source_meet"] for x in matches if x["source_meet"] is not None})
                ),
                "source_observation_ids_json": canonical_json(
                    [x["explanation_observation_id"] for x in matches]
                ),
                "source_files_json": canonical_json(sorted({x["source_file"] for x in matches})),
                "description_text_sha256": exact_text_hash(key[2]) if key[2] is not None else None,
            }
        )
    write_parquet(
        "explanation_terms.parquet",
        terms,
        [
            ("exact_explanation_tuple_sha256", "str"),
            ("source_title", "str"),
            ("source_english_name", "str"),
            ("description_text", "str"),
            ("description_present", "bool"),
            ("source_observation_count", "i32"),
            ("source_kinds_json", "str"),
            ("source_meets_json", "str"),
            ("source_observation_ids_json", "str"),
            ("source_files_json", "str"),
            ("description_text_sha256", "str"),
        ],
    )

    profile = [
        x
        for x in observations
        if x["source_kind"].startswith("kra_profile_")
        or x["source_kind"] == "user_provided_profile_detail"
    ]
    profile_titles = {x["source_title"] for x in profile if x["source_title"]}
    profile_titles_with_description = {
        x["source_title"] for x in profile if x["source_title"] and x["description_present"]
    }
    web_rows = [x for x in observations if x["source_kind"] == "kra_web_disease_glossary"]
    user_rows = [x for x in observations if x["source_kind"] == "user_provided_kra_glossary_detail"]
    return observations, {
        "explanation_observation_count": len(observations),
        "unique_exact_explanation_tuple_count": len(terms),
        "profile_capture_source_record_count": len(profile),
        "profile_observations_as_recorded_count": sum(
            x["source_observation_count"] or 0 for x in profile
        ),
        "unique_profile_title_count": len(profile_titles),
        "unique_profile_title_with_description_count": len(profile_titles_with_description),
        "profile_capture_source_record_counts_by_meet": {
            str(meet): sum(x["source_meet"] == meet for x in profile) for meet in (1, 2, 3)
        },
        "profile_reported_observation_counts_by_meet": {
            str(meet): sum(
                (x["source_observation_count"] or 0) for x in profile if x["source_meet"] == meet
            )
            for meet in (1, 2, 3)
        },
        "web_glossary_row_count": len(web_rows),
        "user_provided_detail_row_count": len(user_rows),
        "historical_publication_time_column_present_but_unknown": True,
        "source_time_and_event_date_are_separate_columns": True,
        "source_input_hashes": hashes,
    }


def write_readme(metrics: dict[str, Any]) -> None:
    lines = [
        "# Medical dictionary snapshot v1",
        "",
        "This folder contains a frozen research dictionary built from saved KRA source captures and the reviewed phrase snapshot. It contains no medical event rows and does not assign diagnoses to horses or races.",
        "",
        "## Scope and handling",
        "",
        "- The phrase review snapshot spans the previous all-meet source inventory. Its old usage counts are not copied into this package and are not a research-scope count. The event loader must compute counts from the approved Seoul and Busan-Gyeongnam source rows for 2010-01-01 through 2026-09-29.",
        "- API33 `illDesc` is preserved exactly; every source value is `-`, so it is not treated as an explanation.",
        "- KRA web glossary, KRA profile captures, and user-provided KRA detail are distinct sources. `collected_at_kst` records when the capture was saved; `event_date_local`/`event_dates_json` record historical profile dates. `source_publication_at_kst` is null because the saved evidence does not provide a publication time.",
        "- Profile source meet 2 is Jeju, meet 1 is Seoul, and meet 3 is Busan-Gyeongnam. The captured explanation evidence is retained with its original source meet; the research event loader must exclude Jeju clinical events.",
        "- Phrase IDs are SHA-256 hashes of the exact UTF-8 raw phrase. Operating database integer IDs are deliberately absent. Original phrase text, including spacing and punctuation, is preserved.",
        "- `phrase_components.reviewed_target_ordinal` preserves the order in the review cell separated by exact ` | `. It is the saved reviewed target order, not an inferred diagnosis-slot order. It must not be used to split source event slots.",
        "- Phrase rows preserve the approved review status, but `event_link_policy` disables automatic event linking. Contextual mappings require fresh in-scope event evidence; do not turn them into global aliases.",
        "- 356 historical Dacom72 decisions removed literal `동물  ` before matching. That prefix can come from a hospital-cell parsing artifact in the prior Text workflow; `mapping_rule_scope=prior_rpt_parser_context_only` and `prefix_rule_reusable=false` keep those decisions as audit evidence only. Do not strip the prefix from new API16_1 diagnosis slots.",
        "- Excluded phrase rows stay in `phrase_decisions.parquet` with their exact raw text and review note; the source text is not altered or deleted.",
        "- Explanation observations retain repeated source provenance. `explanation_terms.parquet` is a deduplicated exact-tuple lookup derived from those observations; it does not discard the source observation rows.",
        "- No explanation is synthesized. A missing or title-only explanation stays null.",
        "- Full Parquet column names, Arrow types, and nullability are recorded in `schema.json`; source file hashes and row-level validation details are in `manifest.json`.",
        "",
        "## Parquet files",
        "",
        "| File | Grain | Rows | Key fields |",
        "|---|---|---:|---|",
        f"| `api33_source_rows.parquet` | one original API33 response row | {metrics['api33']['source_row_count']:,} | page/row ordinal, exact title/English/description, source hashes |",
        f"| `api33_terms.parquet` | one exact Korean+English+description tuple | {metrics['api33']['exact_tuple_count']:,} | exact tuple hash, first source row, all duplicate source row IDs |",
        f"| `phrase_decisions.parquet` | one exact raw phrase review decision | {metrics['phrases']['phrase_decision_count']:,} | raw phrase hash/text, review status, rule note, event link policy |",
        f"| `phrase_components.parquet` | one reviewed target per phrase | {metrics['phrases']['component_link_row_count']:,} | raw phrase hash/text, target ordinal/title, evidence note |",
        f"| `explanation_observations.parquet` | one saved source capture/summary row | {metrics['explanations']['explanation_observation_count']:,} | source kind, exact title/English/description, capture and event provenance |",
        f"| `explanation_terms.parquet` | one exact captured title+English+description tuple | {metrics['explanations']['unique_exact_explanation_tuple_count']:,} | exact tuple hash, source kinds and observation IDs |",
        "",
        "## Snapshot checks",
        "",
        f"- API33 original rows: {metrics['api33']['source_row_count']:,}; exact tuple rows: {metrics['api33']['exact_tuple_count']:,}; distinct Korean titles: {metrics['api33']['unique_korean_title_count']:,}; exact duplicate excess rows: {metrics['api33']['source_duplicate_excess_count']:,}.",
        f"- Phrase decisions: {metrics['phrases']['phrase_decision_count']:,}; reviewed mapping rows: {metrics['phrases']['confirmed_mapping_count']:,}; excluded raw phrases: {metrics['phrases']['excluded_count']}.",
        f"- Profile title count represented by saved sources: {metrics['explanations']['unique_profile_title_count']:,}; profile titles with non-empty captured description: {metrics['explanations']['unique_profile_title_with_description_count']:,}.",
        f"- KRA web glossary source rows: {metrics['explanations']['web_glossary_row_count']:,}; user-provided KRA detail rows: {metrics['explanations']['user_provided_detail_row_count']:,}.",
        "- API33 XML page SHA-256, per-page counts, and row-for-row XML/JSON field equality were asserted by `build_dictionary.py` before writing the Parquet files.",
        "",
        "Rebuild with the repository virtual environment: `./.venv/bin/python thoroughbred/research/20261002_medical_v1/dictionary/build_dictionary.py`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    api_source_paths = [
        API33 / "api33_glossary.json",
        API33 / "api33_glossary_deduplicated_exact.json",
        API33 / "manifest.json",
        API33 / "raw/api33_page_001.xml",
        API33 / "raw/api33_page_002.xml",
        API33 / "raw/api33_page_003.xml",
        API33 / "raw/api33_page_004.xml",
        REVIEW_CSV,
        API33 / "profile_hover_expansion_20261001/source_manifest.json",
        PROFILE_OLD,
        PHRASE_RECHECK / "kra_profile_observations.csv",
        PHRASE_RECHECK / "user_provided_kra_term_details.json",
        PROFILE / "profile_hover_observations.csv",
        PROFILE / "profile_hover_observations_additional_20261001.csv",
        WEB / "glossary.json",
        API33 / "manual_review_decisions_20260930.csv",
        API33 / "composite_review_20260930/composite_component_review.csv",
    ]
    api_rows, api_terms, api_metrics = build_api33()
    phrase_rows, phrase_components, phrase_metrics = build_phrase_tables()
    explanation_rows, explanation_metrics = build_explanation_observations()
    inputs = input_inventory(api_source_paths)
    generated_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    metrics = {"api33": api_metrics, "phrases": phrase_metrics, "explanations": explanation_metrics}
    write_readme(metrics)

    output_files = [
        "api33_source_rows.parquet",
        "api33_terms.parquet",
        "phrase_decisions.parquet",
        "phrase_components.parquet",
        "explanation_observations.parquet",
        "explanation_terms.parquet",
        "schema.json",
        "README.md",
        "build_dictionary.py",
    ]
    parquet_files = [name for name in output_files if name.endswith(".parquet")]
    schemas = {
        name: [
            {"name": field.name, "arrow_type": str(field.type), "nullable": field.nullable}
            for field in pq.read_schema(OUT / name)
        ]
        for name in parquet_files
    }
    (OUT / "schema.json").write_text(
        json.dumps(schemas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    outputs = {
        name: {
            "sha256": sha256_file(OUT / name),
            "bytes": (OUT / name).stat().st_size,
            "row_count": (
                api_metrics["source_row_count"]
                if name == "api33_source_rows.parquet"
                else api_metrics["exact_tuple_count"]
                if name == "api33_terms.parquet"
                else phrase_metrics["phrase_decision_count"]
                if name == "phrase_decisions.parquet"
                else phrase_metrics["component_link_row_count"]
                if name == "phrase_components.parquet"
                else explanation_metrics["explanation_observation_count"]
                if name == "explanation_observations.parquet"
                else explanation_metrics["unique_exact_explanation_tuple_count"]
                if name == "explanation_terms.parquet"
                else None
            ),
        }
        for name in output_files
    }
    manifest = {
        "dataset": "medical_dictionary_snapshot_v1",
        "generated_at_kst": generated_at,
        "dataset_scope": {
            "kind": "research_dictionary_and_review_provenance",
            "medical_event_scope": "events are loaded separately for Seoul and Busan-Gyeongnam, 2010-01-01 through 2026-09-29",
            "phrase_review_snapshot_scope": "prior all-meet unique-phrase audit; no usage counts are exported here",
            "jeju_profile_source_meet": 2,
            "meet_names": {"1": "Seoul", "2": "Jeju", "3": "Busan-Gyeongnam"},
        },
        "hash_contract": {
            "raw_text_sha256": "SHA-256 of exact UTF-8 raw phrase bytes; no normalization",
            "api33_tuple_sha256": "length-prefixed exact UTF-8 illName, illEngName, illDesc; null encoded distinctly",
            "explanation_tuple_sha256": "length-prefixed exact UTF-8 title, English name, description; null encoded distinctly",
        },
        "schema_file": "schema.json",
        "metrics": metrics,
        "source_files": inputs,
        "output_files": outputs,
        "safety": {
            "operating_sqlite_or_supabase_accessed": False,
            "core_duckdb_accessed_or_modified": False,
            "network_used": False,
            "term_id_copied": False,
            "automatic_event_linking_enabled": False,
            "legacy_dacom72_prefix_rule_reuse_enabled": False,
            "api33_ill_desc_used_as_explanation": False,
        },
        "xml_validation": {
            "parser": "lxml.etree XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)",
            "raw_xml_hashes_checked_against_manifest": True,
            "page_item_counts_checked": True,
            "every_xml_row_compared_to_json_row": True,
            "page_checks": api_metrics["xml_page_checks"],
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
