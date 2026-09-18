"""Guard observed Seoul source anomalies against fabricated finish labels."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_seoul_backfill import result_status  # noqa: E402
from finalize_seoul_backfill import EARLY_HEADING, WEIGHT_LINE  # noqa: E402


def test_unmapped_special_98_is_not_a_dead_heat_finish() -> None:
    assert result_status(98, 0) == (None, "unmapped_special_98")
    assert result_status(97, 0) == (None, "unmapped_special_code")


def test_numeric_rank_without_positive_time_is_unconfirmed() -> None:
    assert result_status(1, 0) == (None, "ranked_time_missing_unconfirmed")
    assert result_status(3, None) == (None, "ranked_time_missing_unconfirmed")
    assert result_status(1, 75.2) == (1, "finished")


def test_first_weight_text_layout_remains_parseable() -> None:
    heading = EARLY_HEADING.search(";TI03년 09월 06일 (토)    제01경주")
    assert heading is not None and heading.groups() == ("03", "09", "06", "1")
    weight = WEIGHT_LINE.match("      1     소리축제            404     -2     03.08.24")
    assert weight is not None and weight.groups() == ("1", "소리축제", "404", "-2")
