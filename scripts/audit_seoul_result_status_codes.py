"""Cross-check Seoul API4_3 special result codes with preserved AI result labels."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("data/research/seoul_backfill_20260915_v1")
AI = Path("data/raw/kra/ai_race_result/2026")


def rows(payload: dict) -> list[dict]:
    wrapped = payload["response"]["body"].get("items") or {}
    item = wrapped.get("item", []) if isinstance(wrapped, dict) else []
    return [item] if isinstance(item, dict) else item or []


def main() -> None:
    labels: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    source_files = []
    for path in sorted(AI.rglob("*.json")):
        raw = path.read_bytes()
        for row in rows(json.loads(raw)):
            if row.get("rccrsNm") != "서울":
                continue
            key = (
                str(row.get("raceDt")),
                str(row.get("raceNo")),
                str(row.get("hrno") or "").zfill(7),
            )
            if row.get("rk") is not None:
                labels[key].add(str(row["rk"]))
        source_files.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    source = ROOT / "raw_results/2026/page_0001.json"
    raw = source.read_bytes()
    mapping: dict[str, Counter] = defaultdict(Counter)
    mismatched_labels = []
    for row in rows(json.loads(raw)):
        key = (str(row["rcDate"]), str(row["rcNo"]), str(row["hrNo"]).zfill(7))
        label_set = labels.get(key, set())
        if len(label_set) > 1:
            mismatched_labels.append({"key": key, "labels": sorted(label_set)})
        for label in label_set:
            mapping[str(row.get("ord"))][label] += 1
    result = {
        "scope": "preserved 2026 Seoul AI race-result rows overlapping annual API4_3",
        "api_source": str(source),
        "api_sha256": hashlib.sha256(raw).hexdigest(),
        "ai_files": source_files,
        "special_code_labels": {k: dict(mapping[k]) for k in ("91", "92", "93", "94", "95", "99")},
        "conflicting_ai_labels": mismatched_labels,
    }
    (ROOT / "result_code_crosscheck.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result["special_code_labels"], ensure_ascii=False))


if __name__ == "__main__":
    main()
