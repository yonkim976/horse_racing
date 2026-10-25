"""Source-level feature controls, frozen-model replay and independent probability math."""

import argparse
import itertools
import json
import re
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
import research as c
import lightgbm as lgb
import duckdb


def features():
    c.check()
    f = c.base_frame()
    sample = f.iloc[np.linspace(0, len(f) - 1, 52).astype(int)].reset_index(drop=True)
    h, sanctions = c.sources()
    actual = c.construct(sample, h, sanctions)
    expected = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for r in sample.itertuples():
            past = h[h.horse_id.eq(r.horse_id) & h.race_date.le(r.cutoff_date)].sort_values(
                "race_date", ascending=False
            )
            last = past.iloc[0] if len(past) else None
            body = past.head(5).body_weight
            b = {
                "body_previous_kg": float(body.iloc[0]) if len(body) else np.nan,
                "body_mean3_kg": body.head(3).mean(),
                "body_previous_vs_prior3_kg": float(body.iloc[0]) - body.iloc[1:4].mean()
                if len(body)
                else np.nan,
                "body_sd5_kg": body.std(ddof=0) if body.notna().sum() >= 2 else np.nan,
                "body_n5": int(body.notna().sum()),
                "burden_pct_previous_body": 100 * r.current_carried_weight / body.iloc[0]
                if len(body)
                else np.nan,
                "report_support3": float(past.head(3).report_available.eq(1).mean())
                if len(past)
                else np.nan,
                "report_mentions_last": last.mentions if last is not None else np.nan,
                "report_mentions_mean3": past.head(3).mentions.mean(),
            }
            for name in c.REPORT_TERMS:
                b["report_" + name + "_last"] = last[name] if last is not None else np.nan
            old = sanctions[
                sanctions.horse_id.eq(r.horse_id) & sanctions.race_date.le(r.cutoff_date)
            ]
            recent = old[old.race_date.gt(r.cutoff_date - pd.Timedelta(days=90))]
            for source, target in [
                ("count", "sanctions90"),
                ("start", "sanction_start90"),
                ("running", "sanction_running90"),
                ("vet", "sanction_vet90"),
            ]:
                b[target] = float(recent[source].sum())
            gap = (r.race_date - old.race_date.max()).days if len(old) else np.nan
            b["sanction_gap365"] = gap if gap <= 367 else np.nan
            expected.append(b)
    cols = c.REPORT_COLS + c.BODY_COLS
    np.testing.assert_allclose(
        actual[cols],
        pd.DataFrame(expected)[cols].map(lambda x: np.nan if pd.isna(x) else float(x)),
        atol=1e-10,
        rtol=0,
        equal_nan=True,
    )
    poison = h.iloc[:1].copy()
    poison["race_date"] = pd.Timestamp("2027-01-01")
    poison["body_weight"] = 650.0
    poison[["mentions", *c.REPORT_TERMS]] = 999.0
    poison["report_available"] = 1.0
    sh = sanctions.iloc[:1].copy()
    sh["race_date"] = pd.Timestamp("2027-01-01")
    sh[["count", *c.SANCTION_TERMS]] = 999.0
    future_checks = 0
    # Repeat for every sampled official horse ID; future events cannot affect inputs.
    hh, ss = [], []
    for horse in sample.horse_id.unique():
        hh.append(poison.assign(horse_id=horse))
        ss.append(sh.assign(horse_id=horse))
    hh = (
        pd.concat([h, *hh], ignore_index=True)
        .sort_values(["horse_id", "race_date"])
        .reset_index(drop=True)
    )
    ss = (
        pd.concat([sanctions, *ss], ignore_index=True)
        .sort_values(["horse_id", "race_date"])
        .reset_index(drop=True)
    )
    future = c.construct(sample, hh, ss)
    np.testing.assert_allclose(actual[cols], future[cols], atol=0, rtol=0, equal_nan=True)
    future_checks += len(sample) * len(cols)
    parser_checks = 0
    with duckdb.connect(str(c.CORE), read_only=True) as db:
        for row in (
            h[h.report_available.eq(1) & h.mentions.gt(0)]
            .iloc[
                np.linspace(
                    0, int((h.report_available.eq(1) & h.mentions.gt(0)).sum()) - 1, 24
                ).astype(int)
            ]
            .itertuples()
        ):
            meet, date, race = row.race_key.split(":")
            paragraphs = db.execute(
                """SELECT DISTINCT paragraph_raw FROM horse_steward_history
                WHERE horse_id=? AND actual_meet_code=? AND replace(event_date,'-','')=? AND race_no=?
                AND source_report_text_field='judgement' AND parent_report_event_date=event_date""",
                [row.horse_id, int(meet), date, int(race)],
            ).fetchall()
            c.require(len(paragraphs) == row.mentions)
            for name, pattern in c.REPORT_TERMS.items():
                c.require(
                    int(any(re.search(pattern, p[0]) is not None for p in paragraphs))
                    == int(getattr(row, name))
                )
                parser_checks += 1
    saved = pd.read_parquet(c.OUT / "feature_delta.parquet").set_index("row_number")
    np.testing.assert_allclose(
        saved.loc[sample.row_number, cols], actual[cols], atol=0, rtol=0, equal_nan=True
    )
    result = {
        "status": "passed",
        "independent_feature_values": len(sample) * len(cols),
        "future_insertion_values": future_checks,
        "raw_paragraph_pattern_checks": parser_checks,
        "feature_sha256": c.sha(c.OUT / "feature_delta.parquet"),
        "historical_publication_time_verified": False,
    }
    c.save(c.OUT / "feature_verification.json", result)
    print(json.dumps(result), flush=True)


def models():
    c.check()
    f = c.frame()
    count, values, maximum, temp_error = 0, 0, 0.0, 0.0
    for path in sorted((c.OUT / "models").glob("*/metadata.json")):
        m = json.loads(path.read_text())
        model = lgb.Booster(model_file=str(path.parent / "model.txt"))
        c.require(c.sha(path.parent / "model.txt") == m["model_sha256"])
        one = f[f.meet.eq(m["meet"]) & f.year.isin([m["year"] - 1, m["year"]])].copy()
        x, _ = c.previous.old.base.encode(one, m["features"], vocabulary=m["category_vocabulary"])
        pred = pd.Series(model.predict(x, raw_score=True, num_threads=4), index=one.row_number)
        old = pd.read_parquet(path.parent / "scores.parquet")
        error = float(np.max(np.abs(old.score - old.row_number.map(pred))))
        c.require(error < 1e-12, "Model replay mismatch")
        maximum = max(maximum, error)
        cal = one[one.year.eq(m["year"] - 1)].copy()
        cal["score"] = cal.row_number.map(pred)
        energies, truths, ordered = [], [], []
        for _, g in cal.groupby("race_key", sort=False):
            score = g.score.to_numpy()
            sets = np.array(list(itertools.combinations(range(len(g)), 3)))
            energies.append(score[sets].sum(1))
            truths.append(score[g.outcome.between(1, 3)].sum())
            ordered.append(
                np.array([score[np.flatnonzero(g.outcome.to_numpy() == j)[0]] for j in [1, 2, 3]])
            )
        width = max(map(len, energies))
        matrix = np.full((len(energies), width), -np.inf)
        for i, e in enumerate(energies):
            matrix[i, : len(e)] = e
        truths, ordered = np.array(truths), np.array(ordered)
        st = minimize_scalar(
            lambda t: float(np.mean(logsumexp(matrix / t, axis=1) - truths / t)),
            bounds=(0.35, 4.0),
            method="bounded",
        )
        ot = minimize_scalar(
            lambda t: float(
                np.mean(
                    logsumexp(ordered / t, axis=1)
                    - ordered[:, 0] / t
                    + np.logaddexp(ordered[:, 1] / t, ordered[:, 2] / t)
                    - ordered[:, 1] / t
                )
            ),
            bounds=(0.35, 4.0),
            method="bounded",
        )
        delta = max(abs(float(st.x) - m["temperature"]), abs(float(ot.x) - m["order_temperature"]))
        c.require(delta < 1e-5, "Calibration mismatch")
        temp_error = max(temp_error, delta)
        count += 1
        values += len(old)
        print("Verified model", path.parent.name, flush=True)
    c.require(count == 18)
    c.save(
        c.OUT / "model_verification.json",
        {
            "status": "passed",
            "models": count,
            "replayed_scores": values,
            "max_score_error": maximum,
            "max_independent_temperature_error": temp_error,
        },
    )


def numbers():
    c.check()
    f = c.base_frame()
    metrics = pd.read_parquet(c.OUT / "race_metrics.parquet")
    runners = pd.read_parquet(c.OUT / "runner_probabilities.parquet")
    tickets = pd.read_parquet(c.OUT / "tickets.parquet")
    require_cols = ["variant", "race_key", "program_no"]
    c.require(not runners.duplicated(require_cols).any())
    for variant in c.VARIANTS:
        c.require(metrics[metrics.variant.eq(variant)].race_key.nunique() == 4799)
        c.require(len(runners[runners.variant.eq(variant)]) == 50754)
    # Independent direct enumeration of all ordered triples on 3 races per fold.
    error, races = 0.0, 0
    for path in sorted((c.OUT / "models").glob("*/metadata.json")):
        meta = json.loads(path.read_text())
        rows = metrics[
            metrics.variant.eq(meta["variant"])
            & metrics.meet.eq(meta["meet"])
            & metrics.year.eq(meta["year"])
        ]
        selected = rows.iloc[np.linspace(0, len(rows) - 1, 3).astype(int)]
        scores = (
            pd.read_parquet(path.parent / "scores.parquet")
            .query("phase=='evaluation'")
            .set_index("row_number")
            .score
        )
        for row in selected.itertuples():
            g = f[f.race_key.eq(row.race_key)].sort_values("program_no")
            s = g.row_number.map(scores).to_numpy(float)
            sets = list(itertools.combinations(range(len(g)), 3))
            q = np.exp(
                np.array([sum(s[list(t)]) / meta["temperature"] for t in sets])
                - logsumexp([sum(s[list(t)]) / meta["temperature"] for t in sets])
            )
            u = np.exp((s - s.max()) / meta["order_temperature"])
            wp = np.zeros((len(g), len(g)))
            qp = wp.copy()
            marginals = np.zeros((len(g), 3))
            outcome = g.outcome.to_numpy()
            actual_set = np.flatnonzero((outcome >= 1) & (outcome <= 3))
            true_order = tuple(int(np.flatnonzero(outcome == j)[0]) for j in [1, 2, 3])
            order_mass = {}
            for group, prob in zip(sets, q):
                for a, b, d in itertools.permutations(group):
                    mass = prob * u[a] / sum(u[list(group)]) * u[b] / (u[b] + u[d])
                    order_mass[a, b, d] = mass
                    marginals[a, 0] += mass
                    marginals[[a, b], 1] += mass
                    marginals[[a, b, d], 2] += mass
                    qp[a, b] += mass
                    qp[b, a] += mass
                    for i, j in itertools.combinations([a, b, d], 2):
                        wp[i, j] += mass
                        wp[j, i] += mass
            saved = runners[
                runners.variant.eq(meta["variant"]) & runners.race_key.eq(row.race_key)
            ].sort_values("program_no")
            error = max(
                error, float(np.max(np.abs(saved[["win", "top2", "top3"]].to_numpy() - marginals)))
            )
            axis = int(np.argsort(-np.round(marginals[:, 2], 12), kind="stable")[0])
            c.require(int(g.program_no.iloc[axis]) == row.axis_program_no)
            for pool, matrix in [("quinella", qp), ("qpl", wp)]:
                pairs = list(itertools.combinations(range(len(g)), 2))
                chosen = sorted(pairs, key=lambda pair: -round(float(matrix[pair]), 12))[:3]
                old = tickets[
                    tickets.variant.eq(meta["variant"])
                    & tickets.race_key.eq(row.race_key)
                    & tickets.pool.eq(pool)
                ].sort_values("rank")
                c.require(
                    list(zip(old.program_a, old.program_b))
                    == [(int(g.program_no.iloc[i]), int(g.program_no.iloc[j])) for i, j in chosen]
                )
            best6 = np.argsort(-np.round(q, 12), kind="stable")[:6]
            c.require(
                int(any(np.array_equal(np.array(sets[i]), actual_set) for i in best6))
                == row.trio_six
            )
            error = max(error, abs(-np.log(order_mass[true_order]) - row.ordered_logloss))
            races += 1
    c.require(error < 1e-10)
    c.save(
        c.OUT / "numeric_verification.json",
        {
            "status": "passed",
            "independent_races": races,
            "max_probability_or_loss_error": error,
            "all_runners_retained": True,
            "same_fixed_ticket_budgets": True,
            "operating_registry_unchanged": True,
        },
    )
    print("Independent numbers", races, error, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["features", "models", "numbers"])
    args = parser.parse_args()
    globals()[args.stage]()
