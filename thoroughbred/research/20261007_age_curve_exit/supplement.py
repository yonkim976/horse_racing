"""Post-result coverage and valid-final-start sensitivity; no primary model refit."""

import json
from pathlib import Path

import pandas as pd
from analyze import estimate

OUT = Path(__file__).resolve().parent / "outputs"


def main():
    landmarks = pd.read_parquet(OUT / "annual_followup_landmarks.parquet")
    coverage = (
        landmarks.groupby(["meet", "age_bin", "no_start_365"], dropna=False)
        .agg(
            landmarks=("row_key", "size"),
            six_valid_times=("six_available", "sum"),
            context_available=("context_seconds_per60_change", "count"),
            final_start_valid=("anchor_time_available", "sum"),
        )
        .reset_index()
    )
    coverage["context_coverage"] = coverage.context_available / coverage.landmarks
    coverage.to_csv(OUT / "trend_coverage.csv", index=False)
    rows = []
    for col in ["raw_seconds_per60_change", "context_seconds_per60_change"]:
        q = landmarks[landmarks.anchor_time_available.eq(True) & landmarks[col].notna()]
        for (meet, status), g in q.groupby(["meet", "no_start_365"]):
            rows.append(
                dict(
                    meet=meet,
                    inactive=bool(status),
                    metric=col,
                    sensitivity="posthoc_final_start_has_valid_time",
                )
                | estimate(g, col)
                | dict(not_worse_share=float(g[col].le(0).mean()))
            )
    sensitivity = pd.DataFrame(rows)
    sensitivity.to_csv(OUT / "valid_final_start_sensitivity.csv", index=False)
    # Independent direct checks against the persisted landmark rows.
    for r in sensitivity.itertuples():
        g = landmarks[
            landmarks.meet.eq(r.meet)
            & landmarks.no_start_365.astype(bool).eq(r.inactive)
            & landmarks.anchor_time_available.eq(True)
            & landmarks[r.metric].notna()
        ]
        assert len(g) == r.rows and abs(g[r.metric].mean() - r.mean) < 1e-12
        assert abs(g[r.metric].le(0).mean() - r.not_worse_share) < 1e-12
    web = json.loads((OUT / "web_age_curve_exit.json").read_text())
    web["trend_coverage"] = json.loads(coverage.to_json(orient="records", force_ascii=False))
    web["posthoc_valid_final_start_sensitivity"] = json.loads(
        sensitivity.to_json(orient="records", force_ascii=False)
    )
    (OUT / "web_age_curve_exit.json").write_text(
        json.dumps(web, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    (OUT / "supplement_verification.json").write_text(
        json.dumps(
            dict(
                passed=True,
                posthoc=True,
                coverage_rows=len(coverage),
                final_start_sensitivity_rows=len(rows),
                primary_model_refitted=False,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(sensitivity.to_string(index=False))


if __name__ == "__main__":
    main()
