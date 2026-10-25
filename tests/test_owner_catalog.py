import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from test_race_day import migrated_session

from horse_racing.db.models import IngestionRun, Owner, OwnerCatalogSnapshot
from horse_racing.services import owner_catalog as catalog
from scripts import collect_owner_catalog as cli


def raw(meet=1, **changes):
    return {
        "meet": {1: "서울", 2: "제주", 3: "영남"}[meet],
        "owNo": 110034,
        "owName": "공식 마주",
        "stDate": 20101031,
        "totHorses": 131,
        "ownerHorses": 28,
        **changes,
    }


def page(meet, number, items, total):
    payload = {
        "response": {
            "header": {"resultCode": "00"},
            "body": {
                "items": {"item": items},
                "pageNo": number,
                "numOfRows": 1,
                "totalCount": total,
            },
        }
    }
    return SimpleNamespace(
        payload=payload,
        body=json.dumps(payload).encode(),
        source_url="https://apis.data.go.kr/B551015/API309/horseOwnerInfo",
        public_params={"pageNo": number, "meet": meet},
        requested_at_ms=1,
        retrieved_at_ms=2,
        status_code=200,
        content_type="application/json",
    )


class Client:
    def iter_pages(self, **kwargs):
        meet = kwargs["public_params"]["meet"]
        return iter(
            [
                page(meet, 1, [raw(meet)], 2),
                page(meet, 2, [raw(meet, owNo=110035, owName="두 번째")], 2),
            ]
        )


def test_parse_preserves_total_and_current_owned_counts_separately():
    row = catalog.parse_owner(raw(), 1, date(2026, 10, 8))
    assert row.kra_owner_id == "110034"
    assert row.total_registered_horses == 131
    assert row.current_owned_horses == 28
    assert row.registration_date == date(2010, 10, 31)


@pytest.mark.parametrize(
    "changes",
    [
        dict(owNo=0),
        dict(owNo="secret"),
        dict(totHorses=-1),
        dict(totHorses="1.5"),
        dict(totHorses=None),
        dict(ownerHorses=None),
        dict(ownerHorses=""),
        dict(ownerHorses=-1),
        dict(ownerHorses="1.5"),
        dict(ownerHorses=132),
        dict(stDate=20260230),
        dict(stDate=20270101),
        dict(meet="제주"),
        dict(owName=""),
    ],
)
def test_invalid_rows_rejected(changes):
    with pytest.raises(ValueError):
        catalog.parse_owner({**raw(), **changes}, 1, date(2026, 10, 8))


def test_null_registration_is_not_invented():
    assert catalog.parse_owner(raw(stDate="-"), 1, date(2026, 10, 8)).registration_date is None


def test_complete_pagination_preserves_cross_region_ids_and_raw(tmp_path):
    rows, docs = catalog.fetch_catalog(
        Client(), tmp_path, observed_on=date(2026, 10, 8), page_size=1
    )
    assert len(rows) == len(docs) == 6
    assert len({r.kra_owner_id for r, _ in rows}) == 2
    assert {r.meet_code for r, _ in rows} == {1, 2, 3}
    assert len(list(tmp_path.glob("api309_*.json"))) == 6
    assert all(len(d["sha256"]) == 64 for d in docs)


@pytest.mark.parametrize(
    "mode", ["missing_page", "duplicate_owner", "changed_total", "wrong_page", "empty"]
)
def test_incomplete_or_duplicate_source_aborts_all_regions(tmp_path, mode):
    class BrokenClient:
        def iter_pages(self, **kwargs):
            meet = kwargs["public_params"]["meet"]
            if mode == "missing_page":
                return iter([page(meet, 1, [raw(meet)], 2)])
            if mode == "duplicate_owner":
                return iter([page(meet, 1, [raw(meet), raw(meet)], 2)])
            if mode == "changed_total":
                return iter(
                    [page(meet, 1, [raw(meet)], 2), page(meet, 2, [raw(meet, owNo=110035)], 3)]
                )
            if mode == "wrong_page":
                return iter([page(meet, 2, [raw(meet)], 1)])
            return iter([page(meet, 1, [], 0)])

    with pytest.raises(ValueError):
        catalog.fetch_catalog(BrokenClient(), tmp_path, observed_on=date(2026, 10, 8))


def test_store_replay_changes_and_exact_id_only_linkage(tmp_path):
    factory = migrated_session(tmp_path)
    capture = tmp_path / "capture"
    capture.mkdir()
    rows, docs = catalog.fetch_catalog(Client(), capture, observed_on=date(2026, 10, 8))
    with factory() as session:
        exact = Owner(kra_owner_id="110034", name_ko="옛 이름 보존")
        text_id = Owner(kra_owner_id="TEXT:두 번째", name_ko="두 번째")
        session.add_all([exact, text_id])
        session.commit()
        with session.begin():
            result = catalog.persist_catalog(session, rows, docs, started_at_ms=10)
        assert (result["rows"], result["linked"], result["unlinked"]) == (6, 3, 3)
        session.expire_all()
        assert session.get(Owner, exact.id).name_ko == "옛 이름 보존"
        assert session.scalar(select(func.count()).select_from(Owner)) == 2
        session.rollback()
        with session.begin():
            replay = catalog.persist_catalog(session, rows, docs, started_at_ms=20)
        assert replay["status"] == "unchanged" and replay["run_id"] == result["run_id"]
        assert session.scalar(select(func.count()).select_from(OwnerCatalogSnapshot)) == 6
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 1
        session.rollback()
        changed = [
            (
                replace(r, current_owned_horses=r.current_owned_horses + 1),
                source,
            )
            for r, source in rows
        ]
        with session.begin():
            second = catalog.persist_catalog(session, changed, docs, started_at_ms=30)
        assert second["run_id"] != result["run_id"]
        assert catalog.latest_complete_run(session) == second["run_id"]
        assert session.scalar(select(func.count()).select_from(OwnerCatalogSnapshot)) == 12
        assert {row.current_owned_horses for row in session.scalars(
            select(OwnerCatalogSnapshot).where(
                OwnerCatalogSnapshot.ingestion_run_id == result["run_id"],
            )
        )} == {28}
        assert {row.current_owned_horses for row in session.scalars(
            select(OwnerCatalogSnapshot).where(
                OwnerCatalogSnapshot.ingestion_run_id == second["run_id"],
            )
        )} == {29}


def test_missing_region_never_creates_run(tmp_path):
    factory = migrated_session(tmp_path)
    with factory() as session:
        with pytest.raises(ValueError, match="all_owner_regions_required"):
            catalog.persist_catalog(session, [], [], started_at_ms=1)
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0


def test_cli_dry_run_has_no_io(monkeypatch):
    monkeypatch.setattr(cli.live, "load_settings", lambda: pytest.fail("secrets read"))
    monkeypatch.setattr(cli, "create_engine_for_url", lambda *_a: pytest.fail("DB opened"))
    assert cli.execute() == 0
