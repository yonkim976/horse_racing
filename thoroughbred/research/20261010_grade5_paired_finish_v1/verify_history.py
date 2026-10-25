"""Reconstruct actual slots and same-start peer means independently."""

import numpy as np
import pandas as pd
import run as r


def main():
    r.check()
    d = pd.read_parquet(r.SOURCE)
    targets = d[(1 - d.base_risk >= 0.7) & d.axis_grade.eq(5)]
    h = pd.read_parquet(r.build.HISTORY)
    history = {
        horse: g.sort_values("race_date", ascending=False) for horse, g in h.groupby("horse_id")
    }
    a = pd.read_parquet(r.build.OBS)
    a["race_key"] = a.source_key.str.replace("서울:", "1:", regex=False).str.replace(
        "부산:", "3:", regex=False
    )
    a = a.merge(
        pd.read_parquet(r.build.CORRECTIONS), on="row_key", how="left", validate="one_to_one"
    )
    races = {key: g for key, g in a.groupby("race_key")}
    paired = pd.read_parquet(r.OUT / "paired_features.parquet").set_index("race_key")
    slots = pd.read_parquet(r.OUT / "paired_history_slots.parquet")
    by_current = {key: g.sort_values("slot") for key, g in slots.groupby("current_race_key")}
    cached = {}

    def context(key, horse):
        pair = (key, horse)
        if pair in cached:
            return cached[pair]
        result = {}
        if key not in races or not races[key].horse_id.eq(horse).any():
            for n in ["early", "g3", "g1"]:
                result[n + "_seconds"] = result[n + "_adv"] = result[n + "_peers"] = result[
                    n + "_coverage"
                ] = np.nan
                result[n + "_supported"] = False
        else:
            group = races[key]
            selfrow = group[group.horse_id.eq(horse)].iloc[0]
            for name, col in [("early", "early"), ("g3", "last600"), ("g1", "late")]:
                corrected = group[col + "_adjusted"].combine_first(group[col])
                v = selfrow[col + "_adjusted"]
                if not np.isfinite(v):
                    v = selfrow[col]
                other = corrected[group.horse_id.ne(horse)].dropna()
                coverage = corrected.notna().sum() / selfrow.field_size
                adv = (
                    other.mean() - v
                    if np.isfinite(v) and len(other) >= 5 and coverage >= 0.8
                    else np.nan
                )
                adv = float(np.round(adv, 10))
                result[name + "_seconds"], result[name + "_adv"] = v, adv
                result[name + "_peers"], result[name + "_coverage"] = len(other), coverage
                flag = selfrow[col + "_correction_supported"]
                result[name + "_supported"] = pd.notna(flag) and bool(flag)
        valid = np.isfinite([result[n + "_adv"] for n in ["early", "g3", "g1"]]).all()
        result["valid"] = valid
        result["fast"] = valid and result["early_adv"] > 0
        result["keep"] = result["fast"] and result["g3_adv"] >= 0 and result["g1_adv"] >= 0
        cached[pair] = result
        return result

    checked = 0
    for axis in targets.itertuples():
        cutoff = axis.race_date - pd.Timedelta(days=2)
        hg = history.get(axis.axis_horse_id, h.iloc[:0])
        eligible = hg[
            (hg.race_date <= cutoff) & (hg.race_date >= axis.race_date - pd.Timedelta(days=730))
        ].head(5)
        stored = by_current.get(axis.race_key, slots.iloc[:0])
        assert eligible.race_key.tolist() == stored.history_race_key.tolist()
        assert stored.slot.tolist() == list(range(1, len(eligible) + 1))
        assert stored.horse_id.eq(axis.axis_horse_id).all()
        assert stored.cutoff_date.eq(cutoff).all()
        values = []
        for prior, st in zip(eligible.itertuples(), stored.itertuples(), strict=True):
            assert prior.race_date == st.history_date and st.history_date <= cutoff
            assert prior.race_key != axis.race_key
            v = context(prior.race_key, axis.axis_horse_id)
            for k, val in v.items():
                if k.endswith("_supported"):
                    flag = getattr(st, k)
                    assert (pd.notna(flag) and bool(flag)) == val
                elif k in ["valid", "fast", "keep"]:
                    assert getattr(st, k) == val
                else:
                    assert np.allclose(getattr(st, k), val, atol=1e-12, rtol=0, equal_nan=True), k
            values.append(v)
            checked += 1
        fast = [v for v in values if v["fast"]]
        n = len(fast)
        keep = sum(v["keep"] for v in fast)
        expected = dict(
            paired_valid_n=sum(v["valid"] for v in values),
            paired_fast_n=n,
            paired_keep_n=keep,
            paired_g3=np.mean([v["g3_adv"] for v in fast]) * n / (n + 3) if n else np.nan,
            paired_g1=np.mean([v["g1_adv"] for v in fast]) * n / (n + 3) if n else np.nan,
            paired_keep_rate=(keep + 1) / (n + 2) if n else np.nan,
        )
        row = paired.loc[axis.race_key]
        for k, val in expected.items():
            assert np.allclose(row[k], val, atol=1e-12, rtol=0, equal_nan=True), k
        assert (
            pd.isna(row.paired_source_max) and len(eligible) == 0
        ) or row.paired_source_max == eligible.race_date.max()
    assert len(paired) == len(targets) == 593 and checked == len(slots)
    # Check support and the fixed profile labels without using their builder.
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    expected = np.where(
        p.paired_fast_n.eq(0),
        "no_fast_history",
        np.where(
            p.paired_fast_n.eq(1),
            "one_fast_history",
            np.where(
                p.paired_keep_rate.lt(0.5), "supported_low_retention", "supported_high_retention"
            ),
        ),
    )
    assert np.array_equal(p.profile, expected)
    coverage = pd.read_csv(r.OUT / "coverage.csv")
    for year, g in p[p.is_target].groupby("year"):
        row = coverage[coverage.year.eq(year)].iloc[0]
        assert [row.n, row.no_valid, row.no_fast, row.one_fast, row.two_plus_fast] == [
            len(g),
            g.paired_valid_n.eq(0).sum(),
            g.paired_fast_n.eq(0).sum(),
            g.paired_fast_n.eq(1).sum(),
            g.paired_fast_n.ge(2).sum(),
        ]
    r.save(
        r.OUT / "history_verification.json",
        dict(
            status="passed",
            target_axis_rows=593,
            actual_slots_checked=checked,
            unique_history_contexts=len(cached),
            self_excluded_peer_means="passed",
            same_start_pairing="passed",
            T_minus_2_and_730_days="passed",
            missing_slots_not_skipped="passed",
            conditional_features="passed",
        ),
    )
    r.check()
    print("Independent history verification passed", checked, len(cached))


if __name__ == "__main__":
    main()
