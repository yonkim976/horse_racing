"""Independent no-fit check of the gain/loss context supplements."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261010_joint_gain_loss_v1"
CTX = ROOT / "jeju/research/20261010_joint_gain_loss_context_v1/runner_context.csv"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
RUNNERS = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
LEDGER = STUDY / "outputs/race_ledger_1779.csv"
BANDS = ["건조", "양호", "다습", "포화", "불량"]
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
YEARS = [2024, 2025, 2026]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def close(a, b, tol=2e-10):
    return bool(np.isclose(float(a), float(b), atol=tol, rtol=tol, equal_nan=True))


def check_frame(actual, expected, keys, numeric_cols):
    assert not actual.duplicated(keys).any()
    assert not expected.duplicated(keys).any()
    a = actual.sort_values(keys).reset_index(drop=True)
    e = expected.sort_values(keys).reset_index(drop=True)
    assert a[keys].astype(str).equals(e[keys].astype(str)), (keys, "key coverage")
    for col in numeric_cols:
        av, ev = pd.to_numeric(a[col], errors="coerce"), pd.to_numeric(e[col], errors="coerce")
        assert np.allclose(av, ev, atol=2e-10, rtol=2e-10, equal_nan=True), (col, float((av-ev).abs().max()))


def main():
    # Validate every receipt-bound artifact before interpreting any result.
    srec = json.loads((STUDY / "outputs_supplemental/supplemental_receipt.json").read_text())
    frec = json.loads((STUDY / "outputs_followup_addendum/followup_receipt.json").read_text())
    hrec = json.loads((STUDY / "outputs_followup_addendum/history_scope_correction_receipt.json").read_text())
    top3fix_path=STUDY/"outputs_followup_addendum/top3_summary_feature_label_correction_receipt.json"
    top3fix=json.loads(top3fix_path.read_text())
    assert srec["no_fit"] and frec["no_fit"] and hrec["no_fit"]
    assert srec["input_hashes"]["jeju/research/20261010_joint_gain_loss_context_v1/runner_context.csv"] == sha(CTX)
    assert frec["input_hashes"]["jeju/research/20261010_joint_gain_loss_v1/outputs/race_ledger_1779.csv"] == sha(LEDGER)
    assert frec["input_hashes"]["jeju/research/20261010_joint_gain_loss_context_v1/ARTIFACT_MANIFEST.json"] == sha(CTX.parent / "ARTIFACT_MANIFEST.json")
    assert hrec["new_supplemental_context_contract_sha256"] == sha(STUDY / "SUPPLEMENTAL_CONTEXT_CONTRACT.json")
    assert hrec["new_history_extension_contract_sha256"] == sha(STUDY / "SAVED_HISTORY_EXTENSION_CONTRACT.json")
    assert sha(STUDY / "contracts_as_run/SUPPLEMENTAL_CONTEXT_CONTRACT.json") == srec["supplemental_contract_sha256"]
    assert sha(STUDY / "contracts_as_run/SAVED_HISTORY_EXTENSION_CONTRACT.json") == srec["history_extension_contract_sha256"]
    v2_path=STUDY/"outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv"
    assert sha(v2_path)==top3fix["replacement_table_sha256"]
    assert sha(STUDY/"outputs_followup_addendum/actual_top3_context_summary_corrected.csv")==top3fix["prior_corrected_table_sha256"]
    output_checks = {}
    for name, expected in srec["output_hashes"].items():
        p = STUDY / "outputs_supplemental" / name
        assert sha(p) == expected, name
        output_checks[f"outputs_supplemental/{name}"] = sha(p)
    for name, expected in frec["output_hashes"].items():
        p = STUDY / "outputs_followup_addendum" / name
        assert sha(p) == expected, name
        output_checks[f"outputs_followup_addendum/{name}"] = sha(p)
    corrected_history = STUDY / "outputs_followup_addendum/same_distance_support_available_range_corrected.csv"
    assert sha(corrected_history) == hrec["corrected_table_sha256"]
    assert sha(STUDY / "outputs_supplemental/lifetime_same_distance_support.csv") == hrec["original_table_sha256"]

    # Rebuild runner-keyed and race-level context directly from frozen source rows.
    ctx = pd.read_csv(CTX)
    runs = pd.read_csv(RUNNERS)
    feat = pd.read_parquet(FEATURES)
    led = pd.read_csv(LEDGER)
    assert len(ctx) == len(runs) == 17412 and ctx.api_record_id.is_unique and runs.api_record_id.is_unique
    assert set(ctx.api_record_id) == set(runs.api_record_id)
    fcols = ["api_record_id", "race_id", "race_date", "finish_position", "same_starts", "same_valid_times", "same_distance_last5_actual_n", "same_distance_last5_normal_n"]
    f = feat.loc[feat.api_record_id.isin(runs.api_record_id), fcols]
    assert len(f) == 17412 and f.api_record_id.is_unique and set(f.api_record_id) == set(runs.api_record_id)
    x = ctx.merge(runs[["api_record_id", "race_id", "race_date", "evaluation_year", "y_top3"]], on="api_record_id", validate="one_to_one", suffixes=("_ctx", "_run"))
    x = x.merge(f, on="api_record_id", validate="one_to_one", suffixes=("", "_feat"))
    for a, b in [("race_id_ctx", "race_id_run"), ("race_id_ctx", "race_id"), ("race_date_ctx", "race_date_run"), ("race_date_ctx", "race_date")]:
        assert x[a].astype(str).equals(x[b].astype(str)), (a, b)
    assert np.array_equal(x.y_top3.astype(int), (x.finish_position.astype(int) <= 3).astype(int))
    x["race_id"] = x["race_id_ctx"]
    x["race_date"] = x["race_date_ctx"]
    x["evaluation_year"] = x["evaluation_year_ctx"]
    x["carried_body_ratio"] = x.carried_weight_kg / x.body_kg
    assert (x.body_kg > 0).all() and (x.carried_weight_kg > 0).all()
    assert x.groupby("race_id").band.nunique().eq(1).all() and x.groupby("race_id").moisture.nunique().eq(1).all()
    aggs = {
        "context_race_date": ("race_date", "first"), "context_evaluation_year": ("evaluation_year", "first"),
        "band": ("band", "first"), "moisture": ("moisture", "first"), "runner_rows": ("api_record_id", "size"),
        "body_kg_mean": ("body_kg", "mean"), "body_kg_sd_population": ("body_kg", lambda z: z.std(ddof=0)), "body_kg_nonmissing": ("body_kg", "count"),
        "carried_weight_kg_mean": ("carried_weight_kg", "mean"), "carried_weight_kg_sd_population": ("carried_weight_kg", lambda z: z.std(ddof=0)), "carried_weight_kg_nonmissing": ("carried_weight_kg", "count"),
        "carried_body_ratio_mean": ("carried_body_ratio", "mean"), "carried_body_ratio_sd_population": ("carried_body_ratio", lambda z: z.std(ddof=0)), "carried_body_ratio_nonmissing": ("carried_body_ratio", "count"),
        "same_starts_roster_mean": ("same_starts", "mean"), "same_starts_roster_median": ("same_starts", "median"),
        "same_valid_times_roster_mean": ("same_valid_times", "mean"), "same_valid_times_roster_median": ("same_valid_times", "median"),
        "last5_actual_n_roster_mean": ("same_distance_last5_actual_n", "mean"), "last5_actual_n_roster_median": ("same_distance_last5_actual_n", "median"),
        "last5_normal_n_roster_mean": ("same_distance_last5_normal_n", "mean"), "last5_normal_n_roster_median": ("same_distance_last5_normal_n", "median"),
    }
    v = x.groupby("race_id", sort=False).agg(**aggs).reset_index()
    v = v.merge(led[["race_id", "race_date", "evaluation_year", "hit_class", "baseline_hit6", "candidate_hit6", "delta_hit6"]], on="race_id", validate="one_to_one")
    v["body_kg_missing_share"] = 1 - v.body_kg_nonmissing / v.runner_rows
    v["carried_weight_kg_missing_share"] = 1 - v.carried_weight_kg_nonmissing / v.runner_rows
    v["carried_body_ratio_missing_share"] = 1 - v.carried_body_ratio_nonmissing / v.runner_rows
    got = pd.read_csv(STUDY / "outputs_supplemental/race_context_vectors.csv")
    nums = [c for c in got.columns if c not in {"race_id", "context_race_date", "band", "race_date", "hit_class"}]
    check_frame(got, v, ["race_id"], nums)
    assert len(got) == 1779 and got.race_id.is_unique

    # Directly rebuild race-level context summaries and paired-date band CI.
    context_features=["body_kg_mean","body_kg_sd_population","body_kg_missing_share","carried_weight_kg_mean","carried_weight_kg_sd_population","carried_weight_kg_missing_share","carried_body_ratio_mean","carried_body_ratio_sd_population","carried_body_ratio_missing_share"]
    vector_rows=[]
    for group_name, part in [("all_1779",got)]+[(g,got.loc[got.hit_class.eq(g)]) for g in ["both_hit","both_miss","gained","lost"]]:
        for feature in context_features:
            z=pd.to_numeric(part[feature],errors="coerce").dropna()
            vector_rows.append({"outcome_group":group_name,"unit":"race","feature":feature,"units":len(part),"nonmissing_units":len(z),"mean":z.mean(),"median":z.median(),"p25":z.quantile(.25),"p75":z.quantile(.75)})
    expected_summary=pd.DataFrame(vector_rows)
    saved_summary=pd.read_csv(STUDY/"outputs_supplemental/race_context_by_outcome.csv")
    join=saved_summary.merge(expected_summary,on=["outcome_group","unit","feature","units","nonmissing_units"],suffixes=("_out","_calc"),validate="one_to_one")
    assert len(join)==45
    for c in ["mean","median","p25","p75"]: assert np.allclose(join[f"{c}_out"],join[f"{c}_calc"],atol=2e-10,rtol=2e-10),c

    def date_ci(group):
        by_date=[z.delta_hit6.to_numpy(float) for _,z in group.groupby("race_date",sort=True)]
        if not by_date:return (np.nan,np.nan,0)
        rng=np.random.default_rng(20261008); draws=np.empty(2000)
        for i in range(2000):
            idx=rng.integers(0,len(by_date),size=len(by_date)); total=0.; n=0
            for j in idx: total+=float(by_date[int(j)].sum()); n+=len(by_date[int(j)])
            draws[i]=total/n
        return (*np.quantile(draws,[.025,.975],method="linear"),len(by_date))
    band_rows=[]
    for label,part in [("all_1779",got)]+[(b,got.loc[got.band.eq(b)]) for b in BANDS]:
        n=len(part); base=int(part.baseline_hit6.sum()); cand=int(part.candidate_hit6.sum()); lo,hi,nd=date_ci(part)
        band_rows.append({"factor":"all" if label=="all_1779" else "moisture_band","condition":"all_1779" if label=="all_1779" else label,"races":n,"share_of_full_1779":n/1779,"race_dates":part.race_date.nunique(),"gained":int(part.hit_class.eq("gained").sum()),"lost":int(part.hit_class.eq("lost").sum()),"net_gained_minus_lost":int(part.hit_class.eq("gained").sum()-part.hit_class.eq("lost").sum()),"both_hit":int(part.hit_class.eq("both_hit").sum()),"both_miss":int(part.hit_class.eq("both_miss").sum()),"baseline_hits":base,"candidate_hits":cand,"baseline_hit_rate":base/n,"candidate_hit_rate":cand/n,"candidate_minus_baseline_hit_rate":(cand-base)/n,"paired_date_ci95_low":lo,"paired_date_ci95_high":hi,"ci_dates":nd,"ci_draws":2000,"ci_seed":20261008})
    band_table=pd.read_csv(STUDY/"outputs_supplemental/moisture_band_condition_summary.csv")
    check_frame(band_table,pd.DataFrame(band_rows),["factor","condition"],[c for c in band_table.columns if c not in {"factor","condition"}])

    # Independently re-create the corrected Top3 summaries from exact target runners.
    discord = set(led.loc[led.hit_class.isin(["gained", "lost"]), "race_id"])
    actual = x.loc[x.race_id.isin(discord) & (x.finish_position <= 3), ["race_id", "race_date", "api_record_id", "horse_number", "finish_position", "body_kg", "carried_weight_kg", "carried_body_ratio", "moisture", "band"]].copy()
    actual = actual.merge(led[["race_id", "hit_class"]], on="race_id", validate="many_to_one")
    saved_actual = pd.read_csv(STUDY / "outputs_supplemental/actual_top3_context_84_races.csv")
    check_frame(saved_actual, actual, ["api_record_id"], ["horse_number", "finish_position", "body_kg", "carried_weight_kg", "carried_body_ratio", "moisture"])
    assert len(actual) == 252 and actual.race_id.nunique() == 84 and actual.groupby("race_id").size().eq(3).all()
    race_top = actual.groupby(["race_id", "hit_class"], sort=True).agg(
        actual_top3_runner_count=("api_record_id", "size"), actual_top3_body_kg_mean=("body_kg", "mean"), actual_top3_body_kg_sd_population=("body_kg", lambda z: z.std(ddof=0)),
        actual_top3_carried_weight_kg_mean=("carried_weight_kg", "mean"), actual_top3_carried_weight_kg_sd_population=("carried_weight_kg", lambda z: z.std(ddof=0)),
        actual_top3_carried_body_ratio_mean=("carried_body_ratio", "mean"), actual_top3_carried_body_ratio_sd_population=("carried_body_ratio", lambda z: z.std(ddof=0))).reset_index()
    summary_rows=[]
    for group, part in [("all_discordant_84", race_top), ("gained", race_top[race_top.hit_class.eq("gained")]), ("lost", race_top[race_top.hit_class.eq("lost")])]:
        for feature in ["actual_top3_body_kg_mean", "actual_top3_body_kg_sd_population", "actual_top3_carried_weight_kg_mean", "actual_top3_carried_weight_kg_sd_population", "actual_top3_carried_body_ratio_mean", "actual_top3_carried_body_ratio_sd_population"]:
            z=part[feature].dropna()
            summary_rows.append({"scope":"gained_lost_only","outcome_group":group,"races":len(part),"nonmissing_races":len(z),"actual_top3_runner_rows":int(part.actual_top3_runner_count.sum()),"feature":feature,"mean":z.mean(),"median":z.median(),"p25":z.quantile(.25),"p75":z.quantile(.75)})
    calc=pd.DataFrame(summary_rows)
    out=pd.read_csv(v2_path)
    assert set(out.outcome_group)=={"all_discordant_84","gained","lost"} and len(out)==18
    assert out.groupby("outcome_group").races.first().to_dict()=={"all_discordant_84":84,"gained":50,"lost":34}
    # V2 explicitly preserves feature and unit identifiers, checked against direct aggregates.
    assert out.unit.eq("race (three actual finishers collapsed within race)").all()
    assert out.feature.tolist()==calc.feature.tolist()
    expected_units={"actual_top3_body_kg_mean":"kg","actual_top3_body_kg_sd_population":"kg","actual_top3_carried_weight_kg_mean":"kg","actual_top3_carried_weight_kg_sd_population":"kg","actual_top3_carried_body_ratio_mean":"ratio","actual_top3_carried_body_ratio_sd_population":"ratio"}
    assert out.feature_unit.tolist()==[expected_units[z] for z in calc.feature]
    for c in ["scope","outcome_group","races","nonmissing_races","actual_top3_runner_rows"]:
        assert out[c].astype(str).tolist()==calc[c].astype(str).tolist(), c
    for c in ["mean","median","p25","p75"]: assert np.allclose(out[c],calc[c],atol=2e-10,rtol=2e-10), c

    # Check fixed cross-tabs against the independent race ledger and context.
    race = led.merge(got[["race_id","band"]],on="race_id",validate="one_to_one")
    def cell(part, stratum, year, cond):
        n=len(part); base=int(part.baseline_hit6.sum()); cand=int(part.candidate_hit6.sum())
        return {"stratum":stratum,"evaluation_year":year,"year_is_partial":year==2026,"condition":cond,"races":n,"share_of_full_1779":n/1779,"race_dates":part.race_date.nunique(),"support_status":"zero_support" if n==0 else "observed","gained":int((part.hit_class=="gained").sum()),"lost":int((part.hit_class=="lost").sum()),"net_gained_minus_lost":int((part.hit_class=="gained").sum()-(part.hit_class=="lost").sum()),"both_hit":int((part.hit_class=="both_hit").sum()),"both_miss":int((part.hit_class=="both_miss").sum()),"baseline_hits":base,"candidate_hits":cand,"baseline_hit_rate":base/n if n else np.nan,"candidate_hit_rate":cand/n if n else np.nan,"candidate_minus_baseline_hit_rate":(cand-base)/n if n else np.nan}
    exp=[]
    for y in YEARS:
        for d in DISTANCES: exp.append(cell(race[(race.evaluation_year==y)&(race.distance_m==d)],"year_x_distance",y,d))
    cross=pd.read_csv(STUDY/"outputs_followup_addendum/year_distance_condition_summary.csv")
    assert len(cross)==24 and cross.races.sum()==1779 and cross.groupby("evaluation_year").races.sum().to_dict()=={2024:637,2025:654,2026:488}
    check_frame(cross,pd.DataFrame(exp),["stratum","evaluation_year","condition"],[c for c in cross.columns if c not in {"stratum","condition","support_status"}])
    exp=[]
    for y in YEARS:
        for b in BANDS: exp.append(cell(race[(race.evaluation_year==y)&(race.band==b)],"year_x_moisture_band",y,b))
    crossb=pd.read_csv(STUDY/"outputs_followup_addendum/year_moisture_band_condition_summary.csv")
    assert len(crossb)==15 and crossb.races.sum()==1779
    check_frame(crossb,pd.DataFrame(exp),["stratum","evaluation_year","condition"],[c for c in crossb.columns if c not in {"stratum","condition","support_status"}])

    # Corrected-history table has a truthful bounded scope and the original remains immutable.
    hist=pd.read_csv(corrected_history)
    assert set(hist.history_scope_definition)=={
      "overall_same_distance_count_within_available_past_query_range_not_complete_lifetime_census",
      "bounded_support_count_in_most_recent_five_history_slots"}
    assert "available_past_query_range" in " ".join(hist.history_scope_definition.astype(str))

    schema_ok = "feature" in out.columns and "feature_unit" in out.columns
    receipt={"status":"PASS" if schema_ok else "FAIL_SCHEMA","validation":"independent direct-source joins and reaggregation; no analysis-A helper imported; no model fit","supplemental_receipt_sha256":sha(STUDY/"outputs_supplemental/supplemental_receipt.json"),"followup_receipt_sha256":sha(STUDY/"outputs_followup_addendum/followup_receipt.json"),"history_scope_correction_receipt_sha256":sha(STUDY/"outputs_followup_addendum/history_scope_correction_receipt.json"),"top3_feature_label_correction_receipt_sha256":sha(top3fix_path),"top3_feature_labeled_v2_sha256":sha(v2_path),"as_run_contract_hashes_verified":{"SUPPLEMENTAL_CONTEXT_CONTRACT.json":sha(STUDY/"contracts_as_run/SUPPLEMENTAL_CONTEXT_CONTRACT.json"),"SAVED_HISTORY_EXTENSION_CONTRACT.json":sha(STUDY/"contracts_as_run/SAVED_HISTORY_EXTENSION_CONTRACT.json")},"corrected_contract_hashes_verified":{"SUPPLEMENTAL_CONTEXT_CONTRACT.json":sha(STUDY/"SUPPLEMENTAL_CONTEXT_CONTRACT.json"),"SAVED_HISTORY_EXTENSION_CONTRACT.json":sha(STUDY/"SAVED_HISTORY_EXTENSION_CONTRACT.json")},"context_csv_sha256":sha(CTX),"context_rows":len(ctx),"runner_exact_key_coverage":len(ctx),"race_vectors":len(got),"race_context_summary_rows":len(saved_summary),"moisture_condition_rows":len(band_table),"top3_rows":len(actual),"discordant_races":len(discord),"corrected_top3_summary_rows":len(out),"corrected_top3_summary_schema_identifiers_present":schema_ok,"year_distance_cells":len(cross),"year_moisture_cells":len(crossb),"cross_tab_races":int(cross.races.sum()),"superseded_bad_label_preserved_and_not_used":True,"superseded_unlabeled_corrected_summary_preserved_and_not_used":True,"output_hashes":output_checks}
    dest=ROOT/"jeju/research/20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json"
    dest.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
