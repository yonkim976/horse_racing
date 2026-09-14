from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from horse_racing.web.race_video import race_video_url


@pytest.mark.parametrize('meet,number', [(2, 7), (2, 1), (3, 1), (3, 9), (1, 1)])
def test_replay_identity(meet, number):
    url = race_video_url(meet_code=meet, race_date=date(2026, 9, 11),
                         race_number=number, status='completed')
    parsed = urlparse(url)
    assert parsed.netloc == 'kraplayer.starplayer.net'
    assert parse_qs(parsed.query) == dict(meet=[str(meet)], rcdate=['20260911'],
                                       rcno=[str(number)], vod_type=['r'])


@pytest.mark.parametrize('status,meet', [('scheduled', 2), ('cancelled', 3),
                                        ('completed', 4), ('unknown', 1)])
def test_no_replay_for_unfinished_or_unverified_meet(status, meet):
    assert race_video_url(meet_code=meet, race_date=date(2026, 9, 11),
                          race_number=1, status=status) is None
