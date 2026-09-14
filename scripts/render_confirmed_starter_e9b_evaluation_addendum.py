"""Presentation-only full-span table; never import or call an extractor/evaluator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BASE = Path("data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1")
OUTPUT = Path("data/experiments/confirmed_starter_e9b_frozen_evaluation_readable_20260913_v1")
EXPECTED_BASE_MANIFEST_SHA = "031287de142e91d63393df9638d46ac9b2e2e2d24989e0895860ff353352c8f9"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def main() -> None:
    if sha(BASE / "artifact_manifest.json") != EXPECTED_BASE_MANIFEST_SHA:
        raise RuntimeError("original one-shot evaluation manifest changed")
    manifest = json.loads((BASE / "artifact_manifest.json").read_text(encoding="utf-8"))
    if sha(BASE / "comparison.json") != manifest["output_sha256"]["comparison.json"]:
        raise RuntimeError("original comparison changed")
    comparison = json.loads((BASE / "comparison.json").read_text(encoding="utf-8"))
    if comparison["metrics_status"] != "complete":
        raise RuntimeError("comparison not complete")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json(
        OUTPUT / "presentation_protocol.json",
        {
            "original_manifest_sha256": EXPECTED_BASE_MANIFEST_SHA,
            "original_comparison_sha256": sha(BASE / "comparison.json"),
            "renderer_sha256": sha(Path(__file__)),
            "role": "post-score presentation only; no extractor calls, labels, or score changes",
        },
    )
    lines = [
        "# E9-B 동결 비교 전체 원문 근거표",
        "",
        "원본 comparison.json의 표시 전용 보충표다. 평가 단위·상태·지표는 변경하지 않았다.",
        "",
        "| 상태 | report | 말 key | 유형 | 역할 | 기준 ID | 출력 ID | 이유 |",
        "|---|---:|---|---|---|---|---|---|",
    ]
    for row in comparison["units"]:
        key = json.dumps(row["horse_source_key"], ensure_ascii=False)
        lines.append(
            f"| {row['status']} | {row['report_id']} | `{key}` | {row['event_type']} | "
            f"{row['role']} | {', '.join(row['reference_ids'])} | "
            f"{', '.join(row['evidence_ids'])} | {row['reason']} |"
        )
    lines.extend(["", "## 전 단위 원문 근거", ""])
    for index, row in enumerate(comparison["units"], 1):
        lines.extend(
            [
                f"### {index}. {row['status']} · report {row['report_id']} "
                f"· {row['event_type']} · {row['role']}",
                "",
                f"- 말 key: `{json.dumps(row['horse_source_key'], ensure_ascii=False)}`",
                f"- 기준 ID: {row['reference_ids']}; 출력 ID: {row['evidence_ids']}",
                f"- 이유: {row['reason']}; mask: {row['mask_reasons']}",
            ]
        )
        for kind in ("reference_spans", "evidence_spans"):
            for span in row[kind]:
                location = f"{span['field']}[{span['start']}:{span['end']}]"
                exact_text = json.dumps(span["text"], ensure_ascii=False)
                lines.append(f"- {kind} {location}: {exact_text}")
        lines.append("")
    lines.extend(["## actor-victim 관계의 원문 근거", ""])
    for row in comparison["relations"]["rows"]:
        lines.append(f"### {row['status']} · report {row['report_id']} · {row['event_type']}")
        lines.append(f"- actor `{row['actor_source_key']}` → victim `{row['victim_source_key']}`")
        lines.append(f"- 기준 ID: {row['reference_ids']}; 출력 ID: {row['evidence_ids']}")
        for kind in ("reference_relation_spans", "output_relation_spans"):
            for span in row[kind]:
                location = f"{span['field']}[{span['start']}:{span['end']}]"
                exact_text = json.dumps(span["text"], ensure_ascii=False)
                lines.append(f"- {kind} {location}: {exact_text}")
        lines.append("")
    with (OUTPUT / "comparison_full_readable.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    write_json(
        OUTPUT / "artifact_manifest.json",
        {
            "original_manifest_sha256": EXPECTED_BASE_MANIFEST_SHA,
            "renderer_sha256": sha(Path(__file__)),
            "output_sha256": {path.name: sha(path) for path in OUTPUT.iterdir() if path.is_file()},
            "extractor_calls": 0,
            "label_changes": 0,
            "score_changes": 0,
        },
    )
    print(
        json.dumps(
            {
                "units_rendered": len(comparison["units"]),
                "relations_rendered": len(comparison["relations"]["rows"]),
            }
        )
    )


if __name__ == "__main__":
    main()
