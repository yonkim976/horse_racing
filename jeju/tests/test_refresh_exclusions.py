"""Every active event/profile table must enforce the deleted-horse contract."""
import sqlite3

import pytest

from jeju.refresh.run import check


TABLES = ('race_result_rows', 'running_trial_rows', 'daily_training_api_rows',
          'medical_api_rows', 'starting_exam_api_rows', 'horse_profile_observations')


@pytest.mark.parametrize('contaminated_table', TABLES)
def test_refresh_rejects_excluded_horse_in_every_active_table(contaminated_table):
    with sqlite3.connect(':memory:') as connection:
        for table in TABLES:
            connection.execute('CREATE TABLE ' + table + '(horse_id TEXT NOT NULL)')
        assert check(connection, {})['excluded_horse_absent'] is True
        connection.execute('INSERT INTO ' + contaminated_table + ' VALUES(?)', ('3005648',))
        with pytest.raises(AssertionError, match='Excluded horse reintroduced'):
            check(connection, {})
