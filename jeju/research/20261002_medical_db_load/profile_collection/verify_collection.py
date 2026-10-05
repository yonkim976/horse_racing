from __future__ import annotations
import hashlib, json, re, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

ROOT = Path("/private/tmp/jeju_medical_20261002/profile_collection")
REPO = Path("/Users/kimyongjin/Desktop/horse_racing")
API16 = REPO / "jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z"
sys.path.insert(0, str(REPO / "src"))
from horse_racing.config import get_settings

def parse_items(data):
    value=json.loads(data)
    response=value.get("response",value) if isinstance(value,dict) else {}
    body=response.get("body",{}) if isinstance(response,dict) else {}
    wrapper=body.get("items",{}) if isinstance(body,dict) else {}
    raw=wrapper.get("item") if isinstance(wrapper,dict) else None
    if raw is None: rows=[]
    elif isinstance(raw,dict): rows=[raw]
    else: rows=raw
    return response.get("header",{}),body,rows

def field_type(value):
    if value is None: return "null"
    if isinstance(value,bool): return "boolean"
    if isinstance(value,int): return "integer"
    if isinstance(value,float): return "number"
    if isinstance(value,str): return "string"
    if isinstance(value,list): return "array"
    if isinstance(value,dict): return "object"
    return type(value).__name__

def main():
    errors=[]
    targets=json.loads((ROOT/"target_manifest.json").read_text())
    source_rows_by_id={t["horse_id"]:t["source_rows"] for t in targets["targets"]}
    profile_rows=[json.loads(x) for x in (ROOT/"validated_profile_rows.jsonl").read_text().splitlines() if x.strip()]
    ledger=[json.loads(x) for x in (ROOT/"request_ledger.jsonl").read_text().splitlines() if x.strip()]
    summary=json.loads((ROOT/"collection_manifest.json").read_text())
    run_manifests=[]
    for p in sorted(ROOT.glob("run_manifest_*.json")):
        m=json.loads(p.read_text())
        events=[e for e in ledger if e.get("run_id")==m.get("run_id")]
        m["probes"]=events
        m["requests_started_this_run"]=len(events)
        m["validation_status_counts"]=dict(sorted(Counter(e.get("validation_status") for e in events).items()))
        m["completed_profile_count"]=sum(e.get("validation_status")=="validated" for e in events)
        p.write_text(json.dumps(m,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
        run_manifests.append(m)

    expected_ids={t["horse_id"] for t in targets["targets"]}
    row_ids=[r["horse_id"] for r in profile_rows]
    if len(profile_rows)!=81 or len(set(row_ids))!=81 or set(row_ids)!=expected_ids:
        errors.append("validated JSONL is not exactly one row for each of the 81 frozen target IDs")
    if summary.get("status")!="complete" or summary.get("validated_profile_count")!=81 or summary.get("completed_profile_count")!=81:
        errors.append("collection manifest does not confirm 81 validated profiles")
    if summary.get("failed_or_invalid_profile_count")!=0 or summary.get("pending_unique_profile_count")!=0:
        errors.append("collection manifest reports unresolved/failed targets")
    raw_count=0
    for row in profile_rows:
        hid=row["horse_id"]
        if row.get("api_result_code")!="00" or row.get("http_status")!=200 or row.get("api_total_count")!=1:
            errors.append(f"API status/count failed for {hid}")
        if row.get("returned_item_count")!=1 or row.get("exact_hr_no_match_count")!=1:
            errors.append(f"returned item identity/count failed for {hid}")
        if not isinstance(row.get("raw_item"),dict) or str(row["raw_item"].get("hrNo") or "").strip()!=hid:
            errors.append(f"raw_item hrNo mismatch for {hid}")
        item=row["raw_item"]
        if len(item)!=218 or row.get("item_field_keys")!=sorted(item.keys()):
            errors.append(f"raw item key count/list mismatch for {hid}")
        types={k:field_type(v) for k,v in sorted(item.items())}
        if row.get("item_field_types")!=types:
            errors.append(f"raw item JSON types mismatch for {hid}")
        if row.get("breed_label_raw")!="제주마" or not str(row.get("horse_name_raw") or "").strip():
            errors.append(f"breed/name unusable for {hid}")
        if not (str(row.get("birth_date_raw") or "").strip() or str(row.get("birth_year_raw") or "").strip()):
            errors.append(f"birth date/year unusable for {hid}")
        rel=Path(row.get("response_file",""))
        if rel.is_absolute() or ".." in rel.parts or not row.get("response_file","").startswith("raw/api42_profiles/"):
            errors.append(f"response path is not safe and relative for {hid}")
            continue
        raw_path=ROOT/rel
        if not raw_path.is_file():
            errors.append(f"raw response missing for {hid}")
            continue
        raw=raw_path.read_bytes()
        raw_count+=1
        if hashlib.sha256(raw).hexdigest()!=row.get("response_sha256") or len(raw)!=row.get("response_bytes"):
            errors.append(f"raw response SHA/size mismatch for {hid}")
        h,b,items=parse_items(raw)
        if str(h.get("resultCode") or "")!="00" or int(b.get("totalCount") or -1)!=1 or len(items)!=1 or items[0]!=item:
            errors.append(f"raw response does not independently reproduce the validated item for {hid}")
        if row.get("response_page_no")!=1 or row.get("response_item_index")!=1:
            errors.append(f"response page/item location is not 1-based page 1 item 1 for {hid}")
        if row.get("request_metadata",{}).get("public_params",{}).get("hr_no")!=hid:
            errors.append(f"request metadata does not bind exact hr_no for {hid}")
        if row.get("clinic_source_rows")!=source_rows_by_id.get(hid):
            errors.append(f"clinic source references differ from the frozen source map for {hid}")
        for ref in row.get("clinic_source_rows",[]):
            source_path=API16/ref["source_page_relative_path"]
            data=source_path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=ref.get("source_page_sha256") or len(data)!=ref.get("source_page_bytes"):
                errors.append(f"API16 source page digest failed for {hid}")
                break
            _,_,clinic_items=parse_items(data)
            i=ref["item_index"]-1
            if i<0 or i>=len(clinic_items) or str(clinic_items[i].get("hrNo") or "").strip()!=hid:
                errors.append(f"API16 source item location/ID failed for {hid}")
                break
            if str(clinic_items[i].get("clinicDate") or "").strip()!=str(ref.get("clinic_date_raw") or ""):
                errors.append(f"API16 clinic date failed for {hid}")
                break
    status_counts=Counter(e.get("validation_status") for e in ledger)
    by_id=defaultdict(list)
    for e in ledger:
        by_id[e["horse_id"]].append(e)
    final_by_id={hid:events[-1].get("validation_status") for hid,events in by_id.items()}
    if set(final_by_id)!=expected_ids or any(x!="validated" for x in final_by_id.values()):
        errors.append("final per-horse ledger state is not validated for every frozen target")
    if len(ledger)!=82 or status_counts.get("validated")!=81 or status_counts.get("transport_error")!=1:
        errors.append("request ledger does not show 81 successes and the one isolated/retried initial transport failure")
    times=sorted(datetime.fromisoformat(e["requested_at_utc"]) for e in ledger)
    min_gap=min(((b-a).total_seconds() for a,b in zip(times,times[1:])),default=None)
    if min_gap is not None and min_gap < 1.05:
        errors.append(f"request start interval violated: {min_gap}")
    priority_counts=Counter(t["priority_group"] for t in targets["targets"])
    clinic_row_counts=Counter()
    for t in targets["targets"]:
        for r in t["source_rows"]:
            clinic_row_counts["after" if r["after_20260919_cutoff"] else "within"]+=1
    if priority_counts!={"within_20260919_cutoff":76,"after_20260919_cutoff":5}:
        errors.append("priority target split changed")
    if clinic_row_counts!={"within":150,"after":6}:
        errors.append("source row cutoff split changed")

    secret=get_settings().data_go_kr_service_key
    key=secret.get_secret_value().encode() if secret is not None else b""
    key_forms={key,quote(key.decode(),safe="").encode() if key else b"",quote_plus(key.decode(),safe="").encode() if key else b""}
    key_forms.discard(b"")
    data_files=[p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() not in {".pyc"}]
    key_hits=0
    auth_url_hits=0
    for p in data_files:
        raw=p.read_bytes()
        if any(k in raw for k in key_forms): key_hits+=1
        if re.search(rb"https?://[^\s\"'<>]*[?&](?:ServiceKey|serviceKey)=",raw,re.I): auth_url_hits+=1
    if key_hits or auth_url_hits:
        errors.append("secret/authenticated URL scan found a hit")

    result={
        "verified":not errors,
        "errors":errors,
        "unique_targets":len(expected_ids),
        "validated_profile_rows":len(profile_rows),
        "raw_api42_responses_present_and_hash_matched":raw_count,
        "api16_source_row_references_rechecked":sum(len(r.get("clinic_source_rows",[])) for r in profile_rows),
        "profile_field_count_distribution":dict(sorted(Counter(len(r["item_field_keys"]) for r in profile_rows).items())),
        "validated_breed_distribution":dict(sorted(Counter(str(r.get("breed_label_raw")) for r in profile_rows).items())),
        "profile_name_and_birth_present":all(bool(str(r.get("horse_name_raw") or "").strip() and (str(r.get("birth_date_raw") or "").strip() or str(r.get("birth_year_raw") or "").strip())) for r in profile_rows),
        "source_target_split":dict(sorted(priority_counts.items())),
        "source_row_cutoff_split":dict(sorted(clinic_row_counts.items())),
        "request_attempt_count":len(ledger),
        "request_status_counts":dict(sorted(status_counts.items())),
        "final_per_horse_status_counts":dict(sorted(Counter(final_by_id.values()).items())),
        "minimum_request_start_gap_seconds":min_gap,
        "api42_known_prior_requests_kst_today":summary.get("prior_known_api42_requests"),
        "api42_this_stage_requests_kst_today":summary.get("requests_started_by_this_stage_today"),
        "api42_daily_cap":summary.get("quota_assessment",{}).get("daily_advertised_request_cap"),
        "api42_known_total_kst_today":(summary.get("prior_known_api42_requests") or 0)+(summary.get("requests_started_by_this_stage_today") or 0),
        "credential_or_authenticated_url_hits":key_hits+auth_url_hits,
        "run_manifests_reconciled":len(run_manifests),
    }
    (ROOT/"verification_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    if errors:
        print(json.dumps(result,ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
