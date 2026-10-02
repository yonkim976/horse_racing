import json

import pytest

from scripts.sync_trainer_affiliations import parse_api_response


def _response(items: list[dict]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "totalCount": len(items),
                    "items": {"item": items},
                },
            }
        },
        ensure_ascii=False,
    ).encode()


def test_api_response_keeps_only_active_trainers() -> None:
    rows = [
        {
            "trNo": f"{number:06d}",
            "trName": f"조교사{number}",
            "meet": "서울",
            "part": number,
            "spDate": "-",
        }
        for number in range(1, 11)
    ]
    rows.append(
        {"trNo": "999999", "trName": "퇴직조교사", "meet": "서울", "part": 11, "spDate": "20260101"}
    )
    parsed = parse_api_response(_response(rows), 1)
    assert len(parsed) == 10
    assert parsed[0].kra_trainer_id == "000001"
    assert parsed[0].meet_code == 1
    assert parsed[0].stable_part == 1
    assert all(row.stats_as_of is None for row in parsed)


def test_api_response_rejects_wrong_meet() -> None:
    rows = [
        {
            "trNo": f"{number:06d}",
            "trName": f"조교사{number}",
            "meet": "영남",
            "part": number,
            "spDate": "-",
        }
        for number in range(1, 11)
    ]
    with pytest.raises(ValueError, match="Unexpected meet label"):
        parse_api_response(_response(rows), 1)
