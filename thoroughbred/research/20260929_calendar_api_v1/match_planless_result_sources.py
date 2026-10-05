"""Match 2026 planless API result groups to already executed race groups."""

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
REVIEW = HERE / "planless_positive_result_review.csv"


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    flags = read_csv(HERE / "race_execution_flags.csv")
    executed = {(int(row["meet"]), int(row["date"]), int(row["race_no"]))
                for row in flags if row["execution_status"] == "executed_plan_and_result"}
    groups = defaultdict(dict)
    for meet in (1, 3, 4):
        path = HERE / f"raw/race_execution_probe/2026/meet_{meet}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            items = json.load(stream)["response"]["body"]["items"]["item"]
        for item in items:
            groups[(meet, int(item["rcDate"]), int(item["rcNo"]))][str(item["hrNo"])] = item

    review = read_csv(REVIEW)
    assert len(review) == 20
    for row in review:
        key = int(row["meet"]), int(row["date"]), int(row["race_no"])
        source_rows = groups[key]
        candidates = [candidate for candidate in executed if candidate != key
                      and candidate in groups and set(groups[candidate]) == set(source_rows)]
        assert len(candidates) == 1, (key, candidates)
        match = candidates[0]
        prior_rows = groups[match]
        horse_count = len(source_rows)
        same_times = sum(source_rows[horse]["rcTime"] == prior_rows[horse]["rcTime"]
                         for horse in source_rows)
        same_orders = sum(source_rows[horse]["ord"] == prior_rows[horse]["ord"]
                          for horse in source_rows)
        row.update(matched_executed_meet=match[0], matched_executed_date=match[1],
                   matched_executed_race_no=match[2], exact_horse_set="yes",
                   horse_count=horse_count, identical_rcTime_rows=same_times,
                   identical_ord_rows=same_orders,
                   review_decision="exclude_reused_or_modified_prior_race_rows_from_active_data",
                   comparison_note=("same_horses_and_times" if same_times == horse_count
                                    else "same_horses_modified_times"))
    headings = list(review[0])
    with REVIEW.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headings)
        writer.writeheader()
        writer.writerows(review)
    print("Matched all 20 excluded API race groups to executed races by exact horse set")


if __name__ == "__main__":
    main()
