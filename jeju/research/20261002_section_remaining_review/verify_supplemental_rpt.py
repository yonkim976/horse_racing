"""Read-only comparison of supplementary official TXT with saved website evidence."""
import collections
import hashlib
import json
import re
from pathlib import Path

from horse_racing.parsers.dacom11 import parse_dacom11_report

OUT = Path(__file__).resolve().parent


def read(name):
    return json.loads((OUT / name).read_text())


def norm(value):
    return re.sub(r"\s+", "", str(value or ""))


def main():
    manifest = read("supplemental_rpt_manifest.json")
    groups = {(r["date"], r["race_no"], r["point"]): r for r in read("group_website_comparisons.json")}
    runners = {(r["date"], r["race_no"], r["program_no"], r["point"]): r for r in read("runner_website_comparisons.json")}
    label = {"S-1F": "S1F", "C1": "1C", "C2": "2C", "C3": "3C", "C4": "4C", "G-1F": "G1F"}
    comparisons = []
    gaps = []
    anomalies = []
    roster_counts = []
    for day in manifest:
        assert day["status"] == "parsed"
        assert hashlib.sha256((OUT / day["raw_file"]).read_bytes()).hexdigest() == day["sha256"]
        for block in day["race_blocks"]:
            data = (OUT / block["block_file"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == block["block_sha256"]
            text = data.decode("utf-8")
            race, = parse_dacom11_report(text.encode("cp949"))
            key = day["date"], block["race_no"]
            assert (str(race.race_date), race.race_number, race.meet_name) == (*key, "제주")
            roster_counts.append({"date": key[0], "race_no": key[1], "runners": len(race.entries), "reason": block["reason"]})
            for match in re.finditer(r"^[ \t]*(?:통과순위[ \t]+)?(S-1F|C1|C2|C3|C4|G-1F)[ \t]*:[ \t]*([^\r\n]*)", text, re.M):
                point = label[match[1]]
                source = groups[(*key, point)]
                comparisons.append({"date": key[0], "race_no": key[1], "point": point, "type": "group", "txt_raw": match[2].strip(), "website_raw": source["website_raw"], "equal": norm(match[2]) == norm(source["website_raw"])})
            for entry in race.entries:
                if entry.passing_order_raw is None:
                    raise AssertionError((key, entry.horse_number, "passing path absent"))
                ranks = [int(v) if v.strip() else None for v in entry.passing_order_raw.split("-")]
                assert len(ranks) == 6
                for index, point in enumerate(label.values()):
                    source = runners[(*key, entry.horse_number, point)]
                    milliseconds = {"S1F": entry.s1f_ms, "G1F": entry.g1f_ms, **entry.corner_times_ms}.get(point)
                    seconds = milliseconds / 1000 if milliseconds and milliseconds > 0 else None
                    comparisons.append({"date": key[0], "race_no": key[1], "program_no": entry.horse_number, "point": point, "type": "individual_order", "txt_value": ranks[index], "website_value": source["website_order"], "api_value": source["api_order"], "txt_equal_api": ranks[index] == source["api_order"], "equal": ranks[index] == source["website_order"]})
                    comparisons.append({"date": key[0], "race_no": key[1], "program_no": entry.horse_number, "point": point, "type": "individual_time", "txt_value": seconds, "website_value": source["website_time"], "api_value": source["api_time"], "txt_equal_api": seconds == source["api_time"], "equal": seconds == source["website_time"]})
                    if key == ("2026-01-17", 5) and entry.horse_number == 8 and point == "G1F":
                        anomalies.append({"date": key[0], "race_no": key[1], "program_no": 8, "field": point, "txt_seconds": seconds, "website_seconds": source["website_time"], "reason": "Official TXT repeats abnormal 77.2 seconds; no alternate correction value."})
            if block["reason"] == "race_level_section_missing":
                lines = [line.strip() for line in text.splitlines() if re.match(r"^(펄롱타임|통과거리|통과타임)\s*:", line)]
                gaps.append({"date": key[0], "race_no": key[1], "raw_lines": lines, "furlong_time_values": re.search(r"^펄롱타임[ \t]*:[ \t]*(.*?)[ \t]*4F", text, re.M)[1].strip(), "cumulative_time_values": re.search(r"^통과타임[ \t]*:[ \t]*([^\r\n]*)", text, re.M)[1].strip(), "note": "Distance grid and 3F/4F aggregates may exist; those do not supply missing detailed split or cumulative times."})
    summary = {"database_modified": False, "txt_dates": len(manifest), "target_races": len(roster_counts), "roster_rows": sum(r["runners"] for r in roster_counts), "comparison_counts": dict(collections.Counter(r["type"] for r in comparisons)), "differences": [r for r in comparisons if not r["equal"]], "missing_race_supplement": gaps, "unresolved_time_supplement": anomalies}
    (OUT / "supplemental_rpt_comparisons.json").write_text(json.dumps(comparisons, ensure_ascii=False, indent=2) + "\n")
    (OUT / "supplemental_rpt_review.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
