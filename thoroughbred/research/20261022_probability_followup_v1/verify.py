"""Independent, bounded verification of frozen follow-up artifacts.

Reads frozen inputs, saved model scores and evaluation products. It does not
train models, fit new parameters, write predictions, or alter source artifacts.
The sole write is outputs/verification.json.
"""
from __future__ import annotations

from itertools import combinations, permutations
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit, logsumexp

import common as c


NEW_VARIANTS = ["mix50", "mixcal", "crossF", "top2_22", "top2_89"]
BASE_VARIANTS = ["additive89", "full103"]
HEAD_VARIANTS = ["top2_22", "top2_89"]
SCOPES = ["all_starters", "normal_finishers_conditioned"]
TOL = 2e-10


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def repo_file(relative: str) -> Path:
    item = Path(relative)
    require(not item.is_absolute(), f"absolute path in manifest: {relative}")
    path = (c.ROOT / item).resolve()
    require(path.is_relative_to(c.ROOT), f"manifest path escapes repository: {relative}")
    return path


def close_arrays(left, right, *, atol=TOL, message="array mismatch") -> float:
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    require(a.shape == b.shape, f"{message}: shape {a.shape} != {b.shape}")
    require(np.isfinite(a).all() and np.isfinite(b).all(), f"{message}: non-finite values")
    error = float(np.max(np.abs(a - b))) if a.size else 0.0
    require(error <= atol, f"{message}: maximum absolute error {error:.3g} > {atol}")
    return error


def verify_frozen_inputs() -> dict:
    manifest_path = c.OUT / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(len(manifest) == 100, f"expected 100 frozen inputs, got {len(manifest)}")
    for relative, expected in manifest.items():
        path = repo_file(relative)
        require(path.is_file(), f"frozen input missing: {relative}")
        require(path.stat().st_size == expected["bytes"], f"frozen input size changed: {relative}")
        require(c.sha(path) == expected["sha256"], f"frozen input hash changed: {relative}")

    protocol = json.loads((c.OUT / "protocol_frozen.json").read_text(encoding="utf-8"))
    require(c.sha(c.HERE / "PLAN.md") == protocol["plan_sha256"], "frozen PLAN hash mismatch")
    require(c.sha(c.HERE / "config.json") == protocol["config_sha256"], "frozen config hash mismatch")
    require(protocol["new_evaluation_started"] is False, "freeze-time marker changed")
    training = json.loads((c.OUT / "training_complete.json").read_text(encoding="utf-8"))
    completed = json.loads((c.OUT / "evaluation_complete.json").read_text(encoding="utf-8"))
    study_sha = c.sha(c.HERE / "study.py")
    require(training["new_final_models"] == 6, "new final model count differs from plan")
    require(training["model_score_folds"] == 12, "score fold count differs from plan")
    require(training["training_code_sha256"] == study_sha, "study.py differs from frozen training code")
    require(completed["study_sha256"] == study_sha, "evaluation used different study.py")
    require(completed["heads_sha256"] == c.sha(c.HERE / "heads.py"), "heads.py changed after evaluation")
    fingerprint = c.sha(manifest_path)
    require(training["input_fingerprint"] == fingerprint, "training input fingerprint mismatch")
    return {
        "manifest_entries": len(manifest),
        "all_frozen_sizes_and_sha256_match": True,
        "plan_and_config_match_frozen_protocol": True,
        "six_new_models_and_twelve_scored_folds": True,
        "study_and_heads_hashes_match_saved_evaluation": True,
        "input_fingerprint": fingerprint,
    }


def verify_saved_head_scores(frame: pd.DataFrame) -> dict:
    errors = []
    fold_count = 0
    feature_contract = json.loads((c.OUT / "feature_contract.json").read_text(encoding="utf-8"))
    manifest_fingerprint = c.sha(c.OUT / "input_manifest.json")
    for venue in c.cfg()["venues"]:
        one = frame.loc[frame.meet.eq(venue)].reset_index(drop=True)
        for year in c.cfg()["evaluation_years"]:
            for variant in HEAD_VARIANTS:
                folder = c.OUT / "models" / f"{variant}_{venue}_{year}"
                metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                score_path = folder / "scores.parquet"
                saved = pd.read_parquet(score_path)
                require(list(saved.columns) == ["row_number", "score", "phase"], f"{variant}/{venue}/{year}: score schema")
                require(saved["row_number"].is_unique, f"{variant}/{venue}/{year}: duplicate scored row")
                require(saved["score"].notna().all() and np.isfinite(saved["score"].to_numpy(float)).all(),
                        f"{variant}/{venue}/{year}: non-finite saved scores")
                require(metadata["variant"] == variant and metadata["target"] == 2,
                        f"{variant}/{venue}/{year}: wrong model target/variant")
                require(metadata["meet"] == venue and metadata["evaluation_year"] == year,
                        f"{variant}/{venue}/{year}: metadata fold mismatch")
                require(metadata["calibration_year"] == year - 1 and metadata["validation_year"] == year - 2,
                        f"{variant}/{venue}/{year}: year split mismatch")
                require(metadata["input_fingerprint"] == manifest_fingerprint,
                        f"{variant}/{venue}/{year}: input fingerprint mismatch")
                expected_features = c.base.contracts()["ability22" if variant == "top2_22" else "additive89"]
                require(metadata["features"] == expected_features == feature_contract[variant],
                        f"{variant}/{venue}/{year}: feature contract mismatch")
                require(bool(metadata["reused"]) == (variant == "top2_22"),
                        f"{variant}/{venue}/{year}: reuse status mismatch")
                model_path = (c.ROOT / metadata["model_path"]).resolve()
                require(model_path.is_relative_to(c.ROOT) and model_path.is_file(),
                        f"{variant}/{venue}/{year}: model path missing or outside repository")
                model_hash = c.sha(model_path)
                require(model_hash == metadata["model_sha256"], f"{variant}/{venue}/{year}: model hash mismatch")
                if variant == "top2_22":
                    old_model = c.source_top2(venue, year) / "model.txt"
                    old_meta = json.loads((c.source_top2(venue, year) / "metadata.json").read_text(encoding="utf-8"))
                    require(model_path == old_model.resolve(), f"{variant}/{venue}/{year}: reused model path mismatch")
                    require(model_hash == old_meta["model_sha256"], f"{variant}/{venue}/{year}: reused baseline hash mismatch")
                else:
                    require(model_path == (folder / "model.txt").resolve(),
                            f"{variant}/{venue}/{year}: new model not in research output folder")

                category_vocabulary = metadata["category_vocabulary"]
                x, _ = c.base.encode(one, metadata["features"], vocabulary=category_vocabulary)
                model = lgb.Booster(model_file=str(model_path))
                for phase, mask in [
                    ("calibration", one.year.eq(year - 1)),
                    ("evaluation", one.year.eq(year)),
                ]:
                    expected_rows = one.loc[mask, "row_number"].to_numpy(dtype=np.int64)
                    actual_phase = saved.loc[saved.phase.eq(phase)]
                    require(len(actual_phase) == len(expected_rows),
                            f"{variant}/{venue}/{year}/{phase}: saved row count mismatch")
                    require(set(actual_phase.row_number.astype(np.int64)) == set(expected_rows),
                            f"{variant}/{venue}/{year}/{phase}: saved row keys mismatch")
                    predicted = model.predict(x.loc[mask], raw_score=True, num_threads=4)
                    actual = actual_phase.set_index("row_number").loc[expected_rows, "score"].to_numpy(float)
                    error = close_arrays(predicted, actual, atol=1e-12,
                                         message=f"{variant}/{venue}/{year}/{phase}: model score reproduction")
                    errors.append(error)
                fold_count += 1
    return {
        "head_score_folds": fold_count,
        "reproduced_rows": int(sum(len(pd.read_parquet(c.OUT / "models" / f"{v}_{venue}_{year}" / "scores.parquet"))
                                    for venue in c.cfg()["venues"] for year in c.cfg()["evaluation_years"]
                                    for v in HEAD_VARIANTS)),
        "maximum_absolute_raw_score_error": max(errors, default=0.0),
        "all_saved_calibration_and_evaluation_scores_reproduced": True,
    }


def verify_cohort_and_tickets(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cohort = frame.loc[frame.year.isin(c.cfg()["evaluation_years"])].copy()
    race_keys = set(cohort.race_key.unique())
    require(len(race_keys) == 4799 and len(cohort) == 50754, "evaluation cohort size differs from frozen research58")
    expected_variants = set(NEW_VARIANTS)
    metrics = pd.read_parquet(c.OUT / "race_metrics.parquet")
    tickets = pd.read_parquet(c.OUT / "tickets.parquet")
    runners = pd.read_parquet(c.OUT / "runner_probabilities.parquet")
    baseline_extra = pd.read_parquet(c.OUT / "baseline_extra_metrics.parquet")
    require(len(metrics) == 4799 * len(NEW_VARIANTS) * 2, "race metric row count mismatch")
    require(not metrics.duplicated(["race_key", "variant", "scope"]).any(), "duplicate race metric key")
    require(set(metrics.variant) == expected_variants and set(metrics.scope) == set(SCOPES), "race metric arms/scopes mismatch")
    require(set(metrics.race_key) == race_keys, "race metrics do not cover the common evaluation cohort")
    require(len(tickets) == 4799 * len(NEW_VARIANTS) * 2 * 3, "ticket row count mismatch")
    require(set(tickets.variant) == expected_variants and set(tickets.race_key) == race_keys,
            "ticket arm/race keys mismatch")
    require(not tickets.duplicated(["race_key", "variant", "pool", "rank"]).any(), "duplicate ticket key")
    counts = tickets.groupby(["race_key", "variant", "pool"], sort=False)["rank"].agg(["size", "nunique", "min", "max"])
    require(counts.eq(pd.Series({"size": 3, "nunique": 3, "min": 1, "max": 3})).all().all(),
            "each pool must have exactly ranks 1,2,3 in every race")
    require(set(tickets.pool) == {"quinella", "qpl"}, "unexpected ticket pool")
    require((tickets.program_a < tickets.program_b).all(), "ticket programs are not in canonical ascending order")

    require(len(runners) == 50754 * len(NEW_VARIANTS), "runner probability row count mismatch")
    require(set(runners.variant) == expected_variants and set(runners.race_key) == race_keys,
            "runner probability arm/race keys mismatch")
    require(not runners.duplicated(["race_key", "program_no", "variant"]).any(), "duplicate runner probability key")
    require(np.isfinite(runners[["win", "top2", "top3"]].to_numpy(float)).all(), "non-finite runner probability")
    require(((runners[["win", "top2", "top3"]] >= -1e-12) &
             (runners[["win", "top2", "top3"]] <= 1 + 1e-12)).all().all(), "runner probabilities out of range")

    # Independently re-evaluate every selected ticket's hit from the frozen
    # runner outcome labels; verify both individual rows and aggregates.
    truth = cohort[["race_key", "program_no", "outcome"]].set_index(["race_key", "program_no"])["outcome"]
    rows = tickets.merge(truth.rename("outcome_a"), left_on=["race_key", "program_a"], right_index=True,
                         how="left", validate="many_to_one")
    rows = rows.merge(truth.rename("outcome_b"), left_on=["race_key", "program_b"], right_index=True,
                      how="left", validate="many_to_one")
    require(rows[["outcome_a", "outcome_b"]].notna().all().all(), "ticket refers to a runner outside the cohort")
    expected_hit = np.where(rows.pool.eq("quinella"),
                            rows.outcome_a.isin([1, 2]) & rows.outcome_b.isin([1, 2]),
                            rows.outcome_a.isin([1, 2, 3]) & rows.outcome_b.isin([1, 2, 3]))
    require(np.array_equal(rows.hit.to_numpy(dtype=bool), np.asarray(expected_hit, dtype=bool)),
            "saved ticket hit differs from actual outcome")
    rows["verified_hit"] = np.asarray(expected_hit, dtype=np.int8)
    summary = rows.groupby(["variant", "pool"], sort=True).verified_hit.agg(["sum", "count"])
    hit_dist = (rows.groupby(["variant", "pool", "race_key"], sort=False).verified_hit.sum()
                .groupby(["variant", "pool"]).value_counts().unstack(fill_value=0))

    # Check persisted per-race top-ticket hits/probability sums against those
    # same ticket rows, for both scopes.
    ticket_stats = rows.groupby(["race_key", "variant", "pool"], sort=False).apply(
        lambda group: pd.Series({
            "rank1_hit": int(group.loc[group["rank"].eq(1), "verified_hit"].iloc[0]),
            "any_hit": int(group.verified_hit.max()),
            "hit_count": int(group.verified_hit.sum()),
            "rank1_probability": float(group.loc[group["rank"].eq(1), "probability"].iloc[0]),
            "probability_sum": float(group.probability.sum()),
        }), include_groups=False).reset_index()
    for pool, fields in [("quinella", ("quinella_one", "quinella_three", "qnl1_probability", "qnl3_probability")),
                         ("qpl", ("qpl_one", "qpl_three", "qpl1_probability", "qpl_expected_count"))]:
        subset = ticket_stats.loc[ticket_stats.pool.eq(pool)].drop(columns="pool")
        joined = metrics.loc[metrics.scope.eq("all_starters")].merge(
            subset, on=["race_key", "variant"], how="left", validate="many_to_one")
        require(joined["rank1_hit"].notna().all(), f"missing {pool} ticket summary")
        for metric_col, ticket_col in zip(fields, ["rank1_hit", "any_hit", "rank1_probability", "probability_sum"], strict=True):
            close_arrays(joined[metric_col], joined[ticket_col], atol=1e-12,
                         message=f"saved {metric_col} vs {pool} ticket aggregate")
    qpl = ticket_stats.loc[ticket_stats.pool.eq("qpl")].copy()
    qpl["pool"] = "qpl"
    qpl_selected = rows.loc[rows.pool.eq("qpl"), ["race_key", "variant", "rank", "program_a", "program_b", "probability", "verified_hit"]]

    # Crossed/top2 heads must retain EL's axis and QPL marginals in both scopes.
    base_metrics = pd.read_parquet(c.BASE / "outputs" / "race_metrics.parquet")
    base_el = base_metrics.loc[base_metrics.variant.eq("additive89")].set_index(["race_key", "scope"]).sort_index()
    preserve = ["axis_program_no", "axis_probability", "axis_top3", "qpl_one", "qpl_three", "qpl_count",
                "qpl_expected_count", "qpl1_probability", "qpl3_probability", "qpl_brier", "qpl1_brier", "qpl3_brier"]
    preservation_max_error = 0.0
    for variant in ["crossF", "top2_22", "top2_89"]:
        cand = metrics.loc[metrics.variant.eq(variant)].set_index(["race_key", "scope"]).sort_index()
        require(cand.index.equals(base_el.index), f"{variant}: race/scope keys differ from additive89")
        for col in preserve:
            left, right = cand[col].to_numpy(), base_el[col].to_numpy()
            if pd.api.types.is_numeric_dtype(cand[col]):
                err = close_arrays(left, right, atol=1e-12, message=f"{variant} must preserve EL {col}")
                preservation_max_error = max(preservation_max_error, err)
            else:
                require(np.array_equal(left, right), f"{variant} must preserve EL {col}")

    # Recompute every saved axis recommendation from the all-starters runner
    # probabilities using the frozen 12-decimal/program-order tie rule.
    runner_axis = runners.sort_values(["race_key", "variant", "program_no"], kind="stable")
    axis_records = []
    for (race_key, variant), group in runner_axis.groupby(["race_key", "variant"], sort=False):
        order = np.argsort(-np.round(group.top3.to_numpy(float), 12), kind="stable")
        axis_records.append((race_key, variant, int(group.program_no.iloc[order[0]]), float(group.top3.iloc[order[0]])))
    axis_frame = pd.DataFrame(axis_records, columns=["race_key", "variant", "axis_program_no", "axis_probability"])
    all_metrics = metrics.loc[metrics.scope.eq("all_starters")].merge(
        axis_frame, on=["race_key", "variant"], suffixes=("_saved", "_recomputed"), validate="one_to_one")
    require((all_metrics.axis_program_no_saved == all_metrics.axis_program_no_recomputed).all(),
            "saved all-starter axis choice differs from runner marginals")
    close_arrays(all_metrics.axis_probability_saved, all_metrics.axis_probability_recomputed, atol=1e-12,
                 message="saved all-starter axis probability differs from runner marginal")

    # Compare all ticket selections/probabilities for the preserved QPL pool.
    base_tickets = pd.read_parquet(c.BASE / "outputs" / "tickets.parquet")
    el_qpl = base_tickets.loc[base_tickets.variant.eq("additive89") & base_tickets.pool.eq("qpl"),
                              ["race_key", "rank", "program_a", "program_b", "probability", "hit"]]
    el_qpl = el_qpl.set_index(["race_key", "rank"]).sort_index()
    for variant in ["crossF", "top2_22", "top2_89"]:
        cand = qpl_selected.loc[qpl_selected.variant.eq(variant),
                                ["race_key", "rank", "program_a", "program_b", "probability", "verified_hit"]]
        cand = cand.rename(columns={"verified_hit": "hit"}).set_index(["race_key", "rank"]).sort_index()
        require(cand.index.equals(el_qpl.index), f"{variant}: QPL ticket keys differ from additive89")
        for col in ["program_a", "program_b", "probability", "hit"]:
            if col == "probability":
                close_arrays(cand[col], el_qpl[col], atol=1e-12, message=f"{variant}: EL QPL ticket probability")
            else:
                require(np.array_equal(cand[col].to_numpy(), el_qpl[col].to_numpy()),
                        f"{variant}: EL QPL ticket {col} differs")

    # QPL-derived per-runner Top3 probability is also invariant for all starts.
    base_runners = pd.read_parquet(c.BASE / "outputs" / "runner_probabilities.parquet")
    el_runner = base_runners.loc[base_runners.variant.eq("additive89"),
                                ["race_key", "program_no", "top3"]].set_index(["race_key", "program_no"]).sort_index()
    runner_preservation_max_error = 0.0
    for variant in ["crossF", "top2_22", "top2_89"]:
        candidate = runners.loc[runners.variant.eq(variant), ["race_key", "program_no", "top3"]].set_index(
            ["race_key", "program_no"]).sort_index()
        require(candidate.index.equals(el_runner.index), f"{variant}: runner keys differ from additive89")
        runner_preservation_max_error = max(runner_preservation_max_error,
            close_arrays(candidate.top3, el_runner.top3, atol=1e-12, message=f"{variant}: EL runner Top3 marginal"))

    # Check the six saved calibration records' chronology, identity and bounds;
    # no parameter optimizer is re-run in this bounded audit.
    calibration_rows = json.loads((c.OUT / "calibration_parameters.json").read_text(encoding="utf-8"))
    require(len(calibration_rows) == 6, "expected six saved calibration records")
    calibration_summary = []
    for venue in c.cfg()["venues"]:
        for year in c.cfg()["evaluation_years"]:
            cm = json.loads((c.OUT / "calibration" / f"{venue}_{year}.json").read_text(encoding="utf-8"))
            require(cm["meet"] == venue and cm["evaluation_year"] == year and cm["calibration_year"] == year - 1,
                    f"calibration fold identity mismatch {venue}/{year}")
            require(cm["input_fingerprint"] == c.sha(c.OUT / "input_manifest.json"),
                    f"calibration fingerprint mismatch {venue}/{year}")
            require(cm["heads_sha256"] == c.sha(c.HERE / "heads.py"), f"calibration heads hash mismatch {venue}/{year}")
            low, high = c.cfg()["temperature_bounds"]
            require(low <= cm["first_temperature"] <= high, f"first temperature out of bounds {venue}/{year}")
            require(0 <= cm["mix_weight_el"] <= 1, f"mixture weight out of bounds {venue}/{year}")
            require(cm["mix_fit"]["success"] and np.isfinite(cm["mix_fit"]["loss"]),
                    f"mixture fit diagnostic invalid {venue}/{year}")
            require(cm["calibration_races"] > 0 and cm["calibration_start"][:4] == str(year - 1) and
                    cm["calibration_end"][:4] == str(year - 1), f"calibration dates/races mismatch {venue}/{year}")
            cal_frame = frame.loc[frame.meet.eq(venue) & frame.year.eq(year - 1)]
            require(int(cal_frame.race_key.nunique()) == int(cm["calibration_races"]),
                    f"calibration race count differs from source cohort {venue}/{year}")
            require(str(cal_frame.race_date.min().date()) == cm["calibration_start"] and
                    str(cal_frame.race_date.max().date()) == cm["calibration_end"],
                    f"calibration date range differs from source cohort {venue}/{year}")
            for variant in HEAD_VARIANTS:
                require(low <= cm["third_temperatures"][variant] <= high,
                        f"third temperature out of bounds {variant}/{venue}/{year}")
                require(np.isfinite(cm["conditional_third_calibration_nll"][variant]),
                        f"invalid third calibration NLL {variant}/{venue}/{year}")
            saved_fit = next((row for row in calibration_rows if row["meet"] == venue and row["evaluation_year"] == year), None)
            require(saved_fit == cm, f"calibration parameter aggregate differs from fold JSON {venue}/{year}")
            calibration_summary.append({"meet": venue, "evaluation_year": year,
                "calibration_year": year - 1, "calibration_races": int(cm["calibration_races"]),
                "mix_weight_el": float(cm["mix_weight_el"]), "third_temperatures": cm["third_temperatures"],
                "first_temperature": float(cm["first_temperature"])})

    summary = {
        "evaluation_races": len(race_keys),
        "evaluation_runner_rows": len(cohort),
        "race_metric_rows": len(metrics),
        "ticket_rows": len(tickets),
        "runner_probability_rows": len(runners),
        "every_saved_ticket_hit_recomputed_from_actual_outcome": True,
        "ticket_hits_by_variant_and_pool": {f"{variant}/{pool}": int(summary_row["sum"])
            for (variant, pool), summary_row in summary.iterrows()},
        "ticket_hit_count_distribution": {
            f"{variant}/{pool}": {str(int(k)): int(v) for k, v in row.items()}
            for (variant, pool), row in hit_dist.iterrows()},
        "candidate_axis_and_QPL_preservation_vs_additive89_both_scopes": True,
        "max_axis_QPL_preservation_error": preservation_max_error,
        "max_runner_top3_preservation_error": runner_preservation_max_error,
        "all_starter_axis_recommendations_recomputed_from_runner_probabilities": True,
        "calibration_folds_checked_for_years_bounds_hashes_and_saved_diagnostics": calibration_summary,
        "calibration_optimizers_recomputed": False,
        "baseline_extra_metric_rows": len(baseline_extra),
    }
    return summary, metrics, tickets, runners, baseline_extra


def independent_joint(scores: np.ndarray, set_temp: float, order_temp: float):
    scores = np.asarray(scores, dtype=float)
    triples = list(combinations(range(len(scores)), 3))
    log_q = np.array([scores[list(trio)].sum() / set_temp for trio in triples], dtype=float)
    q = np.exp(log_q - logsumexp(log_q))
    orders, mass = [], []
    for trio, probability in zip(triples, q, strict=True):
        for order in permutations(trio):
            remaining = list(trio)
            log_probability = 0.0
            for horse in order:
                logits = scores[remaining] / order_temp
                log_probability += scores[horse] / order_temp - logsumexp(logits)
                remaining.remove(horse)
            orders.append(order)
            mass.append(probability * np.exp(log_probability))
    return np.asarray(orders, dtype=np.int64), np.asarray(mass, dtype=float), q, triples


def independent_top2(scores2, scores_first, q, triples, temp_third, temp_first):
    orders, mass = [], []
    for trio, trio_probability in zip(triples, q, strict=True):
        logits_third = -scores2[list(trio)] / temp_third
        p_third = np.exp(logits_third - logsumexp(logits_third))
        for first, second, third in permutations(trio):
            p_first = expit((scores_first[first] - scores_first[second]) / temp_first)
            orders.append((first, second, third))
            mass.append(trio_probability * p_third[trio.index(third)] * p_first)
    return np.asarray(orders, dtype=np.int64), np.asarray(mass, dtype=float)


def independent_marginals(n, orders, mass):
    output = {"win": np.zeros(n), "top2": np.zeros(n), "top3": np.zeros(n),
              "quinella": np.zeros((n, n)), "qpl": np.zeros((n, n)), "exacta": np.zeros((n, n))}
    for (first, second, third), p in zip(orders, mass, strict=True):
        output["win"][first] += p
        output["top2"][[first, second]] += p
        output["top3"][[first, second, third]] += p
        output["quinella"][first, second] += p
        output["quinella"][second, first] += p
        output["exacta"][first, second] += p
        for a, b in ((first, second), (first, third), (second, third)):
            output["qpl"][a, b] += p
            output["qpl"][b, a] += p
    return output


def probability_order(values):
    return np.argsort(-np.round(np.asarray(values, dtype=float), 12), kind="stable")


def sample_scope_metrics(g, orders, mass, marginals, variant, scope):
    active = g.normal_finisher.to_numpy(bool)
    if scope == "normal_finishers_conditioned" and not active.all():
        keep = active[orders].all(axis=1)
        mass = np.where(keep, mass, 0.0)
        require(mass.sum() > 0, "sample conditioned distribution has zero mass")
        mass = mass / mass.sum()
        marginals = independent_marginals(len(g), orders, mass)
    outcome = g.outcome.to_numpy(int)
    eligible = np.flatnonzero(active) if scope == "normal_finishers_conditioned" else np.arange(len(g))
    ii, jj = np.triu_indices(len(g), 1)
    keep_pairs = np.isin(ii, eligible) & np.isin(jj, eligible)
    ii, jj = ii[keep_pairs], jj[keep_pairs]
    qnl_p = marginals["quinella"][ii, jj]
    qpl_p = marginals["qpl"][ii, jj]
    qnl_order = probability_order(qnl_p)[:3]
    qpl_order = probability_order(qpl_p)[:3]
    axis_local = probability_order(marginals["top3"][eligible])[0]
    axis = int(eligible[axis_local])
    top2 = (outcome >= 1) & (outcome <= 2)
    top3 = (outcome >= 1) & (outcome <= 3)
    qnl_hits = [int(top2[ii[k]] and top2[jj[k]]) for k in qnl_order]
    qpl_hits = [int(top3[ii[k]] and top3[jj[k]]) for k in qpl_order]
    qpl_union = np.zeros(len(orders), dtype=bool)
    for k in qpl_order:
        qpl_union |= ((orders == ii[k]).any(axis=1) & (orders == jj[k]).any(axis=1))
    actual_trio = top3[orders].all(axis=1)
    true_order = np.array([np.flatnonzero(outcome == r)[0] for r in (1, 2, 3)])
    true_order_mask = (orders == true_order).all(axis=1)
    actual_third = orders[:, 2] == true_order[2]
    true_pair = top2[orders[:, :2]].all(axis=1)
    metrics = {
        "axis_program_no": int(g.program_no.iloc[axis]),
        "axis_probability": float(marginals["top3"][axis]),
        "axis_top3": int(top3[axis]),
        "quinella_one": qnl_hits[0], "quinella_three": int(any(qnl_hits)),
        "qpl_one": qpl_hits[0], "qpl_three": int(any(qpl_hits)), "qpl_count": int(sum(qpl_hits)),
        "qpl_expected_count": float(qpl_p[qpl_order].sum()),
        "qnl1_probability": float(qnl_p[qnl_order[0]]),
        "qnl3_probability": float(qnl_p[qnl_order].sum()),
        "qpl1_probability": float(qpl_p[qpl_order[0]]),
        "qpl3_probability": float(mass[qpl_union].sum()),
        "trio_logloss": float(-np.log(max(mass[actual_trio].sum(), 1e-300))),
        "ordered_logloss": float(-np.log(max(mass[true_order_mask].sum(), 1e-300))),
        "quinella_logloss": float(-np.log(max(mass[true_pair].sum(), 1e-300))),
        "conditional_third_logloss": float(-np.log(max(mass[actual_trio & actual_third].sum() /
            mass[actual_trio].sum(), 1e-300))),
    }
    tickets = {}
    for pool, indices, probabilities, hits in [("quinella", qnl_order, qnl_p, qnl_hits),
                                               ("qpl", qpl_order, qpl_p, qpl_hits)]:
        tickets[pool] = [(int(g.program_no.iloc[ii[k]]), int(g.program_no.iloc[jj[k]]),
                          float(probabilities[k]), int(hits[rank])) for rank, k in enumerate(indices)]
    return metrics, tickets, marginals


def verify_representative_races(frame, metrics, tickets, runners, baseline_extra) -> dict:
    sample_records = []
    maximum_probability_error = 0.0
    maximum_metric_error = 0.0
    years = c.cfg()["evaluation_years"]
    for venue in c.cfg()["venues"]:
        for year in years:
            fold = frame.loc[frame.meet.eq(venue) & frame.year.eq(year)]
            race_key = sorted(fold.race_key.unique())[0]
            g = fold.loc[fold.race_key.eq(race_key)].sort_values("program_no").reset_index(drop=True)
            n = len(g)
            scores, metadata = {}, {}
            for variant in ["additive89", "full103", "top2_22", "top2_89"]:
                root = c.OUT if variant.startswith("top2_") else c.BASE / "outputs"
                folder = root / "models" / f"{variant}_{venue}_{year}"
                metadata[variant] = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                raw = pd.read_parquet(folder / "scores.parquet")
                saved = raw.loc[raw.phase.eq("evaluation")].set_index("row_number").score
                scores[variant] = saved.loc[g.row_number].to_numpy(float)
            old_cal = {variant: json.loads((c.BASE / "outputs" / "calibration" /
                      f"{variant}_{venue}_{year}.json").read_text(encoding="utf-8")) for variant in BASE_VARIANTS}
            cm = json.loads((c.OUT / "calibration" / f"{venue}_{year}.json").read_text(encoding="utf-8"))
            orders_el, mass_el, q_el, triples = independent_joint(
                scores["additive89"], metadata["additive89"]["temperature"], old_cal["additive89"]["order_temperature"])
            orders_f, mass_f, q_f, triples_f = independent_joint(
                scores["full103"], metadata["full103"]["temperature"], old_cal["full103"]["order_temperature"])
            require(np.array_equal(orders_el, orders_f) and triples == triples_f, "independent order supports differ")
            require(abs(mass_el.sum() - 1) < 1e-12 and abs(mass_f.sum() - 1) < 1e-12,
                    f"{venue}/{year}: base joint distribution not normalized")
            masses = {
                "additive89": mass_el,
                "full103": mass_f,
                "mix50": .5 * mass_el + .5 * mass_f,
                "mixcal": cm["mix_weight_el"] * mass_el + (1 - cm["mix_weight_el"]) * mass_f,
            }
            orders_cross, mass_cross, _, _ = independent_joint(
                scores["full103"], metadata["full103"]["temperature"], old_cal["full103"]["order_temperature"])
            # CrossF keeps the EL unordered trio probabilities but uses F's PL order.
            pl_f = np.divide(mass_cross.reshape(-1, 6), np.repeat(q_f, 6).reshape(-1, 6),
                             out=np.zeros((len(q_f), 6)), where=np.repeat(q_f, 6).reshape(-1, 6) > 0)
            mass_cross_el = (q_el[:, None] * pl_f).reshape(-1)
            masses["crossF"] = mass_cross_el
            for variant in HEAD_VARIANTS:
                orders_top2, candidate_mass = independent_top2(scores[variant], scores["full103"], q_el, triples,
                    cm["third_temperatures"][variant], cm["first_temperature"])
                require(np.array_equal(orders_top2, orders_el), f"{variant}: top2 support order differs")
                masses[variant] = candidate_mass

            runner_saved = runners.loc[runners.race_key.eq(race_key)]
            metric_rows = metrics.loc[metrics.race_key.eq(race_key)]
            ticket_rows = tickets.loc[tickets.race_key.eq(race_key)]
            base_rows = baseline_extra.loc[baseline_extra.race_key.eq(race_key)]
            variant_errors = {}
            for variant, mass in masses.items():
                require(mass.shape == (len(orders_el),) and np.isfinite(mass).all() and (mass >= 0).all(),
                        f"{variant}/{venue}/{year}: invalid joint support/mass")
                close_arrays(mass.sum(), 1.0, atol=1e-12, message=f"{variant}: sample normalization")
                trio_marginal = mass.reshape(-1, 6).sum(axis=1)
                if variant in ["additive89", "crossF", "top2_22", "top2_89"]:
                    expected_trio = q_el
                elif variant == "full103":
                    expected_trio = q_f
                elif variant == "mix50":
                    expected_trio = .5 * q_el + .5 * q_f
                else:
                    expected_trio = cm["mix_weight_el"] * q_el + (1 - cm["mix_weight_el"]) * q_f
                close_arrays(trio_marginal, expected_trio, atol=1e-12,
                             message=f"{variant}: independent trio marginal")
                marg = independent_marginals(n, orders_el, mass)
                selected_metric_errors = []
                for scope in SCOPES:
                    expected, selected, scoped_marg = sample_scope_metrics(g, orders_el, mass, marg, variant, scope)
                    if variant in NEW_VARIANTS:
                        output = metric_rows.loc[metric_rows.variant.eq(variant) & metric_rows.scope.eq(scope)]
                        require(len(output) == 1, f"{variant}/{venue}/{year}/{scope}: metric row absent/duplicated")
                        output = output.iloc[0]
                        for key in ["axis_probability", "qnl1_probability", "qnl3_probability", "qpl1_probability",
                                    "qpl3_probability", "qpl_expected_count", "trio_logloss", "ordered_logloss",
                                    "quinella_logloss", "conditional_third_logloss"]:
                            error = abs(float(output[key]) - expected[key])
                            selected_metric_errors.append(error)
                            require(error <= 2e-9, f"{variant}/{venue}/{year}/{scope}: {key} mismatch {error:.3g}")
                        for key in ["axis_program_no", "axis_top3", "quinella_one", "quinella_three", "qpl_one",
                                    "qpl_three", "qpl_count"]:
                            require(int(output[key]) == int(expected[key]),
                                    f"{variant}/{venue}/{year}/{scope}: {key} mismatch")
                    if scope == "all_starters" and variant in NEW_VARIANTS:
                        saved_runner = runner_saved.loc[runner_saved.variant.eq(variant)].sort_values("program_no")
                        require(len(saved_runner) == n, f"{variant}/{venue}/{year}: sample runner count mismatch")
                        for key in ["win", "top2", "top3"]:
                            err = close_arrays(saved_runner[key].to_numpy(float), scoped_marg[key], atol=1e-11,
                                               message=f"{variant}/{venue}/{year}: saved runner {key}")
                            maximum_probability_error = max(maximum_probability_error, err)
                        saved_tickets = ticket_rows.loc[ticket_rows.variant.eq(variant)]
                        for pool in ["quinella", "qpl"]:
                            actual = saved_tickets.loc[saved_tickets.pool.eq(pool)].sort_values("rank")
                            expected_tickets = selected[pool]
                            require(len(actual) == 3, f"{variant}/{venue}/{year}/{pool}: sample ticket count")
                            for rank, (ticket, expected_ticket) in enumerate(zip(actual.itertuples(index=False),
                                                                                expected_tickets, strict=True), 1):
                                require((int(ticket.program_a), int(ticket.program_b)) == expected_ticket[:2],
                                        f"{variant}/{venue}/{year}/{pool}/{rank}: ticket selection mismatch")
                                require(abs(float(ticket.probability) - expected_ticket[2]) <= 1e-11,
                                        f"{variant}/{venue}/{year}/{pool}/{rank}: ticket probability mismatch")
                                require(int(ticket.hit) == expected_ticket[3],
                                        f"{variant}/{venue}/{year}/{pool}/{rank}: ticket hit mismatch")
                    if variant in BASE_VARIANTS:
                        base_row = base_rows.loc[base_rows.variant.eq(variant) & base_rows.scope.eq(scope)]
                        require(len(base_row) == 1, f"{variant}/{venue}/{year}/{scope}: baseline extra metric missing")
                        for key in ["quinella_logloss", "conditional_third_logloss"]:
                            error = abs(float(base_row.iloc[0][key]) - expected[key])
                            selected_metric_errors.append(error)
                            require(error <= 2e-9,
                                    f"{variant}/{venue}/{year}/{scope}: baseline {key} mismatch {error:.3g}")
                err = max(selected_metric_errors, default=0.0)
                maximum_metric_error = max(maximum_metric_error, err)
                variant_errors[variant] = err
            sample_records.append({"meet": venue, "evaluation_year": year, "race_key": race_key,
                                   "runner_count": n, "maximum_saved_proper_metric_error": max(variant_errors.values(), default=0.0),
                                   "checked_joint_variants": sorted(masses)})
    return {
        "representative_races": sample_records,
        "joint_distribution_variant_count_per_race": 7,
        "maximum_runner_probability_error": maximum_probability_error,
        "maximum_saved_proper_metric_error": maximum_metric_error,
        "independent_enumeration_checks": ["normalization", "trio marginals", "runner win/top2/top3",
            "ticket selections/probabilities/hits", "axis and QPL metrics", "quinella and conditional-third NLL"],
    }


def run_verification() -> dict:
    frozen = verify_frozen_inputs()
    # common.load_frame validates the exact Seoul/Busan runner cohort and source dates.
    frame = c.load_frame()
    scores = verify_saved_head_scores(frame)
    cohort, metrics, tickets, runners, baseline_extra = verify_cohort_and_tickets(frame)
    representatives = verify_representative_races(frame, metrics, tickets, runners, baseline_extra)
    return {
        "status": "passed",
        "verifier": "bounded independent verification; no training or parameter refit",
        "frozen_inputs": frozen,
        "saved_top2_model_scores": scores,
        "full_cohort_tickets_and_preservation": cohort,
        "representative_joint_and_proper_score_checks": representatives,
        "limitations": [
            "Saved calibration parameters were checked for fold identity, provenance hashes, bounds, and finite diagnostics; calibration optimizers were not rerun.",
            "Independent joint enumeration and proper-score recomputation used one deterministic evaluation race for each of the six venue-year folds; full-cohort prediction re-enumeration was not run.",
            "Full-cohort ticket-hit, ticket-count, axis-from-runner-marginal, and EL axis/QPL-preservation checks covered all 4,799 evaluation races.",
        ],
    }


def main() -> int:
    try:
        result = run_verification()
    except Exception as exc:
        result = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "limitations": ["Verification stopped at the first failed assertion; model and evaluation artifacts were not modified. This file records the failed verification."],
        }
        c.save(c.OUT / "verification.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    c.save(c.OUT / "verification.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
