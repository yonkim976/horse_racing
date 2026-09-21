"""Build per-race, append-only Jeju HY_R_FORM update bundles from fresh inference.

Fail closed for scratched races: the reference inference computed relative features
with every declared runner, so dropping a scratched horse after inference would be
an invalid shortcut.  This adapter handles jockey/card changes only when the
complete active field is unchanged.
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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = (
    ROOT
    / ".agents/skills/horse-racing-prediction-publisher/scripts"
    / "build_20260919_publication_bundles.py"
)
KST = ZoneInfo("Asia/Seoul")


def _load_builder():
    spec = importlib.util.spec_from_file_location("frozen_publication_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("기존 publication builder를 읽지 못했습니다")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _database_url(project_ref: str, secret: str, gcp_project: str) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sync_live_race_day import _database_url as load_url

    return load_url(project_ref, secret, gcp_project)


def _query_rows(connection, sql: str, **params) -> list[dict]:
    return [dict(row) for row in connection.execute(text(sql), params).mappings()]


def _db_entries(connection, race_date: str) -> list[dict]:
    return _query_rows(
        connection,
        """
        select r.id race_id, r.race_number, r.scheduled_at_ms, r.status race_status,
               e.id race_entry_id, e.horse_number, e.scratched,
               e.carried_weight_kg, h.kra_horse_id horse_id,
               j.kra_jockey_id jockey_id, t.kra_trainer_id trainer_id,
               o.kra_owner_id owner_id
          from races r
          join racecourses rc on rc.id=r.racecourse_id
          join race_entries e on e.race_id=r.id
          join horses h on h.id=e.horse_id
          left join jockeys j on j.id=e.jockey_id
          left join trainers t on t.id=e.trainer_id
          left join owners o on o.id=e.owner_id
         where r.race_date_local=cast(:race_date as date) and rc.kra_meet_code=2
         order by r.race_number,e.horse_number
        """,
        race_date=race_date,
    )


def _published_card(connection, race_id: int) -> tuple[dict | None, list[dict]]:
    runs = _query_rows(
        connection,
        """
        select pr.id,pr.public_id,pr.prediction_stage,pr.input_card_sha256,
               pr.published_at_ms,pr.parent_prediction_run_id,pr.dataset_version
          from prediction_runs pr
          join model_predictions mp on mp.prediction_run_id=pr.id
         where mp.race_id=:race_id and pr.publication_mode='live' and pr.domain='jeju'
         group by pr.id
         order by pr.published_at_ms desc,pr.id desc limit 1
        """,
        race_id=race_id,
    )
    if not runs:
        return None, []
    latest = runs[0]
    entries = _query_rows(
        connection,
        """
        select mp.race_entry_id,mp.horse_number,mp.runner_identifier,
               mp.jockey_identifier,mp.prob_top3
          from model_predictions mp
         where mp.prediction_run_id=:run_id and mp.race_id=:race_id
         order by mp.horse_number
        """,
        run_id=latest["id"],
        race_id=race_id,
    )
    return latest, entries


def _initial_parent(connection, race_id: int) -> str | None:
    rows = _query_rows(
        connection,
        """
        select pr.public_id from prediction_runs pr
        join model_predictions mp on mp.prediction_run_id=pr.id
        where mp.race_id=:race_id and pr.domain='jeju'
          and pr.publication_mode='live' and pr.prediction_stage='initial_card'
        order by pr.id limit 1
        """,
        race_id=race_id,
    )
    return str(rows[0]["public_id"]) if rows else None


def _card_has_changed(db_entries: list[dict], published_entries: list[dict]) -> bool:
    current = {
        (
            int(row["race_entry_id"]),
            int(row["horse_number"]),
            str(row["horse_id"]).zfill(7),
            str(row["jockey_id"]).zfill(6),
        )
        for row in db_entries
        if not row["scratched"]
    }
    previous = {
        (
            int(row["race_entry_id"]),
            int(row["horse_number"]),
            str(row["runner_identifier"]).zfill(7),
            str(row["jockey_identifier"]).zfill(6),
        )
        for row in published_entries
    }
    return current != previous


def _restores_missing_supplemental_inputs(latest: dict, metadata: dict) -> bool:
    """Only allow a same-card correction of a prior run that omitted frozen H2 data."""
    current_inputs = metadata.get("official_supplemental_inputs")
    if not current_inputs or not metadata.get("h2_changed_horses"):
        return False
    previous_name = str(latest.get("dataset_version") or "")
    if not previous_name or Path(previous_name).name != previous_name:
        return False
    previous_metadata_path = ROOT / "data/predictions" / previous_name / "metadata.json"
    if not previous_metadata_path.is_file():
        return False
    previous_metadata = json.loads(previous_metadata_path.read_text(encoding="utf-8"))
    return (
        previous_metadata.get("official_supplemental_inputs") is None
        and previous_metadata.get("target_date") == metadata.get("target_date")
        and previous_metadata.get("model_sha256") == metadata.get("model_sha256")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--gcp-secret", required=True)
    parser.add_argument("--gcp-project", required=True)
    args = parser.parse_args()
    builder = _load_builder()
    inference = args.inference_dir.resolve()
    metadata = json.loads((inference / "metadata.json").read_text(encoding="utf-8"))
    race_date = str(metadata["target_date"])
    if metadata["model"] != "HY_R_FORM" or metadata["meet"] != 2:
        raise ValueError("제주 HY_R_FORM 예측 출력만 허용합니다")
    if metadata["target_result_endpoints_called"] or metadata["same_day_weight_used"]:
        raise ValueError("사후 또는 당일 체중 입력이 혼입됐습니다")
    if builder.sha256_file(builder.JEJU_MODEL) != metadata["model_sha256"]:
        raise ValueError("활성 제주 모델 해시가 맞지 않습니다")
    registry, registry_hash = builder.read_registry()
    profile = builder.profile_for(registry, "jeju")
    model_artifact = builder.artifact(profile, "HY_R_FORM_model")
    if model_artifact["sha256"] != metadata["model_sha256"]:
        raise ValueError("예측 모델이 활성 registry 모델과 다릅니다")

    scores = pd.read_parquet(inference / "model_scores.parquet")
    explanations_doc = json.loads(
        (inference / "horse_explanations.json").read_text(encoding="utf-8")
    )
    explanation_by_entry = {int(item["entry_id"]): item for item in explanations_doc}
    official = []
    for page in metadata["source_pages"]:
        path = inference / page["raw_file"]
        if builder.sha256_file(path) != page["raw_sha256"]:
            raise ValueError("공식 출마표 원본 해시가 다릅니다")
        doc = json.loads(path.read_text(encoding="utf-8"))
        official.extend(doc["response"]["body"]["items"]["item"])
    official_by_key = {(int(row["rcNo"]), int(row["chulNo"])): row for row in official}
    source_card_at_ms = max(int(page["retrieved_at_ms"]) for page in metadata["source_pages"])
    feature_hash = builder.sha256_file(inference / "live_features.parquet")
    with builder.JEJU_MODEL.open("rb") as handle:
        model = pickle.load(handle)  # noqa: S301 - registry-verified local artifact
    beta_set = float(model["rank_bundle"]["beta"])
    beta_order = float(model["beta_order"])
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)

    url = _database_url(args.project_ref, args.gcp_secret, args.gcp_project)
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    built: list[dict] = []
    skipped: list[dict] = []
    now_ms = int(datetime.now(KST).timestamp() * 1000)
    with engine.connect() as connection:
        db_entries = _db_entries(connection, race_date)
        by_race: dict[int, list[dict]] = {}
        for entry in db_entries:
            by_race.setdefault(int(entry["race_number"]), []).append(entry)
        for race_no, part in scores.groupby("race_id", sort=True):
            number = int(race_no) - int(race_date.replace("-", "")) * 100
            db_part = by_race.get(number, [])
            reason = None
            if not db_part:
                reason = "DB 경주 없음"
            elif any(row["scratched"] for row in db_part):
                reason = "취소마 있음: 입력 상대 특징 재계산 미지원"
            elif db_part[0]["race_status"] == "completed":
                reason = "경주 완료"
            elif not db_part[0]["scheduled_at_ms"]:
                reason = "출발 시각 없음"
            elif (
                max(now_ms, source_card_at_ms) > int(db_part[0]["scheduled_at_ms"]) - 30 * 60 * 1000
            ):
                reason = "출발 30분 전 마감 지남"
            if reason:
                skipped.append({"race_no": number, "reason": reason})
                continue
            db_lookup = {int(row["horse_number"]): row for row in db_part}
            if len(part) != len(db_part) or set(part.horse_number.astype(int)) != set(db_lookup):
                skipped.append({"race_no": number, "reason": "공식 카드와 DB 편성 불일치"})
                continue
            for item in part.itertuples():
                key = (number, int(item.horse_number))
                card = official_by_key.get(key)
                stored = db_lookup[int(item.horse_number)]
                if card is None or str(item.horse_id).zfill(7) != str(stored["horse_id"]).zfill(7):
                    raise ValueError(f"제주 {number}경주 {item.horse_number}번 말 ID 불일치")
                if str(card.get("jkNo") or "").zfill(6) != str(stored["jockey_id"]).zfill(6):
                    raise ValueError(f"제주 {number}경주 {item.horse_number}번 기수 불일치")
            race_id = int(db_part[0]["race_id"])
            latest, published = _published_card(connection, race_id)
            parent_public_id = _initial_parent(connection, race_id)
            if latest is None or parent_public_id is None:
                skipped.append({"race_no": number, "reason": "초기 live 예측 없음"})
                continue
            card_changed = _card_has_changed(db_part, published)
            supplemental_correction = (
                not card_changed
                and _restores_missing_supplemental_inputs(latest, metadata)
            )
            if not card_changed and not supplemental_correction:
                skipped.append({"race_no": number, "reason": "카드 변경 없음"})
                continue

            part = part.sort_values("horse_id").reset_index(drop=True)
            sets, orders, log_sets, log_joint, _ = builder.distribution(
                part.rank_score.to_numpy(), part.order_score.to_numpy(), beta_set, beta_order
            )
            win, top2, top3 = builder.jeju_marginals(orders, log_joint, len(part))
            ranks = np.argsort(np.argsort(-top3, kind="stable"), kind="stable") + 1
            rows: list[dict] = []
            explanations: list[dict] = []
            for index, item in part.iterrows():
                stored = db_lookup[int(item.horse_number)]
                card = official_by_key[(number, int(item.horse_number))]
                horse_id = str(item.horse_id).zfill(7)
                rows.append(
                    {
                        "race_id": race_id,
                        "race_entry_id": int(stored["race_entry_id"]),
                        "horse_number": int(item.horse_number),
                        "race_date": race_date,
                        "venue_code": "JEJU",
                        "race_no": number,
                        "hr_no": horse_id,
                        "horse_name": str(item.horse_name),
                        "prob_win": float(win[index]),
                        "prob_top2": float(top2[index]),
                        "prob_top3": float(top3[index]),
                        "a_rank_in_race": int(ranks[index]),
                        "field_size": len(part),
                        "raw_rank_score": float(item.rank_score),
                        "raw_order_score": float(item.order_score),
                        "beta_set": beta_set,
                        "beta_order": beta_order,
                        "starter_status": "starter",
                        "runner_identifier": horse_id,
                        "jockey_identifier": str(card["jkNo"]).zfill(6),
                        "trainer_identifier": str(card.get("trNo") or stored["trainer_id"]).zfill(
                            6
                        ),
                        "owner_identifier": str(card.get("owNo") or stored["owner_id"]).zfill(6),
                        "cancellation_status": None,
                        "body_weight_kg": None,
                        "body_weight_change_kg": None,
                        "data_quality_flags_json": "[]",
                    }
                )
                explanation = explanation_by_entry[int(item.entry_id)]
                selected = explanation["positive_reasons"][:3] + explanation["negative_reasons"][:3]
                labels = {value["feature"]: value["label"] for value in selected}
                explanations.extend(
                    builder.select_contributions(
                        race_entry_id=int(stored["race_entry_id"]),
                        names=[value["feature"] for value in selected],
                        values=np.asarray(
                            [value["contribution"] for value in selected], dtype=float
                        ),
                        source={value["feature"]: value.get("raw_value") for value in selected},
                        source_cutoff_at_ms=source_card_at_ms,
                        component="A_B_C",
                        method="lightgbm_pred_contrib_raw_rank_score",
                        supplied_labels=labels,
                    )
                )
            predictions = pd.DataFrame(rows)
            builder.check_probability_contract(predictions)
            if supplemental_correction:
                previous_probabilities = {
                    int(row["horse_number"]): float(row["prob_top3"]) for row in published
                }
                if not any(
                    abs(float(row["prob_top3"]) - previous_probabilities[int(row["horse_number"])])
                    > 1e-9
                    for row in rows
                ):
                    skipped.append({"race_no": number, "reason": "보조 입력 복원 후 확률 동일"})
                    continue
            card_hash = builder.sha256_json(
                {
                    "race_date": race_date,
                    "race_no": number,
                    "official_page_sha256": [
                        page["raw_sha256"] for page in metadata["source_pages"]
                    ],
                    "entries": [
                        {
                            "horse_number": int(row["horse_number"]),
                            "horse_id": str(row["horse_id"]).zfill(7),
                            "jockey_id": str(row["jockey_id"]).zfill(6),
                            "burden": float(row["carried_weight_kg"])
                            if row["carried_weight_kg"] is not None
                            else None,
                        }
                        for row in db_part
                    ],
                }
            )
            bundle_metadata = {
                "schema_version": 1,
                "domain": "jeju",
                "prediction_stage": "pre_race_update",
                "experiment_run_id": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"horse-racing:jeju:{race_date}:{number}:{card_hash}:{feature_hash}",
                    )
                ),
                "model_type": "registered_main_prediction",
                "dataset_version": inference.name,
                "as_of_policy": "start_minus_30m",
                "feature_hash": feature_hash,
                "model_artifact_sha256": model_artifact["sha256"],
                "registry_sha256": registry_hash,
                "input_card_sha256": card_hash,
                "source_card_at_ms": source_card_at_ms,
                "history_cutoff_date": str(metadata["history_last_date"]),
                "feature_cutoff_at_ms": source_card_at_ms,
                "data_availability_status": "partial",
                "probability_contract": profile["probability_contract"],
                "combination_algorithm_version": profile["combination_algorithm_version"],
                "parent_public_id": parent_public_id,
                "components": [
                    {
                        "component": "A_B_C",
                        "model_version": profile["components"]["A_B_C"]["model_version"],
                        "candidate_name": profile["components"]["A_B_C"]["candidate"],
                        "artifact_sha256": model_artifact["sha256"],
                        "metadata_sha256": None,
                        "algorithm_version": profile["combination_algorithm_version"],
                        "parameters": {
                            "beta_set": beta_set,
                            "beta_order": beta_order,
                            "set_score": "rank_score",
                            "order_score": "order_score",
                        },
                    }
                ],
                "notes": (
                    (
                        "공식 보조 입력 누락을 복원한 제주 HY_R_FORM 재예측. "
                        if supplemental_correction else
                        "공식 기수 변경에 따른 제주 HY_R_FORM 재예측. "
                    )
                    + "취소마 경주는 제외. 당일 마체중·주로·배당·결과 미사용."
                ),
            }
            bundle_dir = output_root / f"jeju_race_{number:02d}"
            builder.write_bundle(bundle_dir, predictions, explanations, bundle_metadata)
            built.append(
                {"race_no": number, "runners": len(predictions), "bundle": str(bundle_dir)}
            )
    engine.dispose()
    print(json.dumps({"built": built, "skipped": skipped}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
