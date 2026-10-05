# Jeju legacy cleanup review

Hash-fixed candidate deletion list: **474 files**. Retained evidence inventory: **87 files**. No deletion has been performed. The parent agent should review and approve the exact `delete_allowlist` before execution.

## Candidate groups

- Root `docs/JEJU*.md` outside the five protected core documents: remove only after inbound links point to the Jeju workspace. The dirty steward roadmap is separately protected in this working tree.
- `docs/research_archive/source/jeju*`: copied Jeju evidence; live model inputs and gate files remain in `data/research`.
- Obsolete study runners, reports, and tests: experiments are discontinued; shared annual source DB builders, ingestion, model-input builders, source verifiers, runtime predictor/renderers are retained.
- `src/horse_racing/analysis/jeju*.py`: retain HY_R_FORM imports/pickle classes, input builders, and modified calibration chain; candidates are research-only modules outside that chain.
- `data/research/jeju*/reproduce`: remove old copied research code/docs/tests except minimal source snapshots for final v13 model provenance.

## Safety evidence

- Predictor: `scripts/predict_jeju_live_hy_r_form.py`; pinned model SHA-256 matches the retained model artifact.
- Runtime/pickle modules protected in the retained inventory include `jeju_top3_preprocessing`, `jeju_joint_top3`, `jeju_context_features`, `jeju_h3_features`, `jeju_hybrid_evaluation`, `jeju_joint_evaluation`, `jeju_live_supplementals`, and `jeju_native_top3_states`.
- Candidate files have exact SHA-256 and byte size in `allowlist.json`; any mismatch at deletion time must abort that file.
