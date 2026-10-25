"""Reproduce gate effects and compare Seoul 1600m with other distances."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PRIOR = HERE.parent / "20261002_gate_lateral_bias"
SOURCE = PRIOR / "outputs/runners.parquet"
DISTANCES = [1000, 1200, 1300, 1400, 1600, 1700, 1800, 2000]
SPEC = importlib.util.spec_from_file_location("gate_prior", PRIOR / "analyze.py")
LEGACY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEGACY)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adjust(pvalues):
    p = np.asarray(pvalues)
    order = np.argsort(p)
    m = len(p)
    holm = np.empty(m)
    bh = np.empty(m)
    holm[order] = np.minimum(1, np.maximum.accumulate(p[order] * (m - np.arange(m))))
    bh[order] = np.minimum(
        1, np.minimum.accumulate((p[order] * m / (np.arange(m) + 1))[::-1])[::-1]
    )
    return holm, bh


def fit(frame):
    controls, labels = LEGACY.controls(frame)
    design = np.column_stack(
        [
            frame.gate_side.eq("middle").to_numpy(float),
            frame.gate_side.eq("outer").to_numpy(float),
            controls,
        ]
    )
    race, race_keys = pd.factorize(frame.race_key)
    day, day_keys = pd.factorize(frame.day_key)
    counts = np.bincount(race)
    centered = design - pd.DataFrame(design).groupby(race).transform("mean").to_numpy()
    y = frame.top3.to_numpy(float)
    y = y - pd.Series(y).groupby(race).transform("mean").to_numpy()
    xw = centered / np.sqrt(counts[race, None])
    yw = y / np.sqrt(counts[race])
    gram = xw.T @ xw
    inverse = np.linalg.pinv(gram, rcond=1e-10)
    beta = inverse @ (xw.T @ yw)
    independent = np.linalg.lstsq(xw, yw, rcond=1e-10)[0]
    np.testing.assert_allclose(beta, independent, atol=1e-8, rtol=1e-8)
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    n, races, days = len(frame), len(race_keys), len(day_keys)
    correction = days / (days - 1) * (n - 1) / (n - races - rank)
    residual = yw - xw @ beta
    scores = pd.DataFrame(xw * residual[:, None]).groupby(day).sum().to_numpy()
    covariance = inverse @ (scores.T @ scores) @ inverse * correction
    projection = inverse @ gram
    vectors = {
        "inner_outer": np.eye(len(beta))[1] * -1,
        "inner_middle": np.eye(len(beta))[0] * -1,
        "outer_middle": np.eye(len(beta))[1] - np.eye(len(beta))[0],
    }
    result = {"runners": n, "races": races, "days": days, "rank": rank}
    for label, vector in vectors.items():
        assert np.max(np.abs(vector - vector @ projection)) < 1e-6
        effect = float(vector @ beta) * 100
        se = np.sqrt(max(0, float(vector @ covariance @ vector))) * 100
        cutoff = t.ppf(0.975, days - 1)
        result.update(
            {
                label + "_pp": effect,
                label + "_se": se,
                label + "_low": effect - cutoff * se,
                label + "_high": effect + cutoff * se,
            }
        )
    influence = scores @ inverse @ vectors["inner_outer"] * np.sqrt(correction) * 100
    np.testing.assert_allclose(influence @ influence, result["inner_outer_se"] ** 2)
    old, _ = LEGACY.gate_fit(frame)
    np.testing.assert_allclose(-old[0]["effect_pp"], result["inner_outer_pp"], atol=1e-8)
    np.testing.assert_allclose(
        -np.array(old[0]["ci95_pp"])[::-1],
        [result["inner_outer_low"], result["inner_outer_high"]],
        atol=1e-8,
    )
    return result, pd.Series(influence, index=day_keys)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if OUT.exists() and not args.refresh:
        raise FileExistsError("Refusing to overwrite analysis outputs")
    OUT.mkdir(exist_ok=True)
    paths = [
        SOURCE,
        PRIOR / "analyze.py",
        LEGACY.PRIOR / "analyze.py",
        PRIOR / "outputs/gate_results.json",
        HERE / "PLAN.md",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    data = pd.read_parquet(SOURCE)
    data = data[data.meet.eq(1) & data.distance_m.isin(DISTANCES)].copy()
    assert not data.duplicated(["race_key", "horse_number"]).any()
    assert (data.last_history_date.isna() | data.last_history_date.lt(data.dt)).all()
    dates1600 = set(data.loc[data.distance_m.eq(1600), "day_key"])
    full12keys = [
        key
        for key, g in data.groupby("race_key")
        if set(g.horse_number.astype(int)) == set(range(1, 13)) and len(g) == 12
    ]
    full10keys = [
        key
        for key, g in data.groupby("race_key")
        if set(g.horse_number.astype(int)) == set(range(1, 11)) and len(g) == 10
    ]
    windows = {
        "all": data,
        "2024plus": data[data.year.ge(2024)],
        "same_dates_as_1600": data[data.day_key.isin(dates1600)],
        "full12": data[data.race_key.isin(full12keys)],
        "posthoc_full10": data[data.race_key.isin(full10keys)],
    }
    results, comparisons, influences, raw, unsupported = [], [], [], [], []
    verification = []
    oldrows = json.loads((PRIOR / "outputs/gate_results.json").read_text())
    for window, sample in windows.items():
        estimates, scores = {}, {}
        for distance in DISTANCES:
            frame = sample[sample.distance_m.eq(distance)]
            meta = {"window": window, "distance_m": distance}
            races, days = frame.race_key.nunique(), frame.day_key.nunique()
            if races < 50 or days < 20:
                unsupported.append(meta | {"races": races, "days": days})
                continue
            estimate, influence = fit(frame)
            estimates[distance], scores[distance] = estimate, influence
            results.append(meta | estimate)
            influences.extend(
                meta | {"day_key": key, "influence_pp": float(value)}
                for key, value in influence.items()
            )
            cells = frame.groupby(["race_key", "gate_side"]).top3.mean().unstack()
            for side in ["inner", "middle", "outer"]:
                raw.append(meta | {"side": side, "race_equal_top3": float(cells[side].mean())})
            if window in ["all", "2024plus"]:
                legacy = next(
                    x
                    for x in oldrows
                    if x["meet"] == 1
                    and x["period"] == window
                    and x["scope"] == "distance"
                    and x["distance_m"] == distance
                )
                error = abs(estimate["inner_outer_pp"] + legacy["effect_pp"])
                assert error < 1e-7
                verification.append(meta | {"original_effect_error_pp": error})
        if 1600 not in estimates:
            continue
        rows = []
        for distance in estimates:
            if distance == 1600:
                continue
            aligned = pd.concat([scores[1600], scores[distance]], axis=1).fillna(0).to_numpy()
            variance = float(np.square(aligned[:, 0] - aligned[:, 1]).sum())
            covariance = float(aligned[:, 0] @ aligned[:, 1])
            independent_variance = (
                estimates[1600]["inner_outer_se"] ** 2
                + estimates[distance]["inner_outer_se"] ** 2
                - 2 * covariance
            )
            np.testing.assert_allclose(variance, independent_variance, atol=1e-9)
            delta = estimates[1600]["inner_outer_pp"] - estimates[distance]["inner_outer_pp"]
            se = np.sqrt(variance)
            df = min(estimates[1600]["days"], estimates[distance]["days"]) - 1
            cutoff = t.ppf(0.975, df)
            rows.append(
                {
                    "window": window,
                    "other_distance_m": distance,
                    "advantage_1600_pp": estimates[1600]["inner_outer_pp"],
                    "advantage_other_pp": estimates[distance]["inner_outer_pp"],
                    "difference_pp": delta,
                    "se": se,
                    "ci_low": delta - cutoff * se,
                    "ci_high": delta + cutoff * se,
                    "df": df,
                    "shared_date_covariance": covariance,
                    "p": float(2 * t.sf(abs(delta / se), df)),
                }
            )
        holm, bh = adjust([r["p"] for r in rows])
        for row, h, b in zip(rows, holm, bh, strict=True):
            row.update(
                {
                    "holm": float(h),
                    "bh": float(b),
                    "stronger_holm": bool(h < 0.05 and row["difference_pp"] > 0),
                }
            )
        comparisons.extend(rows)
    pd.DataFrame(results).to_csv(OUT / "distance_effects.csv", index=False)
    pd.DataFrame(comparisons).to_csv(OUT / "distance_comparisons.csv", index=False)
    pd.DataFrame(raw).to_csv(OUT / "raw_gate_rates.csv", index=False)
    pd.DataFrame(influences).to_parquet(OUT / "day_influences.parquet", index=False)
    pd.DataFrame(unsupported).to_csv(OUT / "unsupported.csv", index=False)
    year_counts = (
        data[data.distance_m.eq(1600)]
        .groupby("year")
        .agg(
            runners=("horse_id", "size"), races=("race_key", "nunique"), days=("day_key", "nunique")
        )
    )
    year_counts.to_csv(OUT / "seoul1600_year_counts.csv")
    field_counts = data.drop_duplicates("race_key").groupby(["distance_m", "n"]).size()
    field_counts.rename("races").to_csv(OUT / "field_size_counts.csv")
    pd.DataFrame(verification).to_csv(OUT / "legacy_reproduction.csv", index=False)
    for name, digest in hashes.items():
        assert sha(ROOT / name) == digest
    audit = {
        "passed": True,
        "input_hashes": hashes,
        "source_rows": len(data),
        "source_races": int(data.race_key.nunique()),
        "source_horses": int(data.horse_id.nunique()),
        "models_lstsq_and_legacy_solver_checked": len(results),
        "original_result_rows_checked": len(verification),
        "cross_distance_variances_checked": len(comparisons),
        "unsupported_cells": unsupported,
        "new_outlier_removal": False,
        "forecast_validation": False,
        "seconds_correction_adopted": False,
    }
    (OUT / "verification.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(
        pd.DataFrame(results)[
            ["window", "distance_m", "races", "days", "inner_outer_pp"]
        ].to_string(index=False)
    )
    print(
        pd.DataFrame(comparisons)[
            [
                "window",
                "other_distance_m",
                "difference_pp",
                "ci_low",
                "ci_high",
                "holm",
                "stronger_holm",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
