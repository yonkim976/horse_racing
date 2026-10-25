"""Repair only F1-scope means leaked into the all-period S2 support rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "outputs_f1_supplement"
SOURCE = OUTDIR / "S2_full_grid_support.csv"
OUTPUT = OUTDIR / "S2_full_grid_support_v2.csv"
RECEIPT = OUTDIR / "S2_full_grid_v2_verification.json"
EXPECTED_SOURCE_SHA = "fefae9d136744b9dba89634e986d49d12b9423f75eefd963e30d62813b11bdff"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if OUTPUT.exists() or RECEIPT.exists():
        raise FileExistsError("Refusing to overwrite v2 grid or its verification receipt")
    source_sha = sha(SOURCE)
    if source_sha != EXPECTED_SOURCE_SHA:
        raise RuntimeError(f"Unexpected source grid SHA-256: {source_sha}")
    original = pd.read_csv(SOURCE)
    required = {"period", "condition", "rows", "F1_rows", "mean_p_F1", "F1_residual"}
    if required - set(original.columns):
        raise RuntimeError(f"S2 source grid missing fields: {sorted(required - set(original.columns))}")
    mask = original.period.eq("all") & original.F1_rows.eq(0) & original.mean_p_F1.notna()
    changed_cells = original.loc[mask, ["condition", "rows", "F1_rows", "mean_p_F1"]].to_dict("records")
    if len(changed_cells) != 6:
        raise RuntimeError(f"Expected six all-period F1-scope leaks, found {len(changed_cells)}")
    repaired = original.copy()
    repaired.loc[mask, "mean_p_F1"] = np.nan
    repaired.to_csv(OUTPUT, index=False)
    roundtrip = pd.read_csv(OUTPUT)
    expected = original.copy()
    expected.loc[mask, "mean_p_F1"] = np.nan
    pd.testing.assert_frame_equal(expected, roundtrip)
    if roundtrip.loc[roundtrip.period.eq("all") & roundtrip.F1_rows.eq(0), "mean_p_F1"].notna().any():
        raise RuntimeError("All-period rows without F1 scope still contain mean F1 predictions")
    # Prove the source file stayed byte-identical after emitting the new output.
    if sha(SOURCE) != EXPECTED_SOURCE_SHA:
        raise RuntimeError("Original S2 grid changed during repair")
    receipt = {
        "passed": True,
        "purpose": "correction-only copy; no condition statistics or model outputs recomputed",
        "source_path": str(SOURCE.relative_to(HERE)),
        "source_sha256": source_sha,
        "source_bytes": SOURCE.stat().st_size,
        "repair_code_path": str(Path(__file__).relative_to(HERE)),
        "repair_code_sha256": sha(Path(__file__)),
        "output_path": str(OUTPUT.relative_to(HERE)),
        "output_sha256": sha(OUTPUT),
        "output_bytes": OUTPUT.stat().st_size,
        "changed_row_count": int(mask.sum()),
        "changed_field_only": "mean_p_F1",
        "changed_cells": changed_cells,
        "all_other_rows_and_fields_identical_after_csv_roundtrip": True,
        "all_period_F1_rows_zero_mean_p_F1_null": True,
        "original_grid_preserved": True,
        "model_training_count": 0,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("S2 v2 repair verified:", receipt["output_path"], receipt["output_sha256"], flush=True)


if __name__ == "__main__":
    main()
