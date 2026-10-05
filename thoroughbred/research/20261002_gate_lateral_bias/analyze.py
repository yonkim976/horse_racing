"""Separate registered starting-number bias from observed within-pack lateral positions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PRIOR = HERE.parent / "20261002_moisture_position"
AUDIT = HERE.parent / "20261002_track_source_reconciliation/results"
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
SPEC = importlib.util.spec_from_file_location("position", PRIOR / "analyze.py")
POSITION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POSITION)
CONTROLS = [c for c in POSITION.CONTROLS if c != "gate_pct"]
DISTANCES = [1000, 1200, 1300, 1400, 1600, 1700, 1800, 2000]
POINTS = {1: ["S1F", "3C", "4C", "G1F"], 3: ["S1F", "G4F", "G3F", "G1F"]}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def controls(frame):
    columns, labels = [], []
    for key in CONTROLS:
        v = frame[key].to_numpy(float)
        missing = ~np.isfinite(v)
        median = np.median(v[~missing]) if (~missing).any() else 0
        v = np.where(missing, median, v)
        scale = v.std()
        columns.append((v - v.mean()) / (scale if scale > 1e-10 else 1))
        labels.append(key)
        if missing.any():
            columns.append(missing.astype(float))
            labels.append(f"missing:{key}")
    return np.column_stack(columns), labels


def supported(frame):
    return frame.race_key.nunique() >= 50 and frame.day_key.nunique() >= 20


def gate_fit(frame, individual=False):
    c, labels = controls(frame)
    levels = list(range(2, 13)) if individual else ["middle", "outer"]
    indicators = [
        frame.horse_number.eq(g).to_numpy(float)
        if individual
        else frame.gate_side.eq(g).to_numpy(float)
        for g in levels
    ]
    x = np.column_stack(indicators + list(c.T))
    beta, cov, projection, days, rank = POSITION.cluster_fit(frame, x)
    rows = []
    for j, level in enumerate(levels):
        if not individual and level != "outer":
            continue
        vector = np.zeros(x.shape[1])
        vector[j] = 1
        rows.append(
            {
                "gate": level,
                "reference": 1 if individual else "inner",
                **POSITION.contrast(beta, cov, projection, days, vector),
            }
        )
    return rows, {"columns": x.shape[1], "rank": rank, "days": days, "controls": labels}


def strata(frame):
    yield "all", None, None, frame
    for distance, one in frame[frame.distance_m.isin(DISTANCES)].groupby("distance_m"):
        yield "distance", int(distance), None, one
        for band, cell in one.groupby("band"):
            yield "distance_band", int(distance), band, cell


def gate_results(population):
    results, raw, individual, diagnostics = [], [], [], []
    for meet, venue in population.groupby("meet"):
        for period in ["all", "2024plus"]:
            sample = venue if period == "all" else venue[venue.year.ge(2024)]
            for scope, distance, band, one in strata(sample):
                metadata = {
                    "meet": int(meet),
                    "period": period,
                    "scope": scope,
                    "distance_m": distance,
                    "band": band,
                    "runners": len(one),
                    "races": int(one.race_key.nunique()),
                    "days": int(one.day_key.nunique()),
                }
                rates = one.groupby("gate_side").agg(
                    runners=("horse_id", "size"),
                    top3_rate=("top3", "mean"),
                    win_rate=("win", "mean"),
                    rating=("rating", "mean"),
                )
                for side, r in rates.iterrows():
                    raw.append({**metadata, "side": side, **r.to_dict()})
                if not supported(one):
                    continue
                cells = one.groupby(["race_key", "gate_side"]).top3.mean().unstack()
                difference = float((cells.outer - cells.inner).mean()) * 100
                fits, diagnostic = gate_fit(one)
                results.append({**metadata, "raw_effect_pp": difference, **fits[0]})
                diagnostics.append({**metadata, "kind": "gate", **diagnostic})
            full12 = sample[sample.n.eq(12)].copy()
            keys = [
                key
                for key, one in full12.groupby("race_key")
                if set(one.horse_number.astype(int)) == set(range(1, 13))
            ]
            full12 = full12[full12.race_key.isin(keys)]
            for scope, distance, _band, one in strata(full12):
                if scope == "distance_band" or not supported(one):
                    continue
                fits, diagnostic = gate_fit(one, individual=True)
                base = {
                    "meet": int(meet),
                    "period": period,
                    "scope": scope,
                    "distance_m": distance,
                    "runners": len(one),
                    "races": int(one.race_key.nunique()),
                    "days": int(one.day_key.nunique()),
                }
                rate1 = float(one[one.horse_number.eq(1)].top3.mean())
                for fit in fits:
                    cell = one[one.horse_number.eq(fit["gate"])]
                    individual.append(
                        {
                            **base,
                            **fit,
                            "raw_top3": float(cell.top3.mean()),
                            "raw_win": float(cell.win.mean()),
                            "raw_effect_pp": (float(cell.top3.mean()) - rate1) * 100,
                        }
                    )
                diagnostics.append({**base, "kind": "individual_gate", **diagnostic})
    for rows, family in [(results, "distance"), (individual, "distance")]:
        eligible = [
            r for r in rows if r["period"] == "all" and r["scope"] == family and r["estimable"]
        ]
        for r, q in zip(eligible, POSITION.bh([r["p"] for r in eligible]), strict=True):
            r["q_distance"] = float(q)
    return results, raw, individual, diagnostics


def paired_positions(population, passing):
    look = {
        key: one.set_index("horse_number").to_dict("index")
        for key, one in population.groupby("race_key")
    }
    pairs, issues, observations, counts = [], [], [], Counter()
    for row in passing.itertuples(index=False):
        if row.race_key not in look or row.point not in POINTS[int(row.meet)]:
            continue
        counts["eligible_point_rows"] += 1
        roster = look[row.race_key]
        try:
            packs = POSITION.parse(row.notation_raw)
        except ValueError as error:
            issues.append(
                {
                    "race_key": row.race_key,
                    "point": row.point,
                    "reason": str(error),
                    "raw": row.notation_raw,
                }
            )
            continue
        members = [number for pack in packs for number in pack["members"]]
        if set(members) != set(roster):
            issues.append(
                {
                    "race_key": row.race_key,
                    "point": row.point,
                    "reason": "roster_mismatch",
                    "raw": row.notation_raw,
                }
            )
            continue
        counts["parsed_and_roster_matched"] += 1
        for j, pack in enumerate(packs):
            n = len(pack["members"])
            for k, number in enumerate(pack["members"]):
                horse = roster[number]
                side = (
                    "single"
                    if n == 1
                    else "inner"
                    if k == 0
                    else "outer"
                    if k == n - 1
                    else "middle"
                )
                observations.append(
                    {
                        "meet": int(row.meet),
                        "point": row.point,
                        "race_key": row.race_key,
                        "gate_side": horse["gate_side"],
                        "pack_side": side,
                    }
                )
            if n < 2:
                continue
            inner_number, outer_number = pack["members"][0], pack["members"][-1]
            inner, outer = roster[inner_number], roster[outer_number]
            pair = {
                "meet": int(row.meet),
                "point": row.point,
                "race_key": row.race_key,
                "day_key": inner["day_key"],
                "date": inner["date"],
                "year": int(inner["year"]),
                "distance_m": int(inner["distance_m"]),
                "band": inner["band"],
                "pack_index": j,
                "pack_size": n,
                "inner_number": int(inner_number),
                "outer_number": int(outer_number),
                "top3_difference": outer["top3"] - inner["top3"],
                "source": row.selected_source,
                "notation_raw": row.notation_raw,
            }
            for control in CONTROLS + ["gate_pct"]:
                pair[f"inner_{control}"] = inner[control]
                pair[f"outer_{control}"] = outer[control]
            pairs.append(pair)
    return pd.DataFrame(pairs), pd.DataFrame(issues), pd.DataFrame(observations), dict(counts)


def pair_fit(frame, adjusted):
    vectors = [np.ones(len(frame))]
    if adjusted:
        for control in CONTROLS + ["gate_pct"]:
            inner, outer = (
                frame[f"inner_{control}"].to_numpy(float),
                frame[f"outer_{control}"].to_numpy(float),
            )
            missing_inner, missing_outer = ~np.isfinite(inner), ~np.isfinite(outer)
            combined = np.concatenate([inner[~missing_inner], outer[~missing_outer]])
            median = np.median(combined) if len(combined) else 0
            scale = combined.std() if len(combined) else 1
            difference = np.where(missing_outer, median, outer) - np.where(
                missing_inner, median, inner
            )
            vectors.append(difference / (scale if scale > 1e-10 else 1))
            if missing_inner.any() or missing_outer.any():
                vectors.append(missing_outer.astype(float) - missing_inner.astype(float))
    x = np.column_stack(vectors)
    weights = 1 / frame.groupby("race_key").race_key.transform("size").to_numpy()
    xw, yw = x * np.sqrt(weights[:, None]), frame.top3_difference.to_numpy(float) * np.sqrt(weights)
    gram = xw.T @ xw
    inverse = np.linalg.pinv(gram, rcond=1e-10)
    projection = inverse @ gram
    beta = inverse @ (xw.T @ yw)
    errors = yw - xw @ beta
    day, codes = pd.factorize(frame.day_key)
    days = len(codes)
    scores = xw * errors[:, None]
    sums = np.column_stack([np.bincount(day, weights=v, minlength=days) for v in scores.T])
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    covariance = (
        inverse
        @ (sums.T @ sums)
        @ inverse
        * days
        / (days - 1)
        * (len(frame) - 1)
        / max(len(frame) - rank, 1)
    )
    vector = np.zeros(x.shape[1])
    vector[0] = 1
    return POSITION.contrast(beta, covariance, projection, days, vector)


def lateral_results(pairs):
    rows = []
    for (meet, point), venue in pairs.groupby(["meet", "point"]):
        for period in ["all", "2024plus"]:
            sample = venue if period == "all" else venue[venue.year.ge(2024)]
            for scope, distance, band, cell in strata(sample):
                if not supported(cell):
                    continue
                rows.append(
                    {
                        "meet": int(meet),
                        "point": point,
                        "period": period,
                        "scope": scope,
                        "distance_m": distance,
                        "band": band,
                        "pairs": len(cell),
                        "races": int(cell.race_key.nunique()),
                        "days": int(cell.day_key.nunique()),
                        "raw": pair_fit(cell, False),
                        "adjusted": pair_fit(cell, True),
                    }
                )
    family = [
        r
        for r in rows
        if r["period"] == "all" and r["scope"] == "all" and r["adjusted"]["estimable"]
    ]
    for r, q in zip(family, POSITION.bh([r["adjusted"]["p"] for r in family]), strict=True):
        r["q_point"] = float(q)
    return rows


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PRIOR / "analyze.py",
        PRIOR / "outputs/core_runner_snapshot.parquet",
        POSITION.SECTIONS,
        AUDIT / "api_study_population.parquet",
        AUDIT / "api_band_percent_conflicts.csv",
        AUDIT / "runner_clean_differences.csv",
        CORE,
    ]
    hashes = {str(p): sha(p) for p in paths}
    OUT.mkdir()
    POSITION.check_parser()
    print("Rebuilding prior-only runner histories", flush=True)
    runners = POSITION.runners_with_priors()
    population, exclusions = POSITION.eligible_population(runners)
    population = population[population.dt.le("2026-09-20")].copy()
    bad = pd.read_csv(paths[6])[POSITION.KEY[:3]]
    differences = pd.read_csv(paths[7])
    bad = pd.concat(
        [bad, differences[differences.status.eq("different")][POSITION.KEY[:3]]]
    ).drop_duplicates()
    bad["race_key"] = bad.meet.astype(str) + ":" + bad.date + ":" + bad.race_no.astype(str)
    before = len(population)
    population = population[~population.race_key.isin(bad.race_key)].copy()
    population["gate_side"] = pd.cut(
        population.gate_pct, [0, 1 / 3, 2 / 3, 1], labels=["inner", "middle", "outer"]
    ).astype(str)
    assert not population.duplicated(POSITION.KEY).any()
    assert (
        population.last_history_date.isna() | population.last_history_date.lt(population.dt)
    ).all()
    for _, race in population.groupby("race_key"):
        assert sorted(race["rank"].astype(int)) == list(range(1, len(race) + 1))
    population.to_parquet(OUT / "runners.parquet", index=False)
    pd.DataFrame(exclusions).to_csv(OUT / "race_exclusions.csv", index=False)
    print(f"Gate population {len(population)} runners; fitting", flush=True)
    gate, raw, numbers, diagnostics = gate_results(population)
    pd.DataFrame(raw).to_csv(OUT / "raw_gate_rates.csv", index=False)
    pd.DataFrame(gate).to_json(
        OUT / "gate_results.json", orient="records", force_ascii=False, indent=2
    )
    pd.DataFrame(numbers).to_json(
        OUT / "number_results.json", orient="records", force_ascii=False, indent=2
    )
    print("Snapshotting selected passing points read-only", flush=True)
    with duckdb.connect(str(CORE), read_only=True) as connection:
        passing = connection.execute(
            "SELECT actual_meet_code AS meet,event_date AS date,race_no,"
            "canonical_point_code AS point,notation_raw,selected_source,selection_status "
            "FROM race_passing_groups WHERE actual_meet_code IN (1,3) "
            "AND event_date BETWEEN '2018-01-01' AND '2026-09-20' "
            "AND canonical_point_code IN ('S1F','3C','4C','G1F','G4F','G3F')"
        ).fetchdf()
    passing["race_key"] = (
        passing.meet.astype(str) + ":" + passing.date + ":" + passing.race_no.astype(str)
    )
    assert not passing.duplicated(["race_key", "point"]).any()
    passing.to_parquet(OUT / "passing_snapshot.parquet", index=False)
    pairs, issues, positions, counts = paired_positions(population, passing)
    pairs.to_parquet(OUT / "pack_pairs.parquet", index=False)
    issues.to_csv(OUT / "notation_issues.csv", index=False)
    positions.to_parquet(OUT / "gate_to_lateral_positions.parquet", index=False)
    print(f"Lateral pairs {len(pairs)}; fitting", flush=True)
    lateral = lateral_results(pairs)
    assert hashes == {str(p): sha(p) for p in paths}
    saved = {
        "inputs_sha256": hashes,
        "coverage": {
            "runners_before_quality_exclusions": before,
            "source_quality_excluded_runners": before - len(population),
            "runners": len(population),
            "races": population.race_key.nunique(),
            "by_venue": population.groupby("meet")
            .agg(
                runners=("horse_id", "size"),
                races=("race_key", "nunique"),
                days=("day_key", "nunique"),
            )
            .reset_index()
            .to_dict("records"),
            "passing": counts,
            "issues": len(issues),
            "pairs": len(pairs),
        },
        "gate": gate,
        "numbers": numbers,
        "lateral": lateral,
        "gate_diagnostics": diagnostics,
        "validation": {
            "input_hashes_unchanged": True,
            "prior_dates_only": True,
            "normal_rank_complete": True,
            "source_core_read_only": True,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    print(json.dumps(saved["coverage"], ensure_ascii=False), flush=True)
    print(
        json.dumps(
            [g for g in gate if g["period"] == "all" and g["scope"] == "distance"],
            ensure_ascii=False,
        ),
        flush=True,
    )
    print(
        json.dumps(
            [g for g in lateral if g["period"] == "all" and g["scope"] == "all"], ensure_ascii=False
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
