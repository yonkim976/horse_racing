"""Independently check gate coefficients and cross-distance date covariance using FWL."""

import json

import analyze as study
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control, t


def main():
    source = pd.read_parquet(study.SOURCE)
    data = source[source.meet.eq(3) & source.distance_m.isin(study.DISTANCES)].copy()
    frames = study.samples(data)
    effects = pd.read_csv(study.OUT / "distance_effects.csv")
    pairs = pd.read_csv(study.OUT / "distance_comparisons.csv")
    scores = pd.read_parquet(study.OUT / "day_influences.parquet")
    recalculated, errors = {}, []
    for row in effects.itertuples():
        f = frames[row.window]
        f = f[f.distance_m.eq(row.distance_m)].reset_index(drop=True)
        columns = [
            f.gate_side.eq("middle").to_numpy(float),
            f.gate_side.eq("outer").to_numpy(float),
        ]
        for key in study.LEGACY.CONTROLS:
            raw = f[key].to_numpy(float)
            missing = ~np.isfinite(raw)
            fill = np.median(raw[~missing]) if (~missing).any() else 0
            values = np.where(missing, fill, raw)
            sd = np.std(values)
            columns.append((values - np.mean(values)) / (sd if sd > 1e-10 else 1))
            if missing.any():
                columns.append(missing.astype(float))
        x = pd.DataFrame(np.column_stack(columns))
        race_counts = f.groupby("race_key").horse_id.transform("size").to_numpy()
        x = x - x.groupby(f.race_key).transform("mean")
        y = f.top3 - f.groupby("race_key").top3.transform("mean")
        xw = x.to_numpy() / np.sqrt(race_counts[:, None])
        yw = y.to_numpy() / np.sqrt(race_counts)
        other = xw[:, np.arange(xw.shape[1]) != 1]
        z = xw[:, 1] - other @ np.linalg.lstsq(other, xw[:, 1], rcond=1e-10)[0]
        beta = float(z @ yw / (z @ z))
        residual = yw - xw @ np.linalg.lstsq(xw, yw, rcond=1e-10)[0]
        rank = np.linalg.matrix_rank(xw.T @ xw, tol=1e-8)
        n, races, days = len(f), f.race_key.nunique(), f.day_key.nunique()
        correction = days / (days - 1) * (n - 1) / (n - races - rank)
        influence = pd.Series(-z * residual / (z @ z) * 100, index=f.day_key).groupby(
            level=0
        ).sum() * np.sqrt(correction)
        existing = scores[scores.window.eq(row.window) & scores.distance_m.eq(row.distance_m)]
        existing = existing.set_index("day_key").influence_pp.reindex(influence.index)
        np.testing.assert_allclose(influence, existing, atol=1e-8)
        effect = -beta * 100
        se = np.sqrt(influence @ influence)
        np.testing.assert_allclose(
            [effect, se], [row.inner_outer_pp, row.inner_outer_se], atol=1e-8
        )
        recalculated[row.window, row.distance_m] = influence
        errors.append(abs(effect - row.inner_outer_pp))
    for row in pairs.itertuples():
        aligned = pd.concat(
            [
                recalculated[row.window, row.left_distance_m],
                recalculated[row.window, row.right_distance_m],
            ],
            axis=1,
        ).fillna(0)
        se = np.sqrt(float(np.square(aligned.iloc[:, 0] - aligned.iloc[:, 1]).sum()))
        np.testing.assert_allclose(se, row.se, atol=1e-8)
        p = 2 * t.sf(abs(row.difference_pp / se), row.df)
        np.testing.assert_allclose(p, row.p, atol=1e-10)
    for _, group in pairs.groupby("window"):
        values = group.p.to_numpy()
        reference_holm = [
            min(
                1,
                max(
                    (len(values) - j) * values[k]
                    for j, k in enumerate(np.argsort(values))
                    if values[k] <= value
                ),
            )
            for value in values
        ]
        np.testing.assert_allclose(reference_holm, group.holm, atol=1e-12)
        np.testing.assert_allclose(
            false_discovery_control(group.p.to_numpy(), method="bh"), group.bh, atol=1e-12
        )
    audit = json.loads((study.OUT / "verification.json").read_text())
    for name, digest in audit["input_hashes"].items():
        assert study.sha(study.ROOT / name) == digest
    result = {
        "passed": True,
        "fwl_effect_and_day_score_models": len(effects),
        "maximum_fwl_effect_error_pp": max(errors),
        "cross_distance_tests": len(pairs),
        "holm_and_bh_families": int(pairs.window.nunique()),
        "source_hashes_unchanged": True,
    }
    (study.OUT / "independent_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
