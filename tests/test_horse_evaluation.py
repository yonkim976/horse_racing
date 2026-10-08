from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult
from horse_racing.web.app import create_app
from horse_racing.web.horse_evaluation import (
    EvaluationStart,
    build_evaluation,
    evaluate_start,
    load_horse_evaluation,
    moisture_band,
    profile_metrics,
)

AS_OF = date(2026, 10, 8)
REFS = {
    "version": "test",
    "raw": {"1:2026:1200": [75.0, 2.0]},
    "moist": {"1:2026:1200": [76.0, 2.0]},
    "corrections": {"1:2026:1200:다습": 0.5},
}


def start(days: int = 10, **kwargs) -> EvaluationStart:
    return replace(
        EvaluationStart(AS_OF - timedelta(days=days), 1, 1, 1200, "국5", 4, 74_000, 12),
        **kwargs,
    )


def test_metrics_keep_missing_actual_starts_and_disjoint_trend() -> None:
    result = profile_metrics([None, 2.0, 4.0, 1.0, None, 3.0, 100.0])
    assert result["last"] is None
    assert result["mean3"] == 3
    assert result["best5"] == 4  # the 7th start never fills a missing recent start
    assert result["top2mean5"] == 3
    assert result["trend"] == 1
    assert result["std5"] == pytest.approx(1.52752523165)
    assert result["count3"] == 2
    assert profile_metrics([1.0])["top2mean5"] is None
    assert profile_metrics([1.0, 2.0])["std5"] is None
    assert profile_metrics([1.0, None, None, 2.0, 3.0])["trend"] is None


@pytest.mark.parametrize(
    ("moisture", "expected"),
    [
        (None, None),
        (0, None),
        (float("nan"), None),
        (101, None),
        (5, "건조"),
        (5.1, "양호"),
        (9, "양호"),
        (14, "다습"),
        (19, "포화"),
        (20, "불량"),
    ],
)
def test_moisture_boundaries(moisture, expected) -> None:
    assert moisture_band(moisture) == expected


def test_correction_missing_reference_and_invalid_records() -> None:
    value = evaluate_start(start(), REFS)
    assert value.raw_index == 0.5
    assert value.moist_index == 0.75
    assert value.corrected_seconds == 74.5
    assert value.supported
    assert value.correction_seconds == 0.5
    assert value.raw_reference == (75.0, 2.0)
    assert value.moist_reference == (76.0, 2.0)
    assert value.reference_gap == 1.5
    assert value.comparison == "과거 중앙기록보다 1.50초 빠름"
    assert "시간을 더함" in value.correction_explanation
    slower_track = dict(REFS, corrections={"1:2026:1200:다습": -0.75})
    assert "시간을 뺌" in evaluate_start(start(), slower_track).correction_explanation
    missing = evaluate_start(start(moisture=None), REFS)
    assert missing.corrected_seconds == 74
    assert missing.moist_index == 1  # separate historical reference; no time correction
    assert not missing.supported
    assert "함수율 미확인" in missing.status
    assert missing.correction_explanation == "보정 근거가 없어 원기록 유지"
    unsupported = evaluate_start(start(moisture=20), REFS)
    assert unsupported.corrected_seconds == 74
    assert "보정 근거 부족" in unsupported.status
    assert evaluate_start(start(race_date=date(2027, 1, 1)), REFS).moist_index is None
    for change in (
        {"finish_position": 93},
        {"disqualified": True},
        {"finish_time_ms": None},
        {"finish_time_ms": 10_000},
        {"race_date": date(2016, 1, 1)},
        {"meet": 2},
        {"outcome_remark": "실격"},
    ):
        assert evaluate_start(start(**change), REFS).moist_index is None


def test_profile_cutoff_no_history_and_best_evidence() -> None:
    starts = [start(i + 2, finish_time_ms=74_000 + i * 100) for i in range(12)]
    result = build_evaluation([start(0, finish_time_ms=60_000), *starts], as_of=AS_OF, refs=REFS)
    assert len(result.history) == 10
    assert result.cutoff == AS_OF - timedelta(days=2)
    assert result.best.source == starts[0]
    assert result.valid5 == 5
    assert result.supported5 == 5
    assert build_evaluation([], as_of=AS_OF, refs=REFS).status == "실전 이력 없음"
    # Adding a current/future result cannot change the historical profile.
    mutated = build_evaluation([start(-1), *starts], as_of=AS_OF, refs=REFS)
    assert result == mutated


def test_seconds_interpretations_use_actual_times_and_refuse_mixed_conditions() -> None:
    starts = [start(i + 2, finish_time_ms=74_000 + i * 1000) for i in range(6)]
    result = build_evaluation(starts, as_of=AS_OF, refs=REFS)
    assert result.metrics[1].interpretation == "1200m 기준 · 과거 중앙기록보다 0.50초 빠름"
    assert result.metrics[4].interpretation == "이전 3전보다 최근 3전 평균 3.00초 빨라짐"
    assert "표준편차 1.58초" in result.metrics[5].interpretation
    mixed_refs = dict(
        REFS,
        raw={**REFS["raw"], "1:2026:1400": [90, 3]},
        moist={**REFS["moist"], "1:2026:1400": [90, 3]},
    )
    starts[1] = replace(starts[1], distance=1400, finish_time_ms=85_000)
    mixed = build_evaluation(starts, as_of=AS_OF, refs=mixed_refs)
    assert "혼합" in mixed.metrics[1].interpretation
    assert "초 단위로 합쳐 해석하지 않음" in mixed.metrics[4].interpretation
    # Clipping the index at +10 must never turn into a false second difference.
    narrow = dict(REFS, moist={"1:2026:1200": [100, 0.5]})
    clipped = build_evaluation([start()], as_of=AS_OF, refs=narrow)
    assert clipped.metrics[0].corrected == 10
    assert "25.50초 빠름" in clipped.metrics[0].interpretation


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'evaluation.sqlite3'}")
    Base.metadata.create_all(engine)
    result = sessionmaker(bind=engine, expire_on_commit=False)
    yield result
    engine.dispose()


def seed(session: Session, source: EvaluationStart, horse: Horse, **kwargs) -> None:
    course = session.get(Racecourse, source.meet)
    if course is None:
        course = Racecourse(
            id=source.meet,
            kra_meet_code=source.meet,
            code=str(source.meet),
            name_ko="서울" if source.meet == 1 else "제주",
        )
        session.add(course)
    race = Race(
        racecourse=course,
        race_date_local=source.race_date,
        race_number=source.race_number,
        distance_m=source.distance,
        grade=source.grade,
        status="completed",
        track_moisture_percent=source.moisture,
    )
    entry = RaceEntry(race=race, horse=horse, horse_number=1, **kwargs)
    RaceResult(
        race_entry=entry,
        finish_position=source.finish_position,
        finish_time_ms=source.finish_time_ms,
        disqualified=source.disqualified,
        rank_remark=source.outcome_remark,
    )
    session.add(entry)


def test_loader_excludes_cards_cancellations_and_future_but_retains_stops(factory) -> None:
    with factory() as session:
        horse = Horse(kra_horse_id="1234567", name_ko="테스트", meet_code=1)
        session.add(horse)
        for i in range(12):
            seed(session, start(i + 2), horse)
        seed(session, start(0), horse)
        seed(session, start(1, finish_position=91), horse, scratched=True)
        # Imported stop marked scratched still occupies the most recent actual slot.
        seed(
            session,
            start(2, race_number=2, finish_position=92, outcome_remark="중지"),
            horse,
            scratched=True,
        )
        seed(session, start(3, race_number=2, finish_position=91), horse)
        session.flush()
        result = load_horse_evaluation(session, horse, as_of=AS_OF)
        assert len(result.history) == 10
        assert result.history[0].finish_label == "주행중지"
        assert result.metrics[0].corrected is None
        assert result.metrics[1].evidence == "유효 2 / 최근 3전"
        assert all(s.source.finish_position != 91 for s in result.history)
        horse.meet_code = 2
        assert load_horse_evaluation(session, horse, as_of=AS_OF) is None


def test_web_shows_evaluation_and_escapes_labels_without_affecting_jeju(factory, monkeypatch):
    monkeypatch.setattr("horse_racing.web.horse_evaluation.today_seoul", lambda: AS_OF)
    with factory() as session:
        horse = Horse(kra_horse_id="1234567", name_ko="평가마", meet_code=1)
        seed(session, start(10, grade="<script>alert(1)</script>"), horse)
        session.add(Horse(kra_horse_id="2234567", name_ko="신마", meet_code=1))
        session.add(Horse(kra_horse_id="3234567", name_ko="제주마", meet_code=2))
        session.commit()
    with TestClient(create_app(factory)) as client:
        page = client.get("/horses/1234567?tab=evaluation")
        assert page.status_code == 200
        assert 'id="horse-evaluation"' in page.text
        assert 'document.cookie = "hr-layout="' not in page.text
        assert "최근 능력" in page.text
        assert "2026-10-06까지" in page.text
        assert "단일 관측" in page.text
        assert "함수율 반영 지수" in page.text
        assert "실제 완주기록" in page.text
        assert "과거 중앙기록보다" in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
        assert "<script>alert(1)</script>" not in page.text
        assert 'href="/races/1"' in page.text
        assert "평가할 실전 이력이 없습니다" in client.get(
            "/horses/2234567?tab=evaluation",
        ).text
        assert "제공되는 평가표가 없습니다" in client.get(
            "/horses/3234567?tab=evaluation",
        ).text


def test_horse_detail_tabs_render_separate_sections_and_keep_empty_tabs(factory):
    from bs4 import BeautifulSoup

    with factory() as session:
        session.add(Horse(kra_horse_id="1234567", name_ko="탭 확인마", meet_code=1))
        session.commit()
    with TestClient(create_app(factory)) as client:
        default = BeautifulSoup(client.get("/horses/1234567").text, "html.parser")
        nav = default.select_one('nav[aria-label="말 상세 메뉴"]')
        links = nav.select("a")
        assert [a.text for a in links] == ["기본정보", "전적", "말별 평가표", "말이력"]
        assert nav.select_one('[aria-current="page"]').text == "기본정보"
        assert not default.select(".summary-grid, .history-jump")
        targets = ["horse-profile", "start-history", "horse-evaluation", "horse-history"]
        for link, target in zip(links, targets, strict=True):
            response = client.get(link["href"])
            assert response.status_code == 200
            soup = BeautifulSoup(response.text, "html.parser")
            assert soup.select_one('[aria-label="말 상세 메뉴"] [aria-current="page"]').text \
                == link.text
            assert soup.find(id=target)
            assert all(soup.find(id=other) is None for other in targets if other != target)
            assert not soup.select(".summary-grid")
        empty_history = client.get("/horses/1234567?tab=history")
        assert "말 이력이 없습니다" in empty_history.text
        invalid = BeautifulSoup(client.get("/horses/1234567?tab=unknown").text, "html.parser")
        assert invalid.select_one('[aria-label="말 상세 메뉴"] [aria-current="page"]').text \
            == "기본정보"
        assert client.get("/horses/nonexistent?tab=history").status_code == 404
