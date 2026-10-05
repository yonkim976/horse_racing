"""Observed running position by moisture/distance, with prior ability controls."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
AUDIT = HERE.parent / "20261002_track_source_reconciliation/results"
SECTIONS = ROOT / "thoroughbred/data/section_api_2010_20260929_v1/section_measurements.parquet"
KEY = ["meet", "date", "race_no", "horse_id"]
ROLES = ["solo", "leading_pack", "stalking", "middle", "rear"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
DISTANCES = [1200, 1300, 1400, 1600, 1700, 1800]
CONTROLS = [
    "rating",
    "age",
    "weight",
    "gate_pct",
    "prior_finish",
    "prior_top3",
    "prior_early",
    "log_starts",
    "log_gap",
]
TOKEN = re.compile(r"\((?:\^?\d+,)*\^?\d+\)|\^?\d+")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(raw):
    text = re.sub(r"\s+", "", raw)
    if not text or any(c not in "0123456789^(),-=≡" for c in text):
        raise ValueError("unsupported notation")
    groups, cursor, all_horses = [], 0, []
    for match in TOKEN.finditer(text):
        separator = text[cursor : match.start()]
        if (cursor == 0 and separator) or (cursor > 0 and separator not in [",", "-", "=", "≡"]):
            raise ValueError("invalid delimiter")
        horses = [int(x) for x in re.findall(r"\d+", match.group())]
        if min(horses) < 1:
            raise ValueError("invalid number")
        groups.append({"members": horses, "separator": separator})
        all_horses += horses
        cursor = match.end()
    if not groups or cursor != len(text) or len(set(all_horses)) != len(all_horses):
        raise ValueError("trailing text or duplicate horse")
    return groups


def check_parser():
    assert parse("(1,^2,3),4-5=6≡7")[0]["members"] == [1, 2, 3]
    assert parse("3-(1,2),4")[1]["separator"] == "-"
    assert parse("(2,^1),3")[0]["members"] == [2, 1]
    for raw in ["1,1", "1 ·2", "(1,2", "1--2", "0,1", "1,2,", ""]:
        try:
            parse(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(raw)


def runners_with_priors():
    raw = pd.read_parquet(OUT / "core_runner_snapshot.parquet")
    names = {
        "source_meet": "meet",
        "result_date": "date",
        "result_race_no": "race_no",
        "result_rank_raw": "rank",
        "finish_time_seconds_raw": "finish",
        "horse_program_no_raw": "horse_number",
        "horse_id_raw": "horse_id",
        "horse_age_raw": "age",
        "carried_weight_raw": "weight",
        "horse_rating_raw": "rating",
        "race_distance_m_raw": "distance_m",
        "odds_win_raw": "odds",
    }
    runners = raw.rename(columns=names)
    for column in [
        "meet",
        "race_no",
        "rank",
        "finish",
        "horse_number",
        "age",
        "weight",
        "rating",
        "distance_m",
        "odds",
    ]:
        runners[column] = pd.to_numeric(runners[column], errors="coerce")
    runners["dt"] = pd.to_datetime(runners.date, format="%Y%m%d")
    runners["date"] = runners.dt.dt.strftime("%Y-%m-%d")
    assert not runners.duplicated(KEY).any()
    assert runners[KEY].notna().all().all()
    runners["race_key"] = (
        runners.meet.astype(int).astype(str)
        + ":"
        + runners.date
        + ":"
        + runners.race_no.astype(int).astype(str)
    )
    runners["scratched"] = runners["rank"].isin([93, 94, 95])
    runners["n"] = (~runners.scratched).groupby(runners.race_key).transform("sum")
    runners["valid"] = runners["rank"].between(1, 20) & runners.finish.gt(0)
    runners["finish_pct"] = (runners["rank"] - 1) / (runners.n - 1)
    runners["top3"] = runners["rank"].le(3).astype(float)
    runners["win"] = runners["rank"].eq(1).astype(float)
    sections = pd.read_parquet(
        SECTIONS,
        columns=["meet", "race_date", "race_no", "horse_id", "horse_program_no", "passing_order"],
        filters=[
            ("meet", "in", [1, 3]),
            ("point_code", "=", "S1F"),
            ("measure_kind", "=", "passing_order"),
        ],
    )
    sections["date"] = pd.to_datetime(sections.race_date, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    assert not sections.duplicated(KEY).any()
    runners = runners.merge(
        sections[KEY + ["horse_program_no", "passing_order"]],
        on=KEY,
        how="left",
        validate="one_to_one",
    )
    observed = runners.horse_program_no.notna()
    assert runners.loc[observed, "horse_program_no"].eq(runners.loc[observed, "horse_number"]).all()
    runners["early_pct"] = ((runners.passing_order - 1) / (runners.n - 1)).where(
        runners.passing_order.between(1, runners.n)
    )
    runners = runners.sort_values(["date", "race_no", "meet", "horse_number"]).reset_index(
        drop=True
    )
    state = defaultdict(
        lambda: {"finish": deque(maxlen=5), "early": deque(maxlen=5), "starts": 0, "last": None}
    )
    priors = []
    for date, group in runners.groupby("dt", sort=True):
        for row in group.itertuples():
            history = state[row.horse_id]
            form = history["finish"]
            priors.append(
                {
                    "index": row.Index,
                    "prior_finish": np.mean([x[0] for x in form]) if form else np.nan,
                    "prior_top3": np.mean([x[1] for x in form]) if form else np.nan,
                    "prior_early": np.mean(history["early"]) if history["early"] else np.nan,
                    "log_starts": np.log1p(history["starts"]),
                    "log_gap": np.log1p((date - history["last"]).days)
                    if history["last"] is not None
                    else np.nan,
                    "last_history_date": history["last"],
                }
            )
        for row in group.itertuples():
            if row.scratched:
                continue
            history = state[row.horse_id]
            history["starts"] += 1
            history["last"] = date
            if row.valid and row.n >= 2:
                history["finish"].append((row.finish_pct, row.top3))
                if pd.notna(row.early_pct):
                    history["early"].append(row.early_pct)
    priors = pd.DataFrame(priors).set_index("index").reindex(runners.index)
    runners = pd.concat([runners, priors], axis=1)
    assert (runners.last_history_date.isna() | runners.last_history_date.lt(runners.dt)).all()
    return runners


def eligible_population(runners):
    reasons, eligible = [], []
    for race_key, group in runners[runners.dt.ge("2018-01-01")].groupby("race_key", sort=False):
        starters = group[~group.scratched]
        reason = None
        if len(starters) < 6:
            reason = "fewer_than_six"
        elif not starters.valid.all():
            reason = "nonstandard_finish"
        elif sorted(starters["rank"].astype(int)) != list(range(1, len(starters) + 1)):
            reason = "tie_or_incomplete_rank"
        elif starters.horse_number.isna().any() or starters.horse_number.duplicated().any():
            reason = "invalid_program_number"
        if reason:
            reasons.append({"race_key": race_key, "reason": reason})
        else:
            eligible.append(race_key)
    starters = runners[runners.race_key.isin(eligible) & ~runners.scratched].copy()
    api = pd.read_parquet(AUDIT / "api_study_population.parquet")
    fields = ["rank", "horse_number", "distance_m", "moisture"]
    starters = starters.merge(
        api[KEY + fields], on=KEY, how="left", suffixes=("", "_api"), validate="one_to_one"
    )
    for column in fields[:-1]:
        matched = starters[f"{column}_api"].notna()
        assert starters.loc[matched, column].eq(starters.loc[matched, f"{column}_api"]).all()
    moisture_missing = starters.groupby("race_key").moisture.apply(lambda s: s.isna().any())
    missing_keys = moisture_missing[moisture_missing].index
    reasons += [{"race_key": key, "reason": "missing_snapshot_moisture"} for key in missing_keys]
    starters = starters[~starters.race_key.isin(missing_keys)].copy()
    assert starters.groupby("race_key").moisture.nunique().eq(1).all()
    starters["band"] = pd.cut(starters.moisture, [0, 5, 9, 14, 19, np.inf], labels=BANDS).astype(
        str
    )
    starters["year"], starters["month"] = starters.dt.dt.year, starters.dt.dt.month
    starters["day_key"] = starters.meet.astype(int).astype(str) + ":" + starters.date
    starters["gate_pct"] = (
        starters.groupby("race_key").horse_number.rank(method="first") - 0.5
    ) / starters.n
    inv_odds = (1 / starters.odds).where(starters.odds.gt(0))
    starters["market_probability"] = inv_odds / inv_odds.groupby(starters.race_key).transform("sum")
    return starters, reasons


def positions(population):
    passing = pd.read_parquet(OUT / "passing_snapshot.parquet")
    passing = passing.rename(
        columns={"actual_meet_code": "meet", "event_date": "date", "canonical_point_code": "point"}
    )
    passing = passing[
        (passing.point.eq("S1F"))
        | (passing.meet.eq(1) & passing.point.eq("3C"))
        | (passing.meet.eq(3) & passing.point.eq("G4F"))
    ].copy()
    passing["race_key"] = (
        passing.meet.astype(str) + ":" + passing.date + ":" + passing.race_no.astype(str)
    )
    assert not passing.duplicated(["race_key", "point"]).any()
    look = {
        key: set(group.horse_number.astype(int)) for key, group in population.groupby("race_key")
    }
    records, issues = [], []
    for row in passing.itertuples(index=False):
        if row.race_key not in look:
            continue
        try:
            packs = parse(row.notation_raw)
        except ValueError as error:
            issues.append(
                {
                    "race_key": row.race_key,
                    "point": row.point,
                    "raw": row.notation_raw,
                    "reason": str(error),
                }
            )
            continue
        numbers = [number for pack in packs for number in pack["members"]]
        if set(numbers) != look[row.race_key]:
            issues.append(
                {
                    "race_key": row.race_key,
                    "point": row.point,
                    "raw": row.notation_raw,
                    "reason": "roster_mismatch",
                }
            )
            continue
        first, n, before = len(packs[0]["members"]), len(numbers), 0
        strict = first == 1 and len(packs) >= 2 and packs[1]["separator"] in ["-", "=", "≡"]
        for index, pack in enumerate(packs):
            relative = (before + (len(pack["members"]) + 1) / 2 - 1) / (n - 1)
            if index == 0:
                role = "solo" if first == 1 else "leading_pack"
            else:
                role = (
                    "stalking" if relative <= 1 / 3 else ("middle" if relative <= 2 / 3 else "rear")
                )
            for number in pack["members"]:
                records.append(
                    {
                        "race_key": row.race_key,
                        "point": row.point,
                        "horse_number": number,
                        "role": role,
                        "pack_index": index,
                        "pack_size": len(pack["members"]),
                        "pack_relative": relative,
                        "solo_two_lengths": strict,
                        "race_has_solo": first == 1,
                        "notation_raw": row.notation_raw,
                        "selected_source": row.selected_source,
                        "selection_status": row.selection_status,
                    }
                )
            before += len(pack["members"])
    frame = population.merge(
        pd.DataFrame(records), on=["race_key", "horse_number"], validate="one_to_many"
    )
    assert not frame.duplicated(KEY + ["point"]).any()
    assert (
        frame.groupby(["race_key", "point"])
        .horse_id.size()
        .eq(frame.groupby(["race_key", "point"]).n.first())
        .all()
    )
    return frame, issues


def raw_cells(frame):
    return (
        frame.groupby(["meet", "point", "distance_m", "band", "role"], observed=True)
        .agg(
            runners=("horse_id", "size"),
            races=("race_key", "nunique"),
            days=("day_key", "nunique"),
            win_rate=("win", "mean"),
            top3_rate=("top3", "mean"),
            rating=("rating", "mean"),
            prior_top3=("prior_top3", "mean"),
            market_probability=("market_probability", "mean"),
            prior_early=("prior_early", "mean"),
            field_size=("n", "mean"),
        )
        .reset_index()
    )


def design(frame, distance, linear=False, market=False):
    vectors, labels = [], []

    def add(label, vector):
        labels.append(label)
        vectors.append(np.asarray(vector, float))

    for role in ROLES[:-1]:
        indicator = frame.role.eq(role).to_numpy(float)
        add(f"role:{role}", indicator)
        if linear:
            add(f"moisture:{role}", indicator * (frame.moisture.to_numpy(float) - 4) / 5)
        else:
            for band in BANDS[1:]:
                add(f"interaction:{role}:{band}", indicator * frame.band.eq(band))
        for covariate in ["year", "month"] + (["distance_m"] if distance is None else []):
            for value in sorted(frame[covariate].unique())[1:]:
                add(f"nuisance:{role}:{covariate}:{value}", indicator * frame[covariate].eq(value))
    for column in CONTROLS + (["market_probability"] if market else []):
        values = frame[column].to_numpy(float)
        missing = ~np.isfinite(values)
        median = float(np.median(values[~missing])) if (~missing).any() else 0
        values = np.where(missing, median, values)
        scale = values.std()
        add(f"control:{column}", (values - values.mean()) / (scale if scale > 1e-10 else 1))
        if missing.any():
            add(f"missing:{column}", missing)
    return np.column_stack(vectors), labels


def cluster_fit(frame, x):
    race = pd.factorize(frame.race_key)[0]
    day = pd.factorize(frame.day_key)[0]
    n, races, days = len(frame), int(race.max()) + 1, int(day.max()) + 1
    counts = np.bincount(race)
    centered = x - np.column_stack([np.bincount(race, weights=v)[race] / counts[race] for v in x.T])
    y = frame.top3.to_numpy(float)
    y = y - np.bincount(race, weights=y)[race] / counts[race]
    weights = 1 / counts[race]
    xw, yw = centered * np.sqrt(weights[:, None]), y * np.sqrt(weights)
    gram = xw.T @ xw
    inverse = np.linalg.pinv(gram, rcond=1e-10)
    projection = inverse @ gram
    beta = inverse @ (xw.T @ yw)
    errors = yw - xw @ beta
    scores = xw * errors[:, None]
    sums = np.column_stack([np.bincount(day, weights=v, minlength=days) for v in scores.T])
    rank = int(np.linalg.matrix_rank(gram, tol=1e-8))
    correction = days / (days - 1) * (n - 1) / max(n - races - rank, 1)
    covariance = inverse @ (sums.T @ sums) @ inverse * correction
    return beta, covariance, projection, days, rank


def contrast(beta, covariance, projection, days, vector):
    error = float(np.max(np.abs(vector - vector @ projection)))
    if error > 1e-6:
        return {"estimable": False, "projection_error": error}
    effect = float(vector @ beta)
    se = float(np.sqrt(max(0, vector @ covariance @ vector)))
    cutoff = float(t.ppf(0.975, days - 1))
    p = float(2 * t.sf(abs(effect / se), days - 1)) if se > 1e-14 else 1.0
    return {
        "estimable": True,
        "effect_pp": effect * 100,
        "ci95_pp": [(effect - cutoff * se) * 100, (effect + cutoff * se) * 100],
        "p": p,
        "projection_error": error,
    }


def support(frame, role, band):
    cell = frame[frame.role.eq(role) & frame.band.eq(band)]
    return {
        "n": len(cell),
        "races": cell.race_key.nunique(),
        "days": cell.day_key.nunique(),
        "supported": bool(
            len(cell) >= 100 and cell.race_key.nunique() >= 30 and cell.day_key.nunique() >= 20
        ),
    }


def fit_cells(frame, mode="primary", linear=False, market=False):
    rows, diagnostics = [], []
    for (meet, point), venue in frame.groupby(["meet", "point"]):
        distances = [None] + sorted(set(venue.distance_m) & set(DISTANCES))
        for distance in distances:
            one = venue if distance is None else venue[venue.distance_m.eq(distance)]
            if one.race_key.nunique() < 100 or one.day_key.nunique() < 30:
                continue
            x, labels = design(one, distance, linear, market)
            beta, covariance, projection, days, rank = cluster_fit(one, x)
            lookup = {name: i for i, name in enumerate(labels)}
            diagnostics.append(
                {
                    "meet": int(meet),
                    "point": point,
                    "distance_m": distance,
                    "mode": mode,
                    "n": len(one),
                    "races": one.race_key.nunique(),
                    "days": days,
                    "columns": len(labels),
                    "rank": rank,
                }
            )
            for role in ROLES[:-1]:
                if linear:
                    vector = np.zeros(len(labels))
                    vector[lookup[f"moisture:{role}"]] = 1
                    rows.append(
                        {
                            "meet": int(meet),
                            "point": point,
                            "distance_m": distance,
                            "mode": mode,
                            "role": role,
                            "band": "per_5_percent",
                            "change": contrast(beta, covariance, projection, days, vector),
                            "support": support(one, role, "건조"),
                        }
                    )
                    continue
                # Standardize position-by-calendar (and distance when pooled) to
                # the equal-race-weight distribution shared by moisture groups.
                baseline = np.zeros(len(labels))
                baseline[lookup[f"role:{role}"]] = 1
                race_distribution = one.drop_duplicates("race_key")
                for name, index in lookup.items():
                    prefix = f"nuisance:{role}:"
                    if name.startswith(prefix):
                        covariate, value = name[len(prefix) :].split(":")
                        baseline[index] = float(
                            race_distribution[covariate].eq(int(float(value))).mean()
                        )
                dry = support(one, role, "건조")
                dry_rear = support(one, "rear", "건조")
                for band in BANDS:
                    change = np.zeros(len(labels))
                    if band != "건조":
                        change[lookup[f"interaction:{role}:{band}"]] = 1
                    cell, rear = support(one, role, band), support(one, "rear", band)
                    supported = (
                        cell["supported"]
                        and rear["supported"]
                        and dry["supported"]
                        and dry_rear["supported"]
                    )
                    rows.append(
                        {
                            "meet": int(meet),
                            "point": point,
                            "distance_m": distance,
                            "mode": mode,
                            "role": role,
                            "band": band,
                            "support": cell,
                            "rear_support": rear,
                            "dry_support": dry,
                            "dry_rear_support": dry_rear,
                            "supported": bool(supported),
                            "advantage_vs_rear": contrast(
                                beta, covariance, projection, days, baseline + change
                            ),
                            "change": contrast(beta, covariance, projection, days, change),
                            "dry_advantage_vs_rear": contrast(
                                beta, covariance, projection, days, baseline
                            ),
                        }
                    )
    return rows, diagnostics


def bh(values):
    values = np.asarray(values, float)
    order = np.argsort(values)
    n = len(values)
    corrected = np.minimum.accumulate((values[order] * n / np.arange(1, n + 1))[::-1])[::-1]
    result = np.empty(n)
    result[order] = np.clip(corrected, 0, 1)
    return result


def main():
    if (OUT / "summary.json").exists():
        raise FileExistsError("Refusing to overwrite analysis outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        OUT / "core_runner_snapshot.parquet",
        OUT / "passing_snapshot.parquet",
        SECTIONS,
        AUDIT / "api_study_population.parquet",
        AUDIT / "api_band_percent_conflicts.csv",
        AUDIT / "runner_clean_differences.csv",
    ]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    check_parser()
    runners = runners_with_priors()
    population, exclusions = eligible_population(runners)
    frame, issues = positions(population)
    conflicts = pd.read_csv(AUDIT / "api_band_percent_conflicts.csv")[KEY[:3]]
    times = pd.read_csv(AUDIT / "runner_clean_differences.csv", dtype={"horse_id": str})
    bad = pd.concat([conflicts, times[times.status.eq("different")][KEY[:3]]]).drop_duplicates()
    bad["race_key"] = bad.meet.astype(str) + ":" + bad.date + ":" + bad.race_no.astype(str)
    primary = frame[~frame.race_key.isin(bad.race_key)].copy()
    primary.to_parquet(OUT / "position_runners.parquet", index=False)
    pd.DataFrame(issues).to_csv(OUT / "notation_issues.csv", index=False)
    pd.DataFrame(exclusions).to_csv(OUT / "excluded_races.csv", index=False)
    raw_cells(primary).to_csv(OUT / "raw_position_cells.csv", index=False)
    raw_cells(frame).to_csv(OUT / "all_api_raw_position_cells.csv", index=False)
    summary = {
        "inputs_sha256": hashes,
        "no_track_speed": True,
        "eligible_population_runners": len(population),
        "eligible_population_races": population.race_key.nunique(),
        "quality_excluded_races": len(bad),
        "notation_issue_counts": dict(Counter(x["reason"] for x in issues)),
        "exclusion_counts": dict(Counter(x["reason"] for x in exclusions)),
        "modes": {},
    }
    modes = [
        ("primary", primary, False, False),
        ("all_api", frame, False, False),
        ("recent_2024plus", primary[primary.year.ge(2024)], False, False),
        (
            "solo_two_lengths",
            primary[~primary.race_has_solo | primary.solo_two_lengths],
            False,
            False,
        ),
        ("market_control", primary, False, True),
        ("linear_moisture", primary, True, False),
    ]
    for mode, sample, linear, market in modes:
        if mode != "primary":
            sample = sample[sample.point.eq("S1F")].copy()
        print(f"Fitting {mode}: {len(sample):,} position rows", flush=True)
        rows, diagnostics = fit_cells(sample, mode, linear, market)
        family = [
            r
            for r in rows
            if r["point"] == "S1F"
            and r["distance_m"] in DISTANCES
            and r["band"] not in ("건조", "per_5_percent")
            and r.get("supported")
            and r["change"]["estimable"]
        ]
        for row, q in zip(family, bh([r["change"]["p"] for r in family]), strict=True):
            row["q"] = float(q)
            row["candidate"] = bool(q < 0.05)
        result = {"rows": rows, "diagnostics": diagnostics, "bh_tests": len(family)}
        summary["modes"][mode] = result
        (OUT / f"{mode}_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if mode == "primary":
            print(
                json.dumps([r for r in family if r.get("candidate")], ensure_ascii=False),
                flush=True,
            )
    assert hashes == {str(path.relative_to(ROOT)): sha(path) for path in paths}
    summary["validation"] = {
        "inputs_unchanged": True,
        "read_only_source_snapshot": True,
        "strict_prior_history_dates": True,
        "normal_complete_rankings": True,
        "unique_runner_point_keys": True,
        "passing_rosters_match": True,
        "parser_examples_and_rejections_pass": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Completed all modes", flush=True)


if __name__ == "__main__":
    main()
