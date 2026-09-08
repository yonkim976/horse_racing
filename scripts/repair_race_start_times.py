from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from horse_racing.db.models import Race, Racecourse
from horse_racing.db.session import SessionLocal
from horse_racing.parsers.race_day import RacePlanItem, parse_items
from horse_racing.services.race_day import _local_datetime_ms

SEOUL = ZoneInfo("Asia/Seoul")


def _meet_from_path(path: Path) -> int:
    for part in path.parts:
        if part.startswith("meet_"):
            return int(part.removeprefix("meet_"))
    raise ValueError(f"경마장 코드가 없는 경로입니다: {path}")


def _is_date_echo_ms(value: int | None, race_date: date) -> bool:
    if value is None:
        return False
    local = datetime.fromtimestamp(value / 1000, tz=SEOUL)
    return local.minute == race_date.month and local.second == race_date.day


def load_official_schedules(raw_root: Path) -> dict[tuple[int, date, int], int]:
    schedules: dict[tuple[int, date, int], int] = {}
    paths = sorted(raw_root.glob("**/*.json"), key=lambda path: path.stat().st_mtime_ns)
    for path in paths:
        meet = _meet_from_path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in parse_items(payload, RacePlanItem):
            scheduled_at_ms = _local_datetime_ms(item.race_date, item.scheduled_time)
            if scheduled_at_ms is not None:
                schedules[(meet, item.race_date, item.race_number)] = scheduled_at_ms
    return schedules


def main() -> None:
    parser = argparse.ArgumentParser(
        description="공식 경주계획 원본으로 예정 출발시각을 복구합니다."
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw/kra/race_plan"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    schedules = load_official_schedules(args.raw_root)
    scheduled_changed = 0
    scheduled_cleared = 0
    actual_cleared = 0

    with SessionLocal() as session:
        rows = session.execute(
            select(Race, Racecourse.kra_meet_code).join(Race.racecourse)
        ).all()
        for race, meet_code in rows:
            key = (meet_code, race.race_date_local, race.race_number)
            official = schedules.get(key)
            if official is not None and race.scheduled_at_ms != official:
                race.scheduled_at_ms = official
                scheduled_changed += 1
            elif official is None and _is_date_echo_ms(
                race.scheduled_at_ms, race.race_date_local
            ):
                race.scheduled_at_ms = None
                scheduled_cleared += 1

            if _is_date_echo_ms(race.actual_start_at_ms, race.race_date_local):
                race.actual_start_at_ms = None
                actual_cleared += 1

        if args.apply:
            session.commit()
        else:
            session.rollback()

    mode = "적용" if args.apply else "미리보기"
    print(
        f"{mode}: 공식 일정 {len(schedules):,}건, "
        f"예정시각 복구 {scheduled_changed:,}건, "
        f"잘못된 예정시각 제거 {scheduled_cleared:,}건, "
        f"잘못된 실제시각 제거 {actual_cleared:,}건"
    )


if __name__ == "__main__":
    main()
