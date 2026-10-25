"""Reclassify actual winning payouts by each race-pool's minimum quote."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "jeju/research/20261014_pool_dividend_frequency_v1"
STUDY = ROOT / "jeju/research/20261014_pool_dividend_minimum_v1"
POOLS = ("WIN", "PLC", "QNL", "QPL", "EXA", "TLA", "TRI")
NAMES = {"WIN": "단승", "PLC": "연승", "QNL": "복승", "QPL": "복연승",
         "EXA": "쌍승", "TLA": "삼복승", "TRI": "삼쌍승"}
CATEGORIES = ("low_lt5", "middle_5_to_lt20", "high_ge20")
EXPECTED = {
    "winning_quotes.csv": "6a208e23ebe175ea20f7a9bfcc86f24245e5dfc675eba0cec22be93eb1dcdca4",
    "SOURCE_HASHES.json": "b385ded73f751678e207ef04c0fedd366895812819835e8a7e628a55b61131fc",
    "ROOT_FINAL_REVIEW.json": "2d254793bbe5d0b919dfd4f408e3e1380f824cac148a30333deff2da773495c8",
    "race_pool_summary.csv": "878c43fb8c98defd9499d364afd4417614341ca38f7b719ae8d1269c893cf022",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def category(value: Decimal) -> str:
    return "low_lt5" if value < 5 else "middle_5_to_lt20" if value < 20 else "high_ge20"


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 6) if d else 0.0


def as_bool(value: str) -> bool:
    if value in ("True", "true", "1"):
        return True
    if value in ("False", "false", "0"):
        return False
    raise ValueError(f"invalid source boolean: {value}")


def main() -> None:
    if not STUDY.resolve().is_relative_to((ROOT / "jeju/research").resolve()):
        raise ValueError("output path escaped the research directory")
    files = {name: SOURCE / name for name in EXPECTED}
    for name, path in files.items():
        if sha(path) != EXPECTED[name]:
            raise ValueError(f"frozen source hash mismatch: {name}")
    source_hashes = json.loads((SOURCE / "SOURCE_HASHES.json").read_text(encoding="utf-8"))
    if source_hashes["output_sha256"]["winning_quotes.csv"] != EXPECTED["winning_quotes.csv"]:
        raise ValueError("source receipt does not bind the expected quote file")
    root_review = json.loads((SOURCE / "ROOT_FINAL_REVIEW.json").read_text(encoding="utf-8"))
    if root_review["status"] != "PASS" or root_review["actual_winning_quotes_verified"] != 13560:
        raise ValueError("frozen independent review is not the expected PASS")
    outputs = ("race_classification.csv", "summary.csv", "oldmax_to_newmin_crosswalk.csv",
               "REPORT.json", "README.md", "SOURCE_HASHES.json")
    if any((STUDY / name).exists() for name in outputs):
        raise FileExistsError("refusing to overwrite an existing study output")
    STUDY.mkdir(parents=True, exist_ok=True)

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with (SOURCE / "winning_quotes.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            row["year"] = int(row["year"])
            row["actual_starters"] = int(row["actual_starters"])
            row["race_number"] = int(row["race_number"])
            row["winning_dividend_multiple"] = Decimal(row["winning_dividend_multiple"])
            if row["pool"] not in POOLS or row["winning_dividend_multiple"] < 1:
                raise ValueError("unknown pool or invalid winning dividend")
            groups[(row["race_id"], row["pool"])].append(row)

    races = sorted({race_id for race_id, _ in groups})
    if len(races) != 1237 or len(groups) != 1237 * 7:
        raise ValueError("source does not contain the reviewed 1,237 × 7 race-pool grid")
    year_counts = Counter(race_id[:4] for race_id in races)
    if year_counts != {"2025": 707, "2026": 530}:
        raise ValueError(f"unexpected race-year denominators: {year_counts}")

    race_rows = []
    for (race_id, pool), quotes in sorted(groups.items()):
        starters = {q["actual_starters"] for q in quotes}
        dates = {q["race_date"] for q in quotes}
        if len(starters) != 1 or len(dates) != 1:
            raise ValueError(f"inconsistent race metadata: {race_id} {pool}")
        expected_quotes = (2 if next(iter(starters)) <= 7 else 3) if pool == "PLC" else 3 if pool == "QPL" else 1
        if len(quotes) != expected_quotes:
            raise ValueError(f"incomplete winning quotes: {race_id} {pool}")
        values = [q["winning_dividend_multiple"] for q in quotes]
        minimum, maximum = min(values), max(values)
        first = quotes[0]
        race_rows.append({"race_id": race_id, "race_date": first["race_date"], "year": first["year"],
                          "race_number": first["race_number"], "actual_starters": first["actual_starters"],
                          "pool": pool, "pool_korean": NAMES[pool], "winning_quote_count": len(quotes),
                          "minimum_winning_dividend": str(minimum), "maximum_winning_dividend": str(maximum),
                          "old_max_category": category(maximum), "new_min_category": category(minimum)})
    source_summary = {}
    with (SOURCE / "race_pool_summary.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            source_summary[(row["race_id"], row["pool"])] = row
    if len(source_summary) != len(race_rows):
        raise ValueError("source race-pool summary has an unexpected row count")

    identity_checks = []
    for row in race_rows:
        ref = source_summary[(row["race_id"], row["pool"])]
        if (int(ref["winning_quote_count"]) != row["winning_quote_count"]
                or Decimal(ref["minimum_winning_dividend"]) != Decimal(row["minimum_winning_dividend"])
                or Decimal(ref["maximum_winning_dividend"]) != Decimal(row["maximum_winning_dividend"])):
            raise ValueError(f"frozen summary disagrees with quote rows: {row['race_id']} {row['pool']}")
        if as_bool(ref["low_any_lt5"]) != (row["new_min_category"] == "low_lt5"):
            raise ValueError("minimum<5 identity failed against frozen source flag")
        if as_bool(ref["high_all_min_ge20"]) != (row["new_min_category"] == "high_ge20"):
            raise ValueError("minimum>=20 identity failed against frozen source flag")

    periods = {"all": race_rows, "2025": [r for r in race_rows if r["year"] == 2025],
               "2026": [r for r in race_rows if r["year"] == 2026]}
    summary_rows, cross_rows = [], []
    for period, period_rows in periods.items():
        for pool in POOLS:
            subset = [r for r in period_rows if r["pool"] == pool]
            counts = Counter(r["new_min_category"] for r in subset)
            old_counts = Counter(r["old_max_category"] for r in subset)
            n = len(subset)
            summary_rows.append({"period": period, "pool": pool, "pool_korean": NAMES[pool], "races": n,
                "winning_quotes": sum(r["winning_quote_count"] for r in subset),
                "low_min_lt5_races": counts["low_lt5"], "low_min_pct": pct(counts["low_lt5"], n),
                "middle_min_5_to_lt20_races": counts["middle_5_to_lt20"], "middle_min_pct": pct(counts["middle_5_to_lt20"], n),
                "high_min_ge20_races": counts["high_ge20"], "high_min_pct": pct(counts["high_ge20"], n),
                "old_max_low_races": old_counts["low_lt5"], "old_max_middle_races": old_counts["middle_5_to_lt20"],
                "old_max_high_races": old_counts["high_ge20"]})
            for old in CATEGORIES:
                for new in CATEGORIES:
                    cross_rows.append({"period": period, "pool": pool, "old_max_category": old,
                                       "new_min_category": new,
                                       "n_races": sum(r["old_max_category"] == old and r["new_min_category"] == new for r in subset)})

    for period, period_rows in periods.items():
        for pool in POOLS:
            subset = [r for r in period_rows if r["pool"] == pool]
            low_n = sum(r["new_min_category"] == "low_lt5" for r in subset)
            high_n = sum(r["new_min_category"] == "high_ge20" for r in subset)
            source_subset = [source_summary[(r["race_id"], pool)] for r in subset]
            assert low_n == sum(as_bool(r["low_any_lt5"]) for r in source_subset)
            assert high_n == sum(as_bool(r["high_all_min_ge20"]) for r in source_subset)
            identity_checks.extend(({"period": period, "pool": pool, "identity": "min_lt5_equals_source_low_any_lt5", "count": low_n},
                                    {"period": period, "pool": pool, "identity": "min_ge20_equals_source_high_all_min_ge20", "count": high_n}))

    write_csv(STUDY / "race_classification.csv", race_rows, list(race_rows[0]))
    write_csv(STUDY / "summary.csv", summary_rows, list(summary_rows[0]))
    write_csv(STUDY / "oldmax_to_newmin_crosswalk.csv", cross_rows, list(cross_rows[0]))
    input_hashes = {name: EXPECTED[name] for name in EXPECTED}
    input_hashes["analyze_minimum.py"] = sha(Path(__file__))
    report = {"study": STUDY.name, "status": "PASS", "scope": {"eligible_races": 1237,
              "race_year_counts": year_counts, "winning_quotes": sum(map(len, groups.values())),
              "race_pool_rows": len(race_rows), "period_denominators": {k: len({r['race_id'] for r in v}) for k, v in periods.items()}},
              "method": {"categories": "low <5; middle 5<=x<20; high >=20", "PLC_QPL": "minimum actual winning quote per race",
                         "other_pools": "singleton actual winning quote; classification unchanged", "old_category": "maximum quote per race, matching v1"},
              "checks": {"all_races_have_seven_pools": True, "pool_quote_counts_complete": True,
                         "source_min_max_and_quote_counts_match": True, "low_min_lt5_identity": True,
                         "high_all_min_ge20_identity": True, "identity_checks": identity_checks,
                         "no_database_or_network_access": True}, "input_sha256": input_hashes,
              "output_sha256": {name: sha(STUDY / name) for name in ("race_classification.csv", "summary.csv", "oldmax_to_newmin_crosswalk.csv", "analyze_minimum.py")}}
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# 제주 실제 당첨배당의 경주별 최저 배당 분류

2026-10-14 사용자 정정에 따라 PLC(연승)·QPL(복연승)은 경주별 실제 당첨 quote 중 **최솟값**으로 분류했다. 나머지 다섯 승식은 경주당 quote 하나여서 이전 분류가 그대로 유지된다. 구간은 저 `<5배`, 중 `5≤배당<20배`, 고 `≥20배`다. 이 결과는 실제 당첨배당의 기술 빈도이며 사전 확률·수익률·베팅 기준이 아니다.

원천은 `jeju/research/20261014_pool_dividend_frequency_v1/winning_quotes.csv`의 13,560개 동결 quote다. 입력 파일, 기존 `race_pool_summary.csv`, 원천 `SOURCE_HASHES.json`, `ROOT_FINAL_REVIEW.json`의 SHA-256은 `SOURCE_HASHES.json`에 기록했다. 원천 최종 독립 검토 해시는 `2d254793bbe5d0b919dfd4f408e3e1380f824cac148a30333deff2da773495c8`이고 당첨 quote 파일 해시는 `6a208e23ebe175ea20f7a9bfcc86f24245e5dfc675eba0cec22be93eb1dcdca4`다.

`race_classification.csv`에는 경주×승식별 원 quote 수, 최솟값·최댓값, 구 max 기준과 새 min 기준이 있다. `summary.csv`는 전체·2025·2026의 경주 수와 분류 비율을, `oldmax_to_newmin_crosswalk.csv`는 이전 max 분류에서 새 min 분류로 이동한 경주 수를 제공한다. 전체/2025/2026 경주 분모는 각각 1,237/707/530이다.

재현: 프로젝트 루트에서 `.venv/bin/python -B jeju/research/20261014_pool_dividend_minimum_v1/analyze_minimum.py`. 스크립트는 동결 파일 해시와 입력 표의 완전성을 확인하고 새 연구 폴더에만 결과를 쓴다. DB나 네트워크를 열지 않는다. 출력 SHA-256은 `SOURCE_HASHES.json`에 기록하며, 그 파일 자체의 해시는 자기참조를 피하기 위해 목록에서 제외한다. 이 후속 계산은 기존 연구·원천·중앙 결론 등록부를 수정하지 않는다.
"""
    (STUDY / "README.md").write_text(readme, encoding="utf-8")
    receipt = {"study": STUDY.name, "input_sha256": {**input_hashes,
                "source/ROOT_FINAL_REVIEW.json": EXPECTED["ROOT_FINAL_REVIEW.json"],
                "source/winning_quotes.csv": EXPECTED["winning_quotes.csv"],
                "source/race_pool_summary.csv": EXPECTED["race_pool_summary.csv"],
                "source/SOURCE_HASHES.json": EXPECTED["SOURCE_HASHES.json"]},
               "output_sha256": {name: sha(STUDY / name) for name in
                ("analyze_minimum.py", "race_classification.csv", "summary.csv", "oldmax_to_newmin_crosswalk.csv", "REPORT.json", "README.md")}}
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "summary": summary_rows, "output_sha256": receipt["output_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
