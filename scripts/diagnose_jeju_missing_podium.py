"""Descriptive error audit of the frozen reference; never used to fit a rule."""

import json

import numpy as np
import polars as pl

from scripts.run_jeju_set_interaction import OUT, V7, load_frame, save

FIELDS = [
    "global_elo_pre",
    "distance_elo_pre",
    "distance_starts_pre",
    "days_since_previous_start",
    "historical_early_front_rate",
    "closing_speed_quality_mean_3",
    "current_vs_previous_rival_elo",
    "declared_horse_number_fraction",
    "declared_burden_kg",
    "current_minus_last_burden_kg",
    "body_weight_delta_kg",
    "jockey_changed",
    "distance_surprise_mean3",
    "distance_valid_count6",
]


def main():
    frame, _, truth, _ = load_frame()
    ev = frame.filter(pl.col("event_date").dt.year() == 2025)
    lookup = {(r["race_id"], r["horse_id"]): r for r in ev.iter_rows(named=True)}
    old = pl.read_parquet(V7 / "race_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    overlaps = {str(i): 0 for i in range(4)}
    pairs = []
    races = []
    for r in old.iter_rows(named=True):
        rid = r["race_id"]
        chosen = set(r["predicted_set"])
        accepted = {tuple(sorted(o)) for o in truth[rid]}
        overlap = max(len(chosen & set(s)) for s in accepted)
        overlaps[str(overlap)] += 1
        races.append(
            dict(
                race_id=rid,
                fold=r["fold"],
                distance_m=r["distance_m"],
                field_size=r["field_size"],
                overlap=overlap,
                boundary_tie=r["boundary_tie"],
            )
        )
        if overlap != 2 or r["boundary_tie"]:
            continue
        assert len(accepted) == 1
        actual = set(next(iter(accepted)))
        missed = next(iter(actual - chosen))
        extra = next(iter(chosen - actual))
        m, e = lookup[(rid, missed)], lookup[(rid, extra)]
        row = dict(
            race_id=rid,
            event_date=r["event_date"],
            missing_horse_id=missed,
            selected_nonpodium_horse_id=extra,
        )
        for c in FIELDS:
            row["missing__" + c] = m[c]
            row["selected__" + c] = e[c]
        pairs.append(row)
    pl.DataFrame(pairs, infer_schema_length=None).write_parquet(OUT / "missing_horse_pairs.parquet")
    result = []
    for c in FIELDS:
        a = np.array(
            [p["missing__" + c] if p["missing__" + c] is not None else np.nan for p in pairs], float
        )
        b = np.array(
            [p["selected__" + c] if p["selected__" + c] is not None else np.nan for p in pairs],
            float,
        )
        ok = np.isfinite(a) & np.isfinite(b)
        result.append(
            dict(
                feature=c,
                paired_observations=int(ok.sum()),
                missing_horse_missing_values=int((~np.isfinite(a)).sum()),
                selected_horse_missing_values=int((~np.isfinite(b)).sum()),
                mean_missing_minus_selected=float(np.mean(a[ok] - b[ok])) if ok.any() else None,
                median_missing=float(np.median(a[ok])) if ok.any() else None,
                median_selected=float(np.median(b[ok])) if ok.any() else None,
            )
        )
    slices = []
    rf = pl.DataFrame(races)
    for dim in ["fold", "distance_m", "field_size"]:
        for val in sorted(rf[dim].unique()):
            s = rf.filter(pl.col(dim) == val)
            slices.append(
                dict(
                    dimension=dim,
                    value=str(val),
                    races=len(s),
                    two_correct=int((s["overlap"] == 2).sum()),
                    three_correct=int((s["overlap"] == 3).sum()),
                )
            )
    save(
        "missing_horse_diagnostic.json",
        dict(
            reference="HY_R_FORM",
            posthoc=True,
            source_manifest=str(V7 / "manifest.json"),
            races=len(old),
            overlap_counts=overlaps,
            pair_races=len(pairs),
            excluded_boundary_tie_two_correct=overlaps["2"] - len(pairs),
            pair_definition="Non-boundary races with exactly two correct: one omitted podium horse "
            "versus one selected nonpodium horse; equal race weights, no causal claim.",
            diagnostic_not_training_filter=True,
            paired_features=result,
            slices=slices,
        ),
    )
    print(json.dumps(dict(overlap_counts=overlaps, pair_races=len(pairs))))


if __name__ == "__main__":
    main()
