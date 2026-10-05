# Early closure-gap follow-up: 2010–2013

Checked 2026-10-01. This is a bounded source follow-up for exact planned holiday, summer, and year-end closures and reported amendments for Seoul (`meet_code=1`) and Busan-Gyeongnam (`meet_code=3`). It is additive: it does not change the v2/v3 evidence, database, or builders.

## Findings

- `interval_candidates.csv` contains **19 reported interval candidates**. All have `confidence=reported_not_official_original`; none is promoted to an official confirmed closure. The strongest newly captured reports are Sports Kyunghyang's contemporaneous 2010 Seoul annual-plan summary, UJNews's captured 2012 Busan December amendment report, and UJNews's captured 2013 Busan summer and Chuseok notices.
- A targeted SROA official plan-board check found the oldest visible items on page 5 are Jan–Jun 2023 (46 posts across five pages). It offers no 2010–2013 schedule. The prior v3 KRA monthly-board check showed only current 2026 items. Earlier guessed annual-plan aliases returned HTTP 200 but only 295-byte non-PDF bodies; these are failed retrievals, not evidence that no other official archive copy exists.
- No original KRA schedule/amendment PDF for 2010–2013 was captured. Media/local-news reporting with explicit KRA attribution remains secondary evidence.

## 2012 amendments and conflicts

`plan_amendments.csv` records two reported schedule changes. For summer, the January KRJ lead `L2012_3_06` put Busan closure on Aug 3–5. A later July KRJ amendment excerpt relayed by the coordinator says Busan instead did not race Jul 27–29; Seoul did not race Aug 3–5; Busan Aug 3 alone had no local races, while Aug 4 and 5 had 5 and 11 local races. Thus the earlier Busan Aug 3–5 window is marked `superseded_reported_plan_not_data_error`; it is not an API error. The July amendment URL is recorded, but TLS hostname validation prevented a local capture, so its article date/title/body still need primary or independently captured review.

For year-end, the January KRJ lead `L2012_3_08` said Busan would be closed Dec 28–30. The captured Nov 28 UJNews article attributes a revision to KRA Busan: no Busan races Dec 21–23, and ordinary Busan racing Dec 28–30. API has 0 scheduled/executed races Dec 21–23 and 20/20 Dec 28–30. The chronology is consistent with the report, but API execution does not establish intent; the original KRA notice remains missing. Both initial leads are therefore marked superseded, not data errors.

## Review items

1. Obtain the original KRA annual/monthly plan or amendment for each year if the product requires official-primary confirmation before adding planned intervals.
2. The 2011 KRJ article’s five listed Busan windows cover 14 calendar days while it reports 10 no-racing days; this likely counts ten scheduled Friday/Sunday meeting dates. It also labels 2011-01-07 a Saturday although that date was Friday. The original HTML/KRA plan was not recovered, so the weekday wording remains a source limitation.
3. Confirm the 2012 summer amendment against the actual KRJ page or KRA notice. The reported partial Busan pause on Aug 3 must not be widened to Aug 3–5; the API has 16 Busan races on Aug 4–5.
4. The 2013 Seoul Aug 3–4 item is from a Nov 25 roundup after the cited period; it is lower confidence than the contemporaneous Busan notices.

## API cross-check use

`api_scheduled_races` and `api_executed_races` in the CSV are summed from the pinned daily calendar. They are execution cross-checks only. Zero races never establish a planned closure; positive races within a reported full-closure window flag a conflict/amendment question.

## Files

- `interval_candidates.csv` — date leads, provenance, status, user-review flags, and API counts.
- `plan_amendments.csv` — before/after plan reports and exact superseded statuses.
- `source_status.csv` — source inventory, capture/access status, coverage, and limits.
- `user_review_items.csv` — specific unresolved source/interpretation checks for integration.
- `raw/` — captured HTML and structured access observations.
- `manifest.json` — byte counts and SHA-256 hashes.
