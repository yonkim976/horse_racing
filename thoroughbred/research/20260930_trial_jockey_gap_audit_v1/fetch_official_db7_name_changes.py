"""Preserve official KRA db7 proof for historical RPT horse-name differences.

The API and official trial score table remain the canonical event identity. This
script records db7 name changes as historical explanation, never as a join key.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WEB_ROWS = HERE / "official_web_name_conflicts_18.jsonl"
RAW = HERE / "raw_official_name_change_db7"
OUTPUT = HERE / "rpt_name_discrepancy_review.jsonl"
MANIFEST = HERE / "rpt_name_discrepancy_review_manifest.json"
URL = "https://race.kra.co.kr/dbdata/fileDownLoad.do"
MAX_RESPONSE_BYTES = 2_000_000

# (RPT historical name, API/current name): (meet, monthly db7 filename, change date)
CHANGES = {
    ("더스트롱", "라이언글로리"): (1, "20150401sdb7.txt", "2015.03.18"),
    ("퀸즈골드", "골드마인"): (1, "20151201sdb7.txt", "2015.11.04"),
    ("원쿨킹", "내가잘나가"): (1, "20161101sdb7.txt", "2016.10.29"),
    ("황금빛로드", "성웅"): (1, "20161101sdb7.txt", "2016.10.29"),
    ("회색유령", "체인지라떼"): (1, "20170101sdb7.txt", "2016.12.02"),
    ("과천킬러", "함양산삼"): (1, "20181101sdb7.txt", "2018.10.11"),
    ("탭댄스엑스프레스", "천사박"): (1, "20190701sdb7.txt", "2019.06.26"),
    ("몬스터브룸", "모신나강"): (3, "20220301bdb7.txt", "2022.02.10"),
    ("라온포스트", "렉스여"): (3, "20240901bdb7.txt", "2024.08.09"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class SameHostRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != "race.kra.co.kr":
            raise ValueError("KRA 외부 리다이렉트를 거부합니다")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def source_url(meet: int, filename: str) -> str:
    region = "seoul" if meet == 1 else "busan"
    remote_path = f"chollian/{region}/jungbo/horse_name_chg/{filename}"
    return URL + "?" + urlencode({"fn": remote_path, "meet": meet})


def main() -> None:
    web_bytes = WEB_ROWS.read_bytes()
    rows = [json.loads(line) for line in web_bytes.splitlines() if line]
    if len(rows) != 18 or len({r["participant_row_id"] for r in rows}) != 18:
        raise ValueError("공식 웹 대조 원장이 18개 고유 행이어야 합니다")

    RAW.mkdir(exist_ok=True)
    files = {}
    opener = build_opener(SameHostRedirectHandler())
    for meet, filename, _ in sorted(set(CHANGES.values())):
        path = RAW / filename
        url = source_url(meet, filename)
        if path.exists():
            body = path.read_bytes()
        else:
            request = Request(url, headers={"User-Agent": "horse-racing-data-platform/0.1"})
            with opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError(f"공식 db7 HTTP {response.status}: {filename}")
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if not body or len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(f"공식 db7 응답 크기 오류: {filename}")
            path.write_bytes(body)
        text = body.decode("cp949")
        files[(meet, filename)] = {
            "path": relative(path), "sha256": sha256(body), "url": url,
            "text": text,
        }

    output_rows = []
    for row in rows:
        old = row["rpt_horse_name_candidate"]
        new = row["api_horse_name"]
        if row["api_horse_id"] != row["official_horse_id"] or new != row["official_horse_name"]:
            raise ValueError(f"API/공식 웹 말 신원 불일치: {row['participant_row_id']}")
        proof = CHANGES.get((old, new))
        result = {
            "participant_row_id": row["participant_row_id"],
            "meet": row["meet"], "date": row["date"],
            "trial_no": row["trial_no"], "horse_program_no": row["horse_program_no"],
            "api_horse_id": row["api_horse_id"],
            "api_horse_name_canonical": new,
            "rpt_horse_name_historical_candidate": old,
            "official_web_source_file": row["official_web_source_file"],
            "official_web_source_sha256": row["official_web_source_sha256"],
        }
        if proof is None:
            result.update({
                "review_status": "name_difference_unresolved_no_individual_db7_proof",
                "official_db7_change_date": None,
                "official_db7_source_file": None,
                "official_db7_source_sha256": None,
                "official_db7_source_url": None,
                "official_db7_source_line": None,
            })
        else:
            meet, filename, change_date = proof
            if row["meet"] != meet:
                raise ValueError(f"db7 시행장 불일치: {old} → {new}")
            f = files[(meet, filename)]
            hits = [line.strip() for line in f["text"].splitlines()
                    if re.search(rf"(?<!\S){re.escape(old)}\s+{re.escape(new)}\s+.*?{re.escape(change_date)}(?:\s|$)", line)]
            if len(hits) != 1:
                raise ValueError(f"db7 변경행 검증 실패: {old} → {new}, {filename}, {len(hits)}건")
            result.update({
                "review_status": "official_db7_name_change_confirmed",
                "official_db7_change_date": change_date,
                "official_db7_source_file": f["path"],
                "official_db7_source_sha256": f["sha256"],
                "official_db7_source_url": f["url"],
                "official_db7_source_line": hits[0],
            })
        output_rows.append(result)

    confirmed = sum(r["review_status"] == "official_db7_name_change_confirmed" for r in output_rows)
    if confirmed != 13 or len({(r["rpt_horse_name_historical_candidate"], r["api_horse_name_canonical"])
                               for r in output_rows if r["review_status"] == "official_db7_name_change_confirmed"}) != 9:
        raise ValueError("기대했던 공식 마명변경 9쌍/13행과 다릅니다")
    output_bytes = ("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                              for r in output_rows) + "\n").encode("utf-8")
    manifest = {
        "source_web_rows": relative(WEB_ROWS), "source_web_rows_sha256": sha256(web_bytes),
        "official_db7_files": [{k: v for k, v in f.items() if k != "text"}
                               for _, f in sorted(files.items())],
        "rows": len(output_rows), "confirmed_name_change_rows": confirmed,
        "confirmed_distinct_name_changes": 9,
        "unresolved_rows": len(output_rows) - confirmed,
        "output": relative(OUTPUT), "output_sha256": sha256(output_bytes),
    }
    OUTPUT.write_bytes(output_bytes)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"official db7 confirmed: {confirmed}/18 rows, 9 distinct name changes; unresolved: {18-confirmed}")


if __name__ == "__main__":
    main()
