"""Matched before/after record summaries and tie-aware within-horse comparisons."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("history_application", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
EPS = 1e-8


def stats(g, part):
    old, new, delta = (g[f"{prefix}_{part}"] for prefix in ["raw", "adjusted", "add"])
    good = old.notna() & new.notna()
    old, new, delta = old[good], new[good], delta[good]
    if not len(delta):
        return None
    return dict(
        rows=len(delta),
        horses=int(g.loc[good].horse_id.nunique()),
        raw_mean=float(old.mean()),
        adjusted_mean=float(new.mean()),
        delta_mean=float(delta.mean()),
        delta_median=float(delta.median()),
        mean_absolute_delta=float(abs(delta).mean()),
        delta_p10=float(delta.quantile(0.1)),
        delta_p90=float(delta.quantile(0.9)),
        delta_min=float(delta.min()),
        delta_max=float(delta.max()),
        abs_ge_01_rate=float(abs(delta).ge(0.1 - EPS).mean()),
        abs_ge_02_rate=float(abs(delta).ge(0.2 - EPS).mean()),
    )


def horse_comparisons(d):
    keys = ["meet", "horse_id", "distance_m"]
    good = d[d.complete].copy()
    good = good[good.groupby(keys).row_key.transform("size").ge(2)]
    bests, trends = [], []
    for part in A.TARGETS:
        old, new = f"raw_{part}", f"adjusted_{part}"
        z = good.copy()
        z["raw_min"] = z.groupby(keys)[old].transform("min")
        raw_best = (
            z[z[old].sub(z.raw_min).abs().lt(EPS)]
            .sort_values([new, "date", "row_key"])
            .drop_duplicates(keys)
        )
        adjusted_best = z.sort_values([new, "date", "row_key"]).drop_duplicates(keys)
        cols = keys + ["row_key", "horse_name", "date", old, new]
        paired = raw_best[cols].merge(
            adjusted_best[cols],
            on=keys,
            validate="one_to_one",
            suffixes=("_raw_best", "_adjusted_best"),
        )
        paired["section"] = part
        paired["changed_best"] = paired[new + "_raw_best"] - paired[new + "_adjusted_best"] > EPS
        paired["raw_record_gap"] = paired[old + "_adjusted_best"] - paired[old + "_raw_best"]
        paired["adjusted_preference_gap"] = (
            paired[new + "_raw_best"] - paired[new + "_adjusted_best"]
        )
        paired["records"] = pd.MultiIndex.from_frame(paired[keys]).map(good.groupby(keys).size())
        bests.append(paired)
        order = z.sort_values(keys + ["date", "row_key"])
        order["previous_key"] = order.groupby(keys).row_key.shift()
        order["raw_change"] = order[old] - order.groupby(keys)[old].shift()
        order["adjusted_change"] = order[new] - order.groupby(keys)[new].shift()
        order = order[order.previous_key.notna()]
        order["flip"] = ((order.raw_change > EPS) & (order.adjusted_change < -EPS)) | (
            (order.raw_change < -EPS) & (order.adjusted_change > EPS)
        )
        for venue, group in order.groupby("meet"):
            trends.append(
                dict(
                    meet=venue,
                    section=part,
                    pairs=len(group),
                    strict_direction_flips=int(group.flip.sum()),
                    raw_ties=int(group.raw_change.abs().lt(EPS).sum()),
                    flipped_raw_gap_ge_01=int(
                        (group.flip & group.raw_change.abs().ge(0.1 - EPS)).sum()
                    ),
                )
            )
    best = pd.concat(bests, ignore_index=True)
    best.to_parquet(OUT / "horse_best_record_comparisons.parquet", index=False)
    pd.DataFrame(trends).to_csv(OUT / "consecutive_record_comparisons.csv", index=False)
    best.groupby(["meet", "section"]).agg(
        groups=("horse_id", "size"),
        changed_best=("changed_best", "sum"),
        changed_rate=("changed_best", "mean"),
    ).reset_index().to_csv(OUT / "horse_best_summary.csv", index=False)
    cases = best[best.changed_best & best.section.eq("finish")].copy()
    chosen = []
    for _, g in cases.groupby(["meet", "distance_m"]):
        row = g.iloc[np.argmin(abs(g.adjusted_preference_gap - g.adjusted_preference_gap.median()))]
        chosen += [row.row_key_raw_best, row.row_key_adjusted_best]
    d[d.row_key.isin(chosen)].sort_values(["meet", "distance_m", "horse_id", "date"])[
        A.META + [f"{prefix}_{part}" for part in A.TARGETS for prefix in ["raw", "add", "adjusted"]]
    ].to_csv(OUT / "changed_horse_examples.csv", index=False)


def race_orders(d):
    rows = []
    for (venue, race), g in d[d.complete].groupby(["meet", "race_key"]):
        if len(g) != int(g.n.iloc[0]):
            continue
        ix, jx = np.triu_indices(len(g), 1)
        raw = g.raw_finish.to_numpy()[ix] - g.raw_finish.to_numpy()[jx]
        adj = g.adjusted_finish.to_numpy()[ix] - g.adjusted_finish.to_numpy()[jx]
        flips = ((raw > EPS) & (adj < -EPS)) | ((raw < -EPS) & (adj > EPS))
        for term in ["moisture", "month"]:
            assert g[f"{term}_add_finish"].max() - g[f"{term}_add_finish"].min() < EPS
        gate = g.gate_add_finish.to_numpy()[ix] - g.gate_add_finish.to_numpy()[jx]
        assert np.allclose(adj - raw, gate, atol=EPS)
        rows.append(
            dict(
                meet=venue,
                race_key=race,
                n=len(g),
                pairs=len(raw),
                strict_flips=int(flips.sum()),
                raw_ties=int((abs(raw) < EPS).sum()),
                raw_ties_split=int(((abs(raw) < EPS) & (abs(adj) > EPS)).sum()),
                flipped_raw_gap_ge_01=int((flips & (abs(raw) >= 0.1 - EPS)).sum()),
            )
        )
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "within_race_time_orders.csv", index=False)
    r.groupby("meet").agg(
        races=("race_key", "size"),
        pairs=("pairs", "sum"),
        races_with_flips=("strict_flips", lambda x: int(x.gt(0).sum())),
        strict_flips=("strict_flips", "sum"),
        raw_ties=("raw_ties", "sum"),
        raw_ties_split=("raw_ties_split", "sum"),
    ).reset_index().to_csv(OUT / "within_race_time_order_summary.csv", index=False)


def main():
    d = pd.read_parquet(OUT / "core_historical_records.parquet")
    alt = pd.read_parquet(OUT / "alternate_historical_records.parquet")
    coverage = []
    for key, g in d.groupby(["meet", "distance_m"]):
        coverage.append(
            dict(
                meet=key[0],
                distance_m=int(key[1]),
                rows=len(g),
                complete=int(g.complete.sum()),
                complete_rate=float(g.complete.mean()),
                estimation_rows=int(g.estimation_keep.sum()),
                complete_outside_estimation=int((g.complete & ~g.estimation_keep).sum()),
                partial_finish=int(g.partial_add_finish.notna().sum()),
            )
        )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    summaries = []
    for cohort in ["all_applied", "estimation_only"]:
        b = d[d.complete & (d.estimation_keep if cohort == "estimation_only" else True)]
        for dimensions in [
            ["meet"],
            ["meet", "distance_m"],
            ["meet", "distance_m", "band"],
            ["meet", "distance_m", "month"],
            ["meet", "distance_m", "gate_block", "gate_level"],
        ]:
            for key, g in b.groupby(dimensions, observed=True):
                key = key if isinstance(key, tuple) else (key,)
                for part in A.TARGETS:
                    row = stats(g, part)
                    if row:
                        summaries.append(
                            dict(zip(dimensions, key, strict=True))
                            | dict(cohort=cohort, grain="+".join(dimensions), section=part)
                            | row
                        )
    pd.DataFrame(summaries).to_csv(OUT / "before_after_summary.csv", index=False)
    alternative = []
    targets = [
        c.removeprefix("raw_") for c in alt if c.startswith("raw_") and c != "raw_partition_valid"
    ]
    for (venue, dist, scope), g in alt[alt.complete].groupby(["meet", "distance_m", "scope"]):
        for part in targets:
            row = stats(g, part)
            if row:
                alternative.append(
                    dict(meet=venue, distance_m=int(dist), scope=scope, section=part) | row
                )
    pd.DataFrame(alternative).to_csv(OUT / "alternate_before_after_summary.csv", index=False)
    chosen = []
    for _, g in d[d.complete].groupby(["meet", "distance_m", "band"]):
        chosen.append(g.iloc[np.argmin(abs(g.add_finish - g.add_finish.median()))].row_key)
    for _, g in d[d.complete].groupby("meet"):
        chosen += (
            g.nsmallest(2, "add_finish").row_key.tolist()
            + g.nlargest(2, "add_finish").row_key.tolist()
        )
    d[d.row_key.isin(chosen)][
        A.META
        + ["scope", "complete"]
        + [
            c
            for c in d
            if c.startswith(
                ("raw_", "add_", "adjusted_", "moisture_add_", "month_add_", "gate_add_")
            )
        ]
    ].to_csv(OUT / "record_examples.csv", index=False)
    horse_comparisons(d)
    race_orders(d)
    A.dump(
        OUT / "summary_complete.json",
        dict(
            records=len(d),
            complete=int(d.complete.sum()),
            alternate_complete=int(alt.complete.sum()),
            coefficient_refit=False,
            production_changed=False,
            prediction_validation=False,
        ),
    )
    print("before/after and horse comparisons saved")


if __name__ == "__main__":
    main()
