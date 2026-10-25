"""Add feature identities to the corrected 84-race table; do not recompute values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT_DIR = HERE / "outputs_followup_addendum"
PRIOR = OUT_DIR / "actual_top3_context_summary_corrected.csv"
ORIGINAL = HERE / "outputs_supplemental/actual_top3_context_summary.csv"
TARGET = OUT_DIR / "actual_top3_context_summary_corrected_v2.csv"
RECEIPT = OUT_DIR / "top3_summary_feature_label_correction_receipt.json"
EXPECTED = {
    "prior_corrected_sha256": "dc2db01105a1d58d79037caaef3337e4761fcd0568381ff3edebdb11957b908d",
    "original_supplemental_sha256": "c05a11a6c8c1077fff45cc83fc711748aab491356cee3d1f48ea13ea7f2ccb79",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if TARGET.exists() or RECEIPT.exists():
        raise FileExistsError("refuse to overwrite Top3 summary correction outputs")
    prior_sha = sha256(PRIOR)
    original_sha = sha256(ORIGINAL)
    if prior_sha != EXPECTED["prior_corrected_sha256"]:
        raise AssertionError("prior corrected table hash mismatch")
    if original_sha != EXPECTED["original_supplemental_sha256"]:
        raise AssertionError("original supplemental table hash mismatch")
    prior = pd.read_csv(PRIOR)
    original = pd.read_csv(ORIGINAL)
    if len(prior) != 18 or set(prior.outcome_group.unique()) != {
        "all_discordant_84", "gained", "lost"
    }:
        raise AssertionError("unexpected prior corrected table scope")
    feature_order = original.loc[original.outcome_group.eq("gained"), "feature"].tolist()
    if len(feature_order) != 6 or len(set(feature_order)) != 6:
        raise AssertionError("cannot recover fixed feature order from original summary")
    prior["feature"] = prior.groupby("outcome_group", sort=False).cumcount().map(
        lambda index: feature_order[int(index)]
    )
    prior["feature_unit"] = prior.feature.map(
        lambda feature: "ratio" if "ratio" in feature else "kg"
    )
    if prior.feature.isna().any():
        raise AssertionError("feature labels were not fully added")
    # Ensure the already summarized gained/lost values are copied without alteration.
    comparison_fields = {
        "races": "units",
        "mean": "mean",
        "median": "median",
        "p25": "p25",
        "p75": "p75",
    }
    for group in ["gained", "lost"]:
        left = prior.loc[prior.outcome_group.eq(group)].sort_values("feature")
        right = original.loc[original.outcome_group.eq(group)].sort_values("feature")
        for left_column, right_column in comparison_fields.items():
            left_values = left[left_column].to_numpy(float)
            right_values = right[right_column].to_numpy(float)
            if not np.allclose(left_values, right_values, atol=2e-12, rtol=0):
                raise AssertionError(f"existing {group} values changed in {left_column}")
    prior.to_csv(TARGET, index=False, encoding="utf-8", mode="x", float_format="%.12g")
    receipt = {
        "status": "feature-label correction only; no data rows or numeric summaries recalculated",
        "prior_corrected_table": str(PRIOR.relative_to(ROOT)),
        "prior_corrected_table_sha256": prior_sha,
        "original_table_used_for_feature_names": str(ORIGINAL.relative_to(ROOT)),
        "original_table_sha256": original_sha,
        "replacement_table": str(TARGET.relative_to(ROOT)),
        "replacement_table_sha256": sha256(TARGET),
        "feature_names": feature_order,
        "feature_units": {name: ("ratio" if "ratio" in name else "kg") for name in feature_order},
        "replacement_scope": ["all_discordant_84", "gained", "lost"],
        "races_per_scope": {"all_discordant_84": 84, "gained": 50, "lost": 34},
        "prior_corrected_file_preserved": True,
        "gained_lost_values_match_original_feature_labeled_summary": True,
        "no_fit_or_new_context_calculation": True,
    }
    with RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
