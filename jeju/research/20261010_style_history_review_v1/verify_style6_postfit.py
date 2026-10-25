"""Independent read-only replay and target-row perturbation audit for F1_STYLE6.

The script reloads saved LightGBM files only. It does not train, optimize tau,
write to the database, or alter any source/model/report artifact. Its only
outputs are a JSON receipt and compact CSV tables in this review folder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import sqlite3
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ABLA = ROOT / "jeju/research/20261010_style_history_ablation_v1"
AB_OUT = ABLA / "outputs"
REPORT_DIR = AB_OUT / "report"
BASE = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
BASE_OUT = BASE / "outputs"
PROFILE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2"
R1 = ROOT / "jeju/research/20261009_field_relative_ability_v1/outputs"
SOURCE = ROOT / "jeju/research/20261010_style_history_source_audit_v1"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
OP = ROOT / "jeju/research/20261009_operating_model_comparison_v1/outputs"
YEARS = (2024, 2025, 2026)
SEED = 20261008
REPS = 2000
ATOL = 1e-12
SAMPLES = {
    "zero_history": 179155,
    "partial_history": 179156,
    "full_five_history": 179159,
    "distance_1300": 176361,
    "history_conflict": 179196,
    "invalid_time_no_backfill": 175756,
    "target_after_t_minus_2": 179157,
}


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def near(a, b, atol=ATOL):
    return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                       rtol=0, atol=atol, equal_nan=True)


def import_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transform(frame, meta):
    cols = list(meta["features"])
    x = frame[cols].copy()
    for col, vocab in meta["vocabulary"].items():
        assert col in cols
        x[col] = pd.Categorical(x[col].astype("string"), categories=vocab)
    return x


def score(model, frame, meta):
    assert list(model.feature_name()) == list(meta["features"])
    return model.predict(transform(frame, meta), raw_score=True, num_threads=4)


def eval_race(frame, z, tau, variant):
    frame = frame.reset_index(drop=True)
    n = len(frame)
    assert n >= 6 and frame.horse_number.is_monotonic_increasing
    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    energy = np.sort(np.asarray(z)[triples], axis=1).sum(axis=1)
    log_q = energy / float(tau) - logsumexp(energy / float(tau))
    q = np.exp(log_q)
    incidence = np.zeros((len(triples), n), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    p = q @ incidence
    assert np.isclose(q.sum(), 1.0, rtol=0, atol=1e-12)
    assert np.isclose(p.sum(), 3.0, rtol=0, atol=1e-10)
    y = frame.finish_position.to_numpy(dtype=float) <= 3
    assert int(y.sum()) == 3
    clipped = np.clip(p, 1e-12, 1.0 - 1e-12)
    y_float = y.astype(np.float64)
    ll = -y_float * np.log(clipped) - (~y).astype(np.float64) * np.log1p(-clipped)
    brier = (p - y_float) ** 2
    truth = set(np.flatnonzero(y).tolist())
    truth_ticket = int(np.flatnonzero(np.asarray([(set(t) == truth) for t in triples]))[0])
    pick_order = np.argsort(-np.asarray(z), kind="stable")
    top6 = np.argsort(-energy, kind="stable")[:6]
    race = {
        "race_id": str(frame.race_id.iloc[0]),
        "race_date": str(frame.race_date.iloc[0]),
        "year": int(frame.year.iloc[0]),
        "variant": variant,
        "distance_m": int(frame.distance_m.iloc[0]),
        "grade_raw": frame.grade_raw.iloc[0],
        "field_n": n,
        "any_no_history": bool(frame.observed_starts.eq(0).any()),
        "any_low_history": bool(frame.observed_starts.lt(5).any()),
        "any_no_same_time": bool(frame.same_valid_times.eq(0).any()),
        "log_loss": float(ll.mean()),
        "brier": float(brier.mean()),
        "trio_nll": float(-log_q[truth_ticket]),
        "six_combo_hit": int(truth_ticket in set(top6.tolist())),
        "six_combo_mass": float(q[top6].sum()),
        "pick_hit": int(bool(y[pick_order[0]])),
    }
    for k in (3, 4, 5, 6):
        chosen = set(pick_order[:k].tolist())
        race[f"top{k}_capture"] = len(truth & chosen) / 3.0
        race[f"top{k}_all3"] = int(truth.issubset(chosen))
    numbers = frame.horse_number.to_numpy(dtype=int)
    tickets = []
    for rank, idx in enumerate(top6, 1):
        combo = triples[idx]
        tickets.append({
            "race_id": str(frame.race_id.iloc[0]),
            "variant": variant,
            "selection_rank": rank,
            "numbers": ",".join(str(int(numbers[k])) for k in combo),
            "probability": float(q[idx]),
            "hit": int(idx == truth_ticket),
        })
    runners = []
    for i, row in enumerate(frame.itertuples(index=False)):
        runners.append({
            "api_record_id": int(row.api_record_id), "race_id": str(row.race_id),
            "race_date": str(row.race_date), "year": int(row.year),
            "distance_m": int(row.distance_m), "grade_raw": row.grade_raw,
            "horse_id": str(row.horse_id), "horse_number": int(row.horse_number),
            "observed_starts": int(row.observed_starts),
            "same_valid_times": int(row.same_valid_times), "field_n": n,
            "variant": variant, "score": float(z[i]), "p_top3": float(p[i]),
            "y": int(y[i]), "log_loss": float(ll[i]), "brier": float(brier[i]),
            "previous_result_status": str(row.previous_result_status),
            "previous_top3": row.previous_top3,
            "same_distance_last5_actual_n": int(row.same_distance_last5_actual_n),
            "same_distance_last5_normal_n": int(row.same_distance_last5_normal_n),
            "hist_s1f_relpos_n": int(row.hist_s1f_relpos_n),
            "hist_s1f_to_c4_pair_n": int(row.hist_s1f_to_c4_pair_n),
            "hist_c4_to_g1f_pair_n": int(row.hist_c4_to_g1f_pair_n),
        })
    return race, runners, tickets, q, p, triples, energy


def prediction_distribution(frame, z, tau):
    """Probability-only evaluator for perturbations, independent of labels."""
    frame = frame.reset_index(drop=True)
    n = len(frame)
    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    energy = np.sort(np.asarray(z)[triples], axis=1).sum(axis=1)
    q = np.exp(energy / float(tau) - logsumexp(energy / float(tau)))
    incidence = np.zeros((len(triples), n), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    p = q @ incidence
    best = np.argsort(-energy, kind="stable")[:6]
    numbers = frame.horse_number.to_numpy(dtype=int)
    canonical = [tuple(int(numbers[i]) for i in triples[j]) for j in best]
    assert np.isclose(q.sum(), 1.0, rtol=0, atol=1e-12)
    assert np.isclose(p.sum(), 3.0, rtol=0, atol=1e-10)
    return q, p, canonical


def sorted_equal(saved, calc, keys, numeric=(), strings=()):
    a = saved.sort_values(keys, kind="stable").reset_index(drop=True)
    b = calc.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(a) == len(b), (len(a), len(b))
    for col in list(keys) + list(strings):
        assert a[col].fillna("<NA>").astype(str).equals(b[col].fillna("<NA>").astype(str)), col
    for col in numeric:
        assert near(pd.to_numeric(a[col], errors="coerce"),
                    pd.to_numeric(b[col], errors="coerce")), col


def bootstrap(frame, metric):
    assert frame.api_record_id.is_unique if "api_record_id" in frame else frame.race_id.is_unique
    daily = frame.groupby("race_date", sort=True).delta.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    index = rng.integers(0, len(daily), size=(REPS, len(daily)))
    samples = daily["sum"].to_numpy()[index].sum(axis=1) / daily["size"].to_numpy()[index].sum(axis=1)
    return {
        "delta_candidate_minus_f1": float(frame.delta.mean()),
        "ci95_low": float(np.quantile(samples, .025)),
        "ci95_high": float(np.quantile(samples, .975)),
        "races": int(frame.race_id.nunique()), "race_days": int(frame.race_date.nunique()),
        "resamples": REPS, "seed": SEED,
    }


def bootstrap_races(candidate, baseline, metric):
    a = candidate[["race_id", "race_date", metric]].rename(columns={metric: "candidate"})
    b = baseline[["race_id", metric]].rename(columns={metric: "f1"})
    pair = a.merge(b, on="race_id", how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    pair["delta"] = pair.candidate - pair.f1
    return bootstrap(pair, metric)


def compare_report(races, runners, tickets):
    saved_r = pd.read_parquet(REPORT_DIR / "race_metrics.parquet")
    saved_u = pd.read_parquet(REPORT_DIR / "runner_predictions.parquet")
    saved_t = pd.read_csv(REPORT_DIR / "canonical_six_combinations.csv")
    metric_cols = ["log_loss", "brier", "trio_nll", "six_combo_hit", "six_combo_mass",
                   "top3_capture", "top3_all3", "top4_capture", "top4_all3",
                   "top5_capture", "top5_all3", "top6_capture", "top6_all3", "pick_hit"]
    sorted_equal(saved_r, races, ["variant", "race_id"], numeric=metric_cols,
                 strings=["race_date", "grade_raw"])
    sorted_equal(saved_u, runners, ["variant", "api_record_id"],
                 numeric=["score", "p_top3", "y", "log_loss", "brier", "field_n"],
                 strings=["race_id", "race_date", "horse_id", "grade_raw", "previous_result_status"])
    sorted_equal(saved_t, tickets, ["variant", "race_id", "selection_rank"],
                 numeric=["probability", "hit"], strings=["numbers"])
    return True


def paired_report(races, runners, features):
    rows = []
    primary = ["log_loss", "brier"]
    secondary = ["top5_capture", "top5_all3", "six_combo_hit", "pick_hit"]
    merged = races.loc[races.variant.eq("F1_STYLE6")].merge(
        races.loc[races.variant.eq("F1"), ["race_id", "race_date", "year", "distance_m"] + primary + secondary],
        on="race_id", how="inner", suffixes=("_candidate", "_f1"), validate="one_to_one")
    assert len(merged) == 1779
    groups = [("all", "all", merged)]
    groups.extend(("year", str(int(y)), g) for y, g in merged.groupby("year_candidate", sort=True))
    groups.extend(("distance_m", str(int(d)), g) for d, g in merged.groupby("distance_m_candidate", sort=True))
    for kind, value, group in groups:
        for metric in primary + secondary:
            pair = group[["race_id", "race_date_candidate", f"{metric}_candidate", f"{metric}_f1"]].copy()
            pair = pair.rename(columns={"race_date_candidate": "race_date"})
            pair["delta"] = pair[f"{metric}_candidate"] - pair[f"{metric}_f1"]
            rows.append({"group": kind, "value": value, "metric": metric, **bootstrap(pair, metric)})
    calc = pd.DataFrame(rows)
    saved = pd.read_csv(REPORT_DIR / "paired_date_bootstrap.csv")
    sorted_equal(saved, calc, ["group", "value", "metric"],
                 numeric=["delta_candidate_minus_f1", "ci95_low", "ci95_high", "races",
                          "race_days", "resamples", "seed"])
    overall = calc.loc[calc.group.eq("all") & calc.metric.isin(primary)].set_index("metric")
    gate = bool((overall.delta_candidate_minus_f1 < 0).all()
                and (overall.ci95_high < 0).any())
    receipt = json.loads((REPORT_DIR / "report_receipt.json").read_text())
    saved_gate = receipt["primary_gate"]
    assert gate == saved_gate["primary_gate_passed"]
    assert set(saved_gate["primary_point_differences"]) == set(primary)
    assert set(saved_gate["primary_ci95_upper"]) == set(primary)
    for metric in primary:
        assert near([overall.loc[metric, "delta_candidate_minus_f1"]],
                    [saved_gate["primary_point_differences"][metric]])
        assert near([overall.loc[metric, "ci95_high"]],
                    [saved_gate["primary_ci95_upper"][metric]])
    return calc, gate


def conditional_losses(runners, features):
    keys = ["api_record_id", "race_id", "race_date", "year", "distance_m"]
    c = runners.loc[runners.variant.eq("F1_STYLE6"), keys + ["log_loss", "brier"]].rename(
        columns={"log_loss": "log_loss_candidate", "brier": "brier_candidate"})
    f = runners.loc[runners.variant.eq("F1"), keys + ["log_loss", "brier"]].rename(
        columns={"log_loss": "log_loss_f1", "brier": "brier_f1"})
    pair = c.merge(f, on=keys, how="inner", validate="one_to_one")
    context = features[["api_record_id", "observed_starts", "hist_s1f_relpos_n",
                         "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_pair_n"]]
    pair = pair.merge(context, on="api_record_id", how="left", validate="one_to_one")
    career = pd.cut(pair.observed_starts, [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"])
    groups = [("all", "all", pair)]
    groups.extend(("year", str(int(y)), g) for y, g in pair.groupby("year", sort=True))
    groups.extend(("distance_m", str(int(d)), g) for d, g in pair.groupby("distance_m", sort=True))
    groups.extend(("career_observed_starts", k, pair.loc[career.astype("string").eq(k)])
                  for k in ("0", "1_4", "5_plus"))
    for name, col in (("s1f_position", "hist_s1f_relpos_n"),
                      ("s1f_to_4c_change", "hist_s1f_to_c4_pair_n"),
                      ("4c_to_g1f_change", "hist_c4_to_g1f_pair_n")):
        groups.extend((f"history_valid_n:{name}", str(n), pair.loc[pair[col].eq(n)]) for n in range(6))
        groups.append((f"history_availability:{name}", "unknown_no_valid_history", pair.loc[pair[col].eq(0)]))
        groups.append((f"history_availability:{name}", "has_valid_history", pair.loc[pair[col].gt(0)]))
    rows = []
    for kind, value, subset in groups:
        for metric in ("log_loss", "brier"):
            if subset.empty:
                rows.append(dict(group=kind, value=value, metric=metric, runner_rows=0,
                                 races=0, race_days=0, delta_candidate_minus_f1=np.nan,
                                 ci95_low=np.nan, ci95_high=np.nan, resamples=REPS, seed=SEED))
                continue
            w = subset[["api_record_id", "race_id", "race_date", f"{metric}_candidate", f"{metric}_f1"]].copy()
            w["delta"] = w[f"{metric}_candidate"] - w[f"{metric}_f1"]
            s = bootstrap(w, metric)
            rows.append(dict(group=kind, value=value, metric=metric,
                             runner_rows=len(w), **s))
    calc = pd.DataFrame(rows)
    saved = pd.read_csv(REPORT_DIR / "conditional_runner_losses.csv")
    sorted_equal(saved, calc, ["group", "value", "metric"],
                 numeric=["runner_rows", "races", "race_days", "delta_candidate_minus_f1",
                          "ci95_low", "ci95_high", "resamples", "seed"])
    return calc


def operating_467(races):
    operating = pd.read_csv(OP / "race_metrics.csv")
    hy = operating.loc[operating.variant.eq("HY_R_FORM")].copy()
    ids = set(hy.race_id.astype(str))
    assert len(ids) == 467
    candidate = races.loc[races.race_id.astype(str).isin(ids)].copy()
    assert candidate.groupby("variant").race_id.nunique().to_dict() == {"F1": 467, "F1_STYLE6": 467}
    summaries = []
    for variant, g in [("HY_R_FORM", hy), *list(candidate.groupby("variant", sort=True))]:
        summaries.append({
            "variant": variant,
            "races": int(g.race_id.nunique()),
            "log_loss": float(g.log_loss.mean()),
            "brier": float(g.brier.mean()),
            "pick_hit": float(g.pick_hit.mean()),
            "top5_capture": float(g.top5_capture.mean()),
            "six_combo_hit": float(g.six_combo_hit.mean()),
        })
    saved = pd.read_csv(REPORT_DIR / "operating_common_467_summary.csv")
    sorted_equal(saved, pd.DataFrame(summaries), ["variant"],
                 numeric=["races", "log_loss", "brier", "pick_hit", "top5_capture", "six_combo_hit"])
    paired = []
    for variant in ("F1", "F1_STYLE6"):
        a = candidate.loc[candidate.variant.eq(variant)]
        for metric in ("log_loss", "brier", "pick_hit", "top5_capture", "six_combo_hit"):
            b = hy[["race_id", "race_date", metric]]
            aa = a[["race_id", "race_date", metric]]
            stat = bootstrap_races(aa, b, metric)
            paired.append({"comparison": f"{variant}-HY_R_FORM", "metric": metric,
                           "probability_semantics": "HY native PL separate from additive six-set", **stat})
    saved_paired = pd.read_csv(REPORT_DIR / "operating_common_467_paired_differences.csv")
    sorted_equal(saved_paired, pd.DataFrame(paired), ["comparison", "metric"],
                 numeric=["delta_candidate_minus_f1", "ci95_low", "ci95_high", "races",
                          "race_days", "resamples", "seed"])
    return pd.DataFrame(summaries), pd.DataFrame(paired)


def query_current_rows(ids):
    uri = f"file:{DB.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        assert con.execute("PRAGMA query_only").fetchone()[0] == 1
        marks = ",".join("?" for _ in ids)
        params = list(map(int, ids))
        current = pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,"
            "race_distance_m,finish_position,finish_time_seconds "
            f"FROM race_result_rows WHERE api_record_id IN ({marks})", con, params=params)
        times = pd.read_sql_query(
            "SELECT api_record_id,field_name,time_seconds,time_status "
            "FROM jeju_race_section_time_values "
            f"WHERE api_record_id IN ({marks}) AND field_name IN (?,?,?)",
            con, params=params + ["jeS1fTime", "je_4cTime", "jeG1fTime"])
        orders = pd.read_sql_query(
            "SELECT api_record_id,field_name,quality_order_value,quality_order_status "
            "FROM jeju_race_section_order_quality_values "
            f"WHERE api_record_id IN ({marks}) AND field_name IN (?,?,?)",
            con, params=params + ["sjS1fOrd", "sj_4cOrd", "sjG1fOrd"])
        assert con.execute("PRAGMA query_only").fetchone()[0] == 1
        assert len(current) == len(ids) and current.api_record_id.is_unique
        return current, times, orders
    finally:
        con.close()


def mutate_target_inputs(target, row_frame, snapshot, current_times, current_orders):
    target_id = int(target.api_record_id)
    original_label = int(target.finish_position)
    flipped = 4 if original_label <= 3 else 1
    row_frame.loc[row_frame.api_record_id.eq(target_id), "finish_position"] = flipped
    if "finish_position" in snapshot.columns:
        snapshot.loc[snapshot.api_record_id.eq(target_id), "finish_position"] = flipped
    if "finish_time_seconds" in snapshot.columns:
        snapshot.loc[snapshot.api_record_id.eq(target_id), "finish_time_seconds"] = 1_000_000.0
    if "valid_time" in snapshot.columns:
        original_valid_time = bool(snapshot.loc[snapshot.api_record_id.eq(target_id), "valid_time"].iloc[0])
        snapshot.loc[snapshot.api_record_id.eq(target_id), "valid_time"] = not original_valid_time
    changed_times = current_times.copy()
    if len(changed_times):
        changed_times.loc[changed_times.api_record_id.eq(target_id), "time_seconds"] = 1_000_000.0
        changed_times.loc[changed_times.api_record_id.eq(target_id), "time_status"] = "counterfactual_extreme_value"
    changed_orders = current_orders.copy()
    if len(changed_orders):
        changed_orders.loc[changed_orders.api_record_id.eq(target_id), "quality_order_value"] = 99999
        changed_orders.loc[changed_orders.api_record_id.eq(target_id), "quality_order_status"] = "counterfactual_extreme_value"
        assert changed_orders.quality_order_value.eq(99999).all()
    return flipped, changed_times, changed_orders


def input_matrix(frame, meta):
    return transform(frame, meta)


def select_last5_from_snapshot(snapshot, horse_id, distance_m, cutoff):
    eligible = snapshot.loc[
        snapshot.horse_id.astype(str).eq(str(horse_id))
        & pd.to_numeric(snapshot.race_distance_m, errors="coerce").eq(int(distance_m))
        & snapshot.started.astype(bool)
        & snapshot.race_date.astype(str).le(str(cutoff))
    ].sort_values(["race_date", "race_id", "horse_number"], kind="stable")
    return eligible.api_record_id.astype("int64").tail(5).tolist()


def row_perturbation(features, source_snapshot, slots, current, current_times, current_orders,
                     f1_mod, style_mod, candidate_metas, f1_metas, candidate_models, f1_models):
    slot_counts = slots.groupby("target_api_record_id").size().to_dict()
    out = []
    exact_cutoff_rows = int((slots.source_race_date.astype(str) == slots.target_cutoff.astype(str)).sum())
    assert exact_cutoff_rows == 0
    for case, target_id in SAMPLES.items():
        base_target = features.loc[features.api_record_id.eq(target_id)].iloc[0]
        current_row = current.loc[current.api_record_id.eq(target_id)].iloc[0]
        assert str(current_row.race_date) == str(base_target.race_date)
        assert str(current_row.horse_id) == str(base_target.horse_id)
        ids = style_mod.normalize_ids(base_target.last5_same_source_ids)
        reselected_before = select_last5_from_snapshot(
            source_snapshot, base_target.horse_id, base_target.distance_m, base_target.history_cutoff)
        assert reselected_before == ids
        hist_slots = slots.loc[slots.target_api_record_id.eq(target_id)].sort_values("slot_oldest_to_newest")
        assert hist_slots.source_api_record_id.astype("int64").tolist() == ids
        assert target_id not in ids
        assert len(ids) == int(slot_counts.get(target_id, 0))
        if case == "zero_history":
            assert len(ids) == 0
        if case == "partial_history":
            assert 0 < len(ids) < 5
        if case == "full_five_history":
            assert len(ids) == 5
        if case == "distance_1300":
            assert int(base_target.distance_m) == 1300
        if case == "target_after_t_minus_2":
            assert str(base_target.race_date) > str(base_target.history_cutoff)
        if case == "invalid_time_no_backfill":
            v = hist_slots.source_snapshot_valid_time.map(style_mod.as_bool).to_numpy(bool)
            assert (~v).any() and len(ids) == 5
        if case == "history_conflict":
            conflict = hist_slots.loc[hist_slots.source_api_record_id.eq(165876)].iloc[0]
            assert str(conflict.s1f_api303_group_status) == "unresolved_official_internal_conflict"
            assert not style_mod.as_bool(conflict.s1f_final_point_eligible)

        id_set = set(ids) | {target_id}
        snap_case = source_snapshot.loc[source_snapshot.api_record_id.astype("int64").isin(id_set)].copy()
        assert set(snap_case.api_record_id.astype("int64")) == id_set
        row_case = features.loc[features.api_record_id.eq(target_id)].drop(
            columns=style_mod.STYLE_FEATURES).reset_index(drop=True).copy()
        slot_case = hist_slots.copy()
        original_time = current_times.loc[current_times.api_record_id.eq(target_id)].copy()
        original_order = current_orders.loc[current_orders.api_record_id.eq(target_id)].copy()
        shifted, changed_time, changed_order = mutate_target_inputs(
            base_target, row_case, snap_case, original_time, original_order)
        assert changed_time.empty or changed_time.time_seconds.eq(1_000_000.0).all()
        assert changed_order.empty or changed_order.quality_order_value.eq(99999).all()
        # Re-select the target's own history from the full frozen started-source
        # pool before and after changing the target event. The selected IDs stay
        # the same because the target event is later than its T-2 cutoff.
        eligible_pool = source_snapshot.loc[
            source_snapshot.horse_id.astype(str).eq(str(base_target.horse_id))
            & pd.to_numeric(source_snapshot.race_distance_m, errors="coerce").eq(int(base_target.distance_m))
            & source_snapshot.started.astype(bool)
            & source_snapshot.race_date.astype(str).le(str(base_target.history_cutoff))
        ].copy()
        pool_after = pd.concat([
            eligible_pool,
            snap_case.loc[snap_case.api_record_id.astype("int64").eq(target_id)],
        ], ignore_index=True).drop_duplicates("api_record_id", keep="last")
        reselected_after = select_last5_from_snapshot(
            pool_after, base_target.horse_id, base_target.distance_m, base_target.history_cutoff)
        assert reselected_after == reselected_before == ids
        built, _ = style_mod.build_style_features(row_case, snap_case, slot_case)
        assert int(built.finish_position.iloc[0]) == shifted
        assert built[style_mod.BASE_COLUMNS].iloc[0].astype("string").fillna("<NA>").equals(
            row_case[style_mod.BASE_COLUMNS].iloc[0].astype("string").fillna("<NA>"))
        before_style = features.loc[features.api_record_id.eq(target_id), style_mod.STYLE_FEATURES].iloc[0]
        after_style = built[style_mod.STYLE_FEATURES].iloc[0]
        assert near(before_style, after_style)
        # The source history rows feeding this target are fixed at or before T-2.
        assert hist_slots.source_race_date.astype(str).le(str(base_target.history_cutoff)).all()
        if case == "target_after_t_minus_2":
            assert str(base_target.race_date) > str(base_target.history_cutoff)

        race = features.loc[features.race_id.eq(base_target.race_id)].sort_values(
            "horse_number", kind="stable").reset_index(drop=True)
        perturbed_race = race.copy()
        perturbed_target = perturbed_race.api_record_id.eq(target_id)
        perturbed_race.loc[perturbed_target, "finish_position"] = shifted
        for col in style_mod.STYLE_FEATURES:
            perturbed_race.loc[perturbed_target, col] = after_style[col]
        year = int(base_target.year)
        f1_before = input_matrix(race, f1_metas[year])
        f1_after = input_matrix(perturbed_race, f1_metas[year])
        c_before = input_matrix(race, candidate_metas[year])
        c_after = input_matrix(perturbed_race, candidate_metas[year])
        assert f1_before.equals(f1_after) and c_before.equals(c_after)
        zfb = f1_models[year].predict(f1_before, raw_score=True, num_threads=4)
        zfa = f1_models[year].predict(f1_after, raw_score=True, num_threads=4)
        zcb = candidate_models[year].predict(c_before, raw_score=True, num_threads=4)
        zca = candidate_models[year].predict(c_after, raw_score=True, num_threads=4)
        assert np.array_equal(zfb, zfa) and np.array_equal(zcb, zca)
        tau_f = float(f1_metas[year]["tau"])
        tau_c = float(candidate_metas[year]["tau"])
        rb = prediction_distribution(race, zfb, tau_f)
        ra = prediction_distribution(perturbed_race, zfa, tau_f)
        cb = prediction_distribution(race, zcb, tau_c)
        ca = prediction_distribution(perturbed_race, zca, tau_c)
        assert np.array_equal(rb[0], ra[0]) and np.array_equal(rb[1], ra[1])
        assert np.array_equal(cb[0], ca[0]) and np.array_equal(cb[1], ca[1])
        assert rb[2] == ra[2] and cb[2] == ca[2]
        out.append({
            "case": case, "target_api_record_id": target_id, "race_id": str(base_target.race_id),
            "year": year, "distance_m": int(base_target.distance_m), "history_slots": len(ids),
            "history_source_ids": ids, "latest_history_date": str(hist_slots.source_race_date.max()) if len(ids) else None,
            "cutoff": str(base_target.history_cutoff), "target_current_date_after_cutoff": str(base_target.race_date) > str(base_target.history_cutoff),
            "history_ids_reselected_from_full_snapshot_before_and_after": reselected_before == reselected_after == ids,
            "current_finish_before": int(base_target.finish_position), "current_finish_after": shifted,
            "current_finish_time_set_to": 1000000.0,
            "current_section_time_rows_perturbed": int(len(changed_time)),
            "current_section_order_rows_perturbed": int(len(changed_order)),
            "target_source_id_absent_from_own_history": target_id not in ids,
            "F1_24_input_matrix_identical": True, "STYLE6_30_input_matrix_identical": True,
            "F1_raw_score_max_abs_delta": float(np.max(np.abs(zfb-zfa))),
            "STYLE6_raw_score_max_abs_delta": float(np.max(np.abs(zcb-zca))),
            "F1_joint_probability_max_abs_delta": float(np.max(np.abs(rb[0]-ra[0]))),
            "STYLE6_joint_probability_max_abs_delta": float(np.max(np.abs(cb[0]-ca[0]))),
            "F1_top3_marginal_max_abs_delta": float(np.max(np.abs(rb[1]-ra[1]))),
            "STYLE6_top3_marginal_max_abs_delta": float(np.max(np.abs(cb[1]-ca[1]))),
            "F1_canonical_six_unchanged": rb[2] == ra[2],
            "STYLE6_canonical_six_unchanged": cb[2] == ca[2],
        })
    return pd.DataFrame(out), exact_cutoff_rows


def independent_model_replay():
    style_mod = import_from(ABLA / "prepare.py", "style_history_independent_prepare")
    f1_mod = import_from(BASE / "prepare.py", "style_history_independent_f1_prepare")
    features = pd.read_parquet(AB_OUT / "features.parquet")
    baseline_features = pd.read_parquet(BASE_OUT / "features.parquet")
    pd.testing.assert_frame_equal(features[style_mod.BASE_COLUMNS], baseline_features[style_mod.BASE_COLUMNS], check_exact=True)
    assert features.api_record_id.astype("int64").tolist() == baseline_features.api_record_id.astype("int64").tolist()
    assert style_mod.MODEL_COLUMNS[:24] == f1_mod.CONTRACTS["F1"]
    assert len(style_mod.MODEL_COLUMNS) == 30
    completion = json.loads((AB_OUT / "candidate_training_completion.json").read_text())
    final_receipt = json.loads((AB_OUT / "final_verification.json").read_text())
    assert completion["passed"] and completion["candidate_models"] == 3
    assert completion["lightgbm_train_calls"] == 6 and completion["temperature_optimizations"] == 3
    assert final_receipt["passed"] and final_receipt["candidate_models_fit"] == 3
    assert final_receipt["finalizer_fit_calls"] == 0 and final_receipt["finalizer_tau_optimizations"] == 0
    model_recs = {int(row["year"]): row for row in completion["model_years"]}
    candidate_metas, f1_metas, candidate_models, f1_models = {}, {}, {}, {}
    all_races, all_runners, all_tickets = [], [], []
    score_matches, calibration_objectives = {}, {}
    for year in YEARS:
        cfolder = AB_OUT / f"F1_STYLE6_{year}"
        ffolder = BASE_OUT / f"F1_{year}"
        cmeta = json.loads((cfolder / "meta.json").read_text())
        fmeta = json.loads((ffolder / "meta.json").read_text())
        cmodel_path, fmodel_path = cfolder / "top3.txt", ffolder / "top3.txt"
        assert sha(cmodel_path) == cmeta["model_sha256"]
        assert sha(fmodel_path) == fmeta["model_sha256"]
        assert cmeta["features"] == style_mod.MODEL_COLUMNS
        assert cmeta["features"][:24] == fmeta["features"]
        assert cmeta["trees"] == model_recs[year]["trees"]
        assert cmeta["tau"] == model_recs[year]["tau"]
        assert .35 <= float(cmeta["tau"]) <= 4.0
        cmodel = lgb.Booster(model_file=str(cmodel_path))
        fmodel = lgb.Booster(model_file=str(fmodel_path))
        assert cmodel.current_iteration() == int(cmeta["trees"])
        assert fmodel.current_iteration() == int(fmeta["trees"])
        candidate_metas[year], f1_metas[year] = cmeta, fmeta
        candidate_models[year], f1_models[year] = cmodel, fmodel
        train_completion_tau = float(model_recs[year]["tau"])
        assert float(cmeta["tau"]) == train_completion_tau
        cal = features.loc[features.year.eq(year-1)].reset_index(drop=True)
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        ccal = score(cmodel, cal, cmeta)
        fcal = score(fmodel, baseline_features.loc[baseline_features.year.eq(year-1)].reset_index(drop=True), fmeta)
        saved_ccal = pd.read_parquet(cfolder / "calibration_scores.parquet")
        saved_fcal = pd.read_parquet(ffolder / "calibration_scores.parquet")
        assert ccal.shape == (len(saved_ccal),) and fcal.shape == (len(saved_fcal),)
        assert np.allclose(ccal, saved_ccal.score.to_numpy(float), rtol=0, atol=ATOL)
        assert np.allclose(fcal, saved_fcal.score.to_numpy(float), rtol=0, atol=ATOL)
        ccal_obj = calibration_objective(cal, ccal, float(cmeta["tau"]))
        fcal_obj = calibration_objective(baseline_features.loc[baseline_features.year.eq(year-1)].reset_index(drop=True),
                                         fcal, float(fmeta["tau"]))
        ctest = score(cmodel, test, cmeta)
        ftest = score(fmodel, baseline_features.loc[baseline_features.year.eq(year)].reset_index(drop=True), fmeta)
        c_saved = pd.read_parquet(cfolder / "evaluation_scores.parquet")
        f_saved = pd.read_parquet(AB_OUT / "f1_reproduced_runner_predictions.parquet")
        f_saved = f_saved.loc[f_saved.year.eq(year)]
        c_stage = pd.read_parquet(AB_OUT / "candidate_scores_fit_stage.parquet")
        c_stage = c_stage.loc[c_stage.year.eq(year)]
        assert test.api_record_id.astype("int64").tolist() == c_saved.api_record_id.astype("int64").tolist()
        assert np.allclose(ctest, c_saved.score.to_numpy(float), rtol=0, atol=ATOL)
        assert np.allclose(ctest, c_stage.score.to_numpy(float), rtol=0, atol=ATOL)
        assert np.allclose(ftest, f_saved.score.to_numpy(float), rtol=0, atol=ATOL)
        year_races, year_runners, year_tickets = [], [], []
        for race_id, positions in test.groupby("race_id", sort=False).indices.items():
            idx = np.asarray(positions, dtype=np.int64)
            one = test.iloc[idx].sort_values("horse_number", kind="stable").reset_index(drop=True)
            # Model scores follow test row order; evaluation feature rows are already horse-number sorted.
            sorted_ids = one.api_record_id.astype("int64").to_numpy()
            original_ids = test.iloc[idx].api_record_id.astype("int64").to_numpy()
            order = pd.Index(original_ids).get_indexer(sorted_ids)
            zc = ctest[idx][order]
            zf = ftest[idx][order]
            c_result = eval_race(one, zc, float(cmeta["tau"]), "F1_STYLE6")
            f_result = eval_race(one, zf, float(fmeta["tau"]), "F1")
            for result in (c_result, f_result):
                year_races.append(result[0]); year_runners.extend(result[1]); year_tickets.extend(result[2])
        all_races.extend(year_races)
        all_runners.extend(year_runners)
        all_tickets.extend(year_tickets)
        score_matches[str(year)] = {
            "candidate_model_sha256": sha(cmodel_path), "baseline_model_sha256": sha(fmodel_path),
            "candidate_trees": cmodel.current_iteration(), "baseline_trees": fmodel.current_iteration(),
            "candidate_fixed_tau": float(cmeta["tau"]), "baseline_fixed_tau": float(fmeta["tau"]),
            "candidate_calibration_rows": int(len(ccal)), "baseline_calibration_rows": int(len(fcal)),
            "candidate_eval_rows": int(len(ctest)), "baseline_eval_rows": int(len(ftest)),
            "candidate_cal_raw_score_match_atol_1e-12": True,
            "baseline_cal_raw_score_match_atol_1e-12": True,
            "candidate_eval_raw_score_match_atol_1e-12": True,
            "baseline_eval_raw_score_match_atol_1e-12": True,
        }
        calibration_objectives[str(year)] = {
            "candidate_fixed_tau_joint_nll": ccal_obj,
            "baseline_fixed_tau_joint_nll": fcal_obj,
            "tau_optimizer_calls": 0,
        }
    return (style_mod, f1_mod, features, baseline_features, candidate_metas, f1_metas,
            candidate_models, f1_models, pd.DataFrame(all_races), pd.DataFrame(all_runners),
            pd.DataFrame(all_tickets), score_matches, calibration_objectives)


def calibration_objective(frame, scores, tau):
    losses = []
    for _, group in frame.reset_index(drop=True).groupby("race_id", sort=False):
        idx = group.index.to_numpy(dtype=int)
        triples = np.asarray(list(itertools.combinations(range(len(idx)), 3)), dtype=np.int64)
        energy = np.sort(np.asarray(scores)[idx][triples], axis=1).sum(axis=1)
        truth = np.flatnonzero(group.finish_position.to_numpy(dtype=float) <= 3)
        assert len(truth) == 3
        ti = int(np.flatnonzero((triples == truth[None, :]).all(axis=1))[0])
        losses.append(float(logsumexp(energy / tau) - energy[ti] / tau))
    return float(np.mean(losses))


def main():
    assert not (HERE / "style6_postfit_independent_receipt.json").exists()
    (style_mod, f1_mod, features, baseline_features, cmeta, fmeta, cmodels, fmodels,
     races, runners, tickets, score_matches, cal_obj) = independent_model_replay()
    assert len(races) == 3558 and races.race_id.nunique() == 1779
    assert len(runners) == 34824 and len(tickets) == 21348
    assert races.groupby("variant").race_id.nunique().eq(1779).all()
    assert np.allclose(runners.groupby(["variant", "race_id"], sort=False).p_top3.sum().to_numpy(float),
                       3.0, rtol=0, atol=1e-10)
    assert compare_report(races, runners, tickets)
    paired, gate = paired_report(races, runners, features)
    cond = conditional_losses(runners, features)
    op_summary, op_paired = operating_467(races)

    # Query only the seven selected current target records and their selected section values.
    ids = list(SAMPLES.values())
    current, current_times, current_orders = query_current_rows(ids)
    assert set(current.api_record_id.astype(int)) == set(ids)
    source_snapshot = pd.read_parquet(PROFILE / "source_snapshot.parquet")
    slots = pd.read_parquet(SOURCE / "actual_slot_point_eligibility.parquet")
    perturb, cutoff_count = row_perturbation(
        features, source_snapshot, slots, current, current_times, current_orders,
        f1_mod, style_mod, cmeta, fmeta, cmodels, fmodels)
    assert len(perturb) == 7
    assert perturb.F1_24_input_matrix_identical.all()
    assert perturb.STYLE6_30_input_matrix_identical.all()
    assert perturb.F1_raw_score_max_abs_delta.eq(0).all()
    assert perturb.STYLE6_raw_score_max_abs_delta.eq(0).all()
    assert perturb.F1_joint_probability_max_abs_delta.eq(0).all()
    assert perturb.STYLE6_joint_probability_max_abs_delta.eq(0).all()
    assert perturb.F1_canonical_six_unchanged.all() and perturb.STYLE6_canonical_six_unchanged.all()

    # Persist only this review agent's own new artifacts.
    (HERE / "style6_target_row_perturbations.csv").open("x", encoding="utf-8").close()
    perturb.to_csv(HERE / "style6_target_row_perturbations.csv", index=False)
    (HERE / "style6_independent_paired_ci.csv").open("x", encoding="utf-8").close()
    paired.to_csv(HERE / "style6_independent_paired_ci.csv", index=False)
    (HERE / "style6_independent_conditional_losses.csv").open("x", encoding="utf-8").close()
    cond.to_csv(HERE / "style6_independent_conditional_losses.csv", index=False)
    (HERE / "style6_independent_operating_467.csv").open("x", encoding="utf-8").close()
    op_summary.to_csv(HERE / "style6_independent_operating_467.csv", index=False)
    (HERE / "style6_independent_operating_467_paired.csv").open("x", encoding="utf-8").close()
    op_paired.to_csv(HERE / "style6_independent_operating_467_paired.csv", index=False)
    receipt = {
        "passed": True,
        "scope": "read-only independent reload/replay of frozen F1 and F1_STYLE6; no training or tau optimization",
        "models_reloaded": 6,
        "candidate_fit_calls": 0,
        "tau_optimizer_calls": 0,
        "candidate_eval_rows": 17412,
        "races": 1779,
        "race_days": 269,
        "canonical_six_rows": 10674,
        "model_score_parity": score_matches,
        "fixed_tau_calibration_objectives": cal_obj,
        "report_outputs_recomputed_from_saved_models": True,
        "full_joint_probability_sum_one_checked": True,
        "runner_top3_marginal_sum_three_checked": True,
        "top6_probability_mass_compared_to_six_combo_mass_not_one": True,
        "race_log_loss_brier_top5_sixsets_recomputed": True,
        "paired_date_bootstrap": {
            "resamples": REPS, "seed_reset_for_each_metric_group": SEED,
            "all_saved_rows_match_atol_1e-12": True,
            "primary_gate_passed": gate,
            "primary_points": paired.loc[paired.group.eq("all") & paired.metric.isin(["log_loss", "brier"]),
                                          ["metric", "delta_candidate_minus_f1", "ci95_low", "ci95_high"]].to_dict("records"),
        },
        "conditional_loss_rows_recomputed_and_matched": int(len(cond)),
        "operating_common_467_recomputed_and_matched": op_summary.to_dict("records"),
        "operating_467_paired_rows_recomputed_and_matched": int(len(op_paired)),
        "operating_probability_semantics": "HY native PL; F1/F1_STYLE6 additive canonical six-set probabilities",
        "row_specific_perturbations": {
            "rows": int(len(perturb)), "all_24_and_30_input_matrices_unchanged": True,
            "all_raw_scores_and_probabilities_unchanged": True,
            "canonical_top_six_unchanged": True,
            "current_target_history_ids_reselected_before_and_after_from_started_snapshot": True,
            "current_section_quality_rows_mutated_in_memory_but_not_consumed_by_fixed_cache_builder": True,
            "source_slots_exact_t_minus_2_count": cutoff_count,
            "scope_limit": "seven specified current target rows and the frozen source-window/slot consumer in a fixed cohort; does not prove every raw-source-to-cohort regeneration path; later target rows may legitimately change when an earlier event is altered",
        },
        "database_access": "SQLite mode=ro and PRAGMA query_only=ON; seven parameterized target IDs only",
        "database_or_production_changed": False,
        "output_hashes": {
            name: {"bytes": (HERE / name).stat().st_size, "sha256": sha(HERE / name)}
            for name in ["style6_target_row_perturbations.csv", "style6_independent_paired_ci.csv",
                         "style6_independent_conditional_losses.csv", "style6_independent_operating_467.csv",
                         "style6_independent_operating_467_paired.csv"]
        },
    }
    with (HERE / "style6_postfit_independent_receipt.json").open("x", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
