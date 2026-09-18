from __future__ import annotations

import json
from pathlib import Path

import pytest

import horse_racing.services.jeju_pregame_store as storage
from horse_racing.parsers.jeju_pregame import PregameParseError, full_timestamp, parse_page
from horse_racing.services.jeju_pregame_store import PregameStore, replay, timestamp_ms

FIX = Path(__file__).parent / "fixtures/jeju_pregame"
BASE = timestamp_ms("2026-09-16T12:00:00+09:00")
DAY = "2026-09-17"


def fixture(name):
    return (FIX / f"{name}.html").read_bytes()


@pytest.mark.parametrize("kind", ["schedule", "card", "changes", "weight_index", "weight", "track"])
def test_official_page_structures(kind):
    parsed = parse_page(kind, fixture(kind), "utf-8")
    assert parsed
    if kind == "schedule":
        assert len(parsed["races"]) == 22
    if kind == "card":
        assert len(parsed["runners"]) == 9
        assert parsed["runners"][0]["horse_id"] == "3104234"
    if kind == "weight_index":
        assert {r["race_date"] for r in parsed["races"]} == {"2026-09-12"}
    if kind == "track":
        assert parsed["effective_at"] == "2026-09-13T09:00:00+09:00"
        assert parsed["published_at"] is None


def test_rating_and_delta_not_concatenated():
    card = parse_page("card", fixture("card_rated"), "utf-8")
    assert card["runners"][0]["rating"] == 20
    assert card["runners"][0]["rating_delta"] == 0


def test_time_only_notice_does_not_invent_date():
    assert full_timestamp("11:35") is None
    assert full_timestamp("2026/09/17 11:35") == "2026-09-17T11:35:00+09:00"


def test_empty_changed_layout_not_treated_as_no_notices():
    with pytest.raises(PregameParseError):
        parse_page("changes", b"<html><table></table></html>", "utf-8")


def test_track_legend_not_current_moisture():
    body = fixture("track").replace("함수율 : 4%(건조)".encode(), b"")
    with pytest.raises(PregameParseError):
        parse_page("track", body, "utf-8")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = PregameStore(tmp_path)
    counter = [BASE]
    store.clock = lambda: counter[0]
    monkeypatch.setattr(storage, "parse_page", lambda kind, body, encoding: json.loads(body))

    def add(kind, payload, *, step=10, race=None, error=None):
        counter[0] += step
        return store.record(
            kind=kind,
            url="https://race.kra.co.kr/test",
            body=json.dumps(payload).encode(),
            requested_ms=counter[0] - 2,
            retrieved_ms=counter[0] - 1,
            status_code=200,
            request_race=race,
            error=error,
        )

    add(
        "schedule",
        dict(
            races=[
                dict(
                    race_date=DAY,
                    race_number=1,
                    scheduled_start_at=DAY + "T13:00:00+09:00",
                    declared_count=3,
                    listed_count=3,
                )
            ]
        ),
    )
    runners = [
        dict(
            horse_number=i,
            horse_id=str(i),
            horse_name=f"말{i}",
            jockey_id="old",
            jockey_name="기수A",
            burden_kg=55,
        )
        for i in [1, 2, 3]
    ]
    card = dict(race_date=DAY, race_number=1, runners=runners, complete=True)
    add("card", card, race=(DAY, 1))
    return store, add, counter, card


def race(store, cutoff):
    return replay(store, cutoff)["races"][0]


def notice(kind="withdrawal", **kwargs):
    return dict(
        kind=kind,
        race_date=DAY,
        race_number=1,
        horse_number=1,
        horse_name="말1",
        published_at="2026-09-16T10:00:00+09:00",
        notice_time_raw="10:00",
        **kwargs,
    )


def test_cutoff_uses_admission_not_download_or_backdated_notice(setup):
    store, add, clock, _ = setup
    p = add("changes", dict(notices=[notice()]))
    before = race(store, p["retrieved_ms"])
    assert before["eligible_numbers"] == [1, 2, 3]
    after = race(store, p["known_at_ms"])
    assert after["eligible_numbers"] == [2, 3]
    assert len(after["runners"]) == 3  # withdrawal preserved, not dropped from source field


def test_future_revision_does_not_change_old_replay(setup):
    store, add, clock, card = setup
    cutoff = clock[0]
    before = race(store, cutoff)
    card["runners"][0]["burden_kg"] = 59
    add("card", card, race=(DAY, 1))
    assert race(store, cutoff) == before
    assert race(store, clock[0])["runners"][0]["burden_kg"] == 59


def test_withdrawal_persists_after_notice_disappears(setup):
    store, add, clock, _ = setup
    add("changes", dict(notices=[notice()]))
    add("changes", dict(notices=[]))
    assert race(store, clock[0])["eligible_numbers"] == [2, 3]


def test_jockey_update_clears_unverified_id_and_preserves_old_replay(setup):
    store, add, clock, _ = setup
    before = clock[0]
    add(
        "changes",
        dict(
            notices=[
                notice(
                    "jockey_change",
                    old_jockey_name="기수A",
                    new_jockey_name="기수B",
                    new_burden_kg=54,
                )
            ]
        ),
    )
    runner = race(store, clock[0])["runners"][0]
    assert (runner["jockey_name"], runner["jockey_id"], runner["burden_kg"]) == ("기수B", None, 54)
    assert race(store, before)["runners"][0]["jockey_name"] == "기수A"


def test_notice_wrong_horse_does_not_remove_runner(setup):
    store, add, clock, _ = setup
    n = notice()
    n["horse_name"] = "다른말"
    add("changes", dict(notices=[n]))
    r = race(store, clock[0])
    assert r["eligible_numbers"] == [1, 2, 3]
    assert "notice_identity_mismatch" in r["issues"]


def test_invalid_latest_card_blocks_silent_fallback(setup):
    store, add, clock, _ = setup
    add("card", {}, race=(DAY, 1), error="partial response")
    r = race(store, clock[0])
    assert not r["declaration_complete"] and r["runners"] == []


def test_count_mismatch_and_card_removal_retained(setup):
    store, add, clock, card = setup
    card["runners"] = card["runners"][:-1]
    add("card", card, race=(DAY, 1))
    r = race(store, clock[0])
    assert not r["declaration_complete"]
    assert r["card_revision"]["removed"] == ["3"]


def test_previous_day_weight_and_track_cannot_fill_target(setup):
    store, add, clock, _ = setup
    add(
        "weight",
        dict(
            race_date="2026-09-12",
            race_number=1,
            runners=[
                dict(horse_number=1, horse_id="1", body_weight_kg=300, body_weight_delta_kg=2)
            ],
        ),
        race=("2026-09-12", 1),
    )
    add("track", dict(effective_at="2026-09-13T09:00:00+09:00", moisture_percent=4))
    r = race(store, clock[0])
    assert r["body_weight_rows"] == 0 and r["track"] is None


def test_same_race_weight_identity_mismatch_rejected(setup):
    store, add, clock, _ = setup
    add(
        "weight",
        dict(
            race_date=DAY,
            race_number=1,
            runners=[
                dict(horse_number=1, horse_id="other", body_weight_kg=300, body_weight_delta_kg=2)
            ],
        ),
        race=(DAY, 1),
    )
    r = race(store, clock[0])
    assert r["body_weight_rows"] == 0
    assert "weight_identity_mismatch" in r["issues"]


def test_requested_date_mismatch_recorded_as_error(setup):
    store, add, clock, card = setup
    p = add("card", card, race=("2026-09-18", 1))
    assert p["parsed"] is None and "does not match" in p["error"]


def test_raw_tampering_fails(setup):
    store, _, clock, _ = setup
    p = store.observations()[0]
    raw = store.root / "observations" / p["observation_id"] / "raw.html"
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="tampering"):
        replay(store, clock[0])


def test_incomplete_write_has_no_admission(setup):
    store, add, clock, _ = setup
    p = add("changes", dict(notices=[notice()]))
    (store.root / "observations" / p["observation_id"] / "admission.json").unlink()
    assert race(store, clock[0])["eligible_numbers"] == [1, 2, 3]


def test_no_after_start_replay_and_naive_cutoff_rejected(setup):
    store, _, _, _ = setup
    assert replay(store, timestamp_ms(DAY + "T13:00:00+09:00"))["races"] == []
    with pytest.raises(ValueError, match="zone"):
        timestamp_ms(DAY + "T12:00:00")


def test_same_time_conflicting_cards_fail_closed(setup):
    store, add, clock, card = setup
    card["runners"][0]["burden_kg"] = 57
    add("card", card, step=0, race=(DAY, 1))
    assert not race(store, clock[0])["declaration_complete"]


def test_positive_same_day_weight_track_and_notice_after_cutoff(setup):
    store, add, clock, _ = setup
    clock[0] = timestamp_ms(DAY + "T10:00:00+09:00")
    add("track", dict(effective_at=DAY + "T09:00:00+09:00", moisture_percent=8))
    add(
        "weight",
        dict(
            race_date=DAY,
            race_number=1,
            runners=[
                dict(horse_number=1, horse_id="1", body_weight_kg=300, body_weight_delta_kg=2)
            ],
        ),
        race=(DAY, 1),
    )
    n = notice()
    n["published_at"] = DAY + "T11:00:00+09:00"
    add("changes", dict(notices=[n]))
    r = race(store, clock[0])
    assert r["body_weight_rows"] == 1 and r["track"]["moisture_percent"] == 8
    assert r["eligible_numbers"] == [1, 2, 3]
    assert "notice_future_publication" in r["issues"]


def test_collector_does_not_follow_old_weight_links(tmp_path):
    import httpx

    from scripts.collect_jeju_pregame import collect

    paths = {
        "/chulmainfo/ChulmaDetailInfoList.do": "schedule",
        "/chulmainfo/chulmaDetailInfoChulmapyo.do": "card",
        "/raceFastreport/ChulmapyoChange.do": "changes",
        "/raceFastreport/ChuljumaWeightWeight.do": "weight_index",
        "/chulmainfo/trackView.do": "track",
    }
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("ChulmaDetailInfoList.do"):
            from bs4 import BeautifulSoup

            s = BeautifulSoup(fixture("schedule"), "html.parser")
            t = s.find("table")
            for row in t.select("tbody tr")[1:]:
                row.decompose()
            body = str(s).encode()
        else:
            body = fixture(paths[request.url.path])
        return httpx.Response(
            200, content=body, headers={"content-type": "text/html; charset=utf-8"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, result = collect(tmp_path, dates=[DAY], client=client)
    # This test is intentionally independent of calendar progression.
    assert all("ChuljumaWeightList" not in p for p in calls)
    assert result["errors"] == []


def test_export_is_replayable_and_refuses_overwrite(setup, tmp_path):
    from datetime import UTC, datetime

    from scripts.replay_jeju_pregame import export

    store, _, clock, _ = setup
    out = tmp_path / "export"
    cutoff = datetime.fromtimestamp(clock[0] / 1000, UTC).isoformat()
    result = export(store.root, cutoff, out)
    assert result == replay(store, clock[0])
    manifest = json.loads((out / "manifest.json").read_text())
    assert all(storage.digest((out / k).read_bytes()) == v for k, v in manifest.items())
    with pytest.raises(FileExistsError):
        export(store.root, cutoff, out)


def test_populated_official_notice_tables_parse_without_invented_date():
    body = """<table><caption>말취소내용</caption><tbody><tr>
    <td>출전취소</td><td>제주</td><td>2026/09/17</td><td>1</td><td>2</td>
    <td>이글킹</td><td>한상배</td><td>원유일</td><td>부상</td><td>11:35</td>
    </tr></tbody></table><table><caption>기수변경내용</caption><tbody><tr>
    <td>제주</td><td>2026/09/17</td><td>1</td><td>1</td><td>흑룡스타</td>
    <td>박재희</td><td>55</td><td>김홍권</td><td>54</td><td>변경</td>
    <td>2026/09/17 11:40</td></tr></tbody></table>"""
    notices = parse_page("changes", body.encode(), "utf-8")["notices"]
    assert notices[0]["horse_number"] == 2 and notices[0]["published_at"] is None
    assert notices[1]["new_burden_kg"] == 54
    assert notices[1]["new_jockey_name"] == "김홍권"
    assert notices[1]["published_at"] == "2026-09-17T11:40:00+09:00"
