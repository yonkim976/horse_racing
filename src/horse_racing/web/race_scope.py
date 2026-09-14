"""Operational race scope shared by web views."""

from sqlalchemy import or_

from horse_racing.db.models import Race, Racecourse


def active_race_clause():
    """Exclude the retired Jeju Halla race regime from operational views."""
    return or_(
        Racecourse.kra_meet_code != 2,
        Race.grade.is_(None),
        ~Race.grade.like("한%"),
    )


def is_retired_halla_race(race: Race) -> bool:
    return (
        race.racecourse.kra_meet_code == 2
        and bool(race.grade)
        and race.grade.startswith("한")
    )
