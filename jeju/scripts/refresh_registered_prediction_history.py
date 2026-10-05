"""Refresh HY_R_FORM race history without changing its frozen T-2 contract.

Read-only production snapshot; append missing races to private input copies.
The registered reference builds every feature and scores the active field again.
This command prepares bundles only. The repository publisher handles DB writes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sync_live_race_day import _database_url  # noqa: E402

from horse_racing.analysis.jeju_native_top3_states import build_states  # noqa: E402

KST = ZoneInfo("Asia/Seoul")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target(row):
    return {
        "entry_id": 100000000 + row["race_entry_id"],
        "race_id": 100000000 + row["db_race_id"],
        "horse_id": str(row["horse_id"]).zfill(7),
        "event_date": row["event_date"],
        "distance_m": row["distance_m"],
        "field_size": row["field_size"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    day = datetime.strptime(args.date, "%Y%m%d").date()
    high = day - timedelta(days=2)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    ref = load_module("registered_reference", ROOT / "scripts/predict_jeju_live_hy_r_form.py")
    b = load_module(
        "publication_builder",
        ROOT
        / ".agents/skills/horse-racing-prediction-publisher/scripts"
        / "build_20260919_publication_bundles.py",
    )
    registry, registry_hash = b.read_registry()
    profile = b.profile_for(registry, "jeju")
    artifact = b.artifact(profile, "HY_R_FORM_model")
    if ref.sha256(ref.MODEL) != artifact["sha256"]:
        raise ValueError("Registered model hash differs")
    history = pl.read_parquet(ref.DATA / "history_results.parquet")
    old_last = history["event_date"].max()
    engine = create_engine(
        _database_url("xkykmhhkjtosptoibduo", "horse-racing-database-url", "mapilog-509017"),
        pool_size=1,
        max_overflow=0,
    )
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        recent = [
            dict(r)
            for r in conn.execute(
                text("""
          select e.id race_entry_id,r.id db_race_id,r.race_date_local event_date,
                 r.race_number,e.horse_number,h.kra_horse_id horse_id,r.distance_m,
                 (count(*) filter (where rr.finish_position between 1 and 89
                   or rr.finish_position in (91,92)) over (partition by r.id))::int field_size,
                 rr.finish_position,rr.finish_time_ms,rr.disqualified,
                 e.carried_weight_kg burden_kg,e.body_weight_kg,
                 r.weather,r.track_moisture_percent,
                 j.name_ko jockey_name,j.kra_jockey_id jockey_id,
                 t.name_ko trainer_name,t.kra_trainer_id trainer_id
          from race_results rr join race_entries e on e.id=rr.race_entry_id
          join races r on r.id=e.race_id join horses h on h.id=e.horse_id
          left join jockeys j on j.id=e.jockey_id left join trainers t on t.id=e.trainer_id
          where r.racecourse_id=2 and r.race_date_local>:low and r.race_date_local<=:high
          order by r.race_date_local,r.race_number,e.horse_number
        """),
                {"low": old_last, "high": high},
            ).mappings()
        ]
        current = [
            dict(r)
            for r in conn.execute(
                text("""
          select e.id race_entry_id,r.id race_id,r.race_number,r.scheduled_at_ms,r.status,
                 e.horse_number,e.scratched,h.kra_horse_id horse_id,
                 j.kra_jockey_id jockey_id,t.kra_trainer_id trainer_id,o.kra_owner_id owner_id,
                 e.carried_weight_kg
          from races r join race_entries e on e.race_id=r.id join horses h on h.id=e.horse_id
          left join jockeys j on j.id=e.jockey_id left join trainers t on t.id=e.trainer_id
          left join owners o on o.id=e.owner_id
          where r.racecourse_id=2 and r.race_date_local=:day
          order by r.race_number,e.horse_number
        """),
                {"day": day},
            ).mappings()
        ]
        parent = conn.execute(
            text(
                "select public_id from prediction_runs where id=12 and domain='jeju' "
                "and prediction_stage='initial_card' and race_date_local=:day"
            ),
            {"day": day},
        ).scalar_one()
    engine.dispose()
    if not recent:
        raise ValueError("No new eligible history")
    ref.write_json(
        out / "production_snapshot.json", {"recent_results": recent, "current_entries": current}
    )
    with sqlite3.connect(
        f"file:{ROOT / 'jeju/data/jeju_native_core.sqlite3'}?mode=ro", uri=True
    ) as local:
        local.row_factory = sqlite3.Row
        reviewed = [
            dict(r)
            for r in local.execute(
                """
          select race_date,race_number,horse_id,finish_position,finish_time_seconds,
                 s1f_time_seconds,g1f_time_seconds,g3f_time_seconds,s1f_order,g1f_order
          from jeju_race_postrace_sections_quality_2026
          where race_date>? and race_date<=?
        """,
                (old_last.isoformat(), high.isoformat()),
            )
        ]
    section_map = {
        (r["race_date"].replace("-", ""), r["race_number"], r["horse_id"]): r for r in reviewed
    }
    ref.write_json(out / "reviewed_section_snapshot.json", reviewed)
    for row in recent:
        section = section_map.get(
            (
                row["event_date"].strftime("%Y%m%d"),
                row["race_number"],
                str(row["horse_id"]).zfill(7),
            )
        )
        if section is None:
            raise ValueError("New result lacks reviewed local section source")
        if section["finish_position"] != row["finish_position"]:
            raise ValueError("Local/production result rank differs")
        if row["finish_time_ms"] and section["finish_time_seconds"]:
            if abs(row["finish_time_ms"] - round(section["finish_time_seconds"] * 1000)) > 1:
                raise ValueError("Local/production result time differs")
        row["reviewed_sections"] = section
    extra = []
    for row in recent:
        pos = row["finish_position"]
        normal = pos is not None and 1 <= pos <= row["field_size"] and not row["disqualified"]
        extra.append(
            {
                **target(row),
                "finish_position": pos,
                "finish_time_ms": row["finish_time_ms"],
                "segment_quality": "usable"
                if normal and row["finish_time_ms"] and row["finish_time_ms"] > 0
                else "unusable",
                "outcome_status": "normal_completed" if normal else "non_normal",
                "horse_number": row["horse_number"],
                "event_number": row["race_number"],
                "section_s1f_ms": round(row["reviewed_sections"]["s1f_time_seconds"] * 1000)
                if row["reviewed_sections"]["s1f_time_seconds"]
                else None,
                "section_g1f_ms": round(row["reviewed_sections"]["g1f_time_seconds"] * 1000)
                if row["reviewed_sections"]["g1f_time_seconds"]
                else None,
                "section_g3f_ms": round(row["reviewed_sections"]["g3f_time_seconds"] * 1000)
                if row["reviewed_sections"]["g3f_time_seconds"]
                else None,
            }
        )
    if len({(r["event_date"], r["race_id"], r["horse_id"]) for r in extra}) != len(extra):
        raise ValueError("Duplicate history identity")
    new_history = pl.concat(
        [history, pl.DataFrame(extra, infer_schema_length=None)], how="diagonal_relaxed"
    )
    assert new_history["event_date"].max() <= high
    inputs = out / "inputs"
    inputs.mkdir()
    new_history.write_parquet(inputs / "history_results.parquet")
    # Use the same registered state code to obtain pre-event Elo for new context rows.
    pre, _ = build_states(ref.RESEARCH_DB, pl.DataFrame([target(r) for r in recent]), new_history)
    premap = {r["entry_id"]: r for r in pre.to_dicts()}
    context_extra = []
    for row in recent:
        if row["finish_position"] is None or row["finish_position"] not in (*range(1, 90), 91, 92):
            continue
        key = target(row)
        state = premap[key["entry_id"]]
        normal = 1 <= row["finish_position"] <= row["field_size"] and not row["disqualified"]
        same = [r for r in recent if r["db_race_id"] == row["db_race_id"]]
        times = [
            r["finish_time_ms"]
            for r in same
            if r["finish_time_ms"]
            and r["finish_position"]
            and 1 <= r["finish_position"] <= r["field_size"]
            and not r["disqualified"]
        ]
        rivals = [
            premap[target(r)["entry_id"]]["global_elo_pre"]
            for r in same
            if r["race_entry_id"] != row["race_entry_id"]
        ]
        context_extra.append(
            {
                **key,
                "horse_number": row["horse_number"],
                "global_elo_pre": state["global_elo_pre"],
                "distance_elo_pre": state["distance_elo_pre"],
                "jockey_name": row["jockey_name"],
                "jockey_id": str(row["jockey_id"]).zfill(6) if row["jockey_id"] else None,
                "burden_kg": row["burden_kg"],
                "body_weight_kg": float(row["body_weight_kg"]) if row["body_weight_kg"] else None,
                "finish_position": row["finish_position"] if normal else None,
                "finish_time_ms": row["finish_time_ms"] if normal else None,
                "outcome_status": "normal_completed" if normal else "non_normal",
                "weather": row["weather"],
                "track_moisture_percent": row["track_moisture_percent"],
                "time_minus_race_median_ms": float(row["finish_time_ms"] - np.median(times))
                if normal and row["finish_time_ms"] and len(times) >= 2
                else None,
                "rival_elo_mean": float(np.mean(rivals)) if rivals else None,
                "early_rank": row["reviewed_sections"]["s1f_order"],
                "late_rank": row["reviewed_sections"]["g1f_order"],
                "g1f_seconds": row["reviewed_sections"]["g1f_time_seconds"] if normal else None,
                "closing_speed_quality": None,
            }
        )
    context_df = pd.DataFrame(context_extra)
    valid = (
        context_df.g1f_seconds.notna()
        & context_df.finish_position.between(1, context_df.field_size)
        & (context_df.g1f_seconds > 0)
        & (context_df.g1f_seconds < context_df.finish_time_ms / 1000)
    )
    for _, group in context_df[valid].groupby("race_id"):
        if len(group) >= 2:
            ranks = group.g1f_seconds.rank(method="average", ascending=True)
            context_df.loc[group.index, "closing_speed_quality"] = 1 - (ranks - 1) / (
                len(group) - 1
            )
    context_extra = context_df.to_dict("records")
    original_context = pl.read_parquet(ref.TRANSITION / "context_history.parquet")
    pl.concat(
        [original_context, pl.DataFrame(context_extra, infer_schema_length=None)],
        how="diagonal_relaxed",
    ).write_parquet(inputs / "context_history.parquet")
    people = ref.people_history()
    people.extend(
        {
            "event_date": r["event_date"],
            "horse_id": str(r["horse_id"]).zfill(7),
            "jockey_name": r["jockey_name"],
            "jockey_id": str(r["jockey_id"]).zfill(6) if r["jockey_id"] else None,
            "trainer_name": r["trainer_name"],
            "trainer_id": str(r["trainer_id"]).zfill(6) if r["trainer_id"] else None,
            "win": int(r["finish_position"] == 1),
            "top3": int(r["finish_position"] is not None and 1 <= r["finish_position"] <= 3),
        }
        for r in recent
        if r["finish_position"] is not None and r["finish_position"] in (*range(1, 90), 91, 92)
    )
    now = int(datetime.now(KST).timestamp() * 1000)
    eligible = {
        r["race_number"]
        for r in current
        if r["status"] != "completed"
        and r["scheduled_at_ms"]
        and now < r["scheduled_at_ms"] - 1800000
    }
    active = {
        (r["race_number"], r["horse_number"]): r
        for r in current
        if r["race_number"] in eligible and not r["scratched"]
    }
    if not active:
        raise ValueError("No races before publication deadline")
    actual_fetch = ref.fetch_cards

    def active_cards(race_date, output):
        items, pages = actual_fetch(race_date, output)
        selected = [i for i in items if (i.race_number, i.horse_number) in active]
        if {(i.race_number, i.horse_number) for i in selected} != set(active):
            raise ValueError("Official card missing active runners")
        for i in selected:
            r = active[(i.race_number, i.horse_number)]
            if (
                str(i.horse_id).zfill(7) != str(r["horse_id"]).zfill(7)
                or str(i.jockey_id).zfill(6) != str(r["jockey_id"]).zfill(6)
                or i.carried_weight_kg != r["carried_weight_kg"]
            ):
                raise ValueError("Official card differs from production snapshot")
        return selected, pages

    ref.DATA = inputs
    ref.TRANSITION = inputs
    ref.people_history = lambda: people
    ref.fetch_cards = active_cards
    infer = out / "inference"
    sys.argv = ["registered_reference", "--date", args.date, "--output", str(infer)]
    ref.main()
    meta = json.loads((infer / "metadata.json").read_text())
    meta["history_last_date"] = str(new_history["event_date"].max())
    meta["history_eligibility_cutoff"] = str(high)
    meta["limitations"] = [
        "frozen H2 training, medical, trial and measured-weight sources retained",
        "reviewed local sections used with unresolved values kept null",
        "same-day inputs unused",
    ]
    ref.write_json(infer / "metadata.json", meta)
    scored = pd.read_parquet(infer / "model_scores.parquet")
    docs = {
        int(r["entry_id"]): r for r in json.loads((infer / "horse_explanations.json").read_text())
    }
    with ref.MODEL.open("rb") as handle:
        model = pickle.load(handle)  # Registry hash verified above.
    bs, bo = float(model["rank_bundle"]["beta"]), float(model["beta_order"])
    source_ms = max(p["retrieved_at_ms"] for p in meta["source_pages"])
    built = []
    for rid, part in scored.groupby("race_id", sort=True):
        rn = int(rid) - int(args.date) * 100
        part = part.sort_values("horse_id").reset_index(drop=True)
        _, orders, _, lj, _ = b.distribution(
            part.rank_score.to_numpy(), part.order_score.to_numpy(), bs, bo
        )
        win, top2, top3 = b.jeju_marginals(orders, lj, len(part))
        ranks = np.argsort(np.argsort(-top3, kind="stable"), kind="stable") + 1
        rows = []
        explanations = []
        for k, r in part.iterrows():
            db = active[(rn, int(r.horse_number))]
            rows.append(
                dict(
                    race_id=db["race_id"],
                    race_entry_id=db["race_entry_id"],
                    horse_number=int(r.horse_number),
                    race_date=day.isoformat(),
                    venue_code="JEJU",
                    race_no=rn,
                    hr_no=str(r.horse_id),
                    horse_name=r.horse_name,
                    prob_win=float(win[k]),
                    prob_top2=float(top2[k]),
                    prob_top3=float(top3[k]),
                    a_rank_in_race=int(ranks[k]),
                    field_size=len(part),
                    raw_rank_score=float(r.rank_score),
                    raw_order_score=float(r.order_score),
                    beta_set=bs,
                    beta_order=bo,
                    starter_status="starter",
                    runner_identifier=str(r.horse_id),
                    jockey_identifier=str(db["jockey_id"]).zfill(6),
                    trainer_identifier=str(db["trainer_id"]).zfill(6),
                    owner_identifier=str(db["owner_id"]).zfill(6),
                    cancellation_status=None,
                    body_weight_kg=None,
                    body_weight_change_kg=None,
                    data_quality_flags_json=json.dumps(meta["limitations"]),
                )
            )
            doc = docs[int(r.entry_id)]
            selected = doc["positive_reasons"][:3] + doc["negative_reasons"][:3]
            explanations.extend(
                b.select_contributions(
                    race_entry_id=db["race_entry_id"],
                    names=[v["feature"] for v in selected],
                    values=np.array([v["contribution"] for v in selected]),
                    source={v["feature"]: v.get("raw_value") for v in selected},
                    source_cutoff_at_ms=source_ms,
                    component="A_B_C",
                    method="lightgbm_pred_contrib_raw_rank_score",
                    supplied_labels={v["feature"]: v["label"] for v in selected},
                )
            )
        preds = pd.DataFrame(rows)
        b.check_probability_contract(preds)
        feature_hash = b.sha256_file(infer / "live_features.parquet")
        metadata = dict(
            schema_version=1,
            domain="jeju",
            prediction_stage="pre_race_update",
            experiment_run_id=str(uuid.uuid4()),
            model_type="registered_main_prediction",
            dataset_version=str(out.relative_to(ROOT)),
            as_of_policy="start_minus_30m",
            feature_hash=feature_hash,
            model_artifact_sha256=artifact["sha256"],
            registry_sha256=registry_hash,
            input_card_sha256=b.sha256_json(
                {
                    "official_pages": meta["source_pages"],
                    "active_entries": [v for key, v in active.items() if key[0] == rn],
                }
            ),
            source_card_at_ms=source_ms,
            history_cutoff_date=meta["history_last_date"],
            feature_cutoff_at_ms=source_ms,
            data_availability_status="partial",
            probability_contract=profile["probability_contract"],
            combination_algorithm_version=profile["combination_algorithm_version"],
            parent_public_id=str(parent),
            components=[
                dict(
                    component="A_B_C",
                    model_version=profile["components"]["A_B_C"]["model_version"],
                    candidate_name="HY_R_FORM",
                    artifact_sha256=artifact["sha256"],
                    metadata_sha256=None,
                    algorithm_version=profile["combination_algorithm_version"],
                    parameters=dict(
                        beta_set=bs,
                        beta_order=bo,
                        set_score="rank_score",
                        order_score="order_score",
                    ),
                )
            ],
            notes=(
                f"Race history refreshed through {meta['history_last_date']}, "
                f"preserving T-2 (eligible through {high}). "
                "Active field rebuilt before feature generation. "
                "Reviewed local sections used with unresolved values null. "
                "Frozen H2 retained; same-day inputs unused."
            ),
        )
        bundle = out / "bundles" / f"race_{rn:02d}"
        b.write_bundle(bundle, preds, explanations, metadata)
        built.append({"race_no": rn, "runners": len(preds), "bundle": str(bundle)})
    ref.write_json(
        out / "refresh_summary.json",
        dict(
            old_history_cutoff=str(old_last),
            history_cutoff=meta["history_last_date"],
            eligibility_cutoff=str(high),
            added_results=len(extra),
            added_races=len({r["db_race_id"] for r in recent}),
            built=built,
            limitations=meta["limitations"],
        ),
    )
    print(
        json.dumps(
            {
                "added_results": len(extra),
                "history_last_date": meta["history_last_date"],
                "built": built,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
