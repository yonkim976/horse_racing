from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import polars as pl

from jeju.cli import JEJU_DIR, PREDICTIONS_DIR, output_directory, validate_complete_card


class JejuCliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pin = json.loads((JEJU_DIR / "config/replay_fixture.json").read_text())
        self.metadata = {"meet": 2}
        self.frame = pl.DataFrame(
            {
                "entry_id": [1, 2, 3],
                "race_id": [2026091801] * 3,
                "horse_id": ["a", "b", "c"],
                "event_date": ["2026-09-18"] * 3,
                "distance_m": [900] * 3,
                "field_size": [3] * 3,
                "horse_number": [1, 2, 3],
                "horse_name": ["가", "나", "다"],
                "jockey_name": ["기수1", "기수2", "기수3"],
                "burden_kg": [55.0] * 3,
                "required_feature": [0.1, 0.2, 0.3],
            }
        )
        self.pin["race_sizes"] = {"2026091801": 3}

    def test_complete_jeju_card_passes_and_partial_card_fails(self) -> None:
        validate_complete_card(self.frame, self.metadata, self.pin, {"required_feature"})
        incomplete = self.frame.with_columns(pl.lit(4).alias("field_size"))
        with self.assertRaisesRegex(ValueError, "incomplete card"):
            validate_complete_card(incomplete, self.metadata, self.pin, {"required_feature"})

    def test_meet_domain_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "meet=2"):
            validate_complete_card(self.frame, {"meet": 1}, self.pin, {"required_feature"})

    def test_output_must_be_fresh_and_inside_prediction_workspace(self) -> None:
        with tempfile.TemporaryDirectory(dir=PREDICTIONS_DIR, prefix="cli-test-") as temp:
            existing = Path(temp)
            with self.assertRaises(FileExistsError):
                output_directory(str(existing))
        with self.assertRaisesRegex(ValueError, "jeju/predictions"):
            output_directory(str(JEJU_DIR / "data/fixtures/overwrite-me"))


if __name__ == "__main__":
    unittest.main()
