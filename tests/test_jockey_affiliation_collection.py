import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import Jockey, JockeyAffiliationSnapshot
from scripts.sync_jockey_affiliations import Affiliation, parse_roster, write_snapshots


def sources(meet=1):
    items = [{"jkNo": f"{i:06d}", "jkName": f"기수{i}",
              "meet": {1: "서울", 3: "영남", 2: "제주"}[meet], "spDate": "-"}
             for i in range(1, 12)]
    html = "".join(f'<a href=\'javascript:goPage2("{i:06d}")\'>기수{i}</a>'
                   for i in range(1, 11)).encode()
    return html, items



def payload(items, total=None):
    return json.dumps({"response": {"header": {"resultCode": "00"}, "body": {
        "totalCount": len(items) if total is None else total, "items": {"item": items},
    }}}, ensure_ascii=False).encode()



def test_requires_official_active_membership_not_just_open_registration():
    html, items = sources(3)
    rows = parse_roster(html, payload(items), 3)
    assert len(rows) == 10  # API-only eleventh registration is not on the active roster.
    assert all(row.meet_code == 3 for row in rows)
    assert rows[0].kra_jockey_id == "000001"
    assert all(len(row.source_sha256) == len(row.api_sha256) == 64 for row in rows)



@pytest.mark.parametrize("problem", ["pagination", "name", "ended", "meet", "duplicate"])
def test_rejects_incomplete_or_conflicting_rosters(problem):
    html, items = sources()
    if problem == "name":
        items[0]["jkName"] = "다른사람"
    elif problem == "ended":
        items[0]["spDate"] = "20261001"
    elif problem == "meet":
        items[0]["meet"] = "영남"
    elif problem == "duplicate":
        html += html
    with pytest.raises(ValueError):
        parse_roster(html, payload(items, 999 if problem == "pagination" else None), 1)



def test_atomic_idempotent_snapshot_refresh_and_identity_validation(tmp_path):
    url = f"sqlite:///{tmp_path / 'rosters.sqlite3'}"
    engine = create_engine_for_url(url)
    Base.metadata.create_all(engine)
    rows = [Affiliation(f"{meet}{i:05d}", f"기수{meet}-{i}", meet,
                        "https://race.kra.co.kr/", "a" * 64,
                        "https://apis.data.go.kr/", "b" * 64)
            for meet in [1, 3, 2] for i in range(10)]
    with Session(engine) as session:
        session.add_all([Jockey(kra_jockey_id=row.kra_jockey_id,
                               name_ko=("(-2)" if i == 0 else "") + row.name_ko)
                         for i, row in enumerate(rows)])
        session.commit()
    observed = datetime(2026, 10, 8, tzinfo=ZoneInfo("Asia/Seoul"))
    assert write_snapshots(url, rows, observed) == 30
    assert write_snapshots(url, rows, observed) == 30
    with pytest.raises(ValueError, match="three complete"):
        write_snapshots(url, rows[:10], observed)
    with pytest.raises(ValueError, match="Duplicate"):
        write_snapshots(url, rows + [rows[0]], observed)
    with Session(engine) as session:
        assert len(session.scalars(select(JockeyAffiliationSnapshot)).all()) == 30
    engine.dispose()



def test_profile_fields_are_validated_preserved_and_updated_atomically(tmp_path):
    from dataclasses import replace
    from decimal import Decimal

    html, items = sources()
    for item in items:
        item.update(debut=20010706, wgPart=52.5, wgOther=53)
    rows = parse_roster(html, payload(items), 1)
    assert rows[0].debut_date == "2001-07-06"
    assert rows[0].riding_weight_own_kg == 52.5
    assert rows[0].riding_weight_other_kg == 53
    url = f"sqlite:///{tmp_path / 'profiles.sqlite3'}"
    engine = create_engine_for_url(url)
    Base.metadata.create_all(engine)
    all_rows = [replace(row, kra_jockey_id=f"{meet}{i:05d}", meet_code=meet)
                for meet in (1, 3, 2) for i, row in enumerate(rows)]
    with Session(engine) as session:
        session.add_all(Jockey(kra_jockey_id=row.kra_jockey_id, name_ko=row.name_ko)
                        for row in all_rows)
        session.commit()
    observed = datetime(2026, 10, 8, tzinfo=ZoneInfo("Asia/Seoul"))
    assert write_snapshots(url, all_rows, observed) == 30
    assert write_snapshots(url, all_rows, observed) == 30
    with Session(engine) as session:
        stored = session.scalar(select(JockeyAffiliationSnapshot))
        assert stored.debut_date == date(2001, 7, 6)
        assert stored.riding_weight_own_kg == Decimal("52.5")
        assert stored.riding_weight_other_kg == Decimal("53.0")
    changed = [replace(row, riding_weight_other_kg=52.5) for row in all_rows]
    write_snapshots(url, changed, observed)
    with Session(engine) as session:
        stored = session.scalar(select(JockeyAffiliationSnapshot))
        assert stored.riding_weight_other_kg == Decimal("52.5")
    engine.dispose()



@pytest.mark.parametrize("field,value", [
    ("debut", "20260230"), ("debut", "99990101"),
    ("wgPart", -1), ("wgOther", 100), ("wgPart", "nan"), ("wgOther", 52.55),
])
def test_rejects_invalid_profile_values_before_writing(field, value):
    html, items = sources()
    items[0][field] = value
    with pytest.raises(ValueError):
        parse_roster(html, payload(items), 1)

