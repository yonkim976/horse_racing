"""Manual race notes attach only to their exact published starter field."""

from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from horse_racing.web import race_analysis
from horse_racing.web.race_analysis import attach_race_commentary

WEB_ROOT = Path(__file__).parents[1] / "src" / "horse_racing" / "web"


def matching_page(commentary_index: int = 0) -> SimpleNamespace:
    commentary = deepcopy(race_analysis._race_commentary_assets()[commentary_index])
    race_data = commentary["race"]
    selected_race = SimpleNamespace(
        date=race_data["date"],
        meet_code=race_data["meet_code"],
        number=race_data["number"],
        distance=race_data["distance"],
        field_size=len(race_data["runners"]),
        status="scheduled",
    )
    runners = [
        SimpleNamespace(
            number=runner["number"],
            horse=runner["horse"],
            win_prob=0.123,
            win_pct="12.3%",
            win_label="축 후보",
            prediction_rank=3,
        )
        for runner in race_data["runners"]
    ]
    return SimpleNamespace(
        selected_race=selected_race,
        runners=runners,
        race_commentary=None,
    )


def test_commentary_attaches_exact_match_after_skipping_other_races(monkeypatch) -> None:
    page = matching_page()
    expected = deepcopy(race_analysis._race_commentary_assets()[0])
    other = deepcopy(expected)
    other["race"]["number"] = 4
    monkeypatch.setattr(race_analysis, "_race_commentary_assets", lambda: [other, expected])

    attach_race_commentary(page)

    assert page.race_commentary["summary"] == expected["summary"]
    assert page.race_commentary["source_url"] == (
        "https://race.kra.co.kr/raceFastreport/ChuljumaWeightList.do"
        "?Act=03&Sub=4&meet=1&date=20261003&rcNo=5"
    )


def test_weight_source_url_uses_only_the_matched_race_identity(monkeypatch) -> None:
    page = matching_page()
    other = deepcopy(race_analysis._race_commentary_assets()[0])
    other["race"].update(date="2026-10-04", meet_code=2, number=6)
    page.selected_race.date = "2026-10-04"
    page.selected_race.meet_code = 2
    page.selected_race.number = 6
    monkeypatch.setattr(race_analysis, "_race_commentary_assets", lambda: [other])

    attach_race_commentary(page)

    assert page.race_commentary["source_url"].endswith(
        "?Act=03&Sub=4&meet=2&date=20261004&rcNo=6"
    )


@pytest.mark.parametrize("malformed", [False, True])
def test_missing_or_malformed_optional_json_hides_commentary(
    monkeypatch, malformed: bool
) -> None:
    page = matching_page()
    race_analysis._race_commentary_assets.cache_clear()
    if malformed:
        monkeypatch.setattr(
            Path, "open", lambda *_args, **_kwargs: StringIO("{"), raising=True
        )
    else:
        def missing(*_args, **_kwargs):
            raise FileNotFoundError("missing optional commentary")

        monkeypatch.setattr(Path, "open", missing, raising=True)

    try:
        attach_race_commentary(page)
        assert page.race_commentary is None
    finally:
        race_analysis._race_commentary_assets.cache_clear()


def test_non_object_item_in_valid_json_list_is_skipped(monkeypatch) -> None:
    page = matching_page()
    monkeypatch.setattr(race_analysis, "_race_commentary_assets", lambda: [None])

    attach_race_commentary(page)

    assert page.race_commentary is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date", "2026-10-04"),
        ("meet_code", 2),
        ("number", 4),
        ("distance", 1000),
        ("field_size", 10),
    ],
)
def test_commentary_is_hidden_when_race_identity_differs(field: str, value: object) -> None:
    page = matching_page()
    setattr(page.selected_race, field, value)

    attach_race_commentary(page)

    assert page.race_commentary is None


@pytest.mark.parametrize(("field", "value"), [("number", 12), ("horse", "다른 말")])
def test_commentary_is_hidden_when_any_runner_identity_differs(
    field: str, value: object
) -> None:
    page = matching_page()
    setattr(page.runners[0], field, value)

    attach_race_commentary(page)

    assert page.race_commentary is None


def test_attach_does_not_change_current_model_probabilities_or_labels() -> None:
    page = matching_page()
    current_values = [
        (runner.win_prob, runner.win_pct, runner.win_label, runner.prediction_rank)
        for runner in page.runners
    ]

    attach_race_commentary(page)

    assert [
        (runner.win_prob, runner.win_pct, runner.win_label, runner.prediction_rank)
        for runner in page.runners
    ] == current_values
    assert "70.8" not in str(page.race_commentary)


def test_completed_commentary_is_labeled_and_template_escapes_text() -> None:
    page = matching_page()
    page.selected_race.status = "completed"
    attach_race_commentary(page)
    page.race_commentary["summary"] = "<script>alert(1)</script>"
    environment = Environment(
        loader=FileSystemLoader(WEB_ROOT / "templates"),
        autoescape=select_autoescape(("html",)),
    )

    rendered = environment.get_template("_race_commentary.html").render(page=page)

    assert "경주 전 참고 분석" in rendered
    assert "경주 결과를 반영한 평가는 아닙니다" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered
    assert "2026-10-03 14:06 KST 기준" in rendered
    assert "이 분석에서 참고한 모델 이력 기준 2026-09-13" in rendered
    assert '<details class="rc-details">' in rendered
    assert "공식 출전마 체중표" in rendered
    assert 'href="https://race.kra.co.kr/raceFastreport/' in rendered


def test_both_analysis_templates_load_shared_note_and_stylesheet_before_runner_list() -> None:
    desktop = (WEB_ROOT / "templates" / "analysis.html").read_text(encoding="utf-8")
    mobile = (WEB_ROOT / "templates" / "mobile" / "analysis.html").read_text(encoding="utf-8")

    assert "race-commentary.css') }}?v=2" in desktop
    assert "race-commentary.css') }}?v=2" in mobile
    assert desktop.index('{% include "_race_commentary.html" %}') < desktop.index(
        '{% include "_analysis_field.html" %}'
    )
    assert mobile.index('{% include "_race_commentary.html" %}') < mobile.index(
        "data-runner-shell"
    )


def test_jeju_commentary_matches_exact_field_and_uses_jeju_source_url(monkeypatch) -> None:
    assets = deepcopy(race_analysis._race_commentary_assets())
    page = matching_page(commentary_index=1)
    monkeypatch.setattr(race_analysis, "_race_commentary_assets", lambda: assets)

    attach_race_commentary(page)

    assert page.selected_race.date == "2026-10-03"
    assert page.selected_race.meet_code == 2
    assert page.selected_race.number == 6
    assert page.selected_race.distance == 1200
    assert page.selected_race.field_size == 8
    assert page.race_commentary["source_url"] == (
        "https://race.kra.co.kr/raceFastreport/ChuljumaWeightList.do"
        "?Act=03&Sub=4&meet=2&date=20261003&rcNo=6"
    )
    assert [(item["number"], item["horse"], item["kg"], item["change_kg"])
            for item in page.race_commentary["body_weights"]] == [
        (1, "청룡에이스", 267, 3),
        (2, "노형로", 266, -3),
        (3, "천하무적", 270, 1),
        (4, "수호초", 275, 3),
        (5, "문무태왕", 268, -3),
        (6, "황해바람", 285, 2),
        (7, "영상대부", 302, 6),
        (8, "청룡불빛", 262, 8),
    ]


@pytest.mark.parametrize("mismatch", ["meet", "runner"])
def test_jeju_commentary_is_hidden_when_identity_mismatches(mismatch: str) -> None:
    page = matching_page(commentary_index=1)
    if mismatch == "meet":
        page.selected_race.meet_code = 1
    else:
        page.runners[0].horse = "다른 말"

    attach_race_commentary(page)

    assert page.race_commentary is None


def test_seoul_seven_commentary_matches_exact_roster_weights_and_source(monkeypatch) -> None:
    assets = deepcopy(race_analysis._race_commentary_assets())
    assert [(item["race"]["meet_code"], item["race"]["number"]) for item in assets] == [
        (1, 5), (2, 6), (1, 7)
    ]
    page = matching_page(commentary_index=2)
    monkeypatch.setattr(race_analysis, "_race_commentary_assets", lambda: assets)

    attach_race_commentary(page)

    assert page.selected_race.date == "2026-10-03"
    assert page.selected_race.meet_code == 1
    assert page.selected_race.number == 7
    assert page.selected_race.distance == 1800
    assert page.selected_race.field_size == 11
    assert page.race_commentary["source_url"] == (
        "https://race.kra.co.kr/raceFastreport/ChuljumaWeightList.do"
        "?Act=03&Sub=4&meet=1&date=20261003&rcNo=7"
    )
    assert [(item["number"], item["horse"], item["kg"], item["change_kg"])
            for item in page.race_commentary["body_weights"]] == [
        (1, "벌교의스타", 527, 3),
        (2, "허쉬대보", 509, 4),
        (3, "차밍퀸", 473, -4),
        (4, "마이머닝스", 530, 6),
        (5, "스터닝플래터", 500, 9),
        (6, "울트라드래곤", 494, -6),
        (7, "베스트토르", 483, 2),
        (8, "흥행돌풍", 457, 4),
        (9, "마이티숀", 454, -17),
        (10, "킹마스터", 542, 4),
        (11, "프로시드", 498, 18),
    ]


@pytest.mark.parametrize("mismatch", ["race", "runner"])
def test_seoul_seven_commentary_is_hidden_when_identity_mismatches(mismatch: str) -> None:
    page = matching_page(commentary_index=2)
    if mismatch == "race":
        page.selected_race.number = 5
    else:
        page.runners[0].horse = "다른 말"

    attach_race_commentary(page)

    assert page.race_commentary is None
