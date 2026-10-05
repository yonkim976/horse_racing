# Independent review of upcoming descriptive steward notes

Status: **pass after correcting the prior-race window**.

The initial output selected each horse's last three full-card entries. Review found 18 nonstarters in those windows: 10 void/unresulted entries, four scratches, and four exclusions. That output is preserved in `../upcoming_context_superseded_entries` with a warning. The builder now keeps full history for canonical event linkage but selects evidence only from the last three `starter_eligible` rows before 2026-09-19. This includes completed races and genuine starts ending in DNF or disqualification; it excludes nonstarts.

The corrected windows contain 776 prior starts: 775 finished and one DNF. No nonstarter remains, and all 86 supporting rows belong to the independently reconstructed three-start window for the same `hr_no`. The 86 event IDs exactly match the independent reconstruction.

All 5,136 steward events link to one canonical historical race and horse ID using venue, race date, race number, and `hr_no`; unmatched count is zero. Every selected event date is earlier than both 2026-09-19 and its upcoming race. The latest collection timestamp is 2026-09-10 16:55:42.382 UTC, before generation at 2026-09-18 12:15:20.150954 UTC.

The corrected output covers 67 horses in 25 of 27 upcoming races with 86 supporting rows. Event counts are 55 delayed starts, 21 blocked/trouble events, five wide-path mentions, four bad-break events, and one kickback reaction. A wide-path mention does not establish disadvantage. A blank event summary does not establish that the horse had no trouble; it can also reflect extractor recall limits or unavailable reports.

All 294 entries and 27 races match the preserved v3 r2 A prediction keys. There are zero probability differences and zero rank differences. Neither output table contains future result, finish, placing, or odds fields. This is current locally known evidence for descriptive review only. The collection timestamp proves presence in the local snapshot before this note was generated; it does not prove when KRA originally published the historical report and does not establish leakage-free historical deployment.
