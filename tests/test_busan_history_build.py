from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_busan_history import API_WEIGHT, RACE_HEADING, result_status


def test_special_outcomes_are_not_numeric_finishes() -> None:
    assert result_status(1, 75.2) == (1, "finished")
    assert result_status(91, 75.2) == (None, "disqualified")
    assert result_status(92, 0) == (None, "did_not_finish")
    assert result_status(93, 0) == (None, "start_excluded")
    assert result_status(94, 0) == (None, "race_excluded")
    assert result_status(95, 0) == (None, "scratched")
    assert result_status(99, 0) == (None, "void")
    assert result_status(0, 0) == (None, "void_or_unresulted")


def test_historical_weight_and_race_heading() -> None:
    match = API_WEIGHT.match("433(+5)")
    assert match is not None and match.groups() == ("433", "+5")
    assert API_WEIGHT.match("430()").groups() == ("430", "")
    assert API_WEIGHT.match("0()") is None
    for heading in ("제목 : 06년 01월 06일 (금) 제01경주",
                    "경주일: 2006.01.06   1 경주"):
        assert RACE_HEADING.search(heading) is not None
