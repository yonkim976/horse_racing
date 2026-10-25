#!/usr/bin/env python3
"""Inspect changed max-probability ticket choices without refitting or rescoring outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import baseline


OUT = baseline.OUTPUT
DIAGNOSTIC = OUT / "choice_change_diagnostic.parquet"
SUMMARY = OUT / "choice_change_diagnostic.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ticket_scores(key: tuple[int, ...], score_by_number: dict[int, float]) -> list[float]:
    return [float(score_by_number[int(number)]) for number in key]


def main() -> None:
    require = baseline.require
    require(DIAGNOSTIC.is_relative_to(OUT.resolve()), "diagnostic output escaped experiment outputs")
    require((OUT / "report.json").is_file() and (OUT / "selected_ticket_ledger.parquet").is_file(),
            "completed fit/evaluation outputs are missing")
    require(not DIAGNOSTIC.exists() and not SUMMARY.exists(), "refusing to overwrite existing diagnostic")
    report = baseline.json_read(OUT / "report.json")
    temperature = float(report["fit"]["temperature"])
    selections = pd.read_parquet(OUT / "selected_ticket_ledger.parquet")
    pivot = selections.pivot(index=["pool", "race_id"], columns="arm",
                             values=["selected_ticket_key", "selected_probability", "selected_hit"])
    changed: list[tuple[str, str, tuple[int, ...], tuple[int, ...]]] = []
    for (pool, race_id), row in pivot.iterrows():
        key_t1 = tuple(int(v) for v in json.loads(row[("selected_ticket_key", "T1")]))
        key_temp = tuple(int(v) for v in json.loads(row[("selected_ticket_key", "TEMP")]))
        if key_t1 != key_temp:
            changed.append((str(pool), str(race_id), key_t1, key_temp))
    expected = sum(int(v["changed_ticket_count"]) for v in report["selection_diagnostics"].values())
    require(len(changed) == expected == 61, f"changed choice count mismatch: {len(changed)} vs {expected}")

    _, eval_records, input_report = baseline.prepare_cohorts()
    records = {r["race_id"]: r for r in eval_records}
    output_rows: list[dict[str, object]] = []
    for pool, race_id, key_t1, key_temp in changed:
        race = records[race_id]
        require(pool != "PLC" or race["n"] >= 8, "unknown PLC threshold race unexpectedly has a selected ticket")
        plc_top = 3 if race["n"] >= 8 else 2
        maps_by_arm: dict[str, dict[tuple[int, ...], float]] = {}
        for arm, temp in (("T1", 1.0), ("TEMP", temperature)):
            triples, marginal = baseline.ordered_q(race["scores"], temp)
            maps_by_arm[arm] = baseline.make_ticket_maps(triples, marginal, race["numbers"], plc_top)[pool]
        p11 = float(maps_by_arm["T1"][key_t1])
        p21 = float(maps_by_arm["T1"][key_temp])
        p1t = float(maps_by_arm["TEMP"][key_t1])
        p2t = float(maps_by_arm["TEMP"][key_temp])
        saved = pivot.loc[(pool, race_id)]
        saved_t1 = float(saved[("selected_probability", "T1")])
        saved_temp = float(saved[("selected_probability", "TEMP")])
        require(abs(p11 - saved_t1) <= 3e-12, f"reconstructed T1 selected probability mismatch {pool}/{race_id}")
        require(abs(p2t - saved_temp) <= 3e-12, f"reconstructed TEMP selected probability mismatch {pool}/{race_id}")
        score_by_number = {int(number): float(score) for number, score in zip(race["numbers"], race["scores"])}
        score_t1 = ticket_scores(key_t1, score_by_number)
        score_temp = ticket_scores(key_temp, score_by_number)
        multiset_tie = sorted(score_t1) == sorted(score_temp)
        gap_t1 = p11 - p21
        gap_temp = p1t - p2t
        near_probability_tie = max(abs(gap_t1), abs(gap_temp)) <= 1e-12
        if multiset_tie and near_probability_tie:
            cause = "raw_score_multiset_tie_with_numerical_probability_roundoff"
        elif near_probability_tie:
            cause = "near_equal_ticket_probabilities_with_numerical_selection_flip"
        elif multiset_tie:
            cause = "raw_score_multiset_tie_with_material_probability_gap_review"
        else:
            cause = "non_tied_score_multisets_and_material_probability_gap_review"
        output_rows.append({
            "pool": pool, "race_id": race_id, "race_date": race["date"], "year": race["year"],
            "field_n": race["n"], "ticket_t1_json": json.dumps(list(key_t1), separators=(",", ":")),
            "ticket_temp_json": json.dumps(list(key_temp), separators=(",", ":")),
            "t1_ticket_scores_json": json.dumps(score_t1, separators=(",", ":")),
            "temp_ticket_scores_json": json.dumps(score_temp, separators=(",", ":")),
            "t1_ticket_score_sum": float(sum(score_t1)), "temp_ticket_score_sum": float(sum(score_temp)),
            "ticket_score_sum_gap_t1_minus_temp": float(sum(score_t1) - sum(score_temp)),
            "score_multiset_equal": bool(multiset_tie),
            "p_t1_ticket_at_t1": p11, "p_temp_ticket_at_t1": p21,
            "p_t1_ticket_at_temp": p1t, "p_temp_ticket_at_temp": p2t,
            "ticket_probability_gap_t1_minus_temp_at_t1": gap_t1,
            "ticket_probability_gap_t1_minus_temp_at_temp": gap_temp,
            "max_abs_probability_gap": max(abs(gap_t1), abs(gap_temp)),
            "within_1e_12_probability_tie_both_arms": bool(near_probability_tie),
            "t1_selected_hit": bool(saved[("selected_hit", "T1")]),
            "temp_selected_hit": bool(saved[("selected_hit", "TEMP")]),
            "diagnostic_cause": cause,
        })

    frame = pd.DataFrame(output_rows).sort_values(["pool", "race_date", "race_id"], kind="mergesort")
    require(not frame.empty and len(frame) == 61, "choice diagnostic row count changed")
    frame.to_parquet(DIAGNOSTIC, index=False, compression="zstd")
    counts = frame["diagnostic_cause"].value_counts().to_dict()
    summary = {
        "status": "DIAGNOSTIC_ONLY_NO_MODEL_OR_METRIC_CHANGES",
        "changed_ticket_rows": len(frame), "fitted_temperature_reused": temperature,
        "probability_match_tolerance": 3e-12,
        "numerical_tie_tolerance": 1e-12,
        "cause_counts": {str(k): int(v) for k, v in counts.items()},
        "within_tolerance_rows": int(frame["within_1e_12_probability_tie_both_arms"].sum()),
        "max_abs_probability_gap": float(frame["max_abs_probability_gap"].max()),
        "diagnostic_sha256": sha256(DIAGNOSTIC), "diagnostic_rows": len(frame),
        "input_selected_ledger_sha256": sha256(OUT / "selected_ticket_ledger.parquet"),
        "input_report_sha256": sha256(OUT / "report.json"),
        "source_feature_sha256": input_report["feature_sha256"],
        "source_score_sha256_by_year_role": [
            {"year": s["year"], "role": s["role"], "sha256": s["score_sha256"]}
            for s in input_report["sources"] if s["role"] == "evaluation"
        ],
        "interpretation": "Choice flips within tolerance are numerical tie-breaking behavior, not evidence of better race selection; no original loss, hit, or probability result is modified.",
    }
    with SUMMARY.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
