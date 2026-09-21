from datetime import date
import polars as pl
from scripts.run_jeju_rolling_zero import quarter_start, rolling_parts


def test_quarter_arithmetic_crosses_year_boundaries():
    assert quarter_start(2023, -1) == date(2022, 7, 1)
    assert quarter_start(2023, 0) == date(2022, 10, 1)
    assert quarter_start(2023, 5) == date(2024, 1, 1)


def test_rolling_roles_exclude_future_and_mask_target_labels():
    dates = [date(2018, 8, 30), date(2018, 8, 31), date(2022, 6, 30), date(2022, 7, 1), date(2022, 9, 30), date(2022, 10, 1), date(2022, 12, 31), date(2023, 1, 1), date(2023, 3, 31), date(2023, 4, 1)]
    f = pl.DataFrame({'event_date': dates, 'race_id': list(range(10)), 'horse_id': ['a']*10, 'finish_position': [1.]*10, 'label_top3': [1]*10})
    p = rolling_parts(f, 2023, 1)
    assert p['fit']['race_id'].to_list() == [1, 2]
    assert p['tune']['race_id'].to_list() == [3, 4]
    assert p['calibration']['race_id'].to_list() == [5, 6]
    assert p['prediction']['race_id'].to_list() == [7, 8]
    assert p['prediction']['label_top3'].null_count() == 2
    assert p['prediction']['finish_position'].null_count() == 2
