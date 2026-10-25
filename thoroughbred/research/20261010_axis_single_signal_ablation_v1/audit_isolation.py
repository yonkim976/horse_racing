"""Counterfactual unused-input mutation confirms each single condition is isolated."""

import json

import numpy as np
import pandas as pd
import run as a


def main():
    a.check()
    d = pd.read_parquet(a.PRIOR / "outputs/race_inputs.parquet")
    checks = []
    for year in [2024, 2025, 2026]:
        original = d[d.year.eq(year)].copy()
        for variant in a.FEATURE_SETS:
            mutated = original.copy()
            if variant != "early_only":
                mutated["axis_gap_section_early_mean3"] = np.nan
            if variant != "distance_only":
                mutated["axis_section_previous_distance"] = np.nan
                mutated["axis_distance_m"] = -999
            if variant in ["early_only", "distance_only"]:
                mutated["axis_grade"] = 5
            mutated["collapsed"] = 1 - mutated.collapsed
            model = json.loads((a.OUT / "models" / f"{variant}_{year}.json").read_text())
            np.testing.assert_array_equal(a.predict(original, model), a.predict(mutated, model))
            checks.append(dict(year=year, variant=variant, n=len(original), status="passed"))
    a.save(
        a.OUT / "isolation_audit.json",
        dict(
            status="passed",
            checks=checks,
            unused_predictor_and_current_outcome_mutations_invariant=True,
            script_sha256=a.sha(a.HERE / "audit_isolation.py"),
        ),
    )
    a.check()
    print("Unused-input invariance passed for", len(checks), "models")


if __name__ == "__main__":
    main()
