# 2014–2015 closure gap follow-up

## Scope and result

This review preserves exact-date closure reports for 2014–2015. It found seven venue/date candidates from contemporary press reports attributing schedules or closure decisions to KRA. The candidate table is for root review only; it does not change official closure intervals or the core database. No original KRA notice or monthly calendar was recovered in this bounded review.

The 2014 candidates are Seoul and Busan, 2014-04-25–27, reported as a KRA racing suspension after the Sewol ferry disaster, and Busan, 2014-09-07, reported as a Chuseok day off. The 2015 candidates are Busan, 2015-07-24–26 (summer cross-rotation), Busan, 2015-09-25–27 (Chuseok), Busan, 2015-12-18–20 (winter break), and Seoul, 2015-12-26 (closure inferred from a Busan monthly-plan report saying it added seven races because Seoul was closed).

## Evidence handling

`source_ledger.csv` describes each captured report, its claim, exactness, URL, capture metadata, raw file, and SHA-256. All captured article responses were HTTP 200. The archived raw article bodies and capture manifests are under `raw/`. `interval_candidates.csv` includes daily scheduled/executed counts from the canonical calendar as context. Zero/no-record rows do not establish closure by themselves.

`conflict_exclusions.csv` preserves 2014 week-only claims and conflicts. `user_review_items.csv` enumerates seven exact-date candidate decisions plus four unresolved or conflicting items for human review. `plan_amendments.csv` records the 2014 Busan annual/monthly-plan conflict as an unverified amendment, not as established change history. KRJ's 2014 annual article reports week-only closures. A later Ilyo Busan December plan lists Busan races on Dec 19 and 21; the canonical calendar also records executions on those dates, contradicting the annual Busan December week-3 closure claim. The annual Seoul December week-4 claim conflicts with Seoul execution on Dec 27–28. The 2014 August week-1 and Busan July week-4 claims lack exact source date spans and remain out of the exact-date candidate table.

## Limits

These are contemporary secondary reports of KRA decisions/plans, not original KRA records. July 2014 Busan summer and August 2014 Seoul summer evidence is week-only and was not mapped into exact-date candidates. The 2015 Seoul Dec 26 closure is supported indirectly by the explicit causal schedule statement in the Busan article and API context; a direct Seoul notice was not captured. Candidate dates require root/user review before any integration.
