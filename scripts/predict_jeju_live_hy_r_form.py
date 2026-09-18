"""Generate a sealed pre-race HY_R_FORM forecast for one Jeju race day.

This script only calls the official entry-sheet endpoint.  It never requests
results, odds, same-day weights, weather, or steward reports for the target
date.  Historical inputs come from the reviewed research artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_context_features import (
    FEATURES as CONTEXT_FEATURES,
)
from horse_racing.analysis.jeju_context_features import build_features as build_context
from horse_racing.analysis.jeju_h3_features import (
    BASE_FEATURES,
    RELATIVE_FEATURES,
    add_people_history,
    add_relative,
)
from horse_racing.analysis.jeju_hybrid_evaluation import distribution
from horse_racing.analysis.jeju_live_supplementals import corrected_h2, overlay_h2
from horse_racing.analysis.jeju_native_top3_states import build_states
from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.config import get_settings
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
H3 = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
TRANSITION = ROOT / "data/research/jeju_native_transition_features_v1_20260916"
RESEARCH_DB = (
    ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
)
MODEL = (
    ROOT
    / "data/research/jeju_native_transition_holdout_v13_20260916/bundles/"
    "frozen_2026__HY_R_FORM.pkl"
)
EXPECTED_MODEL_SHA256 = "f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706"
KST = ZoneInfo("Asia/Seoul")

FEATURE_LABELS = {
    "global_elo_pre": "전체 능력 Elo",
    "distance_elo_pre": "거리별 능력 Elo",
    "elo_uncertainty_pre": "능력 추정 불확실성",
    "starts_pre": "과거 출전 수",
    "normal_completed_pre": "정상 완주 수",
    "wins_pre": "과거 우승 수",
    "top3_pre": "과거 입상 수",
    "days_since_previous_start": "직전 출전 후 일수",
    "days_since_previous_normal_finish": "직전 정상 완주 후 일수",
    "distance_starts_pre": "같은 거리 출전 수",
    "distance_wins_pre": "같은 거리 우승 수",
    "distance_top3_pre": "같은 거리 입상 수",
    "recent_finish_score_5_mean": "최근 5경주 상대착순점수",
    "recent_top3_rate_5": "최근 5경주 입상률",
    "performance_variability_pre": "최근 성적 변동성",
    "speed_time_per_100m_mean_pre": "전체 기록의 100m당 환산 평균(초반 구간 아님)",
    "speed_residual_mean_pre": "주변 경주 대비 기록",
    "speed_residual_std_pre": "기록 변동성",
    "section_s1f_ms_mean_pre": "과거 초반 S1F",
    "section_s1f210_ms_mean_pre": "과거 초반 S1F 210m",
    "section_g1f_ms_mean_pre": "과거 막판 G1F",
    "section_g3f_ms_mean_pre": "과거 막판 G3F",
    "training_28d_count": "최근 28일 조교 횟수",
    "training_28d_duration_seconds": "최근 28일 조교 시간",
    "start_training_28d_count": "최근 28일 출발조교 횟수",
    "medical_90d_count": "최근 90일 진료 기록 수",
    "trial_count_pre": "과거 주행심사 수",
    "trial_last_valid_time_ms_pre": "최근 주행심사 기록",
    "weight_last_kg_pre": "최근 관측 마체중",
    "weight_count_pre": "과거 마체중 관측 수",
    "declared_horse_number": "출주번호",
    "declared_age": "나이",
    "declared_female": "암말 여부",
    "declared_gelded": "거세마 여부",
    "declared_burden_kg": "선언 부담중량",
    "declared_rating": "선언 레이팅",
    "declared_grade_number": "선언 등급",
    "jockey_history_win_rate": "기수 과거 우승률",
    "jockey_history_top3_rate": "기수 과거 입상률",
    "trainer_history_win_rate": "조교사 과거 우승률",
    "trainer_history_top3_rate": "조교사 과거 입상률",
    "horse_jockey_history_top3_rate": "말·기수 조합 입상률",
    "rival_global_elo_mean": "경쟁마 평균 Elo",
    "rival_global_elo_gap": "최강 경쟁마와 Elo 차이",
    "rival_distance_elo_gap": "최강 경쟁마와 거리 Elo 차이",
    "declared_horse_number_fraction": "편성 내 출주번호 위치",
    "historical_early_front_rate": "과거 선행 빈도",
    "rival_early_pressure_count": "선행 경쟁마 수",
    "field_early_ability_percentile": "편성 내 선행력 위치",
    "jockey_early_front_rate": "기수의 선행 빈도",
    "current_minus_previous_elo": "직전 경주 후 Elo 변화",
    "current_vs_previous_rival_elo": "현재와 직전 편성 강도 변화",
    "current_minus_last_burden_kg": "직전 대비 부담중량 변화",
    "last_early_rank": "직전 초반 순위",
    "last_late_rank": "직전 막판 순위",
    "closing_speed_quality_mean_3": "최근 3경주 막판 상대속도",
    "progression_last3_vs_prev3": "최근 성적 발전도",
    "best_last5_performance": "최근 5경주 최고 성적",
    "poor_last_but_good_late": "직전 부진·막판 양호",
    "wet_performance_mean": "습윤 주로 성적",
    "dry_performance_mean": "건조 주로 성적",
    "history_time_minus_same_race_median": "경주 내 기록 차이 이력",
    "jockey_changed": "기수 교체",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def grade_number(value: str | None) -> int | None:
    match = re.search(r"([1-6])", value or "")
    return int(match.group(1)) if match else None


def fetch_cards(race_date: str, output: Path):
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("HORSE_RACING_DATA_GO_KR_SERVICE_KEY is missing")
    pages = []
    items = []
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    ) as client:
        for page_number, fetched in enumerate(
            client.iter_entry_sheet_pages(race_date=race_date, meet=2, page_size=1000), 1
        ):
            raw_path = output / f"entry_sheet_page_{page_number}.json"
            raw_path.write_bytes(fetched.body)
            parsed = parse_entry_sheet_page(fetched.payload)
            items.extend(parsed.items)
            pages.append(
                {
                    "page": page_number,
                    "source_url": fetched.source_url,
                    "public_params": fetched.public_params,
                    "requested_at_ms": fetched.requested_at_ms,
                    "retrieved_at_ms": fetched.retrieved_at_ms,
                    "http_status_code": fetched.status_code,
                    "raw_file": raw_path.name,
                    "raw_sha256": sha256(raw_path),
                    "records": len(parsed.items),
                }
            )
    return items, pages


def people_history() -> list[dict]:
    labels = pl.read_parquet(DATA / "labels.parquet")
    connection = sqlite3.connect(f"file:{RESEARCH_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    originals = {
        int(row["entry_id"]): dict(row)
        for row in connection.execute(
            """
            SELECT e.id AS entry_id,
                   json_extract(s.normalized_json,'$.jkName') AS jockey_name,
                   json_extract(s.normalized_json,'$.jkNo') AS jockey_id,
                   json_extract(s.normalized_json,'$.trName') AS trainer_name,
                   json_extract(s.normalized_json,'$.trNo') AS trainer_id
            FROM entry e
            JOIN event v ON e.event_id=v.id
            JOIN source_row s ON s.id=e.source_row_id
            WHERE v.event_type='race' AND v.event_date<='20260912'
            """
        )
    }
    connection.close()
    history = []
    for row in labels.iter_rows(named=True):
        source = originals.get(int(row["entry_id"]))
        if source is None:
            continue
        history.append(
            {
                "event_date": row["event_date"],
                "horse_id": row["horse_id"],
                "jockey_name": source["jockey_name"],
                "jockey_id": str(source["jockey_id"]) if source["jockey_id"] else None,
                "trainer_name": source["trainer_name"],
                "trainer_id": str(source["trainer_id"]) if source["trainer_id"] else None,
                "win": int(row["label_win"]),
                "top3": int(row["label_top3"]),
            }
        )
    return history


def contribution_rows(bundle: dict, frame: pl.DataFrame) -> list[dict]:
    preprocessor = bundle["preprocessor"]
    matrix = preprocessor.transform(frame)
    contributions = np.mean(
        [model.booster_.predict(matrix, pred_contrib=True) for model in bundle["models"]],
        axis=0,
    )
    names = list(preprocessor.names) + ["__bias__"]
    results = []
    for row_index, values in enumerate(contributions):
        pairs = []
        source = frame.row(row_index, named=True)
        for name, value in zip(names, values, strict=True):
            if name == "__bias__":
                continue
            base = name.removesuffix("__missing")
            raw = source.get(base)
            if isinstance(raw, float) and not np.isfinite(raw):
                raw = None
            pairs.append(
                {
                    "feature": name,
                    "label": FEATURE_LABELS.get(base, base)
                    + (" 결측" if name.endswith("__missing") else ""),
                    "raw_value": raw,
                    "contribution": float(value),
                }
            )
        positive = sorted(pairs, key=lambda item: (-item["contribution"], item["feature"]))[:5]
        negative = sorted(pairs, key=lambda item: (item["contribution"], item["feature"]))[:5]
        results.append({"positive": positive, "negative": negative})
    return results


def rank_scores(bundle: dict, frame: pl.DataFrame) -> np.ndarray:
    matrix = bundle["preprocessor"].transform(frame)
    return np.mean(
        [model.predict(matrix, raw_score=True) for model in bundle["models"]], axis=0
    )


def order_scores(bundle: dict, frame: pl.DataFrame) -> np.ndarray:
    matrix = bundle["preprocessor"].transform(frame)
    return np.mean([model.predict(matrix)[:, 1] for model in bundle["models"]], axis=0)


def display_reason(items: list[dict]) -> str:
    return ", ".join(
        f"{item['label']}({item['contribution']:+.3f})" for item in items[:3]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260917")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--official-inputs", type=Path)
    args = parser.parse_args()
    target_date = datetime.strptime(args.date, "%Y%m%d").date()
    now = datetime.now(KST)
    output = args.output or (
        ROOT
        / "data/predictions"
        / f"jeju_live_{args.date}_hy_r_form_{now.strftime('%Y%m%dT%H%M%S%z')}"
    )
    if output.exists():
        raise FileExistsError(f"Refuse to overwrite live prediction: {output}")
    output.mkdir(parents=True)
    if sha256(MODEL) != EXPECTED_MODEL_SHA256:
        raise RuntimeError("HY_R_FORM model hash mismatch")

    items, source_pages = fetch_cards(args.date, output)
    items = [item for item in items if item.race_date == target_date]
    if not items:
        raise RuntimeError("No target entry rows returned")
    races = sorted({item.race_number for item in items})
    if len({item.horse_id for item in items}) != len(items):
        raise RuntimeError("Duplicate horse identity in target card")

    counts = {race: sum(item.race_number == race for item in items) for race in races}
    race_ids = {race: int(args.date) * 100 + race for race in races}
    entry_rows = []
    by_entry = {}
    for item in sorted(items, key=lambda value: (value.race_number, value.horse_number)):
        entry_id = race_ids[item.race_number] * 100 + item.horse_number
        row = {
            "entry_id": entry_id,
            "race_id": race_ids[item.race_number],
            "horse_id": str(item.horse_id).zfill(7),
            "event_date": item.race_date,
            "cutoff_at": datetime.combine(item.race_date, datetime.min.time()),
            "distance_m": item.distance_m,
            "field_size": counts[item.race_number],
        }
        entry_rows.append(row)
        by_entry[entry_id] = item
    entries = pl.DataFrame(entry_rows, infer_schema_length=None)

    history_results = pl.read_parquet(DATA / "history_results.parquet")
    states, state_meta = build_states(RESEARCH_DB, entries, history_results)
    h2_corrections = []
    supplemental_meta = None
    if args.official_inputs is not None:
        official_manifest = json.loads(
            (args.official_inputs / "manifest.json").read_text(encoding="utf-8")
        )
        if official_manifest.get("target_date") != args.date:
            raise ValueError("Official supplemental target date mismatch")
        if official_manifest.get("result_endpoints_called"):
            raise ValueError("Official supplemental input contains result endpoints")
        corrected, supplemental_meta = corrected_h2(
            official_root=args.official_inputs,
            database=RESEARCH_DB,
            horse_ids=entries["horse_id"].to_list(),
            target_date=target_date,
        )
        old_by_horse = {row["horse_id"]: row for row in states.iter_rows(named=True)}
        corrected_by_horse = {
            row["horse_id"]: row for row in corrected.iter_rows(named=True)
        }
        states = overlay_h2(states, corrected)
        for row in entry_rows:
            horse_id = row["horse_id"]
            old = old_by_horse[horse_id]
            fresh = corrected_by_horse[horse_id]
            changes = {
                column: {"old": old.get(column), "new": fresh[column]}
                for column in corrected.columns
                if column != "horse_id" and old.get(column) != fresh[column]
            }
            if changes:
                item = by_entry[row["entry_id"]]
                h2_corrections.append(
                    {
                        "race_number": item.race_number,
                        "horse_number": item.horse_number,
                        "horse_name": item.horse_name,
                        "horse_id": horse_id,
                        "changes": changes,
                    }
                )
    state_map = {row["entry_id"]: row for row in states.iter_rows(named=True)}

    h3_targets = []
    for row in entry_rows:
        item = by_entry[row["entry_id"]]
        rating = item.rating if item.rating is not None and item.rating > 0 else None
        h3_targets.append(
            {
                "entry_id": row["entry_id"],
                "race_id": row["race_id"],
                "horse_id": row["horse_id"],
                "event_date": row["event_date"],
                "card_observed": 1,
                "declared_horse_number": item.horse_number,
                "declared_age": item.age,
                "declared_female": int(item.sex == "암") if item.sex else None,
                "declared_gelded": int(item.sex == "거") if item.sex else None,
                "declared_burden_kg": item.carried_weight_kg,
                "declared_rating": rating,
                "declared_grade_number": grade_number(item.grade),
                "declared_jockey_allowance_kg": 0.0,
                "jockey_name": item.jockey_name,
                "trainer_name": item.trainer_name,
            }
        )
    h3_augmented = pl.DataFrame(
        add_people_history(h3_targets, people_history()), infer_schema_length=None
    )
    h3_features = h3_augmented.select("entry_id", *BASE_FEATURES)
    h3_features = add_relative(states.join(h3_features, on="entry_id", validate="1:1")).select(
        "entry_id", *BASE_FEATURES, *RELATIVE_FEATURES
    )

    context_targets = []
    for row in entry_rows:
        item = by_entry[row["entry_id"]]
        state = state_map[row["entry_id"]]
        context_targets.append(
            {
                "entry_id": row["entry_id"],
                "race_id": row["race_id"],
                "horse_id": row["horse_id"],
                "event_date": row["event_date"],
                "field_size": row["field_size"],
                "horse_number": item.horse_number,
                "global_elo_pre": state["global_elo_pre"],
                "distance_elo_pre": state["distance_elo_pre"],
                "declared_burden_kg": item.carried_weight_kg,
                "jockey_name": item.jockey_name,
                "card_observed": 1,
            }
        )
    context_history = pl.read_parquet(TRANSITION / "context_history.parquet").to_dicts()
    context = pl.DataFrame(
        build_context(context_targets, context_history), infer_schema_length=None
    ).select("entry_id", *CONTEXT_FEATURES)
    frame = states.join(
        h3_features.select(
            "entry_id", *[column for column in h3_features.columns if column not in states.columns]
        ),
        on="entry_id",
        validate="1:1",
    ).join(context, on="entry_id", validate="1:1")

    with MODEL.open("rb") as handle:
        model = pickle.load(handle)  # noqa: S301 - verified trusted local artifact
    rank_bundle = model["rank_bundle"]
    order_bundle = model["order_bundle"]
    missing_rank = sorted(set(rank_bundle["features"]) - set(frame.columns))
    missing_order = sorted(set(order_bundle["features"]) - set(frame.columns))
    if missing_rank or missing_order:
        raise RuntimeError(f"Missing live features: rank={missing_rank}, order={missing_order}")

    rank_raw = rank_scores(rank_bundle, frame)
    order_raw = order_scores(order_bundle, frame)
    explanations = contribution_rows(rank_bundle, frame)
    scored = frame.select(
        "entry_id", "race_id", "horse_id", "event_date", "distance_m", "field_size"
    ).with_columns(
        pl.Series("rank_score", rank_raw),
        pl.Series("order_score", order_raw),
        pl.Series("horse_number", [by_entry[value].horse_number for value in frame["entry_id"]]),
        pl.Series("horse_name", [by_entry[value].horse_name for value in frame["entry_id"]]),
        pl.Series("jockey_name", [by_entry[value].jockey_name for value in frame["entry_id"]]),
        pl.Series(
            "burden_kg",
            [by_entry[value].carried_weight_kg for value in frame["entry_id"]],
        ),
    )

    race_predictions = []
    horse_predictions = []
    report_lines = [
        f"# 제주 {target_date.isoformat()} HY_R_FORM 사전 예측",
        "",
        f"- 생성 시각: {datetime.now(KST).isoformat()}",
        f"- 모델: `HY_R_FORM` / SHA-256 `{EXPECTED_MODEL_SHA256}`",
        "- 입력: 공식 출마표와 2026-09-12까지의 과거 이력",
        (
            f"- H2 보정: 최신 공식 조교·출발조교·진료 원자료를 T-2({supplemental_meta['cutoff_date']})로 "
            f"절단해 {len(h2_corrections)}두의 입력을 교정"
            if args.official_inputs is not None
            else "- H2 보정: 사용하지 않음"
        ),
        "- 제외: 대상 경주 결과·최종 배당·당일 마체중·실제 날씨/주로·대상 경주 심판보고",
        (
            "- 선언 기수 감량은 API에 별도 필드가 없어 0kg로 기록했다. "
            "선언 부담중량은 공식 값을 사용했다."
        ),
        "- 아래 이유는 모델 점수에 대한 기여도이며 실제 경기 결과의 인과 원인이 아니다.",
        "",
    ]
    frame_index = {int(entry_id): index for index, entry_id in enumerate(frame["entry_id"])}
    for race_id in sorted(scored["race_id"].unique().to_list()):
        part = scored.filter(pl.col("race_id") == race_id).sort("horse_id")
        ids = part["horse_id"].to_list()
        set_scores = part["rank_score"].to_numpy()
        ord_scores = part["order_score"].to_numpy()
        sets, orders, log_sets, joint, marginals = distribution(
            set_scores,
            ord_scores,
            rank_bundle["beta"],
            model["beta_order"],
        )
        set_index = int(np.argmax(log_sets))
        order_slice = joint[set_index * 6 : set_index * 6 + 6]
        order_index = set_index * 6 + int(np.argmax(order_slice))
        pick_index = int(np.argmax(set_scores))
        predicted_set = [ids[index] for index in sets[set_index]]
        predicted_order = [ids[index] for index in orders[order_index]]
        names = {
            row["horse_id"]: f"{row['horse_number']}번 {row['horse_name']}"
            for row in part.iter_rows(named=True)
        }
        race_number = int(race_id - int(args.date) * 100)
        boundary = sorted(range(len(ids)), key=lambda index: (-marginals[index], ids[index]))
        record = {
            "race_number": race_number,
            "race_id": race_id,
            "distance_m": int(part["distance_m"][0]),
            "field_size": len(part),
            "pick_horse_id": ids[pick_index],
            "pick": names[ids[pick_index]],
            "pick_top3_probability": float(marginals[pick_index]),
            "predicted_set_horse_ids": predicted_set,
            "predicted_set": [names[value] for value in predicted_set],
            "set_probability": float(np.exp(log_sets[set_index])),
            "predicted_order_horse_ids": predicted_order,
            "predicted_order": [names[value] for value in predicted_order],
            "order_probability": float(np.exp(joint[order_index])),
            "third_by_probability": names[ids[boundary[2]]],
            "fourth_by_probability": names[ids[boundary[3]]],
            "third_fourth_probability_gap": float(marginals[boundary[2]] - marginals[boundary[3]]),
        }
        race_predictions.append(record)
        report_lines.extend(
            [
                f"## {race_number}경주 · {record['distance_m']}m · {len(part)}두",
                "",
                f"- 한 마리 입상: **{record['pick']}** · {record['pick_top3_probability']:.1%}",
                (
                    f"- 입상 세 마리: **{' · '.join(record['predicted_set'])}** · "
                    f"집합 확률 {record['set_probability']:.1%}"
                ),
                (
                    f"- 정확한 순서: **{' → '.join(record['predicted_order'])}** · "
                    f"순서 확률 {record['order_probability']:.1%}"
                ),
                (
                    f"- 선택 경계: {record['third_by_probability']} vs "
                    f"{record['fourth_by_probability']} · 차이 "
                    f"{record['third_fourth_probability_gap']:.1%}p"
                ),
                "",
                "| 모델순위 | 말 | 입상확률 | 기수 | 부담중량 | 주요 유리 요인 | 주요 불리 요인 |",
                "|---:|---|---:|---|---:|---|---|",
            ]
        )
        for model_rank, index in enumerate(boundary, 1):
            row = part.row(index, named=True)
            original_index = frame_index[int(row["entry_id"])]
            reason = explanations[original_index]
            horse_predictions.append(
                {
                    **row,
                    "race_number": race_number,
                    "top3_probability": float(marginals[index]),
                    "model_rank": model_rank,
                    "selected_pick": index == pick_index,
                    "selected_set": ids[index] in predicted_set,
                    "positive_reasons": reason["positive"],
                    "negative_reasons": reason["negative"],
                }
            )
            report_lines.append(
                f"| {model_rank} | {row['horse_number']}번 {row['horse_name']} | "
                f"{marginals[index]:.1%} | {row['jockey_name'] or '미상'} | "
                f"{row['burden_kg'] if row['burden_kg'] is not None else '미상'} | "
                f"{display_reason(reason['positive'])} | {display_reason(reason['negative'])} |"
            )
        report_lines.append("")

    scored.write_parquet(output / "model_scores.parquet", compression="zstd")
    frame.write_parquet(output / "live_features.parquet", compression="zstd")
    pl.DataFrame(
        [
            {
                key: value
                for key, value in row.items()
                if key not in {"positive_reasons", "negative_reasons"}
            }
            for row in horse_predictions
        ],
        infer_schema_length=None,
    ).write_parquet(output / "horse_predictions.parquet", compression="zstd")
    write_json(output / "race_predictions.json", race_predictions)
    write_json(output / "horse_explanations.json", horse_predictions)
    write_json(
        output / "h2_input_corrections.json",
        {
            "official_inputs": str(args.official_inputs) if args.official_inputs else None,
            "metadata": supplemental_meta,
            "changed_horses": len(h2_corrections),
            "corrections": h2_corrections,
        },
    )
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    metadata = {
        "created_at": datetime.now(KST).isoformat(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "target_date": target_date.isoformat(),
        "meet": 2,
        "model": "HY_R_FORM",
        "model_path": str(MODEL),
        "model_sha256": sha256(MODEL),
        "race_numbers": races,
        "races": len(races),
        "entries": len(items),
        "source_pages": source_pages,
        "state_metadata": state_meta,
        "history_last_date": "2026-09-12",
        "target_result_endpoints_called": [],
        "official_supplemental_inputs": (
            str(args.official_inputs) if args.official_inputs is not None else None
        ),
        "h2_supplemental_metadata": supplemental_meta,
        "h2_changed_horses": len(h2_corrections),
        "same_day_weight_used": False,
        "final_odds_used": False,
        "jockey_allowance_policy": (
            "API26_2 has no separate allowance field; fixed 0kg; official burden retained"
        ),
    }
    write_json(output / "metadata.json", metadata)
    manifest = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            {"output": str(output), "races": len(races), "entries": len(items)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
