# Model input contract: Jeju clinic history

## Supported input

The primary analysis surface is `medical_api_rows_analysis_2026`, at one row per exact source API16 clinic item for which the raw official horse ID resolves to a current official 제주마 profile. It includes rows with `clinic_date <= '2026-09-19'`. The full `medical_api_rows` table also retains profile-linked source rows after that analysis cutoff.

Use `horse_id` as the join key. It comes from the exact official `hrNo` field. `hr_name_raw` is source evidence; it is not an identity key. `current_horse_name`, `current_horse_age_2026`, and `current_profile_birth_date_raw` describe the latest current official profile, not the horse's historical name, age at treatment, or breed status on the clinic date.

The event date is the validated `clinic_date` derived from raw `clinicDate` (`YYYYMMDD`). It is a clinic event date, not a report/publication date. No historical publication timestamp is asserted. The source `meet_raw`, `hr_name_raw`, `hr_no_raw`, `hospi_name_raw`, `ill_name1_raw`, `ill_name2_raw`, and `part_raw` are retained. `part_raw` has no verified interpretation and must not be treated as a body-part taxonomy or stable identifier without separate evidence.

## Grain and duplicates

The unit is one original API response item. Duplicates are not deduplicated. If exact source payloads repeat, each occurrence remains a separate row with its page and one-based item index. If one horse has multiple different source payloads on one date, each remains a separate event row. Do not aggregate by horse/date unless a downstream analysis explicitly defines and reports its own aggregation rule.

The analysis view joins one latest profile row per horse and does not join one-to-many diagnosis or glossary rows. `medical_api_diagnosis_slots` has a different grain: two literal slot rows per linked clinic item. Phrase components and explanation text also have separate one-to-many provenance; joining them directly into event-level training data can multiply observations. Prefer an independently materialized phrase-level feature table with its own documented aggregation if a downstream model needs those terms.

## Missing and uncertain values

- A raw `'-'` diagnosis slot is preserved literally and its normalized slot value is NULL. It is an unknown/placeholder value; it does not mean healthy, no injury, or no diagnosis.
- Missing API keys, explicit JSON null, empty strings, and literal strings are distinguished by raw payload, key-presence/key-absence JSON, and captured source types. Do not silently collapse those cases.
- A successful zero-row year partition means only that the recorded request returned zero rows. It is not evidence that no clinic occurred or that older records never existed.
- The separate check re-requested API years 2002–2007 and 2009–2011; all nine returned HTTP 200, result code `00`, and `totalCount=0`. A separate TXT scan covered 1,150 files and 53,185 rows but found no official seven-digit horse ID. Those TXT rows remain unlinked candidates. These results describe the checks performed; they do not prove historical event absence or complete archive availability.

## Dictionary use

This is a separate Jeju clinic research scope authorized in addition to the glossary's original Seoul/Busan thoroughbred event scope. The six dictionary Parquets are preserved unchanged; only reusable terminology and provenance metadata are looked up against Jeju phrases. Source observations are not copied as Jeju event records, and captured explanation text retains its original source provenance. A phrase can be surfaced as an exact reviewed candidate only where the frozen phrase decision meets its documented review criteria and the raw phrase plus SHA-256 match exactly. Contextual-only, prefix, held, or excluded mappings must not be used as automatic labels. Component metadata does not establish diagnosis severity, health status, treatment outcome, or a causal effect on race performance.

`medical_api_diagnosis_components` contains only safe exact reviewed component metadata. Use `medical_api_diagnosis_slot_review` to inspect the disposition of each raw slot. Explanations must come from captured explanation source text; API33 `ill_desc='-'` is not an explanation, and the loader does not synthesize descriptions from titles.

## Profile provenance and exclusions

The appended API42 profiles are current profile observations. They are appended to `horse_profile_observations` and `breed_evidence` with retrieval-time provenance; old profile observations are not rewritten. This import establishes current profile eligibility for exact-ID linkage under the approved scope; it does not establish historical 제주마 status on a clinic date. Horse `3005648` is excluded by the approved reimport policy.

## Safe modeling boundaries

This input supports descriptive, time-aware research over recorded clinic items and reviewed terminology. It does not by itself establish complete historical medical coverage, diagnosis truth, severity, treatment, recovery, absence of disease, or causal/performance effects. Do not feed the raw event table into a promoted race prediction model without a separately approved feature design, temporal leakage review, and validation. Clinical visit counts have not been established as a complete or reliable measure of health burden.
