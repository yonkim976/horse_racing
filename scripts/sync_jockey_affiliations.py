"""Refresh complete official active jockey rosters; dry-run unless --apply is set.

API307's open registration alone is insufficient: KRA's active web roster must
also include each jockey. Race venues are never used to infer base affiliation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, text

from horse_racing.config import get_settings
from horse_racing.db.models import Jockey, JockeyAffiliationSnapshot

SOURCE = "https://race.kra.co.kr/jockey/ProfileJockeyListActive.do"
API_SOURCE = "https://apis.data.go.kr/B551015/API307/jockeyInfo"
MEETS = {1: "서울", 3: "영남", 2: "제주"}
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Affiliation:
    kra_jockey_id: str
    name_ko: str
    meet_code: int
    source_url: str
    source_sha256: str
    api_source_url: str
    api_sha256: str
    debut_date: str | None = None
    riding_weight_own_kg: float | None = None
    riding_weight_other_kg: float | None = None


def _debut_date(value) -> str | None:
    raw = str(value or "").strip()
    if raw in {"", "-", "0"}:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Invalid official jockey debut date") from None
    if not date(1900, 1, 1) <= parsed <= datetime.now(KST).date():
        raise ValueError("Official jockey debut date outside valid range")
    return parsed.isoformat()


def _riding_weight(value) -> float | None:
    raw = str(value or "").strip()
    if raw in {"", "-", "0", "0.0"}:
        return None
    try:
        number = Decimal(raw)
        valid = (number.is_finite() and 0 < number < 100
                 and number == number.quantize(Decimal("0.1")))
    except InvalidOperation:
        valid = False
    if not valid:
        raise ValueError("Invalid official jockey riding weight")
    return float(number)


def parse_roster(html: bytes, payload: bytes, meet: int) -> list[Affiliation]:
    """Reject incomplete/mismatched sources before producing any observations."""
    response = json.loads(payload)["response"]
    if response["header"]["resultCode"] != "00":
        raise ValueError("Jockey API request unsuccessful")
    body = response["body"]
    items = body["items"]["item"]
    if isinstance(items, dict):
        items = [items]
    if len(items) != int(body["totalCount"]):
        raise ValueError("Incomplete jockey API pagination")
    indexed = {}
    for item in items:
        official_id = str(item["jkNo"])
        if item["meet"] != MEETS[meet] or not re.fullmatch(r"[0-9A-Z]{6}", official_id):
            raise ValueError("Invalid jockey API affiliation/ID")
        if official_id in indexed:
            raise ValueError("Duplicate jockey API ID")
        indexed[official_id] = item

    rows = []
    for link in BeautifulSoup(html, "html.parser").select("a[href*=goPage2]"):
        match = re.fullmatch(r'\s*javascript:goPage2\("([0-9]{6})"\)\s*;?\s*',
                             str(link.get("href", "")))
        if match is None:
            raise ValueError("Invalid active jockey roster link")
        official_id = match.group(1)
        name = link.get_text(" ", strip=True)
        api = indexed.get(official_id)
        if (api is None or api["jkName"].strip() != name or not name
                or str(api.get("spDate", "")).strip() != "-"):
            raise ValueError("Active web roster and API identity/registration disagree")
        rows.append(Affiliation(
            official_id, name, meet, f"{SOURCE}?meet={meet}",
            hashlib.sha256(html).hexdigest(), f"{API_SOURCE}?meet={meet}",
            hashlib.sha256(payload).hexdigest(),
            _debut_date(api.get("debut")),
            _riding_weight(api.get("wgPart")), _riding_weight(api.get("wgOther")),
        ))
    if not 10 <= len(rows) <= 80:
        raise ValueError("Unexpected active jockey roster size")
    if len({row.kra_jockey_id for row in rows}) != len(rows):
        raise ValueError("Duplicate active jockey roster ID")
    return rows


def load_rosters(directory: Path) -> list[Affiliation]:
    rows = []
    for meet in MEETS:
        rows.extend(parse_roster((directory / f"active_{meet}.html").read_bytes(),
                                 (directory / f"api_{meet}.json").read_bytes(), meet))
    if len({row.kra_jockey_id for row in rows}) != len(rows):
        raise ValueError("Jockey appears in multiple base affiliations")
    return rows


def fetch_rosters(directory: Path) -> None:
    secret = get_settings().data_go_kr_service_key
    if secret is None:
        raise ValueError("DATA_GO_KR_SERVICE_KEY is required")
    directory.mkdir(parents=True, exist_ok=False)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for meet in MEETS:
            web = client.get(SOURCE, params={"meet": meet})
            web.raise_for_status()
            api = client.get(API_SOURCE, params={
                "serviceKey": secret.get_secret_value(), "meet": meet,
                "pageNo": 1, "numOfRows": 1000, "_type": "json",
            })
            api.raise_for_status()
            (directory / f"active_{meet}.html").write_bytes(web.content)
            (directory / f"api_{meet}.json").write_bytes(api.content)


def write_snapshots(database_url: str, rows: list[Affiliation], observed: datetime) -> int:
    if {row.meet_code for row in rows} != set(MEETS):
        raise ValueError("All three complete rosters are required for an atomic refresh")
    if len({row.kra_jockey_id for row in rows}) != len(rows):
        raise ValueError("Duplicate jockey in refresh")
    if any(not 10 <= sum(row.meet_code == meet for row in rows) <= 80 for meet in MEETS):
        raise ValueError("Incomplete regional roster")
    if observed.tzinfo is None:
        raise ValueError("Observation timestamp must include a timezone")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            existing = {row.kra_jockey_id: row for row in connection.execute(
                select(Jockey.id, Jockey.kra_jockey_id, Jockey.name_ko)
            )}
            # Identity mismatches require review, never merge by name or race location.
            mismatched = [row.kra_jockey_id for row in rows
                          if row.kra_jockey_id not in existing
                          or re.sub(r"^\(-[1-4]\)\s*", "",
                                    existing[row.kra_jockey_id].name_ko) != row.name_ko]
            if mismatched:
                raise ValueError(f"Jockey DB identity mismatch: {mismatched}")
            prior = set(connection.scalars(select(JockeyAffiliationSnapshot.jockey_id).where(
                JockeyAffiliationSnapshot.observed_on == observed.astimezone(KST).date(),
            )))
            incoming = {existing[row.kra_jockey_id].id for row in rows}
            if prior and prior != incoming:
                raise ValueError("Same-day roster membership changed; review before replacing")
            statement = text("""insert into jockey_affiliation_snapshots
                (jockey_id, observed_on, meet_code, official_name_ko, observed_at_ms,
                 source_url, source_sha256, api_source_url, api_sha256,
                 debut_date, riding_weight_own_kg, riding_weight_other_kg)
                values (:jockey_id, :observed_on, :meet_code, :official_name_ko,
                        :observed_at_ms, :source_url, :source_sha256, :api_source_url, :api_sha256,
                        :debut_date, :riding_weight_own_kg, :riding_weight_other_kg)
                on conflict (jockey_id, observed_on) do update set
                    meet_code=excluded.meet_code, official_name_ko=excluded.official_name_ko,
                    observed_at_ms=excluded.observed_at_ms, source_url=excluded.source_url,
                    source_sha256=excluded.source_sha256,
                    api_source_url=excluded.api_source_url, api_sha256=excluded.api_sha256,
                    debut_date=excluded.debut_date,
                    riding_weight_own_kg=excluded.riding_weight_own_kg,
                    riding_weight_other_kg=excluded.riding_weight_other_kg""")
            connection.execute(statement, [{
                "jockey_id": existing[row.kra_jockey_id].id,
                "observed_on": observed.astimezone(KST).date(), "meet_code": row.meet_code,
                "official_name_ko": row.name_ko, "observed_at_ms": int(observed.timestamp() * 1000),
                "source_url": row.source_url, "source_sha256": row.source_sha256,
                "api_source_url": row.api_source_url, "api_sha256": row.api_sha256,
                "debut_date": date.fromisoformat(row.debut_date) if row.debut_date else None,
                "riding_weight_own_kg": row.riding_weight_own_kg,
                "riding_weight_other_kg": row.riding_weight_other_kg,
            } for row in rows])
    finally:
        engine.dispose()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Previously archived complete sources")
    parser.add_argument("--apply", action="store_true", help="Write to configured DB")
    args = parser.parse_args()
    observed = datetime.now(KST)
    directory = args.source_dir
    if directory is None:
        directory = Path("data/research") / f"jockey_roster_{observed:%Y%m%d_%H%M%S}"
        fetch_rosters(directory)
    elif (directory / "manifest.json").exists():
        observed = datetime.fromisoformat(json.loads(
            (directory / "manifest.json").read_text()
        )["observed_at"])
    else:
        raise ValueError("Archived sources require a manifest with their observation timestamp")
    rows = load_rosters(directory)
    (directory / "manifest.json").write_text(json.dumps({
        "observed_at": observed.isoformat(), "rows": [asdict(row) for row in rows],
    }, ensure_ascii=False, indent=2))
    if args.apply:
        write_snapshots(get_settings().database_url, rows, observed)
    print(json.dumps({"applied": args.apply, "total": len(rows), "regions": {
        MEETS[meet]: sum(row.meet_code == meet for row in rows) for meet in MEETS
    }}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as error:
        # HTTP exception strings can contain the service key in the request URL.
        raise SystemExit(f"Official source request failed: {type(error).__name__}") from None
