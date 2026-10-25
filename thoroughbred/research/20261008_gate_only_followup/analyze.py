"""Gate-number profiles and prior-only gate forecasts in a frozen complete-race cohort."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control, t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PRIOR = HERE.parent / "20261003_gate_lateral_time_windows"
SOURCE = HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet"
SPEC = importlib.util.spec_from_file_location("gate_windows", PRIOR / "analyze.py")
TIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIME)
LEGACY = TIME.BIAS
CANDIDATES = ["ability_only", "gate_base"] + [
    f"recent_h{half}_k{strength}" for half in [14, 28, 56] for strength in [40, 80, 120]
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def center(frame, values):
    code = pd.factorize(frame.race_key)[0]
    count = np.bincount(code)
    if values.ndim == 1:
        return values - np.bincount(code, weights=values)[code] / count[code]
    return values - np.column_stack(
        [np.bincount(code, weights=v)[code] / count[code] for v in values.T]
    )


def support(train, frame, levels):
    result = TIME.source_support(train, frame)
    for key, values in levels.items():
        result &= frame[key].isin(values).to_numpy()
    return result


def project(frame, raw):
    """Euclidean box/simplex projection: each complete race has three marginal Top3 places."""
    code = pd.factorize(frame.race_key)[0]
    races = code.max() + 1
    result = np.empty_like(raw)
    for j, values in enumerate(raw.T):
        lo, hi = np.full(races, -100.0), np.full(races, 100.0)
        assert np.max(np.abs(values)) < 90
        for _ in range(50):
            midpoint = (lo + hi) / 2
            p = np.clip(values + midpoint[code], 0.001, 0.999)
            total = np.bincount(code, weights=p)
            lo = np.where(total < 3, midpoint, lo)
            hi = np.where(total >= 3, midpoint, hi)
        result[:, j] = np.clip(values + ((lo + hi) / 2)[code], 0.001, 0.999)
        np.testing.assert_allclose(np.bincount(code, weights=result[:, j]), 3, atol=2e-10)
    return result


def numeric_profiles(data):
    rows, unsupported, reproduction = [], [], []
    original = json.loads((SOURCE.parent / "number_results.json").read_text())
    races = data.groupby("race_key")
    complete = {
        n: [
            key
            for key, g in races
            if len(g) == n and set(g.horse_number.astype(int)) == set(range(1, n + 1))
        ]
        for n in [10, 12]
    }
    for window in ["all", "2024plus"]:
        for n in [10, 12]:
            sample = data[data.race_key.isin(complete[n])]
            if window == "2024plus":
                sample = sample[sample.year.ge(2024)]
            for (meet, distance), f in sample.groupby(["meet", "distance_m"]):
                meta = {
                    "window": window,
                    "meet": int(meet),
                    "distance_m": int(distance),
                    "field_size": n,
                    "races": f.race_key.nunique(),
                    "days": f.day_key.nunique(),
                }
                if meta["races"] < 50 or meta["days"] < 20:
                    unsupported.append(meta)
                    continue
                controls, _ = LEGACY.controls(f)
                x = np.column_stack(
                    [f.horse_number.eq(k).to_numpy(float) for k in range(2, n + 1)]
                    + list(controls.T)
                )
                beta, cov, projection, days, _ = LEGACY.POSITION.cluster_fit(f, x)
                weights = 1 / f.groupby("race_key").race_key.transform("size").to_numpy()
                xw = center(f, x) * np.sqrt(weights[:, None])
                yw = center(f, f.top3.to_numpy(float)) * np.sqrt(weights)
                other = np.linalg.lstsq(xw, yw, rcond=1e-10)[0]
                np.testing.assert_allclose(beta[: n - 1], other[: n - 1], atol=1e-8)
                average = np.zeros(len(beta))
                average[: n - 1] = 1 / n
                for k in range(1, n + 1):
                    vector = -average.copy()
                    if k > 1:
                        vector[k - 2] += 1
                    error = np.max(np.abs(vector - vector @ projection))
                    assert error < 1e-6
                    effect = float(vector @ beta) * 100
                    se = np.sqrt(max(0, float(vector @ cov @ vector))) * 100
                    cutoff = t.ppf(0.975, days - 1)
                    rows.append(
                        meta
                        | {
                            "gate_number": k,
                            "effect_pp": effect,
                            "se": se,
                            "ci_low": effect - cutoff * se,
                            "ci_high": effect + cutoff * se,
                            "p": float(2 * t.sf(abs(effect / se), days - 1)),
                            "raw_top3": float(f[f.horse_number.eq(k)].top3.mean()),
                        }
                    )
                if n == 12:
                    for old in original:
                        if (
                            old["meet"] == meet
                            and old["period"] == window
                            and old["scope"] == "distance"
                            and old["distance_m"] == distance
                        ):
                            difference = float(beta[old["gate"] - 2]) * 100 - old["effect_pp"]
                            assert abs(difference) < 1e-7
                            reproduction.append(
                                meta | {"gate_number": old["gate"], "error_pp": difference}
                            )
    table = pd.DataFrame(rows)
    table["q"] = table.groupby("window").p.transform(
        lambda s: false_discovery_control(s.to_numpy(), method="bh")
    )
    for _, f in table.groupby(["window", "meet", "distance_m", "field_size"]):
        assert abs(f.effect_pp.sum()) < 1e-7
    table.to_csv(OUT / "number_profiles.csv", index=False)
    pd.DataFrame(unsupported).to_csv(OUT / "number_unsupported.csv", index=False)
    pd.DataFrame(reproduction).to_csv(OUT / "number_legacy_reproduction.csv", index=False)
    return len(table), len(reproduction)


def recent_states(train, frame, base_score, levels):
    z = center(
        frame,
        np.column_stack([frame.gate_side.eq(side).to_numpy(float) for side in ["middle", "outer"]]),
    )
    w = 1 / frame.n.to_numpy(float)
    residual = frame.top3.to_numpy(float) - 3 / frame.n.to_numpy(float) - base_score
    eligible = support(train, frame, levels)
    daily = pd.DataFrame(
        {
            "distance_m": frame.distance_m.to_numpy(),
            "date": frame.date.to_numpy(),
            "g00": z[:, 0] ** 2 * w,
            "g01": z[:, 0] * z[:, 1] * w,
            "g11": z[:, 1] ** 2 * w,
            "h0": z[:, 0] * residual * w,
            "h1": z[:, 1] * residual * w,
            "races": (~frame.race_key.duplicated()).to_numpy().astype(int),
        }
    )
    daily = daily[eligible].groupby(["distance_m", "date"], as_index=False).sum()
    ztrain = center(
        train,
        np.column_stack([train.gate_side.eq(side).to_numpy(float) for side in ["middle", "outer"]]),
    )
    grams = {}
    for distance, f in train.groupby("distance_m"):
        index = train.index.get_indexer(f.index)
        a = ztrain[index]
        grams[distance] = a.T @ (a / f.n.to_numpy(float)[:, None]) / f.race_key.nunique()
    return z, daily, grams


def solve_recent(history, date, gram, half, strength):
    ages = (pd.Timestamp(date) - pd.to_datetime(history.date)).dt.days.to_numpy()
    valid = (ages > 0) & (ages <= 84)
    h = history[valid]
    weights = np.exp(-np.log(2) * ages[valid] / half)
    sums = h[["g00", "g01", "g11", "h0", "h1"]].to_numpy().T @ weights
    matrix = np.array([[sums[0], sums[1]], [sums[1], sums[2]]]) + strength * gram
    gamma = np.linalg.solve(matrix, sums[3:])
    independent = np.linalg.lstsq(matrix, sums[3:], rcond=1e-12)[0]
    np.testing.assert_allclose(gamma, independent, atol=1e-12)
    spread = np.ptp(np.r_[0, gamma])
    scale = min(1.0, 0.05 / spread) if spread else 1.0
    gamma *= scale
    assert np.ptp(np.r_[0, gamma]) <= 0.0500000001
    return gamma, {
        "history_first_date": str(h.date.min()) if len(h) else None,
        "history_last_date": str(h.date.max()) if len(h) else None,
        "history_races": int(h.races.sum()),
        "weighted_races": float(h.races.to_numpy() @ weights),
        "cap_scale": scale,
    }


def forecasts(data):
    stored = json.loads((PRIOR / "outputs/baseline_models.json").read_text())
    predictions, states, models, snapshots = [], [], [], []
    for meet, venue in data.groupby("meet"):
        for year in range(2020, 2027):
            train = venue[venue.year.lt(year)].copy()
            start = pd.Timestamp(f"{year}-01-01") - pd.Timedelta(days=84)
            frame = venue[venue.dt.ge(start) & venue.year.le(year)].copy().reset_index(drop=True)
            model = next(
                m
                for m in stored
                if m["meet"] == meet and m["point"] == "gate" and m["year"] == year
            )
            assert model["trained_through"] < year and model["train_rows"] == len(train)
            meta, levels = model["numeric_metadata"], model["levels"]
            xa = np.column_stack(TIME.ability_columns(train, meta)[0])
            xw = center(train, xa) / np.sqrt(train.n.to_numpy()[:, None])
            yw = center(train, train.top3.to_numpy(float)) / np.sqrt(train.n.to_numpy())
            beta0 = np.linalg.pinv(xw.T @ xw, rcond=1e-10) @ (xw.T @ yw)
            np.testing.assert_allclose(beta0, np.linalg.lstsq(xw, yw, rcond=1e-10)[0], atol=1e-8)
            x, labels, _ = TIME.design(frame, levels, meta, False)
            assert labels == model["labels"]
            score1 = center(frame, x @ np.asarray(model["coefficients"]))
            score0 = center(frame, np.column_stack(TIME.ability_columns(frame, meta)[0]) @ beta0)
            eligible = support(train, frame, levels)
            z, daily, grams = recent_states(train, frame, score1, levels)
            target = frame.year.eq(year).to_numpy()
            raw = np.column_stack([score0, score1] + [score1.copy() for _ in range(9)])
            for (distance, date), f in frame[target & eligible].groupby(["distance_m", "date"]):
                history = daily[daily.distance_m.eq(distance)]
                for j, candidate in enumerate(CANDIDATES[2:], start=2):
                    half, strength = map(int, candidate.replace("recent_h", "").split("_k"))
                    gamma, info = solve_recent(history, date, grams[distance], half, strength)
                    raw[f.index, j] += z[f.index] @ gamma
                    states.append(
                        {
                            "meet": int(meet),
                            "year": year,
                            "distance_m": int(distance),
                            "date": date,
                            "candidate": candidate,
                            "middle_pp": gamma[0] * 100,
                            "outer_pp": gamma[1] * 100,
                        }
                        | info
                    )
            raw[~eligible, 1:] = raw[~eligible, :1]
            target_frame = frame[target].copy()
            raw = raw[target] + 3 / target_frame.n.to_numpy()[:, None]
            probabilities = project(target_frame, raw)
            saved = target_frame[
                [
                    "meet",
                    "year",
                    "date",
                    "day_key",
                    "race_key",
                    "race_no",
                    "distance_m",
                    "horse_id",
                    "horse_number",
                    "n",
                    "top3",
                ]
            ].copy()
            saved["eligible"] = eligible[target]
            saved["trained_through"] = year - 1
            for j, candidate in enumerate(CANDIDATES):
                saved[candidate] = probabilities[:, j]
            predictions.append(saved)
            models.append(
                {
                    "meet": int(meet),
                    "year": year,
                    "trained_through": year - 1,
                    "train_last_date": str(train.date.max()),
                    "train_rows": len(train),
                    "ability_coefficients": beta0.tolist(),
                    "numeric_metadata": meta,
                    "gate_model_source": str(
                        (PRIOR / "outputs/baseline_models.json").relative_to(ROOT)
                    ),
                    "test_rows": len(saved),
                    "eligible_races": saved[saved.eligible].race_key.nunique(),
                }
            )
            if year == 2026:
                for distance, history in daily.groupby("distance_m"):
                    if distance not in grams:
                        continue
                    for candidate in CANDIDATES[2:]:
                        half, strength = map(int, candidate.replace("recent_h", "").split("_k"))
                        gamma, info = solve_recent(
                            history, "2026-09-21", grams[distance], half, strength
                        )
                        snapshots.append(
                            {
                                "meet": int(meet),
                                "distance_m": int(distance),
                                "as_of": "2026-09-21",
                                "candidate": candidate,
                                "middle_pp": gamma[0] * 100,
                                "outer_pp": gamma[1] * 100,
                            }
                            | info
                        )
            print(
                f"Forecast meet={meet} year={year} eligible={models[-1]['eligible_races']}",
                flush=True,
            )
    p = pd.concat(predictions, ignore_index=True)
    p.to_parquet(OUT / "runner_predictions.parquet", index=False)
    pd.DataFrame(states).to_parquet(OUT / "recent_gate_states.parquet", index=False)
    pd.DataFrame(snapshots).to_csv(OUT / "snapshot_20260921.csv", index=False)
    dump(OUT / "forecast_models.json", models)
    return p


def losses(predictions):
    rows = []
    for key, f in predictions[predictions.eligible].groupby("race_key", sort=False):
        y = f.top3.to_numpy(float)
        for candidate in CANDIDATES:
            p = f[candidate].to_numpy(float)
            order = np.lexsort((f.horse_number.to_numpy(), -p))[:3]
            rows.append(
                {
                    "race_key": key,
                    "meet": int(f.meet.iloc[0]),
                    "year": int(f.year.iloc[0]),
                    "day_key": f.day_key.iloc[0],
                    "date": f.date.iloc[0],
                    "distance_m": int(f.distance_m.iloc[0]),
                    "candidate": candidate,
                    "log_loss": float(-(y * np.log(p) + (1 - y) * np.log1p(-p)).mean()),
                    "brier": float(np.square(y - p).mean()),
                    "top3_precision": float(y[order].mean()),
                }
            )
    result = pd.DataFrame(rows)
    result.to_parquet(OUT / "race_losses.parquet", index=False)
    selection = (
        result[result.year.isin([2022, 2023])]
        .groupby(["meet", "candidate"])[["log_loss", "brier", "top3_precision"]]
        .mean()
        .reset_index()
    )
    selected = {}
    for meet, f in selection.groupby("meet"):
        eligible = f[f.log_loss.le(f.log_loss.min() + 0.0001)].candidate.tolist()

        def simplicity(candidate):
            if candidate in CANDIDATES[:2]:
                return (CANDIDATES.index(candidate), 0, 0)
            half, strength = map(int, candidate.replace("recent_h", "").split("_k"))
            return (2, -strength, -half)

        selected[int(meet)] = min(eligible, key=simplicity)
    selection["selected"] = [
        selected[m] == c for m, c in zip(selection.meet, selection.candidate, strict=True)
    ]
    selection.to_csv(OUT / "candidate_selection.csv", index=False)
    evaluation = result[result.year.ge(2024)]
    for keys, filename in [
        (["meet", "candidate"], "evaluation.csv"),
        (["meet", "year", "candidate"], "evaluation_by_year.csv"),
        (["meet", "distance_m", "candidate"], "evaluation_by_distance.csv"),
    ]:
        table = (
            evaluation.groupby(keys)
            .agg(
                races=("race_key", "size"),
                days=("day_key", "nunique"),
                log_loss=("log_loss", "mean"),
                brier=("brier", "mean"),
                top3_precision=("top3_precision", "mean"),
            )
            .reset_index()
        )
        table.to_csv(OUT / filename, index=False)
    bootstrap = []
    rng = np.random.default_rng(20261008)
    for meet, f in evaluation.groupby("meet"):
        base = f[f.candidate.eq("ability_only")].set_index("race_key")
        for candidate in sorted({"gate_base", selected[int(meet)]}):
            sample = f[f.candidate.eq(candidate)].set_index("race_key").reindex(base.index)
            for metric in ["log_loss", "brier", "top3_precision"]:
                difference = sample[metric] - base[metric]
                daily = difference.groupby(base.day_key).agg(["sum", "size"])
                draws = rng.integers(0, len(daily), size=(500, len(daily)))
                values = daily["sum"].to_numpy()[draws].sum(axis=1) / daily["size"].to_numpy()[
                    draws
                ].sum(axis=1)
                low, high = np.quantile(values, [0.025, 0.975])
                bootstrap.append(
                    {
                        "meet": int(meet),
                        "candidate": candidate,
                        "metric": metric,
                        "difference": float(difference.mean()),
                        "ci_low": low,
                        "ci_high": high,
                        "resamples": 500,
                        "races": len(base),
                        "days": len(daily),
                    }
                )
    pd.DataFrame(bootstrap).to_csv(OUT / "paired_day_bootstrap.csv", index=False)
    dump(OUT / "selected_candidates.json", selected)
    return selected


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    OUT.mkdir()
    paths = [
        SOURCE,
        PRIOR / "analyze.py",
        PRIOR / "outputs/baseline_models.json",
        SOURCE.parent / "number_results.json",
        HERE / "PLAN.md",
        HERE / "analyze.py",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    data = pd.read_parquet(SOURCE)
    assert len(data) == 151115 and data.race_key.nunique() == 13928
    assert (data.last_history_date.isna() | data.last_history_date.lt(data.dt)).all()
    profile_count, reproduction_count = numeric_profiles(data)
    predictions = forecasts(data)
    selected = losses(predictions)
    for name, digest in hashes.items():
        assert sha(ROOT / name) == digest
    summary = {
        "completed_on": "2026-10-08",
        "source_rows": len(data),
        "source_races": int(data.race_key.nunique()),
        "input_hashes": hashes,
        "number_profile_rows": profile_count,
        "number_legacy_checks": reproduction_count,
        "prediction_rows": len(predictions),
        "eligible_forecast_races": int(predictions[predictions.eligible].race_key.nunique()),
        "selected": selected,
        "new_outlier_removal": False,
        "current_actual_position_used": False,
        "seconds_correction_adopted": False,
        "production_changed": False,
        "new_future_validation": False,
    }
    dump(OUT / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
