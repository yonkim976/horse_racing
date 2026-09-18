#!/usr/bin/env python3
"""Build immutable canonical bundles for the verified 2026-09-19/20 forecasts.

This adapter does not run new training and does not write a database.  It converts
the already verified Thoroughbred A/B/C and Jeju HY_R_FORM outputs into the
publisher's all-runner contract, including joint win/top2/top3 marginals and six
raw-score explanation rows per runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
V2 = REPO_ROOT / "data/research/thoroughbred_win_research_20260918_v2"
V3 = REPO_ROOT / "data/research/thoroughbred_three_targets_20260918_v3"
V4 = REPO_ROOT / "data/research/thoroughbred_followup_20260918_v4"
V5 = REPO_ROOT / "data/research/thoroughbred_offline_20260918_v5"
V6 = REPO_ROOT / "data/research/thoroughbred_boundary_20260918_v6"
JEJU_MODEL = (
    REPO_ROOT
    / "data/research/jeju_native_transition_holdout_v13_20260916/bundles"
    / "frozen_2026__HY_R_FORM.pkl"
)

sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(V6))

import core  # noqa: E402
from horse_racing.analysis.jeju_hybrid_evaluation import distribution  # noqa: E402


THOROUGHBRED_INPUT = V3 / "prediction_input/future_20260919_20_context.parquet"
THOROUGHBRED_V4 = V4 / "model/future_predictions_20260919_20/prepared_v4_features.parquet"
THOROUGHBRED_A = V6 / "future_predictions_20260919_20/A_predictions.parquet"
JEJU_OUTPUT = REPO_ROOT / "data/predictions/jeju_live_20260919_hy_r_form_20260919T035500+0900"
CARD_DIR = REPO_ROOT / "data/predictions/current_cards_20260919T034100+0900/snapshots"
SQLITE_PATH = REPO_ROOT / "data/horse_racing.sqlite3"
REGISTRY_PATH = REPO_ROOT / "config/prediction_model_registry.json"

CARD_FILES = {
    ("2026-09-19", "SEOUL"): CARD_DIR / "20260919_meet1_9ee51f0e87230bf3.json",
    ("2026-09-20", "SEOUL"): CARD_DIR / "20260920_meet1_10bd09a8af1eb215.json",
    ("2026-09-20", "YEONGCHEON"): CARD_DIR / "20260920_meet4_5c7e7e76fd284537.json",
}

READABLE = {
    "burden_weight_kg": "부담중량",
    "hist_days_since_last_race": "최근 출전 간격",
    "research_elo_global": "전체 조건 ELO",
    "research_elo_context": "조건별 ELO",
    "research_elo_vs_field": "편성 대비 ELO",
    "research_context_elo_vs_field": "편성 대비 조건별 ELO",
    "research_speed_vs_field": "편성 대비 보정 스피드",
    "research_speed_last": "직전 보정 스피드",
    "research_speed_avg3": "최근 3회 평균 스피드",
    "research_speed_median5": "최근 5회 중앙 스피드",
    "research_speed_trend": "최근 스피드 추세",
    "research_form_finish_pct_avg3": "최근 3회 상대 성적",
    "research_form_finish_pct_avg5": "최근 5회 상대 성적",
    "research_condition_distance_top3_rate_smoothed": "거리 적성 입상률",
    "research_condition_layoff_log1p": "휴양·출전 주기",
    "research_condition_burden_z5": "최근 부담중량 범위 대비 이번 부담",
    "research_gate_top3_index_distance_3y": "거리별 게이트 지수",
    "research_gate_top3_index_recent_1y": "최근 게이트 지수",
    "research_pace_self_front_advantage": "선행 전개 적합도",
    "research_pace_late_gain_pct_avg5": "추입 전개 적합도",
    "research_v4_finish_pct_slope5": "최근 성적 추세",
    "research_v4_opponent_elo_vs_current_field": "직전 상대 수준 대비 이번 편성",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def combined_file_hash(paths: list[Path]) -> str:
    return sha256_json([{"path": str(path.relative_to(REPO_ROOT)), "sha256": sha256_file(path)} for path in paths])


def json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def epoch_ms(iso_value: str) -> int:
    return int(datetime.fromisoformat(iso_value.replace("Z", "+00:00")).timestamp() * 1000)


def read_registry() -> tuple[dict[str, Any], str]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8")), sha256_file(REGISTRY_PATH)


def profile_for(registry: dict[str, Any], domain: str) -> dict[str, Any]:
    name = registry["domains"][domain]["active_profile"]
    return registry["profiles"][name]


def artifact(profile: dict[str, Any], name: str) -> dict[str, str]:
    item = profile["artifacts"][name]
    path = REPO_ROOT / item["path"]
    actual = sha256_file(path)
    if actual != item["sha256"]:
        raise RuntimeError(f"artifact hash mismatch: {name}")
    return item


def database_entries() -> pd.DataFrame:
    query = """
        SELECT r.id AS db_race_id, e.id AS race_entry_id,
               CAST(r.race_date_local AS TEXT) AS race_date,
               rc.code AS venue_code, r.race_number AS race_no,
               e.horse_number, e.gate_number, e.carried_weight_kg,
               e.body_weight_kg, e.body_weight_change_kg, e.scratched,
               h.kra_horse_id AS runner_identifier, h.name_ko AS db_horse_name,
               j.kra_jockey_id AS db_jockey_identifier,
               t.kra_trainer_id AS db_trainer_identifier,
               o.kra_owner_id AS db_owner_identifier
          FROM races r
          JOIN racecourses rc ON rc.id = r.racecourse_id
          JOIN race_entries e ON e.race_id = r.id
          JOIN horses h ON h.id = e.horse_id
          LEFT JOIN jockeys j ON j.id = e.jockey_id
          LEFT JOIN trainers t ON t.id = e.trainer_id
          LEFT JOIN owners o ON o.id = e.owner_id
         WHERE r.race_date_local IN ('2026-09-19', '2026-09-20')
    """
    uri = f"file:{SQLITE_PATH}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        result = pd.read_sql_query(query, connection)
    result["runner_identifier"] = result["runner_identifier"].astype(str).str.zfill(7)
    return result


def joint_marginals(joint: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    order_probability = np.asarray(joint.order_probability, dtype=float)
    orders = np.asarray(joint.orders, dtype=int)
    count = int(orders.max()) + 1
    win = np.bincount(orders[:, 0], weights=order_probability, minlength=count)
    top2 = np.bincount(orders[:, :2].ravel(), weights=np.repeat(order_probability, 2), minlength=count)
    top3 = np.asarray(joint.inclusion_probability, dtype=float)
    return win, top2, top3


def jeju_marginals(orders: np.ndarray, log_joint: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    probability = np.exp(np.asarray(log_joint, dtype=float))
    probability /= probability.sum()
    win = np.bincount(orders[:, 0], weights=probability, minlength=count)
    top2 = np.bincount(orders[:, :2].ravel(), weights=np.repeat(probability, 2), minlength=count)
    top3 = np.bincount(orders.ravel(), weights=np.repeat(probability, 3), minlength=count)
    return win, top2, top3


def explanation_type(feature_name: str) -> str:
    lowered = feature_name.lower()
    tokens = ("hr_no", "horse_id", "jockey_no", "jockey_id", "trainer_no", "trainer_id", "owner_no", "owner_id")
    return "categorical_model_effect" if any(token in lowered for token in tokens) else "interpretable"


def readable_name(feature_name: str) -> str:
    return READABLE.get(feature_name, feature_name.replace("research_", "").replace("_", " "))


def select_contributions(
    *,
    race_entry_id: int,
    names: list[str],
    values: np.ndarray,
    source: dict[str, Any],
    source_cutoff_at_ms: int,
    component: str,
    method: str,
    supplied_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    pairs = []
    for name, contribution in zip(names, values, strict=True):
        if name == "__bias__":
            continue
        base = name.removesuffix("__missing")
        pairs.append(
            {
                "feature_name": name,
                "readable_feature_name": (
                    supplied_labels.get(name, supplied_labels.get(base, readable_name(base)))
                    if supplied_labels
                    else readable_name(base)
                ) + (" 결측" if name.endswith("__missing") else ""),
                "feature_value": json_value(source.get(base)),
                "contribution_value": float(contribution),
                "explanation_type": explanation_type(name),
            }
        )
    positive = sorted((item for item in pairs if item["contribution_value"] >= 0), key=lambda item: (-item["contribution_value"], item["feature_name"]))[:3]
    negative = sorted((item for item in pairs if item["contribution_value"] <= 0), key=lambda item: (item["contribution_value"], item["feature_name"]))[:3]
    if len(positive) != 3 or len(negative) != 3:
        raise RuntimeError(f"race_entry_id={race_entry_id}: insufficient signed contributions")
    rows = []
    for direction, selected in (("positive", positive), ("negative", negative)):
        for rank, item in enumerate(selected, 1):
            rows.append(
                {
                    "race_entry_id": int(race_entry_id),
                    "component": component,
                    **item,
                    "field_percentile": None,
                    "contribution_direction": direction,
                    "contribution_rank": rank,
                    "explanation_method": method,
                    "source_cutoff_at_ms": int(source_cutoff_at_ms),
                }
            )
    return rows


def check_probability_contract(frame: pd.DataFrame) -> None:
    for race_id, part in frame.groupby("race_id", sort=False):
        for column, target in (("prob_win", 1.0), ("prob_top2", 2.0), ("prob_top3", 3.0)):
            error = abs(float(part[column].sum()) - target)
            if error > 1e-8:
                raise RuntimeError(f"race_id={race_id} {column} sum error={error}")
        if not ((part.prob_win <= part.prob_top2 + 1e-10) & (part.prob_top2 <= part.prob_top3 + 1e-10)).all():
            raise RuntimeError(f"race_id={race_id}: probability monotonicity failed")
        if sorted(part.a_rank_in_race.tolist()) != list(range(1, len(part) + 1)):
            raise RuntimeError(f"race_id={race_id}: rank permutation failed")


def write_bundle(directory: Path, predictions: pd.DataFrame, explanations: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    runner_path = directory / "runner_predictions.parquet"
    explanation_path = directory / "runner_explanations.json"
    predictions.sort_values(["race_id", "horse_number"]).to_parquet(runner_path, index=False)
    explanation_path.write_text(json.dumps(explanations, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    metadata["runner_predictions_sha256"] = sha256_file(runner_path)
    metadata["runner_explanations_sha256"] = sha256_file(explanation_path)
    (directory / "publication_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def thoroughbred_frame() -> tuple[pd.DataFrame, Any, Any, Any, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_parquet(THOROUGHBRED_INPUT)
    v4 = pd.read_parquet(THOROUGHBRED_V4)
    keys = ["race_id", "hr_no", "race_date"]
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.strftime("%Y-%m-%d")
    v4["race_date"] = pd.to_datetime(v4["race_date"]).dt.strftime("%Y-%m-%d")
    v4 = v4[keys + [name for name in v4.columns if name.startswith("research_v4_")]]
    frame = frame.merge(v4, on=keys, validate="one_to_one").sort_values(
        ["race_date", "race_id", "chul_no", "hr_no"]
    ).reset_index(drop=True)
    win = core.tc.load_v2_win_bundle(V2 / "models/2026/H3_relative")
    bc = core.tc.load_bundle(V4 / "model/models/2026/top3_growth_strength")
    a = core.tc.load_bundle(V5 / "windows/models/2026H2/rolling_all")
    win_score = core.tc.raw_scores(win, frame)["win"]
    bc_score = core.tc.raw_scores(bc, frame)["top3"]
    a_score = core.tc.raw_scores(a, frame)["top3"]
    matrix = core.tc.prepare_matrix(frame, a.categorical_features, a.numeric_features, a.category_vocab)
    contributions = np.asarray(a.models["top3"].predict(matrix, pred_contrib=True, num_threads=4), dtype=float)
    return frame, win, bc, a, win_score, bc_score, a_score, contributions


def build_thoroughbred(
    *,
    race_date: str,
    output: Path,
    db: pd.DataFrame,
    registry_hash: str,
    profile: dict[str, Any],
    values: tuple[pd.DataFrame, Any, Any, Any, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> dict[str, Any]:
    frame, win_bundle, bc_bundle, a_bundle, win_score, bc_score, a_score, contributions = values
    positions = np.flatnonzero(frame.race_date.astype(str).eq(race_date).to_numpy())
    subset = frame.iloc[positions].copy()
    cards = [CARD_FILES[(race_date, venue)] for venue in sorted(subset.venue_code.unique())]
    card_docs = [json.loads(path.read_text(encoding="utf-8")) for path in cards]
    source_card_at_ms = max(epoch_ms(doc["observed_at_utc"]) for doc in card_docs)
    input_card_sha256 = sha256_json(card_docs)
    rows: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []
    db_part = db[(db.race_date == race_date) & db.venue_code.isin(subset.venue_code.unique())].copy()
    db_lookup = {(row.venue_code, int(row.race_no), int(row.horse_number)): row for row in db_part.itertuples()}
    a_temperature = a_bundle.metadata["temperature_by_target_and_venue"]["A"]
    win_temperature = win_bundle.metadata["temperature_by_venue"]
    feature_names = list(a_bundle.categorical_features) + list(a_bundle.numeric_features)
    if contributions.shape != (len(frame), len(feature_names) + 1):
        raise RuntimeError("unexpected Thoroughbred pred_contrib shape")
    for synthetic_race_id, local_index in subset.groupby("race_id", sort=False).groups.items():
        global_index = np.asarray(list(local_index), dtype=int)
        card = frame.iloc[global_index]
        venue = str(card.venue_code.iloc[0])
        temperature = float(a_temperature.get(venue, a_temperature["GLOBAL"]))
        joint = core.tc.top3_set_joint(
            a_score[global_index], win_score[global_index], temperature, float(win_temperature.get(venue, 1.0))
        )
        prob_win, prob_top2, prob_top3 = joint_marginals(joint)
        ranks = np.argsort(np.argsort(-prob_top3, kind="stable"), kind="stable") + 1
        for local_position, (global_position, source_row) in enumerate(card.iterrows()):
            key = (venue, int(source_row.race_no), int(source_row.chul_no))
            if key not in db_lookup:
                raise RuntimeError(f"DB mapping missing: {race_date} {key}")
            mapped = db_lookup[key]
            if str(source_row.hr_no).zfill(7) != mapped.runner_identifier:
                raise RuntimeError(f"horse identity mismatch: {race_date} {key}")
            detail = {
                "race_id": int(mapped.db_race_id),
                "race_entry_id": int(mapped.race_entry_id),
                "horse_number": int(mapped.horse_number),
                "race_date": race_date,
                "venue_code": venue,
                "race_no": int(source_row.race_no),
                "hr_no": str(source_row.hr_no).zfill(7),
                "horse_name": str(source_row.horse_name_normalized),
                "prob_win": float(prob_win[local_position]),
                "prob_top2": float(prob_top2[local_position]),
                "prob_top3": float(prob_top3[local_position]),
                "a_rank_in_race": int(ranks[local_position]),
                "field_size": int(len(card)),
                "raw_a_top3_score": float(a_score[global_position]),
                "raw_bc_top3_score": float(bc_score[global_position]),
                "raw_win_score": float(win_score[global_position]),
                "starter_status": "starter",
                "runner_identifier": str(source_row.hr_no).zfill(7),
                "jockey_identifier": str(source_row.jockey_no).zfill(6),
                "trainer_identifier": str(source_row.trainer_no).zfill(6),
                "owner_identifier": str(source_row.owner_no).zfill(6),
                "cancellation_status": None,
                "body_weight_kg": None,
                "body_weight_change_kg": None,
                "data_quality_flags_json": "[]",
            }
            rows.append(detail)
            explanations.extend(
                select_contributions(
                    race_entry_id=int(mapped.race_entry_id),
                    names=feature_names,
                    values=contributions[global_position, :-1],
                    source=source_row.to_dict(),
                    source_cutoff_at_ms=source_card_at_ms,
                    component="A",
                    method="lightgbm_pred_contrib_raw_a_score",
                )
            )
    predictions = pd.DataFrame(rows)
    expected = 109 if race_date == "2026-09-19" else 185
    if len(predictions) != expected or len(explanations) != expected * 6:
        raise RuntimeError(f"Thoroughbred completeness failed for {race_date}")
    check_probability_contract(predictions)
    a_art = artifact(profile, "A_model")
    a_meta = artifact(profile, "A_metadata")
    bc_art = artifact(profile, "BC_model")
    bc_meta = artifact(profile, "BC_metadata")
    order_art = artifact(profile, "WIN_ORDER_model")
    order_meta = artifact(profile, "WIN_ORDER_metadata")
    components = [
        {"component": "A", "model_version": profile["components"]["A"]["model_version"], "candidate_name": profile["components"]["A"]["candidate"], "artifact_sha256": a_art["sha256"], "metadata_sha256": a_meta["sha256"], "algorithm_version": profile["combination_algorithm_version"], "parameters": {"temperature_by_venue": a_temperature}},
        {"component": "B", "model_version": profile["components"]["B"]["model_version"], "candidate_name": profile["components"]["B"]["candidate"], "artifact_sha256": bc_art["sha256"], "metadata_sha256": bc_meta["sha256"], "algorithm_version": profile["combination_algorithm_version"], "parameters": {"temperature_by_venue": bc_bundle.metadata["temperature_by_target_and_venue"]["B"]}},
        {"component": "C", "model_version": profile["components"]["C"]["model_version"], "candidate_name": profile["components"]["C"]["candidate"], "artifact_sha256": bc_art["sha256"], "metadata_sha256": bc_meta["sha256"], "algorithm_version": profile["combination_algorithm_version"], "parameters": {"temperature_by_venue": bc_bundle.metadata["temperature_by_target_and_venue"]["C"], "order_artifact_sha256": order_art["sha256"]}},
        {"component": "C_ORDER", "model_version": "v2_2026_H3_relative", "candidate_name": "H3_relative", "artifact_sha256": order_art["sha256"], "metadata_sha256": order_meta["sha256"], "algorithm_version": "plackett_luce_within_set_v1", "parameters": {"temperature_by_venue": win_temperature}},
    ]
    feature_hash = combined_file_hash([THOROUGHBRED_INPUT, THOROUGHBRED_V4])
    metadata = {
        "schema_version": 1,
        "domain": "thoroughbred",
        "prediction_stage": "initial_card",
        "experiment_run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"horse-racing:thoroughbred:{race_date}:{input_card_sha256}:{feature_hash}")),
        "model_type": "registered_main_prediction",
        "dataset_version": "thoroughbred_boundary_20260918_v6/future_predictions_20260919_20",
        "as_of_policy": "start_minus_30m",
        "feature_hash": feature_hash,
        "model_artifact_sha256": a_art["sha256"],
        "registry_sha256": registry_hash,
        "input_card_sha256": input_card_sha256,
        "source_card_at_ms": source_card_at_ms,
        "history_cutoff_date": "2026-09-13",
        "feature_cutoff_at_ms": source_card_at_ms,
        "data_availability_status": "partial",
        "probability_contract": profile["probability_contract"],
        "combination_algorithm_version": profile["combination_algorithm_version"],
        "parent_public_id": None,
        "components": components,
        "notes": "초기 출마표 예측. 현재 공식 출마표 재확인 완료. 당일 마체중·날씨·주로·배당·결과는 사용하지 않음. B/C 조합은 저장하지 않고 원시 점수로 백엔드에서 계산.",
    }
    write_bundle(output, predictions, explanations, metadata)
    return {"domain": "thoroughbred", "date": race_date, "races": int(predictions.race_id.nunique()), "runners": len(predictions), "explanations": len(explanations), "output": str(output)}


def build_jeju(*, output: Path, db: pd.DataFrame, registry_hash: str, profile: dict[str, Any]) -> dict[str, Any]:
    scores = pd.read_parquet(JEJU_OUTPUT / "model_scores.parquet")
    explanation_docs = json.loads((JEJU_OUTPUT / "horse_explanations.json").read_text(encoding="utf-8"))
    explanations_by_entry = {int(item["entry_id"]): item for item in explanation_docs}
    metadata_doc = json.loads((JEJU_OUTPUT / "metadata.json").read_text(encoding="utf-8"))
    source_card_at_ms = int(metadata_doc["source_pages"][0]["retrieved_at_ms"])
    input_card_sha256 = str(metadata_doc["source_pages"][0]["raw_sha256"])
    with JEJU_MODEL.open("rb") as handle:
        model = pickle.load(handle)
    beta_set = float(model["rank_bundle"]["beta"])
    beta_order = float(model["beta_order"])
    db_part = db[(db.race_date == "2026-09-19") & (db.venue_code == "JEJU")].copy()
    db_lookup = {(int(row.race_no), int(row.horse_number)): row for row in db_part.itertuples()}
    raw_card = json.loads((JEJU_OUTPUT / "entry_sheet_page_1.json").read_text(encoding="utf-8"))
    official_items = raw_card["response"]["body"]["items"]["item"]
    official_lookup = {(int(item["rcNo"]), int(item["chulNo"])): item for item in official_items}
    rows: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []
    for synthetic_race_id, part in scores.groupby("race_id", sort=True):
        part = part.sort_values("horse_id").reset_index(drop=True)
        sets, orders, log_sets, log_joint, _ = distribution(
            part.rank_score.to_numpy(), part.order_score.to_numpy(), beta_set, beta_order
        )
        prob_win, prob_top2, prob_top3 = jeju_marginals(orders, log_joint, len(part))
        ranks = np.argsort(np.argsort(-prob_top3, kind="stable"), kind="stable") + 1
        race_no = int(int(synthetic_race_id) - 2026091900)
        for index, source_row in part.iterrows():
            key = (race_no, int(source_row.horse_number))
            if key not in db_lookup or key not in official_lookup:
                raise RuntimeError(f"Jeju DB/card mapping missing: {key}")
            mapped = db_lookup[key]
            official = official_lookup[key]
            horse_id = str(source_row.horse_id).zfill(7)
            if horse_id != mapped.runner_identifier or horse_id != str(official["hrNo"]).zfill(7):
                raise RuntimeError(f"Jeju horse identity mismatch: {key}")
            rows.append(
                {
                    "race_id": int(mapped.db_race_id),
                    "race_entry_id": int(mapped.race_entry_id),
                    "horse_number": int(mapped.horse_number),
                    "race_date": "2026-09-19",
                    "venue_code": "JEJU",
                    "race_no": race_no,
                    "hr_no": horse_id,
                    "horse_name": str(source_row.horse_name),
                    "prob_win": float(prob_win[index]),
                    "prob_top2": float(prob_top2[index]),
                    "prob_top3": float(prob_top3[index]),
                    "a_rank_in_race": int(ranks[index]),
                    "field_size": int(len(part)),
                    "raw_rank_score": float(source_row.rank_score),
                    "raw_order_score": float(source_row.order_score),
                    "beta_set": beta_set,
                    "beta_order": beta_order,
                    "starter_status": "starter",
                    "runner_identifier": horse_id,
                    "jockey_identifier": str(official.get("jkNo") or mapped.db_jockey_identifier).zfill(6),
                    "trainer_identifier": str(official.get("trNo") or mapped.db_trainer_identifier).zfill(6),
                    "owner_identifier": str(official.get("owNo") or mapped.db_owner_identifier).zfill(6),
                    "cancellation_status": None,
                    "body_weight_kg": None,
                    "body_weight_change_kg": None,
                    "data_quality_flags_json": "[]",
                }
            )
            explanation = explanations_by_entry[int(source_row.entry_id)]
            supplied_labels = {
                item["feature"]: item["label"]
                for item in explanation["positive_reasons"] + explanation["negative_reasons"]
            }
            selected = explanation["positive_reasons"][:3] + explanation["negative_reasons"][:3]
            names = [item["feature"] for item in selected]
            values = np.asarray([item["contribution"] for item in selected], dtype=float)
            source = {item["feature"]: item.get("raw_value") for item in selected}
            explanations.extend(
                select_contributions(
                    race_entry_id=int(mapped.race_entry_id),
                    names=names,
                    values=values,
                    source=source,
                    source_cutoff_at_ms=source_card_at_ms,
                    component="A_B_C",
                    method="lightgbm_pred_contrib_raw_rank_score",
                    supplied_labels=supplied_labels,
                )
            )
    predictions = pd.DataFrame(rows)
    if len(predictions) != 63 or len(explanations) != 378:
        raise RuntimeError("Jeju completeness failed")
    check_probability_contract(predictions)
    model_art = artifact(profile, "HY_R_FORM_model")
    feature_hash = sha256_file(JEJU_OUTPUT / "live_features.parquet")
    components = [
        {
            "component": "A_B_C",
            "model_version": profile["components"]["A_B_C"]["model_version"],
            "candidate_name": profile["components"]["A_B_C"]["candidate"],
            "artifact_sha256": model_art["sha256"],
            "metadata_sha256": None,
            "algorithm_version": profile["combination_algorithm_version"],
            "parameters": {"beta_set": beta_set, "beta_order": beta_order, "set_score": "rank_score", "order_score": "order_score"},
        }
    ]
    metadata = {
        "schema_version": 1,
        "domain": "jeju",
        "prediction_stage": "initial_card",
        "experiment_run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"horse-racing:jeju:2026-09-19:{input_card_sha256}:{feature_hash}")),
        "model_type": "registered_main_prediction",
        "dataset_version": "jeju_live_20260919_hy_r_form_20260919T035500+0900",
        "as_of_policy": "start_minus_30m",
        "feature_hash": feature_hash,
        "model_artifact_sha256": model_art["sha256"],
        "registry_sha256": registry_hash,
        "input_card_sha256": input_card_sha256,
        "source_card_at_ms": source_card_at_ms,
        "history_cutoff_date": "2026-09-12",
        "feature_cutoff_at_ms": source_card_at_ms,
        "data_availability_status": "partial",
        "probability_contract": profile["probability_contract"],
        "combination_algorithm_version": profile["combination_algorithm_version"],
        "parent_public_id": None,
        "components": components,
        "notes": "제주 HY_R_FORM 초기 출마표 예측. T-2 공식 조교·출발조교·진료 보정 포함. 당일 마체중·날씨·주로·배당·결과는 사용하지 않음. 조합은 저장하지 않고 원시 점수로 백엔드에서 계산.",
    }
    write_bundle(output, predictions, explanations, metadata)
    return {"domain": "jeju", "date": "2026-09-19", "races": int(predictions.race_id.nunique()), "runners": len(predictions), "explanations": len(explanations), "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    registry, registry_hash = read_registry()
    db = database_entries()
    thoroughbred_values = thoroughbred_frame()
    results = [
        build_thoroughbred(race_date="2026-09-19", output=output_root / "thoroughbred_20260919", db=db, registry_hash=registry_hash, profile=profile_for(registry, "thoroughbred"), values=thoroughbred_values),
        build_jeju(output=output_root / "jeju_20260919", db=db, registry_hash=registry_hash, profile=profile_for(registry, "jeju")),
        build_thoroughbred(race_date="2026-09-20", output=output_root / "thoroughbred_20260920", db=db, registry_hash=registry_hash, profile=profile_for(registry, "thoroughbred"), values=thoroughbred_values),
    ]
    (output_root / "build_summary.json").write_text(json.dumps({"ok": True, "bundles": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "bundles": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
