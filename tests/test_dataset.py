from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from horse_racing.analysis.dataset import (
    DatasetValidationError,
    apply_label_policy,
    compute_auc,
    compute_prediction_at,
    leakage_canary,
    validate_dataset,
)
from horse_racing.analysis.pit import (
    ForbiddenSnapshotJoinError,
    FutureObservationError,
    assert_point_in_time,
    ensure_pit_allowed,
    point_in_time_join,
)

KST = ZoneInfo("Asia/Seoul")


def _entry(
    race_id: int,
    finish_position: int | None,
    *,
    scratched: bool = False,
    has_result: bool = True,
) -> dict:
    return {
        "race_id": race_id,
        "scratched": scratched,
        "finish_position": finish_position,
        "result_id": 1 if has_result else None,
    }


def synthetic_entries() -> pl.DataFrame:
    rows = [
        # 경주 1: 정상 6두 (1착 동착) + 취소 1 + 특수코드 1 + 착순 NULL 1 + 결과행 없음 1
        _entry(1, 1),
        _entry(1, 1),
        _entry(1, 3),
        _entry(1, 4),
        _entry(1, 5),
        _entry(1, 6),
        _entry(1, None, scratched=True, has_result=False),
        _entry(1, 99),
        _entry(1, None),
        _entry(1, None, has_result=False),
        # 경주 2: 4두뿐 → 소두수 제외
        _entry(2, 1),
        _entry(2, 2),
        _entry(2, 3),
        _entry(2, 4),
        # 경주 3: 5두인데 1착 없음 → 경주 제외
        _entry(3, 2),
        _entry(3, 3),
        _entry(3, 4),
        _entry(3, 5),
        _entry(3, 6),
    ]
    return pl.DataFrame(rows)


def test_label_policy_exclusions_and_labels() -> None:
    labeled, stats = apply_label_policy(synthetic_entries())

    assert stats.scratched == 1
    assert stats.special_finish_code == 1
    assert stats.missing_finish_position == 1
    assert stats.missing_result_row == 1
    assert stats.small_field_races == 1
    assert stats.small_field_rows == 4
    assert stats.no_winner_races == 1
    assert stats.no_winner_rows == 5

    assert labeled.height == 6
    assert labeled.get_column("race_id").unique().to_list() == [1]
    # 동착: 1착 2두 모두 win=1, top2에도 포함
    assert labeled.get_column("win").sum() == 2
    assert labeled.get_column("top2").sum() == 2
    assert labeled.get_column("top3").sum() == 3
    # 출주 두수는 취소·특수·결측 제외한 정상 완주 기준
    assert labeled.get_column("starters").unique().to_list() == [6]


def test_base_dataset_query_explicitly_excludes_running_trials(tmp_path) -> None:
    from datetime import date

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from horse_racing.analysis.dataset import fetch_base_rows
    from horse_racing.db.base import Base
    from horse_racing.db.models import (
        Horse,
        Race,
        Racecourse,
        RaceEntry,
        RaceResult,
        RunningTrial,
        RunningTrialResult,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'scope.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        horse = Horse(kra_horse_id="scope-1", name_ko="범위확인마")
        race = Race(
            racecourse=course,
            race_date_local=date(2026, 8, 27),
            race_number=1,
            distance_m=1200,
            scheduled_at_ms=1_788_000_000_000,
            status="completed",
        )
        entry = RaceEntry(race=race, horse=horse, horse_number=1)
        result = RaceResult(race_entry=entry, finish_position=1)
        trial = RunningTrial(
            meet_code=1,
            trial_date_local=date(2026, 8, 27),
            trial_race_number=1,
            distance_m=1000,
            observed_at_ms=1,
        )
        trial_result = RunningTrialResult(
            trial=trial,
            horse=horse,
            horse_number=1,
            horse_name_raw="범위확인마",
            finish_position=1,
            judgement="합",
            observed_at_ms=1,
        )
        session.add_all([course, horse, race, entry, result, trial, trial_result])
        session.commit()

        frame = fetch_base_rows(session)
        race_id = race.id

    assert frame.height == 1
    assert frame.get_column("race_id").to_list() == [race_id]
    assert "running_trial_id" not in frame.columns
    assert {"finish_time_ms", "margin_text"} <= set(frame.columns)


def test_prediction_at_start_minus_30m() -> None:
    frame = pl.DataFrame({"scheduled_at_ms": [1_000_000_000], "race_date_local": ["2026-08-22"]})
    result = compute_prediction_at(frame, "start_minus_30m")
    assert result.get_column("prediction_at_ms")[0] == 1_000_000_000 - 30 * 60 * 1000


def test_prediction_at_day_before_18() -> None:
    frame = pl.DataFrame({"scheduled_at_ms": [1], "race_date_local": ["2026-08-22"]})
    result = compute_prediction_at(frame, "day_before_18")
    expected = int(datetime(2026, 8, 21, 18, 0, tzinfo=KST).timestamp() * 1000)
    assert result.get_column("prediction_at_ms")[0] == expected


def test_prediction_at_unknown_policy() -> None:
    with pytest.raises(ValueError, match="as-of"):
        compute_prediction_at(pl.DataFrame({"scheduled_at_ms": [1]}), "nope")


def test_validate_dataset_rejects_prediction_after_start() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1] * 5,
            "prediction_at_ms": [200] * 5,
            "scheduled_at_ms": [100] * 5,
            "win": [1, 0, 0, 0, 0],
            "top2": [1, 1, 0, 0, 0],
            "top3": [1, 1, 1, 0, 0],
        }
    )
    with pytest.raises(DatasetValidationError, match="출발시각 이후"):
        validate_dataset(frame)


def test_point_in_time_join_picks_last_prior_observation() -> None:
    base = pl.DataFrame({"horse_id": [1, 1, 2], "prediction_at_ms": [100, 250, 100]})
    history = pl.DataFrame(
        {
            "horse_id": [1, 1, 1, 2],
            "observed_at_ms": [50, 200, 300, 400],
            "body_weight_kg": [480, 484, 490, 500],
        }
    )
    joined = point_in_time_join(
        base,
        history,
        source_table="horse_weight_history",
        by="horse_id",
        base_time_col="prediction_at_ms",
    ).sort(["horse_id", "prediction_at_ms"])

    weights = joined.get_column("body_weight_kg").to_list()
    # horse 1 @100 → 50의 관측(480), horse 1 @250 → 200의 관측(484),
    # horse 2 @100 → 미래 관측(400)뿐이라 null
    assert weights == [480, 484, None]


def test_point_in_time_join_rejects_snapshot_tables() -> None:
    base = pl.DataFrame({"horse_id": [1], "prediction_at_ms": [100]})
    history = pl.DataFrame({"horse_id": [1], "observed_at_ms": [50], "rating_1": [70.0]})
    with pytest.raises(ForbiddenSnapshotJoinError, match="스냅샷"):
        point_in_time_join(
            base,
            history,
            source_table="horse_rating_snapshots",
            by="horse_id",
            base_time_col="prediction_at_ms",
        )


def test_point_in_time_join_rejects_unlisted_tables() -> None:
    with pytest.raises(ForbiddenSnapshotJoinError, match="허용 목록에 없습니다"):
        ensure_pit_allowed("mystery_table")


def test_assert_point_in_time_detects_future_rows() -> None:
    frame = pl.DataFrame({"observed": [10, 300], "as_of": [100, 100]})
    with pytest.raises(FutureObservationError, match="미래 관측"):
        assert_point_in_time(frame, observed_col="observed", as_of_col="as_of")


def test_compute_auc_known_values() -> None:
    assert compute_auc([0.9, 0.8, 0.3, 0.1], [1, 1, 0, 0]) == 1.0
    assert compute_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert compute_auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5
    assert compute_auc([0.5, 0.5], [1, 1]) is None


def test_leakage_canary_flags_injected_future_feature() -> None:
    labeled, _ = apply_label_policy(synthetic_entries())
    frame = labeled.with_columns(
        # 의도적 누수: 착순 자체를 feature로 주입
        (-pl.col("finish_position")).cast(pl.Float64).alias("leaky_feature"),
        # 정상 feature: 라벨과 무관한 값
        pl.Series("benign_feature", [0.3, 0.9, 0.1, 0.8, 0.2, 0.7]),
    )
    flagged = leakage_canary(frame, ["leaky_feature", "benign_feature"], label_column="win")
    assert "leaky_feature" in flagged
    assert flagged["leaky_feature"] >= 0.95
    assert "benign_feature" not in flagged
