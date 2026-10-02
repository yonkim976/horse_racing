from __future__ import annotations

import hashlib
import json
from pathlib import Path

from horse_racing.db.models import SourceDocument
from scripts.backfill_api78_equipment_history import SavedDocument, _cached_pages


def test_cached_pages_keeps_local_and_remote_run_ids_separate(tmp_path: Path) -> None:
    payload = {
        "response": {
            "body": {
                "items": {
                    "item": {
                        "raceDt": "2017년01월07일(토)",
                        "raceNo": "제1경주",
                        "gtno": "1",
                        "hrnm": "테스트마",
                        "equipCrs": "망사눈+",
                    }
                },
                "pageNo": 1,
                "numOfRows": 1000,
                "totalCount": 1,
            }
        }
    }
    body = json.dumps(payload).encode()
    raw_path = tmp_path / "card.json"
    raw_path.write_bytes(body)
    params = json.dumps({"race_dt": "20170107", "rccrs_cd": 1, "pageNo": 1})

    def saved(path: Path) -> SavedDocument:
        return SavedDocument(
            document=SourceDocument(
                ingestion_run_id=7,
                source_url="https://example.test/API78/chulmainfo",
                endpoint="/API78/chulmainfo",
                operation="chulmainfo",
                request_params_json=params,
                requested_at_ms=1,
                retrieved_at_ms=2,
                http_status_code=200,
                content_type="application/json",
                response_bytes=len(body),
                local_path=str(path),
                sha256=hashlib.sha256(body).hexdigest(),
            ),
            run_status="completed",
            run_data_type="equipment_history_api78",
        )

    pages = _cached_pages(
        {"local": [saved(tmp_path / "missing.json")], "remote": [saved(raw_path)]}
    )

    assert pages is not None
    assert len(pages) == 1
    assert pages[0].body == body
