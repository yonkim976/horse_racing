"""Official replay links, independent of whether KRA has published the video."""
from datetime import date
from urllib.parse import urlencode


def race_video_url(*, meet_code: int, race_date: date, race_number: int,
                   status: str) -> str | None:
    # Yeongcheon/player meet mapping is not verified. Do not guess it.
    if status != "completed" or meet_code not in (1, 2, 3) or race_number < 1:
        return None
    query = urlencode(dict(meet=meet_code, rcdate=race_date.strftime("%Y%m%d"),
                           rcno=race_number, vod_type="r"))
    return f"https://kraplayer.starplayer.net/kra/vod/starplayer.php?{query}"
