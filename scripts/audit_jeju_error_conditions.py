"""Frozen-reference pre-race changes, post-race observations and model explanations."""

import json
import pickle
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_error_conditions import (
    changed,
    closing_quality,
    delta,
    flags,
    number,
    rank_quality,
    valid_rank,
)
from scripts.build_jeju_context_features import DB, _history_rows, _source_rows
from scripts.freeze_jeju_trial_protocol import CTX, DATA, H3, ROOT, TRIAL, V5, sha
from scripts.run_jeju_trial_experiment import data_frame

OUT = ROOT / "data/research/jeju_native_error_conditions_v12_20260916"
V8 = ROOT / "data/research/jeju_native_set_interaction_v8_20260916"
METRICS = {
    "pre_distance_change_m": "선언 거리−직전 출전 거리(m)",
    "pre_burden_change_kg": "선언 부담중량−직전 실제 부담중량(kg)",
    "pre_rival_change_elo": "현재 상대 사전Elo평균−직전 상대 사전Elo평균",
    "pre_number_fraction_change": "현재 출주번호 상대위치−직전 상대위치; 물리 게이트 확정 아님",
    "pre_jockey_changed": "선언 기수와 직전 실제 기수 이름 차이",
    "pre_early_pressure_change": "현재 사전 선행성향 상대 수−직전의 사전 수",
    "pre_previous_finish_quality": "직전 정상 상대착순점수; 높을수록 앞선 착순",
    "distance_starts_pre": "동일 거리 사전 출전 경험",
    "days_since_previous_start": "기존 사전 최근 출전 간격",
    "current_vs_previous_rival_elo": "현재 편성−최근3회 편성 기존 추정치",
    "closing_speed_quality_mean_3": "기존 사전 최근3회 막판200m 상대속도",
    "historical_early_front_rate": "기존 사전 초반3위 내 빈도",
    "post_bodyweight_change_kg": "당일 결과문서 마체중−직전 실제 체중(kg); 시점 미입증",
    "post_moisture_change_pp": "당일 함수율−직전 함수율(%p); 결과문서 관측",
    "post_early_vs_history": "당일 초반 상대순위점수−사전 최근3회 평균",
    "post_closing_vs_history": "당일 막판200m 상대속도−사전 최근3회 평균",
    "post_early_to_finish_gain": "당일 S1F통과순위−착순; 결과를 포함한 묘사",
    "post_g1_to_finish_gain": "당일 결승200m전 순위−착순; 결과를 포함한 묘사",
    "post_actual_vs_declared_burden": "실제 부담중량−출마표 부담중량",
    "post_actual_vs_declared_jockey": "실제 기수와 출마표 기수 이름 차이",
}


def save(name, obj):
    (OUT / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


def paired_stats(pairs, columns):
    days = sorted({r["event_date"] for r in pairs})
    daymap = {d: i for i, d in enumerate(days)}
    dayids = np.array([daymap[r["event_date"]] for r in pairs])
    draws = np.random.default_rng(17).integers(0, len(days), (5000, len(days)))
    result = []
    for key in columns:
        a = np.array(
            [
                r.get("missed__" + key) if r.get("missed__" + key) is not None else np.nan
                for r in pairs
            ],
            float,
        )
        b = np.array(
            [
                r.get("selected__" + key) if r.get("selected__" + key) is not None else np.nan
                for r in pairs
            ],
            float,
        )
        ok = np.isfinite(a) & np.isfinite(b)
        d = a - b
        sums = np.zeros(len(days))
        counts = np.zeros(len(days))
        np.add.at(sums, dayids[ok], d[ok])
        np.add.at(counts, dayids[ok], 1)
        den = counts[draws].sum(axis=1)
        num = sums[draws].sum(axis=1)
        boot = np.divide(num, den, out=np.full(5000, np.nan), where=den > 0)
        result.append(
            dict(
                metric=key,
                paired_n=int(ok.sum()),
                missed_observed_n=int(np.isfinite(a).sum()),
                selected_observed_n=int(np.isfinite(b).sum()),
                missed_mean=float(np.mean(a[ok])) if ok.any() else None,
                selected_mean=float(np.mean(b[ok])) if ok.any() else None,
                missed_median=float(np.median(a[ok])) if ok.any() else None,
                selected_median=float(np.median(b[ok])) if ok.any() else None,
                mean_difference=float(np.mean(d[ok])) if ok.any() else None,
                day_ci=np.nanquantile(boot, [0.025, 0.975]).tolist() if ok.any() else None,
            )
        )
    return result


def main():
    OUT.mkdir(exist_ok=False)
    protocol = dict(
        created_at=datetime.now(UTC).isoformat(),
        reference="HY_R_FORM",
        purpose="Posthoc descriptive audit, no causal attribution, no feature/model/threshold fitting.",  # noqa: E501
        primary="Exactly two correct, nonboundary2025 races:332 pairs. All709 nonboundary races as descriptive context.",  # noqa: E501
        timing="pre_ only sealed T-2 histories/declarations, historical publication proof incomplete. post_ results are diagnosis only.",  # noqa: E501
        metrics=METRICS,
        flags=list(flags({})),
        thresholds="burden-1kg, rivals-20Elo, early/closing quality delta0.25, lost3positions, absweight10kg; descriptive fixed thresholds, not learned optimal conditions.",  # noqa: E501
        uncertainty="5000 paired race-day bootstrap seed17, unadjusted exploratory95% intervals. Correctness-conditioned sample, no causal/population extrapolation.",  # noqa: E501
        explanation="Mean two frozen R_FORM tree contribution arrays; verify score reconstruction. Explains model score, not biological cause. Correlated features share credit non-uniquely.",  # noqa: E501
        case_selection="Largest saved selected-minus-missed score margin; top6 overall in appendix, one example per fixed flag with largest margin when available.",  # noqa: E501
        parents={
            str(p.relative_to(ROOT)): sha(p / "manifest.json")
            for p in [DATA, H3, CTX, TRIAL, V5, V8]
        },
        database_sha256=sha(DB),
        fits=0,
        predictions_changed=0,
        predictions_2026=0,
    )
    save("protocol.json", protocol)
    p5 = json.loads((V5 / "protocol.json").read_text())
    frame, meta, truth, folds = data_frame(p5)
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() <= 2025)
    states = pl.read_parquet(DATA / "horse_states.parquet")
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    source = _source_rows(c)
    history = _history_rows(entries, labels, source, states)
    emap = {r["entry_id"]: r for r in entries.iter_rows(named=True)}
    fmap = {r["entry_id"]: r for r in frame.iter_rows(named=True)}
    hmap = {r["entry_id"]: r for r in history}
    lines = {
        r["entry_id"]: r for r in pl.read_parquet(H3 / "lineage.parquet").iter_rows(named=True)
    }
    byhorse = defaultdict(list)
    byrace = defaultdict(list)
    for r in history:
        byhorse[str(r["horse_id"])].append(r)
        byrace[r["race_id"]].append(r)
    for rs in byhorse.values():
        rs.sort(key=lambda r: (r["event_date"], r["entry_id"]))
    maxnumber = {rid: max(r["horse_number"] for r in rs) for rid, rs in byrace.items()}
    previous = {}
    records = []
    predictions = pl.read_parquet(V5 / "race_predictions.parquet").filter(
        pl.col("model") == "HY_R_FORM"
    )
    predictionmap = {r["race_id"]: r for r in predictions.iter_rows(named=True)}
    hp = pl.read_parquet(V5 / "horse_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    hpmap = {(r["race_id"], r["horse_id"]): r for r in hp.iter_rows(named=True)}
    for t in frame.filter(pl.col("event_date").dt.year() == 2025).iter_rows(named=True):
        eid = t["entry_id"]
        rid = t["race_id"]
        current = hmap[eid]
        src = source[eid]
        cutoff = t["event_date"] - timedelta(days=2)
        prior = [r for r in byhorse[str(t["horse_id"])] if r["event_date"] <= cutoff]
        prev = prior[-1] if prior else None
        previous[eid] = prev["entry_id"] if prev else None
        pf = fmap[prev["entry_id"]] if prev else {}
        ps = source[prev["entry_id"]] if prev else {}
        pred = predictionmap[rid]
        selected = t["horse_id"] in pred["predicted_set"]
        podium = t["label_top3"] == 1
        role = (
            ("selected_hit" if selected else "missed_podium")
            if podium
            else ("selected_miss" if selected else "unselected_nonpodium")
        )
        field = t["field_size"]
        finish = valid_rank(current["finish_position"], field)
        early = valid_rank(src["early_rank"], field)
        g1rank = valid_rank(src["g1_rank"], field)
        peers = byrace[rid]
        g1time = number(current["g1f_seconds"])
        g1time = (
            g1time
            if g1time is not None
            and current["finish_time_ms"] is not None
            and 0 < g1time < current["finish_time_ms"] / 1000
            else None
        )
        closing = closing_quality(
            g1time,
            [
                r["g1f_seconds"]
                for r in peers
                if r["finish_time_ms"] is not None
                and number(r["g1f_seconds"]) is not None
                and 0 < float(r["g1f_seconds"]) < r["finish_time_ms"] / 1000
            ],
        )
        prev_fraction = (
            (prev["horse_number"] - 1) / (maxnumber[prev["race_id"]] - 1)
            if prev and maxnumber[prev["race_id"]] > 1
            else None
        )
        hpone = hpmap[(rid, t["horse_id"])]
        row = dict(
            entry_id=eid,
            race_id=rid,
            event_date=str(t["event_date"]),
            event_number=emap[eid]["event_number"],
            horse_id=t["horse_id"],
            horse_name=src["horse_name"],
            horse_number=emap[eid]["horse_number"],
            distance_m=t["distance_m"],
            field_size=field,
            fold=pred["fold"],
            boundary_tie=pred["boundary_tie"],
            role=role,
            selected=selected,
            official_top3=podium,
            finish_position=finish,
            previous_entry_id=previous[eid],
            previous_date=str(prev["event_date"]) if prev else None,
            cutoff_date=str(cutoff),
            score=hpone["score"],
            place_probability=hpone["pl_place_probability"],
            pre_distance_change_m=delta(
                t["distance_m"], emap[prev["entry_id"]]["distance_m"] if prev else None
            ),
            pre_burden_change_kg=delta(
                t["declared_burden_kg"], prev["burden_kg"] if prev else None
            ),
            pre_rival_change_elo=delta(
                t["rival_global_elo_mean"], prev["rival_elo_mean"] if prev else None
            ),
            pre_number_fraction_change=delta(t["declared_horse_number_fraction"], prev_fraction),
            pre_jockey_changed=changed(
                lines[eid]["jockey_name"], prev["jockey_name"] if prev else None
            ),
            pre_early_pressure_change=delta(
                t["rival_early_pressure_count"], pf.get("rival_early_pressure_count")
            ),
            pre_previous_finish_quality=rank_quality(prev["finish_position"], prev["field_size"])
            if prev
            else None,
            post_bodyweight_change_kg=delta(src["body_weight_kg"], ps.get("body_weight_kg")),
            post_moisture_change_pp=delta(
                src["track_moisture_percent"], ps.get("track_moisture_percent")
            ),
            post_early_vs_history=delta(rank_quality(early, field), t["early_rank_percentile_3"]),
            post_closing_vs_history=delta(closing, t["closing_speed_quality_mean_3"]),
            post_early_to_finish_gain=delta(early, finish),
            post_g1_to_finish_gain=delta(g1rank, finish),
            post_actual_vs_declared_burden=delta(src["burden_kg"], t["declared_burden_kg"]),
            post_actual_vs_declared_jockey=changed(src["jockey_name"], lines[eid]["jockey_name"]),
            post_early_rank=early,
            post_g1_rank=g1rank,
            post_g1f_seconds=g1time,
            post_closing_quality=closing,
            pre_declared_burden_kg=t["declared_burden_kg"],
            pre_declared_jockey=lines[eid]["jockey_name"],
            post_actual_jockey=src["jockey_name"],
            post_bodyweight_kg=src["body_weight_kg"],
            post_moisture=src["track_moisture_percent"],
            post_weather=src["weather"],
        )
        for key in METRICS:
            if key not in row:
                row[key] = t[key]
        row.update(flags(row))
        records.append(clean(row))
    rf = pl.DataFrame(records, infer_schema_length=None)
    rf.write_parquet(OUT / "entry_conditions.parquet")
    lookup = {(r["race_id"], r["horse_id"]): r for r in records}
    oldpairs = pl.read_parquet(V8 / "missing_horse_pairs.parquet")
    pairs = []
    for pair in oldpairs.iter_rows(named=True):
        m = lookup[(pair["race_id"], pair["missing_horse_id"])]
        s = lookup[(pair["race_id"], pair["selected_nonpodium_horse_id"])]
        assert (
            m["role"] == "missed_podium" and s["role"] == "selected_miss" and not m["boundary_tie"]
        )
        row = dict(
            race_id=pair["race_id"],
            event_date=pair["event_date"],
            missed_entry_id=m["entry_id"],
            selected_entry_id=s["entry_id"],
            score_margin=s["score"] - m["score"],
        )
        for prefix, entry in [("missed", m), ("selected", s)]:
            for key, val in entry.items():
                row[prefix + "__" + key] = val
        pairs.append(row)
    assert len(pairs) == 332
    pl.DataFrame(pairs, infer_schema_length=None).write_parquet(OUT / "paired_conditions.parquet")
    save(
        "paired_statistics.json",
        paired_stats(pairs, list(dict.fromkeys(list(METRICS) + list(flags({}))))),
    )
    controls = []
    for role in sorted(rf["role"].unique()):
        rs = [r for r in records if r["role"] == role and not r["boundary_tie"]]
        for key in list(dict.fromkeys(list(METRICS) + list(flags({})))):
            a = [r[key] for r in rs if number(r.get(key)) is not None]
            controls.append(
                dict(
                    role=role,
                    metric=key,
                    entries=len(rs),
                    observed=len(a),
                    mean=float(np.mean(a)) if a else None,
                )
            )
    save("all_entry_context.json", controls)
    print("conditions and332pairs complete", flush=True)
    # Exact frozen model score contribution differences; never refit any estimator.
    pairids = {r["missed_entry_id"] for r in pairs} | {r["selected_entry_id"] for r in pairs}
    contrib = {}
    features = {}
    maxerror = 0
    for fold in sorted(folds["fold_id"].unique()):
        b = pickle.loads((V5 / "bundles" / f"{fold}__R_FORM.pkl").read_bytes())
        ids = folds.filter((pl.col("fold_id") == fold) & (pl.col("role") == "evaluation")).select(
            "race_id"
        )
        ev = (
            frame.join(ids, on="race_id", how="semi")
            .filter(pl.col("entry_id").is_in(pairids))
            .sort("entry_id")
        )
        x = b["preprocessor"].transform(ev)
        values = np.mean([model.predict(x, pred_contrib=True) for model in b["models"]], axis=0)
        raw = np.mean([model.predict(x, raw_score=True) for model in b["models"]], axis=0)
        np.testing.assert_allclose(values.sum(axis=1), raw, atol=1e-10, rtol=0)
        for idx, r in enumerate(ev.iter_rows(named=True)):
            np.testing.assert_allclose(
                raw[idx], hpmap[(r["race_id"], r["horse_id"])]["score"], atol=1e-12, rtol=0
            )
            contrib[r["entry_id"]] = dict(
                zip(b["preprocessor"].names + ["__expected_value"], values[idx], strict=True)
            )
        maxerror = max(maxerror, float(np.max(np.abs(values.sum(axis=1) - raw))))
        features[fold] = b["preprocessor"].names
    allcontrib = []
    explanations = []
    for pair in pairs:
        a = contrib[pair["missed_entry_id"]]
        b = contrib[pair["selected_entry_id"]]
        keys = sorted(set(a) | set(b))
        diff = {k: a.get(k, 0) - b.get(k, 0) for k in keys}
        assert abs(sum(diff.values()) + pair["score_margin"]) < 1e-10
        factors = {}
        for k, v in diff.items():
            if k == "__expected_value":
                continue
            factors[k] = float(v)
            allcontrib.append(
                dict(
                    race_id=pair["race_id"],
                    event_date=pair["event_date"],
                    feature=k,
                    missed_minus_selected=float(v),
                )
            )
        explanations.append(
            dict(
                race_id=pair["race_id"],
                score_margin=pair["score_margin"],
                model_favored_selected=sorted(factors.items(), key=lambda kv: kv[1])[:5],
                model_favored_missed=sorted(factors.items(), key=lambda kv: kv[1], reverse=True)[
                    :5
                ],
            )
        )
    cf = pl.DataFrame(allcontrib)
    cf.write_parquet(OUT / "score_contribution_pairs.parquet")
    agg = cf.group_by("feature").agg(
        pl.col("missed_minus_selected").sum().alias("sum_difference"),
        pl.len().alias("present_pairs"),
    )
    agg = agg.with_columns(
        (pl.col("sum_difference") / 332).alias("mean_difference_all_pairs")
    ).sort("mean_difference_all_pairs")
    save(
        "model_explanation_summary.json",
        dict(
            max_reconstruction_error=maxerror,
            features_by_fold=features,
            aggregates=agg.to_dicts(),
            interpretation="Explains frozen model scoring, not causes of race outcomes. Missing features across folds contribute0.",  # noqa: E501
        ),
    )
    save("case_model_explanations.json", explanations)
    needed = {r["entry_id"] for r in records} | {
        r["previous_entry_id"] for r in records if r["previous_entry_id"] is not None
    }
    evidence = []
    for r in c.execute(
        "select e.id entry_id,e.source_row_id,v.grade,s.source_artifact_id,s.line_number,s.row_sha256,s.normalized_json from entry e join event v on v.id=e.event_id join source_row s on s.id=e.source_row_id where v.event_type='race' and v.event_date<='20251231'"  # noqa: E501
    ):
        if r["entry_id"] in needed:
            evidence.append(dict(r))
    with (OUT / "source_evidence.jsonl").open("w") as f:
        for r in evidence:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    c.close()
    save(
        "summary.json",
        dict(
            entries=len(records),
            nonboundary_entries=rf.filter(~pl.col("boundary_tie")).height,
            pairs=len(pairs),
            pair_days=len({r["event_date"] for r in pairs}),
            role_counts=rf.filter(~pl.col("boundary_tie")).group_by("role").len().to_dicts(),
            condition_definitions=METRICS,
            evidence_rows=len(evidence),
            source_time="Current actual bodyweight/weather/sections are result-document diagnostics, not historical release-time proof.",  # noqa: E501
            fits=0,
            predictions_changed=0,
            predictions_2026=0,
        ),
    )
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
