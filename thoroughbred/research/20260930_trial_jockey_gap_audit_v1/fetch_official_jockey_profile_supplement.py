"""Preserve the official profile for a Jeju jockey observed in Seoul trials."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw_official_jockey_profile_003097.html"
OUTPUT = HERE / "official_jockey_profile_supplement.jsonl"
MANIFEST = HERE / "official_jockey_profile_supplement_manifest.json"
URL = "https://race.kra.co.kr/jockey/ProfilePersonItem.do"
FORM = {"meet": "2", "Act": "06", "Sub": "7", "hrNo": "", "jkNo": "003097",
        "trNo": "", "retireYn": ""}


class SameHostRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != "race.kra.co.kr":
            raise ValueError("KRA 외부 리다이렉트를 거부합니다")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    if RAW.exists():
        payload = RAW.read_bytes()
    else:
        request = Request(URL, data=urlencode(FORM).encode("ascii"), method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        opener = build_opener(SameHostRedirectHandler())
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or urlparse(response.url).hostname != "race.kra.co.kr":
                raise ValueError("Unexpected official jockey profile response")
            payload = response.read(2_000_001)
        if not payload or len(payload) > 2_000_000:
            raise ValueError("Official jockey profile response size invalid")
        RAW.write_bytes(payload)

    html = payload.decode("euc-kr")
    expected = [
        r"<title>기수프로필_기수정보_제주경마</title>",
        r'name="jkNo"\s+value=\s*"003097"',
        r'name="meet"\s+value=\s*"2"',
        r"<span>성명</span>김동규",
        r"<span>데뷔일자</span>2026/08/03",
    ]
    if any(re.search(pattern, html) is None for pattern in expected):
        raise ValueError("Official jockey profile identity did not match")
    row = {
        "entity_type": "jockey", "official_jockey_id": "003097",
        "official_jockey_name": "김동규", "profile_meet": 2,
        "profile_meet_label": "제주", "debut_date": "2026-08-03",
        "review_status": "official_profile_confirmed_cross_venue_trial_jockey",
        "profile_source_file": rel(RAW), "profile_source_sha256": sha(payload),
        "profile_source_url": URL, "profile_request_form": FORM,
    }
    output_bytes = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    OUTPUT.write_bytes(output_bytes)
    MANIFEST.write_text(json.dumps({
        "profile_source_file": rel(RAW), "profile_source_sha256": sha(payload),
        "profile_source_url": URL, "profile_request_form": FORM,
        "output": rel(OUTPUT), "output_sha256": sha(output_bytes), "rows": 1,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("official profile confirmed: 003097 김동규, meet=2 제주")


if __name__ == "__main__":
    main()
