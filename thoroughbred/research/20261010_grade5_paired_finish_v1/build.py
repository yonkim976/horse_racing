"""Pair all three sections within a historical start; preserve actual slots."""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
S = R / "20261009_section_style_finish_v1/outputs"
HISTORY = S / "history_observations.parquet"
OBS = R / "20261008_field_pace_prediction/outputs/observations.parquet"
CORRECTIONS = S / "section_corrections.parquet"
PARTS = {"early": "early", "g3": "last600", "g1": "late"}


def contexts():
    cols = ["row_key", "source_key", "horse_id", "gate", "date", "field_size", *PARTS.values()]
    a = pd.read_parquet(OBS, columns=cols)
    a["race_key"] = a.source_key.str.replace("서울:", "1:", regex=False).str.replace(
        "부산:", "3:", regex=False
    )
    assert not a.duplicated(["race_key", "horse_id"]).any()
    corr = pd.read_parquet(CORRECTIONS)
    a = a.merge(corr, on="row_key", how="left", validate="one_to_one")
    for short, col in PARTS.items():
        adj = a[col + "_adjusted"].where(a[col + "_adjusted"].notna(), a[col])
        a[short + "_seconds"] = adj
        a[short + "_supported"] = a[col + "_correction_supported"].eq(True)
        grouped = adj.groupby(a.race_key)
        count, total = grouped.transform("count"), grouped.transform("sum")
        other = count - adj.notna().astype(int)
        good = adj.notna() & other.ge(5) & count.ge(0.8 * a.field_size)
        a[short + "_adv"] = ((total - adj) / other - adj).where(good).round(10)
        a[short + "_peers"] = other
        a[short + "_coverage"] = count / a.field_size
    a["valid"] = a[[n + "_adv" for n in PARTS]].notna().all(axis=1)
    a["fast"] = a.valid & a.early_adv.gt(0)
    a["keep"] = a.fast & a.g3_adv.ge(0) & a.g1_adv.ge(0)
    return a


def prepare(d):
    h = pd.read_parquet(
        HISTORY, columns=["race_key", "program_no", "horse_id", "race_date", "result_distance"]
    )
    assert not h.duplicated(["horse_id", "race_date"]).any()
    a = contexts()
    context_cols = ["race_key", "horse_id", "valid", "fast", "keep"] + [
        n + s for n in PARTS for s in ["_seconds", "_supported", "_adv", "_peers", "_coverage"]
    ]
    h = h.merge(a[context_cols], on=["race_key", "horse_id"], how="left", validate="one_to_one")
    h = h.sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    dates = h.race_date.to_numpy("datetime64[D]")
    groups = h.groupby("horse_id", sort=False).indices
    rows, features = [], []
    for axis in d.itertuples():
        if not ((1 - axis.base_risk) >= 0.7 and axis.axis_grade == 5):
            continue
        current = np.datetime64(axis.race_date, "D")
        cutoff = current - np.timedelta64(2, "D")
        ix = groups.get(axis.axis_horse_id, np.array([], dtype=int))
        past = ix[(dates[ix] <= cutoff) & ((current - dates[ix]).astype(int) <= 730)]
        use = past[-5:][::-1]
        g = h.iloc[use]
        for slot, (_, v) in enumerate(g.iterrows(), 1):
            rows.append(
                dict(
                    current_race_key=axis.race_key,
                    current_date=axis.race_date,
                    horse_id=axis.axis_horse_id,
                    slot=slot,
                    cutoff_date=pd.Timestamp(cutoff),
                    history_race_key=v.race_key,
                    history_date=v.race_date,
                    history_distance=v.result_distance,
                    valid=pd.notna(v.valid) and bool(v.valid),
                    fast=pd.notna(v.fast) and bool(v.fast),
                    keep=pd.notna(v.keep) and bool(v.keep),
                    **{
                        n + s: v[n + s]
                        for n in PARTS
                        for s in ["_seconds", "_supported", "_adv", "_peers", "_coverage"]
                    },
                )
            )
        valid = g.valid.eq(True)
        fast = g.fast.eq(True)
        n, keep = int(fast.sum()), int(g.keep.eq(True).sum())
        features.append(
            dict(
                race_key=axis.race_key,
                paired_valid_n=int(valid.sum()),
                paired_fast_n=n,
                paired_keep_n=keep,
                paired_g3=float(g.loc[fast, "g3_adv"].mean() * n / (n + 3)) if n else np.nan,
                paired_g1=float(g.loc[fast, "g1_adv"].mean() * n / (n + 3)) if n else np.nan,
                paired_keep_rate=(keep + 1) / (n + 2) if n else np.nan,
                paired_source_max=g.race_date.max() if len(g) else pd.NaT,
            )
        )
    return pd.DataFrame(features), pd.DataFrame(rows)
