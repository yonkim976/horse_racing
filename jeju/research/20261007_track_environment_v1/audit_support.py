"""Read-only Jeju support audit for moisture, calendar month and start-number research."""

import bisect
import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
PATTERN = re.compile(r"^\s*([^()]*)\s*\((\d+(?:\.\d+)?)%\)\s*$")
BANDS = ("건조", "양호", "다습", "포화", "불량")
SEASONS = {12:"겨울",1:"겨울",2:"겨울",3:"봄",4:"봄",5:"봄",6:"여름",7:"여름",8:"여름",9:"가을",10:"가을",11:"가을"}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def save(name, value):
    with (HERE/name).open("x",encoding="utf-8") as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)
        handle.write("\n")


def positive(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x > 0


def track(raw):
    match = PATTERN.fullmatch(str(raw or ""))
    if not match:
        return None,None,None
    n = float(match[2])
    if not 0 < n <= 100 or not n.is_integer():
        return match[1].strip(),None,None
    band = "건조" if n <= 5 else "양호" if n <= 9 else "다습" if n <= 14 else "포화" if n <= 19 else "불량"
    return match[1].strip(),n,band


def key(row):
    return row["race_date"],row["meet_code"],row["race_number"]


def valid(row):
    return row["finish_position"] is not None and 1 <= row["finish_position"] <= 89 and positive(row["finish_time_seconds"]) and positive(row["race_distance_m"])


def grouped(rows, fields):
    groups=defaultdict(list)
    for row in rows:
        groups[tuple(row[f] for f in fields)].append(row)
    result=[]
    for values,sample in sorted(groups.items(),key=lambda pair:repr(pair[0])):
        entry=dict(zip(fields,values))
        entry.update(races=len(sample),race_days=len({r["race_date"] for r in sample}),runners=sum(r["field_n"] for r in sample),
                     first_date=min(r["race_date"] for r in sample),last_date=max(r["race_date"] for r in sample),
                     raw_race_mean_time_average_s=statistics.mean(r["raw_race_mean_time_s"] for r in sample),
                     prior_time_available_at_least4_races=sum(r["prior_time_available_runners"]>=4 for r in sample))
        result.append(entry)
    return result


def main():
    before=DB.stat()
    digest=sha(DB)
    con=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    columns=("api_record_id","race_date","meet_code","race_number","horse_id","horse_number","race_distance_m","rank_class_raw","finish_position","finish_time_seconds","track_raw","carried_weight_kg","age_at_race_raw","sex_at_race_raw","api4_3_payload_sha256")
    sql="SELECT "+",".join('"'+c+'"' for c in columns)+" FROM jeju_race_postrace_sections_quality_2026"
    print("Reading selected Jeju history",flush=True)
    history=[dict(r) for r in con.execute(sql)]
    full_counts={(r[0],r[1],r[2]):r[3] for r in con.execute("SELECT race_date,meet_code,race_number,COUNT(*) FROM race_result_rows GROUP BY race_date,meet_code,race_number")}
    con.close()
    by_race=defaultdict(list)
    by_horse_distance=defaultdict(list)
    for row in history:
        if valid(row):
            by_horse_distance[(row["horse_id"],row["race_distance_m"])].append(row)
        if row["race_date"] >= "2017-01-01":
            by_race[key(row)].append(row)
    prior_index={}
    for hd,sample in by_horse_distance.items():
        sample.sort(key=lambda r:(r["race_date"],r["race_number"],r["api_record_id"]))
        prior_index[hd]=([r["race_date"] for r in sample],sample)
    excluded=Counter()
    valid_races=[]
    unknown_tracks=[]
    all_labels=Counter()
    for race_key,rows in sorted(by_race.items()):
        n=len(rows)
        reasons=[]
        if n < 6:reasons.append("fewer_than_6_candidates")
        if n != full_counts.get(race_key):reasons.append("partial_vs_stored_result_rows")
        if not all(valid(r) for r in rows):reasons.append("non_normal_or_nonpositive_result")
        positions=[r["finish_position"] for r in rows]
        if any(p is None for p in positions) or sorted(p for p in positions if p is not None)!=list(range(1,n+1)):
            reasons.append("ranks_not_unique_complete_1_through_N")
        if len({r["horse_id"] for r in rows})!=n:reasons.append("duplicate_horse_id")
        numbers=[r["horse_number"] for r in rows]
        if any(not positive(x) for x in numbers) or len(set(numbers))!=n:reasons.append("invalid_or_duplicate_start_number")
        if any(len({r[f] for r in rows})!=1 for f in ("race_distance_m","rank_class_raw","track_raw")):
            reasons.append("within_race_condition_conflict")
        if reasons:
            excluded.update(reasons)
            continue
        raw=rows[0]
        label,moisture,band=track(raw["track_raw"])
        all_labels[(label,band)]+=1
        if moisture is None:
            unknown_tracks.append({"race_date":race_key[0],"race_number":race_key[2],"track_raw":raw["track_raw"]})
        supported=[]
        latest=[]
        for r in rows:
            dates,past=prior_index.get((r["horse_id"],r["race_distance_m"]),([],[]))
            cutoff=(date.fromisoformat(r["race_date"])-timedelta(days=2)).isoformat()
            end=bisect.bisect_right(dates,cutoff)
            chosen=past[max(0,end-3):end]
            assert all(h["race_date"]<=cutoff for h in chosen)
            if chosen:
                supported.append(r["api_record_id"])
                latest.append(chosen[-1]["race_date"])
        month=int(race_key[0][5:7])
        valid_races.append({"race_date":race_key[0],"meet_code":race_key[1],"race_number":race_key[2],
                            "distance_m":raw["race_distance_m"],"grade_raw":raw["rank_class_raw"],"track_raw":raw["track_raw"],
                            "moisture_percent":moisture,"band":band,"label_raw":label,
                            "year":int(race_key[0][:4]),"month":month,"season":SEASONS[month],"field_n":n,
                            "start_numbers":sorted(numbers),"continuous_1_through_N":sorted(numbers)==list(range(1,n+1)),
                            "raw_race_mean_time_s":statistics.mean(r["finish_time_seconds"] for r in rows),
                            "prior_time_available_runners":len(supported),"prior_last_date_max":max(latest,default=None),
                            "source_api_record_ids":[r["api_record_id"] for r in rows]})
    # No raw group/time/passing ranks enter this audit.
    periods={"all_2017_plus":valid_races,"complete_2017_2025":[r for r in valid_races if r["year"]<=2025],
             "recent_2024_plus":[r for r in valid_races if r["year"]>=2024],
             "complete_2024_2025":[r for r in valid_races if r["year"] in (2024,2025)]}
    bands=[]
    for period,sample in periods.items():
        known=[r for r in sample if r["band"] is not None]
        tab=grouped(known,("distance_m","band"))
        dry={r["distance_m"]:r for r in tab if r["band"]=="건조"}
        for r in tab:
            r["period"]=period
            r["dry_reference_race_days"]=dry.get(r["distance_m"],{}).get("race_days",0)
            r["provisional_20_day_support"]=r["race_days"]>=20 and r["dry_reference_race_days"]>=20
        bands.extend(tab)
    save("moisture_support.json",bands)
    save("month_support.json",[{"period":p,**r} for p,s in periods.items() for r in grouped([x for x in s if x["band"] is not None],("distance_m","band","month"))])
    save("grade_year_support.json",grouped(valid_races,("year","grade_raw","distance_m")))
    save("gate_field_support.json",grouped(valid_races,("year","distance_m","field_n","continuous_1_through_N")))
    common=[]
    for period in ("complete_2017_2025","complete_2024_2025"):
        layers=defaultdict(list)
        for r in periods[period]:
            if r["band"] is not None:layers[(r["distance_m"],r["year"],r["grade_raw"],r["moisture_percent"])].append(r)
        per_distance=defaultdict(list)
        for layer,sample in layers.items():
            summer=[r for r in sample if r["season"]=="여름"]
            winter=[r for r in sample if r["season"]=="겨울"]
            if summer and winter:
                per_distance[layer[0]].append({"year":layer[1],"grade_raw":layer[2],"moisture_percent":layer[3],
                                               "summer_races":len(summer),"winter_races":len(winter),
                                               "summer_days":len({r["race_date"] for r in summer}),"winter_days":len({r["race_date"] for r in winter})})
        for distance in sorted({r["distance_m"] for r in periods[period]}):
            sample=per_distance[distance]
            common.append({"period":period,"distance_m":distance,"common_layers":len(sample),
                           "common_layer_years":sorted({r["year"] for r in sample}),
                           "summer_races":sum(r["summer_races"] for r in sample),"winter_races":sum(r["winter_races"] for r in sample),"layers":sample})
    save("season_common_support.json",common)
    save("race_support_rows.json",valid_races)
    summary={"candidate_rows_2017_plus":sum(len(s) for s in by_race.values()),"candidate_races_2017_plus":len(by_race),
             "complete_normal_races":len(valid_races),"complete_normal_rows":sum(r["field_n"] for r in valid_races),
             "race_days":len({r["race_date"] for r in valid_races}),"known_moisture_races":sum(r["band"] is not None for r in valid_races),
             "excluded_races":len(by_race)-len(valid_races),"exclusion_reason_counts_overlapping":dict(excluded),
             "unknown_track_races":unknown_tracks,"label_band_counts":[{"label_raw":k[0],"numeric_band":k[1],"races":v} for k,v in all_labels.items()],
             "numbering_gap_races":sum(not r["continuous_1_through_N"] for r in valid_races),
             "field_size_counts":dict(sorted(Counter(r["field_n"] for r in valid_races).items())),
             "prior_time_at_least4_races":sum(r["prior_time_available_runners"]>=4 for r in valid_races),
             "time_adjustment_estimated":False,"predictive_training_performed":False}
    assert sum(r["races"] for r in bands if r["period"]=="all_2017_plus")==summary["known_moisture_races"]
    assert all(r["prior_last_date_max"] is None or r["prior_last_date_max"] <= (date.fromisoformat(r["race_date"])-timedelta(days=2)).isoformat() for r in valid_races)
    assert track("건조 (0%)")[1] is None and track("건조 (%)")[1] is None
    assert track("포화 (17%)")==("포화",17.0,"포화")
    after=DB.stat()
    assert digest==sha(DB) and (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    save("summary.json",summary)
    save("verification.json",{"status":"passed","database":str(DB),"database_sha256":digest,"size_bytes":before.st_size,
                              "query_columns":columns,"database_unchanged":True,
                              "checks":["complete unique ranks 1..N","unique horse and start number within race","race conditions consistent","not partial vs stored results","historical dates <= T-2","moisture group counts reconcile","unknown moisture not zero dry","DB hash/size/mtime unchanged"]})
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
