"""Build immutable current-card bundles with the registered frozen models.

Read-only against production. Reuses the reviewed feature/scoring implementations;
the separate repository publisher is the only database writer.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import sys
import uuid
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "data/research/thoroughbred_win_research_20260918_v2"
V3 = ROOT / "data/research/thoroughbred_three_targets_20260918_v3"
V4 = ROOT / "data/research/thoroughbred_followup_20260918_v4"
SOURCE = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
sys.path[:0] = [str(V2 / "code"), str(V3 / "code"), str(V4 / "model/code")]
import context_features  # noqa: E402
import features_v2  # noqa: E402
import shadow  # noqa: E402
from infer_targets import validate_frame  # noqa: E402
from run_v4_model import NEW, strict_features  # noqa: E402
from sync_live_race_day import _database_url  # noqa: E402


def builder_module():
    path = (
        ROOT
        / ".agents/skills/horse-racing-prediction-publisher/scripts"
        / "build_20260919_publication_bundles.py"
    )
    spec = importlib.util.spec_from_file_location("frozen_publication_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def context_history(before):
    with duckdb.connect(str(SOURCE), read_only=True) as c:
        history = (
            c.execute(
                """
          WITH s1f AS (SELECT race_id,hr_no,try_cast(position_raw AS INTEGER) s1f_position
            FROM section WHERE section_code='S1F' AND venue_code IN ('SEOUL','YEONGCHEON')
            AND semantic_status IN ('verified_source_field','official_api_verified_first_meeting'))
          SELECT e.race_id,e.race_date,e.chul_no,e.hr_no,e.venue_code,r.distance_m,
            CASE WHEN e.finish_order IS NOT NULL THEN e.finish_order
              WHEN e.venue_code='YEONGCHEON' AND e.result_status='finished'
              THEN try_cast(e.finish_raw AS INTEGER) ELSE NULL END finish_order,
            e.result_status,CASE WHEN e.venue_code='YEONGCHEON' AND e.result_status='finished'
              AND try_cast(e.finish_raw AS INTEGER) IS NOT NULL THEN true
              ELSE e.is_rank_label END is_rank_label,
            e.jockey_no,e.burden_weight_kg,e.horse_weight_kg,s.s1f_position,
            b.research_elo_global baseline_elo
          FROM entry_result e JOIN race r USING(race_id)
          LEFT JOIN s1f s USING(race_id,hr_no)
          LEFT JOIN read_parquet(?) b USING(race_id,hr_no)
          WHERE r.official_result_state='confirmed' AND e.race_date>=DATE '2000-01-01'
            AND e.race_date < ?::DATE ORDER BY e.race_date,e.race_id,e.chul_no,e.hr_no
        """,
                [str(V2 / "prepared_v2.parquet"), before],
            )
            .fetchdf()
            .to_dict("records")
        )
        trials = (
            c.execute(
                """SELECT trial_event_id,trial_date,hr_no,distance_m,finish_time_ms
          FROM trial_entry WHERE hr_no IS NOT NULL AND trial_date < ?::DATE
            AND venue_resolution_status IN ('confirmed','confirmed_historical_text')
            AND ((horse_link_status='confirmed'
                  AND venue_resolution_status='confirmed_historical_text')
              OR horse_link_status IN ('confirmed_official_id','linked_profile_signature',
                'linked_race_age_corroborated','linked_training_date_corroborated',
                'linked_training_disambiguated'))
          ORDER BY trial_date,trial_event_id,hr_no""",
                [before],
            )
            .fetchdf()
            .to_dict("records")
        )
    return history, trials


def enrich_context(base, history, trials):
    enriched = pd.DataFrame(context_features.derive_context_features(history, base, trials))
    for name in context_features.ALL_FEATURES:
        enriched[name] = pd.to_numeric(enriched[name], errors="raise")
    keys = ["race_id", "hr_no"]
    return base.merge(
        enriched[keys + context_features.ALL_FEATURES], on=keys, validate="one_to_one"
    )


def enrich_v4(frame, before):
    old = pd.read_parquet(V3 / "prepared_context.parquet")
    old["race_date"] = pd.to_datetime(old.race_date)
    old = old[old.race_date < pd.Timestamp(before)].copy()
    future = frame.copy()
    for col in old:
        if col not in future:
            future[col] = False if col == "target_is_rank_label" else np.nan
    together = pd.concat([old, future[old.columns]], ignore_index=True)
    together["race_date"] = pd.to_datetime(together.race_date)
    out = strict_features(together)
    extra = out[out.race_id.isin(set(frame.race_id))][["race_id", "hr_no"] + NEW]
    return frame.merge(extra, on=["race_id", "hr_no"], validate="one_to_one")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True)
    p.add_argument("--seoul-snapshot", type=Path, required=True)
    p.add_argument("--jeju-inference", type=Path, required=True)
    p.add_argument("--prepared-seoul-features", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    # This legacy builder hardcodes old A/BC/WIN assets. It must never label
    # those scores as a different active champion after a registry promotion.
    current_registry = json.loads((ROOT / "config/prediction_model_registry.json").read_text())
    active_thoroughbred = current_registry["domains"]["thoroughbred"]["active_profile"]
    if active_thoroughbred != "thoroughbred-main-20260919-v1":
        raise ValueError(
            "This legacy builder is incompatible with the active Thoroughbred profile; "
            "use scripts/predict_thoroughbred_main.py with its result-free card contract"
        )
    a.output = a.output.resolve()
    day = datetime.strptime(a.date, "%Y%m%d").date().isoformat()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    b = builder_module()
    registry, registry_hash = b.read_registry()
    url = _database_url("xkykmhhkjtosptoibduo", "horse-racing-database-url", "mapilog-509017")
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    with engine.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        db = pd.read_sql_query(
            text("""SELECT r.id db_race_id,e.id race_entry_id,
          cast(r.race_date_local as text) race_date,rc.code venue_code,r.race_number race_no,
          e.horse_number,e.gate_number,e.carried_weight_kg,e.scratched,
          h.kra_horse_id runner_identifier,h.name_ko horse_name,
          j.kra_jockey_id jockey_identifier,t.kra_trainer_id trainer_identifier,
          o.kra_owner_id owner_identifier FROM races r
          JOIN racecourses rc ON rc.id=r.racecourse_id JOIN race_entries e ON e.race_id=r.id
          JOIN horses h ON h.id=e.horse_id LEFT JOIN jockeys j ON j.id=e.jockey_id
          LEFT JOIN trainers t ON t.id=e.trainer_id LEFT JOIN owners o ON o.id=e.owner_id
          WHERE r.race_date_local=cast(:day as date) AND rc.kra_meet_code in (1,2)
          ORDER BY rc.kra_meet_code,r.race_number,e.horse_number"""),
            c,
            params={"day": day},
        )
    engine.dispose()
    db["runner_identifier"] = db.runner_identifier.astype(str).str.zfill(7)
    if db.scratched.any():
        raise ValueError("Scratched cards require a verified relative-feature rebuild")

    history, trials = context_history(day)
    # Reproduce the preserved context and v4 fixture before accepting new cards.
    old_base = pd.read_parquet(V2 / "shadow/features/future_20260919_20_base38_v2_verified.parquet")
    old_context = enrich_context(old_base, history, trials)
    fixture = pd.read_parquet(V3 / "prediction_input/future_20260919_20_context.parquet")
    old_context = old_context.sort_values(["race_id", "hr_no"]).reset_index(drop=True)
    fixture = fixture.sort_values(["race_id", "hr_no"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        old_context[context_features.ALL_FEATURES],
        fixture[context_features.ALL_FEATURES],
        check_dtype=False,
        atol=1e-12,
        rtol=1e-12,
    )
    replay = (
        enrich_v4(fixture, "2026-09-19").sort_values(["race_id", "hr_no"]).reset_index(drop=True)
    )
    expected_v4 = (
        pd.read_parquet(V4 / "model/future_predictions_20260919_20/prepared_v4_features.parquet")
        .sort_values(["race_id", "hr_no"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(
        replay[NEW], expected_v4[NEW], check_dtype=False, atol=1e-12, rtol=1e-12
    )
    print("Frozen context/v4 replay passed", flush=True)

    snapshot = json.loads(a.seoul_snapshot.read_text())
    if snapshot["race_date"] != day or snapshot["meet"] != 1:
        raise ValueError("Wrong Seoul card date/venue")
    raw_history = shadow._history_rows(SOURCE, day)
    cards = shadow._card_rows([snapshot])
    if a.prepared_seoul_features is None:
        base = pd.DataFrame(
            features_v2.derive_features(raw_history, shadow._base38(cards, raw_history))
        )
        frame = enrich_v4(enrich_context(base, history, trials), day)
    else:
        frame = pd.read_parquet(a.prepared_seoul_features)
        expected_keys = {(r["race_id"], r["hr_no"]) for r in cards}
        if set(zip(frame.race_id, frame.hr_no, strict=True)) != expected_keys:
            raise ValueError("Prepared Seoul feature card identities differ")
        if not frame.source_snapshot_id.eq(snapshot["snapshot_id"]).all():
            raise ValueError("Prepared Seoul features reference a different card snapshot")
    frame["race_date"] = pd.to_datetime(frame.race_date)
    frame["feature_cutoff"] = pd.to_datetime(frame.feature_cutoff)
    frame = frame.sort_values(["race_date", "race_id", "chul_no", "hr_no"]).reset_index(drop=True)
    validate_frame(frame, False)
    frame.to_parquet(a.output / "seoul_features.parquet", index=False)
    tc = b.core.tc
    win = tc.load_v2_win_bundle(b.V2 / "models/2026/H3_relative")
    bc = tc.load_bundle(b.V4 / "model/models/2026/top3_growth_strength")
    am = tc.load_bundle(b.V5 / "windows/models/2026H2/rolling_all")
    ws, bs, aas = (
        tc.raw_scores(win, frame)["win"],
        tc.raw_scores(bc, frame)["top3"],
        tc.raw_scores(am, frame)["top3"],
    )
    matrix = tc.prepare_matrix(
        frame, am.categorical_features, am.numeric_features, am.category_vocab
    )
    contrib = np.asarray(am.models["top3"].predict(matrix, pred_contrib=True, num_threads=4))
    names = list(am.categorical_features) + list(am.numeric_features)
    if contrib.shape != (len(frame), len(names) + 1):
        raise ValueError("Contribution shape mismatch")
    summary = []
    for domain in ("thoroughbred", "jeju"):
        profile = b.profile_for(registry, domain)
        stored = db[db.venue_code == ("SEOUL" if domain == "thoroughbred" else "JEJU")]
        lookup = {(int(r.race_no), str(r.runner_identifier)): r for r in stored.itertuples()}
        rows, explanations = [], []
        if domain == "thoroughbred":
            values = frame
            source_ms = b.epoch_ms(snapshot["observed_at_utc"])
            card_hash = b.sha256_json(snapshot)
            feature_hash = b.sha256_file(a.output / "seoul_features.parquet")
            cutoff = max(str(r["race_date"])[:10] for r in raw_history)
            components = []
            for component, model, metaname, artifactname in [
                ("A", am, "A_metadata", "A_model"),
                ("B", bc, "BC_metadata", "BC_model"),
                ("C", bc, "BC_metadata", "BC_model"),
                ("C_ORDER", win, "WIN_ORDER_metadata", "WIN_ORDER_model"),
            ]:
                params = {
                    "temperature_by_venue": model.metadata["temperature_by_venue"]
                    if component == "C_ORDER"
                    else model.metadata["temperature_by_target_and_venue"][component]
                }
                if component == "C":
                    params["order_artifact_sha256"] = b.artifact(profile, "WIN_ORDER_model")[
                        "sha256"
                    ]
                components.append(
                    {
                        "component": component,
                        "model_version": profile["components"]
                        .get(component, {})
                        .get("model_version", "v2_2026_H3_relative"),
                        "candidate_name": profile["components"]
                        .get(component, {})
                        .get("candidate", "H3_relative"),
                        "artifact_sha256": b.artifact(profile, artifactname)["sha256"],
                        "metadata_sha256": b.artifact(profile, metaname)["sha256"],
                        "algorithm_version": profile["combination_algorithm_version"]
                        if component != "C_ORDER"
                        else "plackett_luce_within_set_v1",
                        "parameters": params,
                    }
                )
            model_hash = b.artifact(profile, "A_model")["sha256"]
        else:
            meta = json.loads((a.jeju_inference / "metadata.json").read_text())
            if (
                meta["target_date"] != day
                or meta["target_result_endpoints_called"]
                or meta["model_sha256"] != b.artifact(profile, "HY_R_FORM_model")["sha256"]
            ):
                raise ValueError("Jeju inference provenance mismatch")
            values = pd.read_parquet(a.jeju_inference / "model_scores.parquet")
            source_ms = max(p["retrieved_at_ms"] for p in meta["source_pages"])
            for page in meta["source_pages"]:
                if b.sha256_file(a.jeju_inference / page["raw_file"]) != page["raw_sha256"]:
                    raise ValueError("Jeju raw-card hash mismatch")
            card_hash = (
                meta["source_pages"][0]["raw_sha256"]
                if len(meta["source_pages"]) == 1
                else b.sha256_json(meta["source_pages"])
            )
            feature_hash = b.sha256_file(a.jeju_inference / "live_features.parquet")
            cutoff = meta["history_last_date"]
            with b.JEJU_MODEL.open("rb") as f:
                model = pickle.load(f)  # hash-verified trusted local artifact
            beta, beta_order = float(model["rank_bundle"]["beta"]), float(model["beta_order"])
            docs = {
                int(r["entry_id"]): r
                for r in json.loads((a.jeju_inference / "horse_explanations.json").read_text())
            }
            model_hash = meta["model_sha256"]
            components = [
                {
                    "component": "A_B_C",
                    "model_version": profile["components"]["A_B_C"]["model_version"],
                    "candidate_name": "HY_R_FORM",
                    "artifact_sha256": model_hash,
                    "metadata_sha256": None,
                    "algorithm_version": profile["combination_algorithm_version"],
                    "parameters": {
                        "beta_set": beta,
                        "beta_order": beta_order,
                        "set_score": "rank_score",
                        "order_score": "order_score",
                    },
                }
            ]
        for rid, indexes in values.groupby("race_id", sort=False).groups.items():
            part = values.loc[indexes]
            if domain == "thoroughbred":
                pos = np.asarray(list(indexes), int)
                joint = tc.top3_set_joint(
                    aas[pos],
                    ws[pos],
                    am.metadata["temperature_by_target_and_venue"]["A"]["SEOUL"],
                    win.metadata["temperature_by_venue"].get("SEOUL", 1.0),
                )
                probs = b.joint_marginals(joint)
                # Verify B/C full-support distributions from the persisted raw scores.
                for target in ("B", "C"):
                    fixture_joint = tc.top3_set_joint(
                        bs[pos],
                        ws[pos],
                        bc.metadata["temperature_by_target_and_venue"][target]["SEOUL"],
                        win.metadata["temperature_by_venue"].get("SEOUL", 1.0),
                    )
                    if max(tc.probability_invariants(fixture_joint).values()) > 1e-10:
                        raise ValueError("B/C probability invariants failed")
            else:
                part = part.sort_values("horse_id")
                _, orders, _, logjoint, _ = b.distribution(
                    part.rank_score.to_numpy(), part.order_score.to_numpy(), beta, beta_order
                )
                probs = b.jeju_marginals(orders, logjoint, len(part))
            ranks = np.argsort(np.argsort(-probs[2], kind="stable"), kind="stable") + 1
            for k, (index, r) in enumerate(part.iterrows()):
                race_no = (
                    int(r.race_no) if domain == "thoroughbred" else int(rid) - int(a.date) * 100
                )
                horse_id = str(r.hr_no if domain == "thoroughbred" else r.horse_id).zfill(7)
                entry = lookup[(race_no, horse_id)]
                number = int(r.chul_no if domain == "thoroughbred" else r.horse_number)
                if (
                    number != int(entry.horse_number)
                    or abs(
                        float(r.burden_weight_kg if domain == "thoroughbred" else r.burden_kg)
                        - float(entry.carried_weight_kg)
                    )
                    > 1e-8
                ):
                    raise ValueError("DB/card number or burden mismatch")
                if domain == "thoroughbred":
                    for col in ("jockey", "trainer", "owner"):
                        if str(r[col + "_no"]).zfill(6) != str(
                            getattr(entry, col + "_identifier")
                        ).zfill(6):
                            raise ValueError("DB/card people identity mismatch")
                row = {
                    "race_id": int(entry.db_race_id),
                    "race_entry_id": int(entry.race_entry_id),
                    "horse_number": number,
                    "race_date": day,
                    "venue_code": entry.venue_code,
                    "race_no": race_no,
                    "hr_no": horse_id,
                    "horse_name": entry.horse_name,
                    "prob_win": float(probs[0][k]),
                    "prob_top2": float(probs[1][k]),
                    "prob_top3": float(probs[2][k]),
                    "a_rank_in_race": int(ranks[k]),
                    "field_size": len(part),
                    "starter_status": "starter",
                    "runner_identifier": horse_id,
                    "jockey_identifier": str(entry.jockey_identifier).zfill(6),
                    "trainer_identifier": str(entry.trainer_identifier).zfill(6),
                    "owner_identifier": str(entry.owner_identifier).zfill(6),
                    "cancellation_status": None,
                    "body_weight_kg": None,
                    "body_weight_change_kg": None,
                    "data_quality_flags_json": json.dumps(
                        ["frozen_history_through_" + cutoff, "same_day_fields_unavailable"]
                    ),
                }
                if domain == "thoroughbred":
                    row.update(
                        raw_a_top3_score=float(aas[index]),
                        raw_bc_top3_score=float(bs[index]),
                        raw_win_score=float(ws[index]),
                    )
                    explanation = b.select_contributions(
                        race_entry_id=entry.race_entry_id,
                        names=names,
                        values=contrib[index, :-1],
                        source=r.to_dict(),
                        source_cutoff_at_ms=source_ms,
                        component="A",
                        method="lightgbm_pred_contrib_raw_a_score",
                    )
                else:
                    row.update(
                        raw_rank_score=float(r.rank_score),
                        raw_order_score=float(r.order_score),
                        beta_set=beta,
                        beta_order=beta_order,
                    )
                    reason = docs[int(r.entry_id)]
                    selected = reason["positive_reasons"] + reason["negative_reasons"]
                    explanation = b.select_contributions(
                        race_entry_id=entry.race_entry_id,
                        names=[v["feature"] for v in selected],
                        values=np.asarray([v["contribution"] for v in selected]),
                        source={v["feature"]: v.get("raw_value") for v in selected},
                        source_cutoff_at_ms=source_ms,
                        component="A_B_C",
                        method="lightgbm_pred_contrib_raw_rank_score",
                        supplied_labels={v["feature"]: v["label"] for v in selected},
                    )
                rows.append(row)
                explanations.extend(explanation)
        predictions = pd.DataFrame(rows)
        if set(predictions.race_entry_id) != set(stored.race_entry_id) or len(predictions) != len(
            stored
        ):
            raise ValueError("Incomplete eligible card")
        b.check_probability_contract(predictions)
        metadata = {
            "schema_version": 1,
            "domain": domain,
            "prediction_stage": "initial_card",
            "experiment_run_id": str(uuid.uuid4()),
            "model_type": "registered_main_prediction",
            "dataset_version": str(a.output.relative_to(ROOT)),
            "as_of_policy": "start_minus_30m",
            "feature_hash": feature_hash,
            "model_artifact_sha256": model_hash,
            "registry_sha256": registry_hash,
            "input_card_sha256": card_hash,
            "source_card_at_ms": source_ms,
            "history_cutoff_date": cutoff,
            "feature_cutoff_at_ms": source_ms,
            "data_availability_status": "partial",
            "probability_contract": profile["probability_contract"],
            "combination_algorithm_version": profile["combination_algorithm_version"],
            "parent_public_id": None,
            "components": components,
            "notes": (
                f"{day} 현재 공식 출마표 기반 운영 모델 발행. 과거 경주 이력 {cutoff}까지. "
                "최근 이력 공백과 당일 체중·주로·날씨 미반영은 partial로 명시. "
                "기존 운영 모델·보정값 유지. frozen context/v4 재현 검증 통과."
            ),
        }
        dest = a.output / domain
        b.write_bundle(dest, predictions, explanations, metadata)
        summary.append(
            {
                "domain": domain,
                "races": int(predictions.race_id.nunique()),
                "runners": len(predictions),
                "explanations": len(explanations),
                "history_cutoff": cutoff,
                "bundle": str(dest),
            }
        )
    (a.output / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
