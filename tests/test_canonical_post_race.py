from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.db.models import RacePointSourceBatch
from horse_racing.jobs.canonical_post_race import (
    CORNER_POINTS,
    DETAIL_GROUPS,
    SourceMismatch,
    millis,
    normalize_day,
)
from horse_racing.parsers.dacom11 import Dacom11Entry, Dacom11Race


def sample(meet=1):
    names = {1: "서울", 2: "제주", 3: "부산경남", 4: "영천"}
    snapshot = [
        {
            "meet": meet,
            "race_day": "2026-10-05",
            "race_id": 101,
            "race_number": 1,
            "distance_m": 1200,
            "entry_id": 201,
            "horse_number": 1,
            "kra_horse_id": "0050001",
            "scratched": False,
            "finish_position": 1,
            "finish_time_ms": 80000,
        }
    ]
    raw = {
        "meet": names[meet],
        "rcDate": 20261005,
        "rcNo": 1,
        "rcDist": 1200,
        "chulNo": 1,
        "hrNo": "0050001",
        "hrName": "테스트",
        "ord": 1,
        "rcTime": 80,
    }
    if meet in (1, 2):
        raw.update({"sjS1fOrd": 1, "sj_3cOrd": 1, "sj_4cOrd": 1, "sjG1fOrd": 1})
        if meet == 1:
            raw.update(
                {
                    "seS1fAccTime": 14,
                    "se_3cAccTime": 25,
                    "se_4cAccTime": 45,
                    "seG3fAccTime": 40,
                    "seG1fAccTime": 65,
                    "sjG3fOrd": 1,
                }
            )
        else:
            raw.update(
                {
                    "jeS1fTime": 14,
                    "je_3cTime": 25,
                    "je_4cTime": 45,
                    "jeG3fTime": 40,
                    "jeG1fTime": 15,
                    "sjG3fOrd": 0,
                }
            )
    else:
        raw.update(
            {
                "buS1fAccTime": 14,
                "buG4fAccTime": 25,
                "buG3fAccTime": 40,
                "buG2fAccTime": 53,
                "buG1fAccTime": 65,
                "buS1fOrd": 1,
                "buG4fOrd": 1,
                "buG3fOrd": 1,
                "buG2fOrd": 1,
                "buG1fOrd": 1,
                "bu_3fGTime": 40,
                "bu_1fGTime": 15,
                "bu_2fGTime": 27,
                "buS1fTime": 14,
                "bu_4_2fTime": 28,
            }
        )
    points = {"S1F", "3C", "4C", "G1F"} if meet in (1, 2) else {"S1F", "G4F", "G3F", "G2F", "G1F"}
    group = {
        "rcNo": 1,
        **{f"corner_{c}": "1" if p in points else "-" for c, p in CORNER_POINTS[meet].items()},
    }
    detail = {
        "rcNo": 1,
        "rcDist": 1200,
        **{f: "1" if p in points else "-" for p, f in DETAIL_GROUPS[meet].items()},
    }
    data = {
        "sections": [raw],
        "groups": [group],
        "race_detail": [detail],
        "stewards": [
            {"meet": names[meet], "rcDate": 20261005, "rcNo": 1, "judgement": "공식 심판 리포트"}
        ],
    }
    entry = Dacom11Entry(
        1,
        "1",
        1,
        "테스트",
        "한",
        "수",
        3,
        55,
        None,
        None,
        None,
        None,
        finish_time_ms=80000,
        g3f_ms=40000,
        s1f_ms=14000,
        g1f_ms=15000,
    )
    if meet in (1, 2):
        entry.corner_times_ms = {"3C": 25000, "4C": 45000}
    races = [
        Dacom11Race(
            date(2026, 10, 5),
            1,
            names[meet],
            1200,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            entries=[entry],
        )
    ]
    return snapshot, data, races


def test_sections_can_refresh_before_delayed_stewards():
    snapshot, data, races = sample()
    data["stewards"] = []
    with pytest.raises(SourceMismatch):
        normalize_day(1, "2026-10-05", snapshot, data, races)
    result = normalize_day(1, "2026-10-05", snapshot, data, races, require_stewards=False)
    assert result["sections"] and result["groups"] and result["stewards"] == []


@pytest.mark.parametrize("meet", [1, 2, 3, 4])
def test_explicit_time_types_and_group_mapping(meet):
    snapshot, data, races = sample(meet)
    result = normalize_day(meet, "2026-10-05", snapshot, data, races)
    rows = {(r[1], r[2]): r for r in result["sections"]}
    assert rows[("G3F", "closing")][3] == 40000
    assert rows[("G1F", "closing")][3] == 15000
    assert (("G3F", "cumulative") in rows) == (meet != 2)
    assert rows[("S1F", "cumulative")][3] == 14000
    assert result["issues"] == []
    if meet in (1, 2):
        assert not any(r[1] == "G3F" for r in result["groups"])
    if meet in (3, 4):
        assert rows[("G3F", "closing")][4] is None
    if meet == 2:
        assert rows[("G3F", "closing")][4] is None
        assert rows[("G1F", "closing")][4] == 1  # passage rank, not closing-time rank


@pytest.mark.parametrize(
    "change,error",
    [
        ({"hrNo": "0059999"}, "horse_id_mismatch"),
        ({"rcTime": 81}, "db_finish_mismatch"),
        ({"ord": 2}, "db_rank_mismatch"),
        ({"seS1fAccTime": 15}, "text_section_mismatch"),
        ({"seS1fAccTime": 0}, "text_section_mismatch"),
    ],
)
def test_conflicting_source_rejected_before_write(change, error):
    snapshot, data, races = sample()
    data["sections"][0].update(change)
    with pytest.raises(SourceMismatch, match=error):
        normalize_day(1, "2026-10-05", snapshot, data, races)


def test_duplicate_api_runners_rejected():
    snapshot, data, races = sample()
    data["sections"].append(deepcopy(data["sections"][0]))
    with pytest.raises(SourceMismatch, match="duplicate_api_entry"):
        normalize_day(1, "2026-10-05", snapshot, data, races)


def test_busan_visitor_prefix_alias_keeps_source_and_id_validation():
    snapshot, data, races = sample()
    data["sections"][0]["hrName"] = "[영남]테스트"
    races[0].entries[0].horse_name = "[부]테스트"
    original = deepcopy(data)
    result = normalize_day(1, "2026-10-05", snapshot, data, races)
    assert result["sections"]
    assert result["issues"][0]["kind"] == "verified_busan_visitor_prefix_alias"
    assert data == original
    data["sections"][0]["hrNo"] = "0059999"
    with pytest.raises(SourceMismatch, match="horse_id_mismatch"):
        normalize_day(1, "2026-10-05", snapshot, data, races)


@pytest.mark.parametrize(
    "api_name,text_name,meet",
    [
        ("[영남]다른말", "[부]테스트", 1),
        ("[영남]테스트", "테스트", 1),
        ("[제주]테스트", "[부]테스트", 1),
        ("[영남]테스트", "[부]테스트", 2),
    ],
)
def test_prefix_normalization_never_weakens_horse_identity(api_name, text_name, meet):
    snapshot, data, races = sample(meet)
    data["sections"][0]["hrName"] = api_name
    races[0].entries[0].horse_name = text_name
    with pytest.raises(SourceMismatch, match="text_horse_name_mismatch"):
        normalize_day(meet, "2026-10-05", snapshot, data, races)


def test_blank_rank_dnf_requires_explicit_text_stopped_status():
    snapshot, data, races = sample(3)
    snapshot[0].update(finish_position=92, finish_time_ms=None)
    data["sections"][0].update(ord=92, rcTime=0)
    entry = races[0].entries[0]
    entry.finish_rank_raw = ""
    entry.finish_position = None
    entry.finish_time_ms = None
    with pytest.raises(SourceMismatch, match="text_stopped_status_mismatch"):
        normalize_day(3, "2026-10-05", snapshot, data, races)
    entry.margin_text = "0 주행중지"
    result = normalize_day(3, "2026-10-05", snapshot, data, races)
    assert result["issues"][0]["official_rank_code"] == 92
    assert snapshot[0]["finish_time_ms"] is None


def test_stopped_zero_time_and_99_positions_are_missing_not_real_records():
    snapshot, data, races = sample(1)
    snapshot[0].update(finish_position=92, finish_time_ms=None)
    raw = data["sections"][0]
    raw.update(ord=92, rcTime=0)
    for field in list(raw):
        if "Time" in field:
            raw[field] = 0
        if "Ord" in field:
            raw[field] = 99
    entry = races[0].entries[0]
    entry.finish_rank_raw = ""
    entry.finish_position = None
    entry.finish_time_ms = 0
    entry.margin_text = "주행중지"
    entry.s1f_ms = entry.g3f_ms = entry.g1f_ms = None
    entry.corner_times_ms = {}
    entry.passing_order_raw = "- - - - -99"
    result = normalize_day(1, "2026-10-05", snapshot, data, races)
    assert result["sections"] == []
    assert any(i["kind"] == "stopped_position_sentinel" for i in result["issues"])
    assert raw["sjG1fOrd"] == 99 and raw["rcTime"] == 0  # Original evidence unchanged.
    snapshot, data, races = sample(1)
    data["sections"][0]["sjS1fOrd"] = 99
    with pytest.raises(SourceMismatch, match="invalid_position"):
        normalize_day(1, "2026-10-05", snapshot, data, races)


def test_individual_rank_is_cross_checked_against_official_text():
    snapshot, data, races = sample()
    races[0].entries[0].passing_order_raw = "1- - - 1- 1- 1"
    normalize_day(1, "2026-10-05", snapshot, data, races)
    races[0].entries[0].passing_order_raw = "2- - - 1- 1- 1"
    with pytest.raises(SourceMismatch, match="text_rank_mismatch"):
        normalize_day(1, "2026-10-05", snapshot, data, races)


def test_cancelled_runner_absent_from_text_is_not_a_missing_finisher():
    snapshot, data, races = sample()
    cancelled = deepcopy(snapshot[0])
    cancelled.update(
        entry_id=202,
        horse_number=2,
        kra_horse_id="0050002",
        scratched=True,
        finish_position=94,
        finish_time_ms=None,
    )
    snapshot.append(cancelled)
    raw = {
        "rcNo": 1,
        "chulNo": 2,
        "hrNo": "0050002",
        "hrName": "취소마",
        "rcDist": 1200,
        "rcTime": 0,
        "ord": 94,
    }
    data["sections"].append(raw)
    result = normalize_day(1, "2026-10-05", snapshot, data, races)
    assert result["issues"][0]["kind"] == "scratched_no_section"
    assert all(r[0] != 202 for r in result["sections"])


def test_group_conflict_and_empty_steward_rejected():
    snapshot, data, races = sample()
    data["groups"][0]["corner_7"] = "2"
    with pytest.raises(SourceMismatch, match="api_group_conflict"):
        normalize_day(1, "2026-10-05", snapshot, data, races)
    snapshot, data, races = sample()
    data["stewards"][0]["judgement"] = ""
    with pytest.raises(SourceMismatch, match="empty_steward"):
        normalize_day(1, "2026-10-05", snapshot, data, races)


def test_official_group_preserved_without_inventing_unpublished_individual_rank():
    snapshot, data, races = sample(2)
    data["sections"][0].update(je_2cTime=14, sj_2cOrd=0)
    data["groups"][0]["corner_2"] = "1"
    data["race_detail"][0]["passrankG6f_2c"] = "1"
    races[0].entries[0].corner_times_ms["2C"] = 14000
    result = normalize_day(2, "2026-10-05", snapshot, data, races)
    assert result["issues"][0]["kind"] == "individual_rank_not_provided"
    assert next(r for r in result["sections"] if r[1] == "2C")[4] is None
    assert any(r[1] == "2C" for r in result["groups"])


def test_conflicting_sum_quarantined_without_deleting_source():
    snapshot, data, races = sample()
    data["sections"][0]["seG3fAccTime"] = 39
    original = deepcopy(data)
    result = normalize_day(1, "2026-10-05", snapshot, data, races)
    assert result["issues"][0]["kind"] == "time_sum_mismatch"
    assert not any(r[1] == "G3F" for r in result["sections"])
    assert data == original


def test_annual_batch_and_new_delta_coexist_in_model():
    engine = create_engine("sqlite:///:memory:")
    RacePointSourceBatch.__table__.create(engine)
    with Session(engine) as session:
        for file in ("annual.sqlite3", "later_day.json"):
            session.add(
                RacePointSourceBatch(
                    source_file=file,
                    source_sha256="a" * 64,
                    meet_code=1,
                    race_year=2026,
                    section_row_count=1,
                    passing_group_row_count=1,
                    loaded_at_ms=1,
                )
            )
        session.commit()


def test_exact_decimal_milliseconds():
    assert millis("62.3") == 62300
    assert millis(0) is None
    with pytest.raises(SourceMismatch):
        millis("NaN")
