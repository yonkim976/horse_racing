"""Read-only asset inventory and locked-prediction error decomposition. No training/deletion."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT/'data/research'
OUT = RESEARCH/'jeju_accuracy_reset_audit_20260918'
DATA = RESEARCH/'jeju_native_top3_dataset_v1_20260915_r2'
ANN = RESEARCH/'jeju_annual_revalidation_20260918'
P26 = RESEARCH/'jeju_steward_pace_v2_pilot_20260918'

def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def save(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False))

def main():
    OUT.mkdir(exist_ok=False)
    save('protocol.json', dict(created_at=datetime.now(UTC).isoformat(), training_runs=0, deletion=False,
        scope='Jeju research directories; static literal references, not proof of complete dynamic dependencies',
        diagnosis='Existing BASE predictions 2024/2025/2026: overlap 0/1/2/3, set/order error split, omitted horse probability ranks 4/5/6+. Descriptive only.',
        paused=['dividend research','return optimization','video'], cutoff='2026-09-12'))
    dirs=sorted(p for p in RESEARCH.glob('*jeju*') if p.is_dir() and p != OUT)
    # Do not scan raw provider documents or credentials. Capture only local artifact names/references.
    documents=[]
    for folder in ['scripts','src','tests','docs']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix in {'.py','.md'}:
                documents.append((p,p.read_text(errors='replace')))
    for d in dirs:
        for p in d.glob('*.json'):
            if p.name in {'manifest.json','protocol.json','prediction_lock.json','delivery_manifest.json'}:
                documents.append((p,p.read_text(errors='replace')))
    inventory=[]; bundles=[]
    for d in dirs:
        files=[p for p in d.rglob('*') if p.is_file()]
        refs=[]
        for p,content in documents:
            if not p.is_relative_to(d) and d.name in content:
                refs.append(dict(path=str(p.relative_to(ROOT)),lines=[i for i,l in enumerate(content.splitlines(),1) if d.name in l]))
        own=[]
        for p in files:
            if p.suffix in {'.pkl','.joblib','.npz','.pt','.bin'}:
                item=dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p))
                bundles.append(item);own.append(item)
        inventory.append(dict(path=str(d.relative_to(ROOT)),files=len(files),bytes=sum(p.stat().st_size for p in files),
                              empty=not files,bundle_count=len(own),bundle_bytes=sum(p['bytes'] for p in own),literal_references=refs))
    groups=defaultdict(list)
    for b in bundles:groups[b['sha256']].append(b)
    duplicates=[v for v in groups.values() if len(v)>1]
    obsolete=['jeju_native_context_features_draft_rejected_20260916','jeju_native_context_features_pre_track_parse_20260916',
              'jeju_native_h3_features_v1_20260916_initial_parser','jeju_native_top3_dataset_v1_20260915']
    oldnew=[]
    for name in obsolete:
        d=RESEARCH/name
        replacement=(RESEARCH/'jeju_native_context_features_v1_20260916' if 'context' in name else
                     RESEARCH/'jeju_native_h3_features_v1_20260916' if 'h3_' in name else DATA)
        same=[];different=[];oldonly=[]
        for p in d.rglob('*'):
            if not p.is_file():continue
            rel=p.relative_to(d);other=replacement/rel
            if not other.is_file():oldonly.append(str(rel))
            elif sha(p)==sha(other):same.append(dict(path=str(rel),bytes=p.stat().st_size))
            else:different.append(str(rel))
        oldnew.append(dict(obsolete=str(d.relative_to(ROOT)),replacement=str(replacement.relative_to(ROOT)),
                           identical=same,different=different,old_only=oldonly,
                           deletion_status='archive first; historical manifests and diagnostic evidence must remain recoverable'))
    save('directory_inventory.json',inventory);save('model_bundles.json',bundles)
    save('byte_identical_model_groups.json',duplicates);save('superseded_artifacts.json',oldnew)
    # Independent label-based diagnosis, including accepted dead-heat alternatives.
    accepted=defaultdict(list)
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():
        accepted[r['race_id']].append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    race_meta={r['race_id']:r for r in pl.read_parquet(DATA/'races.parquet').to_dicts()}
    labels={(r['race_id'],r['horse_id']):r['label_top3'] for r in pl.read_parquet(DATA/'labels.parquet').to_dicts()}
    states={(r['race_id'],r['horse_id']):r for r in pl.read_parquet(DATA/'horse_states.parquet').select('race_id','horse_id','starts_pre','distance_starts_pre').to_dicts()}
    predictions=[];horses=[]
    for folder in [ANN,P26]:
        predictions.extend(pl.read_parquet(folder/'race_predictions.parquet').filter(pl.col('model')=='BASE').to_dicts())
        horses.extend(pl.read_parquet(folder/'horse_predictions.parquet').filter(pl.col('model')=='BASE').to_dicts())
    by_race=defaultdict(list)
    for h in horses:by_race[h['race_id']].append(h)
    rows=[];omitted=[]
    for r in predictions:
        rid=r['race_id'];truth=accepted[rid];selected=set(r['predicted_set'])
        set_hit=any(selected==set(t) for t in truth)
        order_hit=tuple(r['predicted_order']) in truth
        overlap=max(len(selected & set(t)) for t in truth)
        assert (set_hit,order_hit,overlap)==(r['set_hit'],r['order_hit'],r['compatible_max_overlap'])
        assert r['pick_hit']==bool(labels[(rid,r['pick_horse_id'])])
        ranking=sorted(by_race[rid],key=lambda h:(-h['p'],h['horse_id']))
        ranks={h['horse_id']:i+1 for i,h in enumerate(ranking)}
        common=dict(year=r['event_date'].year,race_id=rid,date=r['event_date'].isoformat())
        row=dict(**common,pick_hit=r['pick_hit'],set_hit=set_hit,order_hit=order_hit,overlap=overlap,
                 order_only_error=set_hit and not order_hit,selection_error=not set_hit,
                 distance=race_meta[rid]['distance_m'],field_size=race_meta[rid]['field_size'],
                 boundary_tie=race_meta[rid]['boundary_tie'])
        rows.append(row)
        # Unique missing horse requires two correct selections and no boundary tie.
        if overlap==2 and not race_meta[rid]['boundary_tie']:
            target=set(truth[0]);missing=target-selected;wrong=selected-target
            assert len(missing)==len(wrong)==1
            h=next(iter(missing));w=next(iter(wrong))
            omitted.append(dict(**common,missing_horse=h,wrong_horse=w,missing_probability_rank=ranks[h],
                missing_starts=states[(rid,h)]['starts_pre'],missing_distance_starts=states[(rid,h)]['distance_starts_pre']))
    summary=[]
    for y in [2024,2025,2026]:
        g=[r for r in rows if r['year']==y];o=[r for r in omitted if r['year']==y]
        n=len(g);a=sum(r['pick_hit'] for r in g);b=sum(r['set_hit'] for r in g);c=sum(r['order_hit'] for r in g)
        summary.append(dict(year=y,races=n,A=a,B=b,C=c,overlap_counts=dict(sorted(Counter(r['overlap'] for r in g).items())),
            wrong_set=n-b,correct_set_wrong_order=b-c,order_failures=n-c,
            share_of_order_failures_with_wrong_set=(n-b)/(n-c),
            two_correct_nonboundary=len(o),missing_rank_counts=dict(sorted(Counter(r['missing_probability_rank'] for r in o).items())),
            missing_rank_4_or_5=sum(r['missing_probability_rank'] in [4,5] for r in o),
            missing_rank_6plus=sum(r['missing_probability_rank']>=6 for r in o),
            missing_no_previous_start=sum(r['missing_starts']==0 for r in o),
            missing_no_distance_start=sum(r['missing_distance_starts']==0 for r in o)))
    save('error_races.json',rows);save('two_correct_missing_horses.json',omitted);save('error_summary.json',summary)
    save('audit_summary.json',dict(directories=len(inventory),bytes=sum(d['bytes'] for d in inventory),
         bundle_files=len(bundles),bundle_bytes=sum(b['bytes'] for b in bundles),
         byte_identical_bundle_groups=len(duplicates),redundant_bundle_bytes=sum(sum(x['bytes'] for x in group[1:]) for group in duplicates),
         empty_directories=[d['path'] for d in inventory if d['empty']],
         old_draft_bytes=sum(d['bytes'] for d in inventory if Path(d['path']).name in obsolete[:3]),
         initial_dataset_bytes=sum(d['bytes'] for d in inventory if Path(d['path']).name==obsolete[3]),
         raw_sources_deleted=0,models_deleted=0,new_model_fits=0))
    inputs=[Path(__file__),DATA/'accepted_orders.parquet',DATA/'races.parquet',DATA/'labels.parquet',DATA/'horse_states.parquet']
    inputs += [f/n for f in [ANN,P26] for n in ['race_predictions.parquet','horse_predictions.parquet']]
    save('manifest.json',dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},
                              outputs={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(json.dumps(dict(inventory=json.loads((OUT/'audit_summary.json').read_text()),errors=summary),ensure_ascii=False))

if __name__=='__main__':main()
