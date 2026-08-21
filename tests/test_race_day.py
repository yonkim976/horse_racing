import json
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    IngestionRun,
    OddsSnapshot,
    Race,
    RaceEntry,
    RaceResult,
    SourceDocument,
)
from horse_racing.parsers.race_day import (
    AiRaceResultItem,
    FinalDividendItem,
    parse_body_weight,
    parse_track_status,
)
from horse_racing.services.race_day import (
    ingest_race_day,
    race_day_is_complete,
    result_data_exists,
)

ENTRY_FIXTURE = Path(__file__).parent / "fixtures" / "entry_sheet_page.json"


def api_payload(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": items},
                "numOfRows": "1000",
                "pageNo": "1",
                "totalCount": str(len(items)),
            },
        }
    }


def race_plan_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "raceDt": "20260822",
                "raceNo": "1",
                "raceDs": "1200M",
                "rccrsNm": "서울",
                "raceDyCnt": "62",
                "ptinNhr": "2",
                "raceClas": "국6등급",
                "raceNm": "일반",
                "cndtsBurdWgt": "별정A",
                "cndtsAg": "3세",
                "cndtsGndr": "암수",
                "cndtsRatg": "0~40",
                "cndtsNcmr": "신마",
                "strtPargTm": "10:35",
                "wetr": "맑음",
                "going": "건조 (3%)",
            }
        ]
    )


def ai_result_payload() -> dict[str, object]:
    items: list[dict[str, object]] = []
    for number, horse_id, name, rank, time, win, place in (
        (1, "5001", "테스트원", 1, "75.2", "2.1", "1.2"),
        (2, "005002", "테스트투", 2, "76.0", "3.0", "1.4"),
    ):
        items.append(
            {
                "raceDt": "20260822",
                "raceNo": "1",
                "raceDs": "1200",
                "rccrsNm": "서울",
                "gtno": number,
                "hrno": horse_id,
                "hrnm": name,
                "engHrnm": f"TEST {number}",
                "bthd": "20230401",
                "gndrNm": "수" if number == 1 else "암",
                "pctyNm": "한국",
                "burdWgt": "55.5",
                "ratgSo": "40",
                "rchrWeg": "480(+2)" if number == 1 else "470(-3)",
                "jckyNm": "김기수",
                "trarNm": "이조교",
                "ownerNm": "박마주",
                "rk": rank,
                "raceRcd": time,
                "margin": "머리" if number == 2 else "-",
                "winPrice": win,
                "placePrice": place,
                "raceNm": "일반",
            }
        )
    return api_payload(items)


def detailed_result_payload() -> dict[str, object]:
    items: list[dict[str, object]] = []
    for number, horse_id, name, rank, time, jockey_id in (
        (1, "5001", "테스트원", 1, "01:15.2", "080001"),
        (2, "005002", "테스트투", 2, "01:16.0", "080002"),
    ):
        items.append(
            {
                "schdRaceDt": "2026.08.22",
                "schdRaceNo": "1R",
                "cndRaceDs": "1200M",
                "schdRccrsNm": "서울",
                "schdRaceDyCnt": "62",
                "schdRaceNm": "일반",
                "cndRaceClas": "국6등급",
                "cndBurdGb": "별정A",
                "cndAg": "3세",
                "cndGndr": "암수",
                "cndRatg": "0~40",
                "cndStrtPargTim": "10:35",
                "rsutRlStrtTim": "10:36:05",
                "rsutStrtTimChgRs": "안전 점검",
                "rsutWetr": "맑음",
                "rsutTrckStus": "건조 (3%)",
                "pthrGtno": number,
                "pthrHrno": horse_id,
                "pthrHrnm": name,
                "pthrBthd": "2023.04.01",
                "pthrGndr": "수" if number == 1 else "암",
                "pthrNtnlty": "한국",
                "pthrBurdWgt": "55.5",
                "pthrRatg": "40",
                "pthrWeg": "480(+2)" if number == 1 else "470(-3)",
                "pthrEquip": "망사눈가면",
                "hrmJckyId": jockey_id,
                "hrmJckyNm": "김기수" if number == 1 else "최기수",
                "hrmTrarId": f"07000{number}",
                "hrmTrarNm": "이조교",
                "hrmOwnerId": f"06000{number}",
                "hrmOwnerNm": "박마주",
                "rsutRk": rank,
                "rsutRaceRcd": time,
                "rsutMargin": "머리" if number == 2 else "-",
                "rsutRkPurse": "15000000" if number == 1 else "6000000",
                "rsutRkAdmny": "1500000" if number == 1 else "600000",
                "rsutRkRemk": "-",
                "rsutWinPrice": "2.1" if number == 1 else "3.0",
                "rsutQnlaPrice": "1.2" if number == 1 else "1.4",
            }
        )
    return api_payload(items)


def final_dividend_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "rcDate": "20260822",
                "rcNo": "1",
                "meet": "서울",
                "pool": "WIN",
                "chulNo": "1",
                "chulNo2": "0",
                "chulNo3": "0",
                "odds": "2.1",
            },
            {
                "rcDate": "20260822",
                "rcNo": "1",
                "meet": "서울",
                "pool": "QNL",
                "chulNo": "1",
                "chulNo2": "2",
                "chulNo3": "0",
                "odds": "4.8",
            },
        ]
    )


def migrated_session(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{tmp_path / 'race_day.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_race_day_parsing_helpers() -> None:
    assert parse_body_weight("480(+2)") == (480, 2)
    assert parse_body_weight("470(-3)") == (470, -3)
    assert parse_track_status("건조 (3%)") == ("건조", 3.0)


def test_zero_finish_time_and_position_are_treated_as_missing() -> None:
    item = ai_result_payload()["response"]["body"]["items"]["item"][0]
    item["rk"] = "0"
    item["raceRcd"] = "0"

    parsed = AiRaceResultItem.model_validate(item)

    assert parsed.finish_position is None
    assert parsed.finish_time_ms is None


def test_zero_final_dividend_is_treated_as_unsold() -> None:
    item = final_dividend_payload()["response"]["body"]["items"]["item"][0]
    item["odds"] = "0"

    parsed = FinalDividendItem.model_validate(item)

    assert parsed.odds is None


def test_ingest_race_day_connects_datasets_and_is_idempotent(tmp_path: Path) -> None:
    entry_payload = json.loads(ENTRY_FIXTURE.read_text(encoding="utf-8"))
    responses = {
        "/B551015/API154/racePlan": race_plan_payload(),
        "/B551015/API26_2/entrySheet_2": entry_payload,
        "/B551015/API155/raceResult": ai_result_payload(),
        "/B551015/API156/raceRsutDtl": detailed_result_payload(),
        "/B551015/API301/Dividend_rate_total": final_dividend_payload(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url.params.get("ServiceKey") == "secret-test-key"
            or request.url.params.get("serviceKey") == "secret-test-key"
        )
        return httpx.Response(200, json=responses[request.url.path], request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        first = ingest_race_day(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        second = ingest_race_day(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert list(first.stages) == [
            "race_plan",
            "entry_sheet",
            "ai_race_result",
            "detailed_race_result",
            "final_dividend",
        ]
        assert second.records_fetched == first.records_fetched == 9
        assert session.scalar(select(func.count()).select_from(Race)) == 1
        assert session.scalar(select(func.count()).select_from(RaceEntry)) == 2
        assert session.scalar(select(func.count()).select_from(RaceResult)) == 2
        assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 5
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 10
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 10

        race = session.scalar(select(Race))
        assert race is not None
        assert race.status == "completed"
        assert race.field_size == 2
        assert race.track_condition == "건조"
        assert race.track_moisture_percent == 3.0
        assert race.actual_start_at_ms is not None

        winning_entry = session.scalar(select(RaceEntry).where(RaceEntry.horse_number == 1))
        assert winning_entry is not None
        assert winning_entry.body_weight_kg == 480
        assert winning_entry.body_weight_change_kg == 2
        assert winning_entry.equipment == "망사눈가면"
        assert winning_entry.result is not None
        assert winning_entry.result.finish_position == 1
        assert winning_entry.result.finish_time_ms == 75_200
        assert winning_entry.result.prize_money_krw == 15_000_000

        qnl = session.scalar(
            select(OddsSnapshot).where(
                OddsSnapshot.bet_type == "QNL",
                OddsSnapshot.selection_key == "1-2",
            )
        )
        assert qnl is not None
        assert qnl.odds == 4.8
        assert all(run.status == "completed" for run in session.scalars(select(IngestionRun)))
        assert race_day_is_complete(
            session,
            race_date=race.race_date_local,
            meet=1,
        )


def test_result_data_exists_uses_lightweight_probe() -> None:
    payload = ai_result_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["numOfRows"] == "1"
        assert request.url.params["race_dt"] == "20260822"
        return httpx.Response(200, json=payload, request=request)

    with KraApiClient(
        "secret-test-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert result_data_exists(client, race_date="20260822", meet=1)
