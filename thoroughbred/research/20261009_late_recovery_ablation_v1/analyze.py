"""Fixed paired comparisons, gains/losses, and runner rescue accounting."""

import numpy as np
import pandas as pd
import run as e

HITS = [
    "trio6",
    "axis_top3",
    "axis_top2",
    "axis_win",
    "quinella_one",
    "quinella_box4",
    "top5_contains_truth",
]
PAIRS = [
    ("late30", "baseline22"),
    ("recovery32", "baseline22"),
    ("pressure43", "baseline22"),
    ("reference53", "baseline22"),
    ("recovery32", "late30"),
    ("pressure43", "recovery32"),
]


def windows(frame):
    return [
        ("all", frame),
        ("2024", frame[frame.year.eq(2024)]),
        ("2025", frame[frame.year.eq(2025)]),
        ("2026", frame[frame.year.eq(2026)]),
        ("2025_2026", frame[frame.year.ge(2025)]),
    ]


def boot(frame, difference, denominator=None):
    value = np.asarray(difference, float)
    den = np.ones(len(frame)) if denominator is None else np.asarray(denominator, float)
    codes, dates = pd.factorize(frame.race_date, sort=True)
    totals = np.bincount(codes, weights=value, minlength=len(dates))
    counts = np.bincount(codes, weights=den, minlength=len(dates))
    ix = np.random.default_rng(e.config()["bootstrap_seed"]).integers(
        0, len(dates), (e.config()["bootstrap_draws"], len(dates))
    )
    d = counts[ix].sum(1)
    estimates = totals[ix].sum(1) / np.maximum(d, 1)
    lo, hi = np.quantile(estimates, [0.025, 0.975])
    return float(lo), float(hi)


def summary(g, variant, period):
    out = dict(
        variant=variant,
        period=period,
        races=len(g),
        low_winners=int(g.low_winners.sum()),
        low_winners_up=int(g.low_winners_up.sum()),
        low_winner_recall=float(g.low_winners_up.sum() / g.low_winners.sum()),
        old_winners=int(g.old_winners.sum()),
        old_winners_down=int(g.old_winners_down.sum()),
        old_winner_loss_rate=float(g.old_winners_down.sum() / g.old_winners.sum()),
        signal_winners=int(g.signal_low_winners.sum()),
        signal_winners_up=int(g.signal_winners_up.sum()),
        signal_recall=float(g.signal_winners_up.sum() / g.signal_low_winners.sum()),
        set_logloss=float(g.set_logloss.mean()),
        brier=float(g.brier.mean()),
    )
    for col in HITS:
        out[col + "_hits"] = int(g[col].sum())
        out[col + "_rate"] = float(g[col].mean())
    return out


def main():
    e.check()
    r = pd.read_parquet(e.OUT / "race_metrics.parquet")
    totals, paired, strata, signals = [], [], [], []
    for variant, one in r.groupby("variant"):
        for period, g in windows(one):
            totals.append(summary(g, variant, period))
        one = one.copy()
        one["distance_band"] = pd.cut(
            one.distance_m, [-1, 1300, 1600, 10000], labels=["short", "middle", "long"]
        )
        one["field_band"] = pd.cut(
            one.field_size, [0, 9, 11, 100], labels=["6_9", "10_11", "12plus"]
        )
        one["grade_band"] = np.select(
            [one.grade.eq(6), one.grade.eq(5), one.grade.between(1, 4)],
            ["6", "5", "1_4"],
            default="other",
        )
        for kind in ["distance_band", "field_band", "grade_band"]:
            for key, g in one.groupby(kind, observed=True):
                strata.append(summary(g, variant, "all") | dict(stratum=kind, value=str(key)))
    for candidate, base in PAIRS:
        a = r[r.variant.eq(candidate)].set_index("race_key").sort_index()
        b = r[r.variant.eq(base)].set_index("race_key").sort_index()
        assert a.index.equals(b.index)
        for period, g in windows(a):
            control = b.loc[g.index]
            for col in HITS + ["set_logloss", "brier"]:
                delta = g[col] - control[col]
                lo, hi = boot(g, delta)
                rec = dict(
                    candidate=candidate,
                    baseline=base,
                    period=period,
                    metric=col,
                    races=len(g),
                    difference=float(delta.mean()),
                    ci_low=lo,
                    ci_high=hi,
                )
                if col in HITS:
                    rec.update(
                        gained=int(((g[col] == 1) & (control[col] == 0)).sum()),
                        lost=int(((g[col] == 0) & (control[col] == 1)).sum()),
                    )
                paired.append(rec)
            signal_races = g[g.has_signal_low_winner.eq(1)]
            ctrl = control.loc[signal_races.index]
            signals.append(
                dict(
                    candidate=candidate,
                    baseline=base,
                    period=period,
                    races=len(signal_races),
                    hits=int(signal_races.trio6.sum()),
                    gained=int((signal_races.trio6.eq(1) & ctrl.trio6.eq(0)).sum()),
                    lost=int((signal_races.trio6.eq(0) & ctrl.trio6.eq(1)).sum()),
                    low_winners=int(signal_races.signal_low_winners.sum()),
                    winners_up=int(signal_races.signal_winners_up.sum()),
                )
            )
    pd.DataFrame(totals).to_csv(e.OUT / "summary.csv", index=False)
    pd.DataFrame(paired).to_csv(e.OUT / "paired_differences.csv", index=False)
    pd.DataFrame(strata).to_csv(e.OUT / "stratified_summary.csv", index=False)
    pd.DataFrame(signals).to_csv(e.OUT / "signal_race_gains_losses.csv", index=False)
    base = r[r.variant.eq("baseline22")].set_index("race_key")
    events = []
    for candidate in ["late30", "recovery32", "pressure43", "reference53"]:
        g = r[r.variant.eq(candidate)].set_index("race_key")
        flip = g.trio6.ne(base.loc[g.index].trio6)
        events.append(
            g[flip]
            .reset_index()
            .assign(change=np.where(g.loc[flip, "trio6"].to_numpy() == 1, "gained", "lost"))
        )
    pd.concat(events, ignore_index=True).to_csv(e.OUT / "trio_changed_races.csv", index=False)
    e.check()
    print(pd.DataFrame(totals).query("period=='all'").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
