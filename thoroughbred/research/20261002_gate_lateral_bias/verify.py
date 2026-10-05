"""Rebuild contrasts with a separate solver and verify every paired source connection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("study", HERE / "analyze.py")
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def bh(values):
    p = np.array(values)
    order = np.argsort(p)
    q = p[order] * len(p) / np.arange(1, len(p) + 1)
    for i in range(len(q) - 2, -1, -1):
        q[i] = min(q[i], q[i + 1])
    result = np.empty(len(p))
    result[order] = np.minimum(q, 1)
    return result


def equivalent(left, right):
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            equivalent(left[key], right[key])
    elif isinstance(left, list):
        assert len(left) == len(right)
        for a, b in zip(left, right, strict=True):
            equivalent(a, b)
    elif isinstance(left, float):
        assert np.isclose(left, right, rtol=0, atol=1e-8)
    else:
        assert left == right


def reconstruct_gate(frame):
    indicators = [frame.gate_side.eq(side).to_numpy(float) for side in ["middle", "outer"]]
    for key in STUDY.CONTROLS:
        values = frame[key].to_numpy(float)
        absent = np.isnan(values) | np.isinf(values)
        filled = np.where(absent, np.median(values[~absent]) if (~absent).any() else 0, values)
        spread = np.std(filled)
        indicators.append((filled - filled.mean()) / (spread if spread > 1e-10 else 1))
        if absent.any():
            indicators.append(absent.astype(float))
    x = pd.DataFrame(np.column_stack(indicators), index=frame.index)
    centered = x - x.groupby(frame.race_key).transform("mean")
    y = frame.top3 - frame.groupby("race_key").top3.transform("mean")
    weight = 1 / frame.groupby("race_key").race_key.transform("size")
    fit, _, _, _ = np.linalg.lstsq(
        centered.to_numpy() * np.sqrt(weight.to_numpy())[:, None],
        y.to_numpy() * np.sqrt(weight.to_numpy()),
        rcond=1e-10,
    )
    return float(fit[1]) * 100


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    for path, digest in saved["inputs_sha256"].items():
        assert STUDY.sha(Path(path)) == digest
    population = pd.read_parquet(OUT / "runners.parquet")
    assert len(population) == saved["coverage"]["runners"]
    assert population.race_key.nunique() == saved["coverage"]["races"]
    assert not population.duplicated(STUDY.POSITION.KEY).any()
    assert (
        population.last_history_date.isna() | population.last_history_date.lt(population.dt)
    ).all()
    for _, group in population.groupby("race_key"):
        assert len(group) >= 6
        assert sorted(group["rank"].astype(int)) == list(range(1, len(group) + 1))
        expected = (group.horse_number.rank(method="first") - 0.5) / len(group)
        np.testing.assert_allclose(group.gate_pct, expected, rtol=0, atol=1e-12)
    reconstructed = []
    for row in saved["gate"]:
        if row["period"] != "all" or row["scope"] != "distance":
            continue
        frame = population[
            population.meet.eq(row["meet"]) & population.distance_m.eq(row["distance_m"])
        ]
        coefficient = reconstruct_gate(frame)
        assert abs(coefficient - row["effect_pp"]) < 1e-8
        cells = frame.groupby(["race_key", "gate_side"]).top3.mean().unstack()
        raw = float((cells.outer - cells.inner).mean()) * 100
        assert abs(raw - row["raw_effect_pp"]) < 1e-10
        reconstructed.append(
            {
                "meet": row["meet"],
                "distance_m": row["distance_m"],
                "effect_difference_pp": coefficient - row["effect_pp"],
            }
        )
    for family in [saved["gate"], saved["numbers"]]:
        rows = [
            r
            for r in family
            if r["period"] == "all" and r["scope"] == "distance" and r["estimable"]
        ]
        np.testing.assert_allclose(
            [r["q_distance"] for r in rows], bh([r["p"] for r in rows]), rtol=0, atol=1e-12
        )
    rows = [
        r
        for r in saved["lateral"]
        if r["period"] == "all" and r["scope"] == "all" and r["adjusted"]["estimable"]
    ]
    np.testing.assert_allclose(
        [r["q_point"] for r in rows], bh([r["adjusted"]["p"] for r in rows]), rtol=0, atol=1e-12
    )
    pairs = pd.read_parquet(OUT / "pack_pairs.parquet")
    passing = pd.read_parquet(OUT / "passing_snapshot.parquet")
    points = passing.set_index(["race_key", "point"])
    packs = {}
    for (race, point), row in points.iterrows():
        tokens = re.findall(r"\([^()]+\)|\^?\d+", row.notation_raw)
        packs[race, point] = [list(map(int, re.findall(r"\d+", token))) for token in tokens]
    look = population.set_index(["race_key", "horse_number"])
    for row in pairs.itertuples(index=False):
        members = packs[row.race_key, row.point][row.pack_index]
        assert len(members) == row.pack_size >= 2
        assert members[0] == row.inner_number and members[-1] == row.outer_number
    inner_index = pd.MultiIndex.from_arrays([pairs.race_key, pairs.inner_number])
    outer_index = pd.MultiIndex.from_arrays([pairs.race_key, pairs.outer_number])
    inner, outer = look.reindex(inner_index), look.reindex(outer_index)
    np.testing.assert_array_equal(
        pairs.top3_difference.to_numpy(), outer.top3.to_numpy() - inner.top3.to_numpy()
    )
    for key in STUDY.CONTROLS + ["gate_pct"]:
        for side, frame in [("inner", inner), ("outer", outer)]:
            np.testing.assert_allclose(
                pairs[f"{side}_{key}"].to_numpy(),
                frame[key].to_numpy(),
                rtol=0,
                atol=0,
                equal_nan=True,
            )
    assert len(pairs) == saved["coverage"]["pairs"]
    assert not pairs.duplicated(["race_key", "point", "pack_index"]).any()
    for row in rows:
        sample = pairs[pairs.meet.eq(row["meet"]) & pairs.point.eq(row["point"])]
        raw = float(sample.groupby("race_key").top3_difference.mean().mean()) * 100
        assert abs(raw - row["raw"]["effect_pp"]) < 1e-8
        adjusted = STUDY.pair_fit(sample, True)
        assert abs(adjusted["effect_pp"] - row["adjusted"]["effect_pp"]) < 1e-10
    first = json.loads((HERE / "outputs_initial/summary.json").read_text())
    for key in ["coverage", "gate", "numbers", "lateral"]:
        equivalent(first[key], saved[key])
    section = json.loads(
        (HERE.parent / "20261002_moisture_section_strength/outputs/summary.json").read_text()
    )
    for path, digest in section["inputs_sha256"].items():
        if path.endswith("TRACK_MOISTURE_CORRECTION_DECISION_2026-10-02.md"):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    report = {
        "source_hashes_unchanged": True,
        "normal_rank_and_prior_dates_checked": True,
        "all_quality_gate_distances_reconstructed_separate_solver": reconstructed,
        "bh_families_recomputed": True,
        "all_paired_source_rosters_and_control_values_checked": len(pairs),
        "raw_race_equal_lateral_means_recomputed": len(rows),
        "repeat_results_equivalent_at_1e_8": True,
        "fulltime_decision_original_preserved": True,
    }
    (OUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
