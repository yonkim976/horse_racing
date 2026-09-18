"""Explicitly posthoc class-transition audit discovered during case review."""

import json
import re
from datetime import UTC, datetime

import numpy as np
import polars as pl

from scripts.audit_jeju_error_conditions import OUT, V5, paired_stats, save


def grade(value):
    m = re.fullmatch(r"제([1-6])등급", str(value))
    return int(m.group(1)) if m else None


def main():
    save(
        "grade_supplement_protocol.json",
        dict(
            created_at=datetime.now(UTC).isoformat(),
            status="Posthoc expansion after primary audit; exploratory, not predeclared evidence.",
            reason="Top-error case had grade4->5 vs6->5. Official2025 plan changes grade/rating regime.",  # noqa: E501
            rule="Numeric1..6 only; transitions restricted to previous and current event in2025. Unknown/OPEN/cross-year excluded.",  # noqa: E501
            source_url="https://race.kra.co.kr/down/raceplan2025_jeju.pdf",
            source_pages="PDF pages4,8,12 (1-based)",
            official_summary="2025 grade thresholds changed; existing official ratings reduced35 points. Grade6 is unrated and grade5 promotion has prize/rating criteria.",  # noqa: E501
            distinction="Official rating is not our Elo. This does not justify subtracting35 from Elo.",  # noqa: E501
            fits=0,
        ),
    )
    e = {
        r["entry_id"]: r
        for r in [json.loads(x) for x in (OUT / "source_evidence.jsonl").read_text().splitlines()]
    }
    p = json.loads((V5 / "protocol.json").read_text())
    fields = p["base_features"] + p["context_features"] + p["form_features"]
    rows = []
    for r in pl.read_parquet(OUT / "entry_conditions.parquet").iter_rows(named=True):
        cur = grade(e[r["entry_id"]]["grade"])
        previous = grade(e.get(r["previous_entry_id"], {}).get("grade"))
        sameyear = bool(r["previous_date"] and r["previous_date"].startswith("2025"))
        comparable = sameyear and cur is not None and previous is not None
        rows.append(
            dict(
                entry_id=r["entry_id"],
                race_id=r["race_id"],
                event_date=r["event_date"],
                grade_now=cur,
                grade_previous=previous,
                comparable_2025=comparable,
                grade6_to5=float(previous == 6 and cur == 5) if comparable else None,
                grade_number_decrease=float(cur < previous) if comparable else None,
                grade_number_increase=float(cur > previous) if comparable else None,
            )
        )
    gf = pl.DataFrame(rows, infer_schema_length=None)
    gf.write_parquet(OUT / "grade_conditions.parquet")
    g = {r["entry_id"]: r for r in rows}
    pairs = []
    for pair in pl.read_parquet(OUT / "paired_conditions.parquet").iter_rows(named=True):
        row = {"event_date": pair["event_date"], "race_id": pair["race_id"]}
        for prefix, key in [("missed", "missed_entry_id"), ("selected", "selected_entry_id")]:
            for k in ["grade6_to5", "grade_number_decrease", "grade_number_increase"]:
                row[prefix + "__" + k] = g[pair[key]][k]
        pairs.append(row)
    paired = paired_stats(pairs, ["grade6_to5", "grade_number_decrease", "grade_number_increase"])
    joint = (
        pl.read_parquet(OUT / "entry_conditions.parquet")
        .join(gf.select("entry_id", "grade6_to5", "comparable_2025"), on="entry_id", validate="1:1")
        .filter(~pl.col("boundary_tie"))
    )
    groups = []
    for selected in [None, True, False]:
        part = joint if selected is None else joint.filter(pl.col("selected") == selected)
        for value in [0.0, 1.0]:
            s = part.filter(pl.col("grade6_to5") == value)
            daily = (
                s.group_by("event_date")
                .agg(
                    (pl.col("place_probability") - pl.col("official_top3").cast(pl.Float64))
                    .sum()
                    .alias("error"),
                    pl.len().alias("n"),
                )
                .sort("event_date")
            )
            if len(daily):
                draws = np.random.default_rng(17).integers(0, len(daily), (5000, len(daily)))
                boot = daily["error"].to_numpy()[draws].sum(axis=1) / daily["n"].to_numpy()[
                    draws
                ].sum(axis=1)
                bias_ci = np.quantile(boot, [0.025, 0.975]).tolist()
            else:
                bias_ci = None
            groups.append(
                dict(
                    bias_day_ci=bias_ci,
                    population="all"
                    if selected is None
                    else "selected3"
                    if selected
                    else "not_selected",
                    grade6_to5=value,
                    entries=len(s),
                    races=s["race_id"].n_unique(),
                    observed_rate=float(s["official_top3"].mean()) if len(s) else None,
                    mean_probability=float(s["place_probability"].mean()) if len(s) else None,
                )
            )
    save(
        "grade_transition_diagnostic.json",
        dict(
            posthoc=True,
            paired=paired,
            full_population=groups,
            model_has_current_grade="declared_grade_number" in fields,
            model_has_explicit_grade_transition=any(
                "grade" in f and ("change" in f or "previous" in f) for f in fields
            ),
            caution="Not causal, unadjusted exploratory comparisons; excludes cross-year for official2025 regime change. No refit.",  # noqa: E501
        ),
    )
    print(json.dumps(paired + groups, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
