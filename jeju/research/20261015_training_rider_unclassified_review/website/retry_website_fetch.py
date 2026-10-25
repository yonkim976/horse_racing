#!/usr/bin/env python3
"""Retry the eight exact official KRA pages and preserve a separate attempt record."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BASE_MANIFEST = OUT / "collection_manifest.json"
RETRY_RAW = OUT / "retry_raw_html"
COLLECTOR_PATH = ROOT / "jeju/research/20261015_training_rider_identity/source_review/collect_kra_training_html.py"
REVIEW_PATH = OUT / "run_website_review.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load local module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_new_json(path: Path, document):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    outputs = [OUT / "retry_collection_manifest.json", OUT / "retry_website_event_evidence.json"]
    if any(path.exists() for path in outputs):
        raise FileExistsError("Refusing to overwrite a previous retry result")
    base = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    plan = base["selected_pages"]
    collector = load_module("kra_training_collector_retry", COLLECTOR_PATH)
    review = load_module("website_review_retry", REVIEW_PATH)
    RETRY_RAW.mkdir(exist_ok=True)
    pages = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(collector.fetch_page, {"horse_id": str(item["horse_id"]), "url": item["url"]}): item
            for item in plan
        }
        for future in as_completed(futures):
            item = futures[future]
            retrieved = now_utc()
            try:
                fetched = future.result()
                raw_path = RETRY_RAW / f"kra_profileTrainState_hrNo_{item['horse_id']}.html"
                with raw_path.open("xb") as handle:
                    handle.write(fetched.pop("body"))
                fetched["fetch_status"] = "ok"
                fetched["retrieved_at_utc"] = retrieved
                fetched["source_path"] = str(raw_path.relative_to(ROOT))
                pages.append(fetched)
            except Exception as exc:
                pages.append({
                    "horse_id": str(item["horse_id"]), "url": item["url"],
                    "fetch_status": "error", "retrieved_at_utc": retrieved,
                    "error_type": type(exc).__name__, "error": str(exc),
                })
    pages.sort(key=lambda row: row["horse_id"])
    retry_manifest = {
        "generated_at_utc": now_utc(),
        "retry_of": str(BASE_MANIFEST.relative_to(ROOT)),
        "retry_reason": "Initial exact-host requests failed with DNS name resolution errors; retry performed with authorized network escalation.",
        "host_allowlist": ["race.kra.co.kr"],
        "path_allowlist": ["/racehorse/profileTrainState.do"],
        "requested_page_count": len(plan),
        "success_count": sum(row.get("fetch_status") == "ok" for row in pages),
        "failure_count": sum(row.get("fetch_status") != "ok" for row in pages),
        "pages": [{key: value for key, value in row.items() if key != "body"} for row in pages],
    }
    source_manifest = json.loads((ROOT / "jeju/research/20261015_training_rider_identity/source_review/http_collection_manifest.json").read_text(encoding="utf-8"))
    old_ids = {str(row["horse_id"]) for row in source_manifest.get("pages", [])}
    candidates = review.read_candidates(old_ids)
    event_result = review.match_events(candidates, pages, collector)
    retry_evidence = {
        "generated_at_utc": now_utc(),
        "retry_manifest": str((OUT / "retry_collection_manifest.json").relative_to(ROOT)),
        "source_policy": "Exact horse ID, training date, entry time, exit time and duration minutes are all required. Only explicit row markers in the exact page row can suggest a type; API kind, employee number, and current roster/position are not used to infer historical type.",
        "selected_horses": plan,
        "summary": {key: value for key, value in event_result.items() if key not in {"evidence_rows", "unmatched_rows", "comparison_unavailable_rows", "ambiguous_exact_event_keys_detail", "page_parse"}},
        "page_parse": event_result["page_parse"],
        "evidence_rows": event_result["evidence_rows"],
        "unmatched_rows": event_result["unmatched_rows"],
        "comparison_unavailable_rows": event_result["comparison_unavailable_rows"],
        "ambiguous_exact_event_keys": event_result["ambiguous_exact_event_keys_detail"],
    }
    write_new_json(OUT / "retry_collection_manifest.json", retry_manifest)
    write_new_json(OUT / "retry_website_event_evidence.json", retry_evidence)
    print(json.dumps({
        "success_count": retry_manifest["success_count"],
        "failure_count": retry_manifest["failure_count"],
        "summary": retry_evidence["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
