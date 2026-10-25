#!/usr/bin/env python3
"""Refresh the central source index with all frozen gain/loss artifacts.

Run after the approved topic-19 append has produced its local receipt and C
manifest. This is the final scoped source_manifest write in the publication
dependency chain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=ROOT/"jeju/research/20261010_joint_gain_loss_review_v1"
STUDY=ROOT/"jeju/research/20261010_joint_gain_loss_v1"
CONTEXT=ROOT/"jeju/research/20261010_joint_gain_loss_context_v1"
CENTRAL=ROOT/"jeju/research/conclusions"
TOKEN="ROOT_APPROVES_GAIN_LOSS_TOPIC19_APPEND"
MANIFEST=HERE/"ARTIFACT_MANIFEST.json"
PUBLICATION=HERE/"central_publication_receipt.json"
REFRESH_RECEIPT=HERE/"source_manifest_refresh_receipt.json"


def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def readj(path): return json.loads(path.read_text(encoding="utf-8"))
def encodej(obj): return (json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode("utf-8")

def manifest_rows(path:Path,base:Path):
    obj=readj(path)
    rows=obj.get("artifacts",obj.get("local_files",obj.get("files",[])))
    if not rows: raise AssertionError(f"manifest contains no local inventory: {path}")
    result=[]
    for row in rows:
        rel=Path(row["path"])
        full=ROOT/rel if str(rel).startswith("jeju/") else base/rel
        assert full.is_file(),f"manifest file missing: {full}"
        assert sha(full)==row["sha256"],f"manifest hash mismatch: {full}"
        if "bytes" in row: assert full.stat().st_size==row["bytes"],f"manifest byte count mismatch: {full}"
        result.append(full)
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--root-approval",default="")
    args=ap.parse_args()
    if not args.apply: raise SystemExit("no dry-run mode: pass --apply only after the approved central append is complete")
    if args.apply and args.root_approval!=TOKEN: raise SystemExit("source_manifest write refused: explicit root approval token required")
    assert PUBLICATION.is_file() and MANIFEST.is_file()
    pub=readj(PUBLICATION); cm=readj(MANIFEST)
    assert pub["status"]=="applied" and pub["topic18_unchanged_after_write"] is True
    assert sha(CENTRAL/"19_JOINT_RELATIONSHIP.md")==next(x["sha256"] for x in pub["written_files"] if x["path"].endswith("19_JOINT_RELATIONSHIP.md"))
    assert sha(CENTRAL/"source_manifest.json")==pub["initial_source_manifest_sha256"],"central source manifest changed since scoped publication"
    assert cm["status"].startswith("independent verification PASS")

    a_manifest=STUDY/"ARTIFACT_MANIFEST.json"
    context_manifest=CONTEXT/"ARTIFACT_MANIFEST.json"
    assert sha(a_manifest)==pub["study_manifest_sha256"]
    # Preserve the exact pre-refresh C manifest before it is extended with the
    # final source-index refresh receipt. This keeps every receipt hash resolvable.
    archive=HERE/"ARTIFACT_MANIFEST_pre_refresh.json"
    assert not archive.exists(),"refuse to overwrite the pre-refresh C manifest archive"
    prior_manifest_hash=sha(MANIFEST)
    archive.write_bytes(MANIFEST.read_bytes())
    assert sha(archive)==prior_manifest_hash
    scoped=set(manifest_rows(a_manifest,STUDY))
    scoped.update(manifest_rows(context_manifest,CONTEXT))
    # The C manifest excludes its own hash but freezes every other local C file.
    for entry in cm["local_files"]:
        p=ROOT/entry["path"]
        assert p.is_file() and sha(p)==entry["sha256"] and p.stat().st_size==entry["bytes"]
        scoped.add(p)
    scoped.add(a_manifest); scoped.add(context_manifest); scoped.add(MANIFEST); scoped.add(archive)

    receipt={"status":"prepared for final scoped source-manifest refresh","authorization_scope":"same root-authorized gain/loss publication; one central source_manifest update only","publication_receipt_sha256":sha(PUBLICATION),"A_manifest_sha256":sha(a_manifest),"context_manifest_sha256":sha(context_manifest),"C_manifest_before_refresh":{"path":archive.relative_to(ROOT).as_posix(),"sha256":prior_manifest_hash,"archived_byte_identical":True},"scoped_file_count":len(scoped)+1,"local_files_included":True,"source_manifest_final_self_hash_excluded":True,"no_database_or_model_change":True}
    if args.apply:
        assert not REFRESH_RECEIPT.exists(),"refuse to overwrite existing source manifest refresh receipt"
        REFRESH_RECEIPT.write_bytes(encodej(receipt))
        scoped.add(REFRESH_RECEIPT)
        # Rebuild C manifest once to include this final refresh receipt, then freeze it.
        local=[]
        for p in sorted(HERE.rglob("*")):
            if not p.is_file() or p==MANIFEST or "__pycache__" in p.parts or "central_publication_preview_gain_loss" in p.parts:
                continue
            local.append({"path":p.relative_to(ROOT).as_posix(),"sha256":sha(p),"bytes":p.stat().st_size})
        cm["local_files"]=local
        cm["source_manifest_refresh_receipt"]={"path":REFRESH_RECEIPT.relative_to(ROOT).as_posix(),"sha256":sha(REFRESH_RECEIPT)}
        cm["pre_refresh_manifest_archive"]={"path":archive.relative_to(ROOT).as_posix(),"sha256":sha(archive)}
        MANIFEST.write_bytes(encodej(cm))
        scoped.add(MANIFEST)

        sm_path=CENTRAL/"source_manifest.json"
        sm=readj(sm_path)
        rows={x["path"]:x for x in sm["files"]}
        central_expected={
          "jeju/research/conclusions/README.md":CENTRAL/"README.md",
          "jeju/research/conclusions/SOURCES.md":CENTRAL/"SOURCES.md",
          "jeju/research/conclusions/research_register.json":CENTRAL/"research_register.json",
          "jeju/research/conclusions/19_JOINT_RELATIONSHIP.md":CENTRAL/"19_JOINT_RELATIONSHIP.md",
        }
        # Refresh only the four approved central document rows.
        for rel,p in central_expected.items():
            rows[rel]={"path":rel,"role":"research_registry" if rel.endswith("research_register.json") else "conclusion_or_management","sha256":sha(p),"bytes":p.stat().st_size}
        for p in sorted(scoped):
            rel=p.relative_to(ROOT).as_posix()
            if rel=="jeju/research/conclusions/source_manifest.json": continue
            prior=rows.get(rel)
            new={"path":rel,"role":prior.get("role") if prior else "research_artifact","sha256":sha(p),"bytes":p.stat().st_size}
            if prior and rel not in central_expected:
                assert prior["sha256"]==new["sha256"] and prior["bytes"]==new["bytes"],f"refusing to rewrite existing noncentral source entry: {rel}"
            rows[rel]=new
        sm["files"]=sorted(rows.values(),key=lambda x:x["path"])
        sm["managed_files_bytes_excluding_this_manifest"]=sum(x.get("bytes",0) for x in sm["files"])
        sm["updated_at"]="2026-10-10"
        sm["latest_study"]="jeju/research/20261010_joint_gain_loss_v1"
        sm["latest_verification"]="jeju/research/20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json"
        sm["latest_status"]="retrospective_diagnostic_completed_original_gate_failed_no_operational_change"
        payload=encodej(sm)
        temp=sm_path.with_name("source_manifest.json.gainloss.tmp")
        with temp.open("wb") as f: f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(temp,sm_path)
        result=dict(receipt)
        result["execution_status"]="applied"
        result["included_source_entries"]=len(scoped)
        result["final_source_manifest_sha256"]=sha(sm_path)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
