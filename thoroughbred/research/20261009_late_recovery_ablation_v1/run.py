"""Small frozen late/recovery/pressure ablations; local research writes only."""

import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / "outputs"
S = R / "20261009_section_style_finish_v1"
V = R / "20261009_axis_pool_validation_v1/outputs"
F = R / "20261009_failure_clusters_v1/outputs"
W = R / "20261008_profile_carried_weight_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


engine = module("section_style_finish_frozen", S / "run.py")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def config():
    return json.loads((HERE / "config.json").read_text())


def check():
    for name, expected in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == expected, name


def refs():
    paths = [HERE / n for n in ["PLAN.md", "config.json", "run.py", "analyze.py", "verify.py"]]
    paths += [
        S / n
        for n in ["run.py", "config.json", "outputs/features.parquet", "outputs/verification.json"]
    ]
    paths += [
        W / n for n in ["features_month_gate_weight22.parquet", "research_baseline_selection.json"]
    ]
    paths += [V / n for n in ["runner_inputs.parquet", "verification.json"]]
    paths += [
        F / n for n in ["runner_inputs.parquet", "verification.json", "selected_conditions.json"]
    ]
    paths += [ROOT / "config/prediction_model_registry.json"]
    for year in config()["evaluation_years"]:
        for meet in config()["venues"]:
            paths += [
                W / "models" / f"{meet}_{year}_month_gate_weight22" / n
                for n in ["top3.txt", "metadata.json"]
            ]
    return paths


def derive(f):
    """Only past runner attributes and today's declared peer roster."""
    out = pd.DataFrame(index=f.index)
    for part in ["last600", "late"]:
        col = "section_" + part + "_mean3"
        g = f.groupby("race_key")[col]
        count = g.transform("count") - f[col].notna().astype(int)
        others = (g.transform("sum") - f[col].fillna(0)) / count.replace(0, np.nan)
        out[part + "_relative_adv"] = others - f[col]
        out[part + "_percentile"] = g.rank(ascending=False, method="average", pct=True)
    role = f.style_role0_rate5.where(f.style_role_n5.ge(3))
    grouped = role.groupby(f.race_key)
    other_count = grouped.transform("count") - role.notna().astype(int)
    mass = grouped.transform("sum") - role.fillna(0)
    out["field_other_lead_mass"] = mass.where(other_count.gt(0))
    strong = role.ge(0.4).astype(float).where(role.notna())
    out["field_strong_front_n"] = (
        strong.groupby(f.race_key).transform("sum") - strong.fillna(0)
    ).where(other_count.gt(0))
    out["field_early_faster_n"] = np.nan
    out["field_early_support"] = np.nan
    early_values = f.section_early_mean3.where(f.section_early_n5.ge(3)).to_numpy()
    for ix in f.groupby("race_key", sort=False).indices.values():
        early = early_values[ix]
        known = np.isfinite(early)
        faster = (early[None, :] < early[:, None]).sum(1)
        supported = known.sum() - known.astype(int)
        out.loc[ix, "field_early_faster_n"] = np.where(known & (supported > 0), faster, np.nan)
        out.loc[ix, "field_early_support"] = supported / (len(ix) - 1)
    pressure = out.field_other_lead_mass / (f.field_size - 1)
    out["last600_x_lead_pressure"] = out.last600_relative_adv * pressure
    out["late_x_lead_pressure"] = out.late_relative_adv * pressure
    out["recovery_x_lead_pressure"] = f.style_recovery_mean5 * pressure
    return out


def prepare():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs()})
    baseline = json.loads((W / "research_baseline_selection.json").read_text())["features"]
    late = [
        "section_last600_mean3",
        "section_last600_n5",
        "section_late_mean3",
        "section_late_n5",
        "last600_relative_adv",
        "late_relative_adv",
        "last600_percentile",
        "late_percentile",
    ]
    recovery = ["style_recovery_mean5", "style_recovery_n5"]
    pressure = [
        "section_early_mean3",
        "section_early_n5",
        "style_role0_rate5",
        "style_role_n5",
        "field_other_lead_mass",
        "field_strong_front_n",
        "field_early_faster_n",
        "field_early_support",
        "last600_x_lead_pressure",
        "late_x_lead_pressure",
        "recovery_x_lead_pressure",
    ]
    contract = dict(
        baseline22=baseline,
        late30=baseline + late,
        recovery32=baseline + late + recovery,
        pressure43=baseline + late + recovery + pressure,
    )
    assert [len(x) for x in contract.values()] == [22, 30, 32, 43]
    meta = KEY + [
        "meet",
        "race_date",
        "year",
        "outcome",
        "history_source_date",
        "profile_source_date",
        "cutoff_date",
        "horse_name",
    ]
    original = pd.read_parquet(S / "outputs/features.parquet")
    source_cols = list(
        dict.fromkeys(
            meta + baseline + [c for c in late + recovery + pressure if c in original.columns]
        )
    )
    f = (
        original[source_cols]
        .sort_values(["meet", "race_date", "race_key", "program_no"])
        .reset_index(drop=True)
    )
    f = pd.concat([f, derive(f)], axis=1)
    assert f[baseline].equals(
        original.set_index(KEY)
        .loc[pd.MultiIndex.from_frame(f[KEY]), baseline]
        .reset_index(drop=True)
    )
    for cols in contract.values():
        assert len(cols) == len(set(cols))
        assert not any(
            "jockey" in c
            or "trainer" in c
            or c.startswith("aux_")
            or c in ["outcome", "program_no", "race_date"]
            for c in cols
        )
    f.to_parquet(OUT / "features.parquet", index=False)
    save(OUT / "feature_contract.json", contract)
    save(
        OUT / "features_complete.json",
        dict(
            rows=len(f),
            evaluation_rows=int(f.year.ge(2024).sum()),
            date_end=str(f.race_date.max().date()),
            feature_count={k: len(v) for k, v in contract.items()},
            features_sha256=sha(OUT / "features.parquet"),
        ),
    )
    check()
    print("Prepared", len(f), {k: len(v) for k, v in contract.items()}, flush=True)


def train():
    check()
    f = pd.read_parquet(OUT / "features.parquet")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    for variant in config()["variants"]:
        for meet in config()["venues"]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in config()["evaluation_years"]:
                folder = OUT / "models" / f"{variant}_{meet}_{year}"
                if (folder / "runners.parquet").exists():
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                with threadpool_limits(limits=4):
                    _, runners = engine.fit(one, contracts[variant], year, 3, variant, folder)
                runners.to_parquet(folder / "runners.parquet", index=False)
                print("Trained", variant, meet, year, flush=True)
    records = []
    for folder in sorted((OUT / "models").iterdir()):
        metadata = json.loads((folder / "metadata.json").read_text())
        p = pd.read_parquet(folder / "runners.parquet")
        p["tau"] = metadata["temperature"]
        records.append(p)
    inputs = pd.concat(records, ignore_index=True)
    old = pd.read_parquet(V / "runner_inputs.parquet")
    old = old[old.year.ge(2024) & old.model.eq("style_history53")].rename(
        columns={"score": "raw_score", "model": "variant"}
    )
    old["variant"] = "reference53"
    old["target"] = 3
    old["target_probability"] = np.nan
    inputs = pd.concat([inputs, old[inputs.columns]], ignore_index=True)
    # Preserve current and past condition context once in the common feature artifact.
    inputs.to_parquet(OUT / "runner_predictions.parquet", index=False)
    check()
    print("Predictions saved", len(inputs), flush=True)


def evaluate():
    check()
    p = pd.read_parquet(OUT / "runner_predictions.parquet")
    prior = pd.read_parquet(F / "runner_inputs.parquet")[
        KEY
        + [
            "model_rank",
            "top3",
            "g3f_pct",
            "g1f_pct",
            "section_last600_n5",
            "section_late_n5",
            "style_recovery_mean5",
            "style_recovery_n5",
        ]
    ]
    prior["signal"] = (
        prior.g3f_pct.ge(2 / 3)
        & prior.g1f_pct.ge(2 / 3)
        & prior.section_last600_n5.ge(3)
        & prior.section_late_n5.ge(3)
        & prior.style_recovery_mean5.ge(0.4)
        & prior.style_recovery_n5.ge(3)
    )
    p = p.merge(
        prior[KEY + ["model_rank", "signal"]].rename(columns={"model_rank": "baseline_rank"}),
        on=KEY,
        validate="many_to_one",
    )
    context = pd.read_parquet(OUT / "features.parquet")[
        KEY + ["distance_m", "grade", "field_size", "history_count"]
    ]
    p = p.merge(context, on=KEY, validate="many_to_one")
    rows, horses, tickets = [], [], []
    for (variant, rid), g in p.groupby(["variant", "race_key"], sort=True):
        g = g.sort_values("program_no").reset_index(drop=True)
        programs = g.program_no.to_numpy(int)
        order = np.lexsort((programs, -g.raw_score.to_numpy()))
        ranks = np.empty(len(g), int)
        ranks[order] = np.arange(1, len(g) + 1)
        sets = np.array(list(itertools.combinations(range(len(g)), 3)), int)
        energy = np.sort((g.raw_score.to_numpy() / g.tau.iloc[0])[sets], axis=1).sum(1)
        q = np.exp(energy - logsumexp(energy))
        take = np.argsort(-energy, kind="stable")[:6]
        truth = np.flatnonzero(g.outcome.between(1, 3).to_numpy())
        assert len(truth) == 3 and len(take) == 6
        truth_index = np.flatnonzero((sets == truth).all(1))[0]
        hit = int(truth_index in take)
        marginal = np.zeros(len(g))
        for j in range(3):
            np.add.at(marginal, sets[:, j], q)
        y = g.outcome.to_numpy()[order]
        win2 = set(np.flatnonzero((y >= 1) & (y <= 2)))
        winner_ranks = ranks[truth]
        baseline_rank = g.baseline_rank.to_numpy()
        actual_low = (baseline_rank >= 6) & g.outcome.between(1, 3).to_numpy()
        signal_winner = actual_low & g.signal.to_numpy()
        low_up = actual_low & (ranks <= 5)
        old_good = (baseline_rank <= 5) & g.outcome.between(1, 3).to_numpy()
        rows.append(
            dict(
                variant=variant,
                race_key=rid,
                race_date=str(g.race_date.iloc[0]),
                year=int(g.year.iloc[0]),
                meet=int(g.meet.iloc[0]),
                distance_m=float(g.distance_m.iloc[0]),
                grade=float(g.grade.iloc[0]) if pd.notna(g.grade.iloc[0]) else None,
                field_size=len(g),
                trio6=hit,
                axis_top3=int(1 <= y[0] <= 3),
                axis_top2=int(1 <= y[0] <= 2),
                axis_win=int(y[0] == 1),
                quinella_one=int(win2 == {0, 1}),
                quinella_box4=int(win2 <= set(range(4))),
                top5_contains_truth=int(winner_ranks.max() <= 5),
                low_winners=int(actual_low.sum()),
                low_winners_up=int(low_up.sum()),
                old_winners=int(old_good.sum()),
                old_winners_down=int((old_good & (ranks >= 6)).sum()),
                signal_low_winners=int(signal_winner.sum()),
                signal_winners_up=int((signal_winner & (ranks <= 5)).sum()),
                has_signal_low_winner=int(signal_winner.any()),
                set_logloss=float(-np.log(q[truth_index])),
                brier=float(np.mean((marginal - g.outcome.between(1, 3).to_numpy()) ** 2)),
                six_probability=float(q[take].sum()),
            )
        )
        for j, item in enumerate(g.itertuples()):
            horses.append(
                dict(
                    variant=variant,
                    race_key=rid,
                    program_no=int(item.program_no),
                    horse_id=item.horse_id,
                    year=int(item.year),
                    baseline_rank=int(item.baseline_rank),
                    model_rank=int(ranks[j]),
                    outcome=int(item.outcome),
                    signal=bool(item.signal),
                    probability=float(marginal[j]),
                )
            )
        for j in take:
            tickets.append(
                dict(
                    variant=variant,
                    race_key=rid,
                    combination="-".join(map(str, programs[sets[j]])),
                    probability=float(q[j]),
                    hit=int(j == truth_index),
                )
            )
    pd.DataFrame(rows).to_parquet(OUT / "race_metrics.parquet", index=False)
    pd.DataFrame(horses).to_parquet(OUT / "runner_metrics.parquet", index=False)
    pd.DataFrame(tickets).to_parquet(OUT / "six_tickets.parquet", index=False)
    check()
    print("Evaluated", len(rows), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train", "evaluate"])
    args = parser.parse_args()
    {"prepare": prepare, "train": train, "evaluate": evaluate}[args.stage]()
