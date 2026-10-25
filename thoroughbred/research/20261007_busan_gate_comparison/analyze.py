"""Compare every supported pair of Busan distances using shared-day covariance."""

import importlib.util
import itertools
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
DISTANCES = [1000, 1200, 1300, 1400, 1600, 1800, 2000]
REUSED = HERE.parent / "20261007_seoul1600_gate_comparison/analyze.py"
SPEC = importlib.util.spec_from_file_location("seoul_gate_math", REUSED)
MATH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATH)
LEGACY = MATH.LEGACY
sha = MATH.sha


def samples(data):
    keys = [
        key
        for key, g in data.groupby("race_key")
        if len(g) == 12 and set(g.horse_number.astype(int)) == set(range(1, 13))
    ]
    return {
        "all": data,
        "2024plus": data[data.year.ge(2024)],
        "full12": data[data.race_key.isin(keys)],
    }


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite analysis outputs")
    OUT.mkdir()
    paths = [
        SOURCE,
        REUSED,
        PRIOR / "analyze.py",
        LEGACY.PRIOR / "analyze.py",
        PRIOR / "outputs/gate_results.json",
        HERE / "PLAN.md",
        HERE / "analyze.py",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    d = pd.read_parquet(SOURCE)
    d = d[d.meet.eq(3) & d.distance_m.isin(DISTANCES)].copy()
    assert not d.duplicated(["race_key", "horse_number"]).any()
    assert (d.last_history_date.isna() | d.last_history_date.lt(d.dt)).all()
    effects, tests, influence_rows, unsupported, reproduction = [], [], [], [], []
    original = json.loads((PRIOR / "outputs/gate_results.json").read_text())
    for window, sample in samples(d).items():
        estimates, influences = {}, {}
        for distance in DISTANCES:
            frame = sample[sample.distance_m.eq(distance)]
            meta = {"window": window, "distance_m": distance}
            if frame.race_key.nunique() < 50 or frame.day_key.nunique() < 20:
                unsupported.append(
                    meta | {"races": frame.race_key.nunique(), "days": frame.day_key.nunique()}
                )
                continue
            estimate, influence = MATH.fit(frame)
            estimates[distance], influences[distance] = estimate, influence
            effects.append(meta | estimate)
            influence_rows.extend(
                meta | {"day_key": day, "influence_pp": float(value)}
                for day, value in influence.items()
            )
            if window in ["all", "2024plus"]:
                old = next(
                    x
                    for x in original
                    if x["meet"] == 3
                    and x["period"] == window
                    and x["scope"] == "distance"
                    and x["distance_m"] == distance
                )
                error = abs(estimate["inner_outer_pp"] + old["effect_pp"])
                assert error < 1e-7
                reproduction.append(meta | {"original_effect_error_pp": error})
        pairs = []
        for left, right in itertools.combinations(estimates, 2):
            aligned = pd.concat([influences[left], influences[right]], axis=1).fillna(0).to_numpy()
            covariance = float(aligned[:, 0] @ aligned[:, 1])
            se = np.sqrt(np.square(aligned[:, 0] - aligned[:, 1]).sum())
            np.testing.assert_allclose(
                se**2,
                estimates[left]["inner_outer_se"] ** 2
                + estimates[right]["inner_outer_se"] ** 2
                - 2 * covariance,
            )
            delta = estimates[left]["inner_outer_pp"] - estimates[right]["inner_outer_pp"]
            df = min(estimates[left]["days"], estimates[right]["days"]) - 1
            cutoff = t.ppf(0.975, df)
            pairs.append(
                {
                    "window": window,
                    "left_distance_m": left,
                    "right_distance_m": right,
                    "left_inner_advantage_pp": estimates[left]["inner_outer_pp"],
                    "right_inner_advantage_pp": estimates[right]["inner_outer_pp"],
                    "difference_pp": delta,
                    "se": float(se),
                    "ci_low": delta - cutoff * se,
                    "ci_high": delta + cutoff * se,
                    "df": df,
                    "shared_date_covariance": covariance,
                    "p": float(2 * t.sf(abs(delta / se), df)),
                }
            )
        holm, bh = MATH.adjust([x["p"] for x in pairs])
        for row, h, b in zip(pairs, holm, bh, strict=True):
            row.update({"holm": float(h), "bh": float(b), "different_holm": bool(h < 0.05)})
        tests.extend(pairs)
    pd.DataFrame(effects).to_csv(OUT / "distance_effects.csv", index=False)
    pd.DataFrame(tests).to_csv(OUT / "distance_comparisons.csv", index=False)
    pd.DataFrame(influence_rows).to_parquet(OUT / "day_influences.parquet", index=False)
    pd.DataFrame(unsupported).to_csv(OUT / "unsupported.csv", index=False)
    pd.DataFrame(reproduction).to_csv(OUT / "legacy_reproduction.csv", index=False)
    races = d.drop_duplicates("race_key")
    races.groupby(["distance_m", "year"]).size().rename("races").to_csv(OUT / "year_counts.csv")
    races.groupby(["distance_m", "n"]).size().rename("races").to_csv(OUT / "field_size_counts.csv")
    for name, digest in hashes.items():
        assert sha(ROOT / name) == digest
    audit = {
        "passed": True,
        "input_hashes": hashes,
        "source_rows": len(d),
        "source_races": int(d.race_key.nunique()),
        "source_horses": int(d.horse_id.nunique()),
        "first_date": str(d.date.min()),
        "last_date": str(d.date.max()),
        "models_lstsq_and_legacy_checked": len(effects),
        "original_result_rows_checked": len(reproduction),
        "pairwise_tests": len(tests),
        "new_outlier_removal": False,
        "seconds_correction_adopted": False,
        "forecast_validation": False,
        "production_changed": False,
    }
    (OUT / "verification.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(
        pd.DataFrame(effects)[
            [
                "window",
                "distance_m",
                "races",
                "inner_outer_pp",
                "inner_outer_low",
                "inner_outer_high",
            ]
        ].to_string(index=False)
    )
    print(
        pd.DataFrame(tests)
        .query("window == 'all'")[["left_distance_m", "right_distance_m", "difference_pp", "holm"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
