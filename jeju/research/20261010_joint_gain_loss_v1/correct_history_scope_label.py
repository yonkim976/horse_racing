"""Add a correctly scoped history-support table without overwriting the first output."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT_DIR = HERE / "outputs_followup_addendum"
SOURCE = HERE / "outputs_supplemental/lifetime_same_distance_support.csv"
CONTRACT = HERE / "SAVED_HISTORY_EXTENSION_CONTRACT.json"
SUPPLEMENTAL_CONTRACT = HERE / "SUPPLEMENTAL_CONTEXT_CONTRACT.json"
SUPPLEMENTAL_RECEIPT = HERE / "outputs_supplemental/supplemental_receipt.json"
TARGET = OUT_DIR / "same_distance_support_available_range_corrected.csv"
RECEIPT = OUT_DIR / "history_scope_correction_receipt.json"
SOURCE_SHA = "d2e6a08e6cb186ae335c0d46556feb90313167b161fbffa164baea382452cfe4"
OLD_HISTORY_CONTRACT_SHA = "31f9382d9ed2be331de02d4a20db341f939a1c737683237ddfbce5dd426325bf"
OLD_SUPPLEMENTAL_CONTRACT_SHA = "0f612469b9ddbc8e3a33b4b94e7ea611f8b43cf5607fdae5c32cda89f8f81052"
OLD_PLAN_SHA = "559f123b0a5585113765ed0ee45dd7607f7758a7b1e9a529f952401c82e3896e"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if TARGET.exists() or RECEIPT.exists():
        raise FileExistsError("refuse to overwrite history-scope correction outputs")
    if sha256(SOURCE) != SOURCE_SHA:
        raise AssertionError("original history table changed")
    supplemental = json.loads(SUPPLEMENTAL_RECEIPT.read_text(encoding="utf-8"))
    if supplemental.get("history_extension_contract_sha256") != OLD_HISTORY_CONTRACT_SHA:
        raise AssertionError("old contract hash does not match the original run receipt")
    if supplemental.get("supplemental_contract_sha256") != OLD_SUPPLEMENTAL_CONTRACT_SHA:
        raise AssertionError("old supplemental contract hash does not match the original run receipt")
    if supplemental.get("supplemental_plan_sha256") != OLD_PLAN_SHA:
        raise AssertionError("old supplemental plan hash does not match the original run receipt")

    original = pd.read_csv(SOURCE)
    if "feature" not in original or "unit" not in original:
        raise AssertionError("source history table schema changed")
    corrected = original.copy()
    overall_counts = {"same_starts", "same_valid_times"}
    corrected["history_scope_definition"] = corrected.feature.map(
        lambda feature: (
            "overall_same_distance_count_within_available_past_query_range_not_complete_lifetime_census"
            if feature in overall_counts
            else "bounded_support_count_in_most_recent_five_history_slots"
        )
    )
    new_contract_hash = sha256(CONTRACT)
    new_supplemental_contract_hash = sha256(SUPPLEMENTAL_CONTRACT)
    OUT_DIR.mkdir(exist_ok=True)
    corrected.to_csv(TARGET, index=False, encoding="utf-8", mode="x", float_format="%.12g")
    payload = {
        "status": "history-scope wording correction; numeric rows are copied unchanged",
        "old_history_extension_contract_sha256": OLD_HISTORY_CONTRACT_SHA,
        "new_history_extension_contract_sha256": new_contract_hash,
        "old_supplemental_context_contract_sha256": OLD_SUPPLEMENTAL_CONTRACT_SHA,
        "new_supplemental_context_contract_sha256": new_supplemental_contract_hash,
        "original_table": str(SOURCE.relative_to(ROOT)),
        "original_table_sha256": SOURCE_SHA,
        "corrected_table": str(TARGET.relative_to(ROOT)),
        "corrected_table_sha256": sha256(TARGET),
        "numeric_values_unchanged": bool(
            corrected.drop(columns=["history_scope_definition"]).equals(original)
        ),
        "scope_definition": {
            "same_starts": "overall same-distance history within the saved feature's available past query range; not a complete lifetime census",
            "same_valid_times": "overall valid same-distance history within the saved feature's available past query range; not a complete lifetime census",
            "same_distance_last5_actual_n": "bounded support among the most recent five actual-history slots",
            "same_distance_last5_normal_n": "bounded support among the most recent five normalized-history slots",
        },
        "reason": (
            "The original output filename and initial contract used lifetime wording. "
            "The source feature only represents the available past query range. The "
            "original file is preserved; this corrected table adds an explicit scope column."
        ),
        "original_supplemental_run_receipt_sha256": sha256(SUPPLEMENTAL_RECEIPT),
        "no_fit": True,
    }
    with RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
