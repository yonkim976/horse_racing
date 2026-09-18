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


def running_trial_video_url(
    *, meet_code: int, trial_date: date, trial_race_number: int
) -> str | None:
    """Return the official KRA player link for a running trial.

    KRA uses the same player identity as ordinary races, with ``vod_type=t``.
    The player itself reports when an older or not-yet-published video is
    unavailable, so the application can expose one stable official link for
    every supported trial without storing volatile media URLs.
    """
    if meet_code not in (1, 2, 3) or trial_race_number < 1:
        return None
    query = urlencode(
        {
            "meet": meet_code,
            "rcdate": trial_date.strftime("%Y%m%d"),
            "rcno": trial_race_number,
            "vod_type": "t",
        }
    )
    return f"https://kraplayer.starplayer.net/kra/vod/starplayer.php?{query}"
