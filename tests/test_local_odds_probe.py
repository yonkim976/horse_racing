import json
from datetime import date, datetime, timedelta

import httpx
import pytest

from horse_racing.jobs import local_odds_probe as job

DAY = date(2026, 10, 9)
START = datetime(2026, 10, 9, 13, 0, tzinfo=job.KST)


def schedule():
    return dict(meet=2, race_no=3, start_ms=job.stamp(START), source_start_ms=job.stamp(START))


def raw(**changes):
    return dict(
        rcDate=20261009,
        rcNo=3,
        meet="제주",
        pool="WIN",
        chulNo=1,
        chulNo2=0,
        chulNo3=0,
        odds=2.0,
        **changes,
    )


def payload(items, total=None, code="00"):
    return {
        "response": {
            "header": {"resultCode": code},
            "body": {
                "totalCount": len(items) if total is None else total,
                "pageNo": 1,
                "numOfRows": 20000,
                "items": {"item": items},
            },
        }
    }


@pytest.mark.parametrize("minutes", [16, 14, 12, 10, 8, 6, 4, 2, -10])
def test_exact_experiment_offsets(minutes):
    now = START - timedelta(minutes=minutes)
    assert job.due([schedule()], job.stamp(now)) == [(schedule(), minutes)]


@pytest.mark.parametrize("minutes", [17, 15, 1, 0, -1, -9, -12])
def test_outside_slots_not_backfilled(minutes):
    # 15 minutes is still a legitimate <=69s delivery delay for T-16.
    now = START - timedelta(minutes=minutes) + timedelta(seconds=11)
    assert job.due([schedule()], job.stamp(now)) == []


def test_dry_run_and_wrong_date_do_not_read_secrets_or_files(monkeypatch):
    monkeypatch.setattr(job, "Settings", lambda **_k: pytest.fail("secrets accessed"))
    monkeypatch.setattr(job, "secure_directory", lambda _p: pytest.fail("disk accessed"))
    assert job.execute(DAY) == 0
    assert job.execute(datetime.now(job.KST).date() + timedelta(days=1), apply=True) == 0


def test_public_time_field_is_not_actual_departure():
    rows = job.parse_schedule(
        [dict(raceDt=20261009, rccrsNm="제주", raceNo=3, strtPargTm="13:00", strtTm="13:05")],
        2,
        DAY,
        1,
    )
    assert rows[0][2] == rows[0][3] == job.stamp(START + timedelta(minutes=5))


def test_raw_empty_response_and_auth_not_saved(tmp_path):
    db = job.connect(tmp_path / "probe")

    def handler(request):
        assert request.url.path == "/B551015/API301/Dividend_rate_total"
        assert request.url.params["serviceKey"] == "test-secret"
        return httpx.Response(200, json=payload([]))

    with httpx.Client(
        base_url="https://apis.data.go.kr/B551015/", transport=httpx.MockTransport(handler)
    ) as client:
        items, ids, requested, received = job.request(db, client, "test-secret", "odds", 2, DAY)
    assert items == [] and len(ids) == 1 and requested <= received
    row = db.execute("SELECT * FROM responses").fetchone()
    assert row["valid"] == 1 and row["total_count"] == 0
    assert b"test-secret" not in row["payload"]
    assert len(row["sha256"]) == 64
    db.close()


def test_quota_archived_and_stops_without_retry(tmp_path):
    db = job.connect(tmp_path / "probe")
    with httpx.Client(
        base_url="https://apis.data.go.kr/B551015/",
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload([], code="22"))),
    ) as client:
        with pytest.raises(RuntimeError, match="source_quota_stop"):
            job.request(db, client, "test", "odds", 2, DAY)
    assert db.execute("SELECT count(*) FROM responses").fetchone()[0] == 1
    assert db.execute("SELECT result_code FROM responses").fetchone()[0] == "22"
    db.close()


def test_duplicate_wrong_day_wrong_meet_invalid_odds_rejected():
    for row in (
        {**raw(), "rcDate": 20261002},
        {**raw(), "meet": "서울"},
        {**raw(), "odds": "NaN"},
        {**raw(), "pool": "UNKNOWN"},
    ):
        with pytest.raises(ValueError):
            job.normalize([row], 2, DAY)
    with pytest.raises(ValueError, match="duplicate"):
        job.normalize([raw(), raw()], 2, DAY)


def test_same_values_retained_empty_not_deleted_and_replay_deduplicated(tmp_path):
    db = job.connect(tmp_path / "probe")
    r = schedule()
    db.execute(
        "INSERT INTO schedule VALUES(?,?,?,?,?,1)", (2, 3, r["start_ms"], r["source_start_ms"], 1)
    )
    values = job.normalize([raw()], 2, DAY)[3]
    for offset in (16, 14):
        at = job.stamp(START - timedelta(minutes=offset))
        job.save_observation(db, r, offset, values, [1], at, at + 100)
        job.save_observation(db, r, offset, values, [1], at, at + 100)
    at = job.stamp(START - timedelta(minutes=12))
    job.save_observation(db, r, 12, [], [2], at, at + 100)
    result = job.comparison(db)[0]
    assert result["observations"] == 3
    assert result["pre_present"] == 2 and result["pre_empty"] == 1
    assert result["changed_common_selections"] == [0]
    assert result["conclusion"] == "pre_scheduled_start_values_observed"
    db.close()


def test_changes_common_selection_and_cross_start_not_counted_as_pre(tmp_path):
    db = job.connect(tmp_path / "probe")
    r = schedule()
    db.execute(
        "INSERT INTO schedule VALUES(?,?,?,?,?,1)", (2, 3, r["start_ms"], r["source_start_ms"], 1)
    )
    for offset, value in ((16, 2), (14, 3)):
        at = job.stamp(START - timedelta(minutes=offset))
        job.save_observation(
            db, r, offset, job.normalize([{**raw(), "odds": value}], 2, DAY)[3], [1], at, at + 100
        )
    job.save_observation(
        db, r, 2, job.normalize([raw()], 2, DAY)[3], [1], r["start_ms"] - 100, r["start_ms"] + 100
    )
    result = job.comparison(db)[0]
    assert result["pre_present"] == 2 and result["changed_common_selections"] == [1]
    assert result["conclusion"] == "pre_scheduled_start_changes_observed"
    db.close()


def test_transport_error_is_not_valid_empty(tmp_path):
    db = job.connect(tmp_path / "probe")

    def failed(request):
        raise httpx.ReadTimeout("private exception URL", request=request)

    with httpx.Client(
        base_url="https://apis.data.go.kr/B551015/", transport=httpx.MockTransport(failed)
    ) as client:
        with pytest.raises(httpx.ReadTimeout):
            job.request(db, client, "test-secret", "odds", 2, DAY)
    row = db.execute("SELECT * FROM responses").fetchone()
    assert row["valid"] == 0 and row["error"] == "ReadTimeout"
    assert "private" not in json.dumps(dict(row))
    db.close()
