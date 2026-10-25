"""Extract previously verified gate-only date/weekend/month tables without refitting."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ROOT = HERE.parents[2]
SOURCE = HERE.parent / "20261003_three_lateral_positions/outputs"


def main():
    checks = []
    for window in ["date", "weekend", "month"]:
        path = SOURCE / f"{window}_contrasts.csv"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        data = pd.read_csv(path)
        gate = data[data.point.eq("gate")].copy()
        destination = OUT / f"gate_{window}_periods.csv"
        gate.to_csv(destination, index=False)
        recovered = pd.read_csv(destination)
        assert len(gate) == len(recovered) and list(gate.columns) == list(recovered.columns)
        for column in gate:
            if pd.api.types.is_numeric_dtype(gate[column]):
                np.testing.assert_allclose(
                    gate[column], recovered[column], equal_nan=True, atol=1e-12
                )
            else:
                assert (
                    gate[column]
                    .fillna("")
                    .astype(str)
                    .reset_index(drop=True)
                    .eq(recovered[column].fillna("").astype(str))
                    .all()
                )
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        checks.append(
            {
                "window": window,
                "source": str(path.relative_to(ROOT)),
                "source_sha256": digest,
                "source_rows": len(data),
                "gate_rows": len(gate),
                "output": str(destination.relative_to(ROOT)),
                "passed": True,
            }
        )
    months = pd.read_csv(OUT / "gate_month_periods.csv")
    sign = months[months.distance_m.isna() & months.supported & months.q_month.lt(0.05)]
    sign.to_csv(OUT / "gate_significant_month_deviations.csv", index=False)
    report = {
        "passed": True,
        "refitted": False,
        "q_values_recomputed": False,
        "checks": checks,
        "supported_all_distance_month_q005_rows": len(sign),
        "meaning": (
            "Preserved gate-only three-contrast tables; q tests deviation "
            "from prior baseline, not actual advantage."
        ),
    }
    (OUT / "period_table_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
