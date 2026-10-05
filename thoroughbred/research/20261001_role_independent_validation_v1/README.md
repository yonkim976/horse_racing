# Independent role review validation

Read-only integration validation for the 60 race trainer/owner targets and 224 trial trainer targets. No source ledger, raw capture, builder, or core database was modified by this reviewer.

## Result

**PASS.** The final database SHA-256 matches its manifest; all 54 build checks pass. The 221 official trial score-page files match their recorded SHA-256 values, and the 61 supplemental trainer IDs were independently reparsed from the exact event, program, and horse rows with direct `goPage3` links. The 224 participant keys and their review statuses are preserved in the normalized CSV and core review/evidence tables.

The 22 trial rows without an exact official event row remain unresolved. Placeholder `0AAAAA` / `휴양마` values were not converted into person identities. Race event meet and a profile link's meet parameter are retained separately.

## Evidence summary

- Baseline DB SHA-256: `5fef8038538d9a6c19f62b022c67b570d192b969baadacefb4413414c6e35bdc`
- Final DB SHA-256: `fd4e1135b1286b8b70b39441bd326e634772e143a551c6bf1a1584cac49a1bf5`
- Trial review: 224 unique keys = 61 exact-person supplements + 141 confirmed non-person placeholders + 22 unresolved.
- Race review: 60 unique keys; 37 trainer IDs and 37 owner IDs were directly supplemented, while 23 trainer placeholders remain.
- Current exception view: 186 unique rows = 23 race placeholders + 141 trial placeholders + 22 unresolved.
- The core role ID columns are `VARCHAR`; all 61 supplemented trial trainer IDs retain their six-character string form and leading zero.

See [`validation.json`](validation.json) for hashes, counts, and validation gates.
